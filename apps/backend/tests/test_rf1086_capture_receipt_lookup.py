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


def retained_source(codec, *, version=1):
    """Real frozen pure codecs; source ordinal is independent of wire codec."""
    from datetime import timedelta
    from test_rf1086_year_source import basis, prepare
    from test_rf1086_year_source_v2 import v2_basis, prepare as prepare_v2
    command, context = basis() if codec == 1 else v2_basis('no_activity')
    factory = prepare if codec == 1 else prepare_v2
    source = factory(command, context)
    if version == 2:
        command = replace(command, supersedes_source_id=source.source_id,
            supersedes_source_sha256=source.source_sha256, correction_reason='Correct retained source evidence')
        source = factory(command, context, previous=source,
            source_id=rf.Rf1086YearSourceId(str(uuid4())),
            confirmed_at=source.confirmed_at + timedelta(days=1))
    return source


def retained_source_row(source):
    serializer = rf.serialize_rf1086_year_source if type(source) is rf.Rf1086YearSourceSnapshot else rf.serialize_rf1086_year_source_v2
    return {'id': source.source_id.value, 'company_id': str(source.company_id),
        'income_year': int(source.income_year), 'version': source.version,
        'source_sha256': source.source_sha256, 'actor_id': str(source.confirmed_by.subject),
        'confirmed_at': source.confirmed_at,
        'predecessor_id': source.command.supersedes_source_id.value if source.command.supersedes_source_id else None,
        'predecessor_sha256': source.command.supersedes_source_sha256,
        'correction_reason': source.command.correction_reason,
        'request_sha256': rf.rf1086_year_source_digest(source.command),
        'snapshot_text': serializer(source)}


@pytest.mark.parametrize('codec,version', [(1, 1), (1, 2), (2, 1), (2, 2)])
def test_retained_source_decoder_dispatches_codec_independently_of_ordinal(codec, version):
    source = retained_source(codec, version=version)
    loaded = PostgresShareholderRegisterFilingSession._year_source(retained_source_row(source))
    assert type(loaded) is type(source) and loaded == source
    assert loaded.version == version


@pytest.mark.parametrize('codec', [1, 2])
@pytest.mark.parametrize('field', ['id', 'company_id', 'income_year', 'version', 'source_sha256',
    'actor_id', 'confirmed_at', 'predecessor_id', 'predecessor_sha256', 'correction_reason', 'request_sha256'])
def test_retained_both_codecs_keep_every_stored_row_binding(codec, field):
    from datetime import timedelta
    source = retained_source(codec, version=2)
    row = retained_source_row(source)
    if field in {'id', 'company_id', 'actor_id', 'predecessor_id'}: row[field] = str(uuid4())
    elif field in {'income_year', 'version'}: row[field] += 1
    elif field == 'confirmed_at': row[field] += timedelta(microseconds=1)
    elif field == 'correction_reason': row[field] += ' changed'
    else: row[field] = 'f' * 64
    with pytest.raises(rf.Rf1086YearSourceError, match='rf1086_source_storage_invalid'):
        PostgresShareholderRegisterFilingSession._year_source(row)


@pytest.mark.parametrize('codec', [1, 2])
@pytest.mark.parametrize('mutation', ['unknown', 'other_codec', 'other_record', 'extra', 'missing',
    'duplicate_codec', 'duplicate_snapshot', 'duplicate_nested', 'null', 'array', 'boolean', 'bytes'])
def test_retained_dispatch_never_reconstructs_ambiguous_or_cross_codec_payload(codec, mutation):
    import json
    from talli_backend.adapters.postgres_shareholder_register_filing import _parse_retained_year_source
    text = retained_source_row(retained_source(codec))['snapshot_text']
    raw = json.loads(text)
    if mutation == 'unknown': raw['codec'] = 'rf1086-year-source-v3'
    elif mutation == 'other_codec': raw['codec'] = 'rf1086-year-source-v2' if codec == 1 else 'rf1086-year-source-v1'
    elif mutation == 'other_record': raw['snapshot']['record'] = 'Rf1086YearSourceSnapshotV2' if codec == 1 else 'Rf1086YearSourceSnapshot'
    elif mutation == 'extra': raw['untrusted'] = True
    elif mutation == 'missing': del raw['snapshot']
    if mutation in {'unknown', 'other_codec', 'other_record', 'extra', 'missing'}: text = json.dumps(raw)
    elif mutation == 'duplicate_codec': text = text.replace('"codec":', '"codec":"unknown","codec":', 1)
    elif mutation == 'duplicate_snapshot': text = text.replace('"snapshot":', '"snapshot":null,"snapshot":', 1)
    elif mutation == 'duplicate_nested': text = text.replace('"version":', '"version":999,"version":', 1)
    elif mutation == 'null': text = 'null'
    elif mutation == 'array': text = '[]'
    elif mutation == 'boolean': text = 'true'
    elif mutation == 'bytes': text = text.encode()
    with pytest.raises(rf.Rf1086YearSourceError): _parse_retained_year_source(text)


