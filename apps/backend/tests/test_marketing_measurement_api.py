import time

from fastapi.testclient import TestClient

from talli_backend.modules.marketing_measurement.public import (
    MarketingFunnelReport,
    MarketingMeasurementEvent,
    MarketingMeasurementGateway,
    MarketingRepeatedSignal,
)
from talli_backend.main import create_app


INTERNAL_KEY = "m" * 32
INTERNAL_HEADERS = {"X-Talli-Marketing-Measurement-Key": INTERNAL_KEY}
SESSION_HASH = "a" * 64


class OperatorGatewayStub:
    async def session_subject(self, access_token: str) -> str:
        return "00000000-0000-0000-0000-000000000011"

    async def support_operator(self, _access_token: str, _subject: str):
        return (
            {"user_id": _subject, "role": "admin", "active": True}
            if _access_token == "operator-token"
            else None
        )


class MarketingMeasurementGatewayStub(MarketingMeasurementGateway):
    def __init__(self) -> None:
        self.events: list[MarketingMeasurementEvent] = []
        self.withdrawals: list[str] = []
        self.report_actor_ids: list[str] = []
        self.purge_calls = 0

    async def record(self, event: MarketingMeasurementEvent) -> bool:
        inserted = event.client_event_id not in {
            existing.client_event_id for existing in self.events
        }
        if inserted:
            self.events.append(event)
        return inserted

    async def withdraw(self, anonymous_session_hash: str) -> int:
        self.withdrawals.append(anonymous_session_hash)
        return 2

    async def purge(self) -> int:
        self.purge_calls += 1
        return 0

    async def report(self, actor_id: str, window_days: int) -> MarketingFunnelReport:
        self.report_actor_ids.append(actor_id)
        assert window_days == 30
        return MarketingFunnelReport(
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-31T00:00:00Z",
            counts={"home_view": 10, "signup_start": 2},
            rates={
                "home_to_purchase": 0.2,
                "eligibility_to_purchase": 0.25,
                "company_year_completion": 0.5,
                "refund": 0.0,
                "unsupported": 0.1,
                "acquisition_cost_minor": None,
            },
            median_seconds={
                "home_to_purchase": 420.0,
                "company_year_completion": 86400.0,
            },
            support_by_surface={"eligibility": 3},
            repeated_signals=(
                MarketingRepeatedSignal(
                    event="provisional_clarify",
                    surface="eligibility",
                    reason="missing_required_facts",
                    count=5,
                ),
            ),
        )


def measurement_client() -> tuple[TestClient, MarketingMeasurementGatewayStub]:
    measurement = MarketingMeasurementGatewayStub()
    app = create_app(
        company_access_gateway=OperatorGatewayStub(),
        marketing_measurement_gateway=measurement,
        marketing_measurement_internal_key=INTERNAL_KEY,
    )
    return TestClient(app), measurement


def event_payload() -> dict[str, object]:
    return {
        "clientEventId": "10000000-0000-4000-8000-000000000001",
        "anonymousSessionHash": SESSION_HASH,
        "consentVersion": "marketing-analytics-v1",
        "firstLayerNoticeVersion": "candidate-2026-08-29",
        "firstLayerNoticeSha256": "a" * 64,
        "privacyNoticeVersion": "2026-08-29-candidate",
        "privacyNoticeSha256": "b" * 64,
        "releaseSha256": "c" * 64,
        "event": "home_view",
        "reason": None,
        "surface": "homepage",
        "campaignSource": "direct",
    }


def test_record_endpoint_requires_internal_transport_and_accepts_exact_bounded_event() -> None:
    client, measurement = measurement_client()

    forbidden = client.post("/api/v1/marketing-measurement/events", json=event_payload())
    accepted = client.post(
        "/api/v1/marketing-measurement/events",
        headers=INTERNAL_HEADERS,
        json=event_payload(),
    )
    duplicate = client.post(
        "/api/v1/marketing-measurement/events",
        headers=INTERNAL_HEADERS,
        json=event_payload(),
    )

    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "MARKETING_MEASUREMENT_TRANSPORT_REQUIRED"
    assert accepted.status_code == 202
    assert accepted.json() == {"accepted": True, "duplicate": False}
    assert duplicate.status_code == 202
    assert duplicate.json() == {"accepted": True, "duplicate": True}
    assert len(measurement.events) == 1
    assert measurement.events[0].anonymous_session_hash == SESSION_HASH


