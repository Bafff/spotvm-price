from __future__ import annotations

import csv
import re
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

import wcwidth
from colorama import Fore, Style, init

from .models import CandidateInsight


@dataclass(frozen=True)
class RenderOptions:
    colors_enabled: bool


def initialize_color_output() -> None:
    """Initialize terminal color support explicitly from the CLI entry path."""
    init(autoreset=True)


def _resolve_render_options(render_options: RenderOptions | None) -> RenderOptions:
    if render_options is not None:
        return render_options
    return RenderOptions(colors_enabled=sys.stdout.isatty())


def _colorize_eviction(rate: float | None, *, render_options: RenderOptions | None = None) -> str:
    """Colorize eviction rate based on risk level.

    Color scheme:
    - Blue (<5%): Excellent - very low eviction risk
    - Green (5-10%): Good - low eviction risk
    - Yellow (10-15%): Medium - moderate eviction risk
    - Red (15-24%): High - high eviction risk
    - Bright Red (≥25%): Critical - very high eviction risk
    """
    options = _resolve_render_options(render_options)
    if rate is None or not options.colors_enabled:
        return _format_percentage(rate)

    formatted = _format_percentage(rate)

    if rate < 5.0:
        return f"{Fore.BLUE}{formatted}{Style.RESET_ALL}"
    if rate < 10.0:
        return f"{Fore.GREEN}{formatted}{Style.RESET_ALL}"
    if rate < 15.0:
        return f"{Fore.YELLOW}{formatted}{Style.RESET_ALL}"
    if rate < 25.0:
        return f"{Fore.RED}{formatted}{Style.RESET_ALL}"
    return f"{Fore.RED}{Style.BRIGHT}{formatted}{Style.RESET_ALL}"


def _colorize_placement(score: str | None, *, render_options: RenderOptions | None = None) -> str:
    """Colorize placement score.

    Color scheme:
    - Green (High): Good capacity availability
    - Yellow (Medium): Moderate capacity availability
    - Red (Low): Limited capacity availability
    """
    options = _resolve_render_options(render_options)
    if score is None or not options.colors_enabled:
        return score or "N/A"

    if score == "High":
        return f"{Fore.GREEN}{score}{Style.RESET_ALL}"
    if score == "Medium":
        return f"{Fore.YELLOW}{score}{Style.RESET_ALL}"
    if score == "Low":
        return f"{Fore.RED}{score}{Style.RESET_ALL}"
    return score


