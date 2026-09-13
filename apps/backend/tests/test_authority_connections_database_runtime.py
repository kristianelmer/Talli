"""Real restricted-role proof for the canonical Authority Connections expansion."""

import asyncio
from dataclasses import replace
from datetime import timedelta
import json
import os
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb
import pytest

from talli_backend.adapters.postgres_authority_connections import PostgresAuthorityConnectionsSession
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.modules.authority_connections.public import (
    AuthorityConnectionsError, AuthorityFailureCode, SystemUserIdentity,
    SystemUserOwner, SystemUserRequestStatus as Status, SystemUserStateUpdate,
)
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, UserId


pytestmark = pytest.mark.authority_database
DATABASE_URL = os.environ.get("DATABASE_URL", "")
ROOT = Path(__file__).resolve().parents[3]
MIGRATION = "20260909120610_authority_connections_capability.sql"
OPERATIONS_MIGRATION = "20260909123709_authority_operations_capability.sql"
RF_MIGRATION = "20260909125113_legacy_rf1086_authority_relocation.sql"
CONTRACT = "20260909124659_authority_connections_contract.sql"
RF151_EXPAND = "20260909190548_shareholder_register_filing_capability.sql"
RF151_CUTOVER = "20260909190905_shareholder_register_filing_cutover.sql"
RF151_CONTRACT = "20260909190955_shareholder_register_filing_contract.sql"


def insert(connection, table, values):
    connection.execute(sql.SQL("insert into {} ({}) values ({})").format(
        sql.Identifier(*table.split(".")), sql.SQL(",").join(map(sql.Identifier, values)),
        sql.SQL(",").join(sql.Placeholder() for _ in values),
    ), tuple(values.values()))


def ensure_fixture_admin_access(connection):
    principal=connection.execute("select current_user").fetchone()[0]
    for role in ("authority_connections_store_owner","billing_store_owner","ledger_store_owner"):
        connection.execute(sql.SQL("grant {} to {}").format(sql.Identifier(role),sql.Identifier(principal)))


def delete_fixture_company(connection, company):
    # Billing recutover intentionally leaves its receipt owner without DELETE.
    # Borrow only for this disposable company cascade, in the caller's transaction.
    borrowed = not connection.execute(
        "select has_table_privilege('billing_store_owner','billing.billing_command_receipts','DELETE')"
    ).fetchone()[0]
    if borrowed:
        connection.execute("grant delete on billing.billing_command_receipts to billing_store_owner")
    connection.execute("delete from public.companies where id=%s", (company,))
    if borrowed:
        connection.execute("revoke delete on billing.billing_command_receipts from billing_store_owner")


@pytest.fixture(scope="module")
def backend_url():
    assert DATABASE_URL, "DATABASE_URL must identify the owned disposable test database"
    name = "authority_test_" + uuid4().hex
    password = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        principal=connection.execute("select current_user").fetchone()[0]
        borrowed=[role for role in ("authority_connections_store_owner","billing_store_owner","ledger_store_owner")
                  if not connection.execute("select pg_has_role(current_user,%s,'SET')",(role,)).fetchone()[0]]
        ensure_fixture_admin_access(connection)
        assert connection.execute("select to_regclass('authority_connections.system_user_requests')").fetchone()[0]
        connection.execute(sql.SQL("create role {} login noinherit nobypassrls password {}").format(
            sql.Identifier(name), sql.Literal(password)))
        connection.execute(sql.SQL("grant authority_connections_executor to {} with inherit false,set true").format(sql.Identifier(name)))
    try:
        yield make_conninfo(DATABASE_URL, user=name, password=password)
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(sql.SQL("revoke authority_connections_executor from {}").format(sql.Identifier(name)))
            connection.execute(sql.SQL("drop role {}").format(sql.Identifier(name)))
            for role in borrowed:
                connection.execute(sql.SQL("revoke {} from {}").format(sql.Identifier(role),sql.Identifier(principal)))


