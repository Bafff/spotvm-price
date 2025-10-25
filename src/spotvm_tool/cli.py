from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from .analysis import merge_datasets, rank_candidates, summarize_top_candidates
from .auth import AzureAuthenticator
from .config import ToolConfig, load_config_file, merge_cli_overrides
from .http_client import AzureRestClient, AzureHttpError
from .placement_score import fetch_placement_scores
from .reporting import render_table
from .resource_graph import fetch_historical_metrics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spotvm-tool",
        description="Analyze Azure Spot VM placement scores against historical metrics.",
    )
    parser.add_argument("--subscription-id", help="Azure subscription ID")
    parser.add_argument("--regions", nargs="*", help="List of Azure regions")
    parser.add_argument("--sizes", nargs="*", help="List of VM sizes (SKUs)")
    parser.add_argument("--desired-count", type=int, help="Desired number of VMs")
    parser.add_argument(
        "--os-type",
        choices=["linux", "windows"],
        help="Operating system for price history queries",
    )
    parser.add_argument(
        "--availability-zones",
        action="store_true",
        help="Include availability zone-specific placement scores",
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
        "--skip-placement",
        action="store_true",
        help="Skip calling the Spot Placement Score API",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    logger = logging.getLogger("spotvm-tool")

    base_config: Dict[str, Any] = {}
    if args.config:
        base_config = load_config_file(args.config)

    overrides: Dict[str, Any] = {
        "subscription_id": args.subscription_id,
        "regions": args.regions,
        "sizes": args.sizes,
        "desired_count": args.desired_count,
        "os_type": args.os_type,
        "availability_zones": args.availability_zones or None,
        "cache_ttl_minutes": args.cache_ttl_minutes,
        "save_report": str(args.save_report) if args.save_report else None,
        "emit_json": args.json,
        "result_limit": args.limit,
    }
    if args.skip_placement:
        overrides["enable_placement"] = False

    config_data = merge_cli_overrides(base_config, overrides)
    try:
        config = ToolConfig.from_dict(config_data)
    except Exception as exc:  # noqa: BLE001 - surface configuration errors
        parser.error(str(exc))
        return 1

    if args.clear_cache:
        from . import cache

        cache.clear()
        logger.info("Cache cleared")

    authenticator = AzureAuthenticator()
    client = AzureRestClient(authenticator)

    try:
        placement_scores = (
            fetch_placement_scores(client, config)
            if config.enable_placement
            else []
        )
        historical_metrics = fetch_historical_metrics(client, config)
    except AzureHttpError as exc:
        logger.error("Azure API request failed: %s", exc)
        return 2

    candidates = merge_datasets(placement_scores, historical_metrics)
    ranked = rank_candidates(candidates)

    if config.result_limit:
        ranked = ranked[: config.result_limit]

    table = render_table(ranked)
    print(table)

    summary_lines = summarize_top_candidates(ranked)
    if summary_lines:
        print("\nRecommendations:")
        for line in summary_lines:
            print(f" - {line}")

    if config.emit_json or config.save_report:
        report_payload = _build_report(ranked)
        if config.emit_json:
            print("\nJSON Output:")
            print(json.dumps(report_payload, indent=2, default=_json_serializer))
        if config.save_report:
            config.save_report.write_text(
                json.dumps(report_payload, indent=2, default=_json_serializer),
                encoding="utf-8",
            )
            logger.info("Saved report to %s", config.save_report)

    disclaimer = (
        "Note: Azure Spot placement scores are point-in-time indicators and "
        "do not guarantee successful allocation or avoidance of eviction."
    )
    print(f"\n{disclaimer}")

    return 0


def _build_report(candidates: List[Any]) -> Dict[str, Any]:
    return {
        "generatedAt": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "candidates": [
            {
                "rank": item.recommendation_rank,
                "region": item.region,
                "availabilityZone": item.availability_zone,
                "vmSize": item.vm_size,
                "placementScore": item.placement_score,
                "quotaAvailable": item.quota_available,
                "priceUSDPerHour": item.price_usd,
                "priceLastUpdated": _json_serializer(item.price_last_updated),
                "evictionRatePercent": item.eviction_rate,
                "evictionLastUpdated": _json_serializer(item.eviction_last_updated),
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
