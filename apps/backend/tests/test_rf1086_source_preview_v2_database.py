"""Full-schema closed preview path; claims/Auth/storage are explicit fixtures.

Borrowed saved-admission fixture retains one setup-only preview. The deterministic
preview tested here is created solely through the new application/held adapter.
No live Auth or external object-store recovery is claimed.
"""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from hashlib import sha256

import psycopg
from psycopg import sql
import pytest

from talli_backend.application.shareholder_register_source_preview_v2 import ShareholderRegisterSourcePreviewV2
from talli_backend.modules.documents import public as docs
from talli_backend.modules.shareholder_register_filing import public as rf
from rf1086_year_source_v2_database_fixture import (
    admitted, closed_source_role, withdrawal_fixture_role, amendment_fixture_authority,
    connection, withdrawal, amend, DATABASE_URL, PRODUCER,
)
from test_rf1086_guarded_source_capture_v2_database import (
    capture_login, restricted_capture_session, complete_inputs,
)
from test_documents_historical_original_integrity_database import backend_url, documents_authority
from test_rf1086_source_admission_v2_database import fixture, monitor_guard
from test_rf1086_source_company_guard_database import waiting
from test_rf1086_source_preview import preview_source


pytestmark = pytest.mark.authority_database


def workflow(state):
    return ShareholderRegisterSourcePreviewV2(state.workflow._sessions,state.workflow._documents)


def arguments(state):
    return dict(company_id=state.source.company_id,income_year=state.source.income_year,
        source_id=state.source.source_id,correlation_id=state.arguments['correlation_id'])


def generate(state):
    return asyncio.run(workflow(state).generate('synthetic-token',**arguments(state)))


def preview_rows(state):
    with psycopg.connect(DATABASE_URL) as db:
        return db.execute('select id,payload_text,payload_sha256,created_by,created_at '
            'from shareholder_register_filing.source_previews where company_id=%s and income_year=%s order by id',
            (str(state.source.company_id),int(state.source.income_year))).fetchall()


@pytest.mark.parametrize('kind',['cash_issue','loss_covering_reduction'])
@pytest.mark.parametrize('count',[0,1,2])
def test_actual_closed_generation_and_replay_preserve_exact_saved_payload_and_metadata(
        admitted,closed_source_role,withdrawal_fixture_role,capture_login,backend_url,kind,count):
    item,command,originals = complete_inputs(admitted,closed_source_role,withdrawal_fixture_role,kind,count)
    state = fixture(item,command,originals,capture_login,backend_url)
    old_rows = preview_rows(state)
    source_wire = rf.serialize_rf1086_year_source_v2(state.source)
    result = generate(state)
    assert result.preview.preview_id != state.preview.preview_id
    assert result.payload_text == rf.serialize_rf1086_source_preview(result.preview)
    assert sha256(result.payload_text.encode()).hexdigest() == result.payload_sha256
    assert result.created_by == str(state.source.confirmed_by.subject)
    assert len(state.byte_reads) == len(originals) and len(state.traces) == 4
    assert generate(state) == result
    rows = preview_rows(state)
    assert len(rows) == len(old_rows)+1 and all(row in rows for row in old_rows)
    assert rf.serialize_rf1086_year_source_v2(state.source) == source_wire and not state.held


def test_current_new_owner_replays_original_capture_with_unavailable_historical_actor(
        admitted,closed_source_role,withdrawal_fixture_role,capture_login,backend_url):
    item,command,originals = complete_inputs(admitted,closed_source_role,withdrawal_fixture_role,'loss_covering_reduction',1)
    state = fixture(item,command,originals,capture_login,backend_url)
    first = generate(state); rows = preview_rows(state)
    with psycopg.connect(DATABASE_URL) as db:
        db.execute("insert into public.company_memberships(company_id,user_id,role,accepted_at) values(%s,%s,'owner',clock_timestamp())",
            (admitted['company'],admitted['outsider']))
        db.execute("update public.company_memberships set role='read_only' where company_id=%s and user_id=%s",
            (admitted['company'],admitted['owner']))
        assert db.execute("update auth.users set banned_until='infinity' where id=%s",(admitted['owner'],)).rowcount == 1
        assert db.execute('select banned_until>clock_timestamp() from auth.users where id=%s',
            (admitted['owner'],)).fetchone()[0] is True
    with pytest.raises(rf.ShareholderRegisterFilingError): generate(state)
    state.store,state.traces = restricted_capture_session(item,capture_login,actor=admitted['outsider'])
    monitor_guard(state)
    assert generate(state) == first and preview_rows(state) == rows
    assert first.created_by != str(state.store.actor_id.subject) and state.source.confirmed_by != state.store.actor_id


