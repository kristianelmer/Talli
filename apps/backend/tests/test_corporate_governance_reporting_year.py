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


def cash_lifecycle(registered=None, *, subscription_year=2026):
    """Synthetic explicit reference shared by all three owned capital phases."""
    from talli_backend.modules.corporate_governance.public import BankTransactionReference
    registered = registered or capital()
    bank_id = ref(BankTransactionReference)
    facts = dict(registered.event.canonical_facts)
    facts.setdefault('businessFacts', {'nominal_increase': {'amount':'30000.00','currency':'NOK'},
        'share_premium': {'amount':'500.00','currency':'NOK'}, 'issued_share_count':100})
    facts['bankFact'] = {'transaction_id': {'value':str(bank_id)},
        'transaction_date': f'{subscription_year}-05-01',
        'signed_amount': {'amount':'30500.00','currency':'NOK'}, 'source_sha256':'b'*64}
    registered = replace(registered, event=replace(registered.event, canonical_facts=facts), bank_transaction_id=bank_id)
    rows = []
    for phase in (SupportedCorporateEventPhase.BINDING_SUBSCRIPTION, SupportedCorporateEventPhase.RESTRICTED_PAYMENT):
        phase_facts = dict(facts)
        if phase is SupportedCorporateEventPhase.BINDING_SUBSCRIPTION:
            phase_facts['bankFact'] = None
        rows.append(replace(registered, event=replace(registered.event, event_id=ref(SupportedCorporateEventId),
            phase=phase, income_year=IncomeYear(subscription_year), event_date=LocalDate(date(subscription_year,5,1)),
            canonical_facts=phase_facts), accounting_entry_id=ref(AccountingEntryReference),
            bank_transaction_id=None if phase is SupportedCorporateEventPhase.BINDING_SUBSCRIPTION else bank_id))
    return (*rows, registered)


def test_completed_cash_lifecycle_reports_registration_and_retains_every_original():
    rows = cash_lifecycle()
    output = build(events=rows)
    assert len(output.supported_events) == 1
    evidence = output.supported_events[0]
    assert evidence.recorded == rows[2] and evidence.status == 'recorded'
    assert evidence.lifecycle_events == rows
    assert output.enumeration_sha256 == build(events=tuple(reversed(rows))).enumeration_sha256


@pytest.mark.parametrize('omitted', [0,1,2])
def test_registered_receipt_preserves_ledger_opening_anchors_without_inventing_governance_rows(omitted):
    rows = cash_lifecycle()
    output = build(events=tuple(row for index,row in enumerate(rows) if index != omitted))
    assert len(output.supported_events) == 1
    assert output.supported_events[0].status == ('incomplete' if omitted == 2 else 'recorded')
    assert len(output.supported_events[0].lifecycle_events) == 2


def test_subscription_reversal_blocks_the_entire_registered_lifecycle():
    rows = cash_lifecycle()
    output = build(events=rows, amendments=(amendment(rows[0].accounting_entry_id),))
    assert len(output.supported_events) == 1
    assert output.supported_events[0].status == 'reversed'
    assert output.supported_events[0].lifecycle_events == rows
    assert len(output.ledger_amendments) == 1


def test_cross_year_cash_anchors_are_retained_and_affect_registration_digest():
    rows = cash_lifecycle(subscription_year=2025)
    current = build(events=rows)
    assert current.supported_events[0].status == 'recorded'
    assert current.supported_events[0].lifecycle_events == rows
    assert {int(row.event.income_year) for row in current.supported_events[0].lifecycle_events} == {2025,2026}
    assert build(events=rows, year=2025).supported_events[0].status == 'incomplete'
    amended = build(events=rows, amendments=(amendment(rows[0].accounting_entry_id),))
    assert amended.supported_events[0].status == 'reversed'
    assert amended.enumeration_sha256 != current.enumeration_sha256


def test_identical_amounts_and_dates_do_not_correlate_different_references():
    rows = list(cash_lifecycle())
    rows[0] = replace(rows[0], event=replace(rows[0].event, event_reference=ref(SupportedCorporateEventReference)))
    output = build(events=tuple(rows))
    assert len(output.supported_events) == 2
    assert {item.status for item in output.supported_events} == {'incomplete', 'recorded'}
    assert sum(len(item.lifecycle_events) for item in output.supported_events) == 3


