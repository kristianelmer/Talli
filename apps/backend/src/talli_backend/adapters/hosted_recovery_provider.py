"""Exact, read-only provider state for an isolated native compatibility target.

This profile does not provision a managed service or transfer provider keys.
Provider definitions, original privileges and every row must already match.
The ordinary hosted transport deliberately supplies no isolation capability.
"""
import re

from talli_backend.adapters.hosted_recovery_capture import (
    digest, encoded, json_bytes, normalized_access, normalized_catalog, qi, require,
)

SCHEMAS = frozenset({'_realtime', 'net', 'pgboss_v10', 'supabase_functions',
    'supabase_migrations'})
MANAGED_ACCESS_SCHEMAS = frozenset({'auth', 'storage'})
STRUCTURE_SCHEMAS = SCHEMAS | MANAGED_ACCESS_SCHEMAS
PROFILE_V1 = 'talli-inert-native-provider-state-v1'
PROFILE = 'talli-inert-native-provider-state-v2'
TABLES = frozenset({'_realtime.extensions', '_realtime.feature_flags',
    '_realtime.schema_migrations', '_realtime.tenants', 'net._http_response',
    'net.http_request_queue', 'pgboss_v10.archive', 'pgboss_v10.job',
    'pgboss_v10.queue', 'pgboss_v10.schedule', 'pgboss_v10.subscription',
    'pgboss_v10.version', 'supabase_functions.hooks',
    'supabase_functions.migrations', 'supabase_migrations.schema_migrations'})
WORK_TABLES = TABLES - {'_realtime.extensions', '_realtime.feature_flags',
    '_realtime.schema_migrations', '_realtime.tenants', 'pgboss_v10.version',
    'supabase_functions.migrations', 'supabase_migrations.schema_migrations'}

# OID-independent facts missing from the common function/constraint/index/RLS
# catalog: columns/defaults, views, types, triggers, sequence definitions,
# default/column privileges, partitioning and extension membership. Values are
# private capture material; receipts contain only its commitment.
SQL = """select jsonb_build_object(
'relations',(select coalesce(jsonb_agg(jsonb_build_array(n.nspname,c.relname,c.relkind,
pg_get_userbyid(c.relowner),c.relpersistence,c.relreplident,c.reloptions,
pg_get_expr(c.relpartbound,c.oid),case when c.relkind='p' then pg_get_partkeydef(c.oid) end,
case when c.relkind in('v','m') then pg_get_viewdef(c.oid,true) end,
(select coalesce(jsonb_agg(jsonb_build_array(a.attname,format_type(a.atttypid,a.atttypmod),
a.attnotnull,a.attidentity,a.attgenerated,pg_get_expr(d.adbin,d.adrelid),a.attacl::text,
co.collname,cn.nspname)order by a.attnum),'[]')from pg_attribute a
left join pg_attrdef d on d.adrelid=a.attrelid and d.adnum=a.attnum
left join pg_collation co on co.oid=a.attcollation left join pg_namespace cn on cn.oid=co.collnamespace
where a.attrelid=c.oid and a.attnum>0 and not a.attisdropped))order by n.nspname,c.relname),'[]')
from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname=any(%s)),
'types',(select coalesce(jsonb_agg(jsonb_build_array(n.nspname,t.typname,t.typtype,
pg_get_userbyid(t.typowner),format_type(t.typbasetype,t.typtypmod),t.typnotnull,t.typdefault,
(select coalesce(jsonb_agg(e.enumlabel order by e.enumsortorder),'[]')from pg_enum e where e.enumtypid=t.oid),
(select coalesce(jsonb_agg(pg_get_constraintdef(k.oid,true)order by k.conname),'[]')
from pg_constraint k where k.contypid=t.oid),t.typacl::text)order by n.nspname,t.typname),'[]')
from pg_type t join pg_namespace n on n.oid=t.typnamespace where n.nspname=any(%s)),
'triggers',(select coalesce(jsonb_agg(jsonb_build_array(n.nspname,c.relname,t.tgname,
pg_get_triggerdef(t.oid),t.tgenabled)order by n.nspname,c.relname,t.tgname),'[]')from pg_trigger t
join pg_class c on c.oid=t.tgrelid join pg_namespace n on n.oid=c.relnamespace
where not t.tgisinternal and n.nspname=any(%s)),
'sequences',(select coalesce(jsonb_agg(jsonb_build_array(n.nspname,c.relname,
format_type(s.seqtypid,null),s.seqstart,s.seqincrement,s.seqmax,s.seqmin,s.seqcache,s.seqcycle)
order by n.nspname,c.relname),'[]')from pg_sequence s join pg_class c on c.oid=s.seqrelid
join pg_namespace n on n.oid=c.relnamespace where n.nspname=any(%s)),
'defaultAcl',(select coalesce(jsonb_agg(jsonb_build_array(pg_get_userbyid(d.defaclrole),
n.nspname,d.defaclobjtype,d.defaclacl::text)order by d.defaclrole::regrole::text,n.nspname,d.defaclobjtype),'[]')
from pg_default_acl d join pg_namespace n on n.oid=d.defaclnamespace where n.nspname=any(%s)),
'extensionMembers',(select coalesce(jsonb_agg(jsonb_build_array(e.extname,i.type,i.schema,i.name,i.identity)
order by e.extname,i.type,i.identity),'[]')from pg_depend d join pg_extension e on e.oid=d.refobjid
cross join lateral pg_identify_object(d.classid,d.objid,d.objsubid)i
where d.refclassid='pg_extension'::regclass and d.deptype='e' and e.extname='pg_net'))"""


