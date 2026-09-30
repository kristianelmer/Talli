"""File-backed Storage recovery for an explicitly owned, quiescent local fixture.

Only the newly created container and volume are removed. The source file tree is
read through tar; it is never mounted in the restored service. This helper is not
a hosted backup command or proof of independent-cluster role recovery.
"""
from contextlib import contextmanager
import hashlib
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
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import uuid4

import httpx
from psycopg.conninfo import conninfo_to_dict

from talli_backend.adapters.supabase_documents import (
    DocumentsSupabaseConfiguration, SupabaseDocumentsAdapter, SupabaseDocumentObjectStorage,
)
from talli_backend.modules.documents.public import DocumentErrorCode, DocumentTransferKind, DocumentsError

# BusyBox tar in the pinned Storage image does not preserve Linux xattrs.
# Its own installed fs-xattr library carries Storage's content type/cache/etag.
CAPTURE_ATTRIBUTES = r"""
const fs = require('fs'), path = require('path'), xattr = require('fs-xattr');
const entries = [];
function walk(relative) {
  const file = path.join('/mnt', relative), stat = fs.lstatSync(file);
  if (stat.isSymbolicLink() || (!stat.isDirectory() && !stat.isFile())) throw Error('unsupported storage file');
  const attributes = {};
  for (const key of xattr.listSync(file).sort()) attributes[key] = xattr.getSync(file, key).toString('base64');
  entries.push({ path: relative, directory: stat.isDirectory(), attributes });
  if (stat.isDirectory()) for (const name of fs.readdirSync(file).sort()) walk(path.join(relative, name));
}
walk('.'); process.stdout.write(JSON.stringify(entries));
"""
RESTORE_ATTRIBUTES = r"""
const fs = require('fs'), path = require('path'), xattr = require('fs-xattr');
for (const entry of JSON.parse(fs.readFileSync(0, 'utf8'))) {
  if (path.isAbsolute(entry.path) || (entry.path !== '.' && entry.path.split('/').some(p => !p || p === '.' || p === '..')))
    throw Error('invalid storage path');
  const file = path.join('/mnt', entry.path), stat = fs.lstatSync(file);
  if (stat.isSymbolicLink() || stat.isDirectory() !== entry.directory || (!stat.isDirectory() && !stat.isFile()))
    throw Error('storage file type mismatch');
  for (const [key, value] of Object.entries(entry.attributes)) xattr.setSync(file, key, Buffer.from(value, 'base64'));
}
"""


def attributes(container):
    return checked(['docker', 'exec', container, 'node', '-e', CAPTURE_ATTRIBUTES], stdout=subprocess.PIPE).stdout


def ordinary_originals(snapshots):
    originals = {}
    for snapshot in snapshots:
        original = snapshot.original
        identity = str(original.receipt.document_id)
        if identity in originals and originals[identity] != original:
            raise ValueError('Ordinary object has conflicting retained generations')
        originals[identity] = original
    return list(originals.values())


def storage_source(workdir, database_url, boundary):
    db_id, _ = boundary.owned_source(workdir, database_url, boundary.inspect_container)
    boundary.verify_source_session(database_url, db_id)
    config = tomllib.loads((Path(workdir) / 'supabase/config.toml').read_text())
    project = config['project_id']
    name, network = 'supabase_storage_' + project, 'supabase_network_' + project
    source = boundary.inspect_container(name)
    env = dict(entry.split('=', 1) for entry in source['Config']['Env'])
    mounts = [mount for mount in source['Mounts'] if mount['Destination'] == '/mnt']
    if (source['Name'] != '/' + name or not source['State']['Running']
            or set(source['NetworkSettings']['Networks']) != {network}
            or network not in boundary.inspect_container(db_id)['NetworkSettings']['Networks']
            or env.get('STORAGE_BACKEND') != 'file' or env.get('FILE_STORAGE_BACKEND_PATH') != '/mnt'
            or len(mounts) != 1 or mounts[0]['Type'] != 'volume'
            or not re.fullmatch(r'sha256:[a-f0-9]{64}', source['Image'])):
        raise ValueError('Storage source is not the owned file-backed container')
    for key in ('DATABASE_URL', 'VECTOR_DATABASE_URL'):
        url = urlsplit(env.get(key, ''))
        if (url.scheme not in ('postgres', 'postgresql') or url.hostname != 'supabase_db_' + project
                or url.port != 5432 or url.path != '/postgres' or url.query or url.fragment):
            raise ValueError('Storage database does not identify the owned source')
    auth = urlsplit(os.environ.get('SUPABASE_URL', ''))
    gateway_name = 'supabase_kong_' + project
    gateway = boundary.inspect_container(gateway_name)
    bindings = gateway.get('NetworkSettings', {}).get('Ports', {}).get('8000/tcp', []) or []
    if (auth.scheme != 'http' or auth.hostname not in ('127.0.0.1', 'localhost', '::1')
            or auth.port != config['api']['port'] or auth.path not in ('', '/')
            or auth.username or auth.password or auth.query or auth.fragment
            or gateway.get('Name') != '/' + gateway_name or not gateway.get('State', {}).get('Running')
            or set(gateway.get('NetworkSettings', {}).get('Networks', {})) != {network}
            or not any(binding.get('HostPort') == str(auth.port)
                       and binding.get('HostIp') in ('127.0.0.1', '0.0.0.0', '::', '::1') for binding in bindings)
            or not env.get('SERVICE_KEY') or not os.environ.get('SUPABASE_SERVICE_ROLE_KEY')):
        raise ValueError('Storage authentication must use the owned local API')
    return source, env, network


