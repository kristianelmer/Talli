"""Direct old SQL admissions versus withdrawal; no provider or runtime activation."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
import json
from queue import Queue
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import IdempotencyKey
from test_rf1086_register_observation_withdrawal_database import (
    staged, connection, observed, withdraw, append as append_withdrawal, wait_for_lock,
    admitted, backend_url, cleanup_owned_fixture, rf_fixture_admin_access, DATABASE_URL, ROOT,
)
from test_rf1086_annual_approval_database import (
    annual_fixture, approval_fixture, remove_only_bridge_fixture, remove_only_preview_fixture,
    remove_only_owned_source_fixture, remove_only_annual_opening_fixture, fixture_roles, proof, query,
)
from test_rf1086_year_source import basis
from test_rf1086_source_preview_database import generate
from test_rf1086_source_review_bridge_database import bridge

pytestmark = pytest.mark.authority_database
MIGRATION = '20261009215302_rf1086_withdrawal_source_admission_guards.sql'
GUARD = 'shareholder_register_filing.assert_source_register_observations_active_internal_v1'
EXTRA_FUNCTIONS = (
    GUARD + '(uuid,integer,text)', GUARD + '(uuid,integer,uuid,text)',
    'shareholder_register_filing.read_source_approval_context_v1(uuid,uuid,text)',
    'shareholder_register_filing.append_source_approval_v1(uuid,uuid,text,text,text,text)',
    'shareholder_register_filing.claim_source_submission_v1(uuid,text,uuid,text)',
)
STAGES = ('source', 'preview', 'bridge', 'approval_v1', 'approval_v2', 'claim_v1', 'claim_v2',
          'intent_main', 'intent_child', 'intent_confirm', 'retry_main', 'retry_child', 'retry_confirm')


@pytest.fixture
def downstream(annual_fixture, staged):
    # The existing annual fixture owns foreign prerequisites and their teardown.
    # Create a NEW source version; never mutate an immutable stored snapshot.
    f = dict(annual_fixture)
    f['staged'] = dict(staged, store=f['store'])
    with psycopg.connect(DATABASE_URL) as db:
        db.execute((ROOT / 'supabase/migrations' / MIGRATION).read_text())
        db.execute('set local role shareholder_register_filing_store_owner')
        db.execute(sql.SQL('grant execute on function ' + ','.join(EXTRA_FUNCTIONS) + ' to {}').format(sql.Identifier(staged['role'])))
    try:
        observation = observed(f['staged'])
        command, context = basis('cash_issue')
        original = f['source']
        documents = f['command'].documents
        case = replace(command.case, company=f['command'].case.company,
                       events=tuple(replace(event, timestamp=event.timestamp.replace(year=2026)) for event in command.case.events))
        receipt = replace(context.governance_receipts[0], receipt_id=str(uuid4()),
            company_id=original.company_id, income_year=original.income_year,
            economic_sha256=rf.rf1086_year_source_digest(rf.rf1086_governance_economic_facts(case.events[0])),
            signed_document_hashes=(documents[0].content_sha256,),
            register_observation_id=observation.observation_id.value, register_observation_sha256=observation.fact_sha256)
        command = replace(command, company_id=original.company_id, income_year=original.income_year,
            actor_id=f['store'].actor_id, case=case, documents=documents,
            opening_document_ids=(documents[0].document_id,), closing_document_ids=(documents[0].document_id,),
            paid_in_document_ids=(documents[0].document_id,), event_evidence=(replace(command.event_evidence[0],
                event_sha256=rf.rf1086_year_source_digest(case.events[0]), document_ids=(documents[0].document_id,),
                governance_receipt_id=receipt.receipt_id),), supersedes_source_id=original.source_id,
            supersedes_source_sha256=original.source_sha256, correction_reason='Owned reference-bearing fixture')
        context = replace(context, actor_id=f['store'].actor_id, company_id=original.company_id,
            income_year=original.income_year, company=case.company, documents=documents,
            governance_receipts=(receipt,), governance_enumeration_sha256=rf.rf1086_year_source_digest((receipt,)))
        key = IdempotencyKey(str(uuid4()))
        source = asyncio.run(f['store'].record_year_source(command, context=context, idempotency_key=key))
        f.update(command=command, context=context, source=source, source_key=key, observation=observation)
        f['preview'] = generate(f['store'], source)
        f['connection'] = asyncio.run(f['store'].read_connection(str(f['request']), str(f['seed']['company'])))
        yield f
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('set local role shareholder_register_filing_store_owner')
            db.execute(sql.SQL('revoke execute on function ' + ','.join(EXTRA_FUNCTIONS) + ' from {}').format(sql.Identifier(staged['role'])))


def locked(db, f):
    db.execute('select shareholder_register_filing.lock_year_source_v1(%s,%s)', (f['seed']['company'], 2026))


def preview_call(db, preview):
    text = rf.serialize_rf1086_source_preview(preview)
    return db.execute('select shareholder_register_filing.append_source_preview_v1(%s,%s,%s,%s,%s,%s,%s,%s)',
        (preview.preview_id.value, preview.company_id.value, preview.income_year.value, preview.source_id.value,
         preview.source_sha256, preview.case_sha256, sha256(text.encode()).hexdigest(), text)).fetchone()[0]


def bridge_call(db, f):
    return db.execute('select shareholder_register_filing.bridge_source_preview_v1(%s,%s,%s)',
        (f['preview'].preview_id.value, sha256(rf.serialize_rf1086_source_preview(f['preview']).encode()).hexdigest(),
         str(f['store'].actor_id.subject))).fetchone()[0]


def source_call(db, f, *, mutate=None):
    command = replace(f['command'], supersedes_source_id=f['source'].source_id,
        supersedes_source_sha256=f['source'].source_sha256, correction_reason='New directly admitted source')
    at = db.execute('select clock_timestamp()').fetchone()[0]
    source = rf.prepare_rf1086_year_source(command, context=f['context'], previous=f['source'],
        source_id=rf.Rf1086YearSourceId(str(uuid4())), confirmed_at=at)
    encoded = rf.serialize_rf1086_year_source(source)
    if mutate is not None:
        raw = json.loads(encoded)
        mutate(raw)
        encoded = json.dumps(raw, separators=(',', ':'))
    db.execute('select shareholder_register_filing.append_year_source_v1(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
        (source.source_id.value, source.company_id.value, source.income_year.value, source.version,
         source.source_sha256, rf.rf1086_year_source_digest(command), str(uuid4()), f['source'].source_id.value,
         f['source'].source_sha256, command.correction_reason, encoded, at))
    return source.source_id.value


def approval_call(db, f):
    locked(db, f)
    return db.execute('select to_jsonb(r) from shareholder_register_filing.append_source_approval_v'
        + str(f['version']) + '(%s,%s,%s,%s,%s,%s) r',
        (f['preview'].preview_id.value, f['entitlement'], f['manifest_text'], f['manifest'].manifest_sha256,
         f['review_sha'], str(f['store'].actor_id.subject))).fetchone()[0]


def claim_call(db, f):
    locked(db, f)
    args = [f['approval']['id'], f['manifest'].manifest_sha256, None]
    if f['version'] == 2:
        args.append(f['annual_text'])
    args.append(str(f['store'].actor_id.subject))
    return db.execute('select shareholder_register_filing.claim_source_submission_v' + str(f['version'])
        + '(' + ','.join('%s' for _ in args) + ')', args).fetchone()[0]


def intent_call(db, f, *, name=None, digest=None, expected=None):
    locked(db, f)
    return db.execute('select shareholder_register_filing.prepare_source_operation_v2(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
        (f['claim']['claim']['submission_id'], f['manifest'].manifest_sha256,
         name or f['operation'], digest or f['body_sha'], str(uuid4()), expected or f.get('expected_event'),
         f['annual_text'] if (name or f['operation']) == 'post_hovedskjema' else None,
         str(f['request']), f['connection'].external_ref, str(f['store'].actor_id.subject))).fetchone()[0]


def finish_call(db, f, intent, *, state='succeeded', failure=None):
    event = intent['operation']
    reference = ('main-reference' if event['operation_name'] == 'post_hovedskjema' else 'child-reference') if state == 'succeeded' else None
    if state == 'succeeded' and event['operation_name'] == 'confirm':
        reference = json.dumps({'dialogId': str(uuid4()), 'forsendelseId': str(uuid4())}, separators=(',', ':'))
    return db.execute('select to_jsonb(r) from shareholder_register_filing.finish_source_operation_v1(%s,%s,%s,%s,%s,%s) r',
        (f['claim']['claim']['submission_id'], event['id'], state, reference, failure, str(f['store'].actor_id.subject))).fetchone()[0]


def prepare_stage(f, stage):
    if stage == 'source':
        return lambda db: source_call(db, f)
    if stage == 'preview':
        preview = replace(f['preview'], preview_id=rf.PreviewId(str(uuid4())))
        return lambda db: preview_call(db, preview)
    if stage == 'bridge':
        return lambda db: bridge_call(db, f)
    asyncio.run(bridge(f['store'], f['preview']))
    f['version'] = 1 if stage.endswith('_v1') else 2
    if f['version'] == 1:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('update public.filing_readiness_snapshots set ready=true where company_id=%s', (f['seed']['company'],))
        f['annual_text'] = None
    else:
        async def annual():
            async with f['store'].source_admission(query(f)) as scope:
                return await proof(f, scope)
        f['annual'] = asyncio.run(annual())
        f['annual_text'] = rf.serialize_rf1086_annual_readiness(f['annual'], f['source'], f['preview'])
    with connection(f['staged']) as db:
        locked(db, f)
        args = [f['preview'].preview_id.value, f['entitlement']]
        if f['version'] == 2:
            args.append(f['annual_text'])
        args.append(str(f['store'].actor_id.subject))
        review = db.execute('select shareholder_register_filing.read_source_approval_context_v' + str(f['version'])
            + '(' + ','.join('%s' for _ in args) + ')', args).fetchone()[0]
        assert review['blockers'] == [], review['blockers']
    f['review_sha'] = review['reviewSha256']
    f['manifest'] = rf.build_rf1086_source_approval_manifest(rf.Rf1086SourceApprovalManifestBasis(
        f['source'], f['preview'], f['store'].actor_id, str(f['entitlement']), f['review_sha'],
        tuple(review['warningCodes']), annual_readiness=f.get('annual')))
    f['manifest_text'] = rf.serialize_rf1086_source_approval_manifest(f['manifest'])
    if stage.startswith('approval_'):
        return lambda db: approval_call(db, f)
    with connection(f['staged']) as db:
        f['approval'] = approval_call(db, f)
    if stage.startswith('claim_'):
        return lambda db: claim_call(db, f)
    with connection(f['staged']) as db:
        f['claim'] = claim_call(db, f)
    docs = f['manifest'].manifest['documentHashes']
    operations = [('post_hovedskjema' if doc['name'] == 'hovedskjema' else
                   'post_underskjema:' + doc['name'].removeprefix('underskjema_'), doc['sha256']) for doc in docs]
    operations.append(('confirm', sha256(f'main-reference:{len(docs)-1}'.encode()).hexdigest()))
    position = 0 if stage.endswith('_main') else 1 if stage.endswith('_child') else len(operations) - 1
    for name, digest in operations[:position]:
        with connection(f['staged']) as db:
            intent = intent_call(db, f, name=name, digest=digest)
            finish_call(db, f, intent)
    f['operation'], f['body_sha'] = operations[position]
    if stage.startswith('retry_'):
        with connection(f['staged']) as db:
            failed = finish_call(db, f, intent_call(db, f), state='failed', failure='retryable')
        f['expected_event'] = failed['id']
    return lambda db: intent_call(db, f)


def state(f):
    tables = ('year_source_versions', 'year_source_heads', 'source_previews', 'source_review_bridges',
              'filing_approval_snapshots', 'source_approval_bindings', 'source_submission_bindings',
              'submission_heads', 'production_filing_submissions')
    with connection(f['staged']) as db:
        result = [db.execute('select count(*) from shareholder_register_filing.' + table + ' where company_id=%s',
                            (f['seed']['company'],)).fetchone()[0] for table in tables]
        result.append(db.execute('select count(*) from shareholder_register_filing.production_filing_events e '
            'join shareholder_register_filing.production_filing_submissions s on s.id=e.submission_id where s.company_id=%s',
            (f['seed']['company'],)).fetchone()[0])
        result.append(db.execute('select id,invalidated_at from shareholder_register_filing.filing_approval_snapshots '
            'where company_id=%s order by id', (f['seed']['company'],)).fetchall())
        return result


@pytest.mark.parametrize('stage', STAGES)
def test_withdrawal_first_blocks_every_direct_old_sql_admission_without_mutation(downstream, stage):
    f = downstream
    operation = prepare_stage(f, stage)
    before = state(f)
    withdraw(f['staged'], f['observation'])
    with connection(f['staged']) as db:
        with pytest.raises(psycopg.Error, match='rf1086_source_register_observation_stale'):
            operation(db)
    assert state(f) == before
    assert asyncio.run(f['store'].read_year_source_capture_receipt(f['command'], idempotency_key=f['source_key'])) == f['source']


@pytest.mark.parametrize('stage', STAGES)
@pytest.mark.parametrize('winner', ['withdrawal', 'admission'])
def test_both_company_lock_orders_linearize_fresh_admission_and_withdrawal(downstream, stage, winner):
    f = downstream
    operation = prepare_stage(f, stage)
    before = state(f)
    started = Queue()
    def compete():
        with connection(f['staged']) as db:
            started.put(db.execute('select pg_backend_pid()').fetchone()[0])
            return operation(db) if winner == 'withdrawal' else append_withdrawal(db, f['observation'])
    with ThreadPoolExecutor(max_workers=1) as pool:
        with connection(f['staged']) as db:
            if winner == 'withdrawal':
                append_withdrawal(db, f['observation'])
            else:
                operation(db)
            pending = pool.submit(compete)
            wait_for_lock(started.get(timeout=5))
        if winner == 'withdrawal':
            with pytest.raises(psycopg.Error, match='rf1086_source_register_observation_stale'):
                pending.result(timeout=10)
            assert state(f) == before
        else:
            assert rf.parse_rf1086_register_observation_withdrawal(pending.result(timeout=10)).command.observation_id == f['observation'].observation_id
            assert state(f) != before


@pytest.mark.parametrize('stage', tuple(stage for stage in STAGES if stage != 'source'))
def test_committed_replay_precedes_new_observation_check(downstream, stage):
    f = downstream
    operation = prepare_stage(f, stage)
    with connection(f['staged']) as db:
        first = operation(db)
    before = state(f)
    withdraw(f['staged'], f['observation'])
    with connection(f['staged']) as db:
        replay = operation(db)
    if stage.startswith(('intent_', 'retry_')):
        assert replay['operation'] == first['operation'] and replay['newlyPrepared'] is False
    elif stage.startswith('claim_'):
        assert replay['claim'] == first['claim'] and replay['newlyClaimed'] is False
    else:
        assert replay == first
    assert state(f) == before


@pytest.mark.parametrize('outcome,failure', [('succeeded', None), ('failed', 'retryable'), ('unknown', 'unknown')])
def test_already_admitted_intent_can_record_outcome_after_withdrawal(downstream, outcome, failure):
    f = downstream
    operation = prepare_stage(f, 'intent_main')
    with connection(f['staged']) as db:
        intent = operation(db)
    withdraw(f['staged'], f['observation'])
    with connection(f['staged']) as db:
        result = finish_call(db, f, intent, state=outcome, failure=failure)
    with connection(f['staged']) as db:
        assert finish_call(db, f, intent, state=outcome, failure=failure) == result
    with connection(f['staged']) as db:
        if outcome == 'failed':
            f['expected_event'] = result['id']
            with pytest.raises(psycopg.Error, match='rf1086_source_register_observation_stale'):
                operation(db)
        elif outcome == 'succeeded':
            child = f['manifest'].manifest['documentHashes'][1]
            with pytest.raises(psycopg.Error, match='rf1086_source_register_observation_stale'):
                intent_call(db, f, name='post_underskjema:' + child['name'].removeprefix('underskjema_'), digest=child['sha256'])
        else:
            assert operation(db)['newlyPrepared'] is False


@pytest.mark.parametrize('stage', STAGES)
@pytest.mark.parametrize('isolation', ['repeatable read', 'serializable'])
def test_old_sql_rejects_snapshot_fixed_before_withdrawal(downstream, stage, isolation):
    f = downstream
    operation = prepare_stage(f, stage)
    with connection(f['staged'], repeatable_read=True) as db:
        if isolation == 'serializable':
            # connection() already selected RR before any snapshot; only SETs
            # and set_config have run, so use a dedicated pre-query transaction.
            db.rollback()
            db.execute('set transaction isolation level serializable')
            db.execute(sql.SQL('set local role {}').format(sql.Identifier(f['staged']['role'])))
            db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true),set_config('request.jwt.claims',%s,true)",
                (str(f['store'].actor_id.subject), f['store']._verified.claims_json, f['store']._verified.claims_json))
            db.execute("set local statement_timeout='8s'")
            db.execute("set local lock_timeout='5s'")
        db.execute('select count(*) from shareholder_register_filing.register_observations').fetchone()
        withdraw(f['staged'], f['observation'])
        with pytest.raises(psycopg.Error, match='rf1086_source_approval_guard_required'):
            operation(db)


@pytest.mark.parametrize('change', ['missing', 'null', 'scalar', 'wrong_record', 'half_null', 'boolean_id', 'invalid_id',
    'uppercase_hash', 'wrong_scope', 'missing_bound_receipt', 'missing_both_collections', 'capital_as_dividend', 'duplicate_index', 'duplicate_keys', 'unknown_target', 'wrong_hash', 'not_predating'])
def test_reference_parser_fails_closed_before_any_new_effect(downstream, change):
    f = downstream
    raw = json.loads(rf.serialize_rf1086_year_source(f['source']))
    fields = raw['snapshot']['fields']
    receipt = fields['governance_receipts'][0]['fields']
    expected = 'rf1086_source_storage_invalid'
    if change == 'missing': del fields['governance_receipts']
    if change == 'null': fields['governance_receipts'] = None
    if change == 'scalar': fields['governance_receipts'] = 'none'
    if change == 'wrong_record': fields['governance_receipts'][0]['record'] = 'OtherReceipt'
    if change == 'half_null': receipt['register_observation_id'] = None
    if change == 'boolean_id': receipt['register_observation_id'] = True
    if change == 'invalid_id': receipt['register_observation_id'] = 'invalid'
    if change == 'uppercase_hash': receipt['register_observation_sha256'] = 'A' * 64
    if change == 'wrong_scope': receipt['company_id']['fields']['value'] = str(uuid4())
    if change == 'missing_bound_receipt': fields['governance_receipts'] = []
    if change == 'missing_both_collections':
        fields['governance_receipts'] = []
        fields['command']['fields']['event_evidence'] = []
    if change == 'capital_as_dividend':
        receipt['event_type'] = 'dividend'
        receipt['register_observation_id'] = receipt['register_observation_sha256'] = None
    if change == 'duplicate_index':
        fields['command']['fields']['case']['fields']['events'] *= 2
        fields['command']['fields']['event_evidence'] *= 2
    if change == 'unknown_target': receipt['register_observation_id'] = str(uuid4()); expected = 'rf1086_source_register_observation_stale'
    if change == 'wrong_hash': receipt['register_observation_sha256'] = '0' * 64; expected = 'rf1086_source_register_observation_stale'
    if change == 'not_predating': fields['confirmed_at']['datetime'] = f['observation'].confirmed_at.isoformat(); expected = 'rf1086_source_register_observation_stale'
    text = json.dumps(raw, separators=(',', ':'))
    if change == 'duplicate_keys': text = text.replace('"register_observation_id":', '"register_observation_id":null,"register_observation_id":', 1)
    before = state(f)
    with connection(f['staged']) as db:
        locked(db, f)
        with pytest.raises(psycopg.Error, match=expected):
            db.execute('select ' + GUARD + '(%s,%s,%s)', (f['seed']['company'], 2026, text))
    assert state(f) == before


def test_unrelated_withdrawal_does_not_block_reference_free_or_other_exact_sources(downstream):
    f = downstream
    unrelated = observed(f['staged'])
    withdraw(f['staged'], unrelated)
    with connection(f['staged']) as db:
        locked(db, f)
        db.execute('select ' + GUARD + '(%s,%s,%s,%s)',
            (f['seed']['company'], 2026, f['source'].source_id.value, f['source'].source_sha256))
        source = db.execute('select id,source_sha256 from shareholder_register_filing.year_source_versions '
            'where company_id=%s and version=1', (f['seed']['company'],)).fetchone()
        db.execute('select ' + GUARD + '(%s,%s,%s,%s)', (f['seed']['company'], 2026, *source))


def test_migration_replay_retains_catalog_attributes_closed_grants_and_rollback_barrier(downstream):
    f = downstream
    with psycopg.connect(DATABASE_URL) as db:
        catalog = "select oid,proowner,proacl::text,proconfig,prosecdef,provolatile,proparallel from pg_proc where pronamespace='shareholder_register_filing'::regnamespace order by oid"
        before = db.execute(catalog).fetchall()
        memberships = db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall()
        db.execute((ROOT / 'supabase/migrations' / MIGRATION).read_text())
        assert db.execute(catalog).fetchall() == before
        assert db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall() == memberships
        for role in ('anon', 'authenticated', 'service_role', 'shareholder_register_filing_executor', 'corporate_governance_workflow_executor'):
            for function in EXTRA_FUNCTIONS:
                assert not db.execute("select has_function_privilege(%s,%s,'EXECUTE')", (role, function)).fetchone()[0]
        db.execute((ROOT / 'supabase/rollback' / MIGRATION).read_text())
        assert db.execute(catalog).fetchall() == before
    withdraw(f['staged'], f['observation'])
    with psycopg.connect(DATABASE_URL) as db:
        with pytest.raises(psycopg.Error, match='retained_withdrawals_block_rollback'):
            db.execute((ROOT / 'supabase/rollback' / MIGRATION).read_text())
    with connection(f['staged']) as db:
        assert db.execute("select relforcerowsecurity from pg_class where oid='shareholder_register_filing.register_observation_withdrawals'::regclass").fetchone()[0]


@pytest.mark.parametrize('attack', ['remove_both_arrays', 'disguise_capital_as_dividend'])
def test_direct_old_append_cannot_omit_or_disguise_required_reference(downstream, attack):
    f = downstream
    def mutate(raw):
        fields = raw['snapshot']['fields']
        if attack == 'remove_both_arrays':
            fields['governance_receipts'] = []
            fields['command']['fields']['event_evidence'] = []
        else:
            receipt = fields['governance_receipts'][0]['fields']
            receipt['event_type'] = 'dividend'
            receipt['register_observation_id'] = receipt['register_observation_sha256'] = None
    before = state(f)
    with connection(f['staged']) as db:
        with pytest.raises(psycopg.Error, match='rf1086_source_storage_invalid'):
            source_call(db, f, mutate=mutate)
    assert state(f) == before


def test_real_old_sql_stale_error_is_typed_without_driver_details(downstream):
    f = downstream
    preview = replace(f['preview'], preview_id=rf.PreviewId(str(uuid4())))
    text = rf.serialize_rf1086_source_preview(preview)
    withdraw(f['staged'], f['observation'])
    async def run():
        async with f['store']._transaction() as db:
            await db.execute('select shareholder_register_filing.append_source_preview_v1(%s,%s,%s,%s,%s,%s,%s,%s)',
                (preview.preview_id.value, preview.company_id.value, preview.income_year.value, preview.source_id.value,
                 preview.source_sha256, preview.case_sha256, sha256(text.encode()).hexdigest(), text))
    with pytest.raises(rf.Rf1086YearSourceError) as caught:
        asyncio.run(run())
    assert str(caught.value) == 'rf1086_source_register_observation_stale'
    assert caught.value.__suppress_context__