@pytest.mark.parametrize('problem', ['duplicate_phase','wrong_amount','wrong_count','wrong_date','wrong_record_time',
    'different_bank','different_bank_hash','missing_bank','reused_entry','different_policy','mixed_kind'])
def test_conflicting_cash_lifecycle_retains_all_originals_and_blocks(problem):
    rows = list(cash_lifecycle())
    payment = rows[1]
    if problem == 'duplicate_phase': rows.append(replace(payment,event=replace(payment.event,event_id=ref(SupportedCorporateEventId)),accounting_entry_id=ref(AccountingEntryReference)))
    if problem in {'wrong_amount','wrong_count'}:
        facts = dict(payment.event.canonical_facts);business=dict(facts['businessFacts'])
        business['issued_share_count' if problem == 'wrong_count' else 'nominal_increase'] = 101 if problem == 'wrong_count' else {'amount':'30001.00','currency':'NOK'}
        facts['businessFacts']=business;rows[1]=replace(payment,event=replace(payment.event,canonical_facts=facts))
    if problem == 'wrong_date': rows[1]=replace(payment,event=replace(payment.event,event_date=LocalDate(date(2026,6,1))))
    if problem == 'wrong_record_time': rows[1]=replace(payment,recorded_at=NOW.replace(year=2027))
    if problem == 'different_bank': rows[1]=replace(payment,bank_transaction_id=ref(type(payment.bank_transaction_id)))
    if problem == 'different_bank_hash':
        facts=dict(payment.event.canonical_facts);facts['bankFact']={**facts['bankFact'],'source_sha256':'c'*64}
        rows[1]=replace(payment,event=replace(payment.event,canonical_facts=facts))
    if problem == 'missing_bank': rows[1]=replace(payment,bank_transaction_id=None)
    if problem == 'reused_entry': rows[1]=replace(payment,accounting_entry_id=rows[0].accounting_entry_id)
    if problem == 'different_policy': rows[1]=replace(payment,event=replace(payment.event,policy_version='another-policy'))
    if problem == 'mixed_kind': rows[1]=replace(payment,event=replace(payment.event,event_kind=SupportedCorporateEventKind.BANK_LOAN))
    output = build(events=tuple(rows))
    assert len(output.supported_events) == 1
    assert output.supported_events[0].status == 'conflicting'
    assert {row.event.event_id for row in output.supported_events[0].lifecycle_events} == {row.event.event_id for row in rows}


def test_changed_subscription_evidence_changes_digest_without_overwriting_registration():
    rows = list(cash_lifecycle())
    before = build(events=tuple(rows))
    facts = dict(rows[0].event.canonical_facts)
    facts['documentFacts'] = [{'evidence_kind':'signed_decision','document_id':str(uuid4()),'content_sha256':'e'*64}]
    rows[0] = replace(rows[0], event=replace(rows[0].event,canonical_facts=facts,facts_sha256='e'*64))
    after = build(events=tuple(rows))
    assert after.enumeration_sha256 != before.enumeration_sha256
    assert after.supported_events[0].recorded == before.supported_events[0].recorded
    assert after.supported_events[0].lifecycle_events[0] == rows[0]


def test_cash_correction_with_another_reference_retains_both_groups_and_blocks():
    rows = cash_lifecycle()
    replacement = replace(capital(year=2027), correction_of_event_id=rows[0].event.event_id)
    output = build(events=(*rows,replacement))
    assert len(output.supported_events) == 2
    assert any(item.status == 'corrected' for item in output.supported_events)
    assert replacement in tuple(row for item in output.supported_events for row in item.lifecycle_events)


def test_lifecycle_receipt_list_is_immutable():
    from talli_backend.modules.corporate_governance.public import CorporateYearSupportedEvidence
    originals = list(cash_lifecycle())
    value = CorporateYearSupportedEvidence(originals[2], 'recorded', originals)
    originals.clear()
    assert len(value.lifecycle_events) == 3


def test_standalone_registered_cash_preserves_accepted_opening_position_path():
    # Ledger phase_basis_v1 also reads OpeningCapitalIncreaseComponent. A paid
    # opening supplies subscription/payment anchors without Governance rows.
    registered = capital()
    result = build(events=(registered,)).supported_events[0]
    assert result.status == 'recorded' and result.recorded == registered
    assert result.lifecycle_events == (registered,)


