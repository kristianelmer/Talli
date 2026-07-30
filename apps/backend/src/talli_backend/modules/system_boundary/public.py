"""The only supported Python import path for the system-boundary module."""

from typing import Final, Literal

SYSTEM_BOUNDARY_AVAILABLE: Final[Literal["AVAILABLE"]] = "AVAILABLE"
BOUNDARY_UNAVAILABLE: Final[Literal["BOUNDARY_UNAVAILABLE"]] = "BOUNDARY_UNAVAILABLE"

__all__ = ["BOUNDARY_UNAVAILABLE", "SYSTEM_BOUNDARY_AVAILABLE"]
