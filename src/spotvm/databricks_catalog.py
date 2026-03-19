from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Callable

import requests

DEFAULT_DATABRICKS_PRICING_URL = "https://azure.microsoft.com/en-us/pricing/details/databricks/"


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
    path = resources.files("spotvm").joinpath("data", "databricks_pricing.json")
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


def refresh_catalog(
    *,
    catalog_path: Path | None = None,
    source_url: str = DEFAULT_DATABRICKS_PRICING_URL,
    fetch_source: Callable[[str], str] | None = None,
    parse_source: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    target_path = catalog_path or _catalog_snapshot_path()
    fetcher = fetch_source or _fetch_source
    parser = parse_source or _parse_source

    existing = load_catalog_from_path(target_path) if target_path.exists() else None
    source_text = fetcher(source_url)
    catalog = _catalog_from_payload(parser(source_text))
    _write_catalog_atomic(target_path, catalog.to_dict())

    previous_entries = {entry.sku: entry for entry in existing.entries} if existing is not None else {}
    next_entries = {entry.sku: entry for entry in catalog.entries}

    new_count = sum(1 for sku in next_entries if sku not in previous_entries)
    removed_count = sum(1 for sku in previous_entries if sku not in next_entries)
    changed_count = sum(
        1 for sku, entry in next_entries.items() if sku in previous_entries and entry != previous_entries[sku]
    )

    return {
        "catalog_path": target_path,
        "sku_count": len(catalog.entries),
        "new_count": new_count,
        "changed_count": changed_count,
        "removed_count": removed_count,
    }


def _catalog_snapshot_path() -> Path:
    return Path(__file__).with_name("data") / "databricks_pricing.json"


def _fetch_source(source_url: str) -> str:
    response = requests.get(source_url, timeout=60)
    if not response.ok:
        raise DatabricksCatalogError(
            f"Failed to fetch Databricks pricing source ({response.status_code}) from {source_url}"
        )
    return response.text


def _parse_source(source_text: str) -> dict[str, Any]:
    try:
        payload = json.loads(source_text)
    except json.JSONDecodeError as exc:
        raise DatabricksCatalogError(
            "Failed to parse Databricks pricing source. Expected normalized JSON input."
        ) from exc
    if not isinstance(payload, dict):
        raise DatabricksCatalogError("Databricks pricing source must be a JSON object")
    return payload


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


def _write_catalog_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        temp_path.replace(path)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise
