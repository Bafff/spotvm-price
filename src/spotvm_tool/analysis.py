from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from .models import CandidateInsight, HistoricalMetrics, PlacementScoreResult
from .vm_specs import calculate_relative_performance

PLACEMENT_ORDER = {"high": 3, "medium": 2, "low": 1}


def merge_datasets(
    placement_scores: Iterable[PlacementScoreResult],
    historical_metrics: Iterable[HistoricalMetrics],
) -> List[CandidateInsight]:
    """Combine placement and historical metrics per SKU/region."""

    placement_map: Dict[Tuple[str, str, Optional[str]], PlacementScoreResult] = {}
    for entry in placement_scores:
        key = (
            (entry.region or "").lower(),
            (entry.vm_size or "").lower(),
            (entry.availability_zone or "").lower() if entry.availability_zone else None,
        )
        placement_map[key] = entry

    metrics_map: Dict[Tuple[str, str], HistoricalMetrics] = {}
    for entry in historical_metrics:
        key = ((entry.region or "").lower(), (entry.vm_size or "").lower())
        metrics_map[key] = entry

    keys = set(metrics_map.keys())
    keys.update((k[0], k[1]) for k in placement_map.keys())

    combined: List[CandidateInsight] = []
    for region_key, sku_key in sorted(keys):
        matching_placement_entries = [
            value
            for key, value in placement_map.items()
            if key[0] == region_key and key[1] == sku_key
        ]
        if not matching_placement_entries:
            # Create a synthetic placement entry so knowledge of historical data still surfaces.
            matching_placement_entries = [
                PlacementScoreResult(
                    region=metrics_map[(region_key, sku_key)].region
                    if (region_key, sku_key) in metrics_map
                    else region_key,
                    vm_size=metrics_map[(region_key, sku_key)].vm_size
                    if (region_key, sku_key) in metrics_map
                    else sku_key,
                    placement_score=None,
                    quota_available=None,
                )
            ]

        metrics = metrics_map.get((region_key, sku_key))
        for entry in matching_placement_entries:
            combined.append(
                CandidateInsight(
                    region=entry.region or metrics.region if metrics else region_key,
                    vm_size=entry.vm_size or metrics.vm_size if metrics else sku_key,
                    placement_score=entry.placement_score,
                    quota_available=entry.quota_available,
                    price_usd=metrics.price_usd if metrics else None,
                    price_last_updated=metrics.price_last_updated if metrics else None,
                    eviction_rate=metrics.eviction_rate if metrics else None,
                    eviction_last_updated=metrics.eviction_last_updated if metrics else None,
                    availability_zone=entry.availability_zone,
                    notes=entry.error_detail,
                )
            )
    return combined


def rank_candidates(candidates: List[CandidateInsight]) -> List[CandidateInsight]:
    def sort_key(item: CandidateInsight) -> tuple:
        score_rank = PLACEMENT_ORDER.get(
            (item.placement_score or "").lower(),
            0,
        )
        eviction = item.eviction_rate if item.eviction_rate is not None else float("inf")

        # Use price/performance if available (better value), otherwise use raw price
        if item.price_per_performance is not None:
            price_metric = item.price_per_performance
        else:
            price_metric = item.price_usd if item.price_usd is not None else float("inf")

        return (-score_rank, eviction, price_metric)

    ranked = sorted(candidates, key=sort_key)
    for idx, item in enumerate(ranked, 1):
        item.recommendation_rank = idx
    return ranked


def enrich_with_performance(
    candidates: List[CandidateInsight],
    baseline_sku: Optional[str] = None,
) -> List[CandidateInsight]:
    """Calculate performance metrics relative to baseline SKU.

    Args:
        candidates: List of candidate insights
        baseline_sku: SKU to use as 100% baseline. If None, no performance calculation.

    Returns:
        Same list with performance_relative and price_per_performance populated
    """
    if not baseline_sku:
        return candidates

    for candidate in candidates:
        # Calculate relative performance
        perf = calculate_relative_performance(candidate.vm_size, baseline_sku)
        candidate.performance_relative = perf

        # Calculate price per performance unit
        if perf and perf > 0 and candidate.price_usd:
            # Price per 1% of baseline performance
            candidate.price_per_performance = candidate.price_usd / perf

    return candidates


def summarize_top_candidates(
    candidates: List[CandidateInsight],
    limit: int = 3,
) -> List[str]:
    summary = []
    for item in candidates[:limit]:
        parts = [
            f"#{item.recommendation_rank} {item.vm_size} in {item.region}",
        ]
        if item.availability_zone:
            parts.append(f"zone {item.availability_zone}")
        if item.placement_score:
            parts.append(f"placement score {item.placement_score}")
        if item.eviction_rate is not None:
            parts.append(f"eviction {item.eviction_rate:.1f}%")
        if item.performance_relative is not None:
            parts.append(f"perf {item.performance_relative:.0f}%")
        if item.price_usd is not None:
            parts.append(f"${item.price_usd:.4f}/hr")
        summary.append("; ".join(parts))
    return summary
