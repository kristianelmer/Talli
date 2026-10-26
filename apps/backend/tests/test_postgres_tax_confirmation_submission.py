"""Restricted PG17 + actual HTTP confirmation PUT and read-only recovery."""
import asyncio
import threading

import psycopg
import pytest

from talli_backend.adapters.company_tax_calculated_schemas import PinnedTax2025CalculatedSchemas
from talli_backend.modules.company_tax_filing.public import TaxMutationKind
from test_postgres_tax_confirmation_evidence import (
    database,draft_database,current_database,current_draft,events_database,observation_database,upload_database,
    validation_database,confirmation_database,draft,enable_confirmation,
)
from test_postgres_tax_validation_submission import validation_http,uploaded
from test_postgres_tax_upload_submission import upload_http
from test_postgres_tax_delivery_submission import journal
from test_company_tax_calculated_schemas import documents,result
from test_company_tax_delivery import ACTOR,COMPANY

pytestmark=pytest.mark.company_tax_database


@pytest.fixture
def confirmation_http(confirmation_database,validation_http):
    enable_confirmation(confirmation_database)
    session,service,review,state,database=validation_http
    state.update(processTask='data',processElement='Task_1',processFlow=1,confirmationPuts=0,lostPreparation=False,
        on_confirmation=lambda:None,processResponse=b'\xef\xbb\xbf {"currentTask":{"altinnTaskType":"confirmation"}}\n')
    # The review names the exact draft stored by the owned real HTTP fixture.
    async def retained():
        from talli_backend.modules.company_tax_filing.public import CompanyTaxSourceQuery
        async with session.transaction(snapshot=True) as tx:return await tx.delivery_journal(
            CompanyTaxSourceQuery(COMPANY,review.income_year,ACTOR),str(review.filing_id))
    stored=asyncio.run(retained()).draft
    state['validationResult']=result(documents(stored)).raw_bytes
    service._calculated_schemas=PinnedTax2025CalculatedSchemas()
    return validation_http


async def validated(fixture):
    session,service,*_=fixture;command,creation,upload=await uploaded(fixture)
    validation=await service.advance_validation(session,command)
    assert validation.status=='mutation_completed'
    return command,creation,upload,validation


@pytest.mark.parametrize('lost',[False,True])
def test_actual_put_is_committed_once_and_complete_originals_recover_only_by_get(confirmation_http,lost):
    session,service,_,state,_=confirmation_http
    async def exercise():
        command,creation,upload,validation=await validated(confirmation_http);state['lostPreparation']=lost
        pending=await service.advance_confirmation(session,command)
        assert pending.status=='uncertain' and pending.mutation_kind is TaxMutationKind.PREPARE_CONFIRMATION
        assert state['confirmationPuts']==1
        count=len(state['calls']);assert await service.advance_confirmation(session,command)==pending
        assert len(state['calls'])==count
        completed=await service.reconcile_confirmation(session,command)
        assert completed.status=='mutation_completed' and all(method=='GET' for method,_ in state['calls'][count:])
        before=len(state['calls']);assert await service.reconcile_confirmation(session,command)==completed and len(state['calls'])==before
        assert await service.advance_validation(session,command)==validation
        assert await service.advance_upload(session,command)==upload
        assert await service.advance(session,command)==creation
        retained=await journal(session,command)
        if not lost:
            ack=next(event.value for event in retained.events if event.slot=='acknowledgment:prepare_confirmation')
            assert ack.original.raw_bytes==state['processResponse']
        proof=next(event.value for event in retained.events if event.slot=='completion:prepare_confirmation').confirmation_read_evidence
        assert proof.instance.original.raw_bytes.startswith(b'\xef\xbb\xbf')
        assert proof.envelope.original.raw_bytes==state['uploaded'] and state['confirmationPuts']==1
    asyncio.run(exercise())


def test_actual_concurrent_confirmation_attempts_elect_one_committed_put(confirmation_http):
    session,service,_,state,_=confirmation_http
    async def exercise():
        command,*_=await validated(confirmation_http)
        state['parallel']=True;barrier=threading.Barrier(2);state['on_job']=lambda:barrier.wait(timeout=10)
        results=await asyncio.wait_for(asyncio.gather(service.advance_confirmation(session,command),
            service.advance_confirmation(session,command),return_exceptions=True),timeout=30)
        assert all(not isinstance(result,BaseException) for result in results),[type(result).__name__ for result in results]
        assert results[0]==results[1] and state['confirmationPuts']==1
        assert sum(event.slot=='intent:prepare_confirmation' for event in (await journal(session,command)).events)==1
    asyncio.run(exercise())


def test_actual_known_put_acknowledgment_survives_owner_revocation(confirmation_http):
    session,service,_,state,database=confirmation_http
    async def exercise():
        command,*_=await validated(confirmation_http)
        def revoke():
            with psycopg.connect(**database,user='postgres',autocommit=True) as db:
                db.execute('delete from public.tax_draft_fixture_owner where company=%s',(str(COMPANY),))
        state['on_confirmation']=revoke
        try:
            pending=await service.advance_confirmation(session,command)
            assert pending.status=='uncertain' and state['confirmationPuts']==1
            with psycopg.connect(**database,user='postgres',autocommit=True) as db:
                assert db.execute("select count(*) from company_tax_filing.delivery_events where filing_id=%s and slot='acknowledgment:prepare_confirmation'",(str(command.filing_id),)).fetchone()==(1,)
        finally:
            with psycopg.connect(**database,user='postgres',autocommit=True) as db:
                db.execute('insert into public.tax_draft_fixture_owner values(%s,%s) on conflict do nothing',(str(COMPANY),str(ACTOR.subject)))
    asyncio.run(exercise())


def test_actual_parallel_reconcilers_share_one_completed_original_without_another_put(confirmation_http):
    session,service,_,state,_=confirmation_http
    async def exercise():
        command,*_=await validated(confirmation_http);await service.advance_confirmation(session,command)
        state['parallel']=True;barrier=threading.Barrier(2);state['on_file']=lambda:barrier.wait(timeout=10)
        results=await asyncio.wait_for(asyncio.gather(service.reconcile_confirmation(session,command),
            service.reconcile_confirmation(session,command),return_exceptions=True),timeout=30)
        assert all(not isinstance(result,BaseException) for result in results),[type(result).__name__ for result in results]
        assert results[0]==results[1] and results[0].status=='mutation_completed' and state['confirmationPuts']==1
        assert sum(event.slot=='completion:prepare_confirmation' for event in (await journal(session,command)).events)==1
    asyncio.run(exercise())


def test_actual_known_confirmation_result_survives_owner_change_during_final_file_get(confirmation_http):
    session,service,_,state,database=confirmation_http
    async def exercise():
        command,*_=await validated(confirmation_http);await service.advance_confirmation(session,command)
        def revoke():
            with psycopg.connect(**database,user='postgres',autocommit=True) as db:
                db.execute('delete from public.tax_draft_fixture_owner where company=%s',(str(COMPANY),))
        state['on_file']=revoke
        try:
            complete=await service.reconcile_confirmation(session,command)
            assert complete.status=='mutation_completed' and state['confirmationPuts']==1
        finally:
            with psycopg.connect(**database,user='postgres',autocommit=True) as db:
                db.execute('insert into public.tax_draft_fixture_owner values(%s,%s) on conflict do nothing',(str(COMPANY),str(ACTOR.subject)))
    asyncio.run(exercise())
