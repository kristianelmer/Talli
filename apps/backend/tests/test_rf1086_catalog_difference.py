"""Catalog diagnostics distinguish failures without publishing catalog values."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
import rf1086_catalog_difference as diagnostic
import rf1086_identity_restore as identity


ROWS = [
    ['schema', 'auth', 'private-owner', None],
    ['relation', 'auth', 'private-table', 'r', 'private-owner', None, True, True],
    ['function', 'public', 'private-function', 'private-argument text', 'private-owner', None, True, None],
    ['default_acl', 'private-owner', 'public', 'r', '{private-acl}'],
    ['column_acl', 'auth', 'private-table', 'private-column', '{private-acl}'],
    ['policy', 'auth', 'private-table', 'private-policy', '*', True, ['private-role'], 'private-using', None],
]


def raw(rows=None, database=None, settings=None):
    return ('\n'.join(json.dumps(part, ensure_ascii=False) for part in [
        deepcopy(ROWS) if rows is None else rows,
        {'datname': 'postgres', 'datacl': None, 'owner': 'private-owner'} if database is None else database,
        [['postgres', 'private-role', ['private-key=private-value']]] if settings is None else settings,
    ]) + '\n').encode('utf-8')


def captured(value):
    result = diagnostic.CatalogCapture()
    result.capture(value)
    return result


@pytest.mark.parametrize(('row_index', 'field_index', 'field', 'replacement'), [
    (0, 2, 'owner', 'another-owner'), (0, 3, 'acl', '{secret-acl}'),
    (1, 3, 'kind', 'v'), (1, 4, 'owner', 'another-owner'), (1, 5, 'acl', '{secret-acl}'),
    (1, 6, 'rls', False), (1, 7, 'force_rls', False),
    (2, 4, 'owner', 'another-owner'), (2, 5, 'acl', '{secret-acl}'),
    (2, 6, 'security_definer', False), (2, 7, 'configuration', '{secret-setting}'),
    (3, 4, 'acl', '{secret-acl}'), (4, 4, 'acl', '{secret-acl}'),
    (5, 4, 'command', 'r'), (5, 5, 'permissive', False),
    (5, 6, 'roles', ['another-role']), (5, 7, 'using', 'secret-predicate'),
    (5, 8, 'with_check', 'secret-predicate'),
])
def test_every_catalog_attribute_has_an_exact_closed_field_label(row_index, field_index, field, replacement):
    changed = deepcopy(ROWS)
    changed[row_index][field_index] = replacement
    result = diagnostic.catalog_difference(captured(raw()), captured(raw(changed)))
    assert result['counts'] == {'changed': 1, 'source-only': 0, 'target-only': 0}
    item, = result['details']
    assert item['kind'] == ROWS[row_index][0]
    assert item['fields'] == [{'field': field, 'change': 'source-null' if ROWS[row_index][field_index] is None else 'value'}]
    assert len(item['identitySha256']) == 64
    rendered = json.dumps(result)
    assert 'private-' not in rendered and 'secret-' not in rendered and 'another-' not in rendered


@pytest.mark.parametrize('kind', ['schema', 'relation', 'function', 'default_acl', 'column_acl', 'policy'])
def test_missing_and_extra_records_preserve_kind_and_identity_without_names(kind):
    row = next(row for row in ROWS if row[0] == kind)
    baseline = raw(rows=[row], settings=[])
    empty = raw(rows=[], settings=[])
    removed = diagnostic.catalog_difference(captured(baseline), captured(empty))
    added = diagnostic.catalog_difference(captured(empty), captured(baseline))
    assert removed['counts']['source-only'] == added['counts']['target-only'] == 1
    assert removed['details'][0]['kind'] == kind
    assert removed['details'][0]['identitySha256'] == added['details'][0]['identitySha256']
    assert removed['details'][0]['fields'] == added['details'][0]['fields'] == []
    assert 'private-' not in json.dumps([removed, added])


@pytest.mark.parametrize(('before', 'after', 'expected'), [
    ({'datacl': None}, {'datacl': ['secret-acl']}, [('datacl', 'source-null')]),
    ({'datcollversion': 'private-version'}, {'datcollversion': None}, [('datcollversion', 'target-null')]),
    ({'datconnlimit': -1}, {'datconnlimit': 10}, [('datconnlimit', 'value')]),
    ({'datcollversion': 'private-version'}, {}, [('datcollversion', 'target-field-missing')]),
    ({}, {'datcollversion': 'private-version'}, [('datcollversion', 'source-field-missing')]),
    ({'private-database-field': 'private-value'}, {'private-database-field': 'another-value'}, [('unclassified', 'value')]),
    ({'datacl': ['private-a', 'private-b']}, {'datacl': ['private-b', 'private-a']}, [('datacl', 'array-order-only')]),
])
def test_database_fields_are_typed_and_unknown_names_are_not_rendered(before, after, expected):
    result = diagnostic.catalog_difference(captured(raw(database=before)), captured(raw(database=after)))
    assert [(v['field'], v['change']) for v in result['details'][0]['fields']] == expected
    assert result['details'][0]['kind'] == 'database'
    assert 'private-' not in json.dumps(result) and 'another-' not in json.dumps(result)


@pytest.mark.parametrize('order_only', [False, True])
def test_database_role_settings_never_publish_role_or_guc_values(order_only):
    old = [['postgres', 'private-actor', ['private-a=secret-a', 'private-b=secret-b']]]
    new = deepcopy(old)
    new[0][2] = list(reversed(new[0][2])) if order_only else ['private-a=secret-replacement']
    result = diagnostic.catalog_difference(captured(raw(settings=old)), captured(raw(settings=new)))
    assert result['details'][0]['kind'] == 'database_role_setting'
    assert result['details'][0]['fields'] == [{'field': 'settings', 'change': 'array-order-only' if order_only else 'value'}]
    assert 'private-' not in json.dumps(result) and 'secret-' not in json.dumps(result)


def test_identical_bytes_and_representation_differences_do_not_change_acceptance():
    source = raw()
    assert diagnostic.catalog_difference(captured(source), captured(source))['status'] == 'equal'
    reordered = raw(list(reversed(ROWS)))
    result = diagnostic.catalog_difference(captured(source), captured(reordered))
    assert result['status'] == 'representation-only' and result['details'] == []
    assert hashlib.sha256(source).digest() != hashlib.sha256(reordered).digest()
    assert result['qualification'] == 'diagnostic-only-strict-fingerprint-unchanged'


@pytest.mark.parametrize('separator', ['\u0085', '\u2028', '\u2029'])
def test_valid_unicode_inside_json_does_not_split_psql_records(separator):
    value = raw(rows=[['schema', 'private' + separator + 'name', 'owner', None]])
    assert diagnostic.catalog_difference(captured(value), captured(value))['status'] == 'equal'
    assert diagnostic.catalog_difference(captured(value), captured(value.removesuffix(b'\n')))['status'] == 'representation-only'


def test_detail_order_is_deterministic_and_record_counts_survive_truncation():
    rows = [['schema', f'private-schema-{i}', 'private-owner', None] for i in range(80)]
    removed = diagnostic.catalog_difference(captured(raw(rows)), captured(raw(rows=[])))
    reversed_input = diagnostic.catalog_difference(captured(raw(list(reversed(rows)))), captured(raw(rows=[])))
    assert removed == reversed_input
    assert removed['counts']['source-only'] == 80
    assert len(removed['details']) == 32 and removed['truncated']
    assert all(v['schema'] == 'unclassified' for v in removed['details'])
    assert 'private-' not in json.dumps(removed)


def test_output_byte_limit_includes_tag_and_newline(monkeypatch, capsys):
    monkeypatch.setattr(diagnostic, 'MAX_OUTPUT_BYTES', 1000)
    rows = [['schema', f'private-schema-{i}', 'private-owner', None] for i in range(80)]
    source, target = captured(raw(rows)), captured(raw(rows=[]))
    diagnostic.emit_catalog_difference(source, target)
    output = capsys.readouterr().err
    assert len(output.encode()) <= 1000
    result = json.loads(output.removeprefix('owned_identity_catalog_difference '))
    assert result['truncated'] and result['counts']['source-only'] == 80
    assert source._raw is target._raw is None


@pytest.mark.parametrize('invalid', [
    b'', b'[]\n{}\n', b'[]\n{}\n[]\n[]\n', b'\xff\n{}\n[]\n',
    b'[]\n{"owner":"secret-a","owner":"secret-b"}\n[]\n',
    b'[]\n{"owner":NaN}\n[]\n', b'[]\n{"owner":1.5}\n[]\n',
    raw(rows=[['private-kind', 'private-name']]),
    raw(rows=[['schema', 'private-name', 'private-owner']]),
    raw(rows=[ROWS[0], ROWS[0]]),
    raw(rows=[['schema', None, 'private-owner', None]]),
    raw(rows=[['schema', 'auth', True, None]]),
    raw(rows=[['relation', 'auth', 'private-table', 'r', 'owner', None, 0, True]]),
    raw(database={'datallowconn': 0}), raw(database={'datconnlimit': False}),
    raw(database={'datacl': 'private-acl'}),
    raw(settings=[['postgres', 'private-role', ['a=secret']], ['postgres', 'private-role', ['b=secret']]]),
    raw(settings=[['postgres', 'private-role', 'secret-not-array']]),
    raw(rows={'private-key': 'private-value'}), raw(database=[]), raw(settings={}),
])
def test_malformed_or_ambiguous_capture_emits_only_fixed_unavailable(invalid, capsys):
    source, target = captured(raw()), captured(invalid)
    diagnostic.emit_catalog_difference(source, target)
    output = capsys.readouterr().err
    assert json.loads(output.removeprefix('owned_identity_catalog_difference ')) == {
        'status': 'unavailable', 'qualification': 'diagnostic-only-strict-fingerprint-unchanged'}
    assert source._raw is target._raw is None


def test_capture_limit_is_utf8_bytes_and_does_not_copy_or_accept_one_more_byte(monkeypatch, capsys):
    value = raw(rows=[['schema', 'private-Æ', 'owner', None]])
    monkeypatch.setattr(diagnostic, 'MAX_CAPTURE_BYTES', len(value))
    source = captured(value)
    assert source._raw is value
    target = captured(value + b' ')
    assert target._raw is None
    diagnostic.emit_catalog_difference(source, target)
    assert '"status":"unavailable"' in capsys.readouterr().err


def test_record_limit_counts_catalog_database_and_settings(monkeypatch, capsys):
    monkeypatch.setattr(diagnostic, 'MAX_RECORDS', 3)
    exact = captured(raw(rows=[ROWS[0]]))
    assert diagnostic.catalog_difference(exact, exact)['sourceRecords'] == 3
    diagnostic.emit_catalog_difference(exact, captured(raw(rows=[ROWS[0], ROWS[1]])))
    assert '"status":"unavailable"' in capsys.readouterr().err


@pytest.mark.parametrize('restored', [False, True])
def test_fingerprint_hashes_and_captures_the_same_query_bytes_once(monkeypatch, restored):
    catalog = raw()
    calls = []
    def query(container, statement, **kwargs):
        calls.append((container, statement, kwargs))
        if statement == identity.ROLE_SQL: return b'private-role-attributes\n'
        if statement == identity.CATALOG_SQL: return catalog
        if 'from pg_tables' in statement: return b'[]\n'
        return b'private-membership-rows\n'
    monkeypatch.setattr(identity, 'query', query)
    monkeypatch.setattr(identity, 'source_query', query)
    capture = diagnostic.CatalogCapture()
    result = identity.fingerprint('owned-container', restored=restored, bootstrap='supabase_admin', catalog_capture=capture)
    assert capture._raw is catalog
    assert result == {'roles': hashlib.sha256(b'private-role-attributes\n').hexdigest(),
        'catalog': hashlib.sha256(catalog).hexdigest(), 'auth': hashlib.sha256().hexdigest(),
        'companyMemberships': hashlib.sha256(b'private-membership-rows\n').hexdigest()}
    assert sum(statement == identity.CATALOG_SQL for _, statement, _ in calls) == 1


@pytest.mark.parametrize('failure', ['classifier', 'output'])
def test_diagnostic_failures_release_captures_without_escaping(monkeypatch, capsys, failure):
    source, target = captured(raw()), captured(raw(rows=[]))
    def broken(*_args, **_kwargs): raise RuntimeError('secret-diagnostic-error')
    if failure == 'classifier': monkeypatch.setattr(diagnostic, 'catalog_difference', broken)
    else: monkeypatch.setattr(diagnostic.sys, 'stderr', type('BrokenOutput', (), {'write': broken})())
    diagnostic.emit_catalog_difference(source, target)
    assert source._raw is target._raw is None
    if failure == 'classifier': assert 'secret' not in capsys.readouterr().err
