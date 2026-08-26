import asyncio
import base64
import json
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Self

import pytest
from fastapi.testclient import TestClient
from talli_backend.adapters.brreg_company_registry import (
    BrregCompanyRegistryAdapter,
    BrregCompanyRegistryConfiguration,
)
from talli_backend.main import create_app
from talli_backend.modules.company_access.public import (
    CompanyAccessError,
    CompanyAgreementAcceptanceGatewayCommand,
    CompanyOnboardingGatewayCommand,
)

BUSINESS_TERMS_SHA256 = "f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543"
DPA_SHA256 = "083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c"


def access_token() -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"aal": "aal1"}).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


def agreement_evidence() -> dict[str, object]:
    return {
        "agreementAccepted": True,
        "businessTermsVersion": "2026-07-17",
        "businessTermsSha256": BUSINESS_TERMS_SHA256,
        "dpaVersion": "2026-07-17",
        "dpaSha256": DPA_SHA256,
    }


class CompanyRegistryStub:
    def __init__(self, *, entity_type: str = "AS") -> None:
        self.entity_type = entity_type
        self.calls: list[str] = []

    async def lookup_company(self, org_number: str) -> Mapping[str, object]:
        self.calls.append(org_number)
        return {
            "org_number": org_number,
            "name": "Rolig Holding AS",
            "entity_type": self.entity_type,
            "address": "Testveien 1",
            "postal_code": "0150",
            "city": "Oslo",
            "status_text": "aktiv",
            "source": "brreg",
        }


class OnboardingGatewayStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.role = "owner"

    async def session_identity(self, _access_token: str) -> Mapping[str, object]:
        return {"id": "00000000-0000-0000-0000-000000000044", "email": "owner@example.no"}

    async def session_subject(self, _access_token: str) -> str:
        return "00000000-0000-0000-0000-000000000044"

    async def memberships(self, _access_token: str, _subject: str) -> list[Mapping[str, object]]:
        return [{
            "company_id": "10000000-0000-0000-0000-000000000001",
            "role": self.role,
            "accepted_at": "2026-08-26T00:00:00Z",
        }]

    async def companies(
        self, _access_token: str, company_ids: list[str]
    ) -> list[Mapping[str, object]]:
        if "10000000-0000-0000-0000-000000000001" not in company_ids:
            return []
        return [{
            "id": "10000000-0000-0000-0000-000000000001",
            "org_number": "314159265",
            "name": "Rolig Holding AS",
            "entity_type": "AS",
            "address": "Testveien 1",
            "postal_code": "0150",
            "city": "Oslo",
            "status_text": "aktiv",
            "source": "brreg",
            "created_by": "00000000-0000-0000-0000-000000000044",
            "identity_confirmed_at": "2026-08-26T00:00:00Z",
            "identity_locked_at": "2026-08-26T00:00:00Z",
            "created_at": "2026-08-26T00:00:00Z",
        }]

    async def support_operator(
        self, _access_token: str, _subject: str
    ) -> Mapping[str, object] | None:
        if self.role not in {"support", "admin"}:
            return None
        return {"role": self.role, "active": True}

    async def search_operator_companies(
        self, access_token: str, query: str
    ) -> list[Mapping[str, object]]:
        self.calls.append(("search_operator_companies", query))
        return await self.companies(access_token, ["10000000-0000-0000-0000-000000000001"])

    async def onboard_company(
        self, _access_token: str, command: CompanyOnboardingGatewayCommand
    ) -> Mapping[str, object]:
        self.calls.append(("onboard_company", command))
        return {
            "company_id": "10000000-0000-0000-0000-000000000001",
            "current_agreement_accepted": True,
            "replayed": False,
        }

    async def reaccept_agreement(
        self, _access_token: str, command: CompanyAgreementAcceptanceGatewayCommand
    ) -> Mapping[str, object]:
        self.calls.append(("reaccept_agreement", command))
        return {
            "company_id": command.company_id,
            "current_agreement_accepted": True,
            "replayed": True,
        }


def test_owner_onboards_supported_as_through_the_backend_boundary() -> None:
    gateway = OnboardingGatewayStub()
    registry = CompanyRegistryStub()
    response = TestClient(create_app(gateway, registry)).post(
        "/api/v1/company-access/onboarding",
        headers={"Authorization": f"Bearer {access_token()}"},
        json={"orgNumber": "314159265", **agreement_evidence()},
    )

    assert response.status_code == 201
    assert response.json() == {
        "companyId": "10000000-0000-0000-0000-000000000001",
        "currentAgreementAccepted": True,
        "replayed": False,
    }
    assert registry.calls == ["314159265"]
    command = gateway.calls[0][1]
    assert isinstance(command, CompanyOnboardingGatewayCommand)
    assert str(command.verified_actor) == "00000000-0000-0000-0000-000000000044"
    assert command.verified_email == "owner@example.no"
    assert command.company.entity_type == "AS"


