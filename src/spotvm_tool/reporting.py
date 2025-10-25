from __future__ import annotations

import unicodedata
from datetime import datetime
from typing import Iterable, List

from .models import CandidateInsight


def _display_width(text: str) -> int:
    """Calculate display width of text, accounting for emoji taking 2 columns."""
    width = 0
    for char in text:
        if unicodedata.east_asian_width(char) in ('F', 'W'):
            width += 2  # Full-width characters
        elif unicodedata.category(char) == 'So':  # Symbol, Other (includes emoji)
            width += 2
        else:
            width += 1
    return width


TABLE_COLUMNS = [
    "Rank",
    "Region",
    "Zone",
    "VM Size",
    "Placement",
    "Quota",
    "Price (USD/hr)",
    "Eviction %",
    "Perf %",
    "Price/Perf",
    "Price Updated",
    "Eviction Updated",
    "Notes",
]


def render_table(candidates: Iterable[CandidateInsight]) -> str:
    rows: List[List[str]] = [TABLE_COLUMNS]
    for item in candidates:
        rows.append(
            [
                _format_rank(item.recommendation_rank),
                item.region or "",
                item.availability_zone or "",
                item.vm_size or "",
                item.placement_score or (item.notes or "N/A"),
                _format_quota(item.quota_available),
                _format_price(item.price_usd),
                _format_percentage(item.eviction_rate),
                _format_performance(item.performance_relative),
                _format_price_per_perf(item.price_per_performance),
                _format_dt(item.price_last_updated),
                _format_dt(item.eviction_last_updated),
                item.notes or "",
            ]
        )
    col_widths = _compute_widths(rows)
    lines = [
        _format_row(row, col_widths)
        for row in rows
    ]
    separator = "-" * len(lines[0])
    return "\n".join([lines[0], separator, *lines[1:]])


def _compute_widths(rows: List[List[str]]) -> List[int]:
    """Compute maximum display width for each column, accounting for emoji."""
    return [max(_display_width(row[idx]) for row in rows) for idx in range(len(rows[0]))]


def _format_row(row: List[str], widths: List[int]) -> str:
    """Format row with proper spacing, accounting for emoji taking 2 columns."""
    formatted_cells = []
    for idx, cell in enumerate(row):
        display_width = _display_width(cell)
        padding = widths[idx] - display_width
        formatted_cells.append(cell + " " * padding)
    return " | ".join(formatted_cells)


def _format_rank(rank: int | None) -> str:
    return str(rank) if rank is not None else "-"


def _format_quota(value: bool | None) -> str:
    if value is True:
        return "✅ Yes"
    if value is False:
        return "❌ No"
    return "❓ Unknown"


def _format_price(value: float | None) -> str:
    if value is None:
        return "-"
    return f"${value:0.4f}"


def _format_percentage(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}%"


def _format_dt(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.isoformat(timespec="minutes")


def _format_performance(value: float | None) -> str:
    """Format performance percentage relative to baseline."""
    if value is None:
        return "-"
    return f"{value:.0f}%"


def _format_price_per_perf(value: float | None) -> str:
    """Format price per performance unit."""
    if value is None:
        return "-"
    return f"${value:.6f}"
