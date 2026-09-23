"""Trusted owner composition and fail-closed source capture, without providers."""
import asyncio
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
import json
from types import SimpleNamespace
from uuid import UUID,uuid4

import pytest
from talli_backend.application.shareholder_register_source_workflow import ShareholderRegisterSourceWorkflow
from talli_backend.modules.corporate_governance.public import (
    AccountingEntryReference,CorporateArtifactId,CorporateArtifactKind,CorporateArtifactRecord,
    CorporateArtifactVariant,CorporateDecisionId,CorporateDecisionKind,CorporateDecisionRecord,
    CorporateDocumentSetId,CorporateFinalizationId,CorporateFinalizationRecord,CorporateGovernanceYearEvidence,
    CorporateSourceReference,CorporateYearDividendEvidence,CorporateLedgerAmendment,DocumentReference,
)
from talli_backend.modules.documents.public import DocumentId,DocumentRecord,DocumentStatus,DocumentsError,VerifiedDocumentEvidence
from talli_backend.modules.shareholder_register_filing.public import (
    Rf1086PaidInSourceFacts,Rf1086YearDocumentEvidence,Rf1086YearEventEvidence,Rf1086YearSourceError,
    Rf1086YearSourceId,parse_rf1086_case,prepare_rf1086_year_source,rf1086_year_source_digest,
    Rf1086RegisterObservationId,prepare_rf1086_register_observation,
)
from talli_backend.shared.kernel import CompanyId,CorrelationId,IdempotencyKey,IncomeYear,LocalDate
from test_rf1086_year_source import basis,ACTOR,COMPANY,YEAR,NOW,DOCUMENT,RECEIPT,ROOT


def ref(kind):return kind(str(uuid4()))


def prepared(kind='no_activity'):
    command,_=basis('dividend' if kind=='dividend' else 'cash_issue' if kind=='cash_issue' else 'no_activity')
    if kind in {'formation','transfer'}:
        name='stiftelse.json' if kind=='formation' else 'share_sale.json'
        case=parse_rf1086_case(json.loads((ROOT/'tests/fixtures/rf1086'/name).read_text()))
        shares=case.share_snapshot
        command=replace(command,case=case,paid_in=Rf1086PaidInSourceFacts(shares.previous_paid_in_share_capital,
            shares.current_paid_in_share_capital,shares.previous_paid_in_premium,shares.current_paid_in_premium),
            no_activity_confirmed=False,event_evidence=tuple(Rf1086YearEventEvidence(i,rf1086_year_source_digest(event),(DOCUMENT,)) for i,event in enumerate(case.events)))
    record=DocumentRecord(DocumentId(DOCUMENT),COMPANY,IncomeYear(2024),'signed_source','Original signed source.pdf',
        'source-register',DocumentStatus.SIGNED_OWNER_ATTESTED,10,'private/opaque/object','application/pdf',123,'a'*64,ACTOR,NOW,None,None)
    doc=Rf1086YearDocumentEvidence(document_id=DOCUMENT,company_id=COMPANY,content_version_sha256='a'*64,content_sha256='a'*64,
        document_type=record.document_type,integrity_status=record.status.value,byte_length=record.byte_length,
        created_at=record.created_at,metadata_sha256=rf1086_year_source_digest(record),source_income_year=record.income_year)
    return replace(command,documents=(doc,)),record


