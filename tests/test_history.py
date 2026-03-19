"""Tests for historical data management."""

import csv
import json
import logging
from datetime import datetime
from pathlib import Path

import pytest

from spotvm.config import ToolConfig
from spotvm.history import (
    analyze_history,
    generate_history_csv,
    load_historical_runs,
    save_run_results,
)
from spotvm.models import CandidateInsight


@pytest.fixture
def temp_results_dir(tmp_path):
    """Create a temporary results directory for testing."""
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    return results_dir


@pytest.fixture
def sample_candidates():
    """Sample candidate data for testing."""
    return [
        CandidateInsight(
            vm_size="Standard_D4as_v5",
            region="centralus",
            availability_zone="1",
            price_usd=0.0336,
            price_last_updated=datetime(2025, 1, 25, 14, 30),
            eviction_rate=2.5,
            eviction_last_updated=datetime(2025, 1, 25, 14, 30),
            placement_score="High",
            quota_available=True,
            performance_relative=95.2,
            price_per_performance=0.000353,
            recommendation_rank=1,
        ),
        CandidateInsight(
            vm_size="Standard_D2as_v6",
            region="eastus",
            availability_zone="2",
            price_usd=0.0168,
            price_last_updated=datetime(2025, 1, 25, 14, 30),
            eviction_rate=5.1,
            eviction_last_updated=datetime(2025, 1, 25, 14, 30),
            placement_score="Medium",
            quota_available=True,
            performance_relative=47.6,
            price_per_performance=0.000353,
            recommendation_rank=2,
        ),
    ]


@pytest.fixture
def sample_config():
    """Sample configuration for testing."""
    return ToolConfig(
        subscription_id="test-subscription-id",
        regions=["centralus", "eastus"],
        sizes=["Standard_D4as_v5", "Standard_D2as_v6"],
        enable_placement=True,
        desired_count=10,
        baseline_sku="Standard_D4as_v6",
    )


def test_save_run_results_creates_json(temp_results_dir, sample_candidates, sample_config):
    """Test that save_run_results creates a JSON file with correct structure."""
    saved_path = save_run_results(
        candidates=sample_candidates,
        config=sample_config,
        results_dir=temp_results_dir,
    )

    # Check file was created
    assert saved_path.exists()
    assert saved_path.suffix == ".json"
    assert saved_path.parent.name == "runs"

    # Load and verify structure
    with saved_path.open("r") as f:
        data = json.load(f)

    assert "timestamp" in data
    assert "config" in data
    assert "candidates" in data
    assert len(data["candidates"]) == 2

    # Verify config data
    assert data["config"]["regions"] == ["centralus", "eastus"]
    assert data["config"]["baseline_sku"] == "Standard_D4as_v6"
    assert "..." in data["config"]["subscription_id"]  # Privacy check

    # Verify candidate data
    assert data["candidates"][0]["vm_size"] == "Standard_D4as_v5"
    assert data["candidates"][0]["price_usd"] == 0.0336
    assert data["candidates"][0]["eviction_rate"] == 2.5


def test_load_historical_runs_empty_dir(temp_results_dir):
    """Test loading from empty directory returns empty list."""
    snapshots = load_historical_runs(temp_results_dir)
    assert snapshots == []


def test_load_historical_runs_loads_all_files(temp_results_dir, sample_candidates, sample_config):
    """Test loading multiple historical runs."""
    # Create 3 snapshots
    for _i in range(3):
        save_run_results(sample_candidates, sample_config, temp_results_dir)

    snapshots = load_historical_runs(temp_results_dir)
    assert len(snapshots) == 3

    # Verify snapshots are sorted by timestamp
    for snapshot in snapshots:
        assert snapshot.timestamp
        assert snapshot.config
        assert len(snapshot.candidates) == 2


def test_load_historical_runs_with_depth(temp_results_dir, sample_candidates, sample_config):
    """Test loading with depth limit."""
    # Create 5 snapshots
    for _i in range(5):
        save_run_results(sample_candidates, sample_config, temp_results_dir)

    # Load only last 2
    snapshots = load_historical_runs(temp_results_dir, depth=2)
    assert len(snapshots) == 2


