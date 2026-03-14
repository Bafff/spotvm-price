from __future__ import annotations

import logging
from unittest.mock import MagicMock

from spotvm.config import ToolConfig
from spotvm.placement_score import _build_result, _parse_response, fetch_placement_scores


def test_parse_response_logs_items_without_vm_size(caplog):
    payload = {
        "placementScores": [{"scoresByLocation": [{"location": "eastus", "score": "High", "isQuotaAvailable": True}]}]
    }

    with caplog.at_level(logging.DEBUG, logger="spotvm"):
        results = _parse_response(payload)

    assert results == []
    assert "Skipping placement score item without VM size" in caplog.text


def test_build_result_coerces_non_string_region_to_empty_string():
    result = _build_result("Standard_D4as_v5", {"location": 123, "score": "High"})

    assert result.region == ""


def test_fetch_placement_scores_ignores_malformed_cached_payload(monkeypatch, caplog):
    monkeypatch.setattr("spotvm.placement_score.cache.load", lambda *args, **kwargs: ["bad-cache"])
    monkeypatch.setattr("spotvm.placement_score.cache.store", lambda *args, **kwargs: None)

    client = MagicMock()
    client.post_json.return_value = {"placementScores": []}
    config = ToolConfig(
        subscription_id="sub-id",
        regions=["eastus"],
        sizes=["Standard_D4as_v5"],
        enable_placement=True,
    )

    with caplog.at_level(logging.WARNING, logger="spotvm"):
        result = fetch_placement_scores(client, config)

    assert result == []
    assert client.post_json.called
    assert "Ignoring malformed cached placement data" in caplog.text
