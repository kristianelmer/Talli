"""Committed RF captures are observable without repeating source admission."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from talli_backend.adapters.postgres_shareholder_register_filing import PostgresShareholderRegisterFilingSession
from talli_backend.application.shareholder_register_filing_session import ShareholderRegisterFilingAuthenticationError
from talli_backend.application.shareholder_register_source_workflow import ShareholderRegisterSourceWorkflow
from talli_backend.main import create_app
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CorrelationId, IdempotencyKey
from test_shareholder_register_source_api import ApiHarness, BASE, HEADERS, draft
from test_shareholder_register_source_workflow import Harness
from test_rf1086_year_source import ACTOR


@pytest.mark.parametrize('outcome', ['recorded', 'conflict', 'lookup_failure', 'wrong_actor'])
def test_capture_resolves_committed_key_before_mutable_evidence(outcome):
    h = Harness()
    snapshot = h.capture()
    command = h.command
    calls = []
    key = IdempotencyKey('committed-source-capture-001')
    if outcome == 'conflict':
        command = replace(command, case=replace(command.case, case_id='changed-command'))
    actor = replace(ACTOR, subject=type(ACTOR.subject)(str(uuid4()))) if outcome == 'wrong_actor' else ACTOR
    class Session:
        actor_id = actor
        async def read_year_source_capture_receipt(self, candidate, *, idempotency_key):
            calls.append('lookup')
            assert candidate == command and idempotency_key == key
            if outcome == 'lookup_failure':
                raise TimeoutError('receipt lookup unavailable')
            rf.assert_rf1086_year_source_replay(snapshot, candidate)
            return snapshot
        async def record_year_source(self, *args, **kwargs):
            raise AssertionError('A committed replay must not write another source')
    class Factory:
        async def session(self, token):
            calls.append('authenticate')
            assert token == 'verified-token'
            return Session()
    class ForbiddenDependency:
        def __getattr__(self, name):
            raise AssertionError('Capture replay must not refresh current evidence')
    workflow = ShareholderRegisterSourceWorkflow(Factory(), ForbiddenDependency(),
        ForbiddenDependency(), ForbiddenDependency())
    def capture():
        return asyncio.run(workflow.capture_year_source('verified-token', command,
            idempotency_key=key, correlation_id=CorrelationId('capture-replay')))
    if outcome == 'recorded':
        result = capture()
        assert result is snapshot
        assert rf.serialize_rf1086_year_source(result) == rf.serialize_rf1086_year_source(snapshot)
    elif outcome == 'lookup_failure':
        with pytest.raises(TimeoutError, match='receipt lookup unavailable'):
            capture()
    else:
        error = 'rf1086_source_owner_required' if outcome == 'wrong_actor' else 'rf1086_source_idempotency_conflict'
        with pytest.raises(rf.Rf1086YearSourceError, match=error):
            capture()
    assert calls == (['authenticate'] if outcome == 'wrong_actor' else ['authenticate', 'lookup'])


@pytest.mark.parametrize('kind', ['year-sources', 'register-observations'])
def test_lookup_recovers_original_after_changed_current_evidence_without_capture(kind):
    original = ApiHarness(capital=kind == 'register-observations')
    command = original.h.register_command if kind == 'register-observations' else original.h.command
    body = draft(command)
    captured = original.client.post(BASE + '/' + kind, json=body, headers=HEADERS)
    assert captured.status_code == 200
    snapshot = original.h.register_saved[0] if kind == 'register-observations' else original.h.saved[0]
    expected = captured.json()
    # The write committed but its HTTP response was lost. Today's source inputs
    # can now be unavailable or changed, without rewriting that stored success.
    original.h.document_failure = True
    original.h.view = None
    original.h.company.name = 'Changed legal name'
    calls = []
    class Session:
        actor_id = ACTOR
        async def read_year_source_capture_receipt(self, candidate, *, idempotency_key):
            calls.append(('year-sources', idempotency_key.value))
            assert kind == 'year-sources'
            if idempotency_key.value != HEADERS['Idempotency-Key']:return None
            rf.assert_rf1086_year_source_replay(snapshot, candidate)
            return snapshot
        async def read_register_observation_capture_receipt(self, candidate, *, idempotency_key):
            calls.append(('register-observations', idempotency_key.value))
            assert kind == 'register-observations'
            if idempotency_key.value != HEADERS['Idempotency-Key']:return None
            if rf.rf1086_register_observation_request_digest(candidate) != rf.rf1086_register_observation_request_digest(snapshot.command):
                raise rf.Rf1086RegisterObservationError('rf1086_register_idempotency_conflict')
            return snapshot
    class Factory:
        async def session(self, token):
            if token != 'verified-token':raise ShareholderRegisterFilingAuthenticationError()
            return Session()
    class ForbiddenDependency:
        def __getattr__(self, name):
            raise AssertionError('Receipt lookup must not refresh current evidence')
    client = TestClient(create_app(shareholder_register_filing_session_factory=Factory(),
        documents_session_factory=ForbiddenDependency(), company_access_gateway=ForbiddenDependency(),
        corporate_governance_session_factory=ForbiddenDependency()))
    response = client.post(BASE + '/' + kind + '/receipt-lookup', json=body, headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {'status': 'recorded', 'receipt': expected}
    assert response.headers['cache-control'] == 'no-store'
    assert calls == [(kind, HEADERS['Idempotency-Key'])]
    if kind == 'year-sources':
        replay = client.post(BASE + '/' + kind, json=body, headers=HEADERS)
        assert replay.status_code == 200 and replay.json() == expected
        assert calls == [(kind, HEADERS['Idempotency-Key'])] * 2
    missing = client.post(BASE + '/' + kind + '/receipt-lookup', json=body,
        headers={**HEADERS, 'Idempotency-Key': str(uuid4())})
    assert missing.json() == {'status': 'not_observed', 'receipt': None}
    changed = {**body, 'case': {**body['case'], 'case_id': 'different-original-request'}} if kind == 'year-sources' else body
    if kind == 'register-observations':
        changed = {**body, 'effective_at': command.effective_at.replace(day=2).isoformat()}
    conflict = client.post(BASE + '/' + kind + '/receipt-lookup', json=changed, headers=HEADERS)
    assert conflict.status_code == 409
    assert 'idempotency_conflict' in conflict.json()['code']
    assert conflict.headers['cache-control'] == 'no-store'
    assert client.post(BASE + '/' + kind + '/receipt-lookup', json=body,
        headers={'Idempotency-Key': HEADERS['Idempotency-Key']}).status_code == 401
    assert client.post(BASE + '/' + kind + '/receipt-lookup', json=body,
        headers={'Authorization': HEADERS['Authorization']}).status_code == 422
    assert client.post(BASE + '/' + kind + '/receipt-lookup', json=body,
        headers={**HEADERS, 'Authorization': 'Bearer invalid'}).status_code == 401
    assert client.post(BASE + '/' + kind + '/receipt-lookup', json={**body, 'actorId': str(ACTOR.subject)}, headers=HEADERS).status_code == 422
    assert len(original.h.register_saved if kind == 'register-observations' else original.h.saved) == 1


@pytest.mark.parametrize('kind', ['year-sources', 'register-observations'])
def test_adapter_lookup_scope_readonly_integrity_and_current_owner(kind):
    api = ApiHarness(capital=kind == 'register-observations')
    command = api.h.register_command if kind == 'register-observations' else api.h.command
    response = api.client.post(BASE + '/' + kind, json=draft(command), headers=HEADERS)
    assert response.status_code == 200
    snapshot = api.h.register_saved[0] if kind == 'register-observations' else api.h.saved[0]
    key = IdempotencyKey(HEADERS['Idempotency-Key'])
    statements = []
    allowed = True
    row = {'request_sha256': rf.rf1086_register_observation_request_digest(command) if kind == 'register-observations'
           else rf.rf1086_year_source_digest(command)}
    class Cursor:
        def __init__(self, value):self.value = value
        async def fetchone(self):return self.value
    class Connection:
        async def execute(self, sql, parameters):
            statements.append((sql, parameters))
            if 'company_access_is_accepted_owner_v1' in sql:return Cursor({'allowed': allowed})
            assert parameters == (str(command.company_id), int(command.income_year), str(ACTOR.subject), key.value)
            assert 'and actor_id=%s::uuid and idempotency_key=%s' in sql
            return Cursor(row)
    class Store(PostgresShareholderRegisterFilingSession):
        @property
        def actor_id(self):return ACTOR
        @asynccontextmanager
        async def _transaction(self, *, snapshot=False, read_only=False):
            assert snapshot is True and read_only is True
            yield Connection()
        def _year_source(self, value):return snapshot
        def _register_observation(self, value):return snapshot
    store = object.__new__(Store)
    operation = store.read_register_observation_capture_receipt if kind == 'register-observations' else store.read_year_source_capture_receipt
    assert asyncio.run(operation(command, idempotency_key=key)) == snapshot
    assert len(statements) == 2
    assert all(statement.startswith('select ') for statement, _ in statements)
    allowed = False
    with pytest.raises(rf.ShareholderRegisterFilingError):
        asyncio.run(operation(command, idempotency_key=key))
    assert len(statements) == 3  # no key existence query for unauthorized scope