@pytest.fixture
def fixture(backend_url):
    owner, outsider, admin, company = [uuid4() for _ in range(4)]
    with psycopg.connect(DATABASE_URL) as connection:
        now = connection.execute("select clock_timestamp()-interval '1 second'").fetchone()[0]
        for actor in (owner, outsider, admin):
            insert(connection,"auth.users",{"id":actor,"email":f"{actor}@example.test"})
        insert(connection,"public.companies",{
            "id":company,"org_number":str(100000000+company.int%899999999),"name":"Authority Fixture AS",
            "entity_type":"AS","address":"Testveien 1","postal_code":"0150","city":"Oslo",
            "status_text":"aktiv","source":"test","created_by":owner,
            "identity_confirmed_at":now,"identity_locked_at":now,
        })
        insert(connection,"public.company_memberships",{
            "company_id":company,"user_id":owner,"role":"owner","accepted_at":now,
        })
        insert(connection,"public.support_operators",{"user_id":admin,"role":"admin","active":True})
    data = dict(owner=owner,outsider=outsider,admin=admin,company=company,now=now,url=backend_url)
    try:
        yield data
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute("delete from public.support_case_openings where company_id=%s",(company,))
            connection.execute("delete from public.support_access_operation_receipts where case_id in (select case_id from public.support_access_grants where company_id=%s)",(company,))
            connection.execute("delete from public.support_access_grants where company_id=%s",(company,))
            connection.execute("delete from billing.production_pilot_entitlements where company_id=%s",(company,))
            connection.execute("delete from authority_connections.system_user_requests where company_id=%s",(company,))
            connection.execute("delete from authority_connections.authority_operations where actor_id=any(%s::uuid[])",([owner,outsider,admin],))
            connection.execute("delete from public.support_operators where user_id=any(%s::uuid[])",([owner,outsider,admin],))
            delete_fixture_company(connection, company)
            connection.execute("delete from auth.users where id=any(%s::uuid[])",([owner,outsider,admin],))


@pytest.mark.parametrize("delete_present", [False, True])
@pytest.mark.parametrize("late_failure", [False, True])
def test_fixture_company_cleanup_preserves_receipt_acl_and_atomic_rollback(fixture, delete_present, late_failure):
    with psycopg.connect(DATABASE_URL) as connection:
        baseline_acl = connection.execute(
            "select relacl::text from pg_class where oid='billing.billing_command_receipts'::regclass"
        ).fetchone()[0]
        try:
            connection.execute(
                ("grant delete on billing.billing_command_receipts to billing_store_owner" if delete_present
                 else "revoke delete on billing.billing_command_receipts from billing_store_owner")
            )
            original_acl = connection.execute(
                "select relacl::text from pg_class where oid='billing.billing_command_receipts'::regclass"
            ).fetchone()[0]
            connection.execute("savepoint fixture_cleanup")
            delete_fixture_company(connection, fixture["company"])
            assert connection.execute("select count(*) from public.companies where id=%s", (fixture["company"],)).fetchone()[0] == 0
            assert connection.execute(
                "select relacl::text from pg_class where oid='billing.billing_command_receipts'::regclass"
            ).fetchone()[0] == original_acl
            if late_failure:
                with pytest.raises(psycopg.errors.DivisionByZero):
                    connection.execute("select 1/0")
                connection.execute("rollback to savepoint fixture_cleanup")
                assert connection.execute("select count(*) from public.companies where id=%s", (fixture["company"],)).fetchone()[0] == 1
                assert connection.execute(
                    "select relacl::text from pg_class where oid='billing.billing_command_receipts'::regclass"
                ).fetchone()[0] == original_acl
        finally:
            connection.rollback()
    with psycopg.connect(DATABASE_URL) as observer:
        assert observer.execute("select count(*) from public.companies where id=%s", (fixture["company"],)).fetchone()[0] == 1
        assert observer.execute(
            "select relacl::text from pg_class where oid='billing.billing_command_receipts'::regclass"
        ).fetchone()[0] == baseline_acl


def claims(fixture, *, actor=None, fresh=True):
    return {"sub":str(actor or fixture["owner"]),"role":"authenticated","aal":"aal2",
            "amr":[{"method":"totp","timestamp":(fixture["now"]-timedelta(hours=1) if not fresh else fixture["now"]).timestamp()}]}


def session(fixture, *, actor=None, fresh=True):
    actor_id=ActorId(ActorKind.USER,UserId(str(actor or fixture["owner"])))
    return PostgresAuthorityConnectionsSession(fixture["url"],_VerifiedActor(actor_id,json.dumps(claims(fixture,actor=actor,fresh=fresh))))


def owner_for(fixture, store=None, *, fresh=True):
    store=store or session(fixture,fresh=fresh)
    return asyncio.run(store.authorize_owner(CompanyId(str(fixture["company"])),store.actor_id,require_fresh_mfa=fresh))


def begin(fixture, store=None):
    store=store or session(fixture)
    owner=owner_for(fixture,store)
    return owner,asyncio.run(store.begin_request(owner,str(uuid4()),uuid4().hex+uuid4().hex[:11]))


