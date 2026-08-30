import base64
import copy
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from talli_backend.main import create_app
from talli_backend.modules.company_access.public import (
    CompanyYearAdmissionGatewayCommand,
    CompanyYearEligibilityRecheckGatewayCommand,
)
from talli_backend.modules.validation_observation.public import (
    PassiveValidationObserver,
    ValidationObservationConfiguration,
)


BUSINESS_TERMS_SHA256 = "afc6fc3610f05056f3de8cc849a33accbf3bdff7d469aef8be57c5ccbe074c04"
DPA_SHA256 = "1f5c45a882db79fb248bdff92bd1a245e97b9a7a2f174b943b761f67bda4b94a"
PRIVACY_SHA256 = "041a65be9f020c037bd65b7097e04afdbeb2c944ef45d7bef3dd380e92f907de"
CUSTOMER_CLAIMS = [
    "Komplett gjenoppbygging av selskapsåret fra 1. januar",
    "Bokføring gjennom hele selskapsåret",
    "Nødvendige selskapsdokumenter",
    "Direkte innsending av aksjonærregisteroppgaven (RF-1086)",
    "Direkte innsending av skattemeldingen for selskapet",
    "Direkte innsending av årsregnskapet",
    "Banktilkobling med robust filimport som reserve",
    "SAF-T 1.40",
    "Komplett selskapsårsarkiv",
    "Sporbare rettelser",
    "Henting av offisielle utfall",
    "Kvitteringer for innsendingene",
]


def access_token() -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"aal": "aal1"}).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


class CompanyRegistryStub:
    def __init__(self, *, entity_type: str = "AS", status_text: str = "aktiv") -> None:
        self.entity_type = entity_type
        self.status_text = status_text
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
            "status_text": self.status_text,
            "source": "brreg",
        }


class AdmissionGatewayStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.admission_replay: Mapping[str, object] | None = None
        self.recheck_replay: Mapping[str, object] | None = None
        self.latest_answers: Mapping[str, object] = {}

    async def session_identity(self, _access_token: str) -> Mapping[str, object]:
        return {
            "id": "00000000-0000-0000-0000-000000000044",
            "email": "owner@example.no",
        }

    async def admit_company_year(
        self, _access_token: str, command: CompanyYearAdmissionGatewayCommand
    ) -> Mapping[str, object]:
        self.calls.append(("admit_company_year", command))
        return {
            "company_id": "10000000-0000-0000-0000-000000000001",
            "company_year_admission_id": "20000000-0000-0000-0000-000000000002",
            "accounting_year": command.accounting_year,
            "reconstruct_from": f"{command.accounting_year}-01-01",
            "capability_manifest_version": command.capability_manifest_version,
            "capability_manifest_sha256": command.capability_manifest_sha256,
            "current_agreement_accepted": True,
            "replayed": False,
        }

    async def company_year_admission_replay(
        self, _access_token: str, _operation_id: str
    ) -> Mapping[str, object] | None:
        return self.admission_replay

    async def company_year_admission_context(
        self,
        _access_token: str,
        company_year_admission_id: str,
        _operation_id: str,
    ) -> Mapping[str, object] | None:
        if company_year_admission_id != "20000000-0000-0000-0000-000000000002":
            return None
        context = {
            "company_year_admission_id": company_year_admission_id,
            "company_id": "10000000-0000-0000-0000-000000000001",
            "accounting_year": 2026,
            "org_number": "314159265",
            "accepted_capability_manifest_version": "2026.1",
            "accepted_capability_manifest_sha256": (
                "9f91a66d0e2cb560d880b6b290c707bc45a8d117a4175780c75e2d1ccdb694de"
            ),
            "accepted_company_year_promise": {
                "accountingYear": 2026,
                "startsOn": "2026-01-01",
                "endsOn": "2026-12-31",
                "reconstructionRequiredFrom": "2026-01-01",
                "onlyAccountingAndFilingProduct": True,
                "customerClaims": CUSTOMER_CLAIMS,
            },
            "latest_assessment_id": "30000000-0000-0000-0000-000000000003",
            "latest_answers": self.latest_answers,
        }
        return {**context, **(self.recheck_replay or {})}

    async def record_company_year_eligibility_recheck(
        self, _access_token: str, command: CompanyYearEligibilityRecheckGatewayCommand
    ) -> Mapping[str, object]:
        self.calls.append(("record_company_year_eligibility_recheck", command))
        return {
            "company_year_eligibility_assessment_id": (
                "31000000-0000-0000-0000-000000000003"
            ),
            "replayed": False,
        }


