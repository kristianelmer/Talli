"""The diagnostic handoff cannot accept recovery or broaden restore permissions."""
import base64
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import signal
import sys
import time
from types import SimpleNamespace

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
import rf1086_actual_replay as replay
import rf1086_actual_replay_package as package
from rf1086_catalog_difference import CatalogCapture, _encoded


@pytest.fixture
def setup(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    monkeypatch.setenv('RUNNER_TEMP', str(root))
    monkeypatch.setenv('GITHUB_RUN_ID', '123')
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '1')
    monkeypatch.setenv('GITHUB_SHA', 'a' * 40)
    monkeypatch.setenv('TALLI_RF_REPLAY_DIR', str(root / 'talli-rf-replay-123-1'))
    monkeypatch.setenv('TALLI_RF_REPLAY_EXPORT_MS', '150000')
    monkeypatch.setattr(package, '_EXPORT_STARTED', None)
    package.start_export_clock()
    package.prepare()
    source = CatalogCapture(); source.capture(b'[]\n{}\n[]\n')
    failed = CatalogCapture(); failed.capture(b'[]\n{"datacl":null}\n[]\n')
    values = dict.fromkeys(('roles', 'auth', 'companyMemberships'), 'b' * 64)
    return {'roles': io.BytesIO(b'private-roles'), 'dump': io.BytesIO(b'private-archive'),
        'source': {'Id': 'a' * 64, 'Image': package.IMAGE,
            'NetworkSettings': {'Networks': {'supabase_network_owned': {}}}},
        'auth': {'Id': 'b' * 64}, 'preload': 'pg_stat_statements',
        'before': values | {'catalog': package.digest(source._raw)},
        'failed': values | {'catalog': package.digest(failed._raw)},
        'source_raw': source._raw, 'failed_raw': failed._raw,
        'causal': SimpleNamespace(replay_snapshots={'private': 'bound-snapshot'}), 'init': 'fixed init'}


def test_private_package_copies_original_descriptors_and_preserves_positions(setup, capsys):
    setup['roles'].seek(3); setup['dump'].seek(4)
    assert package.publish(**setup)
    assert (setup['roles'].tell(), setup['dump'].tell()) == (3, 4)
    path, metadata, hashed = package.read_package()
    assert (path / 'archive.dump').read_bytes() == b'private-archive'
    assert metadata['before'] == setup['before'] and metadata['failed'] == setup['failed']
    assert metadata['outerBusinessPostchecks'] is False
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in path.iterdir())
    assert path.stat().st_mode & 0o777 == 0o700
    assert hashed == package.digest((path / 'metadata.json').read_bytes())
    assert capsys.readouterr() == ('', '')
    assert not package.publish(**setup)  # Never replace a ready package.


@pytest.mark.parametrize('fault', ['unknown_budget', 'expired', 'oversized', 'missing_capture', 'mixed_failure', 'wrong_image'])
def test_no_ready_publication_on_unknown_budget_or_incomplete_binding(setup, monkeypatch, fault):
    if fault == 'unknown_budget': monkeypatch.setattr(package, '_EXPORT_STARTED', None)
    elif fault == 'expired': monkeypatch.setattr(package, '_EXPORT_STARTED', time.monotonic() - 160)
    elif fault == 'oversized': monkeypatch.setitem(package.LIMITS, 'archive.dump', 2)
    elif fault == 'missing_capture': setup['causal'].replay_snapshots = None
    elif fault == 'mixed_failure': setup['failed']['roles'] = 'c' * 64
    else: setup['source']['Image'] = 'postgres:latest'
    assert not package.publish(**setup)
    assert not (package.package_path() / 'ready.json').exists()