def test_record_endpoint_rejects_unknown_fields_and_invalid_reason_pairs() -> None:
    client, measurement = measurement_client()
    extra = event_payload() | {"email": "must-not-cross@example.test"}
    invalid_reason = event_payload() | {
        "event": "provisional_clarify",
        "surface": "eligibility",
        "reason": "a free-text explanation",
    }

    extra_response = client.post(
        "/api/v1/marketing-measurement/events", headers=INTERNAL_HEADERS, json=extra
    )
    reason_response = client.post(
        "/api/v1/marketing-measurement/events",
        headers=INTERNAL_HEADERS,
        json=invalid_reason,
    )

    assert extra_response.status_code == 422
    assert reason_response.status_code == 422
    assert measurement.events == []


def test_record_endpoint_rejects_missing_or_malformed_notice_binding() -> None:
    client, measurement = measurement_client()
    missing = event_payload()
    missing.pop("privacyNoticeSha256")
    malformed = event_payload() | {"releaseSha256": "not-a-release-digest"}

    for payload in (missing, malformed):
        response = client.post(
            "/api/v1/marketing-measurement/events",
            headers=INTERNAL_HEADERS,
            json=payload,
        )
        assert response.status_code == 422
    assert measurement.events == []


def test_withdrawal_deletes_the_bounded_session_without_exposing_raw_rows() -> None:
    client, measurement = measurement_client()

    response = client.post(
        "/api/v1/marketing-measurement/withdrawals",
        headers=INTERNAL_HEADERS,
        json={"anonymousSessionHash": SESSION_HASH},
    )

    assert response.status_code == 200
    assert response.json() == {"deletedEventCount": 2}
    assert measurement.withdrawals == [SESSION_HASH]


def test_report_requires_both_internal_transport_and_active_operator() -> None:
    client, measurement = measurement_client()

    no_transport = client.get(
        "/api/v1/marketing-measurement/report",
        headers={"Authorization": "Bearer operator-token"},
    )
    no_operator = client.get(
        "/api/v1/marketing-measurement/report",
        headers=INTERNAL_HEADERS | {"Authorization": "Bearer nonoperator-token"},
    )
    response = client.get(
        "/api/v1/marketing-measurement/report",
        headers=INTERNAL_HEADERS | {"Authorization": "Bearer operator-token"},
        params={"window_days": 30},
    )

    assert no_transport.status_code == 403
    assert no_operator.status_code == 403
    assert no_operator.json()["code"] == "OPERATOR_ACCESS_REQUIRED"
    assert response.status_code == 200
    assert response.json()["counts"] == {"home_view": 10, "signup_start": 2}
    assert response.json()["rates"]["acquisition_cost_minor"] is None
    assert response.json()["repeatedSignals"] == [{
        "event": "provisional_clarify",
        "surface": "eligibility",
        "reason": "missing_required_facts",
        "count": 5,
    }]
    assert measurement.report_actor_ids == ["00000000-0000-0000-0000-000000000011"]


def test_private_transport_is_an_explicit_combined_openapi_security_contract() -> None:
    client, _measurement = measurement_client()
    contract = client.app.openapi()

    assert contract["components"]["securitySchemes"]["marketingMeasurementKey"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-Talli-Marketing-Measurement-Key",
    }
    assert contract["paths"]["/api/v1/marketing-measurement/events"]["post"]["security"] == [
        {"marketingMeasurementKey": []}
    ]
    assert contract["paths"]["/api/v1/marketing-measurement/withdrawals"]["post"]["security"] == [
        {"marketingMeasurementKey": []}
    ]
    assert contract["paths"]["/api/v1/marketing-measurement/report"]["get"]["security"] == [
        {"bearerAuth": [], "marketingMeasurementKey": []}
    ]


def test_underlength_backend_transport_configuration_fails_closed() -> None:
    measurement = MarketingMeasurementGatewayStub()
    app = create_app(
        company_access_gateway=OperatorGatewayStub(),
        marketing_measurement_gateway=measurement,
        marketing_measurement_internal_key="short",
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/marketing-measurement/events",
        headers={"X-Talli-Marketing-Measurement-Key": "short"},
        json=event_payload(),
    )

    assert response.status_code == 503
    assert response.json()["code"] == "MARKETING_MEASUREMENT_UNAVAILABLE"
    assert measurement.events == []


def test_retention_maintenance_runs_when_the_service_starts() -> None:
    client, measurement = measurement_client()

    with client:
        deadline = time.monotonic() + 1
        while measurement.purge_calls == 0 and time.monotonic() < deadline:
            time.sleep(0.01)

    assert measurement.purge_calls >= 1
