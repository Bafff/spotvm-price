from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
import json

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    yaml = None


DEFAULT_CACHE_TTL_MINUTES = 15
DEFAULT_OS_TYPE = "linux"
VALID_OS_TYPES = {"linux", "windows"}


@dataclass
class ToolConfig:
    """Runtime configuration for the Spot VM analysis tool."""

    subscription_id: str
    regions: List[str]
    sizes: List[str]
    desired_count: int
    os_type: str = DEFAULT_OS_TYPE
    availability_zones: bool = False
    cache_ttl_minutes: int = DEFAULT_CACHE_TTL_MINUTES
    max_sizes_per_request: int = 5
    max_regions_per_request: int = 8
    retry_attempts: int = 4
    retry_backoff_seconds: float = 2.0
    result_limit: Optional[int] = None
    save_report: Optional[Path] = None
    emit_json: bool = False
    enable_placement: bool = True

    def __post_init__(self) -> None:
        self.regions = _clean_list(self.regions)
        self.sizes = _clean_list(self.sizes)
        if not self.subscription_id:
            raise ValueError("subscription_id is required")
        if not self.regions:
            raise ValueError("At least one region must be supplied")
        if not self.sizes:
            raise ValueError("At least one VM size must be supplied")
        if self.desired_count <= 0:
            raise ValueError("desired_count must be positive")
        self.os_type = self.os_type.lower()
        if self.os_type not in VALID_OS_TYPES:
            raise ValueError(f"os_type must be one of {sorted(VALID_OS_TYPES)}")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolConfig":
        payload = data.copy()
        save_report = payload.get("save_report")
        if save_report:
            payload["save_report"] = Path(save_report)
        return cls(**payload)

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "subscription_id": self.subscription_id,
            "regions": self.regions,
            "sizes": self.sizes,
            "desired_count": self.desired_count,
            "os_type": self.os_type,
            "availability_zones": self.availability_zones,
            "cache_ttl_minutes": self.cache_ttl_minutes,
            "max_sizes_per_request": self.max_sizes_per_request,
            "max_regions_per_request": self.max_regions_per_request,
            "retry_attempts": self.retry_attempts,
            "retry_backoff_seconds": self.retry_backoff_seconds,
            "result_limit": self.result_limit,
            "save_report": str(self.save_report) if self.save_report else None,
            "emit_json": self.emit_json,
            "enable_placement": self.enable_placement,
        }
        return payload


def _clean_list(values: Iterable[str]) -> List[str]:
    return [v.strip() for v in values if v and v.strip()]


def load_config_file(path: Path) -> Dict[str, Any]:
    """Load configuration from a JSON or YAML file into a dictionary."""

    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    suffix = path.suffix.lower()
    raw = path.read_text(encoding="utf-8")
    if suffix in {".json"}:
        return json.loads(raw)
    if suffix in {".yaml", ".yml"}:
        if yaml is None:
            raise RuntimeError("PyYAML is required to parse YAML configuration files")
        return yaml.safe_load(raw) or {}
    raise ValueError("Unsupported configuration file format. Use JSON or YAML.")


def merge_cli_overrides(config_data: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Overlay CLI-provided overrides onto base configuration data."""

    result = config_data.copy()
    for key, value in overrides.items():
        if value is None:
            continue
        result[key] = value
    return result
