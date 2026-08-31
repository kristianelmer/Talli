import asyncio
import base64
import json
from collections.abc import Mapping
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from talli_backend.adapters.supabase_company_access import (
    SupabaseCompanyAccessAdapter,
    SupabaseConfiguration,
)
from talli_backend.main import create_app
from talli_backend.modules.company_access.public import (
    GrantSupportAccessRequest,
    RevokeSupportAccessRequest,
)


CASE_ID = "70000000-0000-4000-8000-000000000007"
COMPANY_ID = "10000000-0000-4000-8000-000000000001"
OPERATOR_ID = "00000000-0000-4000-8000-000000000044"
ADMIN_ID = "00000000-0000-4000-8000-000000000099"
GRANT_OPERATION_ID = "40000000-0000-4000-8000-000000000001"
OPEN_OPERATION_ID = "40000000-0000-4000-8000-000000000002"
REVOKE_OPERATION_ID = "40000000-0000-4000-8000-000000000003"
SUPPORT_RESOURCE_KEYS = (
    "companies",
    "audit_events",
    "company_cancellations",
    "filing_submissions",
    "filing_readiness_snapshots",
    "billing_accounts",
    "billing_payment_events",
    "authority_permissions",
    "authority_test_runs",
    "system_user_requests",
    "production_pilot_entitlements",
    "filing_approval_snapshots",
    "production_filing_submissions",
    "production_filing_events",
    "production_feedback_artifacts",
    "documents",
    "storage_objects",
    "company_deletion_reviews",
)


def support_resources() -> dict[str, list[dict[str, object]]]:
    return {key: [] for key in SUPPORT_RESOURCE_KEYS}


def access_token(*, aal: str = "aal2", mfa_age_seconds: int = 30) -> str:
    now = int(datetime.now(UTC).timestamp())
    claims = {
        "aal": aal,
        "amr": [{"method": "totp", "timestamp": now - mfa_age_seconds}],
    }
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


def headers(token: str | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token or access_token()}"}


class SupportAccessGatewayStub:
    def __init__(self, *, role: str = "admin") -> None:
        self.role = role
        self.calls: list[tuple[str, object]] = []

    async def session_subject(self, _access_token: str) -> str:
        return ADMIN_ID

    async def support_operator(
        self, _access_token: str, _subject: str
    ) -> Mapping[str, object] | None:
        if self.role not in {"support", "admin"}:
            return None
        return {"role": self.role, "active": True}

    @staticmethod
    def grant(*, revoked: bool = False) -> Mapping[str, object]:
        return {
            "case_id": CASE_ID,
            "company_id": COMPANY_ID,
            "operator_user_id": OPERATOR_ID,
            "reason": "customer_request",
            "scopes": ["profile", "audit", "cancellation"],
            "starts_at": "2026-08-30T08:00:00Z",
            "expires_at": "2026-08-30T16:00:00Z",
            "granted_by": ADMIN_ID,
            "granted_at": "2026-08-30T07:59:00Z",
            "revoked_at": "2026-08-30T09:00:00Z" if revoked else None,
            "revoked_by": ADMIN_ID if revoked else None,
            "revocation_reason": "case_closed" if revoked else None,
        }

    async def grant_support_access(
        self, _access_token: str, command: GrantSupportAccessRequest
    ) -> Mapping[str, object]:
        self.calls.append(("grant_support_access", command))
        return self.grant()

    async def revoke_support_access(
        self, _access_token: str, case_id: str, command: RevokeSupportAccessRequest
    ) -> Mapping[str, object] | None:
        self.calls.append(("revoke_support_access", (case_id, command)))
        return self.grant(revoked=True) if case_id == CASE_ID else None

    async def open_support_case(
        self, _access_token: str, case_id: str, operation_id: str
    ) -> Mapping[str, object] | None:
        self.calls.append(("open_support_case", (case_id, operation_id)))
        if case_id != CASE_ID:
            return None
        return {
            "operation_id": operation_id,
            "case_id": case_id,
            "company_id": COMPANY_ID,
            "opened_by": OPERATOR_ID,
            "opened_at": "2026-08-30T08:15:00Z",
        }

    async def read_support_case(
        self, _access_token: str, case_id: str
    ) -> Mapping[str, object] | None:
        self.calls.append(("read_support_case", case_id))
        if case_id != CASE_ID:
            return None
        resources = support_resources()
        resources["companies"] = [
            {
                "id": COMPANY_ID,
                "org_number": "123456789",
                "name": "Talli Holding AS",
                "entity_type": "AS",
                "address": "Testveien 1",
                "postal_code": "0001",
                "city": "Oslo",
                "status_text": "Active",
                "source": "brreg",
                "created_by": ADMIN_ID,
                "identity_confirmed_at": "2026-08-30T08:00:00Z",
                "identity_locked_at": "2026-08-30T08:00:00Z",
                "created_at": "2026-08-30T08:00:00Z",
            }
        ]
        return {
            "case_id": case_id,
            "company_id": COMPANY_ID,
            "scopes": ["profile", "audit", "cancellation"],
            "resources": resources,
        }

    def __getattr__(self, _name: str):
        async def unused(*_args: object, **_kwargs: object):
            return []

        return unused


