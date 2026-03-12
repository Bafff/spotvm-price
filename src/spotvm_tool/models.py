from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional


PerformanceBasis = Literal["coremark", "heuristic"]


@dataclass
class PlacementScoreResult:
    region: str
    vm_size: str
    placement_score: Optional[str]
    quota_available: Optional[bool]
    availability_zone: Optional[str] = None
    error_detail: Optional[str] = None


@dataclass
class HistoricalMetrics:
    region: str
    vm_size: str
    price_usd: Optional[float]
    price_last_updated: Optional[datetime]
    eviction_rate: Optional[float]
    eviction_last_updated: Optional[datetime]


@dataclass
class CandidateInsight:
    region: str
    vm_size: str
    placement_score: Optional[str]
    quota_available: Optional[bool]
    price_usd: Optional[float]
    price_last_updated: Optional[datetime]
    eviction_rate: Optional[float]
    eviction_last_updated: Optional[datetime]
    availability_zone: Optional[str] = None
    recommendation_rank: Optional[int] = None
    notes: Optional[str] = None
    performance_relative: Optional[float] = None  # % relative to baseline
    price_per_performance: Optional[float] = None  # USD per performance unit
    performance_basis: Optional[PerformanceBasis] = None
    performance_note: Optional[str] = None
    cpu_arch: Optional[str] = None  # "x64" or "arm"
    coremark_score: Optional[int] = None  # CoreMark benchmark score
    coremark_per_vcpu: Optional[float] = None  # CoreMark per vCPU (efficiency metric)
