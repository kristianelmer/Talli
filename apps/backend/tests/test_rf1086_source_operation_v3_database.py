"""Full-schema closed intent SQL and real producers; synthetic Auth/original fixture.

No provider, hosted grant, genuine data or independent-project proof is inferred.
"""
import asyncio
from dataclasses import replace
from hashlib import sha256
import json
import sys
from uuid import uuid4

import psycopg
import pytest

from talli_backend.application.shareholder_register_source_dispatch_v3 import ShareholderRegisterSourceDispatchV3
from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_source_claim_v3_database import (
    state, claim_access, prepare_claim, claim, rows, answers, DATABASE_URL, ROOT,
    admitted, closed_source_role, withdrawal_fixture_role, approval_login, backend_url,
    fixture_roles, approved_release, approval_seed_access, rf_fixture_admin_access,
    documents_authority, amendment_fixture_authority, capture_login, prepare_state,
)
from test_rf1086_retained_readiness_observation_v2 import close_fresh_rendering

pytestmark = pytest.mark.authority_database
MIGRATION = '20261011045100_rf1086_closed_source_operation_v3.sql'
CONTRACT = 'shareholder_register_filing.prepare_source_operation_v3(uuid,text,text,text,uuid,uuid,text,uuid,text,text)'
LEGACY = ('shareholder_register_filing.prepare_source_operation_v1(uuid,text,text,text,uuid,uuid,text,text)',
    'shareholder_register_filing.prepare_source_operation_v2(uuid,text,text,text,uuid,uuid,text,uuid,text,text)')


async def drain_race_waiter(waiter, restore_owner, *, consumed=False, primary_failure=None):
    """Retrieve every owned task outcome; restore membership before reporting failure."""
    failures = []
    try:
        if waiter is not None:
            if not waiter.done():
                waiter.cancel()
            outcome, = await asyncio.gather(waiter, return_exceptions=True)
            if not consumed and isinstance(outcome, BaseException) and not isinstance(outcome, asyncio.CancelledError):
                failures.append(outcome)
    except BaseException as failure:
        failures.append(failure)
    finally:
        if restore_owner is not None:
            try:
                await restore_owner()
            except BaseException as failure:
                failures.append(failure)
    if failures:
        if primary_failure is not None:
            failures.insert(0, primary_failure)
        raise BaseExceptionGroup('RF race fixture cleanup failed', failures)


@pytest.fixture
def operation_access(claim_access):
    with psycopg.connect(DATABASE_URL) as db:
        before = db.execute('select oid,proacl::text from pg_proc where oid=%s::regprocedure', (CONTRACT,)).fetchall()
        added = not db.execute("select has_function_privilege('shareholder_register_filing_executor',%s,'EXECUTE')", (CONTRACT,)).fetchone()[0]
        if added:
            db.execute('set local role shareholder_register_filing_store_owner')
            db.execute('grant execute on function '+CONTRACT+' to shareholder_register_filing_executor')
    try:
        yield claim_access
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            if added:
                db.execute('set local role shareholder_register_filing_store_owner')
                db.execute('revoke all on function '+CONTRACT+' from shareholder_register_filing_executor')
            assert db.execute('select oid,proacl::text from pg_proc where oid=%s::regprocedure', (CONTRACT,)).fetchall() == before


def operation_state(state):
    prepare_claim(state)
    state.operation_claim = claim(state).claim
    state.dispatch = ShareholderRegisterSourceDispatchV3(state.workflow._sessions, state.workflow._documents)
    return state


async def prepare_main(state):
    owned = state.operation_claim
    retained = await state.store.read_source_claim_approval_v3(owned.approval_id)
    prepared = await state.dispatch.prepare_main_intent_v3('synthetic-token', state.store,
        claim=owned, retained=retained, correlation_id=state.arguments['correlation_id'])
    connection = await state.store.read_connection(str(state.request), str(owned.company_id))
    async with state.store.source_operation_recovery_v3(owned) as historical:
        async with historical.fresh_operation_admission_v3() as fresh:
            await state.dispatch.validate_held_main_intent_v3(prepared, fresh, state.arguments['correlation_id'])
            result = await fresh.prepare_main_operation_v3(prepared, idempotency_key=str(uuid4()),
                expected_event_id=None, connection=connection, correlation_id=state.arguments['correlation_id'])
    return result


async def operation_rows(state):
    return await state.store._rows('select * from shareholder_register_filing.production_filing_events '
        'where submission_id=%s order by created_at,id', (state.operation_claim.submission_id.value,))


