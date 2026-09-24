"""Real public-contract verifier and Governance transaction-boundary behavior."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from talli_backend.application.corporate_register_evidence import CorporateRegisterEvidenceVerifier
from talli_backend.application.corporate_governance_workflow import CorporateGovernanceApplication
from talli_backend.modules.corporate_governance.public import (
    AccountingEntryReference, CorporateGovernanceError, CorporateGovernanceErrorCode,
    CorporateSourceReference, DocumentReference, PreparedSupportedCorporateEvent,
    RecordedSupportedCorporateEvent, SupportedCorporateDocumentFact,
    SupportedCorporateEventKind as Kind, SupportedCorporateEventPhase as Phase,
    SupportedCorporateEvidenceKind as EvidenceKind, SupportedCorporateSourceFact,
)
from talli_backend.modules.documents.public import (
    DocumentId, DocumentsError, DocumentStatus, RetainedDocumentOriginalReceipt,
    VerifiedDocumentEvidence, document_metadata_sha256,
)
from talli_backend.modules.shareholder_register_filing.public import ShareholderRegisterFilingError
from talli_backend.shared.kernel import ErrorCategory, IncomeYear, Timestamp, LocalDate, Money
from test_corporate_governance_supported_events import bank, capital_facts, command, reduction_facts
from test_shareholder_register_capital_source_workflow import setup, capture_register
from test_rf1086_year_source import COMPANY, ACTOR, YEAR, NOW


def harness(kind="cash_issue"):
    source = setup(kind)
    snapshot = capture_register(source)
    evidence = VerifiedDocumentEvidence(source.record, source.record.content_sha256,
        source.record.byte_length, source.record.status, RetainedDocumentOriginalReceipt(
            str(uuid4()), source.record.document_id, COMPANY, source.record.income_year,
            document_metadata_sha256(source.record), source.record.content_sha256, source.record.byte_length, NOW))
    h = SimpleNamespace(snapshot=snapshot, evidence=evidence, rf_actor=ACTOR, document_actor=ACTOR,
        read_error=None, document_error=None, reads=[], originals=[])
    class RFSession:
        @property
        def actor_id(self): return h.rf_actor
        async def read_current_register_observation(self, query, identity):
            h.reads.append((query, identity))
            if h.read_error: raise h.read_error
            return h.snapshot
    class RFFactory:
        async def session(self, token):
            assert token == "owner-token"
            return RFSession()
    class DocumentsSession:
        @property
        def actor_id(self): return h.document_actor
        async def verify_document_evidence(self, identity):
            h.originals.append(identity)
            if h.document_error: raise h.document_error
            return h.evidence
        async def list_documents(self, companies):
            assert companies == (COMPANY,)
            return h.records
    class DocumentsFactory:
        async def session(self, token):
            assert token == "owner-token"
            return DocumentsSession()
    doc_kinds = [EvidenceKind.SIGNED_DECISION, EvidenceKind.AMENDED_ARTICLES, EvidenceKind.REGISTRATION_RECEIPT]
    if kind == "cash_issue": doc_kinds.append(EvidenceKind.CONTRIBUTION_CONFIRMATION)
    facts = tuple(SupportedCorporateDocumentFact(DocumentReference(str(uuid4())), k, 1, "a" * 64) for k in doc_kinds)
    h.records = tuple(replace(source.record, document_id=DocumentId(str(f.document_id)), income_year=YEAR) for f in facts)
    business = replace(capital_facts(), nominal_increase=Money.nok("30000"), share_premium=Money.nok("500")) if kind == "cash_issue" else replace(
        reduction_facts(), old_share_capital=Money.nok("60000"), new_share_capital=Money.nok("30000"), nominal_reduction=Money.nok("30000"))
    h.command = replace(command(kind=Kind.CASH_CAPITAL_INCREASE if kind == "cash_issue" else Kind.LOSS_COVERAGE_CAPITAL_REDUCTION,
        phase=Phase.REGISTERED, facts=business, documents=facts, bank_fact=bank("30500") if kind == "cash_issue" else None,
        shareholder_register_fact=SupportedCorporateSourceFact(CorporateSourceReference(snapshot.observation_id.value), snapshot.version, snapshot.fact_sha256)),
        company_id=COMPANY, actor_id=ACTOR, income_year=YEAR, event_date=LocalDate(snapshot.command.effective_at.date()))
    h.rf_factory, h.documents_factory = RFFactory(), DocumentsFactory()
    h.verifier = CorporateRegisterEvidenceVerifier(h.rf_factory, h.documents_factory)
    h.verify = lambda: asyncio.run(h.verifier.verify("owner-token", h.command))
    return h


@pytest.mark.parametrize("kind,phase", [("cash_issue", Phase.REGISTERED),
    ("loss_covering_reduction", Phase.REGISTERED), ("loss_covering_reduction", Phase.FIRST_RECOGNIZED_AFTER_REGISTRATION)])
def test_real_verifier_binds_current_observation_and_reverifies_unique_prior_year_original(kind, phase):
    h = harness(kind); h.command = replace(h.command, phase=phase)
    assert h.verify() == h.snapshot
    query, identity = h.reads[0]
    assert (query.company_id, query.income_year, query.actor_id, identity) == (COMPANY, YEAR, ACTOR, h.snapshot.observation_id)
    assert h.originals == [h.evidence.document.document_id]
    assert h.evidence.document.income_year == IncomeYear(2024)


@pytest.mark.parametrize("change", ["missing", "wrong_id", "revision", "boolean_revision", "fractional_revision", "hash", "company", "year", "date", "count", "nominal", "kind"])
def test_reference_scope_date_and_economics_mismatch_are_rejected(change):
    h = harness()
    if change == "missing": h.snapshot = None
    elif change == "wrong_id": h.command = replace(h.command, shareholder_register_fact=replace(h.command.shareholder_register_fact, record_id=CorporateSourceReference(str(uuid4()))))
    elif change == "revision": h.command = replace(h.command, shareholder_register_fact=replace(h.command.shareholder_register_fact, revision=2))
    elif change in {"boolean_revision", "fractional_revision"}: h.command = replace(h.command,
        shareholder_register_fact=replace(h.command.shareholder_register_fact, revision=True if change == "boolean_revision" else 1.0))
    elif change == "hash": h.command = replace(h.command, shareholder_register_fact=replace(h.command.shareholder_register_fact, fact_sha256="b" * 64))
    elif change == "company": h.command = replace(h.command, company_id=type(COMPANY)(str(uuid4())))
    elif change == "year": h.command = replace(h.command, income_year=IncomeYear(2024))
    elif change == "date": h.command = replace(h.command, event_date=LocalDate(h.command.event_date.value + timedelta(days=1)))
    elif change == "count": h.command = replace(h.command, facts=replace(h.command.facts, issued_share_count=99))
    elif change == "nominal": h.command = replace(h.command, facts=replace(h.command.facts, nominal_increase=Money.nok("29999.99")))
    elif change == "kind": h.snapshot = harness("loss_covering_reduction").snapshot
    with pytest.raises(CorporateGovernanceError) as caught: h.verify()
    assert caught.value.code == CorporateGovernanceErrorCode.CORPORATE_EVENT_EVIDENCE_INCOMPLETE.value
    assert not h.originals


@pytest.mark.parametrize("field", ["old_share_capital", "new_share_capital", "nominal_reduction"])
def test_reduction_economics_match_each_authoritative_amount(field):
    h = harness("loss_covering_reduction")
    h.command = replace(h.command, facts=replace(h.command.facts, **{field: Money.nok("40000")}))
    with pytest.raises(CorporateGovernanceError): h.verify()


@pytest.mark.parametrize("change", ["metadata", "status", "type", "link", "content", "length", "year", "created", "foreign", "evidence_hash", "evidence_length", "evidence_status", "retained_missing", "retained_hash", "retained_metadata", "retained_company", "retained_year", "retained_document"])
def test_independent_original_and_retained_receipt_must_match_every_recorded_binding(change):
    h = harness(); evidence = h.evidence; record = evidence.document
    if change == "metadata": record = replace(record, name="Changed document")
    if change == "status": record = replace(record, status=DocumentStatus.GENERATED_UNSIGNED)
    if change == "type": record = replace(record, document_type="authority_feedback")
    if change == "link": record = replace(record, linked_to="corporate_decision:" + str(uuid4()))
    if change == "content": record = replace(record, content_sha256="b" * 64)
    if change == "length": record = replace(record, byte_length=999)
    if change == "year": record = replace(record, income_year=YEAR)
    if change == "created": record = replace(record, created_at=record.created_at + timedelta(seconds=1))
    if change == "foreign": record = replace(record, company_id=type(COMPANY)(str(uuid4())))
    evidence = replace(evidence, document=record)
    if change == "evidence_hash": evidence = replace(evidence, content_sha256="b" * 64)
    if change == "evidence_length": evidence = replace(evidence, byte_length=999)
    if change == "evidence_status": evidence = replace(evidence, integrity_status=DocumentStatus.STORED)
    if change == "retained_missing": evidence = replace(evidence, retained_original=None)
    if change.startswith("retained_") and change != "retained_missing":
        field, value = {"retained_hash": ("content_sha256", "b" * 64), "retained_metadata": ("metadata_sha256", "b" * 64),
            "retained_company": ("company_id", type(COMPANY)(str(uuid4()))), "retained_year": ("source_income_year", YEAR),
            "retained_document": ("document_id", DocumentId(str(uuid4())))}[change]
        evidence = replace(evidence, retained_original=replace(evidence.retained_original, **{field: value}))
    h.evidence = evidence
    with pytest.raises(CorporateGovernanceError) as caught: h.verify()
    assert caught.value.category is ErrorCategory.PRECONDITION_FAILED


@pytest.mark.parametrize("actor_field", ["rf_actor", "document_actor"])
def test_session_actors_must_match_authenticated_governance_actor(actor_field):
    h = harness(); setattr(h, actor_field, replace(ACTOR, subject=type(ACTOR.subject)(str(uuid4()))))
    with pytest.raises(CorporateGovernanceError) as caught: h.verify()
    assert caught.value.category is ErrorCategory.FORBIDDEN
    assert not h.reads and not h.originals


@pytest.mark.parametrize("field,error,category", [
    ("read_error", ShareholderRegisterFilingError.forbidden(), ErrorCategory.FORBIDDEN),
    ("read_error", ShareholderRegisterFilingError.unavailable(), ErrorCategory.DEPENDENCY_UNAVAILABLE),
    ("document_error", DocumentsError.not_found(), ErrorCategory.PRECONDITION_FAILED),
    ("document_error", DocumentsError.integrity_failed(), ErrorCategory.PRECONDITION_FAILED),
    ("document_error", DocumentsError.forbidden(), ErrorCategory.FORBIDDEN),
    ("document_error", DocumentsError.storage_unavailable(), ErrorCategory.DEPENDENCY_UNAVAILABLE),
])
def test_owner_failures_are_sanitized_without_conflating_forbidden_and_unavailable(field, error, category):
    h = harness(); setattr(h, field, error)
    with pytest.raises(CorporateGovernanceError) as caught: h.verify()
    assert caught.value.category is category


def test_corrupt_persisted_observation_is_unavailable_not_accepted():
    h = harness(); h.snapshot = replace(h.snapshot, fact_sha256="f" * 64)
    with pytest.raises(CorporateGovernanceError) as caught: h.verify()
    assert caught.value.category is ErrorCategory.DEPENDENCY_UNAVAILABLE
    assert not h.originals


def workflow(h, *, verifier=True):
    h.calls, h.committed, h.pending = [], [], []
    h.replay, h.recorded_at, h.rolled_back = None, NOW, False
    class Transaction:
        actor_id = ACTOR
        async def actor_role(self, company): return "owner"
        async def prepare_supported_event(self, command, canonical):
            h.calls.append("prepare")
            return PreparedSupportedCorporateEvent(canonical, h.replay)
        async def complete_supported_event(self, command, entry, prepared):
            h.calls.append("complete")
            result = RecordedSupportedCorporateEvent(prepared.event, entry, None, None, h.recorded_at, False)
            h.pending.append(result)
            return result
    transaction = Transaction()
    class Session:
        actor_id = ACTOR
        @asynccontextmanager
        async def transaction(self):
            try:
                yield transaction
                h.committed.extend(h.pending); h.pending.clear()
            except Exception:
                h.pending.clear(); h.rolled_back = True
                raise
    class Factory:
        async def session(self, token): return Session()
    class Ledger:
        async def recognize_holding_action(self, command):
            h.calls.append("ledger"); h.pending.append(command)
            return SimpleNamespace(entry_id=AccountingEntryReference(str(uuid4())))
    h.governance_factory, h.transaction = Factory(), transaction
    h.app = CorporateGovernanceApplication(Factory(), h.documents_factory, lambda tx: Ledger(), h.verifier if verifier else None)
    h.run = lambda: asyncio.run(h.app.record_supported_event("owner-token", h.command))
    return h


def test_workflow_checks_real_verifier_before_any_ledger_effect():
    h = workflow(harness()); result = h.run()
    assert h.calls == ["prepare", "ledger", "complete"] and len(h.committed) == 2
    assert h.originals and result.event.canonical_facts["shareholderRegisterFact"]["fact_sha256"] == h.snapshot.fact_sha256


@pytest.mark.parametrize("missing_verifier", [True, False])
def test_workflow_fails_closed_before_ledger_for_missing_verifier_or_stale_observation(missing_verifier):
    h = workflow(harness(), verifier=not missing_verifier)
    h.snapshot = None
    with pytest.raises(CorporateGovernanceError): h.run()
    assert h.calls == ["prepare"] and not h.committed and h.rolled_back


def test_exact_completed_replay_precedes_new_live_register_checks():
    h = workflow(harness()); first = h.run()
    h.replay = replace(first, replayed=True); h.snapshot = None; h.document_error = DocumentsError.storage_unavailable()
    h.calls.clear(); h.reads.clear(); h.originals.clear(); before = list(h.committed)
    assert h.run() == h.replay
    assert h.calls == ["prepare"] and not h.reads and not h.originals and h.committed == before


def test_postdating_observation_rolls_back_ledger_and_governance_before_commit():
    h = workflow(harness()); h.recorded_at = h.snapshot.confirmed_at - timedelta(seconds=1)
    with pytest.raises(CorporateGovernanceError): h.run()
    assert h.calls == ["prepare", "ledger", "complete"]
    assert h.rolled_back and not h.committed and not h.pending


def test_pre_registration_phase_does_not_use_register_verifier():
    h = workflow(harness(), verifier=False)
    h.command = replace(h.command, phase=Phase.BINDING_SUBSCRIPTION, bank_fact=None, shareholder_register_fact=None)
    h.run()
    assert not h.reads and not h.originals and len(h.committed) == 2


def api_payload(h):
    command = h.command
    return {
        "companyId": str(COMPANY), "incomeYear": int(YEAR), "eventId": str(command.event_id),
        "eventReference": str(command.event_reference), "eventDate": command.event_date.value.isoformat(),
        "eventKind": "cash_capital_increase", "phase": "registered",
        "facts": {"factType": "cash_capital_increase", "nominalIncrease": {"amount": "30000", "currency": "NOK"},
            "sharePremium": {"amount": "500", "currency": "NOK"}, "issuedShareCount": 100,
            "singleOrdinaryClass": True, "cashOnly": True, "bindingSubscription": True,
            "fullTimelyPayment": True, "independentConfirmation": True, "registerReconciled": True,
            "norwegianSubscribersOnly": True, "noSpecialTerms": True, "noDirectUseException": True, "issueCostsResolved": True},
        "documentFacts": [{"documentId": str(f.document_id), "evidenceKind": f.evidence_kind.value,
            "revision": f.revision, "contentSha256": f.content_sha256} for f in command.document_facts],
        "bankFact": {"transactionId": str(command.bank_fact.transaction_id),
            "transactionDate": command.event_date.value.isoformat(), "signedAmount": {"amount": "30500", "currency": "NOK"},
            "sourceSha256": command.bank_fact.source_sha256},
        "shareholderRegisterFact": {"recordId": str(command.shareholder_register_fact.record_id),
            "revision": command.shareholder_register_fact.revision, "factSha256": command.shareholder_register_fact.fact_sha256},
        "taxCalculationFact": None,
    }


@pytest.mark.parametrize("failure,status", [(None, 201), ("missing", 409), ("forged_hash", 409), ("unavailable_original", 503)])
def test_actual_http_composition_uses_verified_rf_and_documents_contracts(failure, status):
    from talli_backend.main import create_app
    from talli_backend.modules.ledger.public import LedgerEntryId, LedgerEntryKind, PostedLedgerEntry
    h = workflow(harness())
    async def registration(command, **kwargs):
        h.calls.append("ledger")
        h.pending.append(command)
        return PostedLedgerEntry(LedgerEntryId(str(uuid4())), COMPANY, YEAR,
            LedgerEntryKind.CAPITAL_INCREASE, Timestamp(NOW), False)
    h.transaction.record_cash_capital_increase_registration = registration
    payload = api_payload(h)
    if failure == "missing": h.snapshot = None
    if failure == "forged_hash": payload["shareholderRegisterFact"]["factSha256"] = "f" * 64
    if failure == "unavailable_original": h.document_error = DocumentsError.storage_unavailable()
    client = TestClient(create_app(corporate_governance_session_factory=h.governance_factory,
        documents_session_factory=h.documents_factory, shareholder_register_filing_session_factory=h.rf_factory))
    response = client.post("/api/v1/corporate-governance/supported-events", json=payload,
        headers={"Authorization": "Bearer owner-token", "Idempotency-Key": "corporate-register-binding-0001", "X-Request-Id": "corporate-register-binding"})
    assert response.status_code == status, response.text
    assert h.reads
    if failure is None:
        assert h.originals and len(h.committed) == 2
        assert response.json()["canonicalFacts"]["shareholderRegisterFact"]["fact_sha256"] == payload["shareholderRegisterFact"]["factSha256"]
        assert response.json()["canonicalFacts"]["shareholderRegisterFact"]["record_id"]["value"] == payload["shareholderRegisterFact"]["recordId"]
    else:
        assert not h.committed and "ledger" not in h.calls
