from __future__ import annotations

import json

import pytest

from spotvm.databricks_catalog import (
    DatabricksCatalogError,
    load_azure_dbu_pricing_rows,
    load_catalog,
    load_catalog_from_path,
    lookup_azure_node_type_pricing,
    lookup_sku,
)


def test_lookup_sku_returns_dbu_and_photon_values():
    catalog = load_catalog()

    entry = lookup_sku(catalog, "Standard_D4ps_v6")

    assert entry is not None
    assert entry.sku == "Standard_D4ps_v6"
    assert entry.dbu_per_hour == 1.17
    assert entry.photon_dbu_per_hour == 1.17


def test_load_catalog_exposes_stable_metadata_shape():
    catalog = load_catalog()

    payload = catalog.to_dict()
    assert set(payload.keys()) == {
        "catalog_version",
        "cloud",
        "pricing_profile",
        "captured_at",
        "source",
        "entries",
    }
    assert set(payload["pricing_profile"].keys()) == {
        "name",
        "dbu_unit_price_usd",
        "photon_dbu_unit_price_usd",
    }
    assert isinstance(payload["entries"], list)
    json.dumps(payload)


def test_lookup_sku_is_case_sensitive_exact_match():
    catalog = load_catalog()

    assert lookup_sku(catalog, "standard_d4ps_v6") is None


def test_load_catalog_from_path_reports_malformed_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not-valid-json", encoding="utf-8")

    with pytest.raises(DatabricksCatalogError, match="Failed to parse Databricks catalog"):
        load_catalog_from_path(path)


def test_load_azure_dbu_pricing_rows_contains_known_saved_entries():
    rows = load_azure_dbu_pricing_rows()

    assert len(rows) > 100
    assert any(row.node_type_id == "Standard_D4ds_v5" and row.dbu_per_hour == 1.0 for row in rows)
    assert any(row.node_type_id == "Standard_E4d_v4" and row.dbu_per_hour == 1.0 for row in rows)
    assert any(row.node_type_id == "Standard_F4" and row.dbu_per_hour == 0.5 for row in rows)


def test_lookup_azure_node_type_pricing_returns_saved_row():
    row = lookup_azure_node_type_pricing("Standard_D8ds_v5")

    assert row is not None
    assert row.node_type_id == "Standard_D8ds_v5"
    assert row.num_cores == 8
    assert row.memory_gb == 32.0
    assert row.dbu_per_hour == 2.0


def test_lookup_azure_node_type_pricing_is_case_sensitive():
    assert lookup_azure_node_type_pricing("standard_d8ds_v5") is None
