"""Durable initial/retry intents serialize full-year mutations before provider I/O."""
import asyncio
from dataclasses import replace
from hashlib import sha256
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import psycopg
import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.adapters.postgres_shareholder_register_filing import _PersistenceError
from test_rf1086_source_approval_database import bind_fixture_owner
from test_rf1086_annual_approval_database import (
    annual_fixture, approval_fixture, admitted, backend_url, rf_fixture_admin_access,
    remove_only_bridge_fixture, remove_only_preview_fixture, remove_only_owned_source_fixture,
    remove_only_annual_opening_fixture, fixture_roles, query, proof, approval, set_answers, DATABASE_URL, ROOT,
)

pytestmark = pytest.mark.authority_database
INTENT_MIGRATION = '20260929182856_rf1086_durable_source_operation_intent.sql'
MIGRATION = '20260929192057_rf1086_dispatch_binding_identity.sql'


@pytest.fixture
def operation_fixture(annual_fixture):
    f = annual_fixture
    with psycopg.connect(DATABASE_URL) as db:
        db.execute((ROOT/'supabase/migrations'/INTENT_MIGRATION).read_text())
        db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
    async def seed():
        f['connection'] = await f['store'].read_connection(str(f['request']), str(f['seed']['company']))
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
            body_sha256=digest, idempotency_key=str(uuid4()), connection=f['connection'], annual=annual, **args)


async def finish(f, intent, state='succeeded', reference=None, failure=None):
    try:
        return await f['store'].finish_source_operation(f['claim'].submission_id, intent.event.id,
            state=state, reference=reference, failure=failure)
    except _PersistenceError as error:
        # Preserve the failure type and safe driver classification for CI;
        # never expose SQL text, parameters, credentials or provider responses.
        error.add_note(f'SQLSTATE={error.code or "unavailable"}')
        raise


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


def test_override_receiver_rollback_stops_new_intents_but_retains_inflight_outcomes(operation_fixture):
    f = operation_fixture
    migration = '20260930083000_rf1086_override_receiver_cutover.sql'
    first = asyncio.run(prepare(f))
    child = f['manifest'].manifest['documentHashes'][1]
    operation = 'post_underskjema:' + child['name'].removeprefix('underskjema_')
    async def events():
        return await f['store']._rows(
            'select * from shareholder_register_filing.production_filing_events where submission_id=%s order by created_at,id',
            (f['claim'].submission_id.value,))
    with psycopg.connect(DATABASE_URL, autocommit=True) as db:
        try:
            db.execute((ROOT/'supabase/rollback'/migration).read_text())
            # A provider outcome already in flight must remain recordable.
            completed = asyncio.run(finish(f, first, reference='retained-main-reference'))
            assert completed.operation_state == 'succeeded'
            before = asyncio.run(events())
            with pytest.raises((rf.ShareholderRegisterFilingError, rf.Rf1086ProductionError)):
                asyncio.run(prepare(f, operation, child['sha256']))
            assert asyncio.run(events()) == before
            db.execute((ROOT/'supabase/migrations'/migration).read_text())
            assert asyncio.run(prepare(f, operation, child['sha256'])).newly_prepared
        finally:
            db.execute((ROOT/'supabase/migrations'/migration).read_text())


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
                    idempotency_key=str(uuid4()), connection=f['connection'])
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


@pytest.mark.parametrize('continuation', [False, True])
@pytest.mark.parametrize('change', ['request', 'external'])
def test_credentials_must_match_the_locked_authority_binding(operation_fixture, continuation, change):
    f = operation_fixture
    name, digest = 'post_hovedskjema', None
    if continuation:
        asyncio.run(finish(f, asyncio.run(prepare(f)), reference='main-reference'))
        name = 'post_underskjema:' + f['manifest'].document_order[0]
        digest = f['manifest'].manifest['documentHashes'][1]['sha256']
    f['connection'] = replace(f['connection'], **({'id': str(uuid4())} if change == 'request'
        else {'external_ref': 'credentials-from-a-different-connection'}))
    with pytest.raises(rf.Rf1086ProductionError, match='connection_unavailable'): asyncio.run(prepare(f, name, digest))
    with psycopg.connect(DATABASE_URL) as db:
        assert db.execute('select count(*) from shareholder_register_filing.production_filing_events where submission_id=%s and operation_name=%s',
            (f['claim'].submission_id.value, name)).fetchone()[0] == 0


