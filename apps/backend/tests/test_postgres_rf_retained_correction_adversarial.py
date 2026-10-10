"""Independent adapter traces using real reader/enumerator methods and fake SQL only."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict, fields, replace
import re
from types import SimpleNamespace
from uuid import UUID

import psycopg
from psycopg.pq import TransactionStatus
import pytest

from talli_backend.adapters import postgres_shareholder_register_filing as adapter
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, UserId
from test_postgres_shareholder_register_filing import session
from test_rf1086_source_correction import predecessor_snapshot
from test_rf1086_year_source import ACTOR


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def fetchone(self):
        return self.rows[0] if self.rows else None

    async def fetchall(self):
        return self.rows


def wire(record):
    result = {field.name: getattr(record, field.name) for field in fields(record)}
    if isinstance(record, rf.Rf1086PreviewRecord):
        result['issues'] = [asdict(issue) for issue in record.issues]
    return result


class Database:
    """Synthetic SQL results; no ownership or lock-race proof is claimed."""
    def __init__(self):
        self.snapshot = predecessor_snapshot()
        self.parent = wire(self.snapshot.submission)
        self.rows = {
            'filing_previews': [wire(self.snapshot.preview)],
            'filing_approval_snapshots': [wire(self.snapshot.approval)],
            'production_filing_submissions': [wire(self.snapshot.submission)],
            'production_filing_events': [wire(row) for row in self.snapshot.reconciliation_events],
            'production_feedback_artifacts': [wire(row) for row in self.snapshot.artifacts],
        }
        self.info = SimpleNamespace(transaction_status=TransactionStatus.IDLE)
        self.sql = []
        self.lifecycle = []
        self.fail_at = None
        self.error = psycopg.errors.InsufficientPrivilege('synthetic selected-parent denial')
        self.connect_count = 0

    async def __aenter__(self):
        self.lifecycle.append('connection-enter')
        return self

    async def __aexit__(self, kind, error, trace):
        self.lifecycle.append('connection-exit')
        return False

    @asynccontextmanager
    async def transaction(self):
        self.lifecycle.append('transaction-enter')
        self.info.transaction_status = TransactionStatus.INTRANS
        try:
            yield self
        finally:
            self.lifecycle.append('transaction-exit')
            self.info.transaction_status = TransactionStatus.IDLE

    async def execute(self, sql, args=()):
        self.sql.append((sql, args))
        if self.fail_at is not None and self.fail_at in sql:
            raise self.error
        if 'lock_correction_predecessor_v1' in sql:
            return Cursor([] if self.parent is None else [self.parent])
        if ('from shareholder_register_filing.production_filing_submissions' in sql
                and re.search(r'where\s+(?:[a-z]+\.)?id\s*=', sql)):
            return Cursor([] if self.parent is None else [self.parent])
        table = re.search(r'from shareholder_register_filing\.([a-z_]+)', sql)
        return Cursor(self.rows.get(table.group(1), []) if table else [])


def harness(monkeypatch):
    db = Database()
    store = session({})
    store._verified = _VerifiedActor(ACTOR, '{}')
    store._configuration = replace(store._configuration, database_url='postgresql://synthetic-unused')
    query = rf.Rf1086SourceQuery(db.snapshot.company_id, db.snapshot.income_year, ACTOR)
    identity = rf.SubmissionId(db.snapshot.submission.id)
    async def connect(*args, **kwargs):
        db.connect_count += 1
        return db
    monkeypatch.setattr(adapter.psycopg.AsyncConnection, 'connect', connect)
    def forbidden_effect(*args, **kwargs):
        raise AssertionError('Retained raw reader must not touch provider, lease or pure admission')
    for name in ('bind_read_only_authority', 'bind_mutation_authority', 'claim_feedback_lease',
                 'release_feedback_lease', 'require_configuration'):
        monkeypatch.setattr(store, name, forbidden_effect)
    monkeypatch.setattr(rf, 'prepare_rf1086_retained_correction_predecessor', forbidden_effect)
    monkeypatch.setattr(rf, 'prepare_rf1086_retained_source_reconciliation', forbidden_effect)
    return db, store, query, identity


def invoke(store, db, query, identity, mode, *, scope_query=None, expired=False):
    if mode == 'preflight':
        return asyncio.run(store.read_retained_correction_archive(query, identity))
    db.info.transaction_status = TransactionStatus.INTRANS
    scope = adapter._SourceAdmission(store, db, scope_query or query, None)
    if expired:
        scope.close()
    return asyncio.run(scope.read_retained_correction_archive(query, identity))


@pytest.mark.parametrize('mode', ['preflight', 'held'])
def test_actual_reader_enumerates_raw_unfiltered_rows_on_exact_connection(mode, monkeypatch):
    db, store, query, identity = harness(monkeypatch)
    extra = replace(db.snapshot.submission, id=str(UUID(int=88331)),
        user_id=str(UUID(int=88332)), submitted_by=str(UUID(int=88332)),
        case_profile='unknown-future-profile', created_at='2099-01-01T00:00:00Z')
    db.rows['production_filing_submissions'].append(wire(extra))
    result = invoke(store, db, query, identity, mode)
    assert type(result) is rf.Rf1086ArchiveSnapshot
    assert result.production_submissions == (db.snapshot.submission, extra)
    assert result.source_history == rf.Rf1086ArchiveSourceHistory()
    assert result.overrides == result.withdrawal_capture_records == ()
    enumerations = [(i, sql, args) for i, (sql, args) in enumerate(db.sql)
        if sql.startswith('select t.* from shareholder_register_filing.production_filing_submissions')]
    assert len(enumerations) == 1
    index, sql, args = enumerations[0]
    assert args == (str(query.company_id), int(query.income_year))
    assert all(token not in sql.lower() for token in ('user_id', 'submitted_by', 'case_profile', 'limit '))
    if mode == 'preflight':
        assert db.connect_count == 1
        assert [sql for sql, _ in db.sql[:3]] == [
            'set transaction isolation level repeatable read', 'set transaction read only',
            'set local role shareholder_register_filing_executor']
        actor_setup = next(args for sql, args in db.sql if 'talli.verified_actor_id' in sql)
        assert actor_setup[0] == str(ACTOR.subject)
        access = next(i for i, (sql, _) in enumerate(db.sql) if 'assert_submission_v1' in sql)
        selected = next(i for i, (sql, _) in enumerate(db.sql)
            if 'from shareholder_register_filing.production_filing_submissions' in sql
            and re.search(r'where\s+(?:[a-z]+\.)?id\s*=', sql))
        assert access < selected < index
        assert db.lifecycle == ['connection-enter', 'transaction-enter', 'transaction-exit', 'connection-exit']
    else:
        assert db.connect_count == 0 and db.lifecycle == []
        assert 'lock_correction_predecessor_v1' in db.sql[0][0]
        assert db.sql[0][1] == (identity.value, str(query.company_id), int(query.income_year), str(ACTOR.subject))
        assert index > 0


@pytest.mark.parametrize('mode', ['preflight', 'held'])
@pytest.mark.parametrize('shape', ['query-subclass', 'actor-subclass', 'subject-subclass', 'raw-subject',
    'raw-company', 'company-subclass', 'year-subclass', 'float-year', 'raw-id', 'id-subclass'])
def test_exact_input_shapes_fail_before_connect_or_sql(mode, shape, monkeypatch):
    db, store, query, identity = harness(monkeypatch)
    class QuerySubclass(rf.Rf1086SourceQuery):
        pass
    class ActorSubclass(ActorId):
        pass
    class UserSubclass(UserId):
        pass
    class CompanySubclass(CompanyId):
        pass
    class YearSubclass(IncomeYear):
        pass
    class IdSubclass(rf.SubmissionId):
        pass
    if shape == 'query-subclass':query = QuerySubclass(query.company_id, query.income_year, ACTOR)
    if shape == 'actor-subclass':query = replace(query, actor_id=ActorSubclass(ActorKind.USER, ACTOR.subject))
    if shape == 'subject-subclass':query = replace(query, actor_id=ActorId(ActorKind.USER, UserSubclass(str(ACTOR.subject))))
    if shape == 'raw-subject':query = replace(query, actor_id=ActorId(ActorKind.USER, str(ACTOR.subject)))
    if shape in ('actor-subclass', 'subject-subclass', 'raw-subject'):
        # Matching malformed session/query actors must not bypass shape validation.
        store._verified = _VerifiedActor(query.actor_id, '{}')
    if shape == 'raw-company':query = replace(query, company_id=str(query.company_id))
    if shape == 'company-subclass':query = replace(query, company_id=CompanySubclass(str(query.company_id)))
    if shape == 'year-subclass':query = replace(query, income_year=YearSubclass(int(query.income_year)))
    if shape == 'float-year':query = replace(query, income_year=IncomeYear(float(query.income_year.value)))
    if shape == 'raw-id':identity = identity.value
    if shape == 'id-subclass':identity = IdSubclass(identity.value)
    with pytest.raises(rf.Rf1086ProductionError, match='^basis_unavailable$'):
        invoke(store, db, query, identity, mode)
    assert db.connect_count == 0 and db.sql == []


@pytest.mark.parametrize('mode', ['preflight', 'held'])
def test_well_typed_foreign_session_actor_fails_before_sql(mode, monkeypatch):
    db, store, query, identity = harness(monkeypatch)
    query = replace(query, actor_id=ActorId(ActorKind.USER, UserId(str(UUID(int=88902)))))
    with pytest.raises(rf.ShareholderRegisterFilingError) as caught:
        invoke(store, db, query, identity, mode)
    assert caught.value.code == rf.ShareholderRegisterFilingError.forbidden().code
    assert db.connect_count == 0 and db.sql == []


@pytest.mark.parametrize('state', ['closed', 'foreign-company', 'foreign-year', 'foreign-actor', 'idle-transaction'])
def test_held_reader_rejects_expired_or_foreign_scope_before_parent_lock(state, monkeypatch):
    db, store, query, identity = harness(monkeypatch)
    scope_query = query
    if state == 'foreign-company':query = replace(query, company_id=CompanyId(str(UUID(int=88901))))
    if state == 'foreign-year':query = replace(query, income_year=IncomeYear(2024))
    if state == 'foreign-actor':query = replace(query, actor_id=ActorId(ActorKind.USER, UserId(str(UUID(int=88902)))))
    if state == 'idle-transaction':
        scope = adapter._SourceAdmission(store, db, query, None)
        call = lambda: asyncio.run(scope.read_retained_correction_archive(query, identity))
    else:
        call = lambda: invoke(store, db, query, identity, 'held', scope_query=scope_query, expired=state == 'closed')
    with pytest.raises(rf.ShareholderRegisterFilingError) as caught:
        call()
    expected = (rf.ShareholderRegisterFilingError.unavailable()
        if state in ('closed', 'idle-transaction') else rf.ShareholderRegisterFilingError.forbidden())
    assert caught.value.code == expected.code
    assert db.connect_count == 0 and db.sql == []


@pytest.mark.parametrize('mode', ['preflight', 'held'])
@pytest.mark.parametrize('change', ['missing', 'foreign-company', 'foreign-year', 'foreign-actor', 'wrong-id', 'malformed-parent'])
def test_selected_parent_failure_stops_before_archive_enumeration(mode, change, monkeypatch):
    db, store, query, identity = harness(monkeypatch)
    if change == 'missing':db.parent = None
    if change == 'foreign-company':db.parent = {**db.parent, 'company_id': str(UUID(int=881))}
    if change == 'foreign-year':db.parent = {**db.parent, 'income_year': 2024}
    if change == 'foreign-actor':db.parent = {**db.parent, 'user_id': str(UUID(int=882))}
    if change == 'wrong-id':db.parent = {**db.parent, 'id': str(UUID(int=883))}
    if change == 'malformed-parent':db.parent.pop('payload_hash')
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        invoke(store, db, query, identity, mode)
    assert not any('assert_member_v1' in sql or sql.startswith('select t.*') for sql, _ in db.sql)


@pytest.mark.parametrize('mode', ['preflight', 'held'])
@pytest.mark.parametrize('change', ['missing', 'duplicate', 'changed-payload', 'changed-time'])
def test_archived_selected_row_must_match_exact_preselected_parent(mode, change, monkeypatch):
    db, store, query, identity = harness(monkeypatch)
    row = wire(db.snapshot.submission)
    if change == 'missing':rows = []
    elif change == 'duplicate':rows = [row, row]
    elif change == 'changed-payload':rows = [{**row, 'payload_hash': 'f' * 64}]
    else:rows = [{**row, 'updated_at': '2026-01-02T00:00:00Z'}]
    db.rows['production_filing_submissions'] = rows
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        invoke(store, db, query, identity, mode)
    assert any('production_filing_submissions t' in sql for sql, _ in db.sql)


@pytest.mark.parametrize('mode', ['preflight', 'held'])
def test_authorization_sql_failure_never_reads_or_enumerates_parent(mode, monkeypatch):
    db, store, query, identity = harness(monkeypatch)
    db.fail_at = 'assert_submission_v1' if mode == 'preflight' else 'lock_correction_predecessor_v1'
    # Preflight owns the transaction translator; held use delegates it to its caller.
    expected = rf.ShareholderRegisterFilingError if mode == 'preflight' else psycopg.errors.InsufficientPrivilege
    with pytest.raises(expected):
        invoke(store, db, query, identity, mode)
    assert db.fail_at in db.sql[-1][0]
    assert not any('from shareholder_register_filing.production_filing_submissions' in sql
        or 'assert_member_v1' in sql for sql, _ in db.sql)
    if mode == 'preflight':
        assert db.lifecycle[-2:] == ['transaction-exit', 'connection-exit']


@pytest.mark.parametrize('mode', ['preflight', 'held'])
def test_existing_archive_decode_error_remains_closed_and_stops_later_reads(mode, monkeypatch):
    db, store, query, identity = harness(monkeypatch)
    db.rows['filing_previews'][0].pop('issues')
    with pytest.raises(rf.ShareholderRegisterFilingError) as caught:
        invoke(store, db, query, identity, mode)
    assert caught.value.code == rf.ShareholderRegisterFilingError.unavailable().code
    assert 'from shareholder_register_filing.filing_previews' in db.sql[-1][0]
    assert not any('register_observation_withdrawals' in sql or 'production_filing_events t' in sql
        for sql, _ in db.sql)
