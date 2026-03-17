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


class TestToolConfigValidation:
    def test_no_subscription_without_placement_succeeds(self):
        config = ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"])
        assert config.subscription_id == ""
        assert config.enable_placement is False

    def test_pricing_only_config_omits_placement_fields(self):
        config = ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"])
        payload = config.to_dict()
        assert "desired_count" not in payload
        assert "availability_zones" not in payload

    def test_placement_without_subscription_fails(self):
        with pytest.raises(ValueError, match="subscription_id is required"):
            ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"], enable_placement=True)

    def test_non_default_desired_count_without_placement_fails(self):
        with pytest.raises(ValueError, match="desired_count requires enable_placement"):
            ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"], desired_count=2)

    def test_availability_zones_without_placement_fails(self):
        with pytest.raises(ValueError, match="availability_zones requires enable_placement"):
            ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"], availability_zones=True)

    def test_placement_with_subscription_succeeds(self):
        config = ToolConfig(
            regions=["centralus"],
            sizes=["Standard_D4s_v5"],
            enable_placement=True,
            subscription_id="abc-123",
        )
        assert config.enable_placement is True

    def test_invalid_cpu_arch_fails(self):
        with pytest.raises(ValueError, match="cpu_arch"):
            ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"], cpu_arch="mips")

    def test_valid_cpu_arch_normalizes(self):
        config = ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"], cpu_arch="X64")
        assert config.cpu_arch == "x64"
