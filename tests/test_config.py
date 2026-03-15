from __future__ import annotations

import json

import pytest

from spotvm.config import ToolConfig, load_config_file


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


def test_tool_config_normalizes_lists_os_type_and_cpu_arch():
    config = ToolConfig(
        regions=[" centralus ", "", "eastus"],
        sizes=[" Standard_D4s_v5 ", " "],
        os_type="WINDOWS",
        cpu_arch="ARM",
    )

    assert config.regions == ["centralus", "eastus"]
    assert config.sizes == ["Standard_D4s_v5"]
    assert config.os_type == "windows"
    assert config.cpu_arch == "arm"


def test_tool_config_requires_subscription_for_placement_mode():
    with pytest.raises(ValueError, match="subscription_id is required"):
        ToolConfig(
            regions=["centralus"],
            sizes=["Standard_D4s_v5"],
            enable_placement=True,
        )
