"""Owned PG17 event admission mechanics; no provider or authenticated UI claim."""
import asyncio
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC,datetime,timedelta
import json
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from talli_backend.modules.annual_accounts_filing.public import AnnualAccountsError,AnnualAccountsSourceQuery,project_annual_accounts_source,StoredAnnualAccountsDeliveryEvent,decode_annual_accounts_delivery_record
from talli_backend.shared.kernel import Timestamp,IncomeYear
from test_annual_accounts_delivery_records import binding,review,admission,intent,Stage,Action,Completion
from test_annual_accounts_delivery_store_database import accounts_database,draft,draft_database,database,session,store,writes,fresh,ACTOR,COMPANY

pytestmark=pytest.mark.accounts_database
ROOT=Path(__file__).resolve().parents[3]
MIGRATION='20261026232554_annual_accounts_delivery_events_v1.sql'


@pytest.fixture(scope='module')
def event_database(accounts_database):
    with psycopg.connect(**accounts_database,user='postgres',autocommit=True) as db:
        memberships='select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3'
        before=db.execute(memberships).fetchall();db.execute((ROOT/'supabase/contract-migrations'/MIGRATION).read_text())
        assert db.execute(memberships).fetchall()==before
    return accounts_database


async def append(database,record,*,aal='aal2'):
    async with session(database,aal=aal).transaction() as tx:
        row=await tx._one_row('select annual_accounts_filing.append_delivery_event_v1(%s,%s,%s) as result',
            (record.canonical_json,record.sha256,str(ACTOR.subject)))
        value=row['result'];event=value['event']
        assert decode_annual_accounts_delivery_record(event['canonical_json'],event['event_sha256'])==record
        return value


@contextmanager
def operations(database):
    def flag(value):
        with psycopg.connect(**database,user='postgres',autocommit=True) as db:
            db.execute('set role annual_accounts_filing_store_owner')
            db.execute("create or replace function annual_accounts_filing.delivery_operations_enabled_v1() returns boolean "
                "language plpgsql volatile security invoker set search_path='' as $$begin return "+str(value).lower()+"; end;$$")
    flag(True)
    try:yield
    finally:flag(False)


def prepared(database,draft):
    value=fresh(draft)
    with writes(database):asyncio.run(store(database,value))
    return value


def approval(draft):return replace(review(draft),reviewed_evidence_sha256=draft.sha256,reviewed_at=Timestamp(datetime.now(UTC)))


def grant(database,draft,approval):
    value=admission(draft,approval=approval);now=Timestamp(datetime.now(UTC))
    return replace(value,issued_at=now,expires_at=Timestamp(now.value+timedelta(seconds=300)))


def test_event_expansion_keeps_new_operations_closed(event_database,draft):
    value=prepared(event_database,draft)
    with pytest.raises(AnnualAccountsError):asyncio.run(append(event_database,approval(value)))


def test_canonical_review_and_admission_roundtrip_with_exact_replay(event_database,draft):
    value=prepared(event_database,draft);checked=approval(value)
    async def exercise():return await asyncio.gather(append(event_database,checked),append(event_database,checked))
    with operations(event_database):first,second=asyncio.run(exercise())
    assert sorted((first['inserted'],second['inserted']))==[False,True]
    assert first['event']==second['event']
    admitted=grant(event_database,value,checked)
    with operations(event_database):result=asyncio.run(append(event_database,admitted))
    assert result['inserted'] is True
    async def read():
        async with session(event_database).transaction(snapshot=True) as tx:
            return (await tx._one_row('select annual_accounts_filing.read_source_snapshot_v3(%s,2025,%s) as result',
                (str(COMPANY),str(ACTOR.subject))))['result']
    source=asyncio.run(read())
    assert source['contractVersion']=='annual-accounts-source-v3'
    assert source['coverage']['deliveryEventCount']==len(source['deliveryEvents'])
    assert source['coverage']['deliveryEventContractValid'] is True
    assert source['coverage']['deliveryEventDigests']=={str(row['sequence']):row['event_sha256'] for row in source['deliveryEvents']}
    async def typed():
        async with session(event_database).transaction() as tx:
            stored,inserted=await tx.append_delivery_event(admitted)
            assert stored.record==admitted and inserted is False
        async with session(event_database).transaction(snapshot=True) as tx:
            query=AnnualAccountsSourceQuery(COMPANY,IncomeYear(2025),ACTOR)
            snapshot=await tx.filing_source_snapshot(query)
            assert snapshot.contract_version=='annual-accounts-source-v3'
            assert len(snapshot.delivery_events)==len(source['deliveryEvents'])
            assert project_annual_accounts_source(query,snapshot).history_coverage.status=='complete'
    asyncio.run(typed())


