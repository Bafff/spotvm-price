from __future__ import annotations

import json

import pytest

from spotvm.databricks_catalog import (
    DatabricksCatalogError,
    load_azure_dbu_pricing_rows,
    load_catalog,
    load_catalog_from_path,
    lookup_azure_node_type_pricing,
)


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


def test_load_catalog_from_path_reports_malformed_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not-valid-json", encoding="utf-8")

    with pytest.raises(DatabricksCatalogError, match="Failed to parse Databricks catalog"):
        load_catalog_from_path(path)


def test_load_catalog_from_path_rejects_zero_photon_unit_price(tmp_path):
    path = tmp_path / "broken-photon-price.json"
    path.write_text(
        json.dumps(
            {
                "catalog_version": 1,
                "cloud": "azure",
                "pricing_profile": {
                    "name": "standard_jobs",
                    "dbu_unit_price_usd": 0.15,
                    "photon_dbu_unit_price_usd": 0.0,
                },
                "captured_at": "2026-03-19T00:00:00Z",
                "source": {"type": "test", "url": "https://example.test"},
                "entries": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(DatabricksCatalogError, match="photon_dbu_unit_price_usd must be positive"):
        load_catalog_from_path(path)


def test_load_catalog_from_path_reports_missing_nested_pricing_key(tmp_path):
    path = tmp_path / "broken-pricing-key.json"
    path.write_text(
        json.dumps(
            {
                "catalog_version": 1,
                "cloud": "azure",
                "pricing_profile": {
                    "name": "standard_jobs",
                    "dbu_unit_price_usd": 0.15,
                },
                "captured_at": "2026-03-19T00:00:00Z",
                "source": {"type": "test", "url": "https://example.test"},
                "entries": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        DatabricksCatalogError, match="pricing_profile is missing required field: photon_dbu_unit_price_usd"
    ):
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


def test_load_azure_dbu_pricing_rows_reports_row_and_column_for_invalid_numeric_value(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    csv_path = data_dir / "databricks_azure_dbu_pricing.csv"
    csv_path.write_text(
        "\n".join(
            [
                "node_type_id,category,num_cores,memory_gb,dbu_per_hour,local_disk_gb,num_gpus,photon_capable,deprecated",
                "Standard_D4ds_v5,General Purpose,4,16.0,N/A,150,0,True,False",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("spotvm.databricks_catalog.resources.files", lambda _pkg: tmp_path)
    import spotvm.databricks_catalog as databricks_catalog

    databricks_catalog._load_azure_dbu_pricing_rows.cache_clear()
    databricks_catalog._azure_dbu_pricing_index.cache_clear()

    with pytest.raises(DatabricksCatalogError, match="row 2, column dbu_per_hour"):
        load_azure_dbu_pricing_rows()
