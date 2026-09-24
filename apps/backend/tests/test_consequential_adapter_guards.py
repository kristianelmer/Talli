"""Command adapters select fresh snapshots and guard before their local row locks."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from talli_backend.adapters.postgres_shareholder_register_filing import PostgresShareholderRegisterFilingSession
from talli_backend.adapters.supabase_documents import SupabaseDocumentsPersistence
from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration, _VerifiedActor
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ActorId, ActorKind, UserId


class Connection:
    def __init__(self):
        self.queries = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    def transaction(self):
        return self

    async def execute(self, query, parameters=()):
        self.queries.append((query, parameters))
        return self

    async def fetchall(self):
        return []


def actor():
    return _VerifiedActor(ActorId(ActorKind.USER, UserId(str(uuid4()))), '{}')


def rf_session():
    return PostgresShareholderRegisterFilingSession(
        LedgerSupabaseConfiguration('', '', 'postgresql://unused'), actor(),
        access_token='', billing=None, documents=None, company_access=None, environment={},
    )


@pytest.mark.parametrize('operation,expected', [
    ('mutation', 'read committed'), ('production', 'read committed'),
    ('snapshot', 'repeatable read'), ('documents', 'read committed'),
])
def test_adapters_choose_isolation_before_role_or_evidence_reads(monkeypatch, operation, expected):
    db = Connection()
    async def connect(*args, **kwargs):
        return db
    monkeypatch.setattr('psycopg.AsyncConnection.connect', connect)
    store = SupabaseDocumentsPersistence('postgresql://unused', actor(), {}) if operation == 'documents' else rf_session()
    async def run():
        if operation == 'production':
            await store._rows('select 1')
        elif operation == 'documents':
            async with store._transaction():
                pass
        else:
            async with store._transaction(snapshot=operation == 'snapshot'):
                pass
    asyncio.run(run())
    assert db.queries[0] == ('set transaction isolation level ' + expected, ())
    assert db.queries[1][0].startswith('set local role ')


@pytest.mark.parametrize('method,basis_method,guard', [
    ('record_preview', '_opening_basis', 'lock_company_write_v1'),
    ('record_simulation', '_simulation_basis', 'lock_preview_write_v1'),
    ('record_approval', '_approval_basis', 'lock_preview_write_v1'),
])
def test_rf_commands_guard_before_basis_row_locks_and_reject_changed_basis(method, basis_method, guard):
    store, db = rf_session(), Connection()
    @asynccontextmanager
    async def transaction():
        yield db
    async def basis(connection, *args, lock=False):
        assert lock is True
        assert connection is db
        assert len(db.queries) == 1
        assert guard in db.queries[0][0]
        return 'changed evidence'
    store._transaction = transaction
    setattr(store, basis_method, basis)
    command = SimpleNamespace(actor_id=store.actor_id, company_id=uuid4(), preview_id=uuid4(), opening_snapshot_id=uuid4())
    with pytest.raises(rf.ShareholderRegisterFilingError):
        asyncio.run(getattr(store, method)(command, SimpleNamespace(basis='prepared evidence')))
    assert len(db.queries) == 1  # no persisted command after stale evidence
