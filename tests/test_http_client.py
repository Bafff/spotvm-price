from __future__ import annotations

import logging

import pytest
import requests

from spotvm.http_client import AzureHttpError, AzureRestClient


class AuthenticatorStub:
    def __init__(self, token: str = "token"):
        self._token = token
        self.calls = 0

    def get_token(self) -> str:
        self.calls += 1
        return self._token


class ResponseStub:
    def __init__(
        self,
        *,
        status_code: int,
        ok: bool | None = None,
        payload: dict | None = None,
        text: str = "{}",
        headers: dict[str, str] | None = None,
        json_error: Exception | None = None,
    ):
        derived_ok = 200 <= status_code < 400
        if ok is not None and ok != derived_ok:
            raise AssertionError("ResponseStub ok state does not match status_code")
        self.status_code = status_code
        self.ok = derived_ok
        self.text = text
        self.headers = headers or {}
        self._payload = payload or {}
        self._json_error = json_error

    def json(self) -> dict:
        if self._json_error is not None:
            raise self._json_error
        return self._payload


class SessionStub:
    def __init__(self, responses: list[ResponseStub]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def post(self, url: str, *, data: str, headers: dict[str, str], timeout: int):
        self.calls.append(
            {
                "url": url,
                "data": data,
                "headers": headers,
                "timeout": timeout,
            }
        )
        if not self._responses:
            raise AssertionError(f"Unexpected extra HTTP call to {url}; configure another ResponseStub response")
        return self._responses.pop(0)


def test_response_stub_rejects_contradictory_ok_state():
    with pytest.raises(AssertionError, match="ok state does not match status_code"):
        ResponseStub(status_code=200, ok=False)


def test_session_stub_raises_clear_assertion_when_responses_are_exhausted():
    session = SessionStub([])

    with pytest.raises(AssertionError, match="Unexpected extra HTTP call"):
        session.post(
            "https://example.test",
            data="{}",
            headers={"Authorization": "Bearer token"},
            timeout=60,
        )


def test_post_json_logs_retries_for_transient_errors(monkeypatch, caplog):
    authenticator = AuthenticatorStub()
    client = AzureRestClient(authenticator=authenticator, user_agent="spotvm/test")
    client._session = SessionStub(
        [
            ResponseStub(status_code=429, ok=False),
            ResponseStub(status_code=200, ok=True, payload={"ok": True}),
        ]
    )

    sleep_calls: list[float] = []
    monkeypatch.setattr("spotvm.http_client.time.sleep", sleep_calls.append)

    with caplog.at_level(logging.WARNING, logger="spotvm"):
        result = client.post_json("https://example.test", {"hello": "world"}, retry_attempts=2)

    assert result == {"ok": True}
    assert sleep_calls == [2.0]
    assert authenticator.calls == 2
    assert client._session.calls[0]["headers"]["Authorization"] == "Bearer token"
    assert client._session.calls[0]["timeout"] == 60
    assert "Retrying Azure API request after 429" in caplog.text


def test_post_json_honors_numeric_retry_after_header(monkeypatch):
    authenticator = AuthenticatorStub()
    client = AzureRestClient(authenticator=authenticator, user_agent="spotvm/test")
    client._session = SessionStub(
        [
            ResponseStub(status_code=503, ok=False, headers={"Retry-After": "7.5"}),
            ResponseStub(status_code=200, ok=True, payload={"ok": True}),
        ]
    )

    sleep_calls: list[float] = []
    monkeypatch.setattr("spotvm.http_client.time.sleep", sleep_calls.append)

    result = client.post_json("https://example.test", {"hello": "world"}, retry_attempts=2)

    assert result == {"ok": True}
    assert sleep_calls == [7.5]


def test_retry_delay_ignores_non_numeric_retry_after(monkeypatch, caplog):
    authenticator = AuthenticatorStub()
    client = AzureRestClient(authenticator=authenticator, user_agent="spotvm/test")
    client._session = SessionStub(
        [
            ResponseStub(status_code=429, ok=False, headers={"Retry-After": "later"}),
            ResponseStub(status_code=200, ok=True, payload={"ok": True}),
        ]
    )

    sleep_calls: list[float] = []
    monkeypatch.setattr("spotvm.http_client.time.sleep", sleep_calls.append)

    with caplog.at_level(logging.DEBUG, logger="spotvm"):
        result = client.post_json("https://example.test", {"hello": "world"}, retry_attempts=2)

    assert result == {"ok": True}
    assert sleep_calls == [2.0]
    assert "Ignoring non-numeric Retry-After header" in caplog.text


def test_post_json_raises_with_response_snippet_on_terminal_http_error():
    authenticator = AuthenticatorStub()
    client = AzureRestClient(authenticator=authenticator, user_agent="spotvm/test")
    client._session = SessionStub(
        [
            ResponseStub(
                status_code=400,
                ok=False,
                text="bad request details",
            )
        ]
    )

    with pytest.raises(AzureHttpError) as exc_info:
        client.post_json("https://example.test", {"hello": "world"}, retry_attempts=1)

    exc = exc_info.value
    assert exc.status_code == 400
    assert exc.url == "https://example.test"
    assert "bad request details" in str(exc)


def test_post_json_raises_when_response_body_is_not_valid_json():
    authenticator = AuthenticatorStub()
    client = AzureRestClient(authenticator=authenticator, user_agent="spotvm/test")
    client._session = SessionStub(
        [
            ResponseStub(
                status_code=200,
                ok=True,
                text="not-json",
                json_error=requests.exceptions.JSONDecodeError("bad json", "not-json", 0),
            )
        ]
    )

    with pytest.raises(AzureHttpError) as exc_info:
        client.post_json("https://example.test", {"hello": "world"}, retry_attempts=1)

    exc = exc_info.value
    assert exc.status_code == 200
    assert "Response was not valid JSON" in str(exc)
    assert "not-json" in str(exc)
