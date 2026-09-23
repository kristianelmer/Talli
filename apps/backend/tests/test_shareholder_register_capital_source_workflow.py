"""Capital capture binds owner evidence to independently retained RF observations."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from talli_backend.modules.corporate_governance.public import (
    CanonicalSupportedCorporateEvent,CorporateYearSupportedEvidence,RecordedSupportedCorporateEvent,
    SupportedCorporateEventId,SupportedCorporateEventReference,SupportedCorporateEventKind,
    SupportedCorporateEventPhase,AccountingEntryReference,
)
from talli_backend.modules.documents.public import DocumentStatus,document_metadata_sha256
from talli_backend.modules.shareholder_register_filing.public import (
    RecordRf1086RegisterObservation,Rf1086RegisterDocumentEvidence,Rf1086YearSourceError,
    Rf1086RegisterObservationError,rf1086_event_register_states,rf1086_year_source_digest,
    Rf1086VerifiedRegisterObservationContext,prepare_rf1086_register_observation,
    Rf1086CashNominalIncreaseEvent,Rf1086NominalIncreaseAllocation,assess_rf1086_readiness,
)
from talli_backend.shared.kernel import IncomeYear,LocalDate,IdempotencyKey,CorrelationId
from test_shareholder_register_source_workflow import Harness
from test_rf1086_year_source import COMPANY,ACTOR,YEAR,NOW,DOCUMENT,RECEIPT


def setup(kind='cash_issue'):
    h=Harness('cash_issue')
    if kind=='loss_covering_reduction':
        from talli_backend.modules.shareholder_register_filing.public import Rf1086LossCoveringReductionEvent
        case=h.command.case
        event=Rf1086LossCoveringReductionEvent(type='loss_covering_reduction',timestamp=case.events[0].timestamp,
            registration_confirmed=True,capital_reduction=Decimal(30000),nominal_value_reduction=Decimal(300),
            nominal_value_after=Decimal(300),fund_issued_capital_before=0)
        shares=replace(case.share_snapshot,previous_share_capital=60000,previous_nominal_value=600,
            previous_paid_in_share_capital=60000,current_share_capital=30000,current_paid_in_share_capital=60000,
            current_share_count=100,current_paid_in_premium=2000)
        case=replace(case,events=(event,),share_snapshot=shares,
            shareholder_snapshots=tuple(replace(row,current_share_count=100) for row in case.shareholder_snapshots))
        h.command=replace(h.command,case=case,paid_in=replace(h.command.paid_in,opening_capital=Decimal(60000),
            closing_capital=Decimal(60000),closing_premium=Decimal(2000)),
            event_evidence=(replace(h.command.event_evidence[0],event_sha256=rf1086_year_source_digest(event)),))
    h.record=replace(h.record,document_type='corporate_document',linked_to='workspace',status=DocumentStatus.ATTACHED,
                     created_at=NOW-timedelta(days=2))
    year_doc=replace(h.command.documents[0],document_type=h.record.document_type,integrity_status=h.record.status.value,
        created_at=h.record.created_at,metadata_sha256=document_metadata_sha256(h.record))
    h.command=replace(h.command,documents=(year_doc,))
    docs=tuple(Rf1086RegisterDocumentEvidence(document_id=DOCUMENT,company_id=COMPANY,
        content_version_sha256=year_doc.content_sha256,content_sha256=year_doc.content_sha256,
        byte_length=year_doc.byte_length,document_type=year_doc.document_type,integrity_status=year_doc.integrity_status,
        created_at=year_doc.created_at,metadata_sha256=year_doc.metadata_sha256,role=role,source_income_year=h.record.income_year)
        for role in ('register_before','register_after','registration'))
    before,after=rf1086_event_register_states(h.command.case,0)
    h.register_command=RecordRf1086RegisterObservation(COMPANY,ACTOR,YEAR,h.command.case.events[0].timestamp,
        kind,before,after,docs,True,True,True)
    return h


def capture_register(h):
    return asyncio.run(h.workflow.capture_register_observation('owner-token',h.register_command,
        idempotency_key=IdempotencyKey('independent-observation'),correlation_id=CorrelationId('independent-observation')))


def prepare_capital(h):
    h.observation=capture_register(h);event=h.command.case.events[0]
    money=lambda value:{'amount':str(value),'currency':'NOK'}
    business=({'nominal_increase':money(30000),'share_premium':money(500),'issued_share_count':100}
        if event.type=='cash_issue' else {'nominal_reduction':money(30000),'old_share_capital':money(60000),'new_share_capital':money(30000)})
    facts={'businessFacts':business,'documentFacts':[{'document_id':{'value':DOCUMENT},'evidence_kind':kind,
        'content_sha256':h.record.content_sha256,'revision':3} for kind in ('signed_decision','amended_articles','registration_receipt')],
        'shareholderRegisterFact':{'record_id':{'value':h.observation.observation_id.value},
            'revision':h.observation.version,'fact_sha256':h.observation.fact_sha256}}
    original=CanonicalSupportedCorporateEvent(SupportedCorporateEventId(RECEIPT),SupportedCorporateEventReference(str(uuid4())),
        COMPANY,YEAR,LocalDate(event.timestamp.date()),
        SupportedCorporateEventKind.CASH_CAPITAL_INCREASE if event.type=='cash_issue' else SupportedCorporateEventKind.LOSS_COVERAGE_CAPITAL_REDUCTION,
        SupportedCorporateEventPhase.REGISTERED,'corporate-governance-supported-events-2026.1',facts,'f'*64)
    recorded=RecordedSupportedCorporateEvent(original,AccountingEntryReference(str(uuid4())),None,None,NOW,False)
    h.view=replace(h.view,supported_events=(CorporateYearSupportedEvidence(recorded,'recorded'),))


def test_register_capture_verifies_original_once_and_retains_actual_prior_document_year():
    h=setup();snapshot=capture_register(h)
    assert h.calls.count('verify_document')==1
    assert {d.source_income_year for d in snapshot.command.documents}=={IncomeYear(2024)}
    assert snapshot.command==replace(h.register_command,documents=tuple(sorted(h.register_command.documents,key=lambda row:(row.document_id,row.role))))
    assert h.register_saved==[snapshot]


@pytest.mark.parametrize('change',['generated','governance_link','filing_output','metadata_changed','reviewer','wrong_actor','unconfirmed'])
def test_register_capture_rejects_unverified_or_nonindependent_originals(change):
    h=setup()
    if change=='generated':h.record=replace(h.record,status=DocumentStatus.GENERATED_UNSIGNED)
    if change=='governance_link':h.record=replace(h.record,linked_to='corporate_decision:'+str(uuid4()))
    if change=='filing_output':h.record=replace(h.record,document_type='authority_feedback')
    if change=='metadata_changed':h.record=replace(h.record,name='Changed original')
    if change=='reviewer':h.company.role='reviewer'
    if change=='wrong_actor':h.register_command=replace(h.register_command,actor_id=replace(ACTOR,subject=type(ACTOR.subject)(str(uuid4()))))
    if change=='unconfirmed':h.register_command=replace(h.register_command,complete_register_confirmed=False)
    with pytest.raises((Rf1086YearSourceError,Rf1086RegisterObservationError)):capture_register(h)
    assert not h.register_saved


@pytest.mark.parametrize('kind',['cash_issue','loss_covering_reduction'])
def test_capital_capture_uses_current_original_observation_and_complete_governance_economics(kind):
    h=setup(kind);prepare_capital(h);snapshot=h.capture();receipt=snapshot.governance_receipts[0]
    assert receipt.receipt_id==RECEIPT and receipt.register_observation_id==h.observation.observation_id.value
    assert receipt.register_observation_sha256==h.observation.fact_sha256
    assert receipt.finalization_sha256==h.view.supported_events[0].recorded.finalization_sha256


@pytest.mark.parametrize('change',['missing','wrong_hash','wrong_revision','different_before','changed_doc','reversed','corrected','pending','wrong_economics','malformed_economics','missing_document','wrong_date'])
def test_capital_observation_and_governance_mismatch_prevent_source_capture(change):
    h=setup();prepare_capital(h);item=h.view.supported_events[0];original=item.recorded.event;facts=dict(original.canonical_facts)
    if change=='missing':h.observation=None
    if change in {'wrong_hash','wrong_revision'}:
        reference=dict(facts['shareholderRegisterFact']);reference['fact_sha256' if change=='wrong_hash' else 'revision']='0'*64 if change=='wrong_hash' else 9
        facts['shareholderRegisterFact']=reference
    if change=='different_before':h.observation=replace(h.observation,command=replace(h.observation.command,before=h.observation.command.after))
    if change=='changed_doc':
        h.record=replace(h.record,name='Changed after independent capture')
        h.command=replace(h.command,documents=(replace(h.command.documents[0],metadata_sha256=document_metadata_sha256(h.record)),))
    if change in {'reversed','corrected'}:item=replace(item,status=change)
    if change=='pending':original=replace(original,phase=SupportedCorporateEventPhase.BINDING_SUBSCRIPTION)
    if change=='wrong_economics':facts['businessFacts']={**facts['businessFacts'],'share_premium':{'currency':'NOK','amount':'999'}}
    if change=='malformed_economics':facts['businessFacts']={}
    if change=='missing_document':facts['documentFacts']=[{**facts['documentFacts'][0],'document_id':{'value':str(uuid4())}}]
    if change=='wrong_date':original=replace(original,event_date=LocalDate(original.event_date.value+timedelta(days=1)))
    h.view=replace(h.view,supported_events=(replace(item,recorded=replace(item.recorded,event=replace(original,canonical_facts=facts))),))
    with pytest.raises((Rf1086YearSourceError,Rf1086RegisterObservationError)):h.capture()
    assert not h.saved


def test_valid_observation_for_different_holder_identity_cannot_prove_source_register():
    h=setup();prepare_capital(h);old=h.observation
    command=replace(old.command,before=replace(old.command.before,holdings=tuple(replace(row,name='Another registered name') for row in old.command.before.holdings)),
        after=replace(old.command.after,holdings=tuple(replace(row,name='Another registered name') for row in old.command.after.holdings)))
    h.observation=prepare_rf1086_register_observation(command,context=Rf1086VerifiedRegisterObservationContext(ACTOR,True,COMPANY,YEAR,command.documents,True),
        observation_id=old.observation_id,confirmed_at=old.confirmed_at)
    item=h.view.supported_events[0];facts=dict(item.recorded.event.canonical_facts)
    facts['shareholderRegisterFact']={**facts['shareholderRegisterFact'],'fact_sha256':h.observation.fact_sha256}
    h.view=replace(h.view,supported_events=(replace(item,recorded=replace(item.recorded,event=replace(item.recorded.event,canonical_facts=facts))),))
    with pytest.raises(Rf1086RegisterObservationError,match='economic_binding_mismatch'):h.capture()
    assert not h.saved


def test_no_activity_cannot_omit_a_recorded_capital_occurrence():
    capital=setup();prepare_capital(capital);h=Harness();h.view=capital.view
    with pytest.raises(Rf1086YearSourceError,match='governance_events_omitted'):h.capture()
    assert not h.saved


def test_observation_capture_does_not_accept_caller_supplied_trust():
    h=setup()
    with pytest.raises(TypeError):asyncio.run(h.workflow.capture_register_observation('owner-token',h.register_command,
        idempotency_key=IdempotencyKey('forged-context-register'),correlation_id=CorrelationId('forged-context'),context=object()))
    assert not h.register_saved


def test_independent_observation_must_exist_before_governance_finalization():
    h=setup();prepare_capital(h);item=h.view.supported_events[0]
    h.view=replace(h.view,supported_events=(replace(item,recorded=replace(item.recorded,
        recorded_at=h.observation.confirmed_at-timedelta(seconds=1))),))
    with pytest.raises(Rf1086YearSourceError,match='register_postdates_governance'):h.capture()
    assert not h.saved


def test_cash_nominal_waits_for_an_authoritative_governance_variant():
    h=Harness('cash_issue');case=h.command.case
    event=Rf1086CashNominalIncreaseEvent(timestamp=case.events[0].timestamp,capital_increase=30000,
        nominal_value_increase=300,nominal_value_after=600,registration_confirmed=True,premium=500,
        allocations=(Rf1086NominalIncreaseAllocation('owner',100,30000,500),))
    case=replace(case,events=(event,),share_snapshot=replace(case.share_snapshot,current_share_count=100,current_nominal_value=600),
        shareholder_snapshots=tuple(replace(row,current_share_count=100) for row in case.shareholder_snapshots))
    assert assess_rf1086_readiness(case).is_ready
    h.command=replace(h.command,case=case,event_evidence=(replace(h.command.event_evidence[0],event_sha256=rf1086_year_source_digest(event)),))
    with pytest.raises(Rf1086YearSourceError,match='governance_nominal_increase_unavailable'):h.capture()
    assert not h.saved


def completed_capital_lifecycle(h):
    from talli_backend.modules.corporate_governance.public import CorporateReportingYearBasis
    from test_corporate_governance_reporting_year import lifecycle, cash_lifecycle
    return CorporateReportingYearBasis(COMPANY,lifecycle(),
        cash_lifecycle(h.view.supported_events[0].recorded,subscription_year=int(YEAR)))


def test_completed_capital_lifecycle_can_capture_and_preview_with_verified_sources():
    from talli_backend.modules.corporate_governance.public import build_reporting_year_evidence
    from test_shareholder_register_source_preview_workflow import preview
    h=setup();prepare_capital(h)
    h.view=build_reporting_year_evidence(basis=completed_capital_lifecycle(h),income_year=YEAR,amendments=())
    source=h.capture()
    assert len(source.governance_receipts)==1
    assert source.governance_receipts[0].receipt_id==RECEIPT
    result=preview(h)
    assert result.source_id==source.source_id
    assert result.source_sha256==source.source_sha256
    assert result.hovedskjema_xml


@pytest.mark.parametrize('omitted_phase',[
    SupportedCorporateEventPhase.BINDING_SUBSCRIPTION,
    SupportedCorporateEventPhase.RESTRICTED_PAYMENT,
])
def test_registered_capital_retains_authority_with_available_predecessor_phases(omitted_phase):
    from talli_backend.modules.corporate_governance.public import build_reporting_year_evidence
    from test_shareholder_register_source_preview_workflow import preview
    h=setup();prepare_capital(h);basis=completed_capital_lifecycle(h)
    basis=replace(basis,supported_events=tuple(item for item in basis.supported_events
        if item.event.phase!=omitted_phase))
    h.view=build_reporting_year_evidence(basis=basis,income_year=YEAR,amendments=())
    source=h.capture()
    assert len(source.governance_receipts)==1
    assert source.governance_receipts[0].receipt_id==RECEIPT
    assert len(h.view.supported_events[0].lifecycle_events)==2
    assert preview(h).source_id==source.source_id


def test_capital_without_registration_still_blocks_source_capture():
    from talli_backend.modules.corporate_governance.public import build_reporting_year_evidence
    h=setup();prepare_capital(h);basis=completed_capital_lifecycle(h)
    basis=replace(basis,supported_events=tuple(item for item in basis.supported_events
        if item.event.phase!=SupportedCorporateEventPhase.REGISTERED))
    h.view=build_reporting_year_evidence(basis=basis,income_year=YEAR,amendments=())
    with pytest.raises(Rf1086YearSourceError,match='governance_unresolved'):
        h.capture()
    assert not h.saved


def test_changed_earlier_capital_phase_invalidates_captured_source_preview():
    from talli_backend.modules.corporate_governance.public import build_reporting_year_evidence
    from test_shareholder_register_source_preview_workflow import preview
    h=setup();prepare_capital(h);basis=completed_capital_lifecycle(h)
    h.view=build_reporting_year_evidence(basis=basis,income_year=YEAR,amendments=())
    h.capture()
    original=basis.supported_events[0]
    changed=replace(original,recorded_at=original.recorded_at-timedelta(seconds=1))
    basis=replace(basis,supported_events=(changed,*basis.supported_events[1:]))
    h.view=build_reporting_year_evidence(basis=basis,income_year=YEAR,amendments=())
    with pytest.raises(Rf1086YearSourceError,match='source_changed'):
        preview(h)
    assert not h.previews
