from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Optional


CACHE_DIR = Path.home() / ".cache" / "spotvm_tool"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _key_digest(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def load(key: str, ttl_minutes: int) -> Optional[Any]:
    digest = _key_digest(key)
    path = CACHE_DIR / f"{digest}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        path.unlink(missing_ok=True)
        return None

    expires_at = payload.get("expires_at")
    if not expires_at or time.time() > expires_at:
        path.unlink(missing_ok=True)
        return None
    return payload.get("data")


def store(key: str, data: Any, ttl_minutes: int) -> None:
    digest = _key_digest(key)
    path = CACHE_DIR / f"{digest}.json"
    payload = {
        "expires_at": time.time() + ttl_minutes * 60,
        "data": data,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def clear() -> None:
    for file in CACHE_DIR.glob("*.json"):
        file.unlink(missing_ok=True)
