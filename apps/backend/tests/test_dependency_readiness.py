import asyncio
import json
from threading import Event

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from talli_backend.adapters import dependency_readiness as health
from talli_backend.main import create_app


def test_application_lifespan_starts_and_drains_owned_tasks(monkeypatch):
    entered, cancelled = Event(), Event()
    closed = []
    original_close = health.CachedReadiness.close

    class Gateway:
        async def purge(self):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    async def close_readiness(self):
        await original_close(self)
        closed.append(True)

    monkeypatch.setattr(health.CachedReadiness, "close", close_readiness)
    with TestClient(create_app(marketing_measurement_gateway=Gateway())) as client:
        assert entered.wait(1), "application startup did not start its owned task"
        assert client.get("/health/live").status_code == 200
    assert cancelled.is_set(), "application shutdown did not drain its owned task"
    assert closed == [True]


def test_health_uses_explicit_probe_and_preserves_safe_liveness():
    for value in (True, False):
        async def probe():
            return value
        client = TestClient(create_app(readiness_probe=probe))
        response = client.get('/health/ready')
        assert response.status_code == (200 if value else 503)
        assert response.json() == {'status': 'ready' if value else 'not_ready'}
        assert response.headers['cache-control'] == 'no-store'
        live = client.get('/health/live')
        assert live.status_code == 200 and live.json() == {'status': 'alive'}
        assert live.headers['cache-control'] == 'no-store'


def test_health_hides_probe_exception_and_missing_default_configuration(monkeypatch):
    async def failure():
        raise RuntimeError('postgres://secret.example/password')
    for probe in (failure, None):
        for name in ('SUPABASE_URL', 'SUPABASE_ANON_KEY', 'TALLI_LEDGER_DATABASE_URL',
                     'TALLI_COMPANY_ACCESS_DATABASE_URL', 'TALLI_BANKING_DATABASE_URL',
                     'TALLI_MARKETING_MEASUREMENT_DATABASE_URL'):
            monkeypatch.delenv(name, raising=False)
        response = TestClient(create_app(readiness_probe=probe)).get('/health/ready')
        assert response.status_code == 503
        assert response.json() == {'status': 'not_ready'}


def test_parallel_single_flight_cache_expiry_and_caller_cancellation():
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = 0
        async def probe():
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()
            return True
        cached = health.CachedReadiness(probe, ttl=.02)
        first = asyncio.create_task(cached())
        await entered.wait()
        other = asyncio.create_task(cached())
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        release.set()
        assert await other is True
        assert await cached() is True and calls == 1
        await asyncio.sleep(.03)
        assert await cached() is True and calls == 2
    asyncio.run(scenario())


def test_deadline_and_shutdown_cancel_and_drain_probe():
    async def scenario():
        cleaned = asyncio.Event()
        async def hanging():
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()
        cached = health.CachedReadiness(hanging, deadline=.02)
        assert await cached() is False
        assert cleaned.is_set()
        # Negative results are cached too.
        assert await cached() is False
        cleaned.clear()
        cached = health.CachedReadiness(hanging)
        task = asyncio.create_task(cached())
        await asyncio.sleep(.001)
        await cached.close()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned.is_set()
    asyncio.run(scenario())


@pytest.mark.parametrize('mode', ['ok', 'key', 'dns', 'timeout', 'redirect', 'malformed', 'shape', 'oversized'])
def test_auth_requires_key_enforced_settings_and_bounded_valid_response(monkeypatch, mode):
    settings = {'external': {'email': True}, 'disable_signup': False}
    def handle(request):
        assert request.url.path == '/auth/v1/settings'
        assert request.headers['apikey'] == ('invalid-key' if mode == 'key' else 'anon-key')
        if mode == 'dns':
            raise httpx.ConnectError('secret DNS failure', request=request)
        if mode == 'timeout':
            raise httpx.ReadTimeout('secret timeout', request=request)
        if mode == 'key':
            return httpx.Response(401, json={'message': 'Invalid API key'})
        if mode == 'redirect':
            return httpx.Response(302, headers={'location': 'https://secret.example'})
        if mode == 'malformed':
            return httpx.Response(200, text='{', headers={'content-type': 'application/json'})
        if mode == 'shape':
            return httpx.Response(200, json={'status': 'ok'})
        if mode == 'oversized':
            return httpx.Response(200, content=json.dumps(settings) + ' ' * health.MAX_RESPONSE_BYTES,
                                  headers={'content-type': 'application/json'})
        return httpx.Response(200, json=settings)
    original = httpx.AsyncClient
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return original(**kwargs, transport=httpx.MockTransport(handle))
    monkeypatch.setattr(health.httpx, 'AsyncClient', client)
    assert asyncio.run(health.probe_auth('https://auth.example', 'invalid-key' if mode == 'key' else 'anon-key')) is (mode == 'ok')


class Connection:
    def __init__(self, *, deny=False, hang=False):
        self.statements = []
        self.closed = False
        self.deny = deny
        self.hang = hang
        self.started = asyncio.Event()
    def transaction(self):
        return self
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    async def execute(self, statement):
        statement = statement if isinstance(statement, str) else statement.as_string()
        self.statements.append(statement)
        if statement.startswith('set local role'):
            if self.deny:
                raise psycopg.errors.InsufficientPrivilege('secret grant detail')
            self.started.set()
            if self.hang:
                await asyncio.Event().wait()
        return self
    async def fetchone(self):
        return (1,)
    async def close(self):
        self.closed = True


