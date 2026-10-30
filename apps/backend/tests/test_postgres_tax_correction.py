"""Native correction codec, parent binding, fork election and containment."""
import asyncio
import concurrent.futures
import time
from dataclasses import replace
from datetime import datetime,UTC,timedelta
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from talli_backend.modules.company_tax_filing.public import (
    TaxDeliveryCorrectionParent,TaxDeliverySubmissionReadEvidence,CompanyTaxError,
    CompanyTaxSourceQuery,TaxDeliveryJournal,approve_tax_delivery_review,TaxDeliveryAuthorityMode,
    project_company_tax_source,assert_tax_delivery_attempt_history,TaxMutationKind,build_tax_delivery_mutation_request,TaxDeliveryMutationCompletion,
    TaxDeliveryCompletionOrigin,complete_tax_delivery_mutation,StoredTaxDeliveryEvent,
    TaxDeliveryAdmissionEvidence,TaxDeliveryReadOriginal,TaxDeliveryOriginalPurpose,
)
from talli_backend.shared.kernel import Timestamp,IdempotencyKey
from talli_backend.application.company_tax_delivery_rehearsal import TaxDeliveryRehearsalAdmission
from test_postgres_tax_final_submission import (
    database,draft_database,current_database,current_draft,events_database,observation_database,upload_database,
    validation_database,confirmation_database,submission_database,draft,enable_submission,
    submission_http,confirmation_http,validation_http,upload_http,reviewed,journal,
)
from test_company_tax_correction import child_draft
from test_company_tax_delivery import ACTOR,COMPANY

pytestmark=pytest.mark.company_tax_database
ROOT=Path(__file__).resolve().parents[3]
MIGRATION='20261026192349_company_tax_correction_lineage_v1.sql'


@pytest.fixture(scope='module')
def correction_database(submission_database):
    with psycopg.connect(**submission_database,user='postgres',autocommit=True) as db:
        members='select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3'
        before=db.execute(members).fetchall()
        db.execute((ROOT/'supabase/contract-migrations'/MIGRATION).read_text())
        assert db.execute(members).fetchall()==before
        assert db.execute('select company_tax_filing.correction_preparation_enabled_v1()').fetchone()==(False,)
        for role in ('snapshot_runtime','company_tax_filing_workflow_executor','anon','authenticated','service_role'):
            for function in ('assert_correction_parent_v1(jsonb,uuid)','guard_correction_draft_v1()','guard_delivery_frontier_v1()','correction_preparation_enabled_v1()','append_delivery_review_record_v1(text,text,text,text)'):
                assert db.execute('select has_function_privilege(%s,%s,%s)',(role,'company_tax_filing.'+function,'EXECUTE')).fetchone()==(False,)
    return submission_database


def enable_correction(database,enabled=True):
    with psycopg.connect(**database,user='postgres',autocommit=True) as db:
        db.execute('set role company_tax_filing_store_owner')
        db.execute('''create or replace function company_tax_filing.correction_preparation_enabled_v1() returns boolean
         language plpgsql volatile security invoker set search_path='' as $$ begin return '''+str(enabled).lower()+'''; end $$''')


@pytest.fixture
def correction_http(correction_database,submission_http):
    enable_correction(correction_database,False)
    return submission_http


@pytest.mark.parametrize(('fixture_name','version'),[
    ('events_database',3),('observation_database',4),('upload_database',5),
    ('validation_database',6),('confirmation_database',7),('submission_database',8),
    ('correction_database',9),
])
def test_default_facts_negotiate_the_installed_journal_extent(request,fixture_name,version):
    from test_postgres_tax_current_draft import current_session
    selected=request.getfixturevalue(fixture_name)
    from talli_backend.shared.kernel import IncomeYear
    query=CompanyTaxSourceQuery(COMPANY,IncomeYear(2025),ACTOR)
    async def exercise():
        async with current_session(selected).transaction(snapshot=True) as tx:
            snapshot=await tx.filing_source_snapshot(query)
        assert snapshot.contract_version==f'company-tax-source-v{version}'
        facts=project_company_tax_source(query,snapshot)
        assert facts.history_coverage.status=='complete',facts.history_coverage.reasons
        assert facts.hard_blocks==('company_tax_production_disabled',)
    asyncio.run(exercise())