def test_new_review_requires_current_owner_and_mfa(event_database,draft):
    value=prepared(event_database,draft);checked=approval(value)
    with operations(event_database),pytest.raises(AnnualAccountsError):asyncio.run(append(event_database,checked,aal='aal1'))


def test_intent_requires_its_retained_review_and_finite_admission(event_database,draft):
    value=prepared(event_database,draft);checked=approval(value);admitted=grant(event_database,value,checked)
    request=replace(intent(value,Action.CREATE_INSTANCE,checked,admitted),prerequisite_sha256=value.sha256)
    with operations(event_database),pytest.raises(AnnualAccountsError):asyncio.run(append(event_database,request))
    # Build a full synthetic effect graph, but retain every original through
    # native restricted RPCs. Native commit times and identity sequence replace
    # the unit clock; dependent record hashes are rebound as each row commits.
    from test_annual_accounts_delivery_journal import complete_world
    from talli_backend.modules.annual_accounts_filing.public import (
        AnnualAccountsDeliveryReview as Review,AnnualAccountsFiniteAdmission as Admission,
        AnnualAccountsDeliveryIntent as Intent,AnnualAccountsDeliveryObservation as Observation,
        AnnualAccountsDeliveryFrameRecord as Frame,inspect_annual_accounts_delivery_journal,
    )
    from talli_backend.adapters.annual_accounts_schemas import PinnedAnnualAccountsSchemas
    expected=complete_world(value);mapped={};events=[]
    with operations(event_database):
        for event in expected.events:
            record=event.record;changes={};now=Timestamp(datetime.now(UTC))
            for name in ('review_sha256','admission_sha256','intent_sha256','prerequisite_sha256','dependency_intent_sha256'):
                old=getattr(record,name,None)
                if old in mapped:changes[name]=mapped[old]
            if type(record) is Review:changes['reviewed_at']=now
            elif type(record) is Admission:changes.update(issued_at=now,expires_at=Timestamp(now.value+timedelta(seconds=300)))
            elif type(record) is Observation:changes['original']=replace(record.original,requested_at=now,observed_at=now)
            elif type(record) is Frame:changes['observation_sha256']=tuple(mapped[ref] for ref in record.observation_sha256)
            rebound=replace(record,**changes)
            if (type(record) is Observation and record.original.purpose.value=='pdf'
                    and not any(type(row.record) is Observation and row.record.original.purpose.value=='pdf'
                        and row.record.original.data_id==record.original.data_id for row in events)):
                learned=next(row.record.original.observed_at.value for row in reversed(events)
                    if type(row.record) is Observation and row.record.original.purpose.value=='instance')
                dependency=next(row.recorded_at.value for row in events if row.record.sha256==rebound.intent_sha256)
                premature=Timestamp(dependency+(learned-dependency)/2)
                invalid=replace(rebound,original=replace(rebound.original,requested_at=premature))
                with pytest.raises(AnnualAccountsError):asyncio.run(append(event_database,invalid))
            result=asyncio.run(append(event_database,rebound))
            assert result['inserted'] is True;mapped[record.sha256]=rebound.sha256
            from talli_backend.adapters.postgres_annual_accounts import PostgresAnnualAccountsTransaction
            events.append(PostgresAnnualAccountsTransaction._stored_delivery_event(result['event']))
            assert asyncio.run(append(event_database,rebound))['inserted'] is False
    with psycopg.connect(**event_database,user='postgres',autocommit=True) as db:
        row=db.execute('select recorded_at from annual_accounts_filing.delivery_drafts where id=%s',(value.filing_id,)).fetchone()
    from talli_backend.modules.annual_accounts_filing.public import StoredAnnualAccountsDeliveryDraft
    stored=StoredAnnualAccountsDeliveryDraft(value,Timestamp(row[0]))
    result=inspect_annual_accounts_delivery_journal(stored,events,schemas=PinnedAnnualAccountsSchemas(),
        expected_event_digests={str(row.sequence):row.record.sha256 for row in events})
    assert result.state=='technical_archive' and result.next_action is None
    # Containment rollback preserves originals/late capture, not fresh review.
    with psycopg.connect(**event_database,user='postgres',autocommit=True) as db:
        db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
        db.execute('delete from public.tax_draft_fixture_owner where company=%s',(str(COMPANY),))
    try:
        sign=next(row.record for row in events if row.record.slot=='intent:sign')
        late=Completion(binding(value),Action.SIGN,sign.sha256,None,None,None,'connection_lost')
        assert asyncio.run(append(event_database,late,aal='aal1'))['inserted'] is True
        async def forbidden():
            async with session(event_database).transaction(snapshot=True) as tx:
                return await tx.filing_source_snapshot(AnnualAccountsSourceQuery(COMPANY,IncomeYear(2025),ACTOR))
        with pytest.raises(AnnualAccountsError):asyncio.run(forbidden())
    finally:
        with psycopg.connect(**event_database,user='postgres',autocommit=True) as db:
            db.execute('insert into public.tax_draft_fixture_owner values(%s,%s)',(str(COMPANY),str(ACTOR.subject)))


