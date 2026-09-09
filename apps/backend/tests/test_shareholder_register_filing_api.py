"""Canonical RF routes use verified sessions and owned immutable result scope."""

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from talli_backend.application.shareholder_register_filing_session import ShareholderRegisterFilingAuthenticationError
from talli_backend.main import create_app
from talli_backend.modules.shareholder_register_filing.public import (
    OpeningSnapshotId, Rf1086ApprovalBasis, Rf1086ApprovalRecord, Rf1086FeedbackArtifactRecord,
    Rf1086OpeningBasis, Rf1086PreviewRecord, Rf1086RecordedResult, Rf1086SimulationBasis, Rf1086SimulationRecord,
    Rf1086WorkspaceSnapshot, ShareholderRegisterFilingError, parse_rf1086_case,
)
from talli_backend.shared.kernel import CompanyId, IncomeYear
from test_shareholder_register_filing_production import (
    APPROVAL, COMPANY, DOCUMENT, ENTITLEMENT, MAIN, OWNER, PREVIEW, SUBMISSION, CoordinatorSession,
)

BASE = "/api/v1/shareholder-register-filings"
HEADERS = {"Authorization": "Bearer local-owner", "X-Request-ID": "rf-new-route-proof"}
SETUP = "d0000000-0000-4000-8000-00000000000d"
COMMENT = "e0000000-0000-4000-8000-00000000000e"
STAMP = "2026-09-09T12:00:00Z"
SIMULATION_ORACLES = json.loads((Path(__file__).parent / "fixtures/rf1086_oracle/runtime-simulation-oracle.json").read_text())


class PreparationSession(CoordinatorSession):
    def __init__(self):
        super().__init__()
        self.commands = []
        self.denied = None
        self.preview_visible = True
        self.prepared = None
        self.record = Rf1086PreviewRecord(PREVIEW, COMPANY, SETUP, 2025, "aksjonærregisteroppgaven", "ready", (),
            "Original preview", "<H>original</H>\r\n", {MAIN: "<U>original</U>"}, "persisted", STAMP)

    def observed(self, command):
        self.commands.append(command)
        if self.denied:
            raise self.denied
        assert command.actor_id == self.actor_id

    def recorded(self, command, *, company_wide=False):
        self.observed(command)
        return Rf1086RecordedResult(SUBMISSION, CompanyId(COMPANY), None if company_wide else IncomeYear(2025))

    async def load_opening(self, command):
        self.observed(command)
        raw = json.loads((Path(__file__).resolve().parents[3] / "tests/fixtures/rf1086/no_activity.json").read_text())
        return Rf1086OpeningBasis(CompanyId(COMPANY), OpeningSnapshotId(SETUP), IncomeYear(2025), parse_rf1086_case(raw), "a" * 64)

    async def record_preview(self, command, prepared):
        self.prepared = prepared
        return self.recorded(command)

    async def record_override(self, command):
        return self.recorded(command)

    async def add_review_comment(self, command):
        return self.recorded(command)

    async def acknowledge_review_comment(self, command):
        return self.recorded(command)

    async def load_simulation_basis(self, command):
        self.observed(command)
        return Rf1086SimulationBasis(self.record, "b" * 64, True, 0, ())

    async def record_simulation(self, command, prepared):
        self.prepared = prepared
        return self.recorded(command)

    async def confirm_filing_permission(self, command):
        return self.recorded(command, company_wide=True)

    async def record_test_evidence(self, command):
        return self.recorded(command, company_wide=True)

    async def load_approval_basis(self, command):
        self.observed(command)
        return Rf1086ApprovalBasis(self.record, "310279617", "c" * 64)

    async def record_approval(self, command, prepared):
        self.prepared = prepared
        return self.recorded(command)

    async def preview_record(self, query):
        self.observed(query)
        return self.record if self.preview_visible else None

    async def workspace(self, query):
        self.observed(query)
        previews = (self.record, replace(self.record, id=DOCUMENT, income_year=2024))
        if query.income_year is not None:
            previews = tuple(row for row in previews if row.income_year == int(query.income_year))
        approval = Rf1086ApprovalRecord(APPROVAL, ENTITLEMENT, PREVIEW, COMPANY, OWNER, 2025,
            "aksjonaerregisteroppgaven", "rf1086_no_activity_v1", "rf1086-production-v1", "a" * 64, "b" * 64,
            {"documentHashes": [{"name": "hovedskjema", "sha256": "c" * 64}], "warnings": []}, OWNER, STAMP, None, None)
        artifact = Rf1086FeedbackArtifactRecord(DOCUMENT, COMPANY, SUBMISSION, MAIN, "application/xml", 17, "d" * 64, STAMP, "accepted")
        return Rf1086WorkspaceSnapshot(query.company_id, query.income_year, previews=previews,
            approvals=(approval,) if query.income_year is None or int(query.income_year) == 2025 else (),
            feedback_artifacts=(artifact,) if query.income_year is None or int(query.income_year) == 2025 else ())


