"""Backend-system application port for privacy-bounded marketing measurement."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal, Mapping, Protocol, TypeVar
from uuid import UUID


MARKETING_CONSENT_VERSION: Final = "marketing-analytics-v1"
MARKETING_EVENT_NAMES: Final = (
    "home_view",
    "eligibility_start",
    "provisional_supported",
    "provisional_clarify",
    "provisional_blocked",
    "definitive_eligible",
    "definitive_blocked",
    "signup_start",
    "unsupported_exit",
)
MARKETING_SURFACES: Final = (
    "homepage",
    "eligibility",
    "signup",
)
MARKETING_CAMPAIGN_SOURCES: Final = (
    "direct",
    "organic",
    "community",
    "partner",
    "approved_campaign",
    "unknown",
)
MARKETING_REASON_CODES: Final = (
    "unknown_material_facts",
    "unsupported_company",
    "unsupported_activity",
    "missing_required_facts",
    "new_unsupported_condition",
)

MarketingEventName = Literal[
    "home_view",
    "eligibility_start",
    "provisional_supported",
    "provisional_clarify",
    "provisional_blocked",
    "definitive_eligible",
    "definitive_blocked",
    "signup_start",
    "unsupported_exit",
]
MarketingSurface = Literal[
    "homepage",
    "eligibility",
    "signup",
]
MarketingCampaignSource = Literal[
    "direct", "organic", "community", "partner", "approved_campaign", "unknown"
]
MarketingReasonCode = Literal[
    "unknown_material_facts",
    "unsupported_company",
    "unsupported_activity",
    "missing_required_facts",
    "new_unsupported_condition",
]


@dataclass(frozen=True)
class MarketingMeasurementEvent:
    client_event_id: UUID
    anonymous_session_hash: str
    consent_version: Literal["marketing-analytics-v1"]
    first_layer_notice_version: str
    first_layer_notice_sha256: str
    privacy_notice_version: str
    privacy_notice_sha256: str
    release_sha256: str
    event: MarketingEventName
    reason: MarketingReasonCode | None
    surface: MarketingSurface
    campaign_source: MarketingCampaignSource


@dataclass(frozen=True)
class MarketingRepeatedSignal:
    event: str
    surface: str
    reason: str
    count: int


@dataclass(frozen=True)
class MarketingFunnelReport:
    window_start: str
    window_end: str
    counts: Mapping[str, int]
    rates: Mapping[str, float | int | None]
    median_seconds: Mapping[str, float | int | None]
    support_by_surface: Mapping[str, int]
    repeated_signals: tuple[MarketingRepeatedSignal, ...]


class MarketingMeasurementError(RuntimeError):
    def __init__(self, *, status: int, code: str, detail: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.detail = detail

    @classmethod
    def invalid(cls) -> MarketingMeasurementError:
        return cls(
            status=422,
            code="MARKETING_MEASUREMENT_INVALID",
            detail="The marketing measurement request is invalid.",
        )

    @classmethod
    def unavailable(cls) -> MarketingMeasurementError:
        return cls(
            status=503,
            code="MARKETING_MEASUREMENT_UNAVAILABLE",
            detail="Marketing measurement is temporarily unavailable.",
        )


class MarketingMeasurementGateway(Protocol):
    async def record(self, event: MarketingMeasurementEvent) -> bool: ...

    async def withdraw(self, anonymous_session_hash: str) -> int: ...

    async def purge(self) -> int: ...

    async def report(self, actor_id: str, window_days: int) -> MarketingFunnelReport: ...


Adapter = TypeVar("Adapter", bound=Callable[..., object])


def marketing_measurement_adapter(
    port: type[object],
) -> Callable[[Adapter], Adapter]:
    """Register the selected restricted persistence adapter for verification."""

    def register(adapter: Adapter) -> Adapter:
        setattr(adapter, "__talli_port__", port)  # noqa: B010
        return adapter

    return register


__all__ = [
    "MARKETING_CAMPAIGN_SOURCES",
    "MARKETING_CONSENT_VERSION",
    "MARKETING_EVENT_NAMES",
    "MARKETING_REASON_CODES",
    "MARKETING_SURFACES",
    "MarketingCampaignSource",
    "MarketingEventName",
    "MarketingFunnelReport",
    "MarketingMeasurementError",
    "MarketingMeasurementEvent",
    "MarketingMeasurementGateway",
    "MarketingReasonCode",
    "MarketingRepeatedSignal",
    "MarketingSurface",
    "marketing_measurement_adapter",
]