def parameters(profile_name=PROFILE):
    require(profile_name in (PROFILE_V1, PROFILE), 'hosted_provider_profile_required')
    return (sorted(STRUCTURE_SCHEMAS if profile_name == PROFILE else SCHEMAS),) * 5


def _name(value):
    require(isinstance(value, str) and re.fullmatch('[a-z_][a-z_0-9]{0,62}', value),
        'hosted_provider_profile_invalid')


def _structure_types(structure, *, schemas=SCHEMAS, roles=None):
    """Validate identities before any slicing, hashing or dynamic identifier use."""
    code = 'hosted_provider_profile_invalid'
    for category in ('relations', 'types', 'sequences'):
        rows = structure[category]
        for row in rows:
            _name(row[0]); _name(row[1])
            require(row[0] in schemas, code)
        require(len({tuple(r[:2]) for r in rows}) == len(rows), code)
    for row in structure['relations']:
        _name(row[3])
        require(roles is None or row[3] in roles, code)
        require(isinstance(row[2], str) and row[2] in ('r', 'p', 'v', 'm', 'S', 'i', 'I', 'c') and
            isinstance(row[10], list) and len(row[10]) <= 256, code)
        for column in row[10]:
            require(isinstance(column, list) and len(column) == 9, code)
            _name(column[0])
            require(isinstance(column[1], str) and type(column[2]) is bool and
                isinstance(column[3], str) and isinstance(column[4], str) and
                all(v is None or isinstance(v, str) for v in column[5:]), code)
        require(len({c[0] for c in row[10]}) == len(row[10]), code)
    for row in structure['types']:
        _name(row[3])
        require(roles is None or row[3] in roles, code)
        require(isinstance(row[2], str) and isinstance(row[4], str) and type(row[5]) is bool and
            all(row[i] is None or isinstance(row[i], str) for i in (6, 9)) and
            all(isinstance(row[i], list) and len(row[i]) <= 512 and
                all(isinstance(v, str) for v in row[i]) for i in (7, 8)), code)
    for row in structure['sequences']:
        require(isinstance(row[2], str) and all(type(v) is int and -(2**63) <= v < 2**63
            for v in row[3:8]) and type(row[8]) is bool and row[4] != 0 and
            row[6] <= row[3] <= row[5] and row[7] > 0, code)
    for row in structure['defaultAcl']:
        _name(row[0]); _name(row[1])
        require(row[1] in schemas and (roles is None or row[0] in roles) and
            isinstance(row[2], str) and isinstance(row[3], str), code)
    if roles is not None:
        for row in structure['triggers']:
            for name in row[:3]: _name(name)
            require(row[0] in schemas and isinstance(row[3], str) and
                row[4] == 'O', 'hosted_provider_trigger_side_effects_unsupported')
        require(len({tuple(r[:3]) for r in structure['triggers']}) ==
            len(structure['triggers']), code)
    for row in structure['extensionMembers']:
        require(row[0] == 'pg_net' and isinstance(row[1], str) and
            all(v is None or isinstance(v, str) for v in row[2:4]) and isinstance(row[4], str), code)


