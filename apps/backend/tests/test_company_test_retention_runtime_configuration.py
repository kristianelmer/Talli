"""Runtime composition through public HTTP; all external services are doubles."""
from dataclasses import asdict
from io import BytesIO
import json
from urllib.error import HTTPError
from urllib.request import OpenerDirector

import httpx
from httpx import AsyncClient as HttpxAsyncClient
import psycopg
import pytest
from fastapi.testclient import TestClient

from talli_backend.adapters import company_test_retention_runtime as runtime
from talli_backend.adapters import dependency_readiness as health
from talli_backend.application.shareholder_register_company_test_retention_stream import verify_company_test_retention_stream
from talli_backend.main import create_app
from test_company_test_retention_download_policy import ArchiveGateway, NOW, token, fixed_policy_clock
from test_dependency_readiness import Connection as ReadinessConnection
from test_rf1086_company_test_retention import ACTOR, COMPANY, OBSERVED, capture, record, wire
from test_rf1086_company_test_retention_http import PATH, ReadFactory, ReadSession

MODE = 'TALLI_COMPANY_TEST_RETENTION_MODE'
DATABASE = 'TALLI_COMPANY_TEST_RETENTION_DATABASE_URL'
SETTINGS = {
    MODE: 'postgres',
    'SUPABASE_URL': 'https://history-auth.example',
    'SUPABASE_ANON_KEY': 'synthetic-publishable-key',
    DATABASE: 'postgresql://history_reader:synthetic-password@history-db.example/history',
}


class InjectedMarketing:
    async def purge(self):
        return None


INJECTED = {
    name: object() for name in (
        'company_access_gateway', 'company_registry_gateway', 'ledger_session_factory',
        'company_tax_session_factory', 'annual_accounts_session_factory',
        'investments_session_factory', 'corporate_governance_session_factory',
        'documents_session_factory', 'banking_session_factory', 'billing_session_factory',
        'annual_billing_session_factory', 'shareholder_register_filing_session_factory',
        'launch_signoff_session_factory', 'authority_connections_session_factory',
        'marketing_measurement_gateway', 'annual_billing_provider',
    )
}
INJECTED['marketing_measurement_gateway'] = InjectedMarketing()


@pytest.fixture(autouse=True)
def isolated_history_configuration(monkeypatch):
    for setting in SETTINGS:
        monkeypatch.delenv(setting, raising=False)
    monkeypatch.setenv('TALLI_ANNUAL_BILLING_MODE', 'off')

    def forbidden(*args, **kwargs):
        pytest.fail('unexpected external I/O')

    monkeypatch.setattr(OpenerDirector, 'open', forbidden)
    monkeypatch.setattr(psycopg.AsyncConnection, 'connect', forbidden)
    monkeypatch.setattr(health.httpx, 'AsyncClient', forbidden)


def enable(monkeypatch):
    for key, value in SETTINGS.items():
        monkeypatch.setenv(key, value)


def test_enabled_missing_dedicated_database_refuses_startup(monkeypatch):
    enable(monkeypatch)
    monkeypatch.delenv(DATABASE)
    monkeypatch.setenv('DATABASE_URL', 'privileged-must-not-substitute')
    monkeypatch.setenv('TALLI_LEDGER_DATABASE_URL', 'general-must-not-substitute')
    with pytest.raises(ValueError, match=DATABASE):
        create_app(**INJECTED)


def test_enabled_history_adds_own_readiness_even_with_general_rf_injected(monkeypatch):
    enable(monkeypatch)
    observed = []

    async def database(dsn, roles):
        observed.append(('database', dsn, roles))
        return True

    async def auth(origin, key):
        observed.append(('auth', origin, key))
        return True

    monkeypatch.setattr(health, 'probe_database', database)
    monkeypatch.setattr(health, 'probe_auth', auth)
    with TestClient(create_app(**INJECTED)) as browser:
        assert browser.get('/health/ready').status_code == 200
    assert sorted(observed) == sorted([
        ('database', SETTINGS[DATABASE], ('shareholder_register_filing_executor',)),
        ('auth', SETTINGS['SUPABASE_URL'], SETTINGS['SUPABASE_ANON_KEY']),
    ])