@pytest.mark.parametrize('defect',['constraint','helper','policy','public-execute'])
def test_same_named_weakened_contract_is_not_positive_coverage(event_database,defect):
    async def contract():
        async with session(event_database).transaction(snapshot=True) as tx:
            value=await tx.filing_source_snapshot(AnnualAccountsSourceQuery(COMPANY,IncomeYear(2025),ACTOR))
            return value.coverage['deliveryEventContractValid']
    assert asyncio.run(contract()) is True
    with psycopg.connect(**event_database,user='postgres',autocommit=True) as db:
        if defect=='constraint':
            definition=db.execute("select pg_get_constraintdef(oid) from pg_constraint where conrelid='annual_accounts_filing.delivery_events'::regclass and conname='accounts_delivery_event_scope'").fetchone()[0]
            db.execute('alter table annual_accounts_filing.delivery_events drop constraint accounts_delivery_event_scope')
            db.execute('alter table annual_accounts_filing.delivery_events add constraint accounts_delivery_event_scope check(true)')
            restore=['alter table annual_accounts_filing.delivery_events drop constraint accounts_delivery_event_scope',
                'alter table annual_accounts_filing.delivery_events add constraint accounts_delivery_event_scope '+definition]
        elif defect=='helper':
            restore=[db.execute("select pg_get_functiondef('annual_accounts_filing.delivery_known_file_v1(uuid,text,text,text,timestamptz)'::regprocedure)").fetchone()[0]]
            db.execute("create or replace function annual_accounts_filing.delivery_known_file_v1(p_filing uuid,p_instance text,p_data text,p_purpose text,p_requested_at timestamptz default null) returns boolean language sql volatile security invoker set search_path='' as $$select true$$")
        elif defect=='policy':
            expression=db.execute("select pg_get_expr(polwithcheck,polrelid) from pg_policy where polrelid='annual_accounts_filing.delivery_events'::regclass and polname='accounts_delivery_event_insert'").fetchone()[0]
            db.execute('alter policy accounts_delivery_event_insert on annual_accounts_filing.delivery_events with check(true)')
            restore=['alter policy accounts_delivery_event_insert on annual_accounts_filing.delivery_events with check('+expression+')']
        else:
            db.execute('grant execute on function annual_accounts_filing.append_delivery_event_v1(text,text,text) to public')
            restore=['revoke execute on function annual_accounts_filing.append_delivery_event_v1(text,text,text) from public']
        try:assert asyncio.run(contract()) is False
        finally:
            for statement in restore:db.execute(statement)
    assert asyncio.run(contract()) is True


def test_unrelated_second_root_intent_cannot_fork_company_year(event_database,draft):
    value=prepared(event_database,draft);checked=approval(value)
    with operations(event_database):
        asyncio.run(append(event_database,checked));admitted=grant(event_database,value,checked)
        asyncio.run(append(event_database,admitted))
        request=replace(intent(value,Action.CREATE_INSTANCE,checked,admitted),prerequisite_sha256=value.sha256)
        with pytest.raises(AnnualAccountsError):asyncio.run(append(event_database,request))
