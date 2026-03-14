from __future__ import annotations

import logging
from unittest.mock import MagicMock

from spotvm.http_client import AzureRestClient


def _response(*, status_code: int, ok: bool, payload: dict | None = None, headers: dict | None = None):
    response = MagicMock()
    response.status_code = status_code
    response.ok = ok
    response.headers = headers or {}
    response.text = "{}"
    response.json.return_value = payload or {}
    return response


def test_post_json_logs_retries_for_transient_errors(monkeypatch, caplog):
    authenticator = MagicMock()
    authenticator.get_token.return_value = "token"
    client = AzureRestClient(authenticator=authenticator, user_agent="spotvm/test")
    client._session = MagicMock()
    client._session.post.side_effect = [
        _response(status_code=429, ok=False),
        _response(status_code=200, ok=True, payload={"ok": True}),
    ]

    sleep_calls: list[float] = []
    monkeypatch.setattr("spotvm.http_client.time.sleep", sleep_calls.append)

    with caplog.at_level(logging.WARNING, logger="spotvm"):
        result = client.post_json("https://example.test", {"hello": "world"}, retry_attempts=2)

    assert result == {"ok": True}
    assert sleep_calls == [2.0]
    assert "Retrying Azure API request after 429" in caplog.text
