"""Owned synthetic clients only: exercise real expiry before nested driver unwind."""
import asyncio
from contextlib import contextmanager
from pathlib import Path
import signal
import sys
import time
from types import SimpleNamespace

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
import rf1086_restore_control as control


def budget():
    return control.RecoveryBudget(time.monotonic())


class Transaction:
    def __init__(self, connection): self.connection = connection
    def __enter__(self): return self
    def __exit__(self, kind, error, traceback):
        if not self.connection.closed:
            self.connection.events.append('rollback')
            if error is not None and not signal.getitimer(signal.ITIMER_REAL)[0]:
                # Finite stand-in for an otherwise unbounded rollback socket wait.
                self.connection.events.append('unbounded_exit')
                time.sleep(.08)
        return False


class Connection:
    def __init__(self, value, wait=.25):
        self.budget = value
        self.wait = wait
        self.events = []
        self.closed = False
        self.expiry = None
    def __enter__(self): return self
    def __exit__(self, kind, error, traceback):
        if not self.closed:
            self.events.append('connection_exit')
            if error is not None and not signal.getitimer(signal.ITIMER_REAL)[0]:
                self.events.append('unbounded_exit')
                time.sleep(.08)
        self.close()
    def close(self):
        if not self.closed: self.events.append('close')
        self.closed = True
    def transaction(self, **kwargs): return Transaction(self)
    def execute(self, query, *args, **kwargs):
        if query == 'synthetic_block':
            try: time.sleep(self.wait)
            except BaseException as error:
                self.expiry = error
                raise
        return self
    def fetchall(self): return []


def test_real_expiry_closes_before_delegated_transaction_exit(monkeypatch):
    value = budget(); connection = Connection(value)
    # No connection acquisition is performed: isolate the already-owned wait.
    monkeypatch.setattr(control, 'deadline_dsn', lambda dsn, budget: dsn)
    value.end = time.monotonic() + .02
    with pytest.raises(control.RestoreUnavailable) as caught:
        with control.bounded_connection(lambda *a, **k: connection, 'dbname=postgres', budget=value) as db:
            with db.transaction(force_rollback=True):
                db.execute('synthetic_block')
    assert caught.value is connection.expiry
    assert connection.closed and 'unbounded_exit' not in connection.events
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0


def test_cancel_identity_closes_before_nested_exit():
    value = budget(); connection = Connection(value); original = KeyboardInterrupt('synthetic')
    with pytest.raises(KeyboardInterrupt) as caught:
        with control.bounded_connection(lambda *a, **k: connection, 'dbname=postgres', budget=value) as db:
            with db.transaction(force_rollback=True): raise original
    assert caught.value is original
    assert connection.events == ['close']


def test_expected_constraint_error_keeps_live_ordinary_rollback():
    value = budget(); connection = Connection(value); original = psycopg.errors.ForeignKeyViolation('synthetic')
    with control.bounded_connection(lambda *a, **k: connection, 'dbname=postgres', budget=value) as db:
        with pytest.raises(psycopg.errors.ForeignKeyViolation) as caught:
            with db.transaction(force_rollback=True): raise original
        assert caught.value is original and connection.events == ['rollback'] and not connection.closed
        with db.transaction(force_rollback=True): db.execute('synthetic_read')
    assert connection.events == ['rollback', 'rollback', 'connection_exit', 'close']


def adapter_operation(kind, connect):
    from talli_backend.adapters.supabase_company_access import SupabaseCompanyAccessAdapter, SupabaseConfiguration
    from talli_backend.adapters.supabase_ledger import SupabaseLedgerAdapter, LedgerSupabaseConfiguration
    if kind == 'company':
        adapter = SupabaseCompanyAccessAdapter(SupabaseConfiguration('http://127.0.0.1', 'synthetic', 'dbname=postgres'), connect=connect)
        async def verified(_): return 'synthetic-actor', {}
        adapter._verified_actor_context = verified
        return adapter._database_rows('synthetic-token', 'synthetic_block')
    adapter = SupabaseLedgerAdapter(LedgerSupabaseConfiguration('http://127.0.0.1', 'synthetic', 'dbname=postgres'), connect=connect)
    async def verified(_): return SimpleNamespace(actor_id=SimpleNamespace(subject='synthetic-actor'), claims_json='{}')
    adapter._verified_actor = verified
    async def query():
        session = await adapter.session('synthetic-token')
        assert session._connect is connect
        return await session._database_rows('synthetic_block')
    return query()


