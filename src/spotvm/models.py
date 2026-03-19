from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

PerformanceBasis = Literal["coremark", "heuristic"]
CPUArchitecture = Literal["x64", "arm"]
DATABRICKS_OPTIONAL_FIELDS = (
    "compute_price_usd",
    "databricks_dbu_per_hour",
    "databricks_dbu_cost_usd",
    "databricks_photon_dbu_per_hour",
    "databricks_photon_cost_usd",
    "total_price_usd",
    "databricks_catalog_updated",
)


@dataclass
class PlacementScoreResult:
    region: str
    vm_size: str
    placement_score: str | None
    quota_available: bool | None
    availability_zone: str | None = None
    error_detail: str | None = None


@dataclass
class HistoricalMetrics:
    region: str
    vm_size: str
    price_usd: float | None
    price_last_updated: datetime | None
    eviction_rate: float | None
    eviction_last_updated: datetime | None


@dataclass
class CandidateInsight:
    region: str
    vm_size: str
    placement_score: str | None
    quota_available: bool | None
    price_usd: float | None
    price_last_updated: datetime | None
    eviction_rate: float | None
    eviction_last_updated: datetime | None
    availability_zone: str | None = None
    recommendation_rank: int | None = None
    notes: str | None = None
    performance_relative: float | None = None  # % relative to baseline
    price_per_performance: float | None = None  # USD per performance unit
    performance_basis: PerformanceBasis | None = None
    performance_note: str | None = None
    cpu_arch: CPUArchitecture | None = None
    coremark_score: int | None = None  # CoreMark benchmark score
    coremark_per_vcpu: float | None = None  # CoreMark per vCPU (efficiency metric)
    compute_price_usd: float | None = None
    databricks_dbu_per_hour: float | None = None
    databricks_dbu_cost_usd: float | None = None
    databricks_photon_dbu_per_hour: float | None = None
    databricks_photon_cost_usd: float | None = None
    total_price_usd: float | None = None
    databricks_catalog_updated: datetime | None = None


def effective_price_usd(candidate: CandidateInsight) -> float | None:
    """Return the user-facing hourly price for a candidate.

    Prefers total_price_usd (which includes Databricks DBU cost when present)
    over the raw Azure VM price_usd.
    """
    if candidate.total_price_usd is not None:
        return candidate.total_price_usd
    return candidate.price_usd
