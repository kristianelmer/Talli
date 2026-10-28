"""Owned PG17 successor contract; no hosted or provider activation."""
import asyncio
from dataclasses import replace
from datetime import UTC,datetime,timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from test_annual_accounts_delivery_events_database import event_database,operations,approval,grant,recreate_insert_policy
from test_annual_accounts_delivery_store_database import session,COMPANY,ACTOR,accounts_database,draft_database,database,draft,writes,store,fresh
from test_annual_accounts_delivery_journal import complete_world
from test_annual_accounts_delivery_corrections import changed_source
from test_annual_accounts_delivery_source import prepare
from test_annual_accounts_delivery_records import binding,intent,Action
from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsError,AnnualAccountsCorrectionReadGrant as Admission,AnnualAccountsAuthorityPort as Port,
    AnnualAccountsCorrectionParentAdmission as ParentAdmission,AnnualAccountsCorrectionParentAttempt as ParentAttempt,AnnualAccountsCorrectionParentObservation as ParentObservation,
    AnnualAccountsCorrectionParentFrame as ParentFrame,AnnualAccountsDeliveryFrameRecord as Frame,AnnualAccountsFrameKind as Kind,
    AnnualAccountsDeliveryObservation as Observation,AnnualAccountsDeliveryIntent as Intent,
    AnnualAccountsSourceQuery,project_annual_accounts_source,inspect_annual_accounts_delivery_history,
)
from talli_backend.shared.kernel import Timestamp,IncomeYear

pytestmark=pytest.mark.accounts_database
ROOT=Path(__file__).resolve().parents[3]
MIGRATION='20261027004007_annual_accounts_delivery_corrections_v1.sql'
PORTABLE_MIGRATION=ROOT/'supabase/migrations/20261028005310_annual_accounts_portable_delivery_contract.sql'
LEGACY_READER=ROOT/'apps/backend/tests/fixtures/accounts_delivery_v4_catalog_ids.sql'


@pytest.fixture(scope='module')
def correction_database(event_database):
    with psycopg.connect(**event_database,user='postgres',autocommit=True) as db:
        query='select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3'
        prior=db.execute(query).fetchall()
        db.execute((ROOT/'supabase/contract-migrations'/MIGRATION).read_text())
        assert db.execute(query).fetchall()==prior
    return event_database


def read(database):
    async def exercise():
        async with session(database).transaction(snapshot=True) as tx:
            return (await tx._one_row('select annual_accounts_filing.read_source_snapshot_v4(%s,2025,%s) as result',
                (str(COMPANY),str(ACTOR.subject))))['result']
    return asyncio.run(exercise())


def test_equivalent_recreated_policy_keeps_correction_contract_complete(correction_database):
    with psycopg.connect(**correction_database,user='postgres',autocommit=True) as db:
        recreate_insert_policy(db)
    assert read(correction_database)['coverage']['deliveryEventContractValid'] is True


def test_legacy_catalog_manifest_upgrades_and_survives_new_policy_ids(correction_database):
    with psycopg.connect(**correction_database,user='postgres',autocommit=True) as db:
        query="select pg_get_functiondef(oid),proowner,proacl::text from pg_proc where oid='annual_accounts_filing.read_source_snapshot_v4(uuid,integer,text)'::regprocedure"
        original=db.execute(query).fetchone()
        members='select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3'
        memberships=db.execute(members).fetchall()
        try:
            db.execute(LEGACY_READER.read_text())
            assert 'pg_catalog.to_jsonb(p)::text' in db.execute(query).fetchone()[0]
            assert read(correction_database)['coverage']['deliveryEventContractValid'] is True
            db.execute(PORTABLE_MIGRATION.read_text())
            assert db.execute(query).fetchone()==original
            assert db.execute(members).fetchall()==memberships
            recreate_insert_policy(db)
            assert read(correction_database)['coverage']['deliveryEventContractValid'] is True
        finally:
            db.execute('rollback')
            db.execute(original[0])


