"""RF's published opening reads retain exact year and quarantine semantics."""
import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
import pytest

from test_annual_purchase_basis_runtime import admitted, DATABASE_URL
from test_rf1086_database_runtime import backend_url, rf_fixture_admin_access
from test_rf1086_year_source_database import session
from test_rf1086_source_company_guard_database import waiting
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId, IncomeYear

pytestmark = pytest.mark.authority_database


@pytest.fixture(autouse=True)
def remove_only_annual_opening_fixture(admitted, backend_url):
    """Incomplete synthetic openings must not escape into global rollback tests."""
    yield
    with psycopg.connect(DATABASE_URL) as db:
        db.execute("delete from shareholder_register_filing.migration_quarantine where company_id=%s and family in ('opening_balance_setups','opening_shareholders')", (admitted['company'],))
        db.execute('set local role shareholder_register_filing_store_owner')
        db.execute('alter table shareholder_register_filing.opening_shareholders no force row level security')
        db.execute('alter table shareholder_register_filing.opening_balance_setups no force row level security')
        db.execute('delete from shareholder_register_filing.opening_shareholders where company_id=%s', (admitted['company'],))
        db.execute('delete from shareholder_register_filing.opening_balance_setups where company_id=%s', (admitted['company'],))
        db.execute('alter table shareholder_register_filing.opening_shareholders force row level security')
        db.execute('alter table shareholder_register_filing.opening_balance_setups force row level security')


def query(fixture, store):
    return rf.Rf1086SourceQuery(CompanyId(str(fixture['company'])), IncomeYear(2026), store.actor_id)


def add_opening(db, fixture, year=2026):
    identity, holder = uuid4(), uuid4()
    db.execute('set local role shareholder_register_filing_store_owner')
    db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s::text,true)",
               (str(fixture['owner']), Jsonb({'sub': str(fixture['owner']), 'role': 'authenticated', 'aal': 'aal2'})))
    db.execute('insert into shareholder_register_filing.opening_balance_setups(id,company_id,income_year,share_capital,share_count,nominal_value,created_by) values(%s,%s,%s,%s,3,%s,%s)',
               (identity, fixture['company'], year, Decimal('30000.03'), Decimal('10000.01'), fixture['owner']))
    db.execute("insert into shareholder_register_filing.opening_shareholders(id,setup_id,company_id,name,shareholder_kind,org_number,share_count,created_by) values(%s,%s,%s,'Synthetic shareholder AS','norwegian_company','930835978',3,%s)",
               (holder, identity, fixture['company'], fixture['owner']))
    db.execute('reset role')
    return identity, holder


def read(store, fixture):
    async def run():
        async with store.source_admission(query(fixture, store)) as scope:
            result = await scope.annual_opening_inputs()
        with pytest.raises(rf.ShareholderRegisterFilingError):
            await scope.annual_opening_inputs()
        return result
    return asyncio.run(run())


def test_exact_year_empty_and_digest_changes_without_rendering_no_activity(admitted, backend_url):
    store = session(admitted, backend_url)
    with psycopg.connect(DATABASE_URL) as db:
        add_opening(db, admitted, 2025)
    empty = read(store, admitted)
    assert empty.company_id == CompanyId(str(admitted['company'])) and empty.income_year == IncomeYear(2026)
    assert empty.opening_sources == ()
    with psycopg.connect(DATABASE_URL) as db:
        identity, holder = add_opening(db, admitted)
    first = read(store, admitted)
    assert str(first.opening_sources[0].opening_snapshot_id) == str(identity)
    assert first.opening_sources[0].shareholder_count == 1
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('set local role shareholder_register_filing_store_owner')
        db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s::text,true)",
                   (str(admitted['owner']), Jsonb({'sub': str(admitted['owner']), 'role': 'authenticated'})))
        db.execute("update shareholder_register_filing.opening_shareholders set name='Changed synthetic name' where id=%s", (holder,))
    assert read(store, admitted).opening_sources[0].source_digest != first.opening_sources[0].source_digest


def test_quarantined_holder_is_unavailable_not_successful_absence(admitted, backend_url):
    store = session(admitted, backend_url)
    with psycopg.connect(DATABASE_URL) as db:
        identity, _ = add_opening(db, admitted)
        db.execute("insert into shareholder_register_filing.migration_quarantine(company_id,income_year,family,record_id,reason,original_row) values(%s,2026,'opening_shareholders',%s,'synthetic incomplete holder',%s)",
                   (admitted['company'], uuid4(), Jsonb({'setup_id': str(identity)})))
    with pytest.raises(rf.ShareholderRegisterFilingError):
        read(store, admitted)


def test_opening_committed_while_admission_waits_is_observed(admitted, backend_url):
    store = session(admitted, backend_url)
    async def run():
        ready = asyncio.get_running_loop().create_future()
        original = store._transaction
        @asynccontextmanager
        async def observed(*args, **kwargs):
            async with original(*args, **kwargs) as db:
                ready.set_result((await (await db.execute('select pg_backend_pid() as pid')).fetchone())['pid'])
                yield db
        store._transaction = observed
        async def read_current():
            async with store.source_admission(query(admitted, store)) as scope:
                return await scope.annual_opening_inputs()
        task = None
        try:
            with psycopg.connect(DATABASE_URL) as blocker:
                blocker.execute('select public.company_archive_lock_company_v1(%s)', (admitted['company'],))
                task = asyncio.create_task(read_current())
                await waiting(await asyncio.wait_for(ready, 3))
                identity, _ = add_opening(blocker, admitted)
            result = await asyncio.wait_for(task, 3)
            assert str(result.opening_sources[0].opening_snapshot_id) == str(identity)
        finally:
            if task is not None and not task.done(): task.cancel()
            if task is not None: await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


def test_opening_holder_writer_cannot_change_evidence_while_admission_is_held(admitted, backend_url):
    store = session(admitted, backend_url)
    with psycopg.connect(DATABASE_URL) as db:
        _, holder = add_opening(db, admitted)
    async def run():
        ready = asyncio.get_running_loop().create_future()
        async def rename():
            async with await psycopg.AsyncConnection.connect(DATABASE_URL) as db:
                await db.execute('set local role shareholder_register_filing_store_owner')
                await db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s::text,true)",
                                 (str(admitted['owner']), Jsonb({'sub': str(admitted['owner']), 'role': 'authenticated'})))
                ready.set_result((await (await db.execute('select pg_backend_pid()')).fetchone())[0])
                await db.execute("update shareholder_register_filing.opening_shareholders set name='After held read' where id=%s", (holder,))
        task = None
        try:
            async with store.source_admission(query(admitted, store)) as scope:
                before = await scope.annual_opening_inputs()
                task = asyncio.create_task(rename())
                await waiting(await asyncio.wait_for(ready, 3))
                assert await scope.annual_opening_inputs() == before
                assert not task.done()
            await asyncio.wait_for(task, 3)
            async with store.source_admission(query(admitted, store)) as scope:
                assert await scope.annual_opening_inputs() != before
        finally:
            if task is not None and not task.done(): task.cancel()
            if task is not None: await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())
