from __future__ import annotations

import json

import pytest

from spotvm.config import load_config_file


def test_load_config_file_rejects_json_array_top_level(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(["not", "a", "mapping"]), encoding="utf-8")

    with pytest.raises(ValueError, match="JSON object"):
        load_config_file(path)


def test_load_config_file_rejects_yaml_scalar_top_level(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("hello\n", encoding="utf-8")

    with pytest.raises(ValueError, match="YAML mapping"):
        load_config_file(path)
