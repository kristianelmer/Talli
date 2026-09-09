"""Real restricted RF role, owner locks, original release gates and receipts.

Runs only on the canonical disposable database. Provider and object transfers
are local fakes; Documents metadata and every RF invocation use actual SQL.
"""

import asyncio
import base64
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb
import pytest

from talli_backend.adapters.postgres_shareholder_register_filing import PostgresShareholderRegisterFilingSession, _PersistenceError
from talli_backend.adapters.supabase_documents import SupabaseDocumentsPersistence
from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration, _VerifiedActor
from talli_backend.modules.shareholder_register_filing.public import (
    Rf1086ProductionError, ProductionOperationFailure, Rf1086Preview, Rf1086ReconciliationArtifact,
    Rf1086ReconciliationSnapshot,
)
from talli_backend.modules.shareholder_register_filing.production import (
    rf1086_current_manifest, rf1086_current_manifest_hash, rf1086_preview_payload_hash,
)
from talli_backend.modules.documents.public import StoredDocumentObject
from talli_backend.modules.documents.service import DocumentsService
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, UserId
from test_authority_connections_database_runtime import delete_fixture_company


pytestmark = pytest.mark.authority_database
DATABASE_URL = os.environ.get("DATABASE_URL", "")
SIGNOFFS = ("launch_legal_name_public_copy", "legal_policy_pack", "security_restore", "support_rollback", "founder_production_go_live", "rf1086_authority")
OBLIGATION = "aksjonaerregisteroppgaven"
PROFILE = "rf1086_no_activity_v1"
MAIN_XML, SUB_XML = "<H>original ø</H>", "<U>original</U>"


def insert(connection, table, values):
    connection.execute(sql.SQL("insert into {} ({}) values ({})").format(
        sql.Identifier(*table.split(".")), sql.SQL(",").join(map(sql.Identifier, values)),
        sql.SQL(",").join(sql.Placeholder() for _ in values)), tuple(values.values()))


def delete_legacy_fixture_projections(connection, company):
    """Remove only this fixture's frozen overlap projections as their table owner.

    Exact trigger modes are restored within the same transaction; an exception
    rolls back both fixture DML and trigger DDL. No application ACL is changed.
    """
    tables = ("filing_review_comments", "filing_overrides", "filing_submissions", "filing_previews", "authority_permissions", "authority_test_runs")
    with connection.transaction():
        triggers = connection.execute(
            "select c.relname,t.tgname,t.tgenabled from pg_trigger t join pg_class c on c.oid=t.tgrelid "
            "join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relname=any(%s) "
            "and not t.tgisinternal order by c.relname,t.tgname", (list(tables),)).fetchall()
        for table, name, _ in triggers:
            connection.execute(sql.SQL("alter table {} disable trigger {}").format(sql.Identifier("public",table),sql.Identifier(name)))
        for table in tables:
            connection.execute(sql.SQL("delete from {} where company_id=%s").format(sql.Identifier("public",table)),(company,))
        for table,name,mode in triggers:
            command = {"O":"enable", "D":"disable", "R":"enable replica", "A":"enable always"}[mode]
            connection.execute(sql.SQL("alter table {} {} trigger {}").format(sql.Identifier("public",table),sql.SQL(command),sql.Identifier(name)))


