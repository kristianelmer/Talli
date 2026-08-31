from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime

from talli_backend.adapters.supabase_investments import (
    SupabaseInvestmentsSession,
    SupabaseInvestmentsTransaction,
)
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.modules.investments.public import (
    AccountingEntryReference,
    PreparedReceivedDividend,
)
from talli_backend.shared.kernel import Money

from test_investments import supported_received_dividend, supported_sale


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


def test_received_dividend_uses_only_the_private_investments_workflow_rpcs() -> None:
    transaction = bound_transaction()
    command = supported_received_dividend()
    calls: list[tuple[str, tuple[object, ...]]] = []
    responses = iter(
        [
            {"result": None},
            {
                "result": {
                    "positionId": str(command.position_id),
                    "investmentName": "Example AS",
                    "payingCompanyName": "Example AS",
                    "taxableAddBack": "3.77",
                }
            },
            {
                "result": {
                    "actionId": str(command.action_id),
                    "positionId": str(command.position_id),
                    "accountingEntryId": "70000000-0000-0000-0000-000000000007",
                    "taxableAddBack": "3.77",
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

    replay = asyncio.run(transaction.get_received_dividend_replay(command))
    prepared = asyncio.run(
        transaction.prepare_received_dividend(
            command, taxable_add_back=Money.nok("3.77")
        )
    )
    recorded = asyncio.run(
        transaction.complete_received_dividend(
            command,
            prepared=PreparedReceivedDividend(
                position_id=command.position_id,
                investment_name="Example AS",
                paying_company_name="Example AS",
                taxable_add_back=Money.nok("3.77"),
            ),
            accounting_entry_id=AccountingEntryReference(
                "70000000-0000-0000-0000-000000000007"
            ),
        )
    )

    assert replay is None
    assert prepared.taxable_add_back == Money.nok("3.77")
    assert recorded.taxable_add_back == Money.nok("3.77")
    assert "get_received_dividend_replay_v1" in calls[0][0]
    assert "prepare_received_dividend_v1" in calls[1][0]
    assert "complete_received_dividend_v1" in calls[2][0]
    request = json.loads(str(calls[1][1][0]))
    assert request == {
        "companyId": str(command.company_id),
        "incomeYear": 2026,
        "actionId": str(command.action_id),
        "idempotencyKey": str(command.idempotency_key),
        "correlationId": str(command.correlation_id),
        "positionId": str(command.position_id),
        "payingCompanyName": "  Example AS  ",
        "declaredDate": "2026-04-01",
        "paidDate": "2026-04-15",
        "grossAmount": "125.50",
        "taxTreatment": "fritaksmetoden",
        "bankTransactionId": None,
        "documentId": None,
        "documentStatus": "not_required",
        "taxableAddBack": "3.77",
    }


def test_canonical_activity_and_allocations_map_every_archive_fact() -> None:
    command = supported_received_dividend()
    session = SupabaseInvestmentsSession(
        "postgresql://unused",
        _VerifiedActor(
            actor_id=command.actor_id,
            claims_json=(
                '{"sub":"20000000-0000-0000-0000-000000000002",'
                '"role":"authenticated","aal":"aal2"}'
            ),
        ),
    )
    queries: list[str] = []
    activity_id = "30000000-0000-0000-0000-000000000003"
    allocation_id = "40000000-0000-0000-0000-000000000004"
    lot_id = "50000000-0000-0000-0000-000000000005"

    async def activity_rows(
        query: str, parameters: tuple[object, ...]
    ) -> list[dict[str, object]]:
        queries.append(query)
        return [{
            "id": activity_id,
            "company_id": str(command.company_id),
            "income_year": 2026,
            "activity_kind": "dividend_received",
            "action_date": date(2026, 4, 15),
            "position_id": str(command.position_id),
            "investment_key": "org:123456789",
            "investment_name": "Example AS",
            "investment_kind": "norwegian_private_company",
            "tax_treatment": "fritaksmetoden",
            "org_number": "123456789",
            "acquisition_lot_id": None,
            "share_count": None,
            "purchase_amount": None,
            "sold_share_count": None,
            "proceeds": None,
            "fifo_cost_basis_reduction": None,
            "remaining_share_count": None,
            "remaining_cost_basis": None,
            "paying_company_name": "Example AS",
            "declared_date": date(2026, 4, 1),
            "gross_amount": "125.50",
            "taxable_add_back": "3.77",
            "gain_or_loss": None,
            "bank_transaction_id": "80000000-0000-0000-0000-000000000008",
            "document_id": "90000000-0000-0000-0000-000000000009",
            "document_status": "attached",
            "accounting_entry_id": "70000000-0000-0000-0000-000000000007",
            "created_by": str(command.actor_id.subject),
            "created_at": datetime(2026, 4, 15, 12, tzinfo=UTC),
        }]

    session._query_rows = activity_rows  # type: ignore[method-assign]
    activity = asyncio.run(session.list_activity(
        actor_id=command.actor_id,
        company_ids=(command.company_id,),
        correlation_id=command.correlation_id,
        cursor=None,
        limit=100,
    ))
    item = activity.items[0]
    assert item.activity_id.value == activity_id
    assert item.gross_amount == Money.nok("125.50")
    assert item.taxable_add_back == Money.nok("3.77")
    assert str(item.bank_transaction_id) == "80000000-0000-0000-0000-000000000008"
    assert "investments.received_dividends" in queries[0]
    assert "holding_actions" not in queries[0]

    async def allocation_rows(
        query: str, parameters: tuple[object, ...]
    ) -> list[dict[str, object]]:
        queries.append(query)
        return [{
            "id": allocation_id,
            "company_id": str(command.company_id),
            "position_id": str(command.position_id),
            "lot_id": lot_id,
            "sale_action_id": activity_id,
            "allocation_order": 1,
            "acquisition_date": date(2026, 1, 5),
            "allocated_share_count": 4,
            "allocated_cost_basis": "50.20",
            "created_by": str(command.actor_id.subject),
            "created_at": datetime(2026, 6, 1, 12, tzinfo=UTC),
        }]

    session._query_rows = allocation_rows  # type: ignore[method-assign]
    allocations = asyncio.run(session.list_share_sale_allocations(
        actor_id=command.actor_id,
        company_ids=(command.company_id,),
        correlation_id=command.correlation_id,
        cursor=None,
        limit=100,
    ))
    allocation = allocations.items[0]
    assert allocation.allocation_id.value == allocation_id
    assert allocation.lot_id.value == lot_id
    assert allocation.allocation_order == 1
    assert allocation.allocated_cost_basis == Money.nok("50.20")
    assert "acquisition_lot_id as lot_id" in queries[1]