def transition(owner, request, status=Status.ACCEPTED, *, failure=None, provider_id=None):
    provider_id=provider_id or request.provider_request_id or str(uuid4())
    return SystemUserStateUpdate(request.request_id,request.identity,provider_id,status,
        "https://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id="+provider_id,failure)


def accepted(fixture):
    store=session(fixture);owner,request=begin(fixture,store)
    request=asyncio.run(store.record_authority_state(owner,transition(owner,request)))
    request=asyncio.run(store.verify_preflight(owner,request.request_id,request.identity.external_reference))
    return store,owner,request


def pilot(fixture, request, *, status="active", year=2026):
    pilot_id=uuid4()
    with psycopg.connect(DATABASE_URL) as connection:
        insert(connection,"billing.production_pilot_entitlements",{
            "id":pilot_id,"company_id":fixture["company"],"user_id":fixture["owner"],"income_year":year,
            "obligation":"aksjonaerregisteroppgaven","case_profile":"rf1086_no_activity_v1",
            "status":status,"billing_exempt":True,"system_user_request_id":request.request_id,
            "system_user_external_reference":request.identity.external_reference,
            "starts_at":fixture["now"],"expires_at":fixture["now"]+timedelta(days=30),
            "evidence_reference":"synthetic-authority-runtime","approved_by":fixture["admin"],
        })
    return pilot_id


def state(fixture):
    with psycopg.connect(DATABASE_URL) as connection:
        return (connection.execute("select to_jsonb(r) from authority_connections.system_user_requests r where company_id=%s order by id",(fixture["company"],)).fetchall(),
                connection.execute("select to_jsonb(p) from billing.production_pilot_entitlements p where company_id=%s order by id",(fixture["company"],)).fetchall())


def test_restricted_session_cannot_assume_store_owner_or_write_tables(fixture):
    with psycopg.connect(fixture["url"]) as connection:
        assert connection.execute("select rolbypassrls,rolinherit from pg_roles where rolname=current_user").fetchone()==(False,False)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with connection.transaction(): connection.execute("set local role authority_connections_store_owner")
        connection.execute("set local role authority_connections_executor")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with connection.transaction(): connection.execute("update authority_connections.system_user_requests set status='accepted'")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with connection.transaction(): connection.execute("select * from billing.production_pilot_entitlements")
    with psycopg.connect(DATABASE_URL) as connection:
        rows=connection.execute("select relrowsecurity,relforcerowsecurity from pg_class where oid in ('authority_connections.system_user_requests'::regclass,'authority_connections.authority_operations'::regclass)").fetchall()
        assert rows==[(True,True),(True,True)]


def test_request_jwt_context_cannot_substitute_for_backend_verification(fixture):
    _,request=begin(fixture)
    with psycopg.connect(fixture["url"]) as connection:
        connection.execute("set local role authority_connections_executor")
        connection.execute("select set_config('request.jwt.claims',%s,true)",(json.dumps(claims(fixture)),))
        assert connection.execute("select id from authority_connections.system_user_requests").fetchall()==[]
        with pytest.raises(psycopg.errors.RaiseException,match="authority_owner_required"):
            with connection.transaction():
                connection.execute("select authority_connections.assert_owner_v1(%s,false)",(fixture["company"],))


def test_begin_is_insert_once_and_owner_originating_reads_are_current(fixture):
    store=session(fixture);owner,request=begin(fixture,store)
    with pytest.raises(AuthorityConnectionsError) as duplicate:
        asyncio.run(store.begin_request(owner,request.request_id,request.identity.external_reference))
    assert duplicate.value.code=="system_user_request_start_failed"
    assert asyncio.run(store.read_request(owner,request.request_id))==request
    assert asyncio.run(store.resolve_request_owner(request.request_id,owner.actor_id))==owner
    assert asyncio.run(store.list_requests((owner.company_id,),owner.actor_id))==(request,)
    outsider=session(fixture,actor=fixture["outsider"])
    assert asyncio.run(outsider.list_requests((owner.company_id,),outsider.actor_id))==()
    with pytest.raises(AuthorityConnectionsError): asyncio.run(outsider.resolve_request_owner(request.request_id,outsider.actor_id))
    with psycopg.connect(DATABASE_URL) as connection:
        insert(connection,"public.company_memberships",{"company_id":fixture["company"],
            "user_id":fixture["outsider"],"role":"owner","accepted_at":fixture["now"]})
    assert asyncio.run(outsider.list_requests((owner.company_id,),outsider.actor_id))==()
    with pytest.raises(AuthorityConnectionsError): asyncio.run(outsider.resolve_request_owner(request.request_id,outsider.actor_id))
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute("update public.company_memberships set role='read_only' where company_id=%s",(fixture["company"],))
    with pytest.raises(AuthorityConnectionsError): asyncio.run(store.read_request(owner,request.request_id))


