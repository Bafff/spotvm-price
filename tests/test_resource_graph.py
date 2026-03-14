from __future__ import annotations

import logging
from unittest.mock import MagicMock

from spotvm.config import ToolConfig
from spotvm.resource_graph import (
    _ensure_list,
    _execute_query,
    _extract_eviction,
    _extract_latest_price,
    _to_float,
)


def test_extract_latest_price_logs_malformed_json(caplog):
    entry = {"spotPrices": ['{"priceUSD": 0.12']}

    with caplog.at_level(logging.DEBUG, logger="spotvm"):
        price, timestamp = _extract_latest_price(entry)

    assert price is None
    assert timestamp is None
    assert "Failed to decode spotPrices JSON" in caplog.text


def test_extract_latest_price_logs_non_dict_latest_entry(caplog):
    entry = {"spotPrices": [123]}

    with caplog.at_level(logging.DEBUG, logger="spotvm"):
        price, timestamp = _extract_latest_price(entry)

    assert price is None
    assert timestamp is None
    assert "Latest spot price entry is not an object" in caplog.text


def test_ensure_list_logs_malformed_json(caplog):
    with caplog.at_level(logging.DEBUG, logger="spotvm"):
        result = _ensure_list("[not-valid-json")

    assert result == []
    assert "Failed to decode list JSON" in caplog.text


def test_ensure_list_logs_non_list_json(caplog):
    with caplog.at_level(logging.DEBUG, logger="spotvm"):
        result = _ensure_list('{"priceUSD": 0.12}')

    assert result == []
    assert "Decoded JSON value is not a list" in caplog.text


def test_to_float_warns_on_malformed_non_empty_value(caplog):
    with caplog.at_level(logging.WARNING, logger="spotvm"):
        result = _to_float("not-a-number")

    assert result is None
    assert "Failed to parse float value" in caplog.text


def test_extract_eviction_warns_on_unparseable_non_empty_value(caplog):
    with caplog.at_level(logging.WARNING, logger="spotvm"):
        rate, timestamp = _extract_eviction({"spotEvictionRate": "unknown"})

    assert rate is None
    assert timestamp is None
    assert "Failed to parse eviction rate" in caplog.text


def test_execute_query_ignores_malformed_cached_payload(monkeypatch, caplog):
    monkeypatch.setattr("spotvm.resource_graph.cache.load", lambda *args, **kwargs: ["bad-cache"])
    monkeypatch.setattr("spotvm.resource_graph.cache.store", lambda *args, **kwargs: None)

    client = MagicMock()
    client.post_json.return_value = {"data": []}
    config = ToolConfig(regions=["eastus"], sizes=["Standard_D4as_v5"])

    with caplog.at_level(logging.WARNING, logger="spotvm"):
        result = _execute_query(client, config, "resources | take 1", "price")

    assert result == []
    assert client.post_json.called
    assert "Ignoring malformed cached price data" in caplog.text
