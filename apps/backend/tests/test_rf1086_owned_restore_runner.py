"""RF restoration can only create and remove its own fresh disposable database."""
import importlib.util
from pathlib import Path
import subprocess
import time

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


@pytest.mark.parametrize('retained', [False, True])
def test_download_verification_precedes_every_owned_restore_resource(monkeypatch, tmp_path, retained):
    # Both main calls below share this one synthetic invocation clock.
    monkeypatch.setattr(runner, '_RECOVERY_STARTED', time.monotonic())
    from test_rf1086_retained_archive_stream_adversarial import legacy_case
    from test_rf1086_archive_stream import download as legacy_download
    from rf1086_retained_stream_fixture import retained_stream_fixture
    from test_rf1086_retained_archive_stream import download, query
    if retained:
        archive, originals = retained_stream_fixture(status='accepted', bound_feedback=True)
        content, _ = download(archive, originals)
    else:
        archive, factory, actor = legacy_case(5)
        content = legacy_download(archive, factory, actor)
    path = tmp_path / 'retained-download.ndjson'
    path.write_bytes(content)
    source = 'postgresql://postgres:local@127.0.0.1:55001/postgres'
    monkeypatch.setenv('DATABASE_URL', source)
    monkeypatch.setenv('TALLI_SUPABASE_WORKDIR', '/explicit-owned-workdir')
    monkeypatch.setenv('TALLI_LEDGER_DATABASE_URL', runner.make_conninfo(source, user='talli_ledger_backend'))
    monkeypatch.setattr(runner.sys, 'argv', ['restore', str(path), '--company-id', str(archive.company_id),
        '--income-year', str(int(archive.income_year)), '--actor-id', str(query(archive).actor_id.subject)])
    reached = []
    def stop(*args):
        reached.append(args)
        raise RuntimeError('verified download reached ownership boundary')
    monkeypatch.setattr(runner.boundary, 'owned_source', stop)
    monkeypatch.setattr(runner.subprocess, 'run', lambda *_a, **_k: pytest.fail('Reached resource mutation'))
    with pytest.raises(RuntimeError, match='verified download reached ownership boundary'):
        runner.main()
    assert len(reached) == 1 and path.read_bytes() == content
    reached.clear()
    path.write_bytes(content[:-1])
    from talli_backend.modules.documents.public import DocumentsError
    with pytest.raises(DocumentsError) as failed:
        runner.main()
    assert type(failed.value) is DocumentsError
    assert reached == [] and path.read_bytes() == content[:-1]


@pytest.mark.parametrize('retained', [False, True])
def test_source_and_restored_comparison_use_the_downloads_owned_canonical_codec(monkeypatch, retained):
    import asyncio
    from test_rf1086_retained_archive_stream_adversarial import legacy_case
    from rf1086_retained_stream_fixture import retained_stream_fixture
    from test_rf1086_retained_archive_stream import query
    from test_rf1086_archive_storage_v6 import forbid_fresh
    from talli_backend.modules.shareholder_register_filing import public as rf
    if retained:
        archive, originals = retained_stream_fixture(amendments=2, status='accepted', bound_feedback=True)
        codec = 'rf1086-production-stream-v2'
        expected = rf.serialize_rf1086_archive_v6(archive, query=query(archive))
        forbid_fresh(monkeypatch)
    else:
        archive, _, _ = legacy_case(5)
        originals = {}
        codec = 'rf1086-production-stream-v1'
        expected = rf.serialize_rf1086_archive(archive, query=query(archive))
    class Owner:
        async def archive_source(self, requested):
            if requested.actor_id != query(archive).actor_id:
                raise rf.ShareholderRegisterFilingError.not_found()
            return archive
    monkeypatch.setattr(runner, 'owner_session', lambda *_: Owner())
    assert asyncio.run(runner.canonical('owned', query(archive), stream_codec=codec)) == (expected, archive)
    async def contents(*_): return list(originals.values())
    monkeypatch.setattr(runner, 'read_originals', contents)
    assert asyncio.run(runner.verify_restored('restored', query(archive), expected,
        list(originals.values()), (), stream_codec=codec)) == archive
    with pytest.raises(ValueError):
        asyncio.run(runner.canonical('owned', query(archive), stream_codec='unknown'))
    with pytest.raises(ValueError, match='differs from the downloaded archive'):
        asyncio.run(runner.verify_restored('restored', query(archive), '{}',
            list(originals.values()), (), stream_codec=codec))
