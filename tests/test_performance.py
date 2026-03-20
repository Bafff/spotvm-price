from __future__ import annotations

from datetime import datetime

import pytest

from spotvm.analysis import enrich_with_performance
from spotvm.models import CandidateInsight
from spotvm.vm_specs import calculate_relative_performance, calculate_relative_performance_details


def test_calculate_relative_performance_prefers_coremark_when_both_skus_have_it():
    perf = calculate_relative_performance("Standard_D4as_v5", "Standard_D4s_v5")

    assert perf == pytest.approx((72_928 / 67_114) * 100.0, rel=1e-4)
    assert perf > 100.0


def test_enrich_with_performance_marks_heuristic_fallback_when_coremark_missing():
    candidate = CandidateInsight(
        region="centralus",
        vm_size="Standard_D4s_v4",
        placement_score=None,
        quota_available=None,
        price_usd=0.05,
        price_last_updated=datetime(2025, 1, 25, 14, 0),
        eviction_rate=2.0,
        eviction_last_updated=datetime(2025, 1, 25, 14, 0),
    )

    [enriched] = enrich_with_performance([candidate], baseline_sku="Standard_D4s_v5")

    assert enriched.performance_relative == pytest.approx(100.0)
    assert enriched.price_per_performance == pytest.approx(0.0005)
    assert enriched.performance_basis == "heuristic"
    assert "CoreMark" in enriched.performance_note


def test_enrich_with_performance_uses_effective_total_price_for_price_performance():
    candidate = CandidateInsight(
        region="centralus",
        vm_size="Standard_D4s_v4",
        placement_score=None,
        quota_available=None,
        price_usd=0.05,
        total_price_usd=0.20,
        price_last_updated=datetime(2025, 1, 25, 14, 0),
        eviction_rate=2.0,
        eviction_last_updated=datetime(2025, 1, 25, 14, 0),
    )

    [enriched] = enrich_with_performance([candidate], baseline_sku="Standard_D4s_v5")

    assert enriched.performance_relative == pytest.approx(100.0)
    assert enriched.price_per_performance == pytest.approx(0.0020)


def test_calculate_relative_performance_details_prefers_coremark_basis():
    perf, basis = calculate_relative_performance_details("Standard_D4as_v5", "Standard_D4s_v5")

    assert perf == pytest.approx((72_928 / 67_114) * 100.0, rel=1e-4)
    assert basis == "coremark"


def test_calculate_relative_performance_details_falls_back_to_heuristic_basis():
    perf, basis = calculate_relative_performance_details("Standard_D4s_v4", "Standard_D4s_v5")

    assert perf == pytest.approx(100.0)
    assert basis == "heuristic"


def test_calculate_relative_performance_details_returns_none_for_unknown_sku():
    assert calculate_relative_performance_details("Standard_UnknownSKU_v99", "Standard_D4s_v5") == (None, None)
