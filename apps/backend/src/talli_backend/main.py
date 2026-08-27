from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Annotated, Any, Literal, TypeVar, cast
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.json_schema import SkipJsonSchema
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from talli_backend.adapters.brreg_company_registry import BrregCompanyRegistryAdapter
from talli_backend.adapters.supabase_company_access import SupabaseCompanyAccessAdapter
from talli_backend.adapters.supabase_ledger import compose_ledger_application
from talli_backend.application.ledger_workflow import (
    AcceptBankTransactionSuggestionCommand,
    FinalizeCorporateDecisionCommand,
    LedgerAuthenticationError,
    LedgerSessionFactory,
    LedgerWriterResult,
    NewYearStartCommand,
    RecordAdministrativeCostCommand,
    RecordInvestmentDividendCommand,
    RecordInvestmentPurchaseFifoCommand,
    RecordInvestmentSaleFifoCommand,
    RecordOwnerDividendPaymentCommand,
    RecordShareholderLoanCommand,
    RecordTaxSettlementCommand,
)
from talli_backend.application.opening_snapshot_compatibility import (
    LegacyOpeningSnapshotCursor,
    LegacyOpeningSnapshotPage,
    LegacyOpeningSnapshotView,
)
from talli_backend.modules.company_access.public import (
    AcceptCompanyInvitationRequest,
    AdministerCompanyMembershipRequest,
    CompanyAccessError,
    CompanyAccessGateway,
    CompanyAccessRecordResponse,
    CompanyAccessService,
    CompanyAgreementAcceptanceRequest,
    CompanyAgreementAcceptanceResponse,
    CompanyCancellationListResponse,
    CompanyCancellationResponse,
    CompanyContextResponse,
    CompanyDeletionReviewResponse,
    CompanyInvitationCommandRequest,
    CompanyInvitationListResponse,
    CompanyInvitationResponse,
    CompanyMembershipListResponse,
    CompanyMembershipResponse,
    CompanyOnboardingRequest,
    CompanyOnboardingResponse,
    CompanyRegistryGateway,
    CompanyYearAdmissionRequest,
    CompanyYearAdmissionResponse,
    CompanyYearEligibilityRecheckRequest,
    CompanyYearEligibilityStateResponse,
    CreateCompanyInvitationRequest,
    EligibilityDecisionResponse,
    EligibilityDefinitiveRequest,
    EligibilityPrecheckRequest,
    FinalizeCompanyDeletionRequest,
    InvitationLookup,
    InvitationSideEffectCompletion,
    InvitationSideEffectContinuationList,
    InvitationTokenRequest,
    OperatorCompanySearchResponse,
    OperatorContextResponse,
    RequestCompanyCancellationRequest,
    ResumeCompanyCancellationRequest,
    ReviewCompanyDeletionRequest,
)
from talli_backend.modules.ledger.public import (
    AdministrativeCostCategory,
    BankLoanMaturity,
    BankLoanReferenceId,
    BankSuggestionRule,
    CapitalIncreasePhase,
    CapitalIncreaseReferenceId,
    CapitalReductionRecognition,
    CapitalReductionReferenceId,
    CompanyYearCloseAssessment,
    CompanyYearCloseGapCode,
    CompanyYearCloseState,
    DividendDecisionReferenceId,
    InvestmentClassification,
    LedgerCursor,
    LedgerEntryId,
    LedgerEntryKind,
    LedgerEntryPage,
    LedgerEntryView,
    LedgerError,
    LedgerFactReference,
    LedgerLine,
    LedgerRiskCode,
    LedgerRiskFlag,
    LedgerSourceCapability,
    LedgerSourceRecordId,
    LockPeriodCommand,
    OpeningBalanceCategory,
    OpeningBalanceComponent,
    OpeningBankLoanComponent,
    OpeningCapitalIncreaseComponent,
    OpeningCapitalReductionComponent,
    OpeningDividendPayableComponent,
    OpeningDividendReceivableComponent,
    OpeningInvestmentComponent,
    OpeningPositionMode,
    PeriodLock,
    PeriodLockPage,
    PostedLedgerEntry,
    PostManualJournalCommand,
    ReconstructionAssessment,
    ReconstructionGapCode,
    ReconstructionState,
    ShareholderLoanDirection,
    TaxSettlementKind,
)
from talli_backend.modules.shareholder_register_filing.public import (
    OpeningShareholder,
    ShareholderRegisterFilingError,
)
from talli_backend.modules.system_boundary.public import (
    SYSTEM_BOUNDARY_AVAILABLE,
    SystemBoundaryTransport,
    adapter_for,
)
from talli_backend.shared.kernel import (
    CompanyId,
    CorrelationId,
    ErrorCategory,
    IdempotencyKey,
    IncomeYear,
    LocalDate,
    Money,
)

API_VERSION = "v1"
CONTRACT_VERSION = "1.0.0"
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
REQUEST_ID_HEADER = {
    "description": "Correlation identifier for the request and response.",
    "schema": {"type": "string"},
}
REQUEST_ID_PARAMETER = {
    "description": "Optional caller-provided correlation identifier.",
    "in": "header",
    "name": "X-Request-ID",
    "required": False,
    "schema": {"type": "string"},
}
BEARER_AUTH = HTTPBearer(scheme_name="bearerAuth", auto_error=False)
BEARER_DEPENDENCY = Depends(BEARER_AUTH)
ResponseT = TypeVar("ResponseT")


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class TransportModel(BaseModel):
    model_config = ConfigDict(alias_generator=lambda name: _to_camel(name), populate_by_name=True)


class SystemBoundaryStatus(TransportModel):
    api_version: str
    service: str
    status: Literal["AVAILABLE"]


class ProblemDetails(TransportModel):
    type: str
    title: str
    status: int
    detail: str
    instance: str
    code: str
    request_id: str


class StrictTransportModel(TransportModel):
    model_config = ConfigDict(
        alias_generator=lambda name: _to_camel(name),
        populate_by_name=True,
        extra="forbid",
    )


class LedgerMoneyWire(StrictTransportModel):
    amount: str = Field(
        max_length=64,
        pattern=r"^-?(?:0|[1-9]\d*)(?:\.\d{1,2})?$",
    )
    currency: Literal["NOK"]

    def to_domain(self) -> Money:
        return Money.nok(self.amount)


class LedgerLineWire(StrictTransportModel):
    account: str = Field(max_length=16)
    description: str = Field(max_length=500)
    debit: LedgerMoneyWire
    credit: LedgerMoneyWire

    def to_domain(self) -> LedgerLine:
        return LedgerLine(
            account=self.account,
            description=self.description,
            debit=self.debit.to_domain(),
            credit=self.credit.to_domain(),
        )


class LedgerCompanyYearWire(StrictTransportModel):
    company_id: UUID
    income_year: int = Field(ge=2000, le=2100)


class NewYearShareholderWire(StrictTransportModel):
    name: str = Field(min_length=1, max_length=255)
    shareholder_kind: Literal["norwegian_person", "norwegian_company"]
    national_id: str | None = Field(default=None, pattern=r"^\d{11}$")
    org_number: str | None = Field(default=None, pattern=r"^\d{9}$")
    share_count: int = Field(ge=0, le=2_147_483_647)


class LedgerFactReferenceWire(StrictTransportModel):
    capability: LedgerSourceCapability
    record_id: str = Field(min_length=1, max_length=255)
    revision: int = Field(ge=1)
    fact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    def to_domain(self) -> LedgerFactReference:
        return LedgerFactReference(
            capability=self.capability,
            record_id=LedgerSourceRecordId(self.record_id),
            revision=self.revision,
            fact_sha256=self.fact_sha256,
        )


class OpeningComponentWire(StrictTransportModel):
    primary_source: LedgerFactReferenceWire
    corroborating_sources: list[LedgerFactReferenceWire] = Field(min_length=1)

    def sources(self) -> tuple[LedgerFactReference, tuple[LedgerFactReference, ...]]:
        return (
            self.primary_source.to_domain(),
            tuple(source.to_domain() for source in self.corroborating_sources),
        )


class OpeningClassifiedBalanceWire(OpeningComponentWire):
    component_kind: Literal["CLASSIFIED_BALANCE"]
    category: OpeningBalanceCategory
    reference_id: str = Field(min_length=1, max_length=255)
    amount: LedgerMoneyWire

    def to_domain(self) -> OpeningBalanceComponent:
        primary, corroborating = self.sources()
        return OpeningBalanceComponent(
            category=self.category,
            reference_id=LedgerSourceRecordId(self.reference_id),
            amount=self.amount.to_domain(),
            primary_source=primary,
            corroborating_sources=corroborating,
        )


class OpeningBankLoanWire(OpeningComponentWire):
    component_kind: Literal["BANK_LOAN"]
    loan_reference_id: str = Field(min_length=1, max_length=255)
    maturity: BankLoanMaturity
    amount: LedgerMoneyWire

    def to_domain(self) -> OpeningBankLoanComponent:
        primary, corroborating = self.sources()
        return OpeningBankLoanComponent(
            loan_reference_id=BankLoanReferenceId(self.loan_reference_id),
            maturity=self.maturity,
            amount=self.amount.to_domain(),
            primary_source=primary,
            corroborating_sources=corroborating,
        )


class OpeningInvestmentWire(OpeningComponentWire):
    component_kind: Literal["INVESTMENT"]
    investment_reference_id: str = Field(min_length=1, max_length=255)
    classification: InvestmentClassification
    amount: LedgerMoneyWire

    def to_domain(self) -> OpeningInvestmentComponent:
        primary, corroborating = self.sources()
        return OpeningInvestmentComponent(
            investment_reference_id=LedgerSourceRecordId(
                self.investment_reference_id
            ),
            classification=self.classification,
            amount=self.amount.to_domain(),
            primary_source=primary,
            corroborating_sources=corroborating,
        )