@pytest.mark.parametrize('codec', [1, 2])
def test_retained_dispatch_preserves_selected_parser_integrity_diagnostic(codec):
    import json
    from talli_backend.adapters.postgres_shareholder_register_filing import _parse_retained_year_source
    raw = json.loads(retained_source_row(retained_source(codec))['snapshot_text'])
    raw['snapshot']['fields']['source_sha256'] = 'f' * 64
    text = json.dumps(raw)
    parser = rf.parse_rf1086_year_source if codec == 1 else rf.parse_rf1086_year_source_v2
    with pytest.raises(rf.Rf1086YearSourceError) as expected: parser(text)
    with pytest.raises(rf.Rf1086YearSourceError) as actual: _parse_retained_year_source(text)
    assert str(actual.value) == str(expected.value)


class RetainedCaptureStore(PostgresShareholderRegisterFilingSession):
    def __init__(self, source, *, replay=True, allowed=True):
        self.source = source
        self.replay = replay
        self.allowed = allowed
        self.statements = []
        self.transactions = []

    @property
    def actor_id(self): return self.source.confirmed_by

    @asynccontextmanager
    async def _transaction(self, *, snapshot=False, read_only=False):
        self.transactions.append((snapshot, read_only))
        yield self

    async def execute(self, sql, parameters):
        self.statements.append((sql, parameters))
        class Cursor:
            def __init__(self, row): self.row = row
            async def fetchone(self): return self.row
        if 'company_access_is_accepted_owner_v1' in sql: return Cursor({'allowed': self.allowed})
        if 'lock_year_source_v1' in sql: return Cursor(None)
        if 'idempotency_key=%s' in sql:
            assert parameters[:3] == (str(self.source.company_id), int(self.source.income_year), str(self.actor_id.subject))
            return Cursor(retained_source_row(self.source) if self.replay else None)
        if 'year_source_heads' in sql: return Cursor(retained_source_row(self.source))
        raise AssertionError('Committed recovery must not inspect time, retain documents, or append: ' + sql)

    async def _retain_source_documents(self, *args):
        raise AssertionError('Committed recovery must not retain new evidence')


@pytest.mark.parametrize('codec,version', [(1, 1), (1, 2), (2, 1), (2, 2)])
@pytest.mark.parametrize('operation', ['lookup', 'record'])
def test_adapter_committed_replay_uses_matching_codec_before_fresh_source_work(codec, version, operation):
    from test_rf1086_year_source import basis
    source = retained_source(codec, version=version)
    store = RetainedCaptureStore(source)
    key = IdempotencyKey('retained-codec-replay-key')
    if operation == 'lookup': result = asyncio.run(store.read_year_source_capture_receipt(source.command, idempotency_key=key))
    else: result = asyncio.run(store.record_year_source(source.command, context=basis()[1], idempotency_key=key))
    assert result == source and type(result) is type(source)
    assert len(store.statements) == 2
    assert store.transactions == [(True, True) if operation == 'lookup' else (False, False)]
    assert store.statements[-1][1][-1] == key.value


@pytest.mark.parametrize('codec', [1, 2])
@pytest.mark.parametrize('operation', ['lookup', 'record'])
def test_adapter_retained_replay_rejects_changed_command_with_original_domain_conflict(codec, operation):
    from test_rf1086_year_source import basis
    source = retained_source(codec)
    store = RetainedCaptureStore(source)
    changed = replace(source.command, case=replace(source.command.case, case_id='changed business request'))
    key = IdempotencyKey('retained-codec-replay-key')
    with pytest.raises(rf.Rf1086YearSourceError, match='rf1086_source_idempotency_conflict'):
        if operation == 'lookup': asyncio.run(store.read_year_source_capture_receipt(changed, idempotency_key=key))
        else: asyncio.run(store.record_year_source(changed, context=basis()[1], idempotency_key=key))
    assert len(store.statements) == 2


