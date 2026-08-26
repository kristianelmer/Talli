import asyncio
import base64
import inspect
import json
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Self
from urllib.parse import urlsplit
from uuid import UUID

import pytest
import talli_backend.modules.company_access.public as company_access_public
from fastapi.testclient import TestClient
from talli_backend.adapters.supabase_company_access import (
    SupabaseCompanyAccessAdapter,
    SupabaseConfiguration,
    _database_contract_row,
)
from talli_backend.main import create_app
from talli_backend.modules.company_access.public import (
    AcceptInvitationGatewayCommand,
    AdministerMembershipGatewayCommand,
    CompanyAccessError,
    CreateInvitationGatewayCommand,
    InvitationIdentityGatewayCommand,
    InvitationMutationGatewayCommand,
    ResendInvitationGatewayCommand,
)


def test_rpc_reconciles_one_unknown_outcome_with_the_identical_command() -> None:
    adapter = SupabaseCompanyAccessAdapter(
        SupabaseConfiguration(url="http://127.0.0.1:1", anon_key="anon-test-key")
    )
    calls: list[tuple[str, str, Mapping[str, object]]] = []

    async def request(
        access_token: str,
        function_name: str,
        body: Mapping[str, object],
        **_kwargs: object,
    ) -> list[Mapping[str, object]]:
        calls.append((function_name, access_token, body))
        if len(calls) == 1:
            raise CompanyAccessError(
                status=503,
                code="COMPANY_ACCESS_UNAVAILABLE",
                title="Company access unavailable",
                detail="Company access is temporarily unavailable.",
            )
        return [{"id": "30000000-0000-0000-0000-000000000001"}]

    adapter._database_rpc_rows = request  # type: ignore[method-assign]
    body = {
        "p_operation_id": "40000000-0000-0000-0000-000000000001",
        "p_company_id": "10000000-0000-0000-0000-000000000001",
    }

    result = asyncio.run(adapter._rpc_row("bearer", "company_access_create_invitation", body))

    assert result == {"id": "30000000-0000-0000-0000-000000000001"}
    assert calls == [
        ("company_access_create_invitation", "bearer", body),
        ("company_access_create_invitation", "bearer", body),
    ]


def test_psycopg_rows_are_normalized_to_contract_scalars() -> None:
    company_id = UUID("10000000-0000-0000-0000-000000000001")
    row = _database_contract_row({
        "id": company_id,
        "effective_date": date(2026, 7, 17),
        "created_at": datetime(2026, 7, 17, 12, 0, tzinfo=UTC),
        "nested": {"company_id": company_id},
        "items": [company_id, date(2026, 7, 18)],
        "active": True,
    })

    assert row == {
        "id": str(company_id),
        "effective_date": "2026-07-17",
        "created_at": "2026-07-17T12:00:00+00:00",
        "nested": {"company_id": str(company_id)},
        "items": [str(company_id), "2026-07-18"],
        "active": True,
    }


def access_token(aal: str = "aal1") -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"aal": aal}).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


