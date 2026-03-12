from __future__ import annotations

import csv
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, List

import wcwidth
from colorama import Fore, Style, init

from .models import CandidateInsight

# Initialize colorama for cross-platform color support
init(autoreset=True)

# Global flag to enable/disable colors (can be controlled via CLI)
_COLORS_ENABLED = sys.stdout.isatty()  # Auto-detect TTY for CI/CD compatibility


def set_colors_enabled(enabled: bool) -> None:
    """Enable or disable colored output globally."""
    global _COLORS_ENABLED
    _COLORS_ENABLED = enabled


def _colorize_eviction(rate: float | None) -> str:
    """Colorize eviction rate based on risk level.

    Color scheme:
    - Blue (<5%): Excellent - very low eviction risk
    - Green (5-10%): Good - low eviction risk
    - Yellow (10-15%): Medium - moderate eviction risk
    - Red (15-24%): High - high eviction risk
    - Bright Red (≥25%): Critical - very high eviction risk
    """
    if rate is None or not _COLORS_ENABLED:
        return _format_percentage(rate)

    formatted = _format_percentage(rate)

    if rate < 5.0:
        return f"{Fore.BLUE}{formatted}{Style.RESET_ALL}"
    elif rate < 10.0:
        return f"{Fore.GREEN}{formatted}{Style.RESET_ALL}"
    elif rate < 15.0:
        return f"{Fore.YELLOW}{formatted}{Style.RESET_ALL}"
    elif rate < 25.0:
        return f"{Fore.RED}{formatted}{Style.RESET_ALL}"
    else:
        return f"{Fore.RED}{Style.BRIGHT}{formatted}{Style.RESET_ALL}"


def _colorize_placement(score: str | None) -> str:
    """Colorize placement score.

    Color scheme:
    - Green (High): Good capacity availability
    - Yellow (Medium): Moderate capacity availability
    - Red (Low): Limited capacity availability
    """
    if score is None or not _COLORS_ENABLED:
        return score or "N/A"

    if score == "High":
        return f"{Fore.GREEN}{score}{Style.RESET_ALL}"
    elif score == "Medium":
        return f"{Fore.YELLOW}{score}{Style.RESET_ALL}"
    elif score == "Low":
        return f"{Fore.RED}{score}{Style.RESET_ALL}"
    else:
        return score


