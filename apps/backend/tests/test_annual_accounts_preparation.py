"""Frozen legacy control outputs and HTTP authorization/normalization boundaries."""
from contextlib import asynccontextmanager
from dataclasses import asdict
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from talli_backend.main import create_app
from talli_backend.application.ledger_session import LedgerAuthenticationError
from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsError, AnnualAccountsRecordedResult, AnnualAccountsRecordId,
    RecordAnnualAccountsOverride, RecordAnnualAccountsTestEvidence, normalize_annual_accounts_override,
    normalize_annual_accounts_test_evidence,
)
from talli_backend.shared.kernel import ActorId,ActorKind,CompanyId,IncomeYear,UserId

COMPANY=CompanyId('00000000-0000-0000-0000-000000000152')
ACTOR=ActorId(ActorKind.USER,UserId('00000000-0000-0000-0000-000000000153'))
RECORD=AnnualAccountsRecordId('00000000-0000-0000-0000-000000000154')


class Sessions:
    actor_id=ACTOR
    def __init__(self):self.commands=[];self.fail=None
    async def session(self,token):
        if token!='fixture':raise LedgerAuthenticationError()
        return self
    @asynccontextmanager
    async def transaction(self):yield self
    async def record_override(self,command):
        self.commands.append(command)
        assert command.field_target=='tax.field' and command.reason=='reason'
        return AnnualAccountsRecordedResult(RECORD,COMPANY,IncomeYear(2025))
    async def add_review_comment(self,command):
        self.commands.append(command)
        assert command.body=='review'
        return AnnualAccountsRecordedResult(RECORD,COMPANY,None)
    async def acknowledge_review_comment(self,query):
        self.commands.append(query)
        if self.fail:raise self.fail
        return AnnualAccountsRecordedResult(query.record_id,COMPANY,None)
    async def confirm_filing_permission(self,command):
        self.commands.append(command)
        if self.fail:raise self.fail
        return AnnualAccountsRecordedResult(RECORD,COMPANY,None)
    async def record_test_evidence(self,command):
        self.commands.append(command)
        assert command.test_reference=='reference' and command.evidence_url is None
        return AnnualAccountsRecordedResult(RECORD,COMPANY,None)
    async def filing_preview(self,query):return None


@pytest.mark.parametrize('path,body',[
    ('overrides',{'previewId':str(RECORD),'fieldTarget':' tax.field ','oldValue':'old','newValue':'new','reason':' reason ','riskLevel':'warning','ownerConfirmed':True}),
    ('review-comments',{'previewId':str(RECORD),'severity':'advisory','body':' review '}),
    (f'review-comments/{RECORD}/acknowledgements',None),
    ('permissions',{'companyId':str(COMPANY),'productionEnabled':False}),
    ('test-evidence',{'companyId':str(COMPANY),'environment':'manual_evidence','status':'pending','testReference':' reference ','evidenceUrl':' '}),
])
def test_preparation_http_binds_actor_and_returns_record_scope(path,body):
    sessions=Sessions();client=TestClient(create_app(annual_accounts_session_factory=sessions));url='/api/v1/annual-accounts/'+path
    assert client.post(url,json=body).status_code==401 and sessions.commands==[]
    result=client.post(url,json=body,headers={'Authorization':'Bearer fixture'})
    assert result.status_code==200,result.text
    assert result.json()['recordId']==str(RECORD) and result.json()['companyId']==str(COMPANY)
    assert sessions.commands[-1].actor_id==ACTOR and result.headers['cache-control']=='no-store'


def test_preparation_unavailable_missing_mfa_and_hard_review_are_distinct():
    sessions=Sessions();client=TestClient(create_app(annual_accounts_session_factory=sessions));headers={'Authorization':'Bearer fixture'}
    assert client.get(f'/api/v1/annual-accounts/previews/{RECORD}',headers=headers).status_code==404
    sessions.fail=AnnualAccountsError.hard_review_block()
    result=client.post(f'/api/v1/annual-accounts/review-comments/{RECORD}/acknowledgements',headers=headers)
    assert result.status_code==403 and result.json()['detail']=='Hard review-blokk kan ikke acknowledges som advisory.'
    for error,status in [(AnnualAccountsError.mfa_required(),403),(AnnualAccountsError.unavailable(),503)]:
        sessions.fail=error
        result=client.post('/api/v1/annual-accounts/permissions',json={'companyId':str(COMPANY),'productionEnabled':True},headers=headers)
        assert result.status_code==status and result.json()['code']==error.code


def test_acknowledgement_identity_mismatch_rolls_back_before_http_response():
    events=[]
    class CorruptSessions(Sessions):
        @asynccontextmanager
        async def transaction(self):
            events.append('begin')
            try:yield self
            except Exception:
                events.append('rollback');raise
            else:events.append('commit')
        async def acknowledge_review_comment(self,query):
            events.append('acknowledgement-write')
            return AnnualAccountsRecordedResult(AnnualAccountsRecordId('00000000-0000-0000-0000-000000000199'),COMPANY,None)
    client=TestClient(create_app(annual_accounts_session_factory=CorruptSessions()))
    result=client.post(f'/api/v1/annual-accounts/review-comments/{RECORD}/acknowledgements',headers={'Authorization':'Bearer fixture'})
    assert result.status_code==503
    assert events==['begin','acknowledgement-write','rollback']
