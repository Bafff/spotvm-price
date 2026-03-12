from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from .analysis import (
    enrich_with_coremark,
    enrich_with_performance,
    filter_by_cost,
    filter_by_requirements,
    merge_datasets,
    rank_candidates,
    summarize_top_candidates,
)
from .vm_specs import discover_skus
from .auth import AzureAuthenticator
from .config import VALID_CPU_ARCHS, ToolConfig, load_config_file, merge_cli_overrides
from .http_client import AzureRestClient, AzureHttpError
from .placement_score import fetch_placement_scores
from .reporting import render_table, export_to_csv, set_colors_enabled
from .resource_graph import fetch_historical_metrics

MAX_UNATTENDED_FAILURES = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spotvm-tool",
        description=(
            "Compare Azure Spot VM pricing, eviction rates, and performance across regions and SKUs. "
            "Add --placement-check with --subscription-id for capacity/quota scoring."
        ),
        epilog=(
            "Quick start (pricing only, no subscription needed):\n"
            "  spotvm-tool --regions centralus --sizes Standard_D4s_v5 Standard_E4s_v5\n\n"
            "With placement scores and quota checking:\n"
            "  spotvm-tool --subscription-id <ID> --regions centralus --sizes Standard_D4s_v5 --placement-check --desired-count 10"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--subscription-id",
        help="Azure subscription ID (only required with --placement-check)",
    )
    parser.add_argument("--regions", nargs="*", help="List of Azure regions")
    parser.add_argument("--sizes", nargs="*", help="List of VM sizes (SKUs)")
    parser.add_argument(
        "--desired-count",
        type=int,
        help="Number of VMs you plan to deploy (used with --placement-check to assess capacity, default: 1)",
    )
    parser.add_argument(
        "--os-type",
        choices=["linux", "windows"],
        help="Operating system for price history queries (default: linux)",
    )
    parser.add_argument(
        "--availability-zones",
        action="store_true",
        help="Break down placement scores by availability zone (requires placement scoring)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to JSON or YAML configuration file",
    )
    parser.add_argument(
        "--cache-ttl-minutes",
        type=int,
        help="Override cache TTL in minutes",
    )
    parser.add_argument(
        "--save-report",
        type=Path,
        help="Optional path to save a JSON report",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON output in addition to the table",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit the number of rows in the output",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Clear cached responses before running",
    )
    parser.add_argument(
        "--placement-check",
        action="store_true",
        help="Enable Placement Score API queries for capacity and quota data "
             "(requires --subscription-id). Useful for large-scale deployments",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output (useful for CI/CD or non-TTY environments)",
    )
    parser.add_argument(
        "--baseline-sku",
        type=str,
        help="Baseline VM size for relative performance comparison (e.g., Standard_D4as_v6 = 100%%)",
    )

    # Requirements-based filtering
    parser.add_argument(
        "--min-vcpu",
        type=int,
        help="Minimum vCPUs required (filters SKUs with fewer cores)",
    )
    parser.add_argument(
        "--min-ram",
        type=int,
        help="Minimum RAM required in GB (filters SKUs with less memory)",
    )
    parser.add_argument(
        "--cpu-arch",
        type=str,
        choices=["x64", "arm"],
        help="CPU architecture filter: x64 for Intel/AMD, arm for ARM-based VMs (Cobalt/Ampere)",
    )

    # Cost-based filtering
    parser.add_argument(
        "--max-price",
        type=float,
        help="Maximum acceptable price per hour in USD (e.g., 0.10 for $0.10/hr)",
    )
    parser.add_argument(
        "--max-eviction",
        type=float,
        help="Maximum acceptable eviction rate in percentage (e.g., 10 for 10%%)",
    )
    parser.add_argument(
        "--min-performance",
        type=float,
        help="Minimum performance relative to baseline in percentage (requires --baseline-sku, e.g., 80 for 80%%)",
    )

    # Historical data features
    parser.add_argument(
        "--save-results",
        action="store_true",
        help="Save run results to results/runs/{timestamp}.json for historical analysis",
    )
    parser.add_argument(
        "--run-unattended",
        type=int,
        nargs="?",
        const=60,
        metavar="MINUTES",
        help="Run continuously in background, collecting data every MINUTES (default: 60). "
             "Automatically enables --save-results. Stop with Ctrl+C.",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path("./results"),
        help="Directory for historical results storage (default: ./results)",
    )
    parser.add_argument(
        "--analyze-history",
        action="store_true",
        help="Analyze previous runs and generate unified history CSV file",
    )
    parser.add_argument(
        "--history-depth",
        type=int,
        help="Number of most recent runs to include in analysis (default: all)",
    )
    parser.add_argument(
        "--history-output",
        type=Path,
        help="Path for history CSV output (default: results/history.csv)",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        help="Export results to CSV file (e.g., results.csv)",
    )

    return parser


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    # Show help when invoked with no arguments
    if (argv is not None and len(argv) == 0) or (argv is None and len(sys.argv) <= 1):
        parser.print_help()
        return 0
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    logger = logging.getLogger("spotvm-tool")
    # Keep our own logger at INFO so our messages still appear
    if not args.verbose:
        logger.setLevel(logging.INFO)

    # Handle --analyze-history mode (separate from normal runs)
    if args.analyze_history:
        from .history import analyze_history

        results_dir = args.results_dir
        history_output = args.history_output or (results_dir / "history.csv")

        logger.info("Analyzing historical data from %s", results_dir)
        num_runs, num_datapoints, csv_path = analyze_history(
            results_dir=results_dir,
            depth=args.history_depth,
            output_path=history_output,
        )

        print(f"Historical Analysis Complete:")
        print(f"  Runs analyzed: {num_runs}")
        print(f"  Data points: {num_datapoints}")
        print(f"  CSV output: {csv_path}")
        print(f"\nUse this CSV for visualization with tools like:")
        print(f"  - Excel/Google Sheets: Import {csv_path}")
        print(f"  - Python: pd.read_csv('{csv_path}')")
        print(f"  - Grafana: CSV data source plugin")

        return 0

    base_config: Dict[str, Any] = {}
    if args.config:
        base_config = load_config_file(args.config)

    # Auto-discover SKUs only when neither CLI nor config specifies sizes.
    # cpu_arch can come from config here; min_vcpu/min_ram are still CLI-only.
    sizes = args.sizes if args.sizes is not None else base_config.get("sizes")
    effective_cpu_arch = args.cpu_arch if args.cpu_arch is not None else base_config.get("cpu_arch")
    if effective_cpu_arch is not None:
        if not isinstance(effective_cpu_arch, str):
            parser.error(f"cpu_arch must be one of {sorted(VALID_CPU_ARCHS)}")
        effective_cpu_arch = effective_cpu_arch.lower()
        if effective_cpu_arch not in VALID_CPU_ARCHS:
            parser.error(f"cpu_arch must be one of {sorted(VALID_CPU_ARCHS)}")
    if not sizes and (args.min_vcpu is not None or args.min_ram is not None or effective_cpu_arch is not None):
        requirements = []
        if args.min_vcpu is not None:
            requirements.append(f"vCPU≥{args.min_vcpu}")
        if args.min_ram is not None:
            requirements.append(f"RAM≥{args.min_ram} GB")
        if effective_cpu_arch:
            requirements.append(f"arch={effective_cpu_arch}")
        logger.info(
            f"No --sizes specified, auto-discovering SKUs matching requirements ({', '.join(requirements)})"
        )
        sizes = discover_skus(
            min_vcpu=args.min_vcpu,
            min_ram=args.min_ram,
            cpu_arch=effective_cpu_arch,
        )
        if not sizes:
            logger.error("No SKUs found matching specified requirements")
            return 1
        logger.info(f"Auto-discovered {len(sizes)} SKUs: {', '.join(sizes[:5])}{'...' if len(sizes) > 5 else ''}")

    overrides: Dict[str, Any] = {
        "subscription_id": args.subscription_id,
        "regions": args.regions,
        "sizes": sizes,
        "desired_count": args.desired_count,
        "os_type": args.os_type,
        "availability_zones": args.availability_zones or None,
        "cache_ttl_minutes": args.cache_ttl_minutes,
        "save_report": str(args.save_report) if args.save_report else None,
        "emit_json": args.json or None,
        "result_limit": args.limit,
        "baseline_sku": args.baseline_sku,
        "cpu_arch": args.cpu_arch,
    }
    if args.placement_check:
        overrides["enable_placement"] = True

    config_data = merge_cli_overrides(base_config, overrides)

    # Validate dependent flags against *merged* config (not just CLI args),
    # so config-file values for enable_placement/baseline_sku are respected.
    merged_placement = config_data.get("enable_placement", False)
    merged_baseline = config_data.get("baseline_sku")
    if not merged_placement:
        if config_data.get("availability_zones"):
            parser.error("--availability-zones requires --placement-check (or enable_placement in config)")
        if config_data.get("desired_count") is not None:
            parser.error("--desired-count requires --placement-check (or enable_placement in config)")
    if args.min_performance is not None and not merged_baseline:
        parser.error("--min-performance requires --baseline-sku (on CLI or in config)")

    try:
        config = ToolConfig.from_dict(config_data)
    except Exception as exc:  # noqa: BLE001 - surface configuration errors
        parser.error(str(exc))
        return 1

    if args.clear_cache:
        from . import cache

        cache.clear()
        logger.info("Cache cleared")

    # Unattended mode: run continuously
    if args.run_unattended:
        # Force save results in unattended mode
        save_results_enabled = True
        interval_minutes = args.run_unattended

        logger.info(
            f"Starting unattended monitoring mode: running every {interval_minutes} minutes. "
            f"Press Ctrl+C to stop."
        )
        _nc = args.no_color
        print(f"{'[*]' if _nc else '🔄'} Monitoring mode started (interval: {interval_minutes} min)")
        print(f"{'[>]' if _nc else '📊'} Results will be saved to: {args.results_dir}/runs/")
        print(f"{'[!]' if _nc else '⏸️ '} Press Ctrl+C to stop\n")

        # Setup signal handler for graceful shutdown
        stop_requested = False

        def signal_handler(signum, frame):
            nonlocal stop_requested
            stop_requested = True
            print(f"\n{'[x]' if _nc else '⏹️ '} Stop requested, finishing current run...")

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        run_count = 0
        unexpected_error_count = 0
        while not stop_requested:
            run_count += 1
            print(f"\n{'='*60}")
            print(f"Run #{run_count} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*60}")

            try:
                _run_single_analysis(
                    args=args,
                    config=config,
                    logger=logger,
                    save_results=save_results_enabled,
                )
                unexpected_error_count = 0
            except AzureHttpError as exc:
                unexpected_error_count = 0
                logger.error(f"Azure API request failed: {exc}")
                logger.info("Continuing despite error...")
            except Exception as exc:  # noqa: BLE001
                unexpected_error_count += 1
                logger.exception(
                    "Unexpected error in unattended run (%d/%d)",
                    unexpected_error_count,
                    MAX_UNATTENDED_FAILURES,
                )
                if unexpected_error_count >= MAX_UNATTENDED_FAILURES:
                    logger.error(
                        "Stopping unattended mode after %d consecutive unexpected errors",
                        MAX_UNATTENDED_FAILURES,
                    )
                    print(
                        f"\n{'[x]' if _nc else '❌'} Stopping monitoring after "
                        f"{MAX_UNATTENDED_FAILURES} consecutive unexpected errors."
                    )
                    return 1
                logger.info("Continuing despite error...")

            if not stop_requested:
                next_run = datetime.now() + timedelta(minutes=interval_minutes)

                logger.info(f"Next run at {next_run.strftime('%H:%M:%S')}")
                print(f"\n{'[.]' if _nc else '💤'} Sleeping for {interval_minutes} minutes...")
                print(f"   Next run at: {next_run.strftime('%H:%M:%S')}")

                # Sleep in small intervals to allow quicker Ctrl+C response
                sleep_seconds = interval_minutes * 60
                for _ in range(sleep_seconds):
                    if stop_requested:
                        break
                    time.sleep(1)

        print(f"\n{'[OK]' if _nc else '✅'} Monitoring stopped after {run_count} run(s)")
        return 0

    # Normal mode: run once
    else:
        try:
            _run_single_analysis(
                args=args,
                config=config,
                logger=logger,
                save_results=args.save_results,
            )
        except AzureHttpError as exc:
            logger.error("Azure API request failed: %s", exc)
            return 2

        return 0