@pytest.fixture(scope="module")
def rf_fixture_admin_access():
    """Temporarily restore former table-owner fixture access to the existing admin.

    Application logins never receive these grants. Keep FORCE RLS unchanged;
    the designated disposable postgres principal already has BYPASSRLS. Borrow
    exact missing ACLs once so the existing lock/observer cases have no per-read
    DDL or catalog locks, and restore them after all fixture cleanup, even on error.
    """
    assert DATABASE_URL, "DATABASE_URL must identify the owned disposable test database"
    owner_role = "shareholder_register_filing_store_owner"
    tables = ("filing_previews", "filing_approval_snapshots", "production_filing_submissions",
              "production_filing_events", "production_feedback_artifacts", "authority_permissions")
    borrowed = {}
    membership_changed = False
    prior_membership = None
    with psycopg.connect(DATABASE_URL) as connection:
        principal, bypass = connection.execute(
            "select current_user,rolbypassrls from pg_roles where rolname=current_user"
        ).fetchone()
        assert bypass, "RF fixture requires the designated disposable database admin"
        if not connection.execute("select pg_has_role(current_user,%s,'SET')", (owner_role,)).fetchone()[0]:
            prior_membership = connection.execute(
                "select m.admin_option,m.inherit_option,m.set_option from pg_auth_members m "
                "join pg_roles r on r.oid=m.roleid where r.rolname=%s "
                "and m.member=(select oid from pg_roles where rolname=current_user) "
                "and m.grantor=m.member", (owner_role,),
            ).fetchone()
            connection.execute(sql.SQL("grant {} to {} with set true granted by {}").format(
                sql.Identifier(owner_role), sql.Identifier(principal), sql.Identifier(principal)))
            membership_changed = True
        schema_acl = connection.execute("select nspacl::text from pg_namespace where nspname='shareholder_register_filing'").fetchone()[0]
        schema_borrowed = not connection.execute("select has_schema_privilege(current_user,'shareholder_register_filing','USAGE')").fetchone()[0]
        for table in tables:
            relation = "shareholder_register_filing." + table
            acl, force = connection.execute("select relacl::text,relforcerowsecurity from pg_class where oid=%s::regclass", (relation,)).fetchone()
            missing = tuple(privilege for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE")
                if not connection.execute("select has_table_privilege(current_user,%s,%s)", (relation,privilege)).fetchone()[0])
            borrowed[table] = (acl, force, missing)
        connection.execute(sql.SQL("set local role {}").format(sql.Identifier(owner_role)))
        if schema_borrowed:
            connection.execute(sql.SQL("grant usage on schema shareholder_register_filing to {}").format(sql.Identifier(principal)))
        for table, (_, _, missing) in borrowed.items():
            if missing:
                connection.execute(sql.SQL("grant {} on {} to {}").format(
                    sql.SQL(",").join(map(sql.SQL,missing)), sql.Identifier("shareholder_register_filing",table), sql.Identifier(principal)))
    try:
        yield
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(sql.SQL("set local role {}").format(sql.Identifier(owner_role)))
            for table, (_, _, missing) in borrowed.items():
                if missing:
                    connection.execute(sql.SQL("revoke {} on {} from {}").format(
                        sql.SQL(",").join(map(sql.SQL,missing)), sql.Identifier("shareholder_register_filing",table), sql.Identifier(principal)))
            if schema_borrowed:
                connection.execute(sql.SQL("revoke usage on schema shareholder_register_filing from {}").format(sql.Identifier(principal)))
            connection.execute("reset role")
            for table, (acl, force, _) in borrowed.items():
                current = connection.execute("select relacl::text,relforcerowsecurity from pg_class where oid=%s::regclass", ("shareholder_register_filing."+table,)).fetchone()
                assert current == (acl,force), "RF fixture must restore exact ACL and FORCE RLS"
            assert connection.execute("select nspacl::text from pg_namespace where nspname='shareholder_register_filing'").fetchone()[0] == schema_acl
            if membership_changed:
                if prior_membership is None:
                    connection.execute(sql.SQL("revoke {} from {} granted by {}").format(
                        sql.Identifier(owner_role), sql.Identifier(principal), sql.Identifier(principal)))
                else:
                    connection.execute(sql.SQL("grant {} to {} with admin {}, inherit {}, set {} granted by {}").format(
                        sql.Identifier(owner_role), sql.Identifier(principal),
                        *(sql.SQL(str(value).lower()) for value in prior_membership), sql.Identifier(principal)))


