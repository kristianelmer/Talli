from __future__ import annotations

import asyncio
import json

from talli_backend.adapters.supabase_investments import SupabaseInvestmentsTransaction
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.modules.investments.public import AccountingEntryReference

from test_investments import supported_sale


def bound_transaction() -> SupabaseInvestmentsTransaction:
    command = supported_sale()
    return SupabaseInvestmentsTransaction(
        "postgresql://unused",
        _VerifiedActor(
            actor_id=command.actor_id,
            claims_json=(
                '{"sub":"20000000-0000-0000-0000-000000000002",'
                '"role":"authenticated","aal":"aal2"}'
            ),
        ),
        None,  # type: ignore[arg-type]
    )


def test_share_sale_uses_only_the_private_investments_workflow_rpcs() -> None:
    transaction = bound_transaction()
    command = supported_sale()
    calls: list[tuple[str, tuple[object, ...]]] = []
    responses = iter(
        [
            {"result": None},
            {
                "result": {
                    "positionId": str(command.position_id),
                    "investmentName": "Example AS",
                    "fifoCostBasisReduction": "50.20",
                }
            },
            {
                "result": {
                    "actionId": str(command.action_id),
                    "positionId": str(command.position_id),
                    "accountingEntryId": "70000000-0000-0000-0000-000000000007",
                    "replayed": False,
                }
            },
        ]
    )

    async def database_rows(
        query: str, parameters: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        calls.append((query, parameters))
        return [next(responses)]

    transaction._database_rows = database_rows  # type: ignore[method-assign]

    replay = asyncio.run(transaction.get_share_sale_replay(command))
    prepared = asyncio.run(transaction.prepare_share_sale(command))
    recorded = asyncio.run(
        transaction.complete_share_sale(
            command,
            accounting_entry_id=AccountingEntryReference(
                "70000000-0000-0000-0000-000000000007"
            ),
        )
    )

    assert replay is None
    assert prepared.investment_name == "Example AS"
    assert format(prepared.fifo_cost_basis_reduction.amount, "f") == "50.20"
    assert recorded.position_id == command.position_id
    assert "get_share_sale_replay_v1" in calls[0][0]
    assert "prepare_share_sale_v1" in calls[1][0]
    assert "complete_share_sale_v1" in calls[2][0]
    request = json.loads(str(calls[1][1][0]))
    assert request == {
        "companyId": str(command.company_id),
        "incomeYear": 2026,
        "actionId": str(command.action_id),
        "idempotencyKey": str(command.idempotency_key),
        "correlationId": str(command.correlation_id),
        "positionId": str(command.position_id),
        "saleDate": "2026-06-01",
        "soldShareCount": 4,
        "proceeds": "75.00",
        "bankTransactionId": None,
        "documentId": None,
        "documentStatus": "not_required",
    }