@pytest.mark.parametrize('kind', ['company', 'ledger'])
def test_actual_adapter_inline_callback_expiry_skips_nested_rollbacks(kind):
    # Real run_async admission reserve fits; no mocked clock/driver/context order.
    value = budget(); value.end = time.monotonic() + 2.1
    connection = Connection(value, wait=3)
    acquire = control.connection_factory(value, connect=lambda *a, **k: connection)
    with pytest.raises(control.RestoreUnavailable) as caught:
        control.run_async(adapter_operation(kind, acquire), budget=value)
    assert caught.value.reason == 'deadline'
    assert connection.expiry is caught.value
    assert connection.events == ['close'] and connection.closed
    assert not control._IO_CONNECTIONS.get()
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0


@pytest.mark.parametrize('number', [signal.SIGTERM, signal.SIGINT])
@pytest.mark.parametrize('secondary', [False, True])
def test_signal_closes_before_driver_cancel_and_preserves_identity(number, secondary):
    value = budget(); original = KeyboardInterrupt('owned-cancel'); events = []
    class Driver(Connection):
        def execute(self, query, *args):
            if query == 'synthetic_cancel':
                try: signal.raise_signal(number)
                except KeyboardInterrupt:
                    if not self.closed:
                        events.append('driver_cancel_wait')
                        time.sleep(.08)
                    if secondary: raise OSError('synthetic closed driver')
                    raise
            return self
    connection = Driver(value)
    previous = signal.getsignal(number)
    def terminate(*_): raise original
    signal.signal(number, terminate)
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            with control.bounded_connection(lambda *a, **k: connection, 'dbname=postgres', budget=value) as db:
                with db.transaction(): db.execute('synthetic_cancel')
        assert signal.getsignal(number) is terminate
    finally: signal.signal(number, previous)
    assert caught.value is original and not events and connection.events == ['close']


def test_expiry_close_secondary_driver_error_cannot_replace_first_failure(monkeypatch):
    value = budget(); value.end = time.monotonic() + .02
    monkeypatch.setattr(control, 'deadline_dsn', lambda dsn, budget: dsn)
    class Driver(Connection):
        def execute(self, *args):
            try: return super().execute(*args)
            except control.RestoreUnavailable:
                assert self.closed
                raise OSError('synthetic driver notices closed PGconn')
    connection = Driver(value)
    with pytest.raises(control.RestoreUnavailable) as caught:
        with control.bounded_connection(lambda *a, **k: connection, 'dbname=postgres', budget=value) as db:
            with db.transaction(): db.execute('synthetic_block')
    assert caught.value is connection.expiry and connection.events == ['close']


def test_close_failure_is_uncertain_and_keeps_primary_before_nested_exit():
    value = budget(); original = KeyboardInterrupt('owned-cancel')
    class Broken(Connection):
        def close(self): raise OSError('synthetic close failure')
    connection = Broken(value)
    with pytest.raises(KeyboardInterrupt) as caught:
        with control.bounded_connection(lambda *a, **k: connection, 'dbname=postgres', budget=value) as db:
            with db.transaction(): raise original
    assert caught.value is original and value.context.owner.uncertain
    assert connection.events == [] and not control._IO_CONNECTIONS.get()


def test_expiry_inside_positive_transaction_exit_closes_before_suppressed_driver_error():
    value = budget(); events = []
    class Commit:
        def __enter__(self): return self
        def __exit__(self, *args):
            try:
                signal.setitimer(signal.ITIMER_REAL, .02)
                time.sleep(.2)
            except Exception as primary:
                # psycopg transaction cleanup may catch Exception and log it.
                events.append(primary)
                assert connection.closed
    connection = Connection(value)
    connection.transaction = lambda **kwargs: Commit()
    with pytest.raises(control.RestoreUnavailable) as caught:
        with control.bounded_connection(lambda *a, **k: connection, 'dbname=postgres', budget=value) as db:
            with db.transaction(force_rollback=True): pass
    assert len(events) == 1 and caught.value is events[0]
    assert connection.events == ['close']


def test_default_factories_remain_lazy_and_documents_forwards_injection():
    from talli_backend.adapters.supabase_company_access import SupabaseCompanyAccessAdapter, SupabaseConfiguration
    from talli_backend.adapters.supabase_ledger import SupabaseLedgerAdapter, LedgerSupabaseConfiguration
    from talli_backend.adapters.supabase_documents import SupabaseDocumentsAdapter, DocumentsSupabaseConfiguration
    assert SupabaseCompanyAccessAdapter(SupabaseConfiguration('', ''))._connect is None
    assert SupabaseLedgerAdapter(LedgerSupabaseConfiguration('', '', ''))._connect is None
    acquire = control.connection_factory(budget(), connect=lambda *a, **k: pytest.fail('constructor must not connect'))
    documents = SupabaseDocumentsAdapter(DocumentsSupabaseConfiguration('', '', '', '', ''), connect=acquire)
    assert documents._authentication._connect is acquire
    assert documents._authorization._gateway._connect is acquire