@pytest.fixture(scope="module")
def backend_url(rf_fixture_admin_access):
    assert DATABASE_URL, "DATABASE_URL must identify the owned disposable test database"
    username, password = "rf_test_" + uuid4().hex, uuid4().hex
    borrowed = []
    with psycopg.connect(DATABASE_URL) as connection:
        principal = connection.execute("select current_user").fetchone()[0]
        for role in ("authority_connections_store_owner", "billing_store_owner", "documents_store_owner"):
            if not connection.execute("select pg_has_role(current_user,%s,'SET')", (role,)).fetchone()[0]:
                connection.execute(sql.SQL("grant {} to {} with set true granted by {}").format(
                    sql.Identifier(role), sql.Identifier(principal), sql.Identifier(principal)))
                borrowed.append(role)
        connection.execute(sql.SQL("create role {} login noinherit nobypassrls password {}").format(sql.Identifier(username), sql.Literal(password)))
        connection.execute(sql.SQL("grant shareholder_register_filing_executor,documents_executor to {} with inherit false,set true").format(sql.Identifier(username)))
    try:
        yield make_conninfo(DATABASE_URL, user=username, password=password)
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(sql.SQL("revoke shareholder_register_filing_executor,documents_executor from {}").format(sql.Identifier(username)))
            connection.execute(sql.SQL("drop role {}").format(sql.Identifier(username)))
            for role in borrowed:
                connection.execute(sql.SQL("revoke {} from {} granted by {}").format(sql.Identifier(role), sql.Identifier(principal), sql.Identifier(principal)))


@pytest.fixture
def fixture(backend_url):
    owner, outsider, company, request, entitlement, preview_id, approval = [uuid4() for _ in range(7)]
    external = base64.urlsafe_b64encode(hashlib.sha256(str(request).encode()).digest()).decode().rstrip("=")
    with psycopg.connect(DATABASE_URL) as connection:
        now = connection.execute("select clock_timestamp()-interval '1 second'").fetchone()[0]
        signoffs = connection.execute("select to_jsonb(s) from public.launch_signoffs s where key=any(%s)", (list(SIGNOFFS),)).fetchall()
        for actor in (owner, outsider):
            insert(connection, "auth.users", {"id": actor, "email": str(actor) + "@example.test"})
        insert(connection, "public.companies", {"id": company, "org_number": str(100000000 + company.int % 899999999),
            "name": "RF local fixture AS", "entity_type": "AS", "address": "Testveien 1", "postal_code": "0150", "city": "Oslo",
            "status_text": "aktiv", "source": "test", "created_by": owner, "identity_confirmed_at": now, "identity_locked_at": now})
        insert(connection, "public.company_memberships", {"company_id": company, "user_id": owner, "role": "owner", "accepted_at": now})
        insert(connection, "authority_connections.system_user_requests", {"id": request, "company_id": company,
            "initiating_owner_user_id": owner, "external_ref": external, "status": "accepted", "preflight_verified_at": now})
        insert(connection, "billing.production_pilot_entitlements", {"id": entitlement, "company_id": company, "user_id": owner,
            "income_year": 2025, "obligation": OBLIGATION, "case_profile": PROFILE, "status": "active", "billing_exempt": True,
            "system_user_request_id": request, "system_user_external_reference": external, "starts_at": now,
            "expires_at": now + timedelta(days=30), "evidence_reference": "local-rf-fixture", "approved_by": owner})
        insert(connection, "shareholder_register_filing.filing_previews", {"id": preview_id, "company_id": company, "income_year": 2025,
            "filing": OBLIGATION, "status": "ready", "preview": "local fixture", "hovedskjema_xml": MAIN_XML,
            "underskjema_xml": Jsonb({str(owner): SUB_XML}), "created_by": owner})
        preview = Rf1086Preview(str(preview_id), str(company), 2025, OBLIGATION, MAIN_XML, {str(owner): SUB_XML}, ())
        insert(connection, "shareholder_register_filing.filing_approval_snapshots", {"id": approval, "entitlement_id": entitlement, "preview_id": preview_id,
            "company_id": company, "user_id": owner, "income_year": 2025, "obligation": OBLIGATION, "case_profile": PROFILE,
            "adapter_version": "rf1086-production-v1", "payload_hash": rf1086_preview_payload_hash(preview),
            "manifest_hash": rf1086_current_manifest_hash(preview, actor_id=str(owner), organization_number=str(100000000 + company.int % 899999999)),
            "manifest": Jsonb(rf1086_current_manifest(preview, actor_id=str(owner), organization_number=str(100000000 + company.int % 899999999))), "approved_by": owner})
        insert(connection, "shareholder_register_filing.authority_permissions", {"company_id": company, "obligation": OBLIGATION,
            "submitter_user_id": owner, "confirmed_by": owner, "production_enabled": True})
        insert(connection, "public.filing_readiness_snapshots", {"company_id": company, "income_year": 2025,
            "obligation": OBLIGATION, "status": "ready", "ready": True, "created_by": owner})
        for key in SIGNOFFS:
            connection.execute("insert into public.launch_signoffs(key,status,reviewer,reviewed_at,evidence_link,decision,recorded_by) "
                "values(%s,'approved','Local fixture',%s,'local-rf-fixture','approved',%s) on conflict(key) do update "
                "set status=excluded.status,reviewer=excluded.reviewer,reviewed_at=excluded.reviewed_at,"
                "evidence_link=excluded.evidence_link,decision=excluded.decision,recorded_by=excluded.recorded_by",
                (key, now, owner))
    data = dict(url=backend_url, owner=owner, outsider=outsider, company=company, request=request,
        entitlement=entitlement, preview=preview_id, approval=approval, now=now, external=external)
    try:
        yield data
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            delete_legacy_fixture_projections(connection, company)
            connection.execute("delete from shareholder_register_filing.production_feedback_artifacts where company_id=%s", (company,))
            connection.execute("delete from documents.evidence_references where document_id in (select id from public.documents where company_id=%s)", (company,))
            connection.execute("delete from shareholder_register_filing.production_filing_submissions where company_id=%s", (company,))
            connection.execute("delete from shareholder_register_filing.filing_approval_snapshots where company_id=%s", (company,))
            connection.execute("delete from shareholder_register_filing.filing_previews where company_id=%s", (company,))
            connection.execute("delete from public.documents where company_id=%s", (company,))
            connection.execute("delete from billing.production_pilot_entitlements where company_id=%s", (company,))
            connection.execute("delete from authority_connections.system_user_requests where company_id=%s", (company,))
            connection.execute("delete from shareholder_register_filing.authority_permissions where company_id=%s", (company,))
            connection.execute("delete from public.filing_readiness_snapshots where company_id=%s", (company,))
            connection.execute("delete from public.company_archive_source_generations where company_id=%s", (company,))
            delete_fixture_company(connection, company)
            connection.execute("delete from public.launch_signoffs where key=any(%s)", (list(SIGNOFFS),))
            for row in signoffs:
                connection.execute("insert into public.launch_signoffs select * from jsonb_populate_record(null::public.launch_signoffs,%s::jsonb)", (json.dumps(row[0]),))
            connection.execute("delete from auth.users where id=any(%s::uuid[])", ([owner, outsider],))