async def candidate(fixture):
    session,service,_,state,_=fixture
    command,recovery=await reviewed(fixture)
    await service.advance_submission(session,command)
    state.update(terminal=True,receiptBytes=b'\xef\xbb\xbf <parent-receipt/>\n\xff')
    await service.reconcile_submission(session,recovery)
    parent=await journal(session,recovery)
    events={e.slot:e.value for e in parent.events};approval=parent.approval
    instance=await service._authority.observe_instance(approval,parent.draft,events['completion:create_instance'])
    feedback=await service._authority.observe_feedback(approval,parent.draft,events['completion:create_instance'],instance)
    envelope=await service._authority.observe_envelope(approval,parent.draft,events['completion:create_instance'],instance)
    pair={d.document_type:d.raw_bytes for d in events['intent:prepare_confirmation'].confirmation_prerequisite.calculated.response.calculated_documents}
    link=TaxDeliveryCorrectionParent(parent.draft.filing_id,parent.draft.sha256,approval.sha256,
        events['intent:confirm_submission'].sha256,events['completion:confirm_submission'].sha256,
        sha256(pair['skattemeldingUpersonligEtterBeregning']).hexdigest(),sha256(pair['naeringsspesifikasjonEtterBeregning']).hexdigest(),
        TaxDeliverySubmissionReadEvidence(instance,envelope,feedback))
    link.assert_parent(parent)
    return parent,child_draft(parent,link,pair,Timestamp(datetime.now(UTC)))


async def store(session,draft):
    async with session.transaction() as tx:return await tx.store_delivery_draft(draft)


async def review_child(session,child,context="d"*64):
    approval=approve_tax_delivery_review(approval_id=str(uuid4()),draft=child,approved_by=ACTOR,
        expected_draft_sha256=child.sha256,expected_review_sha256=child.envelope.review_sha256,
        current_source=child.envelope.source,current_document=child.current_document,current_schema_sha256=child.envelope.schema_sha256,
        authority_mode=TaxDeliveryAuthorityMode.FINITE_LOOPBACK,authority_context_sha256=context)
    async with session.transaction() as tx:assert (await tx.append_delivery_event(approval)).inserted
    return approval


def test_source9_reader_precedes_default_closed_preparation_then_exact_child_review_and_replay(correction_http):
    session,_,_,_,database=correction_http
    async def exercise():
        parent,child=await candidate(correction_http)
        with pytest.raises(CompanyTaxError):await store(session,child)
        enable_correction(database)
        first=await store(session,child);assert await store(session,child)==first
        assert first.draft.canonical_json==child.canonical_json
        approval=await review_child(session,child)
        async with session.transaction() as tx:
            with pytest.raises(CompanyTaxError):await tx._delivery_row('select company_tax_filing.append_delivery_event_v1(%s,%s,%s) as result',
                (approval.canonical_json,approval.sha256,str(ACTOR.subject)))
        query=CompanyTaxSourceQuery(COMPANY,child.envelope.source.income_year,ACTOR)
        async with session.transaction(snapshot=True) as tx:
            snapshot=await tx.journal_history_snapshot(query)
            facts=project_company_tax_source(query,snapshot)
            retained=await tx.delivery_journal(query,child.filing_id)
        assert snapshot.contract_version=='company-tax-source-v9' and facts.history_coverage.status=='complete'
        assert retained.draft==child and retained.correction_evidence and len(snapshot.delivery_drafts)==2
        assert parent.draft.canonical_json==next(row.draft.canonical_json for row in snapshot.delivery_drafts if row.draft.filing_id==parent.draft.filing_id)
    asyncio.run(exercise())


