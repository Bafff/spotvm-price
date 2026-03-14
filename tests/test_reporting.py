import csv
from datetime import datetime

from spotvm import reporting
from spotvm.models import CandidateInsight
from spotvm.reporting import (
    _colorize_eviction,
    _colorize_placement,
    _strip_ansi,
    export_to_csv,
    render_table,
)

COLOR = lambda: reporting.RenderOptions(colors_enabled=True)
NO_COLOR = lambda: reporting.RenderOptions(colors_enabled=False)


def test_render_table_formats_columns():
    candidates = [
        CandidateInsight(
            region="eastus",
            vm_size="Standard_D2s_v4",
            placement_score="High",
            quota_available=True,
            price_usd=0.0456,
            price_last_updated=datetime(2025, 10, 24, 12, 0),
            eviction_rate=3.2,
            eviction_last_updated=datetime(2025, 10, 20, 8, 0),
            recommendation_rank=1,
        ),
        CandidateInsight(
            region="westus",
            vm_size="Standard_D4s_v4",
            placement_score="Medium",
            quota_available=False,
            price_usd=None,
            price_last_updated=None,
            eviction_rate=None,
            eviction_last_updated=None,
            availability_zone="2",
            recommendation_rank=2,
            notes="Data not found",
        ),
    ]

    table = render_table(candidates, render_options=NO_COLOR())

    assert "eastus" in table
    assert "Standard_D4s_v4" in table
    assert "Data not found" in table
    assert table.count("\n") > 2


def test_render_table_shortens_heuristic_performance_note():
    candidates = [
        CandidateInsight(
            region="eastus",
            vm_size="Standard_D4s_v4",
            placement_score=None,
            quota_available=None,
            price_usd=0.0456,
            price_last_updated=datetime(2025, 10, 24, 12, 0),
            eviction_rate=3.2,
            eviction_last_updated=datetime(2025, 10, 20, 8, 0),
            recommendation_rank=1,
            performance_relative=100.0,
            price_per_performance=0.000456,
            performance_basis="heuristic",
            performance_note="Perf % and Price/Perf use the vCPU/RAM heuristic because CoreMark data is unavailable for this comparison.",
        ),
    ]

    table = render_table(candidates, render_options=NO_COLOR())

    assert "Heuristic perf*" in table
    assert "vCPU/RAM heuristic because" not in table


def test_export_to_csv(tmp_path):
    """Test CSV export functionality."""
    candidates = [
        CandidateInsight(
            region="eastus",
            vm_size="Standard_D2s_v4",
            placement_score="High",
            quota_available=True,
            price_usd=0.0456,
            price_last_updated=datetime(2025, 10, 24, 12, 0),
            eviction_rate=3.2,
            eviction_last_updated=datetime(2025, 10, 20, 8, 0),
            recommendation_rank=1,
            performance_relative=100.0,
            price_per_performance=0.000456,
        ),
        CandidateInsight(
            region="westus",
            vm_size="Standard_D4s_v4",
            placement_score="Medium",
            quota_available=False,
            price_usd=None,
            price_last_updated=None,
            eviction_rate=None,
            eviction_last_updated=None,
            availability_zone="2",
            recommendation_rank=2,
            notes="Data not found",
        ),
    ]

    csv_path = tmp_path / "test_export.csv"
    export_to_csv(candidates, csv_path)

    # Verify file was created
    assert csv_path.exists()

    # Read and verify CSV contents
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Verify header row
    assert len(rows) == 2

    # Verify first row data
    row1 = rows[0]
    assert row1["Rank"] == "1"
    assert row1["Region"] == "eastus"
    assert row1["VM Size"] == "Standard_D2s_v4"
    assert row1["Placement Score"] == "High"
    assert row1["Quota Available"] == "Yes"
    assert row1["Price (USD/hr)"] == "0.0456"
    assert row1["Eviction Rate (%)"] == "3.2"
    assert row1["Performance (%)"] == "100"
    assert row1["Price per Performance"] == "0.000456"

    # Verify second row data (with missing values)
    row2 = rows[1]
    assert row2["Rank"] == "2"
    assert row2["Region"] == "westus"
    assert row2["Availability Zone"] == "2"
    assert row2["Quota Available"] == "No"
    assert row2["Price (USD/hr)"] == ""  # None should be empty string
    assert row2["Eviction Rate (%)"] == ""  # None should be empty string
    assert row2["Notes"] == "Data not found"


