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


class TaxTreatment(StrEnum):
    FRITAKSMETODEN = "fritaksmetoden"
    OUTSIDE_FRITAKSMETODEN = "outside_fritaksmetoden"
    NEEDS_ACCOUNTANT = "needs_accountant"


class ThreePercentTreatment(StrEnum):
    APPLIES = "applies"
    GROUP_EXEMPTION = "group_exemption"
    NEEDS_ACCOUNTANT = "needs_accountant"


class InvestmentKind(StrEnum):
    NORWEGIAN_PRIVATE_COMPANY = "norwegian_private_company"
    SIMPLE_LISTED_SECURITY = "simple_listed_security"


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


class InvestmentPosition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    company_id: str
    name: str
    kind: InvestmentKind
    tax_treatment: TaxTreatment
    org_number: str | None = Field(default=None, pattern=r"^\d{9}$")
    share_count: Money = 0
    ownership_percent: Money | None = None
    cost_basis: Money

    @model_validator(mode="after")
    def validate_supported_tax_treatment(self) -> "InvestmentPosition":
        if self.tax_treatment == TaxTreatment.NEEDS_ACCOUNTANT:
            raise ValueError("unclear investment tax treatment needs accountant review")
        return self


class DividendReceivedInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_id: str
    declared_date: date
    paid_date: date
    gross_amount: Money
    paying_company_name: str
    linked_investment_id: str
    tax_treatment: TaxTreatment
    three_percent_treatment: ThreePercentTreatment
    bank_matched: bool
    document_status: DocumentStatus
    currency: Literal["NOK"] = "NOK"

    @model_validator(mode="after")
    def validate_supported_dividend(self) -> "DividendReceivedInput":
        if self.tax_treatment != TaxTreatment.FRITAKSMETODEN:
            raise ValueError("dividend tax treatment is not supported for owner-managed filing")
        if self.three_percent_treatment == ThreePercentTreatment.NEEDS_ACCOUNTANT:
            raise ValueError("dividend three-percent treatment needs accountant review")
        return self


class DividendReceivedResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry: DraftEntry
    taxable_add_back: Money


class SharePurchaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_id: str
    investment_id: str
    investment_name: str
    investment_kind: InvestmentKind
    tax_treatment: TaxTreatment
    acquisition_date: date
    share_count: Money = 0
    ownership_percent: Money | None = None
    purchase_amount: Money
    bank_matched: bool
    document_status: DocumentStatus
    org_number: str | None = Field(default=None, pattern=r"^\d{9}$")
    currency: Literal["NOK"] = "NOK"
    consideration_type: Literal["cash"] = "cash"

    @model_validator(mode="after")
    def validate_supported_purchase(self) -> "SharePurchaseInput":
        if self.tax_treatment == TaxTreatment.NEEDS_ACCOUNTANT:
            raise ValueError("unclear share purchase tax treatment needs accountant review")
        if not self.share_count and self.ownership_percent is None:
            raise ValueError("share purchase requires share count or ownership percent")
        return self


class SharePurchaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry: DraftEntry
    position: InvestmentPosition


class ShareSaleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_id: str
    position: InvestmentPosition
    sale_date: date
    sold_share_count: Money
    proceeds: Money
    bank_matched: bool
    document_status: DocumentStatus
    currency: Literal["NOK"] = "NOK"
    consideration_type: Literal["cash"] = "cash"

    @model_validator(mode="after")
    def validate_supported_sale(self) -> "ShareSaleInput":
        if self.position.tax_treatment == TaxTreatment.NEEDS_ACCOUNTANT:
            raise ValueError("unclear share sale tax treatment needs accountant review")
        if self.sold_share_count <= 0:
            raise ValueError("share sale requires sold shares")
        if self.sold_share_count > self.position.share_count:
            raise ValueError("share sale cannot sell more shares than the recorded position")
        return self


class ShareSaleResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry: DraftEntry
    updated_position: InvestmentPosition
    gain_or_loss: float


class ShareholderDividendAllocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shareholder_id: str
    share_count: Money
    amount: Money


class DividendToOwnerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_id: str
    decision_date: date
    payment_date: date
    total_amount: Money
    distributable_equity: Money
    liquidity_after_payment: float
    document_status: DocumentStatus
    allocations: list[ShareholderDividendAllocation]
    share_class_count: int = 1
    payment_type: Literal["cash"] = "cash"

    @model_validator(mode="after")
    def validate_supported_owner_dividend(self) -> "DividendToOwnerInput":
        if self.share_class_count != 1:
            raise ValueError("multiple share classes are not supported for owner dividends")
        if self.payment_type != "cash":
            raise ValueError("only cash dividends are supported")
        if round(sum(allocation.amount for allocation in self.allocations), 2) != round(self.total_amount, 2):
            raise ValueError("shareholder dividend allocations must equal total dividend")
        if self.total_amount > self.distributable_equity:
            raise ValueError("dividend exceeds distributable equity")
        if self.liquidity_after_payment < 0:
            raise ValueError("dividend fails liquidity check")
        return self


class DividendToOwnerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry: DraftEntry
    board_proposal_title: str
    general_meeting_resolution_title: str


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


def build_dividend_received(data: DividendReceivedInput) -> DividendReceivedResult:
    taxable_add_back = round(data.gross_amount * 0.03, 2) if data.three_percent_treatment == ThreePercentTreatment.APPLIES else 0
    entry = DraftEntry(
        company_id=data.company_id,
        entry_date=data.paid_date,
        memo=f"Dividend received from {data.paying_company_name}",
        source=(
            "holding_action:dividend_received:"
            f"investment:{data.linked_investment_id}:"
            f"tax:{data.tax_treatment.value}:"
            f"three_percent:{data.three_percent_treatment.value}:"
            f"bank_matched:{str(data.bank_matched).lower()}:"
            f"document:{data.document_status.value}:"
            f"taxable_add_back:{taxable_add_back}"
        ),
        lines=[
            _debit(Account.BANK, "Dividend received in bank", data.gross_amount),
            _credit(Account.DIVIDEND_RECEIVED, f"Dividend from {data.paying_company_name}", data.gross_amount),
        ],
    )
    return DividendReceivedResult(entry=entry, taxable_add_back=taxable_add_back)


def build_share_purchase(data: SharePurchaseInput) -> SharePurchaseResult:
    position = InvestmentPosition(
        id=data.investment_id,
        company_id=data.company_id,
        name=data.investment_name,
        kind=data.investment_kind,
        tax_treatment=data.tax_treatment,
        org_number=data.org_number,
        share_count=data.share_count,
        ownership_percent=data.ownership_percent,
        cost_basis=data.purchase_amount,
    )
    entry = DraftEntry(
        company_id=data.company_id,
        entry_date=data.acquisition_date,
        memo=f"Share purchase: {data.investment_name}",
        source=(
            "holding_action:share_purchase:"
            f"investment:{data.investment_id}:"
            f"tax:{data.tax_treatment.value}:"
            f"bank_matched:{str(data.bank_matched).lower()}:"
            f"document:{data.document_status.value}"
        ),
        lines=[
            _debit(Account.SHARE_INVESTMENTS, f"Investment in {data.investment_name}", data.purchase_amount),
            _credit(Account.BANK, "Paid from bank", data.purchase_amount),
        ],
    )
    return SharePurchaseResult(entry=entry, position=position)


def build_share_sale(data: ShareSaleInput) -> ShareSaleResult:
    cost_reduction = round(data.position.cost_basis * (data.sold_share_count / data.position.share_count), 2)
    gain_or_loss = round(data.proceeds - cost_reduction, 2)
    updated_position = data.position.model_copy(
        update={
            "share_count": data.position.share_count - data.sold_share_count,
            "cost_basis": round(data.position.cost_basis - cost_reduction, 2),
        }
    )
    lines = [
        _debit(Account.BANK, "Sale proceeds received in bank", data.proceeds),
        _credit(Account.SHARE_INVESTMENTS, f"Cost basis reduction: {data.position.name}", cost_reduction),
    ]
    if gain_or_loss > 0:
        lines.append(_credit(Account.DIVIDEND_RECEIVED, f"Share sale gain: {data.position.name}", gain_or_loss))
    elif gain_or_loss < 0:
        lines.append(_debit(Account.TAXABLE_INCOME_ADJUSTMENT, f"Share sale loss: {data.position.name}", abs(gain_or_loss)))
    entry = DraftEntry(
        company_id=data.company_id,
        entry_date=data.sale_date,
        memo=f"Share sale: {data.position.name}",
        source=(
            "holding_action:share_sale:"
            f"investment:{data.position.id}:"
            f"tax:{data.position.tax_treatment.value}:"
            f"bank_matched:{str(data.bank_matched).lower()}:"
            f"document:{data.document_status.value}:"
            f"gain_or_loss:{gain_or_loss}"
        ),
        lines=lines,
    )
    return ShareSaleResult(entry=entry, updated_position=updated_position, gain_or_loss=gain_or_loss)


def build_dividend_to_owner(data: DividendToOwnerInput) -> DividendToOwnerResult:
    entry = DraftEntry(
        company_id=data.company_id,
        entry_date=data.payment_date,
        memo="Cash dividend paid to shareholders",
        source=(
            "holding_action:dividend_to_owner:"
            f"decision_date:{data.decision_date.isoformat()}:"
            f"document:{data.document_status.value}:"
            f"allocations:{len(data.allocations)}"
        ),
        lines=[
            _debit(Account.RETAINED_EARNINGS, "Dividend to shareholders", data.total_amount),
            _credit(Account.BANK, "Dividend paid from bank", data.total_amount),
        ],
    )
    return DividendToOwnerResult(
        entry=entry,
        board_proposal_title="Styrets forslag om utdeling av utbytte",
        general_meeting_resolution_title="Generalforsamlingens beslutning om utbytte",
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