def test_begin_requires_fresh_mfa_but_settlement_does_not_add_post_provider_expiry(fixture):
    owner,request=begin(fixture)
    stale=session(fixture,fresh=False)
    with pytest.raises(AuthorityConnectionsError) as denied:
        asyncio.run(stale.authorize_owner(owner.company_id,owner.actor_id,require_fresh_mfa=True))
    assert denied.value.code=="step_up_required"
    assert asyncio.run(stale.record_authority_state(owner,transition(owner,request))).status==Status.ACCEPTED
    assert asyncio.run(stale.verify_preflight(owner,request.request_id,request.identity.external_reference)).preflight_verified_at


def test_provider_binding_and_terminal_evidence_are_immutable(fixture):
    store=session(fixture);owner,request=begin(fixture,store)
    update=transition(owner,request,Status.REJECTED)
    terminal=asyncio.run(store.record_authority_state(owner,update))
    before=state(fixture)
    with pytest.raises(AuthorityConnectionsError):
        asyncio.run(store.record_authority_state(owner,replace(update,provider_request_id=str(uuid4()))))
    assert state(fixture)==before
    with pytest.raises(AuthorityConnectionsError):
        asyncio.run(store.record_authority_state(owner,replace(update,status=Status.ACCEPTED)))
    assert state(fixture)==before
    replay=asyncio.run(store.record_authority_state(owner,update))
    assert replay.provider_request_id==terminal.provider_request_id
    assert replay.resolved_at==terminal.resolved_at


def test_accepted_failure_suspends_only_active_linked_pilot_and_never_reactivates(fixture):
    store,owner,request=accepted(fixture)
    active=pilot(fixture,request)
    completed=pilot(fixture,request,status="completed",year=2025)
    before=state(fixture)
    failed=asyncio.run(store.record_authority_state(owner,transition(owner,request,Status.VERIFICATION_FAILED,failure=AuthorityFailureCode.NETWORK_ERROR)))
    assert failed.preflight_verified_at is None
    after=state(fixture)
    assert after[1][0][0]["approved_by"]==before[1][0][0]["approved_by"]
    statuses={row[0]["id"]:row[0]["status"] for row in after[1]}
    assert statuses[str(active)]=="suspended" and statuses[str(completed)]=="completed"
    restored=asyncio.run(store.record_authority_state(owner,transition(owner,failed)))
    assert restored.status==Status.ACCEPTED
    assert state(fixture)[1]==after[1]


@pytest.mark.parametrize("fault",["raise","zero_row","owner_revoke"])
def test_late_request_write_failure_rolls_pilot_suspension_back(fixture,fault):
    store,owner,request=accepted(fixture);pilot(fixture,request)
    before=state(fixture)
    function="authority_fault_"+uuid4().hex
    body={"raise":"raise exception 'synthetic_late_write';",
          "zero_row":"return null;",
          "owner_revoke":"update public.company_memberships set role='read_only' where company_id=NEW.company_id;"}[fault]
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(sql.SQL("create function public.{}() returns trigger language plpgsql security definer set search_path='' as {} ").format(
            sql.Identifier(function),sql.Literal("begin if NEW.status='verification_failed' then "+body+" end if; return NEW; end;")))
        connection.execute(sql.SQL("create trigger {} before update on authority_connections.system_user_requests for each row execute function public.{}()").format(sql.Identifier(function),sql.Identifier(function)))
    try:
        with pytest.raises(AuthorityConnectionsError):
            asyncio.run(store.record_authority_state(owner,transition(owner,request,Status.VERIFICATION_FAILED,failure=AuthorityFailureCode.NETWORK_ERROR)))
        assert state(fixture)==before
        with psycopg.connect(DATABASE_URL) as connection:
            assert connection.execute("select role from public.company_memberships where company_id=%s",(fixture["company"],)).fetchone()[0]=="owner"
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(sql.SQL("drop trigger {} on authority_connections.system_user_requests").format(sql.Identifier(function)))
            connection.execute(sql.SQL("drop function public.{}()").format(sql.Identifier(function)))