def claims(fixture, *, actor=None, fresh=True):
    return {"sub": str(actor or fixture["owner"]), "role": "authenticated", "aal": "aal2",
        "amr": [{"method": "totp", "timestamp": int((fixture["now"] - timedelta(hours=1) if not fresh else fixture["now"]).timestamp())}]}


def store(fixture, *, actor=None, fresh=True, documents=None, storage_transport=None):
    actor_id = ActorId(ActorKind.USER, UserId(str(actor or fixture["owner"])))
    result = PostgresShareholderRegisterFilingSession(LedgerSupabaseConfiguration("https://project.example.test", "", fixture["url"]),
        _VerifiedActor(actor_id, json.dumps(claims(fixture, actor=actor, fresh=fresh))), access_token="verified-fixture-session",
        billing=None, documents=documents, company_access=None, storage_transport=storage_transport)
    result._roles[str(fixture["company"])] = "owner"
    return result


def begin(fixture, session=None):
    return asyncio.run((session or store(fixture)).begin_production_filing(str(fixture["approval"])))


def confirmed(fixture, session=None):
    session = session or store(fixture)
    submission_id = begin(fixture, session)
    main, transmission, dialog = [str(uuid4()) for _ in range(3)]
    journal = session.operation_journal(submission_id)
    async def execute():
        for name, body, reference in [
            ("post_hovedskjema", MAIN_XML, main), ("post_underskjema:" + str(fixture["owner"]), SUB_XML, "posted"),
            ("confirm", main + ":1", json.dumps({"dialogId": dialog, "forsendelseId": transmission}, separators=(",", ":"))),
            ("list_documents", None, '{"documentCount":0}')]:
            operation = await journal.prepare(submission_id=submission_id, name=name,
                body_hash=hashlib.sha256(body.encode()).hexdigest() if body else None, idempotency_key=str(uuid4()) if body else None)
            await journal.succeed(operation.id, reference)
    asyncio.run(execute())
    return submission_id, transmission


