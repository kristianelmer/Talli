"""The only supported Python import path for the system-boundary module."""

from typing import Callable, Final, Literal, Protocol, TypeVar

SYSTEM_BOUNDARY_AVAILABLE: Final[Literal["AVAILABLE"]] = "AVAILABLE"
BOUNDARY_UNAVAILABLE: Final[Literal["BOUNDARY_UNAVAILABLE"]] = "BOUNDARY_UNAVAILABLE"


class SystemBoundaryTransport(Protocol):
    """Callable composition adapter that constructs the production boundary."""

    def __call__(self) -> object: ...


Adapter = TypeVar("Adapter", bound=Callable[..., object])


def adapter_for(port: type[SystemBoundaryTransport]) -> Callable[[Adapter], Adapter]:
    """Register a source-level adapter binding for architecture verification."""

    def register(adapter: Adapter) -> Adapter:
        setattr(adapter, "__talli_port__", port)
        return adapter

    return register


__all__ = [
    "BOUNDARY_UNAVAILABLE",
    "SYSTEM_BOUNDARY_AVAILABLE",
    "SystemBoundaryTransport",
    "adapter_for",
]
