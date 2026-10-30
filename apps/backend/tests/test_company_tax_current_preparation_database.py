"""Restricted real owners/snapshots/store with a finite synthetic authority GET."""
import asyncio
import base64
from contextlib import asynccontextmanager
from dataclasses import replace
from uuid import uuid4

import httpx
import psycopg
from psycopg.conninfo import conninfo_to_dict
import pytest
from fastapi.testclient import TestClient

from talli_backend.adapters.company_tax_authority import CompanyTaxTransport
from talli_backend.adapters.company_tax_schemas import PinnedTax2025Schemas
from talli_backend.application.company_tax_delivery_preparation import CompanyTaxDeliveryPreparation
from talli_backend.application.company_tax_filing_workflow import CompanyTaxApplication
from talli_backend.main import create_app
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError, PrepareTaxDeliveryDraft, TaxFilingSubmissionId,
    TaxDeliverySource,
)
from talli_backend.shared.kernel import CompanyId, IncomeYear, IdempotencyKey, CorrelationId
from test_company_tax_delivery_database import source_runtime
from test_company_tax_delivery_draft_database import MfaSessions
from test_company_tax_current_document import response
from test_company_tax_delivery import raw_source
from test_company_tax_schemas import prepared

pytestmark=pytest.mark.company_tax_database


class LostCommitSession:
    def __init__(self,inner):self.inner,self.lose=inner,True
    @property
    def actor_id(self):return self.inner.actor_id

    @asynccontextmanager
    async def transaction(self,*,snapshot=False):
        stored=False
        async with self.inner.transaction(snapshot=snapshot) as actual:
            class Transaction:
                def __getattr__(self,name):return getattr(actual,name)
                async def store_delivery_draft(self,draft):
                    nonlocal stored
                    result=await actual.store_delivery_draft(draft)
                    stored=True
                    return result
            yield Transaction()
        if stored and self.lose:
            # The real PostgreSQL context committed before losing this response.
            self.lose=False
            raise CompanyTaxError.unavailable()


def configured(source_runtime,*,during_get=lambda:None,lose_commit=False,mfa_age=0,concurrent_reads=False):
    url,backend,cid,actor,_=source_runtime
    sessions=MfaSessions(backend,actor)
    sessions.age=mfa_age
    schemas=PinnedTax2025Schemas()
    blank=prepared(schemas,TaxDeliverySource(**raw_source('no-activity-zero')))
    original=response(schemas,tax=blank.tax_xml.encode(),bom=True)
    calls=[]
    runtime=conninfo_to_dict(backend)['user']
    both_reads=asyncio.Event()
    async def authority(request):
        assert request.method=='GET' and request.url.path.startswith('/api/skattemelding/v2/2025/')
        if not concurrent_reads:
            with psycopg.connect(url,autocommit=True) as db:
                assert db.execute("select count(*) from pg_stat_activity where usename=%s and state in ('active','idle in transaction')",(runtime,)).fetchone()==(0,)
        calls.append(str(request.url))
        if concurrent_reads:
            if len(calls)==2:both_reads.set()
            await asyncio.wait_for(both_reads.wait(),timeout=5)
        during_get()
        return httpx.Response(200,content=original.raw_bytes)
    reader=CompanyTaxTransport('synthetic-current-access-token',transport=httpx.MockTransport(authority))
    wrapped={}
    class Sessions:
        async def session(self,token):
            if not lose_commit:return await sessions.session(token)
            if 'session' not in wrapped:wrapped['session']=LostCommitSession(await sessions.session(token))
            return wrapped['session']
    app=CompanyTaxApplication(Sessions(),lambda tx:None,preparation=CompanyTaxDeliveryPreparation(reader,schemas))
    command=PrepareTaxDeliveryDraft(CompanyId(str(cid)),IncomeYear(2025),actor,TaxFilingSubmissionId(str(uuid4())),
        IdempotencyKey('current-production-shaped-'+uuid4().hex),CorrelationId('current-database'))
    return app,command,calls,original


def test_actual_source_prepares_and_retains_v2_originals_with_no_http_or_database_reexecution_on_replay(source_runtime):
    app,command,calls,original=configured(source_runtime)
    async def exercise():
        actor=await app.session('synthetic-fixture')
        first=await actor.prepare_delivery_draft(command)
        assert base64.b64decode(first.draft.current_document.response.raw_base64)==original.raw_bytes
        assert 'company-tax-delivery-draft-v2' in first.draft.canonical_json
        replay=await actor.prepare_delivery_draft(replace(command,correlation_id=CorrelationId('current-retry')))
        assert replay==first and replay.draft.canonical_json==first.draft.canonical_json
    asyncio.run(exercise());assert len(calls)==1