def public_client(
    *,
    entity_type: str = "AS",
    status_text: str = "aktiv",
    validation_observer: object | None = None,
) -> tuple[TestClient, AdmissionGatewayStub, CompanyRegistryStub]:
    gateway = AdmissionGatewayStub()
    registry = CompanyRegistryStub(entity_type=entity_type, status_text=status_text)
    return (
        TestClient(
            create_app(
                gateway,
                registry,
                validation_observer=validation_observer,
            )
        ),
        gateway,
        registry,
    )


class ValidationObservationGatewayStub:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.commands = []

    async def record(self, command: object) -> bool:
        self.commands.append(command)
        if self.fail:
            raise RuntimeError("observer unavailable")
        return True


def validation_observer(
    gateway: ValidationObservationGatewayStub, *, enabled: bool
) -> PassiveValidationObserver:
    now = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    return PassiveValidationObserver(
        ValidationObservationConfiguration.from_values(
            requested_mode="invited-pilot" if enabled else "off",
            product_mode="prelaunch-validation",
            entitlement_id="10000000-0000-4000-8000-000000000001",
            approved_run_id="V2P8-20260829-LOCAL",
            starts_at=(now - timedelta(minutes=1)).isoformat(),
            expires_at=(now + timedelta(days=1)).isoformat(),
            release_sha256="a" * 64,
            participant_information_sha256="b" * 64,
            subject_binding_key="local-test-key-with-at-least-32-bytes",
            now=now,
        ),
        gateway,
    )


def precheck(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/v1/company-access/eligibility/precheck",
        json={"orgNumber": "314159265", "accountingYear": 2026},
    )
    assert response.status_code == 200, response.text
    return response.json()


def supported_answers(question_codes: list[str]) -> dict[str, str]:
    no_is_supported = {
        "has_auditor_or_audit_requirement",
        "requires_consolidated_accounts",
        "conducts_regulated_finance",
    }
    return {code: "no" if code in no_is_supported else "yes" for code in question_codes}


def definitive_request(precheck_result: Mapping[str, object]) -> dict[str, object]:
    question_codes = list(precheck_result["questionCodes"])
    return {
        "orgNumber": "314159265",
        "accountingYear": 2026,
        "expectedPublicFactsSha256": precheck_result["publicFactsSha256"],
        "capabilityManifestVersion": precheck_result["capabilityManifestVersion"],
        "capabilityManifestSha256": precheck_result["capabilityManifestSha256"],
        "answers": supported_answers(question_codes),
    }


def definitive(client: TestClient, precheck_result: Mapping[str, object]) -> dict[str, object]:
    response = client.post(
        "/api/v1/company-access/eligibility/definitive",
        json=definitive_request(precheck_result),
    )
    assert response.status_code == 200, response.text
    return response.json()


def admission_request(definitive_result: Mapping[str, object]) -> dict[str, object]:
    return {
        "operationId": "40000000-0000-4000-8000-000000000004",
        "orgNumber": "314159265",
        "accountingYear": 2026,
        "expectedPublicFactsSha256": definitive_result["publicFactsSha256"],
        "capabilityManifestVersion": definitive_result["capabilityManifestVersion"],
        "capabilityManifestSha256": definitive_result["capabilityManifestSha256"],
        "answers": definitive_result["answers"],
        "authorityAccepted": True,
        "companyYearPromiseAccepted": True,
        "agreementAccepted": True,
        "businessTermsVersion": "2026-08-30",
        "businessTermsSha256": BUSINESS_TERMS_SHA256,
        "dpaVersion": "2026-08-30",
        "dpaSha256": DPA_SHA256,
        "privacyNoticeVersion": "2026-08-30",
        "privacyNoticeSha256": PRIVACY_SHA256,
    }


