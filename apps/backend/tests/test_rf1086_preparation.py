from __future__ import annotations
import asyncio
from collections.abc import Mapping
from dataclasses import fields,is_dataclass,replace
import json
from pathlib import Path
import pytest
from talli_backend.modules.shareholder_register_filing.public import (
    PreviewId, OpeningSnapshotId, Rf1086PreviewRecord, Rf1086ReadinessIssue,
    Rf1086SimulationBasis, ConfirmRf1086SimulationCommand, RecordRf1086OverrideCommand,
    AddRf1086ReviewCommentCommand, RecordRf1086TestEvidenceCommand, ConfirmRf1086FilingPermissionCommand,
    GenerateRf1086PreviewCommand, Rf1086OpeningBasis, Rf1086RecordedResult,
    ShareholderRegisterFilingError, parse_rf1086_case, ApproveRf1086ProductionCommand,
    Rf1086ApprovalBasis,
)
from talli_backend.modules.shareholder_register_filing.preparation import Rf1086PreparationService,prepare_simulation
from talli_backend.shared.kernel import ActorId,ActorKind,UserId,CompanyId,IncomeYear,CorrelationId

ORACLE=Path(__file__).parent/'fixtures/rf1086_oracle/runtime-simulation-oracle.json'
CASES=json.loads(ORACLE.read_text())
ACTOR=ActorId(ActorKind.USER,UserId('20000000-0000-4000-8000-000000000002'))
COMPANY=CompanyId('10000000-0000-4000-8000-000000000001')
YEAR=IncomeYear(2025)
CORRELATION=CorrelationId('rf1086-golden')
PREVIEW=PreviewId('30000000-0000-4000-8000-000000000003')
NOW='2026-09-09T12:00:00.123Z'

def values(value):
    if is_dataclass(value):return {f.name:values(getattr(value,f.name)) for f in fields(value)}
    if isinstance(value,Mapping):return {k:values(v) for k,v in value.items()}
    if isinstance(value,tuple):return [values(v) for v in value]
    return value

def preview(case=CASES[0]):
    row=dict(case['preview']);row['issues']=tuple(Rf1086ReadinessIssue(**issue) for issue in row['issues'])
    return Rf1086PreviewRecord(**row)

def basis(case=CASES[0]):return Rf1086SimulationBasis(preview(case),'a'*64,True,0,())
def command(**changes):return replace(ConfirmRf1086SimulationCommand(PREVIEW,True,True,ACTOR,CORRELATION),**changes)

@pytest.mark.parametrize('case',CASES,ids=lambda case:case['name'])
def test_exact_persisted_simulation_and_payload_identity(case):
    prepared=prepare_simulation(command(),basis(case),clock=lambda:NOW)
    actual=values(prepared);actual.pop('basis')
    assert actual == {key:case[key] for key in actual}
    with pytest.raises(TypeError):prepared.result['calls'][0]['status']='changed'

@pytest.mark.parametrize('change',[{'annual_readiness_ready':False},{'annual_readiness_ready':1},{'hard_review_blocks':1},{'blocking_override_targets':('rf1086.shares',)}])
def test_simulation_source_preconditions_fail_closed(change):
    with pytest.raises(ShareholderRegisterFilingError):prepare_simulation(command(),replace(basis(),**change))

@pytest.mark.parametrize('change',[{'authority_confirmed':False},{'preview_confirmed':False},{'authority_confirmed':1},{'preview_confirmed':'yes'}])
def test_simulation_requires_actual_confirmations(change):
    with pytest.raises(ShareholderRegisterFilingError):prepare_simulation(command(**change),basis())

