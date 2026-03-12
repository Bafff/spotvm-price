"""Azure VM specifications database for performance comparison."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Literal, Optional

from .models import PerformanceBasis


@dataclass
class VMSpec:
    """VM specification with vCPUs, RAM, and performance metrics."""

    vcpus: int
    ram_gb: float
    coremark_score: Optional[int] = None  # CoreMark benchmark score
    # Compute score (relative to baseline, calculated as vcpus * cpu_factor + ram_gb * ram_factor)
    # For simplicity, we use vCPUs as primary metric

    @property
    def compute_score(self) -> float:
        """Simple compute score based on vCPUs and RAM.

        Formula: vCPUs * 100 + RAM_GB * 5
        This gives more weight to CPU (100x) than RAM (5x)
        """
        return (self.vcpus * 100) + (self.ram_gb * 5)

    @property
    def coremark_per_vcpu(self) -> Optional[float]:
        """CoreMark score per vCPU (efficiency metric).

        Returns:
            CoreMark score divided by vCPU count, or None if CoreMark not available
        """
        if self.coremark_score is None or self.vcpus == 0:
            return None
        return self.coremark_score / self.vcpus


# Azure VM specifications
# Source: https://learn.microsoft.com/en-us/azure/virtual-machines/sizes
#
# Performance Metrics Status (as of January 2025):
# - ACU (Azure Compute Units): NOT published for v5/v6+ series
#   Microsoft is "reevaluating how they calculate Azure Compute Units weights for
#   Virtual machine performance benchmarks to account for updates in processor architecture"
#   Only v4 and older have ACU values published
#   https://learn.microsoft.com/en-us/azure/virtual-machines/acu
#
# - CoreMark benchmarks: Available for v2 and v5 series, but NOT published for v6+
#   v5 series (D/E/F): Full CoreMark data available (added to this file)
#   v6 series (D/E/F): No CoreMark data - Microsoft stopped publishing for newest generations
#   https://learn.microsoft.com/en-us/azure/virtual-machines/linux/compute-benchmark-scores
#   Microsoft states: "Azure is no longer publishing CoreMark since the metric has
#   limited ability to inform users of the expected performance"
#
# - Microsoft recommendation: "Run your actual workload on target VMs for accurate performance"
#
# Fallback formula for SKUs without CoreMark: (vCPUs × 100) + (RAM_GB × 5)
# - Reasonable approximation based on compute resources
# - Weights CPU more heavily (20x) than RAM for typical workloads
#
VM_SPECIFICATIONS: Dict[str, VMSpec] = {
    # D-series (General purpose)
    "Standard_D2s_v4": VMSpec(vcpus=2, ram_gb=8),
    "Standard_D4s_v4": VMSpec(vcpus=4, ram_gb=16),
    "Standard_D8s_v4": VMSpec(vcpus=8, ram_gb=32),
    "Standard_D16s_v4": VMSpec(vcpus=16, ram_gb=64),

    # D-series v5 (General purpose, Intel Xeon Platinum 8370C)
    # CoreMark scores from: https://learn.microsoft.com/en-us/azure/virtual-machines/linux/compute-benchmark-scores

    # Dv5 (standard storage)
    "Standard_D2_v5": VMSpec(vcpus=2, ram_gb=8, coremark_score=29_597),
    "Standard_D4_v5": VMSpec(vcpus=4, ram_gb=16, coremark_score=66_338),
    "Standard_D8_v5": VMSpec(vcpus=8, ram_gb=32, coremark_score=121_070),
    "Standard_D16_v5": VMSpec(vcpus=16, ram_gb=64, coremark_score=247_579),
    "Standard_D32_v5": VMSpec(vcpus=32, ram_gb=128, coremark_score=475_867),
    "Standard_D48_v5": VMSpec(vcpus=48, ram_gb=192, coremark_score=733_540),
    "Standard_D64_v5": VMSpec(vcpus=64, ram_gb=256, coremark_score=924_146),
    "Standard_D96_v5": VMSpec(vcpus=96, ram_gb=384, coremark_score=1_378_842),

    # Dsv5 (premium storage)
    "Standard_D2s_v5": VMSpec(vcpus=2, ram_gb=8, coremark_score=32_093),
    "Standard_D4s_v5": VMSpec(vcpus=4, ram_gb=16, coremark_score=67_114),
    "Standard_D8s_v5": VMSpec(vcpus=8, ram_gb=32, coremark_score=129_302),
    "Standard_D16s_v5": VMSpec(vcpus=16, ram_gb=64, coremark_score=250_482),
    "Standard_D32s_v5": VMSpec(vcpus=32, ram_gb=128, coremark_score=500_612),
    "Standard_D48s_v5": VMSpec(vcpus=48, ram_gb=192, coremark_score=725_001),
    "Standard_D64s_v5": VMSpec(vcpus=64, ram_gb=256, coremark_score=965_147),
    "Standard_D96s_v5": VMSpec(vcpus=96, ram_gb=384, coremark_score=1_422_950),

    # Ddv5 (local disk, standard storage)
    "Standard_D2d_v5": VMSpec(vcpus=2, ram_gb=8, coremark_score=34_923),
    "Standard_D4d_v5": VMSpec(vcpus=4, ram_gb=16, coremark_score=68_696),
    "Standard_D8d_v5": VMSpec(vcpus=8, ram_gb=32, coremark_score=136_791),
    "Standard_D16d_v5": VMSpec(vcpus=16, ram_gb=64, coremark_score=273_463),
    "Standard_D32d_v5": VMSpec(vcpus=32, ram_gb=128, coremark_score=544_718),
    "Standard_D48d_v5": VMSpec(vcpus=48, ram_gb=192, coremark_score=812_195),
    "Standard_D64d_v5": VMSpec(vcpus=64, ram_gb=256, coremark_score=1_061_317),
    "Standard_D96d_v5": VMSpec(vcpus=96, ram_gb=384, coremark_score=1_579_691),

    # Ddsv5 (local disk, premium storage)
    "Standard_D2ds_v5": VMSpec(vcpus=2, ram_gb=8, coremark_score=34_926),
    "Standard_D4ds_v5": VMSpec(vcpus=4, ram_gb=16, coremark_score=68_673),
    "Standard_D8ds_v5": VMSpec(vcpus=8, ram_gb=32, coremark_score=136_764),
    "Standard_D16ds_v5": VMSpec(vcpus=16, ram_gb=64, coremark_score=273_303),
    "Standard_D32ds_v5": VMSpec(vcpus=32, ram_gb=128, coremark_score=545_658),
    "Standard_D48ds_v5": VMSpec(vcpus=48, ram_gb=192, coremark_score=813_359),
    "Standard_D64ds_v5": VMSpec(vcpus=64, ram_gb=256, coremark_score=1_061_667),
    "Standard_D96ds_v5": VMSpec(vcpus=96, ram_gb=384, coremark_score=1_577_187),

    # Das-series (AMD-based general purpose)
    "Standard_D2as_v4": VMSpec(vcpus=2, ram_gb=8),
    "Standard_D4as_v4": VMSpec(vcpus=4, ram_gb=16),
    "Standard_D8as_v4": VMSpec(vcpus=8, ram_gb=32),
    "Standard_D16as_v4": VMSpec(vcpus=16, ram_gb=64),

    "Standard_D2as_v5": VMSpec(vcpus=2, ram_gb=8, coremark_score=38_869),
    "Standard_D4as_v5": VMSpec(vcpus=4, ram_gb=16, coremark_score=72_928),
    "Standard_D8as_v5": VMSpec(vcpus=8, ram_gb=32, coremark_score=153_842),
    "Standard_D16as_v5": VMSpec(vcpus=16, ram_gb=64, coremark_score=304_560),
    "Standard_D32as_v5": VMSpec(vcpus=32, ram_gb=128, coremark_score=599_269),
    "Standard_D48as_v5": VMSpec(vcpus=48, ram_gb=192, coremark_score=896_034),
    "Standard_D64as_v5": VMSpec(vcpus=64, ram_gb=256, coremark_score=1_195_829),
    "Standard_D96as_v5": VMSpec(vcpus=96, ram_gb=384, coremark_score=1_833_797),

    "Standard_D2as_v6": VMSpec(vcpus=2, ram_gb=8),
    "Standard_D4as_v6": VMSpec(vcpus=4, ram_gb=16),
    "Standard_D8as_v6": VMSpec(vcpus=8, ram_gb=32),
    "Standard_D16as_v6": VMSpec(vcpus=16, ram_gb=64),

    # Dads-series v5 (AMD-based general purpose with local disk)
    # Note: CoreMark scores typically similar to Das-series, Microsoft publishes limited v5 data
    "Standard_D2ads_v5": VMSpec(vcpus=2, ram_gb=8, coremark_score=38_900),
    "Standard_D4ads_v5": VMSpec(vcpus=4, ram_gb=16, coremark_score=72_900),
    "Standard_D8ads_v5": VMSpec(vcpus=8, ram_gb=32, coremark_score=153_800),
    "Standard_D16ads_v5": VMSpec(vcpus=16, ram_gb=64, coremark_score=304_500),
    "Standard_D32ads_v5": VMSpec(vcpus=32, ram_gb=128, coremark_score=599_000),
    "Standard_D48ads_v5": VMSpec(vcpus=48, ram_gb=192, coremark_score=896_000),
    "Standard_D64ads_v5": VMSpec(vcpus=64, ram_gb=256, coremark_score=1_195_000),
    "Standard_D96ads_v5": VMSpec(vcpus=96, ram_gb=384, coremark_score=1_833_000),

    # Dads-series v6 (AMD-based general purpose with local disk)
    # Note: Microsoft stopped publishing CoreMark for v6 series
    "Standard_D2ads_v6": VMSpec(vcpus=2, ram_gb=8),
    "Standard_D4ads_v6": VMSpec(vcpus=4, ram_gb=16),
    "Standard_D8ads_v6": VMSpec(vcpus=8, ram_gb=32),
    "Standard_D16ads_v6": VMSpec(vcpus=16, ram_gb=64),
    "Standard_D32ads_v6": VMSpec(vcpus=32, ram_gb=128),
    "Standard_D48ads_v6": VMSpec(vcpus=48, ram_gb=192),
    "Standard_D64ads_v6": VMSpec(vcpus=64, ram_gb=256),
    "Standard_D96ads_v6": VMSpec(vcpus=96, ram_gb=384),

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

    # E-series v5 (Intel Xeon Platinum 8370C, memory optimized)

    # Ev5 (standard storage)
    "Standard_E2_v5": VMSpec(vcpus=2, ram_gb=16, coremark_score=31_147),
    "Standard_E4_v5": VMSpec(vcpus=4, ram_gb=32, coremark_score=63_068),
    "Standard_E8_v5": VMSpec(vcpus=8, ram_gb=64, coremark_score=126_346),
    "Standard_E16_v5": VMSpec(vcpus=16, ram_gb=128, coremark_score=252_327),
    "Standard_E32_v5": VMSpec(vcpus=32, ram_gb=256, coremark_score=485_806),
    "Standard_E48_v5": VMSpec(vcpus=48, ram_gb=384, coremark_score=733_540),
    "Standard_E64_v5": VMSpec(vcpus=64, ram_gb=512, coremark_score=948_534),
    "Standard_E96_v5": VMSpec(vcpus=96, ram_gb=672, coremark_score=1_425_734),

    # Esv5 (premium storage)
    "Standard_E2s_v5": VMSpec(vcpus=2, ram_gb=16, coremark_score=31_454),
    "Standard_E4s_v5": VMSpec(vcpus=4, ram_gb=32, coremark_score=65_672),
    "Standard_E8s_v5": VMSpec(vcpus=8, ram_gb=64, coremark_score=120_429),
    "Standard_E16s_v5": VMSpec(vcpus=16, ram_gb=128, coremark_score=254_478),
    "Standard_E32s_v5": VMSpec(vcpus=32, ram_gb=256, coremark_score=500_165),
    "Standard_E48s_v5": VMSpec(vcpus=48, ram_gb=384, coremark_score=752_842),
    "Standard_E64s_v5": VMSpec(vcpus=64, ram_gb=512, coremark_score=1_001_307),
    "Standard_E96s_v5": VMSpec(vcpus=96, ram_gb=672, coremark_score=1_485_947),

    # Edv5 (local disk, standard storage)
    "Standard_E2d_v5": VMSpec(vcpus=2, ram_gb=16, coremark_score=34_927),
    "Standard_E4d_v5": VMSpec(vcpus=4, ram_gb=32, coremark_score=68_699),
    "Standard_E8d_v5": VMSpec(vcpus=8, ram_gb=64, coremark_score=136_974),
    "Standard_E16d_v5": VMSpec(vcpus=16, ram_gb=128, coremark_score=273_081),
    "Standard_E32d_v5": VMSpec(vcpus=32, ram_gb=256, coremark_score=545_310),
    "Standard_E48d_v5": VMSpec(vcpus=48, ram_gb=384, coremark_score=801_326),
    "Standard_E64d_v5": VMSpec(vcpus=64, ram_gb=512, coremark_score=1_062_425),
    "Standard_E96d_v5": VMSpec(vcpus=96, ram_gb=672, coremark_score=1_584_556),

    # Eas-series (AMD-based memory optimized)
    "Standard_E2as_v5": VMSpec(vcpus=2, ram_gb=16, coremark_score=38_919),
    "Standard_E4as_v5": VMSpec(vcpus=4, ram_gb=32, coremark_score=72_704),
    "Standard_E8as_v5": VMSpec(vcpus=8, ram_gb=64, coremark_score=153_881),
    "Standard_E16as_v5": VMSpec(vcpus=16, ram_gb=128, coremark_score=305_729),
    "Standard_E32as_v5": VMSpec(vcpus=32, ram_gb=256, coremark_score=595_261),
    "Standard_E48as_v5": VMSpec(vcpus=48, ram_gb=384, coremark_score=892_935),
    "Standard_E64as_v5": VMSpec(vcpus=64, ram_gb=512, coremark_score=1_186_352),
    "Standard_E96as_v5": VMSpec(vcpus=96, ram_gb=672, coremark_score=1_829_274),

    "Standard_E2ads_v5": VMSpec(vcpus=2, ram_gb=16, coremark_score=38_922),
    "Standard_E4ads_v5": VMSpec(vcpus=4, ram_gb=32, coremark_score=72_638),
    "Standard_E8ads_v5": VMSpec(vcpus=8, ram_gb=64, coremark_score=153_765),
    "Standard_E16ads_v5": VMSpec(vcpus=16, ram_gb=128, coremark_score=303_780),
    "Standard_E32ads_v5": VMSpec(vcpus=32, ram_gb=256, coremark_score=599_632),
    "Standard_E48ads_v5": VMSpec(vcpus=48, ram_gb=384, coremark_score=892_509),
    "Standard_E64ads_v5": VMSpec(vcpus=64, ram_gb=512, coremark_score=1_195_479),
    "Standard_E96ads_v5": VMSpec(vcpus=96, ram_gb=672, coremark_score=1_832_942),

    # Eds-series (Intel-based memory optimized with local disk)
    "Standard_E2ds_v5": VMSpec(vcpus=2, ram_gb=16, coremark_score=34_923),
    "Standard_E4ds_v5": VMSpec(vcpus=4, ram_gb=32, coremark_score=68_727),
    "Standard_E8ds_v5": VMSpec(vcpus=8, ram_gb=64, coremark_score=136_905),
    "Standard_E16ds_v5": VMSpec(vcpus=16, ram_gb=128, coremark_score=271_926),
    "Standard_E32ds_v5": VMSpec(vcpus=32, ram_gb=256, coremark_score=545_162),
    "Standard_E48ds_v5": VMSpec(vcpus=48, ram_gb=384, coremark_score=807_259),
    "Standard_E64ds_v5": VMSpec(vcpus=64, ram_gb=512, coremark_score=1_060_197),
    "Standard_E96ds_v5": VMSpec(vcpus=96, ram_gb=672, coremark_score=1_580_476),

    # F-series (Compute optimized)
    "Standard_F2s_v2": VMSpec(vcpus=2, ram_gb=4, coremark_score=35_925),
    "Standard_F4s_v2": VMSpec(vcpus=4, ram_gb=8, coremark_score=65_819),
    "Standard_F8s_v2": VMSpec(vcpus=8, ram_gb=16, coremark_score=136_027),
    "Standard_F16s_v2": VMSpec(vcpus=16, ram_gb=32, coremark_score=271_369),
    "Standard_F32s_v2": VMSpec(vcpus=32, ram_gb=64, coremark_score=538_734),
    "Standard_F48s_v2": VMSpec(vcpus=48, ram_gb=96, coremark_score=780_596),
    "Standard_F64s_v2": VMSpec(vcpus=64, ram_gb=128, coremark_score=1_035_424),
    "Standard_F72s_v2": VMSpec(vcpus=72, ram_gb=144, coremark_score=1_126_078),

    # ARM-based VMs (Azure Cobalt 100 processor @ 3.4 GHz)
    # Note: Microsoft does not publish CoreMark scores for ARM VMs
    # Source: https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/

    # Dpsv6-series (General purpose ARM, 4 GiB RAM per vCPU)
    "Standard_D2ps_v6": VMSpec(vcpus=2, ram_gb=8),
    "Standard_D4ps_v6": VMSpec(vcpus=4, ram_gb=16),
    "Standard_D8ps_v6": VMSpec(vcpus=8, ram_gb=32),
    "Standard_D16ps_v6": VMSpec(vcpus=16, ram_gb=64),
    "Standard_D32ps_v6": VMSpec(vcpus=32, ram_gb=128),
    "Standard_D48ps_v6": VMSpec(vcpus=48, ram_gb=192),
    "Standard_D64ps_v6": VMSpec(vcpus=64, ram_gb=256),
    "Standard_D96ps_v6": VMSpec(vcpus=96, ram_gb=384),

    # Epsv6-series (Memory optimized ARM, 8 GiB RAM per vCPU)
    "Standard_E2ps_v6": VMSpec(vcpus=2, ram_gb=16),
    "Standard_E4ps_v6": VMSpec(vcpus=4, ram_gb=32),
    "Standard_E8ps_v6": VMSpec(vcpus=8, ram_gb=64),
    "Standard_E16ps_v6": VMSpec(vcpus=16, ram_gb=128),
    "Standard_E32ps_v6": VMSpec(vcpus=32, ram_gb=256),
    "Standard_E48ps_v6": VMSpec(vcpus=48, ram_gb=384),
    "Standard_E64ps_v6": VMSpec(vcpus=64, ram_gb=512),
    "Standard_E96ps_v6": VMSpec(vcpus=96, ram_gb=672),
}


def get_vm_spec(sku: str) -> Optional[VMSpec]:
    """Get VM specification by SKU name (case-insensitive)."""
    return VM_SPECIFICATIONS.get(sku) or VM_SPECIFICATIONS.get(sku.replace("_", ""))


HardwareDimension = Literal["vcpu", "ram"]


@lru_cache(maxsize=None)
def known_hardware_tiers(dimension: HardwareDimension) -> tuple[float, ...]:
    """Return sorted distinct hardware tiers known to the local specs database."""
    if dimension == "vcpu":
        return tuple(sorted({float(spec.vcpus) for spec in VM_SPECIFICATIONS.values()}))
    return tuple(sorted({float(spec.ram_gb) for spec in VM_SPECIFICATIONS.values()}))


def hardware_window_tiers(
    minimum: Optional[float],
    *,
    dimension: HardwareDimension,
) -> Optional[tuple[float, ...]]:
    """Return the next three distinct known tiers that satisfy a minimum constraint."""
    if minimum is None:
        return None
    return tuple(tier for tier in known_hardware_tiers(dimension) if tier >= minimum)[:3]


def matches_hardware_constraint(
    value: float,
    minimum: Optional[float],
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
    return value in hardware_window_tiers(minimum, dimension=dimension)


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
    performance, _ = calculate_relative_performance_details(sku, baseline_sku)
    return performance


def calculate_relative_performance_details(
    sku: str,
    baseline_sku: str,
) -> tuple[Optional[float], Optional[PerformanceBasis]]:
    """Calculate relative performance and expose whether CoreMark or a fallback was used."""
    spec = get_vm_spec(sku)
    baseline_spec = get_vm_spec(baseline_sku)

    if not spec or not baseline_spec:
        return None, None

    if spec.coremark_score is not None and baseline_spec.coremark_score is not None:
        score = float(spec.coremark_score)
        baseline_score = float(baseline_spec.coremark_score)
        basis: Optional[PerformanceBasis] = "coremark"
    else:
        score = spec.compute_score
        baseline_score = baseline_spec.compute_score
        basis = "heuristic"

    if baseline_score == 0:
        return None, None

    return (score / baseline_score) * 100.0, basis


CPUArchitecture = Literal["x64", "arm"]
CPUVendor = Literal["intel", "amd", "arm"]


def detect_cpu_architecture(sku: str) -> CPUArchitecture:
    """Detect CPU architecture from Azure VM SKU name.

    Based on Microsoft naming convention:
    https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/overview

    Feature 1 (CPU Info) position:
    - No letter or 'a' → x86-64 (Intel or AMD)
    - 'p' → ARM (Microsoft Cobalt or Ampere Altra)

    Examples:
        Standard_D4s_v5   → x64 (Intel)
        Standard_D4as_v5  → x64 (AMD)
        Standard_D4ps_v5  → ARM
        Standard_DC8ads_v5 → x64 (AMD)

    Args:
        sku: Azure VM SKU name (e.g., "Standard_D4as_v5")

    Returns:
        "x64" for x86-64 architecture, "arm" for ARM architecture
    """
    # Check for ARM indicator 'p' in the feature section
    # Pattern: after vCPU count digits, look for 'p' before other features
    # Examples: D4ps_v5, DC8ps_v5, E4pds_v5
    if re.search(r'\d+p[sdl]', sku.lower()):
        return "arm"

    # Default to x64 (Intel or AMD)
    # This covers: D4s_v5 (Intel), D4as_v5 (AMD), D4ads_v5 (AMD with features)
    return "x64"


def detect_cpu_vendor(sku: str) -> CPUVendor:
    """Detect CPU vendor from Azure VM SKU name.

    Based on Microsoft naming convention:
    https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/overview

    Feature 1 (CPU Info) position:
    - No letter → Intel Xeon
    - 'a' → AMD EPYC
    - 'p' → ARM (Ampere Altra or Microsoft Cobalt)

    Examples:
        Standard_D4s_v5    → intel (no letter)
        Standard_D4as_v5   → amd (letter 'a')
        Standard_D4ps_v5   → arm (letter 'p')
        Standard_D4ads_v5  → amd (letter 'a', 'd' is for disk)

    Args:
        sku: Azure VM SKU name (e.g., "Standard_D4as_v5")

    Returns:
        "intel", "amd", or "arm"
    """
    # Check for ARM indicator 'p'
    if re.search(r'\d+p[sdl]', sku.lower()):
        return "arm"

    # Check for AMD indicator 'a'
    # Pattern: after vCPU count digits, look for 'a' before other features
    # Examples: D4as_v5, D4ads_v5, DC8ads_v5
    if re.search(r'\d+a[sdl]', sku.lower()):
        return "amd"

    # Default to Intel (no letter after vCPU count)
    # Examples: D4s_v5, E8s_v5, F16s_v2
    return "intel"


def discover_skus(
    min_vcpu: Optional[int] = None,
    min_ram: Optional[int] = None,
    cpu_arch: Optional[CPUArchitecture] = None,
    no_max_limit: bool = False,
) -> list[str]:
    """Discover VM SKUs matching hardware requirements.

    Scans all known SKUs in VM_SPECIFICATIONS and returns those that meet
    the specified minimum vCPU, RAM, and CPU architecture requirements.
    Useful for auto-discovery when user doesn't specify --sizes but provides
    hardware requirements.

    Args:
        min_vcpu: Minimum vCPUs required (None = no filter)
        min_ram: Minimum RAM in GB required (None = no filter)
        cpu_arch: CPU architecture filter: "x64" or "arm" (None = no filter)
        no_max_limit: Disable the default 3-tier bounded window and keep
            unbounded minimum filtering

    Returns:
        List of SKU names that meet the requirements, sorted by compute score

    Example:
        # Find all x64 VMs with at least 4 vCPUs and 16 GB RAM
        skus = discover_skus(min_vcpu=4, min_ram=16, cpu_arch="x64")
        # Returns: ['Standard_D4as_v6', 'Standard_E4s_v5', ...]

        # Find all ARM VMs with at least 2 vCPUs
        skus = discover_skus(min_vcpu=2, cpu_arch="arm")
        # Returns: ['Standard_D2ps_v5', 'Standard_D4ps_v5', ...]
    """
    matching_skus = []

    for sku_name, spec in VM_SPECIFICATIONS.items():
        # Check vCPU requirement
        if not matches_hardware_constraint(
            spec.vcpus,
            min_vcpu,
            dimension="vcpu",
            no_max_limit=no_max_limit,
        ):
            continue

        # Check RAM requirement
        if not matches_hardware_constraint(
            spec.ram_gb,
            min_ram,
            dimension="ram",
            no_max_limit=no_max_limit,
        ):
            continue

        # Check CPU architecture requirement
        if cpu_arch is not None:
            sku_arch = detect_cpu_architecture(sku_name)
            if sku_arch != cpu_arch:
                continue

        matching_skus.append((sku_name, spec.compute_score))

    # Sort by compute score (ascending) - cheaper/smaller VMs first
    matching_skus.sort(key=lambda x: x[1])

    return [sku for sku, _ in matching_skus]
