from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

from . import config as config_defaults
from .analysis import (
    enrich_with_coremark,
    enrich_with_databricks_cost,
    enrich_with_performance,
    filter_by_cost,
    filter_by_requirements,
    merge_datasets,
    rank_candidates,
    summarize_top_candidates,
)
from .auth import AzureAuthenticator
from .config import (
    VALID_CPU_ARCHS,
    ToolConfig,
    load_config_file,
    merge_cli_overrides,
)
from .databricks_catalog import (
    DatabricksCatalogError,
    refresh_catalog_instructions,
    refresh_databricks_catalog_cache,
)
from .http_client import AzureHttpError, AzureRestClient
from .models import CandidateInsight, HistoricalMetrics, PlacementScoreResult, SortOrder
from .placement_score import PlacementScoreRequest, fetch_placement_scores
from .projection import project_for_report
from .reporting import RenderOptions, export_to_csv, initialize_color_output, render_table
from .resource_graph import ResourceGraphRequest, fetch_historical_metrics
from .vm_specs import discover_skus

logger = logging.getLogger("spotvm")
_FATAL_UNATTENDED_EXCEPTIONS = (AssertionError, AttributeError, KeyError, NameError, TypeError)


@dataclass(frozen=True)
class AnalysisRunRequest:
    no_color: bool
    min_vcpu: int | None
    min_ram: int | None
    no_max_limit: bool
    explicit_sizes: bool
    max_price: float | None
    max_eviction: float | None
    min_performance: float | None
    sort_order: SortOrder
    csv: Path | None
    results_dir: Path
    save_results: bool


def _build_analysis_run_request(args: argparse.Namespace, *, save_results: bool) -> AnalysisRunRequest:
    return AnalysisRunRequest(
        no_color=args.no_color,
        min_vcpu=args.min_vcpu,
        min_ram=args.min_ram,
        no_max_limit=args.no_max_limit,
        explicit_sizes=args.explicit_sizes,
        max_price=args.max_price,
        max_eviction=args.max_eviction,
        min_performance=args.min_performance,
        sort_order=cast(SortOrder, args.sort),
        csv=args.csv,
        results_dir=args.results_dir,
        save_results=save_results,
    )


def _build_resource_graph_request(config: ToolConfig) -> ResourceGraphRequest:
    return ResourceGraphRequest(
        regions=config.regions,
        sizes=config.sizes,
        os_type=config.os_type,
        cache_ttl_minutes=config.cache_ttl_minutes,
        retry_attempts=config.retry_attempts,
        retry_backoff_seconds=config.retry_backoff_seconds,
    )