class CompanyAccessGatewayStub:
    def __init__(self, role: str = "owner") -> None:
        self.role = role
        self.invitation_status = "pending"
        self.invitation_email = "reviewer@example.no"
        self.invitation_expires_at = (
            datetime.now(UTC) + timedelta(days=1)
        ).isoformat().replace("+00:00", "Z")
        self.calls: list[tuple[str, object]] = []

    async def session_subject(self, _access_token: str) -> str:
        return "owner-1"

    async def memberships(
        self, _access_token: str, _subject: str
    ) -> list[Mapping[str, object]]:
        return [{"company_id": "10000000-0000-0000-0000-000000000001", "role": self.role, "accepted_at": "2026-07-30T00:00:00Z"}]

    async def companies(
        self, _access_token: str, company_ids: list[str]
    ) -> list[Mapping[str, object]]:
        companies = {
            "10000000-0000-0000-0000-000000000001": {
                "id": "10000000-0000-0000-0000-000000000001",
                "org_number": "314159265",
                "name": "Talli Holding AS",
                "entity_type": "AS",
                "address": "Testveien 1",
                "postal_code": "0150",
                "city": "Oslo",
                "status_text": "Registrert",
                "source": "Brønnøysundregistrene",
                "created_by": "owner-1",
                "identity_confirmed_at": "2026-07-30T00:00:00Z",
                "identity_locked_at": None,
                "created_at": "2026-07-30T00:00:00Z",
            },
            "20000000-0000-0000-0000-000000000002": {
                "id": "20000000-0000-0000-0000-000000000002",
                "org_number": "271828182",
                "name": "Other Holding AS",
                "entity_type": "AS",
                "address": "Annen vei 2",
                "postal_code": "5003",
                "city": "Bergen",
                "status_text": "Registrert",
                "source": "Brønnøysundregistrene",
                "created_by": "owner-2",
                "identity_confirmed_at": "2026-07-30T00:00:00Z",
                "identity_locked_at": None,
                "created_at": "2026-07-30T00:00:00Z",
            },
        }
        return [companies[company_id] for company_id in company_ids if company_id in companies]

    async def agreement_acceptances(
        self, _access_token: str, company_ids: list[str]
    ) -> list[Mapping[str, object]]:
        return [
            {
                "company_id": company_id,
                "business_terms_version": "2026-07-17",
                "business_terms_effective_date": "2026-07-17",
                "business_terms_path": "/vilkar",
                "business_terms_sha256": "f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543",
                "dpa_version": "2026-07-17",
                "dpa_effective_date": "2026-07-17",
                "dpa_path": "/databehandleravtale",
                "dpa_sha256": "083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c",
                "authority_statement_version": "authority-v1",
                "acceptance_method": "in_app_clickwrap",
            }
            for company_id in company_ids
        ]

    async def company_year_access_states(
        self, _access_token: str, company_ids: list[str]
    ) -> list[Mapping[str, object]]:
        return [
            {
                "company_id": company_id,
                "company_year_admission_id": "20000000-0000-0000-0000-000000000002",
                "admitted_accounting_year": 2026,
                "current_eligibility_decision": "supported",
                "latest_capability_manifest_version": "2026.1",
                "latest_capability_manifest_sha256": (
                    "9f91a66d0e2cb560d880b6b290c707bc45a8d117a4175780c75e2d1ccdb694de"
                ),
                "eligibility_reason_explanations": [],
                "eligibility_next_step_code": "CONTINUE_COMPANY_YEAR",
                "eligibility_next_step": "Fortsett selskapsåret i Talli.",
                "consequential_operations_allowed": True,
                "archive_export_available": True,
            }
            for company_id in company_ids
        ]

    async def session_identity(self, _access_token: str) -> Mapping[str, object]:
        return {"id": "owner-1", "email": self.invitation_email}

    async def invitations(
        self, _access_token: str, company_id: str
    ) -> list[Mapping[str, object]]:
        self.calls.append(("invitations", company_id))
        return [self._invitation()]

    async def create_invitation(
        self, _access_token: str, invitation: CreateInvitationGatewayCommand
    ) -> Mapping[str, object]:
        self.calls.append(("create_invitation", invitation))
        return {
            **self._invitation(role=invitation.role, email=invitation.invited_email),
            "delivery_token": invitation.acceptance_token,
            "delivery_company_name": "Talli Holding AS",
        }

    async def lookup_invitation(
        self, _access_token: str, command: InvitationIdentityGatewayCommand
    ) -> Mapping[str, object] | None:
        self.calls.append(("lookup_invitation", command))
        if self.invitation_status != "pending":
            return None
        return {
            **self._invitation(),
            "company_name": "Talli Holding AS",
        }

    async def accept_invitation(
        self, _access_token: str, command: AcceptInvitationGatewayCommand
    ) -> Mapping[str, object] | None:
        self.calls.append(("accept_invitation", command))
        return None if self.invitation_status != "pending" else self._membership()

    async def revoke_invitation(
        self, _access_token: str, command: InvitationMutationGatewayCommand
    ) -> Mapping[str, object] | None:
        self.calls.append(("revoke_invitation", command))
        return self._invitation(status="revoked")

    async def resend_invitation(
        self, _access_token: str, command: ResendInvitationGatewayCommand
    ) -> Mapping[str, object] | None:
        self.calls.append(("resend_invitation", command))
        return {
            **self._invitation(),
            "delivery_token": command.acceptance_token,
            "delivery_company_name": "Talli Holding AS",
        }

    async def company_memberships(
        self, _access_token: str, company_id: str
    ) -> list[Mapping[str, object]]:
        self.calls.append(("company_memberships", company_id))
        return [self._membership()]

    async def administer_membership(
        self, _access_token: str, command: AdministerMembershipGatewayCommand
    ) -> Mapping[str, object] | None:
        self.calls.append(("administer_membership", command))
        return self._membership(
            role=str(command.role or "reviewer"),
            state=str(command.state or "active"),
        )

    async def pending_invitation_side_effects(
        self, _access_token: str
    ) -> list[Mapping[str, object]]:
        self.calls.append(("pending_invitation_side_effects", None))
        return [{
            "operation_id": "40000000-0000-0000-0000-000000000009",
            "command_name": "create_invitation",
            "company_id": "10000000-0000-0000-0000-000000000001",
            "result": {
                **self._invitation(),
                "delivery_company_name": "Talli Holding AS",
            },
            "delivery_token": "delivery-token",
        }]

    async def complete_invitation_side_effect(
        self, _access_token: str, operation_id: str
    ) -> bool:
        self.calls.append(("complete_invitation_side_effect", operation_id))
        return True

    def _invitation(
        self,
        *,
        role: str = "reviewer",
        email: str | None = None,
        status: str | None = None,
    ) -> Mapping[str, object]:
        return {
            "id": "30000000-0000-0000-0000-000000000001",
            "company_id": "10000000-0000-0000-0000-000000000001",
            "invited_email": email or self.invitation_email,
            "role": role,
            "status": status or self.invitation_status,
            "expires_at": self.invitation_expires_at,
            "created_at": "2026-08-01T00:00:00Z",
            "updated_at": "2026-08-01T00:00:00Z",
        }

    @staticmethod
    def _membership(
        *, role: str = "reviewer", state: str = "active"
    ) -> Mapping[str, object]:
        return {
            "company_id": "10000000-0000-0000-0000-000000000001",
            "user_id": "00000000-0000-0000-0000-000000000044",
            "role": role,
            "state": state,
            "accepted_at": "2026-08-01T00:00:00Z",
        }


