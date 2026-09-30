"""The browser fault barrier cannot release or fabricate a prepared send grant."""
import asyncio
from pathlib import Path
import runpy
import tempfile
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
install = runpy.run_path(str(ROOT / 'tests/fixtures/start_shareholder_register_filing_backend.py'))['install_prepared_stop']


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