@pytest.mark.parametrize("locked",["request","pilot"])
def test_lock_wait_rechecks_owner_before_any_mutation(fixture,locked):
    store,owner,request=accepted(fixture);pilot_id=pilot(fixture,request)
    before=state(fixture)
    async def exercise():
        with psycopg.connect(DATABASE_URL) as lock:
            if locked=="request":
                lock.execute("select id from authority_connections.system_user_requests where id=%s for update",(request.request_id,))
                waiting_query="select authority_connections.lock_owned_request_v1%"
            else:
                lock.execute("select id from billing.production_pilot_entitlements where id=%s for update",(pilot_id,))
                waiting_query="select billing.suspend_pilot_for_authority_failure_v1%"
            pending=asyncio.create_task(store.record_authority_state(owner,transition(owner,request,Status.VERIFICATION_FAILED,failure=AuthorityFailureCode.NETWORK_ERROR)))
            waited=False
            for _ in range(100):
                await asyncio.sleep(.01)
                with psycopg.connect(DATABASE_URL) as observer:
                    waited=observer.execute("select exists(select 1 from pg_stat_activity where wait_event_type='Lock' and query like %s)",(waiting_query,)).fetchone()[0]
                if waited: break
            assert waited,"must demonstrate a real row-lock wait"
            with psycopg.connect(DATABASE_URL) as revoker:
                revoker.execute("update public.company_memberships set role='read_only' where company_id=%s",(fixture["company"],))
            lock.commit()
            with pytest.raises(AuthorityConnectionsError): await pending
    asyncio.run(exercise())
    assert state(fixture)==before


def test_latest_callback_evidence_is_exact_global_history_with_current_owner_gate(fixture):
    owner=owner_for(fixture)
    with psycopg.connect(DATABASE_URL) as connection:
        insert(connection,"authority_connections.authority_operations",{
            "id":uuid4(),"operation":"set_rf1086_systembruker_callback","actor_id":fixture["admin"],
            "status":"succeeded","request_hash":"c"*64,"result_code":"callback_updated_and_verified",
            "metadata":Jsonb({"systemId":"930835978_talli","callbackPath":"/auth/systembruker/confirm"}),
            "created_at":fixture["now"]+timedelta(minutes=1),"completed_at":fixture["now"],
        })
    evidence=asyncio.run(session(fixture).latest_callback_operation(owner))
    assert evidence.result_code=="callback_updated_and_verified"
    assert dict(evidence.metadata)=={"systemId":"930835978_talli","callbackPath":"/auth/systembruker/confirm"}


def test_capability_rollback_recutover_preserves_original_rows_type_oids_and_fk(fixture,rf151_predecessor_topology):
    store,owner,request=accepted(fixture);pilot(fixture,request)
    before=state(fixture)
    with psycopg.connect(DATABASE_URL,autocommit=True) as connection:
        oid=connection.execute("select 'authority_connections.system_user_requests'::regclass::oid").fetchone()[0]
        contracted=connection.execute("select to_regclass('public.system_user_requests') is null").fetchone()[0]
        rf_active=connection.execute("select prosrc like '%authority_connections.lock_rf_request_v1%' from pg_proc where oid='public.begin_production_filing(uuid)'::regprocedure").fetchone()[0]
        if contracted:
            connection.execute((ROOT/"supabase"/"rollback"/CONTRACT).read_text())
        if rf_active:
            connection.execute((ROOT/"supabase"/"rollback"/RF_MIGRATION).read_text())
        operator_active=connection.execute("select to_regprocedure('authority_connections.begin_operation_v1(uuid,text,text,jsonb)')").fetchone()[0] is not None
        if operator_active:
            connection.execute((ROOT/"supabase"/"rollback"/OPERATIONS_MIGRATION).read_text())
        connection.execute((ROOT/"supabase"/"rollback"/MIGRATION).read_text())
        try:
            assert connection.execute("select 'public.system_user_requests'::regclass::oid").fetchone()[0]==oid
            assert connection.execute("select to_regclass('billing.production_pilot_entitlements')").fetchone()[0]
            assert connection.execute("select status from public.system_user_requests where id=%s",(request.request_id,)).fetchone()[0]=="accepted"
            assert connection.execute("select to_regprocedure('authority_connections.begin_request_v1(uuid,uuid,text)'),to_regprocedure('authority_connections.record_authority_state_v1(uuid,uuid,uuid,text,text,text,text)'),to_regprocedure('billing.suspend_pilot_for_authority_failure_v1(uuid,uuid,uuid)')").fetchone()==(None,None,None)
            assert connection.execute("select has_schema_privilege('authority_connections_executor','authority_connections','USAGE')").fetchone()[0] is False
            with projection_connection(fixture,"billing_store_owner",actor=fixture["admin"]) as projection:
                rows=projection.execute("select * from authority_connections.lock_verified_pilot_request_v1(%s,%s,%s)",(request.request_id,fixture["company"],fixture["owner"])).fetchall()
                assert [(str(row[0]),row[1]) for row in rows]==[(request.request_id,request.identity.external_reference)]
        finally:
            connection.execute((ROOT/"supabase"/"migrations"/MIGRATION).read_text())
            if operator_active:
                connection.execute((ROOT/"supabase"/"migrations"/OPERATIONS_MIGRATION).read_text())
            if rf_active:
                connection.execute((ROOT/"supabase"/"migrations"/RF_MIGRATION).read_text())
            if contracted:
                connection.execute((ROOT/"supabase"/"contract-migrations"/CONTRACT).read_text())
            ensure_fixture_admin_access(connection)
    assert state(fixture)==before
    assert asyncio.run(store.read_request(owner,request.request_id))==request


