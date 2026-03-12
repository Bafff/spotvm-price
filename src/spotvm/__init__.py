"""Azure Spot VM Placement Score Analysis Tool."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("spotvm")
except PackageNotFoundError:  # pragma: no cover - during development
    __version__ = "0.0.0-dev"

__all__ = ["__version__"]