def _format_cpu(vm_size: str | None) -> str:
    """Format CPU vendor with colored emoji or plain text.

    When colors enabled (default):
    - 🟦 for Intel Xeon
    - 🟥 for AMD EPYC
    - 🟩 for ARM (Ampere/Cobalt)

    When colors disabled (--no-color):
    - "Intel" for Intel Xeon
    - "AMD" for AMD EPYC
    - "ARM" for ARM

    Args:
        vm_size: Azure VM SKU name (e.g., "Standard_D4as_v5")

    Returns:
        Formatted CPU vendor string
    """
    if vm_size is None:
        return "-"

    from .vm_specs import detect_cpu_vendor

    vendor = detect_cpu_vendor(vm_size)

    if _COLORS_ENABLED:
        # Colored emoji squares
        if vendor == "intel":
            return "🟦"  # Blue square
        elif vendor == "amd":
            return "🟥"  # Red square
        elif vendor == "arm":
            return "🟩"  # Green square
        else:
            return vendor
    else:
        # Plain text for CSV/CI/CD/--no-color
        return vendor.upper()


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes (colors) from text for width calculation."""
    ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
    return ansi_escape.sub('', text)


def _display_width(text: str) -> int:
    """Calculate display width of text using wcwidth for proper emoji/wide char handling.

    Strips ANSI color codes before calculation as they don't occupy visual space.
    """
    stripped = _strip_ansi(text)
    width = wcwidth.wcswidth(stripped)
    if width < 0:
        return len(stripped)
    return width


TABLE_COLUMNS = [
    "Rank",
    "Region",
    "Zone",
    "VM Size",
    "CPU",
    "Placement",
    "Quota",
    "Price (USD/hr)",
    "Eviction %",
    "Perf %",
    "Price/Perf",
    "CoreMark",
    "CM/vCPU",
    "Price Updated",
    "Notes",
]


def render_table(
    candidates: Iterable[CandidateInsight],
    show_placement: bool = True,
    show_baseline: bool = True,
) -> str:
    # Determine which columns to hide based on mode
    hidden = set()
    if not show_placement:
        hidden |= {"Placement", "Quota"}
    if not show_baseline:
        hidden |= {"Perf %", "Price/Perf"}
    columns = [c for c in TABLE_COLUMNS if c not in hidden]

    rows: List[List[str]] = [columns]
    for item in candidates:
        all_cells = {
            "Rank": _format_rank(item.recommendation_rank),
            "Region": item.region or "",
            "Zone": item.availability_zone or "",
            "VM Size": item.vm_size or "",
            "CPU": _format_cpu(item.vm_size),
            "Placement": _colorize_placement(item.placement_score) if item.placement_score else (item.notes or "N/A"),
            "Quota": _format_quota(item.quota_available),
            "Price (USD/hr)": _format_price(item.price_usd),
            "Eviction %": _colorize_eviction(item.eviction_rate),
            "Perf %": _format_performance(item.performance_relative),
            "Price/Perf": _format_price_per_perf(item.price_per_performance),
            "CoreMark": _format_coremark(item.coremark_score),
            "CM/vCPU": _format_coremark_per_vcpu(item.coremark_per_vcpu),
            "Price Updated": _format_dt(item.price_last_updated),
            "Notes": _format_table_notes(item),
        }
        rows.append([all_cells[c] for c in columns])

    # Auto-hide columns where every data row is empty or dash
    if len(rows) > 1:
        auto_hide = set()
        for col_idx, col_name in enumerate(columns):
            if all(
                _strip_ansi(rows[row_idx][col_idx]).strip() in ("", "-")
                for row_idx in range(1, len(rows))
            ):
                auto_hide.add(col_idx)
        if auto_hide:
            keep = [i for i in range(len(columns)) if i not in auto_hide]
            columns = [columns[i] for i in keep]
            rows = [[row[i] for i in keep] for row in rows]

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
        return "Yes" if not _COLORS_ENABLED else "✅ Yes"
    if value is False:
        return "No" if not _COLORS_ENABLED else "❌ No"
    return "Unknown" if not _COLORS_ENABLED else "❓ Unknown"


def _format_price(value: float | None) -> str:
    if value is None:
        return "-"
    return f"${value:0.4f}"


def _format_percentage(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}%"


def _format_dt(value: datetime | None) -> str:
    """Format datetime as date only (YYYY-MM-DD) without time/timezone."""
    if value is None:
        return "-"
    return value.strftime('%Y-%m-%d')


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


def _format_coremark(value: int | None) -> str:
    """Format CoreMark score with thousands separator."""
    if value is None:
        return "-"
    return f"{value:,}"


def _format_coremark_per_vcpu(value: float | None) -> str:
    """Format CoreMark per vCPU (efficiency metric)."""
    if value is None:
        return "-"
    return f"{value:,.0f}"


def _format_table_notes(item: CandidateInsight) -> str:
    """Keep the terminal table compact and refer detailed perf fallback text to the footer."""
    parts: List[str] = []
    if item.notes:
        parts.append(item.notes)
    if item.performance_note and item.performance_basis == "heuristic":
        parts.append("Heuristic perf*")
    return "; ".join(dict.fromkeys(parts))


def _format_notes(item: CandidateInsight) -> str:
    """Join full analysis notes for exported artifacts."""
    parts: List[str] = []
    for note in (item.notes, item.performance_note):
        if note and note not in parts:
            parts.append(note)
    return "; ".join(parts)


CSV_COLUMNS = [
    "Rank",
    "Region",
    "Availability Zone",
    "VM Size",
    "CPU Vendor",
    "Placement Score",
    "Quota Available",
    "Price (USD/hr)",
    "Eviction Rate (%)",
    "Performance (%)",
    "Price per Performance",
    "CoreMark Score",
    "CoreMark per vCPU",
    "Price Last Updated",
    "Notes",
]

# Columns tied to specific modes
_CSV_PLACEMENT_COLS = {"Placement Score", "Quota Available"}
_CSV_BASELINE_COLS = {"Performance (%)", "Price per Performance"}


def export_to_csv(
    candidates: Iterable[CandidateInsight],
    csv_path: Path,
    show_placement: bool = True,
    show_baseline: bool = True,
) -> None:
    """Export candidate insights to CSV file for Excel/Google Sheets."""
    from .vm_specs import detect_cpu_vendor

    hidden = set()
    if not show_placement:
        hidden |= _CSV_PLACEMENT_COLS
    if not show_baseline:
        hidden |= _CSV_BASELINE_COLS
    columns = [c for c in CSV_COLUMNS if c not in hidden]

    rows: List[List[str]] = []
    for item in candidates:
        vendor = detect_cpu_vendor(item.vm_size) if item.vm_size else ""
        vendor_text = vendor.upper() if vendor else ""

        all_cells = {
            "Rank": str(item.recommendation_rank) if item.recommendation_rank is not None else "",
            "Region": item.region or "",
            "Availability Zone": item.availability_zone or "",
            "VM Size": item.vm_size or "",
            "CPU Vendor": vendor_text,
            "Placement Score": item.placement_score or (item.notes or "N/A"),
            "Quota Available": _csv_format_quota(item.quota_available),
            "Price (USD/hr)": _csv_format_price(item.price_usd),
            "Eviction Rate (%)": _csv_format_percentage(item.eviction_rate),
            "Performance (%)": _csv_format_performance(item.performance_relative),
            "Price per Performance": _csv_format_price_per_perf(item.price_per_performance),
            "CoreMark Score": _csv_format_coremark(item.coremark_score),
            "CoreMark per vCPU": _csv_format_coremark_per_vcpu(item.coremark_per_vcpu),
            "Price Last Updated": _csv_format_datetime(item.price_last_updated),
            "Notes": _format_notes(item),
        }
        rows.append([all_cells[c] for c in columns])

    with csv_path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(columns)
        for row in rows:
            writer.writerow(row)


def _csv_format_quota(value: bool | None) -> str:
    """Format quota for CSV (text-only, no emojis)."""
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    return "Unknown"


def _csv_format_price(value: float | None) -> str:
    """Format price for CSV (numeric value without $ symbol for Excel sorting)."""
    if value is None:
        return ""
    return f"{value:.4f}"


def _csv_format_percentage(value: float | None) -> str:
    """Format percentage for CSV (numeric value without % symbol for Excel sorting)."""
    if value is None:
        return ""
    return f"{value:.1f}"


def _csv_format_performance(value: float | None) -> str:
    """Format performance percentage for CSV."""
    if value is None:
        return ""
    return f"{value:.0f}"


def _csv_format_price_per_perf(value: float | None) -> str:
    """Format price per performance for CSV."""
    if value is None:
        return ""
    return f"{value:.6f}"


def _csv_format_datetime(value: datetime | None) -> str:
    """Format datetime for CSV (ISO format for Excel compatibility)."""
    if value is None:
        return ""
    return value.isoformat()


def _csv_format_coremark(value: int | None) -> str:
    """Format CoreMark score for CSV (numeric value for Excel sorting)."""
    if value is None:
        return ""
    return str(value)


def _csv_format_coremark_per_vcpu(value: float | None) -> str:
    """Format CoreMark per vCPU for CSV (numeric value for Excel sorting)."""
    if value is None:
        return ""
    return f"{value:.0f}"