def grant_body() -> dict[str, object]:
    return {
        "operationId": GRANT_OPERATION_ID,
        "companyId": COMPANY_ID,
        "operatorUserId": OPERATOR_ID,
        "reason": "customer_request",
        "scopes": ["profile", "audit", "cancellation"],
        "startsAt": "2026-08-30T08:00:00Z",
        "expiresAt": "2026-08-30T16:00:00Z",
    }


def test_admin_grants_and_revokes_a_generated_case_through_post_commands() -> None:
    gateway = SupportAccessGatewayStub()
    client = TestClient(create_app(gateway))

    granted = client.post(
        "/api/v1/company-access/operator-support-grants",
        headers=headers(),
        json=grant_body(),
    )
    revoked = client.post(
        f"/api/v1/company-access/operator-support-grants/{CASE_ID}/revocations",
        headers=headers(),
        json={"operationId": REVOKE_OPERATION_ID, "reason": "case_closed"},
    )

    assert granted.status_code == 201, granted.text
    assert granted.json()["grant"]["caseId"] == CASE_ID
    assert "caseId" not in grant_body()
    grant_command = gateway.calls[0][1]
    assert isinstance(grant_command, GrantSupportAccessRequest)
    assert str(grant_command.operation_id) == GRANT_OPERATION_ID
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["grant"]["revocationReason"] == "case_closed"
    revoked_case, revoke_command = gateway.calls[1][1]
    assert revoked_case == CASE_ID
    assert isinstance(revoke_command, RevokeSupportAccessRequest)
    assert str(revoke_command.operation_id) == REVOKE_OPERATION_ID


def test_open_is_explicit_post_and_following_get_is_read_only() -> None:
    gateway = SupportAccessGatewayStub(role="support")
    client = TestClient(create_app(gateway))

    wrong_method = client.get(
        f"/api/v1/company-access/operator-support-cases/{CASE_ID}/openings",
        headers=headers(),
    )
    opened = client.post(
        f"/api/v1/company-access/operator-support-cases/{CASE_ID}/openings",
        headers=headers(),
        json={"operationId": OPEN_OPERATION_ID},
    )
    calls_after_open = list(gateway.calls)
    snapshot = client.get(
        f"/api/v1/company-access/operator-support-cases/{CASE_ID}",
        headers=headers(),
    )

    assert wrong_method.status_code == 405
    assert opened.status_code == 201, opened.text
    assert opened.json()["opening"] == {
        "operationId": OPEN_OPERATION_ID,
        "caseId": CASE_ID,
        "companyId": COMPANY_ID,
        "openedBy": OPERATOR_ID,
        "openedAt": "2026-08-30T08:15:00Z",
    }
    assert calls_after_open[-1] == (
        "open_support_case",
        (CASE_ID, OPEN_OPERATION_ID),
    )
    assert snapshot.status_code == 200, snapshot.text
    assert snapshot.json()["caseId"] == CASE_ID
    assert snapshot.json()["resources"]["companies"][0]["id"] == COMPANY_ID
    assert gateway.calls[len(calls_after_open):] == [("read_support_case", CASE_ID)]


