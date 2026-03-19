from __future__ import annotations

from datetime import datetime, timezone

from spotvm.models import CandidateInsight
from spotvm.projection import project_for_history, project_for_report


def test_project_for_history_returns_expected_keys():
    candidate = CandidateInsight(
        region="centralus",
        vm_size="Standard_D4s_v5",
        placement_score="High",
        quota_available=True,
        price_usd=0.08,
        price_last_updated=datetime(2025, 1, 1, tzinfo=timezone.utc),
        eviction_rate=5.0,
        eviction_last_updated=datetime(2025, 1, 1, tzinfo=timezone.utc),
        availability_zone="1",
        recommendation_rank=1,
        notes="test note",
        performance_relative=100.0,
        price_per_performance=0.0008,
    )

    projected = project_for_history(candidate)

    assert set(projected) == {
        "vm_size",
        "region",
        "availability_zone",
        "price_usd",
        "eviction_rate",
        "placement_score",
        "quota_available",
        "performance_relative",
        "price_per_performance",
        "recommendation_rank",
        "notes",
    }


def test_project_for_report_returns_expected_keys():
    candidate = CandidateInsight(
        region="centralus",
        vm_size="Standard_D4s_v5",
        placement_score="High",
        quota_available=True,
        price_usd=0.08,
        price_last_updated=datetime(2025, 1, 1, tzinfo=timezone.utc),
        eviction_rate=5.0,
        eviction_last_updated=datetime(2025, 1, 1, tzinfo=timezone.utc),
        availability_zone="1",
        recommendation_rank=1,
        notes="test note",
        performance_relative=100.0,
        price_per_performance=0.0008,
        performance_basis="coremark",
        performance_note="note",
        cpu_arch="x64",
        coremark_score=67114,
        coremark_per_vcpu=16778.5,
    )

    projected = project_for_report(
        candidate, lambda value: value.isoformat() if value else None, lambda *parts: "; ".join(p for p in parts if p)
    )

    assert set(projected) == {
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


def test_project_for_report_uses_total_price_when_databricks_fields_present():
    candidate = CandidateInsight(
        region="centralus",
        vm_size="Standard_D4s_v5",
        placement_score="High",
        quota_available=True,
        price_usd=0.03,
        price_last_updated=datetime(2025, 1, 1, tzinfo=timezone.utc),
        eviction_rate=5.0,
        eviction_last_updated=datetime(2025, 1, 1, tzinfo=timezone.utc),
        availability_zone="1",
        recommendation_rank=1,
        cpu_arch="x64",
        compute_price_usd=0.03,
        databricks_dbu_per_hour=1.17,
        databricks_dbu_cost_usd=0.1755,
        total_price_usd=0.2055,
        databricks_catalog_updated=datetime(2026, 3, 19, tzinfo=timezone.utc),
    )

    projected = project_for_report(
        candidate,
        lambda value: value.isoformat() if value else None,
        lambda *parts: "; ".join(p for p in parts if p),
        show_databricks=True,
    )

    assert projected["priceUSDPerHour"] == 0.2055
    assert projected["computePriceUSDPerHour"] == 0.03
    assert projected["totalPriceUSDPerHour"] == 0.2055


def test_project_for_history_serializes_databricks_catalog_updated_datetime():
    candidate = CandidateInsight(
        region="centralus",
        vm_size="Standard_D4s_v5",
        placement_score="High",
        quota_available=True,
        price_usd=0.03,
        price_last_updated=datetime(2025, 1, 1, tzinfo=timezone.utc),
        eviction_rate=5.0,
        eviction_last_updated=datetime(2025, 1, 1, tzinfo=timezone.utc),
        databricks_catalog_updated=datetime(2026, 3, 19, tzinfo=timezone.utc),
    )

    projected = project_for_history(candidate)

    assert projected["databricks_catalog_updated"] == "2026-03-19T00:00:00+00:00"
