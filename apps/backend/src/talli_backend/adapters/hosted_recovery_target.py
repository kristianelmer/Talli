"""Explicit Supabase target transport. No create/pause/delete/billing operations."""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import base64
import json
import os
from pathlib import Path
import re
from urllib.parse import parse_qsl, unquote, urlsplit, quote

import httpx
import psycopg

from talli_backend.adapters.hosted_recovery_capture import digest, private_read, require


@dataclass(frozen=True)
class HostedDesignation:
    project: str
    organization: str
    name: str
    region: str

    def __post_init__(self):
        require(re.fullmatch('[a-z]{20}', self.project) and
            re.fullmatch('[a-z]{20}', self.organization) and
            isinstance(self.name, str) and 1 <= len(self.name) <= 100 and
            re.fullmatch('[a-z]{2}-[a-z]+-[0-9]', self.region), 'hosted_designation_invalid')

    def body(self):
        return {'project': self.project, 'organization': self.organization,
            'name': self.name, 'region': self.region}


def clean_libpq_environment():
    # libpq can use PGHOSTADDR alongside an explicit host, or load options from
    # PGSERVICE. Reject inherited defaults rather than mutating process globals.
    require(not any(name.startswith('PG') and value for name, value in os.environ.items()),
        'hosted_libpq_environment_override_unsupported')


def connection_settings(raw, designation, *, ca, ca_sha256):
    clean_libpq_environment()
    url = urlsplit(raw)
    pairs = parse_qsl(url.query, keep_blank_values=True)
    user = unquote(url.username or '')
    direct = url.hostname == 'db.' + designation.project + '.supabase.co'
    pooler = re.fullmatch(r'aws-[a-z0-9-]+\.pooler\.supabase\.com', url.hostname or '')
    require(url.scheme in ('postgresql', 'postgres') and url.path == '/postgres' and
        url.port == 5432 and not url.fragment and len(pairs) == len(dict(pairs)) and
        set(dict(pairs)) <= {'sslmode', 'connect_timeout'} and
        dict(pairs).get('sslmode') in ('require', 'verify-full') and url.password and
        (direct and user in ('postgres', 'cli_login_postgres') or pooler and
         user in ('postgres.' + designation.project, 'cli_login_postgres.' + designation.project)),
        'hosted_database_destination_mismatch')
    # Never forward DSN host/options/role overrides. TLS is always verify-full.
    require(digest(private_read(ca, 65536)) == ca_sha256, 'hosted_database_ca_changed')
    return {'host': url.hostname, 'port': 5432, 'dbname': 'postgres', 'user': user,
        'password': unquote(url.password), 'sslmode': 'verify-full', 'sslrootcert': str(Path(ca).absolute()),
        'connect_timeout': 8, 'application_name': 'talli-managed-recovery-operator-v1'}