def test_public_precheck_is_provisional_and_asks_only_unresolved_material_facts() -> None:
    client, gateway, registry = public_client()

    result = precheck(client)

    assert result["decision"] == "clarify"
    assert result["provisional"] is True
    assert result["reasonCodes"] == ["MATERIAL_FACTS_REQUIRED"]
    assert result["nextStepCode"] == "ANSWER_ELIGIBILITY_QUESTIONS"
    assert result["companyYearPromise"] is None
    assert result["publicFacts"] == {
        "orgNumber": "314159265",
        "name": "Rolig Holding AS",
        "entityType": "AS",
        "statusText": "aktiv",
        "source": "brreg",
    }
    assert len(result["publicFactsSha256"]) == 64
    assert len(result["capabilityManifestSha256"]) == 64
    assert result["capabilityManifestVersion"] == "2026.1"
    assert result["accountingYear"] == 2026
    assert result["questionCodes"] == [question["code"] for question in result["questions"]]
    assert len(result["questionCodes"]) == len(set(result["questionCodes"]))
    assert "transaction_count" not in json.dumps(result)
    assert registry.calls == ["314159265"]
    assert gateway.calls == []


@pytest.mark.parametrize(
    ("entity_type", "status_text", "reason_code"),
    [
        ("ENK", "aktiv", "LEGAL_FORM_NOT_SUPPORTED"),
        ("AS", "slettet", "COMPANY_STATUS_NOT_SUPPORTED"),
        ("AS", "under konkursbehandling", "COMPANY_STATUS_NOT_SUPPORTED"),
        ("AS", "under avvikling", "COMPANY_STATUS_NOT_SUPPORTED"),
    ],
)
def test_public_facts_block_an_unsupported_company_without_private_questions(
    entity_type: str, status_text: str, reason_code: str
) -> None:
    client, gateway, _registry = public_client(entity_type=entity_type, status_text=status_text)

    result = precheck(client)

    assert result["decision"] == "blocked"
    assert result["provisional"] is True
    assert result["reasonCodes"] == [reason_code]
    assert result["reasonExplanations"] == [
        (
            "Selskapet er ikke registrert som et norsk AS."
            if reason_code == "LEGAL_FORM_NOT_SUPPORTED"
            else "Selskapets registrerte status er ikke aktiv og må avklares før Talli kan brukes."
        )
    ]
    assert result["questions"] == []
    assert result["questionCodes"] == []
    assert result["nextStepCode"] == "USE_ACCOUNTANT"
    assert gateway.calls == []


def test_definitive_support_promises_the_complete_calendar_year_from_january_first() -> None:
    client, gateway, registry = public_client()
    initial = precheck(client)

    result = definitive(client, initial)

    assert result["decision"] == "supported"
    assert result["provisional"] is False
    assert result["reasonCodes"] == []
    assert result["reasonExplanations"] == []
    assert result["nextStepCode"] == "CREATE_ACCOUNT_AND_ACCEPT"
    assert result["answers"] == definitive_request(initial)["answers"]
    assert result["companyYearPromise"] == {
        "accountingYear": 2026,
        "startsOn": "2026-01-01",
        "endsOn": "2026-12-31",
        "reconstructionRequiredFrom": "2026-01-01",
        "onlyAccountingAndFilingProduct": True,
        "customerClaims": CUSTOMER_CLAIMS,
    }
    assert registry.calls == ["314159265", "314159265"]
    assert gateway.calls == []