@pytest.mark.parametrize(
    "body",
    [
        {"orgNumber": "123", **agreement_evidence()},
        {"orgNumber": "314159265", **agreement_evidence(), "agreementAccepted": False},
        {"orgNumber": "314159265", **agreement_evidence(), "businessTermsVersion": "stale"},
        {"orgNumber": "314159265", **agreement_evidence(), "unexpected": "field"},
    ],
)
def test_onboarding_rejects_malformed_or_stale_evidence_before_lookup_or_write(
    body: Mapping[str, object],
) -> None:
    gateway = OnboardingGatewayStub()
    registry = CompanyRegistryStub()
    response = TestClient(create_app(gateway, registry)).post(
        "/api/v1/company-access/onboarding",
        headers={"Authorization": f"Bearer {access_token()}"},
        json=body,
    )

    assert response.status_code in {409, 422}
    assert registry.calls == []
    assert gateway.calls == []


def test_non_as_is_unsupported_without_calling_the_atomic_writer() -> None:
    gateway = OnboardingGatewayStub()
    registry = CompanyRegistryStub(entity_type="ENK")
    response = TestClient(create_app(gateway, registry)).post(
        "/api/v1/company-access/onboarding",
        headers={"Authorization": f"Bearer {access_token()}"},
        json={"orgNumber": "314159265", **agreement_evidence()},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "UNSUPPORTED_COMPANY"
    assert gateway.calls == []


def test_owner_reaccepts_current_agreement_through_the_backend_boundary() -> None:
    gateway = OnboardingGatewayStub()
    response = TestClient(create_app(gateway, CompanyRegistryStub())).post(
        "/api/v1/company-access/agreements/reaccept",
        headers={"Authorization": f"Bearer {access_token()}"},
        json={
            "companyId": "10000000-0000-0000-0000-000000000001",
            **agreement_evidence(),
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "companyId": "10000000-0000-0000-0000-000000000001",
        "currentAgreementAccepted": True,
        "replayed": True,
    }
    command = gateway.calls[0][1]
    assert isinstance(command, CompanyAgreementAcceptanceGatewayCommand)
    assert str(command.verified_actor) == "00000000-0000-0000-0000-000000000044"


def test_reacceptance_conceals_non_owner_membership() -> None:
    gateway = OnboardingGatewayStub()
    gateway.role = "reviewer"
    response = TestClient(create_app(gateway, CompanyRegistryStub())).post(
        "/api/v1/company-access/agreements/reaccept",
        headers={"Authorization": f"Bearer {access_token()}"},
        json={
            "companyId": "10000000-0000-0000-0000-000000000001",
            **agreement_evidence(),
        },
    )

    assert response.status_code == 404
    assert response.json()["code"] == "COMPANY_ACCESS_NOT_FOUND"
    assert gateway.calls == []


def test_accepted_member_reads_tenant_concealed_company_record() -> None:
    gateway = OnboardingGatewayStub()
    gateway.role = "reviewer"
    client = TestClient(create_app(gateway, CompanyRegistryStub()))

    response = client.get(
        "/api/v1/company-access/companies/10000000-0000-0000-0000-000000000001",
        headers={"Authorization": f"Bearer {access_token()}"},
    )
    concealed = client.get(
        "/api/v1/company-access/companies/20000000-0000-0000-0000-000000000002",
        headers={"Authorization": f"Bearer {access_token()}"},
    )

    assert response.status_code == 200
    assert response.json()["company"]["role"] == "reviewer"
    assert response.json()["company"]["orgNumber"] == "314159265"
    assert concealed.status_code == 404


def test_operator_context_and_bounded_company_search_require_active_operator() -> None:
    gateway = OnboardingGatewayStub()
    client = TestClient(create_app(gateway, CompanyRegistryStub()))
    denied = client.get(
        "/api/v1/company-access/operator-context",
        headers={"Authorization": f"Bearer {access_token()}"},
    )
    gateway.role = "admin"
    context = client.get(
        "/api/v1/company-access/operator-context",
        headers={"Authorization": f"Bearer {access_token()}"},
    )
    search = client.get(
        "/api/v1/company-access/operator-companies?query=++Rolig+Holding++",
        headers={"Authorization": f"Bearer {access_token()}"},
    )
    too_short = client.get(
        "/api/v1/company-access/operator-companies?query=R",
        headers={"Authorization": f"Bearer {access_token()}"},
    )

    assert denied.status_code == 403
    assert context.json() == {"role": "admin", "active": True}
    assert search.status_code == 200
    assert search.json()["companies"][0]["orgNumber"] == "314159265"
    assert "role" not in search.json()["companies"][0]
    assert gateway.calls[-1] == ("search_operator_companies", "Rolig Holding")
    assert too_short.status_code == 422


def test_atomic_rpc_retry_reuses_the_identical_onboarding_command() -> None:
    from talli_backend.adapters.supabase_company_access import (
        SupabaseCompanyAccessAdapter,
        SupabaseConfiguration,
    )

    adapter = SupabaseCompanyAccessAdapter(
        SupabaseConfiguration(url="http://127.0.0.1:1", anon_key="anon-test-key")
    )
    calls: list[tuple[str, Mapping[str, object]]] = []

    async def request(
        _access_token: str,
        function_name: str,
        body: Mapping[str, object],
        **_kwargs: object,
    ) -> list[Mapping[str, object]]:
        calls.append((function_name, body))
        if len(calls) == 1:
            raise CompanyAccessError(
                status=503,
                code="COMPANY_ACCESS_UNAVAILABLE",
                title="Company access unavailable",
                detail="Company access is temporarily unavailable.",
            )
        return [{
            "company_id": "10000000-0000-0000-0000-000000000001",
            "current_agreement_accepted": True,
            "replayed": True,
        }]

    adapter._database_rpc_rows = request  # type: ignore[method-assign]
    payload = {"p_operation_id": "40000000-0000-0000-0000-000000000001"}
    result = asyncio.run(adapter._rpc_row("bearer", "company_access_onboard_company", payload))

    assert result["replayed"] is True
    assert calls == [
        ("company_access_onboard_company", payload),
        ("company_access_onboard_company", payload),
    ]


class LocalCompanyRegistry:
    def __init__(self, payload: object, *, status: int = 200, redirect: bool = False) -> None:
        self.payload = payload
        self.status = status
        self.redirect = redirect
        self.paths: list[str] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = Thread(target=self._server.serve_forever, daemon=True)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        registry = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                registry.paths.append(self.path)
                if registry.redirect:
                    self.send_response(302)
                    self.send_header("Location", f"{registry.url}/redirected")
                    self.end_headers()
                    return
                body = json.dumps(registry.payload).encode()
                self.send_response(registry.status)
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


def test_brreg_adapter_maps_the_existing_company_identity_behavior() -> None:
    with LocalCompanyRegistry({
        "organisasjonsnummer": "314159265",
        "navn": "Rolig Holding AS",
        "organisasjonsform": {"kode": "AS"},
        "forretningsadresse": {
            "adresse": ["Testveien 1", "Etasje 2"],
            "postnummer": "0150",
            "poststed": "OSLO",
        },
        "underAvvikling": False,
        "underKonkursbehandling": False,
    }) as server:
        adapter = BrregCompanyRegistryAdapter(
            BrregCompanyRegistryConfiguration(origin=server.url, timeout_seconds=1.0)
        )
        identity = asyncio.run(adapter.lookup_company("314159265"))

    assert identity == {
        "org_number": "314159265",
        "name": "Rolig Holding AS",
        "entity_type": "AS",
        "address": "Testveien 1, Etasje 2",
        "postal_code": "0150",
        "city": "OSLO",
        "status_text": "aktiv",
        "source": "brreg",
    }
    assert server.paths == ["/enhetsregisteret/api/enheter/314159265"]


@pytest.mark.parametrize(
    ("payload", "redirect"),
    [
        ({"organisasjonsnummer": "different", "navn": "Wrong"}, False),
        ({"organisasjonsnummer": "314159265", "navn": 123}, False),
        ({}, True),
    ],
)
def test_brreg_adapter_fails_closed_on_malformed_or_redirected_responses(
    payload: object, redirect: bool
) -> None:
    with LocalCompanyRegistry(payload, redirect=redirect) as server:
        adapter = BrregCompanyRegistryAdapter(
            BrregCompanyRegistryConfiguration(origin=server.url, timeout_seconds=1.0)
        )
        with pytest.raises(CompanyAccessError) as raised:
            asyncio.run(adapter.lookup_company("314159265"))

    assert raised.value.code == "COMPANY_REGISTRY_UNAVAILABLE"
