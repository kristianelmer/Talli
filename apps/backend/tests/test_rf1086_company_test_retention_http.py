"""Closed/injected HTTP and real factory mechanics; Auth/DB gateways are doubles."""
import asyncio
import base64
from dataclasses import replace
from datetime import datetime, timedelta
import json

from fastapi.testclient import TestClient
import pytest

from talli_backend.adapters.postgres_shareholder_register_filing import PostgresCompanyTestRetentionSessionFactory
from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration
from talli_backend.application.ledger_session import LedgerAuthenticationError
from talli_backend.application.shareholder_register_company_test_retention_http import ShareholderRegisterCompanyTestRetentionHttp
from talli_backend.application.shareholder_register_filing_session import ShareholderRegisterFilingAuthenticationError
from talli_backend.application.shareholder_register_company_test_retention_stream import verify_company_test_retention_stream
from talli_backend.main import create_app
from talli_backend.modules.company_access import public as access
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId
from io import BytesIO
from test_rf1086_company_test_retention import COMPANY, ACTOR, capture, record, wire
from test_company_test_retention_download_policy import ArchiveGateway, token, NOW, fixed_policy_clock

PATH='/api/v1/shareholder-register-filings/company-test-retention'


class ReadSession:
    actor_id=ACTOR
    def __init__(self,snapshot=None):
        self.snapshot=capture(record(status='historic',environment='original',payload_hash=' opaque hash ')) if snapshot is None else snapshot
        self.calls=[]
        self.after_read=lambda:None
    async def read_company_test_retention(self,query):
        self.calls.append(query)
        assert query.actor_id==self.actor_id and query.company_id==COMPANY
        self.after_read()
        if isinstance(self.snapshot,BaseException): raise self.snapshot
        return self.snapshot


class ReadFactory:
    def __init__(self,session):self.value=session;self.calls=[]
    async def session(self,access_token):
        self.calls.append(access_token)
        if isinstance(self.value,BaseException):raise self.value
        return self.value


def client(session=None, gateway=None):
    factory=ReadFactory(ReadSession() if session is None else session)
    gateway=ArchiveGateway() if gateway is None else gateway
    return TestClient(create_app(company_access_gateway=gateway,company_test_retention_session_factory=factory)),factory,gateway


@pytest.mark.parametrize('suffix',['','/stream-v1'])
def test_default_closed_before_auth_records_or_ambient_factory(monkeypatch,suffix):
    gateway=ArchiveGateway()
    async def forbidden(*args):pytest.fail('closed retention must not invoke ambient RF factory')
    class GeneralFactory:
        session=forbidden
    application=create_app(company_access_gateway=gateway,shareholder_register_filing_session_factory=GeneralFactory())
    result=TestClient(application).get(PATH+suffix,params={'companyId':str(COMPANY)})
    assert result.status_code==503 and result.json()['code']=='rf1086_company_test_retention_not_configured'
    assert gateway.calls==[]


@pytest.mark.parametrize('role',['owner','reviewer','read_only'])
def test_http_historical_query_preserves_canonical_source_and_needs_no_fresh_mfa(role):
    browser,factory,gateway=client(gateway=ArchiveGateway(role))
    expired=token(amr=[{'method':'totp','timestamp':NOW.timestamp()-3600}])
    response=browser.get(PATH,params={'companyId':str(COMPANY)},headers={'Authorization':'Bearer '+expired})
    assert response.status_code==200 and response.content==wire(factory.value.snapshot).encode()
    assert 'no-store' in response.headers['cache-control'].split(', ')
    assert gateway.calls==[] and len(factory.value.calls)==1
    assert set(response.json()['records'][0])==set(record().__dataclass_fields__)


def test_download_uses_current_member_step_up_and_exact_stream():
    browser,factory,gateway=client()
    response=browser.get(PATH+'/stream-v1',params={'companyId':str(COMPANY)},headers={'Authorization':'Bearer '+token()})
    assert response.status_code==200
    snapshot=verify_company_test_retention_stream(BytesIO(response.content),company_id=COMPANY)
    assert snapshot==factory.value.snapshot
    assert 'company-tests' in response.headers['content-disposition']
    assert 'incomeYear' not in response.headers['content-disposition']
    assert len(gateway.calls)==8  # Same owned action guard before/after acquisition.