def test_real_commit_with_lost_application_response_keeps_the_original_and_never_refetches_current(source_runtime):
    app,command,calls,_=configured(source_runtime,lose_commit=True)
    async def exercise():
        actor=await app.session('synthetic-fixture')
        with pytest.raises(CompanyTaxError):await actor.prepare_delivery_draft(command)
        retained=await actor.prepare_delivery_draft(command)
        assert retained.draft.filing_id==str(command.filing_id)
        assert retained.draft.current_document is not None
    asyncio.run(exercise());assert len(calls)==1


def test_stale_canonical_mfa_prevents_even_the_current_authority_get(source_runtime):
    app,command,calls,_=configured(source_runtime,mfa_age=3600)
    async def exercise():
        with pytest.raises(CompanyTaxError) as error:
            await (await app.session('synthetic-fixture')).prepare_delivery_draft(command)
        assert error.value.code=='COMPANY_TAX_MFA_REQUIRED'
    asyncio.run(exercise());assert calls==[]


def test_http_current_preparation_and_mfa_archive_preserve_one_exact_server_artifact(source_runtime):
    app,command,calls,original=configured(source_runtime)
    client=TestClient(create_app(company_tax_session_factory=app._sessions,
        company_tax_delivery_preparation=app._preparation))
    headers={'Authorization':'Bearer synthetic-fixture','Idempotency-Key':str(command.command_key)}
    body={'companyId':str(command.company_id),'incomeYear':2025,'filingId':str(command.filing_id)}
    first=client.post('/api/v1/company-tax/delivery-drafts',json=body,headers=headers)
    assert first.status_code==200,first.text
    replay=client.post('/api/v1/company-tax/delivery-drafts',json=body,headers=headers)
    assert replay.status_code==200 and replay.json()==first.json() and len(calls)==1
    archive=client.get('/api/v1/company-tax/archive-source/delivery-drafts-v1',
        params={'companyId':str(command.company_id),'incomeYear':2025},headers=headers)
    assert archive.status_code==200,archive.text
    retained=archive.json()['records'];assert len(retained)==1
    assert retained[0]['draftSha256']==first.json()['draftSha256']
    from talli_backend.modules.company_tax_filing.public import decode_tax_delivery_draft
    draft=decode_tax_delivery_draft(retained[0]['canonicalJson'],retained[0]['draftSha256'])
    assert draft.current_document.response.raw_bytes==original.raw_bytes
    assert draft.filing_id==str(command.filing_id) and draft.prepared_by==command.actor_id
    assert 'raw_base64' not in first.text and 'canonicalJson' not in first.text


@pytest.mark.parametrize('change',['annual','owner'])
def test_real_source_drift_or_revocation_during_authority_read_prevents_persistence(source_runtime,change):
    url,_,cid,actor,_=source_runtime
    with psycopg.connect(url) as db:
        accepted=db.execute('select accepted_at from public.company_memberships where company_id=%s and user_id=%s',
            (cid,str(actor.subject))).fetchone()[0]
    def alter():
        with psycopg.connect(url) as db:
            if change=='annual':db.execute("update public.annual_data set updated_at=updated_at+interval '1 microsecond' where company_id=%s",(cid,))
            else:db.execute('update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s',(cid,str(actor.subject)))
    app,command,calls,_=configured(source_runtime,during_get=alter)
    try:
        async def exercise():
            with pytest.raises(CompanyTaxError):await (await app.session('synthetic-fixture')).prepare_delivery_draft(command)
        asyncio.run(exercise());assert len(calls)==1
        with psycopg.connect(url) as db:
            assert db.execute('select count(*) from company_tax_filing.delivery_drafts where company_id=%s',(cid,)).fetchone()==(0,)
    finally:
        with psycopg.connect(url) as db:
            db.execute('update public.company_memberships set accepted_at=%s where company_id=%s and user_id=%s',
                (accepted,cid,str(actor.subject)))


