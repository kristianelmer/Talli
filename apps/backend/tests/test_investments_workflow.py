from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from talli_backend.application.investments_workflow import InvestmentsSession
from talli_backend.modules.investments.public import (
    AccountingEntryReference,
    AcquisitionLotId,
    InvestmentAccountingClassification,
    InvestmentKind,
    InvestmentPositionId,
    InvestmentSaleLotFact,
    PreparedInvestmentCorrection,
    PreparedReceivedDividendFacts,
    PreparedReceivedFundDistributionFacts,
    PreparedReceivedDividend,
    PreparedShareSaleFacts,
    PreparedSharePurchase,
    RecordedShareSale,
    RecordedSharePurchase,
    RecordedReceivedDividend,
    RecordedReceivedFundDistribution,
    RecordedInvestmentCorrection,
)
from talli_backend.modules.ledger.public import (
    LedgerEntryId,
    LedgerEntryKind,
    PostedLedgerEntry,
)
from talli_backend.shared.kernel import IncomeYear, Money, Timestamp

from test_investments import (
    supported_purchase,
    supported_investment_correction,
    supported_received_dividend,
    supported_received_fund_distribution,
    supported_sale,
)


POSITION_ID = InvestmentPositionId("50000000-0000-0000-0000-000000000005")
LOT_ID = AcquisitionLotId("60000000-0000-0000-0000-000000000006")
ENTRY_ID = LedgerEntryId("70000000-0000-0000-0000-000000000007")
ORIGINAL_ENTRY_ID = AccountingEntryReference(
    "70000000-0000-0000-0000-000000000017"
)
NOW = Timestamp(datetime(2026, 8, 31, tzinfo=UTC))