@pytest.mark.parametrize('lost_stage', [None, 'main', 'sub', 'confirm'])
def test_synthetic_provider_observes_committed_intents_outside_database_guard(operation_fixture, lost_stage):
    from test_shareholder_register_filing_production import Authority
    f = operation_fixture
    query = rf.Rf1086ArchiveQuery(f['source'].company_id,f['source'].income_year,f['store'].actor_id)
    class Journal:
        intent = None
        async def prepare(self, *, submission_id, name, body_hash, idempotency_key):
            assert submission_id == f['claim'].submission_id.value
            result = await prepare(f, name, body_hash)
            self.intent = result.event
            return result
        async def finish(self, intent, **args):
            return await f['store'].finish_source_operation(f['claim'].submission_id,intent.id,**args)
    journal, authority = Journal(), Authority()
    for method, stage in [('post_hovedskjema','main'),('post_underskjema','sub'),('confirm','confirm')]:
        original = getattr(authority,method)
        async def verify(*, _original=original, _stage=stage, **args):
            with psycopg.connect(DATABASE_URL,options='-c lock_timeout=250') as db:
                bind_fixture_owner(db,f)
                # A second connection must acquire the company guard now, and
                # see the committed intent before any synthetic provider effect.
                db.execute('select public.company_archive_lock_company_v1(%s)',(f['seed']['company'],))
                row = db.execute('select operation_state,idempotency_key from shareholder_register_filing.production_filing_events where id=%s',
                    (journal.intent.id,)).fetchone()
                assert row == ('prepared', UUID(args['idempotency_key']))
            response = await _original(**args)
            if lost_stage == _stage: raise rf.Rf1086AuthorityError('SYNTHETIC_LOST_RESPONSE')
            return response
        setattr(authority,method,verify)
    async def run():
        archive = await rf.create_rf1086_preparation_service(f['store']).archive_source(query)
        payload = rf.assess_rf1086_source_dispatch(archive,query=query,submission_id=f['claim'].submission_id).payload
        async def dispatch():
            return await rf.execute_rf1086_source_dispatch(payload,journal=journal,
                read_journal=f['store'].operation_journal(f['claim'].submission_id.value),authority_client=authority)
        if lost_stage:
            with pytest.raises(rf.Rf1086UnknownProductionOutcomeError): await dispatch()
        else:
            await dispatch()
        before = list(authority.calls)
        if lost_stage:
            with pytest.raises(rf.Rf1086UnknownProductionOutcomeError): await dispatch()
        else:
            await dispatch()
        assert authority.calls == before
        archive = await rf.create_rf1086_preparation_service(f['store']).archive_source(query)
        assert rf.assess_rf1086_source_dispatch(archive,query=query,submission_id=f['claim'].submission_id).disposition == (
            'recovery_required' if lost_stage else 'confirmed')
    asyncio.run(run())


@pytest.fixture
def dispatch_billing_access(backend_url):
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict
    username = conninfo_to_dict(backend_url)['user']
    assert username.startswith('rf_test_')
    with psycopg.connect(DATABASE_URL) as db:
        db.execute(sql.SQL('grant billing_executor to {} with inherit false,set true').format(sql.Identifier(username)))
    try:
        yield
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute(sql.SQL('revoke billing_executor from {}').format(sql.Identifier(username)))