@pytest.mark.parametrize(
    ("question_code", "unsupported_answer", "reason_code"),
    [
        ("is_small_enterprise", "no", "NOT_SMALL_ENTERPRISE"),
        ("has_auditor_or_audit_requirement", "yes", "AUDIT_NOT_SUPPORTED"),
        ("requires_consolidated_accounts", "yes", "CONSOLIDATED_ACCOUNTS_NOT_SUPPORTED"),
        ("uses_calendar_year", "no", "NON_CALENDAR_YEAR_NOT_SUPPORTED"),
        ("is_owner_managed", "no", "OWNER_MANAGEMENT_REQUIRED"),
        ("conducts_regulated_finance", "yes", "REGULATED_FINANCE_NOT_SUPPORTED"),
        ("has_supported_share_structure", "no", "SHARE_STRUCTURE_NOT_SUPPORTED"),
        ("has_only_norwegian_shareholders", "no", "SHAREHOLDERS_NOT_SUPPORTED"),
        ("uses_only_nok_bank_and_bookkeeping", "no", "FOREIGN_CURRENCY_NOT_SUPPORTED"),
        ("has_only_holding_or_no_activity", "no", "OPERATING_ACTIVITY_NOT_SUPPORTED"),
        ("has_supported_investments", "no", "INVESTMENT_PATTERN_NOT_SUPPORTED"),
        ("investment_tax_treatment_is_clear", "no", "INVESTMENT_TAX_TREATMENT_NOT_SUPPORTED"),
        ("has_no_complex_investment_activity", "no", "INVESTMENT_PATTERN_NOT_SUPPORTED"),
        ("has_supported_dividends", "no", "DIVIDEND_PATTERN_NOT_SUPPORTED"),
        ("dividend_basis_and_evidence_are_clear", "no", "DIVIDEND_EVIDENCE_NOT_SUPPORTED"),
        ("has_supported_capital_events", "no", "CAPITAL_EVENT_NOT_SUPPORTED"),
        ("has_no_complex_corporate_events", "no", "CORPORATE_EVENT_NOT_SUPPORTED"),
        ("has_supported_loans", "no", "LOAN_PATTERN_NOT_SUPPORTED"),
        ("loan_terms_are_ordinary_and_clear", "no", "LOAN_TERMS_NOT_SUPPORTED"),
        ("has_supported_group_contributions", "no", "GROUP_CONTRIBUTION_NOT_SUPPORTED"),
        ("group_contribution_facts_are_clear", "no", "GROUP_CONTRIBUTION_NOT_SUPPORTED"),
        ("has_only_supported_income_and_costs", "no", "INCOME_COST_PATTERN_NOT_SUPPORTED"),
        ("prior_closing_matches_opening", "no", "JANUARY_RECONSTRUCTION_NOT_READY"),
        ("all_bank_movements_available", "no", "JANUARY_RECONSTRUCTION_NOT_READY"),
        ("bank_accounts_reconciliable", "no", "JANUARY_RECONSTRUCTION_NOT_READY"),
        ("material_company_facts_confirmable", "no", "JANUARY_RECONSTRUCTION_NOT_READY"),
        ("documents_available", "no", "JANUARY_RECONSTRUCTION_NOT_READY"),
        ("no_unsupported_current_year_activity", "no", "ACTIVITY_PATTERN_NOT_SUPPORTED"),
        ("requires_no_earlier_year_rebuild", "no", "EARLIER_YEAR_MIGRATION_NOT_SUPPORTED"),
        ("is_deterministic_self_service", "no", "SELF_SERVICE_PATTERN_NOT_SUPPORTED"),
        ("has_normal_holding_volume_character", "no", "ACTIVITY_PATTERN_NOT_SUPPORTED"),
    ],
)
def test_goldens_block_every_closed_decision_branch(
    question_code: str, unsupported_answer: str, reason_code: str
) -> None:
    client, gateway, _registry = public_client()
    initial = precheck(client)
    request = definitive_request(initial)
    request["answers"][question_code] = unsupported_answer

    response = client.post("/api/v1/company-access/eligibility/definitive", json=request)

    assert response.status_code == 200
    result = response.json()
    assert result["decision"] == "blocked"
    assert reason_code in result["reasonCodes"]
    assert result["questions"] == [
        next(question for question in initial["questions"] if question["code"] == question_code)
    ]
    assert result["reasonExplanations"] == [
        f"Dette svaret er utenfor grensen: {result['questions'][0]['prompt']}"
    ]
    assert result["nextStepCode"] == "USE_ACCOUNTANT"
    assert result["companyYearPromise"] is None
    assert gateway.calls == []


