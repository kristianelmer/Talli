"""Documents-owned historical metadata proof on the disposable real database.

Positive retention uses released restricted stage/finalize/retain calls. Owned
corruption fixtures always roll back; no object-store, foreign owner or provider
authority is fabricated. Local collection is not SQL/RLS/race execution proof.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from queue import Queue
import time
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from talli_backend.adapters.postgres_document_originals import _receipt, _snapshot_document
from talli_backend.adapters.supabase_documents import _document
from talli_backend.modules.documents.evidence import metadata_text
from talli_backend.modules.documents.public import DocumentStatus, document_metadata_sha256
from test_document_originals_database import original, retain, DATABASE_URL, ROOT, PDF

pytestmark = pytest.mark.authority_database
MIGRATION = '20261009232839_documents_historical_original_integrity.sql'
GOVERNANCE_SUCCESSOR = '20261009234529_governance_register_evidence_amendments.sql'
ASSERTION = 'documents.assert_historical_original_integrity_v1(uuid,uuid,uuid,integer,text,text,integer,timestamptz,timestamptz,text)'
TABLE = 'documents.retained_originals'
UNSET = object()


@pytest.fixture(scope='module')
def documents_authority():
    """Borrow only missing SET, restoring the exact original membership edge."""
    assert DATABASE_URL, 'DATABASE_URL must identify the owned disposable database'
    changed = False; prior = None
    with psycopg.connect(DATABASE_URL) as db:
        principal, bypass = db.execute('select current_user,rolbypassrls from pg_roles where rolname=current_user').fetchone()
        assert bypass
        if not db.execute("select pg_has_role(current_user,'documents_store_owner','SET')").fetchone()[0]:
            prior = db.execute("select admin_option,inherit_option,set_option from pg_auth_members where roleid='documents_store_owner'::regrole and member=current_user::regrole and grantor=member").fetchone()
            db.execute(sql.SQL('grant documents_store_owner to {} with set true granted by {}').format(sql.Identifier(principal), sql.Identifier(principal)))
            changed = True
    try: yield principal
    finally:
        if changed:
            with psycopg.connect(DATABASE_URL) as db:
                db.execute(sql.SQL('revoke documents_store_owner from {} granted by {}').format(sql.Identifier(principal), sql.Identifier(principal)))
                if prior is not None:
                    db.execute(sql.SQL('grant documents_store_owner to {} with admin {},inherit {},set {} granted by {}').format(
                        sql.Identifier(principal), *(sql.SQL(str(v).lower()) for v in prior), sql.Identifier(principal)))


@pytest.fixture(scope='module')
def backend_url(documents_authority):
    """Documents-only disposable login; no broad inherited fixture authority."""
    name, password = 'document_integrity_' + uuid4().hex, uuid4().hex
    with psycopg.connect(DATABASE_URL) as db:
        db.execute(sql.SQL('create role {} login noinherit nobypassrls password {}').format(sql.Identifier(name), sql.Literal(password)))
        db.execute(sql.SQL('grant documents_executor to {} with inherit false,set true').format(sql.Identifier(name)))
    try: yield make_conninfo(DATABASE_URL, user=name, password=password)
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute(sql.SQL('revoke documents_executor from {}').format(sql.Identifier(name)))
            db.execute(sql.SQL('drop role {}').format(sql.Identifier(name)))


@pytest.fixture(scope='module')
def assertion_role(documents_authority):
    name = 'document_assertion_fixture_' + uuid4().hex
    with psycopg.connect(DATABASE_URL) as db:
        db.execute((ROOT / 'supabase/migrations' / MIGRATION).read_text())
        db.execute((ROOT / 'supabase/migrations' / GOVERNANCE_SUCCESSOR).read_text())
        db.execute(sql.SQL('create role {} nologin noinherit nobypassrls').format(sql.Identifier(name)))
        db.execute(sql.SQL('grant {} to {} with inherit false,set true').format(sql.Identifier(name), sql.Identifier(documents_authority)))
        grant_assertion(db, name)
    try: yield name
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('set local role documents_store_owner')
            db.execute(sql.SQL('revoke all on function ' + ASSERTION + ' from {}').format(sql.Identifier(name)))
            db.execute(sql.SQL('revoke usage on schema documents from {}').format(sql.Identifier(name)))
            db.execute('reset role')
            # DROP removes membership edges itself. Keep creator ADMIN until
            # then: PostgreSQL 17 requires it for a non-superuser to drop roles.
            db.execute(sql.SQL('drop role {}').format(sql.Identifier(name)))


def grant_assertion(db, role):
    db.execute('set local role documents_store_owner')
    db.execute(sql.SQL('grant usage on schema documents to {}').format(sql.Identifier(role)))
    db.execute(sql.SQL('grant execute on function ' + ASSERTION + ' to {}').format(sql.Identifier(role)))
    db.execute('reset role')


@pytest.fixture
def retained(original, assertion_role):
    return original | {'receipt': retain(original), 'role': assertion_role}


@contextmanager
def connection(seed, *, actor=None, role=None, isolation=None):
    with psycopg.connect(DATABASE_URL) as db:
        if isolation: db.execute(sql.SQL('set transaction isolation level {}').format(sql.SQL(isolation)))
        db.execute(sql.SQL('set local role {}').format(sql.Identifier(role or seed['role'])))
        actor = actor or seed['owner']
        claims = json.dumps({'sub': str(actor), 'role': 'authenticated', 'aal': 'aal2'})
        db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true),set_config('request.jwt.claims',%s,true),set_config('talli.authorized_company_roles',%s,true)",
            (str(actor), claims, claims, json.dumps({str(seed['company']): 'owner'})))
        db.execute("set local statement_timeout='8s';set local lock_timeout='5s'")
        yield db


def assert_integrity(db, seed, *, cutoff=UNSET, **changes):
    receipt = seed['receipt']
    args = dict(original=receipt.original_id, document=receipt.document_id.value, company=receipt.company_id.value,
        year=receipt.source_income_year.value, metadata=receipt.metadata_sha256, sha=receipt.content_sha256,
        length=receipt.byte_length, retained_at=receipt.retained_at,
        not_after=db.execute('select clock_timestamp()').fetchone()[0] if cutoff is UNSET else cutoff,
        subject=db.execute("select current_setting('talli.verified_actor_id')").fetchone()[0])
    args.update(changes)
    row = db.execute('select * from documents.assert_historical_original_integrity_v1(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)', tuple(args.values())).fetchone()
    assert len(row) == 1 and isinstance(row[0], str)
    return row[0]


def stored(seed):
    with connection(seed, role='documents_store_owner') as db:
        return db.execute('select document_snapshot from ' + TABLE + ' where id=%s', (seed['receipt'].original_id,)).fetchone()[0]


def rows(seed):
    with connection(seed, role='documents_store_owner') as db:
        return db.execute("select coalesce(jsonb_agg(to_jsonb(r) order by id),'[]'::jsonb) from " + TABLE + ' r where company_id=%s', (seed['company'],)).fetchone()[0]


@contextmanager
def corrupt(seed, *, snapshot=None, **changes):
    """Owned privileged corruption only; row, trigger and RLS changes roll back."""
    with connection(seed, role='documents_store_owner') as db:
        try:
            db.execute('alter table ' + TABLE + ' no force row level security')
            db.execute('alter table ' + TABLE + ' disable trigger retained_original_immutable')
            if snapshot is not None: changes['document_snapshot'] = Jsonb(snapshot)
            assert changes
            db.execute(sql.SQL('update ' + TABLE + ' set {} where id=%s').format(
                sql.SQL(',').join(sql.SQL('{}=%s').format(sql.Identifier(key)) for key in changes)), (*changes.values(), seed['receipt'].original_id))
            db.execute(sql.SQL('set local role {}').format(sql.Identifier(seed['role'])))
            yield db
        finally: db.rollback()


def test_restricted_public_retention_returns_unchanged_16_field_metadata_without_bytes_or_writes(retained):
    before = rows(retained); expected = metadata_text(retained['document'])
    assert len(stored(retained)) == 23
    for cutoff in (retained['receipt'].retained_at, retained['receipt'].retained_at.astimezone(timezone(timedelta(hours=-4)))):
        with connection(retained) as db:
            assert assert_integrity(db, retained, cutoff=cutoff) == expected
            assert assert_integrity(db, retained) == expected
    assert len(json.loads(expected)) == 16
    assert sha256(expected.encode()).hexdigest() == retained['receipt'].metadata_sha256
    assert rows(retained) == before
    assert retain(retained) == retained['receipt'] and rows(retained) == before


@pytest.mark.parametrize('field', ['original', 'document', 'year', 'metadata', 'sha', 'length', 'retained_at'])
@pytest.mark.parametrize('absent', [False, True])
def test_exact_receipt_arguments_cannot_be_omitted_or_changed(retained, field, absent):
    value = None if absent else {'original': str(uuid4()), 'document': str(uuid4()), 'year': 2024,
        'metadata': 'f' * 64, 'sha': 'e' * 64, 'length': 1,
        'retained_at': retained['receipt'].retained_at + timedelta(microseconds=1)}[field]
    with connection(retained) as db:
        with pytest.raises(psycopg.Error, match='documents_invalid_input' if absent else 'documents_evidence_mismatch'):
            assert_integrity(db, retained, **{field: value})


def test_owner_of_two_companies_cannot_rebind_historical_original(retained):
    other = uuid4()
    with psycopg.connect(DATABASE_URL) as db:
        db.execute("insert into public.companies(id,org_number,name,entity_type,source,created_by) values(%s,%s,'Other owned AS','AS','test',%s)",
            (other, str(100000000 + other.int % 899999999), retained['owner']))
        db.execute("insert into public.company_memberships(company_id,user_id,role,accepted_at) values(%s,%s,'owner',clock_timestamp())", (other, retained['owner']))
    with connection(retained) as db:
        with pytest.raises(psycopg.Error, match='documents_evidence_mismatch'): assert_integrity(db, retained, company=other)


@pytest.mark.parametrize('cutoff', [None, 'infinity', '-infinity', '0001-01-01 BC', '9999-01-01T00:00:00Z', 'before'])
def test_finite_nonfuture_cutoff_bounds_exact_retention_time(retained, cutoff):
    error = 'documents_invalid_input'
    if cutoff == 'before': cutoff = retained['receipt'].retained_at - timedelta(microseconds=1); error = 'documents_evidence_mismatch'
    with connection(retained) as db:
        with pytest.raises(psycopg.Error, match=error): assert_integrity(db, retained, cutoff=cutoff)


@pytest.mark.parametrize('case', ['missing_actor', 'subject', 'null_subject', 'tenant', 'null_tenant', 'outsider', 'pending', 'reader', 'revoked'])
def test_verified_current_owner_required_despite_cached_role_map(retained, case):
    changes = {}; actor = retained['outsider'] if case == 'outsider' else None
    if case == 'subject': changes['subject'] = str(retained['outsider'])
    elif case == 'null_subject': changes['subject'] = None
    elif case in ('tenant', 'null_tenant'): changes['company'] = uuid4() if case == 'tenant' else None
    elif case in ('pending', 'reader', 'revoked'):
        with psycopg.connect(DATABASE_URL) as db:
            if case == 'revoked': db.execute('delete from public.company_memberships where company_id=%s', (retained['company'],))
            elif case == 'pending': db.execute('update public.company_memberships set accepted_at=null where company_id=%s', (retained['company'],))
            else: db.execute("update public.company_memberships set role='read_only' where company_id=%s", (retained['company'],))
    with connection(retained, actor=actor) as db:
        if case == 'missing_actor': db.execute("select set_config('talli.verified_actor_id','',true)"); changes['subject'] = str(retained['owner'])
        with pytest.raises(psycopg.Error, match='documents_forbidden'): assert_integrity(db, retained, **changes)


@pytest.mark.parametrize('isolation', ['repeatable read', 'serializable'])
def test_stale_transaction_snapshots_are_rejected(retained, isolation):
    with connection(retained, isolation=isolation) as db:
        with pytest.raises(psycopg.Error, match='documents_guard_requires_read_committed'): assert_integrity(db, retained)


def test_another_current_owner_can_read_original_creator_and_retainer(retained):
    with psycopg.connect(DATABASE_URL) as db:
        db.execute("insert into public.company_memberships(company_id,user_id,role,accepted_at) values(%s,%s,'owner',clock_timestamp())", (retained['company'], retained['outsider']))
        db.execute('delete from public.company_memberships where company_id=%s and user_id=%s', (retained['company'], retained['owner']))
    with connection(retained, actor=retained['outsider']) as db:
        assert assert_integrity(db, retained) == metadata_text(retained['document'])


def test_historical_snapshot_remains_valid_after_current_document_metadata_changes(retained):
    with connection(retained, role='documents_store_owner') as db:
        with db.cursor(row_factory=dict_row) as cur:
            newer = _document(cur.execute('update public.documents set name=%s,income_year=2026 where id=%s returning *',
                ('Changed current metadata.pdf', retained['document'].document_id.value)).fetchone())
    newer_receipt = retain(retained, document=newer)
    assert newer_receipt.original_id != retained['receipt'].original_id
    with connection(retained) as db:
        assert assert_integrity(db, retained) == metadata_text(retained['document'])
        assert assert_integrity(db, retained | {'receipt': newer_receipt}) == metadata_text(newer)


@pytest.mark.parametrize('field', ['id', 'company_id', 'income_year', 'content_sha256', 'byte_length'])
def test_self_consistent_snapshot_digest_cannot_rebind_stored_receipt(retained, field):
    snapshot = stored(retained)
    snapshot[field] = str(uuid4()) if field in ('id', 'company_id') else 2024 if field == 'income_year' else 'f' * 64 if field == 'content_sha256' else len(PDF) + 1
    digest = document_metadata_sha256(_snapshot_document(snapshot))
    # Matching supplied/stored metadata labels cannot prove a different raw
    # document identity, source year, byte hash or length against this receipt.
    with corrupt(retained, snapshot=snapshot, metadata_sha256=digest) as db:
        with pytest.raises(psycopg.Error, match='documents_evidence_mismatch'): assert_integrity(db, retained, metadata=digest)


@pytest.mark.parametrize('attack', ['label_only', 'changed_snapshot_old_label'])
def test_recomputed_metadata_is_required_beyond_matching_caller_and_stored_labels(retained, attack):
    snapshot = stored(retained)
    if attack == 'label_only': digest = 'f' * 64
    else: snapshot['name'] = 'Uncommitted different metadata.pdf'; digest = retained['receipt'].metadata_sha256
    with corrupt(retained, snapshot=snapshot, metadata_sha256=digest) as db:
        with pytest.raises(psycopg.Error, match='documents_evidence_mismatch'): assert_integrity(db, retained, metadata=digest)


def test_restricted_direct_retention_cannot_supply_its_own_metadata_provenance(original, assertion_role):
    """Released SQL accepts a metadata label; the new assertion derives it."""
    forged_sha = 'f' * 64
    assert forged_sha != document_metadata_sha256(original['document'])
    with psycopg.connect(original['url']) as db:
        db.execute('set local role documents_executor')
        db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.authorized_company_roles',%s,true)",
            (str(original['owner']), json.dumps({str(original['company']): 'owner'})))
        value = db.execute('select documents.retain_original_v1(%s,%s,%s,%s,%s,%s,%s)',
            (original['document'].document_id.value, original['company'], forged_sha,
             sha256(PDF).hexdigest(), len(PDF), PDF, str(original['owner']))).fetchone()[0]
        receipt = _receipt(value['receipt'])
        # This old public assertion only matches stored/supplied receipt labels.
        historical = db.execute('select documents.assert_historical_original_v1(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (receipt.original_id, receipt.document_id.value, receipt.company_id.value,
             receipt.source_income_year.value, receipt.metadata_sha256, receipt.content_sha256,
             receipt.byte_length, receipt.retained_at, str(original['owner']))).fetchone()[0]
        assert historical == value['document']
    seed = original | {'receipt': receipt, 'role': assertion_role}
    before = rows(seed)
    with connection(seed) as db:
        with pytest.raises(psycopg.Error, match='documents_evidence_mismatch'):
            assert_integrity(db, seed)
    assert receipt.metadata_sha256 == forged_sha and rows(seed) == before


@pytest.mark.parametrize('field,value', [
    ('id', 'not-a-uuid'), ('company_id', {}), ('income_year', True), ('income_year', '2025'),
    ('income_year', 2025.5), ('income_year', 1999), ('name', None), ('name', {}),
    ('document_type', []), ('linked_to', False), ('status', 'invented'), ('retention_years', True),
    ('retention_years', '5'), ('retention_years', 2147483648), ('storage_key', {}),
    ('content_type', []), ('byte_length', True), ('byte_length', '24'), ('byte_length', 0),
    ('byte_length', 10485761), ('content_sha256', 'A' * 64), ('created_by', None),
    ('created_at', 'infinity'), ('created_at', '2025-01-01T00:00:00'), ('created_at', True),
    ('removed_at', 'not-a-time'), ('removal_reason', []), ('removed_by', False),
    ('declared_byte_length', True), ('declared_byte_length', '24'), ('declared_byte_length', 10485761),
    ('staged_at', 'not-a-time'), ('quarantined_at', {}), ('quarantine_reason', False),
    ('final_status', []), ('removed_from_status', {}),
])
def test_known_sql_snapshot_field_types_fail_closed(retained, field, value):
    snapshot = stored(retained); snapshot[field] = value
    with corrupt(retained, snapshot=snapshot) as db:
        with pytest.raises(psycopg.Error, match='documents_evidence_mismatch'): assert_integrity(db, retained)


@pytest.mark.parametrize('field', ['id', 'content_type', 'removed_by', 'staged_at', 'final_status', 'removed_from_status'])
def test_raw_sql_snapshot_does_not_invent_missing_column_defaults(retained, field):
    snapshot = stored(retained); del snapshot[field]
    with corrupt(retained, snapshot=snapshot) as db:
        with pytest.raises(psycopg.Error, match='documents_evidence_mismatch'): assert_integrity(db, retained)


def test_unknown_raw_sql_column_cannot_be_silently_ignored(retained):
    snapshot = stored(retained); snapshot['owner_verified'] = True
    with corrupt(retained, snapshot=snapshot) as db:
        with pytest.raises(psycopg.Error, match='documents_evidence_mismatch'): assert_integrity(db, retained)


@pytest.mark.parametrize('status', list(DocumentStatus))
def test_integrity_does_not_add_future_consumer_status_or_removal_admission(retained, status):
    # Valid historical representation fixture, not a claim that the current
    # retain command accepts every status. Future consumers decide usable state.
    snapshot = stored(retained); snapshot['status'] = status.value
    snapshot['removed_at'] = retained['receipt'].retained_at.isoformat() if status is DocumentStatus.REMOVED else None
    snapshot['removal_reason'] = 'Historical reason' if status is DocumentStatus.REMOVED else None
    document = _snapshot_document(snapshot); digest = document_metadata_sha256(document)
    with corrupt(retained, snapshot=snapshot, metadata_sha256=digest) as db:
        assert assert_integrity(db, retained, metadata=digest) == metadata_text(document)


@pytest.mark.parametrize('case', ['empty_defaults', 'null_defaults', 'negative_retention', 'unicode', 'offset_time', 'no_auth_rows', 'later_created_at'])
def test_valid_historical_projection_preserves_existing_metadata_semantics(retained, case):
    snapshot = stored(retained); changes = {}
    if case in ('empty_defaults', 'null_defaults'):
        value = '' if case == 'empty_defaults' else None
        snapshot.update(content_type=value, removal_reason=value)
    elif case == 'negative_retention': snapshot['retention_years'] = -1
    elif case == 'unicode': snapshot['name'] = ' ø 😀 e\u0301 "slash\\\n\t\x01.pdf'
    elif case == 'offset_time': snapshot['created_at'] = datetime.fromisoformat(snapshot['created_at']).astimezone(timezone(timedelta(hours=-4))).isoformat()
    elif case == 'no_auth_rows': snapshot['created_by'] = str(uuid4()); changes['retained_by'] = uuid4()
    else: snapshot['created_at'] = (retained['receipt'].retained_at + timedelta(days=1)).isoformat()
    document = _snapshot_document(snapshot); digest = document_metadata_sha256(document)
    with corrupt(retained, snapshot=snapshot, metadata_sha256=digest, **changes) as db:
        assert assert_integrity(db, retained, metadata=digest) == metadata_text(document)


def test_existing_table_constraints_continue_to_prove_stored_byte_hash_and_length(retained):
    for changes in ({'content': b'different'}, {'byte_length': len(PDF) + 1}, {'content_sha256': 'f' * 64}):
        with pytest.raises(psycopg.errors.CheckViolation):
            with corrupt(retained, **changes): pass
    with connection(retained) as db: assert assert_integrity(db, retained) == metadata_text(retained['document'])


def wait_for_lock(pid):
    for _ in range(100):
        with psycopg.connect(DATABASE_URL) as db:
            if db.execute("select exists(select 1 from pg_stat_activity where pid=%s and wait_event='advisory')", (pid,)).fetchone()[0]: return
        time.sleep(.01)
    raise AssertionError('Owned backend did not wait on the shared company guard')


@pytest.mark.parametrize('winner', ['revocation', 'assertion'])
def test_revocation_and_assertion_follow_both_company_lock_orders(retained, winner):
    ready = Queue()
    def competing():
        if winner == 'revocation':
            with connection(retained) as db:
                ready.put(db.execute('select pg_backend_pid()').fetchone()[0]); return assert_integrity(db, retained)
        with psycopg.connect(DATABASE_URL) as db:
            ready.put(db.execute('select pg_backend_pid()').fetchone()[0])
            db.execute('select public.company_archive_lock_company_v1(%s)', (retained['company'],))
            db.execute("update public.company_memberships set role='read_only' where company_id=%s", (retained['company'],))
    with ThreadPoolExecutor(max_workers=1) as pool:
        with psycopg.connect(DATABASE_URL) as first:
            if winner == 'revocation':
                first.execute('select public.company_archive_lock_company_v1(%s)', (retained['company'],))
                first.execute("update public.company_memberships set role='read_only' where company_id=%s", (retained['company'],))
            else:
                first.execute(sql.SQL('set local role {}').format(sql.Identifier(retained['role'])))
                first.execute("select set_config('talli.verified_actor_id',%s,true)", (str(retained['owner']),))
                assert assert_integrity(first, retained) == metadata_text(retained['document'])
            pending = pool.submit(competing); pid = ready.get(timeout=5); wait_for_lock(pid); assert not pending.done()
        if winner == 'revocation':
            with pytest.raises(psycopg.Error, match='documents_forbidden'): pending.result(timeout=10)
        else: pending.result(timeout=10)
    with connection(retained) as db:
        with pytest.raises(psycopg.Error, match='documents_forbidden'): assert_integrity(db, retained)


def catalog(db):
    return dict(functions=db.execute("select oid,to_jsonb(p) from pg_proc p where pronamespace='documents'::regnamespace order by oid").fetchall(),
        memberships=db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall(),
        tables=db.execute("select oid,relacl::text,relrowsecurity,relforcerowsecurity from pg_class where relnamespace='documents'::regnamespace or oid='public.documents'::regclass order by oid").fetchall(),
        schema=db.execute("select nspowner,nspacl::text from pg_namespace where nspname='documents'").fetchall())


def test_closed_assertion_helpers_reapply_and_retained_rollback_preserve_all_authority(retained):
    before_rows = rows(retained)
    try:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute((ROOT / 'supabase/migrations' / MIGRATION).read_text())
            db.execute('set local role documents_store_owner'); before = catalog(db)
            identities = db.execute("select oid from pg_proc where pronamespace='documents'::regnamespace and (proname like 'original_integrity_%' or proname='assert_historical_original_integrity_v1')").fetchall()
            assert len(identities) == 5
            roles = db.execute("select rolname from pg_roles where rolname in ('anon','authenticated','service_role') or rolname like '%executor' or rolname like '%store_owner' or rolname like '%bridge_owner'").fetchall()
            for (identity,) in identities:
                assert not db.execute('select exists(select 1 from pg_proc p cross join lateral aclexplode(p.proacl) a where p.oid=%s and a.grantee=0)', (identity,)).fetchone()[0]
                for (role,) in roles:
                    if role != 'documents_store_owner':
                        assert not db.execute("select has_function_privilege(%s,%s::oid,'EXECUTE')", (role, identity)).fetchone()[0]
            assert not db.execute("select has_function_privilege(%s,%s,'EXECUTE')", (retained['role'], ASSERTION)).fetchone()[0]
            db.execute('reset role'); db.execute((ROOT / 'supabase/migrations' / MIGRATION).read_text())
            db.execute('set local role documents_store_owner'); assert catalog(db) == before
            db.execute('reset role'); db.execute((ROOT / 'supabase/rollback' / MIGRATION).read_text())
            db.execute('set local role documents_store_owner'); assert catalog(db) == before
            db.execute('reset role'); grant_assertion(db, retained['role'])
    finally:
        # Even a failed closed-stage assertion must restore final owner grants.
        with psycopg.connect(DATABASE_URL) as restored:
            restored.execute((ROOT / 'supabase/migrations' / GOVERNANCE_SUCCESSOR).read_text())
    assert rows(retained) == before_rows
    with connection(retained) as db: assert assert_integrity(db, retained) == metadata_text(retained['document'])
    with psycopg.connect(retained['url']) as db:
        db.execute('set local role documents_executor')
        db.execute("select set_config('talli.verified_actor_id',%s,true)", (str(retained['owner']),))
        with pytest.raises(psycopg.errors.InsufficientPrivilege): assert_integrity(db, retained)