def test_upgrade_refuses_an_already_invalid_legacy_catalog_manifest(correction_database):
    with psycopg.connect(**correction_database,user='postgres',autocommit=True) as db:
        original=db.execute("select pg_get_functiondef('annual_accounts_filing.read_source_snapshot_v4(uuid,integer,text)'::regprocedure)").fetchone()[0]
        try:
            db.execute(LEGACY_READER.read_text())
            recreate_insert_policy(db)
            assert read(correction_database)['coverage']['deliveryEventContractValid'] is False
            with pytest.raises(psycopg.errors.RaiseException,match='annual_accounts_portable_contract_changed'):
                db.execute(PORTABLE_MIGRATION.read_text())
        finally:
            db.execute('rollback')
            db.execute(original)
    assert read(correction_database)['coverage']['deliveryEventContractValid'] is True


def test_portable_upgrade_preserves_an_already_attested_reader_and_role_grants(correction_database):
    with psycopg.connect(**correction_database,user='postgres',autocommit=True) as db:
        query="select pg_get_functiondef(oid),proowner,proacl::text from pg_proc where oid='annual_accounts_filing.read_source_snapshot_v4(uuid,integer,text)'::regprocedure"
        before=db.execute(query).fetchone()
        members='select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3'
        memberships=db.execute(members).fetchall()
        db.execute(PORTABLE_MIGRATION.read_text())
        assert db.execute(query).fetchone()==before
        assert db.execute(members).fetchall()==memberships
    assert read(correction_database)['coverage']['deliveryEventContractValid'] is True


def test_portable_upgrade_is_empty_before_the_capability_contract_exists(correction_database):
    name='accounts_portable_not_installed_'+uuid4().hex[:20]
    sql=PORTABLE_MIGRATION.read_text()
    body=sql.replace('\nbegin;\n','\n',1).removesuffix('commit;\n')
    with psycopg.connect(**correction_database,user='postgres',autocommit=True) as db:
        members='select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3'
        before=db.execute(members).fetchall()
        db.execute('begin')
        try:
            # A rollback-only namespace rename reproduces fresh-install lookup
            # without widening the fixture's postgres-only host authentication.
            db.execute('alter schema annual_accounts_filing rename to '+name)
            db.execute(body)
            assert db.execute("select to_regnamespace('annual_accounts_filing')").fetchone()[0] is None
            assert db.execute(members).fetchall()==before
        finally:
            db.execute('rollback')
    assert read(correction_database)['coverage']['deliveryEventContractValid'] is True


def test_portable_upgrade_borrows_only_required_set_authority(correction_database):
    role='accounts_portable_operator_'+uuid4().hex
    with psycopg.connect(**correction_database,user='postgres',autocommit=True) as db:
        db.execute('create role '+role+' nologin noinherit nobypassrls')
        db.execute('grant usage on schema annual_accounts_filing to '+role)
        try:
            db.execute('grant annual_accounts_filing_store_owner to '+role+' with admin true, inherit false, set false')
            query='select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members where member=%s::regrole order by 1,2,3'
            before=db.execute(query,(role,)).fetchall()
            db.execute('set role '+role)
            assert db.execute("select pg_has_role(current_user,'annual_accounts_filing_store_owner','SET')").fetchone()[0] is False
            db.execute(PORTABLE_MIGRATION.read_text())
            assert db.execute('select current_user').fetchone()[0]==role
            db.execute('reset role')
            assert db.execute(query,(role,)).fetchall()==before
        finally:
            db.execute('rollback')
            db.execute('reset role')
            db.execute('revoke usage on schema annual_accounts_filing from '+role)
            db.execute('drop role '+role)
    assert read(correction_database)['coverage']['deliveryEventContractValid'] is True