def dividend_view(command,record):
    event=command.case.events[0];decision_id=ref(CorporateDecisionId);set_id=ref(CorporateDocumentSetId)
    decision=CorporateDecisionRecord(decision_id,set_id,COMPANY,IncomeYear(2024),CorporateDecisionKind.OWNER_DIVIDEND,
        ref(CorporateSourceReference),'b'*64,{'generalMeeting':{'meetingDate':event.timestamp.date().isoformat()},
            'shareholders':[{'shareholderId':row.shareholder_id,'shareCount':row.share_count_basis} for row in event.allocations],
            'dividend':{'amountOre':int(Decimal(str(event.total_amount))*100),
                'allocations':[{'shareholderId':row.shareholder_id,'amountOre':int(Decimal(str(row.amount))*100)} for row in event.allocations]}},
        'c'*64,None,str(ACTOR.subject),NOW)
    kinds=(CorporateArtifactKind.DIVIDEND_BOARD_PROPOSAL,CorporateArtifactKind.DIVIDEND_GENERAL_MEETING_MINUTES)
    artifacts=tuple(CorporateArtifactRecord(ref(CorporateArtifactId),COMPANY,IncomeYear(2024),set_id,kind,
        CorporateArtifactVariant.SIGNED_OWNER_ATTESTED,DocumentReference(DOCUMENT),'a'*64,123,None,str(ACTOR.subject),NOW) for kind in kinds)
    final=CorporateFinalizationRecord(CorporateFinalizationId(RECEIPT),COMPANY,IncomeYear(2024),decision_id,
        'owner_dividend',None,ref(AccountingEntryReference),None,decision.decision_hash,
        {kind.value:'a'*64 for kind in kinds},None,str(ACTOR.subject),NOW)
    item=CorporateYearDividendEvidence(decision,LocalDate(event.timestamp.date()),'finalized',(),artifacts,(),(final,))
    return CorporateGovernanceYearEvidence(COMPANY,YEAR,(item,),(),(),'d'*64)


class Harness:
    def __init__(self,kind='no_activity'):
        self.command,self.record=prepared(kind);self.actor=ACTOR;self.document_actor=ACTOR;self.calls=[];self.saved=[];self.context=None
        case=self.command.case.company
        self.company=SimpleNamespace(id=str(COMPANY),role='owner',entity_type='AS',identity_confirmed_at=NOW.isoformat(),
            identity_locked_at=NOW.isoformat(),org_number=case.org_number,name=case.name,address=case.address,postal_code=case.postal_code,city=case.city)
        self.view=dividend_view(self.command,self.record) if kind=='dividend' else CorporateGovernanceYearEvidence(COMPANY,YEAR,(),(),(),'d'*64)
        self.document_failure=False;self.observation=None;self.register_saved=[]
        owner=self
        class RFSession:
            @property
            def actor_id(self):return owner.actor
            async def record_year_source(self,command,*,context,idempotency_key):
                owner.context=context
                result=prepare_rf1086_year_source(command,context=context,source_id=Rf1086YearSourceId(str(uuid4())),confirmed_at=NOW)
                owner.saved.append(result);owner.calls.append('persist');return result
            async def read_current_register_observation(self,query,observation_id):
                owner.calls.append('read_current_observation')
                assert query.company_id==COMPANY and query.actor_id==ACTOR and query.income_year==YEAR
                return owner.observation if owner.observation is not None and owner.observation.observation_id==observation_id else None
            async def record_register_observation(self,command,*,context,idempotency_key):
                result=prepare_rf1086_register_observation(command,context=context,
                    observation_id=Rf1086RegisterObservationId(str(uuid4())),confirmed_at=NOW-timedelta(seconds=1))
                owner.register_saved.append(result);return result
        class RFFactory:
            async def session(self,token):owner.calls.append('rf_auth');return RFSession()
        class CompanyAccess:
            async def company_record(self,token,*,company_id):owner.calls.append('company');return SimpleNamespace(company=owner.company)
        class Documents:
            @property
            def actor_id(self):return owner.document_actor
            async def verify_document_evidence(self,document_id):
                owner.calls.append('verify_document')
                if owner.document_failure:raise DocumentsError.integrity_failed()
                assert str(document_id)==DOCUMENT
                return VerifiedDocumentEvidence(owner.record,owner.record.content_sha256,owner.record.byte_length,owner.record.status)
        class DocumentsFactory:
            async def session(self,token):return Documents()
        class Governance:
            async def read_reporting_year_evidence(self,token,**kwargs):
                owner.calls.append('governance');assert kwargs['company_id']==COMPANY and kwargs['income_year']==YEAR
                return owner.view
        self.workflow=ShareholderRegisterSourceWorkflow(RFFactory(),CompanyAccess(),DocumentsFactory(),Governance())
    def capture(self):return asyncio.run(self.workflow.capture_year_source('verified-token',self.command,
        idempotency_key=IdempotencyKey('owner-source-capture-001'),correlation_id=CorrelationId('owner-source-capture')))


