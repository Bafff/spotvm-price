"""Azure VM specifications database for performance comparison."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class VMSpec:
    """VM specification with vCPUs, RAM, and performance metrics."""

    vcpus: int
    ram_gb: float
    # Compute score (relative to baseline, calculated as vcpus * cpu_factor + ram_gb * ram_factor)
    # For simplicity, we use vCPUs as primary metric

    @property
    def compute_score(self) -> float:
        """Simple compute score based on vCPUs and RAM.

        Formula: vCPUs * 100 + RAM_GB * 5
        This gives more weight to CPU (100x) than RAM (5x)
        """
        return (self.vcpus * 100) + (self.ram_gb * 5)


# Azure VM specifications
# Source: https://learn.microsoft.com/en-us/azure/virtual-machines/sizes
#
# Performance Metrics Status (as of Dec 2024):
# - ACU (Azure Compute Units): DEPRECATED 12/16/2024 for ALL VM series
#   https://learn.microsoft.com/en-us/azure/virtual-machines/acu
# - CoreMark benchmarks: Available for v2/v3/v4, but NOT published for v5/v6+
#   https://learn.microsoft.com/en-us/azure/virtual-machines/windows/compute-benchmark-scores
#   See also: https://github.com/MicrosoftDocs/azure-docs/issues/84034
# - Microsoft recommendation: "Run your actual workload on target VMs for accurate performance"
#
# Our formula: (vCPUs × 100) + (RAM_GB × 5)
# - Reasonable approximation based on compute resources
# - Weights CPU more heavily (20x) than RAM for typical workloads
#
VM_SPECIFICATIONS: Dict[str, VMSpec] = {
    # D-series (General purpose)
    "Standard_D2s_v4": VMSpec(vcpus=2, ram_gb=8),
    "Standard_D4s_v4": VMSpec(vcpus=4, ram_gb=16),
    "Standard_D8s_v4": VMSpec(vcpus=8, ram_gb=32),
    "Standard_D16s_v4": VMSpec(vcpus=16, ram_gb=64),

    # D-series v5 (General purpose, newer generation)
    "Standard_D2s_v5": VMSpec(vcpus=2, ram_gb=8),
    "Standard_D4s_v5": VMSpec(vcpus=4, ram_gb=16),
    "Standard_D8s_v5": VMSpec(vcpus=8, ram_gb=32),
    "Standard_D16s_v5": VMSpec(vcpus=16, ram_gb=64),

    # Das-series (AMD-based general purpose)
    "Standard_D2as_v4": VMSpec(vcpus=2, ram_gb=8),
    "Standard_D4as_v4": VMSpec(vcpus=4, ram_gb=16),
    "Standard_D8as_v4": VMSpec(vcpus=8, ram_gb=32),
    "Standard_D16as_v4": VMSpec(vcpus=16, ram_gb=64),

    "Standard_D2as_v5": VMSpec(vcpus=2, ram_gb=8),
    "Standard_D4as_v5": VMSpec(vcpus=4, ram_gb=16),
    "Standard_D8as_v5": VMSpec(vcpus=8, ram_gb=32),
    "Standard_D16as_v5": VMSpec(vcpus=16, ram_gb=64),

    "Standard_D2as_v6": VMSpec(vcpus=2, ram_gb=8),
    "Standard_D4as_v6": VMSpec(vcpus=4, ram_gb=16),
    "Standard_D8as_v6": VMSpec(vcpus=8, ram_gb=32),
    "Standard_D16as_v6": VMSpec(vcpus=16, ram_gb=64),

    # DS-series (General purpose, older generation)
    "Standard_DS1_v2": VMSpec(vcpus=1, ram_gb=3.5),
    "Standard_DS2_v2": VMSpec(vcpus=2, ram_gb=7),
    "Standard_DS3_v2": VMSpec(vcpus=4, ram_gb=14),
    "Standard_DS4_v2": VMSpec(vcpus=8, ram_gb=28),
    "Standard_DS5_v2": VMSpec(vcpus=16, ram_gb=56),

    # E-series (Memory optimized)
    "Standard_E2s_v4": VMSpec(vcpus=2, ram_gb=16),
    "Standard_E4s_v4": VMSpec(vcpus=4, ram_gb=32),
    "Standard_E8s_v4": VMSpec(vcpus=8, ram_gb=64),
    "Standard_E16s_v4": VMSpec(vcpus=16, ram_gb=128),

    "Standard_E2s_v5": VMSpec(vcpus=2, ram_gb=16),
    "Standard_E4s_v5": VMSpec(vcpus=4, ram_gb=32),
    "Standard_E8s_v5": VMSpec(vcpus=8, ram_gb=64),
    "Standard_E16s_v5": VMSpec(vcpus=16, ram_gb=128),

    # F-series (Compute optimized)
    "Standard_F2s_v2": VMSpec(vcpus=2, ram_gb=4),
    "Standard_F4s_v2": VMSpec(vcpus=4, ram_gb=8),
    "Standard_F8s_v2": VMSpec(vcpus=8, ram_gb=16),
    "Standard_F16s_v2": VMSpec(vcpus=16, ram_gb=32),
    "Standard_F32s_v2": VMSpec(vcpus=32, ram_gb=64),
}


def get_vm_spec(sku: str) -> Optional[VMSpec]:
    """Get VM specification by SKU name (case-insensitive)."""
    return VM_SPECIFICATIONS.get(sku) or VM_SPECIFICATIONS.get(sku.replace("_", ""))


def calculate_relative_performance(
    sku: str,
    baseline_sku: str,
) -> Optional[float]:
    """Calculate performance relative to baseline SKU.

    Args:
        sku: Target VM SKU
        baseline_sku: Baseline VM SKU (will be 100%)

    Returns:
        Percentage relative to baseline (e.g., 200.0 means 2x faster)
        None if either SKU is not found
    """
    spec = get_vm_spec(sku)
    baseline_spec = get_vm_spec(baseline_sku)

    if not spec or not baseline_spec:
        return None

    # Calculate relative performance
    baseline_score = baseline_spec.compute_score
    if baseline_score == 0:
        return None

    return (spec.compute_score / baseline_score) * 100.0


def discover_skus(
    min_vcpu: Optional[int] = None,
    min_ram: Optional[int] = None,
) -> list[str]:
    """Discover VM SKUs matching hardware requirements.

    Scans all known SKUs in VM_SPECIFICATIONS and returns those that meet
    the specified minimum vCPU and RAM requirements. Useful for auto-discovery
    when user doesn't specify --sizes but provides hardware requirements.

    Args:
        min_vcpu: Minimum vCPUs required (None = no filter)
        min_ram: Minimum RAM in GB required (None = no filter)

    Returns:
        List of SKU names that meet the requirements, sorted by compute score

    Example:
        # Find all VMs with at least 4 vCPUs and 16 GB RAM
        skus = discover_skus(min_vcpu=4, min_ram=16)
        # Returns: ['Standard_D4as_v6', 'Standard_E4s_v5', ...]
    """
    matching_skus = []

    for sku_name, spec in VM_SPECIFICATIONS.items():
        # Check vCPU requirement
        if min_vcpu is not None and spec.vcpus < min_vcpu:
            continue

        # Check RAM requirement
        if min_ram is not None and spec.ram_gb < min_ram:
            continue

        matching_skus.append((sku_name, spec.compute_score))

    # Sort by compute score (ascending) - cheaper/smaller VMs first
    matching_skus.sort(key=lambda x: x[1])

    return [sku for sku, _ in matching_skus]