def _managed_access(value, structure, roles):
    """Require complete original Auth/Storage identities and named grant chains.

    Keep captured values verbatim. Only comparison order may be canonicalized;
    provider grantors, owners and grant options are never repaired or relabelled.
    """
    code = 'hosted_provider_managed_access_invalid'
    require(isinstance(value, dict) and set(value) == {'schemas', 'relations'} and
        all(isinstance(rows, list) and len(rows) <= 4096 for rows in value.values()), code)
    relations = {(r[0], r[1]): (r[2], r[3]) for r in structure['relations']
        if r[0] in MANAGED_ACCESS_SCHEMAS and r[2] in ('r', 'p', 'v', 'm', 'S')}
    identities = {}
    for category, rows in value.items():
        seen = set()
        for row in rows:
            require(isinstance(row, list) and len(row) ==
                (3 if category == 'schemas' else 5), code)
            count = 1 if category == 'schemas' else 2
            for name in row[:count]: _name(name)
            require(row[0] in MANAGED_ACCESS_SCHEMAS and isinstance(row[-2], str) and
                row[-2] in roles and isinstance(row[-1], list) and len(row[-1]) <= 4096, code)
            identity = tuple(row[:count])
            require(identity not in seen, code)
            seen.add(identity)
            if category == 'schemas':
                privileges = {'USAGE', 'CREATE'}
            else:
                require(isinstance(row[2], str) and identity in relations and
                    (row[2], row[3]) == relations[identity], code)
                privileges = {'SELECT', 'UPDATE', 'USAGE'} if row[2] == 'S' else {
                    'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN'}
            grants = set()
            for grant in row[-1]:
                require(isinstance(grant, list) and len(grant) == 4 and
                    all(isinstance(v, str) for v in grant[:3]) and
                    grant[0] in roles and grant[1] in roles | {'PUBLIC'} and
                    grant[2] in privileges and type(grant[3]) is bool, code)
                key = tuple(grant[:3])
                require(key not in grants, code)
                grants.add(key)
        identities[category] = seen
    require(identities['schemas'] == {(s,) for s in MANAGED_ACCESS_SCHEMAS} and
        identities['relations'] == set(relations), code)


