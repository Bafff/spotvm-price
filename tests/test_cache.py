from __future__ import annotations

import logging
from pathlib import Path

import spotvm.cache as cache


def test_load_returns_cache_miss_and_warns_on_oserror(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    cache_path = tmp_path / f"{cache._key_digest('example')}.json"
    cache_path.write_text("{}", encoding="utf-8")

    original_read_text = Path.read_text

    def raising_read_text(self: Path, *args, **kwargs):
        if self == cache_path:
            raise PermissionError("no read access")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", raising_read_text)

    with caplog.at_level(logging.WARNING, logger="spotvm"):
        result = cache.load("example", ttl_minutes=15)

    assert result is None
    assert "Failed to read cache file" in caplog.text


def test_store_warns_and_skips_cache_write_on_oserror(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    cache_path = tmp_path / f"{cache._key_digest('example')}.json"

    original_write_text = Path.write_text

    def raising_write_text(self: Path, *args, **kwargs):
        if self == cache_path:
            raise PermissionError("disk full")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", raising_write_text)

    with caplog.at_level(logging.WARNING, logger="spotvm"):
        cache.store("example", {"value": 1}, ttl_minutes=15)

    assert not cache_path.exists()
    assert "Failed to write cache file" in caplog.text


def test_clear_warns_and_continues_on_unlink_oserror(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    cache_path = tmp_path / "stale.json"
    cache_path.write_text("{}", encoding="utf-8")

    original_unlink = Path.unlink

    def raising_unlink(self: Path, *args, **kwargs):
        if self == cache_path:
            raise PermissionError("locked")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", raising_unlink)

    with caplog.at_level(logging.WARNING, logger="spotvm"):
        cache.clear()

    assert cache_path.exists()
    assert "Failed to remove cache file" in caplog.text
