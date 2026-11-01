"""Policy/custody interfaces only; no database, owner credentials or execution."""
from copy import deepcopy
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest

from talli_backend.adapters.hosted_recovery_capture import digest, encoded
from talli_backend.adapters.hosted_recovery_owner_policy import (
    MAX_MANIFEST, MAX_SQL, export_request, policy_contract, policy_status, read_request,
)


def native(sql, *, tag='objects original_read', owner='supabase_storage_admin', nonce='ABC'):
    return (f'-- PostgreSQL database dump\n\\restrict {nonce}\n'
        'SET statement_timeout = 0;\nSET lock_timeout = 0;\nSET client_encoding = \'UTF8\';\n'
        "SELECT pg_catalog.set_config('search_path', '', false);\n\n"
        f'--\n-- Name: {tag}; Type: POLICY; Schema: storage; Owner: {owner}\n--\n\n'
        f'{sql}\n\n--\n-- PostgreSQL database dump complete\n--\n\\unrestrict {nonce}\n').encode()


@pytest.fixture
def captured():
    catalog = {'policies': [['storage', 'objects', 'original_read', 'PERMISSIVE',
        ['reader', 'reviewer'], 'SELECT', "(name = 'literal;not SQL')", None]],
        'rls': [['storage', 'objects', True, False, 'supabase_storage_admin']]}
    sql = ("CREATE POLICY original_read ON storage.objects FOR SELECT TO reader, reviewer "
        "USING ((name = 'literal;not SQL'));\n")
    return SimpleNamespace(catalog=catalog, commitment=digest(b'original capture')), SimpleNamespace(policies=native(sql)), sql.encode()


@pytest.fixture
def binding(captured):
    capture, program, _ = captured
    return {'version': 1, 'attemptId': str(uuid4()), 'planSha256': digest(b'plan'),
        'captureSha256': capture.commitment, 'preparedSha256': digest(b'prepared'),
        'policySha256': policy_contract(capture, program)['policySha256'],
        'target': {'project': 'b' * 20, 'organization': 'c' * 20,
            'name': 'owned local fictional target', 'region': 'eu-west-1'},
        'targetIdentity': {'kind': 'owned-local-native-v2', 'target': str(uuid4()),
            'systemIdentifier': '7348112577', 'database': 'postgres',
            'databaseImage': 'sha256:' + 'd' * 64}}


def manifest_from(metadata):
    return {key: value for key, value in metadata.items()
        if key not in ('requestSha256', 'manifestSha256', 'directory')}


def test_status_normalizes_roles_and_keywords_without_changing_expressions(captured):
    capture, _, _ = captured
    actual = deepcopy(capture.catalog)
    actual['policies'][0][3:6] = ['permissive', ['reviewer', 'reader'], 'select']
    assert policy_status(capture, actual) == ()
    assert capture.catalog['policies'][0][4] == ['reader', 'reviewer']


def test_missing_is_the_only_allowed_relaxation(captured):
    capture, _, _ = captured
    actual = deepcopy(capture.catalog); actual['policies'] = []
    assert policy_status(capture, actual, allow_missing=True) == (('storage', 'objects', 'original_read'),)
    with pytest.raises(ValueError, match='owner_policy_missing'):
        policy_status(capture, actual)
    actual['rls'][0][4] = 'postgres'
    with pytest.raises(ValueError, match='rls_or_owner_changed'):
        policy_status(capture, actual, allow_missing=True)


@pytest.mark.parametrize('fault', ['extra', 'name', 'roles', 'command', 'permissive', 'qual',
    'check', 'owner', 'rls', 'force_rls', 'missing_rls', 'duplicate', 'duplicate_rls'])
def test_status_rejects_conflicting_or_unknown_inventory(captured, fault):
    capture, _, _ = captured; actual = deepcopy(capture.catalog)
    row = actual['policies'][0]
    if fault == 'extra': actual['policies'].append([*row[:2], 'unexpected', *row[3:]])
    elif fault == 'name': row[2] = 'changed'
    elif fault == 'roles': row[4] = ['reader']
    elif fault == 'command': row[5] = 'ALL'
    elif fault == 'permissive': row[3] = 'RESTRICTIVE'
    elif fault == 'qual': row[6] = 'true'
    elif fault == 'check': row[7] = 'true'
    elif fault == 'owner': actual['rls'][0][4] = 'postgres'
    elif fault == 'rls': actual['rls'][0][2] = False
    elif fault == 'force_rls': actual['rls'][0][3] = True
    elif fault == 'missing_rls': actual['rls'] = []
    elif fault == 'duplicate': actual['policies'].append(deepcopy(row))
    else: actual['rls'].append(deepcopy(actual['rls'][0]))
    with pytest.raises(ValueError, match='hosted_owner_policy_'):
        policy_status(capture, actual, allow_missing=True)