@pytest.mark.parametrize('query',[
    [('companyId',str(COMPANY)),('companyId',str(COMPANY))],
    [('companyId',str(COMPANY)),('incomeYear','2025')],
    [('companyId',str(COMPANY)),('actorId',str(ACTOR.subject))],
    [('companyId',str(COMPANY).replace('-',''))],
],ids=['duplicate','year','actor','noncanonical'])
def test_untrusted_scope_parameters_reject_before_factory(query):
    browser,factory,gateway=client()
    result=browser.get(PATH,params=query,headers={'Authorization':'Bearer '+token()})
    assert result.status_code==422 and factory.calls==[] and gateway.calls==[]


@pytest.mark.parametrize('failure',[ShareholderRegisterFilingAuthenticationError(),rf.ShareholderRegisterFilingError.not_found(),rf.ShareholderRegisterFilingError.unavailable()],ids=['auth','notfound','unavailable'])
def test_finite_failure_has_no_capture_metadata(failure):
    browser,factory,gateway=client(session=failure if isinstance(failure,ShareholderRegisterFilingAuthenticationError) else ReadSession(failure))
    result=browser.get(PATH,params={'companyId':str(COMPANY)},headers={'Authorization':'Bearer '+token()})
    assert result.status_code in {401,404,503} and 'records' not in result.json()
    assert 'opaque hash' not in result.text


def test_unavailable_direct_value_is_not_complete_zero_and_cannot_download():
    unavailable=rf.Rf1086CompanyTestRetentionSnapshot(COMPANY,'unavailable',None,None,None,None)
    browser,_,_=client(ReadSession(unavailable))
    result=browser.get(PATH,params={'companyId':str(COMPANY)},headers={'Authorization':'Bearer '+token()})
    assert result.status_code==200 and set(result.json())=={'codec','companyId','scope','coverage'}
    result=browser.get(PATH+'/stream-v1',params={'companyId':str(COMPANY)},headers={'Authorization':'Bearer '+token()})
    assert result.status_code==503 and 'kind' not in result.json()


@pytest.mark.parametrize('change',['member','auth'])
def test_access_loss_after_capture_stops_before_headers(change):
    session=ReadSession();gateway=ArchiveGateway()
    def revoke():
        if change=='member':gateway.role='revoked'
        else:gateway.live=False
    session.after_read=revoke
    browser,_,_=client(session,gateway)
    result=browser.get(PATH+'/stream-v1',params={'companyId':str(COMPANY)},headers={'Authorization':'Bearer '+token()})
    assert result.status_code in {401,404} and 'application/x-ndjson' not in result.headers['content-type']


def test_cancellation_after_prime_propagates_and_closes_generator(monkeypatch):
    import talli_backend.application.shareholder_register_company_test_retention_http as http
    closed=[]
    def source(snapshot):
        try:yield b'header';yield b'complete'
        finally:closed.append(True)
    monkeypatch.setattr(http,'stream_company_test_retention',source)
    class Policy:
        def __init__(self):self.calls=0
        async def authorize_archive_download_step_up(self,*args,**kwargs):
            self.calls+=1
            if self.calls==2:raise asyncio.CancelledError()
            return access.CompanyArchiveDownloadAuthorization(company_id=str(COMPANY),subject_id=str(ACTOR.subject))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(ShareholderRegisterCompanyTestRetentionHttp(ReadFactory(ReadSession()),Policy()).download(token(),company_id=COMPANY))
    assert closed==[True]


@pytest.mark.parametrize('session_id',['','00000000-0000-0000-0000-000000000000','invalid',None])
def test_real_factory_rejects_stateless_after_server_auth_with_no_database(monkeypatch,session_id):
    factory=PostgresCompanyTestRetentionSessionFactory(LedgerSupabaseConfiguration('',''))
    calls=[]
    async def authenticated(_token):
        calls.append('server-auth')
        return {'id':str(ACTOR.subject),'email':'synthetic@example.invalid'}
    monkeypatch.setattr(factory._authentication,'_auth_user',authenticated)
    with pytest.raises(ShareholderRegisterFilingAuthenticationError):
        asyncio.run(factory.session(token(session_id=session_id)))
    assert calls==['server-auth']


def test_dedicated_factory_authenticates_once_without_billing_or_provider_bindings(monkeypatch):
    factory=PostgresCompanyTestRetentionSessionFactory(LedgerSupabaseConfiguration('',''))
    calls=[]
    async def authenticated(_token):
        calls.append('server-auth')
        return {'id':str(ACTOR.subject),'email':'synthetic@example.invalid'}
    monkeypatch.setattr(factory._authentication,'_auth_user',authenticated)
    session=asyncio.run(factory.session(token()))
    assert session.actor_id==ACTOR and calls==['server-auth']
    assert session._billing is None and session._documents is None and session._company_access is None
    assert session._environment=={}