def projection_connection(fixture, role, *, actor=None, fresh=True):
    """Only the fixture admin borrows a role; the application login remains narrow."""
    from contextlib import contextmanager

    @contextmanager
    def context():
        borrowed=False
        with psycopg.connect(DATABASE_URL) as grant:
            principal=grant.execute("select current_user").fetchone()[0]
            borrowed=not grant.execute("select pg_has_role(current_user,%s,'SET')",(role,)).fetchone()[0]
            if borrowed: grant.execute(sql.SQL("grant {} to {}").format(sql.Identifier(role),sql.Identifier(principal)))
        try:
            with psycopg.connect(DATABASE_URL) as connection:
                connection.execute(sql.SQL("set local role {}").format(sql.Identifier(role)))
                values=claims(fixture,actor=actor,fresh=fresh)
                connection.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true)",(values["sub"],json.dumps(values)))
                yield connection
        finally:
            if borrowed:
                with psycopg.connect(DATABASE_URL) as grant:
                    grant.execute(sql.SQL("revoke {} from {}").format(sql.Identifier(role),sql.Identifier(principal)))
    return context()


def test_billing_projection_requires_current_fresh_admin_and_exact_verified_request(fixture):
    _,_,request=accepted(fixture)
    query="select * from authority_connections.lock_verified_pilot_request_v1(%s,%s,%s)"
    parameters=(request.request_id,fixture["company"],fixture["owner"])
    with projection_connection(fixture,"billing_store_owner",actor=fixture["admin"]) as connection:
        rows=connection.execute(query,parameters).fetchall()
        assert [(str(row[0]),row[1]) for row in rows]==[(request.request_id,request.identity.external_reference)]
        assert connection.execute(query,(request.request_id,fixture["company"],fixture["outsider"])).fetchall()==[]
    for actor,fresh in [(fixture["owner"],True),(fixture["admin"],False)]:
        with projection_connection(fixture,"billing_store_owner",actor=actor,fresh=fresh) as connection:
            with pytest.raises(psycopg.errors.RaiseException,match="production_pilot_admin_required"):
                with connection.transaction(): connection.execute(query,parameters)
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute("update authority_connections.system_user_requests set preflight_verified_at=null where id=%s",(request.request_id,))
    with projection_connection(fixture,"billing_store_owner",actor=fixture["admin"]) as connection:
        assert connection.execute(query,parameters).fetchall()==[]


def test_company_access_support_projection_preserves_opened_case_scope(fixture):
    _,_,request=accepted(fixture)
    case_id=uuid4()
    with psycopg.connect(DATABASE_URL) as connection:
        insert(connection,"public.support_access_grants",{
            "case_id":case_id,"company_id":fixture["company"],"operator_user_id":fixture["admin"],
            "reason":"service_recovery","scopes":["authority"],"starts_at":fixture["now"],
            "expires_at":fixture["now"]+timedelta(hours=1),"granted_by":fixture["admin"],
        })
    with projection_connection(fixture,"company_access_executor",actor=fixture["admin"]) as connection:
        connection.execute("select set_config('talli.support_case_id',%s,true)",(str(case_id),))
        assert connection.execute("select authority_connections.read_support_requests_v1(%s,%s)",(fixture["company"],case_id)).fetchone()[0]==[]
    with psycopg.connect(DATABASE_URL) as connection:
        insert(connection,"public.support_case_openings",{
            "actor_id":fixture["admin"],"operation_id":uuid4(),"case_id":case_id,"company_id":fixture["company"],
        })
    with projection_connection(fixture,"company_access_executor",actor=fixture["admin"]) as connection:
        resources=connection.execute("select resources from public.company_access_read_support_case(%s)",(case_id,)).fetchone()[0]
        rows=resources["system_user_requests"]
        assert len(rows)==1 and rows[0]["id"]==request.request_id
        assert set(rows[0])=={"id","company_id","obligation","status","failure_code","requested_at","updated_at"}
        assert rows[0]["status"]=="accepted"
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute("update public.support_access_grants set revoked_at=now(),revoked_by=%s,revocation_reason='case_closed' where case_id=%s",(fixture["admin"],case_id))
    with projection_connection(fixture,"company_access_executor",actor=fixture["admin"]) as connection:
        with pytest.raises(psycopg.errors.RaiseException,match="support_access_not_available"):
            with connection.transaction(): connection.execute("select resources from public.company_access_read_support_case(%s)",(case_id,))