@pytest.mark.parametrize('change', [None, 'original', 'annual-during-binding'])
def test_capture_approval_claim_and_dispatch_with_real_retained_originals(annual_fixture, dispatch_billing_access, change):
    from talli_backend.adapters.supabase_billing import SupabaseBillingSession
    from talli_backend.adapters.supabase_documents import SupabaseDocumentsPersistence
    from talli_backend.application.shareholder_register_source_workflow import ShareholderRegisterSourceWorkflow
    from talli_backend.application.shareholder_register_source_approval import ShareholderRegisterSourceApprovalWorkflow
    from talli_backend.application.shareholder_register_source_dispatch import ShareholderRegisterSourceDispatchWorkflow
    from talli_backend.modules.documents.public import DocumentsError, StoredDocumentObject
    from talli_backend.modules.documents.service import DocumentsService
    from talli_backend.shared.kernel import CorrelationId, IdempotencyKey
    from test_rf1086_year_source_database import seed_documents
    from test_shareholder_register_filing_production import Authority
    f = annual_fixture
    store = f['store']
    with psycopg.connect(DATABASE_URL) as db:
        for migration in (INTENT_MIGRATION, MIGRATION): db.execute((ROOT/'supabase/migrations'/migration).read_text())
    content = b'%PDF-1.7\nSynthetic complete RF source original\n'
    class Storage:
        data = content
        async def read_object(self, **args): return StoredDocumentObject(self.data,'application/pdf')
    storage = Storage()
    async def refresh_roles():
        async with store.source_admission(query(f)) as scope:
            await scope.company_identity()
        return {f['source'].company_id: 'owner'}
    documents = DocumentsService(SupabaseDocumentsPersistence(store._configuration.database_url,store._verified,
        {f['source'].company_id:'owner'}, role_refresher=refresh_roles),storage)
    class Sessions:
        async def session(self, token): return store
    class DocumentSessions:
        async def session(self, token): return documents
    class Company:
        async def company_record(self, token, *, company_id):
            async with store.source_admission(query(f)) as scope:
                identity = await scope.company_identity()
            company = identity.company
            return SimpleNamespace(company=SimpleNamespace(id=company_id,role='owner',entity_type='AS',
                org_number=company.org_number,name=company.name,address=company.address,
                postal_code=company.postal_code,city=company.city,
                identity_confirmed_at=identity.identity_confirmed_at,identity_locked_at=identity.identity_locked_at))
    class Governance:
        async def read_reporting_year_evidence(self, token, *, company_id, income_year, correlation_id):
            async with store.source_admission(query(f)) as scope:
                return await scope.governance_evidence(correlation_id)
    store._company_access = Company()
    store._billing = SupabaseBillingSession(store._configuration.database_url,store._verified)
    store.require_configuration = lambda: None  # Test binding below never requests credentials.
    authority = Authority()
    discarded = []
    async def binding(*args):
        if change == 'annual-during-binding': set_answers(f,has_unpaid_items=True)
        return SimpleNamespace(authority=authority,discard=lambda:discarded.append(True))
    store.bind_mutation_authority = binding
    async def run():
        correlation = CorrelationId('complete-source-dispatch')
        company = (await store._company_access.company_record('synthetic',company_id=str(f['source'].company_id))).company
        expected = replace(f['command'].documents[0],content_sha256=sha256(content).hexdigest(),
            content_version_sha256=sha256(content).hexdigest(),byte_length=len(content))
        originals = seed_documents(f['seed'],store,(expected,))
        document_id = originals[0].document_id
        current = f['source']
        command = replace(f['command'],case=replace(f['command'].case,company=replace(f['command'].case.company,
            org_number=company.org_number,name=company.name,address=company.address,postal_code=company.postal_code,city=company.city)),
            documents=originals,opening_document_ids=(document_id,),closing_document_ids=(document_id,),paid_in_document_ids=(document_id,),
            supersedes_source_id=current.source_id,supersedes_source_sha256=current.source_sha256,correction_reason='Use verified original bytes and current legal identity')
        source_workflow = ShareholderRegisterSourceWorkflow(Sessions(),store._company_access,DocumentSessions(),Governance())
        f['source'] = await source_workflow.capture_year_source('synthetic',command,
            idempotency_key=IdempotencyKey(str(uuid4())),correlation_id=correlation)
        f['preview'] = await source_workflow.generate_source_preview('synthetic',company_id=f['source'].company_id,
            income_year=f['source'].income_year,source_id=f['source'].source_id,correlation_id=correlation)
        approvals = ShareholderRegisterSourceApprovalWorkflow(Sessions(),DocumentSessions())
        args = dict(company_id=f['source'].company_id,income_year=f['source'].income_year,
            preview_id=f['preview'].preview_id,entitlement_id=str(f['entitlement']),correlation_id=correlation)
        review = await approvals.read_review('synthetic',**args)
        assert review.can_approve, review.blockers
        approved = await approvals.approve('synthetic',**args,review_sha256=review.review_sha256,
            acknowledged_warning_codes=review.warning_codes,real_filing_confirmed=True)
        retained = await store.read_source_claim_approval(rf.ApprovalId(approved.record_id))
        if change == 'original': storage.data = b'changed after approval'
        workflow = ShareholderRegisterSourceDispatchWorkflow(Sessions(),DocumentSessions())
        async def send():
            return await workflow.send('synthetic',approval_id=rf.ApprovalId(approved.record_id),
                manifest_sha256=retained.approval.manifest_hash,correlation_id=correlation)
        if change:
            with pytest.raises((DocumentsError,rf.Rf1086ProductionError,rf.ShareholderRegisterFilingError)): await send()
            assert not authority.calls
            return
        result = await send()
        assert discarded == [True]
        before = list(authority.calls)
        storage.data = b'current mutable object no longer needed for confirmed replay'
        assert await send() == result
        assert authority.calls == before and discarded == [True]
        archive_query = rf.Rf1086ArchiveQuery(f['source'].company_id,f['source'].income_year,store.actor_id)
        archive = await rf.create_rf1086_preparation_service(store).archive_source(archive_query)
        assert rf.assess_rf1086_source_dispatch(archive,query=archive_query,submission_id=rf.SubmissionId(result.submission_id)).disposition == 'confirmed'
    asyncio.run(run())


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
            assert not db.execute("select has_function_privilege(%s,'shareholder_register_filing.prepare_source_operation_v2(uuid,text,text,text,uuid,uuid,text,uuid,text,text)','execute')", (role,)).fetchone()[0]
        assert db.execute("select has_function_privilege('shareholder_register_filing_executor','shareholder_register_filing.prepare_source_operation_v2(uuid,text,text,text,uuid,uuid,text,uuid,text,text)','execute')").fetchone()[0]
        assert not db.execute("select has_function_privilege('shareholder_register_filing_executor','shareholder_register_filing.prepare_source_operation_v1(uuid,text,text,text,uuid,uuid,text,text)','execute')").fetchone()[0]
