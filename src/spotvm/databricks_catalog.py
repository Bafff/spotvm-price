"""Databricks pricing catalog loaders and validation helpers.

This module uses two vendored data sources:
- `databricks_pricing.json` for pricing-profile metadata, per-DBU unit prices,
  and validated snapshot entries
- `databricks_azure_dbu_pricing.csv` for broad Azure node-type DBU coverage used
  at runtime during SKU enrichment
"""

from __future__ import annotations

import csv
import json
import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from functools import cache
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import Any


class DatabricksCatalogError(RuntimeError):
    pass


logger = logging.getLogger("spotvm")


def _require_positive_finite(value: float, name: str) -> None:
    """Validate that a float field is finite and strictly positive."""
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if value <= 0.0:
        raise ValueError(f"{name} must be positive")


@dataclass(frozen=True)
class DatabricksPricingProfile:
    name: str
    dbu_unit_price_usd: float
    photon_dbu_unit_price_usd: float

    def __post_init__(self) -> None:
        normalized_name = self.name.strip()
        object.__setattr__(self, "name", normalized_name)
        if not normalized_name:
            raise ValueError("name must be non-empty")
        _require_positive_finite(self.dbu_unit_price_usd, "dbu_unit_price_usd")
        _require_positive_finite(self.photon_dbu_unit_price_usd, "photon_dbu_unit_price_usd")


@dataclass(frozen=True)
class DatabricksCatalogEntry:
    """Manual JSON snapshot entry used for validation, metadata, and unit prices.

    Runtime VM enrichment uses the vendored Azure CSV because it has the broadest
    Azure SKU coverage. The JSON entry list remains a validated reference
    snapshot rather than the authoritative VM-size lookup table for all SKUs.
    Photon per-SKU rates here are reference snapshot values only. Runtime
    enrichment does not consume this field; it derives Photon totals from the
    CSV base DBU rate and the shared Photon Jobs multiplier.
    """

    sku: str
    dbu_per_hour: float
    photon_dbu_per_hour: float | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        normalized_sku = self.sku.strip()
        object.__setattr__(self, "sku", normalized_sku)
        if not normalized_sku:
            raise ValueError("sku must be non-empty")
        _require_positive_finite(self.dbu_per_hour, "dbu_per_hour")
        if self.photon_dbu_per_hour is not None:
            _require_positive_finite(self.photon_dbu_per_hour, "photon_dbu_per_hour")


@dataclass(frozen=True)
class AzureNodeTypePricingRow:
    node_type_id: str
    category: str | None
    num_cores: int | None
    memory_gb: float | None
    dbu_per_hour: float | None
    local_disk_gb: int | None
    num_gpus: int | None
    photon_capable: bool | None
    deprecated: bool | None

    def __post_init__(self) -> None:
        normalized_node_type_id = self.node_type_id.strip()
        object.__setattr__(self, "node_type_id", normalized_node_type_id)
        if not normalized_node_type_id:
            raise ValueError("node_type_id must be non-empty")
        if self.num_cores is not None and self.num_cores <= 0:
            raise ValueError("num_cores must be positive")
        if self.memory_gb is not None:
            _require_positive_finite(self.memory_gb, "memory_gb")
        if self.local_disk_gb is not None and self.local_disk_gb < 0:
            raise ValueError("local_disk_gb must be non-negative")
        if self.num_gpus is not None and self.num_gpus < 0:
            raise ValueError("num_gpus must be non-negative")
        if self.dbu_per_hour is not None:
            _require_positive_finite(self.dbu_per_hour, "dbu_per_hour")