@pytest.mark.parametrize('suffix',['','/stream-v1'])
def test_injected_component_requires_bearer_before_capture(suffix):
    browser,factory,gateway=client()
    result=browser.get(PATH+suffix,params={'companyId':str(COMPANY)})
    assert result.status_code==401 and factory.calls==[] and gateway.calls==[]


def test_complete_zero_can_stream_and_is_not_unavailable():
    browser,_,_=client(ReadSession(capture()))
    query=browser.get(PATH,params={'companyId':str(COMPANY)},headers={'Authorization':'Bearer '+token()})
    assert query.status_code==200 and query.json()['recordCount']==0 and query.json()['records']==[]
    streamed=browser.get(PATH+'/stream-v1',params={'companyId':str(COMPANY)},headers={'Authorization':'Bearer '+token()})
    assert streamed.status_code==200
    assert verify_company_test_retention_stream(BytesIO(streamed.content),company_id=COMPANY)==capture()


def test_mfa_expiry_during_capture_denies_before_stream_headers(monkeypatch):
    current=[NOW]
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return current[0]
    monkeypatch.setattr(access,'datetime',Clock)
    session=ReadSession()
    session.after_read=lambda:current.__setitem__(0,NOW+timedelta(seconds=1))
    browser,_,_=client(session)
    result=browser.get(PATH+'/stream-v1',params={'companyId':str(COMPANY)},
        headers={'Authorization':'Bearer '+token(amr=[{'method':'totp','timestamp':NOW.timestamp()-900}])})
    assert result.status_code==403 and result.json()['code']=='FRESH_MFA_REQUIRED'
    assert result.headers['content-type'].startswith('application/problem+json')
    assert 'records' not in result.json() and 'content-disposition' not in result.headers


@pytest.mark.parametrize('suffix',['','/stream-v1'])
@pytest.mark.parametrize('change',['foreign','bad-digest','malformed-row'])
def test_untrusted_capture_fails_before_success_headers(suffix,change):
    snapshot=capture(record())
    if change=='foreign':snapshot=replace(snapshot,company_id=CompanyId('00000000-0000-0000-0000-000000000099'))
    elif change=='bad-digest':snapshot=replace(snapshot,records_sha256='0'*64)
    else:snapshot=replace(snapshot,records=(record(recorded_at='untrusted'),))
    browser,_,_=client(ReadSession(snapshot))
    result=browser.get(PATH+suffix,params={'companyId':str(COMPANY)},headers={'Authorization':'Bearer '+token()})
    assert result.status_code==503 and result.headers['content-type'].startswith('application/problem+json')
    assert 'records' not in result.json() and 'content-disposition' not in result.headers


@pytest.mark.parametrize('when',[1,2])
@pytest.mark.parametrize('change',['company','actor'])
def test_action_scope_must_match_authenticated_capture_before_and_after_acquisition(when,change):
    session=ReadSession()
    class Policy:
        def __init__(self):self.calls=0
        async def authorize_archive_download_step_up(self,*args,**kwargs):
            self.calls+=1
            company=str(COMPANY);subject=str(ACTOR.subject)
            if self.calls==when:
                if change=='company':company='00000000-0000-0000-0000-000000000099'
                else:subject='00000000-0000-0000-0000-000000000099'
            return access.CompanyArchiveDownloadAuthorization(company_id=company,subject_id=subject)
    with pytest.raises(rf.ShareholderRegisterFilingError) as denied:
        asyncio.run(ShareholderRegisterCompanyTestRetentionHttp(ReadFactory(session),Policy()).download(token(),company_id=COMPANY))
    assert denied.value.category==rf.ShareholderRegisterFilingError.forbidden().category
    assert len(session.calls)==(0 if when==1 else 1)


def test_transfer_close_closes_primed_producer_without_completion(monkeypatch):
    import talli_backend.application.shareholder_register_company_test_retention_http as http
    events=[]
    def source(snapshot):
        try:
            yield b'header\n'
            yield b'record\n'
            events.append('completed')
            yield b'footer\n'
        finally:events.append('closed')
    monkeypatch.setattr(http,'stream_company_test_retention',source)
    content=asyncio.run(ShareholderRegisterCompanyTestRetentionHttp(ReadFactory(ReadSession()),access.CompanyAccessService(ArchiveGateway())).download(token(),company_id=COMPANY))
    assert next(content)==b'header\n' and next(content)==b'record\n'
    content.close()
    assert events==['closed']


