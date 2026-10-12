"""Rejected restores expose bound grant evidence without accepting equivalence."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
import rf1086_catalog_difference as catalog
import rf1086_catalog_semantics as evidence


def capture(rows):
    result = catalog.CatalogCapture()
    result.capture(('\n'.join(json.dumps(x) for x in [rows, {}, []]) + '\n').encode())
    return result


@pytest.fixture
def pair():
    source = ['relation', 'private-schema', 'private-table', 'r', 'private-owner', '{private-acl}', True, True]
    target = source.copy()
    target[5] = None
    grants = [['private-owner', False, 'private-owner', 'SELECT', False]]
    def observed(row):
        return {'serverVersion': 170006, 'functions': [], 'acls': [{
            'identity': row[:3], 'row': row, 'defaults': '{private-acl}',
            'default_grants': deepcopy(grants), 'grants': deepcopy(grants)}]}
    return capture([source]), capture([target]), observed(source), observed(target)


def report(pair):
    source, target, left, right = pair
    before, after, selected = evidence._selected(source, target)
    return evidence._acl_report(before, after, selected, left, right)


def test_null_target_expansion_is_bound_to_both_exact_catalog_rows(pair):
    result = report(pair)
    assert result['selected'] == 1
    assert result['counts'] == {'rawDefaultEqual': 1, 'defaultGrantsEqual': 1,
                                'targetGrantsEqual': 1, 'different': 0, 'unsupported': 0}
    assert result['rows'][0][1:] == [True, True, True]
    assert 'private-' not in json.dumps(result)


@pytest.mark.parametrize('change', ['grantor', 'grantee', 'public', 'privilege', 'option', 'duplicate'])
def test_grant_differences_cannot_disappear_in_sorting_or_public_role_names(pair, change):
    grants = pair[2]['acls'][0]['grants']
    if change == 'duplicate':
        grants.append(grants[0].copy())
    else:
        index, value = {'grantor': (0, 'other'), 'grantee': (2, 'PUBLIC'),
                        'public': (1, True), 'privilege': (3, 'UPDATE'), 'option': (4, True)}[change]
        grants[0][index] = value
        if change == 'public':
            grants[0][2] = None
    result = report(pair)
    assert result['counts']['different'] == 1
    assert result['rows'][0][2:] == [False, False]


@pytest.mark.parametrize('side', [2, 3])
@pytest.mark.parametrize('change', ['row', 'boolean_as_integer', 'missing', 'duplicate', 'extra', 'dangling', 'bad_public'])
def test_live_drift_incomplete_coverage_and_unresolved_roles_are_unavailable(pair, side, change):
    rows = pair[side]['acls']
    if change == 'row':
        rows[0]['row'] = rows[0]['row'][:-1] + [False]
    elif change == 'boolean_as_integer':
        rows[0]['row'] = rows[0]['row'][:-1] + [1]
    elif change == 'missing':
        rows.clear()
    elif change == 'duplicate':
        rows.append(deepcopy(rows[0]))
    elif change == 'extra':
        extra = deepcopy(rows[0]); extra['identity'][-1] = 'extra'; rows.append(extra)
    elif change == 'dangling':
        rows[0]['grants'][0][0] = None
    else:
        rows[0]['grants'][0][1] = True
    with pytest.raises(ValueError, match='unavailable'):
        report(pair)


def test_unsupported_relation_kind_is_not_default_equivalent(pair):
    pair[2]['acls'][0]['defaults'] = None
    pair[3]['acls'][0]['defaults'] = None
    result = report(pair)
    assert result['counts']['unsupported'] == 1
    assert result['counts']['targetGrantsEqual'] == 0


def test_selected_limit_rejects_whole_capture(monkeypatch, pair):
    monkeypatch.setattr(evidence, 'MAX_SELECTED', 0)
    with pytest.raises(ValueError, match='unavailable'):
        evidence._selected(pair[0], pair[1])


def test_grant_order_changes_preserve_multiplicity(pair):
    for side in pair[2:]:
        for field in ['grants', 'default_grants']:
            side['acls'][0][field].append(['private-owner', True, None, 'INSERT', True])
    pair[3]['acls'][0]['grants'].reverse()
    assert report(pair)['counts']['targetGrantsEqual'] == 1


def test_all_106_identities_fit_without_silently_truncating(pair):
    source_rows, target_rows, source_observed, target_observed = [], [], [], []
    for index in range(106):
        for side, rows, observations in [(2, source_rows, source_observed), (3, target_rows, target_observed)]:
            item = deepcopy(pair[side]['acls'][0])
            item['identity'][-1] = item['row'][2] = f'private-table-{index}'
            rows.append(item['row']); observations.append(item)
    result = report((capture(source_rows), capture(target_rows),
                     {'acls': source_observed}, {'acls': target_observed}))
    assert result['selected'] == result['counts']['targetGrantsEqual'] == 106
    identities = [row[0] for row in result['rows']]
    assert identities == sorted(set(identities))
    assert len(json.dumps(result).encode()) < 13 * 1024


def test_emitter_shields_diagnostic_failures_and_does_not_clear_retained_bytes(monkeypatch, capsys, pair):
    def broken(*args, **kwargs):
        raise RuntimeError('private-secret')
    monkeypatch.setattr(evidence, '_read', broken)
    evidence.emit_catalog_semantics(pair[0], pair[1], source='a'*64, target='b'*64,
                                   image='sha256:'+'c'*64, dump=io.BytesIO())
    raw = capsys.readouterr().err
    assert json.loads(raw.removeprefix(evidence.TAG)) == {'status': 'unavailable', 'qualification': evidence.QUALIFICATION}
    assert pair[0]._raw is not None and pair[1]._raw is not None


@pytest.mark.parametrize('overflow', [False, True])
def test_emitter_keeps_acl_evidence_when_net_is_missing_and_caps_entire_output(monkeypatch, capsys, pair, overflow):
    calls = iter(pair[2:])
    monkeypatch.setattr(evidence, '_read', lambda *args, **kwargs: next(calls))
    if overflow:
        monkeypatch.setattr(evidence, 'MAX_OUTPUT_BYTES', 200)
    evidence.emit_catalog_semantics(pair[0], pair[1], source='a'*64, target='b'*64,
                                   image='sha256:'+'c'*64, dump=io.BytesIO())
    raw = capsys.readouterr().err
    assert 'private-' not in raw
    result = json.loads(raw.removeprefix(evidence.TAG))
    assert result['status'] == ('unavailable' if overflow else 'observed')
    if not overflow:
        assert result['acl']['counts']['targetGrantsEqual'] == 1
        assert result['net']['status'] == result['archive']['status'] == 'unavailable'
        assert result['sourceCatalogSha256'] == hashlib.sha256(pair[0]._raw).hexdigest()


def toc(entries=''):
    count = 1 + sum(bool(line) and not line.startswith(';') for line in entries.splitlines())
    return (f'; TOC Entries: {count}\n; Format: CUSTOM\n'
            '; Dumped from database version: 17.6\n; Dumped by pg_dump version: 17.6\n'
            '; Selected TOC Entries:\n;\n1; 3079 500 EXTENSION - pg_net owner\n' + entries).encode()


def test_toc_exact_type_only_function_mapping_excludes_acl_comment_and_overloads():
    raw = toc('2; 1255 501 FUNCTION net http_get(text, jsonb, jsonb, integer) owner\n'
              '3; 0 0 ACL net FUNCTION http_post(text, jsonb, jsonb, jsonb, integer) owner\n'
              '4; 0 0 COMMENT net FUNCTION http_post(text, jsonb, jsonb, jsonb, integer) owner\n'
              '5; 1255 502 FUNCTION net http_post(text) owner\n')
    result = evidence._toc_report(raw, ['owner', 'owner'])
    assert result['functionDefinitionEntries'] == [1, 0]
    assert result['pgNetExtensionEntries'] == 1


def test_verbose_toc_accepts_sparse_ids_and_dependency_comments():
    raw = toc('9001; 0 0 ENCODING - ENCODING \n;\tdepends on: 1\n'
              '19004; 0 0 STDSTRINGS - STDSTRINGS \n')
    result = evidence._toc_report(raw, ['owner', 'owner'])
    assert result['completeTocEntries'] == 3
    assert result['functionDefinitionEntries'] == [0, 0]


@pytest.mark.parametrize('entries', [
    'malformed\n', '2; 0 501 FUNCTION net http_get(text, jsonb, jsonb, integer) owner\n',
    '2; 1255 501 FUNCTION net http_get(text, jsonb, jsonb, integer) wrong_owner\n',
    '2; 1255 501 FUNCTION net http_get(text, jsonb, jsonb, integer) owner\n'
    '3; 1255 502 FUNCTION net http_get(text, jsonb, jsonb, integer) owner\n',
    '2; 1255 501 FUNCTION net other() owner\n2; 1255 502 FUNCTION net another() owner\n',
])
def test_toc_ambiguity_is_not_reported_as_absence(entries):
    with pytest.raises(ValueError, match='unavailable'):
        evidence._toc_report(toc(entries), ['owner', 'owner'])


def test_net_binding_records_observation_time_and_rejects_wrong_input_types():
    rows, observed = [], []
    for identity, types in zip(evidence.NET_IDENTITIES, evidence.NET_TYPES, strict=True):
        row = identity + ['owner', None, True, '{search_path=net}']
        rows.append(row)
        observed.append({'identity': identity, 'row': row, 'extensions': [['pg_net', '0.19.5', 'owner']],
                         'types': [['pg_catalog', name] for name in types], 'definition': 'private-definition'})
    before = catalog._records(capture(rows))
    side = {'functions': observed}
    result = evidence._net_report(before, before, side, side)
    assert result['observation'] == 'after-restore-not-proof-of-pre-dump-state'
    assert all(row['source']['configurationIsSearchPathNet'] for row in result['functions'])
    assert 'private-definition' not in json.dumps(result)
    observed[0]['types'][0] = ['public', 'text']
    with pytest.raises(ValueError, match='unavailable'):
        evidence._net_report(before, before, side, side)


def test_archive_hash_and_position_use_exact_input_and_versions(monkeypatch):
    rows = [identity + ['owner', None, True, None] for identity in evidence.NET_IDENTITIES]
    before = catalog._records(capture(rows))
    archive = io.BytesIO(b'private-exact-archive'); archive.seek(3)
    def command(args, deadline, **kwargs):
        if '--list' in args:
            assert kwargs['archive'].read() == b'private-exact-archive'
            return toc()
        return (args[3] + ' (PostgreSQL) 17.6\n').encode()
    monkeypatch.setattr(evidence, '_command', command)
    result = evidence._archive_report(archive, 'source', 'target', before, time.monotonic()+5)
    assert archive.tell() == 3
    assert result['sha256'] == hashlib.sha256(b'private-exact-archive').hexdigest()


def test_archive_position_cleanup_cannot_mask_cancellation(monkeypatch):
    interruption = KeyboardInterrupt()
    class Archive(io.BytesIO):
        def seek(self, position, *args):
            if position == 3: raise OSError('private-seek-error')
            return super().seek(position, *args)
    archive = Archive(b'private-archive')
    archive.read(3)
    def interrupt(*args, **kwargs): raise interruption
    monkeypatch.setattr(evidence, '_command', interrupt)
    with pytest.raises(KeyboardInterrupt) as error:
        evidence._archive_report(archive, 'source', 'target', {}, time.monotonic()+1)
    assert error.value is interruption


@pytest.mark.parametrize('code', [
    "import sys; sys.stdout.buffer.write(b'x'*33)",
    "import sys; sys.stderr.buffer.write(b'x'*65537)",
    "import time; time.sleep(10)",
])
def test_command_overflow_and_timeout_reap_owned_client(monkeypatch, code):
    real = subprocess.Popen
    children = []
    def create(*args, **kwargs):
        child = real(*args, **kwargs); children.append(child); return child
    monkeypatch.setattr(evidence.subprocess, 'Popen', create)
    monkeypatch.setattr(evidence, 'MAX_BYTES', 32)
    with pytest.raises((ValueError, subprocess.TimeoutExpired)):
        evidence._command([sys.executable, '-c', code], time.monotonic()+0.3)
    assert children and all(child.poll() is not None for child in children)


def test_command_drains_input_stdout_and_stderr_without_deadlock():
    data = b'x'*100000
    code = "import sys; sys.stderr.write('e'*60000); sys.stdout.buffer.write(sys.stdin.buffer.read())"
    assert evidence._command([sys.executable, '-c', code], time.monotonic()+3, data=data) == data


def test_cancellation_reaps_client_and_is_not_swallowed(monkeypatch):
    real = subprocess.Popen
    children = []
    def create(*args, **kwargs):
        child = real(*args, **kwargs); children.append(child); return child
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt()
    monkeypatch.setattr(evidence.subprocess, 'Popen', create)
    # Patch the active platform class, including Linux CI's EpollSelector.
    monkeypatch.setattr(evidence.selectors.DefaultSelector, 'select', interrupt)
    with pytest.raises(KeyboardInterrupt):
        evidence._command([sys.executable, '-c', 'import time; time.sleep(10)'], time.monotonic()+3)
    assert children[0].poll() is not None


@pytest.mark.parametrize('cleanup_failure', ['wait', 'close', 'selector'])
def test_cleanup_failure_cannot_replace_user_cancellation(monkeypatch, cleanup_failure):
    interruption = KeyboardInterrupt()
    closed = []
    class Stream:
        def __init__(self, name): self.name = name
        def fileno(self): return 100
        def close(self):
            closed.append(self.name)
            if cleanup_failure == 'close': raise OSError('private-cleanup-error')
    class Child:
        stdin, stdout, stderr = Stream('stdin'), Stream('stdout'), Stream('stderr')
        def poll(self): return None
        def kill(self): pass
        def wait(self, timeout):
            if cleanup_failure == 'wait': raise subprocess.TimeoutExpired('private-command', timeout)
            return -9
    class Selector:
        def __enter__(self): return self
        def __exit__(self, *_): self.close()
        def close(self):
            if cleanup_failure == 'selector': raise OSError('private-selector-error')
        def register(self, *_): raise interruption
    monkeypatch.setattr(evidence.subprocess, 'Popen', lambda *a, **kw: Child())
    monkeypatch.setattr(evidence.selectors, 'DefaultSelector', Selector)
    monkeypatch.setattr(evidence.os, 'set_blocking', lambda *a: None)
    with pytest.raises(KeyboardInterrupt) as error:
        evidence._command(['unused'], time.monotonic()+1)
    assert error.value is interruption
    assert closed == ['stdin', 'stdout', 'stderr']


@pytest.mark.parametrize('raw', [
    b'; Dumped from database version: 17.6\n; Dumped by pg_dump version: 17.6\n',
    b'; TOC Entries: 2\n; Format: CUSTOM\n; Dumped from database version: 17.6\n'
    b'; Dumped by pg_dump version: 17.6\n; Selected TOC Entries:\n1; 3079 500 EXTENSION - pg_net owner\n',
])
def test_incomplete_toc_cannot_be_reported_as_zero_function_definitions(raw):
    with pytest.raises(ValueError, match='unavailable'):
        evidence._toc_report(raw, ['owner', 'owner'])