@dataclass(frozen=True, init=False)
class DatabricksCatalog:
    catalog_version: int
    cloud: str
    pricing_profile: DatabricksPricingProfile
    captured_at: datetime
    source: Mapping[str, str]
    entries: tuple[DatabricksCatalogEntry, ...]

    def __init__(
        self,
        catalog_version: int,
        cloud: str,
        pricing_profile: DatabricksPricingProfile,
        captured_at: datetime | str,
        source: Mapping[str, str],
        entries: tuple[DatabricksCatalogEntry, ...],
    ) -> None:
        object.__setattr__(self, "catalog_version", catalog_version)
        object.__setattr__(self, "cloud", cloud)
        object.__setattr__(self, "pricing_profile", pricing_profile)
        object.__setattr__(self, "captured_at", _coerce_catalog_timestamp(captured_at))
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "entries", entries)
        self.__post_init__()

    def __post_init__(self) -> None:
        if self.catalog_version <= 0:
            raise ValueError("catalog_version must be positive")
        if not self.cloud:
            raise ValueError("cloud must be non-empty")
        if not isinstance(self.source, Mapping):
            raise TypeError("source must be a mapping of string keys and values")
        if not all(isinstance(key, str) and isinstance(value, str) for key, value in self.source.items()):
            raise TypeError("source must be a mapping of string keys and values")
        normalized_source = MappingProxyType(dict(self.source))
        object.__setattr__(self, "source", normalized_source)
        sorted_skus = tuple(entry.sku for entry in self.entries)
        if sorted_skus != tuple(sorted(sorted_skus)):
            raise ValueError("entries must be sorted by sku")
        if len(sorted_skus) != len(set(sorted_skus)):
            raise ValueError("entries must not contain duplicate sku values")

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_version": self.catalog_version,
            "cloud": self.cloud,
            "pricing_profile": asdict(self.pricing_profile),
            "captured_at": _format_catalog_timestamp(self.captured_at),
            "source": dict(self.source),
            "entries": [asdict(entry) for entry in self.entries],
        }


def load_catalog() -> DatabricksCatalog:
    path = resources.files("spotvm").joinpath("data/databricks_pricing.json")
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DatabricksCatalogError("Failed to load vendored Databricks catalog") from exc
    return _catalog_from_text(raw_text, source_label="vendored Databricks catalog")


def load_catalog_from_path(path: Path) -> DatabricksCatalog:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DatabricksCatalogError(f"Failed to read Databricks catalog: {path}") from exc
    return _catalog_from_text(raw_text, source_label=f"Databricks catalog at {path}")


def load_azure_dbu_pricing_rows() -> list[AzureNodeTypePricingRow]:
    return list(_load_azure_dbu_pricing_rows())


def load_azure_dbu_pricing_last_updated() -> datetime:
    """Return the vendored JSON snapshot timestamp that accompanies the CSV DBU data."""
    return load_catalog().captured_at