@pytest.mark.parametrize('kind', ['cash_issue', 'loss_covering_reduction'])
@pytest.mark.parametrize('depth', [0, 1, 2])
def test_actual_v3_main_child_confirm_use_one_guarded_scope_and_complete_owned_producers(admitted,
        closed_source_role, withdrawal_fixture_role, operation_access, backend_url, fixture_roles,
        approved_release, kind, depth, monkeypatch):
    state = operation_state(prepare_state(admitted, closed_source_role, withdrawal_fixture_role,
        operation_access, backend_url, kind, depth))
    close_fresh_rendering(monkeypatch)
    saved_source = rf.serialize_rf1086_year_source_v2(state.source)
    async def run():
        first = await prepare_main(state)
        assert first.newly_prepared and first.event.operation_state == 'prepared'
        await state.store.finish_source_operation(state.operation_claim.submission_id, first.event.id,
            state='succeeded', reference='actual-v3-main', failure=None)
        retained = await state.store.read_source_claim_approval_v3(state.operation_claim.approval_id)
        connection = await state.store.read_connection(str(state.request), str(state.source.company_id))
        # Main originals are not read again for child/confirm.
        state.byte_reads.clear()
        for document in retained.approval.manifest['documentHashes'][1:]:
            async with state.store.source_operation_recovery_v3(state.operation_claim) as historical:
                async with historical.fresh_operation_admission_v3() as fresh:
                    item = await fresh.prepare_child_operation_v3(state.operation_claim,
                        document_name=document['name'], body_sha256=document['sha256'],
                        idempotency_key=str(uuid4()), expected_event_id=None, connection=connection,
                        correlation_id=state.arguments['correlation_id'])
            assert item.newly_prepared
            await state.store.finish_source_operation(state.operation_claim.submission_id, item.event.id,
                state='succeeded', reference='actual-v3-child', failure=None)
        count = len(retained.approval.manifest['documentHashes'])-1
        async with state.store.source_operation_recovery_v3(state.operation_claim) as historical:
            async with historical.fresh_operation_admission_v3() as fresh:
                item = await fresh.prepare_confirm_operation_v3(state.operation_claim,
                    body_sha256=sha256(f'actual-v3-main:{count}'.encode()).hexdigest(),
                    idempotency_key=str(uuid4()), expected_event_id=None, connection=connection,
                    correlation_id=state.arguments['correlation_id'])
        await state.store.finish_source_operation(state.operation_claim.submission_id, item.event.id,
            state='succeeded', reference=json.dumps({'dialogId':str(uuid4()),'forsendelseId':str(uuid4())},
                separators=(',', ':')), failure=None)
        assert not state.byte_reads
        async with state.store.source_operation_recovery_v3(state.operation_claim) as historical:
            assert (await historical.read_operation_recovery()).assessment.disposition == 'confirmed'
    asyncio.run(run())
    assert rf.serialize_rf1086_year_source_v2(state.source) == saved_source


@pytest.mark.parametrize('change', ['annual', 'mfa'])
def test_actual_pending_main_survives_current_refusal_without_new_intent_or_original_io(state,
        operation_access, change):
    operation_state(state)
    first = asyncio.run(prepare_main(state))
    if change == 'annual': answers(state, bank_balance_confirmed=False)
    else:
        claims = json.loads(state.store._verified.claims_json)
        claims['amr'][0]['timestamp'] -= 901
        state.store._verified = replace(state.store._verified, claims_json=json.dumps(claims))
    before = asyncio.run(operation_rows(state))
    state.byte_reads.clear()
    with pytest.raises(rf.Rf1086UnknownProductionOutcomeError):
        asyncio.run(state.dispatch.send('synthetic-token', **state.claim_arguments))
    assert asyncio.run(operation_rows(state)) == before and not state.byte_reads
    assert first.event.id in {str(item['id']) for item in before}


def test_actual_closed_v3_migration_reapply_and_rollback_preserve_legacy_catalogs_and_no_runtime_grants():
    with psycopg.connect(DATABASE_URL, autocommit=True) as db:
        def catalog(contracts):
            return db.execute('select oid,to_jsonb(p) from pg_proc p where oid=any(%s::regprocedure[]) order by oid',
                (list(contracts),)).fetchall()
        old, new = catalog(LEGACY), catalog((CONTRACT,))
        edges = db.execute('select * from pg_auth_members order by roleid,member,grantor').fetchall()
        for folder in ('migrations', 'rollback', 'migrations'):
            db.execute((ROOT/'supabase'/folder/MIGRATION).read_text())
            assert catalog(LEGACY) == old and catalog((CONTRACT,)) == new
            assert db.execute('select * from pg_auth_members order by roleid,member,grantor').fetchall() == edges
            for role in ('anon','authenticated','service_role','shareholder_register_filing_executor'):
                assert not db.execute('select has_function_privilege(%s,%s,\'EXECUTE\')', (role, CONTRACT)).fetchone()[0]


