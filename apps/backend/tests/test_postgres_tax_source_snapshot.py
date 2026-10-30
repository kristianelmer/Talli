"""Real PG17 component checks in an owned, empty, disposable database.

This proves snapshot/role/savepoint and exact read-admission mechanics. It does
not substitute for the full Company Access, filing or connected browser gates.
"""
import asyncio
import json
import os
from pathlib import Path
import re
import subprocess
import time
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
import pytest

from talli_backend.adapters.supabase_ledger import _VerifiedActor, _verified_snapshot_rows
from test_investment_reporting_source import ACTOR, COMPANY


pytestmark = pytest.mark.company_tax_database
ROOT = Path(__file__).resolve().parents[3]
MIGRATION = '20261026043538_company_tax_delivery_annual_read_admission.sql'


@pytest.fixture(scope='module')
def database():
    docker = ['docker']
    if os.environ.get('TALLI_DOCKER_HOST'):
        docker += ['--host', os.environ['TALLI_DOCKER_HOST']]
    def run(*args):
        return subprocess.check_output(docker + list(args), stderr=subprocess.STDOUT, timeout=30).decode().strip()
    image = None
    for candidate in ('public.ecr.aws/docker/library/postgres:17-alpine', 'postgres:17-alpine'):
        try:
            image = run('image', 'inspect', candidate, '--format', '{{.Id}}')
            break
        except subprocess.CalledProcessError:
            continue
    assert image, 'Prefetch the fixed PostgreSQL fixture image before this required test.'
    owner = uuid4().hex
    label = 'talli.tax-source-snapshot=' + owner
    container = run('create', '--pull=never', '--label', label,
        '--name', 'talli-tax-source-' + owner, '--user', 'postgres', '--read-only',
        '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit', '64',
        '--memory', '512m', '--cpus', '1', '--dns', '127.0.0.1',
        '--publish', '127.0.0.1::5432',
        '--tmpfs', '/data:rw,nosuid,nodev,uid=70,gid=70,mode=0700,size=128m',
        '--tmpfs', '/tmp:rw,nosuid,nodev,uid=70,gid=70,mode=0700,size=16m',
        '--entrypoint', '/bin/sh', image, '-c',
        "initdb -D /data -U postgres --auth=trust >/dev/null && "
        "printf '%s\\n' 'host postgres postgres,snapshot_runtime samenet trust' >> /data/pg_hba.conf && "
        "exec postgres -D /data -h 0.0.0.0 -k /tmp -c max_connections=16").splitlines()[-1]
    assert re.fullmatch('[0-9a-f]{64}', container)
    try:
        run('start', container)
        port = int(run('port', container, '5432/tcp').removeprefix('127.0.0.1:'))
        connection, last_error = None, ''
        end = time.monotonic() + 20
        while time.monotonic() < end:
            try:
                connection = psycopg.connect(host='127.0.0.1', port=port, user='postgres',
                    dbname='postgres', connect_timeout=1, autocommit=True, sslmode='disable')
                break
            except psycopg.OperationalError as error:
                last_error = str(error)
                time.sleep(.1)
        assert connection is not None, 'Owned PostgreSQL fixture did not start: ' + last_error + '\n' + run('logs', container)[-4000:]
        with connection:
            connection.execute('''
                create role ledger_store_owner nologin noinherit;
                create role backend_system_annual_data_reader nologin noinherit;
                create role company_tax_filing_workflow_executor nologin noinherit;
                create role investments_executor nologin noinherit;
                create role ledger_executor nologin noinherit;
                create role corporate_governance_workflow_executor nologin noinherit;
                create role annual_accounts_filing_workflow_executor nologin noinherit;
                create role snapshot_runtime login noinherit;
                grant company_tax_filing_workflow_executor, investments_executor, ledger_executor,
                  corporate_governance_workflow_executor, annual_accounts_filing_workflow_executor
                  to snapshot_runtime with inherit false, set true;
                create schema backend_system authorization ledger_store_owner;
                grant usage on schema backend_system to backend_system_annual_data_reader;
                create function backend_system.list_annual_data_legacy_v1(uuid,integer,text)
                  returns jsonb language sql security invoker as $$ select '[]'::jsonb $$;
                alter function backend_system.list_annual_data_legacy_v1(uuid,integer,text)
                  owner to backend_system_annual_data_reader;
                revoke all on function backend_system.list_annual_data_legacy_v1(uuid,integer,text) from public;
                create schema snapshot_facts;
                create table snapshot_facts.rows(subject uuid not null, amount integer not null);
                insert into snapshot_facts.rows values
                  ('20000000-0000-0000-0000-000000000001',30),
                  ('20000000-0000-0000-0000-000000000099',99);
                alter table snapshot_facts.rows enable row level security;
                alter table snapshot_facts.rows force row level security;
                create policy own on snapshot_facts.rows for select
                  using(subject = current_setting('talli.verified_actor_id',true)::uuid);
                grant usage on schema snapshot_facts to investments_executor,ledger_executor;
                grant select on snapshot_facts.rows to investments_executor,ledger_executor,corporate_governance_workflow_executor;
                grant usage on schema snapshot_facts to corporate_governance_workflow_executor;
                grant usage on schema backend_system to corporate_governance_workflow_executor;
                grant execute on function backend_system.list_annual_data_legacy_v1(uuid,integer,text) to corporate_governance_workflow_executor;
            ''')
            yield dict(host='127.0.0.1', port=port, dbname='postgres', sslmode='disable')
    finally:
        assert run('inspect', container, '--format', '{{index .Config.Labels "talli.tax-source-snapshot"}}') == owner
        run('rm', '--force', container)


