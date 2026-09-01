from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime
from decimal import Decimal

from talli_backend.adapters.supabase_investments import (
    SupabaseInvestmentsSession,
    SupabaseInvestmentsTransaction,
)
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.modules.investments.public import (
    AccountingEntryReference,
    RecordedInvestmentEconomicEvent,
    InvestmentSettlementBalanceKind,
)
from talli_backend.modules.investments.service import InvestmentsService
from talli_backend.modules.ledger.public import (
    InvestmentClassification,
    InvestmentDividendFacts,
    InvestmentDividendPhase,
    InvestmentPurchaseRecognitionFacts,
    LedgerEntryKind,
    LedgerFactReference,
    LedgerLine,
    LedgerSourceCapability,
    LedgerSourceRecordId,
    RecognizeHoldingActionCommand,
)
from talli_backend.shared.kernel import Money

from test_investments import (
    supported_investment_correction,
    supported_received_dividend,
    supported_received_fund_distribution,
    supported_sale,
)
from test_investments_workflow import (
    lifecycle_dividend,
    lifecycle_fund_distribution,
    lifecycle_purchase,
    lifecycle_sale,
    lifecycle_settlement,
    lifecycle_settlement_correction,
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
            "targetKind": command.target_kind.value,
            "originalRecordId": str(command.original_record_id),
            "replacementRecordId": str(replacement.event_id),
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
        replacement_accounting_entry_id=AccountingEntryReference(
            "70000000-0000-0000-0000-000000000037"
        ),
    ))

    replacement_record = RecordedInvestmentEconomicEvent(
            event_id=replacement.event_id,
            position_id=replacement.position_id,
            recognition_accounting_entry_id=AccountingEntryReference(
                "70000000-0000-0000-0000-000000000037"
            ),
            expected_settlement_amount=replacement.gross_amount,
            settlement_balance_kind=InvestmentSettlementBalanceKind.DIVIDEND_RECEIVABLE,
            replayed=False,
        )

    assert replay is None
    assert recorded.correction_id == command.correction_id
    assert replacement_record.position_id == prepared.original_position_id
    assert "get_lifecycle_correction_replay_v2" in calls[0][0]
    assert "prepare_economic_event_correction_v2" in calls[1][0]
    assert "link_investment_correction_v1" in calls[2][0]
    assert "complete_lifecycle_correction_v2" in calls[3][0]
    request = json.loads(str(calls[1][1][0]))
    assert request["targetKind"] == "economic_event"
    assert request["originalActivityKind"] == "dividend_received"
    assert request["replacementActivityKind"] == "dividend_received"
    assert request["replacement"]["grossAmount"] == "130.00"
    assert request["replacement"]["evidenceDigest"] == replacement.evidence.digest()
    assert request["evidenceDigest"] == prepared.evidence_digest
    assert calls[2][1][2] == str(prepared.original_accounting_entry_id)


