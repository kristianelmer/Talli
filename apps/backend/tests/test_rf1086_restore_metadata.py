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
            f = next(f for f in wire['selectedFunctions'] if f['identity'] == o['identity'])
            rows.append(f['row'])
    rows.extend(s['row'] for s in wire['selectedSchemas'])
    rows.extend(['default_acl', d['owner'], d['schema'], d['kind'], d['acl']['raw']] for d in wire['defaultAcls'])
    return encode(rows) + b'\n{}\n[]\n'


def role_rows(wire):
    return [{'rolname': r['name'], 'rolsuper': r['superuser'], 'rolcanlogin': r['login'],
             'rolinherit': True, 'rolcreaterole': False, 'rolcreatedb': False,
             'rolreplication': False, 'rolbypassrls': False, 'rolconnlimit': -1,
             'rolpassword': None, 'rolvaliduntil': None} for r in wire['roles']]


def source(wire=None):
    wire = fixture() if wire is None else wire
    result = m.decode_metadata(encode(wire), catalog_raw=catalog(wire),
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


def complete_walk(wire, *, extension_created=False, acl_sql=None, acl_deps=None):
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
            namespace=b'public', owner=OWNER.encode(), deps=(20 if extension_created else 42,) if acl_deps is None else acl_deps))
    raw, listing = wire_and_list(rows); script = script_fixture(rows)
    if not extension_created:
        definition = table['definition'] + b'\n\n'
        script = script.replace(definition, definition + b'ALTER TABLE public.t OWNER TO supabase_admin;\n\n')
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