def verified():
    return _VerifiedActor(ACTOR, json.dumps({'sub': str(ACTOR.subject), 'role': 'authenticated', 'aal': 'aal2'}))


async def bind(connection, *, isolation='repeatable read', subject=None):
    await connection.execute('set transaction isolation level ' + isolation)
    await connection.execute('set local role company_tax_filing_workflow_executor')
    await connection.execute("select set_config('talli.verified_actor_id',%s,true), set_config('talli.verified_actor_claims',%s,true)",
        (subject or str(ACTOR.subject), verified().claims_json))


@pytest.mark.parametrize('executor', ['investments_executor', 'ledger_executor', 'corporate_governance_workflow_executor'])
def test_snapshot_read_enforces_rls_and_restores_caller_role(database, executor):
    async def exercise():
        async with await psycopg.AsyncConnection.connect(**database, user='snapshot_runtime', row_factory=dict_row) as connection:
            async with connection.transaction():
                await bind(connection)
                rows = await _verified_snapshot_rows(verified(), connection, executor,
                    'select amount,current_user as reader from snapshot_facts.rows', ())
                assert rows == [{'amount': 30, 'reader': executor}]
                cursor = await connection.execute('select current_user as role')
                assert (await cursor.fetchone())['role'] == 'company_tax_filing_workflow_executor'
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    async with connection.transaction():
                        await connection.execute('select * from snapshot_facts.rows')
    asyncio.run(exercise())


@pytest.mark.parametrize('failure', ['sql', 'cancel'])
def test_failure_and_cancellation_restore_role_and_leave_outer_snapshot_usable(database, failure):
    async def exercise():
        async with await psycopg.AsyncConnection.connect(**database, user='snapshot_runtime', row_factory=dict_row) as connection:
            async with connection.transaction():
                await bind(connection)
                if failure == 'sql':
                    with pytest.raises(psycopg.errors.DivisionByZero):
                        await _verified_snapshot_rows(verified(), connection, 'investments_executor', 'select 1/0', ())
                else:
                    task = asyncio.create_task(_verified_snapshot_rows(verified(), connection,
                        'investments_executor', 'select pg_sleep(10)', ()))
                    await asyncio.sleep(.1)
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError): await task
                cursor = await connection.execute('select current_user as role')
                assert (await cursor.fetchone())['role'] == 'company_tax_filing_workflow_executor'
                assert await _verified_snapshot_rows(verified(), connection, 'ledger_executor',
                    'select amount from snapshot_facts.rows', ()) == [{'amount':30}]
    asyncio.run(exercise())