@pytest.mark.parametrize('change',['withdrawal','amendment','revoked_owner'])
def test_existing_preview_replay_requires_current_complete_owner_evidence(
        admitted,closed_source_role,withdrawal_fixture_role,capture_login,backend_url,change):
    item,command,originals = complete_inputs(admitted,closed_source_role,withdrawal_fixture_role,'loss_covering_reduction',1)
    state = fixture(item,command,originals,capture_login,backend_url)
    generate(state); before = preview_rows(state)
    if change == 'withdrawal': withdrawal(admitted,withdrawal_fixture_role,item['replacement'])
    elif change == 'amendment': amend(item)
    else:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute("update public.company_memberships set role='read_only' where company_id=%s and user_id=%s",
                (admitted['company'],admitted['owner']))
    if change == 'revoked_owner':
        with pytest.raises(docs.DocumentsError) as denied: generate(state)
        assert denied.value.code == docs.DocumentErrorCode.FORBIDDEN
    else:
        with pytest.raises(rf.Rf1086YearSourceError) as denied: generate(state)
        assert str(denied.value) == ('rf1086_source_independent_register_unavailable' if change == 'withdrawal'
            else 'rf1086_source_register_original_changed')
    assert preview_rows(state) == before


@pytest.mark.parametrize('cancel',[False,True])
def test_failure_after_real_append_rolls_back_new_preview_and_transaction_proof(
        admitted,closed_source_role,withdrawal_fixture_role,capture_login,backend_url,cancel):
    item,command,originals = complete_inputs(admitted,closed_source_role,withdrawal_fixture_role,'loss_covering_reduction',0)
    state = fixture(item,command,originals,capture_login,backend_url)
    before = preview_rows(state)
    admission = state.store.source_admission
    error = asyncio.CancelledError() if cancel else RuntimeError('owned post-append abort')
    @asynccontextmanager
    async def failing(query):
        async with admission(query) as scope:
            writer = scope.capture_source_preview_v2
            async def append_then_fail(prepared):
                capture = await writer(prepared)
                row = await (await scope._connection.execute('select payload_text from shareholder_register_filing.source_previews where id=%s',
                    (capture.preview.preview_id.value,))).fetchone()
                assert row['payload_text'] == capture.payload_text
                proof = await (await scope._connection.execute("select to_regclass('pg_temp.rf1086_year_source_governance_proofs') as proof")).fetchone()
                assert proof['proof'] is not None
                raise error
            scope.capture_source_preview_v2 = append_then_fail
            yield scope
    state.store.source_admission = failing
    with pytest.raises(type(error)) as failure: generate(state)
    assert failure.value is error and preview_rows(state) == before and not state.held


@pytest.mark.parametrize('change',['revoked_owner','withdrawal'])
def test_current_evidence_committed_while_preview_waits_cannot_append(
        admitted,closed_source_role,withdrawal_fixture_role,capture_login,backend_url,change):
    item,command,originals = complete_inputs(admitted,closed_source_role,withdrawal_fixture_role,'loss_covering_reduction',0)
    state = fixture(item,command,originals,capture_login,backend_url)
    before = preview_rows(state)
    async def race():
        with connection(admitted,withdrawal_fixture_role) as blocker:
            admission = state.store.source_admission
            reached = asyncio.get_running_loop().create_future()
            proceed = asyncio.Event(); guard_pid = asyncio.get_running_loop().create_future()
            transaction = state.store._transaction
            @asynccontextmanager
            async def announced_transaction(**options):
                async with transaction(**options) as db:
                    if not options.get('snapshot',False):
                        guard_pid.set_result((await (await db.execute('select pg_backend_pid() as pid')).fetchone())['pid'])
                    yield db
            @asynccontextmanager
            async def announced(query):
                reached.set_result(None); await proceed.wait()
                async with admission(query) as scope: yield scope
            state.store.source_admission = announced
            state.store._transaction = announced_transaction
            task = asyncio.create_task(workflow(state).generate('synthetic-token',**arguments(state)))
            try:
                await asyncio.wait_for(reached,5)
                # The fixture role can execute withdrawal, not the private
                # Company helper. The designated observer holds the guard.
                blocker.execute('reset role')
                blocker.execute('select public.company_archive_lock_company_v1(%s)',(admitted['company'],))
                proceed.set(); await waiting(await asyncio.wait_for(guard_pid,5)); assert not task.done()
                if change == 'revoked_owner':
                    blocker.execute("update public.company_memberships set role='read_only' where company_id=%s and user_id=%s",
                        (admitted['company'],admitted['owner']))
                else:
                    blocker.execute(sql.SQL('set local role {}').format(sql.Identifier(withdrawal_fixture_role)))
                    withdrawn = withdrawal(admitted,withdrawal_fixture_role,item['replacement'],db=blocker)
                    assert withdrawn.command.observation_id == item['replacement'].observation_id
            except BaseException:
                task.cancel();await asyncio.gather(task,return_exceptions=True);raise
        if change == 'revoked_owner':
            with pytest.raises(psycopg.errors.RaiseException) as denied: await asyncio.wait_for(task,8)
            assert denied.value.diag.message_primary == 'company_access_forbidden'
        else:
            with pytest.raises(rf.Rf1086YearSourceError) as denied: await asyncio.wait_for(task,8)
            assert str(denied.value) == 'rf1086_source_independent_register_unavailable'
    asyncio.run(race())
    assert preview_rows(state) == before