@pytest.mark.parametrize('fault', ['bytes', 'symlink', 'hardlink', 'mode', 'extra', 'code', 'binding'])
def test_reader_rejects_tampering_and_unsafe_files(setup, monkeypatch, tmp_path, fault):
    assert package.publish(**setup)
    path = package.package_path()
    archive = path / 'archive.dump'
    if fault == 'bytes': archive.write_bytes(b'tampered')
    elif fault == 'symlink':
        outside = tmp_path / 'outside'; outside.write_bytes(archive.read_bytes()); archive.unlink(); archive.symlink_to(outside)
    elif fault == 'hardlink': os.link(archive, tmp_path / 'second')
    elif fault == 'mode': archive.chmod(0o644)
    elif fault == 'extra': (path / 'extra').write_text('unexpected')
    elif fault == 'code': monkeypatch.setattr(package, 'code_hashes', lambda: {})
    else: monkeypatch.setenv('GITHUB_SHA', 'f' * 40)
    with pytest.raises((package.Unavailable, OSError)):
        package.read_package()


def toc(extra=()):
    rows = ['1; 0 0 ENCODING - ENCODING ', '2; 0 0 STDSTRINGS - STDSTRINGS ',
            '3; 0 0 SEARCHPATH - SEARCHPATH ', '4; 1262 5 DATABASE - postgres supabase_admin',
            '5; 2615 10 SCHEMA - graphql supabase_admin',
            '6; 2615 11 SCHEMA - graphql_public supabase_admin',
            '7; 3079 12 EXTENSION - pg_net ',
            '8; 0 0 ACL - SCHEMA graphql supabase_admin',
            '9; 0 0 TABLE DATA public fixture supabase_admin',
            '10; 3466 25 EVENT TRIGGER - fixture supabase_admin',
            '11; 0 0 COMMENT - EVENT TRIGGER fixture supabase_admin', *extra]
    return ('; TOC Entries: ' + str(len(rows)) + '\n' + '\n'.join(rows) + '\n').encode()


def test_toc_uses_global_pass_order_not_sections_and_separates_preamble():
    result = replay.toc_inventory(toc())
    assert result['total'] == 11 and result['headerCountMatches']
    assert result['passCounts'] == {'SPECIAL': 3, 'MAIN': 5, 'ACL': 1, 'POST_ACL': 2}
    assert result['scheduleSha256'] == package.digest(_encoded([4, 5, 6, 7, 9, 8, 10, 11]))
    assert result['orderGate'] == 'session_boundary_unproved'
    assert not result['writerCoverageVerified'] and not result['specialSessionEffectsVerified']


@pytest.mark.parametrize('description', ['ACL', 'COMMENT', 'SECURITY LABEL', 'DATABASE PROPERTIES'])
def test_late_database_metadata_prohibits_chunking(description):
    target = '- postgres supabase_admin' if description == 'DATABASE PROPERTIES' else '- DATABASE postgres supabase_admin'
    result = replay.toc_inventory(toc([f'12; 0 0 {description} {target}']))
    assert result['orderGate'] == 'database_metadata_after_first_cut'
    assert result['lateDatabaseEntries'] == [{'id': 12, 'description': description}]


@pytest.mark.parametrize('fault', ['count', 'duplicate', 'unknown', 'special', 'checkpoint', 'malformed'])
def test_toc_unsupported_or_incomplete_inventory_fails_closed(fault):
    raw = toc()
    if fault == 'count': raw = raw.replace(b'Entries: 11', b'Entries: 12')
    elif fault == 'duplicate': raw = raw.replace(b'11; 0 0', b'10; 0 0')
    elif fault == 'unknown': raw = raw.replace(b'TABLE DATA', b'NEW UNKNOWN')
    elif fault == 'special': raw = raw.replace(b'STDSTRINGS -', b'ENCODING -')
    elif fault == 'checkpoint': raw = raw.replace(b'- pg_net ', b'- different ')
    else: raw += b'injected invalid line\n'
    with pytest.raises(package.Unavailable): replay.toc_inventory(raw)


def test_source_presence_or_listing_failure_prevents_any_target_creation(monkeypatch):
    calls = []
    metadata = {'source': 'a' * 64, 'sourceAuth': 'b' * 64, 'sourceNetwork': 'supabase_network_owned'}
    def present(args, *_args, **_kwargs):
        calls.append(args)
        return b'a' * 64 + b'\n'
    monkeypatch.setattr(replay, 'command', present)
    with pytest.raises(package.Unavailable, match='actual_replay_unavailable'):
        replay.assert_source_absent(metadata, time.monotonic() + 5)
    assert len(calls) == 1 and calls[0][1:3] == ['container', 'ls']
    monkeypatch.setattr(replay, 'command', lambda *a, **k: b'')
    replay.assert_source_absent(metadata, time.monotonic() + 5)


