from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

PerformanceBasis = Literal["coremark", "heuristic"]
CPUArchitecture = Literal["x64", "arm"]
SortOrder = Literal["price", "price-per-vcpu", "eviction"]
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
    """Unified candidate row used across ranking, reporting, and saved history.

    Databricks fields follow two intentional groups:
    - `compute_price_usd` keeps the raw Azure VM hourly price when Databricks
      enrichment ran.
    - `total_price_usd` holds the comparable ranked/display price only when a
      full Databricks-aware total could be computed.

    When Databricks enrichment runs but `total_price_usd` stays `None`,
    reporting may still show the raw VM price via `compute_price_usd`, but
    ranking and `--max-price` must treat the candidate as non-comparable.
    """

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
    compute_price_usd: float | None = None  # Raw Azure VM hourly price when Databricks enrichment ran
    databricks_dbu_per_hour: float | None = None  # Base DBU rate from the vendored catalog
    databricks_dbu_cost_usd: float | None = None  # Base DBU hourly cost using dbu_unit_price_usd
    databricks_photon_dbu_per_hour: float | None = None  # Derived Photon DBU rate for Photon-capable SKUs
    databricks_photon_cost_usd: float | None = None  # Photon hourly cost using photon_dbu_unit_price_usd
    total_price_usd: float | None = None  # Comparable total used for ranking/filtering when fully known
    databricks_catalog_updated: datetime | None = None  # Vendored Databricks catalog snapshot timestamp

    @property
    def effective_price_usd(self) -> float | None:
        """Return the comparable user-facing price for ranking and display."""
        if self.total_price_usd is not None:
            return self.total_price_usd
        if self.compute_price_usd is not None:
            return None
        return self.price_usd


def effective_price_usd(candidate: CandidateInsight) -> float | None:
    """Return the user-facing hourly price for a candidate.

    Prefers total_price_usd (which includes Databricks DBU cost when present)
    over the raw Azure VM price_usd. When Databricks enrichment ran but could
    not compute a comparable total price, intentionally returns None instead of
    falling back to the raw VM price. This preserves comparable-total semantics
    for ranking and `--max-price` filtering while still allowing reporting to
    show `compute_price_usd` separately.
    """
    return candidate.effective_price_usd