@pytest.mark.parametrize('change',['parent-draft','approval','request','completion','tax','business','receipt-hash','active','missing-receipt','stale','foreign'])
def test_raw_rehashed_correction_forgery_is_rejected_by_sql(correction_http,change):
    session,_,_,_,database=correction_http
    async def exercise():
        _,child=await candidate(correction_http);enable_correction(database)
        value=json.loads(child.canonical_json);link=value['draft']['correction_parent'];terminal=link['terminal']
        if change in ('parent-draft','approval','request','completion','tax','business'):
            field={'parent-draft':'draft_sha256','approval':'approval_sha256','request':'submission_request_sha256',
                'completion':'submission_completion_sha256','tax':'calculated_tax_sha256','business':'calculated_business_sha256'}[change]
            link[field]='d'*64
        elif change=='receipt-hash':terminal['feedback_sha256']='d'*64
        elif change=='missing-receipt':terminal['feedback_canonical_json']=terminal['feedback_sha256']=None
        elif change=='foreign':link['filing_id']=str(uuid4())
        else:
            embedded=json.loads(terminal['instance_canonical_json'])
            if change=='stale':embedded['observation']['observed_at']['value']='2025-01-01T00:00:00+00:00'
            else:
                import base64
                raw=json.loads(base64.b64decode(embedded['observation']['original']['body_base64']).decode('utf-8-sig'))
                raw['process']={'currentTask':{'altinnTaskType':'feedback','elementId':'Task_3','flow':3}}
                raw['status']={'isArchived':False}
                embedded['observation']['original']['body_base64']=base64.b64encode(json.dumps(raw).encode()).decode()
            terminal['instance_canonical_json']=json.dumps(embedded,sort_keys=True,separators=(',',':'),ensure_ascii=False)
            terminal['instance_sha256']=sha256(terminal['instance_canonical_json'].encode()).hexdigest()
        raw=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)
        async with session.transaction() as tx:
            with pytest.raises(CompanyTaxError):await tx._delivery_row('select company_tax_filing.store_delivery_draft_v3(%s,%s,%s) as result',
                (raw,sha256(raw.encode()).hexdigest(),str(ACTOR.subject)))
    asyncio.run(exercise())


def test_parallel_children_elect_one_and_existing_child_blocks_parent_and_new_root(correction_http):
    session,_,_,_,database=correction_http
    async def exercise():
        parent,child=await candidate(correction_http);enable_correction(database)
        other=replace(child,filing_id=str(uuid4()),command_key=IdempotencyKey(uuid4().hex))
        results=await asyncio.gather(store(session,child),store(session,other),return_exceptions=True)
        assert sum(not isinstance(row,BaseException) for row in results)==1
        assert sum(isinstance(row,CompanyTaxError) for row in results)==1
        # An unlinked V2 root remains a harmless stored candidate but cannot be reviewed.
        root=replace(parent.draft,filing_id=str(uuid4()),command_key=IdempotencyKey(uuid4().hex))
        await store(session,root)
        approval=replace(parent.approval,approval_id=str(uuid4()),filing_id=root.filing_id,draft_sha256=root.sha256)
        async with session.transaction() as tx:
            with pytest.raises(CompanyTaxError):await tx.append_delivery_event(approval)
    asyncio.run(exercise())


def test_containment_keeps_source9_and_exact_child_originals(correction_http):
    session,_,_,_,database=correction_http
    async def exercise():
        _,child=await candidate(correction_http);enable_correction(database);await store(session,child)
        with psycopg.connect(**database,user='postgres',autocommit=True) as db:db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
        with pytest.raises(CompanyTaxError):await store(session,replace(child,filing_id=str(uuid4()),command_key=IdempotencyKey(uuid4().hex)))
        query=CompanyTaxSourceQuery(COMPANY,child.envelope.source.income_year,ACTOR)
        async with session.transaction(snapshot=True) as tx:
            snapshot=await tx.journal_history_snapshot(query)
        assert snapshot.contract_version=='company-tax-source-v9'
        assert next(row.draft for row in snapshot.delivery_drafts if row.draft.filing_id==child.filing_id)==child
    asyncio.run(exercise())


