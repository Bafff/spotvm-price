from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any


class DatabricksCatalogError(RuntimeError):
    pass


@dataclass(frozen=True)
class DatabricksPricingProfile:
    name: str
    dbu_unit_price_usd: float
    photon_dbu_unit_price_usd: float


@dataclass(frozen=True)
class DatabricksCatalogEntry:
    sku: str
    dbu_per_hour: float
    photon_dbu_per_hour: float | None = None
    notes: str | None = None


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


@dataclass(frozen=True)
class DatabricksCatalog:
    catalog_version: int
    cloud: str
    pricing_profile: DatabricksPricingProfile
    captured_at: str
    source: dict[str, str]
    entries: tuple[DatabricksCatalogEntry, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_version": self.catalog_version,
            "cloud": self.cloud,
            "pricing_profile": asdict(self.pricing_profile),
            "captured_at": self.captured_at,
            "source": self.source,
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


def lookup_sku(catalog: DatabricksCatalog, sku: str) -> DatabricksCatalogEntry | None:
    for entry in catalog.entries:
        if entry.sku == sku:
            return entry
    return None


def load_azure_dbu_pricing_rows() -> list[AzureNodeTypePricingRow]:
    return list(_load_azure_dbu_pricing_rows())


@cache
def _load_azure_dbu_pricing_rows() -> tuple[AzureNodeTypePricingRow, ...]:
    path = resources.files("spotvm").joinpath("data/databricks_azure_dbu_pricing.csv")
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DatabricksCatalogError("Failed to load vendored Azure DBU pricing CSV") from exc

    reader = csv.DictReader(raw_text.splitlines())
    rows: list[AzureNodeTypePricingRow] = []
    for item in reader:
        node_type_id = (item.get("node_type_id") or "").strip()
        if not node_type_id:
            continue
        rows.append(
            AzureNodeTypePricingRow(
                node_type_id=node_type_id,
                category=_optional_str(item.get("category")),
                num_cores=_optional_int(item.get("num_cores")),
                memory_gb=_optional_float(item.get("memory_gb")),
                dbu_per_hour=_optional_float(item.get("dbu_per_hour")),
                local_disk_gb=_optional_int(item.get("local_disk_gb")),
                num_gpus=_optional_int(item.get("num_gpus")),
                photon_capable=_optional_bool(item.get("photon_capable")),
                deprecated=_optional_bool(item.get("deprecated")),
            )
        )
    return tuple(rows)


def lookup_azure_node_type_pricing(node_type_id: str) -> AzureNodeTypePricingRow | None:
    return _azure_dbu_pricing_index().get(node_type_id)


@cache
def _azure_dbu_pricing_index() -> dict[str, AzureNodeTypePricingRow]:
    return {row.node_type_id: row for row in _load_azure_dbu_pricing_rows()}


def refresh_catalog_instructions() -> str:
    return (
        "Manual refresh only.\n"
        "1. Open any Databricks workspace in Chrome DevTools.\n"
        "2. Open the Console tab.\n"
        "3. Run JSON.stringify(window.settings['defaultNodeTypeToPricingUnitsMap']).\n"
        "4. Save the extracted Azure node-type DBU data as src/spotvm/data/databricks_azure_dbu_pricing.csv.\n"
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
        pricing_profile_data = payload["pricing_profile"]
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

    seen_skus: set[str] = set()
    entries: list[DatabricksCatalogEntry] = []
    for raw_entry in entries_data:
        if not isinstance(raw_entry, dict):
            raise DatabricksCatalogError("Each Databricks catalog entry must be an object")
        sku = raw_entry.get("sku")
        if not isinstance(sku, str) or not sku:
            raise DatabricksCatalogError("Each Databricks catalog entry requires a non-empty sku")
        if sku in seen_skus:
            raise DatabricksCatalogError(f"Duplicate Databricks catalog entry for SKU: {sku}")
        seen_skus.add(sku)
        entries.append(
            DatabricksCatalogEntry(
                sku=sku,
                dbu_per_hour=float(raw_entry["dbu_per_hour"]),
                photon_dbu_per_hour=(
                    float(raw_entry["photon_dbu_per_hour"])
                    if raw_entry.get("photon_dbu_per_hour") is not None
                    else None
                ),
                notes=str(raw_entry["notes"]) if raw_entry.get("notes") is not None else None,
            )
        )

    entries.sort(key=lambda entry: entry.sku)
    return DatabricksCatalog(
        catalog_version=int(payload["catalog_version"]),
        cloud=str(payload["cloud"]),
        pricing_profile=DatabricksPricingProfile(
            name=str(pricing_profile_data["name"]),
            dbu_unit_price_usd=float(pricing_profile_data["dbu_unit_price_usd"]),
            photon_dbu_unit_price_usd=float(pricing_profile_data["photon_dbu_unit_price_usd"]),
        ),
        captured_at=str(payload["captured_at"]),
        source={str(key): str(value) for key, value in source.items()},
        entries=tuple(entries),
    )


def _optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _optional_float(value: str | None) -> float | None:
    parsed = _optional_str(value)
    if parsed is None:
        return None
    return float(parsed)


def _optional_int(value: str | None) -> int | None:
    parsed = _optional_str(value)
    if parsed is None:
        return None
    return int(float(parsed))


def _optional_bool(value: str | None) -> bool | None:
    parsed = _optional_str(value)
    if parsed is None:
        return None
    if parsed == "True":
        return True
    if parsed == "False":
        return False
    raise DatabricksCatalogError(f"Unexpected boolean value in Azure DBU pricing CSV: {parsed}")
