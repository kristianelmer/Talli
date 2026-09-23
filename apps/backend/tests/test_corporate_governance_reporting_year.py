"""Public reporting evidence contracts; no provider or database calls."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from talli_backend.modules.corporate_governance.public import (
    AccountingEntryReference, CanonicalSupportedCorporateEvent, CorporateDecisionId,
    CorporateDecisionKind, CorporateDecisionRecord, CorporateDocumentSetId,
    CorporateEventId, CorporateEventRecord, CorporateFinalizationId, CorporateFinalizationRecord,
    CorporateGovernanceError, CorporateLedgerAmendment, CorporateLifecycleSnapshot,
    CorporateReportingYearBasis, CorporateSourceReference, RecordedSupportedCorporateEvent,
    SupportedCorporateEventId, SupportedCorporateEventKind, SupportedCorporateEventPhase,
    SupportedCorporateEventReference, build_reporting_year_evidence,
)
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, CorrelationId, IncomeYear, LocalDate, UserId

NOW = datetime(2026, 9, 23, tzinfo=UTC)
COMPANY = CompanyId(str(uuid4()))
ACTOR = ActorId(ActorKind.USER, UserId(str(uuid4())))
def ref(cls): return cls(str(uuid4()))
def lifecycle(decisions=(), events=(), finals=()): return CorporateLifecycleSnapshot(decisions, (), (), events, finals)
def decision(day='2026-05-01'):
    return CorporateDecisionRecord(ref(CorporateDecisionId), ref(CorporateDocumentSetId), COMPANY,
        IncomeYear(2025), CorporateDecisionKind.OWNER_DIVIDEND, ref(CorporateSourceReference), 'a'*64,
        {'generalMeeting': {'meetingDate': day}, 'dividend': {'paymentDate': '2027-02-01'}},
        'b'*64, None, str(ACTOR.subject), NOW)
def capital(year=2026):
    event = CanonicalSupportedCorporateEvent(ref(SupportedCorporateEventId), ref(SupportedCorporateEventReference),
        COMPANY, IncomeYear(year), LocalDate(date(year, 5, 1)), SupportedCorporateEventKind.CASH_CAPITAL_INCREASE,
        SupportedCorporateEventPhase.REGISTERED, 'corporate-governance-supported-events-2026.1',
        {'documentFacts': [{'evidence_kind':'signed_resolution','document_id':str(uuid4()),'content_sha256':'c'*64}]}, 'd'*64)
    return RecordedSupportedCorporateEvent(event, ref(AccountingEntryReference), None, None, NOW, False)
def build(life=None, events=(), amendments=(), year=2026):
    return build_reporting_year_evidence(basis=CorporateReportingYearBasis(COMPANY, life or lifecycle(), events),
        income_year=IncomeYear(year), amendments=amendments)
def amendment(entry, replacement=None):
    return CorporateLedgerAmendment(entry, ref(AccountingEntryReference), replacement, COMPANY, IncomeYear(2026),
        'Original owner correction', ACTOR, NOW)


def test_dividend_uses_general_meeting_year_not_accounting_payment_or_record_time():
    row = decision()
    output = build(lifecycle((row,)))
    assert output.dividends[0].reporting_date == LocalDate(date(2026, 5, 1))
    assert output.dividends[0].decision.income_year == IncomeYear(2025)
    assert not build(lifecycle((row,)), year=2025).dividends
    assert not build(lifecycle((row,)), year=2027).dividends


def test_empty_complete_enumeration_is_stable_and_added_event_changes_digest():
    assert build().enumeration_sha256 == build().enumeration_sha256
    assert build(events=(capital(),)).enumeration_sha256 != build().enumeration_sha256


def test_reversal_and_replacement_chain_retained_and_changes_digest():
    row = capital(); replacement = ref(AccountingEntryReference)
    first = amendment(row.accounting_entry_id, replacement); second = amendment(replacement)
    before = build(events=(row,)); after = build(events=(row,), amendments=(second, first))
    assert after.supported_events[0].status == 'corrected'
    assert len(after.ledger_amendments) == 2 and after.enumeration_sha256 != before.enumeration_sha256
    assert after.enumeration_sha256 == build(events=(row,), amendments=(first, second)).enumeration_sha256
    assert build(events=(row,), amendments=(amendment(row.accounting_entry_id),)).supported_events[0].status == 'reversed'


def test_unrelated_amendment_does_not_change_selected_year_evidence():
    row = capital()
    assert build(events=(row,)).enumeration_sha256 == build(events=(row,), amendments=(amendment(ref(AccountingEntryReference)),)).enumeration_sha256


def test_signed_finalization_and_rejection_preserve_exact_receipts_and_state():
    row = decision(); entry = ref(AccountingEntryReference)
    final = CorporateFinalizationRecord(ref(CorporateFinalizationId), COMPANY, IncomeYear(2025), row.decision_id,
        'owner_dividend', None, entry, None, row.decision_hash, {'minutes':'e'*64}, None, str(ACTOR.subject), NOW)
    before = build(lifecycle((row,), finals=(final,)))
    assert before.dividends[0].status == 'finalized'
    assert before.dividends[0].finalizations[0].signed_artifact_hashes['minutes'] == 'e'*64
    rejected = CorporateEventRecord(ref(CorporateEventId), COMPANY, IncomeYear(2025), row.decision_id,
        row.document_set_id, None, 'rejected', str(ACTOR.subject), NOW, NOW, row.decision_hash, None, {}, 'original-event')
    after = build(lifecycle((row,), (rejected,), (final,)))
    assert after.dividends[0].status == 'rejected' and after.enumeration_sha256 != before.enumeration_sha256


def test_superseding_decision_from_another_year_is_retained():
    original = decision(); correction = replace(decision('2027-01-01'), supersedes_decision_id=original.decision_id)
    output = build(lifecycle((correction, original)))
    assert {row.reporting_date.value.year for row in output.dividends} == {2026, 2027}
    assert next(row for row in output.dividends if row.decision == original).status == 'superseded'


@pytest.mark.parametrize('problem', ['cross_company','duplicate','missing_date','bad_date','amendment_cycle','decision_cycle','dangling_correction'])
def test_inconsistent_owner_projection_fails_closed(problem):
    row = decision(); cap = capital(); life = lifecycle((row,)); events=(cap,); amendments=()
    if problem == 'cross_company': life = lifecycle((replace(row, company_id=CompanyId(str(uuid4()))),))
    if problem == 'duplicate': events=(cap,cap)
    if problem == 'missing_date': life=lifecycle((replace(row, canonical_input={}),))
    if problem == 'bad_date': life=lifecycle((replace(row, canonical_input={'generalMeeting':{'meetingDate':'not-a-date'}}),))
    if problem == 'amendment_cycle':
        replacement=ref(AccountingEntryReference)
        amendments=(amendment(cap.accounting_entry_id,replacement),amendment(replacement,cap.accounting_entry_id))
    if problem == 'decision_cycle': life=lifecycle((replace(row,supersedes_decision_id=row.decision_id),))
    if problem == 'dangling_correction': events=(replace(cap, correction_of_event_id=ref(SupportedCorporateEventId)),)
    with pytest.raises(CorporateGovernanceError): build(life, events, amendments)


def test_input_lists_and_nested_maps_cannot_mutate_retained_evidence():
    source = [decision()]; basis = CorporateReportingYearBasis(COMPANY,lifecycle(source),[])
    source.clear()
    output=build_reporting_year_evidence(basis=basis,income_year=IncomeYear(2026),amendments=())
    assert len(output.dividends)==1
    with pytest.raises(TypeError): output.dividends[0].decision.canonical_input['generalMeeting']['meetingDate']='2027-01-01'


def test_application_composes_all_owner_reads_in_the_same_transaction():
    from talli_backend.application.corporate_governance_workflow import CorporateGovernanceApplication
    from talli_backend.modules.ledger.public import LedgerEntryAmendment, LedgerEntryId
    from talli_backend.shared.kernel import Timestamp
    cap=capital(); active=False; calls=[]
    class Transaction:
        async def read_reporting_year_basis(self, company_id):
            assert active and company_id==COMPANY
            calls.append('governance')
            return CorporateReportingYearBasis(COMPANY,lifecycle(),(cap,))
        async def list_entry_amendments(self, **kwargs):
            assert active and kwargs['actor_id']==ACTOR and kwargs['company_id']==COMPANY
            calls.append('ledger')
            return (LedgerEntryAmendment(LedgerEntryId(str(cap.accounting_entry_id)),ref(LedgerEntryId),None,
                COMPANY,IncomeYear(2026),'retained reversal',ACTOR,Timestamp(NOW)),)
    tx=Transaction()
    class Session:
        actor_id=ACTOR
        @asynccontextmanager
        async def transaction(self):
            nonlocal active
            active=True
            try: yield tx
            finally: active=False
    class Factory:
        async def session(self, token): return Session()
    app=CorporateGovernanceApplication(Factory(),None,lambda transaction:transaction)
    result=asyncio.run(app.read_reporting_year_evidence('verified',company_id=COMPANY,income_year=IncomeYear(2026),correlation_id=CorrelationId('test-year-read')))
    assert calls==['governance','ledger'] and not active
    assert result.supported_events[0].status=='reversed'


def test_ledger_amendment_adapter_requires_matching_actor_before_any_database_read():
    from test_supabase_corporate_governance import bound_transaction
    from talli_backend.modules.ledger.public import LedgerError
    tx = bound_transaction()
    async def forbidden(*args): raise AssertionError('no query permitted')
    tx._database_rows = forbidden
    with pytest.raises(LedgerError):
        asyncio.run(tx.list_entry_amendments(actor_id=ACTOR,company_id=COMPANY,correlation_id=CorrelationId('amendment-denial')))


def test_ledger_amendment_adapter_retains_exact_receipt_and_rejects_wrong_company():
    from test_supabase_corporate_governance import bound_transaction
    from talli_backend.modules.ledger.public import LedgerError
    tx = bound_transaction(); original, reversal, replacement = [str(uuid4()) for _ in range(3)]
    row = {'original_entry_id': original,'reversal_entry_id': reversal,'replacement_entry_id': replacement,
        'company_id': str(COMPANY),'income_year': 2026,'reason':'Original historical reason',
        'amended_by':str(tx.actor_id.subject),'amended_at':NOW}
    calls=[]
    async def rows(query,parameters):
        calls.append((query,parameters));return [row]
    tx._database_rows=rows
    result=asyncio.run(tx.list_entry_amendments(actor_id=tx.actor_id,company_id=COMPANY,correlation_id=CorrelationId('amendment-read')))
    assert str(result[0].replacement_entry_id)==replacement and result[0].reason==row['reason']
    assert calls[0][0]=='select * from ledger.list_entry_amendments_v1(%s::uuid,%s::text)'
    assert calls[0][1]==(str(COMPANY),str(tx.actor_id.subject))
    row['company_id']=str(uuid4())
    with pytest.raises(LedgerError):asyncio.run(tx.list_entry_amendments(actor_id=tx.actor_id,company_id=COMPANY,correlation_id=CorrelationId('amendment-read')))
