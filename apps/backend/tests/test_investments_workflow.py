from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from talli_backend.application.investments_workflow import InvestmentsSession
from talli_backend.modules.investments.public import (
    AccountingEntryReference,
    AcquisitionLotId,
    InvestmentPositionId,
    PreparedSharePurchase,
    RecordedSharePurchase,
)
from talli_backend.modules.ledger.public import (
    LedgerEntryId,
    LedgerEntryKind,
    PostedLedgerEntry,
)
from talli_backend.shared.kernel import IncomeYear, Money, Timestamp

from test_investments import supported_purchase


POSITION_ID = InvestmentPositionId("50000000-0000-0000-0000-000000000005")
LOT_ID = AcquisitionLotId("60000000-0000-0000-0000-000000000006")
ENTRY_ID = LedgerEntryId("70000000-0000-0000-0000-000000000007")
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

    async def get_share_purchase_replay(self, command):
        self.events.append("investments:replay")
        return None

    async def prepare_share_purchase(self, command):
        self.events.append("investments:prepare")
        return PreparedSharePurchase(
            POSITION_ID, LOT_ID, True, "Example AS", Money.nok("125.50")
        )

    async def complete_share_purchase(
        self, command, *, prepared, accounting_entry_id
    ):
        self.events.append("investments:complete")
        assert prepared == PreparedSharePurchase(
            POSITION_ID, LOT_ID, True, "Example AS", Money.nok("125.50")
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
