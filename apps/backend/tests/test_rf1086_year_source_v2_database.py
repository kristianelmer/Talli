"""Closed RF v2 SQL against real owner records; collection is not execution.

SQL authenticates the current Governance chain manifest and exact effective RF
evidence. It does not authenticate Python's reporting-year digest/business
selection or original byte availability. No production writer/HTTP is activated.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
import json
from queue import Queue
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, UserId, IdempotencyKey
from rf1086_year_source_v2_database_fixture import (
    admitted, amendment_fixture_authority, withdrawal_fixture_role, closed_source_role, source_login,
    original_fixture, amend, next_amendment, inputs, prepare, append_source, store, rows,
    connection, withdrawal, register_capture, append_amendment, DATABASE_URL, ROOT,
    inactive_inputs, pending_governance_event, mint_proof, APPEND, LOCK, GOV_READER, TABLE, HEADS,
    PRODUCER, RECEIVER, INVALIDATOR, PROOFS,
)
from test_governance_register_evidence_amendment_database import wait_for_company_lock
from test_governance_reporting_register_evidence_database import adapter as reporting_projection
from test_rf1086_year_source_v2 import projection
from test_rf1086_year_source_storage_v2 import records
from test_rf1086_year_source_database import session as rf_session
from test_rf1086_year_source import basis as pure_basis


pytestmark = pytest.mark.authority_database
GUARD = 'shareholder_register_filing.assert_source_register_observations_active_internal_v1'
VALIDATE = 'shareholder_register_filing.assert_year_source_v2_internal_v1'
INVALID = 'rf1086_source_storage_invalid'
STALE = 'rf1086_source_register_observation_stale'
CHANGED = 'rf1086_source_governance_evidence_changed'
MIGRATION = '20261010013307_rf1086_closed_year_source_v2.sql'
PRODUCER_MIGRATION = '20261010015851_governance_rf_year_source_proof.sql'


@pytest.fixture
def original(admitted, closed_source_role, withdrawal_fixture_role):
    item = original_fixture(admitted, closed_source_role, withdrawal_fixture_role)
    return item | {'source_inputs': inputs(item)}


def locked(db, item):
    db.execute('select ' + LOCK.split('(')[0] + '(%s,%s)', (item['seed']['company'], 2026))


def assert_current(item, source):
    with connection(item['seed'], item['source_role']) as db:
        mint_proof(db, source)
        db.execute('set local role shareholder_register_filing_store_owner')
        locked(db, item)
        db.execute('select ' + GUARD + '(%s,%s,%s::uuid,%s)',
            (source.company_id.value, source.income_year.value, source.source_id.value, source.source_sha256))


def with_projection(item, value):
    command, context = item['source_inputs']
    return item | {'source_inputs': (command, replace(context, governance_projection=value))}


def raw_json(value):
    # Preserve the exact emitter layout so a field attack cannot pass merely
    # because whitespace or key order is rejected before its intended check.
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


@pytest.mark.parametrize('kind,phase', [('loss_covering_reduction', 'first_recognized_after_registration'),
    ('loss_covering_reduction', 'registered'), ('cash_issue', 'registered')])
@pytest.mark.parametrize('amendments', [0, 1, 2])
def test_real_originals_and_zero_one_two_chains_store_exact_canonical_v2(admitted, closed_source_role, withdrawal_fixture_role, kind, phase, amendments):
    item = original_fixture(admitted, closed_source_role, withdrawal_fixture_role, kind=kind, phase=phase)
    for _ in range(amendments): item = amend(item)
    item['source_inputs'] = inputs(item)
    source = store(item)
    saved = rows(item)
    assert len(saved) == 1
    assert saved[0][1] == 1 and str(saved[0][2]) == str(item['seed']['owner'])
    assert saved[0][4] == rf.rf1086_year_source_digest(source.command)
    assert saved[0][5] == source.source_sha256
    assert saved[0][6] == rf.serialize_rf1086_year_source_v2(source)
    assert rf.parse_rf1086_year_source_v2(saved[0][6]) == source
    assert source.governance_projection.chains[0].amendment_count == amendments
    assert source.governance_receipts[0].register_observation == item['replacement']
    assert_current(item, source)


def test_rpc_duplicate_key_conflicts_while_existing_historical_v1_lookup_still_recovers(original):
    command, context = original['source_inputs']
    old_context = rf.Rf1086VerifiedYearSourceContext(context.actor_id, True, context.company_id,
        context.income_year, context.company, context.company_identity_sha256, context.documents,
        tuple(row.original for row in context.governance_receipts), True,
        context.governance_projection.original_enumeration_sha256)
    key = str(uuid4())
    with connection(original['seed'], 'shareholder_register_filing_executor') as db:
        at = db.execute('select clock_timestamp()').fetchone()[0]
        first = rf.prepare_rf1086_year_source(command, context=old_context,
            source_id=rf.Rf1086YearSourceId(str(uuid4())), confirmed_at=at)
        append_source(db, first, version=1, key=key)
    second = store(original, previous=first)
    assert second.version == 2
    client = rf_session(original['seed'], DATABASE_URL)
    recovered = asyncio.run(client.read_year_source_capture_receipt(command, idempotency_key=IdempotencyKey(key)))
    assert rf.serialize_rf1086_year_source(recovered) == rf.serialize_rf1086_year_source(first)
    # This RPC is not the adapter's historical lookup: a valid new predecessor
    # with an already used actor/year/key cannot append a second receipt.
    with connection(original['seed'], original['source_role']) as db:
        third = prepare(db, original, previous=second)
        with pytest.raises(psycopg.Error, match='rf1086_source_idempotency_conflict'):
            append_source(db, third, key=key)
    assert len(rows(original)) == 2


def test_explicit_v2_correction_advances_head_and_preserves_original_text(original):
    first = store(original)
    before = rows(original)[0][6]
    second = store(original, previous=first)
    assert second.version == 2 and second.confirmed_at > first.confirmed_at
    assert rows(original)[0][6] == before
    assert second.command.supersedes_source_sha256 == first.source_sha256
    with connection(original['seed'], 'shareholder_register_filing_store_owner') as db:
        result = db.execute('select source_id,version,source_sha256 from ' + HEADS
            + ' where company_id=%s and income_year=2026', (original['seed']['company'],)).fetchone()
    assert (str(result[0]), result[1], result[2]) == (second.source_id.value, 2, second.source_sha256)


def test_actual_empty_governance_projection_is_explicit_evidence_not_missing_context(admitted, closed_source_role):
    item = {'seed': admitted, 'source_role': closed_source_role, 'source_inputs': inactive_inputs(admitted)}
    source = store(item)
    assert source.governance_projection.chain_count == 0
    assert source.governance_projection.chains == source.governance_receipts == ()
    assert_current(item, source)


def test_new_current_owner_can_correct_original_actor_source_with_actor_scoped_same_key(original):
    key = str(uuid4())
    first = store(original, key=key)
    with psycopg.connect(DATABASE_URL) as db:
        # Privileged membership fixture, not a new source/evidence writer.
        db.execute('insert into public.company_memberships(company_id,user_id,role,accepted_at) values(%s,%s,\'owner\',clock_timestamp())',
            (original['seed']['company'], original['seed']['outsider']))
        db.execute("update public.company_memberships set role='read_only' where company_id=%s and user_id=%s",
            (original['seed']['company'], original['seed']['owner']))
    actor = ActorId(ActorKind.USER, UserId(str(original['seed']['outsider'])))
    command, context = original['source_inputs']
    item = original | {'seed': original['seed'] | {'owner': original['seed']['outsider']},
        'source_inputs': (replace(command, actor_id=actor), replace(context, actor_id=actor))}
    second = store(item, previous=first, key=key)
    assert second.confirmed_by == actor and second.version == 2
    assert second.governance_receipts == first.governance_receipts
    assert [(str(row[2]), row[3]) for row in rows(item)] == [
        (str(original['seed']['owner']), key), (str(original['seed']['outsider']), key)]


@pytest.mark.parametrize('kind', [ActorKind.SYSTEM, ActorKind.SUPPORT_OPERATOR])
def test_recomputed_source_hash_cannot_relabel_verified_human_actor_kind(original, kind):
    command, _ = original['source_inputs']
    actor = replace(command.actor_id, kind=kind)
    # Privileged construction of an internally hash-consistent payload; the
    # legacy embedded observation remains byte-for-byte unchanged.
    with connection(original['seed'], original['source_role']) as db:
        source = prepare(db, original)
        command = replace(source.command, actor_id=actor)
        digest = rf.rf1086_year_source_digest(dict(schema='rf1086-year-source-v2',
            source_id=source.source_id, version=source.version, command=command,
            confirmed_at=source.confirmed_at, governance_receipts=source.governance_receipts,
            governance_projection=source.governance_projection,
            company_identity_sha256=source.freshness.company_identity_sha256))
        forged = replace(source, command=command, confirmed_by=actor, source_sha256=digest,
            freshness=replace(source.freshness, source_sha256=digest))
        # Serialize the tagged payload without asking the pure validator to
        # admit the forged actor; SQL must independently reject direct callers.
        raw = json.loads(rf.serialize_rf1086_year_source_v2(source))
        raw['snapshot']['fields']['command']['fields']['actor_id']['fields']['kind']['value'] = kind.value
        raw['snapshot']['fields']['confirmed_by']['fields']['kind']['value'] = kind.value
        raw['snapshot']['fields']['source_sha256'] = digest
        raw['snapshot']['fields']['freshness']['fields']['source_sha256'] = digest
        with pytest.raises(psycopg.Error, match=INVALID):
            append_source(db, forged, text=raw_json(raw))
    assert rows(original) == []


@pytest.mark.parametrize('case', ['v2_body_to_old_rpc', 'v1_after_v2_head'])
def test_old_executable_rpc_never_admits_v2_or_downgrades_current_v2(original, case):
    first = store(original) if case == 'v1_after_v2_head' else None
    with connection(original['seed'], 'shareholder_register_filing_executor') as db:
        if case == 'v2_body_to_old_rpc':
            source = prepare(db, original)
            with pytest.raises(psycopg.Error, match=INVALID):
                append_source(db, source, version=1, text=rf.serialize_rf1086_year_source_v2(source))
        else:
            command, context = original['source_inputs']
            # Construct an ordinary v1-format correction with the exact stored
            # v2 predecessor identity. No invented predecessor row is stored.
            old_context = rf.Rf1086VerifiedYearSourceContext(context.actor_id, True, context.company_id,
                context.income_year, context.company, context.company_identity_sha256, context.documents,
                tuple(row.original for row in context.governance_receipts), True,
                context.governance_projection.original_enumeration_sha256)
            at = db.execute('select clock_timestamp()').fetchone()[0]
            root = rf.prepare_rf1086_year_source(command, context=old_context,
                source_id=rf.Rf1086YearSourceId(str(uuid4())), confirmed_at=at)
            command = replace(command, supersedes_source_id=first.source_id,
                supersedes_source_sha256=first.source_sha256, correction_reason='Attempted v1 downgrade')
            digest = rf.rf1086_year_source_digest(dict(schema='rf1086-year-source-v1', source_id=root.source_id,
                version=2, command=command, confirmed_at=at, governance_receipts=root.governance_receipts,
                company_identity_sha256=root.freshness.company_identity_sha256,
                governance_enumeration_sha256=root.freshness.governance_enumeration_sha256))
            crafted = replace(root, version=2, command=command, source_sha256=digest,
                freshness=replace(root.freshness, source_sha256=digest))
            rf.assert_rf1086_year_source_integrity(crafted)
            with pytest.raises(psycopg.Error, match='rf1086_source_codec_downgrade'):
                append_source(db, crafted, version=1)
    assert len(rows(original)) == (1 if first else 0)


@pytest.mark.parametrize('record,field,value', [
    ('Rf1086YearSourceSnapshotV2', 'version', True),
    ('Rf1086YearSourceSnapshotV2', 'version', 1.0),
    ('IncomeYear', 'value', '2026'),
    ('Rf1086YearGovernanceProjectionV2', 'chain_count', 0),
    ('Rf1086YearGovernanceChainV2', 'amendment_count', True),
    ('Rf1086YearGovernanceChainV2', 'head', {}),
    ('Rf1086YearGovernanceChainV2', 'original_anchor_sha256', 'A' * 64),
    ('Rf1086YearRegisterFactV2', 'version', 1.0),
    ('Rf1086YearRegisterFactV2', 'fact_sha256', 'f' * 63),
    ('RecordRf1086YearSource', 'identities_reviewed', 'true'),
    ('RecordRf1086YearSource', 'documents', []),
    ('Rf1086YearGovernanceReceipt', 'active', False),
])
def test_direct_sql_rejects_malformed_nested_codec_before_any_source_write(original, record, field, value):
    with connection(original['seed'], original['source_role']) as db:
        source = prepare(db, original)
        raw = json.loads(rf.serialize_rf1086_year_source_v2(source))
        next(records(raw, record))[field] = value
        with pytest.raises(psycopg.Error, match=INVALID):
            append_source(db, source, text=raw_json(raw))
    assert rows(original) == []


@pytest.mark.parametrize('attack', ['duplicate_top', 'duplicate_nested', 'unknown_top', 'unknown_record',
    'missing_snapshot', 'scientific_year', 'float_version', 'source_hash', 'case_hash', 'request_hash'])
def test_raw_shape_and_hash_attacks_cannot_hide_behind_jsonb_normalization(original, attack):
    with connection(original['seed'], original['source_role']) as db:
        source = prepare(db, original)
        text = rf.serialize_rf1086_year_source_v2(source)
        changes = None
        if attack == 'duplicate_top': text = text.replace('"codec":', '"codec":"rf1086-year-source-v2","codec":', 1)
        elif attack == 'duplicate_nested': text = text.replace('"amendment_count":', '"amendment_count":0,"amendment_count":', 1)
        elif attack == 'scientific_year': text = text.replace('"value":2026', '"value":2.026e3', 1)
        elif attack == 'float_version': text = text.replace('"version":1', '"version":1.0', 1)
        elif attack == 'request_hash': changes = {'request_sha': 'f' * 64}
        else:
            raw = json.loads(text)
            if attack == 'unknown_top': raw['verified'] = True
            elif attack == 'unknown_record': raw['snapshot']['record'] = 'Rf1086YearSourceSnapshot'
            elif attack == 'missing_snapshot': del raw['snapshot']
            elif attack == 'source_hash': raw['snapshot']['fields']['source_sha256'] = 'f' * 64
            elif attack == 'case_hash': raw['snapshot']['fields']['case_sha256'] = 'f' * 64
            text = raw_json(raw)
        with pytest.raises(psycopg.Error, match=INVALID):
            append_source(db, source, text=text, changes=changes)
    assert rows(original) == []


@pytest.mark.parametrize('field', ['identifier', 'company', 'year', 'version', 'source_sha', 'confirmed_at'])
def test_outer_row_claims_are_bound_to_canonical_payload(original, field):
    with connection(original['seed'], original['source_role']) as db:
        source = prepare(db, original)
        changed = {'identifier': str(uuid4()), 'company': str(uuid4()), 'year': 2025,
            'version': 2, 'source_sha': 'f' * 64, 'confirmed_at': source.confirmed_at - timedelta(days=1)}[field]
        with pytest.raises(psycopg.Error, match='rf1086_'):
            append_source(db, source, changes={field: changed})
    assert rows(original) == []


@pytest.mark.parametrize('attack', ['chain_label', 'anchor', 'withdrawal', 'head', 'omitted_chain'])
def test_recomputed_local_hashes_cannot_forge_authoritative_complete_governance_chain(original, attack):
    item = amend(original)
    item['source_inputs'] = inputs(item)
    command, context = item['source_inputs']
    chain = context.governance_projection.chains[0]
    if attack == 'chain_label': chain = replace(chain, enumeration_sha256='f' * 64)
    elif attack == 'anchor': chain = replace(chain, original_anchor_sha256='f' * 64)
    elif attack == 'withdrawal': chain = replace(chain, amendments=(replace(chain.amendments[0], withdrawal_sha256='f' * 64),))
    elif attack == 'head':
        head = replace(chain.head, amendment_sha256='f' * 64)
        chain = replace(chain, head=head, amendments=(replace(chain.amendments[0], head=head),))
    if attack == 'omitted_chain':
        # A reference-free caller cannot turn a real complete owner projection
        # into known-empty evidence merely by removing both local collections.
        base, _ = pure_basis()
        command = replace(command, case=replace(base.case, company=command.case.company),
            paid_in=base.paid_in, event_evidence=(), no_activity_confirmed=True)
        context = replace(context, governance_receipts=())
        chain_values = ()
    else: chain_values = (chain,)
    supplied = projection(chain_values, company_id=command.company_id, income_year=command.income_year,
        original_sha=context.governance_projection.original_enumeration_sha256)
    item = item | {'source_inputs': (command, replace(context, governance_projection=supplied))}
    with connection(item['seed'], item['source_role']) as db:
        source = prepare(db, item)
        rf.assert_rf1086_year_source_integrity_v2(source)
        with pytest.raises(psycopg.Error, match=CHANGED): append_source(db, source)
    assert rows(item) == []


def test_sql_lineage_proof_does_not_claim_authentication_of_python_old_year_digest(original):
    command, context = original['source_inputs']
    supplied = projection(context.governance_projection.chains, company_id=command.company_id,
        income_year=command.income_year, original_sha='f' * 64)
    source = store(with_projection(original, supplied))
    assert source.governance_projection.original_enumeration_sha256 == 'f' * 64
    assert source.governance_projection.chain_enumeration_sha256 == context.governance_projection.chain_enumeration_sha256
    assert len(rows(original)) == 1


@pytest.mark.parametrize('state', ['withdrawn', 'superseded'])
def test_real_effective_observation_changes_block_closed_append_and_stored_admission(original, state):
    source = store(original)
    if state == 'withdrawn': withdrawal(original['seed'], original['withdrawal_role'], original['replacement'])
    else: register_capture(original['seed'], documents=original['replacement_docs'], predecessor=original['replacement'])
    with connection(original['seed'], original['source_role']) as db:
        successor = prepare(db, original, previous=source)
        with pytest.raises(psycopg.Error, match=STALE): append_source(db, successor)
    with pytest.raises(psycopg.Error, match=STALE): assert_current(original, source)
    assert rows(original)[0][6] == rf.serialize_rf1086_year_source_v2(source)


@pytest.mark.parametrize('isolation', ['repeatable read', 'serializable'])
def test_closed_v2_append_rejects_stale_transaction_isolation(original, isolation):
    with connection(original['seed'], original['source_role'], isolation=isolation) as db:
        source = prepare(db, original)
        with pytest.raises(psycopg.Error, match='read_committed|guards_required|guard_required'):
            append_source(db, source)
    assert rows(original) == []


@pytest.mark.parametrize('identity', ['outsider', 'unverified', 'forged_subject', 'revoked'])
def test_current_owner_and_verified_actor_are_not_replaced_by_copied_context(original, identity):
    if identity == 'revoked':
        with psycopg.connect(DATABASE_URL) as db:
            db.execute("update public.company_memberships set role='read_only' where company_id=%s and user_id=%s",
                (original['seed']['company'], original['seed']['owner']))
    with connection(original['seed'], original['source_role'], actor=original['seed']['outsider'] if identity == 'outsider' else None) as db:
        source = prepare(db, original)
        if identity == 'unverified': db.execute("select set_config('talli.verified_actor_id','',true)")
        elif identity == 'forged_subject': db.execute("select set_config('talli.verified_actor_id',%s,true)", (str(original['seed']['outsider']),))
        with pytest.raises(psycopg.Error, match='rf1086_|corporate_governance_'):
            append_source(db, source)
    assert rows(original) == []


def test_competing_corrected_sources_cannot_fork_same_head(original):
    first = store(original)
    def attempt(_):
        try: return store(original, previous=first)
        except psycopg.Error as error:
            assert 'rf1086_source_predecessor_mismatch' in str(error)
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sum(result is not None for result in results) == 1
    assert [row[1] for row in rows(original)] == [1, 2]


@pytest.mark.parametrize('winner', ['source', 'withdrawal'])
def test_both_company_lock_orders_linearize_source_append_and_withdrawal(original, winner):
    started = Queue()
    def competing():
        role = original['source_role'] if winner == 'withdrawal' else original['withdrawal_role']
        with connection(original['seed'], role) as db:
            started.put(db.execute('select pg_backend_pid()').fetchone()[0])
            if winner == 'source': return withdrawal(original['seed'], role, original['replacement'], db=db)
            source = prepare(db, original)
            try: append_source(db, source)
            except psycopg.Error as error:
                assert STALE in str(error)
                return None
            raise AssertionError('Withdrawal-first source must be rejected')
    with ThreadPoolExecutor(max_workers=1) as pool:
        with connection(original['seed'], original['source_role'] if winner == 'source' else original['withdrawal_role']) as db:
            if winner == 'source':
                source = prepare(db, original)
                append_source(db, source)
            else:
                withdrawal(original['seed'], original['withdrawal_role'], original['replacement'], db=db)
            future = pool.submit(competing)
            wait_for_company_lock(started.get(timeout=3))
        future.result(timeout=8)
    assert len(rows(original)) == (1 if winner == 'source' else 0)


def test_live_revocation_committed_during_lock_wait_beats_stale_role_map(original):
    started = Queue()
    def attempt():
        with connection(original['seed'], original['source_role']) as db:
            source = prepare(db, original)
            started.put(db.execute('select pg_backend_pid()').fetchone()[0])
            try: append_source(db, source)
            except psycopg.Error as error:
                assert 'rf1086_' in str(error)
                return
            raise AssertionError('Revoked owner must not append')
    with ThreadPoolExecutor(max_workers=1) as pool:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('select public.company_archive_lock_company_v1(%s)', (original['seed']['company'],))
            future = pool.submit(attempt)
            wait_for_company_lock(started.get(timeout=3))
            db.execute("update public.company_memberships set role='read_only' where company_id=%s and user_id=%s",
                (original['seed']['company'], original['seed']['owner']))
        future.result(timeout=8)
    assert rows(original) == []


def test_late_insert_failure_rolls_back_source_and_head_atomically(original):
    trigger = 'fixture_reject_v2_' + uuid4().hex
    with connection(original['seed'], 'shareholder_register_filing_store_owner') as db:
        # Existing owner immutable trigger raises for every invocation. Reusing
        # it needs no borrowed schema CREATE, and WHEN isolates our company.
        db.execute(sql.SQL('create trigger {} after insert on ' + TABLE
            + ' for each row when(new.company_id={}) execute function shareholder_register_filing.protect_year_source_v1()').format(
                sql.Identifier(trigger), sql.Literal(original['seed']['company'])))
    try:
        with pytest.raises(psycopg.Error, match='rf1086_source_immutable'): store(original)
        assert rows(original) == []
        with connection(original['seed'], 'shareholder_register_filing_store_owner') as db:
            assert db.execute('select count(*) from ' + HEADS + ' where company_id=%s', (original['seed']['company'],)).fetchone()[0] == 0
    finally:
        with connection(original['seed'], 'shareholder_register_filing_store_owner') as db:
            db.execute(sql.SQL('drop trigger {} on ' + TABLE).format(sql.Identifier(trigger)))


def test_closed_append_and_private_validator_do_not_expand_runtime_or_table_authority(original):
    denied = ('anon', 'authenticated', 'service_role', 'shareholder_register_filing_executor',
        'corporate_governance_workflow_executor', 'corporate_governance_store_owner')
    with psycopg.connect(DATABASE_URL) as db:
        functions = db.execute("select p.oid,n.nspname,p.proname,pg_catalog.oidvectortypes(p.proargtypes),p.proowner::regrole::text,p.prosecdef,p.proconfig from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='shareholder_register_filing' and (p.proname in ('append_year_source_v2','assert_year_source_v2_internal_v1') or p.proname like 'year_source_v2_%')").fetchall()
        assert {'append_year_source_v2', 'assert_year_source_v2_internal_v1',
            'year_source_v2_validate_internal_v1'} <= {row[2] for row in functions}
        for oid, _, name, _, owner, _, config in functions:
            assert owner == 'shareholder_register_filing_store_owner' and config == ['search_path=""']
            for role in denied: assert not db.execute("select has_function_privilege(%s,%s::oid,'EXECUTE')", (role, oid)).fetchone()[0]
        gov_oid = db.execute("select p.oid from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='corporate_governance' and p.proname='read_guarded_reporting_register_evidence_v1' and pg_catalog.oidvectortypes(p.proargtypes)='uuid, integer, text'").fetchone()[0]
        assert not db.execute("select has_function_privilege('shareholder_register_filing_store_owner',%s::oid,'EXECUTE')", (gov_oid,)).fetchone()[0]
        for role in ('shareholder_register_filing_executor','anon','authenticated','service_role'):
            assert not db.execute("select has_function_privilege(%s,%s::oid,'EXECUTE')", (role, gov_oid)).fetchone()[0]
        assert not db.execute("select has_table_privilege(%s,%s,'INSERT')", (original['source_role'], TABLE)).fetchone()[0]
    with connection(original['seed'], 'shareholder_register_filing_executor') as db:
        source = prepare(db, original)
        with pytest.raises(psycopg.errors.InsufficientPrivilege): append_source(db, source, proof=False)


def preview(source):
    """Direct SQL fixture, not an activated v2 application preview producer."""
    rendered = rf.generate_rf1086_documents(source.command.case)
    return rf.Rf1086SourcePreview(rf.PreviewId(str(uuid4())), source.company_id, source.income_year,
        source.source_id, source.source_sha256, source.case_sha256, 'ready', (),
        'Owned direct SQL preview fixture', rendered.hovedskjema_xml, rendered.underskjema_xml)


def append_preview(db, value):
    text = rf.serialize_rf1086_source_preview(value)
    return db.execute('select shareholder_register_filing.append_source_preview_v1(%s,%s,%s,%s,%s,%s,%s,%s)',
        (value.preview_id.value, value.company_id.value, value.income_year.value, value.source_id.value,
         value.source_sha256, value.case_sha256, sha256(text.encode()).hexdigest(), text)).fetchone()[0]


def test_existing_preview_hook_dispatches_v2_and_preserves_exact_historical_replay(original):
    source = store(original)
    captured = preview(source)
    with connection(original['seed'], original['source_role']) as db:
        mint_proof(db, source)
        db.execute('set local role shareholder_register_filing_executor')
        assert str(append_preview(db, captured)) == captured.preview_id.value
    withdrawal(original['seed'], original['withdrawal_role'], original['replacement'])
    with connection(original['seed'], 'shareholder_register_filing_executor') as db:
        assert str(append_preview(db, captured)) == captured.preview_id.value
    new_preview = replace(captured, preview_id=rf.PreviewId(str(uuid4())), preview_text='New attempted preview')
    with connection(original['seed'], original['source_role']) as db:
        mint_proof(db, source)
        db.execute('set local role shareholder_register_filing_executor')
        with pytest.raises(psycopg.Error, match=STALE): append_preview(db, new_preview)
    assert rows(original)[0][6] == rf.serialize_rf1086_year_source_v2(source)


@pytest.mark.parametrize('held', ['none', 'company_only'])
def test_private_dispatcher_requires_actual_company_and_year_transaction_guards(original, held):
    with connection(original['seed'], 'shareholder_register_filing_store_owner') as db:
        source = prepare(db, original)
        if held == 'company_only':
            db.execute('select public.company_archive_lock_company_v1(%s)', (original['seed']['company'],))
        with pytest.raises(psycopg.Error, match='rf1086_source_approval_guard_required'):
            db.execute('select ' + GUARD + '(%s,%s,%s::text)',
                (source.company_id.value, source.income_year.value, rf.serialize_rf1086_year_source_v2(source)))


def test_committed_source_history_is_immutable_and_runtime_has_no_direct_head_write(original):
    source = store(original)
    with connection(original['seed'], 'shareholder_register_filing_store_owner') as db:
        # FORCE RLS has no UPDATE policy, so ordinary owner UPDATE affects zero
        # rows. Isolate the immutable-trigger backstop in a rollback-only scope;
        # even a missing trigger/failed expectation cannot commit the mutation.
        with db.transaction(force_rollback=True):
            db.execute('alter table ' + TABLE + ' no force row level security')
            with pytest.raises(psycopg.Error, match='rf1086_source_immutable'):
                with db.transaction():
                    db.execute('update ' + TABLE + ' set request_sha256=%s where id=%s', ('f' * 64, source.source_id.value))
        assert db.execute('select relforcerowsecurity from pg_class where oid=%s::regclass', (TABLE,)).fetchone()[0] is True
    with connection(original['seed'], 'shareholder_register_filing_executor') as db:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute('delete from ' + HEADS + ' where company_id=%s', (original['seed']['company'],))
    assert rows(original)[0][6] == rf.serialize_rf1086_year_source_v2(source)


HOOKS = (
    ('append_year_source_v1', 'uuid, uuid, integer, integer, text, text, text, uuid, text, text, text, timestamp with time zone'),
    ('append_source_preview_v1', 'uuid, uuid, integer, uuid, text, text, text, text'),
    ('bridge_source_preview_v1', 'uuid, text, text'),
    ('append_source_approval_v1', 'uuid, uuid, text, text, text, text'),
    ('append_source_approval_v2', 'uuid, uuid, text, text, text, text'),
    ('claim_source_submission_v1', 'uuid, text, uuid, text'),
    ('claim_source_submission_v2', 'uuid, text, uuid, text, text'),
    ('prepare_source_operation_v1', 'uuid, text, text, text, uuid, uuid, text, text'),
)


def catalog(db):
    return {
        'functions': db.execute("select to_jsonb(p) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname in ('shareholder_register_filing','corporate_governance') order by p.oid").fetchall(),
        'memberships': db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall(),
        'schemas': db.execute("select oid,nspowner,nspacl from pg_namespace where nspname in ('shareholder_register_filing','corporate_governance') order by oid").fetchall(),
        'tables': db.execute("select c.oid,c.relowner,c.relacl,c.relrowsecurity,c.relforcerowsecurity from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='shareholder_register_filing' and c.relname in ('year_source_versions','year_source_heads') order by c.oid").fetchall(),
        'triggers': db.execute("select to_jsonb(t) from pg_trigger t join pg_class c on c.oid=t.tgrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='corporate_governance' and c.relname in ('supported_events','register_evidence_amendments') order by t.oid").fetchall(),
    }


def restore_fixture_grants(db, role):
    db.execute('set local role shareholder_register_filing_store_owner')
    db.execute(sql.SQL('grant execute on function ' + APPEND + ',' + LOCK + ' to {}').format(sql.Identifier(role)))
    db.execute('set local role corporate_governance_store_owner')
    db.execute(sql.SQL('grant execute on function ' + PRODUCER + ' to {}').format(sql.Identifier(role)))
    db.execute('reset role')


def test_all_eight_old_admission_hooks_still_reach_single_closed_codec_dispatcher(original):
    # Catalog evidence of routing only. The direct preview test exercises one
    # real downstream path; this is not a claim of activated v2 filing flows.
    with psycopg.connect(DATABASE_URL) as db:
        for name, arguments in HOOKS:
            row = db.execute("select p.prosrc from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='shareholder_register_filing' and p.proname=%s and pg_catalog.oidvectortypes(p.proargtypes)=%s", (name, arguments)).fetchone()
            assert row is not None and row[0].count(GUARD + '(') == 1
        text = db.execute("select p.prosrc from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='shareholder_register_filing' and p.proname='assert_source_register_observations_active_internal_v1' and pg_catalog.oidvectortypes(p.proargtypes)='uuid, integer, text'").fetchone()[0]
        assert 'rf1086-year-source-v2' in text and VALIDATE + '(' in text
        assert 'rf1086-year-source-v1' in text


def test_reapply_and_retentive_rollback_preserve_history_guards_roles_and_catalog(original):
    source = store(original)
    history = rows(original)
    with psycopg.connect(DATABASE_URL) as db:
        before = catalog(db)
    try:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute((ROOT / 'supabase/migrations' / MIGRATION).read_text())
            db.execute((ROOT / 'supabase/migrations' / PRODUCER_MIGRATION).read_text())
            restore_fixture_grants(db, original['source_role'])
            assert catalog(db) == before
        with psycopg.connect(DATABASE_URL) as db:
            db.execute((ROOT / 'supabase/rollback' / PRODUCER_MIGRATION).read_text())
            db.execute((ROOT / 'supabase/rollback' / MIGRATION).read_text())
            restore_fixture_grants(db, original['source_role'])
            assert catalog(db) == before
        assert rows(original) == history
        assert_current(original, source)
    finally:
        # Ensure failed assertions cannot leave the rest of the owned suite at
        # a deliberate prefix or remove its unique fixture-only capability.
        with psycopg.connect(DATABASE_URL) as db:
            db.execute((ROOT / 'supabase/migrations' / MIGRATION).read_text())
            db.execute((ROOT / 'supabase/migrations' / PRODUCER_MIGRATION).read_text())
            restore_fixture_grants(db, original['source_role'])


def proof_count(db, return_role):
    """Privileged inspection only; the fixture caller has no temp-table read."""
    db.execute('set local role shareholder_register_filing_store_owner')
    result = db.execute('select count(*) from ' + PROOFS).fetchone()[0]
    db.execute(sql.SQL('set local role {}').format(sql.Identifier(return_role)))
    return result


def guarded_raw(db, source):
    db.execute('select ' + GUARD + '(%s,%s,%s::text)',
        (source.company_id.value, source.income_year.value, rf.serialize_rf1086_year_source_v2(source)))


def corrupt_owned_proof_year(db, item, source):
    """Negative temp-slot fixture; shipped Company Access admits only 2026.

    A real owner producer mints the supported-year proof first. Only the RF
    owner can alter its private temporary slot; no unsupported admission rows,
    durable records, permissions or production constraints are changed.
    """
    assert source.income_year.value == 2026
    db.execute('set local role shareholder_register_filing_store_owner')
    changed = db.execute('update ' + PROOFS + ' set income_year=2025 '
        'where transaction_id=pg_current_xact_id() and actor_id=%s and company_id=%s '
        'and income_year=2026 and source_sha256=%s',
        (str(source.command.actor_id.subject), source.company_id.value, source.source_sha256))
    assert changed.rowcount == 1
    db.execute(sql.SQL('set local role {}').format(sql.Identifier(item['source_role'])))


@pytest.mark.parametrize('mismatch', ['absent', 'source', 'year', 'transaction'])
def test_owner_proof_is_required_for_exact_source_scope_and_transaction(original, mismatch):
    if mismatch == 'transaction':
        with connection(original['seed'], original['source_role']) as db:
            source = prepare(db, original)
            mint_proof(db, source)
            assert proof_count(db, original['source_role']) == 1
            db.commit()
            assert db.execute("select to_regclass('pg_temp.rf1086_year_source_governance_proofs')").fetchone()[0] is None
    with connection(original['seed'], original['source_role']) as db:
        if mismatch != 'transaction': source = prepare(db, original)
        if mismatch == 'source':
            mint_proof(db, source)
            source = prepare(db, original)
        elif mismatch == 'year':
            mint_proof(db, source)
            corrupt_owned_proof_year(db, original, source)
        if mismatch == 'transaction':
            # Appending a prior-transaction source correctly fails its timestamp
            # fence before proof admission. Use the actual guarded source check
            # to test this exact source/SHA after its proof transaction ended.
            locked(db, original)
            db.execute('set local role shareholder_register_filing_store_owner')
            with pytest.raises(psycopg.Error, match=CHANGED): guarded_raw(db, source)
        else:
            with pytest.raises(psycopg.Error, match=CHANGED): append_source(db, source, proof=False)
    assert rows(original) == []


def test_owner_proof_survives_nested_guards_but_is_not_caller_readable_or_writable(original):
    with connection(original['seed'], original['source_role']) as db:
        source = prepare(db, original)
        mint_proof(db, source)
        assert proof_count(db, original['source_role']) == 1
        for statement in ('select * from ', 'delete from '):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with db.transaction(): db.execute(statement + PROOFS)
        db.execute('set local role shareholder_register_filing_store_owner')
        guarded_raw(db, source)
        with db.transaction(): guarded_raw(db, source)
        db.execute(sql.SQL('set local role {}').format(sql.Identifier(original['source_role'])))
        append_source(db, source, proof=False)
        db.execute('set local role shareholder_register_filing_executor')
        value = preview(source)
        assert str(append_preview(db, value)) == value.preview_id.value
        assert str(append_preview(db, value)) == value.preview_id.value
        assert proof_count(db, original['source_role']) == 1
    assert len(rows(original)) == 1


@pytest.mark.parametrize('mutation', ['original', 'amendment'])
@pytest.mark.parametrize('rollback', [False, True])
def test_actual_governance_write_invalidates_proof_and_savepoint_rollback_restores_it(original, mutation, rollback):
    if mutation == 'original':
        pending = pending_governance_event(original)
        item = original
    else:
        # The selected original RF is already withdrawn before preparation.
        # Inspect proof rows directly: this isolates invalidation from RF
        # currentness, which would independently reject the old source.
        pending = next_amendment(original)
        item = original
    with connection(item['seed'], item['source_role']) as db:
        source = prepare(db, item)
        mint_proof(db, source)
        mint_proof(db, prepare(db, item))
        assert proof_count(db, item['source_role']) == 2
        try:
            with db.transaction():
                db.execute('set local role corporate_governance_workflow_executor')
                if mutation == 'original':
                    db.execute('select corporate_governance.complete_supported_event_v1(%s,%s)',
                        (Jsonb(pending), str(item['seed']['owner'])))
                else: append_amendment(db, pending)
                assert proof_count(db, item['source_role']) == 0
                if rollback: raise RuntimeError('owned savepoint rollback')
        except RuntimeError as error:
            assert str(error) == 'owned savepoint rollback'
        db.execute(sql.SQL('set local role {}').format(sql.Identifier(item['source_role'])))
        assert proof_count(db, item['source_role']) == 2 * int(rollback)
        if mutation == 'original' and rollback:
            append_source(db, source, proof=False)
        elif not rollback:
            with pytest.raises(psycopg.Error, match=CHANGED):
                with db.transaction(): append_source(db, source, proof=False)


def test_original_replay_does_not_invalidate_valid_owner_proof(original):
    with connection(original['seed'], original['source_role']) as db:
        source = prepare(db, original)
        mint_proof(db, source)
        db.execute('set local role corporate_governance_workflow_executor')
        result = db.execute('select corporate_governance.complete_supported_event_v1(%s,%s)',
            (Jsonb(original['original_request']), str(original['seed']['owner']))).fetchone()[0]
        assert result['replayed'] is True
        assert proof_count(db, original['source_role']) == 1
        append_source(db, source, proof=False)


def test_same_company_write_invalidates_off_year_proof_even_without_chain_manifest_change(original):
    pending = pending_governance_event(original)
    with connection(original['seed'], original['source_role']) as db:
        source = prepare(db, original)
        assert source.income_year.value == 2026
        assert source.governance_projection.chains[0].income_year.value == 2026
        mint_proof(db, source)
        # Invalidation is company-wide, even for an off-year private slot. This
        # is not a claim that the 2026-only admission policy accepts 2025.
        corrupt_owned_proof_year(db, original, source)
        mint_proof(db, prepare(db, original))
        assert proof_count(db, original['source_role']) == 2
        db.execute('set local role corporate_governance_workflow_executor')
        db.execute('select corporate_governance.complete_supported_event_v1(%s,%s)',
            (Jsonb(pending), str(original['seed']['owner'])))
        assert proof_count(db, original['source_role']) == 0
        with pytest.raises(psycopg.Error, match=CHANGED):
            with db.transaction(): append_source(db, source, proof=False)
        # A new owner read may mint fresh lineage evidence. It still does not
        # authenticate the carried Python status/business digest.
        mint_proof(db, source)
        assert proof_count(db, original['source_role']) == 1


@pytest.mark.parametrize('statement', [
    'create temporary table rf1086_year_source_governance_proofs(spoof text)',
    'create temporary view rf1086_year_source_governance_proofs as select 1 as spoof',
])
def test_receiver_rejects_caller_owned_temporary_object_instead_of_repairing_it(original, statement):
    with connection(original['seed'], original['source_role']) as db:
        source = prepare(db, original)
        db.execute(statement)
        oid, owner = db.execute("select c.oid,c.relowner from pg_class c where c.relnamespace=pg_my_temp_schema() and c.relname='rf1086_year_source_governance_proofs'").fetchone()
        with pytest.raises(psycopg.Error, match=CHANGED):
            with db.transaction(): mint_proof(db, source)
        assert db.execute('select relowner from pg_class where oid=%s', (oid,)).fetchone()[0] == owner
        assert str(db.execute('select current_user').fetchone()[0]) == original['source_role']


def test_receiver_and_invalidator_are_closed_to_runtime_and_fixture_callers(original):
    with psycopg.connect(DATABASE_URL) as db:
        for name in ('receive_year_source_governance_proof_v1', 'invalidate_year_source_governance_proofs_v1'):
            oid = db.execute("select p.oid from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='shareholder_register_filing' and p.proname=%s", (name,)).fetchone()[0]
            assert db.execute("select has_function_privilege('corporate_governance_store_owner',%s::oid,'EXECUTE')", (oid,)).fetchone()[0]
            for role in ('shareholder_register_filing_executor','corporate_governance_workflow_executor','anon','authenticated','service_role',original['source_role']):
                assert not db.execute("select has_function_privilege(%s,%s::oid,'EXECUTE')", (role,oid)).fetchone()[0]
    with connection(original['seed'], original['source_role']) as db:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute('select ' + INVALIDATOR.split('(')[0] + '(%s)', (original['seed']['company'],))


@pytest.mark.parametrize('first', ['proof', 'amendment'])
@pytest.mark.parametrize('commit', [False, True])
def test_both_company_lock_orders_reject_stale_source_using_only_committed_governance_amendments(original, first, commit):
    pending = next_amendment(original)
    # next_amendment already withdrew the selected 2026 RF original. At the
    # supported year, an unchanged chain is therefore stale RF evidence; a
    # committed amendment changes the proof manifest before that RF check.
    queued = Queue()
    def competing():
        role = original['source_role'] if first == 'amendment' else 'corporate_governance_workflow_executor'
        with connection(original['seed'], role) as db:
            queued.put(db.execute('select pg_backend_pid()').fetchone()[0])
            if first == 'proof': return append_amendment(db, pending)
            source = prepare(db, original)
            with pytest.raises(psycopg.Error, match=CHANGED if commit else STALE):
                append_source(db, source)
    with ThreadPoolExecutor(max_workers=1) as pool:
        role = original['source_role'] if first == 'proof' else 'corporate_governance_workflow_executor'
        with connection(original['seed'], role) as db:
            if first == 'proof':
                source = prepare(db, original)
                mint_proof(db, source)
                # Preserve the outer company/year guards while recovering the
                # expected SQL failure; otherwise the waiter would not block.
                with pytest.raises(psycopg.Error, match=STALE):
                    with db.transaction(): append_source(db, source, proof=False)
            else: append_amendment(db, pending)
            future = pool.submit(competing)
            wait_for_company_lock(queued.get(timeout=3))
            assert not future.done()
            if commit: db.commit()
            else: db.rollback()
        result = future.result(timeout=8)
    assert rows(original) == []
    if first == 'amendment': assert result is None
    with connection(original['seed'], 'shareholder_register_filing_store_owner') as db:
        assert db.execute('select count(*) from ' + HEADS + ' where company_id=%s',
            (original['seed']['company'],)).fetchone()[0] == 0
    view = reporting_projection(original)
    assert view.register_chains[0].amendment_count == int(first == 'proof' or commit)


def test_proof_actor_binding_survives_switch_to_another_current_accepted_owner(original):
    with psycopg.connect(DATABASE_URL) as db:
        db.execute("insert into public.company_memberships(company_id,user_id,role,accepted_at) values(%s,%s,'owner',clock_timestamp())",
            (original['seed']['company'], original['seed']['outsider']))
    with connection(original['seed'], original['source_role']) as db:
        source = prepare(db, original)
        mint_proof(db, source)
        claims = json.loads(db.execute("select current_setting('talli.verified_actor_claims')").fetchone()[0])
        claims['sub'] = str(original['seed']['outsider'])
        db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true),set_config('request.jwt.claims',%s,true)",
            (claims['sub'],json.dumps(claims),json.dumps(claims)))
        db.execute('set local role shareholder_register_filing_store_owner')
        with pytest.raises(psycopg.Error, match=CHANGED): guarded_raw(db, source)


def test_other_company_proof_cannot_authorize_same_source_hash(original):
    from types import SimpleNamespace
    other = admitted.__wrapped__(SimpleNamespace())
    with psycopg.connect(DATABASE_URL) as db:
        db.execute("insert into public.company_memberships(company_id,user_id,role,accepted_at) values(%s,%s,'owner',clock_timestamp())",
            (other['company'],original['seed']['owner']))
    with connection(original['seed'], original['source_role']) as db:
        source = prepare(db, original)
        db.execute("select set_config('talli.authorized_company_roles',%s,true)",
            (json.dumps({str(original['seed']['company']): 'owner',str(other['company']): 'owner'}),))
        mint_proof(db, source, changes={'company': str(other['company'])})
        with pytest.raises(psycopg.Error, match=CHANGED): append_source(db, source, proof=False)


@pytest.mark.parametrize('mutation', ['grant', 'extra_column', 'rls', 'rule'])
def test_catalog_drift_of_real_owner_temp_table_fails_closed(original, mutation):
    with connection(original['seed'], original['source_role']) as db:
        source = prepare(db, original)
        mint_proof(db, source)
        # Privileged, transaction-rolled-back corruption of the owned temp
        # relation; no runtime caller receives this capability.
        try:
            with db.transaction():
                db.execute('set local role shareholder_register_filing_store_owner')
                if mutation == 'grant':
                    db.execute(sql.SQL('grant select on ' + PROOFS + ' to {}').format(sql.Identifier(original['source_role'])))
                elif mutation == 'extra_column': db.execute('alter table ' + PROOFS + ' add column forged boolean')
                elif mutation == 'rls': db.execute('alter table ' + PROOFS + ' enable row level security')
                else: db.execute('create rule fixture_hide_proof as on delete to ' + PROOFS + ' do instead nothing')
                db.execute(sql.SQL('set local role {}').format(sql.Identifier(original['source_role'])))
                with pytest.raises(psycopg.Error, match=CHANGED):
                    with db.transaction(): append_source(db, source, proof=False)
                raise RuntimeError('owned catalog rollback')
        except RuntimeError as error:
            assert str(error) == 'owned catalog rollback'
        db.execute(sql.SQL('set local role {}').format(sql.Identifier(original['source_role'])))
        append_source(db, source, proof=False)
    assert len(rows(original)) == 1


@pytest.mark.parametrize('assignment', [
    "transaction_id=(transaction_id::text::numeric+1)::text::xid8",
    "actor_id='00000000-0000-0000-0000-000000000001'::uuid",
    "company_id='00000000-0000-0000-0000-000000000001'::uuid",
    'income_year=2025',
    "source_sha256=repeat('f',64)",
    "proof=jsonb_set(proof,'{chain_count}','0')",
    "proof=proof||'{\"verified\":true}'::jsonb",
    "proof=jsonb_set(proof,'{chains,0,original_anchor_sha256}',to_jsonb(repeat('f',64)))",
])
def test_owned_proof_row_binding_and_full_compact_body_are_checked_on_every_use(original, assignment):
    with connection(original['seed'], original['source_role']) as db:
        source = prepare(db, original)
        mint_proof(db, source)
        try:
            with db.transaction():
                # Privileged corruption fixture only; ordinary callers cannot
                # read or update this RF-owned relation at all.
                db.execute('set local role shareholder_register_filing_store_owner')
                db.execute('update ' + PROOFS + ' set ' + assignment)
                with pytest.raises(psycopg.Error, match=CHANGED):
                    with db.transaction(): guarded_raw(db, source)
                raise RuntimeError('owned proof rollback')
        except RuntimeError as error:
            assert str(error) == 'owned proof rollback'
        db.execute(sql.SQL('set local role {}').format(sql.Identifier(original['source_role'])))
        append_source(db, source, proof=False)
    assert len(rows(original)) == 1


def test_temp_table_has_exact_owner_shape_and_transaction_bound_rows(original):
    with connection(original['seed'], original['source_role']) as db:
        source = prepare(db, original)
        mint_proof(db, source)
        metadata = db.execute("select c.oid,c.relowner::regrole::text,c.relkind,c.relpersistence,c.relrowsecurity,c.relforcerowsecurity from pg_class c where c.relnamespace=pg_my_temp_schema() and c.relname='rf1086_year_source_governance_proofs'").fetchone()
        oid, owner, kind, persistence, rls, force = metadata
        assert (owner,kind,persistence,rls,force)==('shareholder_register_filing_store_owner','r','t',False,False)
        assert db.execute('select a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull from pg_attribute a where a.attrelid=%s and a.attnum>0 and not a.attisdropped order by a.attnum', (oid,)).fetchall() == [
            ('transaction_id','xid8',True),('actor_id','uuid',True),('company_id','uuid',True),
            ('income_year','integer',True),('source_sha256','text',True),('proof','jsonb',True)]
        db.execute('set local role shareholder_register_filing_store_owner')
        row = db.execute('select transaction_id=pg_current_xact_id(),actor_id::text,company_id::text,income_year,source_sha256,proof from ' + PROOFS).fetchone()
        assert row[:5]==(True,str(original['seed']['owner']),source.company_id.value,2026,source.source_sha256)
        assert row[5]['codec']=='rf1086-year-governance-proof-v1'
        assert row[5]['chain_count']==1 and len(row[5]['chains'])==1
        assert 'original_enumeration_sha256' not in row[5] and 'enumeration_sha256' not in row[5]


def test_closed_producer_does_not_grant_rf_any_governance_query_or_private_access(original):
    with psycopg.connect(DATABASE_URL) as db:
        oid = db.execute("select p.oid from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='corporate_governance' and p.proname='prepare_rf_year_source_governance_proof_v1' and pg_catalog.oidvectortypes(p.proargtypes)='uuid, integer, text, text'").fetchone()[0]
        for role in ('shareholder_register_filing_executor','shareholder_register_filing_store_owner',
                'corporate_governance_workflow_executor','anon','authenticated','service_role'):
            assert not db.execute("select has_function_privilege(%s,%s::oid,'EXECUTE')", (role,oid)).fetchone()[0]
        assert db.execute("select has_function_privilege(%s,%s::oid,'EXECUTE')", (original['source_role'],oid)).fetchone()[0]
        # Function EXECUTE alone can count unrelated predecessor PUBLIC ACLs.
        # Direct queries require namespace USAGE as well; this producer must
        # neither open the namespace nor grant its four private contracts.
        assert not db.execute("select has_schema_privilege('shareholder_register_filing_store_owner',"
            "'corporate_governance','USAGE')").fetchone()[0]
        assert db.execute("select count(*) from pg_proc p join pg_namespace n on n.oid=p.pronamespace "
            "where n.nspname='corporate_governance' and "
            "has_schema_privilege('shareholder_register_filing_store_owner',n.oid,'USAGE') and "
            "has_function_privilege('shareholder_register_filing_store_owner',p.oid,'EXECUTE')").fetchone()[0] == 0
        assert db.execute("select count(*) from pg_proc p join pg_namespace n on n.oid=p.pronamespace "
            "where n.nspname='corporate_governance' and p.proname in "
            "('rf_year_source_fact_internal_v1','rf_year_source_chain_internal_v1',"
            "'prepare_rf_year_source_governance_proof_v1','invalidate_rf_year_source_proof_internal_v1')").fetchone()[0] == 4
        assert db.execute("select count(*) from pg_proc p join pg_namespace n on n.oid=p.pronamespace "
            "where n.nspname='corporate_governance' and p.proname in "
            "('rf_year_source_fact_internal_v1','rf_year_source_chain_internal_v1',"
            "'prepare_rf_year_source_governance_proof_v1','invalidate_rf_year_source_proof_internal_v1') and "
            "has_function_privilege('shareholder_register_filing_store_owner',p.oid,'EXECUTE')").fetchone()[0] == 0
        assert db.execute("select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace "
            "where n.nspname='corporate_governance' and c.relkind in ('r','p','v','m','f') and "
            "has_table_privilege('shareholder_register_filing_store_owner',c.oid,'SELECT')").fetchone()[0] == 0
        db.execute('set local role shareholder_register_filing_store_owner')
        with pytest.raises(psycopg.errors.InsufficientPrivilege) as denied:
            with db.transaction():
                db.execute("select corporate_governance.rf_year_source_fact_internal_v1('{}'::jsonb)")
        assert denied.value.diag.message_primary == 'permission denied for schema corporate_governance'


def test_actual_restricted_login_mints_and_uses_proof_without_owner_or_temp_authority(original, source_login):
    # Real PostgreSQL authentication/role path. Verified subject/claims are
    # fixture input, not a test of production Auth/session verification.
    with source_login.connect(original['seed']) as db:
        assert db.execute('select current_user,session_user').fetchone() == (source_login.role,source_login.role)
        assert db.execute('select rolsuper,rolcreaterole,rolcreatedb,rolbypassrls from pg_roles where rolname=current_user').fetchone() == (False,False,False,False)
        assert not db.execute('select exists(select 1 from pg_auth_members where member=current_user::regrole and admin_option)').fetchone()[0]
        for owner in ('shareholder_register_filing_store_owner','corporate_governance_store_owner'):
            assert not db.execute("select pg_has_role(current_user,%s,'SET') or pg_has_role(current_user,%s,'USAGE')", (owner,owner)).fetchone()[0]
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with db.transaction(): db.execute(sql.SQL('set local role {}').format(sql.Identifier(owner)))
        source = prepare(db, original)
        mint_proof(db, source)
        owner = db.execute("select relowner::regrole::text from pg_class where relnamespace=pg_my_temp_schema() and relname='rf1086_year_source_governance_proofs'").fetchone()[0]
        assert owner == 'shareholder_register_filing_store_owner'
        for statement in ('select * from ' + PROOFS, 'delete from ' + PROOFS,
                'update ' + PROOFS + ' set income_year=2025', 'drop table ' + PROOFS):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with db.transaction(): db.execute(statement)
        for statement, args in (
            ('select ' + RECEIVER.split('(')[0] + '(%s,%s,%s,%s,%s)',
                (source.company_id.value,2026,source.source_sha256,Jsonb({}),str(original['seed']['owner']))),
            ('select ' + INVALIDATOR.split('(')[0] + '(%s)', (source.company_id.value,)),
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with db.transaction(): db.execute(statement,args)
        # Repeated producer/read admission does not consume the legitimate
        # capability; raw table access or an owner SET edge is unnecessary.
        mint_proof(db, source)
        append_source(db, source, proof=False)
    assert len(rows(original)) == 1


def test_actual_restricted_login_cannot_precreate_a_trusted_proof_relation(original, source_login):
    with source_login.connect(original['seed']) as db:
        source = prepare(db, original)
        db.execute('create temporary table rf1086_year_source_governance_proofs(transaction_id xid8,actor_id uuid,company_id uuid,income_year integer,source_sha256 text,proof jsonb) on commit drop')
        with pytest.raises(psycopg.Error, match=CHANGED):
            with db.transaction(): mint_proof(db, source)
        assert db.execute("select relowner::regrole::text from pg_class where relnamespace=pg_my_temp_schema() and relname='rf1086_year_source_governance_proofs'").fetchone()[0] == source_login.role
    assert rows(original) == []


def test_reusing_minted_proof_still_rechecks_current_owner(original):
    with connection(original['seed'], original['source_role']) as db:
        source = prepare(db, original)
        mint_proof(db, source)
        db.execute('reset role')
        db.execute("update public.company_memberships set role='read_only' where company_id=%s and user_id=%s",
            (original['seed']['company'],original['seed']['owner']))
        db.execute(sql.SQL('set local role {}').format(sql.Identifier(original['source_role'])))
        with pytest.raises(psycopg.Error, match='rf1086_.*forbidden'):
            with db.transaction(): append_source(db, source, proof=False)
    assert rows(original) == []


def test_reusing_minted_proof_still_rechecks_actual_rf_currentness(original):
    with connection(original['seed'], original['source_role']) as db:
        source = prepare(db, original)
        mint_proof(db, source)
        db.execute(sql.SQL('set local role {}').format(sql.Identifier(original['withdrawal_role'])))
        withdrawal(original['seed'], original['withdrawal_role'], original['replacement'], db=db)
        assert proof_count(db, original['source_role']) == 1
        with pytest.raises(psycopg.Error, match=STALE):
            with db.transaction(): append_source(db, source, proof=False)
    assert rows(original) == []
