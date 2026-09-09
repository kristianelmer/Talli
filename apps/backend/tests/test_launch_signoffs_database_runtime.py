"""Real backend-system technical signoff permissions and rollback-safe updates."""
import asyncio
from datetime import timedelta
import json
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
import pytest

from test_authority_connections_database_runtime import DATABASE_URL,backend_url,fixture,claims
from talli_backend.adapters.postgres_launch_signoffs import PostgresLaunchSignoffSession
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.application.launch_signoffs import (
    LaunchSignoffError,LaunchSignoffKey,LaunchSignoffStatus,RecordLaunchSignoff,
)
from talli_backend.shared.kernel import ActorId,ActorKind,UserId

pytestmark=pytest.mark.authority_database
KEY='launch_legal_name_public_copy'


@pytest.fixture
def signoffs(fixture,backend_url):
    name=conninfo_to_dict(backend_url)['user']
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(sql.SQL('grant launch_signoff_executor to {} with inherit false,set true').format(sql.Identifier(name)))
        before=connection.execute('select to_jsonb(s) from public.launch_signoffs s where key=%s',(KEY,)).fetchone()
    try: yield fixture
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute('delete from public.launch_signoffs where key=%s',(KEY,))
            if before:
                connection.execute('insert into public.launch_signoffs select * from jsonb_populate_record(null::public.launch_signoffs,%s::jsonb)',(json.dumps(before[0]),))
            connection.execute(sql.SQL('revoke launch_signoff_executor from {}').format(sql.Identifier(name)))


def store(fixture,actor=None):
    actor=actor or fixture['admin']
    verified=_VerifiedActor(ActorId(ActorKind.USER,UserId(str(actor))),json.dumps(claims(fixture,actor=actor,fresh=False)))
    return PostgresLaunchSignoffSession(fixture['url'],verified)


def command(fixture,**changes):
    return RecordLaunchSignoff(**(dict(key=LaunchSignoffKey.PUBLIC_COPY,status=LaunchSignoffStatus.APPROVED,
        reviewer='Reviewer',reviewed_at=fixture['now'],evidence_link='local-fixture',decision='approved')|changes))


def test_admin_records_and_upserts_without_new_mfa_requirement(signoffs):
    service=store(signoffs)
    initial=asyncio.run(service.record_signoff(command(signoffs)))
    assert initial.recorded_by==service.actor_id.subject
    updated=asyncio.run(service.record_signoff(command(signoffs,decision='updated')))
    assert updated.key==initial.key and updated.decision=='updated'
    rows=asyncio.run(service.list_signoffs())
    assert sum(row.key==LaunchSignoffKey.PUBLIC_COPY for row in rows)==1


@pytest.mark.parametrize('mode',['owner','support','inactive'])
def test_current_operator_visibility_and_admin_mutation(signoffs,mode):
    actor=signoffs['owner'] if mode=='owner' else signoffs['admin']
    if mode!='owner':
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute('update public.support_operators set role=%s,active=%s where user_id=%s',
                ('support' if mode=='support' else 'admin',mode!='inactive',actor))
    service=store(signoffs,actor)
    with pytest.raises(LaunchSignoffError): asyncio.run(service.record_signoff(command(signoffs)))
    if mode=='support': assert isinstance(asyncio.run(service.list_signoffs()),tuple)
    else:
        with pytest.raises(LaunchSignoffError): asyncio.run(service.list_signoffs())


def test_future_review_and_missing_approved_evidence_fail_in_database(signoffs):
    service=store(signoffs)
    for change in (dict(reviewed_at=signoffs['now']+timedelta(days=10)),dict(evidence_link=' ')):
        with pytest.raises(LaunchSignoffError): asyncio.run(service.record_signoff(command(signoffs,**change)))


@pytest.mark.parametrize('fault',['zero_row','admin_revoke'])
def test_late_write_rechecks_roll_back_signoff_and_authorization(signoffs,fault):
    service=store(signoffs)
    initial=asyncio.run(service.record_signoff(command(signoffs)))
    name='signoff_fault_'+uuid4().hex
    body="return null;" if fault=='zero_row' else "update public.support_operators set active=false where user_id=NEW.recorded_by; return NEW;"
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(sql.SQL("create function public.{}() returns trigger language plpgsql security definer set search_path='' as {} ").format(sql.Identifier(name),sql.Literal('begin '+body+' end')))
        connection.execute(sql.SQL('create trigger {} before update on public.launch_signoffs for each row execute function public.{}()').format(sql.Identifier(name),sql.Identifier(name)))
    try:
        with pytest.raises(LaunchSignoffError): asyncio.run(service.record_signoff(command(signoffs,decision='must rollback')))
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(sql.SQL('drop trigger {} on public.launch_signoffs').format(sql.Identifier(name)))
            connection.execute(sql.SQL('drop function public.{}()').format(sql.Identifier(name)))
    rows=asyncio.run(service.list_signoffs())
    assert next(row for row in rows if row.key==initial.key)==initial


def test_expand_contract_rollback_recutover_preserves_rows_and_runtime_authority(signoffs):
    from pathlib import Path
    root=Path(__file__).resolve().parents[3]
    expand='20260909124946_backend_system_launch_signoffs.sql'
    contract='20260909125250_backend_system_launch_signoffs_contract.sql'
    service=store(signoffs)
    original=asyncio.run(service.record_signoff(command(signoffs)))
    def apply(folder,name):
        with psycopg.connect(DATABASE_URL,autocommit=True) as connection:
            connection.execute((root/'supabase'/folder/name).read_text())
    def digest():
        with psycopg.connect(DATABASE_URL) as connection:
            return connection.execute("select md5(coalesce(jsonb_agg(to_jsonb(s) order by key)::text,'')) from public.launch_signoffs s").fetchone()[0]
    with psycopg.connect(DATABASE_URL) as connection:
        contracted=not connection.execute("select has_table_privilege('authenticated','public.launch_signoffs','UPDATE')").fetchone()[0]
    before=digest()
    if not contracted: apply('contract-migrations',contract)
    try:
        with psycopg.connect(signoffs['url']) as connection:
            connection.execute('set local role launch_signoff_executor')
            with pytest.raises(psycopg.errors.InsufficientPrivilege),connection.transaction():
                connection.execute('select * from public.launch_signoffs')
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute('set local role authenticated')
            with pytest.raises(psycopg.errors.InsufficientPrivilege),connection.transaction():
                connection.execute('select * from public.launch_signoffs')
        assert original in asyncio.run(service.list_signoffs())
        apply('rollback',contract)
        apply('rollback',expand)
        assert digest()==before
        with pytest.raises(LaunchSignoffError): asyncio.run(service.list_signoffs())
        with psycopg.connect(DATABASE_URL) as connection:
            assert connection.execute("select has_table_privilege('authenticated','public.launch_signoffs','UPDATE')").fetchone()[0]
            assert connection.execute("select to_regprocedure('backend_system.record_launch_signoff_v1(text,text,text,timestamptz,text,text)')").fetchone()[0] is None
        apply('migrations',expand)
        apply('contract-migrations',contract)
        assert digest()==before
        assert original in asyncio.run(service.list_signoffs())
    finally:
        if not contracted: apply('rollback',contract)
