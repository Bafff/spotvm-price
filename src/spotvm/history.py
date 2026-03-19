"""Historical data management for spotvm.

Saves each run's results to JSON files and provides analysis
of historical price/eviction trends across multiple runs.
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import ToolConfig
from .models import DATABRICKS_OPTIONAL_FIELDS, CandidateInsight
from .projection import project_for_history

logger = logging.getLogger("spotvm")


@dataclass
class RunSnapshot:
    """Snapshot of a single tool run with all results."""

    timestamp: str  # ISO 8601 format
    config: dict[str, str | list[str] | None]  # Config used for this run
    candidates: list[dict[str, str | float | int | bool | None]]  # All candidate results


def save_run_results(
    candidates: list[CandidateInsight],
    config: ToolConfig,
    results_dir: Path,
) -> Path:
    """Save current run results to timestamped JSON file.

    Args:
        candidates: List of analyzed candidates
        config: Tool configuration used for this run
        results_dir: Base directory for results (will create runs/ subdirectory)

    Returns:
        Path to saved JSON file
    """
    # Create directory structure
    runs_dir = results_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    # Create snapshot with microsecond precision to avoid filename collisions
    timestamp = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    snapshot = RunSnapshot(
        timestamp=timestamp,
        config={
            "regions": config.regions,
            "sizes": config.sizes,
            "baseline_sku": config.baseline_sku,
            "subscription_id": config.subscription_id[:8] + "..." if config.subscription_id else None,  # Privacy
        },
        candidates=[project_for_history(candidate) for candidate in candidates],
    )

    # Save to file
    filename = timestamp.replace(":", "-") + ".json"
    filepath = runs_dir / filename

    with filepath.open("w") as f:
        json.dump(asdict(snapshot), f, indent=2)

    return filepath


def load_historical_runs(
    results_dir: Path,
    depth: int | None = None,
) -> list[RunSnapshot]:
    """Load previous run snapshots from disk.

    Args:
        results_dir: Base directory containing runs/
        depth: Maximum number of most recent runs to load (None = all)

    Returns:
        List of RunSnapshot objects, sorted by timestamp (oldest first)
    """
    runs_dir = results_dir / "runs"
    if not runs_dir.exists():
        return []

    # Find all JSON files
    json_files = sorted(runs_dir.glob("*.json"))

    # Apply depth limit (take N most recent)
    if depth is not None and depth > 0:
        json_files = json_files[-depth:]

    # Load snapshots
    snapshots = []
    for filepath in json_files:
        try:
            with filepath.open("r") as f:
                data = json.load(f)
                snapshots.append(
                    RunSnapshot(
                        timestamp=data["timestamp"],
                        config=data["config"],
                        candidates=data["candidates"],
                    )
                )
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("Failed to load historical run %s: %s", filepath, exc)
            continue

    return snapshots


def generate_history_csv(
    snapshots: list[RunSnapshot],
    output_path: Path,
) -> int:
    """Generate unified CSV file from multiple run snapshots.

    Combines all candidates from all runs into a single CSV file
    suitable for visualization and trend analysis.

    Args:
        snapshots: List of run snapshots to combine
        output_path: Path where to write the CSV file

    Returns:
        Number of data points written
    """
    if not snapshots:
        return 0

    include_databricks = any(
        any(field in candidate for field in DATABRICKS_OPTIONAL_FIELDS)
        for snapshot in snapshots
        for candidate in snapshot.candidates
    )

    # Prepare rows for CSV
    rows = []
    for snapshot in snapshots:
        for candidate in snapshot.candidates:
            row = {
                "timestamp": snapshot.timestamp,
                "vm_size": candidate.get("vm_size"),
                "region": candidate.get("region"),
                "zone": candidate.get("availability_zone") or "",
                "price_usd": candidate.get("price_usd") if candidate.get("price_usd") is not None else "",
                "eviction_rate": candidate.get("eviction_rate") if candidate.get("eviction_rate") is not None else "",
                "placement_score": candidate.get("placement_score") or "",
                "quota_available": candidate.get("quota_available")
                if candidate.get("quota_available") is not None
                else "",
                "performance_relative": candidate.get("performance_relative")
                if candidate.get("performance_relative") is not None
                else "",
                "price_per_performance": candidate.get("price_per_performance")
                if candidate.get("price_per_performance") is not None
                else "",
                "recommendation_rank": candidate.get("recommendation_rank")
                if candidate.get("recommendation_rank") is not None
                else "",
            }
            if include_databricks:
                for field in DATABRICKS_OPTIONAL_FIELDS:
                    row[field] = candidate.get(field) if candidate.get(field) is not None else ""
            rows.append(row)

    # Write CSV
    if rows:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "timestamp",
            "vm_size",
            "region",
            "zone",
            "price_usd",
            "eviction_rate",
            "placement_score",
            "quota_available",
            "performance_relative",
            "price_per_performance",
            "recommendation_rank",
        ]
        if include_databricks:
            fieldnames.extend(DATABRICKS_OPTIONAL_FIELDS)

        with output_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    return len(rows)


def analyze_history(
    results_dir: Path,
    depth: int | None = None,
    output_path: Path | None = None,
) -> tuple[int, int, Path]:
    """Analyze historical runs and generate unified CSV.

    Convenience function that combines load + generate steps.

    Args:
        results_dir: Base directory containing runs/
        depth: Maximum number of runs to analyze
        output_path: Where to write CSV (default: results_dir/history.csv)

    Returns:
        Tuple of (num_runs, num_datapoints, csv_path)
    """
    snapshots = load_historical_runs(results_dir, depth)
    num_runs = len(snapshots)

    if output_path is None:
        output_path = results_dir / "history.csv"

    num_datapoints = generate_history_csv(snapshots, output_path)

    return (num_runs, num_datapoints, output_path)
