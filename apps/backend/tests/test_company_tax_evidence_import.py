"""Receipt import composes exact legacy projection, replay and atomic Audit."""
import asyncio
import copy
from contextlib import asynccontextmanager
from dataclasses import replace
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from talli_backend.main import create_app
from talli_backend.application.company_tax_filing_workflow import CompanyTaxApplication
from talli_backend.application.ledger_session import LedgerAuthenticationError
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxCompanyIdentity, CompanyTaxError, ImportedCompanyTaxEvidence,
    ImportCompanyTaxReturnEvidence, TaxAuthorityEvidenceId, TaxFilingSubmissionId,
)
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, UserId

FIXTURE=json.loads((Path(__file__).resolve().parents[3]/'architecture/evidence/issues/152/legacy-characterization.json').read_text())
CASE=next(c for c in FIXTURE['evidenceCases'] if c['id']=='synthetic-completed-pending-feedback')
VALUE=CASE['input']
ACTOR=ActorId(ActorKind.USER,UserId(VALUE['recordedBy']))
COMPANY=CompanyId(VALUE['companyId'])
RESULT=ImportedCompanyTaxEvidence(TaxAuthorityEvidenceId('00000000-0000-0000-0000-000000000171'),TaxFilingSubmissionId('00000000-0000-0000-0000-000000000172'),True)


def command():
    return ImportCompanyTaxReturnEvidence(ACTOR,COMPANY,IncomeYear(2025),copy.deepcopy(VALUE['evidence']),VALUE.get('evidenceUrl'))


