"""Narrow-ledger business invariants and intent-specific posting policy."""

from __future__ import annotations

from decimal import Decimal

from talli_backend.modules.ledger.public import (
    AdministrativeCostCategory,
    BankSuggestionRule,
    LedgerCursor,
    LedgerEntryKind,
    LedgerError,
    LedgerLine,
    LedgerPersistence,
    LedgerRiskCode,
    LedgerRiskFlag,
    LedgerSourceCapability,
    LedgerSourceRecordId,
    LedgerEntryPage,
    LockPeriodCommand,
    PeriodLock,
    PeriodLockPage,
    PostAdministrativeCostCommand,
    PostBankSuggestionOutcomeCommand,
    PostInvestmentDividendCommand,
    PostInvestmentPurchaseCommand,
    PostInvestmentSaleCommand,
    PostOwnerDividendDeclaredCommand,
    PostOwnerDividendPaymentCommand,
    PostShareholderLoanCommand,
    PostTaxSettlementCommand,
    ShareholderLoanDirection,
    TaxSettlementKind,
    PostedLedgerEntry,
    PostManualJournalCommand,
    PostOpeningBalanceCommand,
)
from talli_backend.shared.kernel import ActorId, CompanyId, CorrelationId, Money


_ZERO = Money.nok("0.00")
_SENSITIVE_MANUAL_ACCOUNTS = frozenset(
    {"1370", "1800", "2000", "2050", "2255", "2800", "8070", "8090"}
)
_ADMINISTRATIVE_COST_ACCOUNTS = {
    AdministrativeCostCategory.BANK_FEE: "7770",
    AdministrativeCostCategory.ACCOUNTING_FEE: "6705",
    AdministrativeCostCategory.SOFTWARE: "6420",
    AdministrativeCostCategory.PUBLIC_FEE: "7790",
    AdministrativeCostCategory.LEGAL_ADVISORY: "6720",
    AdministrativeCostCategory.OTHER_ADMIN_COST: "7795",
}
_BANK_SUGGESTION_LINES = {
    BankSuggestionRule.BANK_FEE: ("7770", "Bankomkostninger", False),
    BankSuggestionRule.SYSTEM_SUBSCRIPTION: ("6700", "Fremmede tjenester", False),
    BankSuggestionRule.DEPOSIT_INTEREST: ("8050", "Annen renteinntekt", True),
}


def _positive(value: Money, code: str) -> None:
    if value.amount <= 0:
        raise LedgerError.invalid_input(code)


def _balanced(lines: tuple[LedgerLine, ...], *, permit_zero_line: bool = False) -> None:
    if len(lines) < 2:
        raise LedgerError.invalid_input("LEDGER_ENTRY_REQUIRES_TWO_LINES")
    if not permit_zero_line and any(
        line.debit.amount == 0 and line.credit.amount == 0 for line in lines
    ):
        raise LedgerError.invalid_input("LEDGER_LINE_ZERO")
    currencies = {line.debit.currency for line in lines} | {
        line.credit.currency for line in lines
    }
    if len(currencies) != 1:
        raise LedgerError.invalid_input("LEDGER_CURRENCY_MISMATCH")
    debit = sum((line.debit.amount for line in lines), start=Decimal("0.00"))
    credit = sum((line.credit.amount for line in lines), start=Decimal("0.00"))
    if debit != credit:
        raise LedgerError.invalid_input("LEDGER_ENTRY_UNBALANCED")


