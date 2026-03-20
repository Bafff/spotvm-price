from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from spotvm.databricks_catalog import (
    AzureNodeTypePricingRow,
    DatabricksCatalog,
    DatabricksCatalogEntry,
    DatabricksCatalogError,
    DatabricksPricingProfile,
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


def test_load_catalog_source_is_immutable_mapping():
    catalog = load_catalog()

    with pytest.raises(TypeError):
        catalog.source["extra"] = "value"


def test_direct_databricks_catalog_constructor_wraps_source_as_immutable_mapping():
    catalog = DatabricksCatalog(
        catalog_version=1,
        cloud="azure",
        pricing_profile=DatabricksPricingProfile(
            name="standard_jobs",
            dbu_unit_price_usd=0.15,
            photon_dbu_unit_price_usd=0.15,
        ),
        captured_at="2026-03-19T00:00:00Z",
        source={"type": "manual"},
        entries=(),
    )

    with pytest.raises(TypeError):
        catalog.source["extra"] = "value"


def test_direct_databricks_catalog_constructor_rejects_non_mapping_source():
    with pytest.raises(TypeError, match="source must be a mapping of string keys and values"):
        DatabricksCatalog(
            catalog_version=1,
            cloud="azure",
            pricing_profile=DatabricksPricingProfile(
                name="standard_jobs",
                dbu_unit_price_usd=0.15,
                photon_dbu_unit_price_usd=0.15,
            ),
            captured_at="2026-03-19T00:00:00Z",
            source=None,  # type: ignore[arg-type]
            entries=(),
        )


def test_direct_databricks_catalog_constructor_rejects_non_string_source_values():
    with pytest.raises(TypeError, match="source must be a mapping of string keys and values"):
        DatabricksCatalog(
            catalog_version=1,
            cloud="azure",
            pricing_profile=DatabricksPricingProfile(
                name="standard_jobs",
                dbu_unit_price_usd=0.15,
                photon_dbu_unit_price_usd=0.15,
            ),
            captured_at="2026-03-19T00:00:00Z",
            source={"type": ["manual"]},  # type: ignore[dict-item]
            entries=(),
        )


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


def test_load_catalog_from_path_reports_missing_top_level_field(tmp_path):
    path = tmp_path / "broken-missing-version.json"
    path.write_text(
        json.dumps(
            {
                "cloud": "azure",
                "pricing_profile": {
                    "name": "standard_jobs",
                    "dbu_unit_price_usd": 0.15,
                    "photon_dbu_unit_price_usd": 0.15,
                },
                "captured_at": "2026-03-19T00:00:00Z",
                "source": {"type": "test", "url": "https://example.test"},
                "entries": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(DatabricksCatalogError, match="Databricks catalog is missing required field: catalog_version"):
        load_catalog_from_path(path)


def test_load_catalog_from_path_reports_invalid_entry_numeric_value(tmp_path):
    path = tmp_path / "broken-entry-numeric.json"
    path.write_text(
        json.dumps(
            {
                "catalog_version": 1,
                "cloud": "azure",
                "pricing_profile": {
                    "name": "standard_jobs",
                    "dbu_unit_price_usd": 0.15,
                    "photon_dbu_unit_price_usd": 0.15,
                },
                "captured_at": "2026-03-19T00:00:00Z",
                "source": {"type": "test", "url": "https://example.test"},
                "entries": [
                    {
                        "sku": "Standard_D4ps_v6",
                        "dbu_per_hour": "bad",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(DatabricksCatalogError, match="Invalid Databricks catalog value"):
        load_catalog_from_path(path)


def test_load_catalog_from_path_wraps_invalid_source_metadata(tmp_path):
    path = tmp_path / "broken-source.json"
    path.write_text(
        json.dumps(
            {
                "catalog_version": 1,
                "cloud": "azure",
                "pricing_profile": {
                    "name": "standard_jobs",
                    "dbu_unit_price_usd": 0.15,
                    "photon_dbu_unit_price_usd": 0.15,
                },
                "captured_at": "2026-03-19T00:00:00Z",
                "source": {"type": ["manual"]},
                "entries": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(DatabricksCatalogError, match="source must be a mapping of string keys and values"):
        load_catalog_from_path(path)


def test_load_catalog_from_path_reports_duplicate_sku_entries(tmp_path):
    path = tmp_path / "broken-duplicate-sku.json"
    path.write_text(
        json.dumps(
            {
                "catalog_version": 1,
                "cloud": "azure",
                "pricing_profile": {
                    "name": "standard_jobs",
                    "dbu_unit_price_usd": 0.15,
                    "photon_dbu_unit_price_usd": 0.15,
                },
                "captured_at": "2026-03-19T00:00:00Z",
                "source": {"type": "test", "url": "https://example.test"},
                "entries": [
                    {"sku": "Standard_D4ps_v6", "dbu_per_hour": 1.17},
                    {"sku": "Standard_D4ps_v6", "dbu_per_hour": 1.17},
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(DatabricksCatalogError, match="Duplicate Databricks catalog entry for SKU: Standard_D4ps_v6"):
        load_catalog_from_path(path)


def test_databricks_pricing_profile_validates_positive_prices():
    with pytest.raises(ValueError, match="dbu_unit_price_usd must be positive"):
        DatabricksPricingProfile(name="standard_jobs", dbu_unit_price_usd=0.0, photon_dbu_unit_price_usd=0.15)


def test_databricks_pricing_profile_requires_non_empty_name():
    with pytest.raises(ValueError, match="name must be non-empty"):
        DatabricksPricingProfile(name="", dbu_unit_price_usd=0.15, photon_dbu_unit_price_usd=0.15)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_databricks_pricing_profile_rejects_non_finite_prices(value):
    with pytest.raises(ValueError, match="must be finite"):
        DatabricksPricingProfile(name="standard_jobs", dbu_unit_price_usd=value, photon_dbu_unit_price_usd=0.15)

    with pytest.raises(ValueError, match="must be finite"):
        DatabricksPricingProfile(name="standard_jobs", dbu_unit_price_usd=0.15, photon_dbu_unit_price_usd=value)


def test_databricks_catalog_entry_validates_positive_dbu_rates():
    with pytest.raises(ValueError, match="dbu_per_hour must be positive"):
        DatabricksCatalogEntry(sku="Standard_D4ps_v6", dbu_per_hour=0.0)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_databricks_catalog_entry_rejects_non_finite_rates(value):
    with pytest.raises(ValueError, match="dbu_per_hour must be finite"):
        DatabricksCatalogEntry(sku="Standard_D4ps_v6", dbu_per_hour=value)

    with pytest.raises(ValueError, match="photon_dbu_per_hour must be finite"):
        DatabricksCatalogEntry(sku="Standard_D4ps_v6", dbu_per_hour=1.0, photon_dbu_per_hour=value)


def test_databricks_catalog_requires_sorted_unique_entries():
    pricing_profile = DatabricksPricingProfile(
        name="standard_jobs",
        dbu_unit_price_usd=0.15,
        photon_dbu_unit_price_usd=0.15,
    )
    entry_a = DatabricksCatalogEntry(sku="Standard_A2", dbu_per_hour=1.0)
    entry_b = DatabricksCatalogEntry(sku="Standard_A1", dbu_per_hour=1.0)

    with pytest.raises(ValueError, match="entries must be sorted by sku"):
        DatabricksCatalog(
            catalog_version=1,
            cloud="azure",
            pricing_profile=pricing_profile,
            captured_at="2026-03-19T00:00:00Z",
            source={},
            entries=(entry_a, entry_b),
        )

    with pytest.raises(ValueError, match="entries must not contain duplicate sku values"):
        DatabricksCatalog(
            catalog_version=1,
            cloud="azure",
            pricing_profile=pricing_profile,
            captured_at="2026-03-19T00:00:00Z",
            source={},
            entries=(entry_a, DatabricksCatalogEntry(sku="Standard_A2", dbu_per_hour=2.0)),
        )

    with pytest.raises(ValueError, match="captured_at must be a valid ISO 8601 timestamp"):
        DatabricksCatalog(
            catalog_version=1,
            cloud="azure",
            pricing_profile=pricing_profile,
            captured_at="not-a-timestamp",
            source={},
            entries=(),
        )


@pytest.mark.parametrize(
    ("field_name", "value", "expected_message"),
    [
        ("memory_gb", -1.0, "memory_gb must be non-negative"),
        ("local_disk_gb", -1, "local_disk_gb must be non-negative"),
        ("num_gpus", -1, "num_gpus must be non-negative"),
    ],
)
def test_azure_node_type_pricing_row_rejects_negative_optional_capacity_fields(field_name, value, expected_message):
    kwargs = {
        "node_type_id": "Standard_D4ds_v5",
        "category": "General Purpose",
        "num_cores": 4,
        "memory_gb": 16.0,
        "dbu_per_hour": 1.0,
        "local_disk_gb": 150,
        "num_gpus": 0,
        "photon_capable": True,
        "deprecated": False,
    }
    kwargs[field_name] = value

    with pytest.raises(ValueError, match=expected_message):
        AzureNodeTypePricingRow(**kwargs)


@pytest.mark.parametrize("field_name", ["memory_gb", "dbu_per_hour"])
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_azure_node_type_pricing_row_rejects_non_finite_float_fields(field_name, value):
    kwargs = {
        "node_type_id": "Standard_D4ds_v5",
        "category": "General Purpose",
        "num_cores": 4,
        "memory_gb": 16.0,
        "dbu_per_hour": 1.0,
        "local_disk_gb": 150,
        "num_gpus": 0,
        "photon_capable": True,
        "deprecated": False,
    }
    kwargs[field_name] = value

    with pytest.raises(ValueError, match=f"{field_name} must be finite"):
        AzureNodeTypePricingRow(**kwargs)


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


def test_load_azure_dbu_pricing_rows_requires_node_type_id_header(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    csv_path = data_dir / "databricks_azure_dbu_pricing.csv"
    csv_path.write_text(
        "\n".join(
            [
                "sku,category,num_cores,memory_gb,dbu_per_hour,local_disk_gb,num_gpus,photon_capable,deprecated",
                "Standard_D4ds_v5,General Purpose,4,16.0,1.0,150,0,True,False",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("spotvm.databricks_catalog.resources.files", lambda _pkg: tmp_path)
    import spotvm.databricks_catalog as databricks_catalog

    databricks_catalog._load_azure_dbu_pricing_rows.cache_clear()
    databricks_catalog._azure_dbu_pricing_index.cache_clear()

    with pytest.raises(DatabricksCatalogError, match="missing required header: node_type_id"):
        load_azure_dbu_pricing_rows()


def test_load_azure_dbu_pricing_rows_accepts_lowercase_boolean_values(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    csv_path = data_dir / "databricks_azure_dbu_pricing.csv"
    csv_path.write_text(
        "\n".join(
            [
                "node_type_id,category,num_cores,memory_gb,dbu_per_hour,local_disk_gb,num_gpus,photon_capable,deprecated",
                "Standard_D4ds_v5,General Purpose,4,16.0,1.0,150,0,true,false",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("spotvm.databricks_catalog.resources.files", lambda _pkg: tmp_path)
    import spotvm.databricks_catalog as databricks_catalog

    databricks_catalog._load_azure_dbu_pricing_rows.cache_clear()
    databricks_catalog._azure_dbu_pricing_index.cache_clear()

    rows = load_azure_dbu_pricing_rows()

    assert rows[0].photon_capable is True
    assert rows[0].deprecated is False


def test_load_azure_dbu_pricing_rows_rejects_invalid_boolean_values(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    csv_path = data_dir / "databricks_azure_dbu_pricing.csv"
    csv_path.write_text(
        "\n".join(
            [
                "node_type_id,category,num_cores,memory_gb,dbu_per_hour,local_disk_gb,num_gpus,photon_capable,deprecated",
                "Standard_D4ds_v5,General Purpose,4,16.0,1.0,150,0,yes,False",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("spotvm.databricks_catalog.resources.files", lambda _pkg: tmp_path)
    import spotvm.databricks_catalog as databricks_catalog

    databricks_catalog._load_azure_dbu_pricing_rows.cache_clear()
    databricks_catalog._azure_dbu_pricing_index.cache_clear()

    with pytest.raises(DatabricksCatalogError, match="expected True or False"):
        load_azure_dbu_pricing_rows()


def test_load_azure_dbu_pricing_last_updated_uses_catalog_captured_at(monkeypatch):
    monkeypatch.setattr(
        "spotvm.databricks_catalog.load_catalog",
        lambda: SimpleNamespace(captured_at=datetime(2026, 3, 19, 12, 0, tzinfo=timezone.utc)),
    )

    from spotvm.databricks_catalog import load_azure_dbu_pricing_last_updated

    assert load_azure_dbu_pricing_last_updated() == datetime(2026, 3, 19, 12, 0, tzinfo=timezone.utc)


def test_load_azure_dbu_pricing_rows_warns_when_no_usable_rows_loaded(tmp_path, monkeypatch, caplog):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    csv_path = data_dir / "databricks_azure_dbu_pricing.csv"
    csv_path.write_text(
        "\n".join(
            [
                "node_type_id,category,num_cores,memory_gb,dbu_per_hour,local_disk_gb,num_gpus,photon_capable,deprecated",
                ",General Purpose,4,16.0,1.0,150,0,True,False",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("spotvm.databricks_catalog.resources.files", lambda _pkg: tmp_path)
    import spotvm.databricks_catalog as databricks_catalog

    databricks_catalog._load_azure_dbu_pricing_rows.cache_clear()
    databricks_catalog._azure_dbu_pricing_index.cache_clear()

    with caplog.at_level("WARNING", logger="spotvm"):
        rows = load_azure_dbu_pricing_rows()

    assert rows == []
    assert "Loaded 0 usable Azure Databricks DBU pricing rows" in caplog.text


def test_load_azure_dbu_pricing_rows_warns_when_rows_are_skipped_for_blank_node_type_id(tmp_path, monkeypatch, caplog):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    csv_path = data_dir / "databricks_azure_dbu_pricing.csv"
    csv_path.write_text(
        "\n".join(
            [
                "node_type_id,category,num_cores,memory_gb,dbu_per_hour,local_disk_gb,num_gpus,photon_capable,deprecated",
                ",General Purpose,4,16.0,1.0,150,0,True,False",
                "Standard_D4ds_v5,General Purpose,4,16.0,1.0,150,0,True,False",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("spotvm.databricks_catalog.resources.files", lambda _pkg: tmp_path)
    import spotvm.databricks_catalog as databricks_catalog

    databricks_catalog._load_azure_dbu_pricing_rows.cache_clear()
    databricks_catalog._azure_dbu_pricing_index.cache_clear()

    with caplog.at_level("WARNING", logger="spotvm"):
        rows = load_azure_dbu_pricing_rows()

    assert len(rows) == 1
    assert "Skipped 1 Azure Databricks DBU pricing row(s) with blank node_type_id" in caplog.text


def test_azure_node_type_pricing_row_validates_required_fields():
    from spotvm.databricks_catalog import AzureNodeTypePricingRow

    with pytest.raises(ValueError, match="node_type_id must be non-empty"):
        AzureNodeTypePricingRow(
            node_type_id="",
            category=None,
            num_cores=4,
            memory_gb=16.0,
            dbu_per_hour=1.0,
            local_disk_gb=150,
            num_gpus=0,
            photon_capable=True,
            deprecated=False,
        )


def test_load_azure_dbu_pricing_rows_rejects_fractional_integer_fields(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    csv_path = data_dir / "databricks_azure_dbu_pricing.csv"
    csv_path.write_text(
        "\n".join(
            [
                "node_type_id,category,num_cores,memory_gb,dbu_per_hour,local_disk_gb,num_gpus,photon_capable,deprecated",
                "Standard_D4ds_v5,General Purpose,3.5,16.0,1.0,150,0,True,False",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("spotvm.databricks_catalog.resources.files", lambda _pkg: tmp_path)
    import spotvm.databricks_catalog as databricks_catalog

    databricks_catalog._load_azure_dbu_pricing_rows.cache_clear()
    databricks_catalog._azure_dbu_pricing_index.cache_clear()

    with pytest.raises(DatabricksCatalogError, match="row 2, column num_cores"):
        load_azure_dbu_pricing_rows()
