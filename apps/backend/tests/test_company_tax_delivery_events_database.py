"""Signed local Supabase JWTs and complete Company Access/Tax journal topology."""
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import hmac
import json
import os
import subprocess
import time
from urllib.parse import urlparse
from uuid import uuid4

import httpx
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo,conninfo_to_dict
from psycopg.types.json import Jsonb
import pytest
from fastapi.testclient import TestClient

from talli_backend.adapters.postgres_company_tax_filing import PostgresCompanyTaxAdapter
from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration
from talli_backend.main import create_app
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError,CompanyTaxSourceQuery,TaxDeliveryAuthorityMode,TaxMutationKind,
    approve_tax_delivery_review,build_tax_delivery_mutation_request,
    complete_tax_delivery_mutation,TaxDeliveryCompletionOrigin,
)
from talli_backend.shared.kernel import ActorId,ActorKind,CompanyId,IncomeYear,UserId
from test_shareholder_register_filing_lifecycle import company,insert
from test_company_tax_current_preparation_database import configured

pytestmark=pytest.mark.company_tax_database
ARCHIVE='/api/v1/company-tax/archive-source/delivery-journal-v1'


@pytest.fixture
def signed_runtime():
    url=os.environ.get('DATABASE_URL','');origin=os.environ.get('SUPABASE_URL','')
    assert urlparse(url).hostname in ('localhost','127.0.0.1','::1')
    assert urlparse(origin).hostname in ('localhost','127.0.0.1','::1')
    admin=os.environ['SUPABASE_SERVICE_ROLE_KEY'];anon=os.environ['SUPABASE_ANON_KEY']
    role='tax_journal_'+uuid4().hex;password=uuid4().hex;email=uuid4().hex+'@example.test'
    cid=owner=None
    with httpx.Client(base_url=origin+'/auth/v1/',timeout=10) as auth:
        def call(method,path,*,key=anon,token=None,body=None):
            response=auth.request(method,path,headers={'apikey':key,'Authorization':'Bearer '+(token or key)},json=body)
            assert response.status_code in (200,201),f'Local Auth fixture status {response.status_code}'
            return response.json()
        account=call('POST','admin/users',key=admin,body={'email':email,'password':password,'email_confirm':True})
        owner=account['id']
        try:
            initial=call('POST','token?grant_type=password',body={'email':email,'password':password})
            aal1=initial['access_token']
            factor=call('POST','factors',token=aal1,body={'factor_type':'totp','friendly_name':'Tax journal fixture'})
            challenge=call('POST','factors/'+factor['id']+'/challenge',token=aal1,body={})
            secret=factor['totp']['secret'];secret+='='*(-len(secret)%8)
            digest=hmac.new(base64.b32decode(secret),int(time.time()//30).to_bytes(8,'big'),hashlib.sha1).digest()
            offset=digest[-1]&15;code=str((int.from_bytes(digest[offset:offset+4],'big')&0x7fffffff)%1000000).zfill(6)
            elevated=call('POST','factors/'+factor['id']+'/verify',token=aal1,
                body={'challenge_id':challenge['id'],'code':code})
            token=elevated['access_token']
            payload=json.loads(base64.urlsafe_b64decode(token.split('.')[1]+'='*(-len(token.split('.')[1])%4)))
            assert payload['aal']=='aal2' and payload['sub']==owner
            with psycopg.connect(url) as db:
                assert db.execute('select phase from backend_system.company_tax_return_migration_state').fetchone()==('contracted',)
                cid,_=company(db,owner=owner)
                now=db.execute('select clock_timestamp()').fetchone()[0]
                insert(db,'public.annual_data',id=uuid4(),company_id=cid,income_year=2025,
                    answers=Jsonb({'company_tax_additional_attachments':'none','shareholder_loans':False,
                        'declared_owner_dividends':False,'bought_or_sold_shares':False}),
                    confirmations=Jsonb([]),no_activity_confirmed=True,annual_full_time_equivalents=0,
                    completed_by=owner,completed_at=now,updated_by=owner,updated_at=now)
                db.execute(sql.SQL('create role {} login noinherit nobypassrls password {}').format(sql.Identifier(role),sql.Literal(password)))
                db.execute(sql.SQL('grant company_tax_filing_workflow_executor,ledger_executor,investments_executor to {} with inherit false,set true').format(sql.Identifier(role)))
            backend=make_conninfo(url,user=role,password=password)
            actor=ActorId(ActorKind.USER,UserId(owner))
            sessions=PostgresCompanyTaxAdapter(LedgerSupabaseConfiguration(url=origin,anon_key=anon,database_url=backend))
            yield (url,backend,cid,actor,sessions),token,aal1
        finally:
            if cid is not None:
                with psycopg.connect(url) as db:
                    db.execute(sql.SQL('alter role {} nologin password null').format(sql.Identifier(role)))
                    db.execute('delete from public.annual_data where company_id=%s',(cid,))
                subprocess.run(['node','tests/support/tax-fixture-cleanup.mjs'],input=json.dumps([str(cid)]),
                    text=True,env={**os.environ,'DATABASE_URL':url},check=True)
                with psycopg.connect(url) as db:db.execute(sql.SQL('drop role {}').format(sql.Identifier(role)))
            if owner is not None:call('DELETE','admin/users/'+owner,key=admin)


def retained(signed_runtime):
    runtime,token,_=signed_runtime
    app,command,calls,original=configured(runtime)
    app._sessions=runtime[4]
    async def prepare():return await (await app.session(token)).prepare_delivery_draft(command)
    draft=asyncio.run(prepare()).draft
    approval=approve_tax_delivery_review(approval_id=str(uuid4()),draft=draft,approved_by=command.actor_id,
        expected_draft_sha256=draft.sha256,expected_review_sha256=draft.envelope.review_sha256,
        current_source=draft.envelope.source,current_document=draft.current_document,
        current_schema_sha256=draft.envelope.schema_sha256,authority_mode=TaxDeliveryAuthorityMode.FINITE_LOOPBACK,
        authority_context_sha256='c'*64)
    request=build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.CREATE_INSTANCE)
    async def store():
        session=await runtime[4].session(token)
        async with session.transaction() as tx:await tx.append_delivery_event(approval)
        async with session.transaction() as tx:await tx.append_delivery_event(request)
    asyncio.run(store())
    return app,draft,approval,request,original


def test_real_signed_owner_archive_retains_exact_unknown_journal_and_enforces_step_up(signed_runtime):
    runtime,token,aal1=signed_runtime;url,_,cid,actor,sessions=runtime
    _,draft,approval,request,original=retained(signed_runtime)
    client=TestClient(create_app(company_tax_session_factory=sessions))
    params={'companyId':str(cid),'incomeYear':2025};headers={'Authorization':'Bearer '+token}
    assert client.get(ARCHIVE,params=params).status_code==401
    assert client.get(ARCHIVE,params=params,headers={'Authorization':'Bearer '+aal1}).status_code==403
    assert client.get(ARCHIVE,params=params,headers={'Authorization':'Bearer '+token[:-1]+'!'}).status_code==401
    response=client.get(ARCHIVE,params=params,headers=headers)
    assert response.status_code==200
    archive=response.json();assert archive['draftCount']==1 and archive['eventCount']==2
    assert archive['sourceFacts']['historyCoverage']['status']=='complete'
    assert archive['sourceFacts']['evidence']['version']=='company-tax-source-v3:'+archive['sourceSha256']
    assert archive['drafts'][0]['canonicalJson']==draft.canonical_json
    assert [x['canonicalJson'] for x in archive['events']]==[approval.canonical_json,request.canonical_json]
    assert archive['journals'][0]['status']=='uncertain'
    assert archive['sourceFacts']['productionAttempts']==[]
    assert base64.b64decode(json.loads(archive['drafts'][0]['canonicalJson'])['draft']['current_document']['response']['raw_base64'])==original.raw_bytes
    with psycopg.connect(url) as db:
        generation=db.execute('select generation from public.company_archive_source_generations where company_id=%s and income_year=2025',(cid,)).fetchone()[0]
    assert generation>=3
    assert client.get(ARCHIVE,params=params|{'companyId':str(uuid4())},headers=headers).status_code==404


def test_signed_owner_revoked_while_archive_waits_is_denied(signed_runtime):
    runtime,token,_=signed_runtime;url,backend,cid,actor,sessions=runtime
    retained(signed_runtime)
    client=TestClient(create_app(company_tax_session_factory=sessions))
    with psycopg.connect(url) as blocker,ThreadPoolExecutor(max_workers=1) as workers:
        accepted=blocker.execute('select accepted_at from public.company_memberships where company_id=%s and user_id=%s',(cid,str(actor.subject))).fetchone()[0]
        blocker.execute('select public.company_archive_lock_company_v1(%s)',(cid,))
        future=workers.submit(client.get,ARCHIVE,params={'companyId':str(cid),'incomeYear':2025},headers={'Authorization':'Bearer '+token})
        try:
            waiting=False
            for _ in range(100):
                with psycopg.connect(url,autocommit=True) as probe:
                    waiting=probe.execute("select exists(select 1 from pg_stat_activity where usename=%s and wait_event='advisory')",(conninfo_to_dict(backend)['user'],)).fetchone()[0]
                if waiting:break
                time.sleep(.02)
            assert waiting
            blocker.execute('update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s',(cid,str(actor.subject)))
            blocker.commit()
            assert future.result(timeout=10).status_code==404
        finally:
            blocker.rollback()
            with psycopg.connect(url) as restore:restore.execute('update public.company_memberships set accepted_at=%s where company_id=%s and user_id=%s',(accepted,cid,str(actor.subject)))


def test_canonical_stale_mfa_denies_the_full_topology_archive(signed_runtime):
    runtime,_,_=signed_runtime;_,backend,cid,actor,_=runtime
    from test_company_tax_delivery_draft_database import MfaSessions
    sessions=MfaSessions(backend,actor);sessions.age=3600
    client=TestClient(create_app(company_tax_session_factory=sessions))
    response=client.get(ARCHIVE,params={'companyId':str(cid),'incomeYear':2025},headers={'Authorization':'Bearer synthetic-stale-fixture'})
    assert response.status_code==403


def test_signed_revoked_actor_can_retain_only_the_bound_late_result(signed_runtime):
    runtime,token,_=signed_runtime;url,_,cid,actor,sessions=runtime
    _,draft,approval,request,_=retained(signed_runtime)
    result=complete_tax_delivery_mutation(request,approval,draft,
        response_bytes=json.dumps({'id':'123456/'+str(uuid4())}).encode(),
        observed_at=draft.current_document.response.observed_at,origin=TaxDeliveryCompletionOrigin.MUTATION_RESPONSE)
    with psycopg.connect(url) as db:
        accepted=db.execute('select accepted_at from public.company_memberships where company_id=%s and user_id=%s',(cid,str(actor.subject))).fetchone()[0]
        db.execute('update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s',(cid,str(actor.subject)))
    try:
        async def exercise():
            session=await sessions.session(token)
            async with session.transaction() as tx:assert (await tx.append_delivery_event(result)).inserted
            async with session.transaction() as tx:assert not (await tx.append_delivery_event(result)).inserted
            next_request=build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.UPLOAD_ENVELOPE,
                target_instance=result.result['instanceId'])
            with pytest.raises(CompanyTaxError):
                async with session.transaction() as tx:await tx.append_delivery_event(next_request)
        asyncio.run(exercise())
    finally:
        with psycopg.connect(url) as db:db.execute('update public.company_memberships set accepted_at=%s where company_id=%s and user_id=%s',(accepted,cid,str(actor.subject)))
    response=TestClient(create_app(company_tax_session_factory=sessions)).get(ARCHIVE,
        params={'companyId':str(cid),'incomeYear':2025},headers={'Authorization':'Bearer '+token})
    assert response.status_code==200 and response.json()['events'][-1]['canonicalJson']==result.canonical_json
