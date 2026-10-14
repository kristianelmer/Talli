"""Pure, synthetic backup/restore profiles. No database or actual evidence reads."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
import rf1086_restore_metadata as m
from test_rf1086_causal_protocol import catalogs

OWNER = 'supabase_admin'
TABLE = ('INSERT', 'SELECT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN')


def end():
    return time.monotonic() + 5


@pytest.mark.parametrize('kind', [m.ledger.Unavailable, m.lexical.Unavailable])
@pytest.mark.parametrize('reason', ['deadline', 'limit'])
def test_closed_preserves_exact_resource_failure_identity(kind, reason):
    primary = kind(reason)
    before = dict(vars(primary))
    @m.closed
    def operation():
        raise primary
    with pytest.raises(kind) as caught:
        operation()
    assert caught.value is primary and vars(primary) == before


@pytest.mark.parametrize('case', ['ledger_subclass', 'lexical_subclass', 'foreign',
    'ledger_other', 'lexical_other', 'ledger_nonstring', 'lexical_nonstring',
    'string_subclass', 'type', 'key', 'index', 'unicode', 'overflow', 'recursion'])
def test_closed_keeps_other_conversion_behavior(case):
    class LedgerSubclass(m.ledger.Unavailable): pass
    class LexicalSubclass(m.lexical.Unavailable): pass
    class StringSubclass(str): pass
    errors = {
        'ledger_subclass': LedgerSubclass('deadline'),
        'lexical_subclass': LexicalSubclass('limit'),
        'foreign': ValueError('generated'),
        'ledger_other': m.ledger.Unavailable('role'),
        'lexical_other': m.lexical.Unavailable('profile'),
        'ledger_nonstring': m.ledger.Unavailable(None),
        'lexical_nonstring': m.lexical.Unavailable('deadline'),
        'string_subclass': m.ledger.Unavailable(StringSubclass('deadline')),
        'type': TypeError(), 'key': KeyError(), 'index': IndexError(),
        'unicode': UnicodeError(), 'overflow': OverflowError(), 'recursion': RecursionError(),
    }
    errors['foreign'].reason = 'deadline'
    errors['lexical_nonstring'].reason = ['limit']
    primary = errors[case]
    @m.closed
    def operation():
        raise primary
    with pytest.raises(m.MetadataUnavailable) as caught:
        operation()
    assert type(caught.value) is m.MetadataUnavailable
    assert caught.value.reason == 'metadata_profile' and caught.value is not primary


@pytest.mark.parametrize('primary', [m.MetadataUnavailable('deadline'),
    KeyboardInterrupt('generated'), SystemExit('generated')])
def test_closed_keeps_metadata_and_fatal_identity(primary):
    @m.closed
    def operation():
        raise primary
    with pytest.raises(type(primary)) as caught:
        operation()
    assert caught.value is primary


def encode(value):
    return json.dumps(value, separators=(',', ':'), ensure_ascii=False).encode()


def item(grantee=OWNER, rights=TABLE, options=(), grantor=OWNER):
    return {'grantee': grantee, 'grantor': grantor, 'privileges': list(rights), 'grantOptions': list(options)}


def acl(items, raw=None):
    letters = dict(zip(('INSERT', 'SELECT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER', 'EXECUTE', 'USAGE', 'CREATE', 'TEMPORARY', 'CONNECT', 'SET', 'ALTER SYSTEM', 'MAINTAIN'), 'arwdDxtXUCTcsAm', strict=True))
    if raw is None:
        strings = []
        for x in items:
            rights = ''.join(letter + ('*' if right in x['grantOptions'] else '')
                for right, letter in letters.items() if right in x['privileges'])
            strings.append((x['grantee'] or '') + '=' + rights + '/' + x['grantor'])
        raw = '{' + ','.join(strings) + '}'
    return {'raw': raw, 'items': items}


def fixture(*, ordered=False):
    source, _ = catalogs()
    roles = [{'name': 'bootstrap', 'oid': 10, 'superuser': True, 'login': False},
             {'name': 'pg_monitor', 'oid': 3373, 'superuser': False, 'login': False},
             {'name': 'reader', 'oid': 17000, 'superuser': False, 'login': False},
             {'name': OWNER, 'oid': 17001, 'superuser': True, 'login': True},
             {'name': 'writer', 'oid': 17002, 'superuser': False, 'login': False},
             {'name': 'PUBLIC', 'oid': 17003, 'superuser': False, 'login': False}]
    objects = [{'classOid': 1259, 'objectOid': 20000, 'identity': ['relation', 'public', 't'],
        'kind': 'r', 'owner': OWNER, 'acl': acl([item()] + ([item('reader', ('SELECT',))] if ordered else [])),
        'defaultAcl': acl([item()]), 'initialAcl': None, 'initialPrivilegeType': None,
        'extension': [], 'columnAclCount': 0, 'argumentTypes': [], 'argumentModes': None}]
    for i, f in enumerate(source['functions']):
        objects.append({'classOid': 1255, 'objectOid': 21000 + i, 'identity': f['identity'],
            'kind': 'f', 'owner': OWNER, 'acl': None,
            'defaultAcl': acl([item(None, ('EXECUTE',)), item(OWNER, ('EXECUTE',))]),
            'initialAcl': None, 'initialPrivilegeType': None,
            'extension': f['extensions'], 'columnAclCount': 0,
            'argumentTypes': f['types'], 'argumentModes': None})
    return {'schema': m.SCHEMA, 'serverVersion': 170006, 'database': 'postgres',
            'systemIdentifier': '12345', 'roles': roles, 'objects': objects, 'defaultAcls': [],
            'selectedSchemas': source['schemas'], 'selectedFunctions': source['functions']}


def catalog(wire):
    rows = []
    for o in wire['objects']:
        if o['identity'][0] == 'relation':
            rows.append(o['identity'] + [o['kind'], o['owner'], None if o['acl'] is None else o['acl']['raw'], False, False])
        else:
            f = next((f for f in wire['selectedFunctions'] if f['identity'] == o['identity']), None)
            if f is not None:
                rows.append(f['row'])
            else:
                # Ordinary generated functions need raw catalog owner/ACL binding
                # without pretending they belong to the selected net pair.
                row = deepcopy(wire['selectedFunctions'][0]['row'])
                row[:4] = o['identity']; row[4] = o['owner']
                row[5] = None if o['acl'] is None else o['acl']['raw']
                rows.append(row)
    rows.extend(s['row'] for s in wire['selectedSchemas'])
    rows.extend(['default_acl', d['owner'], d['schema'], d['kind'], d['acl']['raw']] for d in wire['defaultAcls'])
    return encode(rows) + b'\n{}\n[]\n'


def role_rows(wire):
    return [{'rolname': r['name'], 'rolsuper': r['superuser'], 'rolcanlogin': r['login'],
             'rolinherit': True, 'rolcreaterole': False, 'rolcreatedb': False,
             'rolreplication': False, 'rolbypassrls': False, 'rolconnlimit': -1,
             'rolpassword': None, 'rolvaliduntil': None} for r in wire['roles']]


def source(wire=None, *, column_rows=()):
    wire = fixture() if wire is None else wire
    raw = catalog(wire)
    if column_rows:
        first, rest = raw.split(b'\n', 1)
        raw = encode(json.loads(first) + list(column_rows)) + b'\n' + rest
    result = m.decode_metadata(encode(wire), catalog_raw=raw,
                             roles_raw=encode(role_rows(wire)) + b'\n[]\n', deadline=end())
    snapshot, _ = catalogs()
    snapshot['schemas'] = deepcopy(wire['selectedSchemas'])
    snapshot['functions'] = deepcopy(wire['selectedFunctions'])
    return m.bind_source_snapshot(result, snapshot, deadline=end())


def role_sql(wire):
    sql = b"-- PostgreSQL database cluster dump\n\\restrict ABC123\nSET default_transaction_read_only = off;\nSET client_encoding = 'UTF8';\nSET standard_conforming_strings = on;\n"
    for r in sorted(role_rows(wire), key=lambda r: r['rolname']):
        if r['rolname'].startswith('pg_'):
            continue
        n = b'"' + r['rolname'].encode().replace(b'"', b'""') + b'"'
        words = [('' if r[field] else 'NO') + word for field, word in zip(m.ROLE_FLAGS, m.ROLE_WORDS, strict=True)]
        sql += b'CREATE ROLE ' + n + b';\nALTER ROLE ' + n + b' WITH ' + ' '.join(words).encode() + b';\n'
    return sql + b'\\unrestrict ABC123\n'


def plan_data(wire=None, suffix=b'', *, later=False):
    wire = fixture() if wire is None else wire
    src = source(wire)
    prefix = b'-- immutable source script\n'
    script = prefix + suffix + b'-- done\n'
    obj = wire['objects'][0]
    index = {'schema': 'rf1086-repair-index-v1', 'script': {'bytes': len(script), 'sha256': hashlib.sha256(script).hexdigest()},
        'preAcl': len(prefix), 'cuts': {'Is': 2, 'In': 3}, 'objects': [{
        'classOid': obj['classOid'], 'objectOid': obj['objectOid'], 'identity': obj['identity'],
        'kind': obj['kind'], 'owner': obj['owner'], 'createdEnd': 10,
        'aclSpans': [] if not suffix else [[len(prefix), len(prefix) + len(suffix)]], 'laterMutation': later}],
        'defaultAclSpans': []}
    entry = SimpleNamespace(class_oid=1259, object_oid=obj['objectOid'], namespace=b'public',
        tag=b't', owner=OWNER.encode())
    archive = SimpleNamespace(raw=b'generated-fixture-archive', entries=(entry,))
    return src, script, archive, index


def compile_(data):
    s, script, archive, index = data
    return m.compile_plan(s, script=script, archive=archive, index=index, deadline=end())


def target(wire, *, explicit=False):
    wire = deepcopy(wire); wire['systemIdentifier'] = '54321'
    for r in wire['roles']:
        if r['oid'] > 16384:
            r['oid'] += 100
    for o in wire['objects']:
        o['objectOid'] += 100
    if not explicit:
        wire['objects'][0]['acl'] = None
    return m.decode_observation(encode(wire), deadline=end())


def test_source_binding_and_detached_immutable_private_values():
    wire = fixture(); s = source(wire)
    assert s.bootstrap == 'bootstrap'
    assert s.binding == {'bytes': len(encode(wire)), 'sha256': hashlib.sha256(encode(wire)).hexdigest()}
    assert 'bootstrap' not in repr(s) and 'supabase' not in repr(s.objects[0])
    projection = s.selected_catalog; projection['schemas'].clear()
    assert len(s.selected_catalog['schemas']) == 2
    with pytest.raises(AttributeError): s.roles[0].oid = 100


@pytest.mark.parametrize('change', ['version', 'bool_version', 'system', 'unknown', 'duplicate_role',
    'role_order', 'bootstrap_su', 'operator_login', 'class', 'duplicate_oid', 'acl_raw',
    'acl_options', 'unknown_role', 'default', 'initial_type', 'column_bool', 'argument_mode', 'null_item'])
def test_malformed_metadata_refused_without_echo(change):
    wire = fixture()
    if change == 'version': wire['serverVersion'] = 170011
    elif change == 'bool_version': wire['serverVersion'] = True
    elif change == 'system': wire['systemIdentifier'] = 'private-canary'
    elif change == 'unknown': wire['private-canary'] = True
    elif change == 'duplicate_role': wire['roles'].append(deepcopy(wire['roles'][-1]))
    elif change == 'role_order': wire['roles'][2:4] = reversed(wire['roles'][2:4])
    elif change == 'bootstrap_su': wire['roles'][0]['superuser'] = False
    elif change == 'operator_login': wire['roles'][3]['login'] = False
    elif change == 'class': wire['objects'][0]['classOid'] = 1255
    elif change == 'duplicate_oid': wire['objects'].append(deepcopy(wire['objects'][0]))
    elif change == 'acl_raw': wire['objects'][0]['acl']['raw'] = '{private-canary}'
    elif change == 'acl_options': wire['objects'][0]['acl']['items'][0]['grantOptions'] = ['EXECUTE']
    elif change == 'unknown_role': wire['objects'][0]['acl']['items'][0]['grantor'] = 'private-canary'
    elif change == 'default': wire['objects'][0]['defaultAcl'] = acl([])
    elif change == 'initial_type': wire['objects'][0]['initialPrivilegeType'] = 'e'
    elif change == 'column_bool': wire['objects'][0]['columnAclCount'] = True
    elif change == 'argument_mode': wire['objects'][0]['argumentModes'] = ['private-canary']
    else: wire['objects'][0]['acl']['items'] = [None]
    with pytest.raises(m.MetadataUnavailable) as caught:
        m.decode_observation(encode(wire), deadline=end())
    assert str(caught.value) == 'restore_metadata_unavailable'


@pytest.mark.parametrize('raw', [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'['*17+b']'*17,
                                      b'{"a":"'+b'x'*(65537)+b'"}'])
def test_json_rejects_ambiguity_nonfinite_and_oversized_before_semantics(raw):
    with pytest.raises(m.MetadataUnavailable): m.decode_observation(raw, deadline=end())


@pytest.mark.parametrize('part', ['catalog', 'roles', 'missing_object', 'column', 'selected'])
def test_raw_overlap_required(part):
    wire = fixture(); raw = catalog(wire); roles = role_rows(wire)
    if part == 'catalog': raw = raw.replace(b'arwdDxtm', b'arwdDxt')
    elif part == 'roles': roles[0]['rolsuper'] = False
    elif part == 'missing_object': wire['objects'] = wire['objects'][1:]
    elif part == 'column': wire['objects'][0]['columnAclCount'] = 1
    else: wire['selectedSchemas'][0]['row'][3] = None
    with pytest.raises(m.MetadataUnavailable):
        m.decode_metadata(encode(wire), catalog_raw=raw, roles_raw=encode(roles)+b'\n[]\n', deadline=end())


def test_ranked_role_creates_bootstrap_accounting_and_original_suffix():
    wire = fixture(); dump = role_sql(wire); s = source(wire)
    p = m.role_program(dump, s, deadline=end())
    assert p.bootstrap == 'bootstrap' and b'CREATE ROLE "bootstrap";' not in p.sql
    order = [p.sql.index(b'CREATE ROLE "'+x+b'";') for x in (b'reader', b'supabase_admin', b'writer', b'PUBLIC')]
    assert order == sorted(order)
    noncreates = b''.join(line for line in dump.splitlines(keepends=True) if not line.startswith(b'CREATE ROLE '))
    stripped = p.sql
    for n in ('reader', OWNER, 'writer', 'PUBLIC'):
        stripped = stripped.replace(b'CREATE ROLE "'+n.encode()+b'";', b'', 1)
    # Every original newline/comment/attribute remains, including CREATE-line newlines.
    expected = dump
    for n in ('bootstrap', 'reader', OWNER, 'writer', 'PUBLIC'):
        expected = expected.replace(b'CREATE ROLE "'+n.encode()+b'";', b'', 1)
    assert stripped == expected
    assert p.accounting['executedCreates'] == 4 and p.accounting['bootstrapCreates'] == 1
    assert b'ALTER ROLE "bootstrap" WITH SUPERUSER' in p.sql and b'NOLOGIN' in p.sql


@pytest.mark.parametrize('extra', [b'SELECT pg_catalog.set_config(\'role\',\'reader\',false);',
    b'DROP ROLE reader;', b'CREATE DATABASE other;', b'ALTER ROLE reader RENAME TO other;',
    b'SET SESSION AUTHORIZATION reader;', b'ALTER ROLE "bootstrap" WITH NOSUPERUSER;',
    b'CREATE ROLE "reader";', b'\\connect postgres', b'COPY t FROM STDIN;'])
def test_role_grammar_rejects_extra_or_unsafe_statements(extra):
    wire = fixture(); dump = role_sql(wire).replace(b'\\unrestrict', extra+b'\n\\unrestrict')
    with pytest.raises(m.MetadataUnavailable): m.role_program(dump, source(wire), deadline=end())


def test_fake_create_inside_comment_literal_not_partitioned():
    wire = fixture(); dump = role_sql(wire).replace(b'\\unrestrict',
        b'-- CREATE ROLE bad;\nCOMMENT ON ROLE reader IS \'CREATE ROLE fake;\';\n\\unrestrict')
    p = m.role_program(dump, source(wire), deadline=end())
    assert b"IS 'CREATE ROLE fake;'" in p.sql and p.accounting['creates'] == 5


def test_actual_role_order_not_absolute_custom_oids():
    wire = fixture(); s = source(wire); rows = deepcopy(wire['roles'])
    for row in rows:
        if row['oid'] > 16384: row['oid'] += 500
    m.validate_role_order(s, encode(rows), deadline=end())
    rows[2]['oid'], rows[3]['oid'] = rows[3]['oid'], rows[2]['oid']; rows.sort(key=lambda r:r['oid'])
    with pytest.raises(m.MetadataUnavailable): m.validate_role_order(s, encode(rows), deadline=end())


def test_owner_default_materialization_exact_pre_and_post_and_null_untouched():
    wire = fixture(); plan = compile_(plan_data(wire)); before = target(wire)
    mutation = m.pre_acl(plan, before, deadline=end())
    assert mutation.applied == 1 and mutation.noop == 0
    assert b'GRANT INSERT, SELECT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN ON TABLE public.t TO supabase_admin;' in mutation.sql
    assert b'REVOKE' not in mutation.sql
    after = target(wire, explicit=True)
    m.post_acl(plan, before, after, mutation, deadline=end())
    noop = m.pre_acl(plan, after, deadline=end())
    assert noop.sql == b'' and noop.applied == 0 and noop.noop == 1
    assert plan.counts['archiveOnly'] == 2


def test_target_is_not_an_adaptive_patch_source():
    wire = fixture(); plan = compile_(plan_data(wire)); altered = deepcopy(wire)
    altered['objects'][0]['acl'] = acl([item(), item('writer', ('SELECT',))])
    with pytest.raises(m.MetadataUnavailable): m.pre_acl(plan, target(altered, explicit=True), deadline=end())
    before = target(wire); after = target(wire, explicit=True)
    bad = replace(after, objects=(replace(after.objects[0], object_oid=99999), *after.objects[1:]))
    with pytest.raises(m.MetadataUnavailable): m.post_acl(plan, before, bad, m.pre_acl(plan,before,deadline=end()), deadline=end())


def test_ordered_seed_source_order_and_grant_only_identity_suffix():
    wire = fixture(ordered=True)
    # Source reader first, owner last; original default baseline emits owner first.
    wire['objects'][0]['acl']['items'].reverse()
    wire['objects'][0]['acl'] = acl(wire['objects'][0]['acl']['items'])
    plan = compile_(plan_data(wire, b'GRANT SELECT ON TABLE public.t TO reader;\n'))
    assert len(plan.candidates) == 1
    sql = m.pre_acl(plan, target(wire), deadline=end()).sql
    assert sql.index(b'TO reader;') < sql.index(b'TO supabase_admin;')
    assert b'REVOKE ALL ON TABLE public.t FROM supabase_admin RESTRICT;' in sql


def test_original_suffix_already_yields_source_avoids_seed():
    wire = fixture(ordered=True)
    plan = compile_(plan_data(wire, b'GRANT SELECT ON TABLE public.t TO reader;\n'))
    assert not plan.candidates and plan.counts['archiveOnly'] == 3


@pytest.mark.parametrize('suffix', [b'REVOKE SELECT ON TABLE public.t FROM reader;\n',
    b'REVOKE SELECT ON TABLE public.t FROM reader CASCADE;\n',
    b'GRANT UPDATE ON TABLE public.t TO reader;\n', b'GRANT SELECT(x) ON TABLE public.t TO reader;\n',
    b'GRANT SELECT ON TABLE public.other TO reader;\n', b'GRANT SELECT ON TABLE public.t TO reader GRANTED BY writer;\n',
    b'GRANT SELECT ON TABLE public.t TO reader, writer;\n'])
def test_selected_suffix_nonidentity_column_or_wrong_target_refuses(suffix):
    wire = fixture(ordered=True)
    with pytest.raises(m.MetadataUnavailable): compile_(plan_data(wire, suffix))


def test_absent_right_restrict_revoke_is_identity_for_seed():
    wire = fixture(ordered=True)
    plan = compile_(plan_data(wire, b'REVOKE UPDATE ON TABLE public.t FROM reader RESTRICT;\n'))
    assert len(plan.candidates) == 1


@pytest.mark.parametrize('change', ['oid', 'class', 'owner', 'hook', 'late', 'span', 'missing', 'hash'])
def test_complete_index_bindings_and_later_mutation(change):
    data = plan_data(); _, _, _, index = data
    if change == 'oid': index['objects'][0]['objectOid'] += 1
    elif change == 'class': index['objects'][0]['classOid'] = 1255
    elif change == 'owner': index['objects'][0]['owner'] = 'reader'
    elif change == 'hook': index['preAcl'] = 1
    elif change == 'late': index['objects'][0]['laterMutation'] = True
    elif change == 'span': index['objects'][0]['aclSpans'] = [[0,10]]
    elif change == 'missing': index['objects'] = []
    else: index['script']['sha256'] = '0'*64
    with pytest.raises(m.MetadataUnavailable): compile_(data)


def test_default_acl_sorted_role_rank_and_normalized_absence():
    wire = fixture()
    # reader precedes owner in source numeric OID comparator, regardless grant order.
    wire['defaultAcls'] = [{'owner':OWNER,'schema':None,'kind':'r',
        'acl':acl([item('reader',('SELECT',)),item()])}]
    data = plan_data(wire)
    src, script, archive, index = data
    command = b'ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin GRANT SELECT ON TABLES TO reader;\n'
    start = index['preAcl']; script = script[:start]+command+b'-- done\n'
    index['script'] = {'bytes':len(script),'sha256':hashlib.sha256(script).hexdigest()}
    index['defaultAclSpans'] = [[start,start+len(command)]]
    plan = compile_((src,script,archive,index))
    assert plan.counts['defaultAcls'] == 1
    wire['defaultAcls'][0]['acl'] = acl([item(),item('reader',('SELECT',))])
    with pytest.raises(m.MetadataUnavailable):
        compile_((source(wire),script,archive,index))


def test_prefix_programs_preserve_unrelated_prefix_data_and_exact_post():
    wire = fixture(); plan = compile_(plan_data(wire)); before, failed = catalogs()
    # Source-only initial differences do not demand installing old source history.
    is_change = m.prefix_mutation(plan,'Is',failed,deadline=end())
    assert is_change.applied == 1 and is_change.sql.count(b'GRANT USAGE') == 8
    after = deepcopy(failed)
    for a,s in zip(after['schemas'],before['schemas'],strict=True):
        a['row'][3] = s['row'][3]; a['grants'] = s['grants']
    m.prefix_postcheck(plan,'Is',failed,after,deadline=end())
    assert after['schemas'][0]['initial'] == []
    in_change = m.prefix_mutation(plan,'In',after,deadline=end())
    assert len(in_change.sql) == 607
    repaired = deepcopy(after)
    for a,s in zip(repaired['functions'],before['functions'],strict=True):
        a['row'][6:] = s['row'][6:]; a['definition_sha256'] = s['definition_sha256']
    m.prefix_postcheck(plan,'In',after,repaired,deadline=end())
    repaired['functions'][0]['row'][5] = '{owner=X/owner}'
    with pytest.raises(m.MetadataUnavailable): m.prefix_postcheck(plan,'In',after,repaired,deadline=end())


def test_body_mismatch_cannot_select_an_alter():
    plan = compile_(plan_data()); _, failed = catalogs()
    failed['functions'][0]['body_sha256'] = 'f'*64
    with pytest.raises(m.MetadataUnavailable): m.prefix_mutation(plan,'In',failed,deadline=end())


def test_shared_deadline_and_cancellation_are_not_generic_success(monkeypatch):
    with pytest.raises(m.MetadataUnavailable) as e: source_deadline = m.decode_observation(encode(fixture()),deadline=time.monotonic()-1)
    assert e.value.reason == 'deadline'
    sentinel = KeyboardInterrupt('private-canary')
    monkeypatch.setattr(m.time,'monotonic',lambda: (_ for _ in ()).throw(sentinel))
    with pytest.raises(KeyboardInterrupt) as e: m.decode_observation(encode(fixture()), deadline=100)
    assert e.value is sentinel


def test_query_literals_and_config_bindings_are_fixed_read_only():
    assert m.METADATA_SQL.startswith(b'BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;')
    assert b"statement_timeout = '3s'" in m.METADATA_SQL and m.METADATA_SQL.endswith(b'ROLLBACK;\n')
    assert b'LIMIT 8193' in m.METADATA_SQL and b'LIMIT 257' in m.METADATA_SQL
    assert b'bounded_acls AS MATERIALIZED' in m.METADATA_SQL
    assert m.SQL_SHA256 == hashlib.sha256(m.METADATA_SQL).hexdigest()
    assert m.CONFIG_SHA256 == hashlib.sha256(m.canonical(m.CONFIG)).hexdigest()


def test_query_qualifies_functions_without_changing_snapshot_json_keys():
    # The fixed capture decoder accepts defaults/binary {bytes,sha256}. A
    # generated SQL qualification must never alter these external field names.
    assert b"'pg_catalog.sha256'" not in m.METADATA_SQL
    assert m.METADATA_SQL.count(b"'sha256',pg_catalog.encode(") == 2


def complete_walk(wire, *, extension_created=False, acl_sql=None, acl_deps=None,
                  post_rows=(), rows_change=None):
    import rf1086_raw_toc as raw_toc
    import rf1086_sql_ledger as ledger
    from test_rf1086_sql_ledger import source_rows, row, wire_and_list, script_fixture
    rows = source_rows()
    for x in rows:
        if x['owner']: x['owner'] = OWNER.encode()
    table = row(42, b'TABLE', b't', b'CREATE TABLE public.t (id integer);\n',
        class_oid=b'1259', oid=b'20000', namespace=b'public', owner=OWNER.encode(),
        drop=b'DROP TABLE public.t;\n')
    if not extension_created:
        rows.insert(-2, table)
    if acl_sql is not None:
        rows.insert(-1, row(52,b'ACL',b'TABLE t',acl_sql,class_oid=b'0',oid=b'0',
            namespace=b'public', owner=OWNER.encode(), deps=(42,) if acl_deps is None else acl_deps))
    # A dependencyless EVENT TRIGGER is deliberately unknown later-writer proof,
    # not part of a minimal positive ACL fixture. Negative tests add it explicitly.
    rows = [entry for entry in rows if entry['id'] != 60] + list(post_rows)
    if rows_change is not None:
        rows_change(rows)
    raw, listing = wire_and_list(rows); script = script_fixture(rows)
    for entry in rows:
        if entry['description'] == b'TABLE' and entry['owner']:
            definition = entry['definition'] + b'\n\n'
            script = script.replace(definition, definition + b'ALTER TABLE ' + entry['namespace']
                + b'.' + entry['tag'] + b' OWNER TO ' + entry['owner'] + b';\n\n')
    budget = ledger.Budget(end()); budget.phase('metadata')
    archive, _ = raw_toc.inspect(raw, listing, budget.deadline)
    source_catalog, _ = catalogs()
    walk = ledger.verify_restore_core(script, archive, catalog=source_catalog, budget=budget)
    return script, archive, walk


def test_completed_walk_index_maps_extension_lifecycle_and_all_typed_acl_spans():
    for extension in (False, True):
        wire = fixture(ordered=True)
        wire['objects'][0]['acl'] = acl([item('reader',('SELECT',)),item()])
        if extension: wire['objects'][0]['extension'] = [['pg_net','0.20.3',OWNER]]
        src = source(wire)
        script, archive, walk = complete_walk(wire,extension_created=extension,
            acl_sql=b'GRANT SELECT ON TABLE public.t TO reader;\n')
        index = m.restore_metadata_index(script,archive,walk,src,deadline=end())
        plan = m.compile_plan(src,script=script,archive=archive,index=index,deadline=end())
        assert len(plan.candidates) == 1
        assert plan.cuts['In'] < plan.cuts['Is'] < plan.pre_acl
        row = next(x for x in index['objects'] if x['identity'] == ['relation','public','t'])
        assert row['aclSpans'] and row['createdEnd'] <= plan.pre_acl
        assert b'GRANT SELECT' in script[slice(*row['aclSpans'][0])]


def test_index_requires_typed_target_and_dependency_not_just_either():
    wire = fixture(ordered=True); src = source(wire)
    script,archive,walk = complete_walk(wire,acl_sql=b'GRANT SELECT ON TABLE public.t TO reader;\n',acl_deps=(20,))
    with pytest.raises(m.MetadataUnavailable): m.restore_metadata_index(script,archive,walk,src,deadline=end())
    script,archive,walk = complete_walk(wire,acl_sql=b'GRANT SELECT ON TABLE public.other TO reader;\n')
    with pytest.raises(m.MetadataUnavailable): m.restore_metadata_index(script,archive,walk,src,deadline=end())


def arity_family(wire, *, group='bytea, text[], text[]', modes=None):
    """Synthetic ordinary overloads, not observed pgcrypto/pg_net contents."""
    for i, (identity, types) in enumerate((('bytea', ['bytea']),
                                          (group, ['bytea', '_text', '_text']))):
        obj = deepcopy(wire['objects'][1])
        obj.update(objectOid=22000+i, identity=['function', 'public', 'fixture_armor', identity],
                   argumentTypes=[['pg_catalog', t] for t in types],
                   argumentModes=None if i == 0 else modes)
        if i == 1:
            obj['acl'] = acl([item(None, ('EXECUTE',)), item(OWNER, ('EXECUTE',)),
                              item('reader', ('EXECUTE',))])
        wire['objects'].append(obj)


@pytest.mark.parametrize('verb,direction', [('GRANT', 'TO'), ('REVOKE', 'FROM')])
@pytest.mark.parametrize('modes', [None, ['i', 'i', 'i']])
def test_mixed_arity_acl_archive_only_through_complete_walk(verb, direction, modes):
    wire = fixture(ordered=True)
    wire['objects'][0]['acl'] = acl([item('reader', ('SELECT',)), item()])
    arity_family(wire, modes=modes)
    src = source(wire)
    sql = f'{verb} EXECUTE ON FUNCTION public.fixture_armor(bytea, text[], text[]) {direction} reader;\n'.encode()
    script, archive, walk = complete_walk(wire, acl_sql=sql, acl_deps=(420,))
    index = m.restore_metadata_index(script, archive, walk, src, deadline=end())
    family = [row for row in index['objects'] if row['identity'][2] == 'fixture_armor']
    assert len(family) == 2 and all(row['aclSpans'] == [] for row in family)
    plan = m.compile_plan(src, script=script, archive=archive, index=index, deadline=end())
    assert [c.object.identity for c in plan.candidates] == [('relation', 'public', 't')]
    assert plan.counts['unmodeled'] == 1


def arity_candidates():
    wire = fixture(); arity_family(wire)
    return tuple(o for o in source(wire).objects if o.identity[2] == 'fixture_armor')


def resolve_arity(*, matches=None, group=None, sql=None, budget=None):
    matches = arity_candidates() if matches is None else matches
    if sql is None:
        group = matches[1].identity[3].encode() if group is None else group
        sql = b'GRANT EXECUTE ON FUNCTION public.fixture_armor('+group+b') TO reader;'
    budget = m.Budget(end()) if budget is None else budget
    statement = next(m._statements(sql+b'\n', budget))
    return m._target_candidates(statement, {('function', b'public', b'fixture_armor'): matches},
                                budget, roles={'reader', 'writer', OWNER})


@pytest.mark.parametrize('group', ['bytea, text[], text[]',
    '"a, (b)" bytea, second text[], third text[]', 'bytea, nested(1, 2)[], text[]'])
def test_arity_witness_preserves_original_group_and_never_selects_a_type(group):
    scalar, array = arity_candidates()
    # Different catalog namespace and deliberately opaque nested spelling: only
    # arity exclusion is claimed, not PostgreSQL type resolution or grammar.
    array = replace(array, identity=(*array.identity[:3], group),
                    argument_types=(('other', '_one'), ('other', '_two'), ('other', '_three')))
    result = resolve_arity(matches=(scalar, array))
    assert result.exact is None and result.unmodeled is True


@pytest.mark.parametrize('group', ['bytea, pg_catalog.text[], text[]', 'bytea,text[], text[]',
                                 'bytea, text[] /* source lacks this */, text[]'])
def test_arity_witness_does_not_normalize_qualification_or_trivia(group):
    with pytest.raises(m.MetadataUnavailable): resolve_arity(group=group.encode())


@pytest.mark.parametrize('kind', ['f', 'p'])
def test_any_same_arity_supported_candidate_refuses_exclusion(kind):
    scalar, array = arity_candidates()
    same_arity = replace(scalar, object_oid=23000, kind=kind,
        identity=(*scalar.identity[:3], 'bytea, text, text'),
        argument_types=(('pg_catalog', 'bytea'), ('pg_catalog', 'text'), ('pg_catalog', 'text')))
    with pytest.raises(m.MetadataUnavailable): resolve_arity(matches=(scalar, array, same_arity))


@pytest.mark.parametrize('modes', [('o','i','i'), ('b','i','i'), ('t','i','i'),
                                 ('v','i','i'), ('i','v','o'), (), ('i',), ('i',)*4])
@pytest.mark.parametrize('kind', ['f', 'a', 'w', 'p'])
def test_same_arity_modes_cannot_borrow_a_plain_in_witness(modes, kind):
    scalar, array = arity_candidates()
    other = replace(array, object_oid=23000, identity=(*array.identity[:3], 'a bytea, b text[], c text[]'),
                    argument_modes=modes, kind=kind)
    with pytest.raises(m.MetadataUnavailable): resolve_arity(matches=(scalar, array, other))


@pytest.mark.parametrize('kind', ['p', 'a', 'w'])
def test_only_an_ordinary_function_can_witness_canonical_arity(kind):
    scalar, array = arity_candidates()
    with pytest.raises(m.MetadataUnavailable): resolve_arity(matches=(scalar, replace(array, kind=kind)))


@pytest.mark.parametrize('kind', ['f', 'a', 'w'])
def test_possible_same_arity_owners_include_plain_in_aggregates_and_windows(kind):
    scalar, array = arity_candidates()
    other = replace(array, object_oid=23000, kind=kind, owner='writer',
        identity=(*array.identity[:3], 'a bytea, b text[], c text[]'), argument_modes=('i',)*3)
    family = (scalar, array, other)
    assert resolve_arity(matches=family).exact is None  # No new implicit owner equality rule.
    raw = b'GRANT EXECUTE ON FUNCTION public.fixture_armor(bytea, text[], text[]) TO reader GRANTED BY supabase_admin;'
    with pytest.raises(m.MetadataUnavailable): resolve_arity(matches=family, sql=raw)
    assert resolve_arity(matches=(scalar, array, replace(other, owner=OWNER)), sql=raw).unmodeled


def test_different_arity_and_unsupported_procedure_owners_are_not_function_owners():
    scalar, array = arity_candidates()
    different = replace(array, object_oid=23000, owner='writer', argument_types=(('pg_catalog','_text'),),
                        argument_modes=('v',), identity=(*array.identity[:3], 'VARIADIC text[]'))
    procedure = replace(array, object_oid=23001, kind='p', owner='writer',
                        identity=(*array.identity[:3], 'IN a bytea, IN b text[], IN c text[]'))
    raw = b'GRANT EXECUTE ON FUNCTION public.fixture_armor(bytea, text[], text[]) TO reader GRANTED BY supabase_admin;'
    assert resolve_arity(matches=(scalar, array, different, procedure), sql=raw).exact is None


@pytest.mark.parametrize('group', ['', ',bytea, text[]', 'bytea,, text[]', 'bytea, text[],',
                                 'bytea, text[], text[], text[]'])
def test_canonical_text_does_not_override_structural_arity_or_empty_segments(group):
    scalar, array = arity_candidates()
    array = replace(array, identity=(*array.identity[:3], group))
    with pytest.raises((m.MetadataUnavailable, m.ledger.Unavailable)):
        resolve_arity(matches=(scalar, array))


def test_duplicate_canonical_witnesses_refuse_without_first_match_selection():
    scalar, array = arity_candidates()
    with pytest.raises(m.MetadataUnavailable): resolve_arity(matches=(scalar, array, array))


def test_group_boundary_excludes_trivia_after_closing_parenthesis():
    raw = b'GRANT EXECUTE ON FUNCTION public.fixture_armor(bytea, text[], text[]) /* outside */ TO reader;'
    assert resolve_arity(sql=raw).exact is None


def test_typed_ambiguity_and_exact_unsupported_rejection_never_retry_arity(monkeypatch):
    scalar, array = arity_candidates()
    def forbidden(*args, **kwargs): raise AssertionError('typed result downgraded')
    monkeypatch.setattr(m, '_arity_disjoint_target', forbidden)
    with pytest.raises(m.MetadataUnavailable):
        resolve_arity(matches=(scalar, scalar, array), group=b'bytea')
    exact_unsupported = replace(array, identity=(*array.identity[:3], 'value bytea'),
                               argument_types=(('pg_catalog','bytea'),), argument_modes=('v',))
    with pytest.raises(m.MetadataUnavailable):
        resolve_arity(matches=(scalar, exact_unsupported), group=b'value bytea')


@pytest.mark.parametrize('verb,direction', [(b'GRANT', b'TO'), (b'REVOKE', b'FROM')])
@pytest.mark.parametrize('tail', [b', public.fixture_armor(bytea) @ reader;', b'() @ reader;',
    b'@ reader, writer;', b'@ reader extra;', b'@ missing;', b'@ reader CASCADE;',
    b'@ reader GRANTED BY writer;'])
def test_arity_exclusion_consumes_one_target_and_the_complete_ending(verb, direction, tail):
    raw = verb+b' EXECUTE ON FUNCTION public.fixture_armor(bytea, text[], text[]) '+tail.replace(b'@',direction)
    with pytest.raises((m.MetadataUnavailable, m.ledger.Unavailable)): resolve_arity(sql=raw)


@pytest.mark.parametrize('raw', [
    b'GRANT BANANA ON FUNCTION public.fixture_armor(bytea, text[], text[]) TO reader;',
    b'GRANT EXECUTE ON FUNCTION public.fixture_armor(bytea, text[], text[]) FROM reader;',
    b'REVOKE EXECUTE ON FUNCTION public.fixture_armor(bytea, text[], text[]) TO reader;',
    b'GRANT EXECUTE ON FUNCTION public.fixture_armor(bytea, text[], text[]) TO PUBLIC WITH GRANT OPTION;',
    b'GRANT EXECUTE (col) ON FUNCTION public.fixture_armor(bytea, text[], text[]) TO reader;',
])
def test_arity_exclusion_retains_closed_privilege_and_option_rules(raw):
    with pytest.raises((m.MetadataUnavailable, m.ledger.Unavailable)): resolve_arity(sql=raw)


def test_new_group_cap_long_prefix_and_existing_whole_family_fallback():
    scalar, array = arity_candidates()
    suffix = 'bytea, text[], text[]'
    group = ' '*(m.MAX_ROW-len(suffix)) + suffix
    array = replace(array, identity=(*array.identity[:3], group))
    assert resolve_arity(matches=(scalar, array)).exact is None
    with pytest.raises(m.MetadataUnavailable):
        resolve_arity(matches=(scalar, array), group=(group[:-2]+'x]').encode())
    oversized = replace(array, identity=(*array.identity[:3], ' '+group))
    with pytest.raises(m.MetadataUnavailable) as caught: resolve_arity(matches=(scalar, oversized))
    assert caught.value.reason == 'limit'
    # Old all-unsupported structural branch retains its old larger-group limits.
    assert resolve_arity(matches=(oversized,), group=(' '+group).encode()).exact is None


@pytest.mark.parametrize('error_kind', ['metadata', 'ledger', 'keyboard', 'exit', 'clock'])
@pytest.mark.parametrize('seam,visit', [('_arity_disjoint_target',1), ('_arity_disjoint_target',3),
    ('_arity_disjoint_target',5), ('_arity_disjoint_target',6),
    ('_argument_group_span',5), ('_canonical_group_equal',2), ('_canonical_group_equal',7)])
def test_arity_paths_propagate_expiry_and_cancellation(seam, visit, error_kind):
    import inspect
    scalar, array = arity_candidates()
    group = ' '*8192 + array.identity[3]
    array = replace(array, identity=(*array.identity[:3], group))
    errors = {'metadata': m.MetadataUnavailable('deadline'), 'ledger': m.ledger.Unavailable('deadline'),
              'keyboard': KeyboardInterrupt('generated'), 'exit': SystemExit('generated')}
    token = errors.get(error_kind)
    code = getattr(m, seam).__code__
    class TripBudget(m.Budget):
        visits = 0
        def check(self):
            if inspect.currentframe().f_back.f_code is code:
                self.visits += 1
                if self.visits == visit:
                    if token is not None: raise token
                    self.deadline = -1  # Real existing clock guard, no extra time.
            super().check()
    budget = TripBudget(end())
    with pytest.raises(type(token) if token is not None else m.MetadataUnavailable) as caught:
        resolve_arity(matches=(scalar, array), budget=budget)
    if token is not None: assert caught.value is token
    else: assert caught.value.reason == 'deadline'
    assert budget.visits == visit


def test_omitted_member_acl_uses_semantic_binding_not_extension_dump_id():
    wire = fixture(ordered=True)
    wire['objects'][0]['acl'] = acl([item('reader', ('SELECT',)), item()])
    wire['objects'][0]['extension'] = [['pg_net', '0.20.3', OWNER]]
    src = source(wire)
    script, archive, walk = complete_walk(wire, extension_created=True,
        acl_sql=b'GRANT SELECT ON TABLE public.t TO reader;\n', acl_deps=(42,))
    assert 42 not in {entry.dump_id for entry in archive.entries}
    index = m.restore_metadata_index(script, archive, walk, src, deadline=end())
    plan = m.compile_plan(src, script=script, archive=archive, index=index, deadline=end())
    assert len(plan.candidates) == 1
    indexed = next(row for row in index['objects'] if row['identity'] == ['relation', 'public', 't'])
    assert len(indexed['aclSpans']) == 1
    assert script[slice(*indexed['aclSpans'][0])] == b'GRANT SELECT ON TABLE public.t TO reader;'


def omitted_wire(*, no_acl=False):
    wire = fixture(ordered=True)
    wire['objects'][0]['acl'] = acl([item('reader', ('SELECT',)), item()])
    wire['objects'][0]['extension'] = [['pg_net', '0.20.3', OWNER]]
    return wire, None if no_acl else b'GRANT SELECT ON TABLE public.t TO reader;\n'


@pytest.mark.parametrize('deps', [(), (20,), (42, 43), (42, 42), (0,)])
def test_omitted_member_dependency_shape_never_authenticates_a_present_id(deps):
    wire, sql = omitted_wire()
    # Raw TOC may refuse duplicates/zero even before the adapter sees them.
    with pytest.raises((m.MetadataUnavailable, m.ledger.raw_toc.Unavailable)):
        script, archive, walk = complete_walk(wire, extension_created=True, acl_sql=sql, acl_deps=deps)
        m.restore_metadata_index(script, archive, walk, source(wire), deadline=end())


def test_other_absent_dependency_changes_archive_not_semantic_identity():
    wire, sql = omitted_wire(); results = []
    for deps in ((42,), (999999,)):
        script, archive, walk = complete_walk(wire, extension_created=True, acl_sql=sql, acl_deps=deps)
        index = m.restore_metadata_index(script, archive, walk, source(wire), deadline=end())
        plan = m.compile_plan(source(wire), script=script, archive=archive, index=index, deadline=end())
        results.append((archive.raw, plan.candidates))
        assert index['objects'][0]['identity'] == ['relation', 'public', 't']
    assert results[0][0] != results[1][0]
    assert results[0][1] == results[1][1]  # No claim of authenticating the opaque ID.


@pytest.mark.parametrize('change', ['namespace', 'owner', 'class', 'oid', 'raw_pair',
    'missing_membership', 'wrong_membership', 'multiple_membership', 'extension_owner',
    'duplicate_extension', 'late_extension'])
def test_omitted_member_complete_lifecycle_and_acl_identity_required(change):
    from test_rf1086_sql_ledger import row
    wire, sql = omitted_wire()
    if change == 'missing_membership': wire['objects'][0]['extension'] = []
    if change == 'wrong_membership': wire['objects'][0]['extension'][0][0] = 'missing'
    if change == 'multiple_membership': wire['objects'][0]['extension'] *= 2
    def alter(rows):
        aclrow = next(r for r in rows if r['id'] == 52)
        extension = next(r for r in rows if r['id'] == 20)
        if change == 'namespace': aclrow['namespace'] = b'wrong'
        if change == 'owner': aclrow['owner'] = b'writer'
        if change == 'class': aclrow['class_oid'] = b'1259'
        if change == 'oid': aclrow['oid'] = b'20000'
        if change == 'raw_pair':
            # A non-creation raw row is still evidence against omitted membership.
            aclrow.update(class_oid=b'1259', oid=b'20000')
        if change == 'extension_owner': extension['owner'] = b'writer'
        if change == 'duplicate_extension':
            rows.insert(5, dict(extension, id=21))
        if change == 'late_extension':
            rows.remove(extension); rows.append(extension)
    with pytest.raises((m.MetadataUnavailable, m.ledger.Unavailable)):
        src = source(wire)
        script, archive, walk = complete_walk(wire, extension_created=True, acl_sql=sql, rows_change=alter)
        m.restore_metadata_index(script, archive, walk, src, deadline=end())


def test_extension_owner_and_namespace_are_not_member_owner_or_namespace():
    wire, sql = omitted_wire(); wire['objects'][0]['owner'] = 'writer'
    wire['objects'][0]['defaultAcl'] = acl([item('writer', grantor='writer')])
    wire['objects'][0]['acl'] = acl([item('reader', ('SELECT',), grantor='writer'), item('writer', grantor='writer')])
    def alter(rows):
        next(r for r in rows if r['id'] == 52)['owner'] = b'writer'
    script, archive, walk = complete_walk(wire, extension_created=True, acl_sql=sql, rows_change=alter)
    index = m.restore_metadata_index(script, archive, walk, source(wire), deadline=end())
    plan = m.compile_plan(source(wire), script=script, archive=archive, index=index, deadline=end())
    assert len(plan.candidates) == 1 and plan.candidates[0].object.owner == 'writer'


@pytest.mark.parametrize('sql', [
    b'GRANT SELECT ON TABLE public.t TO reader extra;',
    b'GRANT SELECT ON TABLE public.t TO reader; GRANT USAGE ON SCHEMA graphql TO reader;',
    b'GRANT SELECT (id) ON TABLE public.t TO reader;',
    b'GRANT SELECT ON TABLE public.t, public.t TO reader;',
    b'GRANT SELECT ON TABLE public.t TO missing;',
    b'GRANT SELECT ON TABLE public.t TO reader GRANTED BY writer;',
    b'GRANT EXECUTE ON FUNCTION net.http_get(wrong text) TO reader;',
])
def test_semantic_acl_whole_statement_and_same_member_entry_required(sql):
    wire, _ = omitted_wire()
    with pytest.raises((m.MetadataUnavailable, m.ledger.Unavailable)):
        script, archive, walk = complete_walk(wire, extension_created=True, acl_sql=sql+b'\n')
        m.restore_metadata_index(script, archive, walk, source(wire), deadline=end())


@pytest.mark.parametrize('deps', [(), (99999,), (30,), (20, 99999), (20,)])
@pytest.mark.parametrize('no_acl', [False, True])
def test_later_unknown_or_extension_writer_taints_all_omitted_even_no_acl(deps, no_acl):
    from test_rf1086_sql_ledger import source_rows
    wire, sql = omitted_wire(no_acl=no_acl)
    event = dict(source_rows()[-1], deps=deps)
    script, archive, walk = complete_walk(wire, extension_created=True, acl_sql=sql, post_rows=(event,))
    src = source(wire); index = m.restore_metadata_index(script, archive, walk, src, deadline=end())
    assert len(index['objects']) == len(src.objects)
    assert all(r['laterMutation'] for r in index['objects'])
    with pytest.raises(m.MetadataUnavailable) as caught:
        m.compile_plan(src, script=script, archive=archive, index=index, deadline=end())
    assert caught.value.reason == 'suffix_profile'


def test_no_acl_omitted_seed_and_source_null_rows_registered_without_invented_spans():
    wire, _ = omitted_wire(); src = source(wire)
    script, archive, walk = complete_walk(wire, extension_created=True)
    index = m.restore_metadata_index(script, archive, walk, src, deadline=end())
    assert len(index['objects']) == len(src.objects)
    assert all(r['aclSpans'] == [] and not r['laterMutation'] for r in index['objects'])
    plan = m.compile_plan(src, script=script, archive=archive, index=index, deadline=end())
    assert len(plan.candidates) == 1 and plan.counts['archiveOnly'] == 2


def test_unknown_later_writer_archive_only_is_counted_not_silently_seeded():
    from test_rf1086_sql_ledger import source_rows
    wire = fixture(ordered=True); wire['objects'][0]['extension'] = [['pg_net', '0.20.3', OWNER]]
    script, archive, walk = complete_walk(wire, extension_created=True,
        acl_sql=b'GRANT SELECT ON TABLE public.t TO reader;\n', post_rows=(source_rows()[-1],))
    src = source(wire); index = m.restore_metadata_index(script, archive, walk, src, deadline=end())
    plan = m.compile_plan(src, script=script, archive=archive, index=index, deadline=end())
    assert not plan.candidates and plan.counts['archiveOnly'] == 3 and plan.counts['unmodeled'] == 1


@pytest.mark.parametrize('authorized', [False, True])
def test_supported_member_function_arguments_full_operation_and_auth_taint(authorized):
    wire, _ = omitted_wire()
    sql = b'GRANT EXECUTE ON FUNCTION net.http_get(url text, params jsonb, headers jsonb, timeout_milliseconds integer) TO reader;\n'
    if authorized: sql = b'SET SESSION AUTHORIZATION supabase_admin;\n'+sql+b'RESET SESSION AUTHORIZATION;\n'
    def change(rows): next(r for r in rows if r['id']==52)['namespace'] = b'net'
    script, archive, walk = complete_walk(wire, extension_created=True, acl_sql=sql, rows_change=change)
    index = m.restore_metadata_index(script, archive, walk, source(wire), deadline=end())
    function = next(r for r in index['objects'] if r['identity'][2]=='http_get')
    assert len(function['aclSpans']) == 1 and function['laterMutation'] is authorized
    assert script[slice(*function['aclSpans'][0])].startswith(b'GRANT EXECUTE')


@pytest.mark.parametrize('sql', [b'RESET SESSION AUTHORIZATION;\n',
    b'SET SESSION AUTHORIZATION supabase_admin;\nGRANT SELECT ON TABLE public.t TO reader;\n',
    b'SET SESSION AUTHORIZATION supabase_admin;\nSET SESSION AUTHORIZATION supabase_admin;\n'])
def test_semantic_session_authorization_cannot_hide_unbalanced_state(sql):
    wire, _ = omitted_wire()
    with pytest.raises((m.MetadataUnavailable, m.ledger.Unavailable)):
        script, archive, walk = complete_walk(wire, extension_created=True, acl_sql=sql)
        m.restore_metadata_index(script, archive, walk, source(wire), deadline=end())


@pytest.mark.parametrize('second_unsupported', [False, True])
def test_semantic_entry_cannot_mix_two_member_targets(second_unsupported):
    wire, _ = omitted_wire()
    if second_unsupported: wire['objects'][2]['argumentModes'] = ['v']
    sql = (b'GRANT EXECUTE ON FUNCTION net.http_get(url text, params jsonb, headers jsonb, timeout_milliseconds integer) TO reader;\n'
        b'GRANT EXECUTE ON FUNCTION net.http_post(url text, body jsonb, params jsonb, headers jsonb, timeout_milliseconds integer) TO reader;\n')
    def change(rows): next(r for r in rows if r['id']==52)['namespace'] = b'net'
    script, archive, walk = complete_walk(wire, extension_created=True, acl_sql=sql, rows_change=change)
    with pytest.raises(m.MetadataUnavailable) as caught:
        m.restore_metadata_index(script, archive, walk, source(wire), deadline=end())
    assert caught.value.reason == 'archive_profile'


def test_direct_extension_member_does_not_retry_semantics_on_numeric_mismatch():
    wire, sql = omitted_wire()
    script, archive, walk = complete_walk(wire, extension_created=False, acl_sql=sql, acl_deps=(999999,))
    with pytest.raises(m.MetadataUnavailable) as caught:
        m.restore_metadata_index(script, archive, walk, source(wire), deadline=end())
    assert caught.value.reason == 'archive_profile'


def test_resolved_direct_writer_only_taints_direct_object_and_oid_does_not_clear_unknown():
    from test_rf1086_sql_ledger import source_rows
    wire = fixture(); src = source(wire)
    for deps, all_omitted in (((42,), False), ((99999,), True)):
        event = dict(source_rows()[-1], deps=deps, class_oid=b'1259', oid=b'20000')
        script, archive, walk = complete_walk(wire, post_rows=(event,))
        index = m.restore_metadata_index(script, archive, walk, src, deadline=end())
        assert index['objects'][0]['laterMutation'] is True
        assert all(r['laterMutation'] is all_omitted for r in index['objects'][1:])


def unsupported_candidates(*, owners=(OWNER, OWNER)):
    base = source().objects[1]
    # Deliberately unsupported array/mode signatures: unit input to target matching,
    # not a fabricated claim that selected pg_net functions have these signatures.
    return tuple(replace(base, identity=('function', 'private_schema', 'f', f'a type_{i}[]'),
        argument_types=(('private_schema', f'_type_{i}'),), argument_modes=('v',), owner=owner)
        for i, owner in enumerate(owners))


def resolve_unsupported(raw, *, matches=None, budget=None):
    matches = unsupported_candidates() if matches is None else matches
    budget = m.Budget(end()) if budget is None else budget
    statement = next(m._statements(raw+b'\n', budget))
    return m._target_candidates(statement, {('function', b'private_schema', b'f'): matches},
        budget, roles={'reader', 'writer', OWNER})


@pytest.mark.parametrize('group', [b'()', b'(a private_schema.type_0[], b integer)',
    b'("TO, FROM" private_schema.type_0[] /* ) , TO reader */)'])
@pytest.mark.parametrize('form', [b'GRANT EXECUTE ON FUNCTION %s TO reader;',
    b'REVOKE GRANT OPTION FOR EXECUTE ON FUNCTION %s FROM reader RESTRICT;',
    b'GRANT ALL PRIVILEGES ON FUNCTION %s TO reader GRANTED BY supabase_admin;'])
def test_unsupported_single_group_is_structural_not_overload_identity(group, form):
    result = resolve_unsupported(form % (b'private_schema.f'+group))
    assert result.exact is None and result.unmodeled is True


@pytest.mark.parametrize('sql', [
    b'GRANT EXECUTE ON FUNCTION private_schema.f(a t[]), net.http_get(text) TO reader;',
    b'REVOKE EXECUTE ON FUNCTION private_schema.f(a t[]), net.http_get(text) FROM reader;',
    b'GRANT EXECUTE ON FUNCTION private_schema.f(a t[]), private_schema.f(b t[]) TO reader;',
    b'REVOKE EXECUTE ON FUNCTION private_schema.f(a t[]), private_schema.f(b t[]) FROM reader;',
    b'GRANT EXECUTE ON FUNCTION private_schema.f(a t[]) FROM reader;',
    b'REVOKE EXECUTE ON FUNCTION private_schema.f(a t[]) TO reader;',
    b'GRANT BANANA ON FUNCTION private_schema.f(a t[]) TO reader;',
    b'GRANT EXECUTE (column) ON FUNCTION private_schema.f(a t[]) TO reader;',
    b'GRANT EXECUTE ON FUNCTION private_schema.f TO reader;',
    b'GRANT EXECUTE ON FUNCTION private_schema.f(a t[]) () TO reader;',
    b'GRANT EXECUTE ON FUNCTION private_schema.f(a t[]) TO reader, writer;',
    b'REVOKE EXECUTE ON FUNCTION private_schema.f(a t[]) FROM reader CASCADE;',
    b'GRANT EXECUTE ON FUNCTION private_schema.f(a t[]) TO PUBLIC WITH GRANT OPTION;',
    b'GRANT EXECUTE ON FUNCTION private_schema.f(a t[]) TO reader GRANTED BY writer;',
    b'GRANT EXECUTE ON FUNCTION private_schema.f(a t[]) TO missing;',
    b'GRANT EXECUTE ON FUNCTION private_schema.f(a t[]) TO reader extra;',
    b'GRANT EXECUTE ON FUNCTION private_schema.f(a t[] TO reader;',
])
def test_unsupported_statement_never_hides_unread_targets_or_tail(sql):
    with pytest.raises((m.MetadataUnavailable, m.ledger.Unavailable, m.lexical.Unavailable)):
        resolve_unsupported(sql)


def test_unsupported_granted_by_cannot_borrow_first_owner_or_supported_overload():
    sql = b'GRANT EXECUTE ON FUNCTION private_schema.f(a t[]) TO reader GRANTED BY supabase_admin;'
    matches = unsupported_candidates(owners=(OWNER, 'writer'))
    with pytest.raises(m.MetadataUnavailable): resolve_unsupported(sql, matches=matches)
    matches = unsupported_candidates()
    supported = replace(matches[0], argument_modes=None, argument_types=(('pg_catalog', 'text'),),
                        identity=('function', 'private_schema', 'f', 'text'))
    with pytest.raises(m.MetadataUnavailable): resolve_unsupported(sql, matches=(matches[0], supported))


@pytest.mark.parametrize('extension', [False, True])
def test_exact_unsupported_has_no_spans_but_direct_numeric_guard_remains(extension):
    wire, sql = omitted_wire()
    wire['objects'][0]['kind'] = 'c'
    src = source(wire)
    script, archive, walk = complete_walk(wire, extension_created=extension, acl_sql=sql)
    index = m.restore_metadata_index(script, archive, walk, src, deadline=end())
    assert index['objects'][0]['aclSpans'] == []
    plan = m.compile_plan(src, script=script, archive=archive, index=index, deadline=end())
    assert not plan.candidates and plan.counts['archiveOnly'] == 3 and plan.counts['unmodeled'] == 1
    if not extension:
        script, archive, walk = complete_walk(wire, acl_sql=sql, acl_deps=(20,))
        with pytest.raises(m.MetadataUnavailable) as caught:
            m.restore_metadata_index(script, archive, walk, src, deadline=end())
        assert caught.value.reason == 'archive_profile'


@pytest.mark.parametrize('token', [m.MetadataUnavailable('deadline'), m.ledger.Unavailable('deadline'),
                                   KeyboardInterrupt('generated cancellation')])
@pytest.mark.parametrize('seam', ['target', 'argument', 'fallback_group', 'ending'])
def test_new_matching_paths_preserve_deadline_and_cancellation_identity(monkeypatch, token, seam):
    raw = b'GRANT EXECUTE ON FUNCTION private_schema.f(a t[], b integer) TO reader;\n'
    budget = m.Budget(end()); statement = next(m._statements(raw, budget))
    matches = unsupported_candidates()
    def stop(*args, **kwargs): raise token
    if seam == 'target': monkeypatch.setattr(m, '_target', stop)
    elif seam == 'argument': monkeypatch.setattr(m, '_type', stop)
    elif seam == 'fallback_group': monkeypatch.setattr(m.Statement, 'group', stop)
    else: monkeypatch.setattr(m, '_operation_ending', stop)
    with pytest.raises(type(token)) as caught:
        m._target_candidates(statement, {('function', b'private_schema', b'f'): matches},
                             budget, roles={'reader', OWNER})
    assert caught.value is token


@pytest.mark.parametrize('token', [m.MetadataUnavailable('deadline'), m.ledger.Unavailable('deadline'),
                                   KeyboardInterrupt('one-shot cancellation')])
def test_one_shot_type_failure_cannot_be_retried_as_valid_named_argument(monkeypatch, token):
    budget = m.Budget(end())
    statement = next(m._statements(b'x(url text);\n', budget))
    statement.ident(b'x'); statement.need(b'(')
    original = m._type; calls = []
    def once(s, typ):
        calls.append(True)
        if len(calls) == 1: raise token
        return original(s, typ)
    monkeypatch.setattr(m, '_type', once)
    with pytest.raises(type(token)) as caught: m._argument(statement, ('pg_catalog', 'text'))
    assert caught.value is token and len(calls) == 1


def test_one_shot_target_deadline_cannot_fall_back_to_archive_only(monkeypatch):
    primary = m.MetadataUnavailable('deadline'); original = m._target; calls = []
    def once(s, obj):
        calls.append(True)
        if len(calls) == 1: raise primary
        return original(s, obj)
    monkeypatch.setattr(m, '_target', once)
    with pytest.raises(m.MetadataUnavailable) as caught:
        resolve_unsupported(b'GRANT EXECUTE ON FUNCTION private_schema.f(a t[], b integer) TO reader;')
    assert caught.value is primary and len(calls) == 1


def test_fallback_last_budget_check_refuses_even_after_valid_ending(monkeypatch):
    original = m._operation_ending
    def expire(s, **kwargs):
        result = original(s, **kwargs)
        s.budget.deadline = time.monotonic()-1
        return result
    monkeypatch.setattr(m, '_operation_ending', expire)
    with pytest.raises(m.MetadataUnavailable) as caught:
        resolve_unsupported(b'GRANT EXECUTE ON FUNCTION private_schema.f() TO reader;')
    assert caught.value.reason == 'deadline'


def test_index_rejects_tampered_packed_regions_and_script_binding():
    wire = fixture(); src = source(wire); script,archive,walk = complete_walk(wire)
    with pytest.raises(m.MetadataUnavailable):
        m.restore_metadata_index(script,archive,replace(walk,regions=walk.regions[:-1]+b'x'),src,deadline=end())
    with pytest.raises(m.MetadataUnavailable): m.restore_metadata_index(script+b'\n',archive,walk,src,deadline=end())


def test_source_overlap_does_not_claim_omitted_hooks_are_absent():
    wire = fixture(); raw = catalog(wire); rows = json.loads(raw.splitlines()[0])
    rows.append(['function','extensions','grant_pg_net_access','',OWNER,None,False,None])
    # Add the ordinary metadata object too, while selected projection stays two functions.
    template = deepcopy(wire['objects'][1]); template.update(objectOid=29999,
        identity=['function','extensions','grant_pg_net_access',''], argumentTypes=[],extension=[])
    wire['objects'].append(template)
    result = m.decode_metadata(encode(wire),catalog_raw=encode(rows)+b'\n{}\n[]\n',
                              roles_raw=encode(role_rows(wire))+b'\n[]\n',deadline=end())
    assert len(result.selected_catalog['functions']) == 2
    assert result.selected_catalog['hooks'] == []


def test_bound_function_argument_names_are_parsed_not_executed():
    obj = source().objects[1]
    query = b'GRANT EXECUTE ON FUNCTION net.http_get(url text, params jsonb, headers jsonb, timeout_milliseconds integer) TO reader;\n'
    statements = list(m._statements(query,m.Budget(end())))
    result = m._operation(statements[0],obj=obj,roles={'reader',OWNER})
    assert result.grantee == 'reader' and result.rights == frozenset({'EXECUTE'})
    wrong = query.replace(b'url text',b'other text')
    with pytest.raises(m.MetadataUnavailable):
        m._operation(next(m._statements(wrong,m.Budget(end()))),obj=obj,roles={'reader',OWNER})


def test_nonowner_and_column_profiles_explicitly_unmodeled_without_supplement():
    wire = fixture(ordered=True)
    wire['objects'][0]['acl'] = acl([item(),item('reader',('SELECT',),grantor='writer')])
    plan = compile_(plan_data(wire))
    assert not plan.candidates and plan.counts['unmodeled'] == 1


def column_table_walk(shape='missing', *, acl_sql=None, acl_deps=None, wire_change=None):
    """Generated source and real archive walk; source column grants are final state."""
    wire = fixture()
    obj = wire['objects'][0]
    obj['columnAclCount'] = 1
    if shape == 'missing':
        desired = [item('writer', ('SELECT',)), item('reader', ('SELECT',))]
        table_sql = (b'REVOKE ALL ON TABLE public.t FROM supabase_admin;\n'
            b'GRANT SELECT ON TABLE public.t TO reader;\n'
            b'GRANT SELECT ON TABLE public.t TO writer;\n')
    elif shape == 'partial':
        desired = [item('writer', ('SELECT',)), item(OWNER, ('SELECT',)), item('reader', ('UPDATE',))]
        table_sql = (b'REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN ON TABLE public.t FROM supabase_admin;\n'
            b'GRANT UPDATE ON TABLE public.t TO reader;\n'
            b'GRANT SELECT ON TABLE public.t TO writer;\n')
    else:
        assert shape in ('default', 'empty')
        desired = [item()] if shape == 'default' else []
        table_sql = b''
    obj['acl'] = acl(desired)
    if wire_change is not None:
        wire_change(wire)
    src = source(wire, column_rows=(['column_acl', 'public', 't', 'id',
                                    '{reader=r/supabase_admin}'],))
    sql = table_sql + b'GRANT SELECT(id) ON TABLE public.t TO reader;\n' if acl_sql is None else acl_sql
    script, archive, walk = complete_walk(wire, acl_sql=sql, acl_deps=acl_deps)
    index = m.restore_metadata_index(script, archive, walk, src, deadline=end())
    return wire, src, script, archive, index


@pytest.mark.parametrize('shape', ['missing', 'partial', 'default', 'empty'])
def test_column_table_acl_seed_preserves_source_order_before_original_column_grants(shape):
    wire, src, script, archive, index = column_table_walk(shape)
    original = bytes(script)
    plan = m.compile_plan(src, script=script, archive=archive, index=index, deadline=end())
    assert len(plan.candidates) == 1
    spans = index['objects'][0]['aclSpans']
    assert all(b'SELECT(id)' not in script[slice(*span)] for span in spans)
    assert len(spans) == (3 if shape in ('missing', 'partial') else 0)
    creation = deepcopy(wire); creation['objects'][0]['columnAclCount'] = 0
    before = target(creation)
    mutation = m.pre_acl(plan, before, deadline=end())
    assert mutation.applied == 1 and mutation.noop == 0
    assert b'(id)' not in mutation.sql and script == original
    if shape in ('missing', 'partial'):
        assert mutation.sql.index(b'TO writer;') < mutation.sql.index(b'TO reader;')
    if shape == 'missing':
        assert b'TO supabase_admin' not in mutation.sql
    if shape == 'partial':
        assert b'GRANT SELECT ON TABLE public.t TO supabase_admin;' in mutation.sql
    assert plan.candidates[0].materialize is (shape == 'default')
    after = target(creation, explicit=True)
    m.post_acl(plan, before, after, mutation, deadline=end())
    noop = m.pre_acl(plan, after, deadline=end())
    assert noop.sql == b'' and noop.applied == 0 and noop.noop == 1


@pytest.mark.parametrize('shape', ['missing', 'default'])
@pytest.mark.parametrize('explicit', [False, True])
def test_column_table_creation_requires_zero_columns_even_for_noop(shape, explicit):
    wire, src, script, archive, index = column_table_walk(shape)
    plan = m.compile_plan(src, script=script, archive=archive, index=index, deadline=end())
    with pytest.raises(m.MetadataUnavailable) as error:
        m.pre_acl(plan, target(wire, explicit=explicit), deadline=end())
    assert error.value.reason == 'creation_profile'


@pytest.mark.parametrize('drift', ['column', 'unrelated-acl', 'selected-owner', 'selected-acl'])
def test_column_table_immediate_postcheck_preserves_other_state(drift):
    wire, src, script, archive, index = column_table_walk()
    plan = m.compile_plan(src, script=script, archive=archive, index=index, deadline=end())
    creation = deepcopy(wire); creation['objects'][0]['columnAclCount'] = 0
    before, after = target(creation), target(creation, explicit=True)
    mutation = m.pre_acl(plan, before, deadline=end())
    objects = list(after.objects)
    if drift == 'column': objects[0] = replace(objects[0], columns=1)
    elif drift == 'unrelated-acl': objects[1] = replace(objects[1], acl=objects[0].acl)
    elif drift == 'selected-owner': objects[0] = replace(objects[0], owner='reader')
    else: objects[0] = replace(objects[0], acl=None)
    with pytest.raises(m.MetadataUnavailable):
        m.post_acl(plan, before, replace(after, objects=tuple(objects)), mutation, deadline=end())


def test_column_table_destructive_owner_suffix_cannot_be_rescued_by_later_grant():
    sql = (b'REVOKE ALL ON TABLE public.t FROM supabase_admin;\n'
        b'GRANT SELECT ON TABLE public.t TO supabase_admin;\n'
        b'GRANT UPDATE ON TABLE public.t TO reader;\n'
        b'GRANT SELECT ON TABLE public.t TO writer;\n'
        b'GRANT SELECT(id) ON TABLE public.t TO reader;\n')
    _, src, script, archive, index = column_table_walk('partial', acl_sql=sql)
    with pytest.raises(m.MetadataUnavailable) as error:
        m.compile_plan(src, script=script, archive=archive, index=index, deadline=end())
    assert error.value.reason == 'suffix_profile'


def test_column_table_unmodeled_column_authorization_still_taints_table_seed():
    sql = (b'REVOKE ALL ON TABLE public.t FROM supabase_admin;\n'
        b'GRANT SELECT ON TABLE public.t TO reader;\n'
        b'GRANT SELECT ON TABLE public.t TO writer;\n'
        b'SET SESSION AUTHORIZATION reader;\n'
        b'GRANT SELECT(id) ON TABLE public.t TO reader;\n'
        b'RESET SESSION AUTHORIZATION;\n')
    _, src, script, archive, index = column_table_walk(acl_sql=sql)
    row = next(row for row in index['objects'] if row['identity'] == ['relation', 'public', 't'])
    assert row['laterMutation'] and len(row['aclSpans']) == 3
    with pytest.raises(m.MetadataUnavailable) as error:
        m.compile_plan(src, script=script, archive=archive, index=index, deadline=end())
    assert error.value.reason == 'suffix_profile'


@pytest.mark.parametrize('fault', ['extension', 'initial', 'partitioned', 'nonowner',
                                 'duplicate', 'empty-item', 'public-option'])
def test_column_table_seed_domain_does_not_expand_other_profiles(fault):
    def change(wire):
        obj = wire['objects'][0]
        if fault == 'extension': obj['extension'] = [['pg_net', '0.20.3', OWNER]]
        elif fault == 'initial':
            obj['initialAcl'] = deepcopy(obj['defaultAcl']); obj['initialPrivilegeType'] = 'e'
        elif fault == 'partitioned': obj['kind'] = 'p'
        elif fault == 'nonowner': obj['acl'] = acl([item('reader', ('SELECT',), grantor='writer')])
        elif fault == 'duplicate': obj['acl'] = acl([item('reader', ('SELECT',))] * 2)
        elif fault == 'empty-item': obj['acl'] = acl([item('reader', ())])
        else: obj['acl'] = acl([item(None, ('SELECT',), ('SELECT',))])
    _, src, script, archive, index = column_table_walk(wire_change=change)
    plan = m.compile_plan(src, script=script, archive=archive, index=index, deadline=end())
    assert not plan.candidates and plan.counts['unmodeled'] == 1


def test_new_column_table_profile_retains_exact_direct_dependency():
    with pytest.raises(m.MetadataUnavailable) as error:
        column_table_walk('default', acl_deps=(20,))
    assert error.value.reason == 'archive_profile'


def test_acl_array_quoting_unicode_and_public_role_are_not_public():
    wire = fixture(); n = 'odd ,"é'
    wire['roles'].append({'name':n,'oid':17004,'superuser':False,'login':False})
    # Independent expected PG array + aclitem identifier encoding.
    wire['objects'][0]['acl'] = acl([item(),item(n,('SELECT',))],
        '{supabase_admin=arwdDxtm/supabase_admin,"\\"odd ,\\"\\"é\\"=r/supabase_admin"}')
    result = m.decode_observation(encode(wire),deadline=end())
    assert result.objects[0].acl.items[1].grantee == n
    recipient = m._recipient('PUBLIC',m.Budget(end()))
    assert recipient == b'"PUBLIC"' and m._recipient(None,m.Budget(end())) == b'PUBLIC'


def test_deadline_expiry_inside_decode_and_index_not_only_entry(monkeypatch):
    now = time.monotonic(); calls = [0]
    def clock():
        calls[0] += 1
        return now if calls[0] < 4 else now+10
    monkeypatch.setattr(m.time,'monotonic',clock)
    with pytest.raises(m.MetadataUnavailable) as caught:
        m.decode_observation(encode(fixture()),deadline=now+5)
    assert caught.value.reason == 'deadline'


def test_backup_metadata_does_not_retain_role_password():
    wire = fixture(); roles = role_rows(wire)
    roles[0]['rolpassword'] = 'private-password-canary'
    result = m.decode_metadata(encode(wire),catalog_raw=catalog(wire),roles_raw=encode(roles)+b'\n[]\n',deadline=end())
    assert b'private-password-canary' not in result._role_rows
    assert b'rolpassword' not in result._role_rows
    assert json.loads(result._roles_binding)['sha256'] == hashlib.sha256(encode(roles)+b'\n[]\n').hexdigest()


@pytest.mark.parametrize('limit,value', [('MAX_METADATA', 32), ('MAX_ROLES', 2), ('MAX_OBJECTS', 2),
                                        ('MAX_ITEMS', 0), ('MAX_TOTAL_ITEMS', 1), ('MAX_ROW', 20)])
def test_caps_fail_closed_before_candidates(limit,value,monkeypatch):
    monkeypatch.setattr(m,limit,value)
    with pytest.raises(m.MetadataUnavailable) as caught:
        m.decode_observation(encode(fixture()),deadline=end())
    assert caught.value.reason == 'limit'


def test_target_observation_binds_duplicated_selected_function_acl():
    wire = fixture()
    wire['selectedFunctions'][0]['row'][5] = '{supabase_admin=X/supabase_admin}'
    with pytest.raises(m.MetadataUnavailable): m.decode_observation(encode(wire),deadline=end())


def test_postcheck_detects_nonselected_acl_and_role_drift():
    wire = fixture(); plan = compile_(plan_data(wire)); before = target(wire); after = target(wire,explicit=True)
    change = m.pre_acl(plan,before,deadline=end())
    function = replace(after.objects[1],acl=m._default('f',OWNER))
    with pytest.raises(m.MetadataUnavailable):
        m.post_acl(plan,before,replace(after,objects=(after.objects[0],function,after.objects[2])),change,deadline=end())
    with pytest.raises(m.MetadataUnavailable):
        m.post_acl(plan,before,replace(after,roles=(replace(after.roles[0],login=True),*after.roles[1:])),change,deadline=end())


def test_postcheck_cannot_borrow_another_mutation_even_same_count():
    wire = fixture(); plan = compile_(plan_data(wire)); before = target(wire); after = target(wire,explicit=True)
    change = m.pre_acl(plan,before,deadline=end())
    with pytest.raises(m.MetadataUnavailable):
        m.post_acl(plan,before,after,replace(change,sql=change.sql+b'-- extra\n'),deadline=end())


def test_default_acl_global_reset_normalizes_absence_but_schema_empty_is_distinct():
    wire = fixture(); src, script, archive, index = plan_data(wire)
    command = b'ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin GRANT ALL ON TABLES TO supabase_admin;\n'
    start = index['preAcl']; script=script[:start]+command+b'-- done\n'
    index['script']={'bytes':len(script),'sha256':hashlib.sha256(script).hexdigest()}
    index['defaultAclSpans']=[[start,start+len(command)]]
    assert compile_((src,script,archive,index)).counts['defaultAcls']==0
    # Same command in a schema creates a nonempty per-schema row, unlike global default normalization.
    command=command.replace(b' GRANT',b' IN SCHEMA public GRANT')
    script=script[:start]+command+b'-- done\n'; index['script']={'bytes':len(script),'sha256':hashlib.sha256(script).hexdigest()}
    index['defaultAclSpans']=[[start,start+len(command)]]
    with pytest.raises(m.MetadataUnavailable): compile_((src,script,archive,index))


def test_acl_null_empty_and_explicit_default_never_collapse():
    wire=fixture(); result=m.decode_observation(encode(wire),deadline=end())
    assert result.objects[0].acl==result.objects[0].default
    wire['objects'][0]['acl']=None
    assert m.decode_observation(encode(wire),deadline=end()).objects[0].acl is None
    wire['objects'][0]['acl']=acl([])
    empty=m.decode_observation(encode(wire),deadline=end()).objects[0].acl
    assert empty is not None and empty.raw=='{}' and empty.items==()


def test_role_attribute_boolean_is_not_integer_and_anchor_oid_cannot_move():
    wire=fixture(); rows=role_rows(wire); rows[0]['rolconnlimit']=True
    with pytest.raises(m.MetadataUnavailable):
        m.decode_metadata(encode(wire),catalog_raw=catalog(wire),roles_raw=encode(rows)+b'\n[]\n',deadline=end())
    source_=source(wire); wire['roles'][1]['oid']+=1
    with pytest.raises(m.MetadataUnavailable): m.validate_role_order(source_,encode(wire['roles']),deadline=end())


def test_already_desired_net_attributes_with_wrong_definition_hash_refuse():
    wire=fixture(); plan=compile_(plan_data(wire)); good,_=catalogs()
    good['functions'][0]['definition_sha256']='f'*64
    with pytest.raises(m.MetadataUnavailable): m.prefix_mutation(plan,'In',good,deadline=end())


def test_separate_source_snapshot_provides_observed_namespace_no_fabrication():
    wire=fixture()
    decoded=m.decode_metadata(encode(wire),catalog_raw=catalog(wire),roles_raw=encode(role_rows(wire))+b'\n[]\n',deadline=end())
    assert decoded.selected_catalog['extensions']==[]
    with pytest.raises(m.MetadataUnavailable): decoded.snapshot_binding
    snapshot,_=catalogs(); bound=m.bind_source_snapshot(decoded,snapshot,deadline=end())
    assert bound.selected_catalog['extensions']==[['pg_net','0.20.3','extensions',OWNER]]
    assert bound.snapshot_binding['sha256']==hashlib.sha256(m.canonical(bound.selected_catalog)).hexdigest()
    with pytest.raises(m.MetadataUnavailable): m.bind_source_snapshot(bound,snapshot,deadline=end())
    snapshot['extensions'][0][3]='reader'
    with pytest.raises(m.MetadataUnavailable): m.bind_source_snapshot(decoded,snapshot,deadline=end())
    data=list(plan_data()); data[0]=decoded
    with pytest.raises(m.MetadataUnavailable): compile_(data)


def test_source_snapshot_selected_mismatch_and_version_are_rejected():
    wire=fixture()
    decoded=m.decode_metadata(encode(wire),catalog_raw=catalog(wire),roles_raw=encode(role_rows(wire))+b'\n[]\n',deadline=end())
    snapshot,_=catalogs(); snapshot['functions'][0]['body_sha256']='f'*64
    with pytest.raises(m.MetadataUnavailable): m.bind_source_snapshot(decoded,snapshot,deadline=end())
    snapshot,_=catalogs(); snapshot['serverVersion']=170011
    with pytest.raises(m.MetadataUnavailable): m.bind_source_snapshot(decoded,snapshot,deadline=end())


def test_prefix_consumes_once_normalized_hooks_without_hashing_again():
    wire=fixture(); plan=compile_(plan_data(wire)); source_,before=catalogs()
    hook={'identity':['function','extensions','grant_pg_net_access',''],
          'row':['function','extensions','grant_pg_net_access','',OWNER,None,False,'{search_path=extensions}'],
          'body_sha256':'a'*64,'definition_sha256':'b'*64}
    before['hooks']=[hook]
    before=m.capture._validate_snapshot(before,None)
    assert before['hooks'][0]['configurationEncoding']=='sha256-of-canonical-json'
    mutation=m.prefix_mutation(plan,'Is',before,deadline=end())
    assert mutation.applied==1
    after=deepcopy(before)
    for a,s in zip(after['schemas'],source_['schemas'],strict=True):
        a['row'][3]=s['row'][3];a['grants']=s['grants']
    m.prefix_postcheck(plan,'Is',before,after,deadline=end())
    assert after['hooks']==before['hooks']
    after['hooks'][0]['row'][-1]='c'*64
    with pytest.raises(m.MetadataUnavailable):m.prefix_postcheck(plan,'Is',before,after,deadline=end())


# These are excluded source-domain targets, not simulated system objects.
def pg_catalog_target(raw, *, candidates=None, budget=None):
    budget = m.Budget(end()) if budget is None else budget
    statement = next(m._statements(raw + b'\n', budget))
    return m._target_candidates(statement, {} if candidates is None else candidates,
        budget, roles={'reader', 'writer', OWNER})


@pytest.mark.parametrize('target,right', [
    (b'TABLE pg_catalog.pg_class', b'SELECT'),
    (b'SEQUENCE pg_catalog.synthetic_sequence', b'USAGE'),
    (b'FUNCTION pg_catalog.current_database()', b'EXECUTE'),
    (b'FUNCTION "pg_catalog".synthetic_function(a text[], b integer)', b'EXECUTE'),
    (b'PROCEDURE pg_catalog.synthetic_procedure()', b'EXECUTE'),
    (b'PROCEDURE pg_catalog.synthetic_procedure("TO, FROM" text /* ) */)', b'EXECUTE'),
])
@pytest.mark.parametrize('form', [
    b'GRANT %s ON %s TO reader;', b'GRANT %s ON %s TO PUBLIC;',
    b'GRANT %s ON %s TO reader WITH GRANT OPTION;',
    b'REVOKE %s ON %s FROM reader;',
    b'REVOKE GRANT OPTION FOR %s ON %s FROM reader RESTRICT;',
])
def test_pg_catalog_empty_family_is_structural_only(target, right, form):
    result = pg_catalog_target(form % (right, target))
    assert result.exact is None and result.unmodeled is True


@pytest.mark.parametrize('target', [b'public.missing()', b'information_schema.missing()',
    b'pg_toast.missing()', b'pg_temp.missing()', b'pg_catalogue.missing()',
    b'PG_CATALOG.missing()', b'"PG_CATALOG".missing()', b'"pg_catalog.missing"()',
    b'public."pg_catalog.missing"()', b'missing()'])
def test_pg_catalog_exception_never_exempts_other_missing_families(target):
    with pytest.raises(m.MetadataUnavailable) as caught:
        pg_catalog_target(b'GRANT EXECUTE ON FUNCTION ' + target + b' TO reader;')
    assert caught.value.reason in ('source_binding', 'suffix_profile')


@pytest.mark.parametrize('raw', [
    b'GRANT EXECUTE ON FUNCTION pg_catalog.f() TO reader GRANTED BY supabase_admin;',
    b'REVOKE EXECUTE ON FUNCTION pg_catalog.f() FROM reader GRANTED BY reader;',
    b'GRANT EXECUTE ON FUNCTION pg_catalog.f() TO reader GRANTED BY missing;',
    b'GRANT SELECT (oid, relname) ON TABLE pg_catalog.pg_class TO reader;',
    b'GRANT EXECUTE (arg) ON FUNCTION pg_catalog.f() TO reader;',
    b'GRANT USAGE ON TABLE pg_catalog.pg_class TO reader;',
    b'GRANT INSERT ON SEQUENCE pg_catalog.seq TO reader;',
    b'GRANT SELECT ON FUNCTION pg_catalog.f() TO reader;',
    b'GRANT EXECUTE ON FUNCTION pg_catalog.f() FROM reader;',
    b'REVOKE EXECUTE ON FUNCTION pg_catalog.f() TO reader;',
    b'GRANT EXECUTE ON FUNCTION pg_catalog.f() TO missing;',
    b'GRANT EXECUTE ON FUNCTION pg_catalog.f(), net.http_get(text) TO reader;',
    b'REVOKE EXECUTE ON FUNCTION pg_catalog.f(), net.http_get(text) FROM reader;',
    b'GRANT SELECT ON TABLE pg_catalog.pg_class, public.t TO reader;',
    b'REVOKE SELECT ON TABLE pg_catalog.pg_class, public.t FROM reader;',
    b'GRANT EXECUTE ON FUNCTION pg_catalog.f() TO reader, writer;',
    b'REVOKE EXECUTE ON FUNCTION pg_catalog.f() FROM reader CASCADE;',
    b'GRANT EXECUTE ON FUNCTION pg_catalog.f() TO PUBLIC WITH GRANT OPTION;',
    b'GRANT EXECUTE ON FUNCTION pg_catalog.f TO reader;',
    b'GRANT EXECUTE ON FUNCTION pg_catalog.f() () TO reader;',
    b'GRANT EXECUTE ON FUNCTION pg_catalog.f(text TO reader;',
    b'GRANT EXECUTE ON FUNCTION pg_catalog.f(; SELECT 1) TO reader;',
    b'GRANT EXECUTE ON FUNCTION pg_catalog.f() TO reader extra;',
])
def test_pg_catalog_empty_family_requires_complete_closed_statement(raw):
    with pytest.raises((m.MetadataUnavailable, m.ledger.Unavailable, m.lexical.Unavailable)):
        pg_catalog_target(raw)


def test_pg_catalog_nonempty_family_uses_existing_exact_checks():
    # Contradictory synthetic input, deliberately not a claim about METADATA_SQL.
    obj = replace(source().objects[0], identity=('relation', 'pg_catalog', 'pg_class'))
    candidates = {('relation', b'pg_catalog', b'pg_class'): (obj,)}
    raw = b'GRANT SELECT ON TABLE pg_catalog.pg_class TO reader GRANTED BY supabase_admin;'
    result = pg_catalog_target(raw, candidates=candidates)
    assert result.exact is obj and result.unmodeled is False
    with pytest.raises(m.MetadataUnavailable): pg_catalog_target(raw)
    with pytest.raises(m.MetadataUnavailable):
        pg_catalog_target(b'GRANT USAGE ON SEQUENCE pg_catalog.pg_class TO reader;', candidates=candidates)


@pytest.mark.parametrize('deps', [(42,), (99999,)])
def test_pg_catalog_exclusion_preserves_direct_spans_and_dependency_guard(deps):
    wire = fixture(ordered=True)
    system = b'GRANT EXECUTE ON FUNCTION pg_catalog.current_database() TO reader;\n'
    ordinary = b'GRANT SELECT ON TABLE public.t TO reader;\n'
    script, archive, walk = complete_walk(wire, acl_sql=system+ordinary, acl_deps=deps)
    if deps != (42,):
        with pytest.raises(m.MetadataUnavailable) as caught:
            m.restore_metadata_index(script, archive, walk, source(wire), deadline=end())
        assert caught.value.reason == 'archive_profile'
        return
    index = m.restore_metadata_index(script, archive, walk, source(wire), deadline=end())
    spans = [span for row in index['objects'] for span in row['aclSpans']]
    assert len(spans) == 1 and script[slice(*spans[0])] == ordinary.rstrip(b'\n')
    assert all(row['identity'][1] != 'pg_catalog' for row in index['objects'])


def test_pg_catalog_exclusion_cannot_mix_with_omitted_semantic_member():
    wire, ordinary = omitted_wire()
    sql = b'GRANT EXECUTE ON FUNCTION pg_catalog.current_database() TO reader;\n' + ordinary
    script, archive, walk = complete_walk(wire, extension_created=True, acl_sql=sql, acl_deps=(42,))
    with pytest.raises(m.MetadataUnavailable) as caught:
        m.restore_metadata_index(script, archive, walk, source(wire), deadline=end())
    assert caught.value.reason == 'archive_profile'


@pytest.mark.parametrize('seam', ['group', 'ending'])
@pytest.mark.parametrize('primary', [m.MetadataUnavailable('deadline'),
    m.ledger.Unavailable('deadline'), m.ledger.Unavailable('limit'),
    m.lexical.Unavailable('deadline'), m.lexical.Unavailable('limit'),
    KeyboardInterrupt('generated'), SystemExit('generated')])
def test_pg_catalog_exclusion_preserves_resource_and_cancel_identity(monkeypatch, seam, primary):
    def stop(*args, **kwargs): raise primary
    if seam == 'group': monkeypatch.setattr(m.Statement, 'group', stop)
    else: monkeypatch.setattr(m, '_operation_ending', stop)
    with pytest.raises(type(primary)) as caught:
        pg_catalog_target(b'GRANT EXECUTE ON FUNCTION pg_catalog.f(a text, b integer) TO reader;')
    assert caught.value is primary


def test_pg_catalog_exclusion_checks_deadline_after_complete_ending(monkeypatch):
    original = m._operation_ending
    def expire(s, **kwargs):
        result = original(s, **kwargs)
        s.budget.deadline = -1
        return result
    monkeypatch.setattr(m, '_operation_ending', expire)
    with pytest.raises(m.MetadataUnavailable) as caught:
        pg_catalog_target(b'GRANT EXECUTE ON FUNCTION pg_catalog.f() TO reader;')
    assert caught.value.reason == 'deadline'


def column_target(raw, *, empty_family):
    candidates = {}
    obj = None
    if not empty_family:
        obj = replace(source().objects[0], columns=1)
        candidates[('relation', b'public', b't')] = (obj,)
    target = b'pg_catalog.pg_class' if empty_family else b'public.t'
    result = pg_catalog_target(raw.replace(b'@TABLE@', target), candidates=candidates)
    assert result.unmodeled is True and result.exact is obj
    return result


@pytest.mark.parametrize('empty_family', [False, True])
@pytest.mark.parametrize('rights', [b'SELECT(id)', b'INSERT(id)', b'REFERENCES(id)', b'UPDATE(id)',
    b'ALL(id)', b'ALL PRIVILEGES(id)', b'SELECT(id),INSERT(id),REFERENCES(id),UPDATE(id)',
    b'SELECT("C"),UPDATE("C")', b'SELECT("odd,""name"),UPDATE("odd,""name")',
    'SELECT("é"),UPDATE("é")'.encode(), b'SELECT (oid)',
    b'SELECT /* trivia */ (id), UPDATE(id)', b'SELECT("'+b'""'*63+b'")'])
def test_unmodeled_column_rights_preserve_bounded_single_token(rights, empty_family):
    column_target(b'GRANT '+rights+b' ON TABLE @TABLE@ TO reader;', empty_family=empty_family)


@pytest.mark.parametrize('empty_family', [False, True])
@pytest.mark.parametrize('sql', [
    b'GRANT SELECT(id) ON TABLE @TABLE@ TO PUBLIC;',
    b'GRANT SELECT(id) ON TABLE @TABLE@ TO reader WITH GRANT OPTION;',
    b'REVOKE SELECT(id) ON TABLE @TABLE@ FROM reader;',
    b'REVOKE GRANT OPTION FOR SELECT(id) ON TABLE @TABLE@ FROM reader RESTRICT;',
])
def test_unmodeled_column_existing_endings(sql, empty_family):
    column_target(sql, empty_family=empty_family)


@pytest.mark.parametrize('empty_family', [False, True])
@pytest.mark.parametrize('rights', [b'SELECT()', b'SELECT((id))', b'SELECT(id,other)',
    b'SELECT(id+1)', b'SELECT(t.id)', b'SELECT(id::text)', b'SELECT(id),UPDATE(other)',
    b'SELECT("C"),UPDATE(C)', b'SELECT(C),UPDATE(c)', b'SELECT("id"),UPDATE(id)',
    b'SELECT(id),SELECT(id)', b'SELECT(id),UPDATE', b'SELECT,UPDATE(id)',
    b'ALL(id),UPDATE(id)', b'SELECT(id),ALL(id)', b'DELETE(id)', b'EXECUTE(id)',
    b'"SELECT"(id)', b'SELECT(\'id\')', b'SELECT("")', b'SELECT("'+b'x'*64+b'")'])
def test_unmodeled_column_refuses_noncanonical_groups(rights, empty_family):
    with pytest.raises((m.MetadataUnavailable, m.ledger.Unavailable)):
        column_target(b'GRANT '+rights+b' ON TABLE @TABLE@ TO reader;', empty_family=empty_family)


@pytest.mark.parametrize('empty_family', [False, True])
@pytest.mark.parametrize('sql', [
    b'GRANT SELECT(id) ON TABLE @TABLE@, public.other TO reader;',
    b'GRANT SELECT(id) ON TABLE @TABLE@ TO reader, writer;',
    b'GRANT SELECT(id) ON TABLE @TABLE@ FROM reader;',
    b'GRANT SELECT(id) ON TABLE @TABLE@ TO missing;',
    b'GRANT SELECT(id) ON TABLE @TABLE@ TO PUBLIC WITH GRANT OPTION;',
    b'GRANT SELECT(id) ON TABLE @TABLE@ TO reader WITH OPTION;',
    b'GRANT SELECT(id) ON TABLE @TABLE@ TO reader GRANTED BY writer;',
    b'REVOKE SELECT(id) ON TABLE @TABLE@ FROM reader CASCADE;',
    b'GRANT SELECT(id) ON TABLE @TABLE@ TO reader extra;',
])
def test_unmodeled_column_requires_entire_existing_ending(sql, empty_family):
    with pytest.raises((m.MetadataUnavailable, m.ledger.Unavailable)):
        column_target(sql, empty_family=empty_family)


def test_unmodeled_column_cannot_invent_empty_owner_or_change_other_target_kinds():
    sql = b'GRANT SELECT(id) ON TABLE @TABLE@ TO reader GRANTED BY supabase_admin;'
    column_target(sql, empty_family=False)
    with pytest.raises(m.MetadataUnavailable): column_target(sql, empty_family=True)
    for sql in (b'GRANT SELECT(id) ON TABLE public.missing TO reader;',
                b'GRANT SELECT(id) ON SEQUENCE pg_catalog.seq TO reader;',
                b'GRANT EXECUTE(id) ON FUNCTION pg_catalog.f() TO reader;'):
        with pytest.raises((m.MetadataUnavailable, m.ledger.Unavailable)):
            pg_catalog_target(sql)


@pytest.mark.parametrize('sql', [b'GRANT SELECT ON TABLE pg_catalog.t TO reader;',
                                b'GRANT SELECT(id) ON TABLE pg_catalog.t TO reader;'])
@pytest.mark.parametrize('primary', [m.MetadataUnavailable('deadline'),
    m.ledger.Unavailable('deadline'), m.ledger.Unavailable('limit'),
    m.lexical.Unavailable('deadline'), m.lexical.Unavailable('limit'),
    KeyboardInterrupt('generated'), SystemExit('generated')])
def test_unmodeled_table_prefix_preserves_nonrole_failure_identity(monkeypatch, sql, primary):
    def stop(*args): raise primary
    monkeypatch.setattr(m, '_operation_prefix', stop)
    with pytest.raises(type(primary)) as caught: pg_catalog_target(sql)
    assert caught.value is primary


def test_unmodeled_table_fallback_is_exact_class_reason_and_cursor_only(monkeypatch):
    class Subclass(m.ledger.Unavailable): pass
    class Reason(str): pass
    sql = b'GRANT SELECT(id) ON TABLE pg_catalog.t TO reader;'
    for token in (Subclass('role'), m.ledger.Unavailable(Reason('role')), m.ledger.Unavailable('binding')):
        def stop(*args): raise token
        with monkeypatch.context() as patcher:
            patcher.setattr(m, '_operation_prefix', stop)
            with pytest.raises(type(token)) as caught: pg_catalog_target(sql)
            assert caught.value is token
    seen = []
    def expire(s, domain):
        seen.append(s.budget)
        s.budget.deadline = -1
        # Deliberate required-token failure after cursor advancement. The
        # fallback must check the same expired budget, never construct a new one.
        s.at += m.lexical.RECORD.size
        raise m.ledger.Unavailable('role')
    monkeypatch.setattr(m, '_operation_prefix', expire)
    with pytest.raises(m.MetadataUnavailable) as caught: pg_catalog_target(sql)
    assert caught.value.reason == 'deadline' and len(seen) == 1
