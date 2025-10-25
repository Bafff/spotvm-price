"""Azure Spot VM Placement Score Analysis Tool."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("spotvm-tool")
except PackageNotFoundError:  # pragma: no cover - during development
    __version__ = "0.1.0"

__all__ = ["__version__"]
