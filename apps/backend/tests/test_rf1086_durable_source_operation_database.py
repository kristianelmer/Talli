"""Durable initial/retry intents serialize full-year mutations before provider I/O."""
import asyncio
from dataclasses import replace
from hashlib import sha256
import json
from uuid import uuid4

import psycopg
import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_source_approval_database import bind_fixture_owner
from test_rf1086_annual_approval_database import (
    annual_fixture, approval_fixture, admitted, backend_url, rf_fixture_admin_access,
    remove_only_bridge_fixture, remove_only_preview_fixture, remove_only_owned_source_fixture,
    remove_only_annual_opening_fixture, fixture_roles, query, proof, approval, set_answers, DATABASE_URL, ROOT,
)

pytestmark = pytest.mark.authority_database
MIGRATION = '20260929182856_rf1086_durable_source_operation_intent.sql'


@pytest.fixture
def operation_fixture(annual_fixture):
    f = annual_fixture
    with psycopg.connect(DATABASE_URL) as db:
        db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
    async def seed():
        async with f['store'].source_admission(query(f)) as scope:
            result, manifest, annual = await approval(f, scope)
            claim = await scope.claim_source_submission(rf.ApprovalId(result.record_id), manifest.manifest_sha256, None, annual)
            f.update(claim=claim.claim, manifest=manifest, annual=annual)
    asyncio.run(seed())
    return f


async def prepare(f, name='post_hovedskjema', digest=None, **args):
    if digest is None: digest = f['manifest'].manifest['documentHashes'][0]['sha256']
    async with f['store'].source_admission(query(f)) as scope:
        annual = await proof(f, scope) if name == 'post_hovedskjema' else None
        return await scope.prepare_source_operation(f['claim'], operation_name=name,
            body_sha256=digest, idempotency_key=str(uuid4()), annual=annual, **args)


async def finish(f, intent, state='succeeded', reference=None, failure=None):
    return await f['store'].finish_source_operation(f['claim'].submission_id, intent.event.id,
        state=state, reference=reference, failure=failure)


def test_complete_original_payload_journal_and_exact_outcome_replay(operation_fixture):
    f = operation_fixture
    async def run():
        for doc in f['manifest'].manifest['documentHashes']:
            name = 'post_hovedskjema' if doc['name'] == 'hovedskjema' else 'post_underskjema:' + doc['name'].removeprefix('underskjema_')
            intent = await prepare(f, name, doc['sha256'])
            assert intent.newly_prepared and intent.event.operation_state == 'prepared'
            competing = await prepare(f, name, doc['sha256'])
            assert not competing.newly_prepared and competing.event == intent.event
            result = await finish(f, intent, reference='main-reference' if name == 'post_hovedskjema' else 'posted')
            assert await finish(f, intent, reference=result.authority_reference) == result
        count = len(f['manifest'].document_order)
        digest = sha256(f'main-reference:{count}'.encode()).hexdigest()
        intent = await prepare(f, 'confirm', digest)
        confirmation = json.dumps({'dialogId': str(uuid4()), 'forsendelseId': str(uuid4())}, separators=(',', ':'))
        await finish(f, intent, reference=confirmation)
        archive_query = rf.Rf1086ArchiveQuery(f['source'].company_id, f['source'].income_year, f['store'].actor_id)
        archive = await rf.create_rf1086_preparation_service(f['store']).archive_source(archive_query)
        assessment = rf.assess_rf1086_source_dispatch(archive, query=archive_query, submission_id=f['claim'].submission_id)
        assert assessment.disposition == 'confirmed'
        assert assessment.payload.underskjema_xml == f['manifest'].underskjema_xml
    asyncio.run(run())


def test_retry_commits_new_attempt_once_and_preserves_original_key(operation_fixture):
    f = operation_fixture
    async def run():
        first = await prepare(f)
        failed = await finish(f, first, 'failed', failure='retryable')
        second = await prepare(f, expected_event_id=failed.id)
        assert second.newly_prepared and second.event.attempt == 2
        assert second.event.idempotency_key == first.event.idempotency_key
        concurrent = await prepare(f, expected_event_id=failed.id)
        assert not concurrent.newly_prepared and concurrent.event == second.event
        with pytest.raises(Exception): await finish(f, first, reference='main-reference')
        await finish(f, second, reference='main-reference')
    asyncio.run(run())


@pytest.mark.parametrize('retry', [False, True])
def test_concurrent_callers_receive_only_one_committed_dispatch_intent(operation_fixture, retry):
    f = operation_fixture
    async def run():
        expected = None
        if retry:
            failed = await finish(f, await prepare(f), 'failed', failure='retryable')
            expected = failed.id
        results = await asyncio.gather(*(prepare(f, expected_event_id=expected) for _ in range(2)))
        assert sorted(result.newly_prepared for result in results) == [False, True]
        assert results[0].event == results[1].event
        assert results[0].event.attempt == (2 if retry else 1)
    asyncio.run(run())


