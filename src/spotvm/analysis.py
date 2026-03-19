from __future__ import annotations

import logging
from collections.abc import Iterable

from .models import CandidateInsight, CPUArchitecture, HistoricalMetrics, PlacementScoreResult
from .vm_specs import (
    VMSpec,
    calculate_relative_performance_details,
    detect_cpu_architecture,
    get_vm_spec,
    matches_hardware_constraint,
)

logger = logging.getLogger("spotvm")

PLACEMENT_ORDER = {"high": 3, "medium": 2, "low": 1}
PlacementLookupKey = tuple[str, str, str | None]
MetricsLookupKey = tuple[str, str]
RankSortKey = tuple[int, float, float]


def merge_datasets(
    placement_scores: Iterable[PlacementScoreResult],
    historical_metrics: Iterable[HistoricalMetrics],
) -> list[CandidateInsight]:
    """Combine placement and historical metrics per SKU/region."""

    placement_map: dict[PlacementLookupKey, PlacementScoreResult] = {}
    for placement_entry in placement_scores:
        placement_map[_placement_key(placement_entry)] = placement_entry

    metrics_map: dict[MetricsLookupKey, HistoricalMetrics] = {}
    for historical_entry in historical_metrics:
        metrics_map[_metrics_key(historical_entry)] = historical_entry

    keys: set[MetricsLookupKey] = set(metrics_map)
    keys.update((k[0], k[1]) for k in placement_map)

    combined: list[CandidateInsight] = []
    for region_key, sku_key in sorted(keys):
        metrics = metrics_map.get((region_key, sku_key))
        for placement_entry in _matching_placement_entries(placement_map, metrics, region_key, sku_key):
            combined.append(_build_candidate_insight(placement_entry, metrics, region_key, sku_key))
    return combined


def rank_candidates(candidates: list[CandidateInsight]) -> list[CandidateInsight]:
    ranked = sorted(candidates, key=_rank_sort_key)
    for idx, item in enumerate(ranked, 1):
        item.recommendation_rank = idx
    return ranked


def enrich_with_performance(
    candidates: list[CandidateInsight],
    baseline_sku: str | None = None,
) -> list[CandidateInsight]:
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
        perf, basis = calculate_relative_performance_details(candidate.vm_size, baseline_sku)
        candidate.performance_relative = perf
        candidate.performance_basis = basis
        candidate.performance_note = None

        if basis == "heuristic":
            candidate.performance_note = (
                "Perf % and Price/Perf use the vCPU/RAM heuristic because CoreMark data "
                "is unavailable for this comparison."
            )

        # Calculate price per performance unit
        if perf and perf > 0 and candidate.price_usd:
            # Price per 1% of baseline performance
            candidate.price_per_performance = candidate.price_usd / perf
        else:
            candidate.price_per_performance = None

    return candidates


def enrich_with_coremark(
    candidates: list[CandidateInsight],
) -> list[CandidateInsight]:
    """Enrich candidates with CoreMark benchmark data.

    Adds CoreMark absolute score and per-vCPU efficiency metric from VM specifications.

    Args:
        candidates: List of candidate insights

    Returns:
        Same list with coremark_score and coremark_per_vcpu populated
    """
    for candidate in candidates:
        spec = get_vm_spec(candidate.vm_size)
        if spec:
            candidate.coremark_score = spec.coremark_score
            candidate.coremark_per_vcpu = spec.coremark_per_vcpu

    return candidates


def summarize_top_candidates(
    candidates: list[CandidateInsight],
    limit: int = 3,
) -> list[str]:
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


def filter_by_requirements(
    candidates: list[CandidateInsight],
    min_vcpu: int | None = None,
    min_ram: int | None = None,
    cpu_arch: CPUArchitecture | None = None,
    no_max_limit: bool = False,
) -> list[CandidateInsight]:
    """Filter candidates by hardware requirements (vCPU, RAM, CPU architecture).

    Removes candidates that don't meet minimum vCPU or RAM requirements,
    or don't match the requested CPU architecture.
    SKUs not found in VM_SPECIFICATIONS are kept with a warning for vCPU/RAM
    checks only when no_max_limit=True; otherwise bounded hardware filtering
    excludes them. Candidates with unknown architecture are excluded when
    cpu_arch is specified.

    Args:
        candidates: List of candidate insights to filter
        min_vcpu: Minimum vCPUs required (None = no filter)
        min_ram: Minimum RAM in GB required (None = no filter)
        cpu_arch: CPU architecture filter, "x64" or "arm" (None = no filter)
        no_max_limit: Disable the default bounded 3-tier window for min_vcpu/min_ram

    Returns:
        Filtered list of candidates meeting requirements
    """
    if min_vcpu is None and min_ram is None and cpu_arch is None:
        return candidates

    filtered = []
    filtered_count = 0

    for candidate in candidates:
        spec = get_vm_spec(candidate.vm_size)

        if not _matches_requested_architecture(candidate, cpu_arch):
            filtered_count += 1
            continue

        if not _matches_hardware_requirements(candidate, spec, min_vcpu, min_ram, no_max_limit):
            filtered_count += 1
            continue

        filtered.append(candidate)

    if filtered_count > 0:
        parts = _hardware_requirement_parts(min_vcpu, min_ram, cpu_arch)
        logger.info(
            f"Filtered out {filtered_count} candidate(s) not meeting hardware requirements ({', '.join(parts)})"
        )

    return filtered


