"""Real byte verification and application ordering; persistence is explicitly fake."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, time, timedelta
from hashlib import sha256
from types import SimpleNamespace

import pytest

from talli_backend.application.corporate_governance_workflow import CorporateGovernanceApplication
from talli_backend.application.corporate_register_evidence import CorporateRegisterEvidenceVerifier
from talli_backend.modules.corporate_governance import public as gov
from talli_backend.modules.corporate_governance.service import CorporateGovernanceService
from talli_backend.modules.documents import public as docs
from talli_backend.modules.documents.service import DocumentsService
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ErrorCategory, IncomeYear, LocalDate, Money
from test_corporate_register_evidence_amendment import NOW, identifier
from test_corporate_governance_supported_events import command as event_command, bank, capital_facts, reduction_facts, source
from test_rf1086_register_observation import basis
from test_supabase_corporate_register_evidence_amendment import KEY, chain_payload, query


def harness(*, overlap=False, verifier=True, kind="loss_covering_reduction", phase=gov.SupportedCorporateEventPhase.REGISTERED):
    h = SimpleNamespace(events=[], guard=False, owner=True, prepare_error=None, append_error=None,
        replay=None, lookup_status='not_observed', io_hook=None, stored={}, submitted=[], rf_error=None,
        document_actor=None, rf_actor=None, session_error=None)
    cash = kind == 'cash_issue'
    facts = (replace(capital_facts(), nominal_increase=Money.nok('60000'), share_premium=Money.nok('500')) if cash
        else replace(reduction_facts(), old_share_capital=Money.nok('60000'), nominal_reduction=Money.nok('30000')))
    initial = event_command(kind=gov.SupportedCorporateEventKind.CASH_CAPITAL_INCREASE if cash else gov.SupportedCorporateEventKind.LOSS_COVERAGE_CAPITAL_REDUCTION,
        phase=phase, facts=facts, bank_fact=bank('60500') if cash else None, shareholder_register_fact=source(1), documents=())
    actor, company, year = initial.actor_id, initial.company_id, initial.income_year
    h.actor, h.company = actor, company
    records, contents = {}, {}
    for n in range(1, 7):
        identity = docs.DocumentId(identifier(100 + n)); content = ('%PDF-1.7\nOriginal ' + str(n)).encode()
        source_year = IncomeYear(2024) if n == 5 else year
        record = docs.DocumentRecord(identity, company, source_year, 'corporate_document', f'Original {n}.pdf',
            'workspace', docs.DocumentStatus.ATTACHED, 5, str(identity), 'application/pdf', len(content),
            sha256(content).hexdigest(), actor, NOW - timedelta(days=1), None, None)
        records[identity] = record; contents[record.storage_key] = content
    h.records, h.contents = records, contents
    h.gov_ids = tuple(docs.DocumentId(identifier(100 + n)) for n in ((1, 2, 3, 6) if cash else (1, 2, 3)))
    h.memo_id = docs.DocumentId(identifier(104)); h.rf_id = h.gov_ids[0] if overlap else docs.DocumentId(identifier(105))
    kinds = (gov.SupportedCorporateEvidenceKind.SIGNED_DECISION, gov.SupportedCorporateEvidenceKind.AMENDED_ARTICLES,
        gov.SupportedCorporateEvidenceKind.REGISTRATION_RECEIPT)
    if cash: kinds += (gov.SupportedCorporateEvidenceKind.CONTRIBUTION_CONFIRMATION,)
    def fact(identity, kind, revision=3):
        return gov.SupportedCorporateDocumentFact(gov.DocumentReference(identity.value), kind, revision, records[identity].content_sha256)
    event = replace(initial, document_facts=tuple(fact(identity, kind) for identity, kind in zip(h.gov_ids, kinds)),
        event_date=LocalDate(initial.event_date.value))
    original = gov.RecordedSupportedCorporateEvent(CorporateGovernanceService().prepare_supported_event(event),
        gov.AccountingEntryReference(identifier(201)), None, None, NOW, False)
    h.anchor = gov.anchor_supported_corporate_event_evidence(original, original_actor_id=actor.subject)
    observation_command, context = basis(kind)
    rd = records[h.rf_id]
    evidence = tuple(rf.Rf1086RegisterDocumentEvidence(rd.document_id.value, company, rd.content_sha256,
        rd.content_sha256, rd.byte_length, rd.document_type, rd.status.value, rd.created_at,
        docs.document_metadata_sha256(rd), role, rd.income_year) for role in ('register_before','register_after','registration'))
    observation_command = replace(observation_command, company_id=company, actor_id=actor, income_year=year,
        effective_at=datetime.combine(event.event_date.value, time()), documents=evidence)
    context = replace(context, actor_id=actor, company_id=company, income_year=year, documents=evidence)
    h.snapshot = rf.prepare_rf1086_register_observation(observation_command, context=context,
        observation_id=rf.Rf1086RegisterObservationId(identifier(202)), confirmed_at=NOW + timedelta(seconds=1))
    h.command = gov.AmendSupportedCorporateRegisterEvidence(company, year, actor, event.event_id, h.anchor.anchor_sha256,
        None, gov.CorporateRegisterWithdrawalReference(gov.CorporateSourceReference(identifier(203)), 'c'*64, source(1)),
        gov.SupportedCorporateSourceFact(gov.CorporateSourceReference(h.snapshot.observation_id.value), h.snapshot.version, h.snapshot.fact_sha256),
        fact(h.memo_id, gov.SupportedCorporateEvidenceKind.CORRECTION_MEMO, 2), ' Exact reason – ø\n')
    h.chain = lambda: gov.parse_corporate_register_evidence_chain_snapshot(chain_payload(h.anchor), query=query(h.command))
    class Persistence:
        actor_id = actor
        async def get_document(self, identity):
            assert not h.guard; h.events.append(('metadata', identity)); return h.records.get(identity)
        async def refresh_actor_role(self, company_id):
            return 'owner' if h.owner and company_id == company else None
        async def retain_verified_original(self, document, content):
            assert not h.guard and document == h.records.get(document.document_id)
            assert sha256(content).hexdigest() == document.content_sha256
            h.events.append(('retain', document.document_id))
            receipt = docs.RetainedDocumentOriginalReceipt(identifier(300 + len(h.stored)), document.document_id,
                company, document.income_year, docs.document_metadata_sha256(document), document.content_sha256,
                document.byte_length, NOW + timedelta(seconds=2))
            h.stored[document.document_id] = receipt
            return receipt
    class Storage:
        async def read_object(self, *, bucket, storage_key):
            assert not h.guard
            h.events.append(('bytes', storage_key))
            if h.io_hook: h.io_hook(storage_key)
            return docs.StoredDocumentObject(h.contents[storage_key], 'application/pdf')
    service = DocumentsService(Persistence(), Storage())
    class DocumentsFactory:
        async def session(self, token):
            assert token == 'owner-token' and not h.guard
            h.events.append(('documents_session',))
            if h.session_error: raise h.session_error
            if h.document_actor is not None:
                return SimpleNamespace(actor_id=h.document_actor, verify_document_evidence=service.verify_document_evidence)
            return service
    class RFSession:
        @property
        def actor_id(self): return h.rf_actor or actor
        async def read_current_register_observation(self, scope, identity):
            assert not h.guard
            h.events.append(('rf', scope, identity))
            if h.rf_error: raise h.rf_error
            return h.snapshot
    class RFFactory:
        async def session(self, token):
            assert token == 'owner-token' and not h.guard
            h.events.append(('rf_session',)); return RFSession()
    class Transaction:
        actor_id = actor
        async def actor_role(self, scope): return 'owner' if h.owner else None
        async def prepare_register_evidence_amendment(self, command, *, idempotency_key):
            assert h.guard and command == h.command and idempotency_key == KEY
            h.events.append(('prepare',))
            if h.prepare_error: raise h.prepare_error
            if h.replay: return gov.PreparedCorporateRegisterEvidenceAmendment('recorded', receipt=h.replay)
            return gov.PreparedCorporateRegisterEvidenceAmendment('ready', snapshot=h.chain())
        async def append_register_evidence_amendment(self, command, *, originals, idempotency_key):
            assert h.guard
            h.events.append(('append',)); h.submitted.append((command, originals, idempotency_key))
            if h.append_error: raise h.append_error
            result = gov.prepare_supported_corporate_register_evidence_amendment(command, anchor=h.anchor,
                amendment_id=gov.CorporateRegisterEvidenceAmendmentId(identifier(204)), recorded_at=NOW+timedelta(seconds=3), originals=originals)
            h.replay = result
            return getattr(h, 'append_result', result)
        async def lookup_register_evidence_amendment(self, scope, *, idempotency_key, request_sha256):
            assert h.guard and scope == query(h.command) and idempotency_key == KEY
            assert request_sha256 == gov.corporate_register_evidence_amendment_request_digest(h.command)
            h.events.append(('lookup',))
            if h.prepare_error: raise h.prepare_error
            return gov.CorporateRegisterEvidenceAmendmentLookup(h.lookup_status, h.replay if h.lookup_status == 'recorded' else None)
        async def read_register_evidence_chain(self, scope):
            assert h.guard and scope == query(h.command)
            h.events.append(('chain',)); return h.chain()
    class Session:
        actor_id = actor
        @asynccontextmanager
        async def transaction(self, *, guarded_company_id=None):
            assert guarded_company_id == company and not h.guard
            h.guard = True; h.events.append(('begin',))
            try:
                yield Transaction()
                h.events.append(('commit',))
            except BaseException:
                h.events.append(('rollback',)); raise
            finally: h.guard = False
    class Sessions:
        async def session(self, token):
            assert token == 'owner-token'; return Session()
    def no_ledger(_): pytest.fail('Evidence amendment must not create or amend Ledger entries')
    h.verifier = CorporateRegisterEvidenceVerifier(RFFactory(), DocumentsFactory())
    h.app = CorporateGovernanceApplication(Sessions(), DocumentsFactory(), no_ledger, h.verifier if verifier else None)
    h.run = lambda: asyncio.run(h.app.amend_supported_register_evidence('owner-token', h.command, idempotency_key=KEY))
    h.lookup = lambda: asyncio.run(h.app.lookup_register_evidence_amendment('owner-token', query(h.command),
        idempotency_key=KEY, request_sha256=gov.corporate_register_evidence_amendment_request_digest(h.command)))
    return h


@pytest.mark.parametrize('kind,phase', [('cash_issue',gov.SupportedCorporateEventPhase.REGISTERED),
    ('loss_covering_reduction',gov.SupportedCorporateEventPhase.REGISTERED),
    ('loss_covering_reduction',gov.SupportedCorporateEventPhase.FIRST_RECOGNIZED_AFTER_REGISTRATION)])
@pytest.mark.parametrize('overlap', [False, True])
def test_real_documents_bytes_are_verified_once_per_union_identity_between_guarded_transactions(overlap, kind, phase):
    h = harness(overlap=overlap,kind=kind,phase=phase); before = gov.serialize_corporate_register_evidence_amendment_command(h.command)
    result = h.run()
    required = set((*h.gov_ids, h.memo_id, h.rf_id))
    assert {row.document_id.value for row in result.originals} == {row.value for row in required}
    assert len([e for e in h.events if e[0] == 'bytes']) == len(required)
    assert h.events[0:3] == [('begin',), ('prepare',), ('commit',)]
    assert h.events[-3:] == [('begin',), ('append',), ('commit',)]
    assert not h.guard and len(h.submitted) == 1
    assert before == gov.serialize_corporate_register_evidence_amendment_command(h.command)
    assert h.submitted[0][0] == h.command and h.submitted[0][2] == KEY
    by_id = {row.document_id.value: row for row in result.originals}
    assert by_id[h.gov_ids[0].value].revision == 3
    assert by_id[h.memo_id.value].revision == 2
    if not overlap:
        assert by_id[h.rf_id.value].revision == 1 and by_id[h.rf_id.value].source_income_year == IncomeYear(2024)


@pytest.mark.parametrize('failure', ['documents_outage', 'rf_outage', 'missing_verifier'])
def test_committed_prepare_replay_precedes_every_external_evidence_dependency(failure):
    h = harness(); first = h.run(); h.events.clear(); h.submitted.clear()
    h.session_error = docs.DocumentsError.storage_unavailable(); h.snapshot = None
    if failure == 'missing_verifier': h.app._register_evidence = None
    assert h.run() == first
    assert h.events == [('begin',), ('prepare',), ('commit',)] and not h.submitted


@pytest.mark.parametrize('category', [ErrorCategory.PRECONDITION_FAILED, ErrorCategory.FORBIDDEN, ErrorCategory.CONFLICT, ErrorCategory.DEPENDENCY_UNAVAILABLE])
def test_prepare_mfa_admission_owner_conflict_or_outage_fails_before_rf_and_documents_io(category):
    h = harness()
    h.prepare_error = gov.CorporateGovernanceError(code='prepare_failure', category=category, message='Safe prepare failure')
    with pytest.raises(gov.CorporateGovernanceError) as error: h.run()
    assert error.value.category is category
    assert h.events == [('begin',), ('prepare',), ('rollback',)] and not h.stored and not h.submitted


@pytest.mark.parametrize('state', ['not_observed', 'conflict', 'recorded', 'unavailable'])
def test_explicit_recovery_never_prepares_verifies_or_appends(state):
    h = harness()
    if state == 'recorded': h.run()
    h.events.clear(); h.submitted.clear(); h.lookup_status = state
    if state == 'unavailable':
        h.prepare_error = gov.CorporateGovernanceError.unavailable()
        with pytest.raises(gov.CorporateGovernanceError): h.lookup()
    else: assert h.lookup().status == state
    assert all(e[0] in ('begin','lookup','commit','rollback') for e in h.events) and not h.submitted


@pytest.mark.parametrize('attack', ['tamper', 'metadata', 'removed', 'owner_revoked'])
@pytest.mark.parametrize('family', ['governance', 'memo', 'rf'])
def test_real_document_service_blocks_changed_bytes_metadata_or_owner_before_append(attack, family):
    h = harness(); identity = {'governance':h.gov_ids[0], 'memo':h.memo_id, 'rf':h.rf_id}[family]
    def change(key):
        if key != h.records[identity].storage_key: return
        if attack == 'tamper': h.contents[key] = b'%PDF-1.7\ntampered'
        elif attack == 'metadata': h.records[identity] = replace(h.records[identity], name='Changed.pdf')
        elif attack == 'removed': h.records[identity] = replace(h.records[identity], status=docs.DocumentStatus.REMOVED)
        else: h.owner = False
    h.io_hook = change
    with pytest.raises(gov.CorporateGovernanceError): h.run()
    assert not h.submitted and not h.guard and ('append',) not in h.events


@pytest.mark.parametrize('failure', ['mfa_expired', 'owner_revoked', 'head_changed', 'rf_withdrawn', 'documents_changed', 'database_outage'])
def test_final_admission_failure_never_retries_or_changes_exact_command_key(failure):
    h = harness(); before = gov.serialize_corporate_register_evidence_amendment_command(h.command)
    category = ErrorCategory.DEPENDENCY_UNAVAILABLE if failure == 'database_outage' else ErrorCategory.FORBIDDEN if failure == 'owner_revoked' else ErrorCategory.PRECONDITION_FAILED
    h.append_error = gov.CorporateGovernanceError(code=failure, category=category, message='Final admission failed')
    with pytest.raises(gov.CorporateGovernanceError) as error: h.run()
    assert error.value.category is category
    assert len(h.submitted) == 1 and [e[0] for e in h.events].count('prepare') == 1
    assert h.submitted[0][0] == h.command and h.submitted[0][2] == KEY and h.replay is None
    assert before == gov.serialize_corporate_register_evidence_amendment_command(h.command)
    assert h.events[-1] == ('rollback',) and not h.guard


@pytest.mark.parametrize('owner', ['documents', 'rf'])
def test_cross_owner_session_actor_mismatch_is_forbidden_without_byte_io(owner):
    h = harness(); other = replace(h.actor, subject=type(h.actor.subject)(identifier(999)))
    setattr(h, 'document_actor' if owner == 'documents' else 'rf_actor', other)
    with pytest.raises(gov.CorporateGovernanceError) as error: h.run()
    assert error.value.category is ErrorCategory.FORBIDDEN
    assert not any(e[0] == 'bytes' for e in h.events) and not h.submitted


def test_history_read_uses_only_guarded_persistence_and_no_evidence_verifier():
    h = harness(verifier=False)
    result = asyncio.run(h.app.read_register_evidence_chain('owner-token', query(h.command)))
    assert result.chain.anchor == h.anchor
    assert h.events == [('begin',), ('chain',), ('commit',)]


@pytest.mark.parametrize('change', ['count', 'digest', 'query'])
def test_untrusted_typed_ready_snapshot_is_revalidated_before_any_evidence_io(change):
    h = harness(); valid = h.chain()
    broken = (replace(valid, amendment_count=1) if change == 'count' else
        replace(valid, enumeration_sha256='f' * 64) if change == 'digest' else
        replace(valid, query=replace(valid.query, income_year=IncomeYear(2025))))
    h.chain = lambda: broken
    with pytest.raises(gov.CorporateGovernanceError) as error: h.run()
    assert error.value.category is ErrorCategory.DEPENDENCY_UNAVAILABLE
    assert not h.submitted and not any(e[0] in ('rf_session', 'documents_session', 'bytes') for e in h.events)


@pytest.mark.parametrize('change', ['missing', 'corrupt', 'wrong_reference', 'wrong_date', 'wrong_economics'])
def test_replacement_rf_snapshot_is_bound_before_original_byte_io(change):
    h = harness()
    if change == 'missing': h.snapshot = None
    elif change == 'corrupt': h.snapshot = replace(h.snapshot, fact_sha256='f' * 64)
    elif change == 'wrong_reference': h.command = replace(h.command, replacement=replace(h.command.replacement, revision=2))
    else:
        command = h.snapshot.command
        if change == 'wrong_date': command = replace(command, effective_at=command.effective_at+timedelta(days=1))
        else:
            from decimal import Decimal
            command = replace(command, after=replace(command.after, share_capital=Decimal(40000), nominal_value=Decimal(400)))
        context = rf.Rf1086VerifiedRegisterObservationContext(command.actor_id, True, command.company_id, command.income_year, command.documents, True)
        h.snapshot = rf.prepare_rf1086_register_observation(command, context=context,
            observation_id=h.snapshot.observation_id, confirmed_at=h.snapshot.confirmed_at)
        h.command = replace(h.command, replacement=replace(h.command.replacement, fact_sha256=h.snapshot.fact_sha256))
    with pytest.raises(gov.CorporateGovernanceError): h.run()
    assert not h.submitted and not any(e[0] == 'bytes' for e in h.events)


def test_shared_governance_and_rf_document_cannot_hide_contradictory_year_commitments():
    h = harness(overlap=True)
    command = h.snapshot.command
    command = replace(command, documents=tuple(replace(row, source_income_year=IncomeYear(2024)) for row in command.documents))
    context = rf.Rf1086VerifiedRegisterObservationContext(command.actor_id, True, command.company_id, command.income_year, command.documents, True)
    h.snapshot = rf.prepare_rf1086_register_observation(command, context=context,
        observation_id=h.snapshot.observation_id, confirmed_at=h.snapshot.confirmed_at)
    h.command = replace(h.command, replacement=replace(h.command.replacement, fact_sha256=h.snapshot.fact_sha256))
    with pytest.raises(gov.CorporateGovernanceError): h.run()
    assert not h.submitted


def test_missing_verifier_fails_closed_after_prepare_without_document_io():
    h = harness(verifier=False)
    with pytest.raises(gov.CorporateGovernanceError) as error: h.run()
    assert error.value.category is ErrorCategory.DEPENDENCY_UNAVAILABLE
    assert not h.submitted and not any(e[0] in ('rf_session','documents_session','bytes') for e in h.events)


@pytest.mark.parametrize('path', ['prepare_replay', 'append'])
def test_malformed_receipt_from_typed_persistence_is_unavailable_without_retry(path):
    h = harness()
    if path == 'prepare_replay': h.replay = {'verified': True}
    else: h.append_result = {'verified': True}
    with pytest.raises(gov.CorporateGovernanceError) as error: h.run()
    assert error.value.category is ErrorCategory.DEPENDENCY_UNAVAILABLE
    assert len(h.submitted) == (1 if path == 'append' else 0)
    assert [e[0] for e in h.events].count('prepare') == 1


def test_governance_metadata_is_verified_now_without_fabricating_original_time_metadata():
    h = harness()
    identity = h.gov_ids[0]
    h.records[identity] = replace(h.records[identity], name='Renamed before amendment.pdf')
    receipt = h.run()
    retained = next(row for row in receipt.originals if row.document_id.value == identity.value)
    assert retained.metadata_sha256 == docs.document_metadata_sha256(h.records[identity])
    assert receipt.anchor == h.anchor and retained.content_sha256 == h.records[identity].content_sha256