class SessionPersistence:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.posted_command = None

    @property
    def actor_id(self):
        return supported_purchase().actor_id

    @asynccontextmanager
    async def transaction(self):
        self.events.append("transaction:begin")
        yield self
        self.events.append("transaction:commit")

    async def get_investment_correction_replay(self, command):
        self.events.append("investments:correction-replay")
        return None

    async def prepare_investment_correction(self, command, *, evidence_digest):
        self.events.append("investments:correction-prepare")
        return PreparedInvestmentCorrection(
            original_accounting_entry_id=ORIGINAL_ENTRY_ID,
            original_position_id=command.replacement.position_id,
            evidence_digest=evidence_digest,
        )

    async def complete_investment_correction(
        self, command, *, prepared, replacement
    ):
        self.events.append("investments:correction-complete")
        assert prepared.original_accounting_entry_id == ORIGINAL_ENTRY_ID
        assert replacement.accounting_entry_id == AccountingEntryReference(
            str(ENTRY_ID)
        )
        return RecordedInvestmentCorrection(
            correction_id=command.correction_id,
            original_action_id=command.original_action_id,
            replacement_action_id=replacement.action_id,
            reversal_accounting_entry_id=AccountingEntryReference(
                "70000000-0000-0000-0000-000000000027"
            ),
            replacement_accounting_entry_id=replacement.accounting_entry_id,
            replayed=False,
        )

    async def get_share_purchase_replay(self, command):
        self.events.append("investments:replay")
        return None

    async def prepare_share_purchase(
        self, command, *, capitalized_cost, evidence_digest, calculation_id
    ):
        self.events.append("investments:prepare")
        return PreparedSharePurchase(
            POSITION_ID,
            LOT_ID,
            True,
            "Example AS",
            InvestmentAccountingClassification.OTHER_LONG_TERM,
            capitalized_cost,
            evidence_digest,
            calculation_id,
        )

    async def complete_share_purchase(
        self, command, *, prepared, accounting_entry_id
    ):
        self.events.append("investments:complete")
        assert prepared == PreparedSharePurchase(
            POSITION_ID,
            LOT_ID,
            True,
            "Example AS",
            InvestmentAccountingClassification.OTHER_LONG_TERM,
            Money.nok("125.50"),
            prepared.evidence_digest,
            prepared.calculation_id,
        )
        assert accounting_entry_id == AccountingEntryReference(str(ENTRY_ID))
        return RecordedSharePurchase(
            action_id=command.action_id,
            position_id=prepared.position_id,
            lot_id=prepared.lot_id,
            accounting_entry_id=accounting_entry_id,
            position_created=prepared.position_created,
            replayed=False,
        )

    async def get_share_sale_replay(self, command):
        self.events.append("investments:sale-replay")
        return None

    async def prepare_share_sale(self, command, *, net_proceeds, evidence_digest):
        self.events.append("investments:sale-prepare")
        return PreparedShareSaleFacts(
            position_id=POSITION_ID,
            investment_name="Example AS",
            investment_kind=InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
            accounting_classification=InvestmentAccountingClassification.OTHER_LONG_TERM,
            fifo_book_cost_basis_reduction=Money.nok("50.20"),
            fifo_tax_basis_reduction=Money.nok("50.20"),
            lot_facts=(InvestmentSaleLotFact(
                lot_id=LOT_ID,
                allocation_order=1,
                acquisition_date=command.sale_date,
                allocated_share_count=command.sold_share_count,
                allocated_book_cost_basis=Money.nok("50.20"),
                allocated_tax_basis=Money.nok("50.20"),
                acquisition_year_fund_equity_ratio_basis_points=None,
            ),),
        )

    async def complete_share_sale(self, command, *, prepared, accounting_entry_id):
        self.events.append("investments:sale-complete")
        assert accounting_entry_id == AccountingEntryReference(str(ENTRY_ID))
        return RecordedShareSale(
            action_id=command.action_id,
            position_id=command.position_id,
            accounting_entry_id=accounting_entry_id,
            replayed=False,
        )

    async def get_received_dividend_replay(self, command):
        self.events.append("investments:dividend-replay")
        return None

    async def prepare_received_dividend(
        self, command, *, evidence_digest
    ):
        self.events.append("investments:dividend-prepare")
        return PreparedReceivedDividendFacts(
            position_id=command.position_id,
            investment_name="Example AS",
            investment_kind=InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
        )

    async def complete_received_dividend(
        self, command, *, prepared, accounting_entry_id
    ):
        self.events.append("investments:dividend-complete")
        return RecordedReceivedDividend(
            action_id=command.action_id,
            position_id=command.position_id,
            accounting_entry_id=accounting_entry_id,
            taxable_add_back=prepared.taxable_add_back,
            replayed=False,
        )

    async def get_received_fund_distribution_replay(self, command):
        self.events.append("investments:fund-distribution-replay")
        return None

    async def prepare_received_fund_distribution(self, command, *, evidence_digest):
        self.events.append("investments:fund-distribution-prepare")
        return PreparedReceivedFundDistributionFacts(
            position_id=command.position_id,
            investment_name="Norsk Kombinasjonsfond",
            investment_kind=InvestmentKind.NORWEGIAN_EQUITY_FUND,
        )

    async def complete_received_fund_distribution(
        self, command, *, prepared, accounting_entry_id
    ):
        self.events.append("investments:fund-distribution-complete")
        return RecordedReceivedFundDistribution(
            action_id=command.action_id,
            position_id=command.position_id,
            accounting_entry_id=accounting_entry_id,
            dividend_portion=prepared.dividend_portion,
            interest_portion=prepared.interest_portion,
            taxable_add_back=prepared.taxable_add_back,
            total_taxable_income=prepared.total_taxable_income,
            replayed=False,
        )


class LedgerFacade:
    def __init__(self, transaction: SessionPersistence) -> None:
        self.transaction = transaction

    async def post_investment_purchase(self, command):
        self.transaction.events.append("ledger:post")
        self.transaction.posted_command = command
        return PostedLedgerEntry(
            entry_id=ENTRY_ID,
            company_id=command.company_id,
            income_year=IncomeYear(2026),
            entry_kind=LedgerEntryKind.SHARE_PURCHASE,
            posted_at=NOW,
            replayed=False,
        )

    async def post_investment_sale(self, command):
        self.transaction.events.append("ledger:sale-post")
        self.transaction.posted_command = command
        return PostedLedgerEntry(
            entry_id=ENTRY_ID,
            company_id=command.company_id,
            income_year=IncomeYear(2026),
            entry_kind=LedgerEntryKind.SHARE_SALE,
            posted_at=NOW,
            replayed=False,
        )

    async def post_received_dividend(self, command):
        self.transaction.events.append("ledger:dividend-post")
        self.transaction.posted_command = command
        return PostedLedgerEntry(
            entry_id=ENTRY_ID,
            company_id=command.company_id,
            income_year=IncomeYear(2026),
            entry_kind=LedgerEntryKind.DIVIDEND_RECEIVED,
            posted_at=NOW,
            replayed=False,
        )

    async def post_received_fund_distribution(self, command):
        self.transaction.events.append("ledger:fund-distribution-post")
        self.transaction.posted_command = command
        return PostedLedgerEntry(
            entry_id=ENTRY_ID,
            company_id=command.company_id,
            income_year=IncomeYear(2026),
            entry_kind=LedgerEntryKind.DIVIDEND_RECEIVED,
            posted_at=NOW,
            replayed=False,
        )


