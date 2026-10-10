"""Actual v2 admission on full owner schema and restricted disposable logins.

Verified claims and membership refresh are explicit fixtures; Documents metadata,
retention, RF/Governance reads and guards are real SQL. Storage reads exact locally
retained fixture bytes. This does not establish live Auth or object-store recovery.
Immutable fixture history stays until disposable database destruction.
"""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
import pytest

from talli_backend.adapters.supabase_documents import SupabaseDocumentsPersistence
from talli_backend.application.shareholder_register_source_admission_v2 import ShareholderRegisterSourceAdmissionV2
from talli_backend.modules.documents import public as docs
from talli_backend.modules.documents.service import DocumentsService
from talli_backend.modules.shareholder_register_filing import public as rf
from rf1086_year_source_v2_database_fixture import (
    admitted, amendment_fixture_authority, withdrawal_fixture_role, closed_source_role,
    connection, mint_proof, amend, DATABASE_URL,
)
from test_rf1086_guarded_source_capture_v2_database import (
    capture_login, restricted_capture_session, complete_inputs, capture, CORRELATION,
)
from test_documents_historical_original_integrity_database import backend_url, documents_authority
from test_rf1086_source_preview import preview_source
from test_rf1086_retained_readiness_observation_v2 import close_fresh_rendering
from test_rf_annual_opening_admission_database import add_opening
from test_rf_annual_ledger_admission_database import ledger_fixture_insert_access, add_lock
from test_annual_interview_company_guard_database import fixture_roles, seed, bind
from test_rf1086_source_company_guard_database import waiting


pytestmark = pytest.mark.authority_database


def fixture(item, command, originals, login, documents_url):
    store, traces = restricted_capture_session(item, login)
    source = capture(store, command, originals)
    preview = replace(preview_source(source)[0],preview_id=rf.PreviewId(str(uuid4())))
    text = rf.serialize_rf1086_source_preview(preview)
    # Closed proof authorizes only fixture preview setup; admission never mints it.
    with connection(item['seed'],item['source_role']) as db:
        mint_proof(db,source)
        db.execute('set local role shareholder_register_filing_executor')
        saved = db.execute('select shareholder_register_filing.append_source_preview_v1(%s,%s,%s,%s,%s,%s,%s,%s)',
            (preview.preview_id.value,source.company_id.value,int(source.income_year),source.source_id.value,
                source.source_sha256,source.case_sha256,sha256(text.encode()).hexdigest(),text)).fetchone()[0]
        assert str(saved) == preview.preview_id.value
    state = SimpleNamespace(store=store,traces=traces,source=source,preview=preview,item=item,
        arguments=dict(company_id=source.company_id,income_year=source.income_year,
            preview_id=preview.preview_id,correlation_id=CORRELATION),held=False,byte_reads=[])

    async def refresh_roles():
        # Privileged fixture observer supplies current membership, never an assumed owner.
        async with await psycopg.AsyncConnection.connect(DATABASE_URL) as db:
            row = await (await db.execute('select role from public.company_memberships '
                'where company_id=%s and user_id=%s and accepted_at is not null',
                (str(source.company_id),str(state.store.actor_id.subject)))).fetchone()
            return {source.company_id:row[0]} if row else {}

    class Documents:
        async def session(self, token):
            persistence = SupabaseDocumentsPersistence(documents_url,state.store._verified,
                await refresh_roles(),role_refresher=refresh_roles)
            class Storage:
                async def read_object(self,*,bucket,storage_key):
                    assert not state.held
                    state.byte_reads.append(storage_key)
                    expected = next(value for value in originals if value.document_id.value in storage_key)
                    retained = await persistence.read_retained_original(expected.original_id,expected.company_id)
                    return docs.StoredDocumentObject(retained.content,'application/pdf')
            return DocumentsService(persistence,Storage())
    class Sessions:
        async def session(self,token):
            # Explicit fixture authentication state, not a live Auth-server login.
            async with await psycopg.AsyncConnection.connect(DATABASE_URL) as db:
                row = await (await db.execute('select coalesce(banned_until>clock_timestamp(),false) '
                    'from auth.users where id=%s',(str(state.store.actor_id.subject),))).fetchone()
            if row is None or row[0]: raise rf.ShareholderRegisterFilingError.forbidden()
            return state.store
    state.workflow = ShareholderRegisterSourceAdmissionV2(Sessions(),Documents())
    monitor_guard(state)
    return state