@pytest.mark.parametrize('kind',['no_activity','formation','transfer','dividend'])
def test_supported_capture_uses_only_fresh_owner_projections_and_explicit_complete_source(kind):
    h=Harness(kind);snapshot=h.capture()
    assert snapshot.command==h.command and h.calls==['rf_auth','company','verify_document','governance','persist']
    assert h.context.accepted_owner and h.context.company==h.command.case.company
    assert h.context.documents[0].metadata_sha256==rf1086_year_source_digest(h.record)
    assert h.context.documents[0].content_version_sha256==h.record.content_sha256


def test_dividend_rf_year_uses_meeting_year_preserving_original_finalization_source_year():
    h=Harness('dividend');original=h.view.dividends[0].finalizations[0];before=rf1086_year_source_digest(original)
    snapshot=h.capture();receipt=snapshot.governance_receipts[0]
    assert receipt.income_year==YEAR and original.income_year==IncomeYear(2024)
    assert receipt.receipt_id==str(original.finalization_id) and receipt.active
    assert rf1086_year_source_digest(original)==before
    assert original.signed_artifact_hashes=={kind.value:'a'*64 for kind in (CorporateArtifactKind.DIVIDEND_BOARD_PROPOSAL,CorporateArtifactKind.DIVIDEND_GENERAL_MEETING_MINUTES)}


@pytest.mark.parametrize('change',['wrong_actor','wrong_document_actor','reviewer','changed_company','unconfirmed','wrong_document_company','changed_bytes','changed_metadata','invalid_bytes'])
def test_identity_owner_or_document_changes_prevent_capture(change):
    h=Harness()
    if change=='wrong_actor':h.actor=replace(ACTOR,subject=type(ACTOR.subject)(str(uuid4())))
    if change=='wrong_document_actor':h.document_actor=replace(ACTOR,subject=type(ACTOR.subject)(str(uuid4())))
    if change=='reviewer':h.company.role='reviewer'
    if change=='changed_company':h.company.name='changed owner identity'
    if change=='unconfirmed':h.company.identity_locked_at=None
    if change=='wrong_document_company':h.record=replace(h.record,company_id=CompanyId(str(uuid4())))
    if change=='changed_bytes':h.record=replace(h.record,content_sha256='e'*64)
    if change=='changed_metadata':h.record=replace(h.record,name='different retained metadata')
    if change=='invalid_bytes':h.document_failure=True
    with pytest.raises((Rf1086YearSourceError,DocumentsError)):h.capture()
    assert not h.saved and 'persist' not in h.calls


@pytest.mark.parametrize('state',['pending','rejected','superseded'])
def test_unresolved_governance_evidence_cannot_disappear_from_capture(state):
    h=Harness('dividend');h.view=replace(h.view,dividends=(replace(h.view.dividends[0],status=state),))
    with pytest.raises(Rf1086YearSourceError,match='governance_unresolved'):h.capture()
    assert not h.saved


def test_extra_finalized_dividend_invalidates_a_claimed_no_activity_year():
    h=Harness();other=Harness('dividend');h.view=other.view
    with pytest.raises(Rf1086YearSourceError,match='governance_events_omitted'):h.capture()
    assert not h.saved


def test_cash_capital_does_not_use_unbacked_register_reference_as_proof():
    h=Harness('cash_issue')
    with pytest.raises(Rf1086YearSourceError,match='independent_register_unavailable'):h.capture()
    assert not h.saved


