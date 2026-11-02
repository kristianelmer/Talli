"""One explicit managed initialization contract; never edits provider definitions.

This accepts a different provider extension owner and Storage initialization, not
original provider identity or equivalent versioning semantics. Talli's private,
unversioned object dependency must hold at every recovery checkpoint.
"""
import json
import re

from talli_backend.adapters.hosted_recovery_capture import digest, encoded, normalized_catalog, require
from talli_backend.adapters.hosted_recovery_sql import CATALOG_SQL, managed_trigger_definitions

PROFILE = 'supabase-managed-17.11-storage-versioning-v1'
SCHEMAS = {'auth', 'storage', 'extensions'}
SOURCE_EXTENSIONS = [
    ['pg_stat_statements', '1.11', 'supabase_admin', 'extensions'],
    ['pgcrypto', '1.3', 'supabase_admin', 'extensions'],
    ['plpgsql', '1.0', 'supabase_admin', 'pg_catalog'],
    ['supabase_vault', '0.3.1', 'supabase_admin', 'vault'],
    ['uuid-ossp', '1.1', 'supabase_admin', 'extensions'],
]
TARGET_EXTENSIONS = [[name, version, 'postgres' if name in
    {'pg_stat_statements', 'pgcrypto', 'uuid-ossp'} else owner, schema]
    for name, version, owner, schema in SOURCE_EXTENSIONS]
DARK_CONSTRAINT = ['storage',
 'buckets',
 'buckets_versioning_dark_check',
 "CHECK (versioning_status = 'DISABLED'::text)"]
TRANSITION_FUNCTION = ['storage',
 'enforce_versioning_status_transition',
 '',
 'CREATE OR REPLACE FUNCTION storage.enforce_versioning_status_transition()\n'
 ' RETURNS trigger\n'
 ' LANGUAGE plpgsql\n'
 'AS $function$\n'
 'BEGIN\n'
 '    IF NEW.versioning_status = OLD.versioning_status THEN\n'
 '        RETURN NEW;\n'
 '    END IF;\n'
 '\n'
 "    IF NEW.versioning_status = 'DISABLED' OR\n"
 "       (OLD.versioning_status = 'DISABLED' AND NEW.versioning_status = 'SUSPENDED') THEN\n"
 "        RAISE EXCEPTION 'Cannot transition bucket versioning status from % to %',\n"
 '            OLD.versioning_status, NEW.versioning_status;\n'
 '    END IF;\n'
 '\n'
 '    RETURN NEW;\n'
 'END;\n'
 '$function$\n',
 'supabase_storage_admin',
 [['supabase_storage_admin', 'PUBLIC', 'EXECUTE', False],
  ['supabase_storage_admin', 'supabase_storage_admin', 'EXECUTE', False]]]
TRANSITION_TRIGGER = ('CREATE TRIGGER enforce_versioning_status_transition BEFORE UPDATE OF versioning_status ON '
 'storage.buckets FOR EACH ROW EXECUTE FUNCTION storage.enforce_versioning_status_transition()')

BUCKET_COLUMN = ['text', True, "'DISABLED'::text"]
CONTRACT_SHA = digest(encoded([PROFILE, SOURCE_EXTENSIONS, TARGET_EXTENSIONS,
    DARK_CONSTRAINT, TRANSITION_FUNCTION, TRANSITION_TRIGGER, BUCKET_COLUMN,
    {'copyMode': 'origin-foreign-key-ordered', 'foreignKeyTriggers': 'four-internal-origin-nonpartitioned',
     'bucketPolicy': 'all-private-DISABLED'}]))


def expected_catalog(catalog, schemas, *, fresh=False, custom_roles=()):
    """Comparison view only. The capture and executed provider SQL never change."""
    expected = normalized_catalog(catalog, schemas)
    if 'storage' in schemas:
        require(expected['constraints'].count(DARK_CONSTRAINT) == 1 and
            not any(row[:3] == TRANSITION_FUNCTION[:3] for row in expected['functions']),
            'hosted_managed_initialization_source_changed')
        expected['constraints'].remove(DARK_CONSTRAINT)
        expected['functions'].append(json.loads(json.dumps(TRANSITION_FUNCTION)))
    if fresh:
        expected['policies'] = [row for row in expected['policies']
            if row[0] not in ('auth', 'storage')]
        for row in expected['functions']:
            if row[0] == 'extensions':
                row[5] = [grant for grant in row[5] if grant[1] not in custom_roles]
    return normalized_catalog(expected, schemas)


