from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from holding_core.ledger import DraftEntry, LedgerLine


Money = Annotated[float, Field(ge=0)]


class Account(StrEnum):
    BANK = "1920"
    SHARE_INVESTMENTS = "1800"
    DIVIDEND_RECEIVED = "8070"
    TAXABLE_INCOME_ADJUSTMENT = "8090"
    SHAREHOLDER_LOAN_PAYABLE = "2255"
    SHAREHOLDER_LOAN_RECEIVABLE = "1370"
    SHARE_CAPITAL = "2000"
    RETAINED_EARNINGS = "2050"
    DIVIDEND_PAYABLE = "2800"
    BANK_FEES = "7770"
    ACCOUNTING_FEES = "6705"
    SOFTWARE = "6420"
    PUBLIC_FEES = "7790"
    LEGAL_ADVISORY = "6720"
    OTHER_ADMIN_COST = "7795"


class DocumentStatus(StrEnum):
    ATTACHED = "attached"
    MISSING_ACCEPTED_WARNING = "missing_accepted_warning"
    NOT_REQUIRED = "not_required"


class AdminCostCategory(StrEnum):
    BANK_FEE = "bank_fee"
    ACCOUNTING_FEE = "accounting_fee"
    SOFTWARE = "software"
    PUBLIC_FEE = "public_fee"
    LEGAL_ADVISORY = "legal_advisory"
    OTHER_ADMIN_COST = "other_admin_cost"


ADMIN_COST_ACCOUNT = {
    AdminCostCategory.BANK_FEE: Account.BANK_FEES,
    AdminCostCategory.ACCOUNTING_FEE: Account.ACCOUNTING_FEES,
    AdminCostCategory.SOFTWARE: Account.SOFTWARE,
    AdminCostCategory.PUBLIC_FEE: Account.PUBLIC_FEES,
    AdminCostCategory.LEGAL_ADVISORY: Account.LEGAL_ADVISORY,
    AdminCostCategory.OTHER_ADMIN_COST: Account.OTHER_ADMIN_COST,
}


class ShareholderLoanDirection(StrEnum):
    SHAREHOLDER_TO_COMPANY = "shareholder_to_company"
    COMPANY_TO_CORPORATE_SHAREHOLDER = "company_to_corporate_shareholder"
    COMPANY_TO_PERSONAL_SHAREHOLDER = "company_to_personal_shareholder"


class OpeningBalanceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_id: str
    opening_date: date
    bank_balance: Money
    share_investments: Money = 0
    shareholder_loan_payable: Money = 0
    share_capital: Money
    retained_earnings: Money = 0
    prior_annual_accounts_reference: str | None = None

    @model_validator(mode="after")
    def validate_balanced_opening(self) -> "OpeningBalanceInput":
        assets = round(self.bank_balance + self.share_investments, 2)
        equity_and_liabilities = round(self.shareholder_loan_payable + self.share_capital + self.retained_earnings, 2)
        if assets != equity_and_liabilities:
            raise ValueError("opening balance assets must equal equity and liabilities")
        return self


class AdminCostInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_id: str
    paid_date: date
    amount: Money
    payee: str
    category: AdminCostCategory
    document_status: DocumentStatus
    payment_status: Literal["paid"] = "paid"
    vat_deduction: Money = 0
    currency: Literal["NOK"] = "NOK"

    @model_validator(mode="after")
    def validate_launch_scope(self) -> "AdminCostInput":
        if self.vat_deduction:
            raise ValueError("VAT deduction is not supported for launch admin costs")
        return self


class ShareholderLoanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_id: str
    loan_date: date
    amount: Money
    direction: ShareholderLoanDirection
    counterparty_name: str
    document_status: DocumentStatus
    interest_modelled: bool = False
    currency: Literal["NOK"] = "NOK"
    related_party_security: bool = False

    @model_validator(mode="after")
    def validate_supported_loan(self) -> "ShareholderLoanInput":
        if self.direction == ShareholderLoanDirection.COMPANY_TO_PERSONAL_SHAREHOLDER:
            raise ValueError("loan from company to personal shareholder needs accountant review")
        if self.related_party_security:
            raise ValueError("related-party security or guarantee needs accountant review")
        return self


def build_opening_balance_entry(data: OpeningBalanceInput) -> DraftEntry:
    lines: list[LedgerLine] = []
    if data.bank_balance:
        lines.append(_debit(Account.BANK, "Opening bank balance", data.bank_balance))
    if data.share_investments:
        lines.append(_debit(Account.SHARE_INVESTMENTS, "Opening share investments", data.share_investments))
    if data.shareholder_loan_payable:
        lines.append(_credit(Account.SHAREHOLDER_LOAN_PAYABLE, "Opening shareholder loan payable", data.shareholder_loan_payable))
    if data.share_capital:
        lines.append(_credit(Account.SHARE_CAPITAL, "Opening share capital", data.share_capital))
    if data.retained_earnings:
        lines.append(_credit(Account.RETAINED_EARNINGS, "Opening retained earnings", data.retained_earnings))
    return DraftEntry(
        company_id=data.company_id,
        entry_date=data.opening_date,
        memo="Opening balance / new-year start",
        source="holding_action:opening_balance",
        lines=lines,
    )


def build_shareholder_loan(data: ShareholderLoanInput) -> DraftEntry:
    if data.direction == ShareholderLoanDirection.SHAREHOLDER_TO_COMPANY:
        lines = [
            _debit(Account.BANK, f"Loan received from {data.counterparty_name}", data.amount),
            _credit(Account.SHAREHOLDER_LOAN_PAYABLE, f"Loan payable to {data.counterparty_name}", data.amount),
        ]
    else:
        lines = [
            _debit(Account.SHAREHOLDER_LOAN_RECEIVABLE, f"Loan receivable from {data.counterparty_name}", data.amount),
            _credit(Account.BANK, f"Loan paid to {data.counterparty_name}", data.amount),
        ]
    return DraftEntry(
        company_id=data.company_id,
        entry_date=data.loan_date,
        memo=f"Shareholder loan: {data.counterparty_name}",
        source=(
            "holding_action:shareholder_loan:"
            f"direction:{data.direction.value}:"
            f"document:{data.document_status.value}:"
            f"interest_modelled:{str(data.interest_modelled).lower()}"
        ),
        lines=lines,
    )


def build_admin_cost_entry(data: AdminCostInput) -> DraftEntry:
    expense_account = ADMIN_COST_ACCOUNT[data.category]
    return DraftEntry(
        company_id=data.company_id,
        entry_date=data.paid_date,
        memo=f"Admin cost paid to {data.payee}",
        source=f"holding_action:admin_cost:{data.category.value}:document:{data.document_status.value}",
        lines=[
            _debit(expense_account, f"Admin cost: {data.payee}", data.amount),
            _credit(Account.BANK, "Paid from bank", data.amount),
        ],
    )


def _debit(account: Account, description: str, amount: float) -> LedgerLine:
    return LedgerLine(account=account.value, description=description, debit=amount)


def _credit(account: Account, description: str, amount: float) -> LedgerLine:
    return LedgerLine(account=account.value, description=description, credit=amount)