class LedgerService:
    def __init__(self, persistence: LedgerPersistence) -> None:
        self._persistence = persistence

    async def post_opening_balance(
        self, command: PostOpeningBalanceCommand
    ) -> PostedLedgerEntry:
        if command.bank_balance.amount < 0 or command.share_capital_snapshot.amount < 0:
            raise LedgerError.invalid_input("LEDGER_OPENING_BALANCE_NEGATIVE")
        if command.bank_balance.currency != command.share_capital_snapshot.currency:
            raise LedgerError.invalid_input("LEDGER_CURRENCY_MISMATCH")
        retained = command.bank_balance.amount - command.share_capital_snapshot.amount
        retained_debit = Money.nok(str(abs(retained))) if retained < 0 else _ZERO
        retained_credit = Money.nok(str(retained)) if retained > 0 else _ZERO
        lines = (
            LedgerLine("1920", "Bankinnskudd", command.bank_balance, _ZERO),
            LedgerLine("2000", "Aksjekapital", _ZERO, command.share_capital_snapshot),
            LedgerLine(
                "2050",
                "Annen egenkapital" if retained >= 0 else "Udekket tap",
                retained_debit,
                retained_credit,
            ),
        )
        _balanced(lines, permit_zero_line=True)
        return await self._persistence.post_entry(
            command,
            entry_kind=LedgerEntryKind.OPENING_BALANCE,
            memo="Åpningsbalanse for Talli-start",
            lines=lines,
            risk_flags=(),
            warning_accepted=False,
            source_capability=(
                LedgerSourceCapability.SHAREHOLDER_REGISTER_FILING
                if command.opening_snapshot_id is not None
                else LedgerSourceCapability.LEDGER
            ),
            source_record_id=command.opening_snapshot_id
            or LedgerSourceRecordId(str(command.idempotency_key)),
        )

    async def post_administrative_cost(
        self, command: PostAdministrativeCostCommand
    ) -> PostedLedgerEntry:
        _positive(command.amount, "LEDGER_ADMINISTRATIVE_COST_NOT_POSITIVE")
        if command.paid_date.value.year != int(command.income_year):
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        payee = command.payee.strip()
        if not payee:
            raise LedgerError.invalid_input("LEDGER_PAYEE_REQUIRED")
        document = f" (document {command.document_id})" if command.document_id else ""
        lines = (
            LedgerLine(
                _ADMINISTRATIVE_COST_ACCOUNTS[command.category],
                f"Admin cost: {payee}",
                command.amount,
                _ZERO,
            ),
            LedgerLine("1920", "Paid from bank", _ZERO, command.amount),
        )
        return await self._persistence.post_entry(
            command,
            entry_kind=LedgerEntryKind.ADMINISTRATIVE_COST,
            memo=(
                f"Admin cost paid to {payee} on {command.paid_date.value.isoformat()}"
                f"{document}"
            ),
            lines=lines,
            risk_flags=(),
            warning_accepted=False,
            source_capability=LedgerSourceCapability.BANKING,
            source_record_id=command.bank_transaction_id,
        )

    async def post_bank_suggestion_outcome(
        self, command: PostBankSuggestionOutcomeCommand
    ) -> PostedLedgerEntry:
        _positive(command.amount, "LEDGER_INVALID_INPUT")
        account, description, is_income = _BANK_SUGGESTION_LINES[command.rule]
        lines = (
            (
                LedgerLine("1920", "Bank", command.amount, _ZERO),
                LedgerLine(account, description, _ZERO, command.amount),
            )
            if is_income
            else (
                LedgerLine(account, description, command.amount, _ZERO),
                LedgerLine("1920", "Bank", _ZERO, command.amount),
            )
        )
        _balanced(lines)
        return await self._persistence.post_entry(
            command,
            entry_kind=LedgerEntryKind.BANK_RULE_SUGGESTION,
            memo=f"Godkjent bankforslag: {command.transaction_text}",
            lines=lines,
            risk_flags=(),
            warning_accepted=False,
            source_capability=LedgerSourceCapability.BANKING,
            source_record_id=command.acceptance_id,
        )

    async def post_investment_dividend(
        self, command: PostInvestmentDividendCommand
    ) -> PostedLedgerEntry:
        _positive(command.gross_amount, "LEDGER_INVALID_INPUT")
        lines = (
            LedgerLine(
                "1920", "Dividend received in bank", command.gross_amount, _ZERO
            ),
            LedgerLine(
                "8070",
                f"Dividend from {command.paying_company_name}",
                _ZERO,
                command.gross_amount,
            ),
        )
        _balanced(lines)
        return await self._persistence.post_entry(
            command,
            entry_kind=LedgerEntryKind.DIVIDEND_RECEIVED,
            memo=f"Dividend received from {command.paying_company_name}",
            lines=lines,
            risk_flags=(),
            warning_accepted=False,
            source_capability=LedgerSourceCapability.INVESTMENTS,
            source_record_id=command.action_id,
        )

    async def post_investment_purchase(
        self, command: PostInvestmentPurchaseCommand
    ) -> PostedLedgerEntry:
        _positive(command.purchase_amount, "LEDGER_INVALID_INPUT")
        lines = (
            LedgerLine(
                "1800",
                f"Investment in {command.investment_name}",
                command.purchase_amount,
                _ZERO,
            ),
            LedgerLine("1920", "Paid from bank", _ZERO, command.purchase_amount),
        )
        _balanced(lines)
        return await self._persistence.post_entry(
            command,
            entry_kind=LedgerEntryKind.SHARE_PURCHASE,
            memo=f"Share purchase: {command.investment_name}",
            lines=lines,
            risk_flags=(),
            warning_accepted=False,
            source_capability=LedgerSourceCapability.INVESTMENTS,
            source_record_id=command.action_id,
        )

    async def post_investment_sale(
        self, command: PostInvestmentSaleCommand
    ) -> PostedLedgerEntry:
        _positive(command.proceeds, "LEDGER_INVALID_INPUT")
        if command.fifo_cost_basis_reduction.amount < 0:
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        if command.proceeds.currency != command.fifo_cost_basis_reduction.currency:
            raise LedgerError.invalid_input("LEDGER_CURRENCY_MISMATCH")
        gain_or_loss = (
            command.proceeds.amount - command.fifo_cost_basis_reduction.amount
        )
        lines = (
            LedgerLine(
                "1920", "Sale proceeds received in bank", command.proceeds, _ZERO
            ),
            LedgerLine(
                "1800",
                f"Cost basis reduction: {command.investment_name}",
                _ZERO,
                command.fifo_cost_basis_reduction,
            ),
        )
        if gain_or_loss > 0:
            lines += (
                LedgerLine(
                    "8070",
                    f"Share sale gain: {command.investment_name}",
                    _ZERO,
                    Money.nok(gain_or_loss),
                ),
            )
        elif gain_or_loss < 0:
            lines += (
                LedgerLine(
                    "8090",
                    f"Share sale loss: {command.investment_name}",
                    Money.nok(abs(gain_or_loss)),
                    _ZERO,
                ),
            )
        _balanced(lines)
        return await self._persistence.post_entry(
            command,
            entry_kind=LedgerEntryKind.SHARE_SALE,
            memo=f"Share sale: {command.investment_name}",
            lines=lines,
            risk_flags=(),
            warning_accepted=False,
            source_capability=LedgerSourceCapability.INVESTMENTS,
            source_record_id=command.action_id,
        )

    async def post_owner_dividend_declared(
        self, command: PostOwnerDividendDeclaredCommand
    ) -> PostedLedgerEntry:
        _positive(command.declared_amount, "LEDGER_INVALID_INPUT")
        if not command.accounting_policy_version.strip():
            raise LedgerError.precondition_failed(
                "LEDGER_OWNER_DIVIDEND_ACCOUNTING_POLICY_NOT_APPROVED"
            )
        lines = (
            LedgerLine(
                command.declaration_debit_account,
                "Declared dividend to owners",
                command.declared_amount,
                _ZERO,
            ),
            LedgerLine(
                command.dividend_payable_account,
                "Dividend payable to owners",
                _ZERO,
                command.declared_amount,
            ),
        )
        _balanced(lines)
        return await self._persistence.post_entry(
            command,
            entry_kind=LedgerEntryKind.OWNER_DIVIDEND_DECLARED,
            memo="Declared owner dividend from finalized corporate decision",
            lines=lines,
            risk_flags=(),
            warning_accepted=False,
            source_capability=LedgerSourceCapability.CORPORATE_GOVERNANCE,
            source_record_id=command.finalization_id,
            requested_entry_id=command.ledger_entry_id,
        )

    async def post_owner_dividend_payment(
        self, command: PostOwnerDividendPaymentCommand
    ) -> PostedLedgerEntry:
        _positive(command.payment_amount, "LEDGER_INVALID_INPUT")
        if not command.accounting_policy_version.strip():
            raise LedgerError.precondition_failed(
                "LEDGER_OWNER_DIVIDEND_ACCOUNTING_POLICY_NOT_APPROVED"
            )
        lines = (
            LedgerLine(
                command.dividend_payable_account,
                "Dividend payable cleared",
                command.payment_amount,
                _ZERO,
            ),
            LedgerLine(
                command.bank_account,
                "Dividend paid from bank",
                _ZERO,
                command.payment_amount,
            ),
        )
        _balanced(lines)
        return await self._persistence.post_entry(
            command,
            entry_kind=LedgerEntryKind.OWNER_DIVIDEND_PAYMENT,
            memo="Payment of finalized owner dividend payable",
            lines=lines,
            risk_flags=(),
            warning_accepted=False,
            source_capability=LedgerSourceCapability.CORPORATE_GOVERNANCE,
            source_record_id=command.payment_event_id,
            requested_entry_id=command.ledger_entry_id,
        )

    async def post_shareholder_loan(
        self, command: PostShareholderLoanCommand
    ) -> PostedLedgerEntry:
        _positive(command.amount, "LEDGER_INVALID_INPUT")
        if command.direction is ShareholderLoanDirection.SHAREHOLDER_TO_COMPANY:
            lines = (
                LedgerLine(
                    "1920",
                    f"Loan received from {command.counterparty_name}",
                    command.amount,
                    _ZERO,
                ),
                LedgerLine(
                    "2255",
                    f"Loan payable to {command.counterparty_name}",
                    _ZERO,
                    command.amount,
                ),
            )
        else:
            lines = (
                LedgerLine(
                    "1370",
                    f"Loan receivable from {command.counterparty_name}",
                    command.amount,
                    _ZERO,
                ),
                LedgerLine(
                    "1920",
                    f"Loan paid to {command.counterparty_name}",
                    _ZERO,
                    command.amount,
                ),
            )
        _balanced(lines)
        return await self._persistence.post_entry(
            command,
            entry_kind=LedgerEntryKind.SHAREHOLDER_LOAN,
            memo=f"Shareholder loan: {command.counterparty_name}",
            lines=lines,
            risk_flags=(),
            warning_accepted=False,
            source_capability=LedgerSourceCapability.CORPORATE_GOVERNANCE,
            source_record_id=command.action_id,
        )

    async def post_tax_settlement(
        self, command: PostTaxSettlementCommand
    ) -> PostedLedgerEntry:
        _positive(command.amount, "LEDGER_INVALID_INPUT")
        if command.settlement_kind is TaxSettlementKind.PAYABLE:
            lines = (
                LedgerLine("8300", "Skattekostnad", command.amount, _ZERO),
                LedgerLine("2500", "Betalbar skatt", _ZERO, command.amount),
            )
        elif command.settlement_kind is TaxSettlementKind.REFUND:
            lines = (
                LedgerLine(
                    "1920", "Skatterefusjon mottatt", command.amount, _ZERO
                ),
                LedgerLine("1570", "Skatt til gode", _ZERO, command.amount),
            )
        else:
            lines = (
                LedgerLine("2500", "Betalt skatt", command.amount, _ZERO),
                LedgerLine("1920", "Bank", _ZERO, command.amount),
            )
        _balanced(lines)
        return await self._persistence.post_entry(
            command,
            entry_kind=LedgerEntryKind.TAX_SETTLEMENT,
            memo=f"Skatteoppgjør: {command.settlement_kind.value}",
            lines=lines,
            risk_flags=(),
            warning_accepted=False,
            source_capability=LedgerSourceCapability.COMPANY_TAX_FILING,
            source_record_id=command.settlement_id,
        )

    async def post_manual_journal(
        self, command: PostManualJournalCommand
    ) -> PostedLedgerEntry:
        memo = command.memo.strip()
        if not memo:
            raise LedgerError.invalid_input("LEDGER_MEMO_REQUIRED")
        _balanced(command.lines)
        risk_flags = tuple(
            LedgerRiskFlag(
                LedgerRiskCode.MANUAL_JOURNAL_SENSITIVE_ACCOUNT,
                account,
            )
            for account in sorted(
                {line.account for line in command.lines} & _SENSITIVE_MANUAL_ACCOUNTS
            )
        )
        if risk_flags and not command.warning_accepted:
            raise LedgerError.precondition_failed("LEDGER_WARNING_ACCEPTANCE_REQUIRED")
        return await self._persistence.post_entry(
            command,
            entry_kind=LedgerEntryKind.MANUAL_JOURNAL,
            memo=memo,
            lines=command.lines,
            risk_flags=risk_flags,
            warning_accepted=command.warning_accepted,
            source_capability=LedgerSourceCapability.LEDGER,
            source_record_id=LedgerSourceRecordId(str(command.idempotency_key)),
        )

    async def lock_period(self, command: LockPeriodCommand) -> PeriodLock:
        if not command.reason.strip():
            raise LedgerError.invalid_input("LEDGER_LOCK_REASON_REQUIRED")
        return await self._persistence.lock_period(command)

    async def list_entries(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: LedgerCursor | None,
        limit: int,
    ) -> LedgerEntryPage:
        if not 1 <= limit <= 100:
            raise LedgerError.invalid_input("LEDGER_PAGE_LIMIT_INVALID")
        if not company_ids or len(company_ids) > 100:
            raise LedgerError.invalid_input("LEDGER_COMPANY_SCOPE_INVALID")
        return await self._persistence.list_entries(
            actor_id=actor_id,
            company_ids=company_ids,
            correlation_id=correlation_id,
            cursor=cursor,
            limit=limit,
        )

    async def list_period_locks(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: LedgerCursor | None,
        limit: int,
    ) -> PeriodLockPage:
        if not 1 <= limit <= 100:
            raise LedgerError.invalid_input("LEDGER_PAGE_LIMIT_INVALID")
        if not company_ids or len(company_ids) > 100:
            raise LedgerError.invalid_input("LEDGER_COMPANY_SCOPE_INVALID")
        return await self._persistence.list_period_locks(
            actor_id=actor_id,
            company_ids=company_ids,
            correlation_id=correlation_id,
            cursor=cursor,
            limit=limit,
        )