@pytest.mark.parametrize('defect',['predicate','policy-role','public-append','helper-owner','duplicate-policy-name'])
def test_portable_upgrade_never_rebaselines_changed_permission_meaning(correction_database,defect):
    sql=PORTABLE_MIGRATION.read_text()
    # Keep all intentional damage and the migration in one rollback-only test.
    assert sql.count('\nbegin;\n')==1 and sql.endswith('commit;\n')
    body=sql.replace('\nbegin;\n','\n',1).removesuffix('commit;\n')
    with psycopg.connect(**correction_database,user='postgres',autocommit=True) as db:
        db.execute('begin')
        try:
            if defect=='predicate':
                db.execute('alter policy accounts_delivery_event_insert on annual_accounts_filing.delivery_events with check(true)')
            elif defect=='policy-role':
                db.execute('alter policy accounts_delivery_event_insert on annual_accounts_filing.delivery_events to public')
            elif defect=='public-append':
                db.execute('grant execute on function annual_accounts_filing.append_delivery_event_v2(text,text,text) to public')
            elif defect=='helper-owner':
                db.execute('alter function annual_accounts_filing.delivery_creation_permitted_v2(uuid,uuid,integer) owner to postgres')
            else:
                db.execute('create policy accounts_delivery_event_insert on annual_accounts_filing.delivery_drafts for insert to annual_accounts_filing_store_owner with check(true)')
            with pytest.raises(psycopg.errors.RaiseException,match='annual_accounts_portable_contract_(changed|permission_mismatch)'):
                db.execute(body)
        finally:
            db.execute('rollback')
    assert read(correction_database)['coverage']['deliveryEventContractValid'] is True


def test_successor_captures_positive_contract_and_keeps_new_authority_closed(correction_database):
    result=read(correction_database)
    assert result['contractVersion']=='annual-accounts-source-v4'
    assert result['coverage']['deliveryEventCodecVersion']=='annual-accounts-delivery-events-v2'
    assert result['coverage']['deliveryEventContractValid'] is True
    assert result['coverage']['deliveryCorrectionsEnabled'] is False
    assert result['coverage']['deliveryOperationsEnabled'] is False
    assert result['coverage']['deliveryEventCount']==0 and result['coverage']['deliveryEventDigests']=={}


@pytest.mark.parametrize('defect',['helper','index','public-append','check','policy'])
def test_same_name_weakened_successor_evidence_is_incomplete(correction_database,defect):
    with psycopg.connect(**correction_database,user='postgres',autocommit=True) as db:
        if defect=='helper':
            original=db.execute("select pg_get_functiondef('annual_accounts_filing.delivery_creation_permitted_v2(uuid,uuid,integer)'::regprocedure)").fetchone()[0]
            db.execute("create or replace function annual_accounts_filing.delivery_creation_permitted_v2(p_filing uuid,p_company uuid,p_year integer) returns boolean language sql volatile security invoker set search_path='' as $$ select true $$")
            restore=lambda:db.execute(original)
        elif defect=='index':
            original=db.execute("select pg_get_indexdef('annual_accounts_filing.accounts_delivery_one_child_v1'::regclass)").fetchone()[0]
            db.execute('drop index annual_accounts_filing.accounts_delivery_one_child_v1')
            db.execute('create index accounts_delivery_one_child_v1 on annual_accounts_filing.delivery_events(company_id)')
            restore=lambda:(db.execute('drop index annual_accounts_filing.accounts_delivery_one_child_v1'),db.execute(original))
        elif defect=='public-append':
            db.execute('grant execute on function annual_accounts_filing.append_delivery_event_v2(text,text,text) to public')
            restore=lambda:db.execute('revoke execute on function annual_accounts_filing.append_delivery_event_v2(text,text,text) from public')
        elif defect=='check':
            original=db.execute("select pg_get_constraintdef(oid) from pg_constraint where conrelid='annual_accounts_filing.delivery_events'::regclass and conname='accounts_delivery_event_slots'").fetchone()[0]
            db.execute('alter table annual_accounts_filing.delivery_events drop constraint accounts_delivery_event_slots')
            db.execute('alter table annual_accounts_filing.delivery_events add constraint accounts_delivery_event_slots check(true)')
            restore=lambda:(db.execute('alter table annual_accounts_filing.delivery_events drop constraint accounts_delivery_event_slots'),db.execute('alter table annual_accounts_filing.delivery_events add constraint accounts_delivery_event_slots '+original))
        else:
            original=db.execute("select pg_get_expr(polwithcheck,polrelid) from pg_policy where polrelid='annual_accounts_filing.delivery_events'::regclass and polname='accounts_delivery_event_insert'").fetchone()[0]
            db.execute('alter policy accounts_delivery_event_insert on annual_accounts_filing.delivery_events with check(true)')
            restore=lambda:db.execute('alter policy accounts_delivery_event_insert on annual_accounts_filing.delivery_events with check('+original+')')
        try:assert read(correction_database)['coverage']['deliveryEventContractValid'] is False
        finally:restore()
    assert read(correction_database)['coverage']['deliveryEventContractValid'] is True