class Sessions:
    def __init__(self):
        self.value = PreparationSession()
        self.tokens = []

    async def session(self, token):
        self.tokens.append(token)
        if token != "local-owner":
            raise ShareholderRegisterFilingAuthenticationError()
        return self.value


def setup():
    sessions = Sessions()
    return TestClient(create_app(shareholder_register_filing_session_factory=sessions)), sessions


MUTATIONS = [
    ("previews", {"companyId": COMPANY, "openingSnapshotId": SETUP}, False),
    ("overrides", {"previewId": PREVIEW, "fieldTarget": " share_count ", "oldValue": "100", "newValue": "100",
                   "reason": " Reviewed original records ", "riskLevel": "advisory", "ownerConfirmed": True}, False),
    ("review-comments", {"previewId": PREVIEW, "severity": "advisory", "body": " Original records reviewed "}, False),
    ("review-comment-acknowledgements", {"commentId": COMMENT}, False),
    ("simulations", {"previewId": PREVIEW, "authorityConfirmed": True, "previewConfirmed": True}, False),
    ("filing-permissions", {"companyId": COMPANY, "productionEnabled": True}, True),
    ("test-evidence", {"companyId": COMPANY, "environment": "manual_evidence", "status": "accepted",
                       "testReference": " synthetic reference ", "feedbackSummary": " reviewed fixture ",
                       "receiptReference": None, "archiveReference": None, "evidenceUrl": None, "payloadHash": None}, True),
    ("production-approvals", {"previewId": PREVIEW, "entitlementId": ENTITLEMENT, "realFilingConfirmed": True}, False),
]


