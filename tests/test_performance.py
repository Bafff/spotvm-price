from __future__ import annotations

from datetime import datetime

import pytest

from spotvm_tool.analysis import enrich_with_performance
from spotvm_tool.models import CandidateInsight
from spotvm_tool.vm_specs import calculate_relative_performance


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