def filter_by_cost(
    candidates: list[CandidateInsight],
    max_price: float | None = None,
    max_eviction: float | None = None,
    min_performance: float | None = None,
) -> list[CandidateInsight]:
    """Filter candidates by cost and performance constraints.

    Removes candidates that exceed maximum price, eviction rate, or don't
    meet minimum performance requirements.

    Args:
        candidates: List of candidate insights to filter
        max_price: Maximum price per hour in USD (None = no filter)
        max_eviction: Maximum eviction rate percentage (None = no filter)
        min_performance: Minimum performance relative to baseline % (None = no filter)

    Returns:
        Filtered list of candidates meeting cost constraints
    """
    if max_price is None and max_eviction is None and min_performance is None:
        return candidates

    filtered = []
    filtered_count = 0

    for candidate in candidates:
        filter_message = _cost_filter_message(candidate, max_price, max_eviction, min_performance)
        if filter_message is not None:
            logger.debug(filter_message)
            filtered_count += 1
            continue

        filtered.append(candidate)

    if filtered_count > 0:
        parts = _cost_constraint_parts(max_price, max_eviction, min_performance)
        logger.info(f"Filtered out {filtered_count} candidate(s) not meeting cost constraints ({', '.join(parts)})")

    return filtered


def _placement_key(placement_entry: PlacementScoreResult) -> PlacementLookupKey:
    return (
        (placement_entry.region or "").lower(),
        (placement_entry.vm_size or "").lower(),
        (placement_entry.availability_zone or "").lower() if placement_entry.availability_zone else None,
    )


def _metrics_key(historical_entry: HistoricalMetrics) -> MetricsLookupKey:
    return ((historical_entry.region or "").lower(), (historical_entry.vm_size or "").lower())


def _matching_placement_entries(
    placement_map: dict[PlacementLookupKey, PlacementScoreResult],
    metrics: HistoricalMetrics | None,
    region_key: str,
    sku_key: str,
) -> list[PlacementScoreResult]:
    matching_entries = [value for key, value in placement_map.items() if key[0] == region_key and key[1] == sku_key]
    if matching_entries:
        return matching_entries
    return [_synthetic_placement_entry(metrics, region_key, sku_key)]


def _synthetic_placement_entry(
    metrics: HistoricalMetrics | None,
    region_key: str,
    sku_key: str,
) -> PlacementScoreResult:
    return PlacementScoreResult(
        region=metrics.region if metrics else region_key,
        vm_size=metrics.vm_size if metrics else sku_key,
        placement_score=None,
        quota_available=None,
    )


def _build_candidate_insight(
    placement_entry: PlacementScoreResult,
    metrics: HistoricalMetrics | None,
    region_key: str,
    sku_key: str,
) -> CandidateInsight:
    vm_size = (placement_entry.vm_size or metrics.vm_size) if metrics else sku_key
    return CandidateInsight(
        region=(placement_entry.region or metrics.region) if metrics else region_key,
        vm_size=vm_size,
        placement_score=placement_entry.placement_score,
        quota_available=placement_entry.quota_available,
        price_usd=metrics.price_usd if metrics else None,
        price_last_updated=metrics.price_last_updated if metrics else None,
        eviction_rate=metrics.eviction_rate if metrics else None,
        eviction_last_updated=metrics.eviction_last_updated if metrics else None,
        availability_zone=placement_entry.availability_zone,
        notes=placement_entry.error_detail,
        cpu_arch=detect_cpu_architecture(vm_size) if vm_size else None,
    )