def _run_single_analysis(
    args,
    config: ToolConfig,
    logger,
    save_results: bool,
) -> None:
    """Execute a single analysis run.

    Args:
        args: Parsed command-line arguments
        config: Tool configuration
        logger: Logger instance
        save_results: Whether to save results to disk
    """
    # Handle color output setting
    _nc = args.no_color
    if _nc:
        set_colors_enabled(False)

    authenticator = AzureAuthenticator()
    client = AzureRestClient(authenticator)

    placement_scores = (
        fetch_placement_scores(client, config)
        if config.enable_placement
        else []
    )
    historical_metrics = fetch_historical_metrics(client, config)

    candidates = merge_datasets(placement_scores, historical_metrics)

    # Filter by hardware requirements (before ranking to reduce dataset)
    # Use config values so config-file settings (cpu_arch, etc.) are honored
    candidates = filter_by_requirements(
        candidates,
        min_vcpu=args.min_vcpu,
        min_ram=args.min_ram,
        cpu_arch=config.cpu_arch,
    )

    ranked = rank_candidates(candidates)
    ranked = enrich_with_performance(ranked, config.baseline_sku)
    ranked = enrich_with_coremark(ranked)  # Add CoreMark benchmark data

    # Filter by cost constraints (after enrichment for min_performance filter)
    ranked = filter_by_cost(
        ranked,
        max_price=args.max_price,
        max_eviction=args.max_eviction,
        min_performance=args.min_performance,
    )

    if config.result_limit:
        ranked = ranked[: config.result_limit]

    # Save results for historical analysis if requested (even if empty,
    # so automation/unattended monitoring records that a run completed)
    if save_results:
        from .history import save_run_results

        saved_path = save_run_results(
            candidates=ranked,
            config=config,
            results_dir=args.results_dir,
        )
        logger.info("Results saved to %s", saved_path)
        print(f"{'[OK]' if _nc else '✅'} Results saved to: {saved_path}\n")

    # Export to CSV if requested (even if empty, so downstream tools see the run)
    if args.csv:
        try:
            export_to_csv(
                ranked,
                args.csv,
                show_placement=config.enable_placement,
                show_baseline=config.baseline_sku is not None,
            )
        except OSError as exc:
            logger.error("Failed to export CSV to %s: %s", args.csv, exc)
            print(f"{'[x]' if _nc else '❌'} Failed to export CSV to: {args.csv} ({exc})\n")
        else:
            logger.info("Results exported to CSV: %s", args.csv)
            print(f"{'[OK]' if _nc else '✅'} CSV exported to: {args.csv}\n")

    # Emit JSON / save report (even if empty)
    if config.emit_json or config.save_report:
        report_payload = _build_report(ranked)
        if config.emit_json:
            print("\nJSON Output:")
            print(json.dumps(report_payload, indent=2, default=_json_serializer))
        if config.save_report:
            try:
                config.save_report.write_text(
                    json.dumps(report_payload, indent=2, default=_json_serializer),
                    encoding="utf-8",
                )
            except OSError as exc:
                logger.error("Failed to save report to %s: %s", config.save_report, exc)
                print(f"{'[x]' if _nc else '❌'} Failed to save report to: {config.save_report} ({exc})\n")
            else:
                logger.info("Saved report to %s", config.save_report)

    if not ranked:
        print("No candidates match the specified filters. Try relaxing constraints.")
        return

    print(
        render_table(
            ranked,
            show_placement=config.enable_placement,
            show_baseline=config.baseline_sku is not None,
        )
    )

    # Print column explanations
    if config.enable_placement:
        print("\nColumn Descriptions:")
        print("  Quota: Indicates if sufficient vCPU quota is available")
        print("    - Yes: Quota available for deployment")
        print("    - No:  Insufficient quota (increase quota or choose different region/size)")
        print("    - Unknown: Quota data not returned by Azure for this SKU/region")
    if config.baseline_sku:
        print(f"\nPerformance Baseline: {config.baseline_sku} = 100%")
        print("  Perf %: Relative computing power compared to baseline")
        print("  Price/Perf: Price per performance unit (lower is better value)")

    # Print color legend if colors are enabled
    if not args.no_color:
        from colorama import Fore, Style
        print("\nColor Legend:")
        print(f"  Eviction Rate: {Fore.BLUE}<5%{Style.RESET_ALL} | "
              f"{Fore.GREEN}5-<10%{Style.RESET_ALL} | "
              f"{Fore.YELLOW}10-<15%{Style.RESET_ALL} | "
              f"{Fore.RED}15-<25%{Style.RESET_ALL} | "
              f"{Fore.RED}{Style.BRIGHT}≥25%{Style.RESET_ALL}")
        if config.enable_placement:
            print(f"  Placement:     {Fore.GREEN}High{Style.RESET_ALL} | "
                  f"{Fore.YELLOW}Medium{Style.RESET_ALL} | "
                  f"{Fore.RED}Low{Style.RESET_ALL}")

    summary_lines = summarize_top_candidates(ranked)
    if summary_lines:
        print("\nRecommendations:")
        for line in summary_lines:
            print(f" - {line}")

    if config.enable_placement:
        disclaimer = (
            "Note: Azure Spot placement scores are point-in-time indicators and "
            "do not guarantee successful allocation or avoidance of eviction."
        )
        print(f"\n{disclaimer}")
    else:
        print(
            "\nNote: Spot VM pricing and eviction rates are historical estimates "
            "and may change. Use --placement-check for capacity/quota data."
        )


def _build_report(candidates: List[Any]) -> Dict[str, Any]:
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "candidates": [
            {
                "rank": item.recommendation_rank,
                "region": item.region,
                "availabilityZone": item.availability_zone,
                "vmSize": item.vm_size,
                "cpuArchitecture": item.cpu_arch,
                "placementScore": item.placement_score,
                "quotaAvailable": item.quota_available,
                "priceUSDPerHour": item.price_usd,
                "priceLastUpdated": _json_serializer(item.price_last_updated),
                "evictionRatePercent": item.eviction_rate,
                "performanceRelativePercent": item.performance_relative,
                "pricePerPerformance": item.price_per_performance,
                "coremarkScore": item.coremark_score,
                "coremarkPerVCPU": item.coremark_per_vcpu,
                "notes": item.notes,
            }
            for item in candidates
        ],
    }


def _json_serializer(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return value


if __name__ == "__main__":
    sys.exit(main())
