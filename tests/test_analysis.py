from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from spotvm.analysis import enrich_with_databricks_cost, merge_datasets, rank_candidates, summarize_top_candidates
from spotvm.databricks_catalog import DatabricksCatalogError
from spotvm.models import CandidateInsight, HistoricalMetrics, PlacementScoreResult


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


def test_merge_datasets_keeps_distinct_zone_candidates_for_same_sku_and_region():
    placement_scores = [
        PlacementScoreResult(
            region="eastus",
            vm_size="Standard_D4as_v5",
            placement_score="High",
            quota_available=True,
            availability_zone="1",
        ),
        PlacementScoreResult(
            region="eastus",
            vm_size="Standard_D4as_v5",
            placement_score="Medium",
            quota_available=False,
            availability_zone="2",
        ),
    ]
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

    merged = merge_datasets(placement_scores, historical_metrics)

    assert [(candidate.availability_zone, candidate.placement_score) for candidate in merged] == [
        ("1", "High"),
        ("2", "Medium"),
    ]
    assert all(candidate.price_usd == 0.12 for candidate in merged)


def test_merge_datasets_normalizes_casing_via_lookup_keys_for_placement_only_rows():
    placement_scores = [
        PlacementScoreResult(
            region="EastUS",
            vm_size="Standard_D4as_v5",
            placement_score="High",
            quota_available=True,
        )
    ]

    [candidate] = merge_datasets(placement_scores, [])

    assert candidate.region == "eastus"
    assert candidate.vm_size == "standard_d4as_v5"


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


def test_enrich_with_databricks_cost_populates_cost_fields(monkeypatch):
    candidate = CandidateInsight(
        region="centralus",
        vm_size="Standard_D4ds_v5",
        placement_score=None,
        quota_available=None,
        price_usd=0.0471,
        price_last_updated=None,
        eviction_rate=5.0,
        eviction_last_updated=None,
    )

    monkeypatch.setattr(
        "spotvm.analysis.load_catalog",
        lambda: SimpleNamespace(
            captured_at="2026-03-19T00:00:00Z",
            pricing_profile=SimpleNamespace(dbu_unit_price_usd=0.15),
        ),
    )
    monkeypatch.setattr(
        "spotvm.analysis.lookup_azure_node_type_pricing",
        lambda _sku: SimpleNamespace(dbu_per_hour=1.0, photon_capable=True),
    )

    [enriched] = enrich_with_databricks_cost([candidate], include_photon=False)

    assert enriched.price_usd == 0.0471
    assert enriched.compute_price_usd == 0.0471
    assert enriched.databricks_dbu_per_hour == 1.0
    assert enriched.databricks_dbu_cost_usd == 0.15
    assert enriched.total_price_usd == 0.1971
    assert enriched.databricks_catalog_updated == "2026-03-19T00:00:00Z"


def test_enrich_with_databricks_cost_adds_jobs_photon_surcharge(monkeypatch):
    candidate = CandidateInsight(
        region="centralus",
        vm_size="Standard_D4ds_v5",
        placement_score=None,
        quota_available=None,
        price_usd=0.0471,
        price_last_updated=None,
        eviction_rate=5.0,
        eviction_last_updated=None,
    )

    monkeypatch.setattr(
        "spotvm.analysis.load_catalog",
        lambda: SimpleNamespace(
            captured_at="2026-03-19T00:00:00Z",
            pricing_profile=SimpleNamespace(dbu_unit_price_usd=0.15),
        ),
    )
    monkeypatch.setattr(
        "spotvm.analysis.lookup_azure_node_type_pricing",
        lambda _sku: SimpleNamespace(dbu_per_hour=1.0, photon_capable=True),
    )

    [enriched] = enrich_with_databricks_cost([candidate], include_photon=True)

    assert enriched.databricks_photon_dbu_per_hour == 2.5
    assert enriched.databricks_photon_cost_usd == pytest.approx(0.375)
    assert enriched.total_price_usd == pytest.approx(0.4221)


def test_enrich_with_databricks_cost_keeps_unmatched_sku_without_overlay(monkeypatch):
    candidate = CandidateInsight(
        region="centralus",
        vm_size="Standard_Unknown",
        placement_score=None,
        quota_available=None,
        price_usd=0.0471,
        price_last_updated=None,
        eviction_rate=5.0,
        eviction_last_updated=None,
    )

    monkeypatch.setattr(
        "spotvm.analysis.load_catalog",
        lambda: SimpleNamespace(
            captured_at="2026-03-19T00:00:00Z",
            pricing_profile=SimpleNamespace(dbu_unit_price_usd=0.15),
        ),
    )
    monkeypatch.setattr("spotvm.analysis.lookup_azure_node_type_pricing", lambda _sku: None)

    [enriched] = enrich_with_databricks_cost([candidate], include_photon=False)

    assert enriched.price_usd == 0.0471
    assert enriched.compute_price_usd == 0.0471
    assert enriched.databricks_dbu_per_hour is None
    assert enriched.total_price_usd is None


def test_enrich_with_databricks_cost_preserves_none_compute_price(monkeypatch):
    candidate = CandidateInsight(
        region="centralus",
        vm_size="Standard_D4ds_v5",
        placement_score=None,
        quota_available=None,
        price_usd=None,
        price_last_updated=None,
        eviction_rate=5.0,
        eviction_last_updated=None,
    )

    monkeypatch.setattr(
        "spotvm.analysis.load_catalog",
        lambda: SimpleNamespace(
            captured_at="2026-03-19T00:00:00Z",
            pricing_profile=SimpleNamespace(dbu_unit_price_usd=0.15),
        ),
    )
    monkeypatch.setattr(
        "spotvm.analysis.lookup_azure_node_type_pricing",
        lambda _sku: SimpleNamespace(dbu_per_hour=1.0, photon_capable=True),
    )

    [enriched] = enrich_with_databricks_cost([candidate], include_photon=False)

    assert enriched.price_usd is None
    assert enriched.compute_price_usd is None
    assert enriched.databricks_dbu_per_hour == 1.0
    assert enriched.databricks_dbu_cost_usd == 0.15
    assert enriched.total_price_usd is None


def test_enrich_with_databricks_cost_raises_when_catalog_loading_fails(monkeypatch):
    candidate = CandidateInsight(
        region="centralus",
        vm_size="Standard_D4ds_v5",
        placement_score=None,
        quota_available=None,
        price_usd=0.0471,
        price_last_updated=None,
        eviction_rate=5.0,
        eviction_last_updated=None,
    )

    monkeypatch.setattr(
        "spotvm.analysis.load_catalog",
        lambda: (_ for _ in ()).throw(DatabricksCatalogError("broken catalog")),
    )

    with pytest.raises(DatabricksCatalogError, match="broken catalog"):
        enrich_with_databricks_cost([candidate], include_photon=False)
