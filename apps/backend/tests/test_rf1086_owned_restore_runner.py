"""RF restoration can only create and remove its own fresh disposable database."""
import importlib.util
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('rf_restore_runner', ROOT / 'scripts/rehearse-rf1086-owned-restore.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


@pytest.mark.parametrize('failure', [None, 'pg_dump', 'createdb', 'pg_restore', 'verification', 'memberships'])
def test_owned_restore_cleans_only_the_created_database_and_preserves_failures(monkeypatch, failure):
    checks = []
    monkeypatch.setattr(runner.boundary, 'owned_source', lambda *args: ('pinned-container', 'postgres'))
    monkeypatch.setattr(runner.boundary, 'verify_source_session', lambda *args: checks.append(args))
    memberships = iter([['original'], ['changed' if failure == 'memberships' else 'original']])
    monkeypatch.setattr(runner.boundary, 'role_memberships', lambda *_: next(memberships))
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        assert args[:4] == ['docker', 'exec', '-i', 'pinned-container']
        if args[4] == failure:
            raise subprocess.CalledProcessError(1, args)
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(runner.subprocess, 'run', run)
    def execute():
        with runner.restored_database('postgresql://postgres:local@127.0.0.1:55001/postgres', '/explicit-owned-workdir') as restored:
            clone = runner.boundary.conninfo_to_dict(restored)['dbname']
            assert clone.startswith('rf193_restore_') and len(clone) == len('rf193_restore_') + 32
            if failure == 'verification':
                raise ValueError('verification failed')
    if failure in ('pg_dump', 'createdb', 'pg_restore'):
        with pytest.raises(subprocess.CalledProcessError): execute()
    elif failure == 'verification':
        with pytest.raises(ValueError, match='verification failed'): execute()
    elif failure == 'memberships':
        with pytest.raises(RuntimeError, match='cluster role memberships'): execute()
    else:
        execute()
    assert len(checks) == 1
    creates = [args for args, _ in calls if args[4] == 'createdb']
    drops = [args for args, _ in calls if args[4] == 'dropdb']
    assert len(drops) == (0 if failure in ('pg_dump', 'createdb') else 1)
    if drops:
        assert drops[0][-1] == creates[0][-1]
        assert drops[0][-1] != 'postgres'
    restores = [args for args, _ in calls if args[4] == 'pg_restore']
    for args in restores:
        assert '--exit-on-error' in args
        assert '--no-owner' not in args and '--no-acl' not in args


def test_source_boundary_failure_prevents_all_docker_commands(monkeypatch):
    def invalid(*_): raise ValueError('not owned')
    monkeypatch.setattr(runner.boundary, 'owned_source', invalid)
    monkeypatch.setattr(runner.subprocess, 'run', lambda *_args, **_kwargs: pytest.fail('Reached Docker mutation'))
    with pytest.raises(ValueError, match='not owned'):
        with runner.restored_database('remote', '/wrong'):
            pytest.fail('Created a target')


@pytest.mark.parametrize('change', [None, {'user': 'postgres'}, {'host': 'remote'},
    {'port': '55002'}, {'dbname': 'another'}, {'hostaddr': '192.0.2.1'}])
def test_reader_uses_only_existing_backend_credentials_on_the_owned_endpoint(change):
    source = 'postgresql://postgres:local@127.0.0.1:55001/postgres'
    reader = runner.make_conninfo(source, user='talli_ledger_backend', password='disposable')
    if change:
        with pytest.raises(ValueError, match='existing backend role'):
            runner.owner_read_url(source, runner.make_conninfo(reader, **change))
    else:
        assert runner.owner_read_url(source, reader) == reader


def test_company_access_reader_keeps_the_same_boundary_and_cannot_select_an_admin():
    source = 'postgresql://postgres:local@127.0.0.1:55001/postgres'
    reader = runner.make_conninfo(source, user='talli_company_access_backend', password='disposable')
    assert runner.owner_read_url(source, reader, 'talli_company_access_backend') == reader
    with pytest.raises(ValueError, match='existing backend role'):
        runner.owner_read_url(source, source, 'postgres')