@pytest.mark.parametrize('replacement',[False,True])
def test_historical_ledger_reversal_or_correction_blocks_even_finalized_dividend(replacement):
    h=Harness('dividend');final=h.view.dividends[0].finalizations[0]
    amendment=CorporateLedgerAmendment(final.accounting_entry_id,ref(AccountingEntryReference),
        ref(AccountingEntryReference) if replacement else None,COMPANY,IncomeYear(2024),
        'Historical owner correction',ACTOR,NOW)
    h.view=replace(h.view,ledger_amendments=(amendment,))
    with pytest.raises(Rf1086YearSourceError,match='governance_unresolved'):h.capture()
    assert not h.saved


def test_connected_cross_year_dividend_correction_cannot_be_recategorized_into_target_year():
    h=Harness('dividend');item=h.view.dividends[0]
    h.view=replace(h.view,dividends=(replace(item,reporting_date=LocalDate(date(2026,1,1))),))
    with pytest.raises(Rf1086YearSourceError,match='governance_unresolved'):h.capture()
    assert not h.saved


@pytest.mark.parametrize('change',['wrong_scope','unsigned','unbacked_signed_id','altered_amount','missing_finalization','altered_source_year'])
def test_signed_receipts_and_independent_economics_are_verified(change):
    h=Harness('dividend');item=h.view.dividends[0]
    if change=='wrong_scope':h.view=replace(h.view,company_id=CompanyId(str(uuid4())))
    if change=='unsigned':h.view=replace(h.view,dividends=(replace(item,artifacts=tuple(replace(a,variant=CorporateArtifactVariant.UNSIGNED) for a in item.artifacts)),))
    if change=='unbacked_signed_id':h.view=replace(h.view,dividends=(replace(item,artifacts=tuple(replace(a,document_id=ref(DocumentReference)) for a in item.artifacts)),))
    if change=='altered_amount':
        facts=dict(item.decision.canonical_input);facts['dividend']={'amountOre':99999,'allocations':[{'shareholderId':'owner','amountOre':99999}]}
        h.view=replace(h.view,dividends=(replace(item,decision=replace(item.decision,canonical_input=facts)),))
    if change=='missing_finalization':h.view=replace(h.view,dividends=(replace(item,finalizations=()),))
    if change=='altered_source_year':
        before=h.capture().governance_receipts[0].finalization_sha256
        h.view=replace(h.view,dividends=(replace(item,decision=replace(item.decision,income_year=IncomeYear(2023))),))
        assert h.capture().governance_receipts[0].finalization_sha256!=before
        return
    with pytest.raises(Rf1086YearSourceError):h.capture()
    assert not h.saved


def test_callers_cannot_supply_trusted_context():
    h=Harness()
    with pytest.raises(TypeError):asyncio.run(h.workflow.capture_year_source('token',h.command,
        idempotency_key=IdempotencyKey('capture-context-forgery'),correlation_id=CorrelationId('forgery'),context=SimpleNamespace(accepted_owner=True)))
    assert not h.calls


def test_dividend_cents_cannot_round_into_matching_rf_economics():
    from decimal import localcontext
    h=Harness('dividend');item=h.view.dividends[0]
    facts=dict(item.decision.canonical_input);dividend=dict(facts['dividend'])
    original_total=dividend['amountOre']
    rows=[dict(row) for row in dividend['allocations']]
    rows[0]['amountOre']+=1
    dividend.update(amountOre=original_total+1,allocations=rows);facts['dividend']=dividend
    h.view=replace(h.view,dividends=(replace(item,decision=replace(item.decision,canonical_input=facts)),))
    with localcontext() as context:
        context.prec=5
        with pytest.raises(Rf1086YearSourceError):h.capture()
    assert not h.saved


def test_dividend_receipt_digest_does_not_depend_on_decimal_precision():
    from decimal import localcontext, Rounded, Inexact
    expected=Harness('dividend').capture().governance_receipts[0].economic_sha256
    actual=Harness('dividend')
    with localcontext() as context:
        context.prec=5
        context.traps[Rounded]=True
        context.traps[Inexact]=True
        assert actual.capture().governance_receipts[0].economic_sha256==expected
