from __future__ import annotations

import json
import logging
import tempfile
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


def test_store_does_not_depend_on_path_write_text(tmp_path, monkeypatch, caplog):
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

    assert "Failed to write cache file" not in caplog.text
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert payload["data"] == {"value": 1}
    assert isinstance(payload["expires_at"], float)


def test_store_preserves_existing_cache_file_when_atomic_replace_fails(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    cache_path = tmp_path / f"{cache._key_digest('example')}.json"
    cache_path.write_text(json.dumps({"expires_at": 123, "data": {"value": "old"}}), encoding="utf-8")

    original_replace = Path.replace

    def raising_replace(self: Path, target: Path):
        if target == cache_path:
            raise PermissionError("replace blocked")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", raising_replace)

    with caplog.at_level(logging.WARNING, logger="spotvm"):
        cache.store("example", {"value": "new"}, ttl_minutes=15)

    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert payload["data"] == {"value": "old"}
    assert "Failed to write cache file" in caplog.text
    assert list(tmp_path.glob(f".{cache_path.name}.*.tmp")) == []


def test_store_cleans_up_temp_file_when_temp_write_fails(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    cache_path = tmp_path / f"{cache._key_digest('example')}.json"
    original_named_temporary_file = tempfile.NamedTemporaryFile

    def failing_named_temporary_file(*args, **kwargs):
        handle = original_named_temporary_file(*args, **kwargs)

        class FailingHandle:
            name = handle.name

            def __enter__(self):
                handle.__enter__()
                return self

            def __exit__(self, exc_type, exc, tb):
                return handle.__exit__(exc_type, exc, tb)

            def write(self, *args, **kwargs):
                raise OSError("temp write failed")

        return FailingHandle()

    monkeypatch.setattr(cache.tempfile, "NamedTemporaryFile", failing_named_temporary_file)

    with caplog.at_level(logging.WARNING, logger="spotvm"):
        cache.store("example", {"value": 1}, ttl_minutes=15)

    assert "Failed to write cache file" in caplog.text
    assert not cache_path.exists()
    assert list(tmp_path.glob(f".{cache_path.name}.*.tmp")) == []


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
