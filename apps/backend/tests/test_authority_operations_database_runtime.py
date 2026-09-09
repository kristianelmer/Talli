"""Restricted current-admin audit transitions; no provider calls."""

import asyncio
from dataclasses import replace
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from test_authority_connections_database_runtime import (
    DATABASE_URL, backend_url, fixture, insert, session,
)
from talli_backend.shared.kernel import ErrorCategory
from talli_backend.modules.authority_connections.public import (
    AuthorityOperationCode as Code, AuthorityOperationCompletion, AuthorityOperationError,
    AuthorityOperationIntent, AuthorityOperationKind as Kind, AuthorityOperationStatus as Status,
    RunAuthorityOperationCommand,
)


pytestmark=pytest.mark.authority_database


def started(fixture, kind=Kind.REGISTER_RF1086_SYSTEM):
    store=session(fixture,actor=fixture["admin"])
    command=RunAuthorityOperationCommand(store.actor_id,str(uuid4()),kind,kind.value)
    intent=AuthorityOperationIntent(kind,str(uuid4()))
    return store,command,intent,asyncio.run(store.begin_operation(command,intent))


def audit(fixture, operation_id):
    with psycopg.connect(DATABASE_URL) as connection:
        return connection.execute("select to_jsonb(o) from authority_connections.authority_operations o where id=%s",(operation_id,)).fetchone()[0]


@pytest.mark.parametrize("kind",list(Kind))
def test_begin_is_insert_once_and_completion_preserves_original_intent(fixture,kind):
    store,command,intent,initial=started(fixture,kind)
    assert initial.status==Status.STARTED and initial.completed_at is None
    with pytest.raises(AuthorityOperationError) as duplicate: asyncio.run(store.begin_operation(command,intent))
    assert duplicate.value.code==Code.AUTHORITY_OPERATION_CONFLICT
    code=Code.ALREADY_VERIFIED if kind==Kind.REGISTER_RF1086_SYSTEM else Code.CALLBACK_ALREADY_VERIFIED
    completion=AuthorityOperationCompletion(Status.SUCCEEDED,code,200)
    stale=session(fixture,actor=fixture["admin"],fresh=False)
    completed=asyncio.run(stale.complete_operation(stale.actor_id,initial.operation_id,completion))
    assert completed.operation==initial.operation and completed.actor_id==initial.actor_id
    assert completed.request_hash==initial.request_hash==intent.request_hash
    assert dict(completed.metadata)==dict(initial.metadata)==dict(intent.metadata)
    assert completed.created_at==initial.created_at and completed.completed_at is not None
    before=audit(fixture,initial.operation_id)
    with pytest.raises(AuthorityOperationError) as replay:
        asyncio.run(store.complete_operation(store.actor_id,initial.operation_id,completion))
    assert replay.value.code==Code.AUTHORITY_OPERATION_CONFLICT and audit(fixture,initial.operation_id)==before


@pytest.mark.parametrize("mode",["owner","outsider","inactive","non_admin","stale"])
def test_begin_requires_current_active_admin_and_fresh_mfa(fixture,mode):
    actor=fixture[mode] if mode in ("owner","outsider") else fixture["admin"]
    if mode in ("inactive","non_admin"):
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute("update public.support_operators set active=%s,role=%s where user_id=%s",
                (mode!="inactive","support" if mode=="non_admin" else "admin",actor))
    store=session(fixture,actor=actor,fresh=mode!="stale")
    command=RunAuthorityOperationCommand(store.actor_id,str(uuid4()),Kind.REGISTER_RF1086_SYSTEM,"register_rf1086_system")
    with pytest.raises(AuthorityOperationError) as denied:
        asyncio.run(store.begin_operation(command,AuthorityOperationIntent(command.operation,str(uuid4()))))
    assert denied.value.category==(ErrorCategory.PRECONDITION_FAILED if mode=="stale" else ErrorCategory.FORBIDDEN)
    with psycopg.connect(DATABASE_URL) as connection:
        assert connection.execute("select count(*) from authority_connections.authority_operations where id=%s",(command.operation_id,)).fetchone()[0]==0