def test_contracted_begin_retains_exact_bound_identity_and_needs_no_foreign_table_grants(fixture):
    session = store(fixture)
    assert asyncio.run(session.read_approval(str(fixture["approval"]))).company_id == str(fixture["company"])
    assert asyncio.run(session.read_connection(str(fixture["request"]), str(fixture["company"]))).external_ref == fixture["external"]
    submission = begin(fixture, session)
    assert begin(fixture, session) == submission
    with psycopg.connect(DATABASE_URL) as connection:
        assert connection.execute("select to_regclass('public.system_user_requests')").fetchone()[0] is None
        assert connection.execute("select pg_has_role('talli_ledger_backend','shareholder_register_filing_executor','SET'), "
            "pg_has_role('talli_ledger_backend','shareholder_register_filing_executor','USAGE')").fetchone() == (True, False)
        assert connection.execute("select company_id,user_id,approval_id,entitlement_id,status from shareholder_register_filing.production_filing_submissions where id=%s", (submission,)).fetchone() == (
            fixture["company"], fixture["owner"], fixture["approval"], fixture["entitlement"], "sending")
        for table in ("billing.production_pilot_entitlements", "authority_connections.system_user_requests", "public.documents"):
            assert not connection.execute("select has_table_privilege('shareholder_register_filing_executor',%s,'SELECT')", (table,)).fetchone()[0]
        assert not connection.execute("select has_table_privilege('shareholder_register_filing_executor','shareholder_register_filing.production_filing_events','INSERT')").fetchone()[0]


@pytest.mark.parametrize("gate", ["stale_mfa", "approval_invalidated", "pilot_expired", "pilot_suspended", "preflight_missing",
    "external_reference_changed", "permission_removed", "readiness_blocked", "restore_stale", *SIGNOFFS])
def test_begin_rechecks_each_original_release_gate_without_creating_submission(fixture, gate):
    with psycopg.connect(DATABASE_URL) as connection:
        if gate == "approval_invalidated":
            connection.execute("update shareholder_register_filing.filing_approval_snapshots set invalidated_at=now(),invalidation_reason='fixture' where id=%s", (fixture["approval"],))
        elif gate == "pilot_expired":
            connection.execute("update billing.production_pilot_entitlements set starts_at=now()-interval '2 days',expires_at=now()-interval '1 day' where id=%s", (fixture["entitlement"],))
        elif gate == "pilot_suspended":
            connection.execute("update billing.production_pilot_entitlements set status='suspended' where id=%s", (fixture["entitlement"],))
        elif gate == "preflight_missing":
            connection.execute("update authority_connections.system_user_requests set preflight_verified_at=null where id=%s", (fixture["request"],))
        elif gate == "external_reference_changed":
            connection.execute("update billing.production_pilot_entitlements set system_user_external_reference='mismatched-reference' where id=%s", (fixture["entitlement"],))
        elif gate == "permission_removed":
            connection.execute("update shareholder_register_filing.authority_permissions set production_enabled=false where company_id=%s", (fixture["company"],))
        elif gate == "readiness_blocked":
            connection.execute("update public.filing_readiness_snapshots set hard_blocks='[\"block\"]'::jsonb where company_id=%s", (fixture["company"],))
        elif gate == "restore_stale":
            connection.execute("update public.launch_signoffs set reviewed_at=now()-interval '31 days' where key='security_restore'")
        elif gate in SIGNOFFS:
            connection.execute("update public.launch_signoffs set status='pending' where key=%s", (gate,))
    with pytest.raises((Rf1086ProductionError, _PersistenceError)):
        begin(fixture, store(fixture, fresh=gate != "stale_mfa"))
    with psycopg.connect(DATABASE_URL) as connection:
        assert connection.execute("select count(*) from shareholder_register_filing.production_filing_submissions where company_id=%s", (fixture["company"],)).fetchone()[0] == 0