def profile(capture):
    # Access coverage cannot hide provider tables or catalog entries. Capture
    # admission binds all three inventories before granting the inert capability.
    require(all(isinstance(r, list) and r and isinstance(r[0], str)
        for rows in capture.catalog.values() for r in rows), 'hosted_provider_profile_invalid')
    mentioned = set(capture.schemas) | {t[0] for t in capture.profile['tables']}
    mentioned |= {r[0] for rows in capture.catalog.values() for r in rows}
    mentioned |= {r[0] for r in capture.access['relations']}
    present = mentioned & SCHEMAS
    value = capture.profile.get('providerState')
    if not present:
        require(value is None, 'hosted_provider_profile_invalid')
        return None
    if not capture.source_project.startswith('native:'):
        # Hosted CLI migration history is application-owned payload. Its name
        # also appears in the native platform profile; that overlap does not
        # turn a managed capture into a native provider-state transfer.
        require(not (present - {'supabase_migrations'}), 'hosted_provider_profile_required')
        require(value is None, 'hosted_provider_profile_invalid')
        return None
    require(present == SCHEMAS and SCHEMAS <= capture.schemas and
        capture.source_project.startswith('native:') and
        isinstance(value, dict) and value.get('profile') in (PROFILE_V1, PROFILE),
        'hosted_provider_profile_required')
    extended = value['profile'] == PROFILE
    require(not extended or not (MANAGED_ACCESS_SCHEMAS & capture.schemas),
        'hosted_provider_profile_invalid')
    require(set(value) == {'profile', 'structure', 'sequenceState'} |
        ({'managedAccess'} if extended else set()), 'hosted_provider_profile_required')
    require(len(encoded(value)) <= 4 * 1024**2, 'hosted_provider_profile_invalid')
    structure = value['structure']
    require(isinstance(structure, dict) and set(structure) ==
        {'relations', 'types', 'triggers', 'sequences', 'defaultAcl', 'extensionMembers'} and
        all(isinstance(v, list) and len(v) <= 4096 for v in structure.values()),
        'hosted_provider_profile_invalid')
    sizes = {'relations': 11, 'types': 10, 'triggers': 5, 'sequences': 9,
        'defaultAcl': 4, 'extensionMembers': 5}
    require(all(isinstance(row, list) and len(row) == sizes[key]
        for key, rows in structure.items() for row in rows), 'hosted_provider_profile_invalid')
    schemas = STRUCTURE_SCHEMAS if extended else SCHEMAS
    roles = {r[0] for r in capture.roles['roles']}
    _structure_types(structure, schemas=schemas, roles=roles if extended else None)
    tables = {'.'.join(t) for t in capture.profile['tables'] if t[0] in schemas}
    require({r[0] + '.' + r[1] for r in structure['relations'] if r[2] in ('r', 'p')} == tables,
        'hosted_provider_table_profile_changed')
    require(not any(r[0] in SCHEMAS | {'auth'} for r in structure['triggers']) if extended else
        not structure['triggers'], 'hosted_background_provider_work_unsupported')
    require({'.'.join(t) for t in capture.profile['tables'] if t[0] in SCHEMAS} == TABLES,
        'hosted_provider_table_profile_changed')
    require(all(capture.rows[t]['rows'] == 0 for t in WORK_TABLES),
        'hosted_background_provider_work_unsupported')
    require(['pg_net', '0.20.3', 'supabase_admin', 'extensions'] in capture.profile['extensions'] and
        ['pg_net', 'schema', None, 'net', 'net'] in structure['extensionMembers'],
        'hosted_provider_extension_membership_changed')
    if extended:
        _managed_access(value['managedAccess'], structure, roles)
    # Auth/Storage counters are restored by the importer. Only immutable
    # provider counters are prerequisites, even when their definitions span V2.
    sequences = [r for r in structure['sequences'] if r[0] in SCHEMAS]
    require(isinstance(value['sequenceState'], list) and len(value['sequenceState']) <= 512 and
        all(isinstance(r, list) and len(r) == 4 and isinstance(r[0], str) and
            isinstance(r[1], str) and type(r[2]) is int and type(r[3]) is bool
            for r in value['sequenceState']) and
        {tuple(r[:2]) for r in value['sequenceState']} ==
        {tuple(r[:2]) for r in sequences} and
        len(value['sequenceState']) == len(sequences),
        'hosted_provider_sequence_profile_changed')
    for schema, name, counter, _ in value['sequenceState']:
        _name(schema); _name(name)
        sequence = next(r for r in sequences if r[:2] == [schema, name])
        require(sequence[6] <= counter <= sequence[5], 'hosted_provider_sequence_profile_changed')
    return value


def summary(capture):
    value = profile(capture)
    if value is None:
        return None
    return {'profile': value['profile'], 'structureSha256': digest(encoded(value)),
        **({'version': 2, 'ownerPolicyStageRequired': True,
            'managedAccessAlreadyPresentRequired': True,
            'managedAccessImportAuthorized': False} if value['profile'] == PROFILE else {}),
        'tables': {t: capture.rows[t] for t in sorted(TABLES)},
        'stateAlreadyPresentRequired': True, 'providerStateImportAuthorized': False,
        'customRolesAlreadyPresentRequired': True, 'customRoleImportAuthorized': False,
        'managedPolicyInstallRequiresOriginalOwner': sorted({r[0] + '.' + r[1]
            for r in capture.catalog['policies'] if r[0] in ('auth', 'storage')}),
        'providerServiceActivationAuthorized': False, 'providerKeyPortabilityVerified': False}