def monitor_guard(state):
    transaction = state.store._transaction
    @asynccontextmanager
    async def monitored(**options):
        async with transaction(**options) as db:
            state.held = not options.get('snapshot',False)
            try: yield db
            finally: state.held = False
    state.store._transaction = monitored


async def admitted_read(state):
    async with state.workflow.admit('synthetic-token',**state.arguments) as result:
        assert state.held
        pid = await (await result.transaction._connection.execute('select pg_backend_pid() as pid')).fetchone()
        assert pid['pid'] == state.traces[-1]['pid']
        return result


@pytest.mark.parametrize('kind',['cash_issue','loss_covering_reduction'])
@pytest.mark.parametrize('count',[0,1,2])
def test_real_saved_admission_uses_current_complete_owner_evidence_and_preserves_bytes(
        admitted,closed_source_role,withdrawal_fixture_role,capture_login,backend_url,kind,count,monkeypatch):
    item,command,originals = complete_inputs(admitted,closed_source_role,withdrawal_fixture_role,kind,count)
    state = fixture(item,command,originals,capture_login,backend_url)
    expected = rf.build_rf1086_source_readiness_v2(state.source,state.preview)
    wire = rf.serialize_rf1086_year_source_v2(state.source)
    close_fresh_rendering(monkeypatch)
    result = asyncio.run(admitted_read(state))
    assert result.source_readiness == expected and result.source == state.source
    assert result.retained_preview.payload_text == rf.serialize_rf1086_source_preview(state.preview)
    assert result.retained_preview.created_by == str(state.source.confirmed_by.subject)
    assert len(state.byte_reads) == len(originals) and len(state.traces) == 4
    assert rf.serialize_rf1086_year_source_v2(result.source) == wire and not result.transaction._active


def test_new_accepted_owner_observes_unavailable_original_actor_and_saved_creation_metadata(
        admitted,closed_source_role,withdrawal_fixture_role,capture_login,backend_url,monkeypatch):
    item,command,originals = complete_inputs(admitted,closed_source_role,withdrawal_fixture_role,'loss_covering_reduction',1)
    state = fixture(item,command,originals,capture_login,backend_url)
    before = asyncio.run(admitted_read(state))
    with psycopg.connect(DATABASE_URL) as db:
        db.execute("insert into public.company_memberships(company_id,user_id,role,accepted_at) values(%s,%s,'owner',clock_timestamp())",
            (admitted['company'],admitted['outsider']))
        db.execute("update public.company_memberships set role='read_only' where company_id=%s and user_id=%s",
            (admitted['company'],admitted['owner']))
        blocked = db.execute("update auth.users set banned_until='infinity' where id=%s",(admitted['owner'],))
        assert blocked.rowcount == 1
        assert db.execute('select banned_until>clock_timestamp() from auth.users where id=%s',
            (admitted['owner'],)).fetchone()[0] is True
    with pytest.raises(rf.ShareholderRegisterFilingError) as unavailable:
        asyncio.run(state.workflow._sessions.session('synthetic-token'))
    assert unavailable.value.code == rf.ShareholderRegisterFilingErrorCode.FORBIDDEN
    # Track the exact connection while using the new owner's explicit claims.
    state.store,state.traces = restricted_capture_session(item,capture_login,actor=admitted['outsider'])
    monitor_guard(state)
    close_fresh_rendering(monkeypatch)
    after = asyncio.run(admitted_read(state))
    assert after.source == before.source and after.retained_preview == before.retained_preview
    assert after.source.confirmed_by != state.store.actor_id


@pytest.mark.parametrize('change',['withdrawal','amendment','revoked_owner'])
def test_changed_current_owner_evidence_cannot_admit_saved_source(
        admitted,closed_source_role,withdrawal_fixture_role,capture_login,backend_url,change,monkeypatch):
    from rf1086_year_source_v2_database_fixture import withdrawal
    item,command,originals = complete_inputs(admitted,closed_source_role,withdrawal_fixture_role,'loss_covering_reduction',1)
    state = fixture(item,command,originals,capture_login,backend_url)
    if change == 'withdrawal': withdrawal(admitted,withdrawal_fixture_role,item['replacement'])
    elif change == 'amendment': amend(item)
    else:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute("update public.company_memberships set role='read_only' where company_id=%s and user_id=%s",
                (admitted['company'],admitted['owner']))
    close_fresh_rendering(monkeypatch)
    if change == 'revoked_owner':
        with pytest.raises(docs.DocumentsError) as denied: asyncio.run(admitted_read(state))
        assert denied.value.code == docs.DocumentErrorCode.FORBIDDEN
    else:
        expected = ('rf1086_source_independent_register_unavailable' if change == 'withdrawal'
            else 'rf1086_source_register_original_changed')
        with pytest.raises(rf.Rf1086YearSourceError) as denied: asyncio.run(admitted_read(state))
        assert str(denied.value) == expected