@pytest.mark.parametrize('value', [None, [], [None], [[]], [[None] * 8],
    [['storage', 'objects', 'read', 'PERMISSIVE', None, 'SELECT', None, None]]])
def test_malformed_catalog_has_a_bounded_error(captured, value):
    capture, _, _ = captured
    actual = deepcopy(capture.catalog)
    if value is None: actual = None
    else: actual['policies'] = value
    with pytest.raises(ValueError, match='hosted_owner_policy_'):
        policy_status(capture, actual)


def test_contract_preserves_native_ddl_and_ignores_random_client_framing(captured):
    capture, program, body = captured
    contract = policy_contract(capture, program)
    assert contract == {'policySha256': digest(body), 'bytes': len(body),
        'owners': ['supabase_storage_admin'],
        'policyIdentities': [['storage', 'objects', 'original_read']]}
    assert policy_contract(capture, SimpleNamespace(policies=native(body.decode(), nonce='RANDOM321'))) == contract


@pytest.mark.parametrize('permissive,command,roles,qual,check,clauses', [
    ('PERMISSIVE', 'ALL', ['public'], None, None, ''),
    ('RESTRICTIVE', 'UPDATE', ['reader'], 'true', 'false',
        ' AS RESTRICTIVE FOR UPDATE TO reader USING (true) WITH CHECK (false)'),
    ('PERMISSIVE', 'INSERT', ['reader'], None, 'true', ' FOR INSERT TO reader WITH CHECK (true)'),
])
def test_contract_matches_captured_policy_variants(captured, permissive, command, roles, qual, check, clauses):
    capture, _, _ = captured
    capture.catalog['policies'][0][3:] = [permissive, roles, command, qual, check]
    body = 'CREATE POLICY original_read ON storage.objects' + clauses + ';\n'
    assert policy_contract(capture, SimpleNamespace(policies=native(body)))['policySha256'] == digest(body.encode())


def test_contract_preserves_every_policy_and_native_declaration_order(captured):
    capture, program, first = captured
    second = b'CREATE POLICY original_insert ON storage.objects FOR INSERT TO reader WITH CHECK (true);\n'
    capture.catalog['policies'].append(['storage', 'objects', 'original_insert', 'PERMISSIVE',
        ['reader'], 'INSERT', None, 'true'])
    raw = program.policies.replace(b'-- PostgreSQL database dump complete',
        b'-- Name: objects original_insert; Type: POLICY; Schema: storage; Owner: -\n--\n' +
        second + b'\n-- PostgreSQL database dump complete')
    contract = policy_contract(capture, SimpleNamespace(policies=raw))
    assert contract['policySha256'] == digest(first + second)
    assert contract['policyIdentities'] == [['storage', 'objects', 'original_insert'],
        ['storage', 'objects', 'original_read']]


@pytest.mark.parametrize('fault', ['grant', 'alter_owner', 'password', 'client_command',
    'changed_expression', 'changed_roles', 'changed_header', 'wrong_owner', 'missing', 'duplicate'])
def test_export_refuses_anything_except_the_captured_native_policy(captured, binding, tmp_path, fault):
    capture, program, body = captured
    raw = program.policies
    extras = {'grant': 'GRANT ALL ON storage.objects TO reader;',
        'alter_owner': 'ALTER TABLE storage.objects OWNER TO postgres;',
        'password': "ALTER ROLE reader PASSWORD 'never-export-this';",
        'client_command': '\\connect another_database'}
    if fault in extras: raw = native(body.decode() + extras[fault])
    elif fault == 'changed_expression': raw = native(body.decode().replace("(name = 'literal;not SQL')", 'true'))
    elif fault == 'changed_roles': raw = native(body.decode().replace('reader, reviewer', 'public'))
    elif fault == 'changed_header': raw = native(body.decode(), tag='objects other_read')
    elif fault == 'wrong_owner': raw = native(body.decode(), owner='postgres')
    elif fault == 'missing': raw = b''
    else:
        raw = raw.replace(b'-- PostgreSQL database dump complete',
            b'-- Name: objects original_read; Type: POLICY; Schema: storage; Owner: supabase_storage_admin\n--\n' + body)
    with pytest.raises(ValueError, match='hosted_'):
        export_request(capture, SimpleNamespace(policies=raw), binding, tmp_path / 'request')
    assert not (tmp_path / 'request').exists()


def test_request_round_trip_has_exact_inventory_and_private_modes(captured, binding, tmp_path):
    capture, program, body = captured; destination = tmp_path / 'request'
    metadata = export_request(capture, program, binding, destination)
    manifest, sql = read_request(destination, metadata['requestSha256'], binding=binding)
    assert sql == body and manifest == manifest_from(metadata)
    assert metadata['directory'] == str(destination)
    assert metadata['manifestSha256'] == metadata['requestSha256']
    assert manifest['policySha256'] == binding['policySha256']
    assert {p.name for p in destination.iterdir()} == {'request.json', 'policies.sql'}
    assert destination.stat().st_mode & 0o777 == 0o700
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in destination.iterdir())