@pytest.mark.parametrize('change', ['body', 'operation', 'foreign-event', 'missing-proof'])
def test_changed_intent_identity_never_inserts_a_journal_event(operation_fixture, change):
    f = operation_fixture
    async def run():
        if change == 'missing-proof':
            async with f['store'].source_admission(query(f)) as scope:
                await scope.prepare_source_operation(f['claim'], operation_name='post_hovedskjema',
                    body_sha256=f['manifest'].manifest['documentHashes'][0]['sha256'],
                    idempotency_key=str(uuid4()))
        else:
            args = {}
            if change == 'body': args['digest'] = 'a'*64
            if change == 'operation': args['name'] = 'post_underskjema:unapproved'
            if change == 'foreign-event': args['expected_event_id'] = str(uuid4())
            await prepare(f, **args)
    with pytest.raises(Exception): asyncio.run(run())
    with psycopg.connect(DATABASE_URL) as db:
        assert db.execute('select count(*) from shareholder_register_filing.production_filing_events where submission_id=%s',
            (f['claim'].submission_id.value,)).fetchone()[0] == 0


@pytest.mark.parametrize('state,failure', [('unknown', 'unknown'), ('failed', 'blocked')])
def test_uncertain_or_blocked_outcome_never_grants_another_intent(operation_fixture, state, failure):
    f = operation_fixture
    async def run():
        first = await prepare(f)
        outcome = await finish(f, first, state, failure=failure)
        result = await prepare(f, expected_event_id=outcome.id)
        assert not result.newly_prepared and result.event == outcome
        with pytest.raises(Exception): await finish(f, first, reference='invented-success')
    asyncio.run(run())


def test_changed_annual_facts_after_claim_block_first_intent(operation_fixture):
    f = operation_fixture
    set_answers(f, has_unpaid_items=True)
    with pytest.raises(Exception): asyncio.run(prepare(f))
    with psycopg.connect(DATABASE_URL) as db:
        assert db.execute('select count(*) from shareholder_register_filing.production_filing_events where submission_id=%s',
                          (f['claim'].submission_id.value,)).fetchone()[0] == 0


def test_unexplained_unknown_projection_never_grants_first_intent(operation_fixture):
    f = operation_fixture
    with psycopg.connect(DATABASE_URL) as db:
        bind_fixture_owner(db, f)
        db.execute("update shareholder_register_filing.production_filing_submissions set status='unknown' where id=%s", (f['claim'].submission_id.value,))
    with pytest.raises(Exception): asyncio.run(prepare(f))


