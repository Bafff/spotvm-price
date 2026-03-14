from __future__ import annotations

import logging
from datetime import datetime, timezone
from unittest.mock import MagicMock

from spotvm.config import ToolConfig
from spotvm.resource_graph import (
    _ensure_list,
    _execute_query,
    _extract_eviction,
    _extract_latest_price,
    _parse_datetime_string,
    _resource_graph_endpoint,
    _to_float,
    fetch_historical_metrics,
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


def test_fetch_historical_metrics_does_not_log_full_queries(monkeypatch, caplog):
    monkeypatch.setattr("spotvm.resource_graph._build_price_query", lambda config: "PRICE_QUERY_SECRET")
    monkeypatch.setattr("spotvm.resource_graph._build_eviction_query", lambda config: "EVICTION_QUERY_SECRET")
    monkeypatch.setattr("spotvm.resource_graph._execute_query", lambda *args, **kwargs: [])

    client = MagicMock()
    config = ToolConfig(regions=["eastus"], sizes=["Standard_D4as_v5"])

    with caplog.at_level(logging.DEBUG, logger="spotvm"):
        metrics = fetch_historical_metrics(client, config)

    assert metrics == []
    assert "PRICE_QUERY_SECRET" not in caplog.text
    assert "EVICTION_QUERY_SECRET" not in caplog.text


def test_execute_query_does_not_log_sample_payload_contents(monkeypatch, caplog):
    monkeypatch.setattr("spotvm.resource_graph.cache.load", lambda *args, **kwargs: None)
    monkeypatch.setattr("spotvm.resource_graph.cache.store", lambda *args, **kwargs: None)

    client = MagicMock()
    client.post_json.return_value = {
        "data": [
            {
                "skuName": "Standard_D4as_v5",
                "location": "eastus",
                "secretField": "SUPER-SECRET-PAYLOAD",
            }
        ]
    }
    config = ToolConfig(regions=["eastus"], sizes=["Standard_D4as_v5"])

    with caplog.at_level(logging.DEBUG, logger="spotvm"):
        rows = _execute_query(client, config, "resources | take 1", "price")

    assert rows == client.post_json.return_value["data"]
    assert "SUPER-SECRET-PAYLOAD" not in caplog.text
    assert "authorizationScopeFilter" not in caplog.text


def test_execute_query_uses_resource_graph_endpoint_builder(monkeypatch):
    sentinel_endpoint = "https://example.invalid/resource-graph"

    monkeypatch.setattr("spotvm.resource_graph.cache.load", lambda *args, **kwargs: None)
    monkeypatch.setattr("spotvm.resource_graph.cache.store", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "spotvm.resource_graph._resource_graph_endpoint",
        lambda: sentinel_endpoint,
        raising=False,
    )

    client = MagicMock()
    client.post_json.return_value = {"data": []}
    config = ToolConfig(regions=["eastus"], sizes=["Standard_D4as_v5"])

    _execute_query(client, config, "resources | take 1", "price")

    assert client.post_json.call_args.args[0] == sentinel_endpoint


def test_resource_graph_endpoint_builds_expected_url():
    assert (
        _resource_graph_endpoint()
        == "https://management.azure.com/providers/Microsoft.ResourceGraph/resources?api-version=2022-10-01"
    )


def test_parse_datetime_string_accepts_unix_timestamp_strings():
    assert _parse_datetime_string("1735689600") == datetime(2025, 1, 1, tzinfo=timezone.utc)


def test_parse_datetime_string_accepts_whitespace_padded_unix_timestamp_strings():
    assert _parse_datetime_string(" 1735689600 ") == datetime(2025, 1, 1, tzinfo=timezone.utc)


def test_parse_datetime_string_accepts_float_unix_timestamp_strings():
    assert _parse_datetime_string("1735689600.5") == datetime(2025, 1, 1, 0, 0, 0, 500000, tzinfo=timezone.utc)


def test_parse_datetime_string_rejects_implausible_numeric_strings():
    assert _parse_datetime_string("401") is None


def test_parse_datetime_string_rejects_negative_unix_timestamp_strings():
    assert _parse_datetime_string("-1") is None


def test_parse_datetime_string_rejects_non_matching_strings():
    assert _parse_datetime_string("not-a-date") is None