class OpeningCapitalIncreaseWire(OpeningComponentWire):
    component_kind: Literal["CAPITAL_INCREASE"]
    capital_increase_reference_id: str = Field(min_length=1, max_length=255)
    phase: CapitalIncreasePhase
    nominal_increase: LedgerMoneyWire
    share_premium: LedgerMoneyWire

    def to_domain(self) -> OpeningCapitalIncreaseComponent:
        primary, corroborating = self.sources()
        return OpeningCapitalIncreaseComponent(
            capital_increase_reference_id=CapitalIncreaseReferenceId(
                self.capital_increase_reference_id
            ),
            phase=self.phase,
            nominal_increase=self.nominal_increase.to_domain(),
            share_premium=self.share_premium.to_domain(),
            primary_source=primary,
            corroborating_sources=corroborating,
        )


class OpeningCapitalReductionWire(OpeningComponentWire):
    component_kind: Literal["CAPITAL_REDUCTION"]
    capital_reduction_reference_id: str = Field(min_length=1, max_length=255)
    recognition: CapitalReductionRecognition
    nominal_reduction: LedgerMoneyWire

    def to_domain(self) -> OpeningCapitalReductionComponent:
        primary, corroborating = self.sources()
        return OpeningCapitalReductionComponent(
            capital_reduction_reference_id=CapitalReductionReferenceId(
                self.capital_reduction_reference_id
            ),
            recognition=self.recognition,
            nominal_reduction=self.nominal_reduction.to_domain(),
            primary_source=primary,
            corroborating_sources=corroborating,
        )


class OpeningDividendWire(OpeningComponentWire):
    decision_reference_id: str = Field(min_length=1, max_length=255)
    amount: LedgerMoneyWire


class OpeningDividendReceivableWire(OpeningDividendWire):
    component_kind: Literal["DIVIDEND_RECEIVABLE"]

    def to_domain(self) -> OpeningDividendReceivableComponent:
        primary, corroborating = self.sources()
        return OpeningDividendReceivableComponent(
            decision_reference_id=DividendDecisionReferenceId(
                self.decision_reference_id
            ),
            amount=self.amount.to_domain(),
            primary_source=primary,
            corroborating_sources=corroborating,
        )


class OpeningDividendPayableWire(OpeningDividendWire):
    component_kind: Literal["DIVIDEND_PAYABLE"]

    def to_domain(self) -> OpeningDividendPayableComponent:
        primary, corroborating = self.sources()
        return OpeningDividendPayableComponent(
            decision_reference_id=DividendDecisionReferenceId(
                self.decision_reference_id
            ),
            amount=self.amount.to_domain(),
            primary_source=primary,
            corroborating_sources=corroborating,
        )


OpeningPositionComponentWire = Annotated[
    OpeningClassifiedBalanceWire
    | OpeningBankLoanWire
    | OpeningInvestmentWire
    | OpeningCapitalIncreaseWire
    | OpeningCapitalReductionWire
    | OpeningDividendReceivableWire
    | OpeningDividendPayableWire,
    Field(discriminator="component_kind"),
]


class NewYearStartWire(LedgerCompanyYearWire):
    bank_balance: LedgerMoneyWire
    share_capital: LedgerMoneyWire
    share_count: int = Field(gt=0, le=2_147_483_647)
    nominal_value: LedgerMoneyWire
    shareholders: list[NewYearShareholderWire] = Field(min_length=1, max_length=100)
    opening_mode: OpeningPositionMode = OpeningPositionMode.NEW_COMPANY
    opening_basis: LedgerFactReferenceWire | None = None
    opening_components: list[OpeningPositionComponentWire] | None = None

    @model_validator(mode="after")
    def opening_fields_match_mode(self) -> NewYearStartWire:
        if self.opening_mode is OpeningPositionMode.NEW_COMPANY:
            if self.opening_basis is not None or self.opening_components is not None:
                raise ValueError("new-company opening facts are backend-owned")
        elif self.opening_basis is None or not self.opening_components:
            raise ValueError("prior-close opening facts are required")
        return self


class LedgerAdministrativeCostWire(LedgerCompanyYearWire):
    bank_transaction_id: str = Field(min_length=1, max_length=255)
    category: AdministrativeCostCategory
    payee: str = Field(min_length=1, max_length=255)
    amount: LedgerMoneyWire
    paid_date: date
    document_id: str | None = Field(default=None, min_length=1, max_length=255)


class LedgerInvestmentDividendWire(LedgerCompanyYearWire):
    action_id: UUID
    paying_company_name: str = Field(min_length=1, max_length=255)
    declared_date: date
    paid_date: date
    gross_amount: LedgerMoneyWire
    linked_investment_id: UUID | None = None
    tax_treatment: Literal[
        "fritaksmetoden", "outside_fritaksmetoden", "needs_accountant"
    ]
    bank_transaction_id: UUID | None = None
    document_id: UUID | None = None
    document_status: Literal[
        "attached", "missing_accepted_warning", "not_required"
    ]


class LedgerShareholderLoanWire(LedgerCompanyYearWire):
    action_id: UUID
    loan_date: date
    amount: LedgerMoneyWire
    direction: Literal[
        "shareholder_to_company", "company_to_corporate_shareholder"
    ]
    counterparty_name: str = Field(min_length=1, max_length=255)
    document_status: Literal[
        "attached", "missing_accepted_warning", "not_required"
    ]
    interest_modelled: bool
    related_party_security: Literal[False]
    bank_transaction_id: UUID | None = None
    document_id: UUID | None = None


class LedgerTaxSettlementWire(LedgerCompanyYearWire):
    action_id: UUID
    settlement_date: date
    amount: LedgerMoneyWire
    settlement_kind: TaxSettlementKind
    document_status: Literal[
        "attached", "missing_accepted_warning", "not_required"
    ]
    bank_transaction_id: UUID | None = None
    document_id: UUID | None = None


class LedgerBankSuggestionWire(LedgerCompanyYearWire):
    acceptance_id: UUID
    bank_transaction_id: UUID
    rule: Literal["bank_fee", "system_subscription", "deposit_interest"]
    rule_version: str = Field(min_length=1, max_length=64)


class LedgerInvestmentPurchaseWire(LedgerCompanyYearWire):
    action_id: UUID
    investment_key: str = Field(min_length=1, max_length=255)
    investment_name: str = Field(min_length=1, max_length=255)
    investment_kind: Literal["norwegian_private_company"]
    tax_treatment: Literal["fritaksmetoden"]
    acquisition_date: date
    share_count: int = Field(gt=0, le=9_007_199_254_740_991)
    purchase_amount: LedgerMoneyWire
    org_number: str | None = Field(default=None, pattern=r"^\d{9}$")
    bank_transaction_id: UUID | None = None
    document_id: UUID | None = None
    document_status: Literal[
        "attached", "missing_accepted_warning", "not_required"
    ]


class LedgerInvestmentSaleWire(LedgerCompanyYearWire):
    action_id: UUID
    position_id: UUID
    sale_date: date
    sold_share_count: int = Field(gt=0, le=9_007_199_254_740_991)
    proceeds: LedgerMoneyWire
    bank_transaction_id: UUID | None = None
    document_id: UUID | None = None
    document_status: Literal[
        "attached", "missing_accepted_warning", "not_required"
    ]


class LedgerCorporateDecisionFinalizationWire(LedgerCompanyYearWire):
    decision_id: UUID
    set_id: UUID
    decision_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    finalization_id: UUID
    holding_action_id: UUID | None = None
    ledger_entry_id: UUID | None = None

    @model_validator(mode="after")
    def optional_ids_move_together(self) -> LedgerCorporateDecisionFinalizationWire:
        if (self.holding_action_id is None) is not (self.ledger_entry_id is None):
            raise ValueError("owner-dividend identifiers must be complete")
        return self


class LedgerOwnerDividendPaymentWire(LedgerCompanyYearWire):
    decision_id: UUID
    set_id: UUID
    decision_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    bank_transaction_id: UUID
    holding_action_id: UUID
    ledger_entry_id: UUID


class LedgerManualJournalWire(LedgerCompanyYearWire):
    memo: str = Field(min_length=1, max_length=500)
    lines: list[LedgerLineWire] = Field(min_length=2, max_length=100)
    warning_accepted: bool


class LedgerLockPeriodWire(LedgerCompanyYearWire):
    reason: str = Field(min_length=1, max_length=500)


class LedgerPostedEntryWire(TransportModel):
    entry_id: str
    company_id: str
    income_year: int
    entry_kind: LedgerEntryKind
    posted_at: datetime
    replayed: bool


class NewYearOpeningEntryWire(TransportModel):
    entry_id: UUID
    company_id: UUID
    income_year: int = Field(ge=2000, le=2100)
    entry_kind: Literal["OPENING_BALANCE"]
    posted_at: datetime
    replayed: bool


class AdministrativeCostEntryWire(TransportModel):
    entry_id: UUID
    company_id: UUID
    income_year: int = Field(ge=2000, le=2100)
    entry_kind: Literal["ADMINISTRATIVE_COST"]
    posted_at: datetime
    replayed: bool


class LedgerWriterResultWire(TransportModel):
    posted_entry: LedgerPostedEntryWire | None
    replayed: bool


