from __future__ import annotations

import logging
from collections.abc import Iterable

from .models import CandidateInsight, CPUArchitecture, HistoricalMetrics, PlacementScoreResult
from .vm_specs import (
    calculate_relative_performance_details,
    detect_cpu_architecture,
    get_vm_spec,
    matches_hardware_constraint,
)

logger = logging.getLogger("spotvm")

PLACEMENT_ORDER = {"high": 3, "medium": 2, "low": 1}


def merge_datasets(
    placement_scores: Iterable[PlacementScoreResult],
    historical_metrics: Iterable[HistoricalMetrics],
) -> list[CandidateInsight]:
    """Combine placement and historical metrics per SKU/region."""

    placement_map: dict[tuple[str, str, str | None], PlacementScoreResult] = {}
    for placement_entry in placement_scores:
        placement_key = (
            (placement_entry.region or "").lower(),
            (placement_entry.vm_size or "").lower(),
            (placement_entry.availability_zone or "").lower() if placement_entry.availability_zone else None,
        )
        placement_map[placement_key] = placement_entry

    metrics_map: dict[tuple[str, str], HistoricalMetrics] = {}
    for historical_entry in historical_metrics:
        metrics_key = ((historical_entry.region or "").lower(), (historical_entry.vm_size or "").lower())
        metrics_map[metrics_key] = historical_entry

    keys: set[tuple[str, str]] = set(metrics_map)
    keys.update((k[0], k[1]) for k in placement_map)

    combined: list[CandidateInsight] = []
    for region_key, sku_key in sorted(keys):
        matching_placement_entries = [
            value for key, value in placement_map.items() if key[0] == region_key and key[1] == sku_key
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
        for placement_entry in matching_placement_entries:
            vm_size = placement_entry.vm_size or metrics.vm_size if metrics else sku_key
            combined.append(
                CandidateInsight(
                    region=placement_entry.region or metrics.region if metrics else region_key,
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
            )
    return combined


def rank_candidates(candidates: list[CandidateInsight]) -> list[CandidateInsight]:
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

        # Check CPU architecture requirement (works even without spec data)
        if cpu_arch:
            candidate_arch = candidate.cpu_arch
            # Fall back to detecting from VM name if cpu_arch not populated
            if not candidate_arch and candidate.vm_size:
                candidate_arch = detect_cpu_architecture(candidate.vm_size)
            if not candidate_arch:
                logger.warning(f"Cannot determine architecture for {candidate.vm_size}, excluding from results")
                filtered_count += 1
                continue
            normalized_candidate_arch = candidate_arch.lower()
            # Normalize: "intel", "amd" -> "x64"; "arm" stays "arm"
            if normalized_candidate_arch in ("intel", "amd"):
                normalized_candidate_arch = "x64"
            if normalized_candidate_arch != cpu_arch.lower():
                logger.debug(f"Filtered {candidate.vm_size}: arch {normalized_candidate_arch} != {cpu_arch}")
                filtered_count += 1
                continue

        if not spec:
            if min_vcpu is not None or min_ram is not None:
                if no_max_limit:
                    logger.warning(
                        f"VM size {candidate.vm_size} not in specifications database, "
                        f"cannot verify vCPU/RAM requirements"
                    )
                    filtered.append(candidate)
                    continue
                logger.warning(
                    f"VM size {candidate.vm_size} not in specifications database, "
                    f"excluding from bounded hardware results"
                )
                filtered_count += 1
                continue
            filtered.append(candidate)
            continue

        # Check vCPU requirement
        if not matches_hardware_constraint(
            spec.vcpus,
            min_vcpu,
            dimension="vcpu",
            no_max_limit=no_max_limit,
        ):
            logger.debug(f"Filtered {candidate.vm_size}: {spec.vcpus} vCPU does not match requested window")
            filtered_count += 1
            continue

        # Check RAM requirement
        if not matches_hardware_constraint(
            spec.ram_gb,
            min_ram,
            dimension="ram",
            no_max_limit=no_max_limit,
        ):
            logger.debug(f"Filtered {candidate.vm_size}: {spec.ram_gb} GB RAM does not match requested window")
            filtered_count += 1
            continue

        filtered.append(candidate)

    if filtered_count > 0:
        parts = []
        if min_vcpu is not None:
            parts.append(f"vCPU≥{min_vcpu}")
        if min_ram is not None:
            parts.append(f"RAM≥{min_ram} GB")
        if cpu_arch is not None:
            parts.append(f"arch={cpu_arch}")
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
        # Check price constraint
        if max_price is not None and candidate.price_usd is not None and candidate.price_usd > max_price:
            logger.debug(
                f"Filtered {candidate.vm_size} in {candidate.region}: "
                f"price ${candidate.price_usd:.4f} > ${max_price} max"
            )
            filtered_count += 1
            continue

        # Check eviction rate constraint
        if max_eviction is not None and candidate.eviction_rate is not None and candidate.eviction_rate > max_eviction:
            logger.debug(
                f"Filtered {candidate.vm_size} in {candidate.region}: "
                f"eviction {candidate.eviction_rate:.1f}% > {max_eviction}% max"
            )
            filtered_count += 1
            continue

        # Check performance constraint
        if (
            min_performance is not None
            and candidate.performance_relative is not None
            and candidate.performance_relative < min_performance
        ):
            logger.debug(
                f"Filtered {candidate.vm_size} in {candidate.region}: "
                f"performance {candidate.performance_relative:.0f}% < {min_performance}% min"
            )
            filtered_count += 1
            continue

        filtered.append(candidate)

    if filtered_count > 0:
        parts = []
        if max_price is not None:
            parts.append(f"price<=${max_price}")
        if max_eviction is not None:
            parts.append(f"eviction<={max_eviction}%")
        if min_performance is not None:
            parts.append(f"performance>={min_performance}%")
        logger.info(f"Filtered out {filtered_count} candidate(s) not meeting cost constraints ({', '.join(parts)})")

    return filtered
