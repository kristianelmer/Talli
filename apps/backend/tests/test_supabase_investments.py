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
    RecordedReceivedDividend,
)
from talli_backend.modules.investments.service import InvestmentsService
from talli_backend.shared.kernel import Money

from test_investments import (
    supported_investment_correction,
    supported_received_dividend,
    supported_received_fund_distribution,
    supported_sale,
)


def test_correction_uses_private_prepare_link_and_complete_rpcs() -> None:
    transaction = bound_transaction()
    command = supported_investment_correction()
    replacement = command.replacement
    calls: list[tuple[str, tuple[object, ...]]] = []
    responses = iter([
        {"result": None},
        {"result": {
            "originalAccountingEntryId": "70000000-0000-0000-0000-000000000017",
            "originalPositionId": str(replacement.position_id),
        }},
        {"reversal_entry_id": "70000000-0000-0000-0000-000000000027"},
        {"result": {
            "correctionId": str(command.correction_id),
            "originalActionId": str(command.original_action_id),
            "replacementActionId": str(replacement.action_id),
            "reversalAccountingEntryId": "70000000-0000-0000-0000-000000000027",
            "replacementAccountingEntryId": "70000000-0000-0000-0000-000000000037",
            "replayed": False,
        }},
    ])

    async def database_rows(
        query: str, parameters: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        calls.append((query, parameters))
        return [next(responses)]

    transaction._database_rows = database_rows  # type: ignore[method-assign]
    replay = asyncio.run(transaction.get_investment_correction_replay(command))
    prepared = asyncio.run(
        InvestmentsService(transaction).prepare_investment_correction(command)
    )
    recorded = asyncio.run(transaction.complete_investment_correction(
        command,
        prepared=prepared,
        replacement=RecordedReceivedDividend(
            action_id=replacement.action_id,
            position_id=replacement.position_id,
            accounting_entry_id=AccountingEntryReference(
                "70000000-0000-0000-0000-000000000037"
            ),
            taxable_add_back=Money.nok("3.90"),
            replayed=False,
        ),
    ))

    assert replay is None
    assert recorded.correction_id == command.correction_id
    assert "get_correction_replay_v1" in calls[0][0]
    assert "prepare_correction_v1" in calls[1][0]
    assert "link_investment_correction_v1" in calls[2][0]
    assert "complete_correction_v1" in calls[3][0]
    request = json.loads(str(calls[1][1][0]))
    assert request["originalActivityKind"] == "dividend_received"
    assert request["replacementActivityKind"] == "dividend_received"
    assert request["replacement"]["grossAmount"] == "130.00"
    assert request["evidenceDigest"] == prepared.evidence_digest
    assert calls[2][1][2] == str(prepared.original_accounting_entry_id)


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
                    "investmentKind": "norwegian_private_company",
                    "accountingClassification": "other_long_term",
                    "fifoBookCostBasisReduction": "50.20",
                    "fifoTaxBasisReduction": "50.20",
                    "lotFacts": [{
                        "lotId": "60000000-0000-0000-0000-000000000006",
                        "allocationOrder": 1,
                        "acquisitionDate": date(2026, 4, 15),
                        "allocatedShareCount": 4,
                        "allocatedBookCostBasis": "50.20",
                        "allocatedTaxBasis": "50.20",
                        "acquisitionYearFundEquityRatioBasisPoints": None,
                    }],
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
    prepared = asyncio.run(InvestmentsService(transaction).prepare_share_sale(command))
    recorded = asyncio.run(
        transaction.complete_share_sale(
            command,
            prepared=prepared,
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
        "transactionCosts": "0.00",
        "saleYearFundEquityRatioBasisPoints": None,
        "fundTaxStatementReference": None,
        "evidenceMode": "manual_fallback",
        "evidenceReference": "broker-note-example-sale",
        "ownerAttested": True,
        "bankTransactionId": None,
        "documentId": None,
        "documentStatus": "missing_accepted_warning",
        "netProceeds": "75.00",
        "evidenceDigest": prepared.evidence_digest,
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
                    "investmentKind": "norwegian_private_company",
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
        InvestmentsService(transaction).prepare_received_dividend(command)
    )
    recorded = asyncio.run(
        transaction.complete_received_dividend(
            command,
            prepared=prepared,
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
        "payingCompanyName": "Example AS",
        "declaredDate": "2026-04-01",
        "paidDate": "2026-04-15",
        "grossAmount": "125.50",
        "taxTreatment": "fritaksmetoden",
        "lawfulDividendConfirmed": True,
        "groupExceptionClaimed": False,
        "yearEndOwnershipBasisPoints": None,
        "yearEndVotingBasisPoints": None,
        "groupEvidenceReference": None,
        "evidenceMode": "manual_fallback",
        "evidenceReference": "dividend-advice-example",
        "ownerAttested": True,
        "bankTransactionId": None,
        "documentId": None,
        "documentStatus": "missing_accepted_warning",
        "evidenceDigest": prepared.evidence_digest,
    }


def test_received_fund_distribution_uses_private_workflow_rpcs() -> None:
    transaction = bound_transaction()
    command = supported_received_fund_distribution()
    calls: list[tuple[str, tuple[object, ...]]] = []
    responses = iter(
        [
            {"result": None},
            {"result": {
                "positionId": str(command.position_id),
                "investmentName": "Norsk Kombinasjonsfond",
                "investmentKind": "norwegian_equity_fund",
            }},
            {"result": {
                "actionId": str(command.action_id),
                "positionId": str(command.position_id),
                "accountingEntryId": "70000000-0000-0000-0000-000000000007",
                "dividendPortion": "50.00",
                "interestPortion": "50.00",
                "taxableAddBack": "1.50",
                "totalTaxableIncome": "51.50",
                "replayed": False,
            }},
        ]
    )

    async def database_rows(
        query: str, parameters: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        calls.append((query, parameters))
        return [next(responses)]

    transaction._database_rows = database_rows  # type: ignore[method-assign]
    replay = asyncio.run(transaction.get_received_fund_distribution_replay(command))
    prepared = asyncio.run(
        InvestmentsService(transaction).prepare_received_fund_distribution(command)
    )
    recorded = asyncio.run(transaction.complete_received_fund_distribution(
        command,
        prepared=prepared,
        accounting_entry_id=AccountingEntryReference(
            "70000000-0000-0000-0000-000000000007"
        ),
    ))

    assert replay is None
    assert prepared.dividend_portion == Money.nok("50.00")
    assert recorded.total_taxable_income == Money.nok("51.50")
    assert "get_received_fund_distribution_replay_v1" in calls[0][0]
    assert "prepare_received_fund_distribution_v1" in calls[1][0]
    assert "complete_received_fund_distribution_v1" in calls[2][0]
    request = json.loads(str(calls[1][1][0]))
    assert request["fundName"] == "Norsk Kombinasjonsfond"
    assert request["openingFundEquityRatioBasisPoints"] == 5_000
    assert request["fundTaxStatementReference"] == "provider-tax-statement-2026-r1"
    assert request["evidenceDigest"] == prepared.evidence_digest


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
            "accounting_classification": "other_long_term",
            "tax_treatment": "fritaksmetoden",
            "org_number": "123456789",
            "fund_equity_ratio_basis_points": None,
            "fund_tax_statement_reference": None,
            "acquisition_lot_id": None,
            "share_count": None,
            "purchase_amount": None,
            "transaction_costs": None,
            "capitalized_cost": None,
            "sold_share_count": None,
            "proceeds": None,
            "net_proceeds": None,
            "fifo_cost_basis_reduction": None,
            "fifo_tax_basis_reduction": None,
            "remaining_share_count": None,
            "remaining_cost_basis": None,
            "remaining_tax_basis": None,
            "paying_company_name": "Example AS",
            "declared_date": date(2026, 4, 1),
            "gross_amount": "125.50",
            "taxable_add_back": "3.77",
            "gain_or_loss": None,
            "book_gain_or_loss": None,
            "tax_gain_or_loss": None,
            "exempt_gain": None,
            "taxable_gain": None,
            "non_deductible_loss": None,
            "deductible_loss": None,
            "lawful_dividend_confirmed": True,
            "group_exception_claimed": False,
            "group_exception_applied": False,
            "year_end_ownership_basis_points": None,
            "year_end_voting_basis_points": None,
            "group_evidence_reference": None,
            "fund_name": None,
            "entitlement_date": None,
            "opening_fund_equity_ratio_basis_points": None,
            "dividend_portion": None,
            "interest_portion": None,
            "total_taxable_income": None,
            "bank_transaction_id": "80000000-0000-0000-0000-000000000008",
            "document_id": "90000000-0000-0000-0000-000000000009",
            "document_status": "attached",
            "evidence_mode": "linked_sources",
            "evidence_reference": "dividend-advice-19",
            "evidence_digest": "c" * 64,
            "calculation_id": "d" * 64,
            "owner_attested": False,
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
            "allocated_book_cost_basis": "50.20",
            "allocated_tax_basis": "50.20",
            "allocated_net_proceeds": "60.00",
            "average_fund_equity_ratio_basis_points": None,
            "tax_gain_or_loss": "9.80",
            "exempt_gain": "9.80",
            "taxable_gain": "0.00",
            "non_deductible_loss": "0.00",
            "deductible_loss": "0.00",
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
    assert allocation.allocated_tax_basis == Money.nok("50.20")
    assert allocation.exempt_gain == Money.nok("9.80")
    assert "acquisition_lot_id as lot_id" in queries[1]


def test_correction_query_maps_immutable_lineage_and_evidence() -> None:
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
    correction_id = "40000000-0000-0000-0000-000000000042"
    query_text = ""

    async def correction_rows(
        query: str, parameters: tuple[object, ...]
    ) -> list[dict[str, object]]:
        nonlocal query_text
        query_text = query
        return [{
            "id": correction_id,
            "company_id": str(command.company_id),
            "income_year": 2026,
            "original_action_id": str(command.action_id),
            "original_activity_kind": "dividend_received",
            "reversal_accounting_entry_id": "70000000-0000-0000-0000-000000000027",
            "replacement_action_id": "40000000-0000-0000-0000-000000000044",
            "replacement_activity_kind": "dividend_received",
            "replacement_accounting_entry_id": "70000000-0000-0000-0000-000000000037",
            "reason": "Correct gross dividend amount",
            "bank_transaction_id": None,
            "document_id": None,
            "document_status": "missing_accepted_warning",
            "evidence_mode": "manual_fallback",
            "evidence_reference": "correction-owner-evidence",
            "evidence_digest": "e" * 64,
            "owner_attested": True,
            "created_by": str(command.actor_id.subject),
            "created_at": datetime(2026, 8, 31, tzinfo=UTC),
        }]

    session._query_rows = correction_rows  # type: ignore[method-assign]
    page = asyncio.run(session.list_corrections(
        actor_id=command.actor_id,
        company_ids=(command.company_id,),
        correlation_id=command.correlation_id,
        cursor=None,
        limit=100,
    ))

    assert page.items[0].correction_id.value == correction_id
    assert page.items[0].evidence_reference == "correction-owner-evidence"
    assert "from investments.corrections" in query_text