def test_real_factory_rejects_server_denied_session_before_claim_or_database(monkeypatch):
    factory=PostgresCompanyTestRetentionSessionFactory(LedgerSupabaseConfiguration('',''))
    calls=[]
    async def denied(_token):
        calls.append('server-auth')
        raise LedgerAuthenticationError()
    monkeypatch.setattr(factory._authentication,'_auth_user',denied)
    with pytest.raises(ShareholderRegisterFilingAuthenticationError):
        asyncio.run(factory.session(token()))
    assert calls==['server-auth']


@pytest.mark.parametrize('raw',[
    '{"sub":"'+str(ACTOR.subject)+'","session_id":"00000000-0000-0000-0000-000000000077","session_id":"00000000-0000-0000-0000-000000000078"}',
    '{"sub":"'+str(ACTOR.subject)+'","session_id":"00000000-0000-0000-0000-000000000077","extra":NaN}',
])
def test_real_factory_rejects_duplicate_and_nonfinite_signed_claims_after_server_auth(monkeypatch,raw):
    factory=PostgresCompanyTestRetentionSessionFactory(LedgerSupabaseConfiguration('',''))
    async def authenticated(_token):return {'id':str(ACTOR.subject),'email':'synthetic@example.invalid'}
    monkeypatch.setattr(factory._authentication,'_auth_user',authenticated)
    payload=base64.urlsafe_b64encode(raw.encode()).decode().rstrip('=')
    with pytest.raises(ShareholderRegisterFilingAuthenticationError):
        asyncio.run(factory.session('synthetic.'+payload+'.signature'))


@pytest.mark.parametrize('overflow',['1e999','-1e999'])
@pytest.mark.parametrize('position',['extra','nested','unsupported-method'])
def test_real_factory_rejects_overflow_everywhere_after_auth_before_database(monkeypatch,overflow,position):
    factory=PostgresCompanyTestRetentionSessionFactory(LedgerSupabaseConfiguration('',''))
    calls=[]
    async def authenticated(_token):
        calls.append('server-auth')
        return {'id':str(ACTOR.subject),'email':'synthetic@example.invalid'}
    monkeypatch.setattr(factory._authentication,'_auth_user',authenticated)
    raw=base64.urlsafe_b64decode(token().split('.')[1]+'==').decode()
    if position=='extra':raw=raw[:-1]+',"extra":'+overflow+'}'
    elif position=='nested':raw=raw[:-1]+',"extra":{"nested":['+overflow+']}}'
    else:raw=raw.replace('"amr": [','"amr": [{"method":"password","timestamp":'+overflow+'},',1)
    payload=base64.urlsafe_b64encode(raw.encode()).decode().rstrip('=')
    with pytest.raises(ShareholderRegisterFilingAuthenticationError):
        asyncio.run(factory.session('synthetic.'+payload+'.signature'))
    assert calls==['server-auth']


def test_real_factory_accepts_ordinary_float_claims(monkeypatch):
    factory=PostgresCompanyTestRetentionSessionFactory(LedgerSupabaseConfiguration('',''))
    async def authenticated(_token):return {'id':str(ACTOR.subject),'email':'synthetic@example.invalid'}
    monkeypatch.setattr(factory._authentication,'_auth_user',authenticated)
    assert asyncio.run(factory.session(token(extra={'ordinary':1.25}))).actor_id==ACTOR


@pytest.mark.parametrize('subject,expected',[('malformed',503),(str(ACTOR.subject).replace('-',''),401)])
def test_untrusted_auth_response_subject_has_finite_http_denial_before_database(monkeypatch,subject,expected):
    factory=PostgresCompanyTestRetentionSessionFactory(LedgerSupabaseConfiguration('',''))
    async def authenticated(_token):return {'id':subject,'email':'synthetic@example.invalid'}
    monkeypatch.setattr(factory._authentication,'_auth_user',authenticated)
    browser=TestClient(create_app(company_access_gateway=ArchiveGateway(),company_test_retention_session_factory=factory))
    result=browser.get(PATH,params={'companyId':str(COMPANY)},headers={'Authorization':'Bearer '+token(sub=subject)})
    assert result.status_code==expected and result.headers['content-type'].startswith('application/problem+json')
    assert 'records' not in result.json()
