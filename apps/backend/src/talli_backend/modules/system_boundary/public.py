"""The only supported Python import path for the system-boundary module."""

from collections.abc import Callable
from typing import Final, Protocol, TypeVar

SYSTEM_BOUNDARY_AVAILABLE: Final = "AVAILABLE"
BOUNDARY_UNAVAILABLE: Final = "BOUNDARY_UNAVAILABLE"


class SystemBoundaryTransport(Protocol):
    """Callable composition adapter that constructs the production boundary."""

    def __call__(self) -> object: ...


Adapter = TypeVar("Adapter", bound=Callable[..., object])


def adapter_for(port: type[object]) -> Callable[[Adapter], Adapter]:
    """Register a source-level adapter binding for architecture verification."""

    def register(adapter: Adapter) -> Adapter:
        setattr(adapter, "__talli_port__", port)  # noqa: B010
        return adapter

    return register


__all__ = [
    "BOUNDARY_UNAVAILABLE",
    "SYSTEM_BOUNDARY_AVAILABLE",
    "SystemBoundaryTransport",
    "adapter_for",
]