class LocalSupabaseGateway:
    """Hermetic HTTP server for the only remaining Supabase HTTP seam: Auth."""

    def __init__(self, redirect_to: str | None = None) -> None:
        self.calls: list[tuple[str, str, str, str]] = []
        self.redirect_to = redirect_to
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = Thread(target=self._server.serve_forever, daemon=True)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                path = urlsplit(self.path).path
                authorization = self.headers.get("Authorization", "")
                api_key = self.headers.get("apikey", "")
                gateway.calls.append((path, authorization, api_key, self.path))
                token = authorization.removeprefix("Bearer ")
                if path == "/auth/v1/user":
                    if gateway.redirect_to:
                        self.send_response(302)
                        self.send_header("Location", gateway.redirect_to)
                        self.end_headers()
                        return
                    if token == "provider-failure":
                        self._json(500, {"message": "upstream failure"})
                    elif token in {"malformed", "expired", "revoked"}:
                        self._json(401, {"message": "invalid session"})
                    elif token == access_token("aal1") or token == access_token("aal2"):
                        self._json(200, {"id": "member-1", "email": "member@example.no"})
                    elif token == f"outsider-{access_token('aal2')}":
                        self._json(200, {"id": "outsider-1"})
                    else:
                        self._json(401, {"message": "invalid session"})
                    return
                self._json(404, {})

            def _json(self, status: int, payload: object) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        return Handler

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._server.shutdown()
        self._thread.join()
        self._server.server_close()


def gateway_app(server: LocalSupabaseGateway):
    return create_app(
        SupabaseCompanyAccessAdapter(
            SupabaseConfiguration(url=server.url, anon_key="anon-test-key")
        )
    )


def test_company_context_fails_closed_without_a_bearer_session() -> None:
    response = TestClient(create_app()).get("/api/v1/company-access/context")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTHENTICATION_REQUIRED"


def test_company_context_returns_full_context_only_after_aal2() -> None:
    app = create_app(CompanyAccessGatewayStub())

    response = TestClient(app).get(
        "/api/v1/company-access/context",
        headers={"Authorization": f"Bearer {access_token('aal2')}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "selectedCompany": {
            "id": "10000000-0000-0000-0000-000000000001",
            "orgNumber": "314159265",
            "name": "Talli Holding AS",
            "entityType": "AS",
            "address": "Testveien 1",
            "postalCode": "0150",
            "city": "Oslo",
            "statusText": "Registrert",
            "source": "Brønnøysundregistrene",
            "createdBy": "owner-1",
            "identityConfirmedAt": "2026-07-30T00:00:00Z",
            "identityLockedAt": None,
            "createdAt": "2026-07-30T00:00:00Z",
            "role": "owner",
            "resourceScope": "owner_sensitive",
            "aal": "aal2",
            "currentAgreementAccepted": True,
            "companyYearAdmissionId": "20000000-0000-0000-0000-000000000002",
            "admittedAccountingYear": 2026,
            "currentEligibilityDecision": "supported",
            "eligibilityReasonExplanations": [],
            "eligibilityNextStepCode": "CONTINUE_COMPANY_YEAR",
            "eligibilityNextStep": "Fortsett selskapsåret i Talli.",
            "consequentialOperationsAllowed": True,
            "archiveExportAvailable": True,
        },
        "companies": [{
            "id": "10000000-0000-0000-0000-000000000001",
            "orgNumber": "314159265",
            "name": "Talli Holding AS",
            "entityType": "AS",
            "address": "Testveien 1",
            "postalCode": "0150",
            "city": "Oslo",
            "statusText": "Registrert",
            "source": "Brønnøysundregistrene",
            "createdBy": "owner-1",
            "identityConfirmedAt": "2026-07-30T00:00:00Z",
            "identityLockedAt": None,
            "createdAt": "2026-07-30T00:00:00Z",
            "role": "owner",
            "resourceScope": "owner_sensitive",
            "aal": "aal2",
            "currentAgreementAccepted": True,
            "companyYearAdmissionId": "20000000-0000-0000-0000-000000000002",
            "admittedAccountingYear": 2026,
            "currentEligibilityDecision": "supported",
            "eligibilityReasonExplanations": [],
            "eligibilityNextStepCode": "CONTINUE_COMPANY_YEAR",
            "eligibilityNextStep": "Fortsett selskapsåret i Talli.",
            "consequentialOperationsAllowed": True,
            "archiveExportAvailable": True,
        }],
    }