def role_program(capture, *, definition_owners=()):
    """Use original pre-provisioned roles; never replace an original grantor.

    Native fixtures can include a provider-granted membership to a custom
    operator. postgres cannot recreate that grant as supabase_admin. The inert
    profile therefore requires the complete original role graph up front.
    Only temporary owner access needed by application DDL is adjusted here.
    """
    custom = {r[0] for r in capture.custom_roles}
    scope = capture.application_schemas | {'auth', 'storage'}
    owners = {r[-2] for rows in capture.access.values() for r in rows if r[0] in scope}
    owners |= {r[4] for r in capture.catalog['functions'] if r[0] in scope}
    owners |= set(definition_owners)
    temporary = custom & owners
    start = ''.join('grant ' + qi(role) + ' to postgres with inherit true,set true;'
        for role in sorted(temporary))
    final = []
    roots = set()
    for parent, member, grantor, admin, inherit, can_set in capture.roles['memberships']:
        if parent not in temporary or member != 'postgres' or grantor != 'postgres':
            continue
        roots.add(parent)
        final.append('grant ' + qi(parent) + ' to postgres with admin ' + str(admin).lower() +
            ',inherit ' + str(inherit).lower() + ',set ' + str(can_set).lower() + ';')
    final.extend('revoke ' + qi(role) + ' from postgres granted by postgres;'
        for role in sorted(temporary - roots))
    return start.encode(), ''.join(final).encode()


def verify(db, capture, *, pending_managed_policies=False):
    value = profile(capture)
    if value is None:
        return
    from talli_backend.adapters.hosted_recovery_access import ACCESS_SQL, row_commitments
    from talli_backend.adapters.hosted_recovery_sql import CATALOG_SQL
    extended = value['profile'] == PROFILE
    require(not pending_managed_policies or extended, 'hosted_provider_profile_required')
    schemas = STRUCTURE_SCHEMAS if extended else SCHEMAS
    db.execute("set local search_path=''")
    require(db.execute(SQL, parameters(value['profile'])).fetchone()[0] == value['structure'],
        'hosted_provider_structure_changed')
    if extended:
        actual = db.execute(ACCESS_SQL, (sorted(MANAGED_ACCESS_SCHEMAS),
            sorted(MANAGED_ACCESS_SCHEMAS))).fetchone()[0]
        require(normalized_access(value['managedAccess']) == normalized_access(actual),
            'hosted_provider_managed_access_changed')
    for schema, name, counter, called in capture.profile['providerState']['sequenceState']:
        require(db.execute('select last_value,is_called from ' + qi(schema) + '.' + qi(name)).fetchone()
            == (counter, called), 'hosted_provider_sequence_state_changed')
    # No grant or membership repair is allowed for these roles. The source's
    # platform-role privileges and grantor/option chains must already match.
    custom = {r[0] for r in capture.custom_roles}
    names = sorted(r[0] for r in capture.roles['roles'] if r[0] not in custom)
    wanted_roles = [r for r in capture.roles['roles'] if r[0] in names]
    actual_roles = db.execute('select rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,'
        'rolreplication,rolbypassrls,rolconnlimit,rolvaliduntil::text,rolconfig from pg_roles '
        'where rolname=any(%s)', (names,)).fetchall()
    require(sorted(wanted_roles, key=encoded) == sorted([list(r) for r in actual_roles], key=encoded),
        'hosted_provider_roles_changed')
    all_names = {r[0] for r in db.execute('select rolname from pg_roles').fetchall()}
    require(all_names == {r[0] for r in capture.roles['roles']}, 'hosted_provider_role_inventory_changed')
    wanted_memberships = [r for r in capture.roles['memberships'] if r[0] in names and r[1] in names]
    actual_memberships = db.execute('select r.rolname,u.rolname,g.rolname,m.admin_option,m.inherit_option,m.set_option '
        'from pg_auth_members m join pg_roles r on r.oid=m.roleid join pg_roles u on u.oid=m.member '
        'join pg_roles g on g.oid=m.grantor where r.rolname=any(%s)and u.rolname=any(%s)',
        (names, names)).fetchall()
    require(sorted(wanted_memberships, key=encoded) == sorted([list(r) for r in actual_memberships], key=encoded),
        'hosted_provider_memberships_changed')
    wanted = {k: [r for r in rows if r[0] in SCHEMAS] for k, rows in capture.access.items()}
    actual = db.execute(ACCESS_SQL, (sorted(SCHEMAS), sorted(SCHEMAS))).fetchone()[0]
    require(normalized_access(wanted) == normalized_access(actual), 'hosted_provider_access_changed')
    actual_catalog = db.execute(CATALOG_SQL).fetchone()[0]
    if extended:
        from talli_backend.adapters.hosted_recovery_owner_policy import policy_status
        policy_status(capture, actual_catalog, allow_missing=pending_managed_policies)
    wanted_catalog = normalized_catalog(capture.catalog, schemas)
    current_catalog = normalized_catalog(actual_catalog, schemas)
    if extended:
        # The policy inventory guard above is authoritative for named missing
        # policies. All other policies and every other catalog field stay exact.
        for catalog in (wanted_catalog, current_catalog):
            catalog['policies'] = [r for r in catalog['policies']
                if r[0] not in MANAGED_ACCESS_SCHEMAS]
    require(wanted_catalog == current_catalog, 'hosted_provider_catalog_changed')
    require(row_commitments(db, [t.split('.') for t in sorted(TABLES)]) ==
        {t: capture.rows[t] for t in TABLES}, 'hosted_provider_state_changed')