def test_current_owner_origin_and_verified_claims_cannot_be_substituted(fixture):
    submission = begin(fixture)
    outsider = store(fixture, actor=fixture["outsider"])
    assert asyncio.run(outsider.read_approval(str(fixture["approval"]))) is None
    assert asyncio.run(outsider.read_preview(str(fixture["preview"]))) is None
    assert asyncio.run(outsider.read_submission(submission)) is None
    with pytest.raises(_PersistenceError):
        asyncio.run(outsider.read_connection(str(fixture["request"]), str(fixture["company"])))
    with psycopg.connect(fixture["url"]) as connection:
        connection.execute("set local role shareholder_register_filing_executor")
        connection.execute("select set_config('request.jwt.claims',%s,true)", (json.dumps(claims(fixture)),))
        with pytest.raises(psycopg.errors.RaiseException, match="verified_owner_required"):
            with connection.transaction():
                connection.execute("select * from shareholder_register_filing.filing_approval_snapshots")
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute("update public.company_memberships set role='read_only' where company_id=%s", (fixture["company"],))
    assert asyncio.run(store(fixture).read_submission(submission)) is None
    with pytest.raises(_PersistenceError):
        asyncio.run(store(fixture).claim_feedback_lease(submission, str(uuid4())))


def test_interrupted_preparation_preserves_uuid_body_and_never_becomes_fresh_preparation(fixture):
    session = store(fixture)
    submission = begin(fixture, session)
    key, other = str(uuid4()), str(uuid4())
    digest = hashlib.sha256(MAIN_XML.encode()).hexdigest()
    async def execute():
        first = await session.operation_journal(submission).prepare(submission_id=submission, name="post_hovedskjema", body_hash=digest, idempotency_key=key)
        resumed = await session.operation_journal(submission).prepare(submission_id=submission, name="post_hovedskjema", body_hash="0"*64, idempotency_key=other)
        return first, resumed
    first, resumed = asyncio.run(execute())
    assert first.state == "prepared" and resumed.state == "unknown"
    assert first.id == resumed.id and resumed.idempotency_key == key and resumed.body_hash == digest
    with psycopg.connect(DATABASE_URL) as connection:
        assert connection.execute("select count(*) from shareholder_register_filing.production_filing_events where submission_id=%s", (submission,)).fetchone()[0] == 1


def test_retry_cap_twenty_uses_same_persisted_key_and_stops(fixture):
    session = store(fixture)
    submission = begin(fixture, session)
    digest, key = hashlib.sha256(MAIN_XML.encode()).hexdigest(), str(uuid4())
    async def execute():
        for attempt in range(1, 21):
            journal = session.operation_journal(submission)
            operation = await journal.prepare(submission_id=submission, name="post_hovedskjema", body_hash=digest, idempotency_key=key)
            assert operation.attempt == attempt and operation.idempotency_key == key
            await journal.fail(operation.id, ProductionOperationFailure("retryable", "GLD_004", None))
        return await session.operation_journal(submission).prepare(submission_id=submission, name="post_hovedskjema", body_hash=digest, idempotency_key=str(uuid4()))
    last = asyncio.run(execute())
    assert last.attempt == 20 and last.failure_classification == "blocked"


