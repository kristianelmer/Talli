"""Independent immutable observation lineages through actual restricted PostgreSQL."""
import asyncio
from dataclasses import replace
from pathlib import Path
from uuid import uuid4
import psycopg
import pytest
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId, IncomeYear, IdempotencyKey
from test_rf1086_year_source_database import session, DATABASE_URL, ROOT, seed_documents
from test_annual_purchase_basis_runtime import admitted
from test_rf1086_database_runtime import backend_url, rf_fixture_admin_access
from test_rf1086_register_observation import basis

pytestmark=pytest.mark.authority_database
MIGRATION='20260923102314_rf1086_register_observation_store.sql'

@pytest.fixture(autouse=True)
def cleanup_owned_fixture(admitted,rf_fixture_admin_access,backend_url):
    yield
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('set local role documents_store_owner')
        db.execute('delete from documents.evidence_references where company_id=%s',(admitted['company'],))
        db.execute('set local role shareholder_register_filing_store_owner')
        db.execute('alter table shareholder_register_filing.register_observations disable trigger register_observation_immutable')
        db.execute('alter table shareholder_register_filing.register_observations no force row level security')
        db.execute('delete from shareholder_register_filing.register_observations where company_id=%s',(admitted['company'],))
        db.execute('alter table shareholder_register_filing.register_observations force row level security')
        db.execute('alter table shareholder_register_filing.register_observations enable trigger register_observation_immutable')

def inputs(seed,store):
    c,ctx=basis();company=CompanyId(str(seed['company']));year=IncomeYear(2026)
    docs=seed_documents(seed,store,c.documents)
    return replace(c,company_id=company,income_year=year,actor_id=store.actor_id,effective_at=c.effective_at.replace(year=2026),documents=docs),replace(ctx,company_id=company,income_year=year,actor_id=store.actor_id,documents=docs)

def capture(s,c,ctx,key=None):return asyncio.run(s.record_register_observation(c,context=ctx,idempotency_key=key or IdempotencyKey(str(uuid4()))))
def query(c):return rf.Rf1086SourceQuery(c.company_id,c.income_year,c.actor_id)
def correction(c,first):return replace(c,supersedes_observation_id=first.observation_id,supersedes_observation_sha256=first.fact_sha256,correction_reason='Correct independently verified original')

def test_independent_lineages_and_current_exact_id_preserve_history(admitted,backend_url):
    s=session(admitted,backend_url);c,ctx=inputs(admitted,s);key=IdempotencyKey(str(uuid4()))
    first=capture(s,c,ctx,key);independent=capture(s,c,ctx)
    assert independent.version==1 and independent.observation_id!=first.observation_id
    second=capture(s,correction(c,first),ctx)
    assert second.version==2
    assert asyncio.run(s.read_current_register_observation(query(c),first.observation_id)) is None
    assert asyncio.run(s.read_register_observation(query(c),first.observation_id))==first
    assert asyncio.run(s.read_current_register_observation(query(c),independent.observation_id))==independent
    assert asyncio.run(s.read_current_register_observation(query(c),second.observation_id))==second
    assert capture(s,c,ctx,key)==first
    assert asyncio.run(s.list_register_observations(query(c)))==(first,independent,second)
    assert asyncio.run(s.list_register_observations(replace(query(c),income_year=IncomeYear(2025))))==()


def test_replay_normalization_and_key_conflict(admitted,backend_url):
    s=session(admitted,backend_url);c,ctx=inputs(admitted,s);key=IdempotencyKey(str(uuid4()));first=capture(s,c,ctx,key)
    assert capture(s,replace(c,documents=tuple(reversed(c.documents))),ctx,key)==first
    with pytest.raises(rf.Rf1086RegisterObservationError,match='idempotency_conflict'):
        capture(s,replace(c,effective_at=c.effective_at.replace(day=2)),ctx,key)