def test_two_actual_generations_share_one_exact_committed_preview(
        admitted,closed_source_role,withdrawal_fixture_role,capture_login,backend_url):
    item,command,originals = complete_inputs(admitted,closed_source_role,withdrawal_fixture_role,'loss_covering_reduction',0)
    state = fixture(item,command,originals,capture_login,backend_url)
    before = preview_rows(state)
    async def competing():
        admission = state.store.source_admission
        both_preflight = asyncio.Event(); arrivals = 0
        @asynccontextmanager
        async def barrier(query):
            nonlocal arrivals
            arrivals += 1
            if arrivals == 2: both_preflight.set()
            await asyncio.wait_for(both_preflight.wait(),5)
            async with admission(query) as scope: yield scope
        state.store.source_admission = barrier
        results = await asyncio.wait_for(asyncio.gather(
            workflow(state).generate('synthetic-token',**arguments(state)),
            workflow(state).generate('synthetic-token',**arguments(state))),15)
        assert arrivals == 2 and results[0] == results[1]
        return results[0]
    result = asyncio.run(competing())
    rows = preview_rows(state)
    assert len(rows) == len(before)+1 and all(row in rows for row in before)
    assert sum(str(row[0]) == result.preview.preview_id.value for row in rows) == 1


def test_runtime_roles_cannot_mint_preview_governance_proof(
        admitted,closed_source_role,withdrawal_fixture_role,capture_login,backend_url):
    item,command,originals = complete_inputs(admitted,closed_source_role,withdrawal_fixture_role,'loss_covering_reduction',0)
    state = fixture(item,command,originals,capture_login,backend_url)
    before = preview_rows(state)
    with psycopg.connect(DATABASE_URL) as db:
        for role in ('anon','authenticated','service_role','shareholder_register_filing_executor'):
            assert not db.execute("select has_function_privilege(%s,%s,'EXECUTE')",(role,PRODUCER)).fetchone()[0]
    with connection(admitted,'shareholder_register_filing_executor') as db:
        db.execute('select shareholder_register_filing.lock_year_source_v1(%s,%s)',
            (str(state.source.company_id),int(state.source.income_year)))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute('select ' + PRODUCER.split('(')[0] + '(%s,%s,%s,%s)',
                (str(state.source.company_id),int(state.source.income_year),state.source.source_sha256,
                    str(state.store.actor_id.subject)))
    assert preview_rows(state) == before


@pytest.mark.parametrize('field,value',[('filing','forged-obligation'),('hovedskjema_xml','<forged/>')])
def test_real_held_writer_rejects_forged_identity_or_xml_before_proof(
        admitted,closed_source_role,withdrawal_fixture_role,capture_login,backend_url,field,value):
    item,command,originals = complete_inputs(admitted,closed_source_role,withdrawal_fixture_role,'loss_covering_reduction',0)
    state = fixture(item,command,originals,capture_login,backend_url)
    before = preview_rows(state)
    _,prepared_store = preview_source(state.source)
    forged = replace(prepared_store.prepared,rendered=replace(prepared_store.prepared.rendered,**{field:value}))
    proof_calls = []
    async def run():
        scope = None
        try:
            async with workflow(state)._admission.admit_year_source('synthetic-token',**arguments(state)) as admitted_source:
                scope = admitted_source.transaction
                producer = scope.prepare_source_governance_proof
                async def observed(source):
                    proof_calls.append(source.source_sha256)
                    return await producer(source)
                scope.prepare_source_governance_proof = observed
                await scope.capture_source_preview_v2(forged)
        finally:
            assert scope is not None and not scope._active
    with pytest.raises(rf.Rf1086YearSourceError,match='rf1086_source_preview_mismatch'): asyncio.run(run())
    assert not proof_calls and preview_rows(state) == before and not state.held