@pytest.mark.parametrize("path,body,company_wide", MUTATIONS, ids=[row[0] for row in MUTATIONS])
def test_mutation_binds_actor_correlation_and_returns_verified_original_scope(path, body, company_wide):
    api, sessions = setup()
    response = api.post(BASE + "/" + path, json=body, headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json() == {"recordId": SUBMISSION, "companyId": COMPANY, "incomeYear": None if company_wide else 2025}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"] == "rf-new-route-proof"
    assert sessions.tokens == ["local-owner"]
    assert sessions.value.commands
    for command in sessions.value.commands:
        assert command.actor_id == sessions.value.actor_id
        assert str(command.correlation_id) == "rf-new-route-proof"
    if path == "previews":
        assert sessions.value.prepared.rendered.filing == "aksjonærregisteroppgaven"
    if path == "production-approvals":
        assert sessions.value.prepared.manifest["obligation"] == "aksjonaerregisteroppgaven"
        assert sessions.value.record.filing == "aksjonærregisteroppgaven"


@pytest.mark.parametrize("path,body,_", MUTATIONS, ids=[row[0] for row in MUTATIONS])
@pytest.mark.parametrize("forged", ["actorId", "correlationId", "incomeYear", "ready", "hovedskjemaXml", "manifest", "confirmedAt"])
def test_mutation_rejects_client_authority_and_generated_facts_before_session(path, body, _, forged):
    api, sessions = setup()
    response = api.post(BASE + "/" + path, json=body | {forged: "untrusted"}, headers=HEADERS)
    assert response.status_code == 422
    assert not sessions.tokens and not sessions.value.commands


@pytest.mark.parametrize("path,field", [("overrides", "ownerConfirmed"), ("simulations", "authorityConfirmed"),
    ("simulations", "previewConfirmed"), ("filing-permissions", "productionEnabled"), ("production-approvals", "realFilingConfirmed")])
@pytest.mark.parametrize("value", ["true", 1, None])
def test_confirmation_fields_reject_coercible_non_booleans(path, field, value):
    api, sessions = setup()
    body = next(row[1] for row in MUTATIONS if row[0] == path)
    assert api.post(BASE + "/" + path, json=body | {field: value}, headers=HEADERS).status_code == 422
    assert not sessions.tokens


@pytest.mark.parametrize("factory,status", [(ShareholderRegisterFilingError.forbidden, 403),
    (ShareholderRegisterFilingError.not_found, 404), (ShareholderRegisterFilingError.company_year_not_admitted, 409),
    (ShareholderRegisterFilingError.unavailable, 503)])
def test_owned_role_and_availability_errors_are_bounded_without_evidence_leak(factory, status):
    api, sessions = setup()
    sessions.value.denied = factory()
    response = api.get(BASE + f"/workspace?companyId={COMPANY}", headers=HEADERS)
    assert response.status_code == status
    assert response.headers["cache-control"] == "no-store"
    assert "Original preview" not in response.text and "original</H>" not in response.text


@pytest.mark.parametrize("suffix", [f"/workspace?companyId={COMPANY}", f"/previews/{PREVIEW}"])
def test_reads_require_verified_bearer_and_preserve_no_store(suffix):
    api, sessions = setup()
    for headers in ({}, {"Authorization": "Bearer forged"}):
        response = api.get(BASE + suffix, headers=headers)
        assert response.status_code == 401 and "forged" not in response.text
    assert not sessions.value.commands


def test_workspace_all_history_is_not_implicitly_filtered_and_immutable_nested_values_serialize():
    api, sessions = setup()
    response = api.get(BASE + f"/workspace?companyId={COMPANY}", headers=HEADERS)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["incomeYear"] is None
    assert [row["incomeYear"] for row in body["previews"]] == [2025, 2024]
    assert body["approvals"][0]["manifest"]["documentHashes"][0]["sha256"] == "c" * 64
    assert body["feedbackArtifacts"][0]["documentId"] == MAIN
    assert sessions.value.commands[-1].income_year is None
    filtered = api.get(BASE + f"/workspace?companyId={COMPANY}&incomeYear=2024", headers=HEADERS)
    assert filtered.status_code == 200
    assert [row["incomeYear"] for row in filtered.json()["previews"]] == [2024]
    assert filtered.json()["approvals"] == []
    assert filtered.json()["feedbackArtifacts"] == []
    assert int(sessions.value.commands[-1].income_year) == 2024


def test_preview_read_preserves_raw_label_xml_and_missing_evidence_remains_not_found():
    api, sessions = setup()
    response = api.get(BASE + f"/previews/{PREVIEW}", headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["filing"] == "aksjonærregisteroppgaven"
    assert response.json()["hovedskjemaXml"] == "<H>original</H>\r\n"
    assert response.json()["underskjemaXml"] == {MAIN: "<U>original</U>"}
    assert str(sessions.value.commands[-1].preview_id) == PREVIEW
    sessions.value.preview_visible = False
    missing = api.get(BASE + f"/previews/{PREVIEW}", headers=HEADERS)
    assert missing.status_code == 404 and "original" not in missing.text


def _simulation_workspace_api(case):
    result = case["result"]
    recorded_at = result["authority_confirmed_at"]
    record = Rf1086SimulationRecord(
        id=SUBMISSION, preview_id=case["preview"]["id"], authority_test_run_id=None,
        company_id=result["company_id"], income_year=result["income_year"], filing=result["filing"],
        mode="simulation", adapter_mode="simulation", payload_hash=case["payload_hash"],
        idempotency_key=case["idempotency_key"], status=result["status"], calls=tuple(result["calls"]),
        receipt_id=result["receipt_id"], feedback_document_ids=tuple(result["feedback_document_ids"]),
        feedback_items=tuple(case["feedback_items"]), receipt_metadata=case["receipt_metadata"],
        submitted_payload_ref=case["submitted_payload_ref"], submitted_payload=case["submitted_payload"],
        authority_confirmed_at=result["authority_confirmed_at"], preview_confirmed_at=result["preview_confirmed_at"],
        created_at=recorded_at, updated_at=recorded_at, submitted_by=result["authority_confirmed_by"],
    )

    class HistoricalSimulationSession(PreparationSession):
        async def workspace(self, query):
            self.observed(query)
            return Rf1086WorkspaceSnapshot(query.company_id, query.income_year, simulations=(record,))

    sessions = Sessions()
    sessions.value = HistoricalSimulationSession()
    api = TestClient(create_app(shareholder_register_filing_session_factory=sessions))
    return api, record


def _assert_original_simulation_json_through_workspace(case):
    api, record = _simulation_workspace_api(case)
    response = api.get(BASE + f"/workspace?companyId={record.company_id}", headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    row = response.json()["simulations"][0]
    # Only the published transport's field names change. Persisted nested
    # values, XML strings, hashes, ordering and timestamp spelling remain exact.
    expected_calls = [{
        "endpoint": call["endpoint"], "bodyHash": call["body_hash"],
        "idempotencyKey": call["idempotency_key"], "status": call["status"], "createdAt": call["created_at"],
    } for call in case["result"]["calls"]]
    assert row["calls"] == expected_calls
    assert row["receiptMetadata"] == case["receipt_metadata"]
    assert row["submittedPayloadRef"] == case["submitted_payload_ref"]
    assert row["submittedPayload"] == case["submitted_payload"]
    assert row["feedbackItems"] == case["feedback_items"]
    assert row["payloadHash"] == case["payload_hash"]
    assert row["idempotencyKey"] == case["idempotency_key"]


@pytest.mark.parametrize("case", SIMULATION_ORACLES, ids=lambda case: case["name"])
def test_workspace_preserves_full_original_runtime_simulation_json(case):
    _assert_original_simulation_json_through_workspace(case)


@pytest.mark.parametrize("timestamp", ["2026-09-09T12:00:00Z", "2026-09-09T12:00:00.123Z", "2026-09-09T12:00:00.123000Z"],
    ids=["seconds", "milliseconds", "microseconds"])
def test_workspace_preserves_nested_historical_timestamp_precision(timestamp):
    case = deepcopy(SIMULATION_ORACLES[0])
    for call in case["result"]["calls"]:
        call["created_at"] = timestamp
    case["receipt_metadata"]["receivedAt"] = timestamp
    case["submitted_payload_ref"]["storedAt"] = timestamp
    _assert_original_simulation_json_through_workspace(case)