@pytest.mark.parametrize('drift', ['old-body', 'old-runtime-acl', 'new-body', 'new-search-path'])
def test_actual_version_copy_rejects_definition_drift_without_mutating_legacy_or_journal(drift):
    with psycopg.connect(DATABASE_URL) as db:
        def catalog():
            return db.execute('select oid,to_jsonb(p) from pg_proc p where oid=any(%s::regprocedure[]) order by oid',
                (list(LEGACY)+( [CONTRACT]),)).fetchall()
        before = catalog()
        with db.transaction(force_rollback=True):
            routine = LEGACY[0] if drift.startswith('old-') else CONTRACT
            if drift.endswith('body'):
                definition, body = db.execute('select pg_get_functiondef(%s::regprocedure),prosrc from pg_proc '
                    'where oid=%s::regprocedure', (routine,routine)).fetchone()
                db.execute(definition.replace(body, body+'\n-- controlled closed-intent drift\n'))
            elif drift == 'old-runtime-acl':
                db.execute('grant execute on function '+routine+' to authenticated')
            else:
                db.execute('alter function '+routine+' set search_path=public')
            script = (ROOT/'supabase/migrations'/MIGRATION).read_text()
            script = script.replace('begin;', '', 1).rsplit('commit;', 1)[0]
            with pytest.raises(psycopg.errors.RaiseException) as caught:
                with db.transaction(): db.execute(script)
            assert caught.value.diag.message_primary == 'rf1086_operation_v3_definition_drift'
        assert catalog() == before


async def next_saved_operation(state, operation):
    first=await prepare_main(state)
    await state.store.finish_source_operation(state.operation_claim.submission_id,first.event.id,
        state='succeeded',reference='actual-v3-main',failure=None)
    retained=await state.store.read_source_claim_approval_v3(state.operation_claim.approval_id)
    connection=await state.store.read_connection(str(state.request),str(state.source.company_id))
    documents=retained.approval.manifest['documentHashes'][1:]
    if operation=='confirm':
        for document in documents:
            async with state.store.source_operation_recovery_v3(state.operation_claim) as historical:
                async with historical.fresh_operation_admission_v3() as fresh:
                    item=await fresh.prepare_child_operation_v3(state.operation_claim,document_name=document['name'],
                        body_sha256=document['sha256'],idempotency_key=str(uuid4()),expected_event_id=None,
                        connection=connection,correlation_id=state.arguments['correlation_id'])
            await state.store.finish_source_operation(state.operation_claim.submission_id,item.event.id,
                state='succeeded',reference='actual-v3-child',failure=None)
    return connection,documents[0] if operation=='child' else sha256(f'actual-v3-main:{len(documents)}'.encode()).hexdigest()


async def prepare_saved_operation(state,fresh,connection,body,operation):
    args=dict(idempotency_key=str(uuid4()),expected_event_id=None,connection=connection,
        correlation_id=state.arguments['correlation_id'])
    if operation=='child':
        return await fresh.prepare_child_operation_v3(state.operation_claim,
            document_name=body['name'],body_sha256=body['sha256'],**args)
    return await fresh.prepare_confirm_operation_v3(state.operation_claim,body_sha256=body,**args)


@pytest.fixture
def proof_corruption_authority(operation_access):
    """Only the disposable owned login temporarily borrows owner SET for corruption.

    The operation itself runs as RF executor after genuine producer invocation.
    Runtime grants and exact previous role-edge options are restored afterward.
    """
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict
    principal=conninfo_to_dict(operation_access)['user']
    owner='shareholder_register_filing_store_owner'
    with psycopg.connect(DATABASE_URL) as db:
        before=db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members '
            'where roleid=%s::regrole and member=%s::regrole order by grantor',(owner,principal)).fetchall()
        prior=db.execute('select admin_option,inherit_option,set_option from pg_auth_members '
            'where roleid=%s::regrole and member=%s::regrole and grantor=current_user::regrole',(owner,principal)).fetchone()
        db.execute(sql.SQL('grant {} to {} with inherit false,set true granted by current_user').format(
            sql.Identifier(owner),sql.Identifier(principal)))
    try:yield
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            if prior is None:
                db.execute(sql.SQL('revoke {} from {} granted by current_user').format(sql.Identifier(owner),sql.Identifier(principal)))
            else:
                # Update the existing membership in place; revoke/regrant would
                # replace its catalog OID even when key/options match.
                db.execute(sql.SQL('grant {} to {} with admin {},inherit {},set {} granted by current_user').format(
                    sql.Identifier(owner),sql.Identifier(principal),*(sql.SQL(str(value).lower()) for value in prior)))
            assert db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members '
                'where roleid=%s::regrole and member=%s::regrole order by grantor',(owner,principal)).fetchall()==before