@cache
def _load_azure_dbu_pricing_rows() -> tuple[AzureNodeTypePricingRow, ...]:
    path = resources.files("spotvm").joinpath("data/databricks_azure_dbu_pricing.csv")
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DatabricksCatalogError("Failed to load vendored Azure DBU pricing CSV") from exc

    reader = csv.DictReader(raw_text.splitlines())
    _validate_azure_dbu_csv_headers(reader.fieldnames)
    rows: list[AzureNodeTypePricingRow] = []
    skipped_blank_node_type_id = 0
    skipped_blank_node_type_id_rows: list[int] = []
    skipped_default_stub_rows = 0
    skipped_default_stub_examples: list[str] = []
    for row_number, item in enumerate(reader, start=2):
        node_type_id = (item.get("node_type_id") or "").strip()
        if not node_type_id:
            skipped_blank_node_type_id += 1
            if len(skipped_blank_node_type_id_rows) < 5:
                skipped_blank_node_type_id_rows.append(row_number)
            continue

        category = _optional_str(item.get("category"))
        num_cores = _optional_int(item.get("num_cores"), row_number=row_number, column_name="num_cores")
        dbu_per_hour = _optional_float(
            item.get("dbu_per_hour"),
            row_number=row_number,
            column_name="dbu_per_hour",
        )

        # The browser extraction includes placeholder rows that only carry the
        # node_type_id plus a default dbu_per_hour of 1. Those rows skew runtime
        # ranking badly (for example D16as_v6) and should fall through to the
        # "DBU data not available" path instead of being treated as real pricing.
        # Keep blank-metadata rows when they carry a specific non-default rate,
        # because the vendored catalog also contains legitimate pricing in that
        # shape (for example DS14=4 and DS3=0.75).
        if category is None and num_cores is None and dbu_per_hour == 1.0:
            skipped_default_stub_rows += 1
            if len(skipped_default_stub_examples) < 5:
                skipped_default_stub_examples.append(node_type_id)
            continue

        rows.append(
            AzureNodeTypePricingRow(
                node_type_id=node_type_id,
                category=category,
                num_cores=num_cores,
                memory_gb=_optional_float(item.get("memory_gb"), row_number=row_number, column_name="memory_gb"),
                dbu_per_hour=dbu_per_hour,
                local_disk_gb=_optional_int(
                    item.get("local_disk_gb"), row_number=row_number, column_name="local_disk_gb"
                ),
                num_gpus=_optional_int(item.get("num_gpus"), row_number=row_number, column_name="num_gpus"),
                photon_capable=_optional_bool(
                    item.get("photon_capable"),
                    row_number=row_number,
                    column_name="photon_capable",
                ),
                deprecated=_optional_bool(item.get("deprecated"), row_number=row_number, column_name="deprecated"),
            )
        )
    if skipped_blank_node_type_id > 0:
        logger.warning(
            "Skipped %d Azure Databricks DBU pricing row(s) with blank node_type_id (rows: %s)",
            skipped_blank_node_type_id,
            ", ".join(str(row) for row in skipped_blank_node_type_id_rows),
        )
    if skipped_default_stub_rows > 0:
        logger.warning(
            "Skipped %d Azure Databricks DBU pricing row(s) missing category and num_cores with default dbu_per_hour=1 "
            "(likely placeholder data): %s%s",
            skipped_default_stub_rows,
            ", ".join(skipped_default_stub_examples),
            " ..." if skipped_default_stub_rows > 5 else "",
        )
    if not rows:
        logger.warning("Loaded 0 usable Azure Databricks DBU pricing rows from %s", path)
        raise DatabricksCatalogError("Loaded 0 usable Azure Databricks DBU pricing rows from vendored catalog")
    return tuple(rows)


def lookup_azure_node_type_pricing(node_type_id: str) -> AzureNodeTypePricingRow | None:
    return _azure_dbu_pricing_index().get(node_type_id)


@cache
def _azure_dbu_pricing_index() -> dict[str, AzureNodeTypePricingRow]:
    # _load_azure_dbu_pricing_rows already raises if no usable rows are found
    return {row.node_type_id: row for row in _load_azure_dbu_pricing_rows()}


def refresh_databricks_catalog_cache() -> None:
    _load_azure_dbu_pricing_rows.cache_clear()
    _azure_dbu_pricing_index.cache_clear()


def refresh_catalog_instructions() -> str:
    return (
        "Manual refresh only.\n"
        "1. Open any Databricks workspace.\n"
        "2. Open Chrome DevTools and switch to the Console tab.\n"
        "3. Run JSON.stringify(window.settings['defaultNodeTypeToPricingUnitsMap']).\n"
        "4. Convert the extracted JSON map into the CSV layout at src/spotvm/data/databricks_azure_dbu_pricing.csv.\n"
        "5. See docs/databricks-dbu-pricing-refresh.md for the full procedure and multiplier notes."
    )


def _catalog_from_text(raw_text: str, *, source_label: str) -> DatabricksCatalog:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise DatabricksCatalogError(f"Failed to parse Databricks catalog from {source_label}") from exc
    if not isinstance(payload, dict):
        raise DatabricksCatalogError(f"Databricks catalog from {source_label} must be a JSON object")
    return _catalog_from_payload(payload)