class ManagedInitialization:
    """Bound expectation, usable for read-only inspection after capture loss."""
    def __init__(self, binding):
        require(isinstance(binding, dict) and set(binding) == {'profile', 'contractSha256',
            'preflightCatalogSha256', 'restoredCatalogSha256', 'triggersSha256'} and
            binding['profile'] == PROFILE and binding['contractSha256'] == CONTRACT_SHA and
            all(isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value)
                for key, value in binding.items() if key != 'profile'),
            'hosted_managed_initialization_binding_invalid')
        self.binding = dict(binding)

    @classmethod
    def from_capture(cls, capture, archive, requested):
        require(requested == PROFILE and re.fullmatch('[a-z]{20}', capture.source_project) and
            capture.profile.get('providerState') is None and capture.profile['facts'][0] == 170011 and
            capture.profile['extensions'] == SOURCE_EXTENSIONS,
            'hosted_managed_initialization_source_unsupported')
        entries = [e for e in archive.entries if e.kind == 'TABLE' and
            e.schema == 'storage' and e.tag == 'buckets']
        require(len(entries) == 1 and
            b"    versioning_status text DEFAULT 'DISABLED'::text NOT NULL," in archive.sql(entries),
            'hosted_managed_initialization_bucket_source_unsupported')
        triggers = managed_trigger_definitions(archive)
        require(TRANSITION_TRIGGER not in triggers, 'hosted_managed_initialization_source_changed')
        custom = {row[0] for row in capture.custom_roles}
        fresh = expected_catalog(capture.catalog, SCHEMAS, fresh=True, custom_roles=custom)
        restored = expected_catalog(capture.catalog, SCHEMAS)
        return cls({'profile': PROFILE, 'contractSha256': CONTRACT_SHA,
            'preflightCatalogSha256': digest(encoded(fresh)),
            'restoredCatalogSha256': digest(encoded(restored)),
            'triggersSha256': digest(encoded(sorted([(t, 'O') for t in triggers] +
                [(TRANSITION_TRIGGER, 'O')])) )})

    def verify(self, db, *, fresh=False):
        """Revalidate owners, bodies, grantors, constraints, triggers and bucket state."""
        db.execute("set local search_path=''")
        require(db.execute("select current_setting('server_version_num')::integer").fetchone()[0] == 170011,
            'hosted_managed_initialization_engine_changed')
        extensions = [list(row) for row in db.execute('select e.extname,e.extversion,'
            'pg_get_userbyid(e.extowner),n.nspname from pg_extension e join pg_namespace n '
            'on n.oid=e.extnamespace order by e.extname').fetchall()]
        require(extensions == TARGET_EXTENSIONS, 'hosted_extension_profile_changed')
        actual = normalized_catalog(db.execute(CATALOG_SQL).fetchone()[0], SCHEMAS)
        key = 'preflightCatalogSha256' if fresh else 'restoredCatalogSha256'
        require(digest(encoded(actual)) == self.binding[key],
            'hosted_managed_initialization_catalog_changed')
        triggers = db.execute('select pg_get_triggerdef(t.oid),t.tgenabled from pg_trigger t '
            'join pg_class c on c.oid=t.tgrelid join pg_namespace n on n.oid=c.relnamespace '
            "where n.nspname in('auth','storage') and not t.tgisinternal").fetchall()
        require(digest(encoded(sorted(triggers))) == self.binding['triggersSha256'],
            'hosted_managed_trigger_profile_changed')
        # Constraint definitions do not expose disabled internal enforcement
        # triggers. This profile supports ordinary nonpartitioned managed FKs:
        # two referencing checks and two referenced actions, all live in origin.
        require(db.execute("select count(*) from pg_constraint k join pg_class c on c.oid=k.conrelid "
            "join pg_namespace n on n.oid=c.relnamespace where k.contype='f' "
            "and n.nspname in('auth','storage','extensions') and ("
            "k.conparentid<>0 or c.relkind<>'r' or "
            "(select relkind from pg_class where oid=k.confrelid)<>'r' or "
            "(select count(*) from pg_trigger t where t.tgconstraint=k.oid)<>4 or "
            "(select count(*) from pg_trigger t where t.tgconstraint=k.oid and t.tgisinternal "
            "and t.tgenabled in('O','A') and t.tgrelid in(k.conrelid,k.confrelid))<>4)").fetchone()[0] == 0,
            'hosted_managed_foreign_key_enforcement_changed')
        column = db.execute("select format_type(a.atttypid,a.atttypmod),a.attnotnull,"
            "pg_get_expr(d.adbin,d.adrelid) from pg_attribute a left join pg_attrdef d "
            "on d.adrelid=a.attrelid and d.adnum=a.attnum where a.attrelid='storage.buckets'::regclass "
            "and a.attname='versioning_status' and not a.attisdropped").fetchone()
        require(column is not None and list(column) == BUCKET_COLUMN,
            'hosted_managed_initialization_bucket_column_changed')
        require(db.execute("select count(*) from storage.buckets where public is distinct from false "
            "or versioning_status is distinct from 'DISABLED'").fetchone()[0] == 0,
            'hosted_managed_initialization_bucket_mode_changed')