def test_cleanup_never_deletes_a_foreign_resource(setup, monkeypatch):
    monkeypatch.setattr(replay, 'resource_exists', lambda *a: True)
    monkeypatch.setattr(replay, 'inspect', lambda *a: {'Name': 'foreign', 'Labels': {}})
    deleted = []
    monkeypatch.setattr(replay, 'command', lambda *a, **k: deleted.append(a))
    assert not replay.cleanup_resources(package.package_path(), time.monotonic() + 5)
    assert deleted == []


def test_cleanup_removes_partial_package_without_recursive_deletion(setup):
    path = package.package_path()
    package.write_private(path / 'archive.dump', b'incomplete-private-archive')
    replay.remove_package(path)
    assert not path.exists()


@pytest.fixture(scope='module')
def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=3072)


def aad(key):
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return {'version': 2, 'run': '123', 'attempt': '1', 'mergeSha': 'a' * 40,
            'image': package.IMAGE, 'packageSha256': 'c' * 64, 'publicKeySha256': package.digest(public)}


def test_new_protocol_encrypts_once_and_cannot_extend_legacy_three_frames(key):
    bound = aad(key)
    line = replay.seal({'private': 'canary', 'recoveryAccepted': False}, bound, key.public_key())
    assert 'canary' not in line and not line.startswith('owned_identity_catalog_causal ')
    expected = {k: v for k, v in bound.items() if k != 'version'}
    assert replay.decrypt('2026-10-12T00:00:00.000Z ' + line, key, expected)['private'] == 'canary'
    with pytest.raises(package.Unavailable): replay.decrypt(line + '\n' + line, key, expected)
    with pytest.raises(package.Unavailable): replay.decrypt(line, key, expected | {'run': '456'})
    value = json.loads(line.removeprefix(replay.TAG)); value['ciphertext'] = base64.b64encode(b'wrong').decode()
    with pytest.raises(InvalidTag): replay.decrypt(replay.TAG + _encoded(value).decode(), key, expected)


def test_command_output_and_deadline_are_bounded_without_private_errors(capsys):
    with pytest.raises(package.Unavailable):
        replay.command([sys.executable, '-c', 'print("private-canary"*10000)'], time.monotonic() + 3, cap=100)
    started = time.monotonic()
    with pytest.raises(package.Unavailable):
        replay.command([sys.executable, '-c', 'import time; time.sleep(30)'], time.monotonic() + 0.1)
    assert time.monotonic() - started < 3
    assert 'private-canary' not in str(capsys.readouterr())


def test_original_timeouts_and_failure_only_workflow_contract():
    root = Path(__file__).resolve().parents[3]
    browser = (root / 'tests/browser_shareholder_register_filing.mjs').read_text()
    workflow = (root / '.github/workflows/release-gate.yml').read_text()
    assert 'timeout: 360_000' in browser and 'timeout: 180_000' in browser
    assert "failure() && steps.rehearsal.outcome == 'failure'" in workflow
    assert workflow.index('actual_replay.py consume') < workflow.index('actual_replay.py cleanup')
    assert 'upload-artifact' not in workflow[workflow.index('  database:'):workflow.index('  evidence:')]