@pytest.fixture
def rf151_predecessor_topology(fixture):
    """Rehearse frozen AU lifecycle SQL only after its RF successor rolls back."""
    phase = None
    with psycopg.connect(DATABASE_URL) as connection:
        if connection.execute("select to_regclass('shareholder_register_filing.migration_state')").fetchone()[0]:
            # This read-only phase probe borrows authority within a transaction
            # that is always rolled back; it changes no persistent ACL/membership.
            try:
                principal = connection.execute("select current_user").fetchone()[0]
                if not connection.execute("select pg_has_role(current_user,'shareholder_register_filing_store_owner','SET')").fetchone()[0]:
                    connection.execute(sql.SQL("grant shareholder_register_filing_store_owner to {} with set true granted by {}").format(
                        sql.Identifier(principal),sql.Identifier(principal)))
                connection.execute("set local role shareholder_register_filing_store_owner")
                phase = connection.execute("select shareholder_register_filing.phase_v1()").fetchone()[0]
                assert phase in ('legacy_overlap','canonical_overlap','contracted')
            finally:
                connection.rollback()
    if phase is not None:
        with psycopg.connect(DATABASE_URL,autocommit=True) as connection:
            connection.execute((ROOT/"supabase"/"rollback"/RF151_EXPAND).read_text())
    try:
        yield
    finally:
        if phase is not None:
            with psycopg.connect(DATABASE_URL,autocommit=True) as connection:
                connection.execute((ROOT/"supabase"/"migrations"/RF151_EXPAND).read_text())
                if phase in ('canonical_overlap','contracted'):
                    connection.execute((ROOT/"supabase"/"migrations"/RF151_CUTOVER).read_text())
                if phase == 'contracted':
                    connection.execute((ROOT/"supabase"/"contract-migrations"/RF151_CONTRACT).read_text())
                ensure_fixture_admin_access(connection)


@pytest.fixture
def legacy_overlap(fixture,rf151_predecessor_topology):
    with psycopg.connect(DATABASE_URL,autocommit=True) as connection:
        contracted=connection.execute("select to_regclass('public.system_user_requests') is null").fetchone()[0]
        if contracted:
            connection.execute((ROOT/"supabase"/"rollback"/CONTRACT).read_text())
            ensure_fixture_admin_access(connection)
    try:
        yield
    finally:
        if contracted:
            with psycopg.connect(DATABASE_URL,autocommit=True) as connection:
                connection.execute((ROOT/"supabase"/"contract-migrations"/CONTRACT).read_text())
                ensure_fixture_admin_access(connection)


def test_temporary_overlap_preserves_legacy_owner_start_and_atomic_failure(fixture,legacy_overlap):
    request_id=str(uuid4());external_ref=uuid4().hex+uuid4().hex[:11]
    # Prove the legacy function owner works without fixture-borrowed store roles.
    with psycopg.connect(DATABASE_URL) as connection:
        principal=connection.execute("select current_user").fetchone()[0]
        connection.execute(sql.SQL("revoke authority_connections_store_owner,billing_store_owner from {}").format(sql.Identifier(principal)))
    try:
        with projection_connection(fixture,"authenticated") as connection:
            legacy_claims=claims(fixture)
            legacy_claims["amr"][0]["timestamp"]=int(legacy_claims["amr"][0]["timestamp"])
            connection.execute("select set_config('request.jwt.claims',%s,true)",(json.dumps(legacy_claims),))
            created=connection.execute("select to_jsonb(public.begin_system_user_request(%s,%s,%s))",(request_id,fixture["company"],external_ref)).fetchone()[0]
            assert created["status"]=="creating"
        provider=str(uuid4());confirmation="https://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id="+provider
        with projection_connection(fixture,"service_role") as connection:
            connection.execute("select set_config('request.jwt.claims',%s,true)",(json.dumps({"role":"service_role"}),))
            result=connection.execute("select to_jsonb(public.record_system_user_authority_state(%s,%s,%s,%s,'accepted',%s,null,null))",(request_id,fixture["company"],provider,external_ref,confirmation)).fetchone()[0]
            assert result["status"]=="accepted"
    finally:
        with psycopg.connect(DATABASE_URL) as connection: ensure_fixture_admin_access(connection)
    store=session(fixture);owner=owner_for(fixture,store)
    request=asyncio.run(store.read_request(owner,request_id));pilot_id=pilot(fixture,request)
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(sql.SQL("revoke authority_connections_store_owner,billing_store_owner from {}").format(sql.Identifier(principal)))
    try:
        with projection_connection(fixture,"service_role") as connection:
            connection.execute("select set_config('request.jwt.claims',%s,true)",(json.dumps({"role":"service_role"}),))
            result=connection.execute("select to_jsonb(public.record_system_user_authority_state(%s,%s,%s,%s,'verification_failed',%s,'network_error',null))",(request_id,fixture["company"],provider,external_ref,confirmation)).fetchone()[0]
            assert result["status"]=="verification_failed"
    finally:
        with psycopg.connect(DATABASE_URL) as connection: ensure_fixture_admin_access(connection)
    with psycopg.connect(DATABASE_URL) as connection:
        assert connection.execute("select status,approved_by from billing.production_pilot_entitlements where id=%s",(pilot_id,)).fetchone()==("suspended",fixture["admin"])