def test_unknown_answer_is_clarify_and_never_silently_treated_as_no() -> None:
    client, gateway, _registry = public_client()
    initial = precheck(client)
    request = definitive_request(initial)
    request["answers"]["has_only_holding_or_no_activity"] = "unknown"

    response = client.post("/api/v1/company-access/eligibility/definitive", json=request)

    assert response.status_code == 200
    result = response.json()
    assert result["decision"] == "clarify"
    assert result["reasonCodes"] == ["MATERIAL_FACT_UNKNOWN"]
    assert result["reasonExplanations"] == [
        f"Dette må avklares: {result['questions'][0]['prompt']}"
    ]
    assert result["nextStepCode"] == "CLARIFY_WITH_ACCOUNTANT"
    assert result["companyYearPromise"] is None
    assert gateway.calls == []


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_definitive_rejects_an_incomplete_or_undeclared_answer_set(mutation: str) -> None:
    client, gateway, registry = public_client()
    initial = precheck(client)
    request = definitive_request(initial)
    if mutation == "missing":
        request["answers"].pop("uses_calendar_year")
    else:
        request["answers"]["transaction_count"] = "yes"

    response = client.post("/api/v1/company-access/eligibility/definitive", json=request)

    assert response.status_code == 422
    assert response.json()["code"] == "ELIGIBILITY_ANSWERS_INVALID"
    assert registry.calls == ["314159265", "314159265"]
    assert gateway.calls == []


def test_manifest_or_public_fact_change_requires_a_fresh_precheck() -> None:
    client, gateway, registry = public_client()
    initial = precheck(client)
    stale_manifest = definitive_request(initial)
    stale_manifest["capabilityManifestVersion"] = "2025.9"

    manifest_response = client.post(
        "/api/v1/company-access/eligibility/definitive", json=stale_manifest
    )

    assert manifest_response.status_code == 409
    assert manifest_response.json()["code"] == "ELIGIBILITY_MANIFEST_CHANGED"
    assert registry.calls == ["314159265"]

    changed_facts = definitive_request(initial)
    registry.status_text = "under avvikling"
    facts_response = client.post(
        "/api/v1/company-access/eligibility/definitive", json=changed_facts
    )

    assert facts_response.status_code == 409
    assert facts_response.json()["code"] == "ELIGIBILITY_FACTS_CHANGED"
    assert gateway.calls == []


def test_supported_admission_rechecks_and_writes_one_immutable_company_year_command() -> None:
    client, gateway, registry = public_client()
    accepted = definitive(client, precheck(client))

    response = client.post(
        "/api/v1/company-access/company-year-admissions",
        headers={"Authorization": f"Bearer {access_token()}"},
        json=admission_request(accepted),
    )

    assert response.status_code == 201, response.text
    assert response.json() == {
        "companyId": "10000000-0000-0000-0000-000000000001",
        "companyYearAdmissionId": "20000000-0000-0000-0000-000000000002",
        "accountingYear": 2026,
        "reconstructFrom": "2026-01-01",
        "capabilityManifestVersion": "2026.1",
        "capabilityManifestSha256": accepted["capabilityManifestSha256"],
        "currentAgreementAccepted": True,
        "replayed": False,
    }
    assert registry.calls == ["314159265", "314159265", "314159265"]
    assert len(gateway.calls) == 1
    command = gateway.calls[0][1]
    assert isinstance(command, CompanyYearAdmissionGatewayCommand)
    assert command.accounting_year == 2026
    assert str(command.operation_id) == "40000000-0000-4000-8000-000000000004"
    assert command.reconstruct_from == "2026-01-01"
    assert command.public_facts_sha256 == accepted["publicFactsSha256"]
    assert command.answers_sha256 == accepted["answersSha256"]
    assert command.privacy_notice_version == "2026-08-30"
    assert command.privacy_notice_sha256 == PRIVACY_SHA256
    assert str(command.verified_actor) == "00000000-0000-0000-0000-000000000044"


