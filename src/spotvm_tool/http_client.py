from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

from .auth import AzureAuthenticator


@dataclass
class AzureRestClient:
    """Thin wrapper around requests for Azure management API calls."""

    authenticator: AzureAuthenticator
    user_agent: str = ""

    def __post_init__(self) -> None:
        if not self.user_agent:
            from . import __version__
            self.user_agent = f"spotvm-tool/{__version__}"
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
        })

    def post_json(
        self,
        url: str,
        payload: Dict[str, Any],
        retry_attempts: int = 4,
        retry_backoff_seconds: float = 2.0,
    ) -> Dict[str, Any]:
        body = json.dumps(payload)
        for attempt in range(retry_attempts):
            token = self.authenticator.get_token()
            response = self._session.post(
                url,
                data=body,
                headers={"Authorization": f"Bearer {token}"},
                timeout=60,
            )
            if response.status_code in {429, 500, 502, 503, 504} and attempt + 1 < retry_attempts:
                delay = self._retry_delay(response, retry_backoff_seconds, attempt)
                time.sleep(delay)
                continue
            if not response.ok:
                raise AzureHttpError(url, response.status_code, response.text)
            return response.json()
        raise AzureHttpError(url, response.status_code, response.text)

    def _retry_delay(self, response: requests.Response, backoff: float, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
        return backoff * (2**attempt)


class AzureHttpError(RuntimeError):
    def __init__(self, url: str, status_code: int, body: Optional[str] = None):
        message = f"Azure API request failed ({status_code}) for {url}"
        if body:
            snippet = body.strip()
            if len(snippet) > 400:
                snippet = snippet[:400] + "..."
            message += f": {snippet}"
        super().__init__(message)
        self.url = url
        self.status_code = status_code
        self.body = body
