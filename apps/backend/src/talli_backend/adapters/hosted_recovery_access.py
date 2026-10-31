"""Source-bound named privileges, including fresh-project default ACL repair."""
import json

from talli_backend.adapters.hosted_recovery_capture import (
    encoded, normalized_access, normalized_catalog, qi, require,
)
from talli_backend.adapters.hosted_recovery_sql import CATALOG_SQL, execute_batch

ACCESS_SQL = """select jsonb_build_object(
'schemas',(select coalesce(jsonb_agg(jsonb_build_array(nspname,pg_get_userbyid(nspowner),
coalesce((select jsonb_agg(jsonb_build_array(pg_get_userbyid(a.grantor),
case when a.grantee=0 then 'PUBLIC'else pg_get_userbyid(a.grantee)end,a.privilege_type,a.is_grantable))
from aclexplode(coalesce(nspacl,acldefault('n',nspowner)))a),'[]'::jsonb))),'[]'::jsonb)
from pg_namespace where nspname=any(%s)),
'relations',(select coalesce(jsonb_agg(jsonb_build_array(n.nspname,c.relname,c.relkind,
pg_get_userbyid(c.relowner),coalesce((select jsonb_agg(jsonb_build_array(pg_get_userbyid(a.grantor),
case when a.grantee=0 then 'PUBLIC'else pg_get_userbyid(a.grantee)end,a.privilege_type,a.is_grantable))
from aclexplode(coalesce(c.relacl,acldefault(case when c.relkind='S'then'S'::"char"else'r'::"char"end,c.relowner)))a),
'[]'::jsonb))),'[]'::jsonb)from pg_class c join pg_namespace n on n.oid=c.relnamespace
where n.nspname=any(%s)and c.relkind in('r','p','v','m','S')))
"""
DATABASE_ACCESS_SQL = """select jsonb_build_object('database',datname,'owner',pg_get_userbyid(datdba),
'grants',(select jsonb_agg(jsonb_build_array(pg_get_userbyid(a.grantor),
case when a.grantee=0 then null else pg_get_userbyid(a.grantee)end,a.privilege_type,a.is_grantable))
from aclexplode(coalesce(datacl,acldefault('d',datdba)))a))from pg_database where datname=current_database()"""


def grantee(name):
    return 'PUBLIC' if name in (None, 'PUBLIC') else qi(name)


def restore_database_access(db, expected):
    require(expected is not None, 'hosted_database_acl_profile_required')
    actual = db.execute(DATABASE_ACCESS_SQL).fetchone()[0]
    require(actual['database'] == expected['database'] == 'postgres' and
        actual['owner'] == expected['owner'] == 'postgres', 'hosted_database_owner_changed')
    for role in sorted({r[1] for r in actual['grants'] + expected['grants'] if r[1] is not None}):
        db.execute('revoke all on database postgres from ' + grantee(role) + ' cascade')
    db.execute('revoke all on database postgres from public cascade')
    for grantor, role, privilege, option in expected['grants']:
        require(grantor == 'postgres' and privilege in ('CONNECT', 'CREATE', 'TEMPORARY'),
            'hosted_database_acl_unsupported')
        db.execute('grant ' + privilege + ' on database postgres to ' + grantee(role) +
            (' with grant option' if option else ''))
    observed = db.execute(DATABASE_ACCESS_SQL).fetchone()[0]
    require(sorted(observed['grants'], key=encoded) == sorted(expected['grants'], key=encoded),
        'hosted_database_acl_changed')