def plain(value):
    from collections.abc import Mapping
    if isinstance(value,Mapping):return {k:plain(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [plain(v) for v in value]
    return value


class Sessions:
    actor_id=ACTOR
    def __init__(self,created=True,fail=None):
        self.created,self.fail,self.events,self.pending,self.committed=created,fail,[],[],[]
    async def session(self,token):
        if token!='fixture':raise LedgerAuthenticationError()
        return self
    @asynccontextmanager
    async def transaction(self):
        self.events.append('begin')
        try:yield self
        except Exception:
            self.pending.clear();self.events.append('rollback');raise
        else:
            self.committed+=self.pending;self.pending.clear();self.events.append('commit')
    async def filing_company_identity(self,company_id,actor_id):
        self.events.append('company-identity')
        assert company_id==COMPANY and actor_id==ACTOR
        if self.fail=='authorization':raise CompanyTaxError.forbidden()
        return CompanyTaxCompanyIdentity(COMPANY,VALUE['expectedCompanyOrgNumber'])
    async def import_return_evidence(self,projection,actor_id):
        self.events.append('import')
        assert actor_id==ACTOR
        assert plain({'authorityRun':projection.authority_run,'submission':projection.submission})==CASE['output']['value']
        if self.fail=='mfa':raise CompanyTaxError.mfa_required()
        if self.created:self.pending.append('tax-rows')
        return replace(RESULT,created=self.created)
    async def include_audit_event(self,event):
        self.events.append('audit')
        assert event.company_id==COMPANY and event.actor_id==ACTOR
        assert event.category=='submission' and event.action=='company_tax_tt02_evidence_imported'
        assert event.message=='Skattemelding TT02-evidens importert og venter på klassifisering med ref '+CASE['output']['value']['authorityRun']['test_reference']+'.'
        if self.fail=='audit':raise CompanyTaxError.unavailable()
        self.pending.append('audit-row')


def execute(sessions,value=None):
    async def run():
        app=await CompanyTaxApplication(sessions,lambda _:None).session('fixture')
        return await app.import_return_evidence(value or command())
    return asyncio.run(run())


@pytest.mark.parametrize('created',[True,False])
def test_exact_projection_and_audit_only_when_created(created):
    sessions=Sessions(created=created)
    assert execute(sessions)==replace(RESULT,created=created)
    assert sessions.events==['begin','company-identity','import']+(['audit'] if created else [])+['commit']
    assert sessions.committed==(['tax-rows','audit-row'] if created else [])


def test_audit_failure_rolls_back_tax_rows():
    sessions=Sessions(fail='audit')
    with pytest.raises(CompanyTaxError):execute(sessions)
    assert sessions.events[-1]=='rollback' and sessions.committed==[] and sessions.pending==[]


def test_forged_actor_never_opens_transaction():
    sessions=Sessions()
    with pytest.raises(CompanyTaxError):execute(sessions,replace(command(),actor_id=ActorId(ActorKind.USER,UserId('00000000-0000-0000-0000-000000000199'))))
    assert sessions.events==[]


def test_invalid_evidence_never_persists_or_echoes_source():
    sessions=Sessions()
    with pytest.raises(CompanyTaxError) as error:execute(sessions,replace(command(),evidence={'private':'synthetic-secret'}))
    assert error.value.code=='COMPANY_TAX_INVALID_INPUT'
    assert 'synthetic-secret' not in str(error.value)
    assert sessions.events==['begin','company-identity','rollback']


def test_http_requires_session_and_preserves_ids_replay_and_mfa_code():
    sessions=Sessions();client=TestClient(create_app(company_tax_session_factory=sessions))
    body={'companyId':str(COMPANY),'incomeYear':2025,'evidenceJson':json.dumps(VALUE['evidence']),'evidenceUrl':VALUE.get('evidenceUrl')}
    path='/api/v1/company-tax/tt02-evidence-imports';headers={'Authorization':'Bearer fixture'}
    assert client.post(path,json=body).status_code==401 and sessions.events==[]
    response=client.post(path,json=body,headers=headers)
    assert response.status_code==200,response.text
    assert response.json()=={'authorityTestRunId':str(RESULT.authority_test_run_id),'filingSubmissionId':str(RESULT.filing_submission_id),'created':True}
    assert response.headers['cache-control']=='no-store'
    sessions.created=False
    assert client.post(path,json=body,headers=headers).json()['created'] is False
    sessions.fail='mfa'
    response=client.post(path,json=body,headers=headers)
    assert response.status_code==403 and response.json()['code']=='COMPANY_TAX_MFA_REQUIRED'


@pytest.mark.parametrize('evidence',['', '[]','{broken','{"ignored":NaN}', 'ø'*(256*1024+1)])
def test_http_rejects_invalid_or_oversize_file_without_side_effects(evidence):
    sessions=Sessions();client=TestClient(create_app(company_tax_session_factory=sessions))
    response=client.post('/api/v1/company-tax/tt02-evidence-imports',headers={'Authorization':'Bearer fixture'},json={
        'companyId':str(COMPANY),'incomeYear':2025,'evidenceJson':evidence})
    assert response.status_code==422,response.text
    assert sessions.committed==[] and 'import' not in sessions.events
    assert evidence not in response.text if len(evidence)>2 else True


@pytest.mark.parametrize('result',[
    None, {}, {'authority_test_run_id':None,'filing_submission_id':str(RESULT.filing_submission_id),'created':False},
    {'authority_test_run_id':str(RESULT.authority_test_run_id),'filing_submission_id':'invalid','created':False},
    {'authority_test_run_id':str(RESULT.authority_test_run_id),'filing_submission_id':str(RESULT.filing_submission_id),'created':'false'},
])
def test_adapter_rejects_malformed_import_receipt(result):
    from talli_backend.adapters.postgres_company_tax_filing import PostgresCompanyTaxTransaction
    from talli_backend.adapters.supabase_ledger import _VerifiedActor
    from talli_backend.modules.company_tax_filing.public import CompanyTaxEvidenceProjection
    class Cursor:
        async def fetchall(self):return [{'result':result}]
    class Connection:
        async def execute(self,query,parameters):
            assert query=='select company_tax_filing.import_tt02_evidence_v1(%s::jsonb,%s::text) as result'
            assert json.loads(parameters[0])==CASE['output']['value'] and parameters[1]==str(ACTOR.subject)
            return Cursor()
    tx=PostgresCompanyTaxTransaction(_VerifiedActor(ACTOR,'{}'),Connection())
    projection=CompanyTaxEvidenceProjection(CASE['output']['value']['authorityRun'],CASE['output']['value']['submission'])
    with pytest.raises(CompanyTaxError) as error:asyncio.run(tx.import_return_evidence(projection,ACTOR))
    assert error.value.code=='COMPANY_TAX_DEPENDENCY_UNAVAILABLE'


def test_valid_evidence_with_non_json_number_in_ignored_field_is_rejected_before_transaction():
    sessions=Sessions();client=TestClient(create_app(company_tax_session_factory=sessions))
    evidence={**VALUE['evidence'],'ignored':float('nan')}
    response=client.post('/api/v1/company-tax/tt02-evidence-imports',headers={'Authorization':'Bearer fixture'},json={
        'companyId':str(COMPANY),'incomeYear':2025,'evidenceJson':json.dumps(evidence)})
    assert response.status_code==422 and sessions.events==[]


def test_deep_ignored_json_remains_supported_and_recursively_immutable():
    sessions=Sessions();client=TestClient(create_app(company_tax_session_factory=sessions))
    evidence_json=json.dumps(VALUE['evidence'])[:-1]+',"ignored":'+('['*600)+'"original"'+(']'*600)+'}'
    response=client.post('/api/v1/company-tax/tt02-evidence-imports',headers={'Authorization':'Bearer fixture'},json={
        'companyId':str(COMPANY),'incomeYear':2025,'evidenceJson':evidence_json,'evidenceUrl':VALUE.get('evidenceUrl')})
    assert response.status_code==200,response.text
    value=ImportCompanyTaxReturnEvidence(ACTOR,COMPANY,IncomeYear(2025),json.loads(evidence_json))
    nested=value.evidence['ignored']
    for _ in range(600):
        assert isinstance(nested,tuple)
        nested=nested[0]
    assert nested=='original'


@pytest.mark.parametrize('message',['company_tax_evidence_conflict','company_tax_evidence_invalid_payload','company_tax_evidence_forbidden_content'])
def test_persistence_rejections_remain_distinct_from_projection_validation(message):
    from types import SimpleNamespace
    from talli_backend.adapters.postgres_company_tax_filing import _company_tax_database_error
    error=_company_tax_database_error(SimpleNamespace(diag=SimpleNamespace(message_primary=message)))
    assert error.code=='COMPANY_TAX_EVIDENCE_PERSISTENCE_REJECTED'
