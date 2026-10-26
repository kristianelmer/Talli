"""Owning source composition and exact drafts; no provider or common-ready claims."""
import asyncio
from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import json
from uuid import uuid4

import pytest

from talli_backend.adapters.annual_accounts_schemas import PinnedAnnualAccountsSchemas
from talli_backend.application.annual_accounts_delivery_source import read_annual_accounts_delivery_source
from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsDeliverySource, AnnualAccountsError, AnnualAccountsSourceQuery,
    decode_annual_accounts_delivery_draft, prepare_annual_accounts_delivery,
)
from talli_backend.modules.corporate_governance.public import (
    CorporateArtifactId,CorporateArtifactKind,CorporateArtifactRecord,CorporateArtifactVariant,
    CorporateDecisionKind,CorporateEventId,CorporateEventRecord,CorporateFinalizationId,
    CorporateFinalizationRecord,DocumentReference,
)
from talli_backend.modules.corporate_governance.service import CorporateGovernanceService
from talli_backend.shared.kernel import CorrelationId, IdempotencyKey, IncomeYear, Money
from talli_backend.modules.ledger.public import LedgerEntryKind,LedgerLine
from test_corporate_governance import supported_annual_close
from test_corporate_governance_workflow import application as governance_application
from test_ledger_reporting_snapshot import entry,amendment,Queries

COMMAND=supported_annual_close();COMPANY=COMMAND.company_id;ACTOR=COMMAND.actor_id;YEAR=IncomeYear(2025)
NOW=datetime(2026,10,26,tzinfo=UTC)
QUERY=AnnualAccountsSourceQuery(COMPANY,YEAR,ACTOR)


def corporate_snapshot():
    app,transaction,_,_,_=governance_application()
    snapshot=asyncio.run(transaction.read_lifecycle(COMMAND.decision_id));decision=snapshot.decisions[0]
    artifacts=tuple(CorporateArtifactRecord(CorporateArtifactId(str(uuid4())),COMPANY,YEAR,decision.document_set_id,
        kind,variant,DocumentReference(str(uuid4())),str(index)*64,100,None,str(ACTOR.subject),NOW)
        for index,(kind,variant) in enumerate(((CorporateArtifactKind.ANNUAL_BOARD_MINUTES,CorporateArtifactVariant.UNSIGNED),
            (CorporateArtifactKind.ANNUAL_GENERAL_MEETING_MINUTES,CorporateArtifactVariant.UNSIGNED),
            (CorporateArtifactKind.ANNUAL_BOARD_MINUTES,CorporateArtifactVariant.SIGNED_OWNER_ATTESTED),
            (CorporateArtifactKind.ANNUAL_GENERAL_MEETING_MINUTES,CorporateArtifactVariant.SIGNED_OWNER_ATTESTED)),1))
    event=CorporateEventRecord(CorporateEventId(str(uuid4())),COMPANY,YEAR,decision.decision_id,
        decision.document_set_id,None,'facts_approved',str(ACTOR.subject),NOW,NOW,decision.decision_hash,None,{},'source-facts-approved')
    final=CorporateFinalizationRecord(CorporateFinalizationId(str(uuid4())),COMPANY,YEAR,decision.decision_id,
        'annual_close_finalized',None,None,decision.annual_close_source_id,decision.decision_hash,
        {item.artifact_kind.value:item.content_sha256 for item in artifacts if item.variant is CorporateArtifactVariant.SIGNED_OWNER_ATTESTED},
        None,str(ACTOR.subject),NOW)
    return app,transaction,replace(snapshot,artifacts=artifacts,events=(event,),finalizations=(final,))


def raw_history(transaction):
    source=transaction.source_facts(2025).annual_data[0]
    return [{'sourceId':str(source.source_id),'companyId':str(COMPANY),'incomeYear':2025,'answers':dict(source.answers),
        'confirmations':list(source.confirmations),'noActivityConfirmed':source.no_activity_confirmed,
        'annualFullTimeEquivalents':source.annual_full_time_equivalents,'completedAt':source.completed_at,'updatedAt':source.updated_at}]