def _build_placement_score_request(config: ToolConfig) -> PlacementScoreRequest:
    return PlacementScoreRequest(
        subscription_id=config.subscription_id,
        regions=config.regions,
        sizes=config.sizes,
        desired_count=config.desired_count,
        availability_zones=config.availability_zones,
        cache_ttl_minutes=config.cache_ttl_minutes,
        max_sizes_per_request=config.max_sizes_per_request,
        max_regions_per_request=config.max_regions_per_request,
        retry_attempts=config.retry_attempts,
        retry_backoff_seconds=config.retry_backoff_seconds,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spotvm",
        description=(
            "Compare Azure Spot VM pricing, eviction rates, and performance across regions and SKUs. "
            "Add --placement-check with --subscription-id for capacity/quota scoring."
        ),
        epilog=(
            "Quick start (pricing only, no subscription needed):\n"
            "  spotvm --regions centralus --sizes Standard_D4s_v5 Standard_E4s_v5\n\n"
            "With placement scores and quota checking:\n"
            "  spotvm --subscription-id <ID> --regions centralus --sizes Standard_D4s_v5 --placement-check --desired-count 10"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_base_arguments(parser)
    _add_filtering_arguments(parser)
    _add_history_arguments(parser)
    return parser


def _add_base_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--subscription-id",
        help="Azure subscription ID (only required with --placement-check)",
    )
    parser.add_argument("--regions", nargs="*", help="List of Azure regions")
    parser.add_argument("--sizes", nargs="*", help="List of VM sizes (SKUs)")
    parser.add_argument(
        "--desired-count",
        type=int,
        help="Number of VMs you plan to deploy (used with --placement-check to assess capacity; effective default in placement mode: 1)",
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
        help="Emit machine-readable JSON to stdout and suppress human-readable console output",
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
    parser.add_argument(
        "--include-databricks-cost",
        action="store_true",
        help="Overlay vendored Databricks DBU cost metadata onto matching VM SKUs",
    )
    parser.add_argument(
        "--include-photon-cost",
        action="store_true",
        help="Use the full Photon DBU rate when Databricks cost mode is enabled",
    )
    parser.add_argument(
        "--refresh-databricks-catalog",
        action="store_true",
        help="Print the manual Databricks pricing refresh procedure and exit",
    )


def _add_filtering_arguments(parser: argparse.ArgumentParser) -> None:
    # Requirements-based filtering
    parser.add_argument(
        "--min-vcpu",
        type=int,
        help="Minimum vCPUs required. By default, discovery/filtering keeps the next three distinct known vCPU tiers from the specs database. Use --no-max-limit to disable.",
    )
    parser.add_argument(
        "--min-ram",
        type=int,
        help="Minimum RAM required in GB. By default, discovery/filtering keeps the next three distinct known RAM tiers from the specs database. Use --no-max-limit to disable.",
    )
    parser.add_argument(
        "--no-max-limit",
        action="store_true",
        help="Disable bounded hardware windows for --min-vcpu/--min-ram and keep unbounded minimum filtering",
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
        help=(
            "Maximum acceptable hourly price in USD "
            "(uses combined VM + Databricks hourly cost when --include-databricks-cost is enabled)"
        ),
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

    # Sorting
    parser.add_argument(
        "--sort",
        type=str,
        choices=["price", "price-per-vcpu", "eviction"],
        default="price",
        help="Sort order for results: price (default), price-per-vcpu, or eviction",
    )


def _add_history_arguments(parser: argparse.ArgumentParser) -> None:
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    # Show help when invoked with no arguments
    if (argv is not None and len(argv) == 0) or (argv is None and len(sys.argv) <= 1):
        parser.print_help()
        return 0
    args = parser.parse_args(argv)
    logger = _build_cli_logger(args)
    if args.refresh_databricks_catalog:
        return _run_refresh_mode(logger=logger)
    history_rc = _run_history_mode_if_requested(
        args=args,
        logger=logger,
        run_history_analysis=_run_history_analysis,
    )
    if history_rc is not None:
        return history_rc
    prepared = _prepare_analysis_execution(
        parser=parser,
        args=args,
        logger=logger,
    )
    if isinstance(prepared, int):
        return prepared
    config, request = prepared
    return _run_analysis_mode(
        request=request,
        config=config,
        logger=logger,
        clear_cache=args.clear_cache,
        interval_minutes=args.run_unattended,
        run_single_analysis=_run_single_analysis,
        run_unattended_monitoring=_run_unattended_monitoring,
    )


def _build_cli_logger(args: argparse.Namespace) -> logging.Logger:
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    logger = logging.getLogger("spotvm")
    if not args.verbose:
        logger.setLevel(logging.INFO)
    if not args.no_color:
        initialize_color_output()
    return logger


def _run_history_mode_if_requested(
    *,
    args: argparse.Namespace,
    logger: logging.Logger,
    run_history_analysis: Callable[..., int],
) -> int | None:
    if not args.analyze_history:
        return None
    return run_history_analysis(
        results_dir=args.results_dir,
        depth=args.history_depth,
        history_output=args.history_output,
        logger=logger,
    )


def _prepare_analysis_execution(
    *,
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    logger: logging.Logger,
) -> tuple[ToolConfig, AnalysisRunRequest] | int:
    base_config: dict[str, Any] = {}
    if args.config:
        base_config = load_config_file(args.config)

    sizes, auto_discovery_attempted = _resolve_requested_sizes(
        parser=parser,
        args=args,
        base_config=base_config,
        logger=logger,
    )
    if auto_discovery_attempted and not sizes:
        logger.error("No SKUs found matching specified requirements")
        return 1

    config = _build_runtime_config(
        parser=parser,
        args=args,
        base_config=base_config,
        sizes=sizes,
    )
    request = _build_analysis_run_request(args, save_results=args.save_results)
    return config, request


def _build_runtime_config(
    *,
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    base_config: dict[str, Any],
    sizes: list[str] | None,
) -> ToolConfig:
    overrides: dict[str, Any] = {
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
        "include_databricks_cost": args.include_databricks_cost or None,
        "include_photon_cost": args.include_photon_cost or None,
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
    if config_data.get("include_photon_cost") and not config_data.get("include_databricks_cost"):
        parser.error("--include-photon-cost requires --include-databricks-cost")

    try:
        return ToolConfig.from_dict(config_data)
    except (TypeError, ValueError) as exc:
        parser.error(str(exc))
        raise SystemExit(2) from exc


def _run_analysis_mode(
    *,
    request: AnalysisRunRequest,
    config: ToolConfig,
    logger: logging.Logger,
    clear_cache: bool,
    interval_minutes: int | None,
    run_single_analysis: Callable[..., None],
    run_unattended_monitoring: Callable[..., int],
) -> int:
    if clear_cache:
        from . import cache

        cache.clear()
        logger.info("Cache cleared")

    if interval_minutes:
        return run_unattended_monitoring(
            request=replace(request, save_results=True),
            config=config,
            logger=logger,
            interval_minutes=interval_minutes,
            run_single_analysis=run_single_analysis,
        )

    try:
        run_single_analysis(
            request=request,
            config=config,
            logger=logger,
        )
    except AzureHttpError as exc:
        logger.error("Azure API request failed: %s", exc)  # noqa: TRY400 - user-facing API failure should stay concise
        return 2
    except DatabricksCatalogError as exc:
        logger.error(  # noqa: TRY400 - user-facing remediation should stay concise without a traceback
            "Databricks pricing catalog failed: %s. Use --refresh-databricks-catalog to refresh vendored data, "
            "or remove --include-databricks-cost to continue without Databricks enrichment.",
            exc,
        )
        return 2

    return 0


def _run_refresh_mode(*, logger: logging.Logger) -> int:
    logger.info("Databricks catalog refresh is manual-only")
    print(refresh_catalog_instructions())
    return 0


def _run_unattended_monitoring(
    *,
    request: AnalysisRunRequest,
    config: ToolConfig,
    logger: logging.Logger,
    interval_minutes: int,
    run_single_analysis,
    emit=print,
    sleep=None,
    install_signal_handlers: bool = True,
    should_stop=None,
) -> int:
    logger.info(f"Starting unattended monitoring mode: running every {interval_minutes} minutes. Press Ctrl+C to stop.")
    _nc = request.no_color
    emit(f"{'[*]' if _nc else '🔄'} Monitoring mode started (interval: {interval_minutes} min)")
    emit(f"{'[>]' if _nc else '📊'} Results will be saved to: {request.results_dir}/runs/")
    emit(f"{'[!]' if _nc else '⏸️ '} Press Ctrl+C to stop\n")

    stop_requested = False

    def signal_handler(signum, frame):
        nonlocal stop_requested
        stop_requested = True
        emit(f"\n{'[x]' if _nc else '⏹️ '} Stop requested, finishing current run...")

    if install_signal_handlers:
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    if sleep is None:
        sleep = time.sleep

    if should_stop is None:

        def should_stop() -> bool:
            return stop_requested

    run_count = 0
    unexpected_error_count = 0
    while not should_stop():
        run_count += 1
        emit(f"\n{'=' * 60}")
        emit(f"Run #{run_count} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        emit(f"{'=' * 60}")

        unexpected_error_count, exit_code = _run_unattended_iteration(
            request=request,
            config=config,
            logger=logger,
            run_single_analysis=run_single_analysis,
            unexpected_error_count=unexpected_error_count,
            emit=emit,
        )
        if exit_code is not None:
            return exit_code

        if not should_stop():
            _sleep_until_next_run(
                interval_minutes=interval_minutes,
                logger=logger,
                emit=emit,
                sleep=sleep,
                should_stop=should_stop,
                no_color=_nc,
            )

    emit(f"\n{'[OK]' if _nc else '✅'} Monitoring stopped after {run_count} run(s)")
    return 0


def _run_unattended_iteration(
    *,
    request: AnalysisRunRequest,
    config: ToolConfig,
    logger: logging.Logger,
    run_single_analysis,
    unexpected_error_count: int,
    emit=print,
) -> tuple[int, int | None]:
    try:
        run_single_analysis(
            request=request,
            config=config,
            logger=logger,
        )
    except AzureHttpError as exc:
        # Azure API failures are treated as transient service errors in
        # unattended mode, so they do not count toward the stop threshold.
        logger.error(f"Azure API request failed: {exc}")  # noqa: TRY400 - traceback is noise for API failures
        logger.info("Continuing despite error...")
        return unexpected_error_count, None
    except DatabricksCatalogError as exc:
        unexpected_error_count += 1
        logger.error(  # noqa: TRY400 - catalog failures are user-facing and do not need tracebacks
            "Databricks pricing catalog failed (%d/%d): %s",
            unexpected_error_count,
            config_defaults.DEFAULT_MAX_UNATTENDED_FAILURES,
            exc,
        )
        if unexpected_error_count >= config_defaults.DEFAULT_MAX_UNATTENDED_FAILURES:
            logger.error(  # noqa: TRY400 - stop condition is a state transition, not an exception report
                "Stopping unattended mode after %d consecutive unattended monitoring failures",
                config_defaults.DEFAULT_MAX_UNATTENDED_FAILURES,
            )
            emit(
                f"\n{'[x]' if request.no_color else '❌'} Stopping monitoring after "
                f"{config_defaults.DEFAULT_MAX_UNATTENDED_FAILURES} consecutive unattended monitoring failures."
            )
            return unexpected_error_count, 1
        logger.info("Continuing despite error...")
        return unexpected_error_count, None
    except MemoryError:
        raise
    except _FATAL_UNATTENDED_EXCEPTIONS:
        logger.exception("Fatal programming error in unattended run")
        emit(f"\n{'[x]' if request.no_color else '❌'} Stopping monitoring after a fatal programming error.")
        return unexpected_error_count, 1
    except Exception:
        unexpected_error_count += 1
        logger.exception(
            "Unexpected error in unattended run (%d/%d)",
            unexpected_error_count,
            config_defaults.DEFAULT_MAX_UNATTENDED_FAILURES,
        )
        if unexpected_error_count >= config_defaults.DEFAULT_MAX_UNATTENDED_FAILURES:
            logger.error(  # noqa: TRY400 - traceback already emitted immediately above
                "Stopping unattended mode after %d consecutive unattended monitoring failures",
                config_defaults.DEFAULT_MAX_UNATTENDED_FAILURES,
            )
            emit(
                f"\n{'[x]' if request.no_color else '❌'} Stopping monitoring after "
                f"{config_defaults.DEFAULT_MAX_UNATTENDED_FAILURES} consecutive unattended monitoring failures."
            )
            return unexpected_error_count, 1
        logger.info("Continuing despite error...")
        return unexpected_error_count, None
    else:
        return 0, None


def _sleep_until_next_run(
    *,
    interval_minutes: int,
    logger: logging.Logger,
    emit=print,
    sleep=time.sleep,
    should_stop,
    no_color: bool = True,
    now=None,
) -> None:
    if now is None:
        now = datetime.now

    next_run = now() + timedelta(minutes=interval_minutes)
    logger.info(f"Next run at {next_run.strftime('%H:%M:%S')}")
    emit(f"\n{'[.]' if no_color else '💤'} Sleeping for {interval_minutes} minutes...")
    emit(f"   Next run at: {next_run.strftime('%H:%M:%S')}")

    sleep_seconds = interval_minutes * 60
    for _ in range(sleep_seconds):
        if should_stop():
            break
        sleep(1)


def _resolve_effective_cpu_arch(
    *,
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    base_config: dict[str, Any],
) -> str | None:
    effective_cpu_arch = args.cpu_arch if args.cpu_arch is not None else base_config.get("cpu_arch")
    if effective_cpu_arch is None:
        return None
    if not isinstance(effective_cpu_arch, str):
        parser.error(f"cpu_arch must be one of {sorted(VALID_CPU_ARCHS)}")
        raise SystemExit(2)
    effective_cpu_arch = effective_cpu_arch.lower()
    if effective_cpu_arch not in VALID_CPU_ARCHS:
        parser.error(f"cpu_arch must be one of {sorted(VALID_CPU_ARCHS)}")
        raise SystemExit(2)
    return effective_cpu_arch


def _discover_requested_sizes(
    *,
    args: argparse.Namespace,
    effective_cpu_arch: str | None,
    logger: logging.Logger,
) -> tuple[list[str] | None, bool]:
    should_auto_discover = args.min_vcpu is not None or args.min_ram is not None or effective_cpu_arch is not None
    if not should_auto_discover:
        return None, False

    requirements = []
    if args.min_vcpu is not None:
        requirements.append(f"vCPU≥{args.min_vcpu}")
    if args.min_ram is not None:
        requirements.append(f"RAM≥{args.min_ram} GB")
    if effective_cpu_arch:
        requirements.append(f"arch={effective_cpu_arch}")
    logger.info(f"No --sizes specified, auto-discovering SKUs matching requirements ({', '.join(requirements)})")

    discover_kwargs = {
        "min_vcpu": args.min_vcpu,
        "min_ram": args.min_ram,
        "cpu_arch": effective_cpu_arch,
    }
    if args.no_max_limit:
        discover_kwargs["no_max_limit"] = True
    sizes = discover_skus(**discover_kwargs)
    if sizes:
        logger.info(f"Auto-discovered {len(sizes)} SKUs: {', '.join(sizes[:5])}{'...' if len(sizes) > 5 else ''}")
    return sizes, True


def _resolve_requested_sizes(
    *,
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    base_config: dict[str, Any],
    logger: logging.Logger,
) -> tuple[list[str] | None, bool]:
    # Auto-discover SKUs only when neither CLI nor config specifies sizes.
    # cpu_arch can come from config here; min_vcpu/min_ram are still CLI-only.
    sizes = args.sizes if args.sizes is not None else base_config.get("sizes")
    args.explicit_sizes = bool(sizes)
    effective_cpu_arch = _resolve_effective_cpu_arch(
        parser=parser,
        args=args,
        base_config=base_config,
    )
    if sizes:
        return sizes, False
    return _discover_requested_sizes(
        args=args,
        effective_cpu_arch=effective_cpu_arch,
        logger=logger,
    )


def _run_history_analysis(
    *,
    results_dir: Path,
    depth: int | None,
    history_output: Path | None,
    logger: logging.Logger,
    emit=print,
) -> int:
    from .history import HistoricalSnapshotError, analyze_history

    output_path = history_output or (results_dir / "history.csv")

    logger.info("Analyzing historical data from %s", results_dir)
    try:
        num_runs, num_datapoints, csv_path, skipped_files = analyze_history(
            results_dir=results_dir,
            depth=depth,
            output_path=output_path,
        )
    except (HistoricalSnapshotError, OSError) as exc:
        logger.error("Historical analysis failed: %s", str(exc))  # noqa: TRY400 - user-facing history failure should stay concise
        return 2

    emit("Historical Analysis Complete:")
    emit(f"  Runs analyzed: {num_runs}")
    emit(f"  Data points: {num_datapoints}")
    emit(f"  Skipped invalid files: {skipped_files}")
    if csv_path.exists():
        emit(f"  CSV output: {csv_path}")
        emit("\nUse this CSV for visualization with tools like:")
        emit(f"  - Excel/Google Sheets: Import {csv_path}")
        emit(f"  - Python: pd.read_csv('{csv_path}')")
        emit("  - Grafana: CSV data source plugin")
    else:
        emit("  CSV output: not created (no data points)")

    return 0


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, indent=2, default=_json_serializer)
            handle.write("\n")
            temp_path = Path(handle.name)
        temp_path.replace(path)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def _fetch_analysis_inputs(
    *,
    client: AzureRestClient,
    config: ToolConfig,
) -> tuple[list[PlacementScoreResult], list[HistoricalMetrics]]:
    placement_scores: list[PlacementScoreResult] = []
    if config.enable_placement:
        placement_request = _build_placement_score_request(config)
        placement_scores = fetch_placement_scores(client, placement_request)
    resource_graph_request = _build_resource_graph_request(config)
    historical_metrics = fetch_historical_metrics(client, resource_graph_request)
    return placement_scores, historical_metrics


def _build_ranked_candidates(
    *,
    placement_scores: list[PlacementScoreResult],
    historical_metrics: list[HistoricalMetrics],
    request: AnalysisRunRequest,
    config: ToolConfig,
    filter_stats: dict[str, int] | None = None,
) -> list[CandidateInsight]:
    candidates = merge_datasets(placement_scores, historical_metrics)

    effective_no_max_limit = request.no_max_limit or request.explicit_sizes
    candidates = filter_by_requirements(
        candidates,
        min_vcpu=request.min_vcpu,
        min_ram=request.min_ram,
        cpu_arch=config.cpu_arch,
        no_max_limit=effective_no_max_limit,
    )
    if config.include_databricks_cost:
        refresh_databricks_catalog_cache()
        candidates = enrich_with_databricks_cost(
            candidates,
            include_photon=config.include_photon_cost,
        )

    ranked = rank_candidates(candidates, sort_order=request.sort_order)
    ranked = enrich_with_performance(ranked, config.baseline_sku)
    ranked = enrich_with_coremark(ranked)
    ranked = filter_by_cost(
        ranked,
        max_price=request.max_price,
        max_eviction=request.max_eviction,
        min_performance=request.min_performance,
        filter_stats=filter_stats,
    )

    if config.result_limit:
        ranked = ranked[: config.result_limit]
    return ranked


def _run_single_analysis(
    request: AnalysisRunRequest,
    config: ToolConfig,
    logger,
) -> None:
    """Execute a single analysis run.

    Args:
        request: CLI execution request
        config: Tool configuration
        logger: Logger instance
    """
    # Handle color output setting
    _nc = request.no_color
    render_options = RenderOptions(colors_enabled=(not _nc and sys.stdout.isatty()))

    authenticator = AzureAuthenticator()
    client = AzureRestClient(authenticator)
    placement_scores, historical_metrics = _fetch_analysis_inputs(
        client=client,
        config=config,
    )
    filter_stats: dict[str, int] = {}
    ranked = _build_ranked_candidates(
        placement_scores=placement_scores,
        historical_metrics=historical_metrics,
        request=request,
        config=config,
        filter_stats=filter_stats,
    )

    def emit(*values: Any, **kwargs: Any) -> None:
        if config.emit_json:
            return
        print(*values, file=sys.stdout, **kwargs)

    def emit_error(*values: Any, **kwargs: Any) -> None:
        print(*values, file=sys.stderr, **kwargs)

    if _persist_analysis_outputs(
        ranked,
        request=request,
        config=config,
        logger=logger,
        emit=emit,
        emit_error=emit_error,
    ):
        return

    _render_analysis_results(
        ranked,
        request=request,
        config=config,
        render_options=render_options,
        emit=emit,
        missing_databricks_total_count=filter_stats.get("missing_databricks_total_price_count", 0),
    )


def _persist_analysis_outputs(
    ranked: list[CandidateInsight],
    *,
    request: AnalysisRunRequest,
    config: ToolConfig,
    logger: logging.Logger,
    emit,
    emit_error,
) -> bool:
    _nc = request.no_color

    _save_run_results_if_requested(
        ranked,
        request=request,
        config=config,
        logger=logger,
        emit=emit,
        emit_error=emit_error,
    )

    # Export to CSV if requested (even if empty, so downstream tools see the run)
    if request.csv:
        try:
            export_to_csv(
                ranked,
                request.csv,
                show_placement=config.enable_placement,
                show_baseline=config.baseline_sku is not None,
                show_databricks=config.include_databricks_cost,
                show_photon=config.include_photon_cost,
            )
        except OSError as exc:
            logger.error(  # noqa: TRY400 - expected filesystem failure path
                "Failed to export CSV to %s: %s",
                request.csv,
                exc,
            )
            emit_error(f"{'[x]' if _nc else '❌'} Failed to export CSV to: {request.csv} ({exc})\n")
        else:
            logger.info("Results exported to CSV: %s", request.csv)
            emit(f"{'[OK]' if _nc else '✅'} CSV exported to: {request.csv}\n")

    return _emit_report_if_requested(
        ranked,
        request=request,
        config=config,
        logger=logger,
        emit_error=emit_error,
    )


def _save_run_results_if_requested(
    ranked: list[CandidateInsight],
    *,
    request: AnalysisRunRequest,
    config: ToolConfig,
    logger: logging.Logger,
    emit,
    emit_error,
) -> None:
    if not request.save_results:
        return

    # Save results for historical analysis even if the candidate list is empty,
    # so unattended monitoring still records that a run completed.
    from .history import save_run_results

    try:
        saved_path = save_run_results(
            candidates=ranked,
            config=config,
            results_dir=request.results_dir,
        )
    except (OSError, ValueError) as exc:
        logger.warning("Failed to save run results: %s", exc)
        emit_error(f"Failed to save run results: {exc}")
    else:
        _nc = request.no_color
        logger.info("Results saved to %s", saved_path)
        emit(f"{'[OK]' if _nc else '✅'} Results saved to: {saved_path}\n")


def _emit_report_if_requested(
    ranked: list[CandidateInsight],
    *,
    request: AnalysisRunRequest,
    config: ToolConfig,
    logger: logging.Logger,
    emit_error,
) -> bool:
    if not (config.emit_json or config.save_report):
        return False

    report_payload = _build_report(
        ranked,
        show_databricks=config.include_databricks_cost,
        show_photon=config.include_photon_cost,
    )
    if config.emit_json:
        print(json.dumps(report_payload, indent=2, default=_json_serializer), file=sys.stdout)
    if config.save_report:
        try:
            _write_json_atomic(config.save_report, report_payload)
        except OSError as exc:
            _nc = request.no_color
            logger.error(  # noqa: TRY400 - expected filesystem failure path
                "Failed to save report to %s: %s",
                config.save_report,
                exc,
            )
            emit_error(f"{'[x]' if _nc else '❌'} Failed to save report to: {config.save_report} ({exc})\n")
        else:
            logger.info("Saved report to %s", config.save_report)

    return config.emit_json


def _render_analysis_results(
    ranked: list[CandidateInsight],
    *,
    request: AnalysisRunRequest,
    config: ToolConfig,
    render_options: RenderOptions,
    emit,
    missing_databricks_total_count: int = 0,
) -> None:
    if not ranked:
        emit("No candidates match the specified filters. Try relaxing constraints.")
        _emit_missing_databricks_total_note(
            emit=emit,
            request=request,
            config=config,
            missing_databricks_total_count=missing_databricks_total_count,
        )
        return

    emit(
        render_table(
            ranked,
            show_placement=config.enable_placement,
            show_baseline=config.baseline_sku is not None,
            show_databricks=config.include_databricks_cost,
            show_photon=config.include_photon_cost,
            render_options=render_options,
        )
    )

    # Print column explanations
    if config.enable_placement:
        emit("\nColumn Descriptions:")
        emit("  Quota: Indicates if sufficient vCPU quota is available")
        emit("    - Yes: Quota available for deployment")
        emit("    - No:  Insufficient quota (increase quota or choose different region/size)")
        emit("    - Unknown: Quota data not returned by Azure for this SKU/region")
    if config.baseline_sku:
        emit(f"\nPerformance Baseline: {config.baseline_sku} = 100%")
        emit("  Perf %: Relative computing power compared to baseline")
        emit("  Price/Perf: Price per performance unit (lower is better value)")
        if any(item.performance_basis == "heuristic" for item in ranked):
            emit(
                "  * Heuristic perf: Perf % / Price/Perf use the vCPU/RAM fallback "
                "because comparable CoreMark data is unavailable."
            )

    # Print color legend if colors are enabled
    if not request.no_color:
        from colorama import Fore, Style

        emit("\nColor Legend:")
        emit(
            f"  Eviction Rate: {Fore.BLUE}<5%{Style.RESET_ALL} | "
            f"{Fore.GREEN}5-<10%{Style.RESET_ALL} | "
            f"{Fore.YELLOW}10-<15%{Style.RESET_ALL} | "
            f"{Fore.RED}15-<25%{Style.RESET_ALL} | "
            f"{Fore.RED}{Style.BRIGHT}≥25%{Style.RESET_ALL}"
        )
        if config.enable_placement:
            emit(
                f"  Placement:     {Fore.GREEN}High{Style.RESET_ALL} | "
                f"{Fore.YELLOW}Medium{Style.RESET_ALL} | "
                f"{Fore.RED}Low{Style.RESET_ALL}"
            )

    summary_lines = summarize_top_candidates(ranked)
    if summary_lines:
        emit("\nRecommendations:")
        for line in summary_lines:
            emit(f" - {line}")

    _emit_missing_databricks_total_note(
        emit=emit,
        request=request,
        config=config,
        missing_databricks_total_count=missing_databricks_total_count,
    )

    if config.enable_placement:
        disclaimer = (
            "Note: Azure Spot placement scores are point-in-time indicators and "
            "do not guarantee successful allocation or avoidance of eviction."
        )
        emit(f"\n{disclaimer}")
    else:
        emit(
            "\nNote: Spot VM pricing and eviction rates are historical estimates "
            "and may change. Use --placement-check for capacity/quota data."
        )


def _emit_missing_databricks_total_note(
    *,
    emit,
    request: AnalysisRunRequest,
    config: ToolConfig,
    missing_databricks_total_count: int,
) -> None:
    if missing_databricks_total_count <= 0 or not config.include_databricks_cost or request.max_price is None:
        return
    emit(
        "\nDatabricks pricing note: "
        f"{missing_databricks_total_count} candidate(s) were excluded from --max-price "
        "because Databricks total price was unavailable for those SKUs."
    )


def _build_report(
    candidates: list[CandidateInsight],
    *,
    show_databricks: bool = False,
    show_photon: bool = False,
) -> dict[str, Any]:
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "candidates": [
            project_for_report(
                item,
                _json_serializer,
                _merge_notes,
                show_databricks=show_databricks,
                show_photon=show_photon,
            )
            for item in candidates
        ],
    }


def _merge_notes(*notes: Any) -> Any:
    parts: list[str] = []
    for note in notes:
        if isinstance(note, str) and note and note not in parts:
            parts.append(note)
    return "; ".join(parts) or None


def _json_serializer(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise _unsupported_json_type_error(value)


def _unsupported_json_type_error(value: Any) -> TypeError:
    return TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


if __name__ == "__main__":
    sys.exit(main())