def test_recovery_lease_uses_confirmed_reference_after_entitlement_expiry_and_stale_mfa(fixture):
    submission, reference = confirmed(fixture)
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute("update billing.production_pilot_entitlements set starts_at=now()-interval '2 days',expires_at=now()-interval '1 day' where id=%s", (fixture["entitlement"],))
        connection.execute("update shareholder_register_filing.filing_approval_snapshots set invalidated_at=now(),invalidation_reason='fixture' where id=%s", (fixture["approval"],))
    session = store(fixture, fresh=False)
    lease, wrong = str(uuid4()), str(uuid4())
    assert asyncio.run(session.claim_feedback_lease(submission, lease))
    assert asyncio.run(session.read_claimed_reference(submission, lease)) == reference
    assert not asyncio.run(session.claim_feedback_lease(submission, wrong))
    with pytest.raises(Rf1086ProductionError):
        asyncio.run(session.read_claimed_reference(submission, wrong))
    asyncio.run(session.release_feedback_lease(submission, wrong))
    assert asyncio.run(session.read_claimed_reference(submission, lease)) == reference
    asyncio.run(session.release_feedback_lease(submission, lease))
    assert asyncio.run(session.claim_feedback_lease(submission, wrong))
    asyncio.run(session.release_feedback_lease(submission, wrong))


class LocalStorage:
    def __init__(self): self.objects = {}
    async def create_upload_transfer(self, *, bucket, storage_key):
        return "https://unused.invalid", "local-signed-token"
    async def read_object(self, *, bucket, storage_key):
        return self.objects[storage_key]
    async def remove_object(self, *, bucket, storage_key):
        self.objects.pop(storage_key, None)
    def upload(self, request):
        from urllib.parse import unquote
        path = unquote(request.url.path.split("/company-documents/", 1)[1])
        self.objects[path] = StoredDocumentObject(request.content, request.headers["content-type"])
        return httpx.Response(200, json={"Key": path})


class OwnedDocuments:
    def __init__(self, fixture, storage): self.fixture, self.storage = fixture, storage
    async def session(self, _):
        session = store(self.fixture)
        return DocumentsService(SupabaseDocumentsPersistence(self.fixture["url"], session._verified,
            {CompanyId(str(self.fixture["company"])): "owner"}), self.storage)


def test_real_documents_contract_stored_receipt_and_hash_drive_final_feedback_without_metadata_duplication(fixture):
    storage = LocalStorage()
    session = store(fixture, documents=OwnedDocuments(fixture, storage), storage_transport=httpx.MockTransport(storage.upload))
    submission, reference = confirmed(fixture, session)
    lease = str(uuid4())
    assert asyncio.run(session.claim_feedback_lease(submission, lease))
    journal = session.feedback_journal(submission_id=submission, company_id=str(fixture["company"]), income_year=2025,
        forsendelse_id=reference, lease_id=lease)
    raw = b"<tilbakemelding>immutable local receipt</tilbakemelding>"
    digest = hashlib.sha256(raw).hexdigest()
    artifact = Rf1086ReconciliationArtifact(submission, str(fixture["company"]), str(uuid4()), "application/xml", raw, len(raw), digest, "accepted")
    assert asyncio.run(journal.record_artifact(artifact)) == digest
    assert asyncio.run(journal.record_artifact(artifact)) == digest
    snapshot = Rf1086ReconciliationSnapshot("accepted", (digest,), "RF1086_FEEDBACK_ACCEPTED")
    assert asyncio.run(journal.append_reconciliation(snapshot))
    assert not asyncio.run(journal.append_reconciliation(snapshot))
    assert asyncio.run(journal.read_reconciliation_state()).artifact_hashes == (digest,)
    with pytest.raises(_PersistenceError):
        asyncio.run(journal.append_reconciliation(Rf1086ReconciliationSnapshot("rejected", (digest,), "RF1086_FEEDBACK_REJECTED")))
    asyncio.run(session.release_feedback_lease(submission, lease))
    with psycopg.connect(DATABASE_URL) as connection:
        row = connection.execute("select d.status,d.content_sha256,d.byte_length,d.storage_key,a.sha256 "
            "from shareholder_register_filing.production_feedback_artifacts a join public.documents d on d.id=a.document_id where a.submission_id=%s", (submission,)).fetchone()
        assert row[:3] == ("stored", digest, len(raw)) and row[4] == digest
        assert row[3].startswith(str(fixture["company"]) + "/2025/")
        assert connection.execute("select count(*) from shareholder_register_filing.production_feedback_artifacts where submission_id=%s", (submission,)).fetchone()[0] == 1
    assert len(storage.objects) == 1


