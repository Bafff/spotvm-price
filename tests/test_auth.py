from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from spotvm.auth import AzureAuthenticator, _not_expired


def test_authenticator_uses_default_credential_when_none_provided(monkeypatch):
    created_credential = MagicMock()
    monkeypatch.setattr("spotvm.auth.DefaultAzureCredential", lambda **kwargs: created_credential)

    authenticator = AzureAuthenticator()

    assert authenticator.credential is created_credential


def test_get_token_reuses_cached_token_before_expiry(monkeypatch):
    credential = MagicMock()
    credential.get_token.return_value = SimpleNamespace(token="cached-token", expires_on=4000)
    authenticator = AzureAuthenticator(credential=credential)
    monkeypatch.setattr("time.time", lambda: 1000)

    first = authenticator.get_token()
    second = authenticator.get_token()

    assert first == "cached-token"
    assert second == "cached-token"
    assert credential.get_token.call_count == 1


def test_get_token_refreshes_when_token_is_near_expiry(monkeypatch):
    credential = MagicMock()
    credential.get_token.side_effect = [
        SimpleNamespace(token="stale-token", expires_on=1050),
        SimpleNamespace(token="fresh-token", expires_on=4000),
    ]
    authenticator = AzureAuthenticator(credential=credential)
    monkeypatch.setattr("time.time", lambda: 1000)

    first = authenticator.get_token()
    second = authenticator.get_token()

    assert first == "stale-token"
    assert second == "fresh-token"
    assert credential.get_token.call_count == 2


def test_get_token_raises_when_credential_initialization_failed():
    authenticator = AzureAuthenticator(credential=MagicMock())
    authenticator.credential = None

    with pytest.raises(RuntimeError, match="Azure credential initialization failed"):
        authenticator.get_token()


def test_not_expired_refreshes_one_minute_early(monkeypatch):
    monkeypatch.setattr("time.time", lambda: 1000)

    assert _not_expired(1061) is True
    assert _not_expired(1060) is False
