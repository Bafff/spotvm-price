from __future__ import annotations

from spotvm.cli import main
from spotvm.databricks_catalog import refresh_catalog_instructions


def test_refresh_databricks_catalog_exits_without_running_analysis(monkeypatch):
    called: dict[str, bool] = {"instructions": False, "analysis": False}

    def fake_refresh_catalog_instructions():
        called["instructions"] = True
        return "manual refresh instructions"

    def fake_run_analysis_mode(**_kwargs):
        called["analysis"] = True
        return 99

    monkeypatch.setattr("spotvm.cli.refresh_catalog_instructions", fake_refresh_catalog_instructions)
    monkeypatch.setattr("spotvm.cli._run_analysis_mode", fake_run_analysis_mode)

    rc = main(["--refresh-databricks-catalog"])

    assert rc == 0
    assert called == {"instructions": True, "analysis": False}


def test_refresh_catalog_instructions_reference_manual_devtools_workflow():
    instructions = refresh_catalog_instructions()

    assert "Chrome DevTools" in instructions
    assert "window.settings['defaultNodeTypeToPricingUnitsMap']" in instructions
    assert "src/spotvm/data/databricks_azure_dbu_pricing.csv" in instructions
    assert "convert" in instructions.lower()
    assert "manual" in instructions.lower()


def test_normal_analysis_path_does_not_refresh_catalog(monkeypatch):
    called: dict[str, bool] = {"instructions": False}

    def fake_refresh_catalog_instructions():
        called["instructions"] = True
        raise AssertionError("refresh instructions should not be called")

    monkeypatch.setattr("spotvm.cli.refresh_catalog_instructions", fake_refresh_catalog_instructions)
    monkeypatch.setattr("spotvm.cli._prepare_analysis_execution", lambda **_kwargs: 0)
    monkeypatch.setattr("spotvm.cli._run_history_mode_if_requested", lambda **_kwargs: None)

    rc = main(["--regions", "centralus", "--sizes", "Standard_D4s_v5"])

    assert rc == 0
    assert called["instructions"] is False
