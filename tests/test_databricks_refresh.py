from __future__ import annotations

import json
from pathlib import Path

from spotvm.cli import main
from spotvm.databricks_catalog import refresh_catalog


def test_refresh_databricks_catalog_exits_without_running_analysis(monkeypatch):
    called: dict[str, bool] = {"refresh": False, "analysis": False}

    def fake_refresh_catalog(**_kwargs):
        called["refresh"] = True
        return {
            "catalog_path": Path("/tmp/databricks_pricing.json"),
            "sku_count": 1,
            "new_count": 1,
            "changed_count": 0,
            "removed_count": 0,
        }

    def fake_run_analysis_mode(**_kwargs):
        called["analysis"] = True
        return 99

    monkeypatch.setattr("spotvm.cli.refresh_catalog", fake_refresh_catalog)
    monkeypatch.setattr("spotvm.cli._run_analysis_mode", fake_run_analysis_mode)

    rc = main(["--refresh-databricks-catalog"])

    assert rc == 0
    assert called == {"refresh": True, "analysis": False}


def test_refresh_catalog_writes_atomically_and_reports_counts(tmp_path):
    target_path = tmp_path / "databricks_pricing.json"
    target_path.write_text(
        json.dumps(
            {
                "catalog_version": 1,
                "cloud": "azure",
                "pricing_profile": {
                    "name": "standard_jobs",
                    "dbu_unit_price_usd": 0.15,
                    "photon_dbu_unit_price_usd": 0.0,
                },
                "captured_at": "2026-03-18T00:00:00Z",
                "source": {"type": "official_pricing_snapshot", "url": "https://example.test/old"},
                "entries": [
                    {"sku": "Standard_D4ps_v6", "dbu_per_hour": 1.0, "photon_dbu_per_hour": 1.0, "notes": ""}
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = refresh_catalog(
        catalog_path=target_path,
        fetch_source=lambda _url: "ignored-source",
        parse_source=lambda _text: {
            "catalog_version": 1,
            "cloud": "azure",
            "pricing_profile": {
                "name": "standard_jobs",
                "dbu_unit_price_usd": 0.15,
                "photon_dbu_unit_price_usd": 0.0,
            },
            "captured_at": "2026-03-19T00:00:00Z",
            "source": {"type": "official_pricing_snapshot", "url": "https://example.test/new"},
            "entries": [
                {"sku": "Standard_D4ps_v6", "dbu_per_hour": 1.17, "photon_dbu_per_hour": 1.17, "notes": ""},
                {"sku": "Standard_E4ps_v6", "dbu_per_hour": 1.17, "photon_dbu_per_hour": 1.17, "notes": ""},
            ],
        },
    )

    assert summary["catalog_path"] == target_path
    assert summary["sku_count"] == 2
    assert summary["new_count"] == 1
    assert summary["changed_count"] == 1
    assert summary["removed_count"] == 0
    assert list(tmp_path.glob(".*.tmp")) == []

    payload = json.loads(target_path.read_text(encoding="utf-8"))
    assert [entry["sku"] for entry in payload["entries"]] == ["Standard_D4ps_v6", "Standard_E4ps_v6"]


def test_normal_analysis_path_does_not_refresh_catalog(monkeypatch):
    called: dict[str, bool] = {"refresh": False}

    def fake_refresh_catalog(**_kwargs):
        called["refresh"] = True
        raise AssertionError("refresh should not be called")

    monkeypatch.setattr("spotvm.cli.refresh_catalog", fake_refresh_catalog)
    monkeypatch.setattr("spotvm.cli._prepare_analysis_execution", lambda **_kwargs: 0)
    monkeypatch.setattr("spotvm.cli._run_history_mode_if_requested", lambda **_kwargs: None)

    rc = main(["--regions", "centralus", "--sizes", "Standard_D4s_v5"])

    assert rc == 0
    assert called["refresh"] is False