@pytest.mark.parametrize('operation',['child','confirm'])
@pytest.mark.parametrize('fault',['missing','company','year','source-sha','actor','transaction','body','physical-connection'])
def test_actual_child_confirm_receiver_refuses_missing_or_rebound_genuine_proof_before_new_intent(state,
        operation_access,proof_corruption_authority,monkeypatch,operation,fault):
    from talli_backend.adapters.postgres_shareholder_register_filing import _SourceAdmission
    from rf1086_year_source_v2_database_fixture import PROOFS
    operation_state(state)
    connection,body=asyncio.run(next_saved_operation(state,operation))
    before=asyncio.run(operation_rows(state));saved=rows(state);source=rf.serialize_rf1086_year_source_v2(state.source)
    producer=_SourceAdmission.prepare_source_governance_proof
    async def corrupted(held,actual_source):
        assert actual_source==state.source
        await producer(held,actual_source)
        held._require_active()
        await held._connection.execute('set local role shareholder_register_filing_store_owner')
        if fault=='missing': await held._connection.execute('delete from '+PROOFS)
        elif fault=='company': await held._connection.execute("update "+PROOFS+" set company_id='00000000-0000-0000-0000-000000000001'::uuid")
        elif fault=='year': await held._connection.execute('update '+PROOFS+' set income_year=%s',(int(state.source.income_year)-1,))
        elif fault=='source-sha': await held._connection.execute('update '+PROOFS+" set source_sha256=repeat('f',64)")
        elif fault=='actor': await held._connection.execute("update "+PROOFS+" set actor_id='00000000-0000-0000-0000-000000000001'::uuid")
        elif fault=='transaction': await held._connection.execute('update '+PROOFS+' set transaction_id=(transaction_id::text::numeric+1)::text::xid8')
        elif fault=='body': await held._connection.execute('update '+PROOFS+" set proof=proof||'{\"verified\":true}'::jsonb")
        await held._connection.execute('set local role shareholder_register_filing_executor')
    async def no_local_proof(held,actual_source):
        held._require_active();assert actual_source==state.source
        assert (await (await held._connection.execute('select to_regclass(%s) as relation',(PROOFS,))).fetchone())['relation'] is None
    async def attempt():
        if fault=='physical-connection':
            async with state.store.source_operation_recovery_v3(state.operation_claim) as recovery:
                async with recovery.fresh_operation_admission_v3() as other:
                    await producer(other._held,state.source)
                    first_pid=(await (await other._held._connection.execute('select pg_backend_pid() as pid')).fetchone())['pid']
        async with state.store.source_operation_recovery_v3(state.operation_claim) as recovery:
            async with recovery.fresh_operation_admission_v3() as fresh:
                if fault=='physical-connection':
                    second_pid=(await (await fresh._held._connection.execute('select pg_backend_pid() as pid')).fetchone())['pid']
                    assert first_pid!=second_pid
                await prepare_saved_operation(state,fresh,connection,body,operation)
    monkeypatch.setattr(_SourceAdmission,'prepare_source_governance_proof',
        no_local_proof if fault=='physical-connection' else corrupted)
    with pytest.raises(psycopg.errors.RaiseException) as refusal:
        asyncio.run(attempt())
    assert refusal.value.sqlstate == 'P0001'
    assert refusal.value.diag.message_primary == 'rf1086_source_governance_evidence_changed'
    assert asyncio.run(operation_rows(state))==before and rows(state)==saved
    assert rf.serialize_rf1086_year_source_v2(state.source)==source


@pytest.mark.parametrize('operation',['child','confirm'])
@pytest.mark.parametrize('change',['amendment','withdrawal'])
def test_actual_saved_child_confirm_rechecks_current_amendment_and_withdrawal_producer(state,operation_access,
        withdrawal_fixture_role,operation,change):
    from rf1086_year_source_v2_database_fixture import amend,withdrawal
    operation_state(state);connection,body=asyncio.run(next_saved_operation(state,operation))
    before=asyncio.run(operation_rows(state));saved=rows(state);source=rf.serialize_rf1086_year_source_v2(state.source)
    if change=='amendment':amend(state.item)
    else:withdrawal(state.item['seed'],withdrawal_fixture_role,state.item['replacement'])
    state.byte_reads.clear()
    async def attempt():
        async with state.store.source_operation_recovery_v3(state.operation_claim) as recovery:
            async with recovery.fresh_operation_admission_v3() as fresh:
                await prepare_saved_operation(state,fresh,connection,body,operation)
    with pytest.raises(psycopg.errors.RaiseException) as refusal:
        asyncio.run(attempt())
    assert refusal.value.sqlstate == 'P0001'
    assert refusal.value.diag.message_primary == (
        'rf1086_source_governance_evidence_changed' if change == 'amendment'
        else 'rf1086_source_register_observation_stale')
    assert asyncio.run(operation_rows(state))==before and rows(state)==saved and not state.byte_reads
    assert rf.serialize_rf1086_year_source_v2(state.source)==source


@pytest.mark.parametrize('failure',['late-error','cancel'])
def test_actual_new_main_intent_rolls_back_with_scope_after_late_error_or_cancellation(state,operation_access,failure):
    operation_state(state);owned=state.operation_claim
    async def attempt():
        retained=await state.store.read_source_claim_approval_v3(owned.approval_id)
        prepared=await state.dispatch.prepare_main_intent_v3('synthetic-token',state.store,
            claim=owned,retained=retained,correlation_id=state.arguments['correlation_id'])
        connection=await state.store.read_connection(str(state.request),str(owned.company_id))
        async with state.store.source_operation_recovery_v3(owned) as recovery:
            async with recovery.fresh_operation_admission_v3() as fresh:
                await state.dispatch.validate_held_main_intent_v3(prepared,fresh,state.arguments['correlation_id'])
                result=await fresh.prepare_main_operation_v3(prepared,idempotency_key=str(uuid4()),
                    expected_event_id=None,connection=connection,correlation_id=state.arguments['correlation_id'])
                assert result.newly_prepared
                if failure=='cancel':raise asyncio.CancelledError()
                raise RuntimeError('controlled after-write failure')
    before=asyncio.run(operation_rows(state));saved=rows(state)
    with pytest.raises(asyncio.CancelledError if failure=='cancel' else RuntimeError):asyncio.run(attempt())
    assert asyncio.run(operation_rows(state))==before and rows(state)==saved


