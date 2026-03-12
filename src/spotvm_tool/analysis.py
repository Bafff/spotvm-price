from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional, Tuple

from .models import CandidateInsight, HistoricalMetrics, PlacementScoreResult
from .vm_specs import calculate_relative_performance_details, get_vm_spec, detect_cpu_architecture

logger = logging.getLogger("spotvm-tool")

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
            vm_size = entry.vm_size or metrics.vm_size if metrics else sku_key
            combined.append(
                CandidateInsight(
                    region=entry.region or metrics.region if metrics else region_key,
                    vm_size=vm_size,
                    placement_score=entry.placement_score,
                    quota_available=entry.quota_available,
                    price_usd=metrics.price_usd if metrics else None,
                    price_last_updated=metrics.price_last_updated if metrics else None,
                    eviction_rate=metrics.eviction_rate if metrics else None,
                    eviction_last_updated=metrics.eviction_last_updated if metrics else None,
                    availability_zone=entry.availability_zone,
                    notes=entry.error_detail,
                    cpu_arch=detect_cpu_architecture(vm_size) if vm_size else None,
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
    candidates: List[CandidateInsight],
) -> List[CandidateInsight]:
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


def filter_by_requirements(
    candidates: List[CandidateInsight],
    min_vcpu: Optional[int] = None,
    min_ram: Optional[int] = None,
    cpu_arch: Optional[str] = None,
) -> List[CandidateInsight]:
    """Filter candidates by hardware requirements (vCPU, RAM, CPU architecture).

    Removes candidates that don't meet minimum vCPU or RAM requirements,
    or don't match the requested CPU architecture.
    SKUs not found in VM_SPECIFICATIONS are kept with a warning for vCPU/RAM
    checks, but candidates with unknown architecture are excluded when
    cpu_arch is specified.

    Args:
        candidates: List of candidate insights to filter
        min_vcpu: Minimum vCPUs required (None = no filter)
        min_ram: Minimum RAM in GB required (None = no filter)
        cpu_arch: CPU architecture filter, "x64" or "arm" (None = no filter)

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
                logger.warning(
                    f"Cannot determine architecture for {candidate.vm_size}, excluding from results"
                )
                filtered_count += 1
                continue
            candidate_arch = candidate_arch.lower()
            # Normalize: "intel", "amd" -> "x64"; "arm" stays "arm"
            if candidate_arch in ("intel", "amd"):
                candidate_arch = "x64"
            if candidate_arch != cpu_arch.lower():
                logger.debug(
                    f"Filtered {candidate.vm_size}: arch {candidate_arch} != {cpu_arch}"
                )
                filtered_count += 1
                continue

        if not spec:
            if min_vcpu is not None or min_ram is not None:
                # Unknown SKU - keep it but warn about unverifiable requirements
                logger.warning(
                    f"VM size {candidate.vm_size} not in specifications database, "
                    f"cannot verify vCPU/RAM requirements"
                )
            filtered.append(candidate)
            continue

        # Check vCPU requirement
        if min_vcpu is not None and spec.vcpus < min_vcpu:
            logger.debug(
                f"Filtered {candidate.vm_size}: {spec.vcpus} vCPU < {min_vcpu} required"
            )
            filtered_count += 1
            continue

        # Check RAM requirement
        if min_ram is not None and spec.ram_gb < min_ram:
            logger.debug(
                f"Filtered {candidate.vm_size}: {spec.ram_gb} GB RAM < {min_ram} GB required"
            )
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
            f"Filtered out {filtered_count} candidate(s) not meeting "
            f"hardware requirements ({', '.join(parts)})"
        )

    return filtered


def filter_by_cost(
    candidates: List[CandidateInsight],
    max_price: Optional[float] = None,
    max_eviction: Optional[float] = None,
    min_performance: Optional[float] = None,
) -> List[CandidateInsight]:
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
        if min_performance is not None and candidate.performance_relative is not None and candidate.performance_relative < min_performance:
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
        logger.info(
            f"Filtered out {filtered_count} candidate(s) not meeting cost constraints "
            f"({', '.join(parts)})"
        )

    return filtered
