from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from .models import CPUArchitecture

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None


DEFAULT_CACHE_TTL_MINUTES = 15
DEFAULT_OS_TYPE = "linux"
VALID_OS_TYPES = {"linux", "windows"}
VALID_CPU_ARCHS = {"x64", "arm"}


@dataclass
class ToolConfig:
    """Runtime configuration for the Spot VM analysis tool."""

    subscription_id: str = ""
    regions: list[str] = field(default_factory=list)
    sizes: list[str] = field(default_factory=list)
    desired_count: int = 1
    os_type: str = DEFAULT_OS_TYPE
    availability_zones: bool = False
    cache_ttl_minutes: int = DEFAULT_CACHE_TTL_MINUTES
    max_sizes_per_request: int = 5
    max_regions_per_request: int = 8
    retry_attempts: int = 4
    retry_backoff_seconds: float = 2.0
    result_limit: int | None = None
    save_report: Path | None = None
    emit_json: bool = False
    enable_placement: bool = False
    baseline_sku: str | None = None
    cpu_arch: CPUArchitecture | None = None

    def __post_init__(self) -> None:
        self.regions = _clean_list(self.regions)
        self.sizes = _clean_list(self.sizes)
        _validate_placement_mode(self)
        _validate_required_lists(self.regions, self.sizes)
        _validate_desired_count(self.desired_count, self.enable_placement)
        self.os_type = _normalize_os_type(self.os_type)
        self.cpu_arch = _normalize_cpu_arch(self.cpu_arch)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolConfig:
        payload = data.copy()
        save_report = payload.get("save_report")
        if save_report:
            payload["save_report"] = Path(save_report)
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "subscription_id": self.subscription_id,
            "regions": self.regions,
            "sizes": self.sizes,
            "os_type": self.os_type,
            "cache_ttl_minutes": self.cache_ttl_minutes,
            "max_sizes_per_request": self.max_sizes_per_request,
            "max_regions_per_request": self.max_regions_per_request,
            "retry_attempts": self.retry_attempts,
            "retry_backoff_seconds": self.retry_backoff_seconds,
            "result_limit": self.result_limit,
            "save_report": str(self.save_report) if self.save_report else None,
            "emit_json": self.emit_json,
            "enable_placement": self.enable_placement,
            "baseline_sku": self.baseline_sku,
            "cpu_arch": self.cpu_arch,
        }
        if self.enable_placement:
            payload["desired_count"] = self.desired_count
            payload["availability_zones"] = self.availability_zones
        return payload


def _clean_list(values: Iterable[str]) -> list[str]:
    return [v.strip() for v in values if v and v.strip()]


def _validate_placement_mode(config: ToolConfig) -> None:
    if config.enable_placement and not config.subscription_id:
        raise ValueError(
            "subscription_id is required when --placement-check is enabled. "
            "Provide --subscription-id or remove --placement-check."
        )
    if config.availability_zones and not config.enable_placement:
        raise ValueError("availability_zones requires enable_placement")


def _validate_required_lists(regions: list[str], sizes: list[str]) -> None:
    if not regions:
        raise ValueError("At least one region must be supplied")
    if not sizes:
        raise ValueError(
            "At least one VM size must be supplied via --sizes, OR use --min-vcpu/--min-ram for auto-discovery"
        )


def _validate_desired_count(desired_count: int, enable_placement: bool) -> None:
    if desired_count <= 0:
        raise ValueError("desired_count must be positive")
    if desired_count != 1 and not enable_placement:
        raise ValueError("desired_count requires enable_placement")


def _normalize_os_type(os_type: str) -> str:
    normalized_os_type = os_type.lower()
    if normalized_os_type not in VALID_OS_TYPES:
        raise ValueError(f"os_type must be one of {sorted(VALID_OS_TYPES)}")
    return normalized_os_type


def _normalize_cpu_arch(cpu_arch: CPUArchitecture | None) -> CPUArchitecture | None:
    if cpu_arch is None:
        return None
    normalized_cpu_arch = cpu_arch.lower()
    if normalized_cpu_arch not in VALID_CPU_ARCHS:
        raise ValueError(f"cpu_arch must be one of {sorted(VALID_CPU_ARCHS)}")
    return cast(CPUArchitecture, normalized_cpu_arch)


def load_config_file(path: Path) -> dict[str, Any]:
    """Load configuration from a JSON or YAML file into a dictionary."""

    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    suffix = path.suffix.lower()
    raw = path.read_text(encoding="utf-8")
    if suffix in {".json"}:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("Configuration file must contain a JSON object at the top level.")
        return cast(dict[str, Any], parsed)
    if suffix in {".yaml", ".yml"}:
        if yaml is None:
            raise RuntimeError("PyYAML is required to parse YAML configuration files")
        parsed = yaml.safe_load(raw) or {}
        if not isinstance(parsed, dict):
            raise ValueError("Configuration file must contain a YAML mapping at the top level.")
        return cast(dict[str, Any], parsed)
    raise ValueError("Unsupported configuration file format. Use JSON or YAML.")


def merge_cli_overrides(config_data: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Overlay CLI-provided overrides onto base configuration data."""

    result = config_data.copy()
    for key, value in overrides.items():
        if value is None:
            continue
        result[key] = value
    return result