def test_lost_response_retry_returns_complete_exact_request_without_rewriting(captured, binding, tmp_path):
    capture, program, body = captured; destination = tmp_path / 'request'
    first = export_request(capture, program, binding, destination)
    before = {p.name: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns, p.stat().st_ctime_ns)
        for p in destination.iterdir()}
    program.policies = native(body.decode(), nonce='NEWRESTRICT123')
    assert export_request(capture, program, binding, destination) == first
    assert before == {p.name: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns, p.stat().st_ctime_ns)
        for p in destination.iterdir()}


@pytest.mark.parametrize('fault', ['partial', 'policy_bytes', 'binding', 'contract_owner', 'contract_identity'])
def test_export_retry_refuses_partial_or_conflicting_request_without_rewriting(captured, binding, tmp_path, fault):
    capture, program, _ = captured; destination = tmp_path / 'request'
    metadata = export_request(capture, program, binding, destination)
    if fault == 'partial': (destination / 'policies.sql').unlink()
    elif fault == 'policy_bytes': (destination / 'policies.sql').write_bytes(b'conflicting policy')
    elif fault == 'binding': binding['preparedSha256'] = digest(b'another checkpoint')
    else:
        manifest = manifest_from(metadata)
        if fault == 'contract_owner': manifest['contract']['owners'] = ['postgres']
        else: manifest['contract']['policyIdentities'][0][2] = 'other_policy'
        (destination / 'request.json').write_bytes(encoded(manifest))
    before = {p.name: p.read_bytes() for p in destination.iterdir()}
    with pytest.raises((ValueError, OSError)):
        export_request(capture, program, binding, destination)
    assert before == {p.name: p.read_bytes() for p in destination.iterdir()}


@pytest.mark.parametrize('field', ['attemptId', 'planSha256', 'captureSha256', 'preparedSha256',
    'policySha256', 'target', 'targetIdentity'])
def test_request_is_bound_to_every_prepared_identity(captured, binding, tmp_path, field):
    capture, program, _ = captured; destination = tmp_path / 'request'
    metadata = export_request(capture, program, binding, destination)
    changed = deepcopy(binding)
    if field == 'attemptId': changed[field] = str(uuid4())
    elif field == 'target': changed[field]['project'] = 'z' * 20
    elif field == 'targetIdentity': changed[field]['systemIdentifier'] = '1'
    else: changed[field] = digest(b'different independently reviewed checkpoint')
    with pytest.raises(ValueError, match='binding_changed'):
        read_request(destination, metadata['requestSha256'], binding=changed)


@pytest.mark.parametrize('fault', ['unknown_field', 'version_bool', 'uuid', 'hash', 'target',
    'password', 'url', 'callback', 'deep', 'oversize'])
def test_binding_rejects_unbounded_or_credential_shaped_metadata(captured, binding, tmp_path, fault):
    capture, program, _ = captured; changed = deepcopy(binding)
    if fault == 'unknown_field': changed['executor'] = 'not allowed'
    elif fault == 'version_bool': changed['version'] = True
    elif fault == 'uuid': changed['attemptId'] = 'not a uuid'
    elif fault == 'hash': changed['preparedSha256'] = '0' * 63
    elif fault == 'target': changed['target'] = []
    elif fault == 'password': changed['targetIdentity']['password'] = 'never accepted'
    elif fault == 'url': changed['targetIdentity']['endpoint'] = 'postgresql://never-accepted'
    elif fault == 'callback': changed['targetIdentity']['executor'] = lambda: None
    elif fault == 'deep': changed['targetIdentity'] = {'a': {'b': {'c': {'d': {'e': 'too deep'}}}}}
    else: changed['targetIdentity']['image'] = 'x' * 1025
    with pytest.raises(ValueError, match='hosted_owner_policy_'):
        export_request(capture, program, changed, tmp_path / 'request')
    assert not (tmp_path / 'request').exists()


@pytest.mark.parametrize('field,value', [
    ('kind', 'hosted'), ('target', 'not-a-uuid'), ('database', 'other_database'),
    ('databaseImage', 'unpinned:latest'), ('systemIdentifier', 'not-decimal'),
    ('systemIdentifier', str(2**64)), ('systemIdentifier', '001'),
])
def test_v2_identity_is_exactly_bounded_local_metadata(captured, binding, tmp_path, field, value):
    capture, program, _ = captured
    binding['targetIdentity'][field] = value
    with pytest.raises(ValueError, match='hosted_owner_policy_'):
        export_request(capture, program, binding, tmp_path / 'request')
    assert not (tmp_path / 'request').exists()