class Store:
    def __init__(self):self.calls=[]
    async def record_override(self,command):self.calls.append(command);return Rf1086RecordedResult(str(PREVIEW),COMPANY,None if isinstance(command,(RecordRf1086TestEvidenceCommand,ConfirmRf1086FilingPermissionCommand)) else YEAR)
    async def add_review_comment(self,command):self.calls.append(command);return Rf1086RecordedResult(str(PREVIEW),COMPANY,None if isinstance(command,(RecordRf1086TestEvidenceCommand,ConfirmRf1086FilingPermissionCommand)) else YEAR)
    async def record_test_evidence(self,command):self.calls.append(command);return Rf1086RecordedResult(str(PREVIEW),COMPANY,None if isinstance(command,(RecordRf1086TestEvidenceCommand,ConfirmRf1086FilingPermissionCommand)) else YEAR)
    async def confirm_filing_permission(self,command):self.calls.append(command);return Rf1086RecordedResult(str(PREVIEW),COMPANY,None if isinstance(command,(RecordRf1086TestEvidenceCommand,ConfirmRf1086FilingPermissionCommand)) else YEAR)

def test_override_preserves_exact_js_trim_and_no_new_length_policy():
    store=Store();service=Rf1086PreparationService(store)
    command=RecordRf1086OverrideCommand(PREVIEW,'\ufeff rf1086.shares \ufeff',' 0 ',' 1 ','x'*1001,'warning',True,ACTOR,CORRELATION)
    assert asyncio.run(service.record_override(command)).record_id==str(PREVIEW)
    assert store.calls[0].field_target=='rf1086.shares'
    assert store.calls[0].reason=='x'*1001
    assert (store.calls[0].old_value,store.calls[0].new_value)==('0','1')

@pytest.mark.parametrize('change',[{'owner_confirmed':False},{'owner_confirmed':1},{'field_target':' '},{'old_value':'','new_value':''},{'reason':' '},{'risk_level':'unknown'}])
def test_invalid_override_has_no_write(change):
    store=Store();service=Rf1086PreparationService(store)
    command=RecordRf1086OverrideCommand(PREVIEW,'rf1086.x','0','1','reason','warning',True,ACTOR,CORRELATION)
    with pytest.raises(ShareholderRegisterFilingError):asyncio.run(service.record_override(replace(command,**change)))
    assert store.calls==[]

@pytest.mark.parametrize('severity,body',[('advisory',''),('hard_block',' '),('unknown','note')])
def test_invalid_review_has_no_write(severity,body):
    store=Store()
    with pytest.raises(ShareholderRegisterFilingError):asyncio.run(Rf1086PreparationService(store).add_review_comment(AddRf1086ReviewCommentCommand(PREVIEW,severity,body,ACTOR,CORRELATION)))
    assert not store.calls

def test_manual_evidence_is_company_wide_and_not_fetched_or_reinterpreted():
    store=Store()
    command=RecordRf1086TestEvidenceCommand(COMPANY,'manual_evidence','accepted',' reference ',' note ',' ',' archive ',' https://example.invalid/evidence ',' unverified-hash ',ACTOR,CORRELATION)
    asyncio.run(Rf1086PreparationService(store).record_test_evidence(command))
    saved=store.calls[0]
    assert saved.receipt_reference is None and saved.payload_hash=='unverified-hash'
    assert not hasattr(saved,'income_year')
    assert saved.evidence_url=='https://example.invalid/evidence'

@pytest.mark.parametrize('value',[1,'true',None])
def test_permission_requires_boolean_not_truthiness(value):
    store=Store()
    with pytest.raises(ShareholderRegisterFilingError):asyncio.run(Rf1086PreparationService(store).confirm_filing_permission(ConfirmRf1086FilingPermissionCommand(COMPANY,value,ACTOR,CORRELATION)))
    assert not store.calls