def _rank_sort_key(item: CandidateInsight) -> RankSortKey:
    score_rank = PLACEMENT_ORDER.get((item.placement_score or "").lower(), 0)
    eviction = item.eviction_rate if item.eviction_rate is not None else float("inf")
    if item.price_per_performance is not None:
        price_metric = item.price_per_performance
    else:
        price_metric = item.price_usd if item.price_usd is not None else float("inf")
    return (-score_rank, eviction, price_metric)


def _matches_requested_architecture(
    candidate: CandidateInsight,
    requested_arch: CPUArchitecture | None,
) -> bool:
    if not requested_arch:
        return True
    candidate_arch = candidate.cpu_arch
    if not candidate_arch and candidate.vm_size:
        candidate_arch = detect_cpu_architecture(candidate.vm_size)
    if not candidate_arch:
        logger.warning(f"Cannot determine architecture for {candidate.vm_size}, excluding from results")
        return False
    normalized_candidate_arch = _normalized_architecture(candidate_arch)
    if normalized_candidate_arch != requested_arch.lower():
        logger.debug(f"Filtered {candidate.vm_size}: arch {normalized_candidate_arch} != {requested_arch}")
        return False
    return True


def _normalized_architecture(candidate_arch: str) -> str:
    normalized_candidate_arch = candidate_arch.lower()
    if normalized_candidate_arch in ("intel", "amd"):
        return "x64"
    return normalized_candidate_arch


def _matches_hardware_requirements(
    candidate: CandidateInsight,
    spec: VMSpec | None,
    min_vcpu: int | None,
    min_ram: int | None,
    no_max_limit: bool,
) -> bool:
    if spec is None:
        return _allows_unknown_spec(candidate, min_vcpu, min_ram, no_max_limit)
    if not matches_hardware_constraint(
        spec.vcpus,
        min_vcpu,
        dimension="vcpu",
        no_max_limit=no_max_limit,
    ):
        logger.debug(f"Filtered {candidate.vm_size}: {spec.vcpus} vCPU does not match requested window")
        return False
    if not matches_hardware_constraint(
        spec.ram_gb,
        min_ram,
        dimension="ram",
        no_max_limit=no_max_limit,
    ):
        logger.debug(f"Filtered {candidate.vm_size}: {spec.ram_gb} GB RAM does not match requested window")
        return False
    return True


def _allows_unknown_spec(
    candidate: CandidateInsight,
    min_vcpu: int | None,
    min_ram: int | None,
    no_max_limit: bool,
) -> bool:
    if min_vcpu is None and min_ram is None:
        return True
    if no_max_limit:
        logger.warning(
            f"VM size {candidate.vm_size} not in specifications database, cannot verify vCPU/RAM requirements"
        )
        return True
    logger.warning(
        f"VM size {candidate.vm_size} not in specifications database, excluding from bounded hardware results"
    )
    return False


def _hardware_requirement_parts(
    min_vcpu: int | None,
    min_ram: int | None,
    cpu_arch: CPUArchitecture | None,
) -> list[str]:
    parts = []
    if min_vcpu is not None:
        parts.append(f"vCPU≥{min_vcpu}")
    if min_ram is not None:
        parts.append(f"RAM≥{min_ram} GB")
    if cpu_arch is not None:
        parts.append(f"arch={cpu_arch}")
    return parts


def _cost_filter_message(
    candidate: CandidateInsight,
    max_price: float | None,
    max_eviction: float | None,
    min_performance: float | None,
) -> str | None:
    if max_price is not None and candidate.price_usd is not None and candidate.price_usd > max_price:
        return (
            f"Filtered {candidate.vm_size} in {candidate.region}: price ${candidate.price_usd:.4f} > ${max_price} max"
        )
    if max_eviction is not None and candidate.eviction_rate is not None and candidate.eviction_rate > max_eviction:
        return (
            f"Filtered {candidate.vm_size} in {candidate.region}: "
            f"eviction {candidate.eviction_rate:.1f}% > {max_eviction}% max"
        )
    if (
        min_performance is not None
        and candidate.performance_relative is not None
        and candidate.performance_relative < min_performance
    ):
        return (
            f"Filtered {candidate.vm_size} in {candidate.region}: "
            f"performance {candidate.performance_relative:.0f}% < {min_performance}% min"
        )
    return None


def _cost_constraint_parts(
    max_price: float | None,
    max_eviction: float | None,
    min_performance: float | None,
) -> list[str]:
    parts = []
    if max_price is not None:
        parts.append(f"price<=${max_price}")
    if max_eviction is not None:
        parts.append(f"eviction<={max_eviction}%")
    if min_performance is not None:
        parts.append(f"performance>={min_performance}%")
    return parts