def test_actual_deferred_commit_failure_returns_no_main_preparation_and_rolls_back_intent(state,operation_access):
    from psycopg import sql
    operation_state(state)
    function='rf_intent_commit_refusal_'+uuid4().hex
    trigger='rf_intent_commit_refusal_'+uuid4().hex
    table='shareholder_register_filing.production_filing_events'
    before=asyncio.run(operation_rows(state));saved=rows(state)
    with psycopg.connect(DATABASE_URL) as db:
        db.execute(sql.SQL("create function shareholder_register_filing.{}() returns trigger language plpgsql as "
            "$body$ begin if new.submission_id={}::uuid then raise exception 'controlled_rf_v3_commit_failure'; end if; return new; end; $body$").format(
                sql.Identifier(function),sql.Literal(state.operation_claim.submission_id.value)))
        db.execute(sql.SQL('revoke all on function shareholder_register_filing.{}() from public').format(sql.Identifier(function)))
        db.execute(sql.SQL('create constraint trigger {} after insert on '+table+
            ' deferrable initially deferred for each row execute function shareholder_register_filing.{}()').format(
                sql.Identifier(trigger),sql.Identifier(function)))
    try:
        with pytest.raises(psycopg.errors.RaiseException) as refusal:
            asyncio.run(prepare_main(state))
        assert refusal.value.sqlstate == 'P0001'
        assert refusal.value.diag.message_primary == 'controlled_rf_v3_commit_failure'
        assert asyncio.run(operation_rows(state))==before and rows(state)==saved
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute(sql.SQL('drop trigger {} on '+table).format(sql.Identifier(trigger)))
            db.execute(sql.SQL('drop function shareholder_register_filing.{}()').format(sql.Identifier(function)))


@pytest.mark.parametrize('fault',['closed-parent','foreign-physical-connection'])
def test_actual_child_fixed_port_rejects_lost_held_scope_before_intent_sql(state,operation_access,fault):
    operation_state(state);connection,body=asyncio.run(next_saved_operation(state,'child'))
    before=asyncio.run(operation_rows(state));saved=rows(state)
    async def attempt():
        # An unrelated live connection is acquired before company/year guards;
        # it provides no permission to replace the operation's bound connection.
        async with state.store._transaction() as other:
            async with state.store.source_operation_recovery_v3(state.operation_claim) as recovery:
                async with recovery.fresh_operation_admission_v3() as fresh:
                    original=fresh._held._connection
                    if fault=='closed-parent':recovery.close()
                    else:fresh._held._connection=other
                    try:await prepare_saved_operation(state,fresh,connection,body,'child')
                    finally:fresh._held._connection=original
    with pytest.raises(rf.ShareholderRegisterFilingError):asyncio.run(attempt())
    assert asyncio.run(operation_rows(state))==before and rows(state)==saved