def restore_access(db, capture, final_memberships):
    """Repair only captured identities; changed bodies/owners always stop restore.

    PostgreSQL fresh-project DEFAULT PRIVILEGES can add anon/authenticated grants
    which native ACL deltas do not revoke. Reset from captured complete sets,
    under the actual owning role so grantors and grant options remain meaningful.
    """
    schemas = sorted(capture.schemas)
    scope = capture.schemas | {'auth', 'storage'}
    actual = db.execute(CATALOG_SQL).fetchone()[0]
    expected_functions = {tuple(r[:3]): r for r in capture.catalog['functions'] if r[0] in scope}
    actual_functions = {tuple(r[:3]): r for r in actual['functions'] if r[0] in scope}
    require(set(expected_functions) == set(actual_functions), 'hosted_function_inventory_changed')
    observed_access = db.execute(ACCESS_SQL, (schemas, schemas)).fetchone()[0]
    enabled = set()
    repairs = {'functions': 0, 'relations': 0, 'schemas': 0}

    def reset(kind, identity, owner, wanted, present):
        require(all(r[0] == owner for r in wanted), 'hosted_acl_grantor_chain_unsupported')
        db.execute('set local role postgres')
        if owner not in ('postgres', 'pg_database_owner'):
            if owner not in enabled:
                db.execute('grant ' + qi(owner) + ' to postgres with set true')
                enabled.add(owner)
            db.execute('set local role ' + qi(owner))
        for name in sorted({r[1] for r in wanted + present} | {owner, 'PUBLIC'}):
            db.execute('revoke all on ' + kind + ' ' + identity + ' from ' + grantee(name) + ' cascade')
        for grantor, name, privilege, option in wanted:
            require(privilege in {'EXECUTE', 'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE',
                'REFERENCES', 'TRIGGER', 'MAINTAIN', 'USAGE', 'CREATE'}, 'hosted_acl_privilege_invalid')
            db.execute('grant ' + privilege + ' on ' + kind + ' ' + identity + ' to ' +
                grantee(name) + (' with grant option' if option else ''))
        db.execute('set local role postgres')

    for identity, wanted in expected_functions.items():
        present = actual_functions[identity]
        require(wanted[:5] == present[:5], 'hosted_function_definition_or_owner_changed')
        if sorted(wanted[5], key=encoded) != sorted(present[5], key=encoded):
            reset('function', qi(identity[0]) + '.' + qi(identity[1]) + '(' + identity[2] + ')',
                wanted[4], wanted[5], present[5])
            repairs['functions'] += 1
    for category in ('relations', 'schemas'):
        size = 2 if category == 'relations' else 1
        wanted_rows = {tuple(r[:size]): r for r in capture.access[category]}
        present_rows = {tuple(r[:size]): r for r in observed_access[category]}
        require(set(wanted_rows) == set(present_rows), 'hosted_access_inventory_changed')
        for identity, wanted in wanted_rows.items():
            present = present_rows[identity]
            require(wanted[:-1] == present[:-1], 'hosted_relation_or_schema_owner_changed')
            if sorted(wanted[-1], key=encoded) != sorted(present[-1], key=encoded):
                kind = ('sequence' if wanted[2] == 'S' else 'table') if size == 2 else 'schema'
                reset(kind, '.'.join(qi(x) for x in identity), wanted[-2], wanted[-1], present[-1])
                repairs[category] += 1
    execute_batch(db, final_memberships)
    require(normalized_access(capture.access) == normalized_access(
        db.execute(ACCESS_SQL, (schemas, schemas)).fetchone()[0]), 'hosted_source_access_changed')
    require(normalized_catalog(capture.catalog, scope) == normalized_catalog(
        db.execute(CATALOG_SQL).fetchone()[0], scope), 'hosted_source_catalog_changed')
    return repairs


def row_commitments(db, tables):
    """Use the captured profile's length-prefixed row_to_json/C collation codec."""
    from hashlib import sha256
    total = 0
    result = {}
    for schema, table in tables:
        count = 0
        commitment = sha256()
        for row, in db.execute('select row_to_json(t)::text from ' + qi(schema) + '.' + qi(table) +
                ' t order by row_to_json(t)::text collate "C"'):
            raw = row.encode()
            total += len(raw)
            require(total <= 64 * 1024**2, 'hosted_row_comparison_bound')
            commitment.update(len(raw).to_bytes(8, 'big')); commitment.update(raw); count += 1
        result[schema + '.' + table] = {'rows': count, 'sha256': commitment.hexdigest()}
    return result


def verify_custom_roles(db, capture):
    """Passwords are excluded; captured LOGIN alone intentionally becomes false."""
    names = sorted(r[0] for r in capture.custom_roles)
    wanted = []
    for role in capture.custom_roles:
        row = list(role); row[5] = False; wanted.append(row)
    actual = db.execute('select rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,'
        'rolreplication,rolbypassrls,rolconnlimit,rolvaliduntil::text,rolconfig from pg_roles '
        'where rolname=any(%s)', (names,)).fetchall()
    require(sorted(wanted, key=encoded) == sorted([list(r) for r in actual], key=encoded),
        'hosted_custom_role_profile_changed')
    expected = [r for r in capture.roles['memberships'] if r[0] in names or r[1] in names]
    observed = db.execute('select r.rolname,u.rolname,g.rolname,m.admin_option,m.inherit_option,m.set_option '
        'from pg_auth_members m join pg_roles r on r.oid=m.roleid join pg_roles u on u.oid=m.member '
        'join pg_roles g on g.oid=m.grantor where r.rolname=any(%s)or u.rolname=any(%s)',
        (names, names)).fetchall()
    require(sorted(expected, key=encoded) == sorted([list(r) for r in observed], key=encoded),
        'hosted_custom_memberships_changed')