def test_export_requires_the_original_capture_commitment(captured, binding, tmp_path):
    capture, program, _ = captured
    binding['captureSha256'] = digest(b'different capture')
    with pytest.raises(ValueError, match='binding_changed'):
        export_request(capture, program, binding, tmp_path / 'request')
    assert not (tmp_path / 'request').exists()


@pytest.mark.parametrize('fault', ['sql', 'manifest', 'request_pin', 'extra', 'file_mode',
    'dir_mode', 'hardlink', 'symlink', 'sql_bound', 'manifest_bound'])
def test_read_refuses_tampering_inventory_permissions_and_link_changes(captured, binding, tmp_path, fault):
    capture, program, _ = captured; destination = tmp_path / 'request'
    metadata = export_request(capture, program, binding, destination)
    pin = metadata['requestSha256']; member = destination / 'policies.sql'
    if fault == 'sql': member.write_bytes(b'GRANT ALL ON storage.objects TO reader;')
    elif fault == 'manifest': (destination / 'request.json').write_bytes(b'{}')
    elif fault == 'request_pin': pin = digest(b'wrong pin')
    elif fault == 'extra': (destination / 'unexpected').write_bytes(b'no')
    elif fault == 'file_mode': member.chmod(0o640)
    elif fault == 'dir_mode': destination.chmod(0o750)
    elif fault == 'hardlink': os.link(member, tmp_path / 'second-link')
    elif fault == 'symlink':
        other = tmp_path / 'other'; member.rename(other); member.symlink_to(other)
    elif fault == 'sql_bound':
        with member.open('wb') as output: output.truncate(MAX_SQL + 1)
    else:
        with (destination / 'request.json').open('wb') as output: output.truncate(MAX_MANIFEST + 1)
    with pytest.raises((ValueError, OSError)):
        read_request(destination, pin, binding=binding)


def test_changed_binding_cannot_be_blessed_by_repinning_manifest(captured, binding, tmp_path):
    capture, program, _ = captured; destination = tmp_path / 'request'
    metadata = export_request(capture, program, binding, destination)
    manifest = manifest_from(metadata)
    manifest['binding']['preparedSha256'] = digest(b'forged')
    raw = encoded(manifest); (destination / 'request.json').write_bytes(raw)
    with pytest.raises(ValueError, match='binding_changed'):
        read_request(destination, digest(raw), binding=binding)


def test_repinning_sql_and_manifest_cannot_replace_independent_policy_pin(captured, binding, tmp_path):
    capture, program, _ = captured; destination = tmp_path / 'request'
    metadata = export_request(capture, program, binding, destination)
    manifest = manifest_from(metadata)
    changed = b'CREATE POLICY unexpected ON storage.objects USING (true);\n'
    manifest['contract']['policySha256'] = digest(changed)
    manifest['contract']['bytes'] = len(changed)
    (destination / 'policies.sql').write_bytes(changed)
    raw = encoded(manifest); (destination / 'request.json').write_bytes(raw)
    with pytest.raises(ValueError, match='sql_changed'):
        read_request(destination, digest(raw), binding=binding)


def test_request_refuses_foreign_uid(captured, binding, tmp_path, monkeypatch):
    capture, program, _ = captured; destination = tmp_path / 'request'
    metadata = export_request(capture, program, binding, destination)
    original_uid = os.getuid()
    monkeypatch.setattr(os, 'getuid', lambda: original_uid + 1)
    with pytest.raises(ValueError, match='directory_invalid'):
        read_request(destination, metadata['requestSha256'], binding=binding)


def test_export_rejects_symlinked_destination_and_ancestry(captured, binding, tmp_path):
    capture, program, _ = captured
    real = tmp_path / 'real'; real.mkdir(mode=0o700)
    link = tmp_path / 'linked'; link.symlink_to(real, target_is_directory=True)
    for destination in (link, link / 'request'):
        with pytest.raises(ValueError, match='path_invalid'):
            export_request(capture, program, binding, destination)
    assert list(real.iterdir()) == []


def test_read_detects_destination_swap_during_member_open(captured, binding, tmp_path, monkeypatch):
    capture, program, _ = captured; destination = tmp_path / 'request'
    metadata = export_request(capture, program, binding, destination)
    original_open = os.open
    swapped = []
    def swap(path, flags, *args, **kwargs):
        fd = original_open(path, flags, *args, **kwargs)
        if path == 'policies.sql' and not swapped:
            destination.rename(tmp_path / 'original')
            destination.mkdir(mode=0o700)
            swapped.append(True)
        return fd
    monkeypatch.setattr(os, 'open', swap)
    with pytest.raises(ValueError, match='directory_changed'):
        read_request(destination, metadata['requestSha256'], binding=binding)
