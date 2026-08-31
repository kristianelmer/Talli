from __future__ import annotations

import asyncio
import os
import re
import secrets
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import date, datetime
from typing import Annotated, Any, Literal, TypeVar, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.json_schema import SkipJsonSchema
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from talli_backend.adapters.brreg_company_registry import BrregCompanyRegistryAdapter
from talli_backend.adapters.supabase_banking import compose_banking_application
from talli_backend.adapters.supabase_company_access import SupabaseCompanyAccessAdapter
from talli_backend.adapters.supabase_ledger import compose_ledger_application
from talli_backend.adapters.supabase_investments import compose_investments_application
from talli_backend.adapters.supabase_marketing_measurement import (
    SupabaseMarketingMeasurementAdapter,
)
from talli_backend.adapters.supabase_validation_observation import (
    SupabaseValidationObservationAdapter,
)
from talli_backend.modules.marketing_measurement.public import (
    MarketingCampaignSource,
    MarketingEventName,
    MarketingFunnelReport,
    MarketingMeasurementError,
    MarketingMeasurementEvent,
    MarketingMeasurementGateway,
    MarketingReasonCode,
    MarketingSurface,
)
from talli_backend.modules.validation_observation.public import (
    BoundedValidationObservation,
    PassiveValidationObserver,
    ValidationObservationConfiguration,
)
from talli_backend.application.banking_session import (
    AuthenticatedBankingSession,
    BankingAuthenticationError,
    BankingSessionFactory,
)
from talli_backend.application.investments_session import (
    InvestmentsAuthenticationError,
    InvestmentsSessionFactory,
)
from talli_backend.application.ledger_workflow import (
    FinalizeCorporateDecisionCommand,
    LedgerAuthenticationError,
    LedgerSessionFactory,
    LedgerWriterResult,
    NewYearStartCommand,
    RecordAdministrativeCostCommand,
    RecordOwnerDividendPaymentCommand,
    RecordShareholderLoanCommand,
    RecordTaxSettlementCommand,
)
from talli_backend.application.opening_snapshot_compatibility import (
    LegacyOpeningSnapshotCursor,
    LegacyOpeningSnapshotPage,
    LegacyOpeningSnapshotView,
)
from talli_backend.modules.banking.public import (
    AcceptBankFileCommand,
    AcceptBankSuggestionCommand,
    AcceptedBankSuggestion,
    BankStatementImportResult,
    BankAccount,
    BankAccountId,
    BankConnection,
    BankConnectionList,
    BankConnectionId,
    BankConnectorId,
    BankConsentRedirect,
    BankDataProvider,
    BankFileColumnMapping,
    BankFilePreviewCommand,
    BankSourceFileId,
    BankSyncCommand,
    BankSyncMode,
    BankSyncResult,
    BankSuggestionAcceptancePage,
    BankSuggestionAcceptanceId,
    BankSuggestionKind,
    BankTransaction,
    BankTransactionId,
    BankTransactionPage,
    BankingCursor,
    BankingError,
    CompleteBankConnectionCommand,
    ImportBankStatementCommand,
    PersistedBankFilePreview,
    RevokeBankConnectionCommand,
    StartBankConnectionCommand,
    SupportedBankDataFormat,
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
    GrantSupportAccessRequest,
    InvitationLookup,
    InvitationSideEffectCompletion,
    InvitationSideEffectContinuationList,
    InvitationTokenRequest,
    OpenSupportCaseRequest,
    OperatorCompanySearchResponse,
    OperatorContextResponse,
    RevokeSupportAccessRequest,
    RequestCompanyCancellationRequest,
    ResumeCompanyCancellationRequest,
    ReviewCompanyDeletionRequest,
    SupportAccessGrantResponse,
    SupportCaseOpeningResponse,
    SupportCaseSnapshotResponse,
)
from talli_backend.modules.ledger.public import (
    AdministrativeCostCategory,
    BankLoanMaturity,
    BankLoanReferenceId,
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
from talli_backend.modules.investments.public import (
    AcquisitionLotView,
    InvestmentActivityKind,
    InvestmentActivityView,
    InvestmentActionId,
    InvestmentCursor,
    InvestmentDocumentStatus,
    InvestmentKind,
    InvestmentLotHistoryStatus,
    InvestmentPositionId,
    InvestmentPositionView,
    InvestmentSourceReference,
    InvestmentTaxTreatment,
    InvestmentsError,
    RecordReceivedDividendCommand,
    RecordSharePurchaseCommand,
    RecordShareSaleCommand,
    ShareSaleAllocationView,
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
MARKETING_MEASUREMENT_KEY_AUTH = APIKeyHeader(
    name="X-Talli-Marketing-Measurement-Key",
    scheme_name="marketingMeasurementKey",
    auto_error=False,
)
MARKETING_MEASUREMENT_KEY_DEPENDENCY = Depends(MARKETING_MEASUREMENT_KEY_AUTH)
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


MARKETING_REASONS_BY_EVENT: dict[MarketingEventName, tuple[MarketingReasonCode, ...]] = {
    "provisional_clarify": ("unknown_material_facts", "missing_required_facts"),
    "provisional_blocked": ("unsupported_company", "unsupported_activity"),
    "definitive_blocked": (
        "unknown_material_facts",
        "unsupported_company",
        "unsupported_activity",
        "missing_required_facts",
    ),
    "unsupported_exit": (
        "unknown_material_facts",
        "unsupported_company",
        "unsupported_activity",
        "new_unsupported_condition",
    ),
}


class MarketingMeasurementEventWire(StrictTransportModel):
    client_event_id: UUID
    anonymous_session_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    consent_version: Literal["marketing-analytics-v1"]
    first_layer_notice_version: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    first_layer_notice_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    privacy_notice_version: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    privacy_notice_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    release_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    event: MarketingEventName
    reason: MarketingReasonCode | None
    surface: MarketingSurface
    campaign_source: MarketingCampaignSource

    @model_validator(mode="after")
    def reason_matches_event(self) -> MarketingMeasurementEventWire:
        reasons = MARKETING_REASONS_BY_EVENT.get(self.event)
        if (reasons is None and self.reason is not None) or (
            reasons is not None and self.reason not in reasons
        ):
            raise ValueError("invalid bounded reason for marketing event")
        return self

    def to_domain(self) -> MarketingMeasurementEvent:
        return MarketingMeasurementEvent(
            client_event_id=self.client_event_id,
            anonymous_session_hash=self.anonymous_session_hash,
            consent_version=self.consent_version,
            first_layer_notice_version=self.first_layer_notice_version,
            first_layer_notice_sha256=self.first_layer_notice_sha256,
            privacy_notice_version=self.privacy_notice_version,
            privacy_notice_sha256=self.privacy_notice_sha256,
            release_sha256=self.release_sha256,
            event=self.event,
            reason=self.reason,
            surface=self.surface,
            campaign_source=self.campaign_source,
        )


class MarketingMeasurementEventResponse(TransportModel):
    accepted: Literal[True]
    duplicate: bool


class MarketingMeasurementWithdrawalRequest(StrictTransportModel):
    anonymous_session_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class MarketingMeasurementWithdrawalResponse(TransportModel):
    deleted_event_count: int = Field(ge=0)


class MarketingRepeatedSignalWire(TransportModel):
    event: MarketingEventName
    surface: MarketingSurface
    reason: MarketingReasonCode
    count: int = Field(ge=5)


class MarketingFunnelReportResponse(TransportModel):
    window_start: datetime
    window_end: datetime
    counts: dict[MarketingEventName, int]
    rates: dict[str, float | int | None]
    median_seconds: dict[str, float | int | None]
    support_by_surface: dict[MarketingSurface, int]
    repeated_signals: list[MarketingRepeatedSignalWire]

    @classmethod
    def from_domain(cls, report: MarketingFunnelReport) -> MarketingFunnelReportResponse:
        return cls(
            window_start=report.window_start,
            window_end=report.window_end,
            counts=report.counts,
            rates=report.rates,
            median_seconds=report.median_seconds,
            support_by_surface=report.support_by_surface,
            repeated_signals=[
                MarketingRepeatedSignalWire(
                    event=signal.event,
                    surface=signal.surface,
                    reason=signal.reason,
                    count=signal.count,
                )
                for signal in report.repeated_signals
            ],
        )


class LedgerMoneyWire(StrictTransportModel):
    amount: str = Field(
        max_length=64,
        pattern=r"^-?(?:0|[1-9]\d*)(?:\.\d{1,2})?$",
    )
    currency: Literal["NOK"]

    def to_domain(self) -> Money:
        return Money.nok(self.amount)


class BankStatementImportWire(StrictTransportModel):
    company_id: UUID
    income_year: int = Field(ge=2000, le=2100)
    data_format: SupportedBankDataFormat
    statement_text: str = Field(min_length=1, max_length=5_000_000)


class BankStatementImportResultWire(TransportModel):
    imported_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    replayed: bool


class StartBankConnectionWire(StrictTransportModel):
    company_id: UUID
    income_year: int = Field(ge=2000, le=2100)
    connection_id: UUID
    connector_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")
    bank_key: str = Field(min_length=1, max_length=120)
    return_url: str = Field(pattern=r"^https://", max_length=2048)


class BankConsentRedirectWire(TransportModel):
    redirect_url: str
    state: str


class BankAccountWire(TransportModel):
    account_id: UUID
    connection_id: UUID
    masked_account: str
    currency: Literal["NOK"]
    account_kind: str
    display_name: str
    status: str
    earliest_covered_date: date | None
    latest_covered_date: date | None
    last_success_at: datetime | None


class BankConnectionWire(TransportModel):
    connection_id: UUID
    company_id: UUID
    connector_id: str
    status: str
    consent_expires_on: date | None
    accounts: list[BankAccountWire]
    last_success_at: datetime | None
    last_failure_code: str | None


class BankConnectionListWire(TransportModel):
    items: list[BankConnectionWire]


class BankSyncWire(StrictTransportModel):
    company_id: UUID
    income_year: int = Field(ge=2000, le=2100)
    connector_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")
    date_from: date
    date_to: date
    mode: BankSyncMode


class BankConnectionActionWire(StrictTransportModel):
    company_id: UUID
    income_year: int = Field(ge=2000, le=2100)
    connector_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")


class BankSyncResultWire(TransportModel):
    attempt_id: UUID
    page_count: int = Field(ge=0)
    imported_count: int = Field(ge=0)
    updated_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    replayed: bool


class BankFileColumnMappingWire(StrictTransportModel):
    booking_date: str = Field(min_length=1, max_length=120)
    value_date: str | None = Field(default=None, max_length=120)
    text: str = Field(min_length=1, max_length=120)
    amount: str = Field(min_length=1, max_length=120)
    balance: str | None = Field(default=None, max_length=120)
    reference: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=120)


class BankFilePreviewWire(StrictTransportModel):
    company_id: UUID
    income_year: int = Field(ge=2000, le=2100)
    source_file_id: UUID
    account_id: UUID
    data_format: SupportedBankDataFormat
    filename: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=5_000_000)
    column_mapping: BankFileColumnMappingWire | None = None


