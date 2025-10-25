from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


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
