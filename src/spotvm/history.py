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
from typing import Any

from .config import ToolConfig
from .models import DATABRICKS_OPTIONAL_FIELDS, CandidateInsight
from .projection import project_for_history

logger = logging.getLogger("spotvm")


class HistoricalSnapshotError(ValueError):
    pass


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

    try:
        serialized_snapshot = json.dumps(asdict(snapshot), indent=2)
    except TypeError as exc:
        raise _serialization_error(filepath) from exc

    filepath.write_text(serialized_snapshot, encoding="utf-8")

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
    snapshots, _skipped_files = _load_historical_runs_with_skipped_count(results_dir, depth)
    return snapshots


def _run_snapshot_from_payload(data: object) -> RunSnapshot:
    if not isinstance(data, dict):
        raise _invalid_snapshot_payload()
    timestamp = _required_snapshot_field(data, "timestamp")
    config = _required_snapshot_field(data, "config")
    candidates = _required_snapshot_field(data, "candidates")
    if not isinstance(timestamp, str):
        raise _invalid_snapshot_type("timestamp", "a string")
    if not isinstance(config, dict):
        raise _invalid_snapshot_type("config", "a mapping")
    if not isinstance(candidates, list):
        raise _invalid_snapshot_type("candidates", "a list")
    return RunSnapshot(
        timestamp=timestamp,
        config=config,
        candidates=candidates,
    )


def _invalid_snapshot_type(field_name: str, expected: str) -> HistoricalSnapshotError:
    return HistoricalSnapshotError(f"{field_name} must be {expected}")


def _invalid_snapshot_payload() -> HistoricalSnapshotError:
    return HistoricalSnapshotError("snapshot payload must be an object")


def _required_snapshot_field(data: dict[str, Any], key: str) -> Any:
    if key not in data:
        raise _missing_snapshot_field(key)
    return data.get(key)


def _serialization_error(filepath: Path) -> ValueError:
    return ValueError(f"Failed to serialize historical run snapshot: {filepath}")


def _missing_snapshot_field(key: str) -> HistoricalSnapshotError:
    return HistoricalSnapshotError(f"{key} is missing")


def _csv_value(candidate: dict[str, Any], key: str) -> Any:
    """Return the candidate value for *key*, falling back to ``""`` for ``None``."""
    value = candidate.get(key)
    if value is None:
        return ""
    return value


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
                "price_usd": _csv_value(candidate, "price_usd"),
                "eviction_rate": _csv_value(candidate, "eviction_rate"),
                "placement_score": candidate.get("placement_score") or "",
                "quota_available": _csv_value(candidate, "quota_available"),
                "performance_relative": _csv_value(candidate, "performance_relative"),
                "price_per_performance": _csv_value(candidate, "price_per_performance"),
                "recommendation_rank": _csv_value(candidate, "recommendation_rank"),
            }
            if include_databricks:
                for field in DATABRICKS_OPTIONAL_FIELDS:
                    row[field] = _csv_value(candidate, field)
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
) -> tuple[int, int, Path, int]:
    """Analyze historical runs and generate unified CSV.

    Convenience function that combines load + generate steps.

    Args:
        results_dir: Base directory containing runs/
        depth: Maximum number of runs to analyze
        output_path: Where to write CSV (default: results_dir/history.csv)

    Returns:
        Tuple of (num_runs, num_datapoints, csv_path, skipped_files)
    """
    snapshots, skipped_files = _load_historical_runs_with_skipped_count(results_dir, depth)
    num_runs = len(snapshots)

    if output_path is None:
        output_path = results_dir / "history.csv"

    num_datapoints = generate_history_csv(snapshots, output_path)

    return (num_runs, num_datapoints, output_path, skipped_files)


def _load_historical_runs_with_skipped_count(
    results_dir: Path,
    depth: int | None = None,
) -> tuple[list[RunSnapshot], int]:
    runs_dir = results_dir / "runs"
    if not runs_dir.exists():
        return [], 0

    json_files = sorted(runs_dir.glob("*.json"))
    if depth is not None and depth > 0:
        json_files = json_files[-depth:]

    snapshots = []
    skipped_files = 0
    for filepath in json_files:
        try:
            with filepath.open("r") as f:
                data = json.load(f)
                snapshots.append(_run_snapshot_from_payload(data))
        except (OSError, json.JSONDecodeError, HistoricalSnapshotError) as exc:
            skipped_files += 1
            logger.warning("Failed to load historical run %s: %s", filepath, exc)
            continue

    return snapshots, skipped_files