class BankFilePreviewResultWire(TransportModel):
    source_file_id: UUID
    document_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    account_mask: str | None
    interval_start: date
    interval_end: date
    currency: Literal["NOK"]
    opening_balance: LedgerMoneyWire | None
    closing_balance: LedgerMoneyWire | None
    transaction_count: int = Field(ge=1)
    duplicate_count: int = Field(ge=0)
    correction_count: int = Field(ge=0)
    ignored_count: int = Field(ge=0)
    replayed: bool


class AcceptBankFileWire(StrictTransportModel):
    company_id: UUID
    income_year: int = Field(ge=2000, le=2100)
    document_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class AcceptBankSuggestionWire(StrictTransportModel):
    company_id: UUID
    income_year: int = Field(ge=2000, le=2100)
    acceptance_id: UUID
    bank_transaction_id: UUID
    expected_suggestion: BankSuggestionKind
    expected_rule_version: str = Field(min_length=1, max_length=80)


class BankSuggestionWire(TransportModel):
    kind: str
    rule_version: str
    reason: str


class BankTransactionWire(TransportModel):
    transaction_id: UUID
    company_id: UUID
    income_year: int = Field(ge=2000, le=2100)
    transaction_date: date
    text: str
    amount: LedgerMoneyWire
    balance: LedgerMoneyWire | None
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    matched_entry_id: UUID | None
    matched_action_reference: str | None
    warning_accepted: bool
    suggestion: BankSuggestionWire | None
    created_at: datetime


class BankingPageWire(TransportModel):
    next_cursor: str | None
    has_more: bool


class BankTransactionPageWire(TransportModel):
    items: list[BankTransactionWire]
    page: BankingPageWire


class AcceptedBankSuggestionWire(TransportModel):
    acceptance_id: UUID
    bank_transaction_id: UUID
    accounting_entry_id: UUID
    suggestion: BankSuggestionWire
    accepted_by: UUID
    accepted_at: datetime
    replayed: bool


class BankSuggestionAcceptancePageWire(TransportModel):
    items: list[AcceptedBankSuggestionWire]
    page: BankingPageWire


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


class InvestmentsSharePurchaseWire(LedgerCompanyYearWire):
    action_id: UUID
    investment_key: str = Field(min_length=1, max_length=255)
    investment_name: str = Field(min_length=1, max_length=255)
    investment_kind: InvestmentKind
    tax_treatment: InvestmentTaxTreatment
    acquisition_date: date
    share_count: int = Field(gt=0, le=9_007_199_254_740_991)
    purchase_amount: LedgerMoneyWire
    org_number: str | None = Field(default=None, pattern=r"^\d{9}$")
    bank_transaction_id: UUID | None = None
    document_id: UUID | None = None
    document_status: InvestmentDocumentStatus


class InvestmentsSharePurchaseResultWire(TransportModel):
    action_id: UUID
    position_id: UUID
    acquisition_lot_id: UUID
    accounting_entry_id: UUID
    position_created: bool
    replayed: bool


class InvestmentsShareSaleWire(LedgerCompanyYearWire):
    action_id: UUID
    position_id: UUID
    sale_date: date
    sold_share_count: int = Field(gt=0, le=9_007_199_254_740_991)
    proceeds: LedgerMoneyWire
    bank_transaction_id: UUID | None = None
    document_id: UUID | None = None
    document_status: InvestmentDocumentStatus


class InvestmentsShareSaleResultWire(TransportModel):
    action_id: UUID
    position_id: UUID
    accounting_entry_id: UUID
    replayed: bool


class InvestmentsReceivedDividendWire(LedgerCompanyYearWire):
    action_id: UUID
    position_id: UUID
    paying_company_name: str = Field(min_length=1, max_length=255)
    declared_date: date
    paid_date: date
    gross_amount: LedgerMoneyWire
    tax_treatment: InvestmentTaxTreatment
    bank_transaction_id: UUID | None = None
    document_id: UUID | None = None
    document_status: InvestmentDocumentStatus


class InvestmentsReceivedDividendResultWire(TransportModel):
    action_id: UUID
    position_id: UUID
    accounting_entry_id: UUID
    taxable_add_back: LedgerMoneyWire
    replayed: bool


class InvestmentsPageWire(TransportModel):
    next_cursor: str | None
    has_more: bool


class InvestmentPositionWire(TransportModel):
    id: UUID
    company_id: UUID
    investment_key: str
    name: str
    kind: InvestmentKind
    tax_treatment: InvestmentTaxTreatment
    org_number: str | None
    share_count: int
    cost_basis: LedgerMoneyWire
    lot_history_status: InvestmentLotHistoryStatus
    movement_count: int
    movements: list[dict[str, Any]]
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class InvestmentPositionPageWire(TransportModel):
    items: list[InvestmentPositionWire]
    page: InvestmentsPageWire


class AcquisitionLotWire(TransportModel):
    id: UUID
    company_id: UUID
    position_id: UUID
    acquisition_action_id: UUID
    acquisition_date: date
    original_share_count: int
    remaining_share_count: int
    original_cost_basis: LedgerMoneyWire
    remaining_cost_basis: LedgerMoneyWire
    created_by: UUID
    created_at: datetime


class AcquisitionLotPageWire(TransportModel):
    items: list[AcquisitionLotWire]
    page: InvestmentsPageWire


class InvestmentActivityWire(TransportModel):
    id: UUID
    company_id: UUID
    income_year: int
    activity_kind: InvestmentActivityKind
    action_date: date
    position_id: UUID
    investment_key: str
    investment_name: str
    investment_kind: InvestmentKind
    tax_treatment: InvestmentTaxTreatment
    org_number: str | None
    acquisition_lot_id: UUID | None
    share_count: int | None
    purchase_amount: LedgerMoneyWire | None
    sold_share_count: int | None
    proceeds: LedgerMoneyWire | None
    fifo_cost_basis_reduction: LedgerMoneyWire | None
    remaining_share_count: int | None
    remaining_cost_basis: LedgerMoneyWire | None
    paying_company_name: str | None
    declared_date: date | None
    gross_amount: LedgerMoneyWire | None
    taxable_add_back: LedgerMoneyWire | None
    gain_or_loss: LedgerMoneyWire | None
    bank_transaction_id: UUID | None
    document_id: UUID | None
    document_status: InvestmentDocumentStatus
    accounting_entry_id: UUID | None
    created_by: UUID
    created_at: datetime


