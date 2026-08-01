import asyncio
import base64
import json
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from talli_backend.main import create_app
from talli_backend.adapters.supabase_company_access import (
    SupabaseCompanyAccessAdapter,
    SupabaseConfiguration,
)
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
    calls: list[tuple[str, str, str, Mapping[str, object] | None]] = []

    async def request(
        path: str,
        access_token: str,
        *,
        method: str = "GET",
        body: Mapping[str, object] | None = None,
    ) -> object:
        calls.append((path, access_token, method, body))
        if len(calls) == 1:
            raise CompanyAccessError(
                status=503,
                code="COMPANY_ACCESS_UNAVAILABLE",
                title="Company access unavailable",
                detail="Company access is temporarily unavailable.",
            )
        return [{"id": "invitation-1"}]

    adapter._request = request  # type: ignore[method-assign]
    body = {
        "p_operation_id": "40000000-0000-0000-0000-000000000001",
        "p_company_id": "company-1",
    }

    result = asyncio.run(adapter._rpc_row("bearer", "company_access_create_invitation", body))

    assert result == {"id": "invitation-1"}
    assert calls == [
        ("/rest/v1/rpc/company_access_create_invitation", "bearer", "POST", body),
        ("/rest/v1/rpc/company_access_create_invitation", "bearer", "POST", body),
    ]


def access_token(aal: str = "aal1") -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"aal": aal}).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


class CompanyAccessGatewayStub:
    def __init__(self, role: str = "owner") -> None:
        self.role = role
        self.invitation_status = "pending"
        self.invitation_email = "reviewer@example.no"
        self.invitation_expires_at = "2026-08-15T00:00:00Z"
        self.calls: list[tuple[str, object]] = []

    async def session_subject(self, _access_token: str) -> str:
        return "owner-1"

    async def memberships(
        self, _access_token: str, _subject: str
    ) -> list[Mapping[str, object]]:
        return [{"company_id": "company-1", "role": self.role, "accepted_at": "2026-07-30T00:00:00Z"}]

    async def companies(
        self, _access_token: str, company_ids: list[str]
    ) -> list[Mapping[str, object]]:
        companies = {
            "company-1": {
                "id": "company-1",
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
            "company-2": {
                "id": "company-2",
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
        return {**self._invitation(), "delivery_token": command.acceptance_token}

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

    def _invitation(
        self,
        *,
        role: str = "reviewer",
        email: str | None = None,
        status: str | None = None,
    ) -> Mapping[str, object]:
        return {
            "id": "invitation-1",
            "company_id": "company-1",
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
            "company_id": "company-1",
            "user_id": "reviewer-1",
            "role": role,
            "state": state,
            "accepted_at": "2026-08-01T00:00:00Z",
        }


class LocalSupabaseGateway:
    """Hermetic HTTP server that exercises the Auth -> PostgREST gateway path."""

    def __init__(self, membership_role: str = "owner", redirect_to: str | None = None) -> None:
        self.calls: list[tuple[str, str, str, str]] = []
        self.membership_role = membership_role
        self.redirect_to = redirect_to
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = Thread(target=self._server.serve_forever, daemon=True)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
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
                if path == "/rest/v1/company_memberships":
                    self._json(
                        200,
                        [] if token.startswith("outsider-") else [
                            {"company_id": "company-1", "role": gateway.membership_role, "accepted_at": "2026-07-30T00:00:00Z"}
                        ],
                    )
                    return
                if path == "/rest/v1/companies":
                    # This mirrors PostgREST RLS: a member never receives a
                    # cross-company row even if they put its ID in a filter.
                    self._json(200, [] if "company-2" in self.path else [{
                        "id": "company-1",
                        "org_number": "314159265",
                        "name": "Talli Holding AS",
                        "entity_type": "AS",
                        "address": "Testveien 1",
                        "postal_code": "0150",
                        "city": "Oslo",
                        "status_text": "Registrert",
                        "source": "Brønnøysundregistrene",
                        "created_by": "owner-1",
                        "identity_confirmed_at": None,
                        "identity_locked_at": None,
                        "created_at": "2026-07-30T00:00:00Z",
                    }])
                    return
                if path == "/rest/v1/company_invitations":
                    self._json(200, [])
                    return
                self._json(404, {})

            def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
                path = urlsplit(self.path).path
                authorization = self.headers.get("Authorization", "")
                api_key = self.headers.get("apikey", "")
                gateway.calls.append((path, authorization, api_key, self.path))
                content_length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(content_length) or b"{}")
                if path == "/rest/v1/rpc/company_access_create_invitation":
                    self._json(200, [{
                        "id": "invitation-1",
                        "company_id": payload["p_company_id"],
                        "invited_email": payload["p_invited_email"],
                        "role": payload["p_role"],
                        "status": "pending",
                        "expires_at": "2026-08-15T00:00:00Z",
                        "created_at": "2026-08-01T00:00:00Z",
                        "updated_at": "2026-08-01T00:00:00Z",
                        "delivery_token": payload["p_acceptance_token"],
                    }])
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

    def __enter__(self) -> "LocalSupabaseGateway":
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
            "id": "company-1",
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
        },
        "companies": [{
            "id": "company-1",
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
        }],
    }