class SupabaseRecoveryTarget:
    """Transport constructed only by the explicit operator, never an app factory.

    The credential file is external owner custody. It is never copied into the
    work journal, command arguments, receipts, exceptions or the application env.
    """
    def __init__(self, *, designation, credentials, ca, ca_sha256):
        self.designation = designation
        self.credential_path = Path(credentials).absolute()
        values = json.loads(private_read(self.credential_path, 32768))
        require(set(values) == {'project', 'databaseUrl', 'managementToken', 'serviceRoleKey'} and
            values['project'] == designation.project and isinstance(values['managementToken'], str) and
            len(values['managementToken']) >= 20, 'hosted_credentials_binding_invalid')
        key = values['serviceRoleKey']
        try:
            payload = json.loads(base64.urlsafe_b64decode(key.split('.')[1] + '==='))
        except Exception:
            raise ValueError('hosted_service_key_profile_unsupported') from None
        require(payload.get('ref') == designation.project and payload.get('role') == 'service_role',
            'hosted_service_key_destination_mismatch')
        self.settings = connection_settings(values['databaseUrl'], designation, ca=ca, ca_sha256=ca_sha256)
        self._ca_sha256 = ca_sha256
        self._management_token, self._service_key = values['managementToken'], key

    def validate(self, *, source_project, captured_at=None):
        require(self.designation.project != source_project, 'hosted_source_target_same')
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            response = client.get('https://api.supabase.com/v1/projects/' + self.designation.project,
                headers={'Authorization': 'Bearer ' + self._management_token})
        require(response.status_code == 200 and len(response.content) <= 65536,
            'hosted_target_metadata_unavailable')
        metadata = response.json()
        require(metadata.get('id') == self.designation.project and
            metadata.get('organization_id') == self.designation.organization and
            metadata.get('name') == self.designation.name and metadata.get('region') == self.designation.region and
            metadata.get('status') == 'ACTIVE_HEALTHY', 'hosted_target_designation_changed')
        if captured_at is not None:
            created = datetime.fromisoformat(metadata['created_at'].replace('Z', '+00:00'))
            captured = datetime.fromisoformat(captured_at.replace('Z', '+00:00'))
            require(created.tzinfo is not None and captured.tzinfo is not None and created >= captured,
                'hosted_fresh_project_required')
        return {'project': metadata['id'], 'organization': metadata['organization_id'],
            'name': metadata['name'], 'region': metadata['region'], 'status': metadata['status']}

    @contextmanager
    def database(self):
        clean_libpq_environment()
        require(digest(private_read(self.settings['sslrootcert'], 65536)) == self._ca_sha256,
            'hosted_database_ca_changed')
        with psycopg.connect(**self.settings) as db:
            db.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
            db.execute('set role postgres')
            identity = db.execute("select current_user,current_database(),current_setting('server_version_num')::int").fetchone()
            require(identity[0:2] == ('postgres', 'postgres') and identity[2] // 10000 == 17,
                'hosted_database_profile_changed')
            yield db

    def _storage(self, method, path, *, body=None, content_type=None, json_body=None, public=False):
        headers = {} if public else {'apikey': self._service_key, 'Authorization': 'Bearer ' + self._service_key}
        if content_type is not None:
            require('\r' not in content_type and '\n' not in content_type, 'hosted_content_type_invalid')
            headers.update({'Content-Type': content_type, 'x-upsert': 'false'})
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            with client.stream(method, 'https://' + self.designation.project + '.supabase.co/storage/v1' + path,
                    headers=headers, content=body, json=json_body) as response:
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    require(len(content) <= 8 * 1024**2, 'hosted_storage_response_bound')
                return response.status_code, bytes(content)

    def ensure_private_bucket(self, name):
        path = '/bucket/' + quote(name, safe='')
        status, raw = self._storage('GET', path)
        if status in (400, 404):
            # An unknown POST outcome is resolved by the next explicit resume's
            # GET, never by an overwrite or a speculative retry in this command.
            status, _ = self._storage('POST', '/bucket', json_body={'id': name, 'name': name, 'public': False})
            require(status == 200, 'hosted_private_bucket_creation_failed')
            status, raw = self._storage('GET', path)
        require(status == 200 and json.loads(raw).get('id') == name and
            json.loads(raw).get('public') is False, 'hosted_bucket_not_private')

    def restore_object(self, obj, raw):
        self.ensure_private_bucket(obj['bucket'])
        path = '/object/' + quote(obj['bucket'], safe='') + '/' + quote(obj['name'], safe='/')
        status, observed = self._storage('GET', path)
        if status in (400, 404):
            status, _ = self._storage('POST', path, body=raw,
                content_type=obj.get('contentType') or 'application/octet-stream')
            require(status == 200, 'hosted_object_upload_failed')
            status, observed = self._storage('GET', path)
        require(status == 200 and len(observed) == obj['bytes'] and digest(observed) == obj['sha256'],
            'hosted_object_conflict_or_changed')
        status, _ = self._storage('GET', '/object/public/' + quote(obj['bucket'], safe='') + '/' +
            quote(obj['name'], safe='/'), public=True)
        require(status in (400, 401, 403, 404), 'hosted_private_object_publicly_accessible')
        return {'bucket': obj['bucket'], 'name': obj['name'], 'bytes': obj['bytes'],
            'sha256': obj['sha256'], 'servedExact': True, 'publicRouteDenied': True,
            'providerIdsVersionsAndTimestampsAdapted': True}