@pytest.mark.parametrize('mode', [None, 'off'])
def test_off_keeps_both_routes_closed_and_ignores_unused_settings(monkeypatch, mode):
    if mode is not None:
        monkeypatch.setenv(MODE, mode)
    for setting in ('SUPABASE_URL', 'SUPABASE_ANON_KEY', DATABASE):
        monkeypatch.setenv(setting, 'unused-invalid-value')
    monkeypatch.setenv('TALLI_LEDGER_DATABASE_URL', 'general-must-not-enable')
    monkeypatch.setenv('DATABASE_URL', 'privileged-must-not-enable')

    def forbidden(*args):
        pytest.fail('off must not construct a history factory')

    monkeypatch.setattr(runtime, 'PostgresCompanyTestRetentionSessionFactory', forbidden)
    with TestClient(create_app(**INJECTED)) as browser:
        for suffix in ('', '/stream-v1'):
            response = browser.get(PATH + suffix, params={'companyId': str(COMPANY)})
            assert response.status_code == 503
            assert response.json()['code'] == 'rf1086_company_test_retention_not_configured'
        # No composed infrastructure: no probe I/O or implied custom health.
        assert browser.get('/health/ready').status_code == 503


def test_explicit_factory_bypasses_invalid_ambient_config_and_readiness(monkeypatch):
    monkeypatch.setenv(MODE, 'invalid-secret-mode')
    monkeypatch.setenv(DATABASE, 'invalid-secret-dsn')
    session = ReadSession()
    with TestClient(create_app(**INJECTED, company_test_retention_session_factory=ReadFactory(session))) as browser:
        response = browser.get(PATH, params={'companyId': str(COMPANY)}, headers={'Authorization': 'Bearer ' + token()})
        assert response.status_code == 200 and response.content == wire(session.snapshot).encode()
        assert browser.get('/health/ready').status_code == 503


@pytest.mark.parametrize('mode', ['', 'POSTGRES', ' postgres', 'postgres ', 'auto', 'production'])
def test_invalid_mode_reports_only_setting(monkeypatch, mode):
    monkeypatch.setenv(MODE, mode)
    with pytest.raises(runtime.CompanyTestRetentionRuntimeConfigurationError) as failure:
        create_app(**INJECTED)
    assert str(failure.value) == f'Invalid company test retention runtime setting: {MODE}'


INVALID_FIELDS = [
    (setting, value)
    for setting in ('SUPABASE_URL', 'SUPABASE_ANON_KEY', DATABASE)
    for value in (None, '', ' leading-secret', 'trailing-secret ', 'embedded\nsecret', 'secret\x7f', 's' * 8193)
] + [
    ('SUPABASE_URL', value) for value in (
        'http://remote.example', 'https://user:secret@auth.example', 'https://auth.example/path',
        'https://auth.example?secret', 'https://auth.example#secret', 'https://auth.example:0',
        'https://auth.example:bad', 'https://[broken', 'https://auth example', 'https://auth.example\\secret',
    )
] + [
    ('SUPABASE_ANON_KEY', value) for value in ('secret key', 'nonascii-ø')
] + [
    (DATABASE, value) for value in (
        'host=db.example user=reader dbname=history', 'https://reader:secret@db.example/history',
        'postgresql://db.example/history', 'postgresql://reader:secret@db.example/',
        'postgresql://reader:secret@/history', 'postgresql://reader:secret@db.example:0/history',
        'postgresql://reader:secret@db.example:bad/history', 'postgresql://reader:secret@db.example/history#x',
        'postgresql://reader:secret@db.example/history?unknown_option=secret',
    )
]