def ledger_entries():
    opening=replace(entry(),company_id=COMPANY,income_year=YEAR,entry_kind=LedgerEntryKind.OPENING_BALANCE,
        lines=(LedgerLine('1920','Synthetic bank',Money.nok('30000'),Money.nok('0')),
               LedgerLine('2000','Synthetic capital',Money.nok('0'),Money.nok('30000'))))
    return (opening,)


def source_inputs():
    app,transaction,snapshot=corporate_snapshot();transaction.list_snapshot=snapshot
    class Inputs:
        actor_id=ACTOR
        delivery_corporate_queries=transaction
        delivery_ledger_queries=Queries(())
        history=raw_history(transaction)
        async def delivery_annual_interview_history(self,query):return self.history
    inputs=Inputs()
    class Ledger(Queries):
        async def list_entry_amendments(self,**query):return self.amendments
    inputs.delivery_ledger_queries=Ledger(ledger_entries())
    return inputs,app,transaction


def read(inputs,app):return asyncio.run(read_annual_accounts_delivery_source(inputs,QUERY,corporate=app,
    correlation_id=CorrelationId('accounts-owning-source-test')))


def prepare(source):return prepare_annual_accounts_delivery(source,filing_id=str(uuid4()),command_key=IdempotencyKey('accounts-prepare-command'),
    actor_id=ACTOR,contact_email='owner@example.test',confirming_representative='Synthetic Person',schemas=PinnedAnnualAccountsSchemas())


def test_snapshot_reuses_current_corporate_owner_policy_without_new_sessions_or_provider_calls():
    inputs,app,transaction=source_inputs();source=read(inputs,app)
    assert source.owning_snapshots['corporate']['readiness']['current_source_matches'] is True
    assert source.owning_snapshots['corporate']['readiness']['blockers']==()
    assert source.owning_snapshots['ledger']['retained_entries'][0]['entry_id']['value']==str(inputs.delivery_ledger_queries.entries[0].entry_id)
    assert not any(hasattr(source,name) for name in ('ready','submitted','accepted','signed'))
    draft=prepare(source)
    assert draft.main_form_xml and draft.company_accounts_xml
    assert COMMAND.general_meeting.meeting_date.value.isoformat() in draft.main_form_xml
    assert decode_annual_accounts_delivery_draft(draft.canonical_json,draft.sha256)==draft
    before=source.sha256;inputs.history[0]['answers']['changed']=True
    assert source.sha256==before and read(inputs,app).sha256!=before
    with pytest.raises(TypeError):source.owning_snapshots['annual'][0]['answers']['changed']=True


def test_current_financial_changes_and_signature_changes_change_the_source_and_block_stale_approval():
    inputs,app,transaction=source_inputs();source=read(inputs,app)
    transaction.source_facts_changed=True;changed=read(inputs,app)
    assert changed.sha256!=source.sha256
    with pytest.raises(AnnualAccountsError):prepare(changed)
    transaction.source_facts_changed=False
    artifact=transaction.list_snapshot.artifacts[-1]
    transaction.list_snapshot=replace(transaction.list_snapshot,artifacts=(*transaction.list_snapshot.artifacts[:-1],replace(artifact,content_sha256='f'*64)))
    with pytest.raises(AnnualAccountsError):read(inputs,app)


def test_expense_correction_projects_only_replacement_without_losing_original_history():
    inputs,app,_=source_inputs();original=replace(entry('100'),company_id=COMPANY);reversal=replace(entry('100',reverse=True),company_id=COMPANY)
    replacement=replace(entry('50'),company_id=COMPANY)
    change=replace(amendment(original,reversal,replacement),company_id=COMPANY,amended_by=ACTOR)
    inputs.delivery_ledger_queries.entries=(*ledger_entries(),original,reversal,replacement)
    inputs.delivery_ledger_queries.amendments=(change,)
    draft=prepare(read(inputs,app))
    assert len(draft.source.owning_snapshots['ledger']['retained_entries'])==4
    assert len(draft.source.ledger_entries)==2
    assert '<aarets orid="17126">50</aarets>' in draft.company_accounts_xml


