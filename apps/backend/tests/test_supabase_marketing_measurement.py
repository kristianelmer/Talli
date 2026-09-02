import asyncio
import os
from uuid import UUID

import pytest

from talli_backend.adapters.supabase_marketing_measurement import (
    MarketingMeasurementConfiguration,
    SupabaseMarketingMeasurementAdapter,
)
from talli_backend.modules.marketing_measurement.public import (
    MarketingMeasurementError,
    MarketingMeasurementEvent,
)


DATABASE_URL = os.environ.get("TALLI_MARKETING_MEASUREMENT_TEST_DATABASE_URL")
OPERATOR_ID = os.environ.get("TALLI_MARKETING_MEASUREMENT_TEST_OPERATOR_ID")


@pytest.mark.skipif(
    not DATABASE_URL or not OPERATOR_ID,
    reason="the real adapter rehearsal is owned by the PostgreSQL runtime test",
)
def test_restricted_adapter_executes_the_real_measurement_contract() -> None:
    assert DATABASE_URL is not None
    assert OPERATOR_ID is not None
    adapter = SupabaseMarketingMeasurementAdapter(
        MarketingMeasurementConfiguration(database_url=DATABASE_URL)
    )
    event = MarketingMeasurementEvent(
        client_event_id=UUID("30000000-0000-4000-8000-000000000001"),
        anonymous_session_hash="e" * 64,
        consent_version="marketing-analytics-v1",
        first_layer_notice_version="candidate-2026-08-29",
        first_layer_notice_sha256="a" * 64,
        privacy_notice_version="2026-08-29-candidate",
        privacy_notice_sha256="b" * 64,
        release_sha256="c" * 64,
        event="home_view",
        reason=None,
        surface="homepage",
        campaign_source="direct",
    )

    assert asyncio.run(adapter.record(event)) is True
    assert asyncio.run(adapter.record(event)) is False
    report = asyncio.run(adapter.report(OPERATOR_ID, 30))
    assert report.counts["home_view"] >= 1
    assert "anonymous_session_hash" not in repr(report)
    assert asyncio.run(adapter.withdraw(event.anonymous_session_hash)) == 1
    with pytest.raises(MarketingMeasurementError) as withdrawn:
        asyncio.run(adapter.record(MarketingMeasurementEvent(
            client_event_id=UUID("30000000-0000-4000-8000-000000000002"),
            anonymous_session_hash=event.anonymous_session_hash,
            consent_version="marketing-analytics-v1",
            first_layer_notice_version=event.first_layer_notice_version,
            first_layer_notice_sha256=event.first_layer_notice_sha256,
            privacy_notice_version=event.privacy_notice_version,
            privacy_notice_sha256=event.privacy_notice_sha256,
            release_sha256=event.release_sha256,
            event="home_view",
            reason=None,
            surface="homepage",
            campaign_source="direct",
        )))
    assert withdrawn.value.status == 422
    assert asyncio.run(adapter.purge()) >= 0