def _managed_policy_grants(db):
    # Supautils registers this SIGHUP-only GUC when its policy hook is loaded.
    # A user-set custom placeholder is not a registered pg_settings entry. Read
    # existing provider authority only; never set a GUC or grant a membership.
    row = db.execute("select current_user,setting,context,pending_restart from pg_settings "
        "where name='supautils.policy_grants' and vartype='string'").fetchone()
    if row is None:
        return frozenset()
    role, raw, context, pending = row
    code = 'hosted_managed_policy_grants_invalid'
    require(context == 'sighup' and pending is False and isinstance(raw, str) and
        len(raw.encode()) <= 65536, code)
    try:
        values = json_bytes(raw.encode())
    except ValueError:
        raise ValueError(code) from None
    require(isinstance(values, dict) and len(values) <= 512, code)
    for name, tables in values.items():
        require(isinstance(name, str) and re.fullmatch('[a-z_][a-z_0-9]{0,62}', name) and
            isinstance(tables, list) and len(tables) <= 512 and
            all(isinstance(t, str) and re.fullmatch(
                '[a-z_][a-z_0-9]{0,62}\\.[a-z_][a-z_0-9]{0,62}', t) for t in tables), code)
    return frozenset(values.get(role, ()))


def require_policy_authority(db, capture, *, managed_policy_grants=False):
    """Fail before app DDL when postgres cannot install an original policy."""
    owners = {(r[0], r[1]): r[4] for r in capture.catalog['rls']}
    grants = None
    for schema, table, *_ in capture.catalog['policies']:
        if schema not in ('auth', 'storage'):
            continue
        owner = owners.get((schema, table))
        require(owner is not None, 'hosted_managed_policy_owner_unavailable')
        authority = db.execute(
            "select rolsuper or pg_has_role(current_user,%s,'USAGE')from pg_roles where rolname=current_user",
            (owner,)).fetchone()[0]
        if not authority and managed_policy_grants:
            if grants is None:
                grants = _managed_policy_grants(db)
            authority = schema + '.' + table in grants
        require(authority, 'hosted_managed_policy_owner_unavailable')