@pytest.mark.parametrize('defect',['no-annual','foreign-annual','duplicate-year','bad-time','missing-workforce','unsupported-attachment',
    'unfinalized','missing-signed','stale','unknown-account','cents','negative-expense','unbalanced'])
def test_missing_stale_or_unrepresentable_source_never_prepares(defect):
    inputs,app,transaction=source_inputs()
    if defect=='no-annual':inputs.history=[]
    elif defect=='foreign-annual':inputs.history[0]['companyId']=str(uuid4())
    elif defect=='duplicate-year':inputs.history*=2
    elif defect=='bad-time':inputs.history[0]['updatedAt']='not-a-time'
    elif defect=='missing-workforce':inputs.history[0]['annualFullTimeEquivalents']=None
    elif defect=='unsupported-attachment':inputs.history[0]['confirmations'].append('annual_accounts_sustainability_required')
    elif defect=='unfinalized':transaction.list_snapshot=replace(transaction.list_snapshot,finalizations=())
    elif defect=='missing-signed':transaction.list_snapshot=replace(transaction.list_snapshot,artifacts=transaction.list_snapshot.artifacts[:2])
    elif defect=='stale':transaction.source_facts_changed=True
    else:
        current=inputs.delivery_ledger_queries.entries[0]
        if defect=='unknown-account':lines=(replace(current.lines[0],account='9999'),current.lines[1])
        elif defect=='cents':lines=(replace(current.lines[0],debit=Money.nok('30000.01')),replace(current.lines[1],credit=Money.nok('30000.01')))
        elif defect=='negative-expense':lines=(current.lines[0],replace(current.lines[1],account='6700'))
        else:lines=(replace(current.lines[0],debit=Money.nok('30001')),current.lines[1])
        inputs.delivery_ledger_queries.entries=(replace(current,lines=lines),)
    with pytest.raises(AnnualAccountsError):prepare(read(inputs,app))


@pytest.mark.parametrize('defect',['space','duplicate-key','unknown-version','unknown-field','bool-year','actor','key','xml',
    'inspection','schema-generation','source-scope','nonfinite','depth','retained-annual','retained-ledger',
    'retained-finalization','upstream-commitment','ledger-projection'])
def test_rehashed_storage_corruption_never_becomes_a_valid_exact_draft(defect):
    inputs,app,_=source_inputs();draft=prepare(read(inputs,app));raw=draft.canonical_json;value=json.loads(raw);body=value['draft']
    if defect=='space':raw+=' '
    elif defect=='duplicate-key':raw=raw.replace('"version":','"version":"ignored","version":')
    elif defect=='depth':raw='['*1100+']'*1100
    else:
        if defect=='unknown-version':value['version']='future'
        elif defect=='unknown-field':body['ignored']=True
        elif defect=='bool-year':body['source']['income_year']['value']=True
        elif defect=='actor':body['prepared_by']['kind']='SYSTEM'
        elif defect=='key':body['command_key']['value']='short'
        elif defect=='xml':body['main_form_xml']+='\n'
        elif defect=='inspection':body['inspection']['main_form_sha256']='a'*64
        elif defect=='source-scope':body['source']['annual_data']['company_id']=str(uuid4())
        elif defect=='schema-generation':body['inspection']['schema_sha256']='a'*64
        elif defect=='retained-annual':body['source']['owning_snapshots']['annual']=[]
        elif defect=='retained-ledger':body['source']['owning_snapshots']['ledger']['retained_entries']=[]
        elif defect=='retained-finalization':body['source']['owning_snapshots']['corporate']['snapshot']['finalizations']=[]
        elif defect=='upstream-commitment':body['source']['upstream_sha256']['corporate']='a'*64
        elif defect=='ledger-projection':body['source']['ledger_entries'][0]['lines'][0]['debit']='1.00'
        elif defect=='nonfinite':body['source']['annual_data']['ignored']=float('nan')
        raw=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)
    with pytest.raises(ValueError):decode_annual_accounts_delivery_draft(raw,hashlib.sha256(raw.encode()).hexdigest())
