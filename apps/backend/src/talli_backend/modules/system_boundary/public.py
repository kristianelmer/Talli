"""The only supported Python import path for the system-boundary module."""

from typing import Final, Literal

SYSTEM_BOUNDARY_AVAILABLE: Final[Literal["AVAILABLE"]] = "AVAILABLE"

__all__ = ["SYSTEM_BOUNDARY_AVAILABLE"]