class NewYearStartResultWire(TransportModel):
    setup_id: UUID
    posted_entry: NewYearOpeningEntryWire


class LedgerOpeningShareholderWire(TransportModel):
    shareholder_id: UUID
    setup_id: UUID
    company_id: UUID
    name: str = Field(min_length=1, max_length=255)
    shareholder_kind: Literal["norwegian_person", "norwegian_company"]
    national_id: str | None = Field(pattern=r"^\d{11}$")
    org_number: str | None = Field(pattern=r"^\d{9}$")
    share_count: int = Field(ge=0, le=2_147_483_647)


class LedgerOpeningSnapshotWire(TransportModel):
    setup_id: UUID
    company_id: UUID
    income_year: int = Field(ge=2000, le=2100)
    bank_balance: LedgerMoneyWire
    share_capital: LedgerMoneyWire
    share_count: int = Field(gt=0, le=2_147_483_647)
    nominal_value: LedgerMoneyWire
    locked_at: datetime
    created_at: datetime
    created_by: UUID
    shareholders: list[LedgerOpeningShareholderWire] = Field(
        min_length=1, max_length=100
    )


class LedgerOpeningSnapshotPageWire(TransportModel):
    items: list[LedgerOpeningSnapshotWire] = Field(max_length=100)
    next_cursor: str | None
    has_more: bool


class LedgerRiskFlagWire(TransportModel):
    code: LedgerRiskCode
    account: str


class LedgerEntryViewWire(TransportModel):
    model_config = ConfigDict(
        json_schema_extra={
            "dependentRequired": {
                "sourceCapability": ["sourceRecordId", "createdAt"],
                "sourceRecordId": ["sourceCapability", "createdAt"],
                "createdAt": ["sourceCapability", "sourceRecordId"],
            }
        }
    )

    entry_id: str
    company_id: str
    income_year: int
    entry_kind: LedgerEntryKind
    source_capability: LedgerSourceCapability | SkipJsonSchema[None] = None
    source_record_id: str | SkipJsonSchema[None] = Field(
        default=None, min_length=1, max_length=255
    )
    created_at: datetime | SkipJsonSchema[None] = None
    memo: str
    lines: list[LedgerLineWire]
    risk_flags: list[LedgerRiskFlagWire]
    warning_accepted_by: str | None
    warning_accepted_at: datetime | None
    posted_by: str
    posted_at: datetime

    @model_validator(mode="after")
    def source_identity_is_complete(self) -> LedgerEntryViewWire:
        archive_facts = (
            self.source_capability,
            self.source_record_id,
            self.created_at,
        )
        if any(value is None for value in archive_facts) and not all(
            value is None for value in archive_facts
        ):
            raise ValueError("ledger source identity must be complete")
        return self


class LedgerPeriodLockWire(TransportModel):
    period_lock_id: str
    company_id: str
    income_year: int
    reason: str
    locked_by: str
    locked_at: datetime
    replayed: bool


class LedgerPageWire(TransportModel):
    next_cursor: str | None
    has_more: bool


class LedgerEntryPageWire(TransportModel):
    items: list[LedgerEntryViewWire]
    page: LedgerPageWire


class LedgerPeriodLockPageWire(TransportModel):
    items: list[LedgerPeriodLockWire]
    page: LedgerPageWire


class LedgerReconstructionAssessmentWire(TransportModel):
    assessment_id: UUID
    company_id: UUID
    income_year: int = Field(ge=2000, le=2100)
    as_of: date
    state: ReconstructionState
    gap_codes: list[ReconstructionGapCode]
    evidence_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    ledger_state_digest: str | None = Field(pattern=r"^[a-f0-9]{64}$")
    recorded_at: datetime


class LedgerCompanyYearCloseAssessmentWire(TransportModel):
    assessment_id: UUID
    close_lock_id: UUID | None
    reconstruction_assessment_id: UUID
    company_id: UUID
    income_year: int = Field(ge=2000, le=2100)
    period_end: date
    state: CompanyYearCloseState
    gap_codes: list[CompanyYearCloseGapCode]
    evidence_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    ledger_state_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    recorded_at: datetime
    replayed: bool
    is_current: bool


def _money_wire(value: Money) -> LedgerMoneyWire:
    return LedgerMoneyWire(amount=format(value.amount, "f"), currency=value.currency.value)


def _line_wire(value: LedgerLine) -> LedgerLineWire:
    return LedgerLineWire(
        account=value.account,
        description=value.description,
        debit=_money_wire(value.debit),
        credit=_money_wire(value.credit),
    )


def _risk_wire(value: LedgerRiskFlag) -> LedgerRiskFlagWire:
    return LedgerRiskFlagWire(code=value.code, account=value.account)


def _posted_wire(value: PostedLedgerEntry) -> LedgerPostedEntryWire:
    return LedgerPostedEntryWire(
        entry_id=str(value.entry_id),
        company_id=str(value.company_id),
        income_year=int(value.income_year),
        entry_kind=value.entry_kind,
        posted_at=value.posted_at.value,
        replayed=value.replayed,
    )


def _reconstruction_wire(
    value: ReconstructionAssessment,
) -> LedgerReconstructionAssessmentWire:
    return LedgerReconstructionAssessmentWire(
        assessment_id=str(value.assessment_id),
        company_id=str(value.company_id),
        income_year=int(value.income_year),
        as_of=value.as_of.value,
        state=value.state,
        gap_codes=list(value.gap_codes),
        evidence_digest=value.evidence_digest,
        ledger_state_digest=value.ledger_state_digest,
        recorded_at=value.recorded_at.value,
    )


def _company_year_close_wire(
    value: CompanyYearCloseAssessment,
) -> LedgerCompanyYearCloseAssessmentWire:
    return LedgerCompanyYearCloseAssessmentWire(
        assessment_id=str(value.assessment_id),
        close_lock_id=(
            str(value.close_lock_id) if value.close_lock_id is not None else None
        ),
        reconstruction_assessment_id=str(value.reconstruction_assessment_id),
        company_id=str(value.company_id),
        income_year=int(value.income_year),
        period_end=value.period_end.value,
        state=value.state,
        gap_codes=list(value.gap_codes),
        evidence_digest=value.evidence_digest,
        ledger_state_digest=value.ledger_state_digest,
        recorded_at=value.recorded_at.value,
        replayed=value.replayed,
        is_current=value.is_current,
    )


def _writer_wire(value: LedgerWriterResult) -> LedgerWriterResultWire:
    return LedgerWriterResultWire(
        posted_entry=(
            _posted_wire(value.posted_entry)
            if value.posted_entry is not None
            else None
        ),
        replayed=value.replayed,
    )


def _lock_wire(value: PeriodLock) -> LedgerPeriodLockWire:
    return LedgerPeriodLockWire(
        period_lock_id=str(value.period_lock_id),
        company_id=str(value.company_id),
        income_year=int(value.income_year),
        reason=value.reason,
        locked_by=str(value.locked_by.subject),
        locked_at=value.locked_at.value,
        replayed=value.replayed,
    )


def _opening_snapshot_wire(
    value: LegacyOpeningSnapshotView,
) -> LedgerOpeningSnapshotWire:
    return LedgerOpeningSnapshotWire(
        setup_id=str(value.setup_id),
        company_id=str(value.company_id),
        income_year=int(value.income_year),
        bank_balance=_money_wire(value.bank_balance),
        share_capital=_money_wire(value.share_capital),
        share_count=value.share_count,
        nominal_value=_money_wire(value.nominal_value),
        locked_at=value.locked_at.value,
        created_at=value.created_at.value,
        created_by=str(value.created_by.subject),
        shareholders=[
            LedgerOpeningShareholderWire(
                shareholder_id=item.shareholder_id,
                setup_id=str(item.setup_id),
                company_id=str(item.company_id),
                name=item.name,
                shareholder_kind=item.shareholder_kind,
                national_id=item.national_id,
                org_number=item.org_number,
                share_count=item.share_count,
            )
            for item in value.shareholders
        ],
    )


def _entry_view_wire(
    value: LedgerEntryView, *, include_source: bool
) -> LedgerEntryViewWire:
    if include_source and (
        value.source_capability is None
        or value.source_record_id is None
        or value.created_at is None
    ):
        raise LedgerError.unavailable()
    source = (
        {
            "source_capability": value.source_capability,
            "source_record_id": str(value.source_record_id),
            "created_at": value.created_at.value,
        }
        if include_source
        else {}
    )
    return LedgerEntryViewWire(
        entry_id=str(value.entry_id),
        company_id=str(value.company_id),
        income_year=int(value.income_year),
        entry_kind=value.entry_kind,
        **source,
        memo=value.memo,
        lines=[_line_wire(line) for line in value.lines],
        risk_flags=[_risk_wire(flag) for flag in value.risk_flags],
        warning_accepted_by=(
            str(value.warning_accepted_by.subject)
            if value.warning_accepted_by is not None
            else None
        ),
        warning_accepted_at=(
            value.warning_accepted_at.value
            if value.warning_accepted_at is not None
            else None
        ),
        posted_by=str(value.posted_by.subject),
        posted_at=value.posted_at.value,
    )


class ApiProblem(Exception):
    def __init__(self, *, status: int, code: str, title: str, detail: str) -> None:
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail


def _request_id(request: Request) -> str:
    candidate = request.headers.get("X-Request-ID", "")
    return candidate if REQUEST_ID_PATTERN.fullmatch(candidate) else str(uuid4())


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.request_id = _request_id(request)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response