def test_child_cannot_reuse_parent_instance_even_through_raw_completion_writer(correction_http):
    session,_,_,_,database=correction_http
    async def exercise():
        parent,child=await candidate(correction_http);enable_correction(database);await store(session,child)
        issued=Timestamp(datetime.now(UTC))
        grant=TaxDeliveryRehearsalAdmission(str(uuid4()),child.envelope.source.company_id,child.envelope.source.income_year,ACTOR,
            child.filing_id,child.sha256,child.envelope.source.organization_number,issued,Timestamp(issued.value+timedelta(minutes=5)),
            'http://127.0.0.1:41235','a'*64,session.delivery_rehearsal_target,10)
        approval=await review_child(session,child,grant.context_sha256)
        import base64
        admission=TaxDeliveryAdmissionEvidence(child.filing_id,approval.company_id,approval.income_year,ACTOR,approval.sha256,
            TaxDeliveryReadOriginal(TaxDeliveryOriginalPurpose.ADMISSION,base64.b64encode(grant.canonical_context.encode()).decode(),'application/json',None))
        async with session.transaction() as tx:assert (await tx.append_delivery_event(admission)).inserted
        request=build_tax_delivery_mutation_request(approval,child,TaxMutationKind.CREATE_INSTANCE)
        async with session.transaction() as tx:assert (await tx.append_delivery_event(request)).inserted
        identity=child.correction_parent.terminal.instance.instance_id
        raw=json.dumps({'id':identity}).encode();now=Timestamp(datetime.now(UTC))
        with pytest.raises(ValueError):complete_tax_delivery_mutation(request,approval,child,response_bytes=raw,
            observed_at=now,origin=TaxDeliveryCompletionOrigin.MUTATION_RESPONSE)
        import base64
        forged=TaxDeliveryMutationCompletion(request.intent(approval),{'instanceId':identity},base64.b64encode(raw).decode(),
            now,TaxDeliveryCompletionOrigin.MUTATION_RESPONSE)
        async with session.transaction() as tx:
            with pytest.raises(CompanyTaxError):await tx.append_delivery_event(forged)
    asyncio.run(exercise())


def test_correction_fence_is_rechecked_after_waiting_for_company_lock(correction_http):
    session,_,_,_,database=correction_http
    _,child=asyncio.run(candidate(correction_http));enable_correction(database)
    with psycopg.connect(**database,user='postgres') as blocker:
        blocker.execute('select public.company_archive_lock_company_v1(%s)',(str(COMPANY),))
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(lambda:asyncio.run(store(session,child)));waiting=False
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                with psycopg.connect(**database,user='postgres',autocommit=True) as db:
                    waiting=db.execute("select exists(select 1 from pg_stat_activity where wait_event_type='Lock' and query like '%store_delivery_draft_v3%' and pid<>pg_backend_pid())").fetchone()[0]
                if waiting:break
                time.sleep(.02)
            assert waiting
            enable_correction(database,False);blocker.commit()
            with pytest.raises(CompanyTaxError):pending.result(timeout=10)


def test_source9_never_claims_lineage_extent_with_a_disabled_frontier_guard(correction_http):
    session,_,_,_,database=correction_http
    async def exercise():
        parent,_=await candidate(correction_http)
        query=CompanyTaxSourceQuery(COMPANY,parent.draft.envelope.source.income_year,ACTOR)
        with psycopg.connect(**database,user='postgres',autocommit=True) as db:
            db.execute('set role company_tax_filing_store_owner')
            db.execute('alter table company_tax_filing.delivery_events disable trigger tax_delivery_frontier')
            try:
                async with session.transaction(snapshot=True) as tx:snapshot=await tx.journal_history_snapshot(query)
                facts=project_company_tax_source(query,snapshot)
                assert snapshot.coverage['declaredCorrectionExtentValid'] is False
                assert facts.history_coverage.status=='incomplete' and 'correction_source_contract_unproven' in facts.history_coverage.reasons
                async with session.transaction(snapshot=True) as tx:default=await tx.filing_source_snapshot(query)
                assert default.contract_version=='company-tax-source-v9'
                assert project_company_tax_source(query,default).history_coverage.status=='incomplete'
                with pytest.raises(CompanyTaxError):assert_tax_delivery_attempt_history(query,snapshot,parent.draft.filing_id)
            finally:db.execute('alter table company_tax_filing.delivery_events enable trigger tax_delivery_frontier')
    asyncio.run(exercise())