@pytest.mark.parametrize(('setting', 'value'), INVALID_FIELDS, ids=[f'configuration-{i}' for i in range(len(INVALID_FIELDS))])
def test_invalid_enabled_fields_fail_before_construction_without_disclosing_values(monkeypatch, setting, value):
    settings = dict(SETTINGS, DATABASE_URL='privileged-no-fallback', TALLI_LEDGER_DATABASE_URL='general-no-fallback')
    if value is None:
        settings.pop(setting)
    else:
        settings[setting] = value

    def forbidden(*args):
        pytest.fail('validate every field before adapter construction')

    monkeypatch.setattr(runtime, 'PostgresCompanyTestRetentionSessionFactory', forbidden)
    with pytest.raises(runtime.CompanyTestRetentionRuntimeConfigurationError) as failure:
        runtime.compose_company_test_retention_runtime(settings)
    assert str(failure.value) == f'Invalid company test retention runtime setting: {setting}'
    assert failure.value.__cause__ is None


@pytest.mark.parametrize('origin', ['https://auth.example/', 'http://localhost:8000', 'http://127.0.0.1:8000', 'http://[::1]:8000'])
def test_valid_configuration_constructs_without_io_and_redacts_secrets(origin):
    settings = {**SETTINGS, 'SUPABASE_URL': origin}
    config = runtime.CompanyTestRetentionRuntimeConfiguration.from_environment(settings)
    assert config.auth_url == origin.rstrip('/')
    assert config.anon_key == SETTINGS['SUPABASE_ANON_KEY'] and config.database_url == SETTINGS[DATABASE]
    assert config.anon_key not in repr(config) and config.database_url not in repr(config)
    assert 'synthetic-password' not in repr(config)
    assert isinstance(runtime.compose_company_test_retention_runtime(settings), runtime.PostgresCompanyTestRetentionSessionFactory)


def test_explicit_readiness_probe_retains_precedence(monkeypatch):
    enable(monkeypatch)
    calls = []

    async def ready():
        calls.append(True)
        return True

    with TestClient(create_app(**INJECTED, readiness_probe=ready)) as browser:
        assert browser.get('/health/ready').status_code == 200
    assert calls == [True]