class InvestmentActivityPageWire(TransportModel):
    items: list[InvestmentActivityWire]
    page: InvestmentsPageWire


class ShareSaleAllocationWire(TransportModel):
    id: UUID
    company_id: UUID
    position_id: UUID
    lot_id: UUID
    sale_action_id: UUID
    allocation_order: int
    acquisition_date: date
    allocated_share_count: int
    allocated_cost_basis: LedgerMoneyWire
    created_by: UUID
    created_at: datetime


class ShareSaleAllocationPageWire(TransportModel):
    items: list[ShareSaleAllocationWire]
    page: InvestmentsPageWire


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
    economic_facts_digest: str | None = Field(pattern=r"^[a-f0-9]{64}$")
    economic_fact_count: int | None = Field(ge=0)
    source_evidence_digest: str | None = Field(pattern=r"^[a-f0-9]{64}$")
    source_evidence_count: int | None = Field(ge=13, le=13)
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


def _bank_transaction_wire(value: BankTransaction) -> BankTransactionWire:
    return BankTransactionWire(
        transaction_id=str(value.transaction_id),
        company_id=str(value.company_id),
        income_year=int(value.income_year),
        transaction_date=value.transaction_date.value,
        text=value.text,
        amount=_money_wire(value.amount),
        balance=_money_wire(value.balance) if value.balance is not None else None,
        source_hash=value.source_hash,
        matched_entry_id=(
            str(value.matched_entry_id) if value.matched_entry_id is not None else None
        ),
        matched_action_reference=(
            str(value.matched_action_reference)
            if value.matched_action_reference is not None
            else None
        ),
        warning_accepted=value.warning_accepted,
        suggestion=(
            BankSuggestionWire(
                kind=value.suggestion.kind.value,
                rule_version=value.suggestion.rule_version,
                reason=value.suggestion.reason,
            )
            if value.suggestion is not None
            else None
        ),
        created_at=value.created_at.value,
    )


def _accepted_bank_suggestion_wire(
    value: AcceptedBankSuggestion,
) -> AcceptedBankSuggestionWire:
    return AcceptedBankSuggestionWire(
        acceptance_id=str(value.acceptance_id),
        bank_transaction_id=str(value.bank_transaction_id),
        accounting_entry_id=str(value.accounting_entry_id),
        suggestion=BankSuggestionWire(
            kind=value.suggestion.kind.value,
            rule_version=value.suggestion.rule_version,
            reason=value.suggestion.reason,
        ),
        accepted_by=str(value.accepted_by.subject),
        accepted_at=value.accepted_at.value,
        replayed=value.replayed,
    )


def _bank_account_wire(value: BankAccount) -> BankAccountWire:
    return BankAccountWire(
        account_id=str(value.account_id),
        connection_id=str(value.connection_id),
        masked_account=value.masked_account,
        currency=value.currency,
        account_kind=value.account_kind,
        display_name=value.display_name,
        status=value.status.value,
        earliest_covered_date=(
            value.earliest_covered_date.value
            if value.earliest_covered_date is not None
            else None
        ),
        latest_covered_date=(
            value.latest_covered_date.value
            if value.latest_covered_date is not None
            else None
        ),
        last_success_at=(
            value.last_success_at.value if value.last_success_at is not None else None
        ),
    )


