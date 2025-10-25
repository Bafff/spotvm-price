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
# Note: Microsoft's ACU (Azure Compute Units) are NOT published for newer VM generations (v5, v6+)
# See: https://github.com/MicrosoftDocs/azure-docs/issues/84034
# Microsoft is "reevaluating ACU methodology" and now uses CoreMark/SPECInt benchmarks instead.
# Until official performance metrics are published, we use vCPU and RAM as performance indicators.
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