def test_admission_is_exactly_equivalent_with_observer_off_on_or_failing() -> None:
    transcripts = []
    observer_gateways = []
    for enabled, failing in ((False, False), (True, False), (True, True)):
        observer_gateway = ValidationObservationGatewayStub(fail=failing)
        observer_gateways.append(observer_gateway)
        client, business_gateway, registry = public_client(
            validation_observer=validation_observer(
                observer_gateway, enabled=enabled
            )
        )
        accepted = definitive(client, precheck(client))

        response = client.post(
            "/api/v1/company-access/company-year-admissions",
            headers={
                "Authorization": f"Bearer {access_token()}",
                "X-Request-ID": "40000000-0000-4000-8000-000000000099",
            },
            json=admission_request(accepted),
        )
        transcripts.append(
            {
                "status": response.status_code,
                "body": response.content,
                "headers": dict(response.headers),
                "business": copy.deepcopy(business_gateway.calls),
                "external": copy.deepcopy(registry.calls),
            }
        )

    assert transcripts[0] == transcripts[1] == transcripts[2]
    assert observer_gateways[0].commands == []
    assert len(observer_gateways[1].commands) == 1
    assert len(observer_gateways[2].commands) == 1
    command = observer_gateways[1].commands[0]
    assert command.observation.task == "company_year_admission"
    assert command.observation.state == "completed"
    assert command.observation.stage == "onboarding"
    assert not hasattr(command, "company_id")
    assert not hasattr(command.observation, "free_text")


def test_public_request_cannot_supply_any_observation_authority() -> None:
    observer_gateway = ValidationObservationGatewayStub()
    client, business_gateway, _registry = public_client(
        validation_observer=validation_observer(observer_gateway, enabled=True)
    )
    accepted = definitive(client, precheck(client))
    request = admission_request(accepted) | {
        "validationObservationMode": "invited-pilot",
        "validationRunId": "V2P8-20260829-LOCAL",
        "pilotEntitlementId": "10000000-0000-4000-8000-000000000001",
        "validationCaseCode": "V-01",
    }

    response = client.post(
        "/api/v1/company-access/company-year-admissions",
        headers={"Authorization": f"Bearer {access_token()}"},
        json=request,
    )

    assert response.status_code == 422
    assert business_gateway.calls == []
    assert observer_gateway.commands == []


def test_admission_exact_retry_replays_before_registry_lookup() -> None:
    client, gateway, registry = public_client()
    accepted = definitive(client, precheck(client))
    request = admission_request(accepted)
    registry.calls.clear()
    gateway.admission_replay = {
        "company_id": "10000000-0000-0000-0000-000000000001",
        "company_year_admission_id": "20000000-0000-0000-0000-000000000002",
        "accounting_year": 2026,
        "org_number": "314159265",
        "reconstruct_from": "2026-01-01",
        "capability_manifest_version": "2026.1",
        "capability_manifest_sha256": accepted["capabilityManifestSha256"],
        "public_facts_sha256": accepted["publicFactsSha256"],
        "answers": accepted["answers"],
        "business_terms_version": "2026-08-30",
        "business_terms_sha256": BUSINESS_TERMS_SHA256,
        "dpa_version": "2026-08-30",
        "dpa_sha256": DPA_SHA256,
        "privacy_notice_version": "2026-08-30",
        "privacy_notice_sha256": PRIVACY_SHA256,
    }

    response = client.post(
        "/api/v1/company-access/company-year-admissions",
        headers={"Authorization": f"Bearer {access_token()}"},
        json=request,
    )

    assert response.status_code == 201, response.text
    assert response.json()["replayed"] is True
    assert registry.calls == []
    assert gateway.calls == []


def test_admission_operation_id_reuse_with_changed_answers_conflicts_without_provider_io() -> None:
    client, gateway, registry = public_client()
    accepted = definitive(client, precheck(client))
    request = admission_request(accepted)
    registry.calls.clear()
    gateway.admission_replay = {
        "company_id": "10000000-0000-0000-0000-000000000001",
        "company_year_admission_id": "20000000-0000-0000-0000-000000000002",
        "accounting_year": 2026,
        "org_number": "314159265",
        "reconstruct_from": "2026-01-01",
        "capability_manifest_version": "2026.1",
        "capability_manifest_sha256": accepted["capabilityManifestSha256"],
        "public_facts_sha256": accepted["publicFactsSha256"],
        "answers": {**accepted["answers"], "is_small_enterprise": "no"},
        "business_terms_version": "2026-08-30",
        "business_terms_sha256": BUSINESS_TERMS_SHA256,
        "dpa_version": "2026-08-30",
        "dpa_sha256": DPA_SHA256,
        "privacy_notice_version": "2026-08-30",
        "privacy_notice_sha256": PRIVACY_SHA256,
    }

    response = client.post(
        "/api/v1/company-access/company-year-admissions",
        headers={"Authorization": f"Bearer {access_token()}"},
        json=request,
    )

    assert response.status_code == 409
    assert response.json()["code"] == "COMPANY_ACCESS_CONFLICT"
    assert registry.calls == []
    assert gateway.calls == []


