import csv
from datetime import datetime
from pathlib import Path

from spotvm_tool.models import CandidateInsight
from spotvm_tool.reporting import (
    render_table,
    export_to_csv,
    _colorize_eviction,
    _colorize_placement,
    _strip_ansi,
    set_colors_enabled,
)


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

    table = render_table(candidates)

    assert "eastus" in table
    assert "Standard_D4s_v4" in table
    assert "Data not found" in table
    assert table.count("\n") > 2


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
    # Enable colors for testing
    set_colors_enabled(True)

    # Test different eviction rate ranges
    blue_result = _colorize_eviction(3.0)  # <5% should be blue
    green_result = _colorize_eviction(7.0)  # 5-10% should be green
    yellow_result = _colorize_eviction(12.0)  # 10-15% should be yellow
    red_result = _colorize_eviction(20.0)  # 15-24% should be red
    bright_red_result = _colorize_eviction(30.0)  # >=25% should be bright red

    # Verify colors are applied (contains ANSI codes)
    assert '\x1b[' in blue_result  # Contains ANSI escape codes
    assert '\x1b[' in green_result
    assert '\x1b[' in yellow_result
    assert '\x1b[' in red_result
    assert '\x1b[' in bright_red_result

    # Verify percentage formatting is preserved
    assert '3.0%' in blue_result
    assert '7.0%' in green_result
    assert '12.0%' in yellow_result
    assert '20.0%' in red_result
    assert '30.0%' in bright_red_result

    # Test with colors disabled
    set_colors_enabled(False)
    no_color_result = _colorize_eviction(12.0)
    assert '\x1b[' not in no_color_result  # No ANSI codes
    assert no_color_result == "12.0%"

    # Re-enable for other tests
    set_colors_enabled(True)


def test_colorize_placement_scores():
    """Test placement score colorization."""
    set_colors_enabled(True)

    high_result = _colorize_placement("High")
    medium_result = _colorize_placement("Medium")
    low_result = _colorize_placement("Low")

    # Verify colors are applied
    assert '\x1b[' in high_result  # Green
    assert '\x1b[' in medium_result  # Yellow
    assert '\x1b[' in low_result  # Red

    # Verify text is preserved
    assert 'High' in high_result
    assert 'Medium' in medium_result
    assert 'Low' in low_result


def test_strip_ansi():
    """Test ANSI escape code removal."""
    # Create colored string
    colored = "\x1b[31mRed Text\x1b[0m"
    stripped = _strip_ansi(colored)

    assert stripped == "Red Text"
    assert '\x1b[' not in stripped


def test_eviction_none_handling():
    """Test that None eviction rates are handled gracefully."""
    result = _colorize_eviction(None)
    assert result == "-"  # Default formatting for None
