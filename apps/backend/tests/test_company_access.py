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


def access_token(aal: str = "aal1") -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"aal": aal}).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


class CompanyAccessGatewayStub:
    def __init__(self, role: str = "owner") -> None:
        self.role = role

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
                        self._json(200, {"id": "member-1"})
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
