import asyncio
import base64
import time
import json

import pytest

from talli_backend.adapters.preview_synthetic_company_registry import PreviewSyntheticCompanyRegistryAdapter


CONFIG = "TALLI_PREVIEW_SYNTHETIC_REGISTRY_IDENTITY"
IDENTITY = {
    "org_number": "992803750", "name": "Synthetic private Preview unit-fixture",
    "entity_type": "AS", "address": "Synthetic fixture only", "postal_code": "0155",
    "city": "OSLO", "status_text": "aktiv", "source": "browser_test",
}
CONTEXT = {
    "VERCEL": "1", "VERCEL_ENV": "preview", "VERCEL_TARGET_ENV": "preview",
    "VERCEL_PROJECT_ID": "prj_u28yRnkslspXi3LSEDQHvTz8EWCD",
    "SUPABASE_URL": "https://pkpyyxryfhfehrbhbynp.supabase.co",
    "TALLI_RF1086_PRODUCTION_ENABLED": "false", "TALLI_AUTHORITY_OPS_ENABLED": "false",
    "TALLI_ANNUAL_BILLING_MODE": "off", "TALLI_ANNUAL_CHECKOUT_RECONCILIATION_MODE": "off",
    "TALLI_VALIDATION_OBSERVATION_MODE": "off", "TALLI_COMPANY_TEST_RETENTION_MODE": "off",
}


class Fallback:
    def __init__(self):
        self.calls = []

    async def lookup_company(self, org_number):
        self.calls.append(org_number)
        return {"org_number": org_number, "source": "brreg"}


def configured(monkeypatch, identity=IDENTITY):
    for key, value in CONTEXT.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv(CONFIG, json.dumps(identity))


def test_default_uses_the_actual_registry_adapter_without_config(monkeypatch):
    monkeypatch.delenv(CONFIG, raising=False)
    fallback = Fallback()
    assert PreviewSyntheticCompanyRegistryAdapter.from_environment(fallback) is fallback


def test_only_the_approved_fixture_uses_explicit_synthetic_provenance(monkeypatch):
    configured(monkeypatch)
    fallback = Fallback()
    adapter = PreviewSyntheticCompanyRegistryAdapter.from_environment(fallback)
    first = asyncio.run(adapter.lookup_company("992803750"))
    assert first == IDENTITY
    first["source"] = "brreg"
    assert asyncio.run(adapter.lookup_company("992803750"))["source"] == "browser_test"
    assert asyncio.run(adapter.lookup_company("314159265")) == {"org_number": "314159265", "source": "brreg"}
    assert fallback.calls == ["314159265"]


@pytest.mark.parametrize("key,value", [
    ("VERCEL", None), ("VERCEL_ENV", "production"), ("VERCEL_ENV", "development"),
    ("VERCEL_TARGET_ENV", "production"), ("VERCEL_TARGET_ENV", "staging"),
    ("VERCEL_PROJECT_ID", "other-project"), ("VERCEL_PROJECT_ID", None),
    ("SUPABASE_URL", "https://other.supabase.co"), ("SUPABASE_URL", None),
    ("TALLI_RF1086_PRODUCTION_ENABLED", "true"), ("TALLI_AUTHORITY_OPS_ENABLED", "true"),
    ("TALLI_ANNUAL_BILLING_MODE", "live"), ("TALLI_ANNUAL_CHECKOUT_RECONCILIATION_MODE", "live"),
    ("TALLI_VALIDATION_OBSERVATION_MODE", "on"), ("TALLI_COMPANY_TEST_RETENTION_MODE", "on"),
])
def test_production_or_incomplete_and_wrong_targets_fail_closed(monkeypatch, key, value):
    configured(monkeypatch)
    if value is None:
        monkeypatch.delenv(key, raising=False)
    else:
        monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match="designated private Preview"):
        PreviewSyntheticCompanyRegistryAdapter.from_environment(Fallback())