def test_all_actual_annual_owners_keep_blocked_warning_ready_policy_without_renderer(
        admitted,closed_source_role,withdrawal_fixture_role,capture_login,backend_url,fixture_roles,monkeypatch):
    item,command,originals = complete_inputs(admitted,closed_source_role,withdrawal_fixture_role,'loss_covering_reduction',0)
    state = fixture(item,command,originals,capture_login,backend_url)
    close_fresh_rendering(monkeypatch)
    def read():
        return asyncio.run(state.workflow.read_annual_readiness_v2('synthetic-token',**state.arguments))
    initial = read()
    assert initial.readiness_status == 'blocked'
    assert {issue.code for issue in initial.issues} >= {'opening_balance_missing','annual_data_missing','period_not_locked'}
    with psycopg.connect(DATABASE_URL) as db: opening,_ = add_opening(db,admitted)
    with ledger_fixture_insert_access(DATABASE_URL):
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('insert into ledger.opening_bank_inputs(snapshot_id,company_id,income_year,bank_balance_nok,recorded_by,recorded_at) '
                'values(%s,%s,2026,%s,%s,clock_timestamp())',(opening,admitted['company'],Decimal('123.45'),admitted['owner']))
            add_lock(db,admitted)
    interview = seed(admitted)
    warning = read()
    assert warning.readiness_status == 'warning' and warning.required_warning_codes == ('bank_balance_not_confirmed',)
    with psycopg.connect(DATABASE_URL) as db:
        bind(db,admitted)
        db.execute('update public.annual_data set answers=%s where id=%s',(Jsonb({
            'bank_balance_confirmed':True,'has_unpaid_items':False,'authority_to_submit_confirmed':True}),interview))
    ready = read()
    assert ready.readiness_status == 'ready' and ready == read()
    assert ready.annual_inputs.opening_snapshot_ids == ready.annual_inputs.opening_bank_snapshot_ids == (str(opening),)
    assert initial.source == warning.source == ready.source


def test_owner_revocation_committed_while_admission_waits_fails_after_company_guard(
        admitted,closed_source_role,withdrawal_fixture_role,capture_login,backend_url,monkeypatch):
    item,command,originals = complete_inputs(admitted,closed_source_role,withdrawal_fixture_role,'loss_covering_reduction',0)
    state = fixture(item,command,originals,capture_login,backend_url)
    close_fresh_rendering(monkeypatch)
    async def race():
        with psycopg.connect(DATABASE_URL) as blocker:
            # Start after document byte preflight; all later checks stay real.
            admission = state.store.source_admission
            reached = asyncio.get_running_loop().create_future()
            proceed = asyncio.Event()
            guard_pid = asyncio.get_running_loop().create_future()
            transaction = state.store._transaction
            @asynccontextmanager
            async def announced_transaction(**options):
                async with transaction(**options) as db:
                    if not options.get('snapshot',False):
                        guard_pid.set_result((await (await db.execute('select pg_backend_pid() as pid')).fetchone())['pid'])
                    yield db
            @asynccontextmanager
            async def announced(query):
                reached.set_result(None)
                await proceed.wait()
                async with admission(query) as scope: yield scope
            state.store.source_admission = announced
            state.store._transaction = announced_transaction
            task = asyncio.create_task(admitted_read(state))
            try:
                await asyncio.wait_for(reached,5)
                blocker.execute('select public.company_archive_lock_company_v1(%s)',(admitted['company'],))
                proceed.set()
                await waiting(await asyncio.wait_for(guard_pid,5))
                assert not task.done()
                blocker.execute("update public.company_memberships set role='read_only' where company_id=%s and user_id=%s",
                    (admitted['company'],admitted['owner']))
            except BaseException:
                task.cancel();await asyncio.gather(task,return_exceptions=True);raise
        with pytest.raises(psycopg.errors.RaiseException) as denied:
            await asyncio.wait_for(task,8)
        assert denied.value.diag.message_primary == 'company_access_forbidden'
    asyncio.run(race())