def test_colorize_eviction_rates():
    """Test eviction rate colorization with correct thresholds."""
    # Test different eviction rate ranges
    blue_result = _colorize_eviction(3.0, render_options=COLOR())  # <5% should be blue
    green_result = _colorize_eviction(7.0, render_options=COLOR())  # 5-10% should be green
    yellow_result = _colorize_eviction(12.0, render_options=COLOR())  # 10-15% should be yellow
    red_result = _colorize_eviction(20.0, render_options=COLOR())  # 15-24% should be red
    bright_red_result = _colorize_eviction(30.0, render_options=COLOR())  # >=25% should be bright red

    # Verify colors are applied (contains ANSI codes)
    assert "\x1b[" in blue_result  # Contains ANSI escape codes
    assert "\x1b[" in green_result
    assert "\x1b[" in yellow_result
    assert "\x1b[" in red_result
    assert "\x1b[" in bright_red_result

    # Verify percentage formatting is preserved
    assert "3.0%" in blue_result
    assert "7.0%" in green_result
    assert "12.0%" in yellow_result
    assert "20.0%" in red_result
    assert "30.0%" in bright_red_result

    # Test with colors disabled
    no_color_result = _colorize_eviction(12.0, render_options=NO_COLOR())
    assert "\x1b[" not in no_color_result  # No ANSI codes
    assert no_color_result == "12.0%"


def test_colorize_placement_scores():
    """Test placement score colorization."""
    high_result = _colorize_placement("High", render_options=COLOR())
    medium_result = _colorize_placement("Medium", render_options=COLOR())
    low_result = _colorize_placement("Low", render_options=COLOR())

    # Verify colors are applied
    assert "\x1b[" in high_result  # Green
    assert "\x1b[" in medium_result  # Yellow
    assert "\x1b[" in low_result  # Red

    # Verify text is preserved
    assert "High" in high_result
    assert "Medium" in medium_result
    assert "Low" in low_result


def test_strip_ansi():
    """Test ANSI escape code removal."""
    # Create colored string
    colored = "\x1b[31mRed Text\x1b[0m"
    stripped = _strip_ansi(colored)

    assert stripped == "Red Text"
    assert "\x1b[" not in stripped


def _candidate(**kwargs):
    """Create a CandidateInsight with sensible defaults for required fields."""
    defaults = {
        "region": "eastus",
        "vm_size": "Standard_D2s_v4",
        "placement_score": None,
        "quota_available": None,
        "price_usd": None,
        "price_last_updated": None,
        "eviction_rate": None,
        "eviction_last_updated": None,
    }
    defaults.update(kwargs)
    return CandidateInsight(**defaults)


def test_render_table_hides_placement_columns():
    """Placement and Quota columns are omitted when show_placement=False."""
    candidates = [
        _candidate(
            placement_score="High", quota_available=True, price_usd=0.05, eviction_rate=3.0, recommendation_rank=1
        ),
    ]
    table = render_table(candidates, show_placement=False, render_options=NO_COLOR())
    assert "Placement" not in table
    assert "Quota" not in table
    assert "Region" in table
    assert "Price" in table


def test_render_table_hides_baseline_columns():
    """Perf % and Price/Perf columns are omitted when show_baseline=False."""
    candidates = [
        _candidate(
            price_usd=0.05,
            eviction_rate=3.0,
            recommendation_rank=1,
            performance_relative=120.0,
            price_per_performance=0.0004,
        ),
    ]
    table_without = render_table(candidates, show_baseline=False, render_options=NO_COLOR())
    assert "Perf %" not in table_without
    assert "Price/Perf" not in table_without

    table_with = render_table(candidates, show_baseline=True, render_options=NO_COLOR())
    assert "Perf %" in table_with
    assert "Price/Perf" in table_with