@pytest.mark.parametrize('fault', [None, 'archive_binding', 'initialized', 'strict_roles', 'strict_catalog', 'causal'])
def test_full_control_requires_fresh_failed_bindings_before_inventory(setup, monkeypatch, fault):
    import rf1086_identity_restore as identity
    empty = {'serverVersion': 170006, **{k: [] for k in ('schemas', 'functions', 'hooks', 'events', 'extensions')}}
    phases = {
        'source_pre_dump': {'catalog': empty, 'catalogSha256': setup['before']['catalog'],
            'sourceCommandSha256': 'c' * 64, 'files': {'status': 'unavailable'}},
        'target_initialized': {'catalog': empty, 'initSha256': package.digest(identity.INIT.encode())},
        'mismatch': {'catalog': empty, 'catalogSha256': setup['failed']['catalog'],
            'archive': {'status': 'observed', 'value': {'bytes': len(setup['dump'].getvalue()),
                'sha256': package.digest(setup['dump'].getvalue())}}}}
    setup['causal'].replay_snapshots = phases
    setup['init'] = identity.INIT
    setup['roles'] = io.BytesIO(b'CREATE ROLE supabase_admin;\nALTER ROLE supabase_admin WITH SUPERUSER;\n')
    assert package.publish(**setup)
    path, metadata, _ = package.read_package()
    commands = []
    monkeypatch.setattr(replay, 'assert_source_absent', lambda *a: None)
    monkeypatch.setattr(replay, 'start_target', lambda *a: 'e' * 64)
    monkeypatch.setattr(replay, 'installed_files', lambda *a: {})
    monkeypatch.setattr(replay, 'psql', lambda target, statement, *a, **k: commands.append(statement))
    observations = 0
    def snapshot(*a, **k):
        nonlocal observations
        observations += 1
        return empty | {'events': ['unexpected']} if (
            fault == 'initialized' and observations == 1 or fault == 'causal' and observations == 2) else empty
    monkeypatch.setattr(replay, '_snapshot', snapshot)
    def fingerprint(*a, catalog_capture, **k):
        catalog_capture.capture(setup['failed_raw'] if fault != 'strict_catalog' else b'changed')
        return metadata['failed'] | ({'roles': 'wrong'} if fault == 'strict_roles' else {})
    monkeypatch.setattr(identity, 'fingerprint', fingerprint)
    def command(args, *_a, **_k):
        commands.append(args)
        return toc() if '--list' in args else b'private-writer-sql'
    monkeypatch.setattr(replay, 'command', command)
    if fault == 'archive_binding': metadata['phases']['mismatch']['archive']['value']['sha256'] = 'f' * 64
    if fault:
        with pytest.raises(package.Unavailable): replay.replay(path, metadata, time.monotonic() + 5)
        assert not any(isinstance(c, list) and '--list' in c for c in commands)
    else:
        result = replay.replay(path, metadata, time.monotonic() + 5)
        assert result['F2EqualsF'] and result['causalSnapshotEqualsF']
        assert result['S0'] == replay.s0_protocol.unavailable('dependency', 'admission')
        assert result['Is'] == 'unavailable'
        assert result['In'] == 'archive_function_equivalence_unproved'
        assert result['netSourceAttributesObserved'] is True
        assert result['recoveryAccepted'] is result['causalAttributionAccepted'] is False
        assert commands[0] == b'ALTER ROLE supabase_admin WITH SUPERUSER;\n'
        full = [c for c in commands if isinstance(c, list) and '--dbname' in c]
        assert len(full) == 1 and full[0][-1] == 'template1'
        assert all(flag in full[0] for flag in ('--exit-on-error', '--clean', '--if-exists', '--create'))
        assert not any(isinstance(c, list) and '--use-list' in c for c in commands)


def test_real_clearing_emitter_still_publishes_after_cleanup_and_source_postcheck(setup, tmp_path, monkeypatch, capsys):
    from test_rf1086_identity_restore_runner import (
        DB, test_fresh_cluster_cleanup_is_pinned_and_source_stays_untouched as harness,
    )
    monkeypatch.setitem(DB, 'Image', package.IMAGE)
    calls = []
    def publish(inputs):
        calls.append(inputs)
        assert inputs['source_raw'] is not None and inputs['failed_raw'] is not None
        assert package.publish(**inputs)
    harness(tmp_path, monkeypatch, capsys, 'catalog', publication_probe=publish)
    assert len(calls) == 1
    path, metadata, _ = package.read_package()
    assert (path / 'ready.json').exists()
    assert metadata['identitySourcePostcheck'] is True