def test_company_context_accepts_uuid_values_returned_by_psycopg() -> None:
    class PsycopgGatewayStub(CompanyAccessGatewayStub):
        async def companies(
            self, access_token: str, company_ids: list[str]
        ) -> list[Mapping[str, object]]:
            rows = await super().companies(access_token, company_ids)
            return [{**row, "id": UUID(str(row["id"]))} for row in rows]

        async def agreement_acceptances(
            self, access_token: str, company_ids: list[str]
        ) -> list[Mapping[str, object]]:
            rows = await super().agreement_acceptances(access_token, company_ids)
            return [
                {
                    **row,
                    "business_terms_effective_date": date(2026, 7, 17),
                    "dpa_effective_date": date(2026, 7, 17),
                }
                for row in rows
            ]

    response = TestClient(create_app(PsycopgGatewayStub())).get(
        "/api/v1/company-access/context",
        headers={"Authorization": f"Bearer {access_token('aal2')}"},
    )

    assert response.status_code == 200
    assert response.json()["selectedCompany"]["id"] == (
        "10000000-0000-0000-0000-000000000001"
    )
    assert response.json()["selectedCompany"]["currentAgreementAccepted"] is True


def test_company_context_immediately_closes_a_stale_manifest_gate() -> None:
    class StaleManifestGateway(CompanyAccessGatewayStub):
        async def company_year_access_states(
            self, access_token: str, company_ids: list[str]
        ) -> list[Mapping[str, object]]:
            rows = await super().company_year_access_states(access_token, company_ids)
            return [
                {**row, "latest_capability_manifest_sha256": "0" * 64}
                for row in rows
            ]

    response = TestClient(create_app(StaleManifestGateway())).get(
        "/api/v1/company-access/context",
        headers={"Authorization": f"Bearer {access_token('aal2')}"},
    )

    assert response.status_code == 200
    company = response.json()["selectedCompany"]
    assert company["currentEligibilityDecision"] == "clarify"
    assert company["consequentialOperationsAllowed"] is False
    assert company["archiveExportAvailable"] is True
    assert company["eligibilityNextStepCode"] == "RECHECK_REQUIRED"


