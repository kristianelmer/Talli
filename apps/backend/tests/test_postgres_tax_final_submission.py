"""Restricted PG17 + real HTTP final owner decision, races and late results."""
import asyncio
import threading

import psycopg
import pytest

from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError,ConfirmTaxDeliverySubmission,TaxDeliveryOwnerReviewQuery,TaxMutationKind,
)
from test_postgres_tax_submission_evidence import (
    database,draft_database,current_database,current_draft,events_database,observation_database,upload_database,
    validation_database,confirmation_database,submission_database,draft,enable_submission,
)
from test_postgres_tax_confirmation_submission import confirmation_http,validated
from test_postgres_tax_validation_submission import validation_http
from test_postgres_tax_upload_submission import upload_http
from test_postgres_tax_delivery_submission import journal
from test_company_tax_delivery import ACTOR,COMPANY

pytestmark=pytest.mark.company_tax_database


@pytest.fixture
def submission_http(submission_database,confirmation_http):
    enable_submission(submission_database)
    confirmation_http[3].update(submissionEnabled=True,submissionPuts=0,lostSubmission=False,on_submission=lambda:None)
    return confirmation_http


async def reviewed(fixture):
    session,service,*_=fixture;command,*_=await validated(fixture)
    await service.advance_confirmation(session,command);await service.reconcile_confirmation(session,command)
    artifact=await service.owner_review(session,TaxDeliveryOwnerReviewQuery(command.company_id,command.income_year,
        command.actor_id,str(command.filing_id),command.expected_approval_sha256,command.correlation_id))
    return ConfirmTaxDeliverySubmission(command.company_id,command.income_year,command.actor_id,command.filing_id,
        command.command_key,command.correlation_id,command.expected_approval_sha256,artifact.sha256,True,True),command


@pytest.mark.parametrize('lost',[False,True])
def test_actual_final_submission_has_one_committed_put_and_only_known_get_recovery(submission_http,lost):
    session,service,_,state,_=submission_http
    async def exercise():
        command,recovery=await reviewed(submission_http);state['lostSubmission']=lost
        pending=await service.advance_submission(session,command)
        assert pending.status=='uncertain' and state['confirmationPuts']==1 and state['submissionPuts']==1
        before=len(state['calls']);assert await service.advance_submission(session,command)==pending
        assert len(state['calls'])==before
        complete=await service.reconcile_submission(session,recovery)
        assert complete.status=='mutation_completed' and all(method=='GET' for method,_ in state['calls'][before:])
        state.update(terminal=True,receiptBytes=b'\xef\xbb\xbf <opaque-receipt/>\n\xff')
        assert await service.reconcile_feedback(session,recovery)==complete
        retained=await journal(session,recovery)
        original=next(event.value for event in retained.events if event.slot.startswith('observation:feedback:'))
        assert original.original.raw_bytes==state['receiptBytes'] and state['submissionPuts']==1
    asyncio.run(exercise())


def test_actual_concurrent_owner_actions_elect_one_submission_put(submission_http):
    session,service,_,state,_=submission_http
    async def exercise():
        command,_=await reviewed(submission_http);state['parallel']=True
        barrier=threading.Barrier(2);state['on_job']=lambda:barrier.wait(timeout=10)
        results=await asyncio.wait_for(asyncio.gather(service.advance_submission(session,command),
            service.advance_submission(session,command),return_exceptions=True),timeout=30)
        assert all(not isinstance(result,BaseException) for result in results),[type(result).__name__ for result in results]
        assert results[0]==results[1] and state['submissionPuts']==1
    asyncio.run(exercise())


def test_actual_parallel_submission_reconcilers_return_one_immutable_result(submission_http):
    session,service,_,state,_=submission_http
    async def exercise():
        command,recovery=await reviewed(submission_http);await service.advance_submission(session,command)
        state['parallel']=True;barrier=threading.Barrier(2);state['on_file']=lambda:barrier.wait(timeout=10)
        results=await asyncio.wait_for(asyncio.gather(service.reconcile_submission(session,recovery),
            service.reconcile_submission(session,recovery),return_exceptions=True),timeout=30)
        assert all(not isinstance(result,BaseException) for result in results),[type(result).__name__ for result in results]
        assert results[0]==results[1] and results[0].status=='mutation_completed' and state['submissionPuts']==1
    asyncio.run(exercise())


@pytest.mark.parametrize('stage',['submission','feedback'])
def test_actual_known_ack_or_receipt_survives_revocation_during_provider_io(submission_http,stage):
    session,service,_,state,database=submission_http
    def revoke():
        with psycopg.connect(**database,user='postgres',autocommit=True) as db:
            db.execute('delete from public.tax_draft_fixture_owner where company=%s',(str(COMPANY),))
    async def exercise():
        command,recovery=await reviewed(submission_http)
        if stage=='submission':state['on_submission']=revoke
        try:
            pending=await service.advance_submission(session,command)
            if stage=='submission':
                assert pending.status=='uncertain'
                with psycopg.connect(**database,user='postgres',autocommit=True) as db:
                    assert db.execute("select count(*) from company_tax_filing.delivery_events where filing_id=%s and slot='acknowledgment:confirm_submission'",(str(command.filing_id),)).fetchone()==(1,)
            else:
                complete=await service.reconcile_submission(session,recovery)
                state.update(terminal=True,receiptBytes=b'\xef\xbb\xbf <opaque-receipt/>\n\xff',on_feedback=revoke)
                assert await service.reconcile_feedback(session,recovery)==complete
                with psycopg.connect(**database,user='postgres',autocommit=True) as db:
                    assert db.execute("select count(*) from company_tax_filing.delivery_events where filing_id=%s and slot like 'observation:feedback:%%'",(str(command.filing_id),)).fetchone()==(1,)
            with pytest.raises(CompanyTaxError):await journal(session,recovery)
        finally:
            with psycopg.connect(**database,user='postgres',autocommit=True) as db:
                db.execute('insert into public.tax_draft_fixture_owner values(%s,%s) on conflict do nothing',(str(COMPANY),str(ACTOR.subject)))
        assert state['submissionPuts']==1
    asyncio.run(exercise())
