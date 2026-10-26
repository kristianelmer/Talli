"""Restricted PG17 + actual finite HTTP validation and known-job originals.

Owning-source/signed-JWT topology remains a separate gate; no real provider.
"""
import asyncio
from contextlib import asynccontextmanager
import threading

import psycopg
import pytest

from talli_backend.adapters.company_tax_response_schemas import PinnedTaxValidationResponseSchemas
from talli_backend.modules.company_tax_filing.public import CompanyTaxError,TaxMutationKind
from test_company_tax_delivery import ACTOR,COMPANY
from test_postgres_tax_validation_evidence import (
    database,draft_database,current_database,current_draft,current_session,events_database,observation_database,
    upload_database,validation_database,draft,enable_validation,
)
from test_postgres_tax_upload_submission import upload_http,create,NATIVE_JOB
from test_postgres_tax_delivery_submission import journal
from test_company_tax_validation_response_schemas import xml

pytestmark=pytest.mark.company_tax_database


@pytest.fixture
def validation_http(validation_database,upload_http):
    enable_validation(validation_database)
    _,service,_,state,_=upload_http
    service._response_schemas=PinnedTaxValidationResponseSchemas()
    state['scan']='Clean';state['validationResult']=b'\xef\xbb\xbf'+xml()+b'\n'
    return upload_http


async def uploaded(fixture,*,session=None):
    inner,service,*_=fixture;session=session or inner
    command,created=await create(fixture,session=session)
    upload=await service.advance_upload(session,command)
    assert upload.status=='mutation_completed'
    return command,created,upload


def test_actual_validation_post_follows_commit_and_known_job_reads_keep_every_original(validation_http):
    session,service,_,state,_=validation_http
    async def exercise():
        command,creation,upload=await uploaded(validation_http)
        result=await service.advance_validation(session,command)
        assert result.status=='mutation_completed' and result.mutation_kind is TaxMutationKind.START_VALIDATION
        before=len(state['calls'])
        assert await service.advance_validation(session,command)==result
        assert await service.advance_upload(session,command)==upload
        assert await service.reconcile(session,command)==creation
        assert len(state['calls'])==before
        assert await service.reconcile_validation(session,command)==result
        assert state['calls'][-2:][0][1].endswith('/'+NATIVE_JOB+'/status')
        assert state['calls'][-1][1].endswith('/'+NATIVE_JOB+'/resultat')
        first=await journal(session,command)
        assert next(event.value for event in first.events if event.slot=='completion:start_validation').response_bytes.startswith(b'\xef\xbb\xbf')
        assert first.events[-1].value.original.raw_bytes==state['validationResult']
        assert first.events[-1].value.inspect(service._response_schemas).result_code.value=='validertOK'
        assert await service.reconcile_validation(session,command)==result
        assert (await journal(session,command)).events==first.events
    asyncio.run(exercise());assert state['validationPosts']==1


def test_lost_actual_start_response_never_looks_up_or_repeats_a_job(validation_http):
    session,service,_,state,_=validation_http
    async def exercise():
        command,*_=await uploaded(validation_http);state['lostValidation']=True
        result=await service.advance_validation(session,command)
        assert result.status=='uncertain'
        before=len(state['calls'])
        assert await service.advance_validation(session,command)==result
        assert await service.reconcile_validation(session,command)==result
        assert len(state['calls'])==before
        assert (await journal(session,command)).events[-1].slot=='intent:start_validation'
    asyncio.run(exercise());assert state['validationPosts']==1


@pytest.mark.parametrize('lost',['intent:start_validation','completion:start_validation'])
def test_actual_start_commit_ack_loss_never_repeats_post(validation_http,lost):
    inner,service,_,state,_=validation_http
    class Session:
        actor_id=inner.actor_id
        delivery_rehearsal_target=inner.delivery_rehearsal_target
        lose=True
        @asynccontextmanager
        async def transaction(self,*,snapshot=False):
            affected=False
            async with inner.transaction(snapshot=snapshot) as actual:
                class Transaction:
                    def __getattr__(self,name):return getattr(actual,name)
                    async def append_delivery_event(self,value):
                        nonlocal affected
                        result=await actual.append_delivery_event(value);affected=result.event.slot==lost;return result
                yield Transaction()
            if affected and self.lose:self.lose=False;raise CompanyTaxError.unavailable()
    session=Session()
    async def exercise():
        command,*_=await uploaded(validation_http,session=session)
        with pytest.raises(CompanyTaxError):await service.advance_validation(session,command)
        before=len(state['calls']);result=await service.advance_validation(session,command)
        assert result.status==('uncertain' if lost.startswith('intent:') else 'mutation_completed')
        assert len(state['calls'])==before
    asyncio.run(exercise());assert state['validationPosts']==(0 if lost.startswith('intent:') else 1)


def test_two_actual_clean_file_preflights_elect_one_validation_start(validation_http):
    session,service,_,state,_=validation_http
    async def exercise():
        command,*_=await uploaded(validation_http);state['parallel']=True
        pair=threading.Barrier(2);state['on_file']=lambda:pair.wait(timeout=5)
        results=await asyncio.wait_for(asyncio.gather(service.advance_validation(session,command),
            service.advance_validation(session,command)),timeout=15)
        assert any(result.status=='mutation_completed' for result in results)
        assert (await service.advance_validation(session,command)).status=='mutation_completed'
        assert sum(event.slot=='intent:start_validation' for event in (await journal(session,command)).events)==1
    asyncio.run(exercise());assert state['validationPosts']==1


def test_actual_revocation_during_start_keeps_known_result_but_blocks_new_job_read(validation_http):
    session,service,_,state,database=validation_http
    def revoke():
        with psycopg.connect(**database,user='postgres',autocommit=True) as db:
            db.execute('delete from public.tax_draft_fixture_owner where company=%s',(str(COMPANY),))
    async def exercise():
        command,*_=await uploaded(validation_http);state['on_validation']=revoke
        try:
            result=await service.advance_validation(session,command)
            assert result.status=='mutation_completed'
            before=len(state['calls'])
            with pytest.raises(CompanyTaxError):await service.reconcile_validation(session,command)
            assert len(state['calls'])==before
        finally:
            with psycopg.connect(**database,user='postgres',autocommit=True) as db:
                db.execute('insert into public.tax_draft_fixture_owner values(%s,%s)',(str(COMPANY),str(ACTOR.subject)))
        assert (await journal(session,command)).events[-1].slot=='completion:start_validation'
    asyncio.run(exercise())
