from __future__ import annotations

from datetime import datetime

from spotvm.analysis import merge_datasets, rank_candidates, summarize_top_candidates
from spotvm.models import CandidateInsight, HistoricalMetrics


def test_merge_datasets_creates_synthetic_candidate_for_metrics_only_rows():
    historical_metrics = [
        HistoricalMetrics(
            region="eastus",
            vm_size="Standard_D4as_v5",
            price_usd=0.12,
            price_last_updated=datetime(2025, 1, 1, 12, 0),
            eviction_rate=4.0,
            eviction_last_updated=datetime(2025, 1, 1, 12, 0),
        )
    ]

    [candidate] = merge_datasets([], historical_metrics)

    assert candidate.region == "eastus"
    assert candidate.vm_size == "Standard_D4as_v5"
    assert candidate.placement_score is None
    assert candidate.price_usd == 0.12
    assert candidate.eviction_rate == 4.0
    assert candidate.cpu_arch == "x64"


def test_rank_candidates_prefers_price_per_performance_before_raw_price():
    candidates = [
        CandidateInsight(
            region="eastus",
            vm_size="Standard_D4as_v5",
            placement_score="High",
            quota_available=True,
            price_usd=0.20,
            price_last_updated=None,
            eviction_rate=2.0,
            eviction_last_updated=None,
            price_per_performance=0.0040,
        ),
        CandidateInsight(
            region="eastus",
            vm_size="Standard_D8as_v5",
            placement_score="High",
            quota_available=True,
            price_usd=0.18,
            price_last_updated=None,
            eviction_rate=2.0,
            eviction_last_updated=None,
            price_per_performance=0.0060,
        ),
    ]

    ranked = rank_candidates(candidates)

    assert [candidate.vm_size for candidate in ranked] == ["Standard_D4as_v5", "Standard_D8as_v5"]
    assert [candidate.recommendation_rank for candidate in ranked] == [1, 2]


def test_summarize_top_candidates_includes_zone_score_perf_and_price():
    candidates = [
        CandidateInsight(
            region="eastus",
            vm_size="Standard_D4as_v5",
            placement_score="High",
            quota_available=True,
            price_usd=0.1234,
            price_last_updated=None,
            eviction_rate=2.5,
            eviction_last_updated=None,
            availability_zone="1",
            recommendation_rank=1,
            performance_relative=115.0,
        )
    ]

    summary = summarize_top_candidates(candidates)

    assert summary == [
        "#1 Standard_D4as_v5 in eastus; zone 1; placement score High; eviction 2.5%; perf 115%; $0.1234/hr"
    ]