@pytest.mark.parametrize('race',['prepared-before-current-denial','original-owner-revoked'])
def test_actual_postwait_history_wins_before_current_policy_and_revoked_original_owner_still_denies(state,
        operation_access,race):
    from contextlib import asynccontextmanager
    operation_state(state);owned=state.operation_claim
    before=asyncio.run(operation_rows(state));saved=rows(state)
    production_before=asyncio.run(state.store._rows('select * from shareholder_register_filing.production_filing_submissions where id=%s',
        (owned.submission_id.value,)))
    transaction=state.store._transaction
    waiting={'enabled':False,'pids':[],'holder_pid':None}
    @asynccontextmanager
    async def observable(**options):
        async with transaction(**options) as db:
            await db.execute("set local lock_timeout='15s';set local statement_timeout='20s'")
            if waiting['enabled']:waiting['pids'].append(db.info.backend_pid)
            yield db
    state.store._transaction=observable
    def any_waiting():
        if not waiting['pids']:return False
        with psycopg.connect(DATABASE_URL,connect_timeout=5,options='-c statement_timeout=10000') as db:
            return db.execute("select exists(select 1 from pg_stat_activity where pid=any(%s) and wait_event='advisory' and %s=any(pg_blocking_pids(pid)))",
                (waiting['pids'],waiting['holder_pid'])).fetchone()[0]
    def membership(role):
        # Explicit disposable admin revocation oracle, as existing post-wait
        # claim fixtures use. No ordinary role or provider capability is given.
        with psycopg.connect(DATABASE_URL,connect_timeout=5,options='-c lock_timeout=5000 -c statement_timeout=10000') as db:
            changed=db.execute('update public.company_memberships set role=%s where company_id=%s and user_id=%s returning user_id',
                (role,state.item['seed']['company'],state.item['seed']['owner'])).fetchall()
            assert len(changed)==1
            assert db.execute('select role from public.company_memberships where company_id=%s and user_id=%s',
                (state.item['seed']['company'],state.item['seed']['owner'])).fetchone() == (role,)
    @asynccontextmanager
    async def race_holder():
        if race=='prepared-before-current-denial':
            async with state.store.source_operation_recovery_v3(owned) as holder:
                waiting['holder_pid']=holder._connection.info.backend_pid
                yield holder
        else:
            # The real membership trigger uses the same company guard. Revoke
            # on this disposable admin holder so it reenters its own lock;
            # an independent UPDATE awaited here cannot commit before release.
            async with await psycopg.AsyncConnection.connect(DATABASE_URL,connect_timeout=5,
                    options='-c lock_timeout=5000 -c statement_timeout=10000') as holder:
                await holder.execute('select public.company_archive_lock_company_v1(%s::uuid)',
                    (str(owned.company_id),))
                waiting['holder_pid']=holder.info.backend_pid
                yield holder
    async def run():
        retained=await state.store.read_source_claim_approval_v3(owned.approval_id)
        prepared=await state.dispatch.prepare_main_intent_v3('synthetic-token',state.store,
            claim=owned,retained=retained,correlation_id=state.arguments['correlation_id'])
        connection=await state.store.read_connection(str(state.request),str(owned.company_id))
        waiter=None
        consumed=False
        try:
            async with race_holder() as holder:
                if race=='prepared-before-current-denial':
                    async with holder.fresh_operation_admission_v3() as fresh:
                        await state.dispatch.validate_held_main_intent_v3(prepared,fresh,state.arguments['correlation_id'])
                        inserted=await fresh.prepare_main_operation_v3(prepared,idempotency_key=str(uuid4()),
                            expected_event_id=None,connection=connection,correlation_id=state.arguments['correlation_id'])
                        assert inserted.newly_prepared
                # The waiter starts with expired MFA. Historical recovery must
                # still observe the concurrently committed prepared intent.
                claims=json.loads(state.store._verified.claims_json)
                claims['amr'][0]['timestamp']-=901
                state.store._verified=replace(state.store._verified,claims_json=json.dumps(claims))
                state.byte_reads.clear();waiting['enabled']=True
                waiter=asyncio.create_task(state.dispatch.send('synthetic-token',**state.claim_arguments))
                deadline=asyncio.get_running_loop().time()+10
                while asyncio.get_running_loop().time()<deadline:
                    if await asyncio.to_thread(any_waiting):break
                    await asyncio.sleep(.02)
                else:raise AssertionError('no actual operation company/year advisory waiter')
                if race=='original-owner-revoked':
                    assert not waiter.done()
                    changed=await (await holder.execute(
                        'update public.company_memberships set role=%s where company_id=%s and user_id=%s returning user_id',
                        ('reviewer',state.item['seed']['company'],state.item['seed']['owner']))).fetchall()
                    assert len(changed)==1
                    assert await (await holder.execute(
                        'select role from public.company_memberships where company_id=%s and user_id=%s',
                        (state.item['seed']['company'],state.item['seed']['owner']))).fetchone() == ('reviewer',)
                    assert not waiter.done()
            with pytest.raises(rf.Rf1086UnknownProductionOutcomeError if race=='prepared-before-current-denial'
                    else psycopg.errors.RaiseException) as refusal:
                await asyncio.wait_for(waiter,10)
            consumed=True
            if race=='original-owner-revoked':
                assert refusal.value.sqlstate == 'P0001'
                assert refusal.value.diag.message_primary == 'rf1086_forbidden'
            assert not state.byte_reads
        finally:
            waiting['enabled']=False
            async def restore_owner():
                await asyncio.to_thread(membership,'owner')
            await drain_race_waiter(waiter, restore_owner if race=='original-owner-revoked' else None,
                consumed=consumed, primary_failure=sys.exception())
    asyncio.run(run())
    after=asyncio.run(operation_rows(state))
    if race=='prepared-before-current-denial':
        assert len(after)==len(before)+1 and after[-1]['operation_state']=='prepared'
    else:assert after==before
    # A committed preparation updates its bookkeeping clock only; no provider
    # status/reference/outcome changes and exact claim/head records remain.
    actual=rows(state)
    if race=='prepared-before-current-denial':
        production_after=asyncio.run(state.store._rows('select * from shareholder_register_filing.production_filing_submissions where id=%s',
            (owned.submission_id.value,)))
        assert actual[0]==saved[0] and actual[2]==saved[2]
        assert [{k:v for k,v in row.items() if k!='updated_at'} for row in production_after]==[
            {k:v for k,v in row.items() if k!='updated_at'} for row in production_before]
    else:assert actual==saved