def clone_environment(env, restored_url):
    clone = conninfo_to_dict(restored_url)['dbname']
    if not re.fullmatch(r'rf193_restore_[a-f0-9]{32}', clone):
        raise ValueError('Storage requires the newly restored RF database')
    # Copy only the local configuration needed by the pinned Storage image.
    allowed = {'ANON_KEY', 'SERVICE_KEY', 'AUTH_JWT_SECRET', 'JWT_JWKS', 'TENANT_ID',
               'REGION', 'GLOBAL_S3_BUCKET', 'FILE_SIZE_LIMIT', 'DATABASE_SEARCH_PATH',
               'DB_INSTALL_ROLES', 'DB_MIGRATIONS_FREEZE_AT', 'S3_PROTOCOL_ACCESS_KEY_ID',
               'S3_PROTOCOL_ACCESS_KEY_SECRET', 'STORAGE_S3_REGION', 'VECTOR_ENABLED',
               'VECTOR_STORE_MIGRATIONS_ENABLED', 'VECTOR_BUCKET_PROVIDER'}
    result = {key: value for key, value in env.items() if key in allowed}
    for key in ('DATABASE_URL', 'VECTOR_DATABASE_URL'):
        result[key] = urlunsplit(urlsplit(env[key])._replace(path='/' + clone))
    result.update(STORAGE_BACKEND='file', FILE_STORAGE_BACKEND_PATH='/mnt', DB_INSTALL_ROLES='false',
                  ENABLE_IMAGE_TRANSFORMATION='false', LOG_LEVEL='fatal')
    if any('\n' in value or '\r' in value for value in result.values()):
        raise ValueError('Storage environment cannot contain line breaks')
    return result


def checked(args, **kwargs):
    # Avoid command diagnostics that could include configuration or object URLs.
    try:
        result = subprocess.run(args, stderr=subprocess.PIPE, timeout=30, **kwargs)
    except subprocess.TimeoutExpired:
        raise RuntimeError('Owned Storage restore command timed out: ' + args[1]) from None
    if result.returncode:
        raise RuntimeError('Owned Storage restore command failed: ' + args[1])
    return result


def snapshot(container, target):
    checked(['docker', 'exec', container, 'tar', '-C', '/mnt', '-cf', '-', '.'], stdout=target)
    target.seek(0)
    digest = hashlib.file_digest(target, 'sha256').hexdigest()
    target.seek(0)
    return digest


