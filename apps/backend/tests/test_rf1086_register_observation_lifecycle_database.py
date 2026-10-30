"""Lifecycle enumeration on actual restricted RF connections, with staged fixture-only withdrawal authority."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from uuid import uuid4

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import IdempotencyKey, IncomeYear
from test_annual_purchase_basis_runtime import admitted
from test_rf1086_database_runtime import backend_url, rf_fixture_admin_access
from test_rf1086_year_source_database import session
from test_rf1086_register_observation_database import cleanup_owned_fixture, capture, correction, query
from test_rf1086_register_observation_withdrawal_database import staged, observed, withdraw

pytestmark = pytest.mark.authority_database


def read(staged, **scope):
    return asyncio.run(staged['store'].read_register_observation_lifecycle_snapshot(
        replace(query(staged['command']), **scope)))


def test_restricted_lifecycle_preserves_withdrawn_head_superseded_ancestor_and_independent_root(staged):
    original = observed(staged)
    head_command = correction(staged['command'], original); key = IdempotencyKey(str(uuid4()))
    head = capture(staged['store'], head_command, staged['context'], key)
    independent = observed(staged)
    receipt = rf.parse_rf1086_register_observation_withdrawal(withdraw(staged, head))
    snapshot = read(staged)
    rows = {row.observation.observation_id: row for row in snapshot.observations}
    assert len(rows) == 3
    assert rows[original.observation_id].status == 'superseded'
    assert rows[original.observation_id].superseded_by == head.observation_id
    assert rows[head.observation_id].status == 'withdrawn' and rows[head.observation_id].withdrawal == receipt
    assert rows[independent.observation_id].status == 'active'
    assert snapshot.observed_at.value >= receipt.withdrawn_at
    assert read(staged, income_year=IncomeYear(int(staged['command'].income_year)+1)).observations == ()
    assert asyncio.run(staged['store'].read_register_observation(query(staged['command']), head.observation_id)) == head
    assert asyncio.run(staged['store'].read_register_observation_capture_receipt(head_command, idempotency_key=key)) == head
    assert capture(staged['store'], head_command, staged['context'], key) == head


def test_current_owner_check_prevents_rls_empty_success_for_outsider(staged):
    observed(staged)
    outsider = session(staged['seed'], staged['backend_url'], staged['seed']['outsider'])
    with pytest.raises(rf.ShareholderRegisterFilingError):
        asyncio.run(outsider.read_register_observation_lifecycle_snapshot(
            replace(query(staged['command']), actor_id=outsider.actor_id)))


def test_withdrawal_committed_between_enumerations_is_visible_only_in_next_snapshot(staged):
    original = observed(staged)
    store = staged['store']; transaction = store._transaction; committed = []
    class InterposedConnection:
        def __init__(self, connection): self.connection = connection
        async def execute(self, statement, parameters):
            if statement.startswith('select * from shareholder_register_filing.register_observation_withdrawals '):
                committed.append(await asyncio.to_thread(withdraw, staged, original))
            return await self.connection.execute(statement, parameters)
    @asynccontextmanager
    async def interposed(*, snapshot=False):
        assert snapshot
        async with transaction(snapshot=snapshot) as connection:
            yield InterposedConnection(connection)
    store._transaction = interposed
    try:
        before = read(staged)
    finally:
        store._transaction = transaction
    assert len(committed) == 1 and before.observations[0].status == 'active'
    after = read(staged)
    assert after.observations[0].status == 'withdrawn'
    assert after.observations[0].withdrawal == rf.parse_rf1086_register_observation_withdrawal(committed[0])
