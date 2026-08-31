"""Private policy implementation for the investments capability."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import re

from talli_backend.modules.investments.public import (
    AccountingEntryReference,
    InvestmentDocumentStatus,
    InvestmentKind,
    InvestmentTaxTreatment,
    InvestmentsError,
    InvestmentsPersistence,
    PreparedReceivedDividend,
    PreparedSharePurchase,
    PreparedShareSale,
    RecordSharePurchaseCommand,
    RecordShareSaleCommand,
    RecordReceivedDividendCommand,
    RecordedReceivedDividend,
    RecordedSharePurchase,
    RecordedShareSale,
)
from talli_backend.shared.kernel import Money


class InvestmentsService:
    def __init__(self, persistence: InvestmentsPersistence) -> None:
        self._persistence = persistence

    async def get_share_purchase_replay(
        self, command: RecordSharePurchaseCommand
    ) -> RecordedSharePurchase | None:
        return await self._persistence.get_share_purchase_replay(command)

    async def get_received_dividend_replay(
        self, command: RecordReceivedDividendCommand
    ) -> RecordedReceivedDividend | None:
        return await self._persistence.get_received_dividend_replay(command)

    async def prepare_received_dividend(
        self, command: RecordReceivedDividendCommand
    ) -> PreparedReceivedDividend:
        paying_company_name = command.paying_company_name.strip()
        if (
            not paying_company_name
            or len(paying_company_name) > 255
            or command.gross_amount.amount <= 0
            or command.declared_date.value.year != command.income_year.value
            or command.paid_date.value.year != command.income_year.value
            or command.declared_date.value > command.paid_date.value
            or command.tax_treatment is not InvestmentTaxTreatment.EXEMPTION_METHOD
            or command.document_status not in InvestmentDocumentStatus
            or command.bank_transaction_id is not None
            or command.document_id is not None
            or command.document_status is InvestmentDocumentStatus.ATTACHED
        ):
            raise InvestmentsError.invalid_input()
        normalized = replace(command, paying_company_name=paying_company_name)
        taxable_add_back = Money.nok(
            command.gross_amount.amount * Decimal("0.03")
        )
        prepared = await self._persistence.prepare_received_dividend(
            normalized,
            taxable_add_back=taxable_add_back,
        )
        return replace(
            prepared,
            paying_company_name=normalized.paying_company_name,
            taxable_add_back=taxable_add_back,
        )

    async def complete_received_dividend(
        self,
        command: RecordReceivedDividendCommand,
        *,
        prepared: PreparedReceivedDividend,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedReceivedDividend:
        return await self._persistence.complete_received_dividend(
            replace(command, paying_company_name=prepared.paying_company_name),
            prepared=prepared,
            accounting_entry_id=accounting_entry_id,
        )

    async def prepare_share_purchase(
        self, command: RecordSharePurchaseCommand
    ) -> PreparedSharePurchase:
        investment_key = command.investment_key.strip()
        investment_name = command.investment_name.strip()
        org_number = command.org_number.strip() if command.org_number else None
        if (
            not isinstance(command.share_count, int)
            or isinstance(command.share_count, bool)
            or command.share_count <= 0
            or command.purchase_amount.amount <= 0
            or command.acquisition_date.value.year != command.income_year.value
            or not investment_key
            or len(investment_key) > 255
            or not investment_name
            or len(investment_name) > 255
            or command.investment_kind is not InvestmentKind.NORWEGIAN_PRIVATE_COMPANY
            or command.tax_treatment is not InvestmentTaxTreatment.EXEMPTION_METHOD
            or (org_number is not None and re.fullmatch(r"[0-9]{9}", org_number) is None)
            or command.document_status not in InvestmentDocumentStatus
            or command.bank_transaction_id is not None
            or command.document_id is not None
            or command.document_status is InvestmentDocumentStatus.ATTACHED
        ):
            raise InvestmentsError.invalid_input()
        normalized = replace(
            command,
            investment_key=investment_key,
            investment_name=investment_name,
            org_number=org_number,
        )
        prepared = await self._persistence.prepare_share_purchase(normalized)
        return replace(
            prepared,
            investment_name=normalized.investment_name,
            purchase_amount=normalized.purchase_amount,
        )

    async def complete_share_purchase(
        self,
        command: RecordSharePurchaseCommand,
        *,
        prepared: PreparedSharePurchase,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedSharePurchase:
        return await self._persistence.complete_share_purchase(
            command,
            prepared=prepared,
            accounting_entry_id=accounting_entry_id,
        )

    async def prepare_share_sale(
        self, command: RecordShareSaleCommand
    ) -> PreparedShareSale:
        if (
            not isinstance(command.sold_share_count, int)
            or isinstance(command.sold_share_count, bool)
            or command.sold_share_count <= 0
            or command.proceeds.amount <= 0
            or command.sale_date.value.year != command.income_year.value
            or command.document_status not in InvestmentDocumentStatus
            or command.bank_transaction_id is not None
            or command.document_id is not None
            or command.document_status is InvestmentDocumentStatus.ATTACHED
        ):
            raise InvestmentsError.invalid_input()
        return await self._persistence.prepare_share_sale(command)

    async def get_share_sale_replay(
        self, command: RecordShareSaleCommand
    ) -> RecordedShareSale | None:
        return await self._persistence.get_share_sale_replay(command)

    async def complete_share_sale(
        self,
        command: RecordShareSaleCommand,
        *,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedShareSale:
        return await self._persistence.complete_share_sale(
            command,
            accounting_entry_id=accounting_entry_id,
        )


__all__ = ["InvestmentsService"]
