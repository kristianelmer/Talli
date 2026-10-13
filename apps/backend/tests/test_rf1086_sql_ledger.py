"""Synthetic wire/script pairs and independent receipt forgeries. No actual data."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
import rf1086_sql_ledger as ledger
import rf1086_sql_lexical as lexical
import rf1086_raw_toc as raw_toc
from test_rf1086_raw_toc import BASE, fixture

KEY = b'A'*63
SETTINGS = (b'SET statement_timeout = 0;\nSET lock_timeout = 0;\n'
    b'SET idle_in_transaction_session_timeout = 0;\nSET transaction_timeout = 0;\n'
    b"SET client_encoding = 'UTF8';\nSET standard_conforming_strings = on;\n"
    b"SELECT pg_catalog.set_config('search_path', '', false);\n"
    b'SET check_function_bodies = false;\nSET xmloption = content;\n'
    b'SET client_min_messages = warning;\nSET row_security = off;\n\n')
CATALOG = {'serverVersion': 170006, 'schemas': [
    {'identity': ['schema', name], 'row': ['schema', name, 'owner', None]}
    for name in ('graphql', 'graphql_public')], 'extensions': [['pg_net', '1.0', 'extensions', 'owner']]}


def row(id, descriptor, name, definition=None, **kw):
    return BASE | dict(id=id, class_oid=b'2615', oid=str(1000+id).encode(), tag=name,
        description=descriptor, definition=definition, drop=None, owner=b'', deps=()) | kw


def source_rows():
    return [
        row(1, b'ENCODING', b'ENCODING', b"SET client_encoding = 'UTF8';\n"),
        row(2, b'STDSTRINGS', b'STDSTRINGS', b"SET standard_conforming_strings = 'on';\n"),
        row(3, b'SEARCHPATH', b'SEARCHPATH', b"SELECT pg_catalog.set_config('search_path', '', false);\n"),
        row(10, b'DATABASE', b'postgres', b"CREATE DATABASE postgres WITH TEMPLATE = template0 ENCODING = 'UTF8' LOCALE_PROVIDER = libc;\n",
            drop=b'DROP DATABASE postgres;\n', owner=b'owner'),
        row(20, b'EXTENSION', b'pg_net', b'CREATE EXTENSION IF NOT EXISTS pg_net WITH SCHEMA extensions;\n'),
        row(31, b'SCHEMA', b'graphql_public', b'CREATE SCHEMA graphql_public;\n',
            drop=b'DROP SCHEMA graphql_public;\n', owner=b'owner'),
        row(30, b'SCHEMA', b'graphql', b'CREATE SCHEMA graphql;\n',
            drop=b'DROP SCHEMA graphql;\n', owner=b'owner'),
        row(40, b'SEQUENCE SET', b'fixture_id_seq', b"SELECT pg_catalog.setval('public.fixture_id_seq', 1, true);\n",
            namespace=b'public'),
        row(50, b'ACL', b'SCHEMA graphql', b'GRANT USAGE ON SCHEMA graphql TO reader;\n'),
        row(60, b'EVENT TRIGGER', b'fixture_event',
            b'CREATE EVENT TRIGGER fixture_event ON ddl_command_end EXECUTE FUNCTION public.fixture();\n')]


def header(e, data=False):
    dep = b'-- Dependencies:'+b''.join(b' '+str(v).encode() for v in e['deps'])+b'\n' if e['deps'] else b''
    ns = e['namespace'] if e['namespace'] is not None else b'-'
    owner = e['owner'] if e['owner'] is not None else b'-'
    return (f"--\n-- TOC entry {e['id']} (class {e['class_oid'].decode()} OID {e['oid'].decode()})\n".encode()
        +dep+b'-- '+(b'Data for ' if data else b'')+b'Name: '+e['tag']+b'; Type: '+e['description']
        +b'; Schema: '+ns+b'; Owner: '+owner+f"\n-- Data Pos: {e['offset']}\n--\n\n".encode())


def script_fixture(rows=None, *, copy_payload=None, two_occurrences=False):
    rows = source_rows() if rows is None else rows
    output = (b'--\n-- PostgreSQL database dump\n--\n\n\\restrict '+KEY+b'\n\n'
        b'-- Dumped from database version 17.6\n-- Dumped by pg_dump version 17.6\n\n'
        b'-- Started on 2026-10-12 01:02:03 UTC\n\n'+SETTINGS+b'DROP DATABASE IF EXISTS postgres;\n')
    for e in rows[3:]:
        if e['description'] == b'TABLE DATA':
            if two_occurrences:
                output += header(e)+e['definition']+b'\n\n'
            output += header(e, True)+(e['definition']+b'\n\n' if e['definition'] else b'')
            output += e['copy']+copy_payload+b'\\.\n\n\n'
            continue
        output += header(e)+e['definition']+b'\n\n'
        if e['description'] in (b'DATABASE', b'SCHEMA') and e['owner']:
            output += b'ALTER '+e['description']+b' '+e['tag']+b' OWNER TO '+e['owner']+b';\n\n'
        if e['description'] == b'DATABASE':
            output += b'\\unrestrict '+KEY+b'\n\\connect postgres\n\\restrict '+KEY+b'\n\n'+SETTINGS
    return output+b'-- Completed on 2026-10-12 01:02:04 UTC\n\n--\n-- PostgreSQL database dump complete\n--\n\n\\unrestrict '+KEY+b'\n\n'


def wire_and_list(rows):
    raw = fixture(rows, database=b'postgres', remote=b'17.6', version=b'17.6')[0]
    body = b''
    for e in rows:
        ns = e['namespace'] if e['namespace'] is not None else b'-'
        body += str(e['id']).encode()+b'; '+e['class_oid']+b' '+e['oid']+b' '+e['description']+b' '+ns+b' '+e['tag']+b' '+(e['owner'] or b'')+b'\n'
        if e['deps']:
            body += b';\tdepends on:'+b''.join(b' '+str(v).encode() for v in e['deps'])+b'\n'
    listing = (b';\n; Archive created at 2026-10-12 01:02:03 UTC\n;     dbname: postgres\n;     TOC Entries: '
        +str(len(rows)).encode()+b'\n;     Compression: gzip\n;     Dump Version: 1.16-0\n;     Format: CUSTOM\n'
        b';     Integer: 4 bytes\n;     Offset: 8 bytes\n;     Dumped from database version: 17.6\n'
        b';     Dumped by pg_dump version: 17.6\n;\n;\n; Selected TOC Entries:\n;\n'+body)
    return raw, listing


def core(script=None, rows=None, selectors=ledger.SELECTORS):
    rows = source_rows() if rows is None else rows
    script = script_fixture(rows) if script is None else script
    raw, listing = wire_and_list(rows)
    budget = ledger.Budget(time.monotonic()+20)
    budget.phase('metadata')
    archive, _ = raw_toc.inspect(raw, listing, budget.deadline)
    return ledger.verify_core(script, archive, selectors=selectors, catalog=CATALOG, budget=budget)


def receipt_context(tmp_path):
    rows = source_rows(); raw, listing = wire_and_list(rows); script = script_fixture(rows)
    archive = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    fsql = {'status': 'full_sql_verified', 'FsqlEqualsF2': True,
            'tool': {'version': '17.6'}, 'stream': {'bytes': len(script), 'sha256': hashlib.sha256(script).hexdigest()}}
    inventory = {'sha256': hashlib.sha256(listing).hexdigest(), 'total': 10,
        'passCounts': {'SPECIAL': 3, 'MAIN': 5, 'ACL': 1, 'POST_ACL': 1}, 'checkpointIds': [30, 31, 20]}
    code = {name: 'f'*64 for name in ledger.MODULES}
    metadata = {'files': {'archive.dump': archive}, 'code': code, 'phases': {'mismatch': {'catalog': CATALOG}}}
    value = ledger.observe(tmp_path, script, listing, metadata, inventory, fsql, time.monotonic()+21,
                           read_private=lambda path, cap: raw)
    args = dict(fsql=fsql, inventory=inventory, archive_binding=archive, code=code, catalog=CATALOG)
    return value, args


def test_complete_forward_coverage_and_selected_order():
    result = core()
    assert result.counts['rows'] == 10 and result.counts['occurrences'] == 7
    assert result.counts['zeroOccurrenceRows'] == 3 and result.counts['metaLines'] == 5
    assert [v['dumpId'] for v in result.selected] == [20, 31, 30]
    script = script_fixture()
    for value in result.selected:
        assert value['entryEnd'] == value['nextPreludeStart'] == value['cut']
        assert script[value['cut']-2:value['cut']] == b'\n\n'
        assert script[value['cut']:].startswith(b'--\n-- TOC entry ')
    assert not hasattr(result, 'status') and not hasattr(result, 'schema')


def test_complete_ledger_preserves_comment_bytes_and_selected_cuts():
    baseline = core()
    rows = source_rows()
    rows[8]['definition'] = (b'-- leading\n/* outer /* nested */ */ GRANT /* interior */ '
        b'USAGE ON SCHEMA graphql TO reader; -- trailing\n')
    script = script_fixture(rows)
    result = core(script, rows)
    assert result.selected == baseline.selected
    assert result.counts == baseline.counts
    assert result.script == {'bytes': len(script), 'sha256': hashlib.sha256(script).hexdigest()}
    assert result.script != baseline.script
    assert result.indexes['regions'] != baseline.indexes['regions']
    for before, after in ((b'/* interior */ ', b''), (b'-- trailing', b'-- changed')):
        with pytest.raises(ledger.Unavailable) as caught:
            core(script.replace(before, after), rows)
        assert caught.value.reason == 'emitter'


@pytest.mark.parametrize('schema', ['rf1086-sql-ledger-v2', 'rf1086-sql-ledger-v3'])
def test_previous_token_contract_cannot_validate_as_current(tmp_path, schema):
    value, args = receipt_context(tmp_path)
    with pytest.raises(ledger.Unavailable):
        ledger.validate_receipt(value | {'schema': schema}, **args)


@pytest.mark.parametrize('stamp', [b'01:02:03 UTC', b'01:02:04 UTC'])
def test_timestamp_requires_zone_separator_even_with_empty_zone(stamp):
    script = script_fixture()
    core(script.replace(stamp, stamp[:-3]))
    with pytest.raises(ledger.Unavailable) as caught:
        core(script.replace(stamp, stamp[:-4]))
    assert caught.value.reason == 'emitter'


def test_production_receipt_binds_independent_catalog_and_inputs(tmp_path):
    value, args = receipt_context(tmp_path)
    assert value['status'] == 'verified_conditional', value
    assert ledger.validate_receipt(value, **args) is value
    expected = hashlib.sha256(json.dumps(['schema', 'graphql', 'owner'], separators=(',', ':')).encode()).hexdigest()
    assert next(v for v in value['selected'] if v['kind'] == 'graphql_schema')['semanticSha256'] == expected
    assert all(value['claims'][key] is False for key in ('runtime', 'S0', 'causality', 'recovery'))


@pytest.mark.parametrize('change', [
    lambda raw: raw+b'SELECT 1;\n', lambda raw: raw[:-1],
    lambda raw: raw.replace(b'-- Data Pos: 0', b'-- Data Pos: 1', 1),
    lambda raw: raw.replace(b'ALTER SCHEMA graphql OWNER TO owner;\n\n', b''),
    lambda raw: raw.replace(b'CREATE SCHEMA graphql;', b'CREATE SCHEMA graphql; SELECT 1;'),
    lambda raw: raw.replace(b'\\connect postgres', b'\\connect template1'),
    lambda raw: raw.replace(b'-- Completed on 2026', b'-- Completed on XXXX'),
    lambda raw: raw.replace(b'-- Started on ', b'-- Started on \n-- Started on ', 1),
    lambda raw: raw.replace(b'-- Dumped by pg_dump version 17.6', b'-- Dumped by pg_dump version 17.11'),
    lambda raw: raw.replace(b'--\n-- TOC entry 31', b'--\n-- TOC entry 30', 1),
])
def test_complete_bytes_reject_counterexamples(change):
    with pytest.raises((ledger.Unavailable, lexical.Unavailable)):
        core(change(script_fixture()))


@pytest.mark.parametrize('field,value', [('owner', b'other'), ('namespace', b''), ('definition', b'CREATE SCHEMA graphql AUTHORIZATION owner;\n')])
def test_selected_raw_owner_namespace_and_shapes(field, value):
    rows = source_rows(); rows[6][field] = value
    with pytest.raises(ledger.Unavailable): core(rows=rows)


def test_copy_markers_are_payload_and_occurrences_derive_from_requests():
    rows = source_rows()
    e = row(41, b'TABLE DATA', b'fixture', dumper=1, namespace=b'public', copy=b'COPY public.fixture (id, value) FROM stdin;\n')
    rows.insert(8, e)
    payload = b'1\t-- TOC entry 30\n2\t\\\\connect postgres\n'
    result = core(script_fixture(rows, copy_payload=payload), rows)
    assert result.counts['copyGroups'] == 1 and result.counts['occurrences'] == 8
    e['definition'] = b'-- attributed comment-only table data definition\n'
    # Ordinary arbitrary TABLE DATA definitions are not an opaque SQL fallback.
    with pytest.raises(ledger.Unavailable): core(script_fixture(rows, copy_payload=payload, two_occurrences=True), rows)


def test_complete_ledger_preserves_long_copy_rows_and_selected_cuts():
    rows = source_rows()
    rows.insert(8, row(41, b'TABLE DATA', b'fixture', dumper=1, namespace=b'public',
                        copy=b'COPY public.fixture (id, value) FROM stdin;\n'))
    payload = b'1\t'+b'x'*(2*1024**2)+b'\\.\n2\t-- TOC entry 30; \\connect hidden\n'
    script = script_fixture(rows, copy_payload=payload)
    result = core(script, rows)
    baseline = core(script_fixture(rows, copy_payload=b'1\tshort\n'), rows)
    assert result.selected == baseline.selected
    assert result.counts['copyGroups'] == 1 and result.counts['occurrences'] == 8
    assert result.counts == baseline.counts
    assert result.script == {'bytes': len(script), 'sha256': hashlib.sha256(script).hexdigest()}
    assert result.indexes['regions'] != baseline.indexes['regions']
    assert result.indexes['decisions'] == baseline.indexes['decisions']


def test_native_two_schema_core_cannot_validate_as_production(tmp_path):
    value, args = receipt_context(tmp_path)
    native = core(selectors=ledger.SELECTORS[:2])
    assert len(native.selected) == 2
    for forged in ({'schema': 'sql-ledger-native-fixture-v1', 'productionAccepted': False},
                   value | {'selected': list(native.selected)}, value | {'profile': 'pg1711-fixture'}):
        with pytest.raises(ledger.Unavailable): ledger.validate_receipt(forged, **args)


@pytest.mark.parametrize('mutate', [
    lambda v: v['selected'][0].update(semanticSha256='e'*64),
    lambda v: v['selected'][0].update(kind='other'),
    lambda v: v['selected'][0].update(dumpId=30),
    lambda v: v['selected'][0].update(classOid=0),
    lambda v: v['selected'][0].update(objectOid=True),
    lambda v: v['selected'][0].update(occurrence=v['counts']['occurrences']-1),
    lambda v: v['selected'][1].update(occurrence=v['selected'][0]['occurrence']),
    lambda v: v['selected'].reverse(),
    lambda v: v['selected'][0].update(nextPreludeStart=v['selected'][0]['cut']+1),
    lambda v: v['selected'][0].update(cut=0),
    lambda v: v['counts'].update(rows=True),
    lambda v: v['counts'].update(zeroOccurrenceRows=10),
    lambda v: v['counts'].update(metaLines=6),
    lambda v: v['indexes']['regions'].update(bytes=1),
    lambda v: v['inputs']['script'].update(sha256='a'*64),
    lambda v: v['inputs']['archive'].update(bytes=1),
    lambda v: v['code'].update({'rf1086_sql_ledger.py': 'a'*64}),
    lambda v: v['claims'].update(runtime=0),
    lambda v: v.update(extra=None),
    lambda v: v.update(configurationSha256='0'*64),
])
def test_closed_receipt_forgery_rejection(tmp_path, mutate):
    value, args = receipt_context(tmp_path)
    assert value['status'] == 'verified_conditional', value
    mutate(value)
    with pytest.raises(ledger.Unavailable): ledger.validate_receipt(value, **args)


@pytest.mark.parametrize('field,value', [('schemas', [{'identity': ['schema', 'graphql'], 'row': ['schema', 'graphql', 'other']}]),
                                       ('extensions', [['pg_net', '1.0', 'wrong', 'owner']])])
def test_original_catalog_semantic_forgery(tmp_path, field, value):
    receipt, args = receipt_context(tmp_path)
    args['catalog'] = deepcopy(args['catalog']); args['catalog'][field] = value
    with pytest.raises(ledger.Unavailable): ledger.validate_receipt(receipt, **args)


@pytest.mark.parametrize('stage,reason', [('admission', 'headroom'), ('metadata', 'input'), ('lexical', 'lexical'),
    ('emitter', 'role'), ('summary', 'summary')])
def test_finite_unavailable_and_invalid_context(stage, reason):
    value = ledger.unavailable(reason, stage)
    ledger.validate_receipt(value, fsql={})
    for changed in (value | {'stage': 'other'}, value | {'extra': None}, value | {'reason': 'raw sql'},
                    value | {'context': value['context'] | {'rowIndex': True}},
                    value | {'context': value['context'] | {'descriptor': 'unknown'}}):
        with pytest.raises(ledger.Unavailable): ledger.validate_receipt(changed, fsql={})


def test_deadline_and_input_failure_preserve_small_observation(tmp_path):
    assert ledger.observe(tmp_path, b'', b'', {}, {}, {}, time.monotonic()+19,
        read_private=lambda *a: pytest.fail('no admission')) == ledger.unavailable('headroom', 'admission')
    value = ledger.observe(tmp_path, b'', b'', {}, {}, {}, time.monotonic()+21,
        read_private=lambda *a: pytest.fail('invalid binding'))
    assert value['status'] == 'unavailable' and value['stage'] == 'metadata'
    assert len(ledger.canonical(value)) < 512


def test_independent_maximum_shape_sizing(tmp_path):
    value, _ = receipt_context(tmp_path)
    for item in value['inputs'].values(): item.update(bytes=134217728)
    value['counts'].update(rows=8192, zeroOccurrenceRows=8192, occurrences=16384,
        statements=16384, copyGroups=8192, metaLines=32, reconnects=2, regions=262144,
        passRows={'MAIN': 8192, 'ACL': 8192, 'POST_ACL': 8192, 'SPECIAL': 3})
    for item in value['indexes'].values(): item['bytes'] = 4194304
    for item in value['selected']:
        item.update(dumpId=2147483647, classOid=4294967295, objectOid=4294967295,
            occurrence=16384, preludeStart=134217728, definitionStart=134217728,
            entryEnd=134217728, nextPreludeStart=134217728, cut=134217728)
    # Deliberately overestimates jointly reachable numbers; serialization is
    # independently specified and does not call the production JSON helper.
    raw = json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(',', ':')).encode('ascii')
    assert len(raw) == 2798 and len(raw) < 4096
    failed = ledger.unavailable('internal', 'emitter', {
        'rowIndex': 8191, 'dumpId': 2147483647,
        'descriptor': max(raw_toc.DESCRIPTORS, key=len), 'offset': 134217728})
    assert len(json.dumps(failed, sort_keys=True, separators=(',', ':')).encode('ascii')) < 512


def test_optional_profile_budget_does_not_reset_per_helper():
    budget = ledger.Budget(time.monotonic()+20)
    budget.phase('metadata'); budget.phase('preparation')
    deadline = budget.deadline
    for _ in range(100):
        assert ledger.identifier(b'fixture', budget) == b'fixture'
        assert budget.deadline == deadline
    with pytest.raises(ledger.Unavailable): budget.phase('preparation')


def statements(raw):
    scan = lexical.scan(raw, deadline=time.monotonic()+5, profile=lexical.PROFILE)
    budget = ledger.Budget(time.monotonic()+20); budget.phase('metadata')
    token = 0
    for kind, start, end in lexical.RECORD.iter_unpack(scan.leaves):
        if kind != lexical.SQL: continue
        first = token
        while token < len(scan.tokens):
            _, a, b = lexical.RECORD.unpack_from(scan.tokens, token)
            if a >= end: break
            token += lexical.RECORD.size
            if b <= start: first = token
        yield ledger.Statement(raw, scan.tokens, first, token, start, end, budget)


@pytest.mark.parametrize('descriptor,definition,drop', [
    (b'SCHEMA', b'CREATE SCHEMA fixture;\n', None),
    (b'FUNCTION', b'CREATE FUNCTION public.fixture() RETURNS integer LANGUAGE sql AS $$ SELECT 1; -- TOC entry 30\n $$;\n', b'DROP FUNCTION public.fixture();\n'),
    (b'TABLE', b'CREATE TABLE public.fixture (id integer DEFAULT 1);\nALTER TABLE ONLY public.fixture ALTER COLUMN id SET STATISTICS 100;\n', None),
    (b'ACL', b'SET SESSION AUTHORIZATION owner;\nGRANT USAGE ON SCHEMA graphql TO reader;\nRESET SESSION AUTHORIZATION;\n', None),
    (b'DEFAULT', b'ALTER TABLE ONLY public.fixture ALTER COLUMN id SET DEFAULT 1;\n', None),
    (b'INDEX ATTACH', b'ALTER INDEX public.parent ATTACH PARTITION public.child;\n', None),
    (b'SEQUENCE SET', b"SELECT pg_catalog.setval('public.fixture', 9, false);\n", None),
    (b'COMMENT', b"COMMENT ON SCHEMA fixture IS '-- TOC entry 30';\n", None),
    (b'TYPE', b"CREATE TYPE public.fixture AS ENUM ('one', 'two');\n", None),
    (b'DOMAIN', b'CREATE DOMAIN public.fixture AS integer CHECK (VALUE > 0);\n', None),
    (b'SHELL TYPE', b'CREATE TYPE public.fixture;\n', None),
    (b'SEQUENCE', b'CREATE SEQUENCE public.fixture START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;\n', None),
    (b'SEQUENCE OWNED BY', b'ALTER SEQUENCE public.fixture OWNED BY public.table_name.id;\n', None),
    (b'VIEW', b'CREATE VIEW public.fixture AS SELECT 1 AS value;\n', None),
    (b'MATERIALIZED VIEW', b'CREATE MATERIALIZED VIEW public.fixture AS SELECT 1 AS value WITH NO DATA;\n', None),
    (b'MATERIALIZED VIEW DATA', b'REFRESH MATERIALIZED VIEW public.fixture;\n', None),
    (b'TABLE ATTACH', b'ALTER TABLE ONLY public.parent ATTACH PARTITION public.child FOR VALUES IN (1);\n', None),
    (b'INDEX', b'CREATE INDEX fixture ON public.table_name USING btree (id);\n', None),
    (b'CONSTRAINT', b'ALTER TABLE ONLY public.table_name ADD CONSTRAINT fixture PRIMARY KEY (id);\n', None),
    (b'CHECK CONSTRAINT', b'ALTER DOMAIN public.domain_name ADD CONSTRAINT fixture CHECK (VALUE > 0);\n', None),
    (b'FK CONSTRAINT', b'ALTER TABLE ONLY public.child ADD CONSTRAINT fixture FOREIGN KEY (id) REFERENCES public.parent(id);\n', None),
    (b'TRIGGER', b'CREATE TRIGGER fixture AFTER INSERT ON public.table_name FOR EACH ROW EXECUTE FUNCTION public.trigger_function();\n', None),
    (b'RULE', b'CREATE RULE fixture AS ON DELETE TO public.table_name DO INSTEAD NOTHING;\n', None),
    (b'POLICY', b'CREATE POLICY fixture ON public.table_name FOR SELECT TO reader USING (true);\n', None),
    (b'ROW SECURITY', b'ALTER TABLE public.fixture ENABLE ROW LEVEL SECURITY;\n', None),
    (b'PUBLICATION', b"CREATE PUBLICATION fixture WITH (publish = 'insert, update');\n", None),
    (b'PUBLICATION TABLE', b'ALTER PUBLICATION fixture ADD TABLE ONLY public.table_name WHERE (id > 0);\n', None),
    (b'PUBLICATION TABLES IN SCHEMA', b'ALTER PUBLICATION fixture ADD TABLES IN SCHEMA public;\n', None),
    (b'AGGREGATE', b'CREATE AGGREGATE public.fixture(integer) (SFUNC = public.add, STYPE = integer);\n', None),
    (b'OPERATOR CLASS', b'CREATE OPERATOR CLASS public.fixture FOR TYPE integer USING btree AS STORAGE integer;\n', None),
    (b'OPERATOR FAMILY', b'CREATE OPERATOR FAMILY public.fixture USING btree;\n', None),
])
def test_roles_accept_neutral_source_shapes_and_reject_extra_top_level_sql(descriptor, definition, drop):
    e = row(77, descriptor, b'fixture', definition, drop=drop, namespace=None if descriptor == b'SCHEMA' else b'public')
    archive = raw_toc.decode(fixture([e])[0], raw_toc.Budget(time.monotonic()+5))
    budget = ledger.Budget(time.monotonic()+20); budget.phase('metadata')
    ledger.validate_definition(archive.entries[0], statements(definition), budget)
    for extra in (b'SELECT 1;\n', b'SET search_path = bad;\n', b'CALL public.unexpected();\n'):
        with pytest.raises(ledger.Unavailable):
            ledger.validate_definition(archive.entries[0], statements(definition+extra), budget)


@pytest.mark.parametrize('query,accepted', [
    (b'SELECT 1 WITH NO DATA;', True),
    (b'SELECT 1 WITH /* gap */ NO\n DATA; -- tail\n', True),
    (b'SELECT 1; -- WITH NO DATA;\n', False),
    (b'SELECT 1 /* WITH NO DATA */;', False),
    (b"SELECT 'WITH NO DATA';", False),
    (b'SELECT $$WITH NO DATA$$;', False),
    (b'SELECT "WITH" "NO" "DATA";', False),
    (b'SELECT (WITH NO DATA);', False),
])
def test_materialized_view_requires_exposed_statement_suffix(query, accepted):
    definition = b'CREATE MATERIALIZED VIEW public.fixture AS '+query+b'\n'
    e = row(77, b'MATERIALIZED VIEW', b'fixture', definition, namespace=b'public')
    entry = raw_toc.decode(fixture([e])[0], raw_toc.Budget(time.monotonic()+5)).entries[0]
    budget = ledger.Budget(time.monotonic()+20); budget.phase('metadata')
    if accepted:
        ledger.validate_definition(entry, statements(definition), budget)
    else:
        with pytest.raises(ledger.Unavailable) as caught:
            ledger.validate_definition(entry, statements(definition), budget)
        assert caught.value.reason == 'role'


@pytest.mark.parametrize('definition', [
    b'GRANT USAGE ON SCHEMA graphql TO reader;\nREVOKE USAGE ON SCHEMA graphql FROM reader;\n',
    b'SET SESSION AUTHORIZATION owner;\nRESET SESSION AUTHORIZATION;\n',
    b'SET SESSION AUTHORIZATION owner;\nREVOKE USAGE ON SCHEMA graphql FROM reader;\nRESET SESSION AUTHORIZATION;\n',
    b'SET SESSION AUTHORIZATION owner;\nGRANT USAGE ON SCHEMA graphql TO reader WITH GRANT OPTION;\nGRANT USAGE ON SCHEMA graphql TO reader;\nRESET SESSION AUTHORIZATION;\n',
    b'GRANT USAGE ON SCHEMA graphql TO reader, other;\n',
])
def test_acl_source_order_and_authorization_groups(definition):
    e = row(77, b'ACL', b'SCHEMA graphql', definition)
    entry = raw_toc.decode(fixture([e])[0], raw_toc.Budget(time.monotonic()+5)).entries[0]
    budget = ledger.Budget(time.monotonic()+20); budget.phase('metadata')
    with pytest.raises(ledger.Unavailable): ledger.validate_definition(entry, statements(definition), budget)


def test_no_output_and_special_decisions_are_explicit():
    rows = source_rows()
    # This source-backed empty definition has no schema or data request.
    rows.insert(3, row(9, b'COMMENT', b'SCHEMA absent', None))
    raw, listing = wire_and_list(rows)
    budget = ledger.Budget(time.monotonic()+20); budget.phase('metadata')
    archive, _ = raw_toc.inspect(raw, listing, budget.deadline)
    prepared = ledger.prepare(script_fixture(), archive, ledger.SELECTORS, CATALOG, budget)
    records = list(ledger.DECISION.iter_unpack(prepared.decisions))
    assert records[:3] == [(1,0,4,0,1), (2,0,4,0,1), (3,0,4,0,1)]
    assert records[3] == (9,1,0,0,2) and prepared.zero_rows == 4


def test_selected_last_and_unsupported_raw_descriptor_reject():
    rows = source_rows(); rows = rows[:6]+rows[7:8]+rows[6:7]
    # All ordinary rows are MAIN and the script genuinely matches through EOF;
    # the last selected occurrence still lacks the required following prelude.
    with pytest.raises(ledger.Unavailable) as caught: core(script_fixture(rows), rows)
    assert caught.value.reason == 'boundary'
    rows = source_rows(); rows[7]['description'] = b'UNMODELED'
    with pytest.raises(ledger.Unavailable): core(script_fixture(), rows)