def test_prepared_preview_preserves_backend_source_binding():
    class OpeningStore:
        async def load_opening(self,command):return Rf1086OpeningBasis(COMPANY,command.opening_snapshot_id,YEAR,parse_rf1086_case(CASES[0]['input']),'b'*64)
        async def record_preview(self,command,prepared):
            assert prepared.basis.source_digest=='b'*64
            assert prepared.rendered.hovedskjema_xml==CASES[0]['preview']['hovedskjema_xml']
            return Rf1086RecordedResult(str(PREVIEW),COMPANY,YEAR)
    command=GenerateRf1086PreviewCommand(COMPANY,OpeningSnapshotId('40000000-0000-4000-8000-000000000004'),ACTOR,CORRELATION)
    result=asyncio.run(Rf1086PreparationService(OpeningStore()).generate_preview(command))
    assert result.company_id==COMPANY and result.income_year==YEAR

def test_approval_uses_original_norwegian_payload_label_and_verified_actor():
    class ApprovalStore:
        async def load_approval_basis(self,command):return Rf1086ApprovalBasis(preview(),'923456789','c'*64)
        async def record_approval(self,command,prepared):
            assert prepared.manifest['userId']==str(ACTOR.subject)
            assert prepared.manifest['obligation']=='aksjonaerregisteroppgaven'
            assert prepared.manifest['payloadHash']==CASES[0]['payload_hash']
            assert prepared.basis.preview.filing=='aksjonærregisteroppgaven'
            return Rf1086RecordedResult(str(PREVIEW),COMPANY,YEAR)
    command=ApproveRf1086ProductionCommand(PREVIEW,'50000000-0000-4000-8000-000000000005',True,ACTOR,CORRELATION)
    asyncio.run(Rf1086PreparationService(ApprovalStore()).approve_production(command))


def test_source_review_projection_cannot_enter_legacy_approval():
    class ApprovalStore:
        async def load_approval_basis(self, command):
            return Rf1086ApprovalBasis(replace(preview(), source='rf1086-full-year-v1'), '923456789', 'c'*64)
        async def record_approval(self, *args):
            raise AssertionError('Full-year projection must never reach legacy approval persistence')
    command=ApproveRf1086ProductionCommand(PREVIEW,'50000000-0000-4000-8000-000000000005',True,ACTOR,CORRELATION)
    with pytest.raises(ShareholderRegisterFilingError):
        asyncio.run(Rf1086PreparationService(ApprovalStore()).approve_production(command))


@pytest.mark.parametrize('method',['generate_preview','confirm_simulation','approve_production'])
@pytest.mark.parametrize('misbinding',['company','year','type'])
def test_prepared_write_receipt_must_match_verified_source_scope(method,misbinding):
    class MisboundStore:
        async def load_opening(self,command):return Rf1086OpeningBasis(COMPANY,command.opening_snapshot_id,YEAR,parse_rf1086_case(CASES[0]['input']),'a'*64)
        async def load_simulation_basis(self,command):return basis()
        async def load_approval_basis(self,command):return Rf1086ApprovalBasis(preview(),'923456789','a'*64)
        async def record_preview(self,*args):return self.result()
        async def record_simulation(self,*args):return self.result()
        async def record_approval(self,*args):return self.result()
        def result(self):
            if misbinding=='type':return {'record_id':str(PREVIEW),'company_id':COMPANY,'income_year':YEAR}
            return Rf1086RecordedResult(str(PREVIEW),CompanyId('10000000-0000-4000-8000-000000000002') if misbinding=='company' else COMPANY,
                IncomeYear(2024) if misbinding=='year' else YEAR)
    commands={
        'generate_preview':GenerateRf1086PreviewCommand(COMPANY,OpeningSnapshotId('40000000-0000-4000-8000-000000000004'),ACTOR,CORRELATION),
        'confirm_simulation':command(),
        'approve_production':ApproveRf1086ProductionCommand(PREVIEW,'50000000-0000-4000-8000-000000000005',True,ACTOR,CORRELATION),
    }
    with pytest.raises(ShareholderRegisterFilingError):asyncio.run(getattr(Rf1086PreparationService(MisboundStore()),method)(commands[method]))