def test_concurrent_identical_commands_return_the_same_original_despite_distinct_observation_times(source_runtime):
    app,command,calls,_=configured(source_runtime,concurrent_reads=True)
    observed=[]
    fetch=app._preparation._current.fetch_current_document
    async def record_observation(**scope):
        result=await fetch(**scope)
        observed.append(result.observed_at.value)
        return result
    app._preparation._current.fetch_current_document=record_observation
    async def exercise():
        first_actor=await app.session('synthetic-fixture')
        second_actor=await app.session('synthetic-fixture')
        first,second=await asyncio.gather(first_actor.prepare_delivery_draft(command),
            second_actor.prepare_delivery_draft(command))
        assert first==second and first.draft.canonical_json==second.draft.canonical_json
        return first
    retained=asyncio.run(exercise());assert len(calls)==2 and len(set(observed))==2
    url,_,cid,_,_=source_runtime
    with psycopg.connect(url) as db:
        assert db.execute('select count(*),min(draft_sha256) from company_tax_filing.delivery_drafts where company_id=%s',
            (cid,)).fetchone()==(1,retained.draft.sha256)


def test_source_edit_after_rendering_is_detected_under_the_final_company_guard(source_runtime):
    url,_,cid,_,_=source_runtime
    app,command,calls,_=configured(source_runtime)
    schemas=app._preparation._schemas
    class ChangedWhileRendering:
        def __getattr__(self,name):return getattr(schemas,name)
        def validate(self,*args,**kwargs):
            result=schemas.validate(*args,**kwargs)
            with psycopg.connect(url) as db:
                db.execute("update public.annual_data set updated_at=updated_at+interval '1 microsecond' where company_id=%s",(cid,))
            return result
    app._preparation._schemas=ChangedWhileRendering()
    async def exercise():
        with pytest.raises(CompanyTaxError) as error:
            await (await app.session('synthetic-fixture')).prepare_delivery_draft(command)
        assert error.value.code=='COMPANY_TAX_DRAFT_CONFLICT'
    asyncio.run(exercise());assert len(calls)==1
    with psycopg.connect(url) as db:
        assert db.execute('select count(*) from company_tax_filing.delivery_drafts where company_id=%s',(cid,)).fetchone()==(0,)


def test_canonical_mfa_expiring_during_real_source_enumeration_prevents_authority_access(source_runtime,monkeypatch):
    from talli_backend.application import company_tax_delivery_preparation as preparation
    original=preparation.read_company_tax_delivery_source
    enumerated=[]
    async def slow_snapshot(*args,**kwargs):
        value=await original(*args,**kwargs)
        enumerated.append(value)
        # Real canonical policy is 15 minutes; the verified claim starts five
        # seconds short of expiry. No DB policy/clock implementation is stubbed.
        await asyncio.sleep(6)
        return value
    monkeypatch.setattr(preparation,'read_company_tax_delivery_source',slow_snapshot)
    app,command,calls,_=configured(source_runtime,mfa_age=895)
    async def exercise():
        with pytest.raises(CompanyTaxError) as error:
            await (await app.session('synthetic-fixture')).prepare_delivery_draft(command)
        assert error.value.code=='COMPANY_TAX_MFA_REQUIRED'
    asyncio.run(exercise())
    assert len(enumerated)==1 and calls==[]


def test_final_company_guard_serializes_source_writes_until_draft_commit(source_runtime,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from talli_backend.application import company_tax_delivery_preparation as preparation
    url,_,cid,_,_=source_runtime
    app,command,_,_=configured(source_runtime)
    original=preparation.read_company_tax_delivery_source
    name='tax-source-writer-'+uuid4().hex
    reads=[];pending=[]
    def write():
        with psycopg.connect(url,application_name=name) as db:
            db.execute("set local statement_timeout='10s'")
            db.execute("update public.annual_data set updated_at=updated_at+interval '1 microsecond' where company_id=%s",(cid,))
    with ThreadPoolExecutor(max_workers=1) as pool:
        async def final_snapshot(*args,**kwargs):
            source=await original(*args,**kwargs)
            reads.append(source)
            if len(reads)==2:
                pending.append(pool.submit(write))
                waiting=False
                for _ in range(100):
                    with psycopg.connect(url,autocommit=True) as probe:
                        waiting=probe.execute("select exists(select 1 from pg_stat_activity where application_name=%s and wait_event='advisory')",(name,)).fetchone()[0]
                    if waiting:break
                    await asyncio.sleep(.01)
                assert waiting,'Final source read and draft commit must share a held company guard.'
                assert not pending[0].done()
            return source
        monkeypatch.setattr(preparation,'read_company_tax_delivery_source',final_snapshot)
        async def exercise():
            return await (await app.session('synthetic-fixture')).prepare_delivery_draft(command)
        result=asyncio.run(exercise())
        pending[0].result(timeout=5)
    assert len(reads)==2 and reads[0]==reads[1]==result.draft.envelope.source
