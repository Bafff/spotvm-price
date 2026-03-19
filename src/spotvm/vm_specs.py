"""Azure VM specifications: policy facade over the static catalog.

Public API remains stable for existing imports from ``spotvm.vm_specs`` while
the static catalog now lives in ``spotvm.vm_catalog``.
"""

from __future__ import annotations

import re
from functools import cache
from typing import Literal

from .models import CPUArchitecture, PerformanceBasis
from .vm_catalog import (  # noqa: F401
    _NORMALIZED_VM_SPECIFICATIONS,
    VM_SPECIFICATIONS,
    VMSpec,
    get_vm_spec,
)

HardwareDimension = Literal["vcpu", "ram"]


@cache
def known_hardware_tiers(dimension: HardwareDimension) -> tuple[float, ...]:
    """Return sorted distinct hardware tiers known to the local specs database."""
    if dimension == "vcpu":
        return tuple(sorted({float(spec.vcpus) for spec in VM_SPECIFICATIONS.values()}))
    return tuple(sorted({float(spec.ram_gb) for spec in VM_SPECIFICATIONS.values()}))


def hardware_window_tiers(
    minimum: float | None,
    *,
    dimension: HardwareDimension,
) -> tuple[float, ...] | None:
    """Return the next three distinct known tiers that satisfy a minimum constraint."""
    if minimum is None:
        return None
    return tuple(tier for tier in known_hardware_tiers(dimension) if tier >= minimum)[:3]


def matches_hardware_constraint(
    value: float,
    minimum: float | None,
    *,
    dimension: HardwareDimension,
    no_max_limit: bool = False,
) -> bool:
    """Check whether a hardware value satisfies bounded or unbounded minimum filtering."""
    if minimum is None:
        return True
    if value < minimum:
        return False
    if no_max_limit:
        return True
    window = hardware_window_tiers(minimum, dimension=dimension)
    return window is not None and value in window


def calculate_relative_performance(
    sku: str,
    baseline_sku: str,
) -> float | None:
    """Calculate performance relative to baseline SKU."""
    performance, _ = calculate_relative_performance_details(sku, baseline_sku)
    return performance


def calculate_relative_performance_details(
    sku: str,
    baseline_sku: str,
) -> tuple[float | None, PerformanceBasis | None]:
    """Calculate relative performance and expose whether CoreMark or a fallback was used."""
    spec = get_vm_spec(sku)
    baseline_spec = get_vm_spec(baseline_sku)

    if not spec or not baseline_spec:
        return None, None

    if spec.coremark_score is not None and baseline_spec.coremark_score is not None:
        score = float(spec.coremark_score)
        baseline_score = float(baseline_spec.coremark_score)
        basis: PerformanceBasis | None = "coremark"
    else:
        score = spec.compute_score
        if detect_cpu_architecture(sku) == "arm":
            score *= 1.15

        baseline_score = baseline_spec.compute_score
        if detect_cpu_architecture(baseline_sku) == "arm":
            baseline_score *= 1.15

        basis = "heuristic"

    if baseline_score == 0:
        return None, None

    return (score / baseline_score) * 100.0, basis


CPUVendor = Literal["intel", "amd", "arm"]


def _extract_additive_features(sku: str) -> str:
    """Return the additive-feature block from an Azure VM SKU name."""
    normalized = sku.removeprefix("Standard_").lower()
    family_segment = normalized.split("_", 1)[0]
    match = re.search(r"\d+(?:-\d+)?", family_segment)
    if match is None:
        return ""
    return family_segment[match.end() :]


def detect_cpu_architecture(sku: str) -> CPUArchitecture:
    """Detect CPU architecture from Azure VM SKU name."""
    if "p" in _extract_additive_features(sku):
        return "arm"
    return "x64"


def detect_cpu_vendor(sku: str) -> CPUVendor:
    """Detect CPU vendor from Azure VM SKU name."""
    features = _extract_additive_features(sku)

    if "p" in features:
        return "arm"
    if "a" in features:
        return "amd"
    return "intel"


def discover_skus(
    min_vcpu: int | None = None,
    min_ram: int | None = None,
    cpu_arch: CPUArchitecture | None = None,
    no_max_limit: bool = False,
) -> list[str]:
    """Discover VM SKUs matching hardware requirements."""
    matching_skus = []

    for sku_name, spec in VM_SPECIFICATIONS.items():
        if not matches_hardware_constraint(
            spec.vcpus,
            min_vcpu,
            dimension="vcpu",
            no_max_limit=no_max_limit,
        ):
            continue

        if not matches_hardware_constraint(
            spec.ram_gb,
            min_ram,
            dimension="ram",
            no_max_limit=no_max_limit,
        ):
            continue

        if cpu_arch is not None and detect_cpu_architecture(sku_name) != cpu_arch:
            continue

        matching_skus.append((sku_name, spec.compute_score))

    matching_skus.sort(key=lambda item: item[1])
    return [sku for sku, _ in matching_skus]