def _bank_connection_wire(value: BankConnection) -> BankConnectionWire:
    return BankConnectionWire(
        connection_id=str(value.connection_id),
        company_id=str(value.company_id),
        connector_id=str(value.connector_id),
        status=value.status.value,
        consent_expires_on=(
            value.consent_expires_on.value
            if value.consent_expires_on is not None
            else None
        ),
        accounts=[_bank_account_wire(account) for account in value.accounts],
        last_success_at=(
            value.last_success_at.value if value.last_success_at is not None else None
        ),
        last_failure_code=value.last_failure_code,
    )


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
        economic_facts_digest=value.economic_facts_digest,
        economic_fact_count=value.economic_fact_count,
        source_evidence_digest=value.source_evidence_digest,
        source_evidence_count=value.source_evidence_count,
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
    investments_session_factory: InvestmentsSessionFactory | None = None,
    banking_session_factory: BankingSessionFactory | None = None,
    banking_providers: Mapping[str, BankDataProvider] | None = None,
    marketing_measurement_gateway: MarketingMeasurementGateway | None = None,
    marketing_measurement_internal_key: str | None = None,
    validation_observer: PassiveValidationObserver | None = None,
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
    investments_application = compose_investments_application(
        investments_session_factory
    )
    banking_application = compose_banking_application(banking_session_factory)
    provider_registry = dict(banking_providers or {})
    measurement_gateway = (
        marketing_measurement_gateway
        if marketing_measurement_gateway is not None
        else SupabaseMarketingMeasurementAdapter.from_environment()
    )
    measurement_internal_key = (
        marketing_measurement_internal_key
        if marketing_measurement_internal_key is not None
        else os.environ.get("TALLI_MARKETING_MEASUREMENT_INTERNAL_KEY", "")
    )
    measurement_maintenance_task: asyncio.Task[None] | None = None
    passive_validation_observer = validation_observer or PassiveValidationObserver(
        ValidationObservationConfiguration.from_values(
            requested_mode=os.environ.get("TALLI_VALIDATION_OBSERVATION_MODE"),
            product_mode=os.environ.get("TALLI_PRODUCT_MODE"),
            entitlement_id=os.environ.get(
                "TALLI_VALIDATION_PILOT_ENTITLEMENT_ID"
            ),
            approved_run_id=os.environ.get("TALLI_VALIDATION_APPROVED_RUN_ID"),
            starts_at=os.environ.get("TALLI_VALIDATION_OBSERVATION_STARTS_AT"),
            expires_at=os.environ.get("TALLI_VALIDATION_OBSERVATION_EXPIRES_AT"),
            release_sha256=os.environ.get("TALLI_RELEASE_SHA256"),
            participant_information_sha256=os.environ.get(
                "TALLI_VALIDATION_PARTICIPANT_INFORMATION_SHA256"
            ),
            subject_binding_key=os.environ.get(
                "TALLI_VALIDATION_SUBJECT_BINDING_KEY"
            ),
        ),
        SupabaseValidationObservationAdapter.from_environment(),
    )

    async def maintain_marketing_measurement_retention() -> None:
        while True:
            try:
                await measurement_gateway.purge()
            except MarketingMeasurementError:
                pass
            await asyncio.sleep(3_600)

    async def start_marketing_measurement_maintenance() -> None:
        nonlocal measurement_maintenance_task
        measurement_maintenance_task = asyncio.create_task(
            maintain_marketing_measurement_retention()
        )

    async def stop_marketing_measurement_maintenance() -> None:
        if measurement_maintenance_task is None:
            return
        measurement_maintenance_task.cancel()
        try:
            await measurement_maintenance_task
        except asyncio.CancelledError:
            pass

    application.add_event_handler("startup", start_marketing_measurement_maintenance)
    application.add_event_handler("shutdown", stop_marketing_measurement_maintenance)

    def banking_provider(connector_id: BankConnectorId) -> BankDataProvider:
        provider = provider_registry.get(str(connector_id))
        if provider is None or provider.connector_id != connector_id:
            raise BankingError.unavailable()
        return provider

    async def canonical_banking_connector(
        session: AuthenticatedBankingSession,
        *,
        company_id: CompanyId,
        connection_id: BankConnectionId,
        correlation_id: CorrelationId,
    ) -> BankConnectorId:
        connections = await session.list_connections(
            actor_id=session.actor_id,
            company_id=company_id,
            correlation_id=correlation_id,
        )
        canonical_connection = next(
            (
                item
                for item in connections.items
                if item.connection_id == connection_id
            ),
            None,
        )
        if canonical_connection is None:
            raise BankingError.forbidden()
        return canonical_connection.connector_id

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

    def require_marketing_measurement_transport(provided_key: str | None) -> None:
        if len(measurement_internal_key) < 32:
            raise ApiProblem(
                status=503,
                code="MARKETING_MEASUREMENT_UNAVAILABLE",
                title="Marketing measurement unavailable",
                detail="Marketing measurement is temporarily unavailable.",
            )
        if provided_key is None or not secrets.compare_digest(
            provided_key, measurement_internal_key
        ):
            raise ApiProblem(
                status=403,
                code="MARKETING_MEASUREMENT_TRANSPORT_REQUIRED",
                title="Marketing measurement transport required",
                detail="The private marketing measurement transport is required.",
            )

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

    async def marketing_measurement_call(call: Awaitable[ResponseT]) -> ResponseT:
        try:
            return await call
        except MarketingMeasurementError as error:
            raise ApiProblem(
                status=error.status,
                code=error.code,
                title="Marketing measurement request failed",
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

    async def investments_call(
        call: Callable[[], Awaitable[ResponseT]],
    ) -> ResponseT:
        try:
            return await call()
        except InvestmentsAuthenticationError:
            raise ApiProblem(
                status=401,
                code="AUTHENTICATION_REQUIRED",
                title="Authentication required",
                detail="A valid session is required.",
            ) from None
        except InvestmentsError as error:
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
                title="Investments request failed",
                detail=error.message
                or "The investments request could not be completed.",
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
                title="Investments accounting request failed",
                detail=error.message
                or "The investment accounting entry could not be completed.",
            ) from None
    async def banking_call(call: Callable[[], Awaitable[ResponseT]]) -> ResponseT:
        try:
            return await call()
        except BankingAuthenticationError:
            raise ApiProblem(
                status=401,
                code="AUTHENTICATION_REQUIRED",
                title="Authentication required",
                detail="A valid session is required.",
            ) from None
        except BankingError as error:
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
                title="Banking request failed",
                detail=error.message or "The banking request could not be completed.",
            ) from None

    def ledger_input(factory: Callable[[], ResponseT]) -> ResponseT:
        try:
            return factory()
        except (TypeError, ValueError, ShareholderRegisterFilingError):
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT") from None

    def investments_input(factory: Callable[[], ResponseT]) -> ResponseT:
        try:
            return factory()
        except (TypeError, ValueError, InvestmentsError):
            raise InvestmentsError.invalid_input() from None

    def banking_input(factory: Callable[[], ResponseT]) -> ResponseT:
        try:
            return factory()
        except (TypeError, ValueError, BankingError):
            raise BankingError.invalid_input("BANKING_INVALID_INPUT") from None

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

    marketing_measurement_errors: Any = {
        status: {
            "description": "Marketing measurement request failed.",
            "headers": {"X-Request-ID": REQUEST_ID_HEADER},
            "content": {
                "application/problem+json": {
                    "schema": ProblemDetails.model_json_schema(by_alias=True)
                }
            },
        }
        for status in (401, 403, 422, 503)
    }

    @application.post(
        "/api/v1/marketing-measurement/events",
        operation_id="marketingMeasurementRecordEvent",
        response_model=MarketingMeasurementEventResponse,
        status_code=202,
        responses={
            202: {
                "description": "The consented event was accepted or replayed.",
                "headers": {"X-Request-ID": REQUEST_ID_HEADER},
            }
        }
        | {status: marketing_measurement_errors[status] for status in (403, 422, 503)},
        tags=["marketing-measurement"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def record_marketing_measurement_event(
        command: MarketingMeasurementEventWire,
        internal_key: str | None = MARKETING_MEASUREMENT_KEY_DEPENDENCY,
    ) -> MarketingMeasurementEventResponse:
        require_marketing_measurement_transport(internal_key)
        inserted = await marketing_measurement_call(
            measurement_gateway.record(command.to_domain())
        )
        return MarketingMeasurementEventResponse(
            accepted=True,
            duplicate=not inserted,
        )

    @application.post(
        "/api/v1/marketing-measurement/withdrawals",
        operation_id="marketingMeasurementWithdrawSession",
        response_model=MarketingMeasurementWithdrawalResponse,
        responses={
            200: {
                "description": "The anonymous session was removed.",
                "headers": {"X-Request-ID": REQUEST_ID_HEADER},
            }
        }
        | {status: marketing_measurement_errors[status] for status in (403, 422, 503)},
        tags=["marketing-measurement"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def withdraw_marketing_measurement_session(
        command: MarketingMeasurementWithdrawalRequest,
        internal_key: str | None = MARKETING_MEASUREMENT_KEY_DEPENDENCY,
    ) -> MarketingMeasurementWithdrawalResponse:
        require_marketing_measurement_transport(internal_key)
        deleted = await marketing_measurement_call(
            measurement_gateway.withdraw(command.anonymous_session_hash)
        )
        return MarketingMeasurementWithdrawalResponse(deleted_event_count=deleted)

    @application.get(
        "/api/v1/marketing-measurement/report",
        operation_id="marketingMeasurementGetReport",
        response_model=MarketingFunnelReportResponse,
        responses={
            200: {
                "description": "Aggregate-only marketing funnel report.",
                "headers": {"X-Request-ID": REQUEST_ID_HEADER},
            }
        }
        | {
            status: marketing_measurement_errors[status]
            for status in (401, 403, 422, 503)
        },
        tags=["marketing-measurement"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def get_marketing_measurement_report(
        window_days: int = Query(default=30, ge=1, le=90),
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
        internal_key: str | None = MARKETING_MEASUREMENT_KEY_DEPENDENCY,
    ) -> MarketingFunnelReportResponse:
        require_marketing_measurement_transport(internal_key)
        access_token = bearer_token(credentials)
        await company_access_call(company_access_service.operator_context(access_token))
        actor_id = await company_access_call(gateway.session_subject(access_token))
        report = await marketing_measurement_call(
            measurement_gateway.report(actor_id, window_days)
        )
        return MarketingFunnelReportResponse.from_domain(report)

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
        started_at = time.perf_counter()
        result = await company_access_call(
            company_access_service.admit_company_year(
                bearer_token(credentials), command
            )
        )
        await passive_validation_observer.after_outcome(
            subject_identifier=str(result.company_id),
            observation=BoundedValidationObservation(
                observation_id=uuid5(
                    NAMESPACE_URL,
                    (
                        "urn:talli:validation:company-year-admission:"
                        f"{command.operation_id}:completed"
                    ),
                ),
                task="company_year_admission",
                state="completed",
                stage="onboarding",
                reason="none",
                elapsed_milliseconds=min(
                    int((time.perf_counter() - started_at) * 1000), 86_400_000
                ),
                intervention_type="none",
                intervention_count=0,
                intervention_milliseconds=0,
                difference_classification="none",
                rerun_result="not_required",
                package_outcome="not_applicable",
            ),
        )
        return result

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
        deprecated=True,
        responses={
            200: {
                "description": (
                    "Deprecated mixed-revision overlap. Customer-directory search is "
                    "disabled and the result is always empty."
                )
            }
            | company_access_success
        }
        | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def search_company_access_operator_companies_deprecated(
        query: str,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> OperatorCompanySearchResponse:
        del query
        await company_access_call(
            company_access_service.operator_context(bearer_token(credentials))
        )
        return OperatorCompanySearchResponse(companies=[])

    @application.post(
        "/api/v1/company-access/operator-support-grants",
        operation_id="companyAccessGrantSupportAccess",
        response_model=SupportAccessGrantResponse,
        status_code=201,
        responses={201: {"description": "Case-bound support access granted."} | company_access_success}
        | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def grant_company_access_operator_support(
        command: GrantSupportAccessRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> SupportAccessGrantResponse:
        return await company_access_call(
            company_access_service.grant_support_access(bearer_token(credentials), command)
        )

    @application.post(
        "/api/v1/company-access/operator-support-grants/{case_id}/revocations",
        operation_id="companyAccessRevokeSupportAccess",
        response_model=SupportAccessGrantResponse,
        responses={200: {"description": "Case-bound support access revoked."} | company_access_success}
        | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def revoke_company_access_operator_support(
        case_id: UUID,
        command: RevokeSupportAccessRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> SupportAccessGrantResponse:
        return await company_access_call(
            company_access_service.revoke_support_access(
                bearer_token(credentials), case_id, command
            )
        )

    @application.post(
        "/api/v1/company-access/operator-support-cases/{case_id}/openings",
        operation_id="companyAccessOpenSupportCase",
        response_model=SupportCaseOpeningResponse,
        status_code=201,
        responses={201: {"description": "Support case opened with durable audit evidence."} | company_access_success}
        | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def open_company_access_operator_support_case(
        case_id: UUID,
        command: OpenSupportCaseRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> SupportCaseOpeningResponse:
        return await company_access_call(
            company_access_service.open_support_case(
                bearer_token(credentials), case_id, command
            )
        )

    @application.get(
        "/api/v1/company-access/operator-support-cases/{case_id}",
        operation_id="companyAccessReadSupportCase",
        response_model=SupportCaseSnapshotResponse,
        responses={200: {"description": "Read-only case-bound support snapshot."} | company_access_success}
        | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def read_company_access_operator_support_case(
        case_id: UUID,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> SupportCaseSnapshotResponse:
        return await company_access_call(
            company_access_service.read_support_case(
                bearer_token(credentials), case_id=case_id
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
        support_case_id: UUID = Header(alias="X-Support-Case-ID"),
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyDeletionReviewResponse:
        return await company_access_call(
            company_access_service.review_deletion(
                bearer_token(credentials), cancellation_id, support_case_id, command
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

    investments_errors: Any = {
        status: {
            "description": "Investments request failed.",
            "headers": {"X-Request-ID": REQUEST_ID_HEADER},
            "content": {
                "application/problem+json": {
                    "schema": ProblemDetails.model_json_schema(by_alias=True)
                }
            },
        }
        for status in (401, 403, 404, 409, 422, 503)
    }
    investments_success: dict[str, Any] = {
        "headers": {"X-Request-ID": REQUEST_ID_HEADER}
    }

    def position_wire(value: InvestmentPositionView) -> InvestmentPositionWire:
        return InvestmentPositionWire(
            id=UUID(str(value.position_id)),
            company_id=UUID(str(value.company_id)),
            investment_key=value.investment_key,
            name=value.name,
            kind=value.kind,
            tax_treatment=value.tax_treatment,
            org_number=value.org_number,
            share_count=value.share_count,
            cost_basis=_money_wire(value.cost_basis),
            lot_history_status=value.lot_history_status,
            movement_count=value.movement_count,
            movements=[dict(movement) for movement in value.movements],
            created_by=UUID(str(value.created_by.subject)),
            created_at=value.created_at.value,
            updated_at=value.updated_at.value,
        )

    def acquisition_lot_wire(value: AcquisitionLotView) -> AcquisitionLotWire:
        return AcquisitionLotWire(
            id=UUID(str(value.lot_id)),
            company_id=UUID(str(value.company_id)),
            position_id=UUID(str(value.position_id)),
            acquisition_action_id=UUID(str(value.acquisition_action_id)),
            acquisition_date=value.acquisition_date.value,
            original_share_count=value.original_share_count,
            remaining_share_count=value.remaining_share_count,
            original_cost_basis=_money_wire(value.original_cost_basis),
            remaining_cost_basis=_money_wire(value.remaining_cost_basis),
            created_by=UUID(str(value.created_by.subject)),
            created_at=value.created_at.value,
        )

    def investment_activity_wire(value: InvestmentActivityView) -> InvestmentActivityWire:
        return InvestmentActivityWire(
            id=UUID(str(value.activity_id)),
            company_id=UUID(str(value.company_id)),
            income_year=int(value.income_year),
            activity_kind=value.activity_kind,
            action_date=value.action_date.value,
            position_id=UUID(str(value.position_id)),
            investment_key=value.investment_key,
            investment_name=value.investment_name,
            investment_kind=value.investment_kind,
            tax_treatment=value.tax_treatment,
            org_number=value.org_number,
            acquisition_lot_id=(
                UUID(str(value.acquisition_lot_id))
                if value.acquisition_lot_id else None
            ),
            share_count=value.share_count,
            purchase_amount=(
                _money_wire(value.purchase_amount) if value.purchase_amount else None
            ),
            sold_share_count=value.sold_share_count,
            proceeds=_money_wire(value.proceeds) if value.proceeds else None,
            fifo_cost_basis_reduction=(
                _money_wire(value.fifo_cost_basis_reduction)
                if value.fifo_cost_basis_reduction else None
            ),
            remaining_share_count=value.remaining_share_count,
            remaining_cost_basis=(
                _money_wire(value.remaining_cost_basis)
                if value.remaining_cost_basis else None
            ),
            paying_company_name=value.paying_company_name,
            declared_date=(
                value.declared_date.value if value.declared_date else None
            ),
            gross_amount=_money_wire(value.gross_amount) if value.gross_amount else None,
            taxable_add_back=(
                _money_wire(value.taxable_add_back) if value.taxable_add_back else None
            ),
            gain_or_loss=_money_wire(value.gain_or_loss) if value.gain_or_loss else None,
            bank_transaction_id=(
                UUID(str(value.bank_transaction_id))
                if value.bank_transaction_id else None
            ),
            document_id=(
                UUID(str(value.document_id)) if value.document_id else None
            ),
            document_status=value.document_status,
            accounting_entry_id=(
                UUID(str(value.accounting_entry_id))
                if value.accounting_entry_id else None
            ),
            created_by=UUID(str(value.created_by.subject)),
            created_at=value.created_at.value,
        )

    def share_sale_allocation_wire(
        value: ShareSaleAllocationView,
    ) -> ShareSaleAllocationWire:
        return ShareSaleAllocationWire(
            id=UUID(str(value.allocation_id)),
            company_id=UUID(str(value.company_id)),
            position_id=UUID(str(value.position_id)),
            lot_id=UUID(str(value.lot_id)),
            sale_action_id=UUID(str(value.sale_action_id)),
            allocation_order=value.allocation_order,
            acquisition_date=value.acquisition_date.value,
            allocated_share_count=value.allocated_share_count,
            allocated_cost_basis=_money_wire(value.allocated_cost_basis),
            created_by=UUID(str(value.created_by.subject)),
            created_at=value.created_at.value,
        )

    @application.get(
        "/api/v1/investments/activity",
        operation_id="investmentsListActivity",
        response_model=InvestmentActivityPageWire,
        responses={200: {"description": "Visible canonical investment activity."} | investments_success}
        | investments_errors,
        tags=["investments"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def list_investment_activity(
        request: Request,
        company_ids: Annotated[list[UUID], Query(alias="companyId", min_length=1, max_length=100)],
        cursor: str | None = Query(default=None, min_length=1, max_length=80),
        limit: int = Query(default=100, ge=1, le=100),
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> InvestmentActivityPageWire:
        async def execute() -> InvestmentActivityPageWire:
            session = await investments_application.session(bearer_token(credentials))
            page = await session.list_activity(
                company_ids=tuple(
                    investments_input(lambda value=value: CompanyId(str(value)))
                    for value in company_ids
                ),
                correlation_id=CorrelationId(request.state.request_id),
                cursor=(
                    investments_input(lambda: InvestmentCursor(cursor))
                    if cursor else None
                ),
                limit=limit,
            )
            return InvestmentActivityPageWire(
                items=[investment_activity_wire(item) for item in page.items],
                page=InvestmentsPageWire(
                    next_cursor=str(page.next_cursor) if page.next_cursor else None,
                    has_more=page.has_more,
                ),
            )

        return await investments_call(execute)

    @application.get(
        "/api/v1/investments/positions",
        operation_id="investmentsListPositions",
        response_model=InvestmentPositionPageWire,
        responses={200: {"description": "Visible investment positions."} | investments_success}
        | investments_errors,
        tags=["investments"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def list_investment_positions(
        request: Request,
        company_ids: Annotated[list[UUID], Query(alias="companyId", min_length=1, max_length=100)],
        cursor: str | None = Query(default=None, min_length=1, max_length=80),
        limit: int = Query(default=100, ge=1, le=100),
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> InvestmentPositionPageWire:
        async def execute() -> InvestmentPositionPageWire:
            session = await investments_application.session(bearer_token(credentials))
            page = await session.list_positions(
                company_ids=tuple(
                    investments_input(lambda value=value: CompanyId(str(value)))
                    for value in company_ids
                ),
                correlation_id=CorrelationId(request.state.request_id),
                cursor=(
                    investments_input(lambda: InvestmentCursor(cursor))
                    if cursor
                    else None
                ),
                limit=limit,
            )
            return InvestmentPositionPageWire(
                items=[position_wire(item) for item in page.items],
                page=InvestmentsPageWire(
                    next_cursor=str(page.next_cursor) if page.next_cursor else None,
                    has_more=page.has_more,
                ),
            )

        return await investments_call(execute)

    @application.get(
        "/api/v1/investments/acquisition-lots",
        operation_id="investmentsListAcquisitionLots",
        response_model=AcquisitionLotPageWire,
        responses={200: {"description": "Visible acquisition lots."} | investments_success}
        | investments_errors,
        tags=["investments"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def list_investment_acquisition_lots(
        request: Request,
        company_ids: Annotated[list[UUID], Query(alias="companyId", min_length=1, max_length=100)],
        cursor: str | None = Query(default=None, min_length=1, max_length=80),
        limit: int = Query(default=100, ge=1, le=100),
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> AcquisitionLotPageWire:
        async def execute() -> AcquisitionLotPageWire:
            session = await investments_application.session(bearer_token(credentials))
            page = await session.list_acquisition_lots(
                company_ids=tuple(
                    investments_input(lambda value=value: CompanyId(str(value)))
                    for value in company_ids
                ),
                correlation_id=CorrelationId(request.state.request_id),
                cursor=(
                    investments_input(lambda: InvestmentCursor(cursor))
                    if cursor
                    else None
                ),
                limit=limit,
            )
            return AcquisitionLotPageWire(
                items=[acquisition_lot_wire(item) for item in page.items],
                page=InvestmentsPageWire(
                    next_cursor=str(page.next_cursor) if page.next_cursor else None,
                    has_more=page.has_more,
                ),
            )

        return await investments_call(execute)

    @application.get(
        "/api/v1/investments/share-sale-allocations",
        operation_id="investmentsListShareSaleAllocations",
        response_model=ShareSaleAllocationPageWire,
        responses={
            200: {"description": "Visible authoritative FIFO allocations."}
            | investments_success
        }
        | investments_errors,
        tags=["investments"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def list_investment_share_sale_allocations(
        request: Request,
        company_ids: Annotated[list[UUID], Query(alias="companyId", min_length=1, max_length=100)],
        cursor: str | None = Query(default=None, min_length=1, max_length=80),
        limit: int = Query(default=100, ge=1, le=100),
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> ShareSaleAllocationPageWire:
        async def execute() -> ShareSaleAllocationPageWire:
            session = await investments_application.session(bearer_token(credentials))
            page = await session.list_share_sale_allocations(
                company_ids=tuple(
                    investments_input(lambda value=value: CompanyId(str(value)))
                    for value in company_ids
                ),
                correlation_id=CorrelationId(request.state.request_id),
                cursor=(
                    investments_input(lambda: InvestmentCursor(cursor))
                    if cursor
                    else None
                ),
                limit=limit,
            )
            return ShareSaleAllocationPageWire(
                items=[share_sale_allocation_wire(item) for item in page.items],
                page=InvestmentsPageWire(
                    next_cursor=str(page.next_cursor) if page.next_cursor else None,
                    has_more=page.has_more,
                ),
            )

        return await investments_call(execute)

    async def execute_investments_share_purchase(
        request: Request,
        command: InvestmentsSharePurchaseWire,
        idempotency_key: str,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> InvestmentsSharePurchaseResultWire:
        async def execute() -> InvestmentsSharePurchaseResultWire:
            session = await investments_application.session(bearer_token(credentials))
            domain = RecordSharePurchaseCommand(
                company_id=CompanyId(str(command.company_id)),
                actor_id=session.actor_id,
                correlation_id=CorrelationId(request.state.request_id),
                idempotency_key=IdempotencyKey(idempotency_key),
                income_year=IncomeYear(command.income_year),
                action_id=InvestmentActionId(str(command.action_id)),
                investment_key=command.investment_key,
                investment_name=command.investment_name,
                investment_kind=command.investment_kind,
                tax_treatment=command.tax_treatment,
                acquisition_date=LocalDate(command.acquisition_date),
                share_count=command.share_count,
                purchase_amount=command.purchase_amount.to_domain(),
                org_number=command.org_number,
                bank_transaction_id=(
                    InvestmentSourceReference(str(command.bank_transaction_id))
                    if command.bank_transaction_id
                    else None
                ),
                document_id=(
                    InvestmentSourceReference(str(command.document_id))
                    if command.document_id
                    else None
                ),
                document_status=command.document_status,
            )
            result = await session.record_share_purchase(domain)
            return InvestmentsSharePurchaseResultWire(
                action_id=UUID(str(result.action_id)),
                position_id=UUID(str(result.position_id)),
                acquisition_lot_id=UUID(str(result.lot_id)),
                accounting_entry_id=UUID(str(result.accounting_entry_id)),
                position_created=result.position_created,
                replayed=result.replayed,
            )

        return await investments_call(execute)

    @application.post(
        "/api/v1/investments/share-purchases",
        operation_id="investmentsRecordSharePurchase",
        response_model=InvestmentsSharePurchaseResultWire,
        status_code=201,
        responses={
            201: {"description": "Share purchase recorded atomically."}
            | investments_success
        }
        | investments_errors,
        tags=["investments"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def record_investments_share_purchase(
        request: Request,
        command: InvestmentsSharePurchaseWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> InvestmentsSharePurchaseResultWire:
        return await execute_investments_share_purchase(
            request, command, idempotency_key, credentials
        )

    @application.post(
        "/api/v1/investments/share-sales",
        operation_id="investmentsRecordShareSale",
        response_model=InvestmentsShareSaleResultWire,
        status_code=201,
        responses={
            201: {"description": "Share sale recorded atomically."}
            | investments_success
        }
        | investments_errors,
        tags=["investments"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def record_investments_share_sale(
        request: Request,
        command: InvestmentsShareSaleWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> InvestmentsShareSaleResultWire:
        async def execute() -> InvestmentsShareSaleResultWire:
            session = await investments_application.session(bearer_token(credentials))
            domain = RecordShareSaleCommand(
                company_id=CompanyId(str(command.company_id)),
                actor_id=session.actor_id,
                correlation_id=CorrelationId(request.state.request_id),
                idempotency_key=IdempotencyKey(idempotency_key),
                income_year=IncomeYear(command.income_year),
                action_id=InvestmentActionId(str(command.action_id)),
                position_id=InvestmentPositionId(str(command.position_id)),
                sale_date=LocalDate(command.sale_date),
                sold_share_count=command.sold_share_count,
                proceeds=command.proceeds.to_domain(),
                bank_transaction_id=(
                    InvestmentSourceReference(str(command.bank_transaction_id))
                    if command.bank_transaction_id
                    else None
                ),
                document_id=(
                    InvestmentSourceReference(str(command.document_id))
                    if command.document_id
                    else None
                ),
                document_status=command.document_status,
            )
            result = await session.record_share_sale(domain)
            return InvestmentsShareSaleResultWire(
                action_id=UUID(str(result.action_id)),
                position_id=UUID(str(result.position_id)),
                accounting_entry_id=UUID(str(result.accounting_entry_id)),
                replayed=result.replayed,
            )

        return await investments_call(execute)

    @application.post(
        "/api/v1/investments/received-dividends",
        operation_id="investmentsRecordReceivedDividend",
        response_model=InvestmentsReceivedDividendResultWire,
        status_code=201,
        responses={
            201: {"description": "Received dividend recorded atomically."}
            | investments_success
        }
        | investments_errors,
        tags=["investments"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def record_investments_received_dividend(
        request: Request,
        command: InvestmentsReceivedDividendWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> InvestmentsReceivedDividendResultWire:
        async def execute() -> InvestmentsReceivedDividendResultWire:
            session = await investments_application.session(bearer_token(credentials))
            domain = RecordReceivedDividendCommand(
                company_id=CompanyId(str(command.company_id)),
                actor_id=session.actor_id,
                correlation_id=CorrelationId(request.state.request_id),
                idempotency_key=IdempotencyKey(idempotency_key),
                income_year=IncomeYear(command.income_year),
                action_id=InvestmentActionId(str(command.action_id)),
                position_id=InvestmentPositionId(str(command.position_id)),
                paying_company_name=command.paying_company_name,
                declared_date=LocalDate(command.declared_date),
                paid_date=LocalDate(command.paid_date),
                gross_amount=command.gross_amount.to_domain(),
                tax_treatment=command.tax_treatment,
                bank_transaction_id=(
                    InvestmentSourceReference(str(command.bank_transaction_id))
                    if command.bank_transaction_id
                    else None
                ),
                document_id=(
                    InvestmentSourceReference(str(command.document_id))
                    if command.document_id
                    else None
                ),
                document_status=command.document_status,
            )
            result = await session.record_received_dividend(domain)
            return InvestmentsReceivedDividendResultWire(
                action_id=UUID(str(result.action_id)),
                position_id=UUID(str(result.position_id)),
                accounting_entry_id=UUID(str(result.accounting_entry_id)),
                taxable_add_back=_money_wire(result.taxable_add_back),
                replayed=result.replayed,
            )

        return await investments_call(execute)

    banking_errors: Any = {
        status: {
            "description": "Banking request failed.",
            "headers": {"X-Request-ID": REQUEST_ID_HEADER},
            "content": {
                "application/problem+json": {
                    "schema": ProblemDetails.model_json_schema(by_alias=True)
                }
            },
        }
        for status in (400, 401, 403, 404, 409, 422, 503)
    }
    banking_success: dict[str, Any] = {
        "headers": {"X-Request-ID": REQUEST_ID_HEADER}
    }

    @application.get(
        "/api/v1/banking/connections",
        operation_id="bankingListConnections",
        response_model=BankConnectionListWire,
        responses={200: {"description": "Authorized bank connections."} | banking_success}
        | banking_errors,
        tags=["banking"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def list_bank_connections(
        request: Request,
        company_id: Annotated[UUID, Query(alias="companyId")],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> BankConnectionListWire:
        async def execute() -> BankConnectionListWire:
            session = await banking_application.session(bearer_token(credentials))
            connections: BankConnectionList = await session.list_connections(
                actor_id=session.actor_id,
                company_id=banking_input(lambda: CompanyId(str(company_id))),
                correlation_id=CorrelationId(request.state.request_id),
            )
            return BankConnectionListWire(
                items=[_bank_connection_wire(item) for item in connections.items]
            )

        return await banking_call(execute)

    @application.post(
        "/api/v1/banking/connections",
        operation_id="bankingStartConnection",
        response_model=BankConsentRedirectWire,
        responses={200: {"description": "Read-only bank consent started."} | banking_success}
        | banking_errors,
        tags=["banking"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def start_bank_connection(
        request: Request,
        command: StartBankConnectionWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> BankConsentRedirectWire:
        async def execute() -> BankConsentRedirectWire:
            session = await banking_application.session(bearer_token(credentials))
            connector_id = banking_input(lambda: BankConnectorId(command.connector_id))
            redirect: BankConsentRedirect = await session.start_connection(
                banking_input(
                    lambda: StartBankConnectionCommand(
                        company_id=CompanyId(str(command.company_id)),
                        actor_id=session.actor_id,
                        correlation_id=CorrelationId(request.state.request_id),
                        idempotency_key=IdempotencyKey(idempotency_key),
                        income_year=IncomeYear(command.income_year),
                        connection_id=BankConnectionId(str(command.connection_id)),
                        connector_id=connector_id,
                        bank_key=command.bank_key,
                        return_url=command.return_url,
                    )
                ),
                banking_provider(connector_id),
            )
            return BankConsentRedirectWire(
                redirect_url=redirect.redirect_url,
                state=redirect.state,
            )

        return await banking_call(execute)

    @application.get(
        "/api/v1/banking/connections/{connection_id}/callback",
        operation_id="bankingCompleteConnection",
        response_model=BankConnectionWire,
        responses={200: {"description": "Bank consent completed."} | banking_success}
        | banking_errors,
        tags=["banking"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def complete_bank_connection(
        request: Request,
        connection_id: UUID,
        company_id: Annotated[UUID, Query(alias="companyId")],
        income_year: Annotated[int, Query(alias="incomeYear", ge=2000, le=2100)],
        code: Annotated[str | None, Query(max_length=4096)] = None,
        state: Annotated[str | None, Query(max_length=4096)] = None,
        resource_id: Annotated[str | None, Query(alias="resource_id", max_length=4096)] = None,
        result: Annotated[str | None, Query(max_length=4096)] = None,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> BankConnectionWire:
        async def execute() -> BankConnectionWire:
            session = await banking_application.session(bearer_token(credentials))
            connector = await canonical_banking_connector(
                session,
                company_id=banking_input(lambda: CompanyId(str(company_id))),
                connection_id=BankConnectionId(str(connection_id)),
                correlation_id=CorrelationId(request.state.request_id),
            )
            callback = {
                key: value
                for key, value in {
                    "code": code,
                    "state": state,
                    "resource_id": resource_id,
                    "result": result,
                }.items()
                if value is not None
            }
            connection = await session.complete_connection(
                banking_input(
                    lambda: CompleteBankConnectionCommand(
                        company_id=CompanyId(str(company_id)),
                        actor_id=session.actor_id,
                        correlation_id=CorrelationId(request.state.request_id),
                        idempotency_key=IdempotencyKey(
                            f"banking-callback:{connection_id}"
                        ),
                        income_year=IncomeYear(income_year),
                        connection_id=BankConnectionId(str(connection_id)),
                        callback_parameters=callback,
                    )
                ),
                banking_provider(connector),
            )
            return _bank_connection_wire(connection)

        return await banking_call(execute)

    @application.post(
        "/api/v1/banking/connections/{connection_id}/revoke",
        operation_id="bankingRevokeConnection",
        status_code=204,
        responses={204: {"description": "Bank connection revoked."} | banking_success}
        | banking_errors,
        tags=["banking"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def revoke_bank_connection(
        request: Request,
        connection_id: UUID,
        command: BankConnectionActionWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> Response:
        async def execute() -> Response:
            session = await banking_application.session(bearer_token(credentials))
            connector = await canonical_banking_connector(
                session,
                company_id=banking_input(lambda: CompanyId(str(command.company_id))),
                connection_id=BankConnectionId(str(connection_id)),
                correlation_id=CorrelationId(request.state.request_id),
            )
            await session.revoke_connection(
                banking_input(
                    lambda: RevokeBankConnectionCommand(
                        company_id=CompanyId(str(command.company_id)),
                        actor_id=session.actor_id,
                        correlation_id=CorrelationId(request.state.request_id),
                        idempotency_key=IdempotencyKey(idempotency_key),
                        income_year=IncomeYear(command.income_year),
                        connection_id=BankConnectionId(str(connection_id)),
                    )
                ),
                banking_provider(connector),
            )
            return Response(status_code=204)

        return await banking_call(execute)

    @application.post(
        "/api/v1/banking/connections/{connection_id}/accounts/{account_id}/syncs",
        operation_id="bankingSyncAccount",
        response_model=BankSyncResultWire,
        responses={200: {"description": "Read-only bank sync completed."} | banking_success}
        | banking_errors,
        tags=["banking"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def sync_bank_account(
        request: Request,
        connection_id: UUID,
        account_id: UUID,
        command: BankSyncWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> BankSyncResultWire:
        async def execute() -> BankSyncResultWire:
            session = await banking_application.session(bearer_token(credentials))
            connector = await canonical_banking_connector(
                session,
                company_id=banking_input(lambda: CompanyId(str(command.company_id))),
                connection_id=BankConnectionId(str(connection_id)),
                correlation_id=CorrelationId(request.state.request_id),
            )
            result: BankSyncResult = await session.sync(
                banking_input(
                    lambda: BankSyncCommand(
                        company_id=CompanyId(str(command.company_id)),
                        actor_id=session.actor_id,
                        correlation_id=CorrelationId(request.state.request_id),
                        idempotency_key=IdempotencyKey(idempotency_key),
                        income_year=IncomeYear(command.income_year),
                        connection_id=BankConnectionId(str(connection_id)),
                        account_id=BankAccountId(str(account_id)),
                        date_from=LocalDate(command.date_from),
                        date_to=LocalDate(command.date_to),
                        mode=command.mode,
                    )
                ),
                banking_provider(connector),
            )
            return BankSyncResultWire(
                attempt_id=str(result.attempt_id),
                page_count=result.page_count,
                imported_count=result.imported_count,
                updated_count=result.updated_count,
                duplicate_count=result.duplicate_count,
                replayed=result.replayed,
            )

        return await banking_call(execute)

    @application.post(
        "/api/v1/banking/source-files/previews",
        operation_id="bankingPreviewSourceFile",
        response_model=BankFilePreviewResultWire,
        responses={200: {"description": "Bank file preview persisted without importing."} | banking_success}
        | banking_errors,
        tags=["banking"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def preview_bank_source_file(
        request: Request,
        command: BankFilePreviewWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> BankFilePreviewResultWire:
        async def execute() -> BankFilePreviewResultWire:
            session = await banking_application.session(bearer_token(credentials))
            mapping = command.column_mapping
            receipt: PersistedBankFilePreview = await session.preview_file(
                banking_input(
                    lambda: BankFilePreviewCommand(
                        company_id=CompanyId(str(command.company_id)),
                        actor_id=session.actor_id,
                        correlation_id=CorrelationId(request.state.request_id),
                        idempotency_key=IdempotencyKey(idempotency_key),
                        income_year=IncomeYear(command.income_year),
                        source_file_id=BankSourceFileId(str(command.source_file_id)),
                        account_id=BankAccountId(str(command.account_id)),
                        data_format=command.data_format,
                        filename=command.filename,
                        content=command.content,
                        column_mapping=(
                            BankFileColumnMapping(**mapping.model_dump())
                            if mapping is not None
                            else None
                        ),
                    )
                )
            )
            preview = receipt.preview
            return BankFilePreviewResultWire(
                source_file_id=str(receipt.source_file_id),
                document_sha256=preview.document_sha256,
                account_mask=preview.account_mask,
                interval_start=preview.interval_start.value,
                interval_end=preview.interval_end.value,
                currency=preview.currency,
                opening_balance=(
                    _money_wire(preview.opening_balance)
                    if preview.opening_balance is not None
                    else None
                ),
                closing_balance=(
                    _money_wire(preview.closing_balance)
                    if preview.closing_balance is not None
                    else None
                ),
                transaction_count=preview.transaction_count,
                duplicate_count=preview.duplicate_count,
                correction_count=preview.correction_count,
                ignored_count=preview.ignored_count,
                replayed=receipt.replayed,
            )

        return await banking_call(execute)

    @application.post(
        "/api/v1/banking/source-files/{source_file_id}/acceptance",
        operation_id="bankingAcceptSourceFile",
        response_model=BankStatementImportResultWire,
        responses={200: {"description": "Previewed bank file explicitly accepted."} | banking_success}
        | banking_errors,
        tags=["banking"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def accept_bank_source_file(
        request: Request,
        source_file_id: UUID,
        command: AcceptBankFileWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> BankStatementImportResultWire:
        async def execute() -> BankStatementImportResultWire:
            session = await banking_application.session(bearer_token(credentials))
            result = await session.accept_file(
                banking_input(
                    lambda: AcceptBankFileCommand(
                        company_id=CompanyId(str(command.company_id)),
                        actor_id=session.actor_id,
                        correlation_id=CorrelationId(request.state.request_id),
                        idempotency_key=IdempotencyKey(idempotency_key),
                        income_year=IncomeYear(command.income_year),
                        source_file_id=BankSourceFileId(str(source_file_id)),
                        document_sha256=command.document_sha256,
                    )
                )
            )
            return BankStatementImportResultWire(
                imported_count=result.imported_count,
                duplicate_count=result.duplicate_count,
                replayed=result.replayed,
            )

        return await banking_call(execute)

    @application.post(
        "/api/v1/banking/statement-imports",
        operation_id="bankingImportStatement",
        response_model=BankStatementImportResultWire,
        responses={
            200: {"description": "Bank statement imported idempotently."}
            | banking_success
        }
        | banking_errors,
        tags=["banking"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def import_bank_statement(
        request: Request,
        command: BankStatementImportWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> BankStatementImportResultWire:
        async def execute() -> BankStatementImportResultWire:
            session = await banking_application.session(bearer_token(credentials))
            result: BankStatementImportResult = await session.import_statement(
                banking_input(
                    lambda: ImportBankStatementCommand(
                        company_id=CompanyId(str(command.company_id)),
                        actor_id=session.actor_id,
                        correlation_id=CorrelationId(request.state.request_id),
                        idempotency_key=IdempotencyKey(idempotency_key),
                        income_year=IncomeYear(command.income_year),
                        data_format=command.data_format,
                        statement_text=command.statement_text,
                    )
                )
            )
            return BankStatementImportResultWire(
                imported_count=result.imported_count,
                duplicate_count=result.duplicate_count,
                replayed=result.replayed,
            )

        return await banking_call(execute)

    @application.get(
        "/api/v1/banking/transactions",
        operation_id="bankingListTransactions",
        response_model=BankTransactionPageWire,
        responses={
            200: {"description": "Authorized bank-transaction page."}
            | banking_success
        }
        | banking_errors,
        tags=["banking"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def list_bank_transactions(
        request: Request,
        company_id: Annotated[
            list[UUID], Query(alias="companyId", min_length=1, max_length=100)
        ],
        cursor: Annotated[str | None, Query(max_length=4096)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> BankTransactionPageWire:
        async def execute() -> BankTransactionPageWire:
            session = await banking_application.session(bearer_token(credentials))
            page: BankTransactionPage = await session.list_transactions(
                actor_id=session.actor_id,
                company_ids=banking_input(
                    lambda: tuple(CompanyId(str(value)) for value in company_id)
                ),
                correlation_id=CorrelationId(request.state.request_id),
                cursor=(
                    banking_input(lambda: BankingCursor(cursor)) if cursor else None
                ),
                limit=limit,
            )
            return BankTransactionPageWire(
                items=[_bank_transaction_wire(item) for item in page.items],
                page=BankingPageWire(
                    next_cursor=(
                        str(page.page.next_cursor)
                        if page.page.next_cursor is not None
                        else None
                    ),
                    has_more=page.page.has_more,
                ),
            )

        return await banking_call(execute)

    @application.post(
        "/api/v1/banking/suggestion-acceptances",
        operation_id="bankingAcceptSuggestion",
        response_model=AcceptedBankSuggestionWire,
        responses={
            200: {"description": "Bank suggestion explicitly accepted."}
            | banking_success
        }
        | banking_errors,
        tags=["banking"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def accept_bank_suggestion(
        request: Request,
        command: AcceptBankSuggestionWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> AcceptedBankSuggestionWire:
        async def execute() -> AcceptedBankSuggestionWire:
            session = await banking_application.session(bearer_token(credentials))
            accepted = await session.accept_suggestion(
                banking_input(
                    lambda: AcceptBankSuggestionCommand(
                        company_id=CompanyId(str(command.company_id)),
                        actor_id=session.actor_id,
                        correlation_id=CorrelationId(request.state.request_id),
                        idempotency_key=IdempotencyKey(idempotency_key),
                        income_year=IncomeYear(command.income_year),
                        acceptance_id=BankSuggestionAcceptanceId(
                            str(command.acceptance_id)
                        ),
                        bank_transaction_id=BankTransactionId(
                            str(command.bank_transaction_id)
                        ),
                        expected_suggestion=command.expected_suggestion,
                        expected_rule_version=command.expected_rule_version,
                    )
                )
            )
            return _accepted_bank_suggestion_wire(accepted)

        return await banking_call(execute)

    @application.get(
        "/api/v1/banking/suggestion-acceptances",
        operation_id="bankingListSuggestionAcceptances",
        response_model=BankSuggestionAcceptancePageWire,
        responses={
            200: {"description": "Authorized suggestion-acceptance page."}
            | banking_success
        }
        | banking_errors,
        tags=["banking"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def list_bank_suggestion_acceptances(
        request: Request,
        company_id: Annotated[
            list[UUID], Query(alias="companyId", min_length=1, max_length=100)
        ],
        cursor: Annotated[str | None, Query(max_length=4096)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> BankSuggestionAcceptancePageWire:
        async def execute() -> BankSuggestionAcceptancePageWire:
            session = await banking_application.session(bearer_token(credentials))
            page: BankSuggestionAcceptancePage = (
                await session.list_suggestion_acceptances(
                    actor_id=session.actor_id,
                    company_ids=banking_input(
                        lambda: tuple(
                            CompanyId(str(value)) for value in company_id
                        )
                    ),
                    correlation_id=CorrelationId(request.state.request_id),
                    cursor=(
                        banking_input(lambda: BankingCursor(cursor))
                        if cursor
                        else None
                    ),
                    limit=limit,
                )
            )
            return BankSuggestionAcceptancePageWire(
                items=[
                    _accepted_bank_suggestion_wire(item) for item in page.items
                ],
                page=BankingPageWire(
                    next_cursor=(
                        str(page.page.next_cursor)
                        if page.page.next_cursor is not None
                        else None
                    ),
                    has_more=page.page.has_more,
                ),
            )

        return await banking_call(execute)

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

    generated_openapi = application.openapi

    def openapi_with_exact_marketing_security() -> dict[str, Any]:
        contract = generated_openapi()
        paths = contract["paths"]
        paths["/api/v1/marketing-measurement/events"]["post"]["security"] = [
            {"marketingMeasurementKey": []}
        ]
        paths["/api/v1/marketing-measurement/withdrawals"]["post"]["security"] = [
            {"marketingMeasurementKey": []}
        ]
        paths["/api/v1/marketing-measurement/report"]["get"]["security"] = [
            {"bearerAuth": [], "marketingMeasurementKey": []}
        ]
        return contract

    application.openapi = openapi_with_exact_marketing_security  # type: ignore[method-assign]

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