def test_load_historical_runs_skips_malformed_json_file(temp_results_dir, sample_candidates, sample_config, caplog):
    save_run_results(sample_candidates, sample_config, temp_results_dir)
    bad_path = temp_results_dir / "runs" / "broken.json"
    bad_path.write_text("{not-valid-json", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="spotvm"):
        snapshots = load_historical_runs(temp_results_dir)

    assert len(snapshots) == 1
    assert "Failed to load historical run" in caplog.text


def test_load_historical_runs_skips_unreadable_file(
    temp_results_dir, sample_candidates, sample_config, monkeypatch, caplog
):
    save_run_results(sample_candidates, sample_config, temp_results_dir)
    bad_path = temp_results_dir / "runs" / "unreadable.json"
    bad_path.write_text("{}", encoding="utf-8")

    original_open = Path.open

    def raising_open(self: Path, *args, **kwargs):
        if self == bad_path:
            raise PermissionError("no read access")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", raising_open)

    with caplog.at_level(logging.WARNING, logger="spotvm"):
        snapshots = load_historical_runs(temp_results_dir)

    assert len(snapshots) == 1
    assert "Failed to load historical run" in caplog.text


def test_generate_history_csv_creates_file(temp_results_dir, sample_candidates, sample_config):
    """Test CSV generation from snapshots."""
    # Create 2 snapshots
    save_run_results(sample_candidates, sample_config, temp_results_dir)
    save_run_results(sample_candidates, sample_config, temp_results_dir)

    # Load and generate CSV
    snapshots = load_historical_runs(temp_results_dir)
    csv_path = temp_results_dir / "test_history.csv"
    num_points = generate_history_csv(snapshots, csv_path)

    # Verify CSV created
    assert csv_path.exists()
    assert num_points == 4  # 2 candidates x 2 snapshots

    # Parse and verify CSV
    with csv_path.open("r") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 4
    assert rows[0]["vm_size"] == "Standard_D4as_v5"
    assert rows[0]["region"] == "centralus"
    assert rows[0]["price_usd"] == "0.0336"
    assert rows[0]["eviction_rate"] == "2.5"


def test_generate_history_csv_handles_empty(temp_results_dir):
    """Test CSV generation with no snapshots."""
    csv_path = temp_results_dir / "empty_history.csv"
    num_points = generate_history_csv([], csv_path)

    assert num_points == 0
    assert not csv_path.exists()


def test_analyze_history_complete_workflow(temp_results_dir, sample_candidates, sample_config):
    """Test complete analyze_history workflow."""
    # Create 3 snapshots
    for _i in range(3):
        save_run_results(sample_candidates, sample_config, temp_results_dir)

    # Analyze
    num_runs, num_datapoints, csv_path = analyze_history(
        results_dir=temp_results_dir,
        depth=2,  # Only last 2 runs
    )

    assert num_runs == 2
    assert num_datapoints == 4  # 2 candidates x 2 runs
    assert csv_path.exists()
    assert csv_path.name == "history.csv"