def test_cross_company_context_is_concealed() -> None:
    app = create_app(CompanyAccessGatewayStub())

    response = TestClient(app).get(
        "/api/v1/company-access/context?company_id=20000000-0000-0000-0000-000000000002",
        headers={"Authorization": f"Bearer {access_token('aal2')}"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "COMPANY_CONTEXT_NOT_FOUND"


def test_non_owner_memberships_are_concealed_from_owner_sensitive_context() -> None:
    for role in ("reviewer", "read_only"):
        app = create_app(CompanyAccessGatewayStub(role))

        response = TestClient(app).get(
            "/api/v1/company-access/context",
            headers={"Authorization": f"Bearer {access_token('aal2')}"},
        )

        assert response.status_code == 404
        assert response.json()["code"] == "COMPANY_CONTEXT_NOT_FOUND"


def test_full_company_context_cannot_be_downgraded_to_workspace_scope() -> None:
    app = create_app(CompanyAccessGatewayStub())

    response = TestClient(app).get(
        "/api/v1/company-access/context?resource_scope=workspace",
        headers={"Authorization": f"Bearer {access_token()}"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AAL2_REQUIRED"


def test_resource_scope_is_not_a_public_company_context_parameter() -> None:
    schema = create_app(CompanyAccessGatewayStub()).openapi()
    parameters = schema["paths"]["/api/v1/company-access/context"]["get"].get("parameters", [])

    assert "resource_scope" not in {parameter["name"] for parameter in parameters}


def test_owner_context_contract_uses_fixed_role_scope_and_assurance_literals() -> None:
    schema = create_app(CompanyAccessGatewayStub()).openapi()
    context = schema["components"]["schemas"]["CompanyContext"]

    assert context["properties"]["role"] == {"const": "owner", "title": "Role", "type": "string"}
    assert context["properties"]["resourceScope"] == {
        "const": "owner_sensitive",
        "title": "Resourcescope",
        "type": "string",
    }
    assert context["properties"]["aal"] == {"const": "aal2", "title": "Aal", "type": "string"}
    assert context["properties"]["admittedAccountingYear"] == {
        "anyOf": [{"type": "integer"}, {"type": "null"}],
        "title": "Admittedaccountingyear",
    }
    assert context["properties"]["currentEligibilityDecision"]["anyOf"][0]["enum"] == [
        "supported",
        "clarify",
        "blocked",
    ]


def test_real_gateway_validates_session_then_routes_business_reads_to_backend_database() -> None:
    adapter = SupabaseCompanyAccessAdapter(
        SupabaseConfiguration(
            url="http://127.0.0.1:1",
            anon_key="anon-test-key",
            database_url="postgresql://unused",
        )
    )
    calls: list[str] = []

    async def auth_user(_token: str) -> object:
        calls.append("/auth/v1/user")
        return {"id": "owner-1", "email": "owner@example.no"}

    async def database_rows(
        _token: str, query: str, _parameters: tuple[object, ...] = (), **_kwargs: object
    ) -> list[Mapping[str, object]]:
        calls.append("database")
        stub = CompanyAccessGatewayStub()
        if "from public.company_memberships" in query:
            return [{
                "company_id": "10000000-0000-0000-0000-000000000001",
                "role": "owner",
                "accepted_at": "now",
            }]
        if "from public.companies" in query:
            return await stub.companies(
                _token, ["10000000-0000-0000-0000-000000000001"]
            )
        if "from public.company_year_admissions" in query:
            return await stub.company_year_access_states(
                _token, ["10000000-0000-0000-0000-000000000001"]
            )
        return await stub.agreement_acceptances(
            _token, ["10000000-0000-0000-0000-000000000001"]
        )

    adapter._auth_user = auth_user  # type: ignore[method-assign]
    adapter._database_rows = database_rows  # type: ignore[method-assign]
    response = TestClient(create_app(adapter)).get(
        "/api/v1/company-access/context",
        headers={"Authorization": f"Bearer {access_token('aal2')}"},
    )

    assert response.status_code == 200
    assert calls == [
        "/auth/v1/user",
        "database",
        "database",
        "database",
        "database",
    ]


def test_real_gateway_rejects_bad_sessions_before_database_access_and_normalizes_provider_failures() -> None:
    for token, expected_status, expected_code in [
        ("malformed", 401, "AUTHENTICATION_REQUIRED"),
        ("expired", 401, "AUTHENTICATION_REQUIRED"),
        ("revoked", 401, "AUTHENTICATION_REQUIRED"),
        ("provider-failure", 503, "COMPANY_ACCESS_UNAVAILABLE"),
    ]:
        with LocalSupabaseGateway() as server:
            response = TestClient(gateway_app(server)).get(
                "/api/v1/company-access/context",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == expected_status
        assert response.json()["code"] == expected_code
        assert [path for path, *_ in server.calls] == ["/auth/v1/user"]


def test_real_gateway_aal1_and_rls_outsider_or_cross_company_reads_fail_closed() -> None:
    gateway = CompanyAccessGatewayStub()
    client = TestClient(create_app(gateway))
    aal1 = client.get(
        "/api/v1/company-access/context?resource_scope=workspace",
        headers={"Authorization": f"Bearer {access_token()}"},
    )
    cross_company = client.get(
        "/api/v1/company-access/context?company_id=20000000-0000-0000-0000-000000000002",
        headers={"Authorization": f"Bearer {access_token('aal2')}"},
    )

    assert aal1.status_code == 403
    assert aal1.json()["code"] == "AAL2_REQUIRED"
    assert cross_company.status_code == 404
    assert cross_company.json()["code"] == "COMPANY_CONTEXT_NOT_FOUND"


def test_aal1_without_memberships_gets_onboarding_empty_state_before_company_reads() -> None:
    class EmptyGateway(CompanyAccessGatewayStub):
        company_read = False

        async def memberships(
            self, _access_token: str, _subject: str
        ) -> list[Mapping[str, object]]:
            return []

        async def companies(
            self, _access_token: str, _company_ids: list[str]
        ) -> list[Mapping[str, object]]:
            self.company_read = True
            return []

    gateway = EmptyGateway()
    response = TestClient(create_app(gateway)).get(
        "/api/v1/company-access/context",
        headers={"Authorization": f"Bearer {access_token()}"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "COMPANY_CONTEXT_NOT_FOUND"
    assert gateway.company_read is False


def test_real_gateway_conceals_reviewer_and_read_only_memberships() -> None:
    for role in ("reviewer", "read_only"):
        response = TestClient(create_app(CompanyAccessGatewayStub(role))).get(
            "/api/v1/company-access/context?company_id=10000000-0000-0000-0000-000000000001",
            headers={"Authorization": f"Bearer {access_token('aal2')}"},
        )

        assert response.status_code == 404
        assert response.json()["code"] == "COMPANY_CONTEXT_NOT_FOUND"


def test_real_gateway_invitation_writer_uses_backend_database_rpc() -> None:
    source = Path(inspect.getsourcefile(SupabaseCompanyAccessAdapter) or "").read_text()

    assert "await self._database_rpc_rows(access_token, function_name, body)" in source
    assert "/rest/v1/rpc/" not in source
    assert "talli.verified_actor_id" in source
    assert "talli.verified_actor_claims" in source


def test_all_company_access_business_reads_use_the_verified_backend_database() -> None:
    adapter = SupabaseCompanyAccessAdapter(
        SupabaseConfiguration(
            url="http://127.0.0.1:1",
            anon_key="anon-test-key",
            database_url="postgresql://unused",
        )
    )
    calls: list[str] = []

    async def database_rows(
        _token: str, query: str, _parameters: tuple[object, ...] = (), **_kwargs: object
    ) -> list[Mapping[str, object]]:
        calls.append(query)
        return []

    adapter._database_rows = database_rows  # type: ignore[method-assign]

    async def read_all() -> None:
        await adapter.memberships("bearer", "actor")
        await adapter.companies("bearer", ["10000000-0000-0000-0000-000000000001"])
        await adapter.agreement_acceptances(
            "bearer", ["10000000-0000-0000-0000-000000000001"]
        )
        await adapter.company_year_access_states(
            "bearer", ["10000000-0000-0000-0000-000000000001"]
        )
        await adapter.support_operator("bearer", "actor")
        await adapter.search_operator_companies("bearer", "Holding")
        await adapter.invitations("bearer", "10000000-0000-0000-0000-000000000001")
        await adapter.company_memberships(
            "bearer", "10000000-0000-0000-0000-000000000001"
        )

    asyncio.run(read_all())

    assert len(calls) == 8
    assert all("public." in query for query in calls)
    assert all("/rest/v1" not in query for query in calls)


def test_verified_actor_context_rejects_bearer_without_matching_subject() -> None:
    adapter = SupabaseCompanyAccessAdapter(
        SupabaseConfiguration(url="http://127.0.0.1:1", anon_key="anon-test-key")
    )

    async def identity(_token: str) -> Mapping[str, object]:
        return {
            "id": "00000000-0000-0000-0000-000000000001",
            "email": "owner@example.no",
        }

    adapter.session_identity = identity  # type: ignore[method-assign]
    payload = base64.urlsafe_b64encode(json.dumps({"aal": "aal2"}).encode()).decode().rstrip("=")

    with pytest.raises(CompanyAccessError) as error:
        asyncio.run(adapter._verified_actor_context(f"header.{payload}.signature"))

    assert error.value.status == 401


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/api/v1/company-access/invitations",
            {
                "operationId": "not-a-uuid",
                "companyId": "10000000-0000-0000-0000-000000000001",
                "invitedEmail": "reviewer@example.no",
                "role": "reviewer",
            },
        ),
        (
            "/api/v1/company-access/invitations/30000000-0000-0000-0000-000000000001/revoke",
            {
                "operationId": "40000000-0000-0000-0000-000000000001",
                "companyId": "40000000-0000-0000-0000-000000000002",
                "expectedUpdatedAt": "yesterday",
            },
        ),
        (
            "/api/v1/company-access/invitations/30000000-0000-0000-0000-000000000001/revoke",
            {
                "operationId": "40000000-0000-0000-0000-000000000001",
                "companyId": "40000000-0000-0000-0000-000000000002",
                "expectedUpdatedAt": 1704067200,
            },
        ),
        (
            "/api/v1/company-access/invitations/30000000-0000-0000-0000-000000000001/resend",
            {
                "operationId": "40000000-0000-0000-0000-000000000001",
                "companyId": "40000000-0000-0000-0000-000000000002",
                "expectedUpdatedAt": "2024-01-01 00:00:00+00:00",
            },
        ),
    ],
)
def test_real_gateway_rejects_malformed_command_identifiers_before_auth_or_database_access(
    path: str, payload: Mapping[str, object]
) -> None:
    with LocalSupabaseGateway() as server:
        response = TestClient(gateway_app(server)).post(
            path,
            headers={"Authorization": f"Bearer {access_token('aal2')}"},
            json=payload,
        )

    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_VALIDATION_FAILED"
    assert server.calls == []


@pytest.mark.parametrize("role", ["reviewer", "read_only"])
def test_owner_invites_supported_roles_without_exposing_token_hash(role: str) -> None:
    gateway = CompanyAccessGatewayStub()
    response = TestClient(create_app(gateway)).post(
        "/api/v1/company-access/invitations",
        headers={"Authorization": f"Bearer {access_token('aal2')}"},
        json={
            "operationId": "40000000-0000-0000-0000-000000000001",
            "companyId": "10000000-0000-0000-0000-000000000001",
            "invitedEmail": " Reviewer@Example.No ",
            "role": role,
        },
    )

    assert response.status_code == 201
    assert response.json()["invitation"]["invitedEmail"] == "reviewer@example.no"
    assert response.json()["invitation"]["role"] == role
    assert "tokenHash" not in json.dumps(response.json())
    assert isinstance(response.json()["deliveryToken"], str)
    assert response.json()["deliverySubject"] == "Invitasjon til Talli: Talli Holding AS"
    command = gateway.calls[-1][1]
    assert isinstance(command, CreateInvitationGatewayCommand)
    assert len(command.token_hash) == 64
    assert command.token_hash != command.acceptance_token


def test_owner_invitation_accepts_uuid_rows_returned_by_psycopg() -> None:
    class PsycopgGatewayStub(CompanyAccessGatewayStub):
        async def memberships(
            self, access_token: str, subject: str
        ) -> list[Mapping[str, object]]:
            rows = await super().memberships(access_token, subject)
            return [
                {**row, "company_id": UUID(str(row["company_id"]))}
                for row in rows
            ]

        async def companies(
            self, access_token: str, company_ids: list[str]
        ) -> list[Mapping[str, object]]:
            rows = await super().companies(access_token, company_ids)
            return [{**row, "id": UUID(str(row["id"]))} for row in rows]

    response = TestClient(create_app(PsycopgGatewayStub())).post(
        "/api/v1/company-access/invitations",
        headers={"Authorization": f"Bearer {access_token('aal2')}"},
        json={
            "operationId": "40000000-0000-0000-0000-000000000001",
            "companyId": "10000000-0000-0000-0000-000000000001",
            "invitedEmail": "reviewer@example.no",
            "role": "reviewer",
        },
    )

    assert response.status_code == 201
    assert response.json()["invitation"]["companyId"] == (
        "10000000-0000-0000-0000-000000000001"
    )


def test_create_replay_builds_delivery_from_the_committed_token(monkeypatch: pytest.MonkeyPatch) -> None:
    class ReplayGateway(CompanyAccessGatewayStub):
        committed: CreateInvitationGatewayCommand | None = None

        async def create_invitation(
            self, _access_token: str, invitation: CreateInvitationGatewayCommand
        ) -> Mapping[str, object]:
            self.calls.append(("create_invitation", invitation))
            if self.committed is None:
                self.committed = invitation
            return {
                **self._invitation(
                    role=self.committed.role,
                    email=self.committed.invited_email,
                ),
                "delivery_token": self.committed.acceptance_token,
                "delivery_company_name": "Talli Holding AS",
            }

    candidates = iter(["first-committed-token", "second-discarded-token"])
    monkeypatch.setattr(company_access_public.secrets, "token_urlsafe", lambda _size: next(candidates))
    gateway = ReplayGateway()
    client = TestClient(create_app(gateway))
    payload = {
        "operationId": "40000000-0000-0000-0000-000000000001",
        "companyId": "10000000-0000-0000-0000-000000000001",
        "invitedEmail": "reviewer@example.no",
        "role": "reviewer",
    }

    first = client.post(
        "/api/v1/company-access/invitations",
        headers={"Authorization": f"Bearer {access_token('aal2')}"},
        json=payload,
    )
    replay = client.post(
        "/api/v1/company-access/invitations",
        headers={"Authorization": f"Bearer {access_token('aal2')}"},
        json=payload,
    )

    assert first.status_code == replay.status_code == 201
    assert replay.json()["deliveryToken"] == "first-committed-token"
    assert replay.json()["deliveryBody"] == first.json()["deliveryBody"]
    assert "first-committed-token" in replay.json()["deliveryBody"]
    assert "second-discarded-token" not in replay.json()["deliveryBody"]


def test_expired_pending_continuation_never_returns_body_with_a_cleared_token() -> None:
    class ExpiredContinuationGateway(CompanyAccessGatewayStub):
        async def pending_invitation_side_effects(
            self, _access_token: str
        ) -> list[Mapping[str, object]]:
            return [{
                "operation_id": "40000000-0000-0000-0000-000000000009",
                "command_name": "create_invitation",
                "company_id": "10000000-0000-0000-0000-000000000001",
                "result": {
                    **self._invitation(),
                    "delivery_company_name": "Talli Holding AS",
                    "delivery_body": "legacy /invite/accept?token=expired-secret",
                },
                "delivery_token": None,
            }]

    response = TestClient(create_app(ExpiredContinuationGateway())).get(
        "/api/v1/company-access/invitation-side-effects/pending",
        headers={"Authorization": f"Bearer {access_token('aal2')}"},
    )

    assert response.status_code == 200
    continuation = response.json()["continuations"][0]
    assert continuation["deliveryToken"] is None
    assert continuation["deliverySubject"] is None
    assert continuation["deliveryBody"] is None
    assert "expired-secret" not in json.dumps(response.json())


def test_owner_invitation_administration_requires_aal2_and_conceals_foreign_company() -> None:
    gateway = CompanyAccessGatewayStub()
    aal1 = TestClient(create_app(gateway)).get(
        "/api/v1/company-access/invitations?company_id=10000000-0000-0000-0000-000000000001",
        headers={"Authorization": f"Bearer {access_token('aal1')}"},
    )
    foreign = TestClient(create_app(gateway)).get(
        "/api/v1/company-access/invitations?company_id=20000000-0000-0000-0000-000000000002",
        headers={"Authorization": f"Bearer {access_token('aal2')}"},
    )

    assert aal1.status_code == 403
    assert aal1.json()["code"] == "AAL2_REQUIRED"
    assert foreign.status_code == 404
    assert foreign.json()["code"] == "COMPANY_ACCESS_NOT_FOUND"


def test_invitee_lookup_and_acceptance_are_concealed_and_never_return_token_hashes() -> None:
    gateway = CompanyAccessGatewayStub()
    client = TestClient(create_app(gateway))
    lookup = client.post(
        "/api/v1/company-access/invitations/lookup",
        headers={"Authorization": f"Bearer {access_token('aal1')}"},
        json={"token": "raw-invitation-token"},
    )
    accepted = client.post(
        "/api/v1/company-access/invitations/accept",
        headers={"Authorization": f"Bearer {access_token('aal1')}"},
        json={"operationId": "40000000-0000-0000-0000-000000000002", "token": "raw-invitation-token"},
    )

    assert lookup.status_code == 200
    assert lookup.json() == {
        "companyName": "Talli Holding AS",
        "role": "reviewer",
        "expiresAt": gateway.invitation_expires_at,
    }
    assert accepted.status_code == 200
    assert accepted.json()["membership"]["state"] == "active"
    assert "token" not in json.dumps(lookup.json()).lower()
    lookup_command = gateway.calls[-2][1]
    accept_command = gateway.calls[-1][1]
    assert isinstance(lookup_command, InvitationIdentityGatewayCommand)
    assert isinstance(accept_command, AcceptInvitationGatewayCommand)
    assert lookup_command.token_hash == accept_command.token_hash
    assert len(accept_command.token_hash) == 64

    gateway.invitation_status = "revoked"
    concealed = client.post(
        "/api/v1/company-access/invitations/lookup",
        headers={"Authorization": f"Bearer {access_token('aal1')}"},
        json={"token": "raw-invitation-token"},
    )
    assert concealed.status_code == 404
    assert concealed.json()["code"] == "INVITATION_NOT_FOUND"


def test_pending_side_effect_recovery_uses_receipt_continuation_without_reissuing_command() -> None:
    gateway = CompanyAccessGatewayStub()
    client = TestClient(create_app(gateway))
    pending = client.get(
        "/api/v1/company-access/invitation-side-effects/pending",
        headers={"Authorization": f"Bearer {access_token('aal2')}"},
    )
    completed = client.post(
        "/api/v1/company-access/invitation-side-effects/40000000-0000-0000-0000-000000000009/complete",
        headers={"Authorization": f"Bearer {access_token('aal2')}"},
    )

    assert pending.status_code == 200
    assert pending.json()["continuations"][0]["operationId"] == "40000000-0000-0000-0000-000000000009"
    assert pending.json()["continuations"][0]["deliveryToken"] == "delivery-token"
    assert completed.status_code == 200
    assert completed.json() == {
        "operationId": "40000000-0000-0000-0000-000000000009",
        "completed": True,
    }
    assert [name for name, _ in gateway.calls] == [
        "pending_invitation_side_effects",
        "complete_invitation_side_effect",
    ]


def test_owner_can_atomically_change_or_remove_only_non_owner_memberships() -> None:
    gateway = CompanyAccessGatewayStub()
    client = TestClient(create_app(gateway))
    changed = client.patch(
        "/api/v1/company-access/memberships/00000000-0000-0000-0000-000000000044",
        headers={"Authorization": f"Bearer {access_token('aal2')}"},
        json={
            "operationId": "40000000-0000-0000-0000-000000000003",
            "companyId": "10000000-0000-0000-0000-000000000001",
            "expectedRole": "reviewer",
            "role": "read_only",
            "state": "active",
        },
    )
    removed = client.patch(
        "/api/v1/company-access/memberships/00000000-0000-0000-0000-000000000044",
        headers={"Authorization": f"Bearer {access_token('aal2')}"},
        json={
            "operationId": "40000000-0000-0000-0000-000000000004",
            "companyId": "10000000-0000-0000-0000-000000000001",
            "expectedRole": "reviewer",
            "state": "removed",
        },
    )
    forbidden_owner_role = client.patch(
        "/api/v1/company-access/memberships/00000000-0000-0000-0000-000000000044",
        headers={"Authorization": f"Bearer {access_token('aal2')}"},
        json={
            "operationId": "40000000-0000-0000-0000-000000000005",
            "companyId": "10000000-0000-0000-0000-000000000001",
            "expectedRole": "reviewer",
            "role": "owner",
            "state": "active",
        },
    )

    assert changed.status_code == 200
    assert changed.json()["membership"]["role"] == "read_only"
    assert removed.status_code == 200
    assert removed.json()["membership"]["state"] == "removed"
    assert forbidden_owner_role.status_code == 422


def test_supabase_gateway_rejects_unsafe_origins_and_accepts_https_or_loopback() -> None:
    for unsafe in [
        "http://supabase.example",
        "ftp://supabase.example",
        "https://user:password@supabase.example",
        "https://supabase.example/rest/v1",
        "https://supabase.example?tenant=other",
        "https://supabase.example#fragment",
    ]:
        with pytest.raises(ValueError, match="Supabase origin"):
            SupabaseCompanyAccessAdapter(SupabaseConfiguration(url=unsafe, anon_key="anon-test-key"))

    SupabaseCompanyAccessAdapter(SupabaseConfiguration(url="https://project.supabase.co", anon_key="anon-test-key"))
    SupabaseCompanyAccessAdapter(SupabaseConfiguration(url="http://127.0.0.1:54321", anon_key="anon-test-key"))
    SupabaseCompanyAccessAdapter(SupabaseConfiguration(url="http://localhost:54321", anon_key="anon-test-key"))


def test_supabase_gateway_never_follows_same_or_cross_origin_redirects() -> None:
    with LocalSupabaseGateway() as target:
        with LocalSupabaseGateway(redirect_to=f"{target.url}/redirect-target") as source:
            cross_origin = TestClient(gateway_app(source)).get(
                "/api/v1/company-access/context",
                headers={"Authorization": f"Bearer {access_token('aal2')}"},
            )

        assert cross_origin.status_code == 503
        assert [path for path, *_ in source.calls] == ["/auth/v1/user"]
        assert target.calls == []

    with LocalSupabaseGateway() as source:
        source.redirect_to = f"{source.url}/redirect-target"
        same_origin = TestClient(gateway_app(source)).get(
            "/api/v1/company-access/context",
            headers={"Authorization": f"Bearer {access_token('aal2')}"},
        )

    assert same_origin.status_code == 503
    assert [path for path, *_ in source.calls] == ["/auth/v1/user"]