@pytest.mark.parametrize('raises', [False, True])
def test_docker_cleanup_failure_erases_private_files_but_retains_ownership(setup, monkeypatch, raises):
    assert package.publish(**setup)
    path = package.package_path()
    def broken(*_):
        if raises: raise package.Unavailable('command_unavailable')
        return False
    monkeypatch.setattr(replay, 'cleanup_resources', broken)
    with pytest.raises(package.Unavailable): replay.cleanup_package(path)
    assert [p.name for p in path.iterdir()] == ['owner.json']
    assert package.owner(path)['binding'] == package.binding()


def test_cleanup_status_cannot_conflict_with_the_single_encrypted_summary(key):
    bound = aad(key)
    line = replay.seal({'ownedCleanupComplete': False}, bound, key.public_key())
    status = replay.STATUS_TAG + '{"status":"unavailable"}'
    expected = {k: v for k, v in bound.items() if k != 'version'}
    assert replay.decrypt(line + '\n' + status + '\n' + status, key, expected) == {'ownedCleanupComplete': False}
    with pytest.raises(package.Unavailable): replay.decrypt(line + '\n' + line, key, expected)


def test_dynamic_owned_wrapper_import_cannot_reset_the_company_export_clock(monkeypatch):
    monkeypatch.setattr(package, '_EXPORT_STARTED', None)
    moments = iter((100.0, 160.0))
    monkeypatch.setattr(package.time, 'monotonic', lambda: next(moments))
    package.start_export_clock()
    package.start_export_clock()
    assert package._EXPORT_STARTED == 100.0
    root = Path(__file__).resolve().parents[3]
    for name in ('rehearse-rf1086-company-test-retention-restore.py', 'rehearse-rf1086-owned-restore.py'):
        source = (root / 'scripts' / name).read_text()
        assert source.index('start_export_clock()') < source.index('import argparse')


@pytest.mark.parametrize('error,expected', [
    (package.Unavailable('export_budget_exhausted'), 'export_budget_exhausted'),
    (package.Unavailable('private-canary'), 'operation_failed'),
    (ValueError('private-canary'), 'operation_failed'),
    (FileNotFoundError('private-canary'), 'private_file_missing'),
])
def test_availability_status_uses_only_finite_labels(error, expected, capsys):
    package.report_unavailable('private-canary', error)
    output = capsys.readouterr()
    assert output.out == '' and 'private-canary' not in output.err
    assert json.loads(output.err.removeprefix(package.STATUS_TAG)) == {
        'status': 'unavailable', 'action': 'operation', 'reason': expected,
    }


def test_replay_uses_shared_framed_file_observations_with_per_file_budget(monkeypatch):
    calls = []
    monkeypatch.setattr(replay.time, 'monotonic', lambda: 10)
    def command(args, deadline, *, cap):
        calls.append((deadline, cap))
        return b'UNAVAILABLE:pg_config_unavailable\n' if args[-1] == '.control' else b'OK\nprivate-canary'
    monkeypatch.setattr(replay, 'command', command)
    result = replay.installed_files('a' * 64, {'extensions': [['pg_net', '0.20.3', 'net', 'owner']]}, 30)
    assert calls == [(15, replay.FILE_OUTPUT_CAP)] * 2
    assert result['pg_net.control'] == {'status': 'unavailable', 'reason': 'pg_config_unavailable'}
    assert result['pg_net--0.20.3.sql']['sha256'] == package.digest(b'private-canary')
    assert 'private-canary' not in json.dumps(result)


@pytest.mark.parametrize('fault', ['cancel', 'deadline'])
def test_replay_file_observations_cannot_swallow_global_deadline_or_cancel(monkeypatch, fault):
    ticks = [10]
    monkeypatch.setattr(replay.time, 'monotonic', lambda: ticks[0])
    def command(*a, **k):
        if fault == 'cancel': raise KeyboardInterrupt()
        ticks[0] = 31
        raise ValueError('private-canary')
    monkeypatch.setattr(replay, 'command', command)
    with pytest.raises(KeyboardInterrupt if fault == 'cancel' else ValueError):
        replay.installed_files('a' * 64, {'extensions': [['pg_net', '0.20.3', 'net', 'owner']]}, 30)