@pytest.mark.parametrize('method',['confirm_filing_permission','record_test_evidence'])
@pytest.mark.parametrize('misbinding',['company','year'])
def test_company_wide_receipt_cannot_infer_year_or_another_company(method,misbinding):
    class MisboundStore:
        async def confirm_filing_permission(self,command):return self.result()
        async def record_test_evidence(self,command):return self.result()
        def result(self):return Rf1086RecordedResult(str(PREVIEW),CompanyId('10000000-0000-4000-8000-000000000002') if misbinding=='company' else COMPANY,
            YEAR if misbinding=='year' else None)
    commands={
        'confirm_filing_permission':ConfirmRf1086FilingPermissionCommand(COMPANY,False,ACTOR,CORRELATION),
        'record_test_evidence':RecordRf1086TestEvidenceCommand(COMPANY,'test','accepted','reference','',None,None,None,None,ACTOR,CORRELATION),
    }
    with pytest.raises(ShareholderRegisterFilingError):asyncio.run(getattr(Rf1086PreparationService(MisboundStore()),method)(commands[method]))


@pytest.mark.parametrize('variant',['wrong_company','wrong_year','duplicate','foreign_row','foreign_filing'])
def test_workspace_denies_scope_or_identity_mismatch(variant):
    from talli_backend.modules.shareholder_register_filing.public import Rf1086WorkspaceQuery,Rf1086WorkspaceSnapshot
    result=Rf1086WorkspaceSnapshot(COMPANY,YEAR,previews=(preview(),))
    if variant=='wrong_company':result=replace(result,company_id=CompanyId('10000000-0000-4000-8000-000000000002'))
    if variant=='wrong_year':result=replace(result,income_year=IncomeYear(2024))
    if variant=='duplicate':result=replace(result,previews=(preview(),preview()))
    if variant=='foreign_row':result=replace(result,previews=(replace(preview(),company_id='10000000-0000-4000-8000-000000000002'),))
    if variant=='foreign_filing':result=replace(result,previews=(replace(preview(),filing='skattemelding'),))
    class QueryStore:
        async def workspace(self,query):return result
    with pytest.raises(ShareholderRegisterFilingError):asyncio.run(Rf1086PreparationService(QueryStore()).workspace(Rf1086WorkspaceQuery(COMPANY,ACTOR,YEAR)))


def test_workspace_omitted_year_preserves_all_retained_years():
    from talli_backend.modules.shareholder_register_filing.public import Rf1086WorkspaceQuery,Rf1086WorkspaceSnapshot
    result=Rf1086WorkspaceSnapshot(COMPANY,None,previews=(preview(),replace(preview(),id='30000000-0000-4000-8000-000000000004',income_year=2024)))
    class QueryStore:
        async def workspace(self,query):return result
    assert asyncio.run(Rf1086PreparationService(QueryStore()).workspace(Rf1086WorkspaceQuery(COMPANY,ACTOR))) is result


@pytest.mark.parametrize('result',[None,'wrong_id','dict'])
def test_preview_read_returns_exact_identity_or_none(result):
    from talli_backend.modules.shareholder_register_filing.public import ReadRf1086PreviewQuery
    class QueryStore:
        async def preview_record(self,query):
            if result is None:return None
            return {} if result=='dict' else replace(preview(),id='30000000-0000-4000-8000-000000000004')
    if result is None:assert asyncio.run(Rf1086PreparationService(QueryStore()).read_preview(ReadRf1086PreviewQuery(PREVIEW,ACTOR))) is None
    else:
        with pytest.raises(ShareholderRegisterFilingError):asyncio.run(Rf1086PreparationService(QueryStore()).read_preview(ReadRf1086PreviewQuery(PREVIEW,ACTOR)))


def test_persisted_identifiers_are_frozen_without_subclass_mutation_escape():
    assert not hasattr(PREVIEW,'__dict__')
    with pytest.raises((AttributeError,TypeError)):PREVIEW.new_attribute='injected'