def _catalog_from_payload(payload: dict[str, Any]) -> DatabricksCatalog:
    try:
        catalog_version = payload["catalog_version"]
        cloud = payload["cloud"]
        pricing_profile_data = payload["pricing_profile"]
        captured_at = payload["captured_at"]
        source = payload["source"]
        entries_data = payload["entries"]
    except KeyError as exc:
        raise DatabricksCatalogError(f"Databricks catalog is missing required field: {exc.args[0]}") from exc

    if not isinstance(pricing_profile_data, dict):
        raise DatabricksCatalogError("Databricks catalog pricing_profile must be an object")
    if not isinstance(source, dict):
        raise DatabricksCatalogError("Databricks catalog source must be an object")
    if not isinstance(entries_data, list):
        raise DatabricksCatalogError("Databricks catalog entries must be a list")

    dbu_unit_price_usd = _float_mapping_value(
        pricing_profile_data,
        "dbu_unit_price_usd",
        context="Databricks catalog pricing_profile",
    )
    photon_dbu_unit_price_usd = _float_mapping_value(
        pricing_profile_data,
        "photon_dbu_unit_price_usd",
        context="Databricks catalog pricing_profile",
    )
    pricing_profile_name = _string_mapping_value(
        pricing_profile_data,
        "name",
        context="Databricks catalog pricing_profile",
    )
    catalog_version_int = _int_value(catalog_version, context="Databricks catalog catalog_version")
    cloud_text = _string_value(cloud, context="Databricks catalog cloud")
    captured_at_text = _string_value(captured_at, context="Databricks catalog captured_at")
    captured_at_timestamp = _coerce_catalog_timestamp(captured_at_text)

    seen_skus: set[str] = set()
    entries: list[DatabricksCatalogEntry] = []
    for raw_entry in entries_data:
        if not isinstance(raw_entry, dict):
            raise DatabricksCatalogError("Each Databricks catalog entry must be an object")
        raw_sku = raw_entry.get("sku")
        if not isinstance(raw_sku, str) or not raw_sku.strip():
            raise DatabricksCatalogError("Each Databricks catalog entry requires a non-empty sku")
        sku = raw_sku.strip()
        if sku in seen_skus:
            raise DatabricksCatalogError(f"Duplicate Databricks catalog entry for SKU: {sku}")
        seen_skus.add(sku)
        entries.append(
            _catalog_entry(
                sku=sku,
                dbu_per_hour=_float_mapping_value(
                    raw_entry,
                    "dbu_per_hour",
                    context=f"Databricks catalog entry for SKU {sku}",
                ),
                photon_dbu_per_hour=(
                    _float_value(
                        photon_raw,
                        context=f"Databricks catalog entry for SKU {sku} photon_dbu_per_hour",
                    )
                    if (photon_raw := raw_entry.get("photon_dbu_per_hour")) is not None
                    else None
                ),
                notes=_string_optional_value(
                    raw_entry.get("notes"),
                    context=f"Databricks catalog entry for SKU {sku}.notes",
                ),
            )
        )
    entries.sort(key=lambda entry: entry.sku)
    return _catalog(
        catalog_version=catalog_version_int,
        cloud=cloud_text,
        pricing_profile=_pricing_profile(
            name=pricing_profile_name,
            dbu_unit_price_usd=dbu_unit_price_usd,
            photon_dbu_unit_price_usd=photon_dbu_unit_price_usd,
        ),
        captured_at=captured_at_timestamp,
        source=source,
        entries=tuple(entries),
    )