@contextmanager
def storage_gateway(port):
    """Local gateway prefix only; authorization and bytes belong to Storage API."""
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # A signed URL is a credential, never a diagnostic.

        def do_GET(self):
            self.forward()

        def do_POST(self):
            self.forward()

        def forward(self):
            length = int(self.headers.get('Content-Length', '0'))
            if not self.path.startswith('/storage/v1/object/') or not 0 <= length <= 4096:
                self.send_error(404)
                return
            connection = HTTPConnection('127.0.0.1', port, timeout=15)
            try:
                headers = {key: value for key, value in self.headers.items()
                           if key.lower() in ('authorization', 'apikey', 'content-type')}
                connection.request(self.command, self.path[len('/storage/v1'):],
                                   self.rfile.read(length) if length else None, headers)
                response = connection.getresponse()
                body = response.read(10 * 1024 * 1024 + 1)
                if len(body) > 10 * 1024 * 1024:
                    raise ValueError('Object exceeds fixture bound')
                self.send_response(response.status)
                self.send_header('Content-Type', response.getheader('Content-Type', 'application/octet-stream'))
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception:
                self.send_error(502, 'Owned Storage unavailable')
            finally:
                connection.close()

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:' + str(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@contextmanager
def restored_storage(source, env, network, restored_url, boundary):
    restored_env = clone_environment(env, restored_url)
    nonce = uuid4().hex
    volume = 'rf193_objects_' + nonce
    container = None
    volume_created = False
    with tempfile.TemporaryFile() as archive, tempfile.TemporaryDirectory(prefix='talli-rf-storage-') as directory:
        before = snapshot(source['Id'], archive)
        original_attributes = attributes(source['Id'])
        try:
            checked(['docker', 'volume', 'create', '--label', 'talli.rf.restore=' + nonce, volume], stdout=subprocess.PIPE)
            inspected = json.loads(subprocess.check_output(['docker', 'volume', 'inspect', volume]))[0]
            if inspected['Name'] != volume or inspected.get('Labels', {}).get('talli.rf.restore') != nonce:
                raise ValueError('Storage volume ownership mismatch')
            volume_created = True
            checked(['docker', 'run', '--rm', '--pull=never', '--network', 'none', '--user', '0', '--entrypoint', 'tar',
                     '-i', '-v', volume + ':/mnt', source['Image'], '-C', '/mnt', '-xf', '-'],
                    stdin=archive, stdout=subprocess.PIPE)
            helper = ['docker', 'run', '--rm', '--pull=never', '--network', 'none', '--user', '0',
                      '--entrypoint', 'node', '-i', '-v', volume + ':/mnt', source['Image']]
            checked(helper + ['-e', RESTORE_ATTRIBUTES], input=original_attributes, stdout=subprocess.PIPE)
            restored_attributes = checked(helper + ['-e', CAPTURE_ATTRIBUTES], stdout=subprocess.PIPE).stdout
            if restored_attributes != original_attributes:
                raise ValueError('Restored Storage file attributes differ from source')
            configuration = Path(directory) / 'storage.env'
            configuration.touch(mode=0o600)
            configuration.write_text(''.join(key + '=' + value + '\n'
                                            for key, value in restored_env.items()))
            result = checked(['docker', 'create', '--pull=never', '--name', 'rf193_storage_' + nonce,
                              '--label', 'talli.rf.restore=' + nonce, '--network', network,
                              '--env-file', str(configuration), '-v', volume + ':/mnt',
                              '-p', '127.0.0.1::5000', source['Image']], stdout=subprocess.PIPE)
            created_id = result.stdout.decode().strip()
            if not re.fullmatch(r'[a-f0-9]{64}', created_id):
                raise ValueError('Storage container identity missing')
            container = created_id
            checked(['docker', 'start', container], stdout=subprocess.PIPE)
            running = boundary.inspect_container(container)
            ports = running['NetworkSettings']['Ports']['5000/tcp']
            if len(ports) != 1 or ports[0]['HostIp'] != '127.0.0.1':
                raise ValueError('Restored Storage must bind only loopback')
            port = int(ports[0]['HostPort'])
            with httpx.Client(trust_env=False, timeout=1) as client:
                for _ in range(60):
                    try:
                        if client.get(f'http://127.0.0.1:{port}/status').status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.25)
                else:
                    raise RuntimeError('Restored Storage did not become ready')
            with storage_gateway(port) as gateway:
                yield gateway
        finally:
            try:
                if container:
                    checked(['docker', 'rm', '-f', container], stdout=subprocess.PIPE)
            finally:
                if volume_created:
                    checked(['docker', 'volume', 'rm', volume], stdout=subprocess.PIPE)
        with tempfile.TemporaryFile() as after:
            if snapshot(source['Id'], after) != before or attributes(source['Id']) != original_attributes:
                raise ValueError('Restore rehearsal changed source Storage files')


async def verify_objects(database_url, company_access_url, storage_url, originals, *, storage_key=None):
    """Real Auth verification + restored Company Access/Documents + restored bytes."""
    factory = SupabaseDocumentsAdapter(DocumentsSupabaseConfiguration(
        os.environ['SUPABASE_URL'], os.environ['SUPABASE_ANON_KEY'], os.environ['SUPABASE_SERVICE_ROLE_KEY'],
        database_url, company_access_url))
    # The original gateway accepts an opaque secret key and translates it to
    # Storage's internal JWT. The restored direct Storage API needs that JWT.
    factory._storage = SupabaseDocumentObjectStorage(storage_url, storage_key or os.environ['SUPABASE_SERVICE_ROLE_KEY'])
    sessions = {name: await factory.session(os.environ['TALLI_RF_RESTORE_' + name + '_TOKEN'])
                for name in ('OWNER', 'OUTSIDER', 'LOW_AAL')}
    documents = []
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=15) as client:
        for original in originals:
            identity = original.receipt.document_id
            transfer = await sessions['OWNER'].create_transfer(identity, DocumentTransferKind.DOWNLOAD)
            if urlsplit(transfer.signed_url).netloc != urlsplit(storage_url).netloc:
                raise ValueError('Signed object URL left the restored store')
            response = await client.get(transfer.signed_url)
            if response.status_code != 200 or response.content != original.content:
                raise ValueError('Restored ordinary object differs from retained bytes')
            documents.append(transfer.document)
            for name, codes in [('OUTSIDER', {DocumentErrorCode.FORBIDDEN, DocumentErrorCode.NOT_FOUND}),
                                ('LOW_AAL', {DocumentErrorCode.STEP_UP_REQUIRED})]:
                try:
                    await sessions[name].create_transfer(identity, DocumentTransferKind.DOWNLOAD)
                except DocumentsError as error:
                    if error.code not in codes:
                        raise
                else:
                    raise ValueError('Restored Documents admitted ' + name)
            direct = storage_url + '/storage/v1/object/authenticated/company-documents/' + quote(transfer.document.storage_key, safe='/')
            for token in ('', os.environ['TALLI_RF_RESTORE_OWNER_TOKEN'], os.environ['TALLI_RF_RESTORE_OUTSIDER_TOKEN']):
                response = await client.get(direct, headers={'Authorization': 'Bearer ' + token} if token else {})
                if response.status_code not in (400, 401, 403, 404):
                    raise ValueError('Restored Storage admitted a direct object read')
    return documents
