"""Independent, disposable local Postgres roles + Auth recovery for RF evidence.

Never targets a hosted project. Source reads require the aggregate runner's exact
workdir/container/session boundary. Every write targets this invocation's fresh,
nonce-labelled private network, volume and pinned-image containers. Operational
Auth signing configuration is copied explicitly; this is not hosted key recovery.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import base64
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from threading import Thread
import time
import tomllib
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

import httpx
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from rf1086_local_forwarding import forwarded_ports

LABEL = 'talli.rf.identity.restore'
ID = re.compile(r'[a-f0-9]{64}')
IMAGE = re.compile(r'sha256:[a-f0-9]{64}')
# Start the source image's PostgreSQL binaries directly: no Supabase bootstrap,
# migrations, source mounts, source network or existing roles reach this cluster.
INIT = """set -eu
mkdir -p /tmp/rf-recovery/data
initdb -D /tmp/rf-recovery/data --username="$RECOVERY_BOOTSTRAP" --auth-local=trust --auth-host=scram-sha-256 >/dev/null
exec postgres -D /tmp/rf-recovery/data -c listen_addresses='*' -c unix_socket_directories=/tmp -c shared_preload_libraries="$RECOVERY_PRELOAD" -c cron.launch_active_jobs=off
"""


def checked(args, **kwargs):
    """Never render command stderr: dumps, Auth env and SQL may contain secrets."""
    try:
        result = subprocess.run(args, stderr=subprocess.PIPE, timeout=90, **kwargs)
    except subprocess.TimeoutExpired:
        raise RuntimeError('Owned identity recovery command timed out: ' + args[1]) from None
    if result.returncode:
        raise RuntimeError('Owned identity recovery command failed: ' + args[1])
    return result


def inspect_resource(kind, reference):
    for attempt in range(3):
        try:
            return json.loads(checked(['docker', kind, 'inspect', reference], stdout=subprocess.PIPE).stdout)[0]
        except (RuntimeError, ValueError, IndexError):
            if attempt == 2: raise RuntimeError('Recovery ' + kind + ' ownership could not be inspected; cleanup may be required') from None
            time.sleep(0.1)


def query(container, statement, *, user='supabase_admin', database='postgres'):
    return checked(['docker', 'exec', '-i', container, 'psql', '-U', user, '-h', '/tmp',
                    '--dbname', database, '-XAt', '-v', 'ON_ERROR_STOP=1'],
                   input=statement.encode(), stdout=subprocess.PIPE).stdout


def source_query(container, statement):
    return checked(['docker', 'exec', '-i', container, 'psql', '-U', 'supabase_admin',
                    '--dbname', 'postgres', '-XAt', '-v', 'ON_ERROR_STOP=1'],
                   input=statement.encode(), stdout=subprocess.PIPE).stdout


# Compare names, attributes and grants, never database-local catalog OIDs.
ROLE_SQL = """
select coalesce(jsonb_agg(to_jsonb(r)-'oid' order by r.rolname),'[]'::jsonb)
from pg_authid r;
select coalesce(jsonb_agg(jsonb_build_array(r.rolname,m.rolname,g.rolname,a.admin_option,a.inherit_option,a.set_option)
order by r.rolname,m.rolname,g.rolname),'[]'::jsonb)
from pg_auth_members a join pg_roles r on r.oid=a.roleid join pg_roles m on m.oid=a.member
join pg_roles g on g.oid=a.grantor;
"""
CATALOG_SQL = """
select jsonb_agg(item order by item::text) from (
 select jsonb_build_array('schema',n.nspname,pg_get_userbyid(n.nspowner),n.nspacl::text) item
 from pg_namespace n where n.nspname !~ '^pg_' and n.nspname <> 'information_schema'
 union all
 select jsonb_build_array('relation',n.nspname,c.relname,c.relkind,pg_get_userbyid(c.relowner),
 c.relacl::text,c.relrowsecurity,c.relforcerowsecurity) from pg_class c
 join pg_namespace n on n.oid=c.relnamespace where n.nspname !~ '^pg_' and n.nspname <> 'information_schema'
 union all
 select jsonb_build_array('function',n.nspname,p.proname,pg_get_function_identity_arguments(p.oid),
 pg_get_userbyid(p.proowner),p.proacl::text,p.prosecdef,p.proconfig::text) from pg_proc p
 join pg_namespace n on n.oid=p.pronamespace where n.nspname !~ '^pg_' and n.nspname <> 'information_schema'
 union all
 select jsonb_build_array('default_acl',pg_get_userbyid(a.defaclrole),n.nspname,a.defaclobjtype,a.defaclacl::text)
 from pg_default_acl a left join pg_namespace n on n.oid=a.defaclnamespace
 union all
 select jsonb_build_array('column_acl',n.nspname,c.relname,a.attname,a.attacl::text)
 from pg_attribute a join pg_class c on c.oid=a.attrelid join pg_namespace n on n.oid=c.relnamespace
 where a.attacl is not null and n.nspname !~ '^pg_' and n.nspname <> 'information_schema'
 union all
 select jsonb_build_array('policy',n.nspname,c.relname,p.polname,p.polcmd,p.polpermissive,
 (select jsonb_agg(case when r=0 then 'PUBLIC' else pg_get_userbyid(r) end order by r::regrole::text) from unnest(p.polroles) r),
 pg_get_expr(p.polqual,p.polrelid),pg_get_expr(p.polwithcheck,p.polrelid))
 from pg_policy p join pg_class c on c.oid=p.polrelid join pg_namespace n on n.oid=c.relnamespace
) owned;
select (to_jsonb(d)-'oid'-'datfrozenxid'-'datminmxid'-'dattablespace'-'datdba') ||
 jsonb_build_object('owner',pg_get_userbyid(d.datdba),'tablespace',t.spcname)
 from pg_database d join pg_tablespace t on t.oid=d.dattablespace where d.datname=current_database();