@pytest.mark.parametrize(
    ("mutation", "expected_status", "expected_code"),
    [
        ("blocked", 422, "COMPANY_YEAR_NOT_ELIGIBLE"),
        ("stale_privacy", 409, "ADMISSION_EVIDENCE_CHANGED"),
        ("missing_authority", 422, "REQUEST_VALIDATION_FAILED"),
    ],
)
def test_admission_never_writes_for_unsupported_or_stale_evidence(
    mutation: str, expected_status: int, expected_code: str
) -> None:
    client, gateway, _registry = public_client()
    accepted = definitive(client, precheck(client))
    request = admission_request(accepted)
    if mutation == "blocked":
        request["answers"]["has_only_holding_or_no_activity"] = "no"
    elif mutation == "stale_privacy":
        request["privacyNoticeSha256"] = "0" * 64
    else:
        request["authorityAccepted"] = False

    response = client.post(
        "/api/v1/company-access/company-year-admissions",
        headers={"Authorization": f"Bearer {access_token()}"},
        json=request,
    )

    assert response.status_code == expected_status
    assert response.json()["code"] == expected_code
    assert gateway.calls == []


@pytest.mark.parametrize(
    ("trigger", "answer_code", "answer", "decision", "reason_code", "allowed"),
    [
        ("before_filing", None, None, "supported", None, True),
        (
            "material_answer_changed",
            "loan_terms_are_ordinary_and_clear",
            "no",
            "blocked",
            "LOAN_TERMS_NOT_SUPPORTED",
            False,
        ),
        (
            "material_answer_changed",
            "investment_tax_treatment_is_clear",
            "unknown",
            "clarify",
            "MATERIAL_FACT_UNKNOWN",
            False,
        ),
    ],
)
def test_post_admission_recheck_appends_a_safe_current_gate_without_narrowing_the_promise(
    trigger: str,
    answer_code: str | None,
    answer: str | None,
    decision: str,
    reason_code: str | None,
    allowed: bool,
) -> None:
    client, gateway, registry = public_client()
    initial = precheck(client)
    answers = definitive_request(initial)["answers"]
    if answer_code is not None and answer is not None:
        answers[answer_code] = answer

    response = client.post(
        (
            "/api/v1/company-access/company-year-admissions/"
            "20000000-0000-0000-0000-000000000002/eligibility-rechecks"
        ),
        headers={"Authorization": f"Bearer {access_token()}"},
        json={
            "operationId": "41000000-0000-4000-8000-000000000004",
            "trigger": trigger,
            "answers": answers,
        },
    )

    assert response.status_code == 201, response.text
    result = response.json()
    assert result["decision"] == decision
    assert result["consequentialOperationsAllowed"] is allowed
    assert result["archiveExportAvailable"] is True
    assert result["acceptedCapabilityManifestVersion"] == "2026.1"
    assert result["acceptedCompanyYearPromise"] == {
        "accountingYear": 2026,
        "startsOn": "2026-01-01",
        "endsOn": "2026-12-31",
        "reconstructionRequiredFrom": "2026-01-01",
        "onlyAccountingAndFilingProduct": True,
        "customerClaims": CUSTOMER_CLAIMS,
    }
    assert result["reasonCodes"] == ([] if reason_code is None else [reason_code])
    assert registry.calls == ["314159265", "314159265"]
    assert len(gateway.calls) == 1
    command = gateway.calls[0][1]
    assert isinstance(command, CompanyYearEligibilityRecheckGatewayCommand)
    assert command.previous_assessment_id == UUID(
        "30000000-0000-0000-0000-000000000003"
    )
    assert command.decision == decision
    assert command.archive_export_available is True
    assert command.consequential_operations_allowed is allowed


