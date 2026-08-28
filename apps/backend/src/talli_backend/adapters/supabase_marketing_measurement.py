"""Restricted PostgreSQL adapter for backend-system marketing measurement."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

from talli_backend.modules.marketing_measurement.public import (
    MarketingFunnelReport,
    MarketingMeasurementError,
    MarketingMeasurementEvent,
    MarketingMeasurementGateway,
    MarketingRepeatedSignal,
    marketing_measurement_adapter,
)


@dataclass(frozen=True)
class MarketingMeasurementConfiguration:
    database_url: str


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise MarketingMeasurementError.unavailable()
    return value


def _integer_mapping(value: object) -> dict[str, int]:
    source = _mapping(value)
    if not all(isinstance(key, str) and isinstance(item, int) for key, item in source.items()):
        raise MarketingMeasurementError.unavailable()
    return {str(key): int(item) for key, item in source.items()}


def _number_mapping(value: object) -> dict[str, float | int | None]:
    source = _mapping(value)
    if not all(
        isinstance(key, str)
        and (item is None or isinstance(item, (float, int)))
        and not isinstance(item, bool)
        for key, item in source.items()
    ):
        raise MarketingMeasurementError.unavailable()
    return {str(key): item for key, item in source.items()}


def _report(value: object) -> MarketingFunnelReport:
    raw = _mapping(value)
    required = {
        "window_start",
        "window_end",
        "counts",
        "rates",
        "median_seconds",
        "support_by_surface",
        "repeated_signals",
    }
    if set(raw) != required:
        raise MarketingMeasurementError.unavailable()
    window_start = raw["window_start"]
    window_end = raw["window_end"]
    signals = raw["repeated_signals"]
    if not isinstance(window_start, str) or not isinstance(window_end, str) or not isinstance(signals, list):
        raise MarketingMeasurementError.unavailable()
    repeated: list[MarketingRepeatedSignal] = []
    for value in signals:
        signal = _mapping(value)
        if (
            set(signal) != {"event", "surface", "reason", "count"}
            or not isinstance(signal["event"], str)
            or not isinstance(signal["surface"], str)
            or not isinstance(signal["reason"], str)
            or not isinstance(signal["count"], int)
        ):
            raise MarketingMeasurementError.unavailable()
        repeated.append(MarketingRepeatedSignal(
            event=signal["event"],
            surface=signal["surface"],
            reason=signal["reason"],
            count=signal["count"],
        ))
    return MarketingFunnelReport(
        window_start=window_start,
        window_end=window_end,
        counts=_integer_mapping(raw["counts"]),
        rates=_number_mapping(raw["rates"]),
        median_seconds=_number_mapping(raw["median_seconds"]),
        support_by_surface=_integer_mapping(raw["support_by_surface"]),
        repeated_signals=tuple(repeated),
    )


@marketing_measurement_adapter(MarketingMeasurementGateway)
class SupabaseMarketingMeasurementAdapter(MarketingMeasurementGateway):
    """Execute only the private, typed measurement functions through SET-only roles."""

    def __init__(self, configuration: MarketingMeasurementConfiguration) -> None:
        self._configuration = configuration

    @classmethod
    def from_environment(cls) -> SupabaseMarketingMeasurementAdapter:
        return cls(MarketingMeasurementConfiguration(
            database_url=os.environ.get("TALLI_MARKETING_MEASUREMENT_DATABASE_URL", "")
        ))

    async def _scalar(
        self,
        *,
        role: str,
        query: str,
        parameters: tuple[object, ...],
        actor_id: str | None = None,
    ) -> object:
        if not self._configuration.database_url:
            raise MarketingMeasurementError.unavailable()
        if role not in {
            "marketing_measurement_ingest_executor",
            "marketing_measurement_report_executor",
        }:
            raise ValueError("unsupported marketing-measurement database role")

        def execute() -> object:
            try:
                with psycopg.connect(
                    self._configuration.database_url,
                    connect_timeout=5,
                    row_factory=dict_row,
                ) as connection, connection.transaction():
                    connection.execute(f"set local role {role}")
                    if actor_id is not None:
                        connection.execute(
                            "select pg_catalog.set_config('talli.verified_actor_id', %s, true)",
                            (actor_id,),
                        )
                    row = connection.execute(query, parameters).fetchone()
                    if row is None or len(row) != 1:
                        raise MarketingMeasurementError.unavailable()
                    return next(iter(row.values()))
            except MarketingMeasurementError:
                raise
            except psycopg.OperationalError:
                raise MarketingMeasurementError.unavailable() from None
            except psycopg.DatabaseError as error:
                if any(
                    code in str(error)
                    for code in (
                        "marketing_measurement_invalid_",
                        "marketing_measurement_consent_required",
                        "marketing_measurement_consent_withdrawn",
                        "marketing_measurement_session_expired",
                        "marketing_measurement_event_id_conflict",
                        "marketing_measurement_operator_required",
                    )
                ):
                    raise MarketingMeasurementError.invalid() from None
                raise MarketingMeasurementError.unavailable() from None

        return await asyncio.to_thread(execute)

    async def record(self, event: MarketingMeasurementEvent) -> bool:
        value = await self._scalar(
            role="marketing_measurement_ingest_executor",
            query="""
                select backend_system.record_marketing_funnel_event_v1(
                  %s, %s, %s, %s, %s, %s, %s
                ) as inserted
            """,
            parameters=(
                event.client_event_id,
                event.anonymous_session_hash,
                event.consent_version,
                event.event,
                event.reason,
                event.surface,
                event.campaign_source,
            ),
        )
        if not isinstance(value, bool):
            raise MarketingMeasurementError.unavailable()
        return value

    async def withdraw(self, anonymous_session_hash: str) -> int:
        value = await self._scalar(
            role="marketing_measurement_ingest_executor",
            query="""
                select backend_system.withdraw_marketing_funnel_session_v1(%s) as deleted
            """,
            parameters=(anonymous_session_hash,),
        )
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise MarketingMeasurementError.unavailable()
        return value

    async def purge(self) -> int:
        value = await self._scalar(
            role="marketing_measurement_ingest_executor",
            query="select backend_system.purge_expired_marketing_funnel_events_v1() as deleted",
            parameters=(),
        )
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise MarketingMeasurementError.unavailable()
        return value

    async def report(self, actor_id: str, window_days: int) -> MarketingFunnelReport:
        value = await self._scalar(
            role="marketing_measurement_report_executor",
            query="select backend_system.report_marketing_funnel_v1(%s) as report",
            parameters=(window_days,),
            actor_id=actor_id,
        )
        return _report(value)


__all__ = [
    "MarketingMeasurementConfiguration",
    "SupabaseMarketingMeasurementAdapter",
]
