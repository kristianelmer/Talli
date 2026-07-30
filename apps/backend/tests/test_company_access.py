import base64
import json
from collections.abc import Mapping

from fastapi.testclient import TestClient

from talli_backend.main import create_app
from talli_backend.modules.company_access.public import CompanyAccessService


def access_token(aal: str = "aal1") -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"aal": aal}).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


class CompanyAccessGatewayStub:
    async def session_subject(self, _access_token: str) -> str:
        return "owner-1"

    async def memberships(
        self, _access_token: str, _subject: str
    ) -> list[Mapping[str, object]]:
        return [{"company_id": "company-1", "role": "owner", "accepted_at": "2026-07-30T00:00:00Z"}]

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


def test_company_context_fails_closed_without_a_bearer_session() -> None:
    response = TestClient(create_app()).get("/api/v1/company-access/context")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTHENTICATION_REQUIRED"


def test_company_context_returns_only_the_authenticated_membership() -> None:
    app = create_app(CompanyAccessService(CompanyAccessGatewayStub()))

    response = TestClient(app).get(
        "/api/v1/company-access/context",
        headers={"Authorization": f"Bearer {access_token()}"},
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
            "resourceScope": "workspace",
            "aal": "aal1",
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
            "resourceScope": "workspace",
            "aal": "aal1",
        }],
    }


def test_cross_company_context_is_concealed() -> None:
    app = create_app(CompanyAccessService(CompanyAccessGatewayStub()))

    response = TestClient(app).get(
        "/api/v1/company-access/context?company_id=company-2",
        headers={"Authorization": f"Bearer {access_token()}"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "COMPANY_CONTEXT_NOT_FOUND"


def test_sensitive_owner_context_requires_aal2() -> None:
    app = create_app(CompanyAccessService(CompanyAccessGatewayStub()))

    response = TestClient(app).get(
        "/api/v1/company-access/context?resource_scope=owner_sensitive",
        headers={"Authorization": f"Bearer {access_token()}"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AAL2_REQUIRED"