def test_deprecated_v1_company_search_overlap_is_authenticated_and_always_empty() -> None:
    gateway = SupportAccessGatewayStub(role="support")
    client = TestClient(create_app(gateway))

    unauthenticated = client.get(
        "/api/v1/company-access/operator-companies?query=Talli"
    )
    overlap = client.get(
        "/api/v1/company-access/operator-companies?query=Talli",
        headers=headers(),
    )

    assert unauthenticated.status_code == 401
    assert overlap.status_code == 200
    assert overlap.json() == {"companies": []}
    assert gateway.calls == []


def test_support_commands_fail_closed_for_role_mfa_and_guessed_case_id() -> None:
    non_admin = SupportAccessGatewayStub(role="support")
    non_admin_response = TestClient(create_app(non_admin)).post(
        "/api/v1/company-access/operator-support-grants",
        headers=headers(),
        json=grant_body(),
    )
    stale_mfa = TestClient(create_app(SupportAccessGatewayStub())).post(
        f"/api/v1/company-access/operator-support-cases/{CASE_ID}/openings",
        headers=headers(access_token(mfa_age_seconds=901)),
        json={"operationId": OPEN_OPERATION_ID},
    )
    guessed_case = "70000000-0000-4000-8000-000000000099"
    guessed = TestClient(create_app(SupportAccessGatewayStub(role="support"))).get(
        f"/api/v1/company-access/operator-support-cases/{guessed_case}",
        headers=headers(),
    )

    assert non_admin_response.status_code == 404
    assert non_admin.calls == []
    assert stale_mfa.status_code == 403
    assert stale_mfa.json()["code"] == "FRESH_MFA_REQUIRED"
    assert guessed.status_code == 404
    assert guessed.json()["code"] == "COMPANY_ACCESS_NOT_FOUND"


def test_adapter_maps_support_workflows_to_the_exact_executor_rpcs() -> None:
    adapter = SupabaseCompanyAccessAdapter(
        SupabaseConfiguration(url="http://127.0.0.1:1", anon_key="anon-test-key")
    )
    calls: list[tuple[str, Mapping[str, object]]] = []

    async def rpc(
        _token: str, function_name: str, body: Mapping[str, object]
    ) -> Mapping[str, object] | None:
        calls.append((function_name, body))
        if function_name == "company_access_open_support_case":
            return {
                "operation_id": OPEN_OPERATION_ID,
                "case_id": CASE_ID,
                "company_id": COMPANY_ID,
                "opened_by": OPERATOR_ID,
                "opened_at": "2026-08-30T08:15:00Z",
            }
        if function_name == "company_access_read_support_case":
            resources = support_resources()
            return {
                "case_id": CASE_ID,
                "company_id": COMPANY_ID,
                "scopes": ["profile"],
                "resources": resources,
            }
        return SupportAccessGatewayStub.grant(
            revoked=function_name == "company_access_revoke_support_access"
        )

    adapter._rpc_row = rpc  # type: ignore[method-assign]
    grant_command = GrantSupportAccessRequest.model_validate(grant_body())
    revoke_command = RevokeSupportAccessRequest.model_validate({
        "operationId": REVOKE_OPERATION_ID,
        "reason": "case_closed",
    })

    adapter_results = [
        adapter.grant_support_access("bearer", grant_command),
        adapter.revoke_support_access("bearer", CASE_ID, revoke_command),
        adapter.open_support_case("bearer", CASE_ID, OPEN_OPERATION_ID),
        adapter.read_support_case("bearer", CASE_ID),
    ]
    for result in adapter_results:
        assert asyncio.run(result) is not None

    assert [name for name, _body in calls] == [
        "company_access_grant_support_access",
        "company_access_revoke_support_access",
        "company_access_open_support_case",
        "company_access_read_support_case",
    ]
    assert calls[0][1]["p_operation_id"] == grant_command.operation_id
    assert "p_case_id" not in calls[0][1]
    assert calls[1][1] == {
        "p_operation_id": revoke_command.operation_id,
        "p_case_id": CASE_ID,
        "p_revocation_reason": "case_closed",
    }
    assert calls[2][1] == {
        "p_operation_id": OPEN_OPERATION_ID,
        "p_case_id": CASE_ID,
    }
    assert calls[3][1] == {"p_case_id": CASE_ID}