def test_request_lock_is_acquired_before_billing_pilot_lock(fixture):
    async def check():
        session = store(fixture)
        with psycopg.connect(DATABASE_URL) as lock:
            lock.execute("select id from authority_connections.system_user_requests where id=%s for update", (fixture["request"],))
            pending = asyncio.create_task(session.begin_production_filing(str(fixture["approval"])))
            observed = False
            for _ in range(60):
                await asyncio.sleep(.01)
                with psycopg.connect(DATABASE_URL) as observer:
                    observed = observer.execute("select exists(select 1 from pg_stat_activity where wait_event_type='Lock' and query like 'select id from shareholder_register_filing.begin_production_filing%')").fetchone()[0]
                    if observed:
                        observer.execute("select id from billing.production_pilot_entitlements where id=%s for update nowait", (fixture["entitlement"],))
                        break
            assert observed, "begin must be waiting for its original exact System User lock"
            lock.commit()
            return await pending
    assert asyncio.run(check())


def test_year_scoped_archive_source_ignores_unrelated_legacy_preview_decode_failure(fixture):
    from talli_backend.modules.shareholder_register_filing.public import Rf1086ArchiveQuery, ShareholderRegisterFilingError
    from talli_backend.shared.kernel import IncomeYear
    historical=uuid4()
    with psycopg.connect(DATABASE_URL) as connection:
        insert(connection,'shareholder_register_filing.filing_previews',{
            'id':historical,'company_id':fixture['company'],'income_year':2024,'filing':OBLIGATION,'status':'ready',
            'preview':'Retained original warning shape','issues':Jsonb([{'level':'warning','message':'historical'}]),'created_by':fixture['owner'],
        })
    session=store(fixture)
    result=asyncio.run(session.archive_source(Rf1086ArchiveQuery(
        company_id=CompanyId(str(fixture['company'])),income_year=IncomeYear(2025),actor_id=session.actor_id)))
    assert [row.id for row in result.previews]==[str(fixture['preview'])]
    with pytest.raises(ShareholderRegisterFilingError) as captured:
        asyncio.run(session.archive_source(Rf1086ArchiveQuery(
            company_id=CompanyId(str(fixture['company'])),income_year=IncomeYear(2024),actor_id=session.actor_id)))
    assert captured.value.code=='SHAREHOLDER_REGISTER_FILING_DEPENDENCY_UNAVAILABLE'


def test_old_and_new_backend_journal_invocations_share_one_submission_during_overlap(fixture):
    from psycopg.conninfo import conninfo_to_dict
    root=Path(__file__).resolve().parents[3]
    login=conninfo_to_dict(fixture['url'])['user']
    reverse=root/'supabase/rollback/20260909190955_shareholder_register_filing_contract.sql'
    contract=root/'supabase/contract-migrations/20260909190955_shareholder_register_filing_contract.sql'
    with psycopg.connect(DATABASE_URL,autocommit=True) as admin:
        admin.execute(reverse.read_text())
        admin.execute(sql.SQL('grant legacy_rf1086_executor to {} with inherit false,set true').format(sql.Identifier(login)))
    try:
        def old_begin():
            with psycopg.connect(fixture['url']) as connection:
                actor=str(fixture['owner']);verified=json.dumps(claims(fixture))
                connection.execute('set local role legacy_rf1086_executor')
                connection.execute("select set_config('request.jwt.claims',%s,true),set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true)",(verified,actor,verified))
                return str(connection.execute('select id from public.begin_production_filing(%s)',(fixture['approval'],)).fetchone()[0])
        original=old_begin()
        assert begin(fixture)==original
        assert old_begin()==original
        with psycopg.connect(DATABASE_URL) as admin:
            assert admin.execute('select count(*) from shareholder_register_filing.production_filing_submissions where approval_id=%s',(fixture['approval'],)).fetchone()[0]==1
    finally:
        with psycopg.connect(DATABASE_URL,autocommit=True) as admin:
            admin.execute(sql.SQL('revoke legacy_rf1086_executor from {}').format(sql.Identifier(login)))
            admin.execute(contract.read_text())
