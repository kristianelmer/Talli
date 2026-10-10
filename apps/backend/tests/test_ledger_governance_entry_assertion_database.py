"""Staged Ledger provenance assertion on the disposable authority database.

Positive entries and reversals use released restricted Ledger RPCs. Capital
corrections are unsupported by the released correction RPC, so correction-row
cases explicitly seed a legacy/future storage state through owned fixtures.
No Governance, RF, Documents, provider, or original-byte authority is asserted.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, timedelta
import json
import os
from pathlib import Path
from queue import Queue
import time
from types import SimpleNamespace
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
import pytest

from test_annual_purchase_basis_runtime import admitted, database_now, insert, scoped

pytestmark = pytest.mark.authority_database
ROOT = Path(__file__).resolve().parents[3]
DATABASE_URL = os.environ.get('DATABASE_URL', '')
MIGRATION = '20261009225857_ledger_governance_entry_assertion.sql'
GOVERNANCE_SUCCESSOR = '20261009234529_governance_register_evidence_amendments.sql'
GOVERNANCE_APPLICATION = '20261010001936_governance_register_evidence_application.sql'
SIGNATURE = 'ledger.assert_unamended_governance_entry_v1(uuid,uuid,integer,uuid,uuid,date,text,timestamptz,jsonb,text)'
TABLES = ('entries', 'entry_contexts', 'entry_sources', 'entry_reversals', 'entry_corrections',
          'cash_capital_increase_phases', 'loss_coverage_capital_reduction_phases')


def grant_fixture(db, role):
    db.execute('set local role ledger_store_owner')
    db.execute(sql.SQL('grant usage on schema ledger to {}').format(sql.Identifier(role)))
    db.execute(sql.SQL('grant execute on function ' + SIGNATURE + ' to {}').format(sql.Identifier(role)))
    db.execute('reset role')


@pytest.fixture(scope='module')
def assertion_role():
    """A unique NOLOGIN fixture role, never a runtime grant; restore SET edges."""
    assert DATABASE_URL, 'DATABASE_URL must identify the owned disposable database'
    name = 'rf193_ledger_assert_' + uuid4().hex[:12]
    borrowed = []
    with psycopg.connect(DATABASE_URL) as db:
        principal, bypass = db.execute('select current_user,rolbypassrls from pg_roles where rolname=current_user').fetchone()
        assert bypass
        for role in ('ledger_store_owner', 'ledger_executor'):
            if db.execute("select pg_has_role(current_user,%s,'SET')", (role,)).fetchone()[0]:
                continue
            prior = db.execute('select admin_option,inherit_option,set_option from pg_auth_members where roleid=%s::regrole and member=current_user::regrole and grantor=member', (role,)).fetchone()
            db.execute(sql.SQL('grant {} to {} with set true granted by {}').format(sql.Identifier(role), sql.Identifier(principal), sql.Identifier(principal)))
            borrowed.append((role, prior))
        db.execute((ROOT / 'supabase/migrations' / MIGRATION).read_text())
        db.execute((ROOT / 'supabase/migrations' / GOVERNANCE_SUCCESSOR).read_text())
        db.execute((ROOT / 'supabase/migrations' / GOVERNANCE_APPLICATION).read_text())
        db.execute(sql.SQL('create role {} nologin noinherit').format(sql.Identifier(name)))
        db.execute(sql.SQL('grant {} to {} with set true granted by {}').format(sql.Identifier(name), sql.Identifier(principal), sql.Identifier(principal)))
        grant_fixture(db, name)
    try:
        yield name
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('set local role ledger_store_owner')
            db.execute(sql.SQL('revoke all on function ' + SIGNATURE + ' from {}').format(sql.Identifier(name)))
            db.execute(sql.SQL('revoke usage on schema ledger from {}').format(sql.Identifier(name)))
            db.execute('reset role')
            db.execute(sql.SQL('revoke {} from {} granted by {}').format(sql.Identifier(name), sql.Identifier(principal), sql.Identifier(principal)))
            db.execute(sql.SQL('drop role {}').format(sql.Identifier(name)))
            for role, prior in borrowed:
                db.execute(sql.SQL('revoke {} from {} granted by {}').format(sql.Identifier(role), sql.Identifier(principal), sql.Identifier(principal)))
                if prior is not None:
                    db.execute(sql.SQL('grant {} to {} with admin {},inherit {},set {} granted by {}').format(
                        sql.Identifier(role), sql.Identifier(principal), *(sql.SQL(str(v).lower()) for v in prior), sql.Identifier(principal)))


@contextmanager
def connection(seed, role, *, actor=None, isolation=None):
    with psycopg.connect(DATABASE_URL) as db:
        if isolation:
            db.execute(sql.SQL('set transaction isolation level {}').format(sql.SQL(isolation)))
        scoped(db, actor or seed['owner'], role=role)
        db.execute("set local statement_timeout='8s'")
        db.execute("set local lock_timeout='5s'")
        yield db


def source(capability, record, *, primary=False, sha='a', revision=1):
    return {'role': 'PRIMARY' if primary else 'CORROBORATING', 'capability': capability,
            'recordId': str(record), 'revision': revision, 'factSha256': sha * 64}


def post(seed, *, kind='CAPITAL_REDUCTION', reference=None, phase=None):
    event, key = uuid4(), str(uuid4())
    reference = reference or str(uuid4())
    sources = [source('CORPORATE_GOVERNANCE', event, primary=True)]
    if kind == 'CAPITAL_INCREASE' and phase != 'subscription':
        sources += [source('BANKING', uuid4(), sha='b')]
    sources += [source('DOCUMENTS', 'corporate-document-pack:' + str(event), sha='c')]
    if phase not in ('subscription', 'restricted_payment'):
        sources += [source('SHAREHOLDER_REGISTER_FILING', uuid4(), sha='d', revision=2)]
    def line(account, debit, credit):
        return dict(account=account, description='Owned assertion fixture', debit=debit, credit=credit, currency='NOK')
    lines = [line('2000', '10000.00', '0.00'), line('2080', '0.00', '10000.00')]
    if kind == 'CAPITAL_INCREASE':
        if phase == 'subscription': lines = [line('1500', '12000.00', '0.00'), line('2030', '0.00', '12000.00')]
        elif phase == 'restricted_payment': lines = [line('1921', '12000.00', '0.00'), line('1500', '0.00', '12000.00')]
        else: lines = [line('2030', '12000.00', '0.00'), line('2000', '0.00', '10000.00'), line('2020', '0.00', '2000.00'), line('1920', '12000.00', '0.00'), line('1921', '0.00', '12000.00')]
    args = [key, seed['company'], 2026, reference, 10000]
    if kind == 'CAPITAL_INCREASE': args += [2000]
    args += ['Owned assertion fixture', Jsonb(lines), 'CORPORATE_GOVERNANCE', str(event), key,
             str(seed['owner']), date(2026, 5, 1), 'ledger-supported-patterns-2026.1', Jsonb(sources)]
    function = ('record_loss_coverage_capital_reduction_direct_registration_v1' if kind == 'CAPITAL_REDUCTION'
                else 'record_cash_capital_increase_' + (phase or 'registration') + '_v1')
    with connection(seed, 'ledger_executor') as db:
        value = db.execute(sql.SQL('select * from ledger.{}({})').format(sql.Identifier(function), sql.SQL(',').join(sql.Placeholder() for _ in args)), args).fetchone()
    return dict(seed=seed, entry=value[0], event=event, sources=sources, kind=kind, cutoff=database_now(),
                post_function=function, post_args=args, posted_at=value[4])


@pytest.fixture
def saved(admitted, assertion_role):
    return post(admitted) | {'role': assertion_role}


def call(db, item, **changes):
    values = dict(entry=item['entry'], company=item['seed']['company'], year=2026,
                  actor=item['seed']['owner'], event=item['event'], event_date=date(2026, 5, 1),
                  kind=item['kind'], cutoff=item['cutoff'], sources=item['sources'], subject=str(item['seed']['owner'])) | changes
    params = [values[k] for k in ('entry', 'company', 'year', 'actor', 'event', 'event_date', 'kind', 'cutoff')]
    params += [Jsonb(values['sources']), values['subject']]
    return db.execute('select ledger.assert_unamended_governance_entry_v1(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)', params).fetchone()


def snapshot(item):
    with connection(item['seed'], 'ledger_store_owner') as db:
        rows = {table: db.execute(sql.SQL('select coalesce(jsonb_agg(to_jsonb(t) order by to_jsonb(t)::text),\'[]\'::jsonb) from ledger.{} t where company_id=%s').format(sql.Identifier(table)), (item['seed']['company'],)).fetchone()[0] for table in TABLES}
        rows['receipts'] = db.execute('select coalesce(jsonb_agg(to_jsonb(t) order by id),\'[]\'::jsonb) from backend_system.ledger_command_receipts t where company_id=%s', (item['seed']['company'],)).fetchone()[0]
        return rows


@pytest.mark.parametrize('kind', ['CAPITAL_REDUCTION', 'CAPITAL_INCREASE'])
def test_real_typed_post_has_exact_original_binding_and_assertion_is_read_only(admitted, assertion_role, kind):
    if kind == 'CAPITAL_INCREASE':
        reference = str(uuid4())
        post(admitted, kind=kind, reference=reference, phase='subscription')
        post(admitted, kind=kind, reference=reference, phase='restricted_payment')
        item = post(admitted, kind=kind, reference=reference)
    else: item = post(admitted)
    before = snapshot(item)
    with connection(admitted, assertion_role) as db:
        call(db, item); call(db, item)
        # The cutoff equals a later Governance completion statement, not the
        # original Ledger statement; timestamps need not be identical.
        assert item['posted_at'] <= item['cutoff']
    assert snapshot(item) == before
    with connection(admitted, 'ledger_executor') as db:
        row = db.execute(sql.SQL('select * from ledger.{}({})').format(sql.Identifier(item['post_function']), sql.SQL(',').join(sql.Placeholder() for _ in item['post_args'])), item['post_args']).fetchone()
        assert row[0] == item['entry'] and row[-1] is True
    assert snapshot(item) == before


@pytest.mark.parametrize('field', ['entry', 'actor', 'event', 'event_date', 'kind', 'primary_hash', 'reference_revision', 'reference_id', 'reference_hash', 'omit', 'extra', 'order'])
def test_exact_original_binding_rejects_changes(saved, field):
    changes = {}; sources = deepcopy(saved['sources'])
    if field in ('entry', 'actor'): changes[field] = uuid4()
    elif field == 'event':
        changes['event'] = uuid4(); sources[0]['recordId'] = str(changes['event'])
    elif field == 'event_date': changes[field] = date(2026, 5, 2)
    elif field == 'kind': changes[field] = 'CAPITAL_INCREASE'
    elif field == 'primary_hash': sources[0]['factSha256'] = 'f' * 64
    elif field == 'reference_revision': sources[-1]['revision'] += 1
    elif field == 'reference_id': sources[-1]['recordId'] = str(uuid4())
    elif field == 'reference_hash': sources[-1]['factSha256'] = 'f' * 64
    elif field == 'omit': sources.pop()
    elif field == 'extra': sources.append(source('BANKING', uuid4()))
    elif field == 'order': sources[1:] = reversed(sources[1:])
    changes['sources'] = sources
    with connection(saved['seed'], saved['role']) as db:
        with pytest.raises(psycopg.Error, match='ledger_governance_entry_mismatch'): call(db, saved, **changes)


@pytest.mark.parametrize('attack', ['null', 'object', 'empty', 'scalar_item', 'unknown', 'missing_hash', 'null_hash', 'upper_hash', 'bool_revision', 'string_revision', 'fraction_revision', 'overflow_revision', 'zero_revision', 'wrong_primary_capability', 'wrong_primary_id', 'wrong_primary_revision', 'second_primary', 'duplicate', 'null_kind', 'other_kind', 'null_actor', 'null_year', 'infinite_cutoff', 'future_cutoff', 'null_cutoff'])
def test_malformed_expected_evidence_fails_closed(saved, attack):
    sources = deepcopy(saved['sources']); changes = {}
    if attack == 'null': sources = None
    elif attack == 'object': sources = {}
    elif attack == 'empty': sources = []
    elif attack == 'scalar_item': sources[1] = True
    elif attack == 'unknown': sources[1]['extra'] = 'x'
    elif attack == 'missing_hash': del sources[1]['factSha256']
    elif attack == 'null_hash': sources[1]['factSha256'] = None
    elif attack == 'upper_hash': sources[1]['factSha256'] = 'A' * 64
    elif attack.endswith('_revision') and attack != 'wrong_primary_revision':
        sources[1]['revision'] = {'bool_revision': True, 'string_revision': '1', 'fraction_revision': 1.5, 'overflow_revision': 2147483648, 'zero_revision': 0}[attack]
    elif attack == 'wrong_primary_capability': sources[0]['capability'] = 'LEDGER'
    elif attack == 'wrong_primary_id': sources[0]['recordId'] = str(uuid4())
    elif attack == 'wrong_primary_revision': sources[0]['revision'] = 2
    elif attack == 'second_primary': sources[1]['role'] = 'PRIMARY'
    elif attack == 'duplicate': sources.append(deepcopy(sources[-1]))
    elif attack == 'null_kind': changes['kind'] = None
    elif attack == 'other_kind': changes['kind'] = 'SHAREHOLDER_LOAN'
    elif attack == 'null_actor': changes['actor'] = None
    elif attack == 'null_year': changes['year'] = None
    elif attack == 'infinite_cutoff': changes['cutoff'] = 'infinity'
    elif attack == 'future_cutoff': changes['cutoff'] = saved['cutoff'] + timedelta(days=1)
    elif attack == 'null_cutoff': changes['cutoff'] = None
    with connection(saved['seed'], saved['role']) as db:
        with pytest.raises(psycopg.Error, match='ledger_governance_evidence_invalid'): call(db, saved, sources=sources, **changes)


@pytest.mark.parametrize('isolation', ['repeatable read', 'serializable'])
def test_stale_transaction_isolation_is_rejected(saved, isolation):
    with connection(saved['seed'], saved['role'], isolation=isolation) as db:
        with pytest.raises(psycopg.Error, match='rf193_company_guard_requires_read_committed'): call(db, saved)


@pytest.mark.parametrize('case', ['outsider', 'reader', 'pending', 'revoked', 'subject', 'other_company', 'unadmitted_year'])
def test_current_authority_and_scope_are_required(saved, case):
    seed = saved['seed']; changes = {}; actor = seed['owner']; error = 'ledger_forbidden'
    if case == 'outsider': actor = seed['outsider']; changes['subject'] = str(actor); error = 'ledger_not_found'
    elif case == 'subject': changes['subject'] = str(seed['outsider'])
    elif case == 'other_company':
        other = globals()['admitted'].__wrapped__(SimpleNamespace())
        with psycopg.connect(DATABASE_URL) as db:
            insert(db, 'public.company_memberships', {'company_id': other['company'], 'user_id': seed['owner'], 'role': 'owner', 'accepted_at': database_now(db)})
        changes['company'] = other['company']; error = 'ledger_governance_entry_mismatch'
    elif case == 'unadmitted_year': changes.update(year=2025, event_date=date(2025, 5, 1)); error = 'ledger_company_year_not_admitted'
    else:
        with psycopg.connect(DATABASE_URL) as db:
            if case == 'revoked': db.execute('delete from public.company_memberships where company_id=%s and user_id=%s', (seed['company'], actor))
            elif case == 'pending': db.execute('update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s', (seed['company'], actor))
            else: db.execute("update public.company_memberships set role='read_only' where company_id=%s and user_id=%s", (seed['company'], actor))
        if case in ('pending', 'revoked'): error = 'ledger_not_found'
    with connection(seed, saved['role'], actor=actor) as db:
        with pytest.raises(psycopg.Error, match=error): call(db, saved, **changes)


@pytest.mark.parametrize('case', ['early_cutoff', 'entry_time', 'posted_time', 'context_time', 'rule', 'digest', 'ordinal', 'source_hash', 'source_hash_and_expected'])
def test_stored_context_and_source_corruption_cannot_be_hidden_by_expected_digest(saved, case):
    if case == 'early_cutoff':
        with connection(saved['seed'], saved['role']) as db:
            with pytest.raises(psycopg.Error, match='ledger_governance_entry_after_cutoff'): call(db, saved, cutoff=saved['posted_at'] - timedelta(microseconds=1))
        return
    # Privileged corruption fixture only. Roll back every table/trigger change.
    with connection(saved['seed'], 'ledger_store_owner') as db:
        try:
            for table in ('entries', 'entry_contexts', 'entry_sources'):
                db.execute(sql.SQL('alter table ledger.{} no force row level security').format(sql.Identifier(table)))
            for table in ('entry_contexts', 'entry_sources'):
                db.execute(sql.SQL('alter table ledger.{} disable trigger {}').format(sql.Identifier(table), sql.Identifier('ledger_' + table + '_immutable')))
            if case in ('entry_time', 'posted_time'):
                field = 'created_at' if case == 'entry_time' else 'posted_at'
                db.execute(sql.SQL('update ledger.entries set {}=%s where id=%s').format(sql.Identifier(field)), (saved['cutoff'] + timedelta(seconds=1), saved['entry']))
            elif case == 'context_time': db.execute('update ledger.entry_contexts set recorded_at=%s where entry_id=%s', (saved['cutoff'] + timedelta(seconds=1), saved['entry']))
            elif case == 'rule': db.execute("update ledger.entry_contexts set rule_version='ledger-supported-patterns-2026.2' where entry_id=%s", (saved['entry'],))
            elif case == 'digest': db.execute('update ledger.entry_contexts set sources_digest=%s where entry_id=%s', ('f' * 64, saved['entry']))
            elif case == 'ordinal': db.execute('update ledger.entry_sources set ordinal=4 where entry_id=%s and ordinal=3', (saved['entry'],))
            else: db.execute('update ledger.entry_sources set fact_sha256=%s where entry_id=%s and ordinal=3', ('f' * 64, saved['entry']))
            changes = {}
            if case == 'source_hash_and_expected':
                expected = deepcopy(saved['sources']); expected[-1]['factSha256'] = 'f' * 64
                changes['sources'] = expected  # Equality passes; stored context digest must still reject.
            scoped(db, saved['seed']['owner'], role=saved['role'])
            with pytest.raises(psycopg.Error, match='ledger_governance_entry_after_cutoff' if case.endswith('time') else 'ledger_governance_entry_mismatch'): call(db, saved, **changes)
        finally: db.rollback()


def reverse(db, item):
    correction_source = item.setdefault('reversal_source', source('DOCUMENTS', uuid4()))
    return db.execute('select * from ledger.reverse_supported_entry_v1(%s,%s,2026,%s,%s,%s,%s,%s,%s)',
        ('assert-reversal-' + str(item['entry']), item['seed']['company'], item['entry'], 'Owned reversal', 'assert-reversal', str(item['seed']['owner']), date(2026, 6, 1), Jsonb(correction_source))).fetchone()


def correction_fixture(db, item, reversal, replacement):
    """Legacy/future immutable correction state, NOT a supported capital RPC."""
    insert(db, 'ledger.entry_corrections', dict(original_entry_id=item['entry'], reversal_entry_id=reversal['entry'],
        replacement_entry_id=replacement['entry'], company_id=item['seed']['company'], income_year=2026,
        reason='Owned legacy/future correction fixture', corrected_by=item['seed']['owner']))


def wait_for_lock(pid):
    for _ in range(100):
        with psycopg.connect(DATABASE_URL) as db:
            if db.execute("select exists(select 1 from pg_stat_activity where pid=%s and wait_event='advisory')", (pid,)).fetchone()[0]: return
        time.sleep(.01)
    raise AssertionError('Owned backend did not wait on the shared company lock')


@pytest.mark.parametrize('amendment', ['public_reversal', 'legacy_correction_fixture'])
@pytest.mark.parametrize('assertion_first', [False, True])
def test_both_company_lock_orders_serialize_assertion_with_amendment(saved, amendment, assertion_first):
    reversal = replacement = None
    if amendment == 'legacy_correction_fixture': reversal, replacement = post(saved['seed']), post(saved['seed'])
    def mutate(db):
        if amendment == 'public_reversal': reverse(db, saved)
        else: correction_fixture(db, saved, reversal, replacement)
    mutation_role = 'ledger_executor' if amendment == 'public_reversal' else 'ledger_store_owner'
    ready = Queue()
    def competing():
        with connection(saved['seed'], mutation_role if assertion_first else saved['role']) as db:
            ready.put(db.execute('select pg_backend_pid()').fetchone()[0])
            if assertion_first: mutate(db)
            else: call(db, saved)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with connection(saved['seed'], saved['role'] if assertion_first else mutation_role) as first:
            if assertion_first: call(first, saved)
            else: mutate(first)
            future = pool.submit(competing)
            wait_for_lock(ready.get(timeout=3)); assert not future.done()
        if assertion_first: future.result(timeout=8)
        else:
            with pytest.raises(psycopg.Error, match='ledger_governance_entry_amended'): future.result(timeout=8)
    with connection(saved['seed'], saved['role']) as db:
        with pytest.raises(psycopg.Error, match='ledger_governance_entry_amended'): call(db, saved)


def test_rolled_back_reversal_does_not_invalidate_original(saved):
    with connection(saved['seed'], 'ledger_executor') as db:
        reverse(db, saved); db.rollback()
    with connection(saved['seed'], saved['role']) as db: call(db, saved)


def test_original_post_and_reversal_replay_remain_historical_after_amendment(saved):
    with connection(saved['seed'], 'ledger_executor') as db: result = reverse(db, saved)
    before = snapshot(saved)
    with connection(saved['seed'], 'ledger_executor') as db:
        replay = reverse(db, saved)
        assert replay[:-1] == result[:-1] and replay[-1] is True
        original = db.execute(sql.SQL('select * from ledger.{}({})').format(sql.Identifier(saved['post_function']), sql.SQL(',').join(sql.Placeholder() for _ in saved['post_args'])), saved['post_args']).fetchone()
        assert original[0] == saved['entry'] and original[-1] is True
    assert snapshot(saved) == before
    with connection(saved['seed'], saved['role']) as db:
        with pytest.raises(psycopg.Error, match='ledger_governance_entry_amended'): call(db, saved)


def test_owner_revoked_while_assertion_waits_is_rechecked(saved):
    ready = Queue()
    def waiting():
        with connection(saved['seed'], saved['role']) as db:
            ready.put(db.execute('select pg_backend_pid()').fetchone()[0]); call(db, saved)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with psycopg.connect(DATABASE_URL) as blocker:
            blocker.execute('select public.company_archive_lock_company_v1(%s)', (saved['seed']['company'],))
            future = pool.submit(waiting); pid = ready.get(timeout=3); wait_for_lock(pid)
            assert not blocker.execute("select exists(select 1 from pg_locks where pid=%s and locktype='advisory' and granted)", (pid,)).fetchone()[0]
            blocker.execute("update public.company_memberships set role='read_only' where company_id=%s and user_id=%s", (saved['seed']['company'], saved['seed']['owner']))
        with pytest.raises(psycopg.Error, match='ledger_forbidden'): future.result(timeout=8)


def test_new_current_owner_can_prove_retained_original_actor_without_impersonating(saved):
    seed = saved['seed']; current = seed['outsider']
    with psycopg.connect(DATABASE_URL) as db:
        insert(db, 'public.company_memberships', dict(company_id=seed['company'], user_id=current,
            role='owner', accepted_at=database_now(db)))
        db.execute('delete from public.company_memberships where company_id=%s and user_id=%s', (seed['company'], seed['owner']))
    with connection(seed, saved['role'], actor=current) as db:
        call(db, saved, subject=str(current))
        with pytest.raises(psycopg.Error, match='ledger_governance_entry_mismatch'):
            call(db, saved, subject=str(current), actor=current)


def catalog(db):
    return dict(functions=db.execute("select oid,to_jsonb(p) from pg_proc p where pronamespace='ledger'::regnamespace order by oid").fetchall(),
        roles=db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by roleid,member,grantor').fetchall(),
        schema=db.execute("select oid,nspacl::text from pg_namespace where nspname='ledger'").fetchall(),
        tables=db.execute("select oid,relacl::text,relrowsecurity,relforcerowsecurity from pg_class where relnamespace='ledger'::regnamespace order by oid").fetchall())


def test_staged_runtime_acl_catalog_reapply_and_retentive_rollback(saved):
    try:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute((ROOT / 'supabase/migrations' / MIGRATION).read_text())
            before = catalog(db)
            denied = db.execute("select rolname from pg_roles where rolname in ('anon','authenticated','service_role') or rolname like '%executor' or rolname like '%store_owner' or rolname like '%bridge_owner'").fetchall()
            for (role,) in denied:
                if role == 'ledger_store_owner': continue  # Inherent function owner authority.
                assert not db.execute("select has_function_privilege(%s,%s,'EXECUTE')", (role, SIGNATURE)).fetchone()[0], role
            assert not db.execute("select exists(select 1 from aclexplode((select proacl from pg_proc where oid=%s::regprocedure)) where grantee=0)", (SIGNATURE,)).fetchone()[0]
            db.execute((ROOT / 'supabase/migrations' / MIGRATION).read_text())
            assert catalog(db) == before
            db.execute((ROOT / 'supabase/rollback' / MIGRATION).read_text())
            assert catalog(db) == before
            grant_fixture(db, saved['role'])
    finally:
        # Even a failed closed-stage assertion must restore final owner grants.
        with psycopg.connect(DATABASE_URL) as restored:
            restored.execute((ROOT / 'supabase/migrations' / GOVERNANCE_SUCCESSOR).read_text())
            restored.execute((ROOT / 'supabase/migrations' / GOVERNANCE_APPLICATION).read_text())
    with connection(saved['seed'], saved['role']) as db: call(db, saved)
    with connection(saved['seed'], 'ledger_executor') as db:
        with pytest.raises(psycopg.errors.InsufficientPrivilege): call(db, saved)