def test_runtime_ledger_role_cannot_read_or_edit_migration_acl_bookkeeping(fixture):
    with projection_connection(fixture,"ledger_store_owner") as connection:
        assert connection.execute("select * from backend_system.authority_connections_overlap_grants").fetchall()==[]
        assert connection.execute("update backend_system.authority_connections_overlap_grants set grantee=current_user").rowcount==0


def test_final_contract_removes_legacy_authority_and_only_recorded_overlap_grants(fixture):
    store,owner,request=accepted(fixture)
    before=state(fixture)
    with psycopg.connect(DATABASE_URL,autocommit=True) as connection:
        contracted=connection.execute("select to_regclass('public.system_user_requests') is null").fetchone()[0]
        if not contracted:
            connection.execute((ROOT/"supabase"/"contract-migrations"/CONTRACT).read_text())
        ensure_fixture_admin_access(connection)
        principal=connection.execute("select current_user").fetchone()[0]
        grants=connection.execute("select target,grantee,target_oid from backend_system.authority_connections_overlap_grants order by target,grantee").fetchall()
        assert grants,"the fixture must exercise actual temporary grants"
        connection.execute(sql.SQL("revoke authority_connections_store_owner,billing_store_owner from {}").format(sql.Identifier(principal)))
        try:
            assert connection.execute("select to_regclass('public.system_user_requests'),to_regclass('public.authority_operations')").fetchone()==(None,None)
            assert connection.execute("select to_regprocedure('public.begin_system_user_request(uuid,uuid,text)'),to_regprocedure('public.record_system_user_authority_state(uuid,uuid,uuid,text,text,text,text,uuid)'),to_regprocedure('public.verify_system_user_preflight(uuid,text)')").fetchone()==(None,None,None)
            for target,grantee,oid in grants:
                if target.endswith("schema_usage"):
                    allowed=connection.execute("select has_schema_privilege(%s,%s::oid,'USAGE')",(grantee,oid)).fetchone()[0]
                elif target.startswith("request_"):
                    allowed=connection.execute("select has_table_privilege(%s,%s::oid,%s)",(grantee,oid,target.removeprefix("request_").upper())).fetchone()[0]
                else:
                    column={"pilot_updated_at_update":"updated_at","pilot_binding_select":"system_user_request_id"}.get(target,"status")
                    privilege="UPDATE" if target.endswith("update") else "SELECT"
                    allowed=connection.execute("select has_column_privilege(%s,%s::oid,%s,%s)",(grantee,oid,column,privilege)).fetchone()[0]
                assert allowed is False,f"temporary privilege survived contract: {target}"
            with projection_connection(fixture,"authenticated") as legacy:
                with pytest.raises(psycopg.errors.UndefinedFunction):
                    with legacy.transaction():
                        legacy.execute("select public.begin_system_user_request(%s::uuid,%s::uuid,%s::text)",(str(uuid4()),fixture["company"],"a"*43))
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    with legacy.transaction(): legacy.execute("select * from authority_connections.system_user_requests")
            assert asyncio.run(store.read_request(owner,request.request_id))==request
        finally:
            if not contracted:
                connection.execute((ROOT/"supabase"/"rollback"/CONTRACT).read_text())
            ensure_fixture_admin_access(connection)
    assert state(fixture)==before