@pytest.mark.parametrize('operation', ['post_hovedskjema', 'post_underskjema:made-up', 'confirm', ' post_hovedskjema '])
def test_generic_commands_cannot_bypass_full_year_admission(operation_fixture, operation):
    f = operation_fixture
    async def run():
        with pytest.raises(Exception):
            await f['store'].operation_journal(f['claim'].submission_id.value).prepare(
                submission_id=f['claim'].submission_id.value, name=operation, body_hash='a'*64, idempotency_key=str(uuid4()))
        with pytest.raises(Exception):
            await f['store']._rows('select shareholder_register_filing.append_production_filing_event(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (f['claim'].submission_id.value, operation, 'prepared', 1, 'a'*64, str(uuid4()), None, None, 'sending', False))
    asyncio.run(run())


def test_subdocument_and_confirmation_require_persisted_predecessor_success(operation_fixture):
    f = operation_fixture
    name = 'post_underskjema:' + f['manifest'].document_order[0]
    digest = f['manifest'].manifest['documentHashes'][1]['sha256']
    with pytest.raises(Exception): asyncio.run(prepare(f, name, digest))
    with pytest.raises(Exception): asyncio.run(prepare(f, 'confirm', 'a'*64))


def test_read_operation_cannot_be_completed_through_the_mutation_outcome_port(operation_fixture):
    f = operation_fixture
    async def run():
        event = await f['store'].operation_journal(f['claim'].submission_id.value).prepare(
            submission_id=f['claim'].submission_id.value, name='list_documents', body_hash=None, idempotency_key=None)
        with pytest.raises(Exception):
            await f['store'].finish_source_operation(f['claim'].submission_id, event.id,
                state='succeeded', reference='{"documentCount":0}')
    asyncio.run(run())


@pytest.mark.parametrize('reference', [
    '{"dialogId":null,"forsendelseId":null}',
    '{"dialogId":"invalid","forsendelseId":"invalid"}',
    '{"dialogId":1,"forsendelseId":2}',
    '{"dialogId":"00000000-0000-0000-0000-000000000001","dialogId":"00000000-0000-0000-0000-000000000001","forsendelseId":"00000000-0000-0000-0000-000000000002"}',
])
def test_confirmation_cannot_persist_missing_or_ambiguous_external_references(operation_fixture, reference):
    f = operation_fixture
    async def run():
        for doc in f['manifest'].manifest['documentHashes']:
            name = 'post_hovedskjema' if doc['name'] == 'hovedskjema' else 'post_underskjema:' + doc['name'].removeprefix('underskjema_')
            await finish(f, await prepare(f, name, doc['sha256']), reference='main-reference' if name == 'post_hovedskjema' else 'posted')
        intent = await prepare(f, 'confirm', sha256(f'main-reference:{len(f["manifest"].document_order)}'.encode()).hexdigest())
        with pytest.raises(Exception): await finish(f, intent, reference=reference)
        replay = await prepare(f, 'confirm', intent.event.body_hash)
        assert not replay.newly_prepared and replay.event == intent.event
    asyncio.run(run())


def test_continuation_uses_retained_bytes_after_annual_change_but_obeys_current_kill_switch(operation_fixture):
    f = operation_fixture
    async def start():
        await finish(f, await prepare(f), reference='main-reference')
    asyncio.run(start())
    set_answers(f, has_unpaid_items=True)
    name = 'post_underskjema:' + f['manifest'].document_order[0]
    digest = f['manifest'].manifest['documentHashes'][1]['sha256']
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('update shareholder_register_filing.authority_permissions set production_enabled=false where company_id=%s', (f['seed']['company'],))
    with pytest.raises(Exception): asyncio.run(prepare(f, name, digest))
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('update shareholder_register_filing.authority_permissions set production_enabled=true where company_id=%s', (f['seed']['company'],))
    assert asyncio.run(prepare(f, name, digest)).newly_prepared


@pytest.mark.parametrize('continuation', [False, True])
@pytest.mark.parametrize('change', ['owner', 'mfa', 'pilot', 'authority', 'technical'])
def test_every_new_intent_requires_current_authority(operation_fixture, continuation, change):
    f = operation_fixture
    name, digest = 'post_hovedskjema', None
    if continuation:
        asyncio.run(finish(f, asyncio.run(prepare(f)), reference='main-reference'))
        name = 'post_underskjema:' + f['manifest'].document_order[0]
        digest = f['manifest'].manifest['documentHashes'][1]['sha256']
    with psycopg.connect(DATABASE_URL) as db:
        if change == 'owner':
            db.execute("update public.company_memberships set role='read_only' where company_id=%s and user_id=%s",
                (f['seed']['company'], f['seed']['owner']))
        elif change == 'pilot':
            db.execute("update billing.production_pilot_entitlements set starts_at=now()-interval '2 days',expires_at=now()-interval '1 day' where id=%s", (f['entitlement'],))
        elif change == 'authority':
            db.execute('update authority_connections.system_user_requests set preflight_verified_at=null where id=%s', (f['request'],))
        elif change == 'technical':
            db.execute("update public.launch_signoffs set status='pending' where key='rf1086_authority'")
    if change == 'mfa':
        claims = json.loads(f['store']._verified.claims_json)
        for method in claims['amr']: method['timestamp'] = 0
        f['store']._verified = replace(f['store']._verified, claims_json=json.dumps(claims))
    with pytest.raises((rf.Rf1086ProductionError, rf.ShareholderRegisterFilingError)):
        asyncio.run(prepare(f, name, digest))
    with psycopg.connect(DATABASE_URL) as db:
        assert db.execute('select count(*) from shareholder_register_filing.production_filing_events where submission_id=%s and operation_name=%s',
            (f['claim'].submission_id.value, name)).fetchone()[0] == 0


def test_rollback_blocks_new_intents_but_retains_outcome_recording(operation_fixture):
    f = operation_fixture
    intent = asyncio.run(prepare(f))
    try:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
        with pytest.raises(Exception): asyncio.run(prepare(f))
        assert asyncio.run(finish(f, intent, reference='main-reference')).operation_state == 'succeeded'
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())


def test_replay_restores_exact_authority_and_only_backend_can_prepare(operation_fixture):
    with psycopg.connect(DATABASE_URL) as db:
        roles = 'select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3'
        before = db.execute(roles).fetchall()
        schemas = "select nspname,nspowner,nspacl::text from pg_namespace where nspname in ('backend_system','shareholder_register_filing') order by 1"
        before_schema = db.execute(schemas).fetchall()
        for _ in range(2):
            db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
            db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
        assert db.execute(roles).fetchall() == before
        assert db.execute(schemas).fetchall() == before_schema
        for role in ('anon', 'authenticated', 'service_role'):
            assert not db.execute("select has_function_privilege(%s,'shareholder_register_filing.prepare_source_operation_v1(uuid,text,text,text,uuid,uuid,text,text)','execute')", (role,)).fetchone()[0]
        assert db.execute("select has_function_privilege('shareholder_register_filing_executor','shareholder_register_filing.prepare_source_operation_v1(uuid,text,text,text,uuid,uuid,text,text)','execute')").fetchone()[0]