async def complete_claim_with_synthetic_provider_results(state):
    """Actual committed intent/finish APIs; provider responses are explicit doubles."""
    first=await prepare_main(state)
    main=str(uuid4())
    await state.store.finish_source_operation(state.operation_claim.submission_id,first.event.id,
        state='succeeded',reference=main,failure=None)
    retained=await state.store.read_source_claim_approval_v3(state.operation_claim.approval_id)
    connection=await state.store.read_connection(str(state.request),str(state.source.company_id))
    for document in retained.approval.manifest['documentHashes'][1:]:
        async with state.store.source_operation_recovery_v3(state.operation_claim) as recovery:
            async with recovery.fresh_operation_admission_v3() as fresh:
                result=await fresh.prepare_child_operation_v3(state.operation_claim,
                    document_name=document['name'],body_sha256=document['sha256'],idempotency_key=str(uuid4()),
                    expected_event_id=None,connection=connection,correlation_id=state.arguments['correlation_id'])
        assert result.newly_prepared
        await state.store.finish_source_operation(state.operation_claim.submission_id,result.event.id,
            state='succeeded',reference=str(uuid4()),failure=None)
    count=len(retained.approval.manifest['documentHashes'])-1
    async with state.store.source_operation_recovery_v3(state.operation_claim) as recovery:
        async with recovery.fresh_operation_admission_v3() as fresh:
            result=await fresh.prepare_confirm_operation_v3(state.operation_claim,
                body_sha256=sha256(f'{main}:{count}'.encode()).hexdigest(),idempotency_key=str(uuid4()),
                expected_event_id=None,connection=connection,correlation_id=state.arguments['correlation_id'])
    references={'dialogId':str(uuid4()),'forsendelseId':str(uuid4())}
    await state.store.finish_source_operation(state.operation_claim.submission_id,result.event.id,
        state='succeeded',reference=json.dumps(references,separators=(',', ':')),failure=None)
    return references


async def record_actual_parent_feedback_and_claim_successor(state,status):
    """Real Docs/reconciliation/approval/claim commands; no seeded confirmed row."""
    import httpx
    from talli_backend.modules.documents.service import DocumentsService
    from talli_backend.application.shareholder_register_source_correction import ShareholderRegisterSourceCorrection
    from talli_backend.application.shareholder_register_source_claim_v3 import ShareholderRegisterSourceClaimV3
    from talli_backend.application.shareholder_register_source_approval_v3 import ShareholderRegisterSourceApprovalV3
    from test_rf1086_database_runtime import LocalStorage
    references=await complete_claim_with_synthetic_provider_results(state)
    parent=state.operation_claim
    source_documents=state.workflow._documents
    feedback_storage=LocalStorage()
    class Documents:
        async def session(self,token):
            existing=await source_documents.session(token)
            class Storage:
                async def create_upload_transfer(self,**args):return await feedback_storage.create_upload_transfer(**args)
                async def read_object(self,**args):
                    if args['storage_key'] in feedback_storage.objects:
                        assert not state.held
                        state.byte_reads.append(args['storage_key'])
                        return await feedback_storage.read_object(**args)
                    return await existing._storage.read_object(**args)
                async def remove_object(self,**args):return await feedback_storage.remove_object(**args)
            return DocumentsService(existing._persistence,Storage())
    documents=Documents()
    state.store._documents=documents
    state.store._storage_transport=httpx.MockTransport(feedback_storage.upload)
    lease=str(uuid4())
    assert await state.store.claim_feedback_lease(parent.submission_id.value,lease)
    try:
        journal=state.store.feedback_journal(submission_id=parent.submission_id.value,
            company_id=str(parent.company_id),income_year=int(parent.income_year),
            forsendelse_id=references['forsendelseId'],lease_id=lease)
        content=('<tilbakemelding>Synthetic controlled '+status+' parent</tilbakemelding>').encode()
        digest=sha256(content).hexdigest()
        artifact=rf.Rf1086ReconciliationArtifact(parent.submission_id.value,str(parent.company_id),
            str(uuid4()),'application/xml',content,len(content),digest,status)
        assert await journal.record_artifact(artifact)==digest
        assert await journal.append_reconciliation(rf.Rf1086ReconciliationSnapshot(status,(digest,),
            'RF1086_FEEDBACK_'+status.upper()))
    finally:await state.store.release_feedback_lease(parent.submission_id.value,lease)
    retained=await state.store.read_source_claim_approval_v3(parent.approval_id)
    prior=rf.Rf1086SourceCorrectionPredecessor(parent.submission_id,retained.approval.manifest_hash,
        'Controlled actual retained parent correction')
    sessions=state.workflow._sessions
    state.approval_workflow=ShareholderRegisterSourceApprovalV3(sessions,documents)
    state.claim_workflow=ShareholderRegisterSourceClaimV3(sessions,documents)
    state.dispatch=ShareholderRegisterSourceDispatchV3(sessions,documents)
    state.store._source_correction_v3=ShareholderRegisterSourceCorrection(sessions,documents)
    review=(await state.approval_workflow.read_review('synthetic-token',**state.approval_arguments)).review
    assert review.can_approve,review.blockers
    approved=await state.approval_workflow.approve('synthetic-token',**state.approval_arguments,
        review_sha256=review.review_sha256,acknowledged_warning_codes=review.warning_codes,
        real_filing_confirmed=True,predecessor=prior)
    retained=await state.store.read_source_claim_approval_v3(rf.ApprovalId(approved.record_id))
    state.claim_arguments=dict(approval_id=rf.ApprovalId(approved.record_id),
        manifest_sha256=retained.approval.manifest_hash,expected_head=parent.submission_id,
        correlation_id=state.arguments['correlation_id'])
    claimed=await state.claim_workflow.claim('synthetic-token',**state.claim_arguments)
    assert claimed.newly_claimed
    state.operation_claim=claimed.claim
    return parent,prior


