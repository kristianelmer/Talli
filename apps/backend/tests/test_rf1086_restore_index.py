"""Construction boundaries require the complete emitter, never header searches."""
import hashlib
import time

import pytest

from test_rf1086_sql_ledger import (
    CATALOG, SETTINGS, core, header, ledger, lexical, raw_toc, row,
    script_fixture, source_rows, wire_and_list,
)


def construction(rows=None, script=None):
    rows = source_rows() if rows is None else rows
    script = script_fixture(rows) if script is None else script
    raw, listing = wire_and_list(rows)
    budget = ledger.Budget(time.monotonic()+20)
    budget.phase('metadata')
    archive, _ = raw_toc.inspect(raw, listing, budget.deadline)
    return ledger.verify_restore_core(script, archive, catalog=CATALOG, budget=budget)


def test_construction_retains_same_full_walk_and_original_private_indexes():
    script = script_fixture()
    result = construction(script=script)
    assert result.core == core(script)
    for name in ('occurrences', 'regions'):
        raw = getattr(result, name)
        assert result.core.indexes[name] == {
            'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    first_acl = next(e for e in source_rows() if e['description'] == b'ACL')
    assert result.pre_acl['cut'] == script.index(header(first_acl))
    assert result.pre_acl['session'] == [1, None, None]
    assert result.core.script['bytes'] == len(script)


def test_hook_is_before_acl_prelude_and_after_last_main_owner_postlude():
    rows = source_rows()
    index = next(i for i, e in enumerate(rows) if e['description'] == b'ACL')
    rows.insert(index, row(42, b'SCHEMA', b'last_schema', b'CREATE SCHEMA last_schema;\n',
                           drop=b'DROP SCHEMA last_schema;\n', owner=b'owner'))
    next(e for e in rows if e['description'] == b'ACL')['tablespace'] = b'acl_space'
    script = script_fixture(rows)
    result = construction(rows, script)
    cut = result.pre_acl['cut']
    assert script[:cut].endswith(b'ALTER SCHEMA last_schema OWNER TO owner;\n\n')
    assert script[cut:].startswith(b'SET default_tablespace = acl_space;\n\n')
    # The ACL's own assignment is not incorrectly recorded as prefix state.
    assert result.pre_acl['session'] == [1, None, None]


def test_hook_follows_copy_terminator_and_late_database_reconnect():
    rows = source_rows()
    index = next(i for i, e in enumerate(rows) if e['description'] == b'ACL')
    rows[index:index] = [
        row(41, b'TABLE DATA', b'fixture', dumper=1, namespace=b'public',
            copy=b'COPY public.fixture (id, value) FROM stdin;\n'),
        row(42, b'DATABASE PROPERTIES', b'postgres',
            b"ALTER DATABASE postgres SET statement_timeout TO '0';\n"),
    ]
    payload = b'1\t-- Type: ACL; fake boundary\n2\t\\\\connect postgres\n'
    script = script_fixture(rows, copy_payload=payload)
    result = construction(rows, script)
    assert result.pre_acl['session'] == [2, None, None]
    assert script[:result.pre_acl['cut']].endswith(SETTINGS)
    assert result.core.counts['copyGroups'] == 1
    assert result.core.counts['reconnects'] == 2
    occurrences = list(ledger.OCCURRENCE.iter_unpack(result.occurrences))
    assert all(e[1] == ledger.PASSES['MAIN'] for e in occurrences[:result.pre_acl['occurrence']])
    assert occurrences[-1][1] == ledger.PASSES['POST_ACL']
    assert occurrences[-1][5] < len(script)  # verified footer also remains in the original stream


def test_no_acl_pass_cannot_supply_a_construction_hook():
    rows = [e for e in source_rows() if e['description'] != b'ACL']
    with pytest.raises(ledger.Unavailable, match='sql_ledger_unavailable'):
        construction(rows)


@pytest.mark.parametrize('mutate', [
    lambda s: s[:-1],
    lambda s: s+b'SELECT 1;\n',
    lambda s: s.replace(b'ALTER SCHEMA graphql OWNER TO owner;', b'ALTER SCHEMA graphql OWNER TO other;'),
    lambda s: s.replace(b'CREATE EVENT TRIGGER', b'DROP EVENT TRIGGER'),
])
def test_late_or_owner_corruption_never_returns_an_earlier_valid_hook(mutate):
    with pytest.raises((ledger.Unavailable, lexical.Unavailable)):
        construction(script=mutate(script_fixture()))