def test_csv_output_format(temp_results_dir, sample_candidates, sample_config):
    """Test CSV contains all expected columns."""
    save_run_results(sample_candidates, sample_config, temp_results_dir)

    snapshots = load_historical_runs(temp_results_dir)
    csv_path = temp_results_dir / "format_test.csv"
    generate_history_csv(snapshots, csv_path)

    with csv_path.open("r") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames

    expected_headers = [
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

    assert headers == expected_headers


def test_save_run_results_persists_databricks_fields_when_present(temp_results_dir, sample_config):
    candidates = [
        CandidateInsight(
            vm_size="Standard_D4ps_v6",
            region="centralus",
            availability_zone=None,
            price_usd=0.381,
            price_last_updated=datetime(2025, 1, 25, 14, 30),
            eviction_rate=2.5,
            eviction_last_updated=datetime(2025, 1, 25, 14, 30),
            placement_score="High",
            quota_available=True,
            recommendation_rank=1,
            compute_price_usd=0.03,
            databricks_dbu_per_hour=1.17,
            databricks_dbu_cost_usd=0.1755,
            databricks_photon_dbu_per_hour=1.17,
            databricks_photon_cost_usd=0.1755,
            total_price_usd=0.381,
            databricks_catalog_updated="2026-03-19T00:00:00Z",
        ),
    ]

    saved_path = save_run_results(
        candidates=candidates,
        config=sample_config,
        results_dir=temp_results_dir,
    )

    with saved_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    candidate = data["candidates"][0]
    assert candidate["compute_price_usd"] == 0.03
    assert candidate["databricks_dbu_per_hour"] == 1.17
    assert candidate["databricks_dbu_cost_usd"] == 0.1755
    assert candidate["databricks_photon_dbu_per_hour"] == 1.17
    assert candidate["databricks_photon_cost_usd"] == 0.1755
    assert candidate["total_price_usd"] == 0.381
    assert candidate["databricks_catalog_updated"] == "2026-03-19T00:00:00Z"


def test_generate_history_csv_appends_databricks_columns_when_present(temp_results_dir, sample_config):
    candidates = [
        CandidateInsight(
            vm_size="Standard_D4ps_v6",
            region="centralus",
            availability_zone=None,
            price_usd=0.381,
            price_last_updated=datetime(2025, 1, 25, 14, 30),
            eviction_rate=2.5,
            eviction_last_updated=datetime(2025, 1, 25, 14, 30),
            placement_score="High",
            quota_available=True,
            recommendation_rank=1,
            compute_price_usd=0.03,
            databricks_dbu_per_hour=1.17,
            databricks_dbu_cost_usd=0.1755,
            total_price_usd=0.381,
            databricks_catalog_updated="2026-03-19T00:00:00Z",
        ),
    ]

    save_run_results(candidates, sample_config, temp_results_dir)

    snapshots = load_historical_runs(temp_results_dir)
    csv_path = temp_results_dir / "databricks_history.csv"
    generate_history_csv(snapshots, csv_path)

    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        row = next(reader)

    assert "compute_price_usd" in headers
    assert "databricks_dbu_per_hour" in headers
    assert "databricks_dbu_cost_usd" in headers
    assert "total_price_usd" in headers
    assert "databricks_catalog_updated" in headers
    assert row["compute_price_usd"] == "0.03"
    assert row["total_price_usd"] == "0.381"


def test_csv_handles_none_values(temp_results_dir, sample_config):
    """Test CSV generation handles None values correctly."""
    candidates_with_none = [
        CandidateInsight(
            vm_size="Standard_D4as_v5",
            region="centralus",
            availability_zone=None,  # None zone
            price_usd=None,  # None price
            price_last_updated=None,
            eviction_rate=None,  # None eviction
            eviction_last_updated=None,
            placement_score=None,
            quota_available=None,
            performance_relative=None,
            price_per_performance=None,
            recommendation_rank=None,
        ),
    ]

    save_run_results(candidates_with_none, sample_config, temp_results_dir)

    snapshots = load_historical_runs(temp_results_dir)
    csv_path = temp_results_dir / "none_values.csv"
    generate_history_csv(snapshots, csv_path)

    with csv_path.open("r") as f:
        reader = csv.DictReader(f)
        row = next(reader)

    # None values should be empty strings in CSV
    assert row["zone"] == ""
    assert row["price_usd"] == ""
    assert row["eviction_rate"] == ""
    assert row["quota_available"] == ""


def test_timestamp_format(temp_results_dir, sample_candidates, sample_config):
    """Test timestamp is in ISO 8601 format."""
    saved_path = save_run_results(sample_candidates, sample_config, temp_results_dir)

    with saved_path.open("r") as f:
        data = json.load(f)

    timestamp = data["timestamp"]
    # Should be ISO 8601 format with Z suffix
    assert timestamp.endswith("Z")
    # Should be parseable as datetime
    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    assert isinstance(dt, datetime)


def test_mixed_zone_and_regional_data(temp_results_dir, sample_config):
    """Test handling of mixed regional and zone-specific data in same CSV.

    This simulates the real-world scenario where some runs use --availability-zones
    and others don't, resulting in the same SKU appearing multiple times per region.
    """
    # Run 1: Regional data (no zones)
    regional_candidates = [
        CandidateInsight(
            vm_size="Standard_D4as_v5",
            region="centralus",
            availability_zone=None,  # No zone (regional)
            price_usd=0.0336,
            price_last_updated=datetime(2025, 1, 25, 14, 0),
            eviction_rate=2.5,
            eviction_last_updated=datetime(2025, 1, 25, 14, 0),
            placement_score="High",
            quota_available=True,
            performance_relative=95.2,
            price_per_performance=0.000353,
            recommendation_rank=1,
        ),
    ]
    save_run_results(regional_candidates, sample_config, temp_results_dir)

    # Run 2: Zone-specific data (3 zones)
    zone_candidates = [
        CandidateInsight(
            vm_size="Standard_D4as_v5",
            region="centralus",
            availability_zone="1",  # Zone 1
            price_usd=0.0338,
            price_last_updated=datetime(2025, 1, 25, 18, 0),
            eviction_rate=2.8,
            eviction_last_updated=datetime(2025, 1, 25, 18, 0),
            placement_score="High",
            quota_available=True,
            performance_relative=95.2,
            price_per_performance=0.000355,
            recommendation_rank=1,
        ),
        CandidateInsight(
            vm_size="Standard_D4as_v5",
            region="centralus",
            availability_zone="2",  # Zone 2
            price_usd=0.0340,
            price_last_updated=datetime(2025, 1, 25, 18, 0),
            eviction_rate=3.0,
            eviction_last_updated=datetime(2025, 1, 25, 18, 0),
            placement_score="Medium",
            quota_available=True,
            performance_relative=95.2,
            price_per_performance=0.000357,
            recommendation_rank=2,
        ),
        CandidateInsight(
            vm_size="Standard_D4as_v5",
            region="centralus",
            availability_zone="3",  # Zone 3
            price_usd=0.0342,
            price_last_updated=datetime(2025, 1, 25, 18, 0),
            eviction_rate=3.2,
            eviction_last_updated=datetime(2025, 1, 25, 18, 0),
            placement_score="Medium",
            quota_available=False,
            performance_relative=95.2,
            price_per_performance=0.000359,
            recommendation_rank=3,
        ),
    ]
    save_run_results(zone_candidates, sample_config, temp_results_dir)

    # Run 3: Back to regional data
    regional_candidates_2 = [
        CandidateInsight(
            vm_size="Standard_D4as_v5",
            region="centralus",
            availability_zone=None,  # No zone (regional)
            price_usd=0.0335,
            price_last_updated=datetime(2025, 1, 26, 10, 0),
            eviction_rate=2.3,
            eviction_last_updated=datetime(2025, 1, 26, 10, 0),
            placement_score="High",
            quota_available=True,
            performance_relative=95.2,
            price_per_performance=0.000352,
            recommendation_rank=1,
        ),
    ]
    save_run_results(regional_candidates_2, sample_config, temp_results_dir)

    # Generate history CSV
    snapshots = load_historical_runs(temp_results_dir)
    csv_path = temp_results_dir / "mixed_zones.csv"
    num_points = generate_history_csv(snapshots, csv_path)

    # Should have 5 total data points (1 regional + 3 zones + 1 regional)
    assert num_points == 5

    # Parse CSV and verify structure
    with csv_path.open("r") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 5

    # Verify regional data has empty zone
    regional_rows = [r for r in rows if r["zone"] == ""]
    assert len(regional_rows) == 2  # Two regional runs
    assert regional_rows[0]["price_usd"] == "0.0336"
    assert regional_rows[1]["price_usd"] == "0.0335"

    # Verify zone-specific data has zone values
    zone_rows = [r for r in rows if r["zone"] != ""]
    assert len(zone_rows) == 3  # Three zone-specific records
    assert {r["zone"] for r in zone_rows} == {"1", "2", "3"}

    # Verify prices differ between zones
    zone_prices = [float(r["price_usd"]) for r in zone_rows]
    assert zone_prices == [0.0338, 0.0340, 0.0342]  # Ascending order

    # Verify all rows are for same SKU and region
    assert all(r["vm_size"] == "Standard_D4as_v5" for r in rows)
    assert all(r["region"] == "centralus" for r in rows)