@pytest.mark.parametrize('status',['accepted','rejected'])
def test_actual_required_rf_correction_reprojects_full_parent_and_claim_before_committed_main(state,
        operation_access,status):
    operation_state(state)
    source=rf.serialize_rf1086_year_source_v2(state.source)
    async def run():
        parent,prior=await record_actual_parent_feedback_and_claim_successor(state,status)
        retained=await state.store.read_source_claim_approval_v3(state.operation_claim.approval_id)
        full=await state.store.read_retained_correction_archive(
            rf.Rf1086SourceQuery(state.operation_claim.company_id,state.operation_claim.income_year,state.store.actor_id),
            parent.submission_id)
        assert {row.id for row in full.production_submissions}=={parent.submission_id.value,state.operation_claim.submission_id.value}
        rf.serialize_rf1086_archive_v6(full,query=rf.Rf1086ArchiveQuery(full.company_id,full.income_year,state.store.actor_id))
        with pytest.raises(rf.Rf1086ProductionError):
            rf.prepare_rf1086_retained_correction_predecessor(full,
                query=rf.Rf1086ArchiveQuery(full.company_id,full.income_year,state.store.actor_id),predecessor=prior)
        assert rf.prepare_rf1086_claimed_correction_predecessor_v3(full,
            query=rf.Rf1086ArchiveQuery(full.company_id,full.income_year,state.store.actor_id),
            claim=state.operation_claim,retained=retained).submission.id==parent.submission_id.value
        before=await operation_rows(state)
        prepared=await prepare_main(state)
        after=await operation_rows(state)
        assert prepared.newly_prepared and len(after)==len(before)+1
        # Required receipt IO occurred before the guarded write; no second main intent.
        assert state.byte_reads
        async with state.store.source_operation_recovery_v3(state.operation_claim) as recovery:
            assert (await recovery.read_operation_recovery()).assessment.disposition=='recovery_required'
        return prepared
    result=asyncio.run(run())
    assert result.newly_prepared and rf.serialize_rf1086_year_source_v2(state.source)==source


@pytest.mark.parametrize('fault',['missing','selected-evidence','parent-state','original-receipt'])
def test_actual_fixed_main_correction_receiver_refuses_stale_or_rebound_required_proof_before_intent(state,
        operation_access,fault):
    operation_state(state)
    async def run():
        await record_actual_parent_feedback_and_claim_successor(state,'rejected')
        owned=state.operation_claim
        retained=await state.store.read_source_claim_approval_v3(owned.approval_id)
        prepared=await state.dispatch.prepare_main_intent_v3('synthetic-token',state.store,
            claim=owned,retained=retained,correlation_id=state.arguments['correlation_id'])
        correction=prepared.correction
        assert correction is not None and correction.originals
        if fault=='missing':correction=None
        elif fault=='selected-evidence':correction=replace(correction,selected_evidence=None)
        elif fault=='parent-state':correction=replace(correction,snapshot=replace(correction.snapshot,
            submission=replace(correction.snapshot.submission,feedback_safe_error_code='rebound-fixture-error')))
        else:correction=replace(correction,originals=(replace(correction.originals[0],metadata_sha256='f'*64),
            *correction.originals[1:]))
        prepared=replace(prepared,correction=correction)
        connection=await state.store.read_connection(str(state.request),str(owned.company_id))
        before=await operation_rows(state)
        async def attempt():
            async with state.store.source_operation_recovery_v3(owned) as recovery:
                async with recovery.fresh_operation_admission_v3() as fresh:
                    # Exercise the fixed writer independently of the app's validator.
                    await fresh.prepare_main_operation_v3(prepared,idempotency_key=str(uuid4()),
                        expected_event_id=None,connection=connection,correlation_id=state.arguments['correlation_id'])
        with pytest.raises(rf.Rf1086ProductionError):await attempt()
        assert await operation_rows(state)==before
        return owned
    owned=asyncio.run(run())
    assert owned==state.operation_claim