def _problem_response(
    request: Request,
    *,
    status: int,
    code: str,
    title: str,
    detail: str,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", _request_id(request))
    problem = ProblemDetails(
        type=f"https://talli.no/problems/{code.lower().replace('_', '-')}",
        title=title,
        status=status,
        detail=detail,
        instance=request.url.path,
        code=code,
        request_id=request_id,
    )
    return JSONResponse(
        status_code=status,
        content=problem.model_dump(by_alias=True),
        media_type="application/problem+json",
        headers={"X-Request-ID": request_id},
    )


@adapter_for(SystemBoundaryTransport)
def create_app(
    company_access_gateway: CompanyAccessGateway | None = None,
    company_registry_gateway: CompanyRegistryGateway | None = None,
    ledger_session_factory: LedgerSessionFactory | None = None,
) -> FastAPI:
    application = FastAPI(
        title="Talli API",
        summary="Talli web-to-backend production boundary",
        version=CONTRACT_VERSION,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )
    application.add_middleware(RequestIdMiddleware)
    gateway = (
        company_access_gateway
        if company_access_gateway is not None
        else SupabaseCompanyAccessAdapter.from_environment()
    )
    company_access_service = CompanyAccessService(
        gateway,
        company_registry_gateway or BrregCompanyRegistryAdapter.from_environment(),
    )
    ledger_application = compose_ledger_application(ledger_session_factory)

    def bearer_token(
        credentials: HTTPAuthorizationCredentials | None,
    ) -> str:
        if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
            raise ApiProblem(
                status=401,
                code="AUTHENTICATION_REQUIRED",
                title="Authentication required",
                detail="A valid session is required.",
            )
        return credentials.credentials

    async def company_access_call(call: Awaitable[ResponseT]) -> ResponseT:
        try:
            return await call
        except CompanyAccessError as error:
            raise ApiProblem(
                status=error.status,
                code=error.code,
                title=error.title,
                detail=error.detail,
            ) from None

    async def ledger_call(call: Callable[[], Awaitable[ResponseT]]) -> ResponseT:
        try:
            return await call()
        except LedgerAuthenticationError:
            raise ApiProblem(
                status=401,
                code="AUTHENTICATION_REQUIRED",
                title="Authentication required",
                detail="A valid session is required.",
            ) from None
        except LedgerError as error:
            statuses = {
                ErrorCategory.INVALID_INPUT: 422,
                ErrorCategory.NOT_FOUND: 404,
                ErrorCategory.CONFLICT: 409,
                ErrorCategory.FORBIDDEN: 403,
                ErrorCategory.PRECONDITION_FAILED: 409,
                ErrorCategory.DEPENDENCY_UNAVAILABLE: 503,
            }
            raise ApiProblem(
                status=statuses[error.category],
                code=error.code,
                title="Ledger request failed",
                detail=error.message or "The ledger request could not be completed.",
            ) from None
        except ShareholderRegisterFilingError as error:
            statuses = {
                ErrorCategory.INVALID_INPUT: 422,
                ErrorCategory.NOT_FOUND: 404,
                ErrorCategory.CONFLICT: 409,
                ErrorCategory.FORBIDDEN: 403,
                ErrorCategory.PRECONDITION_FAILED: 409,
                ErrorCategory.DEPENDENCY_UNAVAILABLE: 503,
            }
            raise ApiProblem(
                status=statuses[error.category],
                code=error.code,
                title="New-year request failed",
                detail=error.message or "The opening snapshot could not be recorded.",
            ) from None

    def ledger_input(factory: Callable[[], ResponseT]) -> ResponseT:
        try:
            return factory()
        except (TypeError, ValueError, ShareholderRegisterFilingError):
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT") from None

    @application.exception_handler(ApiProblem)
    async def api_problem_handler(request: Request, error: ApiProblem) -> JSONResponse:
        return _problem_response(
            request,
            status=error.status,
            code=error.code,
            title=error.title,
            detail=error.detail,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        _error: RequestValidationError,
    ) -> JSONResponse:
        return _problem_response(
            request,
            status=422,
            code="REQUEST_VALIDATION_FAILED",
            title="Request validation failed",
            detail="The request did not satisfy the API contract.",
        )

    @application.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        request: Request,
        error: StarletteHTTPException,
    ) -> JSONResponse:
        definitions = {
            404: ("RESOURCE_NOT_FOUND", "Resource not found", "The requested resource does not exist."),
            405: ("METHOD_NOT_ALLOWED", "Method not allowed", "The request method is not supported."),
        }
        code, title, detail = definitions.get(
            error.status_code,
            ("HTTP_ERROR", "Request failed", "The request could not be completed."),
        )
        return _problem_response(
            request,
            status=error.status_code,
            code=code,
            title=title,
            detail=detail,
        )

    @application.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, _error: Exception) -> JSONResponse:
        return _problem_response(
            request,
            status=500,
            code="INTERNAL_SERVER_ERROR",
            title="Internal server error",
            detail="An unexpected error occurred.",
        )

    @application.get(
        "/api/v1/system-boundary/tracer",
        operation_id="systemBoundaryGetTracerStatus",
        response_model=SystemBoundaryStatus,
        responses={
            200: {
                "description": "Successful Response",
                "headers": {"X-Request-ID": REQUEST_ID_HEADER},
            },
            500: {
                "description": "An unexpected backend failure occurred.",
                "headers": {"X-Request-ID": REQUEST_ID_HEADER},
                "content": {
                    "application/problem+json": {
                        "schema": ProblemDetails.model_json_schema(by_alias=True)
                    }
                },
            },
            503: {
                "description": "The backend boundary is temporarily unavailable.",
                "headers": {"X-Request-ID": REQUEST_ID_HEADER},
                "content": {
                    "application/problem+json": {
                        "schema": ProblemDetails.model_json_schema(by_alias=True)
                    }
                },
            }
        },
        tags=["system-boundary"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def get_system_boundary_status() -> SystemBoundaryStatus:
        return SystemBoundaryStatus(
            api_version=API_VERSION,
            service="talli-backend",
            status=SYSTEM_BOUNDARY_AVAILABLE,
        )

    @application.get(
        "/api/v1/company-access/context",
        operation_id="companyAccessGetSelectedContext",
        response_model=CompanyContextResponse,
        responses=cast(
            dict[int | str, dict[str, Any]],
            (
            {
                200: {
                    "description": "Selected company context.",
                    "headers": {"X-Request-ID": REQUEST_ID_HEADER},
                }
            }
            | {
                status: {
                    "description": "Company context request failed.",
                    "headers": {"X-Request-ID": REQUEST_ID_HEADER},
                    "content": {
                        "application/problem+json": {
                            "schema": ProblemDetails.model_json_schema(by_alias=True)
                        }
                    },
                }
                for status in (401, 403, 404, 422, 503)
            }
            ),
        ),
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def get_selected_company_context(
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
        company_id: str | None = None,
    ) -> CompanyContextResponse:
        return await company_access_call(
            company_access_service.selected_context(
                bearer_token(credentials),
                company_id=company_id,
            )
        )

    company_access_errors: Any = {
        status: {
            "description": "Company access request failed.",
            "headers": {"X-Request-ID": REQUEST_ID_HEADER},
            "content": {
                "application/problem+json": {
                    "schema": ProblemDetails.model_json_schema(by_alias=True)
                }
            },
        }
        for status in (401, 403, 404, 409, 422, 503)
    }
    company_access_success: dict[str, Any] = {
        "headers": {"X-Request-ID": REQUEST_ID_HEADER}
    }

    @application.post(
        "/api/v1/company-access/eligibility/precheck",
        operation_id="companyAccessEligibilityPrecheck",
        response_model=EligibilityDecisionResponse,
        responses={
            200: {
                "description": "Provisional public-company eligibility result",
                "headers": {"X-Request-ID": REQUEST_ID_HEADER},
            }
        }
        | {status: company_access_errors[status] for status in (404, 422, 503)},
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def eligibility_precheck(
        command: EligibilityPrecheckRequest,
    ) -> EligibilityDecisionResponse:
        return await company_access_call(
            company_access_service.eligibility_precheck(command)
        )

    @application.post(
        "/api/v1/company-access/eligibility/definitive",
        operation_id="companyAccessEligibilityDefinitive",
        response_model=EligibilityDecisionResponse,
        responses={
            200: {
                "description": "Definitive company-year eligibility result",
                "headers": {"X-Request-ID": REQUEST_ID_HEADER},
            }
        }
        | {status: company_access_errors[status] for status in (409, 422, 503)},
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def eligibility_definitive(
        command: EligibilityDefinitiveRequest,
    ) -> EligibilityDecisionResponse:
        return await company_access_call(
            company_access_service.eligibility_definitive(command)
        )

    @application.post(
        "/api/v1/company-access/company-year-admissions",
        operation_id="companyAccessAdmitCompanyYear",
        response_model=CompanyYearAdmissionResponse,
        status_code=201,
        responses={
            201: {
                "description": "Company year admitted",
                "headers": {"X-Request-ID": REQUEST_ID_HEADER},
            }
        }
        | {status: company_access_errors[status] for status in (401, 409, 422, 503)},
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def admit_company_year(
        command: CompanyYearAdmissionRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyYearAdmissionResponse:
        return await company_access_call(
            company_access_service.admit_company_year(
                bearer_token(credentials), command
            )
        )

    @application.post(
        (
            "/api/v1/company-access/company-year-admissions/"
            "{company_year_admission_id}/eligibility-rechecks"
        ),
        operation_id="companyAccessRecheckCompanyYearEligibility",
        response_model=CompanyYearEligibilityStateResponse,
        status_code=201,
        responses={
            201: {
                "description": "Current eligibility gate appended",
                "headers": {"X-Request-ID": REQUEST_ID_HEADER},
            }
        }
        | {status: company_access_errors[status] for status in (401, 404, 409, 422, 503)},
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def recheck_company_year_eligibility(
        company_year_admission_id: UUID,
        command: CompanyYearEligibilityRecheckRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyYearEligibilityStateResponse:
        return await company_access_call(
            company_access_service.recheck_company_year_eligibility(
                bearer_token(credentials), company_year_admission_id, command
            )
        )

    @application.post(
        "/api/v1/company-access/onboarding",
        operation_id="companyAccessOnboardCompany",
        response_model=CompanyOnboardingResponse,
        status_code=201,
        deprecated=True,
        responses={
            201: {"description": "Company and current agreement evidence created atomically."}
            | company_access_success
        }
        | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def onboard_company(
        command: CompanyOnboardingRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyOnboardingResponse:
        return await company_access_call(
            company_access_service.onboard_company(bearer_token(credentials), command)
        )

    @application.post(
        "/api/v1/company-access/agreements/reaccept",
        operation_id="companyAccessReacceptAgreement",
        response_model=CompanyAgreementAcceptanceResponse,
        responses={
            200: {"description": "Current agreement evidence accepted."}
            | company_access_success
        }
        | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def reaccept_company_agreement(
        command: CompanyAgreementAcceptanceRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyAgreementAcceptanceResponse:
        return await company_access_call(
            company_access_service.reaccept_agreement(
                bearer_token(credentials), command
            )
        )

    @application.get(
        "/api/v1/company-access/companies/{company_id}",
        operation_id="companyAccessGetCompanyRecord",
        response_model=CompanyAccessRecordResponse,
        responses={200: {"description": "Accepted-member company record."} | company_access_success}
        | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def get_company_access_record(
        company_id: str,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyAccessRecordResponse:
        return await company_access_call(
            company_access_service.company_record(
                bearer_token(credentials), company_id=company_id
            )
        )

    @application.get(
        "/api/v1/company-access/operator-context",
        operation_id="companyAccessGetOperatorContext",
        response_model=OperatorContextResponse,
        responses={200: {"description": "Active operator context."} | company_access_success}
        | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def get_company_access_operator_context(
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> OperatorContextResponse:
        return await company_access_call(
            company_access_service.operator_context(bearer_token(credentials))
        )

    @application.get(
        "/api/v1/company-access/operator-companies",
        operation_id="companyAccessSearchOperatorCompanies",
        response_model=OperatorCompanySearchResponse,
        responses={200: {"description": "Bounded operator company search."} | company_access_success}
        | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def search_company_access_operator_companies(
        query: str,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> OperatorCompanySearchResponse:
        return await company_access_call(
            company_access_service.search_operator_companies(
                bearer_token(credentials), query=query
            )
        )

    @application.get(
        "/api/v1/company-access/invitations",
        operation_id="companyAccessListInvitations",
        response_model=CompanyInvitationListResponse,
        responses={200: {"description": "Company invitations."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def list_company_invitations(
        company_id: str,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyInvitationListResponse:
        return await company_access_call(
            company_access_service.list_invitations(
                bearer_token(credentials), company_id=company_id
            )
        )

    @application.post(
        "/api/v1/company-access/invitations",
        operation_id="companyAccessCreateInvitation",
        response_model=CompanyInvitationResponse,
        status_code=201,
        responses={201: {"description": "Company invitation created."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def create_company_invitation(
        command: CreateCompanyInvitationRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyInvitationResponse:
        return await company_access_call(
            company_access_service.invite(bearer_token(credentials), command)
        )

    @application.post(
        "/api/v1/company-access/invitations/lookup",
        operation_id="companyAccessLookupInvitation",
        response_model=InvitationLookup,
        responses={200: {"description": "Available invitation."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def lookup_company_invitation(
        command: InvitationTokenRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> InvitationLookup:
        return await company_access_call(
            company_access_service.lookup_invitation(
                bearer_token(credentials), token=command.token
            )
        )

    @application.post(
        "/api/v1/company-access/invitations/accept",
        operation_id="companyAccessAcceptInvitation",
        response_model=CompanyMembershipResponse,
        responses={200: {"description": "Invitation accepted."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def accept_company_invitation(
        command: AcceptCompanyInvitationRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyMembershipResponse:
        return await company_access_call(
            company_access_service.accept_invitation(bearer_token(credentials), command)
        )

    @application.post(
        "/api/v1/company-access/invitations/{invitation_id}/revoke",
        operation_id="companyAccessRevokeInvitation",
        response_model=CompanyInvitationResponse,
        responses={200: {"description": "Invitation revoked."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def revoke_company_invitation(
        invitation_id: UUID,
        command: CompanyInvitationCommandRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyInvitationResponse:
        return await company_access_call(
            company_access_service.revoke_invitation(
                bearer_token(credentials),
                invitation_id=invitation_id,
                command=command,
            )
        )

    @application.post(
        "/api/v1/company-access/invitations/{invitation_id}/resend",
        operation_id="companyAccessResendInvitation",
        response_model=CompanyInvitationResponse,
        responses={200: {"description": "Invitation resent."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def resend_company_invitation(
        invitation_id: UUID,
        command: CompanyInvitationCommandRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyInvitationResponse:
        return await company_access_call(
            company_access_service.resend_invitation(
                bearer_token(credentials),
                invitation_id=invitation_id,
                command=command,
            )
        )

    @application.get(
        "/api/v1/company-access/invitation-side-effects/pending",
        operation_id="companyAccessListPendingInvitationSideEffects",
        response_model=InvitationSideEffectContinuationList,
        responses={200: {"description": "Pending invitation side effects."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def list_pending_invitation_side_effects(
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> InvitationSideEffectContinuationList:
        return await company_access_call(
            company_access_service.pending_invitation_side_effects(
                bearer_token(credentials)
            )
        )

    @application.post(
        "/api/v1/company-access/invitation-side-effects/{operation_id}/complete",
        operation_id="companyAccessCompleteInvitationSideEffect",
        response_model=InvitationSideEffectCompletion,
        responses={200: {"description": "Invitation side effects completed."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def complete_invitation_side_effect(
        operation_id: UUID,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> InvitationSideEffectCompletion:
        return await company_access_call(
            company_access_service.complete_invitation_side_effect(
                bearer_token(credentials), operation_id
            )
        )

    @application.get(
        "/api/v1/company-access/memberships",
        operation_id="companyAccessListMemberships",
        response_model=CompanyMembershipListResponse,
        responses={200: {"description": "Company memberships."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def list_company_memberships(
        company_id: str,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyMembershipListResponse:
        return await company_access_call(
            company_access_service.list_memberships(
                bearer_token(credentials), company_id=company_id
            )
        )

    @application.patch(
        "/api/v1/company-access/memberships/{user_id}",
        operation_id="companyAccessAdministerMembership",
        response_model=CompanyMembershipResponse,
        responses={200: {"description": "Membership changed."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def administer_company_membership(
        user_id: UUID,
        command: AdministerCompanyMembershipRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyMembershipResponse:
        return await company_access_call(
            company_access_service.administer_membership(
                bearer_token(credentials),
                user_id=user_id,
                command=command,
            )
        )

    @application.get(
        "/api/v1/company-access/cancellations",
        operation_id="companyAccessListCancellations",
        response_model=CompanyCancellationListResponse,
        responses={200: {"description": "Visible company cancellation lifecycle records."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def list_company_cancellations(
        company_id: UUID,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyCancellationListResponse:
        return await company_access_call(
            company_access_service.list_cancellations(
                bearer_token(credentials), company_id=str(company_id)
            )
        )

    @application.post(
        "/api/v1/company-access/cancellations",
        operation_id="companyAccessRequestCancellation",
        response_model=CompanyCancellationResponse,
        status_code=201,
        responses={201: {"description": "Cancellation entered retention hold."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def request_company_cancellation(
        command: RequestCompanyCancellationRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyCancellationResponse:
        return await company_access_call(
            company_access_service.request_cancellation(bearer_token(credentials), command)
        )

    @application.post(
        "/api/v1/company-access/cancellations/{cancellation_id}/reviews",
        operation_id="companyAccessReviewDeletion",
        response_model=CompanyDeletionReviewResponse,
        responses={200: {"description": "Append-only deletion review recorded."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def review_company_deletion(
        cancellation_id: UUID,
        command: ReviewCompanyDeletionRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyDeletionReviewResponse:
        return await company_access_call(
            company_access_service.review_deletion(
                bearer_token(credentials), cancellation_id, command
            )
        )

    @application.post(
        "/api/v1/company-access/cancellations/{cancellation_id}/resume",
        operation_id="companyAccessResumeCancellation",
        response_model=CompanyCancellationResponse,
        responses={200: {"description": "Legacy cancellation advanced after authoritative archive export."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def resume_company_cancellation(
        cancellation_id: UUID,
        command: ResumeCompanyCancellationRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyCancellationResponse:
        return await company_access_call(
            company_access_service.resume_cancellation(
                bearer_token(credentials), cancellation_id, command
            )
        )

    @application.post(
        "/api/v1/company-access/cancellations/{cancellation_id}/finalize",
        operation_id="companyAccessFinalizeDeletion",
        response_model=CompanyCancellationResponse,
        responses={200: {"description": "Deletion lifecycle finalized without physical business-data deletion."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def finalize_company_deletion(
        cancellation_id: UUID,
        command: FinalizeCompanyDeletionRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyCancellationResponse:
        return await company_access_call(
            company_access_service.finalize_deletion(
                bearer_token(credentials), cancellation_id, command
            )
        )

    ledger_errors: Any = {
        status: {
            "description": "Ledger request failed.",
            "headers": {"X-Request-ID": REQUEST_ID_HEADER},
            "content": {
                "application/problem+json": {
                    "schema": ProblemDetails.model_json_schema(by_alias=True)
                }
            },
        }
        for status in (400, 401, 403, 404, 409, 422, 503)
    }
    ledger_success: dict[str, Any] = {
        "headers": {"X-Request-ID": REQUEST_ID_HEADER}
    }

    def ledger_correlation(request: Request) -> CorrelationId:
        return CorrelationId(request.state.request_id)

    def ledger_writer_wire(
        result: LedgerWriterResult,
        *,
        company_id: UUID,
        income_year: int,
        expected_kind: LedgerEntryKind | None,
    ) -> LedgerWriterResultWire:
        posted = result.posted_entry
        if expected_kind is None:
            if posted is not None:
                raise LedgerError.unavailable()
        elif (
            posted is None
            or str(posted.company_id) != str(company_id)
            or int(posted.income_year) != income_year
            or posted.entry_kind is not expected_kind
        ):
            raise LedgerError.unavailable()
        return _writer_wire(result)

    @application.get(
        "/api/v1/ledger/reconstruction-assessment",
        operation_id="ledgerGetReconstructionAssessment",
        response_model=LedgerReconstructionAssessmentWire,
        responses={
            200: {"description": "Latest immutable reconstruction assessment."}
            | ledger_success
        }
        | ledger_errors,
        tags=["ledger"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def get_ledger_reconstruction_assessment(
        request: Request,
        company_id: Annotated[UUID, Query(alias="companyId")],
        income_year: Annotated[int, Query(alias="incomeYear", ge=2000, le=2100)],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> LedgerReconstructionAssessmentWire:
        async def execute() -> LedgerReconstructionAssessmentWire:
            session = await ledger_application.session(bearer_token(credentials))
            assessment = await session.get_reconstruction_assessment(
                actor_id=session.actor_id,
                company_id=CompanyId(str(company_id)),
                income_year=IncomeYear(income_year),
                correlation_id=ledger_correlation(request),
            )
            return _reconstruction_wire(assessment)

        return await ledger_call(execute)

    @application.get(
        "/api/v1/ledger/company-year-close-assessment",
        operation_id="ledgerGetCompanyYearCloseAssessment",
        response_model=LedgerCompanyYearCloseAssessmentWire,
        responses={
            200: {"description": "Latest immutable company-year close assessment."}
            | ledger_success
        }
        | ledger_errors,
        tags=["ledger"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def get_ledger_company_year_close_assessment(
        request: Request,
        company_id: Annotated[UUID, Query(alias="companyId")],
        income_year: Annotated[int, Query(alias="incomeYear", ge=2000, le=2100)],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> LedgerCompanyYearCloseAssessmentWire:
        async def execute() -> LedgerCompanyYearCloseAssessmentWire:
            session = await ledger_application.session(bearer_token(credentials))
            assessment = await session.get_company_year_close_assessment(
                actor_id=session.actor_id,
                company_id=CompanyId(str(company_id)),
                income_year=IncomeYear(income_year),
                correlation_id=ledger_correlation(request),
            )
            return _company_year_close_wire(assessment)

        return await ledger_call(execute)

    @application.get(
        "/api/v1/ledger/entries",
        operation_id="ledgerListEntries",
        response_model=LedgerEntryPageWire,
        response_model_exclude_unset=True,
        responses={200: {"description": "Authorized ledger-entry page."} | ledger_success}
        | ledger_errors,
        tags=["ledger"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def list_ledger_entries(
        request: Request,
        company_id: Annotated[
            list[UUID], Query(alias="companyId", min_length=1, max_length=100)
        ],
        cursor: Annotated[str | None, Query(max_length=4096)] = None,
        limit: int = Query(default=50, ge=1, le=100),
        include_source: Annotated[bool, Query(alias="includeSource")] = False,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> LedgerEntryPageWire:
        async def execute() -> LedgerEntryPageWire:
            session = await ledger_application.session(bearer_token(credentials))
            page: LedgerEntryPage = await session.list_entries(
                actor_id=session.actor_id,
                company_ids=ledger_input(
                    lambda: tuple(CompanyId(str(value)) for value in company_id)
                ),
                correlation_id=ledger_correlation(request),
                cursor=ledger_input(lambda: LedgerCursor(cursor)) if cursor else None,
                limit=limit,
            )
            return LedgerEntryPageWire(
                items=[
                    _entry_view_wire(item, include_source=include_source)
                    for item in page.items
                ],
                page=LedgerPageWire(
                    next_cursor=(
                        str(page.page.next_cursor)
                        if page.page.next_cursor is not None
                        else None
                    ),
                    has_more=page.page.has_more,
                ),
            )

        return await ledger_call(execute)

    @application.get(
        "/api/v1/ledger/opening-snapshots",
        operation_id="ledgerListOpeningSnapshots",
        response_model=LedgerOpeningSnapshotPageWire,
        responses={
            200: {"description": "Authorized legacy opening-snapshot projection."}
            | ledger_success
        }
        | ledger_errors,
        tags=["ledger"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def list_opening_snapshots(
        request: Request,
        company_id: Annotated[
            list[UUID], Query(alias="companyId", min_length=1, max_length=100)
        ],
        cursor: Annotated[str | None, Query(max_length=4096)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 100,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> LedgerOpeningSnapshotPageWire:
        async def execute() -> LedgerOpeningSnapshotPageWire:
            session = await ledger_application.session(bearer_token(credentials))
            snapshots: LegacyOpeningSnapshotPage = await session.list_opening_snapshots(
                actor_id=session.actor_id,
                company_ids=ledger_input(
                    lambda: tuple(CompanyId(str(value)) for value in company_id)
                ),
                correlation_id=ledger_correlation(request),
                cursor=(
                    ledger_input(lambda: LegacyOpeningSnapshotCursor(cursor))
                    if cursor
                    else None
                ),
                limit=limit,
            )
            return LedgerOpeningSnapshotPageWire(
                items=[_opening_snapshot_wire(item) for item in snapshots.items],
                next_cursor=(
                    str(snapshots.next_cursor)
                    if snapshots.next_cursor is not None
                    else None
                ),
                has_more=snapshots.has_more,
            )

        return await ledger_call(execute)

    @application.get(
        "/api/v1/ledger/period-locks",
        operation_id="ledgerListPeriodLocks",
        response_model=LedgerPeriodLockPageWire,
        responses={200: {"description": "Authorized period-lock page."} | ledger_success}
        | ledger_errors,
        tags=["ledger"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def list_ledger_period_locks(
        request: Request,
        company_id: Annotated[
            list[UUID], Query(alias="companyId", min_length=1, max_length=100)
        ],
        cursor: Annotated[str | None, Query(max_length=4096)] = None,
        limit: int = Query(default=50, ge=1, le=100),
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> LedgerPeriodLockPageWire:
        async def execute() -> LedgerPeriodLockPageWire:
            session = await ledger_application.session(bearer_token(credentials))
            page: PeriodLockPage = await session.list_period_locks(
                actor_id=session.actor_id,
                company_ids=ledger_input(
                    lambda: tuple(CompanyId(str(value)) for value in company_id)
                ),
                correlation_id=ledger_correlation(request),
                cursor=ledger_input(lambda: LedgerCursor(cursor)) if cursor else None,
                limit=limit,
            )
            return LedgerPeriodLockPageWire(
                items=[_lock_wire(item) for item in page.items],
                page=LedgerPageWire(
                    next_cursor=(
                        str(page.page.next_cursor)
                        if page.page.next_cursor is not None
                        else None
                    ),
                    has_more=page.page.has_more,
                ),
            )

        return await ledger_call(execute)

    @application.post(
        "/api/v1/new-year-starts",
        operation_id="ledgerStartNewYear",
        response_model=NewYearStartResultWire,
        status_code=201,
        responses={201: {"description": "Company year started atomically."} | ledger_success}
        | ledger_errors,
        tags=["ledger"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def start_new_year(
        request: Request,
        command: NewYearStartWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> NewYearStartResultWire:
        async def execute() -> NewYearStartResultWire:
            session = await ledger_application.session(bearer_token(credentials))
            domain_command = ledger_input(
                lambda: NewYearStartCommand(
                    company_id=CompanyId(str(command.company_id)),
                    actor_id=session.actor_id,
                    correlation_id=ledger_correlation(request),
                    idempotency_key=IdempotencyKey(idempotency_key),
                    income_year=IncomeYear(command.income_year),
                    bank_balance=command.bank_balance.to_domain(),
                    share_capital=command.share_capital.to_domain(),
                    share_count=command.share_count,
                    nominal_value=command.nominal_value.to_domain(),
                    shareholders=tuple(
                        OpeningShareholder(
                            name=shareholder.name,
                            shareholder_kind=shareholder.shareholder_kind,
                            national_id=shareholder.national_id,
                            org_number=shareholder.org_number,
                            share_count=shareholder.share_count,
                        )
                        for shareholder in command.shareholders
                    ),
                    opening_mode=command.opening_mode,
                    opening_basis=(
                        command.opening_basis.to_domain()
                        if command.opening_basis is not None
                        else None
                    ),
                    opening_components=tuple(
                        component.to_domain()
                        for component in (command.opening_components or ())
                    ),
                )
            )
            result = await session.start_new_year(domain_command)
            return NewYearStartResultWire(
                setup_id=str(result.setup_id),
                posted_entry=NewYearOpeningEntryWire(
                    entry_id=str(result.posted_entry.entry_id),
                    company_id=str(result.posted_entry.company_id),
                    income_year=int(result.posted_entry.income_year),
                    entry_kind="OPENING_BALANCE",
                    posted_at=result.posted_entry.posted_at.value,
                    replayed=result.posted_entry.replayed,
                ),
            )

        return await ledger_call(execute)

    @application.post(
        "/api/v1/ledger/administrative-costs",
        operation_id="ledgerPostAdministrativeCost",
        response_model=AdministrativeCostEntryWire,
        status_code=201,
        responses={201: {"description": "Administrative cost posted."} | ledger_success}
        | ledger_errors,
        tags=["ledger"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def post_ledger_administrative_cost(
        request: Request,
        command: LedgerAdministrativeCostWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> AdministrativeCostEntryWire:
        async def execute() -> AdministrativeCostEntryWire:
            session = await ledger_application.session(bearer_token(credentials))
            domain_command = ledger_input(
                lambda: RecordAdministrativeCostCommand(
                    company_id=CompanyId(str(command.company_id)),
                    actor_id=session.actor_id,
                    correlation_id=ledger_correlation(request),
                    idempotency_key=IdempotencyKey(idempotency_key),
                    income_year=IncomeYear(command.income_year),
                    bank_transaction_id=LedgerSourceRecordId(command.bank_transaction_id),
                    category=command.category,
                    payee=command.payee,
                    amount=command.amount.to_domain(),
                    paid_date=LocalDate(command.paid_date),
                    document_id=(
                        LedgerSourceRecordId(command.document_id)
                        if command.document_id is not None
                        else None
                    ),
                )
            )
            workflow = await session.record_administrative_cost(domain_command)
            result = workflow.posted_entry
            if (
                result is None
                or result.company_id != domain_command.company_id
                or result.income_year != domain_command.income_year
                or result.entry_kind is not LedgerEntryKind.ADMINISTRATIVE_COST
            ):
                raise LedgerError.unavailable()
            return AdministrativeCostEntryWire(
                entry_id=UUID(str(result.entry_id)),
                company_id=UUID(str(result.company_id)),
                income_year=int(result.income_year),
                entry_kind=result.entry_kind.value,
                posted_at=result.posted_at.value,
                replayed=result.replayed,
            )

        return await ledger_call(execute)

    @application.post(
        "/api/v1/ledger/investment-dividends",
        operation_id="ledgerPostInvestmentDividend",
        response_model=LedgerWriterResultWire,
        status_code=201,
        responses={201: {"description": "Investment dividend recorded atomically."} | ledger_success}
        | ledger_errors,
        tags=["ledger-workflows"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def record_ledger_investment_dividend(
        request: Request,
        command: LedgerInvestmentDividendWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> LedgerWriterResultWire:
        async def execute() -> LedgerWriterResultWire:
            session = await ledger_application.session(bearer_token(credentials))
            domain = ledger_input(lambda: RecordInvestmentDividendCommand(
                company_id=CompanyId(str(command.company_id)),
                actor_id=session.actor_id,
                correlation_id=ledger_correlation(request),
                idempotency_key=IdempotencyKey(idempotency_key),
                income_year=IncomeYear(command.income_year),
                action_id=LedgerSourceRecordId(str(command.action_id)),
                paying_company_name=command.paying_company_name,
                declared_date=LocalDate(command.declared_date),
                paid_date=LocalDate(command.paid_date),
                gross_amount=command.gross_amount.to_domain(),
                linked_investment_id=(LedgerSourceRecordId(str(command.linked_investment_id)) if command.linked_investment_id else None),
                tax_treatment=command.tax_treatment,
                bank_transaction_id=(LedgerSourceRecordId(str(command.bank_transaction_id)) if command.bank_transaction_id else None),
                document_id=(LedgerSourceRecordId(str(command.document_id)) if command.document_id else None),
                document_status=command.document_status,
            ))
            result = await session.record_investment_dividend(domain)
            return ledger_writer_wire(
                result, company_id=command.company_id, income_year=command.income_year,
                expected_kind=LedgerEntryKind.DIVIDEND_RECEIVED,
            )

        return await ledger_call(execute)

    @application.post(
        "/api/v1/ledger/shareholder-loans",
        operation_id="ledgerPostShareholderLoan",
        response_model=LedgerWriterResultWire,
        status_code=201,
        responses={201: {"description": "Shareholder loan recorded atomically."} | ledger_success}
        | ledger_errors,
        tags=["ledger-workflows"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def record_ledger_shareholder_loan(
        request: Request,
        command: LedgerShareholderLoanWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> LedgerWriterResultWire:
        directions = {
            "shareholder_to_company": ShareholderLoanDirection.SHAREHOLDER_TO_COMPANY,
            "company_to_corporate_shareholder": ShareholderLoanDirection.COMPANY_TO_CORPORATE_SHAREHOLDER,
        }

        async def execute() -> LedgerWriterResultWire:
            session = await ledger_application.session(bearer_token(credentials))
            domain = ledger_input(lambda: RecordShareholderLoanCommand(
                company_id=CompanyId(str(command.company_id)), actor_id=session.actor_id,
                correlation_id=ledger_correlation(request), idempotency_key=IdempotencyKey(idempotency_key),
                income_year=IncomeYear(command.income_year), action_id=LedgerSourceRecordId(str(command.action_id)),
                loan_date=LocalDate(command.loan_date), amount=command.amount.to_domain(),
                direction=directions[command.direction], counterparty_name=command.counterparty_name,
                document_status=command.document_status, interest_modelled=command.interest_modelled,
                related_party_security=command.related_party_security,
                bank_transaction_id=(LedgerSourceRecordId(str(command.bank_transaction_id)) if command.bank_transaction_id else None),
                document_id=(LedgerSourceRecordId(str(command.document_id)) if command.document_id else None),
            ))
            result = await session.record_shareholder_loan(domain)
            return ledger_writer_wire(
                result, company_id=command.company_id, income_year=command.income_year,
                expected_kind=LedgerEntryKind.SHAREHOLDER_LOAN,
            )

        return await ledger_call(execute)

    @application.post(
        "/api/v1/ledger/tax-settlements",
        operation_id="ledgerPostTaxSettlement",
        response_model=LedgerWriterResultWire,
        status_code=201,
        responses={201: {"description": "Tax settlement recorded atomically."} | ledger_success}
        | ledger_errors,
        tags=["ledger-workflows"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def record_ledger_tax_settlement(
        request: Request,
        command: LedgerTaxSettlementWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> LedgerWriterResultWire:
        async def execute() -> LedgerWriterResultWire:
            session = await ledger_application.session(bearer_token(credentials))
            domain = ledger_input(lambda: RecordTaxSettlementCommand(
                company_id=CompanyId(str(command.company_id)), actor_id=session.actor_id,
                correlation_id=ledger_correlation(request), idempotency_key=IdempotencyKey(idempotency_key),
                income_year=IncomeYear(command.income_year), action_id=LedgerSourceRecordId(str(command.action_id)),
                settlement_date=LocalDate(command.settlement_date), amount=command.amount.to_domain(),
                settlement_kind=command.settlement_kind, document_status=command.document_status,
                bank_transaction_id=(LedgerSourceRecordId(str(command.bank_transaction_id)) if command.bank_transaction_id else None),
                document_id=(LedgerSourceRecordId(str(command.document_id)) if command.document_id else None),
            ))
            result = await session.record_tax_settlement(domain)
            return ledger_writer_wire(
                result, company_id=command.company_id, income_year=command.income_year,
                expected_kind=LedgerEntryKind.TAX_SETTLEMENT,
            )

        return await ledger_call(execute)

    @application.post(
        "/api/v1/ledger/bank-suggestion-outcomes",
        operation_id="ledgerPostBankSuggestionOutcome",
        response_model=LedgerWriterResultWire,
        status_code=201,
        responses={201: {"description": "Bank suggestion accepted atomically."} | ledger_success}
        | ledger_errors,
        tags=["ledger-workflows"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def record_ledger_bank_suggestion(
        request: Request,
        command: LedgerBankSuggestionWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> LedgerWriterResultWire:
        rules = {
            "bank_fee": BankSuggestionRule.BANK_FEE,
            "system_subscription": BankSuggestionRule.SYSTEM_SUBSCRIPTION,
            "deposit_interest": BankSuggestionRule.DEPOSIT_INTEREST,
        }

        async def execute() -> LedgerWriterResultWire:
            session = await ledger_application.session(bearer_token(credentials))
            domain = ledger_input(lambda: AcceptBankTransactionSuggestionCommand(
                company_id=CompanyId(str(command.company_id)), actor_id=session.actor_id,
                correlation_id=ledger_correlation(request), idempotency_key=IdempotencyKey(idempotency_key),
                income_year=IncomeYear(command.income_year), acceptance_id=LedgerSourceRecordId(str(command.acceptance_id)),
                bank_transaction_id=LedgerSourceRecordId(str(command.bank_transaction_id)),
                rule=rules[command.rule], rule_version=command.rule_version,
            ))
            result = await session.accept_bank_transaction_suggestion(domain)
            return ledger_writer_wire(
                result, company_id=command.company_id, income_year=command.income_year,
                expected_kind=LedgerEntryKind.BANK_RULE_SUGGESTION,
            )

        return await ledger_call(execute)

    @application.post(
        "/api/v1/ledger/investment-purchases",
        operation_id="ledgerPostInvestmentPurchase",
        response_model=LedgerWriterResultWire,
        status_code=201,
        responses={201: {"description": "Investment purchase recorded atomically."} | ledger_success}
        | ledger_errors,
        tags=["ledger-workflows"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def record_ledger_investment_purchase(
        request: Request,
        command: LedgerInvestmentPurchaseWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> LedgerWriterResultWire:
        async def execute() -> LedgerWriterResultWire:
            session = await ledger_application.session(bearer_token(credentials))
            domain = ledger_input(lambda: RecordInvestmentPurchaseFifoCommand(
                company_id=CompanyId(str(command.company_id)), actor_id=session.actor_id,
                correlation_id=ledger_correlation(request), idempotency_key=IdempotencyKey(idempotency_key),
                income_year=IncomeYear(command.income_year), action_id=LedgerSourceRecordId(str(command.action_id)),
                investment_key=command.investment_key, investment_name=command.investment_name,
                investment_kind=command.investment_kind, tax_treatment=command.tax_treatment,
                acquisition_date=LocalDate(command.acquisition_date), share_count=command.share_count,
                purchase_amount=command.purchase_amount.to_domain(), org_number=command.org_number,
                bank_transaction_id=(LedgerSourceRecordId(str(command.bank_transaction_id)) if command.bank_transaction_id else None),
                document_id=(LedgerSourceRecordId(str(command.document_id)) if command.document_id else None),
                document_status=command.document_status,
            ))
            result = await session.record_investment_purchase_fifo(domain)
            return ledger_writer_wire(
                result, company_id=command.company_id, income_year=command.income_year,
                expected_kind=LedgerEntryKind.SHARE_PURCHASE,
            )

        return await ledger_call(execute)

    @application.post(
        "/api/v1/ledger/investment-sales",
        operation_id="ledgerPostInvestmentSale",
        response_model=LedgerWriterResultWire,
        status_code=201,
        responses={201: {"description": "Investment sale recorded atomically."} | ledger_success}
        | ledger_errors,
        tags=["ledger-workflows"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def record_ledger_investment_sale(
        request: Request,
        command: LedgerInvestmentSaleWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> LedgerWriterResultWire:
        async def execute() -> LedgerWriterResultWire:
            session = await ledger_application.session(bearer_token(credentials))
            domain = ledger_input(lambda: RecordInvestmentSaleFifoCommand(
                company_id=CompanyId(str(command.company_id)), actor_id=session.actor_id,
                correlation_id=ledger_correlation(request), idempotency_key=IdempotencyKey(idempotency_key),
                income_year=IncomeYear(command.income_year), action_id=LedgerSourceRecordId(str(command.action_id)),
                position_id=LedgerSourceRecordId(str(command.position_id)), sale_date=LocalDate(command.sale_date),
                sold_share_count=command.sold_share_count, proceeds=command.proceeds.to_domain(),
                bank_transaction_id=(LedgerSourceRecordId(str(command.bank_transaction_id)) if command.bank_transaction_id else None),
                document_id=(LedgerSourceRecordId(str(command.document_id)) if command.document_id else None),
                document_status=command.document_status,
            ))
            result = await session.record_investment_sale_fifo(domain)
            return ledger_writer_wire(
                result, company_id=command.company_id, income_year=command.income_year,
                expected_kind=LedgerEntryKind.SHARE_SALE,
            )

        return await ledger_call(execute)

    @application.post(
        "/api/v1/ledger/corporate-decisions/finalizations",
        operation_id="ledgerFinalizeCorporateDecision",
        response_model=LedgerWriterResultWire,
        status_code=201,
        responses={201: {"description": "Corporate decision finalized atomically."} | ledger_success}
        | ledger_errors,
        tags=["ledger-workflows"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def finalize_ledger_corporate_decision(
        request: Request,
        command: LedgerCorporateDecisionFinalizationWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> LedgerWriterResultWire:
        async def execute() -> LedgerWriterResultWire:
            session = await ledger_application.session(bearer_token(credentials))
            domain = ledger_input(lambda: FinalizeCorporateDecisionCommand(
                company_id=CompanyId(str(command.company_id)), actor_id=session.actor_id,
                correlation_id=ledger_correlation(request), idempotency_key=IdempotencyKey(idempotency_key),
                income_year=IncomeYear(command.income_year), decision_id=LedgerSourceRecordId(str(command.decision_id)),
                set_id=LedgerSourceRecordId(str(command.set_id)), decision_hash=command.decision_hash,
                finalization_id=LedgerSourceRecordId(str(command.finalization_id)),
                holding_action_id=(LedgerSourceRecordId(str(command.holding_action_id)) if command.holding_action_id else None),
                ledger_entry_id=(LedgerEntryId(str(command.ledger_entry_id)) if command.ledger_entry_id else None),
            ))
            result = await session.finalize_corporate_decision(domain)
            expected = (
                LedgerEntryKind.OWNER_DIVIDEND_DECLARED
                if command.ledger_entry_id is not None
                else None
            )
            return ledger_writer_wire(
                result, company_id=command.company_id, income_year=command.income_year,
                expected_kind=expected,
            )

        return await ledger_call(execute)

    @application.post(
        "/api/v1/ledger/owner-dividends/payments",
        operation_id="ledgerPostOwnerDividendPayment",
        response_model=LedgerWriterResultWire,
        status_code=201,
        responses={201: {"description": "Owner-dividend payment recorded atomically."} | ledger_success}
        | ledger_errors,
        tags=["ledger-workflows"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def record_ledger_owner_dividend_payment(
        request: Request,
        command: LedgerOwnerDividendPaymentWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> LedgerWriterResultWire:
        async def execute() -> LedgerWriterResultWire:
            session = await ledger_application.session(bearer_token(credentials))
            domain = ledger_input(lambda: RecordOwnerDividendPaymentCommand(
                company_id=CompanyId(str(command.company_id)), actor_id=session.actor_id,
                correlation_id=ledger_correlation(request), idempotency_key=IdempotencyKey(idempotency_key),
                income_year=IncomeYear(command.income_year), decision_id=LedgerSourceRecordId(str(command.decision_id)),
                set_id=LedgerSourceRecordId(str(command.set_id)), decision_hash=command.decision_hash,
                bank_transaction_id=LedgerSourceRecordId(str(command.bank_transaction_id)),
                holding_action_id=LedgerSourceRecordId(str(command.holding_action_id)),
                ledger_entry_id=LedgerEntryId(str(command.ledger_entry_id)),
            ))
            result = await session.record_owner_dividend_payment(domain)
            return ledger_writer_wire(
                result, company_id=command.company_id, income_year=command.income_year,
                expected_kind=LedgerEntryKind.OWNER_DIVIDEND_PAYMENT,
            )

        return await ledger_call(execute)

    @application.post(
        "/api/v1/ledger/manual-journals",
        operation_id="ledgerPostManualJournal",
        response_model=LedgerPostedEntryWire,
        status_code=201,
        responses={201: {"description": "Manual journal posted."} | ledger_success}
        | ledger_errors,
        tags=["ledger"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def post_ledger_manual_journal(
        request: Request,
        command: LedgerManualJournalWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> LedgerPostedEntryWire:
        async def execute() -> LedgerPostedEntryWire:
            session = await ledger_application.session(bearer_token(credentials))
            domain_command = ledger_input(
                lambda: PostManualJournalCommand(
                    company_id=CompanyId(str(command.company_id)),
                    actor_id=session.actor_id,
                    correlation_id=ledger_correlation(request),
                    idempotency_key=IdempotencyKey(idempotency_key),
                    income_year=IncomeYear(command.income_year),
                    memo=command.memo,
                    lines=tuple(line.to_domain() for line in command.lines),
                    warning_accepted=command.warning_accepted,
                )
            )
            result = await session.post_manual_journal(domain_command)
            return _posted_wire(result)

        return await ledger_call(execute)

    @application.post(
        "/api/v1/ledger/period-locks",
        operation_id="ledgerLockPeriod",
        response_model=LedgerPeriodLockWire,
        status_code=201,
        responses={201: {"description": "Period locked."} | ledger_success}
        | ledger_errors,
        tags=["ledger"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def lock_ledger_period(
        request: Request,
        command: LedgerLockPeriodWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> LedgerPeriodLockWire:
        async def execute() -> LedgerPeriodLockWire:
            session = await ledger_application.session(bearer_token(credentials))
            domain_command = ledger_input(
                lambda: LockPeriodCommand(
                    company_id=CompanyId(str(command.company_id)),
                    actor_id=session.actor_id,
                    correlation_id=ledger_correlation(request),
                    idempotency_key=IdempotencyKey(idempotency_key),
                    income_year=IncomeYear(command.income_year),
                    reason=command.reason,
                )
            )
            result = await session.lock_period(domain_command)
            return _lock_wire(result)

        return await ledger_call(execute)

    @application.get("/health/live", include_in_schema=False)
    async def liveness() -> JSONResponse:
        return JSONResponse(
            {"status": "alive"},
            headers={"Cache-Control": "no-store"},
        )

    @application.get("/health/ready", include_in_schema=False)
    async def readiness() -> JSONResponse:
        return JSONResponse(
            {"status": "ready"},
            headers={"Cache-Control": "no-store"},
        )

    @application.get("/api/v1/openapi.json", include_in_schema=False)
    async def served_openapi() -> Response:
        from talli_backend.openapi import serialize_openapi

        return Response(
            content=serialize_openapi(application),
            media_type="application/vnd.oai.openapi+json;version=3.1",
            headers={"Cache-Control": "no-store"},
        )

    return application


app = create_app()