def test_concurrent_identical_and_correction_fork(admitted,backend_url):
    s=session(admitted,backend_url);c,ctx=inputs(admitted,s);key=IdempotencyKey(str(uuid4()))
    async def identical():return await asyncio.gather(*(session(admitted,backend_url).record_register_observation(c,context=ctx,idempotency_key=key) for _ in range(2)))
    first,again=asyncio.run(identical());assert first==again
    amended=correction(c,first)
    async def forks():return await asyncio.gather(*(session(admitted,backend_url).record_register_observation(amended,context=ctx,idempotency_key=IdempotencyKey(str(uuid4()))) for _ in range(2)),return_exceptions=True)
    result=asyncio.run(forks());assert sum(isinstance(x,rf.Rf1086RegisterObservationSnapshot) for x in result)==1
    assert sum(isinstance(x,rf.Rf1086RegisterObservationError) for x in result)==1


def test_wrong_predecessor_hash_company_year_and_owner_revocation(admitted,backend_url):
    s=session(admitted,backend_url);c,ctx=inputs(admitted,s);key=IdempotencyKey(str(uuid4()));first=capture(s,c,ctx,key)
    with pytest.raises(rf.Rf1086RegisterObservationError):capture(s,replace(correction(c,first),supersedes_observation_sha256='f'*64),ctx)
    assert asyncio.run(s.read_register_observation(replace(query(c),income_year=IncomeYear(2025)),first.observation_id)) is None
    outsider=session(admitted,backend_url,admitted['outsider'])
    with pytest.raises(rf.ShareholderRegisterFilingError):asyncio.run(outsider.read_register_observation(replace(query(c),actor_id=outsider.actor_id),first.observation_id))
    with psycopg.connect(DATABASE_URL) as db:db.execute("update public.company_memberships set role='read_only' where company_id=%s",(admitted['company'],))
    with pytest.raises(rf.ShareholderRegisterFilingError):capture(s,c,ctx,key)
    assert asyncio.run(s.read_register_observation(query(c),first.observation_id))==first
    with pytest.raises(rf.ShareholderRegisterFilingError):asyncio.run(s.list_register_observations(query(c)))
    with pytest.raises(rf.ShareholderRegisterFilingError):
        asyncio.run(outsider.list_register_observations(replace(query(c),actor_id=outsider.actor_id)))


def test_direct_mutation_denied_and_forced_rls(admitted,backend_url):
    s=session(admitted,backend_url);c,ctx=inputs(admitted,s);first=capture(s,c,ctx)
    async def mutate():
        async with s._transaction() as db:await db.execute('delete from shareholder_register_filing.register_observations where id=%s::uuid',(first.observation_id.value,))
    with pytest.raises(rf.ShareholderRegisterFilingError):asyncio.run(mutate())
    with psycopg.connect(DATABASE_URL) as db:
        assert db.execute("select relforcerowsecurity from pg_class where oid='shareholder_register_filing.register_observations'::regclass").fetchone()[0]
        for role in ('anon','authenticated','service_role'):
            assert not db.execute("select has_table_privilege(%s,'shareholder_register_filing.register_observations','SELECT')",(role,)).fetchone()[0]


def test_migration_replay_api_rollback_and_recutover_preserve_original(admitted,backend_url):
    s=session(admitted,backend_url);c,ctx=inputs(admitted,s);first=capture(s,c,ctx)
    with psycopg.connect(DATABASE_URL) as db:
        before=db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by roleid,member,grantor').fetchall()
        db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
        assert db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by roleid,member,grantor').fetchall()==before
    with psycopg.connect(DATABASE_URL) as db:db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
    with pytest.raises(rf.ShareholderRegisterFilingError):asyncio.run(s.read_register_observation(query(c),first.observation_id))
    with psycopg.connect(DATABASE_URL) as db:db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
    assert asyncio.run(s.read_current_register_observation(query(c),first.observation_id))==first