def test_committed_known_parent_reads_admit_one_fresh_child_and_rollback_retains_originals(correction_database,draft):
    parent=complete_world(fresh(draft));child=prepare(changed_source(parent.draft.source))
    with psycopg.connect(**correction_database,user='postgres',autocommit=True) as db:
        # Initial synthetic historical originals, not a fabricated readiness flag.
        db.execute('insert into annual_accounts_filing.delivery_drafts(id,company_id,income_year,prepared_by,command_key,canonical_json,draft_sha256,recorded_at) values(%s,%s,2025,%s,%s,%s,%s,%s)',
            (parent.draft.filing_id,str(COMPANY),str(ACTOR.subject),parent.draft.command_key.value,parent.draft.canonical_json,parent.draft.sha256,parent.stored.recorded_at.value))
        for row in parent.events:
            db.execute('insert into annual_accounts_filing.delivery_events(filing_id,company_id,income_year,recorded_by,slot,canonical_json,event_sha256,recorded_at) values(%s,%s,2025,%s,%s,%s,%s,%s)',
                (parent.draft.filing_id,str(COMPANY),str(ACTOR.subject),row.record.slot,row.record.canonical_json,row.record.sha256,row.recorded_at.value))
    with writes(correction_database):stored=asyncio.run(store(correction_database,child))
    sign=next(row.record for row in parent.events if type(row.record) is Intent and row.record.action is Action.SIGN)
    archive=next(row.record for row in reversed(parent.events) if type(row.record) is Frame and row.record.kind is Kind.ARCHIVE)
    now=Timestamp(datetime.now(UTC))
    lease=Admission(binding(child),Port.KNOWN_READ,str(uuid4()),child.source.organization_number,
        'http://127.0.0.1:23456','b'*64,'c'*64,now,Timestamp(now.value+timedelta(seconds=300)),27,None,parent.inspect().known_instance,None,sign.sha256)
    admitted=ParentAdmission(binding(child),binding(parent.draft),sign.sha256,archive.sha256,lease)
    async def append(record,*,aal="aal2"):
        async with session(correction_database,aal=aal).transaction() as tx:return await tx.append_delivery_event(record)
    with operations(correction_database),pytest.raises(AnnualAccountsError):asyncio.run(append(admitted))
    def correction_flag(enabled):
        with psycopg.connect(**correction_database,user='postgres',autocommit=True) as db:
            db.execute("set role annual_accounts_filing_store_owner")
            db.execute("create or replace function annual_accounts_filing.delivery_corrections_enabled_v1() returns boolean language plpgsql volatile security invoker set search_path='' as $$begin return "+str(enabled).lower()+"; end;$$")
    correction_flag(True)
    try:
        with operations(correction_database):
            event,inserted=asyncio.run(append(admitted));assert inserted
            assert asyncio.run(append(admitted))==(event,False)
            attempt=ParentAttempt(binding(child),str(uuid4()),admitted.sha256,Timestamp(datetime.now(UTC)))
            with pytest.raises(AnnualAccountsError):asyncio.run(append(attempt,aal='aal1'))
            assert asyncio.run(append(attempt))[1]
            observations=[];originals={row.record.sha256:row.record.original for row in parent.events if type(row.record) is Observation}
            failed_at=Timestamp(datetime.now(UTC));failed=replace(originals[archive.observation_sha256[0]],requested_at=failed_at,observed_at=failed_at,
                body_base64=None,content_type=None,http_status=None,failure_code='connection_lost')
            assert asyncio.run(append(ParentObservation(binding(child),str(uuid4()),admitted.sha256,attempt.sha256,failed)))[1]
            attempt=ParentAttempt(binding(child),str(uuid4()),admitted.sha256,Timestamp(datetime.now(UTC)))
            assert asyncio.run(append(attempt))[1]
            for ref in archive.observation_sha256:
                at=Timestamp(datetime.now(UTC));record=ParentObservation(binding(child),str(uuid4()),admitted.sha256,attempt.sha256,
                    replace(originals[ref],requested_at=at,observed_at=at))
                observations.append(record);assert asyncio.run(append(record))[1]
            lineage=ParentFrame(binding(child),str(uuid4()),attempt.sha256,binding(parent.draft),archive.sha256,tuple(row.sha256 for row in observations))
            assert asyncio.run(append(lineage))[1]
            checked=approval(child);assert asyncio.run(append(checked))[1]
            admitted_child=grant(correction_database,child,checked);assert asyncio.run(append(admitted_child))[1]
            create=replace(intent(child,Action.CREATE_INSTANCE,checked,admitted_child),prerequisite_sha256=child.sha256)
            attempt=ParentAttempt(binding(child),str(uuid4()),admitted.sha256,Timestamp(datetime.now(UTC)))
            assert asyncio.run(append(attempt))[1]
            with pytest.raises(AnnualAccountsError):asyncio.run(append(create))
            with pytest.raises(AnnualAccountsError):asyncio.run(append(replace(lineage,frame_id=str(uuid4()))))
            refreshed=[]
            for old in observations:
                at=Timestamp(datetime.now(UTC));row=replace(old,observation_id=str(uuid4()),attempt_sha256=attempt.sha256,original=replace(old.original,requested_at=at,observed_at=at))
                refreshed.append(row);assert asyncio.run(append(row))[1]
            assert asyncio.run(append(replace(lineage,frame_id=str(uuid4()),attempt_sha256=attempt.sha256,observation_sha256=tuple(row.sha256 for row in refreshed))))[1]
            assert asyncio.run(append(create))[1]
        async def snapshot():
            async with session(correction_database).transaction(snapshot=True) as tx:
                return await tx.filing_source_snapshot(AnnualAccountsSourceQuery(COMPANY,IncomeYear(2025),ACTOR))
        complete=asyncio.run(snapshot());query=AnnualAccountsSourceQuery(COMPANY,IncomeYear(2025),ACTOR)
        assert project_annual_accounts_source(query,complete).history_coverage.status=='complete'
        inspected=inspect_annual_accounts_delivery_history(complete.delivery_drafts,complete.delivery_events,schemas=parent.schemas,
            expected_event_digests=complete.coverage['deliveryEventDigests'])
        assert inspected[parent.draft.filing_id].state=='technical_archive' and inspected[child.filing_id].state=='creation_unknown'
        assert asyncio.run(append(replace(archive,frame_id=str(uuid4()))))[1]
        after_parent_read=asyncio.run(snapshot())
        inspected=inspect_annual_accounts_delivery_history(after_parent_read.delivery_drafts,after_parent_read.delivery_events,schemas=parent.schemas,
            expected_event_digests=after_parent_read.coverage['deliveryEventDigests'])
        assert inspected[child.filing_id].state=='creation_unknown'
        with psycopg.connect(**correction_database,user='postgres',autocommit=True) as db:
            before=db.execute('select canonical_json,event_sha256 from annual_accounts_filing.delivery_events order by sequence').fetchall()
            db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
            assert db.execute('select canonical_json,event_sha256 from annual_accounts_filing.delivery_events order by sequence').fetchall()==before
        assert read(correction_database)['coverage']['deliveryCorrectionsEnabled'] is False
        assert read(correction_database)['coverage']['deliveryEventContractValid'] is True
        # Response already in flight can still be captured after containment.
        original=observations[0].original
        assert asyncio.run(append(replace(observations[0],observation_id=str(uuid4()),original=original)))[1]
        with psycopg.connect(**correction_database,user='postgres',autocommit=True) as db:
            db.execute('delete from public.tax_draft_fixture_owner where company=%s',(str(COMPANY),))
        try:
            with pytest.raises(AnnualAccountsError):read(correction_database)
            assert asyncio.run(append(replace(observations[0],observation_id=str(uuid4())),aal='aal1'))[1]
        finally:
            with psycopg.connect(**correction_database,user='postgres',autocommit=True) as db:
                db.execute('insert into public.tax_draft_fixture_owner values(%s,%s)',(str(COMPANY),str(ACTOR.subject)))

    finally:correction_flag(False)
