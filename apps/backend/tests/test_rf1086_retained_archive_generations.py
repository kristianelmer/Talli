"""RF evidence invalidates archive receipts through the actual owner stores."""
import asyncio
import json
import re
from uuid import uuid4

import psycopg
import pytest

from test_annual_purchase_basis_runtime import admitted
from test_rf1086_database_runtime import backend_url, rf_fixture_admin_access
from test_rf1086_year_source_database import session, inputs, capture, query, DATABASE_URL, ROOT, remove_only_owned_source_fixture
from test_rf1086_source_preview_database import generate, remove_only_preview_fixture

pytestmark = pytest.mark.authority_database
MIGRATION = '20260930160335_rf1086_retained_archive_generations.sql'


def identify(db, seed):
    claims = json.dumps({'sub': str(seed['owner']), 'role': 'authenticated', 'aal': 'aal2',
                        'amr': [{'method': 'totp', 'timestamp': seed['now'].timestamp()}]})
    db.execute("select set_config('request.jwt.claims',%s,true),set_config('talli.verified_actor_id',%s,true),"
               "set_config('talli.verified_actor_claims',%s,true)", (claims, str(seed['owner']), claims))


def begin(seed, year=2026, complete=False):
    with psycopg.connect(DATABASE_URL) as db:
        identify(db, seed)
        attempt = db.execute('select public.company_archive_begin_export(%s,%s)', (seed['company'], year)).fetchone()[0]
        if complete:
            db.execute('select public.company_archive_complete_export(%s,%s)', (attempt, 'a' * 64))
        return attempt


def generations(seed):
    with psycopg.connect(DATABASE_URL) as db:
        return dict(db.execute('select income_year,generation from public.company_archive_source_generations where company_id=%s',
                               (seed['company'],)).fetchall())


def test_unapproved_source_and_preview_invalidate_completed_and_inflight_exports(admitted, backend_url):
    store = session(admitted, backend_url)
    command, context = inputs(admitted, store)
    begin(admitted, complete=True)
    with psycopg.connect(DATABASE_URL) as db:
        identify(db, admitted)
        with pytest.raises(RuntimeError, match='undo cancellation baseline'):
            with db.transaction():
                state = db.execute('select status from public.company_access_request_cancellation(%s,%s,2026,%s)',
                    (uuid4(), admitted['company'], 'Synthetic current archive baseline')).fetchone()[0]
                assert state == 'retention_hold'
                raise RuntimeError('undo cancellation baseline')
    inflight = begin(admitted)
    before = generations(admitted)
    source = capture(store, command, context)
    assert generations(admitted)[2026] > before[2026]
    with psycopg.connect(DATABASE_URL) as db:
        identify(db, admitted)
        with pytest.raises(psycopg.Error, match='archive_export_stale'):
            with db.transaction():
                db.execute('select public.company_archive_complete_export(%s,%s)', (inflight, 'b' * 64))
        with pytest.raises(psycopg.Error, match='cancellation_prerequisite_failed'):
            with db.transaction():
                db.execute('select public.company_access_request_cancellation(%s,%s,2026,%s)',
                           (uuid4(), admitted['company'], 'Synthetic stale archive must not authorize cancellation'))
    # A new unreviewed preview changes only source history, not legacy previews.
    inflight = begin(admitted)
    before = generations(admitted)
    preview = generate(store, source)
    assert generations(admitted)[2026] > before[2026]
    with psycopg.connect(DATABASE_URL) as db:
        with pytest.raises(psycopg.Error, match='archive_export_stale'):
            db.execute('select public.company_archive_complete_export(%s,%s)', (inflight, 'c' * 64))
    stable = generations(admitted)
    assert generate(store, source) == preview
    assert generations(admitted) == stable, 'an identical preview read/replay must not invalidate exports'


def test_generation_migration_replay_and_first_activation_preserve_evidence_and_authority(admitted, backend_url):
    store = session(admitted, backend_url)
    command, context = inputs(admitted, store)
    source = capture(store, command, context)
    begin(admitted, year=2025, complete=True)
    begin(admitted, complete=True)
    body = re.sub(r'(?m)^begin;\s*$', '', (ROOT / 'supabase/migrations' / MIGRATION).read_text(), count=1)
    body = re.sub(r'commit;\s*$', '', body)
    before = generations(admitted)
    for first_activation in (False, True):
        with psycopg.connect(DATABASE_URL) as db:
            try:
                roles = db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall()
                acl = db.execute("select proacl::text from pg_proc where oid='public.company_archive_track_source_write_v1()'::regprocedure").fetchone()
                protections = db.execute("select c.oid,c.relrowsecurity,c.relforcerowsecurity,c.relacl::text from pg_class c "
                    "where c.oid in (select tgrelid from pg_trigger where tgname='company_archive_track_retained_rf') order by c.oid").fetchall()
                if first_activation:
                    db.execute('set local role shareholder_register_filing_store_owner')
                    db.execute('drop trigger company_archive_track_retained_rf on shareholder_register_filing.year_source_versions')
                    db.execute('reset role')
                db.execute(body)
                after = dict(db.execute('select income_year,generation from public.company_archive_source_generations where company_id=%s',
                                        (admitted['company'],)).fetchall())
                assert after == {year: value + int(first_activation) for year, value in before.items()}
                assert db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall() == roles
                assert db.execute("select proacl::text from pg_proc where oid='public.company_archive_track_source_write_v1()'::regprocedure").fetchone() == acl
                assert db.execute("select c.oid,c.relrowsecurity,c.relforcerowsecurity,c.relacl::text from pg_class c "
                    "where c.oid in (select tgrelid from pg_trigger where tgname='company_archive_track_retained_rf') order by c.oid").fetchall() == protections
                rows = db.execute("select c.relforcerowsecurity,t.tgtype,t.tgenabled,encode(t.tgargs,'escape') "
                    "from pg_trigger t join pg_class c on c.oid=t.tgrelid where t.tgname='company_archive_track_retained_rf'").fetchall()
                assert len(rows) == 10
                assert all(kind == (29 if args.startswith('company') else 31) and enabled == 'O'
                           for _, kind, enabled, args in rows)
                assert sum(args.startswith('company') for *_, args in rows) == 2
            finally:
                db.rollback()
        assert generations(admitted) == before, 'rollback must also undo technical generation changes'
        assert asyncio.run(store.read_current_year_source(query(command))) == source