def test_recheck_exact_retry_replays_after_an_intervening_material_assessment() -> None:
    client, gateway, registry = public_client()
    answers = definitive_request(precheck(client))["answers"]
    registry.calls.clear()
    gateway.latest_answers = {
        **answers,
        "loan_terms_are_ordinary_and_clear": "no",
    }
    gateway.recheck_replay = {
        "replay_assessment_id": "31000000-0000-0000-0000-000000000003",
        "replay_trigger": "before_filing",
        "replay_decision": "supported",
        "replay_capability_manifest_version": "2026.1",
        "replay_capability_manifest_sha256": (
            "9f91a66d0e2cb560d880b6b290c707bc45a8d117a4175780c75e2d1ccdb694de"
        ),
        "replay_answers": answers,
        "replay_reason_codes": [],
        "replay_reason_explanations": [],
        "replay_next_step_code": "CONTINUE_COMPANY_YEAR",
        "replay_next_step": "Fortsett selskapsåret i Talli.",
        "replay_consequential_operations_allowed": True,
        "replay_archive_export_available": True,
    }

    response = client.post(
        (
            "/api/v1/company-access/company-year-admissions/"
            "20000000-0000-0000-0000-000000000002/eligibility-rechecks"
        ),
        headers={"Authorization": f"Bearer {access_token()}"},
        json={
            "operationId": "41000000-0000-4000-8000-000000000004",
            "trigger": "before_filing",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["replayed"] is True
    assert registry.calls == []
    assert gateway.calls == []


def test_before_filing_recheck_uses_the_latest_committed_answers() -> None:
    client, gateway, registry = public_client()
    answers = definitive_request(precheck(client))["answers"]
    gateway.latest_answers = answers
    registry.calls.clear()

    response = client.post(
        (
            "/api/v1/company-access/company-year-admissions/"
            "20000000-0000-0000-0000-000000000002/eligibility-rechecks"
        ),
        headers={"Authorization": f"Bearer {access_token()}"},
        json={
            "operationId": "42000000-0000-4000-8000-000000000004",
            "trigger": "before_filing",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["decision"] == "supported"
    assert registry.calls == ["314159265"]
    command = gateway.calls[0][1]
    assert isinstance(command, CompanyYearEligibilityRecheckGatewayCommand)
    assert json.loads(command.answers_json) == answers


def test_material_answer_recheck_requires_the_complete_updated_answers() -> None:
    client, gateway, registry = public_client()
    registry.calls.clear()

    response = client.post(
        (
            "/api/v1/company-access/company-year-admissions/"
            "20000000-0000-0000-0000-000000000002/eligibility-rechecks"
        ),
        headers={"Authorization": f"Bearer {access_token()}"},
        json={
            "operationId": "43000000-0000-4000-8000-000000000004",
            "trigger": "material_answer_changed",
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "ELIGIBILITY_ANSWERS_INVALID"
    assert registry.calls == []
    assert gateway.calls == []


def test_recheck_conceals_an_unavailable_admission_before_registry_or_write() -> None:
    client, gateway, registry = public_client()

    response = client.post(
        (
            "/api/v1/company-access/company-year-admissions/"
            "90000000-0000-0000-0000-000000000009/eligibility-rechecks"
        ),
        headers={"Authorization": f"Bearer {access_token()}"},
        json={
            "operationId": "41000000-0000-4000-8000-000000000004",
            "trigger": "before_filing",
            "answers": {"is_small_enterprise": "yes"},
        },
    )

    assert response.status_code == 404
    assert response.json()["code"] == "COMPANY_ACCESS_NOT_FOUND"
    assert registry.calls == []
    assert gateway.calls == []


def test_legacy_as_only_onboarding_is_closed_instead_of_bypassing_eligibility() -> None:
    client, gateway, registry = public_client()

    response = client.post(
        "/api/v1/company-access/onboarding",
        headers={"Authorization": f"Bearer {access_token()}"},
        json={
            "orgNumber": "314159265",
            "agreementAccepted": True,
            "businessTermsVersion": "2026-08-30",
            "businessTermsSha256": BUSINESS_TERMS_SHA256,
            "dpaVersion": "2026-08-30",
            "dpaSha256": DPA_SHA256,
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "DEFINITIVE_ELIGIBILITY_REQUIRED"
    assert registry.calls == []
    assert gateway.calls == []
