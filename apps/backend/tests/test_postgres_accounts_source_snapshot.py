"""Real PG17: Accounts, Corporate and Ledger share one restricted MVCC read."""
import asyncio

import psycopg
from psycopg.rows import dict_row
import pytest

from talli_backend.adapters.postgres_annual_accounts import PostgresAnnualAccountsTransaction
from talli_backend.adapters.supabase_ledger import _verified_snapshot_rows
from talli_backend.modules.annual_accounts_filing.public import AnnualAccountsSourceQuery
from talli_backend.modules.ledger.public import LedgerError
from talli_backend.shared.kernel import IncomeYear
from test_postgres_tax_source_snapshot import database, verified, ACTOR, COMPANY

pytestmark=pytest.mark.accounts_database


async def bind(connection):
    await connection.execute('set transaction isolation level repeatable read')
    await connection.execute('set local role annual_accounts_filing_workflow_executor')
    await connection.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true)",
        (str(ACTOR.subject),verified().claims_json))


def test_owning_readers_share_rls_snapshot_and_restore_accounts_role(database):
    async def exercise():
        async with await psycopg.AsyncConnection.connect(**database,user='snapshot_runtime',row_factory=dict_row) as connection:
            async with connection.transaction():
                await bind(connection);transaction=PostgresAnnualAccountsTransaction(verified(),connection)
                corporate=transaction.delivery_corporate_queries;ledger=transaction.delivery_ledger_queries
                assert corporate._connection is ledger._connection is connection
                first=await corporate._database_rows('select amount,current_user as reader from snapshot_facts.rows')
                assert first==[{'amount':30,'reader':'corporate_governance_workflow_executor'}]
                with psycopg.connect(**database,user='postgres',autocommit=True) as writer:
                    writer.execute('update snapshot_facts.rows set amount=45 where subject=%s',(str(ACTOR.subject),))
                assert await ledger._database_rows('select amount from snapshot_facts.rows')==[{'amount':30}]
                assert await transaction.delivery_annual_interview_history(AnnualAccountsSourceQuery(COMPANY,IncomeYear(2025),ACTOR))==[]
                cursor=await connection.execute('select current_user as role')
                assert (await cursor.fetchone())['role']=='annual_accounts_filing_workflow_executor'
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    async with connection.transaction():await connection.execute('select * from snapshot_facts.rows')
            async with connection.transaction():
                await bind(connection)
                assert await transaction.delivery_corporate_queries._database_rows('select amount from snapshot_facts.rows')==[{'amount':45}]
    asyncio.run(exercise())


@pytest.mark.parametrize('failure',['sql','cancel'])
def test_corporate_role_is_restored_after_failure_or_cancel(database,failure):
    async def exercise():
        async with await psycopg.AsyncConnection.connect(**database,user='snapshot_runtime',row_factory=dict_row) as connection:
            async with connection.transaction():
                await bind(connection);corporate=PostgresAnnualAccountsTransaction(verified(),connection).delivery_corporate_queries
                if failure=='sql':
                    # Unknown database failures use the existing shared Ledger mapper.
                    with pytest.raises(LedgerError):await corporate._database_rows('select 1/0')
                else:
                    task=asyncio.create_task(corporate._database_rows('select pg_sleep(10)'));await asyncio.sleep(.1);task.cancel()
                    with pytest.raises(asyncio.CancelledError):await task
                cursor=await connection.execute('select current_user as role')
                assert (await cursor.fetchone())['role']=='annual_accounts_filing_workflow_executor'
                assert await _verified_snapshot_rows(verified(),connection,'ledger_executor','select 1 as usable',())==[{'usable':1}]
    asyncio.run(exercise())