def test_standalone_reduction_first_recognition_is_unaffected():
    row = capital()
    row = replace(row, event=replace(row.event,
        event_kind=SupportedCorporateEventKind.LOSS_COVERAGE_CAPITAL_REDUCTION,
        phase=SupportedCorporateEventPhase.FIRST_RECOGNIZED_AFTER_REGISTRATION))
    item = build(events=(row,)).supported_events[0]
    assert item.status == 'recorded' and item.recorded == row


def test_identical_bank_facts_must_still_match_the_original_transaction_reference():
    rows = list(cash_lifecycle())
    for index in (1,2):
        facts = dict(rows[index].event.canonical_facts)
        facts['bankFact'] = {**facts['bankFact'], 'transaction_id': {'value':'unrelated-bank-source'}}
        rows[index] = replace(rows[index],event=replace(rows[index].event,canonical_facts=facts))
    result = build(events=tuple(rows)).supported_events[0]
    assert result.status == 'conflicting' and result.lifecycle_events == tuple(rows)


def test_real_governance_canonical_commands_form_the_completed_cash_projection():
    from test_corporate_governance_supported_events import (
        command, capital_facts, document, bank, source,
    )
    from talli_backend.modules.corporate_governance.public import SupportedCorporateEvidenceKind
    from talli_backend.modules.corporate_governance.service import CorporateGovernanceService
    documents = tuple(document(kind, index+1) for index,kind in enumerate((
        SupportedCorporateEvidenceKind.SIGNED_DECISION,
        SupportedCorporateEvidenceKind.CONTRIBUTION_CONFIRMATION,
        SupportedCorporateEvidenceKind.AMENDED_ARTICLES,
        SupportedCorporateEvidenceKind.REGISTRATION_RECEIPT)))
    rows = []
    for phase in (SupportedCorporateEventPhase.BINDING_SUBSCRIPTION,
                  SupportedCorporateEventPhase.RESTRICTED_PAYMENT,
                  SupportedCorporateEventPhase.REGISTERED):
        request = command(kind=SupportedCorporateEventKind.CASH_CAPITAL_INCREASE,
            phase=phase, facts=capital_facts(), documents=documents,
            bank_fact=None if phase is SupportedCorporateEventPhase.BINDING_SUBSCRIPTION else bank('15000'),
            shareholder_register_fact=source() if phase is SupportedCorporateEventPhase.REGISTERED else None)
        request = replace(request, company_id=COMPANY,event_id=ref(SupportedCorporateEventId))
        event = CorporateGovernanceService().prepare_supported_event(request)
        rows.append(RecordedSupportedCorporateEvent(event,ref(AccountingEntryReference),
            request.bank_fact.transaction_id if request.bank_fact else None,None,NOW,False))
    result = build(events=tuple(rows)).supported_events[0]
    assert result.recorded == rows[2] and result.status == 'recorded'
    assert result.lifecycle_events == tuple(rows)


@pytest.mark.parametrize('amount', ['NaN','Infinity','not-a-number'])
def test_malformed_cash_economics_fail_closed(amount):
    rows = list(cash_lifecycle())
    facts = dict(rows[0].event.canonical_facts);business=dict(facts['businessFacts'])
    business['nominal_increase'] = {'amount':amount,'currency':'NOK'};facts['businessFacts']=business
    rows[0]=replace(rows[0],event=replace(rows[0].event,canonical_facts=facts))
    with pytest.raises(CorporateGovernanceError): build(events=tuple(rows))


@pytest.mark.parametrize('predecessor', [0,1])
@pytest.mark.parametrize('problem', ['changed_amount','later_date','amended'])
def test_available_predecessor_is_never_ignored_because_other_anchor_can_be_opening(predecessor, problem):
    all_rows = cash_lifecycle()
    row = all_rows[predecessor]
    amendments = ()
    if problem == 'changed_amount':
        facts = dict(row.event.canonical_facts);business=dict(facts['businessFacts'])
        business['share_premium'] = {'amount':'501.00','currency':'NOK'};facts['businessFacts']=business
        row=replace(row,event=replace(row.event,canonical_facts=facts))
    if problem == 'later_date': row=replace(row,event=replace(row.event,event_date=LocalDate(date(2026,6,1))))
    if problem == 'amended': amendments=(amendment(row.accounting_entry_id),)
    result = build(events=(row,all_rows[2]),amendments=amendments).supported_events[0]
    assert result.status == ('reversed' if problem == 'amended' else 'conflicting')
    assert result.lifecycle_events == (row,all_rows[2])
