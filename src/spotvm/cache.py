from __future__ import annotations

import hashlib
import json
import logging
import tempfile
import time
from pathlib import Path
from typing import Any

CACHE_DIR = Path.home() / ".cache" / "spotvm"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger("spotvm")


def _key_digest(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _remove_cache_file(path: Path, reason: str) -> bool:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        if reason:
            logger.warning("Failed to remove %s cache file %s: %s", reason, path, exc)
        else:
            logger.warning("Failed to remove cache file %s: %s", path, exc)
        return False
    return True


def load(key: str, ttl_minutes: int) -> Any | None:
    digest = _key_digest(key)
    path = CACHE_DIR / f"{digest}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        logger.warning("Failed to read cache file %s: %s", path, exc)
        return None
    except json.JSONDecodeError as exc:
        logger.warning("Failed to decode cache file %s: %s", path, exc)
        _remove_cache_file(path, "malformed")
        return None

    if not isinstance(payload, dict):
        logger.warning("Cache file %s did not contain an object payload", path)
        _remove_cache_file(path, "malformed")
        return None

    expires_at = payload.get("expires_at")
    if not expires_at or time.time() > expires_at:
        _remove_cache_file(path, "expired")
        return None
    return payload.get("data")


def store(key: str, data: Any, ttl_minutes: int) -> bool:
    digest = _key_digest(key)
    path = CACHE_DIR / f"{digest}.json"
    payload = {
        "expires_at": time.time() + ttl_minutes * 60,
        "data": data,
    }
    try:
        _write_text_atomic(path, json.dumps(payload, indent=2))
    except OSError as exc:
        logger.warning("Failed to write cache file %s: %s", path, exc)
        return False
    return True


def clear() -> None:
    for file in CACHE_DIR.glob("*.json"):
        _remove_cache_file(file, "")


def _write_text_atomic(path: Path, payload: str) -> None:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
        temp_path.replace(path)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise
