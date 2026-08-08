import asyncio
import base64
import json
from datetime import datetime, timezone
from collections.abc import Mapping

import pytest
from fastapi.testclient import TestClient

from talli_backend.main import create_app
from talli_backend.modules.company_access.public import (
    CompanyCancellation,
    CompanyDeletionReview,
    CompanyAccessError,
    FinalizeCompanyDeletionGatewayCommand,
    RequestCompanyCancellationGatewayCommand,
    ReviewCompanyDeletionGatewayCommand,
)
from talli_backend.adapters.supabase_company_access import (
    SupabaseCompanyAccessAdapter,
    SupabaseConfiguration,
)


COMPANY_ID = "10000000-0000-0000-0000-000000000001"
CANCELLATION_ID = "50000000-0000-0000-0000-000000000001"
OPERATION_ID = "40000000-0000-0000-0000-000000000001"
OWNER_ID = "00000000-0000-0000-0000-000000000011"


def access_token(*, aal: str = "aal2", mfa_age_seconds: int = 30) -> str:
    now = int(datetime.now(timezone.utc).timestamp())
    claims = {
        "aal": aal,
        "amr": [{"method": "totp", "timestamp": now - mfa_age_seconds}],
    }
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


class LifecycleGatewayStub:
    def __init__(self, *, role: str = "owner") -> None:
        self.role = role
        self.calls: list[tuple[str, object]] = []
        self.hidden = False
        self.rows: list[Mapping[str, object]] | None = None

    async def session_subject(self, _access_token: str) -> str:
        return OWNER_ID

    async def session_identity(self, _access_token: str) -> Mapping[str, object]:
        return {"id": OWNER_ID, "email": "owner@example.no"}

    async def memberships(self, _access_token: str, _subject: str) -> list[Mapping[str, object]]:
        return [{"company_id": COMPANY_ID, "role": self.role, "accepted_at": "2026-08-01T00:00:00Z"}]

    async def companies(self, _access_token: str, company_ids: list[str]) -> list[Mapping[str, object]]:
        return [{
            "id": COMPANY_ID,
            "org_number": "314159265",
            "name": "Talli Holding AS",
            "entity_type": "AS",
            "address": "Testveien 1",
            "postal_code": "0150",
            "city": "Oslo",
            "status_text": "Registrert",
            "source": "Brønnøysundregistrene",
            "created_by": OWNER_ID,
            "identity_confirmed_at": None,
            "identity_locked_at": None,
            "created_at": "2026-07-30T00:00:00Z",
        }] if COMPANY_ID in company_ids else []

    async def cancellations(self, _access_token: str, company_id: str) -> list[Mapping[str, object]]:
        self.calls.append(("cancellations", company_id))
        return [] if self.hidden else (self.rows or [self._cancellation()])

    async def request_cancellation(
        self, _access_token: str, command: RequestCompanyCancellationGatewayCommand
    ) -> Mapping[str, object] | None:
        self.calls.append(("request_cancellation", command))
        return None if self.hidden else self._cancellation()

    async def review_deletion(
        self, _access_token: str, command: ReviewCompanyDeletionGatewayCommand
    ) -> Mapping[str, object] | None:
        self.calls.append(("review_deletion", command))
        if self.hidden:
            return None
        return {
            **self._cancellation(status="deletion_approved" if command.decision == "approved" else "retention_hold"),
            "review": {
                "id": "60000000-0000-0000-0000-000000000001",
                "cancellation_id": CANCELLATION_ID,
                "company_id": COMPANY_ID,
                "decision": command.decision,
                "evidence_reference": command.evidence_reference,
                "reviewed_by": "00000000-0000-0000-0000-000000000044",
                "reviewed_at": "2026-08-08T11:00:00Z",
                "operation_id": command.operation_id,
                "cancellation_revision": command.expected_updated_at,
            },
        }

    async def finalize_deletion(
        self, _access_token: str, command: FinalizeCompanyDeletionGatewayCommand
    ) -> Mapping[str, object] | None:
        self.calls.append(("finalize_deletion", command))
        return None if self.hidden else self._cancellation(status="deleted")

    @staticmethod
    def _cancellation(status: str = "retention_hold") -> Mapping[str, object]:
        return {
            "id": CANCELLATION_ID,
            "company_id": COMPANY_ID,
            "status": status,
            "reason": "Customer requested cancellation",
            "evidence": {
                "archiveIncomeYear": 2025,
                "archiveExportedAt": "2026-08-08T10:00:00Z",
                "archiveDownloadPath": f"/archive/{COMPANY_ID}/2025/download",
            },
            "requested_by": OWNER_ID,
            "requested_at": "2026-08-08T10:30:00Z",
            "reviewed_by": "00000000-0000-0000-0000-000000000044" if status in {"deletion_approved", "deleted"} else None,
            "reviewed_at": "2026-08-08T11:00:00Z" if status in {"deletion_approved", "deleted"} else None,
            "deleted_by": OWNER_ID if status == "deleted" else None,
            "deleted_at": "2026-08-08T12:00:00Z" if status == "deleted" else None,
            "updated_at": "2026-08-08T12:00:00Z" if status == "deleted" else "2026-08-08T10:30:00Z",
        }

    def __getattr__(self, name: str):
        async def unused(*_args: object, **_kwargs: object):
            return []
        return unused


def headers(token: str | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token or access_token()}"}


def test_lists_rls_visible_cancellations_and_conceals_an_empty_tenant_scope() -> None:
    gateway = LifecycleGatewayStub(role="read_only")
    client = TestClient(create_app(gateway))

    visible = client.get(f"/api/v1/company-access/cancellations?company_id={COMPANY_ID}", headers=headers())
    gateway.hidden = True
    concealed = client.get(f"/api/v1/company-access/cancellations?company_id={COMPANY_ID}", headers=headers())

    assert visible.status_code == 200
    assert visible.json()["cancellations"][0]["status"] == "retention_hold"
    assert concealed.status_code == 200
    assert concealed.json() == {"cancellations": []}


def test_lists_legacy_export_required_rows_during_the_expand_deploy_overlap() -> None:
    gateway = LifecycleGatewayStub(role="read_only")
    gateway.rows = [gateway._cancellation(status="export_required")]
    client = TestClient(create_app(gateway))

    response = client.get(
        f"/api/v1/company-access/cancellations?company_id={COMPANY_ID}",
        headers=headers(),
    )

    assert response.status_code == 200
    assert response.json()["cancellations"][0]["status"] == "export_required"


def test_lifecycle_response_models_use_typed_ids_dates_and_forbid_extra_fields() -> None:
    cancellation = LifecycleGatewayStub._cancellation()
    with pytest.raises(ValueError):
        CompanyCancellation(**{**cancellation, "id": "not-a-uuid"})
    with pytest.raises(ValueError):
        CompanyCancellation(**{**cancellation, "requested_at": "2026-08-08"})
    with pytest.raises(ValueError):
        CompanyCancellation(**{**cancellation, "unexpected": True})

    review = {
        "id": "60000000-0000-0000-0000-000000000001",
        "cancellation_id": CANCELLATION_ID,
        "company_id": COMPANY_ID,
        "decision": "approved",
        "evidence_reference": "legal/case-161",
        "reviewed_by": "00000000-0000-0000-0000-000000000044",
        "reviewed_at": "2026-08-08T11:00:00Z",
        "operation_id": OPERATION_ID,
        "cancellation_revision": "2026-08-08T10:30:00Z",
    }
    with pytest.raises(ValueError):
        CompanyDeletionReview(**{**review, "operation_id": "not-a-uuid"})
    with pytest.raises(ValueError):
        CompanyDeletionReview(**{**review, "reviewed_at": "tomorrow"})

    schemas = create_app(LifecycleGatewayStub()).openapi()["components"]["schemas"]
    cancellation_schema = schemas["CompanyCancellation"]
    review_schema = schemas["CompanyDeletionReview"]
    evidence_schema = schemas["CompanyCancellationEvidence"]
    assert cancellation_schema["additionalProperties"] is False
    assert review_schema["additionalProperties"] is False
    assert evidence_schema["additionalProperties"] is False
    assert cancellation_schema["properties"]["id"]["format"] == "uuid"
    assert cancellation_schema["properties"]["requestedAt"]["format"] == "date-time"
    assert review_schema["properties"]["operationId"]["format"] == "uuid"
    assert review_schema["properties"]["cancellationRevision"]["format"] == "date-time"


def test_owner_requests_cancellation_with_a_strict_idempotent_command() -> None:
    gateway = LifecycleGatewayStub()
    client = TestClient(create_app(gateway))

    response = client.post(
        "/api/v1/company-access/cancellations",
        headers=headers(),
        json={
            "operationId": OPERATION_ID,
            "companyId": COMPANY_ID,
            "incomeYear": 2025,
            "reason": "Customer requested cancellation",
        },
    )

    assert response.status_code == 201
    command = gateway.calls[-1][1]
    assert isinstance(command, RequestCompanyCancellationGatewayCommand)
    assert command.operation_id == OPERATION_ID
    assert command.income_year == 2025

    extra = client.post(
        "/api/v1/company-access/cancellations",
        headers=headers(),
        json={
            "operationId": OPERATION_ID,
            "companyId": COMPANY_ID,
            "incomeYear": 2025,
            "reason": "Customer requested cancellation",
            "archiveExportedAt": "caller-controlled",
        },
    )
    assert extra.status_code == 422


def test_request_and_finalize_require_owner_and_fresh_mfa() -> None:
    for role, token in [
        ("reviewer", access_token()),
        ("owner", access_token(aal="aal1")),
        ("owner", access_token(mfa_age_seconds=901)),
    ]:
        client = TestClient(create_app(LifecycleGatewayStub(role=role)))
        response = client.post(
            "/api/v1/company-access/cancellations",
            headers=headers(token),
            json={
                "operationId": OPERATION_ID,
                "companyId": COMPANY_ID,
                "incomeYear": 2025,
                "reason": "Customer requested cancellation",
            },
        )
        assert response.status_code in {403, 404}


def test_admin_review_contract_binds_exact_revision_operation_and_evidence() -> None:
    gateway = LifecycleGatewayStub()
    client = TestClient(create_app(gateway))
    response = client.post(
        f"/api/v1/company-access/cancellations/{CANCELLATION_ID}/reviews",
        headers=headers(),
        json={
            "operationId": OPERATION_ID,
            "companyId": COMPANY_ID,
            "expectedUpdatedAt": "2026-08-08T10:30:00Z",
            "decision": "approved",
            "evidenceReference": "legal-review/2026-08-08/case-161",
        },
    )

    assert response.status_code == 200
    assert response.json()["review"] == {
        "id": "60000000-0000-0000-0000-000000000001",
        "cancellationId": CANCELLATION_ID,
        "companyId": COMPANY_ID,
        "decision": "approved",
        "evidenceReference": "legal-review/2026-08-08/case-161",
        "reviewedBy": "00000000-0000-0000-0000-000000000044",
        "reviewedAt": "2026-08-08T11:00:00Z",
        "operationId": OPERATION_ID,
        "cancellationRevision": "2026-08-08T10:30:00Z",
    }
    command = gateway.calls[-1][1]
    assert isinstance(command, ReviewCompanyDeletionGatewayCommand)
    assert command.cancellation_id == CANCELLATION_ID


def test_review_rejects_blank_evidence_and_owner_cannot_turn_not_found_into_forbidden() -> None:
    gateway = LifecycleGatewayStub()
    client = TestClient(create_app(gateway))
    blank = client.post(
        f"/api/v1/company-access/cancellations/{CANCELLATION_ID}/reviews",
        headers=headers(),
        json={
            "operationId": OPERATION_ID,
            "companyId": COMPANY_ID,
            "expectedUpdatedAt": "2026-08-08T10:30:00Z",
            "decision": "approved",
            "evidenceReference": "   ",
        },
    )
    assert blank.status_code == 422

    gateway.hidden = True
    concealed = client.post(
        f"/api/v1/company-access/cancellations/{CANCELLATION_ID}/reviews",
        headers=headers(),
        json={
            "operationId": OPERATION_ID,
            "companyId": COMPANY_ID,
            "expectedUpdatedAt": "2026-08-08T10:30:00Z",
            "decision": "approved",
            "evidenceReference": "legal-review/case-161",
        },
    )
    assert concealed.status_code == 404
    assert concealed.json()["code"] == "COMPANY_ACCESS_NOT_FOUND"


def test_owner_finalizes_only_through_revision_bound_idempotent_command() -> None:
    gateway = LifecycleGatewayStub()
    client = TestClient(create_app(gateway))
    response = client.post(
        f"/api/v1/company-access/cancellations/{CANCELLATION_ID}/finalize",
        headers=headers(),
        json={
            "operationId": OPERATION_ID,
            "companyId": COMPANY_ID,
            "expectedUpdatedAt": "2026-08-08T11:00:00Z",
        },
    )

    assert response.status_code == 200
    assert response.json()["cancellation"]["status"] == "deleted"
    command = gateway.calls[-1][1]
    assert isinstance(command, FinalizeCompanyDeletionGatewayCommand)
    assert command.cancellation_id == CANCELLATION_ID


def test_lifecycle_gateway_prerequisite_failure_is_stable_and_has_no_success_body() -> None:
    class FailingGateway(LifecycleGatewayStub):
        async def request_cancellation(self, *_args: object) -> Mapping[str, object] | None:
            raise CompanyAccessError(
                status=409,
                code="CANCELLATION_PREREQUISITE_FAILED",
                title="Cancellation prerequisite failed",
                detail="A current complete company archive export is required.",
            )

    response = TestClient(create_app(FailingGateway())).post(
        "/api/v1/company-access/cancellations",
        headers=headers(),
        json={
            "operationId": OPERATION_ID,
            "companyId": COMPANY_ID,
            "incomeYear": 2025,
            "reason": "Customer requested cancellation",
        },
    )
    assert response.status_code == 409
    assert response.json()["code"] == "CANCELLATION_PREREQUISITE_FAILED"
    assert "cancellation" not in response.json()


def test_adapter_lists_cancellations_through_the_query_rpc_not_direct_table_access() -> None:
    adapter = SupabaseCompanyAccessAdapter(
        SupabaseConfiguration(url="http://127.0.0.1:1", anon_key="anon-test-key")
    )
    calls: list[tuple[str, str, str, Mapping[str, object] | None]] = []

    async def request(
        path: str,
        access_token_value: str,
        *,
        method: str = "GET",
        body: Mapping[str, object] | None = None,
    ) -> object:
        calls.append((path, access_token_value, method, body))
        return []

    adapter._request = request  # type: ignore[method-assign]
    assert asyncio.run(adapter.cancellations("bearer", COMPANY_ID)) == []
    assert calls == [(
        "/rest/v1/rpc/company_access_list_cancellations",
        "bearer",
        "POST",
        {"p_company_id": COMPANY_ID},
    )]


def test_adapter_reconciles_unknown_cancellation_outcome_before_retry() -> None:
    adapter = SupabaseCompanyAccessAdapter(
        SupabaseConfiguration(url="http://127.0.0.1:1", anon_key="anon-test-key")
    )
    calls: list[tuple[str, Mapping[str, object] | None]] = []

    async def request(path: str, _token: str, *, method: str = "GET", body=None) -> object:
        calls.append((path, body))
        if len(calls) == 1:
            raise CompanyAccessError(
                status=503, code="COMPANY_ACCESS_UNAVAILABLE",
                title="Company access unavailable", detail="unknown",
            )
        return [{"found": True, "result": LifecycleGatewayStub._cancellation()}]

    adapter._request = request  # type: ignore[method-assign]
    body = {
        "p_operation_id": OPERATION_ID,
        "p_company_id": COMPANY_ID,
        "p_income_year": 2025,
        "p_reason": "Customer requested cancellation",
    }
    result = asyncio.run(adapter._rpc_row("bearer", "company_access_request_cancellation", body))
    assert result == LifecycleGatewayStub._cancellation()
    assert calls[1][0].endswith("/company_access_reconcile_cancellation_operation")
    assert calls[1][1] == {
        **body,
        "p_command_name": "request_cancellation",
    }


@pytest.mark.parametrize("reconciliation", [
    [],
    [{}],
    [{"found": True}],
    [{"found": False, "result": {}}],
    [{"found": "false", "result": None}],
])
def test_adapter_never_retries_after_malformed_reconciliation(reconciliation: object) -> None:
    adapter = SupabaseCompanyAccessAdapter(
        SupabaseConfiguration(url="http://127.0.0.1:1", anon_key="anon-test-key")
    )
    calls = 0

    async def request(path: str, _token: str, *, method: str = "GET", body=None) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise CompanyAccessError(
                status=503, code="COMPANY_ACCESS_UNAVAILABLE",
                title="Company access unavailable", detail="unknown",
            )
        return reconciliation

    adapter._request = request  # type: ignore[method-assign]
    with pytest.raises(CompanyAccessError) as caught:
        asyncio.run(adapter._rpc_row("bearer", "company_access_request_cancellation", {
            "p_operation_id": OPERATION_ID,
            "p_company_id": COMPANY_ID,
            "p_income_year": 2025,
            "p_reason": "Customer requested cancellation",
        }))
    assert caught.value.code == "COMPANY_ACCESS_UNAVAILABLE"
    assert calls == 2


def test_adapter_retries_only_after_explicit_receipt_absence() -> None:
    adapter = SupabaseCompanyAccessAdapter(
        SupabaseConfiguration(url="http://127.0.0.1:1", anon_key="anon-test-key")
    )
    responses: list[object] = [
        CompanyAccessError(status=503, code="COMPANY_ACCESS_UNAVAILABLE", title="Unavailable", detail="unknown"),
        [{"found": False, "result": None}],
        [LifecycleGatewayStub._cancellation()],
    ]

    async def request(*_args: object, **_kwargs: object) -> object:
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    adapter._request = request  # type: ignore[method-assign]
    result = asyncio.run(adapter._rpc_row("bearer", "company_access_request_cancellation", {
        "p_operation_id": OPERATION_ID,
        "p_company_id": COMPANY_ID,
        "p_income_year": 2025,
        "p_reason": "Customer requested cancellation",
    }))
    assert result == LifecycleGatewayStub._cancellation()
    assert responses == []