def test_adapter_v2_lookup_rechecks_current_owner_before_exposing_retained_key():
    store = RetainedCaptureStore(retained_source(2), allowed=False)
    with pytest.raises(rf.ShareholderRegisterFilingError):
        asyncio.run(store.read_year_source_capture_receipt(store.source.command,
            idempotency_key=IdempotencyKey('retained-codec-replay-key')))
    assert len(store.statements) == 1


def test_fresh_v1_capture_refuses_v2_head_before_clock_document_retention_or_append():
    from test_rf1086_year_source import basis
    source = retained_source(2)
    store = RetainedCaptureStore(source, replay=False)
    command = replace(source.command, supersedes_source_id=source.source_id,
        supersedes_source_sha256=source.source_sha256, correction_reason='Attempted downgrade')
    with pytest.raises(rf.Rf1086YearSourceError, match='rf1086_source_codec_downgrade'):
        asyncio.run(store.record_year_source(command, context=basis()[1],
            idempotency_key=IdempotencyKey('fresh-attempt-after-v2')))
    assert len(store.statements) == 3
    assert 'year_source_heads' in store.statements[-1][0]


def test_retained_v1_preserves_offset_significant_bytes_with_utc_database_time():
    from datetime import timedelta, timezone
    from test_rf1086_year_source import basis, prepare, NOW
    source = prepare(*basis(), confirmed_at=NOW.astimezone(timezone(timedelta(hours=2))))
    row = retained_source_row(source)
    row['confirmed_at'] = source.confirmed_at.astimezone(timezone.utc)
    loaded = PostgresShareholderRegisterFilingSession._year_source(row)
    assert loaded == source
    assert rf.serialize_rf1086_year_source(loaded) == row['snapshot_text']
    assert loaded.confirmed_at.utcoffset() == timedelta(hours=2)


@pytest.mark.parametrize('operation', ['lookup', 'record'])
def test_v2_replay_authenticates_actor_before_any_retained_row_read(operation):
    from test_rf1086_year_source import basis
    source = retained_source(2)
    store = RetainedCaptureStore(source)
    command = replace(source.command, actor_id=replace(source.command.actor_id,
        subject=type(source.command.actor_id.subject)(str(uuid4()))))
    with pytest.raises(rf.ShareholderRegisterFilingError):
        if operation == 'lookup':
            asyncio.run(store.read_year_source_capture_receipt(command,
                idempotency_key=IdempotencyKey('retained-codec-replay-key')))
        else:
            asyncio.run(store.record_year_source(command, context=basis()[1],
                idempotency_key=IdempotencyKey('retained-codec-replay-key')))
    assert store.statements == [] and store.transactions == []


@pytest.mark.parametrize('correction', [False, True])
def test_fresh_adapter_path_still_writes_only_frozen_v1_codec(correction):
    from datetime import timedelta
    from test_rf1086_year_source import basis
    previous = retained_source(1)
    command, context = basis()
    if correction:
        command = replace(command, supersedes_source_id=previous.source_id,
            supersedes_source_sha256=previous.source_sha256, correction_reason='V1 correction remains supported')
    class FreshStore(RetainedCaptureStore):
        saved = None
        retained = False
        async def execute(self, sql, parameters=()):
            class Cursor:
                def __init__(self, row): self.row = row
                async def fetchone(self): return self.row
            if 'year_source_heads' in sql:
                self.statements.append((sql, parameters))
                current = self.saved or (previous if correction else None)
                return Cursor(retained_source_row(current) if current else None)
            if 'clock_timestamp()' in sql:
                self.statements.append((sql, parameters))
                return Cursor({'now': previous.confirmed_at + timedelta(days=1)})
            if 'append_year_source_v1(' in sql:
                self.statements.append((sql, parameters))
                assert self.retained
                self.saved = rf.parse_rf1086_year_source(parameters[10])
                assert type(self.saved) is rf.Rf1086YearSourceSnapshot
                return Cursor(None)
            return await super().execute(sql, parameters)
        async def _retain_source_documents(self, connection, record_type, record_id, documents):
            assert connection is self and record_type == 'rf1086_year_source' and documents == command.documents
            self.retained = True
    store = FreshStore(previous, replay=False)
    result = asyncio.run(store.record_year_source(command, context=context,
        idempotency_key=IdempotencyKey('fresh-v1-still-frozen')))
    assert type(result) is rf.Rf1086YearSourceSnapshot and result.version == (2 if correction else 1)
    assert sum('append_year_source_v1(' in sql for sql, _ in store.statements) == 1
    assert not any('append_year_source_v2' in sql for sql, _ in store.statements)
