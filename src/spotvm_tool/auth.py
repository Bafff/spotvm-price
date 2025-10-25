from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional

from azure.identity import DefaultAzureCredential


_DEFAULT_SCOPE = "https://management.azure.com/.default"


@dataclass
class AzureAuthenticator:
    """Wrapper around Azure credential acquisition with basic caching."""

    credential: DefaultAzureCredential | None = None
    scope: str = _DEFAULT_SCOPE

    def __post_init__(self) -> None:
        if self.credential is None:
            self.credential = DefaultAzureCredential(
                exclude_interactive_browser_credential=False
            )
        self._lock = threading.RLock()
        self._cached_token: Optional[str] = None
        self._cached_expiry: Optional[int] = None

    def get_token(self) -> str:
        """Return a bearer token for Azure management APIs."""

        with self._lock:
            if self._cached_token and _not_expired(self._cached_expiry):
                return self._cached_token

            access_token = self.credential.get_token(self.scope)
            self._cached_token = access_token.token
            self._cached_expiry = access_token.expires_on
            return access_token.token


def _not_expired(expiry: Optional[int]) -> bool:
    if not expiry:
        return False
    import time

    # Refresh token a minute early to avoid edge cases.
    return int(time.time()) < expiry - 60