def _format_cpu(vm_size: str | None, *, render_options: RenderOptions | None = None) -> str:
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
    options = _resolve_render_options(render_options)

    if options.colors_enabled:
        # Colored emoji squares
        if vendor == "intel":
            return "🟦"  # Blue square
        if vendor == "amd":
            return "🟥"  # Red square
        if vendor == "arm":
            return "🟩"  # Green square
        return vendor
    # Plain text for CSV/CI/CD/--no-color
    return vendor.upper()


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes (colors) from text for width calculation."""
    ansi_escape = re.compile(r"\x1b\[[0-9;]*m")
    return ansi_escape.sub("", text)


def _display_width(text: str) -> int:
    """Calculate display width of text using wcwidth for proper emoji/wide char handling.

    Strips ANSI color codes before calculation as they don't occupy visual space.
    """
    stripped = _strip_ansi(text)
    width = wcwidth.wcswidth(stripped)
    if width < 0:
        return len(stripped)
    return cast(int, width)


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

_DATABRICKS_TABLE_COLUMNS = [
    "VM (USD/hr)",
    "DBU/h",
    "DB Cost",
    "Photon DBU/h",
    "Photon Cost",
    "Total Cost",
    "Catalog Updated",
]


def render_table(
    candidates: Iterable[CandidateInsight],
    show_placement: bool = True,
    show_baseline: bool = True,
    show_databricks: bool = False,
    show_photon: bool = False,
    render_options: RenderOptions | None = None,
) -> str:
    options = _resolve_render_options(render_options)
    # Determine which columns to hide based on mode
    hidden = set()
    if not show_placement:
        hidden |= {"Placement", "Quota"}
    if not show_baseline:
        hidden |= {"Perf %", "Price/Perf"}
    if not show_photon:
        hidden |= {"Photon DBU/h", "Photon Cost"}
    columns = [c for c in TABLE_COLUMNS if c not in hidden]
    if show_databricks:
        columns += [c for c in _DATABRICKS_TABLE_COLUMNS if c not in hidden]

    rows: list[list[str]] = [columns]
    for item in candidates:
        all_cells = {
            "Rank": _format_rank(item.recommendation_rank),
            "Region": item.region or "",
            "Zone": item.availability_zone or "",
            "VM Size": item.vm_size or "",
            "CPU": _format_cpu(item.vm_size, render_options=options),
            "Placement": (
                _colorize_placement(item.placement_score, render_options=options)
                if item.placement_score
                else (item.notes or "N/A")
            ),
            "Quota": _format_quota(item.quota_available, render_options=options),
            "Price (USD/hr)": _format_price(item.price_usd),
            "Eviction %": _colorize_eviction(item.eviction_rate, render_options=options),
            "Perf %": _format_performance(item.performance_relative),
            "Price/Perf": _format_price_per_perf(item.price_per_performance),
            "CoreMark": _format_coremark(item.coremark_score),
            "CM/vCPU": _format_coremark_per_vcpu(item.coremark_per_vcpu),
            "Price Updated": _format_dt(item.price_last_updated),
            "Notes": _format_table_notes(item),
            "VM (USD/hr)": _format_price(item.compute_price_usd),
            "DBU/h": _format_number(item.databricks_dbu_per_hour),
            "DB Cost": _format_price(item.databricks_dbu_cost_usd),
            "Photon DBU/h": _format_number(item.databricks_photon_dbu_per_hour),
            "Photon Cost": _format_price(item.databricks_photon_cost_usd),
            "Total Cost": _format_price(item.total_price_usd),
            "Catalog Updated": _format_catalog_updated(item.databricks_catalog_updated),
        }
        rows.append([all_cells[c] for c in columns])

    # Auto-hide columns where every data row is empty or dash
    if len(rows) > 1:
        auto_hide = set()
        for col_idx, _col_name in enumerate(columns):
            if all(_strip_ansi(rows[row_idx][col_idx]).strip() in ("", "-") for row_idx in range(1, len(rows))):
                auto_hide.add(col_idx)
        if auto_hide:
            keep = [i for i in range(len(columns)) if i not in auto_hide]
            columns = [columns[i] for i in keep]
            rows = [[row[i] for i in keep] for row in rows]

    col_widths = _compute_widths(rows)
    lines = [_format_row(row, col_widths) for row in rows]
    separator = "-" * len(lines[0])
    return "\n".join([lines[0], separator, *lines[1:]])


def _compute_widths(rows: list[list[str]]) -> list[int]:
    """Compute maximum display width for each column, accounting for emoji."""
    return [max(_display_width(row[idx]) for row in rows) for idx in range(len(rows[0]))]


def _format_row(row: list[str], widths: list[int]) -> str:
    """Format row with proper spacing, accounting for emoji taking 2 columns."""
    formatted_cells = []
    for idx, cell in enumerate(row):
        display_width = _display_width(cell)
        padding = widths[idx] - display_width
        formatted_cells.append(cell + " " * padding)
    return " | ".join(formatted_cells)


def _format_rank(rank: int | None) -> str:
    return str(rank) if rank is not None else "-"


def _format_quota(value: bool | None, *, render_options: RenderOptions | None = None) -> str:
    options = _resolve_render_options(render_options)
    if value is True:
        return "Yes" if not options.colors_enabled else "✅ Yes"
    if value is False:
        return "No" if not options.colors_enabled else "❌ No"
    return "Unknown" if not options.colors_enabled else "❓ Unknown"


def _format_price(value: float | None) -> str:
    if value is None:
        return "-"
    return f"${value:0.4f}"


def _format_number(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:g}"


def _format_percentage(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}%"


def _format_dt(value: datetime | None) -> str:
    """Format datetime as date only (YYYY-MM-DD) without time/timezone."""
    if value is None:
        return "-"
    return value.strftime("%Y-%m-%d")


def _format_catalog_updated(value: str | None) -> str:
    if not value:
        return "-"
    return value[:10] if len(value) >= 10 else value


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
    parts: list[str] = []
    if item.notes:
        parts.append(item.notes)
    if item.performance_note and item.performance_basis == "heuristic":
        parts.append("Heuristic perf*")
    return "; ".join(dict.fromkeys(parts))


def _format_notes(item: CandidateInsight) -> str:
    """Join full analysis notes for exported artifacts."""
    parts: list[str] = []
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

_DATABRICKS_CSV_COLUMNS = [
    "VM Price (USD/hr)",
    "DBU per Hour",
    "Databricks Cost (USD/hr)",
    "Photon DBU per Hour",
    "Photon Cost (USD/hr)",
    "Total Cost (USD/hr)",
    "Databricks Catalog Updated",
]

# Columns tied to specific modes
_CSV_PLACEMENT_COLS = {"Placement Score", "Quota Available"}
_CSV_BASELINE_COLS = {"Performance (%)", "Price per Performance"}
_CSV_PHOTON_COLS = {"Photon DBU per Hour", "Photon Cost (USD/hr)"}


def export_to_csv(
    candidates: Iterable[CandidateInsight],
    csv_path: Path,
    show_placement: bool = True,
    show_baseline: bool = True,
    show_databricks: bool = False,
    show_photon: bool = False,
) -> None:
    """Export candidate insights to CSV file for Excel/Google Sheets."""
    from .projection import project_for_csv
    from .vm_specs import detect_cpu_vendor

    hidden = set()
    if not show_placement:
        hidden |= _CSV_PLACEMENT_COLS
    if not show_baseline:
        hidden |= _CSV_BASELINE_COLS
    if not show_photon:
        hidden |= _CSV_PHOTON_COLS
    columns = [c for c in CSV_COLUMNS if c not in hidden]
    if show_databricks:
        columns += [c for c in _DATABRICKS_CSV_COLUMNS if c not in hidden]

    formatters = {
        "quota": _csv_format_quota,
        "price": _csv_format_price,
        "numeric": _csv_format_number,
        "percentage": _csv_format_percentage,
        "performance": _csv_format_performance,
        "price_per_perf": _csv_format_price_per_perf,
        "coremark": _csv_format_coremark,
        "coremark_per_vcpu": _csv_format_coremark_per_vcpu,
        "datetime": _csv_format_datetime,
        "text": _csv_format_text,
    }

    rows: list[list[str]] = []
    for item in candidates:
        vendor = detect_cpu_vendor(item.vm_size) if item.vm_size else ""
        vendor_text = vendor.upper() if vendor else ""

        all_cells = project_for_csv(
            item,
            vendor_text,
            formatters,
            _format_notes,
            show_databricks=show_databricks,
            show_photon=show_photon,
        )
        rows.append([all_cells[c] for c in columns])

    _write_csv_atomic(csv_path, columns, rows)


def _write_csv_atomic(csv_path: Path, columns: list[str], rows: list[list[str]]) -> None:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            newline="",
            encoding="utf-8",
            dir=csv_path.parent,
            prefix=f".{csv_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as csvfile:
            temp_path = Path(csvfile.name)
            writer = csv.writer(csvfile)
            writer.writerow(columns)
            for row in rows:
                writer.writerow(row)
        temp_path.replace(csv_path)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


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


def _csv_format_number(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:g}"


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


def _csv_format_text(value: str | None) -> str:
    return value or ""


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