@pytest.mark.parametrize('mode', ['ok', 'credentials', 'grant', 'cancel'])
def test_database_checks_actual_credentials_readonly_role_grants_and_closes(monkeypatch, mode):
    async def scenario():
        connection = Connection(deny=mode == 'grant', hang=mode == 'cancel')
        async def connect(dsn, **kwargs):
            assert dsn == 'restricted-actual-dsn'
            assert 'default_transaction_read_only=on' in kwargs['options']
            assert kwargs['connect_timeout'] == 2
            if mode == 'credentials':
                raise psycopg.OperationalError('secret password authentication failed')
            return connection
        monkeypatch.setattr(health.psycopg.AsyncConnection, 'connect', connect)
        task = asyncio.create_task(health.probe_database('restricted-actual-dsn', ('ledger_executor', 'ledger_workflow_executor')))
        if mode == 'cancel':
            await connection.started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            assert await task is (mode == 'ok')
        assert connection.closed is (mode != 'credentials')
        if mode == 'ok':
            assert connection.statements == ['set transaction read only', 'set local role "ledger_executor"',
                'select 1', 'set local role "ledger_workflow_executor"', 'select 1']
    asyncio.run(scenario())


def test_configuration_uses_effective_fallback_and_never_privileged_database_url(monkeypatch):
    async def scenario():
        seen = []
        async def database(dsn, roles):
            seen.append((dsn, roles))
            await asyncio.sleep(0)
            return bool(dsn)
        monkeypatch.setattr(health, 'probe_database', database)
        env = {'DATABASE_URL': 'privileged-do-not-use', 'TALLI_LEDGER_DATABASE_URL': 'restricted'}
        roles = {'TALLI_LEDGER_DATABASE_URL': ('ledger_executor',), 'TALLI_BANKING_DATABASE_URL': ('banking_executor',)}
        assert await health.configured_readiness(env, roles, auth_required=False)()
        assert seen == [('restricted', ('banking_executor', 'ledger_executor'))]
        seen.clear()
        env['TALLI_BANKING_DATABASE_URL'] = ''  # explicit empty must not fall back
        assert not await health.configured_readiness(env, roles, auth_required=False)()
        assert ('', ('banking_executor',)) in seen
        assert not await health.configured_readiness(env, {}, auth_required=False)()
    asyncio.run(scenario())


def test_default_composition_includes_http_roles_excludes_disabled_workers(monkeypatch):
    captured = {}
    def configured(environment, roles, *, auth_required):
        captured.update(roles=roles, auth=auth_required)
        async def ready():
            return True
        return ready
    monkeypatch.setattr('talli_backend.main.configured_readiness', configured)
    monkeypatch.setenv('TALLI_ANNUAL_BILLING_MODE', 'off')
    create_app()
    assert captured['auth']
    assert set(captured['roles']) == {'TALLI_LEDGER_DATABASE_URL', 'TALLI_COMPANY_ACCESS_DATABASE_URL',
                                     'TALLI_BANKING_DATABASE_URL', 'TALLI_MARKETING_MEASUREMENT_DATABASE_URL'}
    assert 'annual_accounts_filing_workflow_executor' in captured['roles']['TALLI_LEDGER_DATABASE_URL']
    assert 'authority_connections_executor' in captured['roles']['TALLI_LEDGER_DATABASE_URL']
    assert 'marketing_measurement_report_executor' in captured['roles']['TALLI_MARKETING_MEASUREMENT_DATABASE_URL']


def test_injected_marketing_adapter_omits_ambient_marketing_dependency(monkeypatch):
    captured = {}
    def configured(environment, roles, *, auth_required):
        captured.update(roles)
        async def ready():
            return True
        return ready
    monkeypatch.setattr('talli_backend.main.configured_readiness', configured)
    create_app(marketing_measurement_gateway=object())
    assert 'TALLI_MARKETING_MEASUREMENT_DATABASE_URL' not in captured
    assert 'TALLI_LEDGER_DATABASE_URL' in captured


def test_enabled_default_notification_intake_adds_its_actual_dsn(monkeypatch):
    from types import SimpleNamespace
    captured = {}
    def configured(environment, roles, *, auth_required):
        captured.update(roles)
        async def ready():
            return True
        return ready
    monkeypatch.setattr('talli_backend.main.configured_readiness', configured)
    monkeypatch.setattr('talli_backend.main.compose_annual_billing_runtime',
                        lambda: SimpleNamespace(provider=object(), notification_intake=object()))
    create_app()
    assert captured['TALLI_ANNUAL_NOTIFICATION_DATABASE_URL'] == ('annual_notification_executor',)
    assert 'TALLI_ANNUAL_CHECKOUT_RECONCILIATION_DATABASE_URL' not in captured


@pytest.mark.parametrize(('origin', 'key'), [('', 'key'), ('https://auth.example', ''),
    ('http://auth.example', 'key'), ('https://auth.example/path', 'key'), ('https://auth.example', 'bad key')])
def test_missing_or_unsafe_auth_configuration_fails_before_io(origin, key, monkeypatch):
    called = []
    def forbidden(**kwargs):
        called.append(True)
        raise AssertionError('configuration must fail before network I/O')
    monkeypatch.setattr(health.httpx, 'AsyncClient', forbidden)
    assert asyncio.run(health.probe_auth(origin, key)) is False
    assert not called
