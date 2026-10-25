"""The browser fault barrier cannot release or fabricate a prepared send grant."""
import asyncio
import ast
from contextlib import asynccontextmanager
from pathlib import Path
import runpy
import tempfile
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
install = runpy.run_path(str(ROOT / 'tests/fixtures/start_shareholder_register_filing_backend.py'))['install_prepared_stop']
LAUNCHER = ROOT / 'tests/fixtures/start_shareholder_register_filing_backend.py'


def launcher_body():
    return next(node.body for node in ast.parse(LAUNCHER.read_text()).body
        if isinstance(node, ast.FunctionDef) and node.name == 'main')


def test_browser_launcher_selects_actual_v3_factory_not_base_adapter():
    from talli_backend.adapters.postgres_shareholder_register_filing import PostgresShareholderRegisterSourceDispatchV3Adapter
    body = launcher_body()
    imports = [node for node in body if isinstance(node, ast.ImportFrom)
        and node.module == 'talli_backend.adapters.postgres_shareholder_register_filing']
    namespace = {}
    exec(compile(ast.Module(body=imports, type_ignores=[]), str(LAUNCHER), 'exec'), namespace)
    call = next(node.value for node in body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == 'rf' for target in node.targets))
    # Resolve the actual constructor expression; do not launch main, Auth, SQL or a server.
    selected = eval(compile(ast.Expression(call.func), str(LAUNCHER), 'eval'), namespace)
    assert selected is PostgresShareholderRegisterSourceDispatchV3Adapter


@pytest.mark.parametrize('operation', ['post_underskjema:holder', 'confirm'])
def test_actual_v3_browser_barrier_waits_after_both_scope_exits(monkeypatch, capsys, operation):
    from talli_backend.application.shareholder_register_source_dispatch import _AdmittedJournal
    from talli_backend.application.shareholder_register_source_dispatch_v3 import _OperationJournalV3
    old_prepare = _AdmittedJournal.prepare
    # Track both classes so even a regression to the old hook cannot leak into another test.
    for journal in (_AdmittedJournal, _OperationJournalV3):
        monkeypatch.setattr(journal, 'prepare', journal.prepare)
    events = []
    result = SimpleNamespace(newly_prepared=True)
    claim = SimpleNamespace(submission_id=SimpleNamespace(value='owned-submission'))
    class Session:
        @asynccontextmanager
        async def source_operation_recovery_v3(self, actual):
            assert actual is claim
            events.append('history-enter')
            try:
                yield self
            finally:
                events.append('history-exit')
        async def read_operation_recovery(self):
            return SimpleNamespace(assessment=SimpleNamespace(disposition='current_admission_required',
                pending_operation=operation, operation_id=None),
                retained_archive=SimpleNamespace(production_events=()))
        @asynccontextmanager
        async def fresh_operation_admission_v3(self):
            events.append('fresh-enter')
            try:
                yield self
            finally:
                events.append('fresh-exit')
        async def prepare_child_operation_v3(self, actual, **kwargs):
            assert actual is claim and kwargs['document_name'] == 'underskjema_holder'
            events.append('prepare')
            return result
        async def prepare_confirm_operation_v3(self, actual, **kwargs):
            assert actual is claim
            events.append('prepare')
            return result
    with tempfile.TemporaryDirectory(prefix='talli-rf-prepared-crash-') as directory:
        path = Path(directory) / 'stop-after-prepare'
        path.write_text('nonce:' + operation.split(':')[0])
        statement = next(node for node in launcher_body() if isinstance(node, ast.If)
            and isinstance(node.test, ast.Name) and node.test.id == 'prepared_stop')
        exec(compile(ast.Module(body=[statement], type_ignores=[]), str(LAUNCHER), 'exec'),
            {'prepared_stop': str(path), 'nonce': 'nonce', 'install_prepared_stop': install})
        assert _AdmittedJournal.prepare is old_prepare
        journal = _OperationJournalV3(None, Session(), 'synthetic-token', claim, object(), 'correlation')
        async def run():
            task = asyncio.create_task(journal.prepare(submission_id='owned-submission', name=operation,
                body_hash='a'*64, idempotency_key='operation-key'))
            await asyncio.sleep(0)
            assert events == ['history-enter', 'history-exit', 'history-enter', 'fresh-enter',
                'prepare', 'fresh-exit', 'history-exit']
            assert not task.done() and not path.exists()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert (await journal.prepare(submission_id='owned-submission', name=operation,
                body_hash='a'*64, idempotency_key='operation-key')) is result
        asyncio.run(run())
        assert capsys.readouterr().out == 'TALLI_RF_PREPARED_STOP:nonce:' + operation.split(':')[0] + '\n'


@pytest.mark.parametrize('operation', ['post_hovedskjema', 'post_underskjema:holder', 'confirm'])
def test_barrier_stops_only_after_original_prepare_returns_and_consumes_its_arm(operation, capsys):
    calls = []
    class Journal:
        async def prepare(self, **_):
            calls.append('committed')
            return SimpleNamespace(newly_prepared=True)
    with tempfile.TemporaryDirectory(prefix='talli-rf-prepared-crash-') as directory:
        path = Path(directory) / 'stop-after-prepare'
        path.write_text('nonce:' + operation.split(':')[0])
        install(Journal, str(path), 'nonce')
        async def run():
            async def send():
                await Journal().prepare(name=operation)
                calls.append('grant-delivered')
            task = asyncio.create_task(send())
            await asyncio.sleep(0)
            assert calls == ['committed'] and not task.done()
            assert not path.exists()
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
            assert calls == ['committed']
            # Restart sees a consumed arm, so the fixture cannot hold a later call.
            assert (await Journal().prepare(name=operation)).newly_prepared
        asyncio.run(run())
        assert capsys.readouterr().out == 'TALLI_RF_PREPARED_STOP:nonce:' + operation.split(':')[0] + '\n'


@pytest.mark.parametrize('arm,newly', [('other:post_hovedskjema', True), ('nonce:confirm', True), ('nonce:post_hovedskjema', False)])
def test_barrier_does_not_intercept_another_arm_or_an_existing_operation(arm, newly, capsys):
    class Journal:
        async def prepare(self, **_): return SimpleNamespace(newly_prepared=newly)
    with tempfile.TemporaryDirectory(prefix='talli-rf-prepared-crash-') as directory:
        path = Path(directory) / 'stop-after-prepare'
        path.write_text(arm)
        install(Journal, str(path), 'nonce')
        assert asyncio.run(Journal().prepare(name='post_hovedskjema')).newly_prepared is newly
        assert path.read_text() == arm
        assert capsys.readouterr().out == ''


def test_failed_prepare_never_signals_a_committed_grant(capsys):
    class Journal:
        async def prepare(self, **_): raise ValueError('commit failed')
    with tempfile.TemporaryDirectory(prefix='talli-rf-prepared-crash-') as directory:
        path = Path(directory) / 'stop-after-prepare'
        path.write_text('nonce:post_hovedskjema')
        install(Journal, str(path), 'nonce')
        with pytest.raises(ValueError, match='commit failed'):
            asyncio.run(Journal().prepare(name='post_hovedskjema'))
        assert path.exists() and capsys.readouterr().out == ''


def test_invalid_control_path_never_installs_a_hook(tmp_path):
    class Journal:
        async def prepare(self, **_): pass
    original = Journal.prepare
    with pytest.raises(ValueError, match='control_path_invalid'):
        install(Journal, str(tmp_path / 'stop-after-prepare'), 'nonce')
    assert Journal.prepare is original