@pytest.mark.parametrize('change', ['isolation', 'subject', 'claims'])
def test_snapshot_binding_rejects_identity_or_isolation_mismatch(database, change):
    async def exercise():
        async with await psycopg.AsyncConnection.connect(**database, user='snapshot_runtime', row_factory=dict_row) as connection:
            async with connection.transaction():
                await bind(connection, isolation='read committed' if change == 'isolation' else 'repeatable read',
                    subject=str(COMPANY) if change == 'subject' else None)
                if change == 'claims':
                    await connection.execute("select set_config('talli.verified_actor_claims','{}',true)")
                with pytest.raises(ValueError):
                    await _verified_snapshot_rows(verified(), connection, 'investments_executor', 'select 1', ())
                cursor = await connection.execute('select current_user as role')
                assert (await cursor.fetchone())['role'] == 'company_tax_filing_workflow_executor'
    asyncio.run(exercise())


def test_annual_read_admission_has_exact_acl_and_preserves_memberships(database):
    with psycopg.connect(**database, user='postgres', autocommit=True) as connection:
        membership = 'select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3'
        before = connection.execute(membership).fetchall()
        connection.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
        assert connection.execute(membership).fetchall() == before
        assert connection.execute("select has_function_privilege('company_tax_filing_workflow_executor','backend_system.list_annual_data_legacy_v1(uuid,integer,text)','execute')").fetchone() == (True,)
        assert connection.execute("select has_function_privilege('snapshot_runtime','backend_system.list_annual_data_legacy_v1(uuid,integer,text)','execute')").fetchone() == (False,)
        assert connection.execute("select has_schema_privilege('company_tax_filing_workflow_executor','backend_system','create')").fetchone() == (False,)
        with psycopg.connect(**database, user='snapshot_runtime') as runtime:
            runtime.execute('set local role company_tax_filing_workflow_executor')
            assert runtime.execute("select backend_system.list_annual_data_legacy_v1(%s,2025,%s)",
                (str(COMPANY), str(ACTOR.subject))).fetchone() == ([],)
        connection.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
        assert connection.execute(membership).fetchall() == before
        assert connection.execute("select has_function_privilege('company_tax_filing_workflow_executor','backend_system.list_annual_data_legacy_v1(uuid,integer,text)','execute')").fetchone() == (False,)
        assert connection.execute("select has_schema_privilege('company_tax_filing_workflow_executor','backend_system','usage')").fetchone() == (False,)
        connection.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
        assert connection.execute(membership).fetchall() == before


def test_different_owner_queries_keep_one_snapshot_across_a_concurrent_change(database):
    async def exercise():
        async with await psycopg.AsyncConnection.connect(**database, user='snapshot_runtime', row_factory=dict_row) as connection:
            async with connection.transaction():
                await bind(connection)
                first = await _verified_snapshot_rows(verified(), connection, 'ledger_executor',
                    'select amount from snapshot_facts.rows', ())
                with psycopg.connect(**database, user='postgres', autocommit=True) as writer:
                    writer.execute('update snapshot_facts.rows set amount=31 where subject=%s', (str(ACTOR.subject),))
                second = await _verified_snapshot_rows(verified(), connection, 'investments_executor',
                    'select amount from snapshot_facts.rows', ())
                assert first == second == [{'amount': 30}]
            async with connection.transaction():
                await bind(connection)
                assert await _verified_snapshot_rows(verified(), connection, 'ledger_executor',
                    'select amount from snapshot_facts.rows', ()) == [{'amount':31}]
    asyncio.run(exercise())