@pytest.mark.parametrize("patch", [
    {"org_number": "314159265"}, {"source": "brreg"}, {"name": "Real company"},
    {"entity_type": "ENK"}, {"status_text": "slettet"}, {"extra_authority": True},
])
def test_other_identity_or_forged_real_registry_provenance_is_refused(monkeypatch, patch):
    configured(monkeypatch, IDENTITY | patch)
    with pytest.raises(ValueError):
        PreviewSyntheticCompanyRegistryAdapter.from_environment(Fallback())


@pytest.mark.parametrize("aal,age,expected", [("aal2", 0, 201), ("aal1", 0, 403), ("aal2", 901, 403)])
def test_real_http_eligibility_and_admission_keep_source_and_require_fresh_mfa(monkeypatch, aal, age, expected):
    from fastapi.testclient import TestClient
    from talli_backend.main import create_app
    from test_company_eligibility import (
        AdmissionGatewayStub, admission_request, definitive_request,
    )

    configured(monkeypatch)
    gateway = AdmissionGatewayStub()
    adapter = PreviewSyntheticCompanyRegistryAdapter.from_environment(Fallback())
    client = TestClient(create_app(gateway, adapter))
    checked = client.post("/api/v1/company-access/eligibility/precheck", json={
        "orgNumber": IDENTITY["org_number"], "accountingYear": 2025,
    })
    assert checked.status_code == 200
    assert checked.json()["publicFacts"]["source"] == "browser_test"
    assessed = client.post("/api/v1/company-access/eligibility/definitive", json={
        **definitive_request(checked.json()), "orgNumber": IDENTITY["org_number"], "accountingYear": 2025,
    })
    assert assessed.status_code == 200
    assert assessed.json()["decision"] == "supported"
    assert assessed.json()["publicFacts"]["source"] == "browser_test"
    claims = {"aal": aal, "amr": [{"method": "totp", "timestamp": int(time.time()) - age}]}
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    response = client.post("/api/v1/company-access/company-year-admissions",
        headers={"Authorization": f"Bearer header.{payload}.signature"},
        json={**admission_request(assessed.json()), "orgNumber": IDENTITY["org_number"], "accountingYear": 2025})
    assert response.status_code == expected, response.text
    if expected == 403:
        assert response.json()["code"] == "FRESH_MFA_REQUIRED"
        assert gateway.calls == []
        return
    command = gateway.calls[-1][1]
    assert command.company.source == "browser_test"
    assert json.loads(command.public_facts_json)["source"] == "browser_test"

    # The HTTP retry shortcut must retain the synthetic record's MFA boundary.
    request = {**admission_request(assessed.json()), "orgNumber": IDENTITY["org_number"], "accountingYear": 2025}
    gateway.admission_replay = {
        "registry_source": "browser_test", "org_number": IDENTITY["org_number"], "accounting_year": 2025,
        "company_id": response.json()["companyId"], "company_year_admission_id": response.json()["companyYearAdmissionId"],
        "reconstruct_from": "2025-01-01", "public_facts_sha256": request["expectedPublicFactsSha256"],
        "capability_manifest_version": request["capabilityManifestVersion"], "capability_manifest_sha256": request["capabilityManifestSha256"],
        "answers": request["answers"], "business_terms_version": request["businessTermsVersion"], "business_terms_sha256": request["businessTermsSha256"],
        "dpa_version": request["dpaVersion"], "dpa_sha256": request["dpaSha256"],
        "privacy_notice_version": request["privacyNoticeVersion"], "privacy_notice_sha256": request["privacyNoticeSha256"],
    }
    gateway.calls.clear()
    for retry_aal, retry_age, status in [("aal2", 0, 201), ("aal1", 0, 403), ("aal2", 901, 403)]:
        retry_claims = {"aal": retry_aal, "amr": [{"method": "totp", "timestamp": int(time.time()) - retry_age}]}
        retry_payload = base64.urlsafe_b64encode(json.dumps(retry_claims).encode()).decode().rstrip("=")
        retried = client.post("/api/v1/company-access/company-year-admissions",
            headers={"Authorization": f"Bearer header.{retry_payload}.signature"}, json=request)
        assert retried.status_code == status, retried.text
        if status == 201:
            assert retried.json()["replayed"] is True
        else:
            assert retried.json()["code"] == "FRESH_MFA_REQUIRED"
    assert gateway.calls == []