def test_export_to_csv_hides_placement_columns(tmp_path):
    """CSV omits Placement Score and Quota Available when show_placement=False."""
    candidates = [
        _candidate(
            placement_score="High", quota_available=True, price_usd=0.05, eviction_rate=3.0, recommendation_rank=1
        ),
    ]
    csv_path = tmp_path / "no_placement.csv"
    export_to_csv(candidates, csv_path, show_placement=False)

    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames
        rows = list(reader)

    assert "Placement Score" not in headers
    assert "Quota Available" not in headers
    assert "Region" in headers
    assert len(rows) == 1


def test_export_to_csv_hides_baseline_columns(tmp_path):
    """CSV omits Performance and Price per Performance when show_baseline=False."""
    candidates = [
        _candidate(
            price_usd=0.05,
            eviction_rate=3.0,
            recommendation_rank=1,
            performance_relative=100.0,
            price_per_performance=0.0005,
        ),
    ]
    csv_path = tmp_path / "no_baseline.csv"
    export_to_csv(candidates, csv_path, show_baseline=False)

    with csv_path.open("r", encoding="utf-8") as f:
        headers = csv.DictReader(f).fieldnames

    assert "Performance (%)" not in headers
    assert "Price per Performance" not in headers


def test_render_table_auto_hides_empty_columns():
    """Columns where every data row is empty or '-' are auto-hidden."""
    candidates = [
        _candidate(price_usd=0.05, eviction_rate=3.0, recommendation_rank=1),
        _candidate(
            region="westus", vm_size="Standard_D4s_v4", price_usd=0.08, eviction_rate=5.0, recommendation_rank=2
        ),
    ]
    table = render_table(candidates, show_placement=False, show_baseline=False, render_options=NO_COLOR())
    # Zone should be auto-hidden (all empty)
    assert "Zone" not in table
    # Region should remain (has values)
    assert "eastus" in table
    assert "westus" in table


def test_render_table_keeps_column_with_one_value():
    """A column with at least one non-empty value is kept."""
    candidates = [
        _candidate(price_usd=0.05, eviction_rate=3.0, recommendation_rank=1, availability_zone="1"),
        _candidate(
            region="westus", vm_size="Standard_D4s_v4", price_usd=0.08, eviction_rate=5.0, recommendation_rank=2
        ),
    ]
    table = render_table(candidates, show_placement=False, show_baseline=False, render_options=NO_COLOR())
    assert "Zone" in table


def test_export_to_csv_keeps_empty_columns_for_stable_schema(tmp_path):
    """CSV keeps the configured schema even when current rows have blank values."""
    candidates = [
        _candidate(price_usd=0.05, eviction_rate=3.0, recommendation_rank=1),
    ]
    csv_path = tmp_path / "auto_hide.csv"
    export_to_csv(candidates, csv_path, show_placement=False, show_baseline=False)

    with csv_path.open("r", encoding="utf-8") as f:
        headers = csv.DictReader(f).fieldnames

    assert "Availability Zone" in headers
    assert "Notes" in headers
    assert "Region" in headers


def test_eviction_none_handling():
    """Test that None eviction rates are handled gracefully."""
    result = _colorize_eviction(None, render_options=NO_COLOR())
    assert result == "-"  # Default formatting for None


def test_render_table_plain_text_mode_is_explicit():
    candidates = [
        _candidate(
            placement_score="High",
            quota_available=True,
            price_usd=0.05,
            eviction_rate=3.0,
            recommendation_rank=1,
        ),
    ]

    table = render_table(candidates, render_options=NO_COLOR())

    assert "\x1b[" not in table
    assert "✅ Yes" not in table
    assert "Yes" in table
