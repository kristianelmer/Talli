"""Atomic owner lifecycle reads preserve history; they do not authorize mutations."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId, IncomeYear, Timestamp
from test_shareholder_register_source_api import ApiHarness, BASE, HEADERS
from test_shareholder_register_observation_read import capture, listing, observation_row
from test_rf1086_year_source import COMPANY, YEAR, NOW


def lifecycle(api, **scope):
    return api.client.get(BASE + '/register-observations/lifecycle', params={
        'companyId': str(COMPANY), 'incomeYear': int(YEAR), **scope}, headers=HEADERS)


def withdraw(observation):
    return rf.prepare_rf1086_register_observation_withdrawal(rf.WithdrawRf1086RegisterObservation(
        observation.command.company_id, observation.command.actor_id, observation.command.income_year,
        observation.observation_id, observation.version, observation.fact_sha256, '  Feil original – behold teksten.\n'),
        observation=observation, withdrawal_id=rf.Rf1086RegisterObservationWithdrawalId(str(uuid4())),
        withdrawn_at=observation.confirmed_at + timedelta(seconds=3, microseconds=123456))


def test_empty_lifecycle_is_scoped_no_store_and_does_not_reverify_originals():
    api = ApiHarness(capital=True)
    response = lifecycle(api)
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert response.json() == {'companyId': str(COMPANY), 'incomeYear': int(YEAR),
        'observedAt': NOW.isoformat().replace('+00:00', 'Z'), 'observations': []}
    assert 'verify_document' not in api.h.calls


def test_withdrawn_head_does_not_reactivate_ancestor_or_hide_independent_root():
    api = ApiHarness(capital=True)
    original = capture(api)
    body = listing(api).json()['observations'][0]['draft']
    body.update(completeRegisterConfirmed=True, registrationConfirmed=True, singleShareClassConfirmed=True,
                correctionReason='Correct original name')
    corrected = capture(api, body)
    independent = capture(api)
    api.withdrawals = (withdraw(api.h.register_saved[1]),)
    retained = tuple(api.h.register_saved)
    api.h.calls.clear(); api.h.document_failure = True
    response = lifecycle(api)
    assert response.status_code == 200, response.text
    rows = {row['receipt']['observationId']: row for row in response.json()['observations']}
    assert rows[original['observationId']]['status'] == 'superseded'
    assert rows[original['observationId']]['supersededBy'] == corrected['observationId']
    row = rows[corrected['observationId']]
    assert row['status'] == 'withdrawn' and row['supersededBy'] is None
    assert row['withdrawal'] == {'withdrawalId': api.withdrawals[0].withdrawal_id.value,
        'withdrawnAt': api.withdrawals[0].withdrawn_at.isoformat().replace('+00:00', 'Z'),
        'reason': api.withdrawals[0].command.reason, 'withdrawalSha256': api.withdrawals[0].withdrawal_sha256}
    assert rows[independent['observationId']]['status'] == 'active'
    assert row['receipt'] == corrected and row['draft']['supersedesObservationSha256'] == corrected['factSha256']
    assert not row['draft']['completeRegisterConfirmed'] and not row['draft']['registrationConfirmed']
    assert tuple(api.h.register_saved) == retained and 'verify_document' not in api.h.calls
    assert all(secret not in response.text for secret in ('actorId', 'snapshot_text', 'idempotency', 'requestSha256'))
    old = listing(api)
    assert old.status_code == 409 and old.json()['code'] == 'rf1086_register_lifecycle_upgrade_required'
    assert old.headers['cache-control'] == 'no-store'
    assert listing(api, incomeYear=int(YEAR)+1).json()['observations'] == []


@pytest.mark.parametrize('change', ['reviewer', 'revoked', 'unconfirmed', 'unlocked', 'other_company'])
def test_lifecycle_requires_current_eligible_owner_before_history(change):
    api = ApiHarness(capital=True)
    scope = {}
    if change == 'reviewer': api.h.company.role = 'reviewer'
    if change == 'revoked': api.auth_failure = True
    if change == 'unconfirmed': api.h.company.identity_confirmed_at = None
    if change == 'unlocked': api.h.company.identity_locked_at = None
    if change == 'other_company': scope['companyId'] = str(uuid4())
    assert lifecycle(api, **scope).status_code in (401, 403, 404)
    assert 'list_observations' not in api.h.calls


@pytest.mark.parametrize('change', ['scope', 'status', 'missing_withdrawal', 'duplicate', 'observed_before_receipt'])
def test_workflow_rejects_malformed_lifecycle_port_projection(change):
    api = ApiHarness(capital=True); capture(api)
    observation = api.h.register_saved[0]; receipt = withdraw(observation)
    rows = rf.derive_rf1086_register_observation_lifecycle(company_id=COMPANY, income_year=YEAR,
        observations=(observation,), withdrawals=(receipt,))
    snapshot = rf.Rf1086RegisterObservationLifecycleSnapshot(COMPANY, YEAR, Timestamp(receipt.withdrawn_at), rows)
    if change == 'scope': snapshot = replace(snapshot, company_id=CompanyId(str(uuid4())))
    if change == 'status': snapshot = replace(snapshot, observations=(replace(rows[0], status='active'),))
    if change == 'missing_withdrawal': snapshot = replace(snapshot, observations=(replace(rows[0], withdrawal=None),))
    if change == 'duplicate': snapshot = replace(snapshot, observations=rows+rows)
    if change == 'observed_before_receipt': snapshot = replace(snapshot, observed_at=Timestamp(observation.confirmed_at))
    api.lifecycle_snapshot = snapshot
    response = lifecycle(api)
    assert response.status_code == 503 and response.json()['code'] == 'rf1086_register_storage_invalid'


def withdrawal_row(receipt):
    command = receipt.command
    return dict(id=receipt.withdrawal_id.value, company_id=str(command.company_id), income_year=int(command.income_year),
        actor_id=str(command.actor_id.subject), observation_id=command.observation_id.value,
        observation_version=command.observation_version, observation_fact_sha256=command.observation_fact_sha256,
        reason=command.reason, request_sha256=receipt.request_sha256, withdrawal_sha256=receipt.withdrawal_sha256,
        withdrawn_at=receipt.withdrawn_at, snapshot_text=rf.serialize_rf1086_register_observation_withdrawal(receipt))


def adapter(observations, withdrawals=(), *, allowed=True, counts=None):
    from test_postgres_shareholder_register_filing import session
    store = session({}); queries = []; transactions = []
    tables = {'register_observations': list(observations), 'register_observation_withdrawals': list(withdrawals)}
    class Cursor:
        def __init__(self, result): self.result = result
        async def fetchone(self): return self.result
        async def fetchall(self): return self.result
    class Connection:
        async def execute(self, statement, parameters):
            queries.append((statement, parameters))
            if 'accepted_owner' in statement: return Cursor({'allowed': allowed})
            if 'clock_timestamp' in statement: return Cursor({'observed_at': NOW + timedelta(days=30)})
            table = next(name for name in tables if f'.{name} ' in statement)
            if statement.startswith('select count'): return Cursor({'count': (counts or {}).get(table, len(tables[table]))})
            return Cursor(tables[table])
    @asynccontextmanager
    async def transaction(*, snapshot=False):
        transactions.append(snapshot); yield Connection()
    store._transaction = transaction
    return store, queries, transactions


def read_adapter(store):
    return asyncio.run(store.read_register_observation_lifecycle_snapshot(rf.Rf1086SourceQuery(COMPANY, YEAR, store.actor_id)))


def test_adapter_uses_one_snapshot_owner_scope_counts_and_verified_retained_rows():
    api = ApiHarness(capital=True); capture(api); original = api.h.register_saved[0]; receipt = withdraw(original)
    store, queries, transactions = adapter([observation_row(original)], [withdrawal_row(receipt)])
    snapshot = read_adapter(store)
    assert transactions == [True] and snapshot.observations[0].observation == original
    assert snapshot.observations[0].withdrawal == receipt and snapshot.observations[0].status == 'withdrawn'
    assert len(queries) == 6 and 'accepted_owner' in queries[0][0]
    for statement, parameters in queries[1:5]:
        assert parameters == (str(COMPANY), int(YEAR)) and 'where company_id=%s::uuid and income_year=%s' in statement


@pytest.mark.parametrize('change', ['row_hash', 'row_actor', 'target', 'snapshot_text', 'observation_digest',
    'missing_target', 'duplicate_withdrawal', 'count_observations', 'count_withdrawals', 'boolean_count', 'owner'])
def test_adapter_fails_closed_for_incomplete_corrupt_or_unauthorized_read(change):
    api = ApiHarness(capital=True); capture(api); original = api.h.register_saved[0]; receipt = withdraw(original)
    observations = [observation_row(original)]; withdrawals = [withdrawal_row(receipt)]; counts = {}
    if change == 'row_hash': withdrawals[0]['withdrawal_sha256'] = 'e'*64
    if change == 'row_actor': withdrawals[0]['actor_id'] = str(uuid4())
    if change == 'target': withdrawals[0]['observation_id'] = str(uuid4())
    if change == 'snapshot_text': withdrawals[0]['snapshot_text'] = '{}'
    if change == 'observation_digest': observations[0]['fact_sha256'] = 'f'*64
    if change == 'missing_target': observations = []
    if change == 'duplicate_withdrawal': withdrawals *= 2
    if change == 'count_observations': counts['register_observations'] = 2
    if change == 'count_withdrawals': counts['register_observation_withdrawals'] = 0
    if change == 'boolean_count': counts['register_observation_withdrawals'] = True
    store, queries, _ = adapter(observations, withdrawals, counts=counts, allowed=change != 'owner')
    with pytest.raises(rf.ShareholderRegisterFilingError): read_adapter(store)
    if change == 'owner': assert len(queries) == 1


def test_superseded_row_with_withdrawal_metadata_is_unavailable_not_legacy_success():
    api = ApiHarness(capital=True); capture(api)
    original = api.h.register_saved[0]
    body = listing(api).json()['observations'][0]['draft']
    body.update(completeRegisterConfirmed=True, registrationConfirmed=True, singleShareClassConfirmed=True,
                correctionReason='Correction')
    capture(api, body); head = api.h.register_saved[-1]
    rows = rf.derive_rf1086_register_observation_lifecycle(company_id=COMPANY, income_year=YEAR,
        observations=(original, head), withdrawals=())
    receipt = withdraw(original)
    rows = tuple(replace(row, withdrawal=receipt) if row.observation == original else row for row in rows)
    api.lifecycle_snapshot = rf.Rf1086RegisterObservationLifecycleSnapshot(COMPANY, YEAR, Timestamp(receipt.withdrawn_at), rows)
    assert listing(api).status_code == 503 and lifecycle(api).status_code == 503


@pytest.mark.parametrize('read_kind', ['source_readiness', 'annual_readiness', 'review'])
def test_withdrawn_current_reference_stops_application_readiness_before_annual_or_review_work(read_kind, monkeypatch):
    import test_rf1086_source_admission as admission_fixture
    from test_shareholder_register_capital_source_workflow import setup, prepare_capital
    from test_rf1086_source_approval import ApprovalHarness, ENTITLEMENT
    from talli_backend.shared.kernel import CorrelationId
    def capital_harness(_kind):
        h = setup(); prepare_capital(h); return h
    monkeypatch.setattr(admission_fixture, 'Harness', capital_harness)
    h = ApprovalHarness()
    retained = h.source_harness.observation
    receipt = withdraw(retained)
    async def current(query, observation_id):
        assert h.held and observation_id == retained.observation_id
        h.calls.append('register')
        rows = rf.derive_rf1086_register_observation_lifecycle(company_id=query.company_id, income_year=query.income_year,
            observations=(retained,), withdrawals=(receipt,))
        return next((row.observation for row in rows if row.status == 'active'), None)
    h.transaction.read_current_register_observation = current
    args = dict(company_id=COMPANY, income_year=YEAR, preview_id=h.preview.preview_id,
        correlation_id=CorrelationId('withdrawal-read-proof'))
    call = h.approval.read_review('token', entitlement_id=ENTITLEMENT, **args) if read_kind == 'review' else (
        h.workflow.read_readiness('token', **args) if read_kind == 'source_readiness' else h.workflow.read_annual_readiness('token', **args))
    with pytest.raises(rf.Rf1086YearSourceError, match='independent_register_unavailable'):
        asyncio.run(call)
    assert not h.committed and not h.held and not h.writes
    assert 'register' in h.calls and 'bridge' not in h.calls and 'review' not in h.calls
    assert h.source_harness.observation == retained


@pytest.mark.parametrize('read_kind', ['generate', 'read'])
def test_withdrawal_invalidates_source_preview_without_deleting_captured_facts(read_kind):
    from test_shareholder_register_capital_source_workflow import setup, prepare_capital
    from test_shareholder_register_source_preview_workflow import preview
    from talli_backend.shared.kernel import CorrelationId
    h = setup(); prepare_capital(h); source = h.capture(); prior_preview = preview(h)
    retained = h.observation; receipt = withdraw(retained)
    # This authenticated port returns no active row, while immutable facts survive.
    h.observation = None
    if read_kind == 'generate':
        with pytest.raises(rf.Rf1086YearSourceError, match='independent_register_unavailable'): preview(h)
    else:
        session_factory = h.workflow._rf_sessions
        class Sessions:
            async def session(self, token):
                session = await session_factory.session(token)
                async def source_preview(preview_id): return prior_preview
                session.source_preview = source_preview
                return session
        h.workflow._rf_sessions = Sessions()
        with pytest.raises(rf.Rf1086YearSourceError, match='independent_register_unavailable'):
            asyncio.run(h.workflow.read_source_preview('token', company_id=COMPANY, income_year=YEAR,
                preview_id=prior_preview.preview_id, correlation_id=CorrelationId('withdrawn-preview')))
    assert h.saved == [source] and h.previews == [prior_preview]
    assert receipt.command.observation_fact_sha256 == retained.fact_sha256


def test_missing_withdrawal_schema_is_safe_unavailable_through_real_transaction_and_both_routes(monkeypatch):
    from psycopg.errors import UndefinedTable
    from test_postgres_shareholder_register_filing import session
    store = session({})
    store._configuration = replace(store._configuration, database_url='postgresql://synthetic.invalid/never-contacted')
    statements = []
    class Connection:
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): return False
        def transaction(self): return self
        async def execute(self, statement, parameters=None):
            statements.append(statement)
            if 'register_observation_withdrawals' in statement:
                raise UndefinedTable('private_schema_detail_should_not_escape')
            return self
        async def fetchone(self): return {'allowed': True, 'count': 0}
        async def fetchall(self): return []
    async def connect(*_args, **_kwargs): return Connection()
    monkeypatch.setattr('talli_backend.adapters.postgres_shareholder_register_filing.psycopg.AsyncConnection.connect', connect)
    with pytest.raises(rf.ShareholderRegisterFilingError) as failure: read_adapter(store)
    assert failure.value.code == rf.ShareholderRegisterFilingError.unavailable().code
    assert 'private_schema_detail' not in str(failure.value)
    assert any('repeatable read' in statement for statement in statements)
    api = ApiHarness(capital=True); api.persistence_error = failure.value
    for response in (lifecycle(api), listing(api)):
        assert response.status_code == 503 and response.headers['cache-control'] == 'no-store'
        assert 'private_schema_detail' not in response.text