@pytest.mark.parametrize('failure', [None, 'auth', 'role'])
def test_composed_readiness_uses_real_probes_and_refuses_auth_or_role_loss(monkeypatch, failure):
    enable(monkeypatch)
    connection = ReadinessConnection(deny=failure == 'role')
    calls = []

    async def connect(dsn, **kwargs):
        assert dsn == SETTINGS[DATABASE] and kwargs['connect_timeout'] == 2
        assert 'default_transaction_read_only=on' in kwargs['options']
        calls.append('database')
        return connection

    def handle(request):
        assert str(request.url) == SETTINGS['SUPABASE_URL'] + '/auth/v1/settings'
        assert request.headers['apikey'] == SETTINGS['SUPABASE_ANON_KEY']
        calls.append('auth')
        return httpx.Response(401 if failure == 'auth' else 200, json={'external': {'email': True}, 'disable_signup': False})

    monkeypatch.setattr(health.httpx, 'AsyncClient', lambda **kwargs: HttpxAsyncClient(**kwargs, transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(psycopg.AsyncConnection, 'connect', connect)
    with TestClient(create_app(**INJECTED)) as browser:
        response = browser.get('/health/ready')
        assert response.status_code == (200 if failure is None else 503)
        assert response.json() == {'status': 'ready' if failure is None else 'not_ready'}
    assert sorted(calls) == ['auth', 'database'] and connection.closed
    assert 'set local role "shareholder_register_filing_executor"' in connection.statements


class HistoryCursor:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.connection.cursor_closed = True

    async def execute(self, statement, params):
        assert 'from shareholder_register_filing.authority_test_runs' in statement
        assert params == (str(COMPANY),)
        self.connection.scanned = True

    async def rows(self):
        yield {**asdict(record()), '_retention_oversize': False}

    def __aiter__(self):
        return self.rows()


class HistoryConnection:
    def __init__(self, failure):
        self.failure = failure
        self.statements = []
        self.scanned = self.cursor_closed = False
        self.exits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.exits += 1

    def transaction(self):
        return self

    async def execute(self, statement, params=None):
        self.statements.append(statement)
        if 'assert_member_v1' in statement:
            assert params == (str(COMPANY),)
            if self.failure == 'member':
                raise psycopg.errors.RaiseException('rf1086_not_found')
        if 'talli.verified_actor_id' in statement:
            assert params[0] == str(ACTOR.subject)
            assert json.loads(params[1])['sub'] == str(ACTOR.subject)
        return self

    async def fetchone(self):
        return {'total': 1, 'observed_at': OBSERVED}

    def cursor(self, *, name):
        assert name.startswith('rf_company_test_retention_')
        return HistoryCursor(self)


@pytest.mark.parametrize(('case', 'status'), [
    ('read', 200), ('fresh-download', 200), ('low-aal-download', 403), ('stale-download', 403),
    ('missing-bearer', 401), ('auth-denied', 401), ('banned', 401), ('foreign-sub', 401),
    ('stateless', 401), ('member', 404), ('database', 503),
])
def test_real_composition_preserves_current_auth_member_and_download_authority(monkeypatch, case, status):
    enable(monkeypatch)
    connection = HistoryConnection(case)
    calls = []
    gateway = ArchiveGateway('read_only')
    credentials = token()
    if case == 'foreign-sub':
        credentials = token(sub='00000000-0000-0000-0000-000000000099')
    if case == 'stateless':
        credentials = token(session_id=None)
    if case == 'low-aal-download':
        credentials = token(aal='aal1')
    if case in {'stale-download', 'read'}:
        credentials = token(amr=[{'method': 'totp', 'timestamp': NOW.timestamp() - 3600}])

    def auth_open(self, request, *, timeout):
        assert request.full_url == SETTINGS['SUPABASE_URL'] + '/auth/v1/user'
        assert request.get_header('Apikey') == SETTINGS['SUPABASE_ANON_KEY']
        assert request.get_header('Authorization') == 'Bearer ' + credentials and timeout == 5
        calls.append('auth')
        if case == 'auth-denied':
            raise HTTPError(request.full_url, 401, 'synthetic-denied', {}, None)
        user = {'id': str(ACTOR.subject), 'email': 'synthetic@example.invalid'}
        if case == 'banned':
            user['banned_until'] = '2999-01-01T00:00:00Z'
        response = BytesIO(json.dumps(user).encode())
        response.status = 200
        return response

    async def connect(dsn, **kwargs):
        assert dsn == SETTINGS[DATABASE] and kwargs['connect_timeout'] == 5
        calls.append('database')
        if case == 'database':
            raise psycopg.OperationalError('synthetic-private-connection-error')
        return connection

    monkeypatch.setattr(OpenerDirector, 'open', auth_open)
    monkeypatch.setattr(psycopg.AsyncConnection, 'connect', connect)
    suffix = '/stream-v1' if 'download' in case else ''
    headers = {} if case == 'missing-bearer' else {'Authorization': 'Bearer ' + credentials}
    dependencies = {**INJECTED, 'company_access_gateway': gateway}
    with TestClient(create_app(**dependencies)) as browser:
        response = browser.get(PATH + suffix, params={'companyId': str(COMPANY)}, headers=headers)
    assert response.status_code == status
    if status == 200:
        expected = capture(record())
        if suffix:
            assert verify_company_test_retention_stream(BytesIO(response.content), company_id=COMPANY) == expected
            assert len(gateway.calls) == 8
        else:
            assert response.content == wire(expected).encode() and gateway.calls == []
        assert calls == ['auth', 'database']
        assert connection.scanned and connection.cursor_closed and connection.exits == 2
        assert connection.statements[:3] == ['set transaction isolation level repeatable read',
                                            'set transaction read only', 'set local role shareholder_register_filing_executor']
    else:
        assert 'records' not in response.json() and 'content-disposition' not in response.headers
        assert 'synthetic-private-connection-error' not in response.text
        assert not connection.scanned
        if status == 401 or case in {'low-aal-download', 'stale-download'}:
            assert calls == ([] if case == 'missing-bearer' else ['auth'])
        if status == 403:
            assert response.json()['code'] == 'FRESH_MFA_REQUIRED'
