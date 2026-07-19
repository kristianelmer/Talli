from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from holding_core.ledger import DraftEntry, LedgerLine
from holding_core.investment_lots import AcquisitionLot, LotAllocation, allocate_fifo_share_sale


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
    acquisition_lots: tuple[AcquisitionLot, ...] = ()

    @model_validator(mode="after")
    def validate_supported_tax_treatment(self) -> "InvestmentPosition":
        if self.tax_treatment == TaxTreatment.NEEDS_ACCOUNTANT:
            raise ValueError("unclear investment tax treatment needs accountant review")
        if int(self.share_count) != self.share_count:
            raise ValueError("share count must be a whole number")
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
    bank_matched: bool
    document_status: DocumentStatus
    currency: Literal["NOK"] = "NOK"

    @model_validator(mode="after")
    def validate_supported_dividend(self) -> "DividendReceivedInput":
        if self.tax_treatment != TaxTreatment.FRITAKSMETODEN:
            raise ValueError("dividend tax treatment is not supported for owner-managed filing")
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
    purchase_reference: str | None = None

    @model_validator(mode="after")
    def validate_supported_purchase(self) -> "SharePurchaseInput":
        if self.tax_treatment == TaxTreatment.NEEDS_ACCOUNTANT:
            raise ValueError("unclear share purchase tax treatment needs accountant review")
        if not self.share_count and self.ownership_percent is None:
            raise ValueError("share purchase requires share count or ownership percent")
        if int(self.share_count) != self.share_count or self.share_count <= 0:
            raise ValueError("share purchase requires a positive whole share count")
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
    acquisition_lots: tuple[AcquisitionLot, ...] = ()
    currency: Literal["NOK"] = "NOK"
    consideration_type: Literal["cash"] = "cash"

    @model_validator(mode="after")
    def validate_supported_sale(self) -> "ShareSaleInput":
        if self.position.tax_treatment == TaxTreatment.NEEDS_ACCOUNTANT:
            raise ValueError("unclear share sale tax treatment needs accountant review")
        if self.sold_share_count <= 0:
            raise ValueError("share sale requires sold shares")
        if int(self.sold_share_count) != self.sold_share_count:
            raise ValueError("sold share count must be a whole number")
        if self.sold_share_count > self.position.share_count:
            raise ValueError("share sale cannot sell more shares than the recorded position")
        return self


class ShareSaleResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry: DraftEntry
    updated_position: InvestmentPosition
    cost_basis_reduction: float
    gain_or_loss: float
    lot_allocations: tuple[LotAllocation, ...]
    updated_lots: tuple[AcquisitionLot, ...]


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
    taxable_add_back = round(data.gross_amount * 0.03, 2)
    entry = DraftEntry(
        company_id=data.company_id,
        entry_date=data.paid_date,
        memo=f"Dividend received from {data.paying_company_name}",
        source=(
            "holding_action:dividend_received:"
            f"investment:{data.linked_investment_id}:"
            f"tax:{data.tax_treatment.value}:"
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
    lot_id = data.purchase_reference or str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            ":".join(
                (
                    data.company_id,
                    data.investment_id,
                    data.acquisition_date.isoformat(),
                    str(data.share_count),
                    str(data.purchase_amount),
                )
            ),
        )
    )
    acquisition_lot = AcquisitionLot(
        id=lot_id,
        acquisition_date=data.acquisition_date,
        original_share_count=int(data.share_count),
        remaining_share_count=int(data.share_count),
        original_cost_basis=data.purchase_amount,
        remaining_cost_basis=data.purchase_amount,
    )
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
        acquisition_lots=(acquisition_lot,),
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
    lots = data.acquisition_lots or data.position.acquisition_lots
    fifo = allocate_fifo_share_sale(
        lots=lots,
        sale_date=data.sale_date,
        sold_share_count=int(data.sold_share_count),
    )
    if (
        fifo.remaining_share_count + data.sold_share_count != data.position.share_count
        or round(fifo.remaining_cost_basis + fifo.cost_basis_reduction, 2) != round(data.position.cost_basis, 2)
    ):
        raise ValueError("lot_position_mismatch: acquisition lots do not match the investment position")
    cost_reduction = fifo.cost_basis_reduction
    gain_or_loss = round(data.proceeds - cost_reduction, 2)
    updated_position = data.position.model_copy(
        update={
            "share_count": data.position.share_count - data.sold_share_count,
            "cost_basis": fifo.remaining_cost_basis,
            "acquisition_lots": fifo.updated_lots,
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
    return ShareSaleResult(
        entry=entry,
        updated_position=updated_position,
        cost_basis_reduction=cost_reduction,
        gain_or_loss=gain_or_loss,
        lot_allocations=fifo.allocations,
        updated_lots=fifo.updated_lots,
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