def _coerce_catalog_timestamp(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if not value:
        raise ValueError("captured_at must be non-empty")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("captured_at must be a valid ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _format_catalog_timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _optional_float(
    value: str | None,
    *,
    row_number: int,
    column_name: str,
) -> float | None:
    parsed = _optional_str(value)
    if parsed is None:
        return None
    try:
        return float(parsed)
    except ValueError as exc:
        raise DatabricksCatalogError(
            f"Invalid Azure DBU pricing CSV value at row {row_number}, column {column_name}: {parsed!r}"
        ) from exc


def _optional_int(
    value: str | None,
    *,
    row_number: int,
    column_name: str,
) -> int | None:
    parsed = _optional_str(value)
    if parsed is None:
        return None
    try:
        numeric_value = float(parsed)
    except ValueError as exc:
        raise DatabricksCatalogError(
            f"Invalid Azure DBU pricing CSV value at row {row_number}, column {column_name}: {parsed!r}"
        ) from exc
    if not numeric_value.is_integer():
        raise DatabricksCatalogError(
            f"Invalid Azure DBU pricing CSV value at row {row_number}, column {column_name}: {parsed!r}"
        )
    return int(numeric_value)


def _optional_bool(
    value: str | None,
    *,
    row_number: int,
    column_name: str,
) -> bool | None:
    parsed = _optional_str(value)
    if parsed is None:
        return None
    normalized = parsed.lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise DatabricksCatalogError(
        f"Invalid Azure DBU pricing CSV value at row {row_number}, column {column_name}: {parsed!r} (expected True or False)"
    )


def _required_mapping_value(mapping: dict[str, Any], key: str, *, context: str) -> Any:
    try:
        return mapping[key]
    except KeyError as exc:
        raise DatabricksCatalogError(f"{context} is missing required field: {key}") from exc


def _validate_azure_dbu_csv_headers(fieldnames: Sequence[str] | None) -> None:
    if fieldnames is None:
        raise DatabricksCatalogError("Azure DBU pricing CSV is empty")
    if "node_type_id" not in fieldnames:
        raise DatabricksCatalogError("Azure DBU pricing CSV is missing required header: node_type_id")


def _float_mapping_value(mapping: dict[str, Any], key: str, *, context: str) -> float:
    return _float_value(_required_mapping_value(mapping, key, context=context), context=f"{context}.{key}")


def _float_value(value: Any, *, context: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise DatabricksCatalogError(f"Invalid Databricks catalog value for {context}: {value!r}") from exc


def _int_value(value: Any, *, context: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise DatabricksCatalogError(f"Invalid Databricks catalog value for {context}: {value!r}") from exc


def _string_mapping_value(mapping: dict[str, Any], key: str, *, context: str) -> str:
    return _string_value(_required_mapping_value(mapping, key, context=context), context=f"{context}.{key}")


def _string_value(value: Any, *, context: str) -> str:
    if not isinstance(value, str):
        raise DatabricksCatalogError(f"Invalid Databricks catalog value for {context}: {value!r}")
    return value


def _string_optional_value(value: Any, *, context: str) -> str | None:
    if value is None:
        return None
    return _string_value(value, context=context)


def _pricing_profile(
    *, name: str, dbu_unit_price_usd: float, photon_dbu_unit_price_usd: float
) -> DatabricksPricingProfile:
    try:
        return DatabricksPricingProfile(
            name=name,
            dbu_unit_price_usd=dbu_unit_price_usd,
            photon_dbu_unit_price_usd=photon_dbu_unit_price_usd,
        )
    except ValueError as exc:
        raise DatabricksCatalogError(str(exc)) from exc


def _catalog_entry(
    *,
    sku: str,
    dbu_per_hour: float,
    photon_dbu_per_hour: float | None = None,
    notes: str | None = None,
) -> DatabricksCatalogEntry:
    try:
        return DatabricksCatalogEntry(
            sku=sku,
            dbu_per_hour=dbu_per_hour,
            photon_dbu_per_hour=photon_dbu_per_hour,
            notes=notes,
        )
    except ValueError as exc:
        raise DatabricksCatalogError(str(exc)) from exc


def _catalog(
    *,
    catalog_version: int,
    cloud: str,
    pricing_profile: DatabricksPricingProfile,
    captured_at: datetime,
    source: Mapping[str, str],
    entries: tuple[DatabricksCatalogEntry, ...],
) -> DatabricksCatalog:
    try:
        return DatabricksCatalog(
            catalog_version=catalog_version,
            cloud=cloud,
            pricing_profile=pricing_profile,
            captured_at=captured_at,
            source=source,
            entries=entries,
        )
    except (TypeError, ValueError) as exc:
        raise DatabricksCatalogError(str(exc)) from exc