def test_cross_company_context_is_concealed() -> None:
    app = create_app(CompanyAccessGatewayStub())

    response = TestClient(app).get(
        "/api/v1/company-access/context?company_id=company-2",
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


def test_real_gateway_validates_session_before_rls_reads_and_keeps_the_user_bearer() -> None:
    with LocalSupabaseGateway() as server:
        response = TestClient(gateway_app(server)).get(
            "/api/v1/company-access/context",
            headers={"Authorization": f"Bearer {access_token('aal2')}"},
        )

    assert response.status_code == 200
    assert [path for path, *_ in server.calls] == [
        "/auth/v1/user",
        "/rest/v1/company_memberships",
        "/rest/v1/companies",
    ]
    for _path, authorization, api_key, _request_path in server.calls:
        assert authorization == f"Bearer {access_token('aal2')}"
        assert api_key == "anon-test-key"
        assert "service_role" not in authorization.lower()


def test_real_gateway_rejects_bad_sessions_before_postgrest_and_normalizes_provider_failures() -> None:
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
    with LocalSupabaseGateway() as server:
        client = TestClient(gateway_app(server))
        aal1 = client.get(
            "/api/v1/company-access/context?resource_scope=workspace",
            headers={"Authorization": f"Bearer {access_token()}"},
        )
        outsider = client.get(
            "/api/v1/company-access/context",
            headers={"Authorization": f"Bearer outsider-{access_token('aal2')}"},
        )
        cross_company = client.get(
            "/api/v1/company-access/context?company_id=company-2",
            headers={"Authorization": f"Bearer {access_token('aal2')}"},
        )

    assert aal1.status_code == 403
    assert aal1.json()["code"] == "AAL2_REQUIRED"
    assert outsider.status_code == 404
    assert outsider.json()["code"] == "COMPANY_CONTEXT_NOT_FOUND"
    assert cross_company.status_code == 404
    assert cross_company.json()["code"] == "COMPANY_CONTEXT_NOT_FOUND"


def test_real_gateway_conceals_reviewer_and_read_only_memberships() -> None:
    for role in ("reviewer", "read_only"):
        with LocalSupabaseGateway(role) as server:
            response = TestClient(gateway_app(server)).get(
                "/api/v1/company-access/context?company_id=company-1",
                headers={"Authorization": f"Bearer {access_token('aal2')}"},
            )

        assert response.status_code == 404
        assert response.json()["code"] == "COMPANY_CONTEXT_NOT_FOUND"
        assert [path for path, *_ in server.calls] == [
            "/auth/v1/user",
            "/rest/v1/company_memberships",
        ]


def test_real_gateway_invitation_write_keeps_bearer_and_uses_transactional_rpc() -> None:
    with LocalSupabaseGateway() as server:
        response = TestClient(gateway_app(server)).post(
            "/api/v1/company-access/invitations",
            headers={"Authorization": f"Bearer {access_token('aal2')}"},
            json={
                "operationId": "40000000-0000-0000-0000-000000000001",
                "companyId": "company-1",
                "invitedEmail": "reviewer@example.no",
                "role": "reviewer",
            },
        )

    assert response.status_code == 201
    assert [path for path, *_ in server.calls] == [
        "/auth/v1/user",
        "/rest/v1/company_memberships",
        "/rest/v1/companies",
        "/rest/v1/rpc/company_access_create_invitation",
    ]
    for _path, authorization, api_key, _request_path in server.calls:
        assert authorization == f"Bearer {access_token('aal2')}"
        assert api_key == "anon-test-key"
        assert "service_role" not in authorization.lower()


@pytest.mark.parametrize("role", ["reviewer", "read_only"])
def test_owner_invites_supported_roles_without_exposing_token_hash(role: str) -> None:
    gateway = CompanyAccessGatewayStub()
    response = TestClient(create_app(gateway)).post(
        "/api/v1/company-access/invitations",
        headers={"Authorization": f"Bearer {access_token('aal2')}"},
        json={
            "operationId": "40000000-0000-0000-0000-000000000001",
            "companyId": "company-1",
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


def test_owner_invitation_administration_requires_aal2_and_conceals_foreign_company() -> None:
    gateway = CompanyAccessGatewayStub()
    aal1 = TestClient(create_app(gateway)).get(
        "/api/v1/company-access/invitations?company_id=company-1",
        headers={"Authorization": f"Bearer {access_token('aal1')}"},
    )
    foreign = TestClient(create_app(gateway)).get(
        "/api/v1/company-access/invitations?company_id=company-2",
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
        "expiresAt": "2026-08-15T00:00:00Z",
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


def test_owner_can_atomically_change_or_remove_only_non_owner_memberships() -> None:
    gateway = CompanyAccessGatewayStub()
    client = TestClient(create_app(gateway))
    changed = client.patch(
        "/api/v1/company-access/memberships/reviewer-1",
        headers={"Authorization": f"Bearer {access_token('aal2')}"},
        json={
            "operationId": "40000000-0000-0000-0000-000000000003",
            "companyId": "company-1",
            "expectedRole": "reviewer",
            "role": "read_only",
            "state": "active",
        },
    )
    removed = client.patch(
        "/api/v1/company-access/memberships/reviewer-1",
        headers={"Authorization": f"Bearer {access_token('aal2')}"},
        json={
            "operationId": "40000000-0000-0000-0000-000000000004",
            "companyId": "company-1",
            "expectedRole": "reviewer",
            "state": "removed",
        },
    )
    forbidden_owner_role = client.patch(
        "/api/v1/company-access/memberships/reviewer-1",
        headers={"Authorization": f"Bearer {access_token('aal2')}"},
        json={
            "operationId": "40000000-0000-0000-0000-000000000005",
            "companyId": "company-1",
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