def test_changed_metadata_rolls_back_all_document_references_and_observation(admitted,backend_url):
    s=session(admitted,backend_url);c,ctx=inputs(admitted,s)
    bad=replace(c.documents[-1],metadata_sha256='e'*64)
    docs=c.documents[:-1]+(bad,);c=replace(c,documents=docs);ctx=replace(ctx,documents=docs)
    with pytest.raises(rf.ShareholderRegisterFilingError):capture(s,c,ctx)
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('set local role documents_store_owner')
        assert db.execute('select count(*) from documents.evidence_references where company_id=%s',(admitted['company'],)).fetchone()[0]==0
    async def count():
        async with s._transaction() as db:
            return (await (await db.execute('select count(*) as n from shareholder_register_filing.register_observations where company_id=%s',(admitted['company'],))).fetchone())['n']
    assert asyncio.run(count())==0


def test_late_rf_failure_rolls_back_successful_document_retention(admitted,backend_url):
    s=session(admitted,backend_url);c,ctx=inputs(admitted,s)
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('set local role shareholder_register_filing_store_owner')
        db.execute("create function shareholder_register_filing.fixture_reject_observation() returns trigger language plpgsql as $$begin raise exception 'fixture_late_reject'; end$$")
        db.execute('create trigger fixture_reject_observation before insert on shareholder_register_filing.register_observations for each row execute function shareholder_register_filing.fixture_reject_observation()')
    try:
        with pytest.raises(rf.ShareholderRegisterFilingError):capture(s,c,ctx)
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('set local role documents_store_owner')
            assert db.execute('select count(*) from documents.evidence_references where company_id=%s',(admitted['company'],)).fetchone()[0]==0
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('set local role shareholder_register_filing_store_owner')
            db.execute('drop trigger fixture_reject_observation on shareholder_register_filing.register_observations')
            db.execute('drop function shareholder_register_filing.fixture_reject_observation()')


def test_year_source_rechecks_observation_supersession_inside_capture_transaction(admitted,backend_url):
    from test_rf1086_year_source import basis as source_basis
    s=session(admitted,backend_url);oc,ox=inputs(admitted,s);observed=capture(s,oc,ox)
    command,context=source_basis('cash_issue')
    company=oc.company_id;year=oc.income_year
    case=replace(command.case,company=replace(command.case.company,income_year=int(year)),
        events=tuple(replace(event,timestamp=event.timestamp.replace(year=int(year))) for event in command.case.events))
    docs=seed_documents(admitted,s,command.documents);did=docs[0].document_id
    evidence=tuple(replace(e,event_sha256=rf.rf1086_year_source_digest(case.events[e.event_index]),document_ids=(did,)) for e in command.event_evidence)
    receipts=tuple(replace(r,company_id=company,income_year=year,
        economic_sha256=rf.rf1086_year_source_digest(rf.rf1086_governance_economic_facts(case.events[0])),
        register_observation_id=observed.observation_id.value,register_observation_sha256=observed.fact_sha256) for r in context.governance_receipts)
    command=replace(command,company_id=company,income_year=year,actor_id=s.actor_id,case=case,documents=docs,
        opening_document_ids=(did,),closing_document_ids=(did,),paid_in_document_ids=(did,),event_evidence=evidence)
    context=replace(context,company_id=company,income_year=year,actor_id=s.actor_id,company=case.company,
        documents=docs,governance_receipts=receipts)
    # The trusted external projection was assembled before the concurrent correction.
    capture(s,correction(oc,observed),ox)
    with pytest.raises(rf.Rf1086YearSourceError,match='register_observation_stale'):
        asyncio.run(s.record_year_source(command,context=context,idempotency_key=IdempotencyKey(str(uuid4()))))
    assert asyncio.run(s.read_current_year_source(query(command))) is None


def test_original_observation_blocks_frozen_predecessor_rehearsal(admitted,backend_url):
    from test_authority_connections_database_runtime import assert_retained_rf_original_refuses_predecessor_rehearsal
    store=session(admitted,backend_url);command,context=inputs(admitted,store)
    original=capture(store,command,context)
    assert_retained_rf_original_refuses_predecessor_rehearsal()
    assert asyncio.run(store.read_register_observation(query(command),original.observation_id))==original
