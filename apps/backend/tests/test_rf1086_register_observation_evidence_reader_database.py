"""Selected-row RF evidence proof through a closed, restricted public SQL read.

Only collected locally; execution requires the owned fully migrated database.
Privileged corruption fixtures roll back all row/trigger/RLS changes. They test
the reader's distrust of stored claims, not an application mutation capability.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from queue import Queue
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import IdempotencyKey
from test_rf1086_register_observation import basis
from test_rf1086_register_observation_withdrawal_database import (
    staged, connection, observed, withdraw, append, old_correction, wait_for_lock,
    admitted, backend_url, cleanup_owned_fixture, rf_fixture_admin_access,
    DATABASE_URL, ROOT,
)
from test_rf1086_register_observation_database import capture, query

pytestmark = pytest.mark.authority_database
MIGRATION = '20261009231107_rf1086_current_observation_evidence_reader.sql'
GOVERNANCE_SUCCESSOR = '20261009234529_governance_register_evidence_amendments.sql'
GOVERNANCE_APPLICATION = '20261010001936_governance_register_evidence_application.sql'
REPORTING_PROJECTION = '20261010005413_governance_reporting_register_evidence.sql'
READER = 'shareholder_register_filing.read_current_register_observation_evidence_v1(uuid,uuid,integer,integer,text,timestamptz,text)'
TABLE = 'shareholder_register_filing.register_observations'
UNSET = object()


@pytest.fixture
def reader(staged):
    with psycopg.connect(DATABASE_URL) as db:
        db.execute((ROOT / 'supabase/migrations' / MIGRATION).read_text())
        db.execute((ROOT / 'supabase/migrations' / GOVERNANCE_SUCCESSOR).read_text())
        db.execute((ROOT / 'supabase/migrations' / GOVERNANCE_APPLICATION).read_text())
        db.execute((ROOT / 'supabase/migrations' / REPORTING_PROJECTION).read_text())
        db.execute('set local role shareholder_register_filing_store_owner')
        db.execute(sql.SQL('grant execute on function ' + READER + ' to {}').format(sql.Identifier(staged['role'])))
    try:
        yield staged
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('set local role shareholder_register_filing_store_owner')
            db.execute(sql.SQL('revoke execute on function ' + READER + ' from {}').format(sql.Identifier(staged['role'])))


def read(db, original, *, not_after=UNSET, **changes):
    args = dict(id=original.observation_id.value, company=original.command.company_id.value,
        year=original.command.income_year.value, revision=original.version, sha=original.fact_sha256,
        not_after=db.execute('select clock_timestamp()').fetchone()[0] if not_after is UNSET else not_after,
        subject=db.execute("select current_setting('talli.verified_actor_id')").fetchone()[0])
    args.update(changes)
    return db.execute('select * from shareholder_register_filing.read_current_register_observation_evidence_v1(%s,%s,%s,%s,%s,%s,%s)', tuple(args.values())).fetchone()


def encoded(original):
    return json.loads(rf.serialize_rf1086_register_observation(original))


def fields(payload):
    snapshot = payload['snapshot']['fields']
    return snapshot, snapshot['command']['fields']


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest_material(value):
    """Independent test-only unwrapping to forge mathematically matching hashes.

    No domain validator runs: invalid economics/confirmations/documents must
    remain invalid even after both attacker-controlled commitments are updated.
    """
    if isinstance(value, list): return [digest_material(item) for item in value]
    if isinstance(value, dict):
        if set(value) == {'record', 'fields'}: return {key: digest_material(item) for key, item in value['fields'].items()}
        if set(value) == {'enum', 'value'}: return value['value']
        if set(value) == {'decimal'}:
            number = format(Decimal(value['decimal']), 'f')
            return number.rstrip('0').rstrip('.') if '.' in number else number
        if set(value) == {'datetime'}: return datetime.fromisoformat(value['datetime']).isoformat()
        raise AssertionError('Use only the known valid wrapper shapes in digest fixtures')
    return value


def forged_hashes(payload):
    snapshot, command = fields(payload)
    material = digest_material(payload['snapshot'])
    confirmed = datetime.fromisoformat(material['confirmed_at']).astimezone(timezone.utc).isoformat()
    fact = hashlib.sha256(compact(['rf1086-register-observation-v1', material['observation_id'],
        material['version'], material['command'], confirmed]).encode()).hexdigest()
    request = hashlib.sha256(compact(['rf1086-register-observation-request-v1', material['command']]).encode()).hexdigest()
    snapshot['fact_sha256'] = fact
    return fact, request


@contextmanager
def corrupt(reader, original, *, text=None, row_changes=None):
    """Scope malformed historical storage to one transaction; always restore."""
    with connection(reader, role='shareholder_register_filing_store_owner') as db:
        try:
            db.execute('alter table ' + TABLE + ' no force row level security')
            db.execute('alter table ' + TABLE + ' disable trigger register_observation_immutable')
            changes = dict(row_changes or {})
            if text is not None: changes['snapshot_text'] = text
            assert changes
            db.execute(sql.SQL('update ' + TABLE + ' set {} where id=%s').format(
                sql.SQL(',').join(sql.SQL('{}=%s').format(sql.Identifier(key)) for key in changes)),
                (*changes.values(), original.observation_id.value))
            db.execute(sql.SQL('set local role {}').format(sql.Identifier(reader['role'])))
            yield db
        finally:
            db.rollback()


def retained_rows(reader):
    with connection(reader) as db:
        return {table: db.execute(sql.SQL('select coalesce(jsonb_agg(to_jsonb(t) order by id),\'[]\'::jsonb) from shareholder_register_filing.{} t where company_id=%s').format(sql.Identifier(table)),
            (reader['seed']['company'],)).fetchone()[0] for table in ('register_observations', 'register_observation_withdrawals')}


@pytest.mark.parametrize('kind', ['cash_issue', 'cash_nominal_increase', 'loss_covering_reduction'])
def test_actual_capture_returns_exact_canonical_snapshot_and_time_without_writes(reader, kind):
    template, _ = basis(kind)
    command = replace(reader['command'], event_kind=kind, before=template.before, after=template.after)
    original = capture(reader['store'], command, reader['context'])
    before = retained_rows(reader)
    expected = rf.serialize_rf1086_register_observation(original)
    fact, request = forged_hashes(encoded(original))
    assert fact == original.fact_sha256
    assert request == rf.rf1086_register_observation_request_digest(original.command)
    for cutoff in (original.confirmed_at, original.confirmed_at.astimezone(timezone(timedelta(hours=-4)))):
        with connection(reader) as db:
            assert read(db, original, not_after=cutoff) == (expected, original.confirmed_at)
            assert read(db, original) == (expected, original.confirmed_at)
    assert retained_rows(reader) == before


def test_current_correction_returns_selected_full_facts_and_keeps_committed_recovery(reader):
    key = IdempotencyKey(str(uuid4()))
    original = capture(reader['store'], reader['command'], reader['context'], key)
    with connection(reader) as db: successor = old_correction(db, reader, original)
    with connection(reader) as db:
        assert read(db, successor) == (rf.serialize_rf1086_register_observation(successor), successor.confirmed_at)
    with connection(reader) as db:
        with pytest.raises(psycopg.Error, match='rf1086_register_predecessor_mismatch'): read(db, original)
    assert capture(reader['store'], reader['command'], reader['context'], key) == original
    assert asyncio.run(reader['store'].read_register_observation(query(original.command), original.observation_id)) == original


@pytest.mark.parametrize('state', ['withdrawn', 'superseded'])
def test_terminal_target_fails_while_independent_current_root_remains_readable(reader, state):
    original = observed(reader)
    if state == 'withdrawn': withdraw(reader, original)
    else:
        with connection(reader) as db: old_correction(db, reader, original)
    independent = observed(reader)
    with connection(reader) as db:
        with pytest.raises(psycopg.Error, match='rf1086_register_predecessor_mismatch'): read(db, original)
    with connection(reader) as db:
        assert read(db, independent)[0] == rf.serialize_rf1086_register_observation(independent)


@pytest.mark.parametrize('changes', [{'id': str(uuid4())}, {'year': 2025}, {'revision': 2}, {'sha': '0' * 64}])
def test_exact_requested_identity_scope_revision_and_hash_are_required(reader, changes):
    original = observed(reader)
    with connection(reader) as db:
        with pytest.raises(psycopg.Error, match='rf1086_register_predecessor_mismatch'): read(db, original, **changes)


@pytest.mark.parametrize('cutoff', [None, 'infinity', '-infinity', '0001-01-01 BC', '9999-01-01T00:00:00Z', 'before_capture'])
def test_cutoff_is_finite_nonfuture_and_binds_capture_time(reader, cutoff):
    original = observed(reader)
    if cutoff == 'before_capture': cutoff = original.confirmed_at - timedelta(microseconds=1); error = 'rf1086_register_observation_after_cutoff'
    else: error = 'rf1086_register_observation_cutoff_invalid'
    with connection(reader) as db:
        with pytest.raises(psycopg.Error, match=error): read(db, original, not_after=cutoff)


@pytest.mark.parametrize('case', ['subject', 'tenant', 'outsider', 'pending', 'reader', 'revoked', 'repeatable_read'])
def test_verified_subject_current_owner_tenant_and_isolation_remain_required(reader, case):
    original = observed(reader); changes = {}; actor = None
    if case == 'subject': changes['subject'] = str(uuid4()); error = 'rf1086_forbidden'
    elif case == 'tenant': changes['company'] = str(uuid4()); error = 'rf1086_not_found'
    elif case == 'outsider': actor = reader['seed']['outsider']; error = 'rf1086_not_found'
    elif case == 'repeatable_read': error = 'rf1086_guard_requires_read_committed'
    else:
        with psycopg.connect(DATABASE_URL) as db:
            if case == 'revoked': db.execute('delete from public.company_memberships where company_id=%s and user_id=%s', (reader['seed']['company'], reader['seed']['owner']))
            elif case == 'pending': db.execute('update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s', (reader['seed']['company'], reader['seed']['owner']))
            else: db.execute("update public.company_memberships set role='read_only' where company_id=%s and user_id=%s", (reader['seed']['company'], reader['seed']['owner']))
        error = 'rf1086_forbidden' if case == 'reader' else 'rf1086_not_found'
    with connection(reader, actor=actor, repeatable_read=case == 'repeatable_read') as db:
        with pytest.raises(psycopg.Error, match=error): read(db, original, **changes)


def test_another_current_owner_reads_original_actor_without_impersonating(reader):
    original = observed(reader)
    with psycopg.connect(DATABASE_URL) as db:
        db.execute("insert into public.company_memberships(company_id,user_id,role,accepted_at) values(%s,%s,'owner',clock_timestamp())", (reader['seed']['company'], reader['seed']['outsider']))
        db.execute('delete from public.company_memberships where company_id=%s and user_id=%s', (reader['seed']['company'], reader['seed']['owner']))
    with connection(reader, actor=reader['seed']['outsider']) as db:
        assert read(db, original) == (rf.serialize_rf1086_register_observation(original), original.confirmed_at)


@pytest.mark.parametrize('field', ['actor_id', 'request_sha256', 'confirmed_at'])
def test_retained_indexed_claims_are_bound_to_valid_snapshot(reader, field):
    original = observed(reader)
    change = reader['seed']['outsider'] if field == 'actor_id' else 'f' * 64 if field == 'request_sha256' else original.confirmed_at - timedelta(microseconds=1)
    with corrupt(reader, original, row_changes={field: change}) as db:
        with pytest.raises(psycopg.Error, match='rf1086_register_storage_invalid'): read(db, original)


@pytest.mark.parametrize('field', ['observation_id', 'company_id', 'income_year', 'actor_id', 'confirmed_at'])
def test_self_consistent_body_and_recomputed_hashes_cannot_change_retained_row_identity(reader, field):
    original = observed(reader); payload = encoded(original); snapshot, command = fields(payload)
    if field == 'observation_id': snapshot[field]['fields']['value'] = str(uuid4())
    elif field == 'company_id':
        company = str(uuid4()); command[field]['fields']['value'] = company
        for doc in command['documents']: doc['fields']['company_id']['fields']['value'] = company
    elif field == 'income_year':
        command[field]['fields']['value'] = 2025
        command['effective_at']['datetime'] = original.command.effective_at.replace(year=2025).isoformat()
    elif field == 'actor_id': command[field]['fields']['subject']['fields']['value'] = str(reader['seed']['outsider'])
    else: snapshot[field]['datetime'] = (original.confirmed_at + timedelta(microseconds=1)).isoformat()
    fact, request = forged_hashes(payload)
    # The pure codec accepts this self-consistent selected object. Only binding
    # it back to the immutable stored row identifies the attempted substitution.
    assert rf.parse_rf1086_register_observation(compact(payload)).fact_sha256 == fact
    with corrupt(reader, original, text=compact(payload), row_changes={'fact_sha256': fact, 'request_sha256': request}) as db:
        with pytest.raises(psycopg.Error, match='rf1086_register_storage_invalid'): read(db, original, sha=fact)


@pytest.mark.parametrize('field', ['supersedes_observation_id', 'supersedes_observation_sha256', 'correction_reason'])
def test_self_consistent_correction_body_cannot_change_immutable_predecessor_binding(reader, field):
    original = observed(reader)
    with connection(reader) as db: successor = old_correction(db, reader, original)
    payload = encoded(successor); _, command = fields(payload)
    if field == 'supersedes_observation_id': command[field]['fields']['value'] = str(uuid4())
    elif field == 'supersedes_observation_sha256': command[field] = 'f' * 64
    else: command[field] = 'A different nonblank correction reason'
    fact, request = forged_hashes(payload)
    assert rf.parse_rf1086_register_observation(compact(payload)).fact_sha256 == fact
    with corrupt(reader, successor, text=compact(payload), row_changes={'fact_sha256': fact, 'request_sha256': request}) as db:
        with pytest.raises(psycopg.Error, match='rf1086_register_storage_invalid'): read(db, successor, sha=fact)


@pytest.mark.parametrize('field,original_token', [('version', '1'), ('share_count', '200'), ('income_year', '2026'), ('byte_length', None)])
@pytest.mark.parametrize('suffix', ['e0', '.0'])
def test_raw_exponent_and_float_tokens_cannot_hide_integer_shape_violations(reader, field, original_token, suffix):
    original = observed(reader); payload = encoded(original)
    if original_token is None: original_token = str(fields(payload)[1]['documents'][0]['fields']['byte_length'])
    text = compact(payload)
    needle = '"income_year":{"fields":{"value":2026' if field == 'income_year' else f'"{field}":{original_token}'
    assert needle in text
    changed = text.replace(needle, needle + suffix, 1)
    assert changed != text and json.loads(changed) == payload
    # Send raw text, never Jsonb: unchanged integer-value hashes cannot make the
    # legacy typed encoder emit a floating/exponent token.
    with corrupt(reader, original, text=changed) as db:
        with pytest.raises(psycopg.Error, match='rf1086_register_storage_invalid'): read(db, original)


@pytest.mark.parametrize('digits', [4301, 4400])
def test_rehashed_raw_integer_beyond_python_codec_limit_is_rejected(reader, digits):
    original = observed(reader); payload = encoded(original); snapshot, command = fields(payload)
    marker = '__raw_oversized_document_length__'
    command['documents'][0]['fields']['byte_length'] = marker
    # Construct raw numeric tokens and both exact digests without changing the
    # process-wide integer limit or converting the oversized number to an int.
    def render(value):
        return compact(value).replace(compact(marker), '1' + '0' * (digits - 1))
    material = digest_material(payload['snapshot'])
    confirmed = datetime.fromisoformat(material['confirmed_at']).astimezone(timezone.utc).isoformat()
    fact = hashlib.sha256(render(['rf1086-register-observation-v1', material['observation_id'],
        material['version'], material['command'], confirmed]).encode()).hexdigest()
    request = hashlib.sha256(render(['rf1086-register-observation-request-v1', material['command']]).encode()).hexdigest()
    snapshot['fact_sha256'] = fact
    text = render(payload)
    assert marker not in text
    with pytest.raises(rf.Rf1086RegisterObservationError, match='rf1086_register_storage_invalid'):
        rf.parse_rf1086_register_observation(text)
    with corrupt(reader, original, text=text, row_changes={'fact_sha256': fact, 'request_sha256': request}) as db:
        with pytest.raises(psycopg.Error, match='rf1086_register_storage_invalid'): read(db, original, sha=fact)


def test_valid_changed_document_commitment_with_old_fact_hash_is_rejected(reader):
    original = observed(reader); payload = encoded(original)
    fields(payload)[1]['documents'][0]['fields']['metadata_sha256'] = 'f' * 64
    with corrupt(reader, original, text=compact(payload)) as db:
        with pytest.raises(psycopg.Error, match='rf1086_register_storage_invalid'): read(db, original)


@pytest.mark.parametrize('violation', ['subject', 'exact_hash'])
def test_existing_authority_and_exact_target_checks_precede_corrupt_body_inspection(reader, violation):
    original = observed(reader)
    changes = {'subject': str(uuid4())} if violation == 'subject' else {'sha': 'f' * 64}
    error = 'rf1086_forbidden' if violation == 'subject' else 'rf1086_register_predecessor_mismatch'
    with corrupt(reader, original, text='{}') as db:
        with pytest.raises(psycopg.Error, match=error): read(db, original, **changes)


@pytest.mark.parametrize('attack', ['bad_codec', 'outer_extra', 'outer_missing', 'wrong_record', 'record_extra', 'missing_field',
    'unknown_command_field', 'plain_uuid', 'extra_uuid_field', 'wrong_actor_enum', 'plain_decimal', 'decimal_extra',
    'datetime_extra', 'bool_version', 'raw_duplicate_codec', 'raw_duplicate_nested', 'noncanonical_spacing', 'noncanonical_key_order'])
def test_closed_raw_codec_rejects_malformed_wrappers_and_duplicate_keys(reader, attack):
    original = observed(reader); payload = encoded(original); snapshot, command = fields(payload)
    if attack == 'bad_codec': payload['codec'] = 'rf1086-year-source-v1'
    elif attack == 'outer_extra': payload['extra'] = True
    elif attack == 'outer_missing': del payload['codec']
    elif attack == 'wrong_record': payload['snapshot']['record'] = 'RecordRf1086RegisterObservation'
    elif attack == 'record_extra': payload['snapshot']['extra'] = True
    elif attack == 'missing_field': del snapshot['fact_sha256']
    elif attack == 'unknown_command_field': command['owner_verified'] = True
    elif attack == 'plain_uuid': command['company_id'] = original.command.company_id.value
    elif attack == 'extra_uuid_field': command['company_id']['fields']['extra'] = True
    elif attack == 'wrong_actor_enum': command['actor_id']['fields']['kind']['enum'] = 'CompanyId'
    elif attack == 'plain_decimal': command['after']['fields']['nominal_value'] = '600'
    elif attack == 'decimal_extra': command['after']['fields']['nominal_value']['extra'] = True
    elif attack == 'datetime_extra': snapshot['confirmed_at']['extra'] = True
    elif attack == 'bool_version': snapshot['version'] = True
    text = compact(payload)
    if attack == 'raw_duplicate_codec': text = text.replace('{"codec":', '{"codec":"rf1086-register-observation-v1","codec":', 1)
    elif attack == 'raw_duplicate_nested': text = text.replace('"share_count":200', '"share_count":200,"share_count":200', 1)
    elif attack == 'noncanonical_spacing': text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    elif attack == 'noncanonical_key_order': text = '{"snapshot":' + compact(payload['snapshot']) + ',"codec":' + compact(payload['codec']) + '}'
    assert text != rf.serialize_rf1086_register_observation(original)
    with corrupt(reader, original, text=text) as db:
        with pytest.raises(psycopg.Error, match='rf1086_register_storage_invalid'): read(db, original)


@pytest.mark.parametrize('attack', ['confirmation', 'registration', 'share_class', 'capital_product', 'minimum_capital',
    'holders_total', 'holders_missing', 'holder_identity', 'holder_identity_changed', 'holder_removed', 'wrong_transition',
    'missing_document_role', 'document_company', 'document_hash', 'document_time', 'event_time', 'decimal_precision'])
def test_recomputed_fact_and_request_hashes_do_not_make_invalid_domain_evidence_valid(reader, attack):
    original = observed(reader); payload = encoded(original); snapshot, command = fields(payload)
    before, after = command['before']['fields'], command['after']['fields']; doc = command['documents'][0]['fields']
    if attack == 'confirmation': command['complete_register_confirmed'] = False
    elif attack == 'registration': command['registration_confirmed'] = False
    elif attack == 'share_class': command['single_share_class_confirmed'] = False
    elif attack == 'capital_product': after['share_capital']['decimal'] = '120001'
    elif attack == 'minimum_capital': before['share_capital']['decimal'] = '20000'; before['nominal_value']['decimal'] = '200'
    elif attack == 'holders_total': after['holdings'][0]['fields']['share_count'] = 199
    elif attack == 'holders_missing': after['holdings'] = []
    elif attack == 'holder_identity': after['holdings'][0]['fields']['identifier'] = 'not-an-identity'
    elif attack == 'holder_identity_changed': after['holdings'][0]['fields']['name'] = 'Changed name'
    elif attack == 'holder_removed': after['holdings'][0]['fields']['shareholder_id'] = 'unrelated-holder'
    elif attack == 'wrong_transition': command['event_kind'] = 'cash_nominal_increase'
    elif attack == 'missing_document_role': command['documents'].pop()
    elif attack == 'document_company': doc['company_id']['fields']['value'] = str(uuid4())
    elif attack == 'document_hash': doc['content_version_sha256'] = 'f' * 64
    elif attack == 'document_time': doc['created_at']['datetime'] = (original.confirmed_at + timedelta(seconds=1)).isoformat()
    elif attack == 'event_time': command['effective_at']['datetime'] = original.confirmed_at.replace(tzinfo=None, microsecond=0).replace(year=2027).isoformat()
    elif attack == 'decimal_precision': after['nominal_value']['decimal'] = '600.0000001'
    fact, request = forged_hashes(payload)
    with corrupt(reader, original, text=compact(payload), row_changes={'fact_sha256': fact, 'request_sha256': request}) as db:
        with pytest.raises(psycopg.Error, match='rf1086_register_storage_invalid'): read(db, original, sha=fact)


@pytest.mark.parametrize('related', ['independent', 'ancestor'])
def test_reader_validates_only_selected_current_row_not_unrelated_history(reader, related):
    other = observed(reader)
    if related == 'ancestor':
        with connection(reader) as db: selected = old_correction(db, reader, other)
    else: selected = observed(reader)
    payload = encoded(other); fields(payload)[1]['complete_register_confirmed'] = False
    with corrupt(reader, other, text=compact(payload)) as db:
        assert read(db, selected) == (rf.serialize_rf1086_register_observation(selected), selected.confirmed_at)


@pytest.mark.parametrize('winner', ['withdrawal', 'reader'])
def test_withdrawal_and_current_read_serialize_in_both_company_lock_orders(reader, winner):
    original = observed(reader); ready = Queue()
    def compete():
        with connection(reader) as db:
            ready.put(db.execute('select pg_backend_pid()').fetchone()[0])
            return read(db, original) if winner == 'withdrawal' else append(db, original)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with connection(reader) as db:
            if winner == 'withdrawal': append(db, original)
            else: assert read(db, original)[0] == rf.serialize_rf1086_register_observation(original)
            pending = pool.submit(compete); wait_for_lock(ready.get(timeout=5)); assert not pending.done()
        if winner == 'withdrawal':
            with pytest.raises(psycopg.Error, match='rf1086_register_predecessor_mismatch'): pending.result(timeout=10)
        else: assert pending.result(timeout=10)
    with connection(reader) as db:
        with pytest.raises(psycopg.Error, match='rf1086_register_predecessor_mismatch'): read(db, original)


def test_rolled_back_withdrawal_preserves_readable_original(reader):
    original = observed(reader); before = retained_rows(reader)
    with connection(reader) as db: append(db, original); db.rollback()
    with connection(reader) as db: assert read(db, original)[0] == rf.serialize_rf1086_register_observation(original)
    assert retained_rows(reader) == before


def test_owner_revocation_during_wait_is_rechecked(reader):
    original = observed(reader); ready = Queue()
    def compete():
        with connection(reader) as db:
            ready.put(db.execute('select pg_backend_pid()').fetchone()[0]); return read(db, original)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('select public.company_archive_lock_company_v1(%s)', (reader['seed']['company'],))
            pending = pool.submit(compete); pid = ready.get(timeout=5); wait_for_lock(pid)
            assert not db.execute("select exists(select 1 from pg_locks where pid=%s and locktype='advisory' and granted)", (pid,)).fetchone()[0]
            db.execute("update public.company_memberships set role='read_only' where company_id=%s", (reader['seed']['company'],))
        with pytest.raises(psycopg.Error, match='rf1086_forbidden'): pending.result(timeout=10)


def catalog(db):
    return dict(functions=db.execute("select oid,to_jsonb(p) from pg_proc p where pronamespace='shareholder_register_filing'::regnamespace order by oid").fetchall(),
        memberships=db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall(),
        tables=db.execute("select oid,relacl::text,relrowsecurity,relforcerowsecurity from pg_class where relnamespace='shareholder_register_filing'::regnamespace order by oid").fetchall(),
        schema=db.execute("select nspowner,nspacl::text from pg_namespace where nspname='shareholder_register_filing'").fetchall())


def test_closed_reader_helpers_and_reapplication_rollback_preserve_catalog_and_rows(reader):
    original = observed(reader); before_rows = retained_rows(reader)
    try:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute((ROOT / 'supabase/migrations' / MIGRATION).read_text())
            before = catalog(db)
            signatures = db.execute("select p.oid from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='shareholder_register_filing' and (p.proname like 'observation_evidence_%' or p.proname='read_current_register_observation_evidence_v1')").fetchall()
            assert len(signatures) >= 2
            roles = db.execute("select rolname from pg_roles where rolname in ('anon','authenticated','service_role') or rolname like '%executor' or rolname like '%store_owner' or rolname like '%bridge_owner'").fetchall()
            for (identity,) in signatures:
                assert not db.execute('select exists(select 1 from pg_proc p cross join lateral aclexplode(p.proacl) a where p.oid=%s and a.grantee=0)', (identity,)).fetchone()[0]
                for (role,) in roles:
                    if role != 'shareholder_register_filing_store_owner':
                        assert not db.execute("select has_function_privilege(%s,%s::oid,'EXECUTE')", (role, identity)).fetchone()[0], role
            assert not db.execute("select has_function_privilege(%s,%s,'EXECUTE')", (reader['role'], READER)).fetchone()[0]
            db.execute((ROOT / 'supabase/migrations' / MIGRATION).read_text())
            assert catalog(db) == before
            db.execute((ROOT / 'supabase/rollback' / MIGRATION).read_text())
            assert catalog(db) == before
            db.execute('set local role shareholder_register_filing_store_owner')
            db.execute(sql.SQL('grant execute on function ' + READER + ' to {}').format(sql.Identifier(reader['role'])))
    finally:
        # Even a failed closed-stage assertion must restore final owner grants.
        with psycopg.connect(DATABASE_URL) as restored:
            restored.execute((ROOT / 'supabase/migrations' / GOVERNANCE_SUCCESSOR).read_text())
            restored.execute((ROOT / 'supabase/migrations' / GOVERNANCE_APPLICATION).read_text())
            restored.execute((ROOT / 'supabase/migrations' / REPORTING_PROJECTION).read_text())
    assert retained_rows(reader) == before_rows
    with connection(reader) as db: assert read(db, original)[0] == rf.serialize_rf1086_register_observation(original)
    with connection(reader, role='shareholder_register_filing_executor') as db:
        with pytest.raises(psycopg.errors.InsufficientPrivilege): read(db, original)