def test_received_dividend_composes_investments_and_ledger_interfaces_atomically() -> None:
    persistence = SessionPersistence()
    command = supported_received_dividend()

    result = asyncio.run(
        InvestmentsSession(persistence, LedgerFacade).record_received_dividend(command)
    )

    assert result.accounting_entry_id == AccountingEntryReference(str(ENTRY_ID))
    assert result.position_id == command.position_id
    assert result.taxable_add_back == Money.nok("3.77")
    assert persistence.events == [
        "transaction:begin",
        "investments:dividend-replay",
        "investments:dividend-prepare",
        "ledger:dividend-post",
        "investments:dividend-complete",
        "transaction:commit",
    ]
    assert persistence.posted_command.paying_company_name == "Example AS"
    assert persistence.posted_command.gross_amount == Money.nok("125.50")
    assert not hasattr(persistence.posted_command, "lines")


def test_correction_composes_reversal_and_same_policy_replacement_atomically() -> None:
    persistence = SessionPersistence()
    command = supported_investment_correction()

    result = asyncio.run(
        InvestmentsSession(persistence, LedgerFacade).correct_investment(command)
    )

    assert result.correction_id == command.correction_id
    assert result.original_action_id == command.original_action_id
    assert result.replacement_action_id == command.replacement.action_id
    assert result.replacement_accounting_entry_id == AccountingEntryReference(
        str(ENTRY_ID)
    )
    assert persistence.events == [
        "transaction:begin",
        "investments:correction-replay",
        "investments:correction-prepare",
        "investments:dividend-prepare",
        "ledger:dividend-post",
        "investments:dividend-complete",
        "investments:correction-complete",
        "transaction:commit",
    ]


def test_fund_distribution_composes_split_and_ledger_atomically() -> None:
    persistence = SessionPersistence()
    command = supported_received_fund_distribution()

    result = asyncio.run(
        InvestmentsSession(persistence, LedgerFacade)
        .record_received_fund_distribution(command)
    )

    assert result.dividend_portion == Money.nok("50.00")
    assert result.interest_portion == Money.nok("50.00")
    assert result.total_taxable_income == Money.nok("51.50")
    assert persistence.events == [
        "transaction:begin",
        "investments:fund-distribution-replay",
        "investments:fund-distribution-prepare",
        "ledger:fund-distribution-post",
        "investments:fund-distribution-complete",
        "transaction:commit",
    ]


def test_share_purchase_composes_investments_and_ledger_interfaces_atomically() -> None:
    persistence = SessionPersistence()
    command = supported_purchase()

    result = asyncio.run(
        InvestmentsSession(persistence, LedgerFacade).record_share_purchase(command)
    )

    assert result.accounting_entry_id == AccountingEntryReference(str(ENTRY_ID))
    assert result.position_id == POSITION_ID
    assert result.lot_id == LOT_ID
    assert persistence.events == [
        "transaction:begin",
        "investments:replay",
        "investments:prepare",
        "ledger:post",
        "investments:complete",
        "transaction:commit",
    ]
    assert persistence.posted_command.investment_name == "Example AS"
    assert persistence.posted_command.purchase_amount == Money.nok("125.50")
    assert not hasattr(persistence.posted_command, "lines")


def test_share_sale_composes_investments_and_ledger_interfaces_atomically() -> None:
    persistence = SessionPersistence()
    command = supported_sale()

    result = asyncio.run(
        InvestmentsSession(persistence, LedgerFacade).record_share_sale(command)
    )

    assert result.accounting_entry_id == AccountingEntryReference(str(ENTRY_ID))
    assert result.position_id == command.position_id
    assert persistence.events == [
        "transaction:begin",
        "investments:sale-replay",
        "investments:sale-prepare",
        "ledger:sale-post",
        "investments:sale-complete",
        "transaction:commit",
    ]
    assert persistence.posted_command.investment_name == "Example AS"
    assert persistence.posted_command.proceeds == Money.nok("75.00")
    assert persistence.posted_command.fifo_cost_basis_reduction == Money.nok(
        "50.20"
    )
    assert not hasattr(persistence.posted_command, "lines")