def test_settlement_correction_maps_prepared_facts_and_lifecycle_completion() -> None:
    transaction = bound_transaction()
    command = lifecycle_settlement_correction()
    replacement = command.replacement
    calls: list[tuple[str, tuple[object, ...]]] = []
    responses = iter([
        {"result": None},
        {"result": {
            "originalAccountingEntryId": "70000000-0000-0000-0000-000000000017",
            "originalSettlementId": str(command.original_record_id),
            "eventId": str(replacement.event_id),
            "recognitionAccountingEntryId": "70000000-0000-0000-0000-000000000018",
            "settlementBalanceKind": "purchase_payable",
            "amount": "125.50",
            "eventFactSha256": "f" * 64,
            "evidenceDigest": replacement.evidence.digest(),
            "originalActivityKind": "share_purchase",
        }},
        {"reversal_entry_id": "70000000-0000-0000-0000-000000000027"},
        {"result": {
            "correctionId": str(command.correction_id),
            "targetKind": "cash_settlement",
            "originalRecordId": str(command.original_record_id),
            "replacementRecordId": str(replacement.settlement_id),
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
    assert asyncio.run(transaction.get_investment_correction_replay(command)) is None
    prepared = asyncio.run(
        InvestmentsService(transaction).prepare_investment_correction(command)
    )
    recorded = asyncio.run(transaction.complete_investment_correction(
        command,
        prepared=prepared,
        replacement_accounting_entry_id=AccountingEntryReference(
            "70000000-0000-0000-0000-000000000037"
        ),
    ))

    assert prepared.amount == Money.nok("125.50")
    assert prepared.original_activity_kind.value == "share_purchase"
    assert recorded.replacement_record_id == replacement.settlement_id
    assert "prepare_cash_settlement_correction_v2" in calls[1][0]
    assert "complete_lifecycle_correction_v2" in calls[3][0]
    request = json.loads(str(calls[1][1][0]))
    assert request["replacement"]["settlementId"] == str(
        replacement.settlement_id
    )
    assert request["replacement"]["evidenceDigest"] == (
        replacement.evidence.digest()
    )


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


def test_lifecycle_ledger_post_uses_only_the_restricted_investments_wrapper() -> None:
    transaction = bound_transaction()
    purchase = lifecycle_purchase()
    primary_source = LedgerFactReference(
        capability=LedgerSourceCapability.INVESTMENTS,
        record_id=LedgerSourceRecordId(str(purchase.event_id)),
        revision=1,
        fact_sha256="e" * 64,
    )
    command = RecognizeHoldingActionCommand(
        company_id=purchase.company_id,
        actor_id=purchase.actor_id,
        correlation_id=purchase.correlation_id,
        idempotency_key=purchase.idempotency_key,
        income_year=purchase.income_year,
        event_date=purchase.acquisition_date,
        primary_source=primary_source,
        corroborating_sources=tuple(
            LedgerFactReference(
                capability=LedgerSourceCapability(fact.capability.value),
                record_id=LedgerSourceRecordId(str(fact.record_id)),
                revision=fact.revision,
                fact_sha256=fact.fact_sha256,
            )
            for fact in purchase.evidence.document_facts
        ),
        facts=InvestmentPurchaseRecognitionFacts(
            investment_name=purchase.investment_name,
            classification=InvestmentClassification[
                purchase.accounting_classification.name
            ],
            acquisition_cost=Money.nok("125.50"),
        ),
    )
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def one_idempotent_row(
        query: str, parameters: tuple[object, ...]
    ) -> dict[str, object]:
        calls.append((query, parameters))
        return {
            "ledger_entry_id": "70000000-0000-0000-0000-000000000007",
            "company_id": str(command.company_id),
            "income_year": 2026,
            "entry_kind": "SHARE_PURCHASE",
            "posted_at": datetime(2026, 8, 31, tzinfo=UTC),
            "replayed": False,
        }

    transaction._one_idempotent_row = one_idempotent_row  # type: ignore[method-assign]
    posted = asyncio.run(transaction.post_entry(
        command,
        entry_kind=LedgerEntryKind.SHARE_PURCHASE,
        memo="Investment recognized: Example AS",
        lines=(
            LedgerLine("1350", "Investment in Example AS", Money.nok("125.50"), Money.nok("0")),
            LedgerLine("2990", "Investment settlement payable", Money.nok("0"), Money.nok("125.50")),
        ),
        risk_flags=(),
        warning_accepted=False,
        source_capability=LedgerSourceCapability.INVESTMENTS,
        source_record_id=primary_source.record_id,
    ))

    assert posted.entry_kind is LedgerEntryKind.SHARE_PURCHASE
    assert len(calls) == 1
    query, parameters = calls[0]
    assert "ledger.post_investment_lifecycle_entry_v2" in query
    assert "ledger.post_supported_entry_v1" not in query
    assert parameters[7] == str(purchase.event_id)
    assert json.loads(str(parameters[12])) == [
        {
            "role": "PRIMARY",
            "capability": "INVESTMENTS",
            "recordId": str(purchase.event_id),
            "revision": 1,
            "factSha256": "e" * 64,
        },
        {
            "role": "CORROBORATING",
            "capability": "DOCUMENTS",
            "recordId": str(purchase.evidence.document_facts[0].record_id),
            "revision": 1,
            "factSha256": "a" * 64,
        },
    ]


def test_dividend_decision_uses_the_restricted_investments_wrapper() -> None:
    transaction = bound_transaction()
    dividend = lifecycle_dividend()
    primary_source = LedgerFactReference(
        capability=LedgerSourceCapability.INVESTMENTS,
        record_id=LedgerSourceRecordId(str(dividend.event_id)),
        revision=1,
        fact_sha256="e" * 64,
    )
    command = RecognizeHoldingActionCommand(
        company_id=dividend.company_id,
        actor_id=dividend.actor_id,
        correlation_id=dividend.correlation_id,
        idempotency_key=dividend.idempotency_key,
        income_year=dividend.income_year,
        event_date=dividend.declared_date,
        primary_source=primary_source,
        corroborating_sources=(),
        facts=InvestmentDividendFacts(
            phase=InvestmentDividendPhase.FINAL_DECISION,
            gross_amount=dividend.gross_amount,
        ),
    )
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def one_idempotent_row(
        query: str, parameters: tuple[object, ...]
    ) -> dict[str, object]:
        calls.append((query, parameters))
        return {
            "ledger_entry_id": "70000000-0000-0000-0000-000000000027",
            "company_id": str(command.company_id),
            "income_year": 2026,
            "entry_kind": "DIVIDEND_RECEIVED",
            "posted_at": datetime(2026, 8, 31, tzinfo=UTC),
            "replayed": False,
        }

    transaction._one_idempotent_row = one_idempotent_row  # type: ignore[method-assign]
    posted = asyncio.run(transaction.record_received_dividend_decision(
        command,
        memo="Final investment-dividend decision recognized",
        lines=(
            LedgerLine("1530", "Dividend receivable", Money.nok("100"), Money.nok("0")),
            LedgerLine("8070", "Dividend income", Money.nok("0"), Money.nok("100")),
        ),
    ))

    assert posted.entry_kind is LedgerEntryKind.DIVIDEND_RECEIVED
    assert len(calls) == 1
    assert "ledger.post_investment_lifecycle_entry_v2" in calls[0][0]
    assert "ledger.record_received_dividend_decision_v1" not in calls[0][0]


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
        "bankTransactionId": "70000000-0000-0000-0000-000000000007",
        "documentId": "80000000-0000-0000-0000-000000000008",
        "documentStatus": "attached",
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
        "bankTransactionId": "70000000-0000-0000-0000-000000000007",
        "documentId": "80000000-0000-0000-0000-000000000008",
        "documentStatus": "attached",
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
            "share_count": Decimal("10.125"),
            "purchase_amount": None,
            "transaction_costs": None,
            "capitalized_cost": None,
            "sold_share_count": Decimal("4.0625"),
            "proceeds": None,
            "net_proceeds": None,
            "fifo_cost_basis_reduction": None,
            "fifo_tax_basis_reduction": None,
            "remaining_share_count": Decimal("6.0625"),
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
    assert item.share_count is not None
    assert item.share_count.amount == Decimal("10.125000000000")
    assert item.sold_share_count is not None
    assert item.sold_share_count.amount == Decimal("4.062500000000")
    assert item.remaining_share_count is not None
    assert item.remaining_share_count.amount == Decimal("6.062500000000")
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
            "allocated_share_count": Decimal("4.0625"),
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
    assert allocation.allocated_share_count.amount == Decimal("4.062500000000")
    assert allocation.allocated_cost_basis == Money.nok("50.20")
    assert allocation.allocated_tax_basis == Money.nok("50.20")
    assert allocation.exempt_gain == Money.nok("9.80")
    assert "acquisition_lot_id as lot_id" in queries[1]


def test_fractional_position_and_lot_units_survive_database_mapping() -> None:
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
    position_id = str(command.position_id)
    action_id = "30000000-0000-0000-0000-000000000003"
    lot_id = "50000000-0000-0000-0000-000000000005"
    created_at = datetime(2026, 4, 15, 12, tzinfo=UTC)
    responses = iter([
        [{
            "id": position_id,
            "company_id": str(command.company_id),
            "investment_key": "org:123456789",
            "name": "Example AS",
            "kind": "norwegian_private_company",
            "accounting_classification": "other_long_term",
            "tax_treatment": "fritaksmetoden",
            "org_number": "123456789",
            "fund_equity_ratio_basis_points": None,
            "fund_tax_statement_reference": None,
            "share_count": Decimal("10.125"),
            "cost_basis": "125.50",
            "tax_basis": "125.50",
            "lot_history_status": "complete",
            "movement_count": 1,
            "movements": [{
                "movement_type": "purchase_recognition",
                "movement_date": "2026-04-15",
                "share_delta": Decimal("10.125"),
            }],
            "created_by": str(command.actor_id.subject),
            "created_at": created_at,
            "updated_at": created_at,
        }],
        [{
            "id": lot_id,
            "company_id": str(command.company_id),
            "position_id": position_id,
            "acquisition_action_id": action_id,
            "acquisition_date": date(2026, 4, 15),
            "original_share_count": Decimal("10.125"),
            "remaining_share_count": Decimal("6.0625"),
            "original_cost_basis": "125.50",
            "remaining_cost_basis": "75.10",
            "original_tax_basis": "125.50",
            "remaining_tax_basis": "75.10",
            "acquisition_year_fund_equity_ratio_basis_points": None,
            "fund_tax_statement_reference": None,
            "created_by": str(command.actor_id.subject),
            "created_at": created_at,
        }],
    ])

    async def rows(
        _query: str, _parameters: tuple[object, ...]
    ) -> list[dict[str, object]]:
        return next(responses)

    session._query_rows = rows  # type: ignore[method-assign]
    positions = asyncio.run(session.list_positions(
        actor_id=command.actor_id,
        company_ids=(command.company_id,),
        correlation_id=command.correlation_id,
        cursor=None,
        limit=100,
    ))
    lots = asyncio.run(session.list_acquisition_lots(
        actor_id=command.actor_id,
        company_ids=(command.company_id,),
        correlation_id=command.correlation_id,
        cursor=None,
        limit=100,
    ))

    assert positions.items[0].share_count.amount == Decimal("10.125000000000")
    assert positions.items[0].movements[0]["share_delta"] == (
        "10.125000000000"
    )
    assert lots.items[0].original_share_count.amount == Decimal("10.125000000000")
    assert lots.items[0].remaining_share_count.amount == Decimal("6.062500000000")


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
            "target_kind": "economic_event",
            "original_record_id": str(command.action_id),
            "original_activity_kind": "dividend_received",
            "reversal_accounting_entry_id": "70000000-0000-0000-0000-000000000027",
            "replacement_record_id": "40000000-0000-0000-0000-000000000044",
            "replacement_activity_kind": "dividend_received",
            "replacement_accounting_entry_id": "70000000-0000-0000-0000-000000000037",
            "reason": "Correct gross dividend amount",
            "document_facts": [{
                "capability": "DOCUMENTS",
                "recordId": "80000000-0000-0000-0000-000000000018",
                "revision": 2,
                "factSha256": "d" * 64,
            }],
            "legacy_bank_transaction_id": None,
            "legacy_document_id": None,
            "legacy_document_status": None,
            "legacy": False,
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
    assert page.items[0].document_facts[0].revision == 2
    assert "from investments.lifecycle_corrections" in query_text
    assert "from investments.corrections legacy" in query_text


def test_purchase_recognition_uses_revisioned_lifecycle_rpcs() -> None:
    transaction = bound_transaction()
    command = lifecycle_purchase()
    calls: list[tuple[str, tuple[object, ...]]] = []
    responses = iter(
        [
            {"result": None},
            {
                "result": {
                    "positionId": "50000000-0000-0000-0000-000000000005",
                    "lotId": "60000000-0000-0000-0000-000000000006",
                    "positionCreated": True,
                    "investmentName": "Example AS",
                    "accountingClassification": "other_long_term",
                    "acquisitionCost": "125.50",
                    "expectedSettlementAmount": "125.50",
                    "settlementBalanceKind": "purchase_payable",
                    "evidenceDigest": "d" * 64,
                    "calculationId": "e" * 64,
                }
            },
            {
                "result": {
                    "eventId": str(command.event_id),
                    "positionId": "50000000-0000-0000-0000-000000000005",
                    "recognitionAccountingEntryId": (
                        "70000000-0000-0000-0000-000000000007"
                    ),
                    "expectedSettlementAmount": "125.50",
                    "settlementBalanceKind": "purchase_payable",
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
    replay = asyncio.run(transaction.get_share_purchase_recognition_replay(command))
    prepared = asyncio.run(
        InvestmentsService(transaction).prepare_share_purchase_recognition(command)
    )
    recorded = asyncio.run(
        transaction.complete_share_purchase_recognition(
            command,
            prepared=prepared,
            accounting_entry_id=AccountingEntryReference(
                "70000000-0000-0000-0000-000000000007"
            ),
        )
    )

    assert replay is None
    assert prepared.acquisition_cost == Money.nok("125.50")
    assert recorded.event_id == command.event_id
    assert "get_share_purchase_recognition_replay_v2" in calls[0][0]
    assert "prepare_share_purchase_recognition_v2" in calls[1][0]
    assert "complete_share_purchase_recognition_v2" in calls[2][0]
    request = json.loads(str(calls[1][1][0]))
    assert request["eventId"] == str(command.event_id)
    assert request["shareCount"] == "10.125000000000"
    assert request["documentFacts"] == [
        {
            "capability": "DOCUMENTS",
            "recordId": "80000000-0000-0000-0000-000000000001",
            "revision": 1,
            "factSha256": "a" * 64,
        }
    ]
    assert request["bankFact"] is None
    assert request["evidenceDigest"] == prepared.evidence_digest


def test_share_sale_recognition_preserves_fractional_fifo_through_v2_rpcs() -> None:
    transaction = bound_transaction()
    command = lifecycle_sale()
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
                        "acquisitionDate": "2026-04-15",
                        "allocatedShareCount": "4.125000000000",
                        "allocatedBookCostBasis": "50.20",
                        "allocatedTaxBasis": "50.20",
                        "acquisitionYearFundEquityRatioBasisPoints": None,
                    }],
                }
            },
            {
                "result": {
                    "eventId": str(command.event_id),
                    "positionId": str(command.position_id),
                    "recognitionAccountingEntryId": (
                        "70000000-0000-0000-0000-000000000017"
                    ),
                    "expectedSettlementAmount": "75.00",
                    "settlementBalanceKind": "sale_receivable",
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
    replay = asyncio.run(transaction.get_share_sale_recognition_replay(command))
    prepared = asyncio.run(
        InvestmentsService(transaction).prepare_share_sale_recognition(command)
    )
    recorded = asyncio.run(
        transaction.complete_share_sale_recognition(
            command,
            prepared=prepared,
            accounting_entry_id=AccountingEntryReference(
                "70000000-0000-0000-0000-000000000017"
            ),
        )
    )

    assert replay is None
    assert recorded.event_id == command.event_id
    assert prepared.lot_calculations[0].allocated_share_count.amount == (
        command.sold_share_count.amount
    )
    assert "get_share_sale_recognition_replay_v2" in calls[0][0]
    assert "prepare_share_sale_recognition_v2" in calls[1][0]
    assert "complete_share_sale_recognition_v2" in calls[2][0]
    request = json.loads(str(calls[1][1][0]))
    assert request["soldShareCount"] == "4.125000000000"
    assert request["documentFacts"][0]["capability"] == "DOCUMENTS"
    assert request["bankFact"] is None
    completed = json.loads(str(calls[2][1][2]))
    assert completed["lotCalculations"][0]["allocatedShareCount"] == (
        "4.125000000000"
    )
    assert completed["netProceeds"] == "75.00"


def test_dividend_recognition_uses_declaration_only_v2_rpcs() -> None:
    transaction = bound_transaction()
    command = lifecycle_dividend()
    calls: list[tuple[str, tuple[object, ...]]] = []
    responses = iter([
        {"result": None},
        {"result": {
            "positionId": str(command.position_id),
            "investmentName": "Example AS",
            "investmentKind": "norwegian_private_company",
        }},
        {"result": {
            "eventId": str(command.event_id),
            "positionId": str(command.position_id),
            "recognitionAccountingEntryId": (
                "70000000-0000-0000-0000-000000000027"
            ),
            "expectedSettlementAmount": "100.00",
            "settlementBalanceKind": "dividend_receivable",
            "replayed": False,
        }},
    ])

    async def database_rows(
        query: str, parameters: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        calls.append((query, parameters))
        return [next(responses)]

    transaction._database_rows = database_rows  # type: ignore[method-assign]
    replay = asyncio.run(transaction.get_received_dividend_recognition_replay(command))
    prepared = asyncio.run(
        InvestmentsService(transaction).prepare_received_dividend_recognition(command)
    )
    recorded = asyncio.run(transaction.complete_received_dividend_recognition(
        command,
        prepared=prepared,
        accounting_entry_id=AccountingEntryReference(
            "70000000-0000-0000-0000-000000000027"
        ),
    ))

    assert replay is None
    assert recorded.event_id == command.event_id
    assert "get_received_dividend_recognition_replay_v2" in calls[0][0]
    assert "prepare_received_dividend_recognition_v2" in calls[1][0]
    assert "complete_received_dividend_recognition_v2" in calls[2][0]
    request = json.loads(str(calls[1][1][0]))
    assert request["declaredDate"] == command.declared_date.value.isoformat()
    assert "paidDate" not in request
    assert request["bankFact"] is None
    completed = json.loads(str(calls[2][1][2]))
    assert completed["taxableAddBack"] == "3.77"
    assert completed["groupExceptionApplied"] is False


def test_fund_distribution_recognition_uses_entitlement_only_v2_rpcs() -> None:
    transaction = bound_transaction()
    command = lifecycle_fund_distribution()
    calls: list[tuple[str, tuple[object, ...]]] = []
    responses = iter([
        {"result": None},
        {"result": {
            "positionId": str(command.position_id),
            "investmentName": "Norsk Kombinasjonsfond",
            "investmentKind": "norwegian_equity_fund",
        }},
        {"result": {
            "eventId": str(command.event_id),
            "positionId": str(command.position_id),
            "recognitionAccountingEntryId": (
                "70000000-0000-0000-0000-000000000037"
            ),
            "expectedSettlementAmount": "100.00",
            "settlementBalanceKind": "fund_distribution_receivable",
            "replayed": False,
        }},
    ])

    async def database_rows(
        query: str, parameters: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        calls.append((query, parameters))
        return [next(responses)]

    transaction._database_rows = database_rows  # type: ignore[method-assign]
    replay = asyncio.run(
        transaction.get_received_fund_distribution_recognition_replay(command)
    )
    prepared = asyncio.run(
        InvestmentsService(transaction)
        .prepare_received_fund_distribution_recognition(command)
    )
    recorded = asyncio.run(
        transaction.complete_received_fund_distribution_recognition(
            command,
            prepared=prepared,
            accounting_entry_id=AccountingEntryReference(
                "70000000-0000-0000-0000-000000000037"
            ),
        )
    )

    assert replay is None
    assert recorded.event_id == command.event_id
    assert "get_received_fund_distribution_recognition_replay_v2" in calls[0][0]
    assert "prepare_received_fund_distribution_recognition_v2" in calls[1][0]
    assert "complete_received_fund_distribution_recognition_v2" in calls[2][0]
    request = json.loads(str(calls[1][1][0]))
    assert request["entitlementDate"] == command.entitlement_date.value.isoformat()
    assert "paidDate" not in request
    assert request["bankFact"] is None
    completed = json.loads(str(calls[2][1][2]))
    assert completed["dividendPortion"] == "50.00"
    assert completed["interestPortion"] == "50.00"


def test_cash_settlement_uses_event_and_bank_fact_rpcs() -> None:
    transaction = bound_transaction()
    command = lifecycle_settlement(lifecycle_purchase())
    calls: list[tuple[str, tuple[object, ...]]] = []
    responses = iter(
        [
            {"result": None},
            {
                "result": {
                    "eventId": str(command.event_id),
                    "recognitionAccountingEntryId": (
                        "70000000-0000-0000-0000-000000000017"
                    ),
                    "settlementBalanceKind": "purchase_payable",
                    "amount": "125.50",
                    "eventFactSha256": "c" * 64,
                    "evidenceDigest": "f" * 64,
                }
            },
            {
                "result": {
                    "settlementId": str(command.settlement_id),
                    "eventId": str(command.event_id),
                    "settlementAccountingEntryId": (
                        "70000000-0000-0000-0000-000000000007"
                    ),
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
    replay = asyncio.run(transaction.get_cash_settlement_replay(command))
    prepared = asyncio.run(
        InvestmentsService(transaction).prepare_cash_settlement(command)
    )
    recorded = asyncio.run(
        transaction.complete_cash_settlement(
            command,
            prepared=prepared,
            accounting_entry_id=AccountingEntryReference(
                "70000000-0000-0000-0000-000000000007"
            ),
        )
    )

    assert replay is None
    assert recorded.settlement_id == command.settlement_id
    assert "get_cash_settlement_replay_v2" in calls[0][0]
    assert "prepare_cash_settlement_v2" in calls[1][0]
    assert "complete_cash_settlement_v2" in calls[2][0]
    request = json.loads(str(calls[1][1][0]))
    assert request["eventId"] == str(command.event_id)
    assert request["bankFact"]["capability"] == "BANKING"
    assert request["documentFacts"] == []
    assert request["evidenceDigest"] == prepared.evidence_digest