def test_list_is_current_admin_only_without_new_mfa_requirement(fixture):
    _,_,_,initial=started(fixture)
    stale=session(fixture,actor=fixture["admin"],fresh=False)
    rows=asyncio.run(stale.list_operations(stale.actor_id))
    assert initial.operation_id in [row.operation_id for row in rows]
    assert len(rows)<=10
    assert [row.created_at.value for row in rows]==sorted([row.created_at.value for row in rows],reverse=True)
    owner=session(fixture)
    with pytest.raises(AuthorityOperationError): asyncio.run(owner.list_operations(owner.actor_id))


def test_another_current_admin_cannot_complete_original_actor_operation(fixture):
    _,_,_,initial=started(fixture)
    with psycopg.connect(DATABASE_URL) as connection:
        insert(connection,"public.support_operators",{"user_id":fixture["outsider"],"role":"admin","active":True})
    other=session(fixture,actor=fixture["outsider"])
    before=audit(fixture,initial.operation_id)
    with pytest.raises(AuthorityOperationError):
        asyncio.run(other.complete_operation(other.actor_id,initial.operation_id,AuthorityOperationCompletion(Status.SUCCEEDED,Code.ALREADY_VERIFIED,200)))
    assert audit(fixture,initial.operation_id)==before


@pytest.mark.parametrize("fault",["raise","zero_row","admin_revoke"])
def test_late_completion_denial_rolls_back_audit_and_authority_change(fixture,fault):
    store,_,_,initial=started(fixture)
    before=audit(fixture,initial.operation_id)
    name="authority_op_fault_"+uuid4().hex
    effect={"raise":"raise exception 'synthetic_audit_failure';","zero_row":"return null;",
            "admin_revoke":"update public.support_operators set active=false where user_id=NEW.actor_id;"}[fault]
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(sql.SQL("create function public.{}() returns trigger language plpgsql security definer set search_path='' as {}").format(
            sql.Identifier(name),sql.Literal("begin if NEW.id='"+initial.operation_id+"'::uuid then "+effect+" end if; return NEW; end;")))
        connection.execute(sql.SQL("create trigger {} before update on authority_connections.authority_operations for each row execute function public.{}()").format(sql.Identifier(name),sql.Identifier(name)))
    try:
        with pytest.raises(AuthorityOperationError):
            asyncio.run(store.complete_operation(store.actor_id,initial.operation_id,AuthorityOperationCompletion(Status.SUCCEEDED,Code.ALREADY_VERIFIED,200)))
        assert audit(fixture,initial.operation_id)==before
        with psycopg.connect(DATABASE_URL) as connection:
            assert connection.execute("select active from public.support_operators where user_id=%s",(fixture["admin"],)).fetchone()[0] is True
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(sql.SQL("drop trigger {} on authority_connections.authority_operations").format(sql.Identifier(name)))
            connection.execute(sql.SQL("drop function public.{}()").format(sql.Identifier(name)))


def test_completion_rechecks_admin_after_real_operation_lock_wait(fixture):
    store,_,_,initial=started(fixture);before=audit(fixture,initial.operation_id)
    async def run():
        with psycopg.connect(DATABASE_URL) as lock:
            lock.execute("select id from authority_connections.authority_operations where id=%s for update",(initial.operation_id,))
            pending=asyncio.create_task(store.complete_operation(store.actor_id,initial.operation_id,AuthorityOperationCompletion(Status.SUCCEEDED,Code.ALREADY_VERIFIED,200)))
            waited=False
            for _ in range(100):
                await asyncio.sleep(.01)
                with psycopg.connect(DATABASE_URL) as observer:
                    waited=observer.execute("select exists(select 1 from pg_stat_activity where wait_event_type='Lock' and query like 'select authority_connections.complete_operation_v1%%')").fetchone()[0]
                if waited: break
            assert waited,"must prove a real operation row-lock wait"
            with psycopg.connect(DATABASE_URL) as revoker:
                revoker.execute("update public.support_operators set active=false where user_id=%s",(fixture["admin"],))
            lock.commit()
            with pytest.raises(AuthorityOperationError): await pending
    asyncio.run(run())
    assert audit(fixture,initial.operation_id)==before