select coalesce(jsonb_agg(jsonb_build_array(case when s.setdatabase=0 then '*' else d.datname end,
 case when s.setrole=0 then '*' else pg_get_userbyid(s.setrole) end,s.setconfig)
 order by d.datname nulls first,s.setrole::regrole::text),'[]'::jsonb)
 from pg_db_role_setting s left join pg_database d on d.oid=s.setdatabase
 where s.setdatabase=0 or d.datname=current_database();
"""


def fingerprint(container, *, restored=False, bootstrap=None):
    run = (lambda statement: query(container, statement, user=bootstrap)) if restored else lambda statement: source_query(container, statement)
    roles = run(ROLE_SQL)
    catalog = run(CATALOG_SQL)
    # Auth rows are copied exactly (including users, sessions, factors, identities
    # and token state). Hash in memory; neither rows nor password hashes escape.
    tables = json.loads(run("select coalesce(json_agg(tablename order by tablename),'[]'::json) from pg_tables where schemaname='auth';"))
    auth = hashlib.sha256()
    for table in tables:
        statement = sql.SQL("select coalesce(jsonb_agg(to_jsonb(t) order by to_jsonb(t)::text),'[]'::jsonb) from auth.{} t;").format(sql.Identifier(table)).as_string()
        auth.update(table.encode())
        auth.update(run(statement))
    memberships = run("select coalesce(jsonb_agg(to_jsonb(m) order by company_id,user_id),'[]'::jsonb) from public.company_memberships m;")
    return {'roles': hashlib.sha256(roles).hexdigest(), 'catalog': hashlib.sha256(catalog).hexdigest(),
            'auth': auth.hexdigest(), 'companyMemberships': hashlib.sha256(memberships).hexdigest()}


def owned_identity_source(workdir, source_url, boundary):
    db_id, database = boundary.owned_source(workdir, source_url, boundary.inspect_container)
    boundary.verify_source_session(source_url, db_id)
    config = tomllib.loads((Path(workdir) / 'supabase/config.toml').read_text())
    project = config['project_id']
    db = boundary.inspect_container(db_id)
    auth = boundary.inspect_container('supabase_auth_' + project)
    network = 'supabase_network_' + project
    env = dict(item.split('=', 1) for item in auth.get('Config', {}).get('Env', []))
    connection = urlsplit(env.get('GOTRUE_DB_DATABASE_URL', ''))
    endpoint = urlsplit(os.environ.get('SUPABASE_URL', ''))
    gateway = boundary.inspect_container('supabase_kong_' + project)
    ports = gateway.get('NetworkSettings', {}).get('Ports', {}).get('8000/tcp', []) or []
    if (db.get('Id') != db_id or not IMAGE.fullmatch(db.get('Image', ''))
            or auth.get('Name') != '/supabase_auth_' + project or not ID.fullmatch(auth.get('Id', ''))
            or not auth.get('State', {}).get('Running') or not IMAGE.fullmatch(auth.get('Image', ''))
            or set(auth.get('NetworkSettings', {}).get('Networks', {})) != {network}
            or network not in db.get('NetworkSettings', {}).get('Networks', {})
            or connection.scheme not in ('postgres', 'postgresql') or connection.hostname != 'supabase_db_' + project
            or connection.port != 5432 or connection.path != '/' + database or connection.query or connection.fragment
            or connection.username != 'supabase_auth_admin'
            or endpoint.scheme != 'http' or endpoint.hostname not in ('127.0.0.1', 'localhost', '::1')
            or endpoint.port != config['api']['port'] or endpoint.path not in ('', '/')
            or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment
            or gateway.get('Name') != '/supabase_kong_' + project or not gateway.get('State', {}).get('Running')
            or set(gateway.get('NetworkSettings', {}).get('Networks', {})) != {network}
            or not any(p.get('HostPort') == str(endpoint.port) and p.get('HostIp') in ('127.0.0.1', '0.0.0.0', '::', '::1') for p in ports)):
        raise ValueError('Identity recovery requires the exact owned local database and Auth service')
    return db, auth, env


def auth_environment(source, host):
    if not re.fullmatch(r'rf193_identity_db_[a-f0-9]{32}', host):
        raise ValueError('Auth recovery requires this invocation\'s fresh database')
    allowed = {'GOTRUE_JWT_SECRET', 'GOTRUE_JWT_KEYS', 'GOTRUE_JWT_AUD', 'GOTRUE_JWT_ADMIN_ROLES',
               'GOTRUE_JWT_DEFAULT_GROUP_NAME', 'GOTRUE_JWT_EXP', 'GOTRUE_DB_NAMESPACE',
               'GOTRUE_SECURITY_REFRESH_TOKEN_ROTATION_ENABLED', 'GOTRUE_SECURITY_REFRESH_TOKEN_REUSE_INTERVAL',
               'GOTRUE_MFA_TOTP_ENROLL_ENABLED', 'GOTRUE_MFA_TOTP_VERIFY_ENABLED'}
    result = {key: value for key, value in source.items() if key in allowed}
    original = urlsplit(source['GOTRUE_DB_DATABASE_URL'])
    result.update(GOTRUE_DB_DATABASE_URL=urlunsplit(original._replace(netloc=original.netloc.rsplit('@', 1)[0] + '@' + host + ':5432')),
        GOTRUE_DB_DRIVER='postgres', GOTRUE_API_HOST='0.0.0.0', GOTRUE_API_PORT='9999',
        API_EXTERNAL_URL='http://127.0.0.1:9999', GOTRUE_SITE_URL='http://127.0.0.1:9999',
        GOTRUE_DISABLE_SIGNUP='true', GOTRUE_EXTERNAL_EMAIL_ENABLED='false',
        GOTRUE_EXTERNAL_PHONE_ENABLED='false', GOTRUE_LOG_LEVEL='fatal')
    if not result.get('GOTRUE_JWT_SECRET') and not result.get('GOTRUE_JWT_KEYS'):
        raise ValueError('Captured local Auth signing configuration is missing')
    if any('\n' in value or '\r' in value for value in result.values()):
        raise ValueError('Auth environment cannot contain line breaks')
    return result


@contextmanager
def auth_gateway(port):
    """Prefix bridge only; the independent Auth process verifies every session."""
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self): self.forward()
        def do_POST(self): self.forward()
        def do_DELETE(self): self.forward()
        def forward(self):
            length = int(self.headers.get('Content-Length', '0'))
            if not self.path.startswith('/auth/v1/') or not 0 <= length <= 4096:
                self.send_error(404)
                return
            upstream = HTTPConnection('127.0.0.1', port, timeout=10)
            try:
                headers = {key: value for key, value in self.headers.items() if key.lower() in ('authorization', 'apikey', 'content-type')}
                upstream.request(self.command, self.path[len('/auth/v1'):], self.rfile.read(length) if length else None, headers)
                response = upstream.getresponse()
                body = response.read(65537)
                if len(body) > 65536: raise ValueError('Auth response exceeds fixture bound')
                self.send_response(response.status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception:
                self.send_error(502, 'Owned Auth unavailable')
            finally:
                upstream.close()
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try: yield 'http://127.0.0.1:' + str(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def published_port(service, target_port):
    value = os.environ.get('TALLI_RF_IDENTITY_' + service + '_PORT', '')
    if value and (not value.isdecimal() or not 1024 <= int(value) <= 65535):
        raise ValueError('Invalid explicitly reserved identity recovery port')
    return '127.0.0.1:' + value + ':' + str(target_port)


def loopback_port(container, port, boundary):
    inspected = boundary.inspect_container(container)
    bindings = inspected.get('NetworkSettings', {}).get('Ports', {}).get(str(port) + '/tcp', []) or []
    if len(bindings) != 1 or bindings[0].get('HostIp') != '127.0.0.1':
        raise ValueError('Independent recovery service must bind only loopback')
    return int(bindings[0]['HostPort'])


def verify_target_session(database_url, container, bootstrap):
    """Observe the exact host connection inside the new pinned target before writes."""
    marker = 'rf193_identity_session_' + uuid4().hex
    with psycopg.connect(database_url, application_name=marker) as connection:
        pid = connection.execute('select pg_backend_pid()').fetchone()[0]
        statement = ("select count(*) from pg_stat_activity where datname='postgres' "
                     f"and usename='postgres' and pid={int(pid)} and application_name='{marker}';")
        if query(container, statement, user=bootstrap).strip() != b'1':
            raise ValueError('Recovered DATABASE_URL is not served by the newly created target')


def verify_target_auth(database_url, auth_url):
    """A target-only nonce proves HTTP Auth uses this independent database."""
    token = os.environ.get('TALLI_RF_RESTORE_OWNER_TOKEN', '')
    try:
        payload = token.split('.')[1]
        actor = str(UUID(json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))['sub']))
    except (IndexError, KeyError, ValueError, TypeError):
        raise ValueError('Independent Auth binding requires the captured owner token') from None
    key, nonce = 'rf193_identity_recovery_probe', uuid4().hex
    with psycopg.connect(database_url) as connection:
        original = connection.execute('select raw_app_meta_data from auth.users where id=%s', (actor,)).fetchone()
        if original is None: raise ValueError('Captured owner is missing from the recovery database')
        metadata = original[0]
        connection.execute('update auth.users set raw_app_meta_data=%s::jsonb where id=%s',
            (json.dumps({**(metadata or {}), key: nonce}), actor))
    try:
        with httpx.Client(trust_env=False, timeout=10) as client:
            response = client.get(auth_url + '/auth/v1/user', headers={'Authorization': 'Bearer ' + token})
            if response.status_code != 200:
                raise ValueError('Independent Auth binding rejected the captured owner session')
            body = response.json()
            if body.get('id') != actor or body.get('app_metadata', {}).get(key) != nonce:
                raise ValueError('Recovered Auth HTTP endpoint does not use the new target database')
    finally:
        with psycopg.connect(database_url) as connection:
            connection.execute('update auth.users set raw_app_meta_data=%s::jsonb where id=%s',
                (None if metadata is None else json.dumps(metadata), actor))


@dataclass(frozen=True)
class RecoveredIdentity:
    database_url: str
    auth_url: str
    admin_key: str
    database_container: str
    bootstrap: str
    proof: dict

    def reader_url(self, source_reader):
        source = conninfo_to_dict(source_reader)
        recovered = conninfo_to_dict(self.database_url)
        return make_conninfo(source_reader, host=recovered['host'], port=recovered['port'], dbname=recovered['dbname'])


@contextmanager
def restored_identity(source_url, workdir, boundary):
    db, auth, source_env = owned_identity_source(workdir, source_url, boundary)
    nonce = uuid4().hex
    network, volume = 'rf193_identity_net_' + nonce, 'rf193_identity_data_' + nonce
    db_name, auth_name = 'rf193_identity_db_' + nonce, 'rf193_identity_auth_' + nonce
    bootstrap = 'supabase_admin'
    created_network, created_volume, containers = False, False, []
    before = fingerprint(db['Id'])
    preload = source_query(db['Id'], 'show shared_preload_libraries;').decode().strip()
    if not re.fullmatch(r'[A-Za-z0-9_, .-]*', preload): raise ValueError('Invalid local preload configuration')
    with tempfile.TemporaryFile() as roles, tempfile.TemporaryFile() as dump, tempfile.TemporaryDirectory(prefix='talli-rf-identity-') as directory:
        checked(['docker', 'exec', db['Id'], 'pg_dumpall', '-U', 'supabase_admin', '--roles-only'], stdout=roles)
        checked(['docker', 'exec', db['Id'], 'pg_dump', '-U', 'supabase_admin', '--format=custom', '--dbname', 'postgres'], stdout=dump)
        try:
            result = checked(['docker', 'network', 'create', '--internal', '--label', LABEL + '=' + nonce, network], stdout=subprocess.PIPE)
            network_id = result.stdout.decode().strip()
            inspect = inspect_resource('network', network_id)
            if not ID.fullmatch(network_id) or inspect.get('Name') != network or inspect.get('Labels', {}).get(LABEL) != nonce or not inspect.get('Internal'):
                raise ValueError('Recovery network ownership mismatch')
            created_network = True
            checked(['docker', 'volume', 'create', '--label', LABEL + '=' + nonce, volume], stdout=subprocess.PIPE)
            inspect = inspect_resource('volume', volume)
            if inspect.get('Name') != volume or inspect.get('Labels', {}).get(LABEL) != nonce:
                raise ValueError('Recovery volume ownership mismatch')
            created_volume = True
            # Initialize only the new volume's directory ownership; never mount a source volume.
            checked(['docker', 'run', '--rm', '--pull=never', '--network', 'none', '--user', '0',
                     '--entrypoint', 'sh', '-v', volume + ':/tmp/rf-recovery', db['Image'], '-c',
                     'chown postgres:postgres /tmp/rf-recovery'], stdout=subprocess.PIPE)
            result = checked(['docker', 'create', '--pull=never', '--name', db_name, '--label', LABEL + '=' + nonce,
                '--network', network, '--user', 'postgres', '--entrypoint', 'sh',
                '-e', 'RECOVERY_BOOTSTRAP=' + bootstrap, '-e', 'RECOVERY_PRELOAD=' + preload,
                '-v', volume + ':/tmp/rf-recovery', '-p', published_port('DB', 5432), db['Image'], '-c', INIT], stdout=subprocess.PIPE)
            target = result.stdout.decode().strip()
            if not ID.fullmatch(target): raise ValueError('Recovery database identity missing')
            containers.append(target)
            checked(['docker', 'start', target], stdout=subprocess.PIPE)
            for _ in range(90):
                result = subprocess.run(['docker', 'exec', target, 'pg_isready', '-h', '/tmp', '-U', bootstrap], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if result.returncode == 0: break
                time.sleep(0.25)
            else: raise RuntimeError('Independent recovery database did not become ready')
            roles.seek(0)
            role_sql = roles.read()
            initialized_role = b'CREATE ROLE supabase_admin;\n'
            if role_sql.count(initialized_role) != 1:
                raise ValueError('Source role dump lacks the exact initialized administrator')
            role_sql = role_sql.replace(initialized_role, b'', 1)
            checked(['docker', 'exec', '-i', target, 'psql', '-U', bootstrap, '-h', '/tmp', '-d', 'postgres', '-Xq', '-v', 'ON_ERROR_STOP=1'], input=role_sql, stdout=subprocess.PIPE)
            # Connect to the new cluster's template1 while pg_restore recreates
            # only its empty postgres database, including owner/ACL/database GUCs.
            dump.seek(0)
            checked(['docker', 'exec', '-i', target, 'pg_restore', '-U', bootstrap, '-h', '/tmp',
                     '--exit-on-error', '--clean', '--if-exists', '--create', '--dbname', 'template1'], stdin=dump, stdout=subprocess.PIPE)
            if fingerprint(target, restored=True, bootstrap=bootstrap) != before:
                raise ValueError('Independent recovery roles, ownership, ACLs or Auth rows differ')
            env = auth_environment(source_env, db_name)
            configuration = Path(directory) / 'auth.env'
            configuration.touch(mode=0o600)
            configuration.write_text(''.join(key + '=' + value + '\n' for key, value in env.items()))
            result = checked(['docker', 'create', '--pull=never', '--name', auth_name, '--label', LABEL + '=' + nonce,
                '--network', network, '--env-file', str(configuration), '-p', published_port('AUTH', 9999), auth['Image']], stdout=subprocess.PIPE)
            target_auth = result.stdout.decode().strip()
            if not ID.fullmatch(target_auth): raise ValueError('Recovery Auth identity missing')
            containers.append(target_auth)
            checked(['docker', 'start', target_auth], stdout=subprocess.PIPE)
            port = loopback_port(target_auth, 9999, boundary)
            db_port = loopback_port(target, 5432, boundary)
            with forwarded_ports((db_port, port)):
                with httpx.Client(trust_env=False, timeout=1) as client:
                    for _ in range(90):
                        try:
                            if client.get(f'http://127.0.0.1:{port}/health').status_code == 200: break
                        except httpx.HTTPError: pass
                        time.sleep(0.25)
                    else: raise RuntimeError('Independent recovery Auth did not become ready')
                database_url = make_conninfo(source_url, host='127.0.0.1', port=db_port)
                verify_target_session(database_url, target, bootstrap)
                # Prove a new system identifier, not merely a renamed database in the source cluster.
                source_system = source_query(db['Id'], 'select system_identifier from pg_control_system();')
                recovered_system = query(target, 'select system_identifier from pg_control_system();', user=bootstrap)
                if source_system == recovered_system: raise ValueError('Recovery reused source Postgres cluster')
                # The admin JWT is the local Storage/Auth service credential, not the
                # opaque gateway key. Read from the captured source Storage config.
                storage = boundary.inspect_container('supabase_storage_' + tomllib.loads((Path(workdir) / 'supabase/config.toml').read_text())['project_id'])
                storage_env = dict(item.split('=', 1) for item in storage['Config']['Env'])
                admin_key = storage_env.get('SERVICE_KEY', '')
                if not admin_key: raise ValueError('Owned local Auth admin JWT is missing')
                with auth_gateway(port) as gateway:
                    verify_target_auth(database_url, gateway)
                    yield RecoveredIdentity(database_url, gateway, admin_key, target, bootstrap,
                        {'independentClusterRestored': True, 'independentAuthRestored': True,
                         'roleAttributesAndMembershipsRestored': True, 'ownershipGrantsAndRlsRestored': True,
                         'authRowsRestoredExactly': True, 'authHttpTargetBindingVerified': True, 'authSigningConfigSource': 'captured-local-service-config',
                         'hostedKeyRecoveryVerified': False})
        finally:
            try:
                cleanup_failure = None
                for container in reversed(containers):
                    try: checked(['docker', 'rm', '-f', container], stdout=subprocess.PIPE)
                    except RuntimeError as error: cleanup_failure = error
                if cleanup_failure: raise cleanup_failure
            finally:
                try:
                    if created_volume: checked(['docker', 'volume', 'rm', volume], stdout=subprocess.PIPE)
                finally:
                    if created_network: checked(['docker', 'network', 'rm', network_id], stdout=subprocess.PIPE)
                    if fingerprint(db['Id']) != before:
                        raise RuntimeError('Identity rehearsal changed source roles, ownership, ACLs, Auth rows or memberships')


async def verify_actor_recovery(recovery, reader_url, query, expected_canonical, originals, original_queries, read_originals, *,
                                stream_codec="rf1086-production-stream-v1"):
    """Target-only lifecycle fixture; it never rewrites captured historical actors."""
    from talli_backend.adapters.postgres_shareholder_register_filing import PostgresShareholderRegisterFilingSession
    from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration, SupabaseLedgerAdapter
    from talli_backend.application.ledger_workflow import LedgerAuthenticationError
    from talli_backend.application.shareholder_register_archive import serialize_download_archive
    from talli_backend.modules.shareholder_register_filing import public as rf
    configuration = LedgerSupabaseConfiguration(recovery.auth_url, os.environ['SUPABASE_ANON_KEY'], reader_url)
    authentication = SupabaseLedgerAdapter(configuration)
    owner_token = os.environ['TALLI_RF_RESTORE_OWNER_TOKEN']
    other_token = os.environ['TALLI_RF_RESTORE_OUTSIDER_TOKEN']
    owner = await authentication._verified_actor(owner_token)
    other = await authentication._verified_actor(other_token)
    if owner.actor_id != query.actor_id or owner.actor_id == other.actor_id:
        raise ValueError('Recovered sessions do not identify distinct expected actors')

    async def archive(token):
        verified = await authentication._verified_actor(token)
        current = rf.Rf1086ArchiveQuery(query.company_id, query.income_year, verified.actor_id)
        session = PostgresShareholderRegisterFilingSession(configuration, verified, access_token=token,
            billing=None, documents=None, company_access=None)
        value = await session.archive_source(current)
        return serialize_download_archive(value, query=current, stream_codec=stream_codec)

    async def denied(token):
        try: await archive(token)
        except rf.ShareholderRegisterFilingError as error:
            if error.code != rf.ShareholderRegisterFilingErrorCode.NOT_FOUND: raise
        else: raise ValueError('Recovered archive admitted a revoked or unrelated actor')

    async def auth_denied(token):
        try: await archive(token)
        except LedgerAuthenticationError: pass
        else: raise ValueError('Independent Auth accepted a revoked or soft-deleted session')

    if await archive(owner_token) != expected_canonical:
        raise ValueError('Independent authenticated recovery changed RF history')
    await denied(other_token)
    async def originals_denied(actor):
        if original_queries:
            try: await read_originals(reader_url, actor, original_queries[:1])
            except psycopg.Error as error:
                if error.diag.message_primary != 'documents_forbidden': raise
            else: raise ValueError('Independent Documents admitted an unrelated or revoked actor')
    await originals_denied(other.actor_id)

    # Explicit synthetic fixture setup on the newly restored target only. Actual
    # production successor authorization remains a separate owner/support act.
    with psycopg.connect(recovery.database_url) as connection:
        if connection.execute('select count(*) from public.company_memberships where company_id=%s and user_id=%s',
            (str(query.company_id), str(other.actor_id.subject))).fetchone()[0] != 0:
            raise ValueError('Recovery actor already has a company membership')
        connection.execute("insert into public.company_memberships(company_id,user_id,role,accepted_at) values(%s,%s,'owner',now())",
            (str(query.company_id), str(other.actor_id.subject)))
        removed = connection.execute('delete from public.company_memberships where company_id=%s and user_id=%s returning user_id',
            (str(query.company_id), str(owner.actor_id.subject))).fetchall()
        if len(removed) != 1: raise ValueError('Historical owner membership was not uniquely revoked')
    await denied(owner_token)
    await originals_denied(owner.actor_id)
    if await archive(other_token) != expected_canonical or await read_originals(reader_url, other.actor_id, original_queries) != originals:
        raise ValueError('Independent successor recovery changed captured history or original bytes')
    with psycopg.connect(recovery.database_url) as connection:
        sessions = connection.execute("select coalesce(jsonb_agg(to_jsonb(s)),'[]'::jsonb) from auth.sessions s where user_id=%s",
            (str(owner.actor_id.subject),)).fetchone()[0]
        if not sessions: raise ValueError('Revocation rehearsal requires a captured live Auth session')
    async with httpx.AsyncClient(trust_env=False, timeout=15) as client:
        response = await client.post(recovery.auth_url + '/auth/v1/logout?scope=global', headers={'Authorization': 'Bearer ' + owner_token})
        if response.status_code != 204: raise ValueError('Independent Auth session revocation failed')
        await auth_denied(owner_token)
        # Restore this target's captured session rows once to prove deletion from
        # an authenticated baseline independently of the preceding logout test.
        with psycopg.connect(recovery.database_url) as connection:
            connection.execute('insert into auth.sessions select * from jsonb_populate_recordset(null::auth.sessions,%s::jsonb)', (json.dumps(sessions),))
        if (await authentication._verified_actor(owner_token)).actor_id != owner.actor_id:
            raise ValueError('Independent deletion baseline did not restore the captured session')
        response = await client.request('DELETE', recovery.auth_url + '/auth/v1/admin/users/' + str(owner.actor_id.subject),
            headers={'Authorization': 'Bearer ' + recovery.admin_key}, json={'should_soft_delete': True})
        if response.status_code != 200: raise ValueError('Independent Auth soft deletion failed')
        await auth_denied(owner_token)
        await originals_denied(owner.actor_id)
    with psycopg.connect(recovery.database_url) as connection:
        retained = connection.execute('select deleted_at is not null from auth.users where id=%s', (str(owner.actor_id.subject),)).fetchone()
        if retained != (True,): raise ValueError('Soft-deleted historical actor tombstone is missing')
        # Always roll back this probe, even if the expected FK restriction fails.
        try:
            with connection.transaction(force_rollback=True):
                connection.execute('delete from auth.users where id=%s', (str(owner.actor_id.subject),))
        except psycopg.errors.ForeignKeyViolation:
            pass
        else:
            raise ValueError('Expected historical-actor physical-erasure restriction is absent')
    if await archive(other_token) != expected_canonical or await read_originals(reader_url, other.actor_id, original_queries) != originals:
        raise ValueError('Soft-deleted actor recovery changed captured history or original bytes')
    return {'independentAuthenticatedArchiveVerified': True, 'originalOutsiderDenied': True,
        'syntheticRecoveryOwnerProvisionedOnlyInTarget': True, 'revokedMembershipReadsDenied': True,
        'revokedAuthSessionDenied': True, 'softDeletedAuthSessionDenied': True,
        'softDeletionTestStartedFromLiveSession': True, 'historicalActorIdentityPreserved': True,
        'independentAuthorizedActorRecoveredArchiveAndOriginals': True,
        'physicalAuthUserErasure': 'blocked-by-preserved-historical-foreign-keys'}
