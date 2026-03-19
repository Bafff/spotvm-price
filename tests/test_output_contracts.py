"""Output contract tests.

These tests freeze the external-facing schemas produced by the tool so that
any accidental key rename, column reorder, or field removal fails loudly.
They deliberately do not test values, only structure.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

from spotvm.cli import _build_report
from spotvm.history import RunSnapshot, generate_history_csv
from spotvm.reporting import CSV_COLUMNS, TABLE_COLUMNS, export_to_csv


def _make_candidate(**overrides):
    defaults = {
        "recommendation_rank": 1,
        "region": "centralus",
        "availability_zone": None,
        "vm_size": "Standard_D4s_v5",
        "cpu_arch": "x64",
        "placement_score": None,
        "quota_available": None,
        "price_usd": 0.08,
        "price_last_updated": datetime(2025, 1, 1, tzinfo=timezone.utc),
        "eviction_rate": 5.0,
        "eviction_last_updated": datetime(2025, 1, 1, tzinfo=timezone.utc),
        "performance_relative": 100.0,
        "price_per_performance": 0.0008,
        "performance_basis": "coremark",
        "performance_note": None,
        "coremark_score": 67114,
        "coremark_per_vcpu": 16778.5,
        "notes": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


_EXPECTED_REPORT_TOP_KEYS = {"generatedAt", "candidates"}
_EXPECTED_CANDIDATE_KEYS = {
    "rank",
    "region",
    "availabilityZone",
    "vmSize",
    "cpuArchitecture",
    "placementScore",
    "quotaAvailable",
    "priceUSDPerHour",
    "priceLastUpdated",
    "evictionRatePercent",
    "performanceRelativePercent",
    "pricePerPerformance",
    "performanceBasis",
    "performanceNote",
    "coremarkScore",
    "coremarkPerVCPU",
    "notes",
}


def test_build_report_top_level_keys():
    report = _build_report([_make_candidate()])
    assert set(report.keys()) == _EXPECTED_REPORT_TOP_KEYS


def test_build_report_candidate_keys():
    report = _build_report([_make_candidate()])
    assert len(report["candidates"]) == 1
    assert set(report["candidates"][0].keys()) == _EXPECTED_CANDIDATE_KEYS


def test_build_report_is_json_serializable():
    report = _build_report([_make_candidate()])
    json.dumps(report)


def test_build_report_uses_camel_case_keys():
    report = _build_report([_make_candidate()])
    candidate = report["candidates"][0]
    assert [key for key in candidate if "_" in key] == []


_EXPECTED_TABLE_COLUMNS = [
    "Rank",
    "Region",
    "Zone",
    "VM Size",
    "CPU",
    "Placement",
    "Quota",
    "Price (USD/hr)",
    "Eviction %",
    "Perf %",
    "Price/Perf",
    "CoreMark",
    "CM/vCPU",
    "Price Updated",
    "Notes",
]


def test_table_columns_are_stable():
    assert TABLE_COLUMNS == _EXPECTED_TABLE_COLUMNS


_EXPECTED_CSV_COLUMNS_FULL = [
    "Rank",
    "Region",
    "Availability Zone",
    "VM Size",
    "CPU Vendor",
    "Placement Score",
    "Quota Available",
    "Price (USD/hr)",
    "Eviction Rate (%)",
    "Performance (%)",
    "Price per Performance",
    "CoreMark Score",
    "CoreMark per vCPU",
    "Price Last Updated",
    "Notes",
]


def test_csv_columns_are_stable():
    assert CSV_COLUMNS == _EXPECTED_CSV_COLUMNS_FULL


def test_export_to_csv_writes_expected_headers(tmp_path):
    csv_path = tmp_path / "out.csv"
    export_to_csv([_make_candidate()], csv_path, show_placement=True, show_baseline=True)

    import csv as csv_module

    with csv_path.open(newline="", encoding="utf-8") as handle:
        headers = next(csv_module.reader(handle))

    assert headers == _EXPECTED_CSV_COLUMNS_FULL


def test_export_to_csv_omits_placement_columns_when_disabled(tmp_path):
    csv_path = tmp_path / "out.csv"
    export_to_csv([_make_candidate()], csv_path, show_placement=False, show_baseline=True)

    import csv as csv_module

    with csv_path.open(newline="", encoding="utf-8") as handle:
        headers = next(csv_module.reader(handle))

    assert "Placement Score" not in headers
    assert "Quota Available" not in headers
    assert "VM Size" in headers


def test_export_to_csv_omits_baseline_columns_when_disabled(tmp_path):
    csv_path = tmp_path / "out.csv"
    export_to_csv([_make_candidate()], csv_path, show_placement=True, show_baseline=False)

    import csv as csv_module

    with csv_path.open(newline="", encoding="utf-8") as handle:
        headers = next(csv_module.reader(handle))

    assert "Performance (%)" not in headers
    assert "Price per Performance" not in headers
    assert "VM Size" in headers


_EXPECTED_HISTORY_FIELDNAMES = [
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


def test_generate_history_csv_writes_expected_fieldnames(tmp_path):
    snapshot = RunSnapshot(
        timestamp="2025-01-01T00:00:00Z",
        config={"regions": ["centralus"], "sizes": ["Standard_D4s_v5"]},
        candidates=[
            {
                "vm_size": "Standard_D4s_v5",
                "region": "centralus",
                "availability_zone": None,
                "price_usd": 0.08,
                "eviction_rate": 5.0,
                "placement_score": None,
                "quota_available": None,
                "performance_relative": 100.0,
                "price_per_performance": 0.0008,
                "recommendation_rank": 1,
            }
        ],
    )
    output_path = tmp_path / "history.csv"
    generate_history_csv([snapshot], output_path)

    import csv as csv_module

    with output_path.open(newline="", encoding="utf-8") as handle:
        reader = csv_module.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])

    assert fieldnames == _EXPECTED_HISTORY_FIELDNAMES
