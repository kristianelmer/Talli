from __future__ import annotations

import asyncio
from base64 import b64decode, b64encode
from binascii import Error as Base64Error
from hashlib import sha256
import os
import re
import secrets
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, date, datetime, time as local_time
from decimal import Decimal
from typing import Annotated, Any, Literal, TypeVar, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic.json_schema import SkipJsonSchema
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import ClientDisconnect

from talli_backend.application.shareholder_register_filing_session import (
    ShareholderRegisterFilingAuthenticationError, ShareholderRegisterFilingSessionFactory,
)
from talli_backend.application.shareholder_register_filing_workflow import ShareholderRegisterFilingWorkflow
from talli_backend.application.launch_signoffs import (
    LaunchSignoffAuthenticationError, LaunchSignoffError, LaunchSignoffKey,
    LaunchSignoffRecord, LaunchSignoffSessionFactory, LaunchSignoffStatus,
    LaunchSignoffWorkflow, RecordLaunchSignoff,
)
from talli_backend.application.annual_notifications import AnnualNotificationIntake
from talli_backend.modules.billing.public import AnnualNotificationRejected, AnnualNotificationUnavailable

from talli_backend.adapters.brreg_company_registry import BrregCompanyRegistryAdapter
from talli_backend.adapters.annual_billing_runtime import compose_annual_billing_runtime
from talli_backend.adapters.supabase_banking import compose_banking_application
from talli_backend.adapters.simulation_billing import SimulationBillingProvider
from talli_backend.adapters.supabase_billing import SupabaseBillingAdapter
from talli_backend.adapters.authority_callback_transport import AuthorityCallbackTransport
from talli_backend.application.authority_connections_session import (
    AuthorityConnectionsAuthenticationError,
    AuthorityConnectionsSessionFactory,
)
from talli_backend.modules.authority_connections.public import (
    AuthorityConnectionsError,
    AuthorityOperationCode, AuthorityOperationError, AuthorityOperationKind,
    AuthorityOperationRecord, AuthorityOperationStatus, AuthorityOperationsProvider,
    RunAuthorityOperationCommand,
    AuthorityConnectionsErrorCode,
    AuthorityFailureCode,
    AuthorityProviderError,
    ReconcileSystemUserRequestCommand,
    StartSystemUserRequestCommand,
    SystemUserAuthorityProvider,
    SystemUserFlowResult,
    SystemUserRequest,
    SystemUserRequestStatus,
)
from talli_backend.application.authority_connections_workflow import AuthorityConnectionsWorkflow, AuthorityOperationsWorkflow
from talli_backend.adapters.supabase_annual_billing import SupabaseAnnualBillingAdapter
from talli_backend.adapters.supabase_company_access import SupabaseCompanyAccessAdapter
from talli_backend.adapters.supabase_corporate_governance import (
    compose_corporate_governance_application,
)
from talli_backend.adapters.supabase_documents import SupabaseDocumentsAdapter
from talli_backend.adapters.supabase_ledger import compose_ledger_application
from talli_backend.adapters.postgres_company_tax_filing import compose_company_tax_application
from talli_backend.application.company_tax_filing_session import CompanyTaxSessionFactory
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError, RecordTaxSettlementCommand, TaxSettlementId,
    BankTransactionReference, DocumentReference, TaxSettlementDocumentStatus,
    TaxSettlementKind as CompanyTaxSettlementKind,
)
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
from talli_backend.application.billing_session import (
    BillingAuthenticationError,
    BillingSessionFactory,
)
from talli_backend.application.billing_workflow import BillingWorkflow
from talli_backend.application.annual_billing import AnnualBillingSessionFactory, AnnualBillingWorkflow, AnnualCheckoutWorkflow, AnnualCheckoutPrerequisiteResolver, AnnualAgreementCleanupWorkflow, AnnualSupportWorkflow, AnnualRefundRecoveryWorkflow, AnnualSupportRefundRecoveryWorkflow, AnnualSupportCleanupRecoveryWorkflow
from talli_backend.application.corporate_governance_session import (
    CorporateGovernanceAuthenticationError,
    CorporateGovernanceSessionFactory,
)
from talli_backend.application.investments_session import (
    InvestmentsAuthenticationError,
    InvestmentsSessionFactory,
)
from talli_backend.application.investments_workflow import (
    LegacyInvestmentEvidence,
    LegacyReceivedDividend,
    LegacyReceivedFundDistribution,
    LegacySharePurchase,
    LegacyShareSale,
)
from talli_backend.application.ledger_workflow import (
    LedgerAuthenticationError,
    LedgerSessionFactory,
    LedgerWriterResult,
    NewYearStartCommand,
    RecordAdministrativeCostCommand,

)
from talli_backend.application.new_year_opening import (
    OpeningSnapshotCursor,
    OpeningSnapshotPage,
    OpeningSnapshotView,
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
from talli_backend.modules.billing.public import (
    AnnualSupportQuery, AnnualSupportCaseId, AnnualOperationStatus,
    AnnualBillingSnapshotQuery, AnnualPurchaseHistoryQuery, AnnualPurchaseSummary, AnnualPurchaseId, AnnualPurchaseStatus, CancelAnnualRenewalCommand,
    AnnualBillingProvider, AnnualCheckout, AnnualCheckoutQuery, StartAnnualCheckoutCommand,
    AnnualCheckoutPreparationQuery,
    AnnualRefundRecoveryQuery, AnnualRefundRequestId,
    AnnualRefundRecoveryTargetsQuery, AnnualSupportRefundRecoveryQuery, AnnualSupportRefundRecoveryTargetsQuery,
    AnnualSupportCleanupRecoveryQuery,
    ActivateSubscriptionCommand,
    BillingAccount,
    BillingEntitlementDecision,
    BillingEntitlementQuery,
    BillingError,
    BillingErrorCode,
    BillingObligation,
    BillingPaymentEvent,
    BillingPaymentKind,
    BillingPaymentProvider,
    BillingPaymentStatus,
    BillingPlan,
    BillingSnapshot,
    BillingSnapshotQuery,
    BillingStatus,
    CancelSubscriptionCommand,
    ConfigureBillingAccountCommand,
    ManageProductionPilotEntitlementCommand,
    MarkBillingUnsupportedCommand,
    ProductionPilotEntitlement,
    ProductionPilotEntitlementId,
    ProductionPilotStatus,
    PurchaseFilingPackageCommand,
    RefundFilingPackageCommand,
    SystemUserRequestReference,
)
from talli_backend.modules.corporate_governance.public import (
    AccountingEntryReference as CorporateAccountingEntryReference,
    AnnualCloseLifecycle,
    AnnualCloseEventKind,
    AnnualCloseProposalCommand,
    ApprovedAnnualBasis,
    ApproveOwnerDividendCommand,
    ApproveAnnualCloseCommand,
    AttestAnnualCloseSignedArtifactCommand,
    AttestOwnerDividendSignedArtifactCommand,
    BankTransactionReference,
    BoardMeeting,
    BoardParticipant,
    BoardRole,
    BoardTreatmentMethod,
    BankLoanEventFacts,
    CashCapitalIncreaseEventFacts,
    CanonicalAnnualCloseDecision,
    CanonicalOwnerDividendDecision,
    CorporateArtifactId,
    CorporateArtifactKind,
    CorporateArtifactRecord,
    CorporateArtifactVariant,
    CorporateDecisionKind,
    CorporateDecisionId,
    CorporateDecisionRecord,
    DerivedCorporateDecisionFacts,
    CorporateDocumentReadiness,
    CorporateDocumentReadinessBlocker,
    CorporateDocumentSetId,
    CorporateDocumentSetRecord,
    CorporateEventId,
    CorporateEventRecord,
    CorporateFinalizationId,
    CorporateFinalizationRecord,
    CorporateGovernanceError,
    CorporateGovernanceErrorCode,
    CorporateLifecycleSnapshot,
    CorporateSourceReference,
    DocumentReference,
    FinalizeOwnerDividendCommand,
    FinalizeAnnualCloseCommand,
    GeneralMeeting,
    GroupContributionEventFacts,
    IntercompanyLoanEventFacts,
    LossCoverageCapitalReductionEventFacts,
    OwnerLoanEventFacts,
    MeetingForm,
    OwnerDividendArtifactReference,
    OwnerDividendLifecycle,
    OwnerDividendEventKind,
    OwnerDividendProposalCommand,
    OwnerDividendState,
    PersistedCompanyFacts,
    PersistedShareholderFacts,
    ProposedAnnualClose,
    ProposedOwnerDividend,
    RecordOwnerDividendPaymentCommand as CorporateRecordOwnerDividendPaymentCommand,
    RecordAnnualCloseEventCommand,
    RecordOwnerDividendEventCommand,
    RecordShareholderLoanCommand as CorporateRecordShareholderLoanCommand,
    RecordSupportedCorporateEventCommand,
    ReverseSupportedCorporateEventCommand,
    RecordedShareholderLoan,
    RecordedSupportedCorporateEvent,
    ReversedSupportedCorporateEvent,
    RegisterAnnualCloseDocumentsCommand,
    RegisterOwnerDividendDocumentsCommand,
    ReviewedOwnerDividendFacts,
    ReviewedShareholderFacts,
    ShareholderBallot,
    ShareholderLoanDirection as CorporateShareholderLoanDirection,
    ShareholderLoanDocumentStatus,
    ShareholderVote,
    SupportedCorporateBankFact,
    SupportedCorporateDocumentFact,
    SupportedCorporateEvidenceKind,
    SupportedCorporateEventId,
    SupportedCorporateEventKind,
    SupportedCorporateEventPhase,
    SupportedCorporateEventReference,
    SupportedCorporatePerspective,
    SupportedCorporateRelationship,
    SupportedCorporateSourceFact,
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
    TaxSettlementKind,
)
from talli_backend.modules.documents.public import (
    BeginDocumentUploadCommand,
    DocumentBackupObject,
    DocumentId,
    DocumentObjectTransfer,
    DocumentRecord,
    DocumentStatus,
    DocumentsError,
    DocumentsSessionFactory,
    DocumentTransferKind,
    DocumentUploadTransfer,
)
from talli_backend.modules.investments.public import (
    AcquisitionLotView,
    CorrectInvestmentCommand,
    InvestmentAccountingClassification,
    InvestmentActivityKind,
    InvestmentActivityView,
    InvestmentCursor,
    InvestmentCorrectionId,
    InvestmentCorrectionTargetKind,
    InvestmentCorrectionView,
    InvestmentDocumentStatus,
    InvestmentEvidenceMode,
    InvestmentEvidence,
    InvestmentFactReference,
    InvestmentEconomicEventId,
    InvestmentKind,
    InvestmentTradingProfile,
    InvestmentLotHistoryStatus,
    InvestmentLifecycleEventView,
    InvestmentMeasurementId,
    InvestmentMeasurementRule,
    InvestmentPositionId,
    InvestmentPositionView,
    InvestmentYearEndMeasurementView,
    InvestmentSourceCapability,
    InvestmentSourceReference,
    InvestmentSettlementId,
    InvestmentSettlementBalanceKind,
    InvestmentUnits,
    InvestmentTaxTreatment,
    InvestmentsError,
    RecognizeReceivedDividendCommand,
    RecognizeReceivedFundDistributionCommand,
    RecognizeSharePurchaseCommand,
    RecognizeShareSaleCommand,
    RecordInvestmentYearEndMeasurementCommand,
    SettleInvestmentCashCommand,
    ShareSaleAllocationView,
)
from talli_backend.modules.shareholder_register_filing.public import (
    AcknowledgeRf1086ReviewCommentCommand, AddRf1086ReviewCommentCommand,
    ApprovalId, ApproveRf1086ProductionCommand, ConfirmRf1086FilingPermissionCommand,
    ConfirmRf1086SimulationCommand, GenerateRf1086PreviewCommand, OpeningShareholder,
    Rf1086ArchiveQuery, OpeningSnapshotId, PreviewId, ReadRf1086PreviewQuery, ReconcileRf1086FeedbackCommand,
    RecordRf1086OverrideCommand, RecordRf1086TestEvidenceCommand, ReviewCommentId,
    Rf1086ProductionError, Rf1086RecordedResult, Rf1086WorkspaceQuery,
    SendApprovedRf1086Command, ShareholderRegisterFilingError, SubmissionId,
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
    Timestamp,
    UserId,
)

API_VERSION = "v1"
CONTRACT_VERSION = "1.0.0"
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
REQUEST_ID_HEADER = {
    "description": "Correlation identifier for the request and response.",
    "schema": {"type": "string"},
}
InvestmentUnitsWireValue = Annotated[
    str,
    Field(pattern=r"^(?:0|[1-9][0-9]{0,25})(?:\.[0-9]{1,12})?$"),
]
SignedInvestmentUnitsWireValue = Annotated[
    str,
    Field(pattern=r"^-?(?:0|[1-9][0-9]{0,25})(?:\.[0-9]{1,12})?$"),
]
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


class AnnualBillingOfferWire(TransportModel):
    company_id: UUID
    income_year: int
    offer_version: str
    terms_digest: str
    terms_text: str
    currency: Literal["NOK"]
    gross_minor: int = Field(gt=0)
    net_minor: int = Field(gt=0)
    vat_minor: int = Field(ge=0)
    vat_basis_points: int
    paid_through: date
    export_through: date
    renewal_date: date
    renewal_reminder_by: date
    price_change_notice_by: date


class AnnualOperationCountsWire(TransportModel):
    created: int = Field(ge=0)
    pending: int = Field(ge=0)
    unknown: int = Field(ge=0)
    confirmed: int = Field(ge=0)
    failed: int = Field(ge=0)


class AnnualPurchaseSummaryWire(TransportModel):
    purchase_id: UUID
    company_id: UUID
    income_year: int
    status: AnnualPurchaseStatus
    accepted_at: datetime
    offer_version: str
    terms_digest: str
    terms_text: str
    currency: Literal["NOK"]
    gross_minor: int = Field(gt=0)
    net_minor: int = Field(gt=0)
    vat_minor: int = Field(ge=0)
    vat_basis_points: int
    captured_minor: int = Field(ge=0)
    refunded_minor: int = Field(ge=0)
    captured_at: datetime | None
    recurring_consent: bool
    renewal_canceled_at: datetime | None
    paid_through: date
    export_through: date
    renewal_date: date


class AnnualPurchaseRefundSummaryWire(AnnualPurchaseSummaryWire):
    recorded_refund_minor: int = Field(ge=0)
    remaining_refund_minor: int = Field(ge=0)
    refund_initiate_by: date | None
    refund_request_count: int = Field(ge=0)
    latest_refund_requested_at: datetime | None
    refund_operations: AnnualOperationCountsWire


class AnnualBillingSnapshotWire(TransportModel):
    offer: AnnualBillingOfferWire
    purchases: list[AnnualPurchaseSummaryWire]
    next_purchase_id: UUID | None


class AnnualBillingRefundSnapshotWire(TransportModel):
    offer: AnnualBillingOfferWire
    purchases: list[AnnualPurchaseRefundSummaryWire]
    next_purchase_id: UUID | None


class AnnualPurchaseHistoryWire(TransportModel):
    company_id: UUID
    purchases: list[AnnualPurchaseRefundSummaryWire]
    next_purchase_id: UUID | None


class AnnualSupportPurchaseWire(TransportModel):
    purchase_id: UUID
    company_id: UUID
    income_year: int = Field(ge=2000, le=2100)
    status: AnnualPurchaseStatus
    accepted_at: datetime
    updated_at: datetime
    currency: Literal["NOK"]
    gross_minor: int = Field(gt=0)
    captured_minor: int = Field(ge=0)
    refunded_minor: int = Field(ge=0)
    renewal_canceled_at: datetime | None
    paid_through: date
    export_through: date
    recurring_consent: bool
    refund_case_count: int = Field(ge=0)
    recorded_refund_minor: int = Field(ge=0)
    remaining_refund_minor: int = Field(ge=0)
    refund_initiate_by: date | None
    refund_request_count: int = Field(ge=0)
    latest_refund_requested_at: datetime | None
    refund_operations: AnnualOperationCountsWire
    cleanup_status: AnnualOperationStatus | None


class AnnualSupportPageWire(TransportModel):
    company_id: UUID
    support_case_id: UUID
    purchases: list[AnnualSupportPurchaseWire]
    next_purchase_id: UUID | None


class AnnualCheckoutCommandWire(StrictTransportModel):
    company_id: UUID
    income_year: int = Field(ge=2000, le=2100)
    offer_version: str = Field(min_length=1, max_length=100)
    terms_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    purchase_accepted: bool = Field(strict=True)
    recurring_consent: bool = Field(strict=True)
    consent_version: str = Field(min_length=1, max_length=100)


class AnnualCheckoutObservationCommandWire(StrictTransportModel):
    company_id: UUID
    purchase_id: UUID


class AnnualCheckoutWire(TransportModel):
    purchase_id: UUID
    company_id: UUID
    income_year: int
    status: AnnualPurchaseStatus
    offer: AnnualBillingOfferWire
    captured_minor: int = Field(ge=0)
    refunded_minor: int = Field(ge=0)
    checkout_url: str | None


class AnnualCheckoutPreparationWire(TransportModel):
    company_id: UUID
    income_year: int = Field(ge=2000, le=2100)
    state: Literal["available", "existing"]
    offer: AnnualBillingOfferWire | None
    consent_version: str | None
    purchase_id: UUID | None


class AnnualCheckoutRequestResolutionWire(TransportModel):
    company_id: UUID
    income_year: int = Field(ge=2000, le=2100)
    state: Literal["existing", "withdrawn"]
    purchase_id: UUID | None
    withdrawal_id: UUID | None
    withdrawn_at: datetime | None


class AnnualRefundRecoveryCommandWire(StrictTransportModel):
    company_id: UUID
    purchase_id: UUID
    refund_request_id: UUID


class AnnualRefundRecoveryWire(TransportModel):
    company_id: UUID
    purchase_id: UUID
    refund_request_id: UUID
    income_year: int
    status: Literal["pending", "unknown", "confirmed", "failed"]


class AnnualRefundRecoveryTargetWire(TransportModel):
    refund_request_id: UUID
    requested_at: datetime
    status: AnnualOperationStatus


class AnnualRefundRecoveryTargetPageWire(TransportModel):
    company_id: UUID
    purchase_id: UUID
    income_year: int = Field(ge=2000, le=2100)
    targets: list[AnnualRefundRecoveryTargetWire]
    next_refund_request_id: UUID | None


class AnnualSupportRefundRecoveryCommandWire(AnnualRefundRecoveryCommandWire):
    support_case_id: UUID


class AnnualSupportRefundRecoveryWire(AnnualRefundRecoveryWire):
    support_case_id: UUID


class AnnualSupportRefundRecoveryTargetPageWire(AnnualRefundRecoveryTargetPageWire):
    support_case_id: UUID


class AnnualSupportCleanupRecoveryCommandWire(StrictTransportModel):
    company_id: UUID
    purchase_id: UUID
    support_case_id: UUID


class AnnualSupportCleanupRecoveryWire(TransportModel):
    company_id: UUID
    purchase_id: UUID
    support_case_id: UUID
    operation_id: UUID
    income_year: int = Field(ge=2000, le=2100)
    status: Literal["pending", "unknown", "confirmed"]


class AnnualRenewalCancellationCommandWire(StrictTransportModel):
    company_id: UUID
    purchase_id: UUID


class AnnualAgreementCleanupCommandWire(StrictTransportModel):
    company_id: UUID
    purchase_id: UUID


class AnnualAgreementCleanupWire(TransportModel):
    company_id: UUID
    purchase_id: UUID
    status: Literal["deferred", "pending", "unknown", "confirmed"]


class AnnualRenewalCancellationWire(TransportModel):
    cancellation_id: UUID
    purchase_id: UUID
    company_id: UUID
    income_year: int
    requested_at: datetime
    effective_at: datetime
    paid_through: date
    export_through: date


class BillingConfigureWire(StrictTransportModel):
    company_id: UUID
    pricing_plan: BillingPlan
    founder_cohort_number: int | None = Field(default=None, ge=1, le=100)


class SystemUserCommandWire(StrictTransportModel):
    company_id: UUID
    request_id: UUID


class SystemUserCallbackWire(StrictTransportModel):
    request_id: UUID


class SystemUserResultWire(TransportModel):
    request_id: UUID
    company_id: UUID
    status: SystemUserRequestStatus
    preflight_verified_at: datetime | None
    confirmation_url: str | None
    failure_code: AuthorityFailureCode | None


class SystemUserRecordWire(SystemUserResultWire):
    initiating_owner_user_id: UUID
    obligation: Literal["aksjonaerregisteroppgaven"]
    external_reference: str
    provider_request_id: UUID | None
    operator_evidence_id: UUID | None
    requested_at: datetime | None
    last_status_checked_at: datetime | None
    accepted_at: datetime | None
    resolved_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None


class SystemUserListWire(TransportModel):
    requests: list[SystemUserRecordWire]


class AuthorityOperationCommandWire(StrictTransportModel):
    operation_id: UUID
    operation: AuthorityOperationKind
    confirmation: str = Field(max_length=128)


class AuthorityOperationRecordWire(TransportModel):
    operation_id: UUID
    operation: AuthorityOperationKind
    actor_id: UUID
    status: AuthorityOperationStatus
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_code: AuthorityOperationCode
    metadata: dict[str, str]
    authority_http_status: int | None
    created_at: datetime
    completed_at: datetime | None


class AuthorityOperationListWire(TransportModel):
    operations: list[AuthorityOperationRecordWire]


class LaunchSignoffCommandWire(StrictTransportModel):
    key: LaunchSignoffKey
    status: LaunchSignoffStatus
    reviewer: str
    reviewed_at: datetime
    evidence_link: str
    decision: str


class LaunchSignoffRecordWire(TransportModel):
    key: LaunchSignoffKey
    status: LaunchSignoffStatus
    reviewer: str
    reviewed_at: datetime
    evidence_link: str
    decision: str
    recorded_by: UUID
    updated_at: datetime


class LaunchSignoffListWire(TransportModel):
    signoffs: list[LaunchSignoffRecordWire]


class LegacyRf1086SendCommandWire(StrictTransportModel):
    approval_id: UUID


class LegacyRf1086ReconcileCommandWire(StrictTransportModel):
    submission_id: UUID


class LegacyRf1086SendResultWire(TransportModel):
    submission_id: UUID


class LegacyRf1086ReconcileResultWire(TransportModel):
    state: Literal["sent", "processing", "accepted", "rejected", "action_required", "unknown"] | None
    error_code: Literal["invalid_request", "authentication_required", "approval_expired", "basis_unavailable",
        "connection_unavailable", "payload_changed", "configuration_unavailable", "send_unavailable",
        "status_unavailable", "status_busy", "step_up_required"] | None
    requires_manual_retry: bool


class Rf1086GeneratePreviewWire(StrictTransportModel):
    company_id: UUID
    opening_snapshot_id: UUID


class Rf1086OverrideCommandWire(StrictTransportModel):
    preview_id: UUID
    field_target: str
    old_value: str
    new_value: str
    reason: str
    risk_level: Literal["advisory", "warning", "block"]
    owner_confirmed: bool = Field(strict=True)


class Rf1086ReviewCommentCommandWire(StrictTransportModel):
    preview_id: UUID
    severity: Literal["advisory", "hard_block"]
    body: str


class Rf1086ReviewAcknowledgementWire(StrictTransportModel):
    comment_id: UUID


class Rf1086SimulationCommandWire(StrictTransportModel):
    preview_id: UUID
    authority_confirmed: bool = Field(strict=True)
    preview_confirmed: bool = Field(strict=True)


class Rf1086PermissionCommandWire(StrictTransportModel):
    company_id: UUID
    production_enabled: bool = Field(strict=True)


class Rf1086TestEvidenceCommandWire(StrictTransportModel):
    company_id: UUID
    environment: Literal["test", "manual_evidence"]
    status: Literal["accepted", "rejected", "blocked", "pending"]
    test_reference: str
    feedback_summary: str
    receipt_reference: str | None
    archive_reference: str | None
    evidence_url: str | None
    payload_hash: str | None


class Rf1086ProductionApprovalCommandWire(StrictTransportModel):
    preview_id: UUID
    entitlement_id: UUID
    real_filing_confirmed: bool = Field(strict=True)


class Rf1086RecordedResultWire(TransportModel):
    record_id: UUID
    company_id: UUID
    income_year: int | None


class Rf1086IssueWire(TransportModel):
    level: str
    code: str
    message: str


class Rf1086PreviewWire(TransportModel):
    id: UUID
    company_id: UUID
    setup_id: UUID | None
    income_year: int
    filing: str
    status: Literal["ready", "blocked", "warning"]
    issues: list[Rf1086IssueWire]
    preview: str
    hovedskjema_xml: str | None
    underskjema_xml: dict[str, str]
    source: str
    created_at: datetime


class Rf1086OverrideWire(TransportModel):
    id: UUID
    preview_id: UUID | None
    company_id: UUID
    income_year: int
    filing: str
    field_target: str
    old_value: str
    new_value: str
    reason: str
    risk_level: Literal["advisory", "warning", "block"]
    owner_confirmed_by: UUID
    owner_confirmed_at: datetime
    created_by: UUID
    created_at: datetime


class Rf1086ReviewCommentWire(TransportModel):
    id: UUID
    preview_id: UUID
    company_id: UUID
    target: str
    severity: Literal["advisory", "hard_block"]
    body: str
    created_by: UUID
    acknowledged_by: UUID | None
    acknowledged_at: datetime | None
    created_at: datetime


class Rf1086PermissionWire(TransportModel):
    id: UUID
    company_id: UUID
    obligation: Literal["aksjonaerregisteroppgaven"]
    submitter_user_id: UUID
    confirmed_by: UUID
    confirmed_at: datetime
    production_enabled: bool
    updated_at: datetime


class Rf1086TestEvidenceWire(TransportModel):
    id: UUID
    company_id: UUID
    obligation: Literal["aksjonaerregisteroppgaven"]
    environment: Literal["test", "manual_evidence"]
    status: Literal["accepted", "rejected", "blocked", "pending"]
    test_reference: str
    feedback_summary: str
    receipt_reference: str | None
    archive_reference: str | None
    evidence_url: str | None
    payload_hash: str | None
    recorded_by: UUID
    recorded_at: datetime


def _validate_rf1086_historical_timestamp(value: str) -> str:
    # These values are retained JSON evidence, unlike top-level DB timestamps.
    # Validate without rewriting the original fractional precision or offset.
    datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


Rf1086HistoricalTimestampWire = Annotated[
    str, AfterValidator(_validate_rf1086_historical_timestamp),
    Field(json_schema_extra={"format": "date-time"}),
]


class Rf1086SimulationCallWire(TransportModel):
    endpoint: str
    body_hash: str
    idempotency_key: str | None
    status: str
    created_at: Rf1086HistoricalTimestampWire


class Rf1086SimulationFeedbackWire(TransportModel):
    severity: Literal["accepted", "error", "warning"]
    code: str
    message: str
    document_id: str | None


class Rf1086ReceiptMetadataWire(TransportModel):
    authority: Literal["simulation", "skatteetaten"]
    receipt_id: str
    status: Literal["receipt_stored"]
    received_at: Rf1086HistoricalTimestampWire
    feedback_document_ids: list[str]


class Rf1086SubmittedPayloadReferenceWire(TransportModel):
    preview_id: UUID
    payload_hash: str
    hovedskjema_hash: str | None
    underskjema_hashes: dict[str, str]
    call_count: int
    stored_at: Rf1086HistoricalTimestampWire


class Rf1086SubmittedPayloadWire(TransportModel):
    filing: str
    company_id: UUID
    income_year: int
    payload_hash: str
    hovedskjema_xml: str | None
    underskjema_xml: dict[str, str]


class Rf1086SimulationWire(TransportModel):
    id: UUID
    preview_id: UUID | None
    authority_test_run_id: UUID | None
    company_id: UUID
    income_year: int
    filing: str
    mode: Literal["simulation", "test_authority"]
    adapter_mode: Literal["simulation", "test_authority", "production"]
    payload_hash: str | None
    idempotency_key: str | None
    status: str
    calls: list[Rf1086SimulationCallWire]
    receipt_id: str | None
    feedback_document_ids: list[str]
    feedback_items: list[Rf1086SimulationFeedbackWire]
    receipt_metadata: Rf1086ReceiptMetadataWire | None
    submitted_payload_ref: Rf1086SubmittedPayloadReferenceWire | None
    submitted_payload: Rf1086SubmittedPayloadWire | None
    authority_confirmed_at: datetime | None
    preview_confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    submitted_by: UUID | None


class Rf1086ApprovalWire(TransportModel):
    id: UUID
    entitlement_id: UUID
    preview_id: UUID
    company_id: UUID
    user_id: UUID
    income_year: int
    obligation: Literal["aksjonaerregisteroppgaven"]
    case_profile: Literal["rf1086_no_activity_v1"]
    adapter_version: str
    payload_hash: str
    manifest_hash: str
    manifest: dict[str, Any]
    approved_by: UUID
    approved_at: datetime
    invalidated_at: datetime | None
    invalidation_reason: str | None


class Rf1086ProductionSubmissionWire(TransportModel):
    id: UUID
    approval_id: UUID
    entitlement_id: UUID
    company_id: UUID
    user_id: UUID
    income_year: int
    obligation: Literal["aksjonaerregisteroppgaven"]
    case_profile: Literal["rf1086_no_activity_v1"]
    payload_hash: str
    adapter_version: str
    environment: Literal["production"]
    status: Literal["approved", "sending", "received", "processing", "accepted", "rejected", "action_required", "unknown"]
    authority_references: dict[str, str]
    failure_class: str | None
    supersedes_submission_id: UUID | None
    submitted_by: UUID
    feedback_state: Literal["sent", "processing", "accepted", "rejected", "action_required", "unknown"]
    feedback_artifact_count: int
    feedback_last_checked_at: datetime | None
    feedback_last_changed_at: datetime | None
    feedback_safe_error_code: str | None
    feedback_correlation_id: str | None
    created_at: datetime
    updated_at: datetime


class Rf1086FeedbackArtifactWire(TransportModel):
    id: UUID
    company_id: UUID
    submission_id: UUID
    document_id: UUID
    content_type: Literal["application/xml", "text/xml", "application/pdf", "text/plain", "application/octet-stream"]
    byte_length: int
    sha256: str
    retrieved_at: datetime
    classification: Literal["accepted", "rejected", "action_required"]


class Rf1086ActionAvailabilityWire(TransportModel):
    action: str
    allowed: bool
    reason_code: str | None


class Rf1086WorkspaceWire(TransportModel):
    company_id: UUID
    income_year: int | None
    previews: list[Rf1086PreviewWire]
    simulations: list[Rf1086SimulationWire]
    overrides: list[Rf1086OverrideWire]
    review_comments: list[Rf1086ReviewCommentWire]
    permissions: list[Rf1086PermissionWire]
    test_evidence: list[Rf1086TestEvidenceWire]
    approvals: list[Rf1086ApprovalWire]
    production_submissions: list[Rf1086ProductionSubmissionWire]
    feedback_artifacts: list[Rf1086FeedbackArtifactWire]
    actions: list[Rf1086ActionAvailabilityWire]


class Rf1086ArchiveSourceWire(TransportModel):
    company_id: UUID
    income_year: int = Field(ge=2000, le=2100)
    previews: list[Rf1086PreviewWire]
    simulations: list[Rf1086SimulationWire]
    review_comments: list[Rf1086ReviewCommentWire]
    permissions: list[Rf1086PermissionWire]
    test_evidence: list[Rf1086TestEvidenceWire]


class BillingCompanyWire(StrictTransportModel):
    company_id: UUID


class BillingFilingPackageWire(BillingCompanyWire):
    income_year: int = Field(ge=2000, le=2100)
    obligation: BillingObligation = BillingObligation.SHAREHOLDER_REGISTER


class BillingUnsupportedWire(BillingCompanyWire):
    reason: str = Field(min_length=1, max_length=500)


class BillingPilotEntitlementCommandWire(BillingCompanyWire):
    entitlement_id: UUID | None = None
    user_id: UUID
    income_year: int = Field(ge=2000, le=2100)
    status: ProductionPilotStatus
    billing_exempt: bool
    system_user_request_id: UUID
    starts_at: datetime
    expires_at: datetime
    evidence_reference: str = Field(min_length=1, max_length=1000)


class BillingAccountWire(TransportModel):
    company_id: UUID
    pricing_plan: BillingPlan
    monthly_nok: int
    filing_package_nok: int
    founder_cohort_number: int | None
    subscription_active: bool
    filing_package_paid: bool
    supported_case: bool
    refund_eligible: bool
    refund_completed: bool
    no_charge_reason: str | None
    provider_customer_reference: str | None
    subscription_provider_reference: str | None
    filing_package_payment_reference: str | None
    refund_provider_reference: str | None
    updated_by: UUID
    created_at: datetime
    updated_at: datetime


class BillingPricingWire(TransportModel):
    plan: BillingPlan
    monthly_nok: int
    filing_package_nok: int


class BillingPaymentEventWire(TransportModel):
    event_id: UUID
    company_id: UUID
    provider: str
    provider_reference: str
    idempotency_key: str
    kind: BillingPaymentKind
    status: BillingPaymentStatus
    amount_nok: int
    income_year: int | None
    created_by: UUID
    created_at: datetime
    replayed: bool


class BillingPilotEntitlementWire(TransportModel):
    entitlement_id: UUID
    company_id: UUID
    user_id: UUID
    income_year: int
    obligation: BillingObligation
    case_profile: str
    status: ProductionPilotStatus
    billing_exempt: bool
    system_user_request_id: UUID
    system_user_external_reference: str
    starts_at: datetime
    expires_at: datetime
    evidence_reference: str
    approved_by: UUID
    created_at: datetime
    updated_at: datetime


class BillingEntitlementDecisionWire(TransportModel):
    company_id: UUID
    income_year: int
    obligation: BillingObligation
    status: BillingStatus
    allowed: bool
    charge_allowed: bool
    readiness_allowed: bool
    billing_exempt: bool
    message: str
    pilot_entitlement_id: UUID | None


class BillingSnapshotWire(TransportModel):
    accounts: list[BillingAccountWire]
    payment_events: list[BillingPaymentEventWire]
    pilot_entitlements: list[BillingPilotEntitlementWire]
    pricing: list[BillingPricingWire]


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


class CorporateCompanyFactsWire(StrictTransportModel):
    organization_number: str = Field(pattern=r"^\d{9}$")
    legal_name: str = Field(min_length=1, max_length=255)


class CorporateShareholderWire(StrictTransportModel):
    shareholder_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    share_count: int = Field(gt=0, le=9_007_199_254_740_991)
    order: int = Field(ge=0, le=10_000)


class CorporateReviewedShareholderWire(StrictTransportModel):
    shareholder_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    share_count: int = Field(gt=0, le=9_007_199_254_740_991)


class CorporateAnnualBasisWire(StrictTransportModel):
    source_id: UUID
    income_year: int = Field(ge=2000, le=2200)
    latest_approved: bool
    annual_data_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    governance_basis_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_after_tax_ore: int = Field(
        ge=-9_007_199_254_740_991, le=9_007_199_254_740_991
    )
    equity_ore: int = Field(ge=-9_007_199_254_740_991, le=9_007_199_254_740_991)
    available_distribution_ore: int = Field(ge=0, le=9_007_199_254_740_991)
    cash_ore: int = Field(ge=-9_007_199_254_740_991, le=9_007_199_254_740_991)


class CorporateReviewedFactsWire(StrictTransportModel):
    organization_number: str = Field(pattern=r"^\d{9}$")
    legal_name: str = Field(min_length=1, max_length=255)
    shareholders: list[CorporateReviewedShareholderWire] = Field(
        min_length=1, max_length=10_000
    )
    total_company_shares: int = Field(gt=0, le=9_007_199_254_740_991)
    available_distribution_ore: int = Field(ge=0, le=9_007_199_254_740_991)
    annual_data_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    governance_basis_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CorporateDecisionFactsWire(StrictTransportModel):
    company: CorporateCompanyFactsWire
    shareholders: list[CorporateShareholderWire]
    annual_basis: CorporateAnnualBasisWire
    reviewed_facts: CorporateReviewedFactsWire


class CorporateBoardMeetingWire(StrictTransportModel):
    meeting_date: date
    meeting_time: local_time
    place: str = Field(min_length=1, max_length=255)
    treatment_method: BoardTreatmentMethod


class CorporateBoardParticipantWire(StrictTransportModel):
    participant_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    role: BoardRole
    order: int = Field(ge=0, le=10_000)


class CorporateGeneralMeetingWire(StrictTransportModel):
    meeting_date: date
    meeting_time: local_time
    place: str = Field(min_length=1, max_length=255)
    meeting_form: MeetingForm
    chair_name: str = Field(min_length=1, max_length=255)
    co_signer_name: str = Field(min_length=1, max_length=255)


class CorporateShareholderBallotWire(StrictTransportModel):
    shareholder_id: str = Field(min_length=1, max_length=255)
    represented_share_count: int = Field(gt=0, le=9_007_199_254_740_991)
    vote: ShareholderVote


class CorporateDecisionProposalWire(StrictTransportModel):
    company_id: UUID
    income_year: int = Field(ge=2000, le=2200)
    decision_id: UUID
    document_set_id: UUID
    company: CorporateCompanyFactsWire
    shareholders: list[CorporateShareholderWire] = Field(
        min_length=1, max_length=10_000
    )
    annual_basis: CorporateAnnualBasisWire
    reviewed_facts: CorporateReviewedFactsWire
    board_meeting: CorporateBoardMeetingWire
    board_participants: list[CorporateBoardParticipantWire] = Field(
        min_length=1, max_length=100
    )
    general_meeting: CorporateGeneralMeetingWire
    shareholder_ballots: list[CorporateShareholderBallotWire] = Field(
        min_length=1, max_length=10_000
    )
    one_share_class_confirmed: bool
    full_board_participation_confirmed: bool
    unanimous_board_confirmed: bool
    supported_dividend_basis_confirmed: bool
    prudent_equity_and_liquidity_confirmed: bool


class OwnerDividendProposalWire(CorporateDecisionProposalWire):
    dividend_amount_ore: int = Field(gt=0, le=9_007_199_254_740_991)
    payment_date: date


class AnnualCloseProposalWire(CorporateDecisionProposalWire):
    annual_result_allocation_ore: int = Field(
        ge=-9_007_199_254_740_991,
        le=9_007_199_254_740_991,
    )


class OwnerDividendArtifactWire(StrictTransportModel):
    artifact_id: UUID
    document_id: UUID
    artifact_kind: CorporateArtifactKind
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_length: int = Field(gt=0, le=9_007_199_254_740_991)


class OwnerDividendDocumentsWire(StrictTransportModel):
    company_id: UUID
    document_set_id: UUID
    decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifacts: list[OwnerDividendArtifactWire] = Field(min_length=2, max_length=2)


class OwnerDividendApprovalWire(StrictTransportModel):
    company_id: UUID
    document_set_id: UUID
    decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_event_id: UUID


class AnnualCloseEventWire(StrictTransportModel):
    company_id: UUID
    document_set_id: UUID
    decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_id: UUID
    event_kind: AnnualCloseEventKind
    metadata: dict[str, str]


class AnnualCloseFinalizationWire(StrictTransportModel):
    company_id: UUID
    document_set_id: UUID
    decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    finalization_id: UUID


class AnnualCloseSignedArtifactWire(StrictTransportModel):
    company_id: UUID
    document_set_id: UUID
    decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    unsigned_artifact_id: UUID
    signed_artifact_id: UUID
    signed_document_id: UUID
    artifact_kind: Literal[
        "annual_board_minutes", "annual_general_meeting_minutes"
    ]
    filename: str = Field(min_length=1, max_length=255)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_length: int = Field(ge=1, le=10_485_760)


class OwnerDividendEventWire(StrictTransportModel):
    company_id: UUID
    document_set_id: UUID
    decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_id: UUID
    event_kind: OwnerDividendEventKind
    metadata: dict[str, str]


class OwnerDividendSignedArtifactWire(StrictTransportModel):
    company_id: UUID
    document_set_id: UUID
    decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    unsigned_artifact_id: UUID
    signed_artifact_id: UUID
    signed_document_id: UUID
    artifact_kind: Literal[
        "dividend_board_proposal", "dividend_general_meeting_minutes"
    ]
    filename: str = Field(min_length=1, max_length=255)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_length: int = Field(ge=1, le=10_485_760)


class OwnerDividendFinalizationWire(StrictTransportModel):
    company_id: UUID
    income_year: int = Field(ge=2000, le=2200)
    document_set_id: UUID
    decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    finalization_id: UUID
    holding_action_id: UUID
    ledger_entry_id: UUID


class OwnerDividendPaymentWire(StrictTransportModel):
    company_id: UUID
    income_year: int = Field(ge=2000, le=2200)
    document_set_id: UUID
    decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    payment_event_id: UUID
    holding_action_id: UUID
    ledger_entry_id: UUID
    bank_transaction_id: UUID


class ShareholderLoanWire(StrictTransportModel):
    company_id: UUID
    income_year: int = Field(ge=2000, le=2200)
    action_id: UUID
    ledger_entry_id: UUID
    loan_date: date
    amount: LedgerMoneyWire
    direction: CorporateShareholderLoanDirection
    counterparty_name: str = Field(min_length=1, max_length=255)
    document_status: ShareholderLoanDocumentStatus
    interest_modelled: bool
    related_party_security: bool
    bank_transaction_id: UUID | None
    document_id: UUID | None


class SupportedCorporateDocumentFactWire(StrictTransportModel):
    document_id: UUID
    evidence_kind: SupportedCorporateEvidenceKind
    revision: int = Field(ge=1)
    content_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


class SupportedCorporateSourceFactWire(StrictTransportModel):
    record_id: UUID
    revision: int = Field(ge=1)
    fact_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


class SupportedCorporateBankFactWire(StrictTransportModel):
    transaction_id: UUID
    transaction_date: date
    signed_amount: LedgerMoneyWire
    source_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


class CashCapitalIncreaseEventFactsWire(StrictTransportModel):
    fact_type: Literal["cash_capital_increase"]
    nominal_increase: LedgerMoneyWire
    share_premium: LedgerMoneyWire
    issued_share_count: int = Field(ge=1)
    single_ordinary_class: bool
    cash_only: bool
    binding_subscription: bool
    full_timely_payment: bool
    independent_confirmation: bool
    register_reconciled: bool
    norwegian_subscribers_only: bool
    no_special_terms: bool
    no_direct_use_exception: bool
    issue_costs_resolved: bool


class LossCoverageCapitalReductionEventFactsWire(StrictTransportModel):
    fact_type: Literal["loss_coverage_capital_reduction"]
    nominal_reduction: LedgerMoneyWire
    old_share_capital: LedgerMoneyWire
    new_share_capital: LedgerMoneyWire
    single_ordinary_class: bool
    unchanged_owners_and_share_count: bool
    loss_only: bool
    loss_evidenced: bool
    other_equity_exhausted: bool
    no_value_transfer: bool
    no_creditor_notice: bool
    no_simultaneous_capital_change: bool
    register_reconciled: bool


class IntercompanyLoanEventFactsWire(StrictTransportModel):
    fact_type: Literal["intercompany_loan"]
    perspective: SupportedCorporatePerspective
    relationship: SupportedCorporateRelationship
    principal: LedgerMoneyWire
    counterparty_name: str = Field(min_length=1, max_length=255)
    counterparty_organization_number: str = Field(pattern=r"^\d{9}$")
    norwegian_counterparty: bool
    signed_agreement: bool
    ordinary_terms: bool
    approval_or_exemption_evidenced: bool
    arm_length_confirmed: bool
    interest_limitation_cleared: bool
    no_complex_terms: bool


class OwnerLoanEventFactsWire(StrictTransportModel):
    fact_type: Literal["owner_loan"]
    principal: LedgerMoneyWire
    owner_name: str = Field(min_length=1, max_length=255)
    owner_is_recorded_shareholder: bool
    norwegian_owner: bool
    signed_agreement: bool
    ordinary_terms: bool
    approval_or_exemption_evidenced: bool
    interest_and_tax_treatment_cleared: bool
    no_security_or_conversion: bool
    no_complex_terms: bool


class BankLoanEventFactsWire(StrictTransportModel):
    fact_type: Literal["bank_loan"]
    principal: LedgerMoneyWire
    interest: LedgerMoneyWire
    fee: LedgerMoneyWire
    lender_name: str = Field(min_length=1, max_length=255)
    norwegian_lender: bool
    signed_agreement: bool
    lender_allocation_confirmed: bool
    ordinary_terms: bool
    no_complex_terms: bool


class GroupContributionEventFactsWire(StrictTransportModel):
    fact_type: Literal["group_contribution"]
    relationship: SupportedCorporateRelationship
    perspective: SupportedCorporatePerspective
    gross_tax_amount: LedgerMoneyWire
    related_tax: LedgerMoneyWire
    after_tax_accounting_amount: LedgerMoneyWire
    counterparty_name: str = Field(min_length=1, max_length=255)
    counterparty_organization_number: str = Field(pattern=r"^\d{9}$")
    both_norwegian: bool
    ownership_basis_points: int = Field(ge=0, le=10_000)
    voting_basis_points: int = Field(ge=0, le=10_000)
    year_end_group_eligibility_proved: bool
    corporate_approval_evidenced: bool
    distribution_capacity_confirmed: bool
    prudent_equity_and_liquidity_confirmed: bool
    post_acquisition_income_proved: bool
    impairment_cleared: bool
    no_equity_method: bool
    no_non_cash_or_circular_route: bool
    consolidation_not_required: bool


SupportedCorporateEventFactsWire = Annotated[
    CashCapitalIncreaseEventFactsWire
    | LossCoverageCapitalReductionEventFactsWire
    | IntercompanyLoanEventFactsWire
    | OwnerLoanEventFactsWire
    | BankLoanEventFactsWire
    | GroupContributionEventFactsWire,
    Field(discriminator="fact_type"),
]


class SupportedCorporateEventWire(StrictTransportModel):
    company_id: UUID
    income_year: int = Field(ge=2000, le=2100)
    event_id: UUID
    event_reference: UUID
    event_date: date
    event_kind: SupportedCorporateEventKind
    phase: SupportedCorporateEventPhase
    facts: SupportedCorporateEventFactsWire
    document_facts: list[SupportedCorporateDocumentFactWire] = Field(
        min_length=1, max_length=12
    )
    bank_fact: SupportedCorporateBankFactWire | None = None
    shareholder_register_fact: SupportedCorporateSourceFactWire | None = None
    tax_calculation_fact: SupportedCorporateSourceFactWire | None = None


class RecordedSupportedCorporateEventWire(TransportModel):
    event_id: UUID
    event_reference: UUID
    company_id: UUID
    income_year: int
    event_date: date
    event_kind: SupportedCorporateEventKind
    phase: SupportedCorporateEventPhase
    policy_version: Literal["corporate-governance-supported-events-2026.1"]
    canonical_facts: dict[str, Any]
    facts_sha256: str
    document_facts: list[SupportedCorporateDocumentFactWire]
    signed_artifact_hashes: dict[str, str]
    finalization_sha256: str
    lifecycle_state: Literal["finalized"]
    accounting_entry_id: UUID
    bank_transaction_id: UUID | None
    correction_of_event_id: UUID | None
    recorded_at: datetime
    replayed: bool


class ReverseSupportedCorporateEventWire(StrictTransportModel):
    company_id: UUID
    income_year: int = Field(ge=2000, le=2100)
    reversal_date: date
    reason: str = Field(min_length=1, max_length=500)
    correction_document_fact: SupportedCorporateDocumentFactWire


class ReversedSupportedCorporateEventWire(TransportModel):
    original_event_id: UUID
    original_accounting_entry_id: UUID
    reversal_accounting_entry_id: UUID
    company_id: UUID
    income_year: int
    reversed_at: datetime
    replayed: bool


class RecordedShareholderLoanWire(TransportModel):
    action_id: UUID
    company_id: UUID
    income_year: int
    loan_date: date
    amount_ore: int
    direction: CorporateShareholderLoanDirection
    counterparty_name: str
    document_status: ShareholderLoanDocumentStatus
    interest_modelled: bool
    related_party_security: bool
    bank_transaction_id: UUID | None
    document_id: UUID | None
    accounting_entry_id: UUID
    replayed: bool


class CorporateFinancialTotalsWire(TransportModel):
    result_after_tax_ore: int
    equity_ore: int
    available_distribution_ore: int
    cash_ore: int


class CorporateCanonicalBoardParticipantWire(TransportModel):
    participant_id: str
    name: str
    role: BoardRole


class CorporateCanonicalShareholderWire(TransportModel):
    shareholder_id: str
    name: str
    share_count: int
    represented_share_count: int
    vote: ShareholderVote


class OwnerDividendAllocationWire(TransportModel):
    shareholder_id: str
    amount_ore: int


class CorporateOwnerDividendFactsWire(TransportModel):
    amount_ore: int
    payment_date: date
    liquidity_after_payment_ore: int
    allocations: list[OwnerDividendAllocationWire]


class CorporateOwnerDividendConfirmationsWire(TransportModel):
    latest_approved_annual_accounts: bool
    supported_dividend_basis: bool
    full_board_participation: bool
    full_share_representation: bool
    unanimous_board: bool
    unanimous_shareholders: bool
    proportional_allocation: bool
    prudent_equity_and_liquidity: bool


class CorporateCanonicalDecisionWire(TransportModel):
    decision_kind: Literal["owner_dividend", "annual_close"]
    decision_id: UUID
    document_set_id: UUID
    company_id: UUID
    organization_number: str
    legal_name: str
    income_year: int
    annual_close_source_id: UUID
    source_hash: str
    template_family: str
    template_version: str
    annual_basis_year: int
    financial_totals: CorporateFinancialTotalsWire
    board_meeting: CorporateBoardMeetingWire
    board_participants: list[CorporateCanonicalBoardParticipantWire]
    general_meeting: CorporateGeneralMeetingWire
    shareholders: list[CorporateCanonicalShareholderWire]
    total_company_shares: int
    one_share_class_confirmed: bool
    dividend: CorporateOwnerDividendFactsWire | None
    annual_result_allocation_ore: int
    confirmations: CorporateOwnerDividendConfirmationsWire
    decision_hash: str


class ProposedOwnerDividendWire(TransportModel):
    decision: CorporateCanonicalDecisionWire
    state: OwnerDividendState
    replayed: bool
    artifacts: list["RenderedCorporateArtifactWire"]


class ProposedAnnualCloseWire(TransportModel):
    decision: CorporateCanonicalDecisionWire
    state: OwnerDividendState
    replayed: bool
    artifacts: list["RenderedCorporateArtifactWire"]


class RenderedCorporateArtifactWire(TransportModel):
    artifact_kind: CorporateArtifactKind
    filename: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_length: int
    decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_base64: str


class OwnerDividendLifecycleWire(TransportModel):
    decision_id: UUID
    document_set_id: UUID
    company_id: UUID
    income_year: int
    decision_hash: str
    state: OwnerDividendState
    declared_amount_ore: int
    paid_amount_ore: int
    remaining_amount_ore: int
    finalization_id: UUID | None
    accounting_entry_id: UUID | None
    replayed: bool


class AnnualCloseLifecycleWire(TransportModel):
    decision_id: UUID
    document_set_id: UUID
    company_id: UUID
    income_year: int
    decision_hash: str
    state: OwnerDividendState
    generated_artifact_hashes: dict[str, str]
    signed_artifact_hashes: dict[str, str]
    finalization_id: UUID | None
    replayed: bool


class CorporateDecisionRecordWire(TransportModel):
    decision_id: UUID
    document_set_id: UUID
    company_id: UUID
    income_year: int
    decision_kind: CorporateDecisionKind
    annual_close_source_id: UUID
    source_hash: str
    canonical_input: dict[str, Any]
    decision_hash: str
    supersedes_decision_id: UUID | None
    created_by: UUID
    created_at: datetime


class CorporateDocumentSetRecordWire(TransportModel):
    document_set_id: UUID
    company_id: UUID
    income_year: int
    decision_id: UUID
    template_family: str
    template_version: str
    decision_hash: str
    supersedes_document_set_id: UUID | None
    created_by: UUID
    created_at: datetime


class CorporateArtifactRecordWire(TransportModel):
    artifact_id: UUID
    company_id: UUID
    income_year: int
    document_set_id: UUID
    artifact_kind: CorporateArtifactKind
    variant: CorporateArtifactVariant
    document_id: UUID
    content_sha256: str
    byte_length: int
    supersedes_artifact_id: UUID | None
    created_by: UUID
    created_at: datetime


class CorporateEventRecordWire(TransportModel):
    event_id: UUID
    company_id: UUID
    income_year: int
    decision_id: UUID
    document_set_id: UUID
    artifact_id: UUID | None
    event_kind: str
    actor_id: UUID
    occurred_at: datetime
    created_at: datetime
    decision_hash: str
    content_sha256: str | None
    metadata: dict[str, Any]
    idempotency_key: str


class CorporateFinalizationRecordWire(TransportModel):
    finalization_id: UUID
    company_id: UUID
    income_year: int
    decision_id: UUID
    finalization_kind: str
    holding_action_id: UUID | None
    accounting_entry_id: UUID | None
    annual_close_source_id: UUID | None
    decision_hash: str
    signed_artifact_hashes: dict[str, str]
    accounting_policy_version: str | None
    created_by: UUID
    created_at: datetime


class CorporateLifecycleSnapshotWire(TransportModel):
    decisions: list[CorporateDecisionRecordWire]
    document_sets: list[CorporateDocumentSetRecordWire]
    artifacts: list[CorporateArtifactRecordWire]
    events: list[CorporateEventRecordWire]
    finalizations: list[CorporateFinalizationRecordWire]


class CorporateDocumentReadinessBlockerWire(TransportModel):
    code: str
    message: str


class CorporateDocumentReadinessWire(TransportModel):
    company_id: UUID
    income_year: int
    decision_kind: CorporateDecisionKind
    decision_id: UUID | None
    document_set_id: UUID | None
    decision_hash: str | None
    source_hash: str | None
    current_source_hash: str | None
    state: OwnerDividendState | None
    current_source_matches: bool | None
    ready_for_signing: bool
    finalized: bool
    annual_submission_ready: bool
    generated_artifact_hashes: dict[str, str]
    signed_artifact_hashes: dict[str, str]
    required_signers: dict[str, list[str]]
    declared_amount_ore: int | None
    paid_amount_ore: int | None
    remaining_amount_ore: int | None
    finalization_id: UUID | None
    accounting_policy_version: str | None
    blockers: list[CorporateDocumentReadinessBlockerWire]


class InvestmentsSharePurchaseWire(LedgerCompanyYearWire):
    action_id: UUID
    investment_key: str = Field(min_length=1, max_length=255)
    investment_name: str = Field(min_length=1, max_length=255)
    investment_kind: InvestmentKind
    accounting_classification: InvestmentAccountingClassification
    tax_treatment: InvestmentTaxTreatment
    acquisition_date: date
    share_count: int = Field(gt=0, le=9_007_199_254_740_991)
    purchase_amount: LedgerMoneyWire
    transaction_costs: LedgerMoneyWire
    org_number: str | None = Field(default=None, pattern=r"^\d{9}$")
    fund_equity_ratio_basis_points: int | None = Field(default=None, ge=0, le=10_000)
    fund_tax_statement_reference: str | None = Field(default=None, min_length=1, max_length=255)
    trading_profile: InvestmentTradingProfile
    non_active_trading_confirmed: bool
    share_class_code: str | None = Field(default=None, min_length=1, max_length=80)
    single_share_class_confirmed: bool | None = None
    equal_share_rights_confirmed: bool | None = None
    unusual_share_rights_absent_confirmed: bool | None = None
    evidence_mode: InvestmentEvidenceMode
    evidence_reference: str = Field(min_length=1, max_length=255)
    owner_attested: bool
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
    transaction_costs: LedgerMoneyWire
    sale_year_fund_equity_ratio_basis_points: int | None = Field(default=None, ge=0, le=10_000)
    fund_tax_statement_reference: str | None = Field(default=None, min_length=1, max_length=255)
    evidence_mode: InvestmentEvidenceMode
    evidence_reference: str = Field(min_length=1, max_length=255)
    owner_attested: bool
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
    lawful_dividend_confirmed: bool
    group_exception_claimed: bool
    year_end_ownership_basis_points: int | None = Field(default=None, ge=0, le=10_000)
    year_end_voting_basis_points: int | None = Field(default=None, ge=0, le=10_000)
    group_evidence_reference: str | None = Field(default=None, min_length=1, max_length=255)
    evidence_mode: InvestmentEvidenceMode
    evidence_reference: str = Field(min_length=1, max_length=255)
    owner_attested: bool
    bank_transaction_id: UUID | None = None
    document_id: UUID | None = None
    document_status: InvestmentDocumentStatus


class InvestmentsReceivedDividendResultWire(TransportModel):
    action_id: UUID
    position_id: UUID
    accounting_entry_id: UUID
    taxable_add_back: LedgerMoneyWire
    replayed: bool


class InvestmentsReceivedFundDistributionWire(LedgerCompanyYearWire):
    action_id: UUID
    position_id: UUID
    fund_name: str = Field(min_length=1, max_length=255)
    entitlement_date: date
    paid_date: date
    gross_amount: LedgerMoneyWire
    opening_fund_equity_ratio_basis_points: int = Field(ge=0, le=10_000)
    fund_tax_statement_reference: str = Field(min_length=1, max_length=255)
    evidence_mode: InvestmentEvidenceMode
    evidence_reference: str = Field(min_length=1, max_length=255)
    owner_attested: bool
    bank_transaction_id: UUID | None = None
    document_id: UUID | None = None
    document_status: InvestmentDocumentStatus


class InvestmentsReceivedFundDistributionResultWire(TransportModel):
    action_id: UUID
    position_id: UUID
    accounting_entry_id: UUID
    dividend_portion: LedgerMoneyWire
    interest_portion: LedgerMoneyWire
    taxable_add_back: LedgerMoneyWire
    total_taxable_income: LedgerMoneyWire
    replayed: bool


class InvestmentFactReferenceWire(StrictTransportModel):
    capability: InvestmentSourceCapability
    record_id: UUID
    revision: int = Field(ge=1)
    fact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    def to_domain(self) -> InvestmentFactReference:
        return InvestmentFactReference(
            capability=self.capability,
            record_id=InvestmentSourceReference(str(self.record_id)),
            revision=self.revision,
            fact_sha256=self.fact_sha256,
        )


class InvestmentsLifecycleEvidenceWire(LedgerCompanyYearWire):
    evidence_mode: InvestmentEvidenceMode
    evidence_reference: str = Field(min_length=1, max_length=500)
    owner_attested: bool
    document_facts: list[InvestmentFactReferenceWire] = Field(
        default_factory=list, max_length=50
    )
    bank_fact: InvestmentFactReferenceWire | None = None

    def evidence_domain(self) -> InvestmentEvidence:
        return InvestmentEvidence(
            mode=self.evidence_mode,
            reference=self.evidence_reference,
            owner_attested=self.owner_attested,
            document_facts=tuple(fact.to_domain() for fact in self.document_facts),
            bank_fact=(self.bank_fact.to_domain() if self.bank_fact else None),
        )


class InvestmentsRecognizeSharePurchaseWire(InvestmentsLifecycleEvidenceWire):
    event_id: UUID
    investment_key: str = Field(min_length=1, max_length=255)
    investment_name: str = Field(min_length=1, max_length=255)
    investment_kind: InvestmentKind
    accounting_classification: InvestmentAccountingClassification
    acquisition_date: date
    share_count: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,25})(?:\.[0-9]{1,12})?$")
    purchase_amount: LedgerMoneyWire
    transaction_costs: LedgerMoneyWire
    org_number: str | None = Field(default=None, pattern=r"^\d{9}$")
    fund_equity_ratio_basis_points: int | None = Field(default=None, ge=0, le=10_000)
    fund_tax_statement_reference: str | None = Field(default=None, min_length=1, max_length=255)
    trading_profile: InvestmentTradingProfile
    non_active_trading_confirmed: bool
    share_class_code: str | None = Field(default=None, min_length=1, max_length=80)
    single_share_class_confirmed: bool | None = None
    equal_share_rights_confirmed: bool | None = None
    unusual_share_rights_absent_confirmed: bool | None = None


class InvestmentsRecognizeShareSaleWire(InvestmentsLifecycleEvidenceWire):
    event_id: UUID
    position_id: UUID
    sale_date: date
    sold_share_count: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,25})(?:\.[0-9]{1,12})?$")
    proceeds: LedgerMoneyWire
    transaction_costs: LedgerMoneyWire
    sale_year_fund_equity_ratio_basis_points: int | None = Field(default=None, ge=0, le=10_000)
    fund_tax_statement_reference: str | None = Field(default=None, min_length=1, max_length=255)


class InvestmentsRecognizeReceivedDividendWire(InvestmentsLifecycleEvidenceWire):
    event_id: UUID
    position_id: UUID
    paying_company_name: str = Field(min_length=1, max_length=255)
    declared_date: date
    gross_amount: LedgerMoneyWire
    lawful_dividend_confirmed: bool
    group_exception_claimed: bool
    year_end_ownership_basis_points: int | None = Field(default=None, ge=0, le=10_000)
    year_end_voting_basis_points: int | None = Field(default=None, ge=0, le=10_000)
    group_evidence_reference: str | None = Field(default=None, min_length=1, max_length=255)


class InvestmentsRecognizeReceivedFundDistributionWire(
    InvestmentsLifecycleEvidenceWire
):
    event_id: UUID
    position_id: UUID
    fund_name: str = Field(min_length=1, max_length=255)
    entitlement_date: date
    gross_amount: LedgerMoneyWire
    opening_fund_equity_ratio_basis_points: int = Field(ge=0, le=10_000)
    fund_tax_statement_reference: str = Field(min_length=1, max_length=255)


class InvestmentsSettleCashWire(InvestmentsLifecycleEvidenceWire):
    settlement_id: UUID
    event_id: UUID
    settlement_date: date
    amount: LedgerMoneyWire


class InvestmentsYearEndMeasurementWire(InvestmentsLifecycleEvidenceWire):
    measurement_id: UUID
    position_id: UUID
    as_of: date
    observed_or_recoverable_value: LedgerMoneyWire
    tax_value: LedgerMoneyWire


class InvestmentsYearEndMeasurementResultWire(TransportModel):
    measurement_id: UUID
    position_id: UUID
    accounting_entry_id: UUID | None
    measurement_rule: InvestmentMeasurementRule
    closing_book_value: LedgerMoneyWire
    tax_basis: LedgerMoneyWire
    tax_value: LedgerMoneyWire
    replayed: bool


class InvestmentsSharePurchaseRecognitionWire(
    InvestmentsRecognizeSharePurchaseWire
):
    replacement_kind: Literal["share_purchase"]


class InvestmentsShareSaleRecognitionWire(InvestmentsRecognizeShareSaleWire):
    replacement_kind: Literal["share_sale"]


class InvestmentsDividendRecognitionWire(
    InvestmentsRecognizeReceivedDividendWire
):
    replacement_kind: Literal["dividend_received"]


class InvestmentsFundDistributionRecognitionWire(
    InvestmentsRecognizeReceivedFundDistributionWire
):
    replacement_kind: Literal["fund_distribution_received"]


class InvestmentsCashSettlementWire(InvestmentsSettleCashWire):
    replacement_kind: Literal["cash_settlement"]


class InvestmentsReplacementCashSettlementWire(InvestmentsSettleCashWire):
    replacement_kind: Literal["cash_settlement"]


class InvestmentsEconomicEventResultWire(TransportModel):
    event_id: UUID
    position_id: UUID
    recognition_accounting_entry_id: UUID
    expected_settlement_amount: LedgerMoneyWire
    settlement_balance_kind: InvestmentSettlementBalanceKind
    replayed: bool


class InvestmentsCashSettlementResultWire(TransportModel):
    settlement_id: UUID
    event_id: UUID
    settlement_accounting_entry_id: UUID
    replayed: bool


InvestmentsLifecycleReplacementWire = Annotated[
    InvestmentsSharePurchaseRecognitionWire
    | InvestmentsShareSaleRecognitionWire
    | InvestmentsDividendRecognitionWire
    | InvestmentsFundDistributionRecognitionWire
    | InvestmentsCashSettlementWire,
    Field(discriminator="replacement_kind"),
]


class InvestmentsCorrectionWire(InvestmentsLifecycleEvidenceWire):
    correction_id: UUID
    target_kind: InvestmentCorrectionTargetKind
    original_record_id: UUID
    original_activity_kind: InvestmentActivityKind
    correction_date: date
    reason: str = Field(min_length=1, max_length=500)
    replacement: InvestmentsLifecycleReplacementWire
    original_settlement_id: UUID | None = None
    settlement_correction_id: UUID | None = None
    replacement_settlement: InvestmentsReplacementCashSettlementWire | None = None

    @model_validator(mode="after")
    def validate_settled_event_bundle(self):
        bundle = (
            self.original_settlement_id,
            self.settlement_correction_id,
            self.replacement_settlement,
        )
        if any(item is not None for item in bundle) and not all(
            item is not None for item in bundle
        ):
            raise ValueError("settled event correction bundle must be complete")
        if self.replacement_settlement is not None and (
            self.target_kind is not InvestmentCorrectionTargetKind.ECONOMIC_EVENT
            or isinstance(self.replacement, InvestmentsCashSettlementWire)
            or self.replacement_settlement.event_id != self.replacement.event_id
        ):
            raise ValueError("settled event correction bundle is inconsistent")
        return self


class InvestmentsCorrectionResultWire(TransportModel):
    correction_id: UUID
    target_kind: InvestmentCorrectionTargetKind
    original_record_id: UUID
    replacement_record_id: UUID
    reversal_accounting_entry_id: UUID
    replacement_accounting_entry_id: UUID
    replayed: bool


class InvestmentCorrectionWire(TransportModel):
    id: UUID
    company_id: UUID
    income_year: int
    target_kind: InvestmentCorrectionTargetKind
    original_record_id: UUID
    original_activity_kind: InvestmentActivityKind
    reversal_accounting_entry_id: UUID
    replacement_record_id: UUID
    replacement_activity_kind: InvestmentActivityKind
    replacement_accounting_entry_id: UUID
    reason: str
    document_facts: list[InvestmentFactReferenceWire]
    legacy_bank_transaction_id: UUID | None
    legacy_document_id: UUID | None
    legacy_document_status: InvestmentDocumentStatus | None
    legacy: bool
    evidence_mode: InvestmentEvidenceMode
    evidence_reference: str
    evidence_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    owner_attested: bool
    created_by: UUID
    created_at: datetime


class InvestmentsPageWire(TransportModel):
    next_cursor: str | None
    has_more: bool


class InvestmentCorrectionPageWire(TransportModel):
    items: list[InvestmentCorrectionWire]
    page: InvestmentsPageWire


class InvestmentYearEndMeasurementViewWire(TransportModel):
    id: UUID
    company_id: UUID
    income_year: int
    position_id: UUID
    as_of: date
    measurement_rule: InvestmentMeasurementRule
    quantity: InvestmentUnitsWireValue
    source_book_cost: LedgerMoneyWire
    pre_measurement_book_value: LedgerMoneyWire
    observed_or_recoverable_value: LedgerMoneyWire
    impairment_amount: LedgerMoneyWire
    reversal_amount: LedgerMoneyWire
    closing_book_value: LedgerMoneyWire
    tax_basis: LedgerMoneyWire
    tax_value: LedgerMoneyWire
    evidence_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    calculation_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    accounting_entry_id: UUID | None
    created_by: UUID
    created_at: datetime


class InvestmentYearEndMeasurementPageWire(TransportModel):
    items: list[InvestmentYearEndMeasurementViewWire]
    page: InvestmentsPageWire


class InvestmentPositionMovementWire(BaseModel):
    model_config = ConfigDict(extra="allow")

    movement_type: str
    movement_date: date
    share_delta: SignedInvestmentUnitsWireValue


class InvestmentPositionWire(TransportModel):
    id: UUID
    company_id: UUID
    investment_key: str
    name: str
    kind: InvestmentKind
    accounting_classification: InvestmentAccountingClassification
    tax_treatment: InvestmentTaxTreatment
    org_number: str | None
    fund_equity_ratio_basis_points: int | None
    fund_tax_statement_reference: str | None
    share_count: InvestmentUnitsWireValue
    cost_basis: LedgerMoneyWire
    tax_basis: LedgerMoneyWire
    lot_history_status: InvestmentLotHistoryStatus
    movement_count: int
    movements: list[InvestmentPositionMovementWire]
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
    original_share_count: InvestmentUnitsWireValue
    remaining_share_count: InvestmentUnitsWireValue
    original_cost_basis: LedgerMoneyWire
    remaining_cost_basis: LedgerMoneyWire
    original_tax_basis: LedgerMoneyWire
    remaining_tax_basis: LedgerMoneyWire
    acquisition_year_fund_equity_ratio_basis_points: int | None
    fund_tax_statement_reference: str | None
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
    accounting_classification: InvestmentAccountingClassification
    tax_treatment: InvestmentTaxTreatment
    org_number: str | None
    fund_equity_ratio_basis_points: int | None
    fund_tax_statement_reference: str | None
    acquisition_lot_id: UUID | None
    share_count: InvestmentUnitsWireValue | None
    purchase_amount: LedgerMoneyWire | None
    transaction_costs: LedgerMoneyWire | None
    capitalized_cost: LedgerMoneyWire | None
    sold_share_count: InvestmentUnitsWireValue | None
    proceeds: LedgerMoneyWire | None
    net_proceeds: LedgerMoneyWire | None
    fifo_cost_basis_reduction: LedgerMoneyWire | None
    fifo_tax_basis_reduction: LedgerMoneyWire | None
    remaining_share_count: InvestmentUnitsWireValue | None
    remaining_cost_basis: LedgerMoneyWire | None
    remaining_tax_basis: LedgerMoneyWire | None
    paying_company_name: str | None
    declared_date: date | None
    gross_amount: LedgerMoneyWire | None
    taxable_add_back: LedgerMoneyWire | None
    gain_or_loss: LedgerMoneyWire | None
    book_gain_or_loss: LedgerMoneyWire | None
    tax_gain_or_loss: LedgerMoneyWire | None
    exempt_gain: LedgerMoneyWire | None
    taxable_gain: LedgerMoneyWire | None
    non_deductible_loss: LedgerMoneyWire | None
    deductible_loss: LedgerMoneyWire | None
    lawful_dividend_confirmed: bool | None
    group_exception_claimed: bool | None
    group_exception_applied: bool | None
    year_end_ownership_basis_points: int | None
    year_end_voting_basis_points: int | None
    group_evidence_reference: str | None
    fund_name: str | None
    entitlement_date: date | None
    opening_fund_equity_ratio_basis_points: int | None
    dividend_portion: LedgerMoneyWire | None
    interest_portion: LedgerMoneyWire | None
    total_taxable_income: LedgerMoneyWire | None
    bank_transaction_id: UUID | None
    document_id: UUID | None
    document_status: InvestmentDocumentStatus
    evidence_mode: InvestmentEvidenceMode
    evidence_reference: str
    evidence_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    calculation_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    owner_attested: bool
    accounting_entry_id: UUID | None
    created_by: UUID
    created_at: datetime


class InvestmentActivityPageWire(TransportModel):
    items: list[InvestmentActivityWire]
    page: InvestmentsPageWire


class InvestmentLifecycleEventWire(TransportModel):
    id: UUID
    company_id: UUID
    income_year: int
    activity_kind: InvestmentActivityKind
    recognition_date: date
    position_id: UUID
    investment_key: str
    investment_name: str
    investment_kind: InvestmentKind
    accounting_classification: InvestmentAccountingClassification
    tax_treatment: InvestmentTaxTreatment
    org_number: str | None
    fund_equity_ratio_basis_points: int | None
    fund_tax_statement_reference: str | None
    acquisition_lot_id: UUID | None
    position_created: bool | None
    share_count: InvestmentUnitsWireValue | None
    purchase_amount: LedgerMoneyWire | None
    transaction_costs: LedgerMoneyWire | None
    capitalized_cost: LedgerMoneyWire | None
    sold_share_count: InvestmentUnitsWireValue | None
    proceeds: LedgerMoneyWire | None
    net_proceeds: LedgerMoneyWire | None
    fifo_cost_basis_reduction: LedgerMoneyWire | None
    fifo_tax_basis_reduction: LedgerMoneyWire | None
    remaining_share_count: InvestmentUnitsWireValue | None
    remaining_cost_basis: LedgerMoneyWire | None
    remaining_tax_basis: LedgerMoneyWire | None
    book_gain_or_loss: LedgerMoneyWire | None
    tax_gain_or_loss: LedgerMoneyWire | None
    exempt_gain: LedgerMoneyWire | None
    taxable_gain: LedgerMoneyWire | None
    non_deductible_loss: LedgerMoneyWire | None
    deductible_loss: LedgerMoneyWire | None
    paying_company_name: str | None
    lawful_dividend_confirmed: bool | None
    group_exception_claimed: bool | None
    group_exception_applied: bool | None
    year_end_ownership_basis_points: int | None
    year_end_voting_basis_points: int | None
    group_evidence_reference: str | None
    fund_name: str | None
    entitlement_date: date | None
    opening_fund_equity_ratio_basis_points: int | None
    gross_amount: LedgerMoneyWire | None
    taxable_add_back: LedgerMoneyWire | None
    dividend_portion: LedgerMoneyWire | None
    interest_portion: LedgerMoneyWire | None
    total_taxable_income: LedgerMoneyWire | None
    expected_settlement_amount: LedgerMoneyWire
    settlement_balance_kind: InvestmentSettlementBalanceKind
    recognition_accounting_entry_id: UUID
    document_facts: list[InvestmentFactReferenceWire]
    evidence_mode: InvestmentEvidenceMode
    evidence_reference: str
    evidence_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    calculation_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    owner_attested: bool
    settlement_id: UUID | None
    settlement_date: date | None
    settlement_amount: LedgerMoneyWire | None
    bank_fact: InvestmentFactReferenceWire | None
    settlement_accounting_entry_id: UUID | None
    created_by: UUID
    created_at: datetime


class InvestmentLifecycleEventPageWire(TransportModel):
    items: list[InvestmentLifecycleEventWire]
    page: InvestmentsPageWire


class ShareSaleAllocationWire(TransportModel):
    id: UUID
    company_id: UUID
    position_id: UUID
    lot_id: UUID
    sale_action_id: UUID
    allocation_order: int
    acquisition_date: date
    allocated_share_count: InvestmentUnitsWireValue
    allocated_cost_basis: LedgerMoneyWire
    allocated_book_cost_basis: LedgerMoneyWire
    allocated_tax_basis: LedgerMoneyWire
    allocated_net_proceeds: LedgerMoneyWire
    average_fund_equity_ratio_basis_points: Decimal | None
    tax_gain_or_loss: LedgerMoneyWire
    exempt_gain: LedgerMoneyWire
    taxable_gain: LedgerMoneyWire
    non_deductible_loss: LedgerMoneyWire
    deductible_loss: LedgerMoneyWire
    created_by: UUID
    created_at: datetime


class ShareSaleAllocationPageWire(TransportModel):
    items: list[ShareSaleAllocationWire]
    page: InvestmentsPageWire


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
    value: OpeningSnapshotView,
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


class DocumentBeginUploadWire(StrictTransportModel):
    company_id: UUID
    income_year: int = Field(ge=2000, le=2100)
    document_id: UUID
    document_type: Literal["bank_statement", "accounting_document", "corporate_document", "authority_feedback"]
    linked_to: str = Field(min_length=1, max_length=200)
    file_name: str = Field(min_length=1, max_length=255)
    content_type: str = Field(max_length=100)
    byte_length: int = Field(ge=1, le=10 * 1024 * 1024)
    header_base64: str = Field(min_length=4, max_length=32)
    final_status: Literal["attached", "generated_unsigned", "signed_owner_attested", "stored"] = "attached"


class DocumentWire(TransportModel):
    id: UUID
    company_id: UUID
    income_year: int
    document_type: str
    name: str
    linked_to: str
    status: str
    retention_years: int
    storage_key: str
    content_type: str
    byte_length: int | None
    content_sha256: str | None
    created_by: UUID
    created_at: datetime
    removed_at: datetime | None
    removal_reason: str | None


class DocumentUploadTransferWire(TransportModel):
    document: DocumentWire
    bucket: Literal["company-documents"]
    storage_key: str
    token: str
    signed_url: str


class DocumentListWire(TransportModel):
    documents: list[DocumentWire]


class DocumentTransferRequestWire(StrictTransportModel):
    kind: DocumentTransferKind


class DocumentTransferWire(TransportModel):
    document: DocumentWire
    kind: DocumentTransferKind
    signed_url: str
    expires_in_seconds: int


class DocumentRemovalRequestWire(StrictTransportModel):
    reason: str = Field(default="owner_requested", min_length=1, max_length=200)


class DocumentBackupObjectWire(TransportModel):
    document_id: UUID
    document_type: str
    name: str
    linked_to: str
    storage_key: str
    status: str
    retention_years: int
    content_type: str
    byte_length: int | None
    content_sha256: str | None
    created_by: UUID
    created_at: datetime
    removed_at: datetime | None
    removal_reason: str | None


class DocumentBackupProjectionWire(TransportModel):
    company_id: UUID
    income_year: int
    objects: list[DocumentBackupObjectWire]


def _document_wire(value: DocumentRecord) -> DocumentWire:
    return DocumentWire(
        id=UUID(str(value.document_id)),
        company_id=UUID(str(value.company_id)),
        income_year=int(value.income_year),
        document_type=value.document_type,
        name=value.name,
        linked_to=value.linked_to,
        status=value.status.value,
        retention_years=value.retention_years,
        storage_key=value.storage_key,
        content_type=value.content_type,
        byte_length=value.byte_length,
        content_sha256=value.content_sha256,
        created_by=UUID(str(value.created_by.subject)),
        created_at=value.created_at,
        removed_at=value.removed_at,
        removal_reason=value.removal_reason,
    )


def _document_upload_transfer_wire(value: DocumentUploadTransfer) -> DocumentUploadTransferWire:
    return DocumentUploadTransferWire(
        document=_document_wire(value.document),
        bucket="company-documents",
        storage_key=value.storage_key,
        token=value.token,
        signed_url=value.signed_url,
    )


def _document_transfer_wire(value: DocumentObjectTransfer) -> DocumentTransferWire:
    return DocumentTransferWire(
        document=_document_wire(value.document),
        kind=value.kind,
        signed_url=value.signed_url,
        expires_in_seconds=value.expires_in_seconds,
    )


def _document_backup_wire(value: DocumentBackupObject) -> DocumentBackupObjectWire:
    return DocumentBackupObjectWire(
        document_id=UUID(str(value.document_id)),
        document_type=value.document_type,
        name=value.name,
        linked_to=value.linked_to,
        storage_key=value.storage_key,
        status=value.status.value,
        retention_years=value.retention_years,
        content_type=value.content_type,
        byte_length=value.byte_length,
        content_sha256=value.content_sha256,
        created_by=UUID(str(value.created_by.subject)),
        created_at=value.created_at,
        removed_at=value.removed_at,
        removal_reason=value.removal_reason,
    )


class AnnualNotificationAcknowledgementWire(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["received"]


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
        if request.url.path == "/api/v1/ledger/opening-snapshots/by-year" or request.url.path.startswith(("/api/v1/billing/annual/", "/api/v1/authority-connections/", "/api/v1/operator-controls/", "/api/v1/legacy-rf1086/", "/api/v1/shareholder-register-filings/")):
            response.headers["Cache-Control"] = "no-store"
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
    company_tax_session_factory: CompanyTaxSessionFactory | None = None,
    investments_session_factory: InvestmentsSessionFactory | None = None,
    corporate_governance_session_factory: CorporateGovernanceSessionFactory | None = None,
    documents_session_factory: DocumentsSessionFactory | None = None,
    banking_session_factory: BankingSessionFactory | None = None,
    banking_providers: Mapping[str, BankDataProvider] | None = None,
    billing_session_factory: BillingSessionFactory | None = None,
    billing_payment_provider: BillingPaymentProvider | None = None,
    shareholder_register_filing_session_factory: ShareholderRegisterFilingSessionFactory | None = None,
    launch_signoff_session_factory: LaunchSignoffSessionFactory | None = None,
    authority_connections_session_factory: AuthorityConnectionsSessionFactory | None = None,
    system_user_authority_provider: SystemUserAuthorityProvider | None = None,
    authority_operations_provider: AuthorityOperationsProvider | None = None,
    authority_callback_internal_key: str | None = None,
    annual_billing_session_factory: AnnualBillingSessionFactory | None = None,
    annual_billing_provider: AnnualBillingProvider | None = None,
    annual_checkout_prerequisites: AnnualCheckoutPrerequisiteResolver | None = None,
    annual_notification_intake: AnnualNotificationIntake | None = None,
    marketing_measurement_gateway: MarketingMeasurementGateway | None = None,
    marketing_measurement_internal_key: str | None = None,
    validation_observer: PassiveValidationObserver | None = None,
) -> FastAPI:
    # Explicit test/application dependencies form their own composition. Avoid
    # mixing an injected provider or intake with an ambient merchant account.
    if annual_billing_provider is None and annual_notification_intake is None:
        annual_runtime = compose_annual_billing_runtime()
        annual_billing_provider = annual_runtime.provider
        annual_notification_intake = annual_runtime.notification_intake
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
    company_tax_application = compose_company_tax_application(company_tax_session_factory)
    investments_application = compose_investments_application(
        investments_session_factory
    )
    documents_application = (
        documents_session_factory
        if documents_session_factory is not None
        else SupabaseDocumentsAdapter.from_environment()
    )
    corporate_governance_application = compose_corporate_governance_application(
        corporate_governance_session_factory,
        documents_application,
    )
    banking_application = compose_banking_application(banking_session_factory)
    billing_sessions = (
        billing_session_factory
        if billing_session_factory is not None
        else SupabaseBillingAdapter.from_environment()
    )
    annual_billing_sessions = annual_billing_session_factory or SupabaseAnnualBillingAdapter.from_environment()

    async def annual_billing_workflow(credentials: HTTPAuthorizationCredentials | None) -> AnnualBillingWorkflow:
        return AnnualBillingWorkflow(await annual_billing_sessions.session(bearer_token(credentials)))

    async def annual_checkout_workflow(credentials: HTTPAuthorizationCredentials | None) -> AnnualCheckoutWorkflow:
        return AnnualCheckoutWorkflow(
            await annual_billing_sessions.session(bearer_token(credentials)),
            annual_billing_provider, annual_checkout_prerequisites,
        )

    async def annual_cleanup_workflow(credentials: HTTPAuthorizationCredentials | None) -> AnnualAgreementCleanupWorkflow:
        return AnnualAgreementCleanupWorkflow(
            await annual_billing_sessions.session(bearer_token(credentials)), annual_billing_provider,
        )

    billing_provider = billing_payment_provider or SimulationBillingProvider()
    if shareholder_register_filing_session_factory is None:
        from talli_backend.adapters.postgres_shareholder_register_filing import PostgresShareholderRegisterFilingAdapter
        async def rf_billing_queries(access_token: str):
            return BillingWorkflow(await billing_sessions.session(access_token), billing_provider)
        shareholder_register_filing_session_factory = PostgresShareholderRegisterFilingAdapter.from_environment(
            billing_queries_factory=rf_billing_queries, documents_session_factory=documents_application,
            company_access_service=company_access_service,
        )

    if launch_signoff_session_factory is None:
        from talli_backend.adapters.postgres_launch_signoffs import PostgresLaunchSignoffsAdapter
        launch_signoff_session_factory = PostgresLaunchSignoffsAdapter.from_environment()

    async def launch_signoff_workflow(credentials: HTTPAuthorizationCredentials | None):
        return LaunchSignoffWorkflow(await launch_signoff_session_factory.session(bearer_token(credentials)))

    if authority_connections_session_factory is None:
        from talli_backend.adapters.postgres_authority_connections import PostgresAuthorityConnectionsAdapter
        authority_connections_session_factory = PostgresAuthorityConnectionsAdapter.from_environment()
    if system_user_authority_provider is None:
        from talli_backend.adapters.altinn_system_user import AltinnSystemUserAdapter
        system_user_authority_provider = AltinnSystemUserAdapter.from_environment()
    if authority_operations_provider is None:
        from talli_backend.adapters.altinn_authority_operations import AltinnAuthorityOperationsAdapter
        authority_operations_provider = AltinnAuthorityOperationsAdapter.from_environment()
    callback_transport = AuthorityCallbackTransport(
        authority_callback_internal_key if authority_callback_internal_key is not None
        else os.environ.get("TALLI_AUTHORITY_CALLBACK_INTERNAL_KEY", ""),
    )

    async def authority_connections_service(credentials: HTTPAuthorizationCredentials | None):
        session = await authority_connections_session_factory.session(bearer_token(credentials))
        return session, AuthorityConnectionsWorkflow(session, system_user_authority_provider)

    async def authority_operations_workflow(credentials: HTTPAuthorizationCredentials | None):
        session = await authority_connections_session_factory.session(bearer_token(credentials))
        return session, AuthorityOperationsWorkflow(session, authority_operations_provider)

    async def billing_workflow(
        credentials: HTTPAuthorizationCredentials | None,
    ) -> BillingWorkflow:
        session = await billing_sessions.session(bearer_token(credentials))
        return BillingWorkflow(session, billing_provider)

    async def investments_session_with_bank_validation(
        credentials: HTTPAuthorizationCredentials | None,
    ):
        return await investments_application.session(bearer_token(credentials))

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

    async def documents_call(call: Callable[[], Awaitable[ResponseT]]) -> ResponseT:
        try:
            return await call()
        except DocumentsError as error:
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
                code=str(error.code),
                title="Document request failed",
                detail=error.message,
            ) from None

    async def corporate_governance_call(
        call: Callable[[], Awaitable[ResponseT]],
    ) -> ResponseT:
        for attempt in range(2):
            try:
                return await call()
            except CorporateGovernanceAuthenticationError:
                raise ApiProblem(
                    status=401,
                    code="AUTHENTICATION_REQUIRED",
                    title="Authentication required",
                    detail="A valid session is required.",
                ) from None
            except (CorporateGovernanceError, LedgerError) as error:
                if (
                    error.category is ErrorCategory.DEPENDENCY_UNAVAILABLE
                    and attempt == 0
                ):
                    continue
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
                    code=str(error.code),
                    title="Corporate-governance request failed",
                    detail=error.message
                    or "The corporate-governance request could not be completed.",
                ) from None
        raise AssertionError("Corporate-governance retry loop exhausted")

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
        except (LedgerError, CompanyTaxError) as error:
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
                code=error.code.replace("COMPANY_TAX_", "LEDGER_") if isinstance(error, CompanyTaxError) else error.code,
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
                code=error.code.replace("COMPANY_TAX_", "LEDGER_") if isinstance(error, CompanyTaxError) else error.code,
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

    async def billing_call(call: Callable[[], Awaitable[ResponseT]]) -> ResponseT:
        try:
            return await call()
        except BillingAuthenticationError:
            raise ApiProblem(
                status=401,
                code="AUTHENTICATION_REQUIRED",
                title="Authentication required",
                detail="A valid session is required.",
            ) from None
        except BillingError as error:
            statuses = {
                ErrorCategory.INVALID_INPUT: 422,
                ErrorCategory.NOT_FOUND: 404,
                ErrorCategory.CONFLICT: 409,
                ErrorCategory.FORBIDDEN: 403,
                ErrorCategory.PRECONDITION_FAILED: 409,
                ErrorCategory.DEPENDENCY_UNAVAILABLE: 503,
            }
            details = {
                BillingErrorCode.INVALID_INPUT: "Ugyldig faktureringsforespørsel.",
                BillingErrorCode.NOT_FOUND: "Faktureringskonto mangler.",
                BillingErrorCode.FORBIDDEN: "Du har ikke tilgang til faktureringskontoen.",
                BillingErrorCode.STEP_UP_REQUIRED: "Ny tofaktorbekreftelse kreves.",
                BillingErrorCode.IDEMPOTENCY_KEY_REUSED: "Operasjonsnøkkelen er allerede brukt med andre data.",
                BillingErrorCode.IDEMPOTENCY_IN_PROGRESS: "Faktureringsoperasjonen behandles allerede.",
                BillingErrorCode.CHECKOUT_REQUEST_WITHDRAWN: "Den tidligere kjøpsforespørselen er trukket tilbake. Du kan gjennomgå et nytt kjøp.",
                BillingErrorCode.SUBSCRIPTION_REQUIRED: "Aktivt abonnement kreves før produksjonsinnsending.",
                BillingErrorCode.FILING_NOT_READY: "Innsendingskontrollen må være klar før innsendingspakken kan betales.",
                BillingErrorCode.FILING_PACKAGE_REQUIRED: "Innsendingspakken må betales før produksjonsinnsending.",
                BillingErrorCode.UNSUPPORTED_CASE: "Saken er utenfor Talli-støtte. Ikke ta betalt for innsendingspakken.",
                BillingErrorCode.REFUND_NOT_ALLOWED: "Kun en støttet, betalt innsendingspakke kan refunderes.",
                BillingErrorCode.LEGACY_ACQUISITION_RETIRED: "Den tidligere prismodellen er avsluttet. Se årsabonnementet for foretaket.",
                BillingErrorCode.PROVIDER_DISABLED: "Betalingsleverandøren er deaktivert.",
                BillingErrorCode.PROVIDER_OUTCOME_UNKNOWN: "Betalingsutfallet er ukjent og må avstemmes.",
                BillingErrorCode.DEPENDENCY_UNAVAILABLE: "Fakturering er midlertidig utilgjengelig.",
            }
            raise ApiProblem(
                status=statuses[error.category],
                code=error.code,
                title="Faktureringsforespørselen mislyktes",
                detail=error.message or details[BillingErrorCode(error.code)],
            ) from None

    async def authority_connections_call(call: Callable[[], Awaitable[ResponseT]]) -> ResponseT:
        try:
            return await call()
        except (AuthorityConnectionsAuthenticationError, LaunchSignoffAuthenticationError):
            raise ApiProblem(
                status=401, code="AUTHENTICATION_REQUIRED", title="Innlogging kreves",
                detail="En gyldig innlogging kreves.",
            ) from None
        except (AuthorityConnectionsError, AuthorityOperationError, LaunchSignoffError) as error:
            statuses = {
                ErrorCategory.INVALID_INPUT: 422,
                ErrorCategory.NOT_FOUND: 404,
                ErrorCategory.CONFLICT: 409,
                ErrorCategory.FORBIDDEN: 403,
                ErrorCategory.PRECONDITION_FAILED: 409,
                ErrorCategory.DEPENDENCY_UNAVAILABLE: 503,
            }
            raise ApiProblem(
                status=statuses[error.category], code=error.code,
                title="Systembrukerforespørselen mislyktes",
                detail="Systembrukerforespørselen kunne ikke behandles.",
            ) from None
        except AuthorityProviderError as error:
            raise ApiProblem(
                status=503, code=error.code.value, title="Systembruker er midlertidig utilgjengelig",
                detail="Status kunne ikke bekreftes. Prøv igjen senere.",
            ) from None

    async def shareholder_register_filing_call(call: Callable[[], Awaitable[ResponseT]]) -> ResponseT:
        try:
            return await call()
        except ShareholderRegisterFilingAuthenticationError:
            raise ApiProblem(status=401, code="authentication_required", title="Innlogging kreves",
                detail="En gyldig innlogging kreves.") from None
        except Rf1086ProductionError as error:
            status = 422 if error.code == "invalid_request" else 401 if error.code == "authentication_required" else (
                503 if error.code in {"configuration_unavailable", "send_unavailable", "status_unavailable"} else 409)
            raise ApiProblem(status=status, code=error.code, title="RF-1086-handlingen kunne ikke fullføres",
                detail="Se lagret innsendingsstatus før du prøver igjen.") from None

        except ShareholderRegisterFilingError as error:
            statuses = {
                ErrorCategory.INVALID_INPUT: 422, ErrorCategory.NOT_FOUND: 404,
                ErrorCategory.CONFLICT: 409, ErrorCategory.FORBIDDEN: 403,
                ErrorCategory.PRECONDITION_FAILED: 409, ErrorCategory.DEPENDENCY_UNAVAILABLE: 503,
            }
            raise ApiProblem(status=statuses[error.category], code=str(error.code),
                title="RF-1086-handlingen kunne ikke fullføres",
                detail="Handlingen kunne ikke bekreftes. Se lagret status før du prøver igjen.") from None

    async def shareholder_register_filing_workflow(
        credentials: HTTPAuthorizationCredentials | None,
    ) -> ShareholderRegisterFilingWorkflow:
        return ShareholderRegisterFilingWorkflow(
            await shareholder_register_filing_session_factory.session(bearer_token(credentials))
        )

    def rf1086_recorded_wire(value: Rf1086RecordedResult) -> Rf1086RecordedResultWire:
        return Rf1086RecordedResultWire(
            record_id=UUID(value.record_id), company_id=UUID(str(value.company_id)),
            income_year=int(value.income_year) if value.income_year is not None else None,
        )

    def rf1086_json_wire(value: Any) -> Any:
        """Materialize immutable JSON at the transport edge, preserving keys/order."""
        if isinstance(value, Mapping):
            return {key: rf1086_json_wire(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [rf1086_json_wire(item) for item in value]
        return value

    def launch_signoff_wire(value: LaunchSignoffRecord) -> LaunchSignoffRecordWire:
        return LaunchSignoffRecordWire(
            key=value.key, status=value.status, reviewer=value.reviewer,
            reviewed_at=value.reviewed_at.value, evidence_link=value.evidence_link, decision=value.decision,
            recorded_by=UUID(str(value.recorded_by)), updated_at=value.updated_at.value,
        )

    def authority_operation_wire(value: AuthorityOperationRecord) -> AuthorityOperationRecordWire:
        return AuthorityOperationRecordWire(
            operation_id=UUID(value.operation_id), operation=value.operation,
            actor_id=UUID(str(value.actor_id)), status=value.status,
            request_hash=value.request_hash, result_code=value.result_code,
            metadata=dict(value.metadata), authority_http_status=value.authority_http_status,
            created_at=value.created_at.value,
            completed_at=value.completed_at.value if value.completed_at else None,
        )

    def system_user_result_wire(value: SystemUserFlowResult | SystemUserRequest) -> SystemUserResultWire:
        return SystemUserResultWire(
            request_id=UUID(value.request_id),
            company_id=UUID(str(value.identity.company_id if isinstance(value, SystemUserRequest) else value.company_id)),
            status=value.status,
            preflight_verified_at=value.preflight_verified_at.value if value.preflight_verified_at else None,
            confirmation_url=value.confirmation_url, failure_code=value.failure_code,
        )

    def system_user_record_wire(value: SystemUserRequest) -> SystemUserRecordWire:
        timestamps = {
            field: getattr(value, field).value if getattr(value, field) else None
            for field in ("requested_at", "last_status_checked_at", "accepted_at", "resolved_at", "created_at", "updated_at")
        }
        return SystemUserRecordWire(
            **system_user_result_wire(value).model_dump(),
            initiating_owner_user_id=UUID(str(value.identity.owner_id)),
            obligation=value.obligation,
            external_reference=value.identity.external_reference,
            provider_request_id=UUID(value.provider_request_id) if value.provider_request_id else None,
            operator_evidence_id=UUID(value.operator_evidence_id) if value.operator_evidence_id else None,
            **timestamps,
        )

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

    def billing_input(factory: Callable[[], ResponseT]) -> ResponseT:
        try:
            return factory()
        except (TypeError, ValueError, BillingError):
            raise BillingError.invalid() from None

    def billing_account_wire(value: BillingAccount) -> BillingAccountWire:
        return BillingAccountWire(
            company_id=UUID(str(value.company_id)),
            pricing_plan=value.pricing.plan,
            monthly_nok=value.pricing.monthly_nok,
            filing_package_nok=value.pricing.filing_package_nok,
            founder_cohort_number=value.founder_cohort_number,
            subscription_active=value.subscription_active,
            filing_package_paid=value.filing_package_paid,
            supported_case=value.supported_case,
            refund_eligible=value.refund_eligible,
            refund_completed=value.refund_completed,
            no_charge_reason=value.no_charge_reason,
            provider_customer_reference=value.provider_customer_reference,
            subscription_provider_reference=value.subscription_provider_reference,
            filing_package_payment_reference=value.filing_package_payment_reference,
            refund_provider_reference=value.refund_provider_reference,
            updated_by=UUID(str(value.updated_by)),
            created_at=value.created_at.value,
            updated_at=value.updated_at.value,
        )

    def billing_event_wire(value: BillingPaymentEvent) -> BillingPaymentEventWire:
        return BillingPaymentEventWire(
            event_id=UUID(str(value.event_id)),
            company_id=UUID(str(value.company_id)),
            provider=value.provider,
            provider_reference=value.provider_reference,
            idempotency_key=str(value.idempotency_key),
            kind=value.kind.value,
            status=value.status.value,
            amount_nok=value.amount_nok,
            income_year=int(value.income_year) if value.income_year else None,
            created_by=UUID(str(value.created_by)),
            created_at=value.created_at.value,
            replayed=value.replayed,
        )

    def billing_pilot_wire(
        value: ProductionPilotEntitlement,
    ) -> BillingPilotEntitlementWire:
        return BillingPilotEntitlementWire(
            entitlement_id=UUID(str(value.entitlement_id)),
            company_id=UUID(str(value.company_id)),
            user_id=UUID(str(value.user_id)),
            income_year=int(value.income_year),
            obligation=value.obligation,
            case_profile=value.case_profile.value,
            status=value.status,
            billing_exempt=value.billing_exempt,
            system_user_request_id=UUID(str(value.system_user_request_id)),
            system_user_external_reference=value.system_user_external_reference,
            starts_at=value.starts_at.value,
            expires_at=value.expires_at.value,
            evidence_reference=value.evidence_reference,
            approved_by=UUID(str(value.approved_by)),
            created_at=value.created_at.value,
            updated_at=value.updated_at.value,
        )

    def billing_decision_wire(
        value: BillingEntitlementDecision,
    ) -> BillingEntitlementDecisionWire:
        return BillingEntitlementDecisionWire(
            company_id=UUID(str(value.company_id)),
            income_year=int(value.income_year),
            obligation=value.obligation,
            status=value.status.value,
            allowed=value.allowed,
            charge_allowed=value.charge_allowed,
            readiness_allowed=value.readiness_allowed,
            billing_exempt=value.billing_exempt,
            message=value.message,
            pilot_entitlement_id=(
                UUID(str(value.pilot_entitlement_id))
                if value.pilot_entitlement_id
                else None
            ),
        )

    def billing_snapshot_wire(value: BillingSnapshot) -> BillingSnapshotWire:
        return BillingSnapshotWire(
            accounts=[billing_account_wire(item) for item in value.accounts],
            payment_events=[billing_event_wire(item) for item in value.payment_events],
            pilot_entitlements=[billing_pilot_wire(item) for item in value.pilot_entitlements],
            pricing=[
                BillingPricingWire(
                    plan=item.plan,
                    monthly_nok=item.monthly_nok,
                    filing_package_nok=item.filing_package_nok,
                )
                for item in value.pricing
            ],
        )

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

    corporate_governance_errors: Any = {
        status: {
            "description": "Corporate-governance request failed.",
            "headers": {"X-Request-ID": REQUEST_ID_HEADER},
            "content": {
                "application/problem+json": {
                    "schema": ProblemDetails.model_json_schema(by_alias=True)
                }
            },
        }
        for status in (401, 403, 404, 409, 422, 503)
    }
    corporate_governance_success: dict[str, Any] = {
        "headers": {"X-Request-ID": REQUEST_ID_HEADER}
    }

    def corporate_governance_input(factory: Callable[[], ResponseT]) -> ResponseT:
        try:
            return factory()
        except (TypeError, ValueError, CorporateGovernanceError):
            raise CorporateGovernanceError.invalid(
                CorporateGovernanceErrorCode.INVALID_INPUT,
                "Corporate-governance input is invalid.",
            ) from None

    def canonical_decision_wire(
        value: CanonicalOwnerDividendDecision | CanonicalAnnualCloseDecision,
    ) -> CorporateCanonicalDecisionWire:
        return CorporateCanonicalDecisionWire(
            decision_kind=(
                "owner_dividend"
                if isinstance(value, CanonicalOwnerDividendDecision)
                else "annual_close"
            ),
            decision_id=UUID(str(value.decision_id)),
            document_set_id=UUID(str(value.document_set_id)),
            company_id=UUID(str(value.company_id)),
            organization_number=value.organization_number,
            legal_name=value.legal_name,
            income_year=int(value.income_year),
            annual_close_source_id=UUID(str(value.annual_close_source_id)),
            source_hash=value.source_hash,
            template_family=value.template_family,
            template_version=value.template_version,
            annual_basis_year=int(value.annual_basis_year),
            financial_totals={
                "resultAfterTaxOre": value.financial_totals.result_after_tax_ore,
                "equityOre": value.financial_totals.equity_ore,
                "availableDistributionOre": value.financial_totals.available_distribution_ore,
                "cashOre": value.financial_totals.cash_ore,
            },
            board_meeting={
                "meetingDate": value.board_meeting.meeting_date.value.isoformat(),
                "meetingTime": value.board_meeting.meeting_time.isoformat(),
                "place": value.board_meeting.place,
                "treatmentMethod": value.board_meeting.treatment_method.value,
            },
            board_participants=[
                {
                    "participantId": item.participant_id,
                    "name": item.name,
                    "role": item.role.value,
                }
                for item in value.board_participants
            ],
            general_meeting={
                "meetingDate": value.general_meeting.meeting_date.value.isoformat(),
                "meetingTime": value.general_meeting.meeting_time.isoformat(),
                "place": value.general_meeting.place,
                "meetingForm": value.general_meeting.meeting_form.value,
                "chairName": value.general_meeting.chair_name,
                "coSignerName": value.general_meeting.co_signer_name,
            },
            shareholders=[
                {
                    "shareholderId": item.shareholder_id,
                    "name": item.name,
                    "shareCount": item.share_count,
                    "representedShareCount": item.represented_share_count,
                    "vote": item.vote.value,
                }
                for item in value.shareholders
            ],
            total_company_shares=value.total_company_shares,
            one_share_class_confirmed=value.one_share_class_confirmed,
            dividend=(
                {
                    "amountOre": value.dividend.amount_ore,
                    "paymentDate": value.dividend.payment_date.value.isoformat(),
                    "liquidityAfterPaymentOre": value.dividend.liquidity_after_payment_ore,
                    "allocations": [
                        {
                            "shareholderId": item.shareholder_id,
                            "amountOre": item.amount_ore,
                        }
                        for item in value.dividend.allocations
                    ],
                }
                if value.dividend is not None
                else None
            ),
            annual_result_allocation_ore=value.annual_result_allocation_ore,
            confirmations={
                "latestApprovedAnnualAccounts": value.confirmations.latest_approved_annual_accounts,
                "supportedDividendBasis": value.confirmations.supported_dividend_basis,
                "fullBoardParticipation": value.confirmations.full_board_participation,
                "fullShareRepresentation": value.confirmations.full_share_representation,
                "unanimousBoard": value.confirmations.unanimous_board,
                "unanimousShareholders": value.confirmations.unanimous_shareholders,
                "proportionalAllocation": value.confirmations.proportional_allocation,
                "prudentEquityAndLiquidity": value.confirmations.prudent_equity_and_liquidity,
            },
            decision_hash=value.decision_hash,
        )

    def proposed_dividend_wire(
        value: ProposedOwnerDividend,
    ) -> ProposedOwnerDividendWire:
        return ProposedOwnerDividendWire(
            decision=canonical_decision_wire(value.decision),
            state=value.state.value,
            replayed=value.replayed,
            artifacts=[rendered_artifact_wire(item) for item in value.artifacts],
        )

    def corporate_decision_facts_wire(
        value: DerivedCorporateDecisionFacts,
    ) -> CorporateDecisionFactsWire:
        return CorporateDecisionFactsWire(
            company=CorporateCompanyFactsWire(
                organization_number=value.company.organization_number,
                legal_name=value.company.legal_name,
            ),
            shareholders=[
                CorporateShareholderWire(
                    shareholder_id=item.shareholder_id,
                    name=item.name,
                    share_count=item.share_count,
                    order=item.order,
                )
                for item in value.shareholders
            ],
            annual_basis=CorporateAnnualBasisWire(
                source_id=UUID(str(value.annual_basis.source_id)),
                income_year=int(value.annual_basis.income_year),
                latest_approved=value.annual_basis.latest_approved,
                annual_data_sha256=value.annual_basis.annual_data_sha256,
                governance_basis_sha256=(
                    value.annual_basis.governance_basis_sha256
                ),
                result_after_tax_ore=value.annual_basis.result_after_tax_ore,
                equity_ore=value.annual_basis.equity_ore,
                available_distribution_ore=(
                    value.annual_basis.available_distribution_ore
                ),
                cash_ore=value.annual_basis.cash_ore,
            ),
            reviewed_facts=CorporateReviewedFactsWire(
                organization_number=value.reviewed_facts.organization_number,
                legal_name=value.reviewed_facts.legal_name,
                shareholders=[
                    CorporateReviewedShareholderWire(
                        shareholder_id=item.shareholder_id,
                        name=item.name,
                        share_count=item.share_count,
                    )
                    for item in value.reviewed_facts.shareholders
                ],
                total_company_shares=value.reviewed_facts.total_company_shares,
                available_distribution_ore=(
                    value.reviewed_facts.available_distribution_ore
                ),
                annual_data_sha256=value.reviewed_facts.annual_data_sha256,
                governance_basis_sha256=(
                    value.reviewed_facts.governance_basis_sha256
                ),
            ),
        )

    def rendered_artifact_wire(value) -> RenderedCorporateArtifactWire:
        return RenderedCorporateArtifactWire(
            artifact_kind=value.artifact_kind,
            filename=value.filename,
            content_sha256=value.content_sha256,
            byte_length=value.byte_length,
            decision_hash=value.decision_hash,
            content_base64=b64encode(value.pdf_bytes).decode("ascii"),
        )

    def proposed_annual_close_wire(
        value: ProposedAnnualClose,
    ) -> ProposedAnnualCloseWire:
        return ProposedAnnualCloseWire(
            decision=canonical_decision_wire(value.decision),
            state=value.state.value,
            replayed=value.replayed,
            artifacts=[rendered_artifact_wire(item) for item in value.artifacts],
        )

    def dividend_lifecycle_wire(
        value: OwnerDividendLifecycle,
    ) -> OwnerDividendLifecycleWire:
        return OwnerDividendLifecycleWire(
            decision_id=UUID(str(value.decision_id)),
            document_set_id=UUID(str(value.document_set_id)),
            company_id=UUID(str(value.company_id)),
            income_year=int(value.income_year),
            decision_hash=value.decision_hash,
            state=value.state.value,
            declared_amount_ore=value.declared_amount_ore,
            paid_amount_ore=value.paid_amount_ore,
            remaining_amount_ore=value.remaining_amount_ore,
            finalization_id=(
                UUID(str(value.finalization_id)) if value.finalization_id else None
            ),
            accounting_entry_id=(
                UUID(str(value.accounting_entry_id))
                if value.accounting_entry_id
                else None
            ),
            replayed=value.replayed,
        )

    def annual_close_lifecycle_wire(
        value: AnnualCloseLifecycle,
    ) -> AnnualCloseLifecycleWire:
        return AnnualCloseLifecycleWire(
            decision_id=UUID(str(value.decision_id)),
            document_set_id=UUID(str(value.document_set_id)),
            company_id=UUID(str(value.company_id)),
            income_year=int(value.income_year),
            decision_hash=value.decision_hash,
            state=value.state,
            generated_artifact_hashes=value.generated_artifact_hashes,
            signed_artifact_hashes=value.signed_artifact_hashes,
            finalization_id=(
                UUID(str(value.finalization_id)) if value.finalization_id else None
            ),
            replayed=value.replayed,
        )

    def corporate_lifecycle_snapshot_wire(
        value: CorporateLifecycleSnapshot,
    ) -> CorporateLifecycleSnapshotWire:
        return CorporateLifecycleSnapshotWire(
            decisions=[
                CorporateDecisionRecordWire(
                    decision_id=UUID(str(item.decision_id)),
                    document_set_id=UUID(str(item.document_set_id)),
                    company_id=UUID(str(item.company_id)),
                    income_year=int(item.income_year),
                    decision_kind=item.decision_kind,
                    annual_close_source_id=UUID(str(item.annual_close_source_id)),
                    source_hash=item.source_hash,
                    canonical_input=dict(item.canonical_input),
                    decision_hash=item.decision_hash,
                    supersedes_decision_id=(
                        UUID(str(item.supersedes_decision_id))
                        if item.supersedes_decision_id
                        else None
                    ),
                    created_by=UUID(item.created_by),
                    created_at=item.created_at,
                )
                for item in value.decisions
            ],
            document_sets=[
                CorporateDocumentSetRecordWire(
                    document_set_id=UUID(str(item.document_set_id)),
                    company_id=UUID(str(item.company_id)),
                    income_year=int(item.income_year),
                    decision_id=UUID(str(item.decision_id)),
                    template_family=item.template_family,
                    template_version=item.template_version,
                    decision_hash=item.decision_hash,
                    supersedes_document_set_id=(
                        UUID(str(item.supersedes_document_set_id))
                        if item.supersedes_document_set_id
                        else None
                    ),
                    created_by=UUID(item.created_by),
                    created_at=item.created_at,
                )
                for item in value.document_sets
            ],
            artifacts=[
                CorporateArtifactRecordWire(
                    artifact_id=UUID(str(item.artifact_id)),
                    company_id=UUID(str(item.company_id)),
                    income_year=int(item.income_year),
                    document_set_id=UUID(str(item.document_set_id)),
                    artifact_kind=item.artifact_kind,
                    variant=item.variant,
                    document_id=UUID(str(item.document_id)),
                    content_sha256=item.content_sha256,
                    byte_length=item.byte_length,
                    supersedes_artifact_id=(
                        UUID(str(item.supersedes_artifact_id))
                        if item.supersedes_artifact_id
                        else None
                    ),
                    created_by=UUID(item.created_by),
                    created_at=item.created_at,
                )
                for item in value.artifacts
            ],
            events=[
                CorporateEventRecordWire(
                    event_id=UUID(str(item.event_id)),
                    company_id=UUID(str(item.company_id)),
                    income_year=int(item.income_year),
                    decision_id=UUID(str(item.decision_id)),
                    document_set_id=UUID(str(item.document_set_id)),
                    artifact_id=(UUID(str(item.artifact_id)) if item.artifact_id else None),
                    event_kind=item.event_kind,
                    actor_id=UUID(item.actor_id),
                    occurred_at=item.occurred_at,
                    created_at=item.created_at,
                    decision_hash=item.decision_hash,
                    content_sha256=item.content_sha256,
                    metadata=dict(item.metadata),
                    idempotency_key=item.idempotency_key,
                )
                for item in value.events
            ],
            finalizations=[
                CorporateFinalizationRecordWire(
                    finalization_id=UUID(str(item.finalization_id)),
                    company_id=UUID(str(item.company_id)),
                    income_year=int(item.income_year),
                    decision_id=UUID(str(item.decision_id)),
                    finalization_kind=item.finalization_kind,
                    holding_action_id=(
                        UUID(str(item.holding_action_id))
                        if item.holding_action_id
                        else None
                    ),
                    accounting_entry_id=(
                        UUID(str(item.accounting_entry_id))
                        if item.accounting_entry_id
                        else None
                    ),
                    annual_close_source_id=(
                        UUID(str(item.annual_close_source_id))
                        if item.annual_close_source_id
                        else None
                    ),
                    decision_hash=item.decision_hash,
                    signed_artifact_hashes=dict(item.signed_artifact_hashes),
                    accounting_policy_version=item.accounting_policy_version,
                    created_by=UUID(item.created_by),
                    created_at=item.created_at,
                )
                for item in value.finalizations
            ],
        )

    def corporate_document_readiness_wire(
        value: CorporateDocumentReadiness,
    ) -> CorporateDocumentReadinessWire:
        return CorporateDocumentReadinessWire(
            company_id=UUID(str(value.company_id)),
            income_year=int(value.income_year),
            decision_kind=value.decision_kind,
            decision_id=(UUID(str(value.decision_id)) if value.decision_id else None),
            document_set_id=(
                UUID(str(value.document_set_id)) if value.document_set_id else None
            ),
            decision_hash=value.decision_hash,
            source_hash=value.source_hash,
            current_source_hash=value.current_source_hash,
            state=value.state,
            current_source_matches=value.current_source_matches,
            ready_for_signing=value.ready_for_signing,
            finalized=value.finalized,
            annual_submission_ready=value.annual_submission_ready,
            generated_artifact_hashes=dict(value.generated_artifact_hashes),
            signed_artifact_hashes=dict(value.signed_artifact_hashes),
            required_signers={
                key: list(signers) for key, signers in value.required_signers.items()
            },
            declared_amount_ore=value.declared_amount_ore,
            paid_amount_ore=value.paid_amount_ore,
            remaining_amount_ore=value.remaining_amount_ore,
            finalization_id=(
                UUID(str(value.finalization_id)) if value.finalization_id else None
            ),
            accounting_policy_version=value.accounting_policy_version,
            blockers=[
                CorporateDocumentReadinessBlockerWire(
                    code=item.code,
                    message=item.message,
                )
                for item in value.blockers
            ],
        )

    def shareholder_loan_wire(
        value: RecordedShareholderLoan,
    ) -> RecordedShareholderLoanWire:
        return RecordedShareholderLoanWire(
            action_id=UUID(str(value.loan.action_id)),
            company_id=UUID(str(value.loan.company_id)),
            income_year=int(value.loan.income_year),
            loan_date=value.loan.loan_date.value,
            amount_ore=value.loan.amount_ore,
            direction=value.loan.direction,
            counterparty_name=value.loan.counterparty_name,
            document_status=value.loan.document_status,
            interest_modelled=value.loan.interest_modelled,
            related_party_security=value.loan.related_party_security,
            bank_transaction_id=(
                UUID(str(value.loan.bank_transaction_id))
                if value.loan.bank_transaction_id
                else None
            ),
            document_id=(
                UUID(str(value.loan.document_id)) if value.loan.document_id else None
            ),
            accounting_entry_id=UUID(str(value.accounting_entry_id)),
            replayed=value.replayed,
        )

    def supported_event_facts(
        value: SupportedCorporateEventFactsWire,
    ):
        common = value.model_dump(exclude={"fact_type"})
        for key, item in tuple(common.items()):
            if isinstance(item, dict) and set(item) == {"amount", "currency"}:
                common[key] = Money.nok(item["amount"])
        if isinstance(value, CashCapitalIncreaseEventFactsWire):
            return CashCapitalIncreaseEventFacts(**common)
        if isinstance(value, LossCoverageCapitalReductionEventFactsWire):
            return LossCoverageCapitalReductionEventFacts(**common)
        if isinstance(value, IntercompanyLoanEventFactsWire):
            return IntercompanyLoanEventFacts(**common)
        if isinstance(value, OwnerLoanEventFactsWire):
            return OwnerLoanEventFacts(**common)
        if isinstance(value, BankLoanEventFactsWire):
            return BankLoanEventFacts(**common)
        if isinstance(value, GroupContributionEventFactsWire):
            return GroupContributionEventFacts(**common)
        raise TypeError("Unsupported corporate-event fact shape.")

    def supported_event_wire(
        value: RecordedSupportedCorporateEvent,
    ) -> RecordedSupportedCorporateEventWire:
        def plain(item: object) -> object:
            if isinstance(item, Mapping):
                return {str(key): plain(child) for key, child in item.items()}
            if isinstance(item, (tuple, list)):
                return [plain(child) for child in item]
            return item

        raw_documents = value.event.canonical_facts.get("documentFacts")
        if not isinstance(raw_documents, (tuple, list)):
            raise CorporateGovernanceError.unavailable()
        document_facts: list[SupportedCorporateDocumentFactWire] = []
        for item in raw_documents:
            if not isinstance(item, Mapping):
                raise CorporateGovernanceError.unavailable()
            raw_document_id = item["document_id"]
            document_id = (
                raw_document_id.get("value")
                if isinstance(raw_document_id, Mapping)
                else raw_document_id
            )
            document_facts.append(
                SupportedCorporateDocumentFactWire(
                    document_id=UUID(str(document_id)),
                    evidence_kind=SupportedCorporateEvidenceKind(
                        str(item["evidence_kind"])
                    ),
                    revision=int(cast(int, item["revision"])),
                    content_sha256=str(item["content_sha256"]),
                )
            )

        return RecordedSupportedCorporateEventWire(
            event_id=UUID(str(value.event.event_id)),
            event_reference=UUID(str(value.event.event_reference)),
            company_id=UUID(str(value.event.company_id)),
            income_year=int(value.event.income_year),
            event_date=value.event.event_date.value,
            event_kind=value.event.event_kind,
            phase=value.event.phase,
            policy_version=value.event.policy_version,
            canonical_facts=cast(dict[str, Any], plain(value.event.canonical_facts)),
            facts_sha256=value.event.facts_sha256,
            document_facts=document_facts,
            signed_artifact_hashes=dict(value.signed_artifact_hashes),
            finalization_sha256=value.finalization_sha256,
            lifecycle_state="finalized",
            accounting_entry_id=UUID(str(value.accounting_entry_id)),
            bank_transaction_id=(
                UUID(str(value.bank_transaction_id))
                if value.bank_transaction_id
                else None
            ),
            correction_of_event_id=(
                UUID(str(value.correction_of_event_id))
                if value.correction_of_event_id
                else None
            ),
            recorded_at=value.recorded_at,
            replayed=value.replayed,
        )

    def reversed_supported_event_wire(
        value: ReversedSupportedCorporateEvent,
    ) -> ReversedSupportedCorporateEventWire:
        return ReversedSupportedCorporateEventWire(
            original_event_id=UUID(str(value.original_event_id)),
            original_accounting_entry_id=UUID(
                str(value.original_accounting_entry_id)
            ),
            reversal_accounting_entry_id=UUID(
                str(value.reversal_accounting_entry_id)
            ),
            company_id=UUID(str(value.company_id)),
            income_year=int(value.income_year),
            reversed_at=value.reversed_at,
            replayed=value.replayed,
        )

    async def governance_actor(access_token: str):
        return await corporate_governance_application.authenticated_actor_id(
            access_token
        )

    def decision_proposal_fields(
        request: Request,
        command: CorporateDecisionProposalWire,
        actor_id: ActorId,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return {
            "company_id": CompanyId(str(command.company_id)),
            "actor_id": actor_id,
            "correlation_id": CorrelationId(request.state.request_id),
            "idempotency_key": IdempotencyKey(idempotency_key),
            "income_year": IncomeYear(command.income_year),
            "decision_id": CorporateDecisionId(str(command.decision_id)),
            "document_set_id": CorporateDocumentSetId(str(command.document_set_id)),
            "company": PersistedCompanyFacts(
                company_id=CompanyId(str(command.company_id)),
                organization_number=command.company.organization_number,
                legal_name=command.company.legal_name,
            ),
            "shareholders": tuple(
                PersistedShareholderFacts(
                    shareholder_id=item.shareholder_id,
                    name=item.name,
                    share_count=item.share_count,
                    order=item.order,
                )
                for item in command.shareholders
            ),
            "annual_basis": ApprovedAnnualBasis(
                source_id=CorporateSourceReference(str(command.annual_basis.source_id)),
                income_year=IncomeYear(command.annual_basis.income_year),
                latest_approved=command.annual_basis.latest_approved,
                annual_data_sha256=command.annual_basis.annual_data_sha256,
                governance_basis_sha256=(
                    command.annual_basis.governance_basis_sha256
                ),
                result_after_tax_ore=command.annual_basis.result_after_tax_ore,
                equity_ore=command.annual_basis.equity_ore,
                available_distribution_ore=(
                    command.annual_basis.available_distribution_ore
                ),
                cash_ore=command.annual_basis.cash_ore,
            ),
            "reviewed_facts": ReviewedOwnerDividendFacts(
                organization_number=command.reviewed_facts.organization_number,
                legal_name=command.reviewed_facts.legal_name,
                shareholders=tuple(
                    ReviewedShareholderFacts(
                        shareholder_id=item.shareholder_id,
                        name=item.name,
                        share_count=item.share_count,
                    )
                    for item in command.reviewed_facts.shareholders
                ),
                total_company_shares=command.reviewed_facts.total_company_shares,
                available_distribution_ore=(
                    command.reviewed_facts.available_distribution_ore
                ),
                annual_data_sha256=command.reviewed_facts.annual_data_sha256,
                governance_basis_sha256=(
                    command.reviewed_facts.governance_basis_sha256
                ),
            ),
            "board_meeting": BoardMeeting(
                meeting_date=LocalDate(command.board_meeting.meeting_date),
                meeting_time=command.board_meeting.meeting_time,
                place=command.board_meeting.place,
                treatment_method=command.board_meeting.treatment_method,
            ),
            "board_participants": tuple(
                BoardParticipant(
                    participant_id=item.participant_id,
                    name=item.name,
                    role=item.role,
                    order=item.order,
                )
                for item in command.board_participants
            ),
            "general_meeting": GeneralMeeting(
                meeting_date=LocalDate(command.general_meeting.meeting_date),
                meeting_time=command.general_meeting.meeting_time,
                place=command.general_meeting.place,
                meeting_form=command.general_meeting.meeting_form,
                chair_name=command.general_meeting.chair_name,
                co_signer_name=command.general_meeting.co_signer_name,
            ),
            "shareholder_ballots": tuple(
                ShareholderBallot(
                    shareholder_id=item.shareholder_id,
                    represented_share_count=item.represented_share_count,
                    vote=item.vote,
                )
                for item in command.shareholder_ballots
            ),
            "one_share_class_confirmed": command.one_share_class_confirmed,
            "full_board_participation_confirmed": (
                command.full_board_participation_confirmed
            ),
            "unanimous_board_confirmed": command.unanimous_board_confirmed,
            "supported_dividend_basis_confirmed": (
                command.supported_dividend_basis_confirmed
            ),
            "prudent_equity_and_liquidity_confirmed": (
                command.prudent_equity_and_liquidity_confirmed
            ),
        }

    @application.get(
        "/api/v1/corporate-governance/decision-facts",
        operation_id="corporateGovernanceDeriveDecisionFacts",
        response_model=CorporateDecisionFactsWire,
        responses={
            200: {"description": "Backend-derived current corporate facts."}
            | corporate_governance_success
        }
        | corporate_governance_errors,
        tags=["corporate-governance"],
    )
    async def derive_corporate_decision_facts(
        request: Request,
        company_id: Annotated[UUID, Query(alias="companyId")],
        income_year: Annotated[int, Query(alias="incomeYear", ge=2000, le=2200)],
        decision_kind: Annotated[
            CorporateDecisionKind, Query(alias="decisionKind")
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CorporateDecisionFactsWire:
        async def execute() -> CorporateDecisionFactsWire:
            return corporate_decision_facts_wire(
                await corporate_governance_application.derive_decision_facts(
                    bearer_token(credentials),
                    company_id=CompanyId(str(company_id)),
                    income_year=IncomeYear(income_year),
                    decision_kind=decision_kind,
                    correlation_id=CorrelationId(request.state.request_id),
                )
            )

        return await corporate_governance_call(execute)

    @application.get(
        "/api/v1/corporate-governance/readiness",
        operation_id="corporateGovernanceReadDecisionReadiness",
        response_model=CorporateDocumentReadinessWire,
        responses={200: {"description": "Backend-owned corporate readiness."} | corporate_governance_success}
        | corporate_governance_errors,
        tags=["corporate-governance"],
    )
    async def read_corporate_document_readiness(
        request: Request,
        company_id: Annotated[UUID, Query(alias="companyId")],
        income_year: Annotated[int, Query(alias="incomeYear", ge=2000, le=2200)],
        decision_kind: Annotated[
            CorporateDecisionKind, Query(alias="decisionKind")
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CorporateDocumentReadinessWire:
        async def execute() -> CorporateDocumentReadinessWire:
            return corporate_document_readiness_wire(
                await corporate_governance_application.read_readiness(
                    bearer_token(credentials),
                    company_id=CompanyId(str(company_id)),
                    income_year=IncomeYear(income_year),
                    decision_kind=decision_kind,
                    correlation_id=CorrelationId(request.state.request_id),
                )
            )

        return await corporate_governance_call(execute)

    @application.get(
        "/api/v1/corporate-governance/decisions",
        operation_id="corporateGovernanceListDecisionLifecycle",
        response_model=CorporateLifecycleSnapshotWire,
        responses={200: {"description": "Corporate lifecycle records."} | corporate_governance_success}
        | corporate_governance_errors,
        tags=["corporate-governance"],
    )
    async def list_corporate_decision_lifecycle(
        company_id: Annotated[list[UUID], Query(alias="companyId", min_length=1)],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CorporateLifecycleSnapshotWire:
        async def execute() -> CorporateLifecycleSnapshotWire:
            access_token = bearer_token(credentials)
            return corporate_lifecycle_snapshot_wire(
                await corporate_governance_application.list_lifecycle(
                    access_token,
                    tuple(CompanyId(str(value)) for value in company_id),
                )
            )

        return await corporate_governance_call(execute)

    @application.get(
        "/api/v1/corporate-governance/decisions/{decision_id}",
        operation_id="corporateGovernanceReadDecisionLifecycle",
        response_model=CorporateLifecycleSnapshotWire,
        responses={200: {"description": "Corporate lifecycle record."} | corporate_governance_success}
        | corporate_governance_errors,
        tags=["corporate-governance"],
    )
    async def read_corporate_decision_lifecycle(
        decision_id: UUID,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CorporateLifecycleSnapshotWire:
        async def execute() -> CorporateLifecycleSnapshotWire:
            access_token = bearer_token(credentials)
            return corporate_lifecycle_snapshot_wire(
                await corporate_governance_application.read_lifecycle(
                    access_token,
                    CorporateDecisionId(str(decision_id)),
                )
            )

        return await corporate_governance_call(execute)

    @application.post(
        "/api/v1/corporate-governance/owner-dividends/proposals",
        operation_id="corporateGovernanceProposeOwnerDividend",
        response_model=ProposedOwnerDividendWire,
        status_code=201,
        responses={
            201: {"description": "Owner dividend proposed."}
            | corporate_governance_success
        }
        | corporate_governance_errors,
        tags=["corporate-governance"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def propose_owner_dividend(
        request: Request,
        command: OwnerDividendProposalWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> ProposedOwnerDividendWire:
        async def execute() -> ProposedOwnerDividendWire:
            access_token = bearer_token(credentials)
            actor_id = await governance_actor(access_token)
            domain_command = corporate_governance_input(
                lambda: OwnerDividendProposalCommand(
                    **decision_proposal_fields(
                        request,
                        command,
                        actor_id,
                        idempotency_key,
                    ),
                    dividend_amount_ore=command.dividend_amount_ore,
                    payment_date=LocalDate(command.payment_date),
                )
            )
            result = await corporate_governance_application.propose_owner_dividend(
                access_token, domain_command
            )
            return proposed_dividend_wire(result)

        return await corporate_governance_call(execute)

    @application.post(
        "/api/v1/corporate-governance/annual-closes/proposals",
        operation_id="corporateGovernanceProposeAnnualClose",
        response_model=ProposedAnnualCloseWire,
        status_code=201,
        responses={
            201: {"description": "Annual close proposed."}
            | corporate_governance_success
        }
        | corporate_governance_errors,
        tags=["corporate-governance"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def propose_annual_close(
        request: Request,
        command: AnnualCloseProposalWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> ProposedAnnualCloseWire:
        async def execute() -> ProposedAnnualCloseWire:
            access_token = bearer_token(credentials)
            actor_id = await governance_actor(access_token)
            domain_command = corporate_governance_input(
                lambda: AnnualCloseProposalCommand(
                    **decision_proposal_fields(
                        request,
                        command,
                        actor_id,
                        idempotency_key,
                    ),
                    annual_result_allocation_ore=(
                        command.annual_result_allocation_ore
                    ),
                )
            )
            result = await corporate_governance_application.propose_annual_close(
                access_token,
                domain_command,
            )
            return proposed_annual_close_wire(result)

        return await corporate_governance_call(execute)

    @application.post(
        "/api/v1/corporate-governance/annual-closes/{decision_id}/documents",
        operation_id="corporateGovernanceRegisterAnnualCloseDocuments",
        response_model=AnnualCloseLifecycleWire,
        status_code=201,
        responses={
            201: {"description": "Annual-close documents registered."}
            | corporate_governance_success
        }
        | corporate_governance_errors,
        tags=["corporate-governance"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def register_annual_close_documents(
        request: Request,
        decision_id: UUID,
        command: OwnerDividendDocumentsWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> AnnualCloseLifecycleWire:
        async def execute() -> AnnualCloseLifecycleWire:
            access_token = bearer_token(credentials)
            actor_id = await governance_actor(access_token)
            domain_command = corporate_governance_input(
                lambda: RegisterAnnualCloseDocumentsCommand(
                    company_id=CompanyId(str(command.company_id)),
                    actor_id=actor_id,
                    correlation_id=CorrelationId(request.state.request_id),
                    idempotency_key=IdempotencyKey(idempotency_key),
                    decision_id=CorporateDecisionId(str(decision_id)),
                    document_set_id=CorporateDocumentSetId(
                        str(command.document_set_id)
                    ),
                    decision_hash=command.decision_hash,
                    artifacts=tuple(
                        OwnerDividendArtifactReference(
                            CorporateArtifactId(str(item.artifact_id)),
                            DocumentReference(str(item.document_id)),
                            item.artifact_kind,
                            item.content_sha256,
                            item.byte_length,
                        )
                        for item in command.artifacts
                    ),
                )
            )
            result = await corporate_governance_application.register_annual_close_documents(
                access_token,
                domain_command,
            )
            return annual_close_lifecycle_wire(result)

        return await corporate_governance_call(execute)

    @application.post(
        "/api/v1/corporate-governance/annual-closes/{decision_id}/approvals",
        operation_id="corporateGovernanceApproveAnnualClose",
        response_model=AnnualCloseLifecycleWire,
        status_code=201,
        responses={201: {"description": "Annual-close facts approved."} | corporate_governance_success}
        | corporate_governance_errors,
        tags=["corporate-governance"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def approve_annual_close(
        request: Request,
        decision_id: UUID,
        command: OwnerDividendApprovalWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> AnnualCloseLifecycleWire:
        async def execute() -> AnnualCloseLifecycleWire:
            access_token = bearer_token(credentials)
            actor_id = await governance_actor(access_token)
            domain_command = corporate_governance_input(
                lambda: ApproveAnnualCloseCommand(
                    company_id=CompanyId(str(command.company_id)),
                    actor_id=actor_id,
                    correlation_id=CorrelationId(request.state.request_id),
                    idempotency_key=IdempotencyKey(idempotency_key),
                    decision_id=CorporateDecisionId(str(decision_id)),
                    document_set_id=CorporateDocumentSetId(str(command.document_set_id)),
                    decision_hash=command.decision_hash,
                    approval_event_id=CorporateEventId(str(command.approval_event_id)),
                )
            )
            return annual_close_lifecycle_wire(
                await corporate_governance_application.approve_annual_close(
                    access_token, domain_command
                )
            )

        return await corporate_governance_call(execute)

    @application.post(
        "/api/v1/corporate-governance/annual-closes/{decision_id}/events",
        operation_id="corporateGovernanceRecordAnnualCloseEvent",
        response_model=AnnualCloseLifecycleWire,
        status_code=201,
        responses={201: {"description": "Annual-close lifecycle event recorded."} | corporate_governance_success}
        | corporate_governance_errors,
        tags=["corporate-governance"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def record_annual_close_event(
        request: Request,
        decision_id: UUID,
        command: AnnualCloseEventWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> AnnualCloseLifecycleWire:
        async def execute() -> AnnualCloseLifecycleWire:
            access_token = bearer_token(credentials)
            actor_id = await governance_actor(access_token)
            domain_command = corporate_governance_input(
                lambda: RecordAnnualCloseEventCommand(
                    company_id=CompanyId(str(command.company_id)),
                    actor_id=actor_id,
                    correlation_id=CorrelationId(request.state.request_id),
                    idempotency_key=IdempotencyKey(idempotency_key),
                    decision_id=CorporateDecisionId(str(decision_id)),
                    document_set_id=CorporateDocumentSetId(str(command.document_set_id)),
                    decision_hash=command.decision_hash,
                    event_id=CorporateEventId(str(command.event_id)),
                    event_kind=command.event_kind,
                    metadata=command.metadata,
                )
            )
            return annual_close_lifecycle_wire(
                await corporate_governance_application.record_annual_close_event(
                    access_token, domain_command
                )
            )

        return await corporate_governance_call(execute)

    @application.post(
        "/api/v1/corporate-governance/annual-closes/{decision_id}/finalizations",
        operation_id="corporateGovernanceFinalizeAnnualClose",
        response_model=AnnualCloseLifecycleWire,
        status_code=201,
        responses={201: {"description": "Annual close finalized."} | corporate_governance_success}
        | corporate_governance_errors,
        tags=["corporate-governance"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def finalize_annual_close(
        request: Request,
        decision_id: UUID,
        command: AnnualCloseFinalizationWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> AnnualCloseLifecycleWire:
        async def execute() -> AnnualCloseLifecycleWire:
            access_token = bearer_token(credentials)
            actor_id = await governance_actor(access_token)
            domain_command = corporate_governance_input(
                lambda: FinalizeAnnualCloseCommand(
                    company_id=CompanyId(str(command.company_id)),
                    actor_id=actor_id,
                    correlation_id=CorrelationId(request.state.request_id),
                    idempotency_key=IdempotencyKey(idempotency_key),
                    decision_id=CorporateDecisionId(str(decision_id)),
                    document_set_id=CorporateDocumentSetId(str(command.document_set_id)),
                    decision_hash=command.decision_hash,
                    finalization_id=CorporateFinalizationId(str(command.finalization_id)),
                )
            )
            return annual_close_lifecycle_wire(
                await corporate_governance_application.finalize_annual_close(
                    access_token, domain_command
                )
            )

        return await corporate_governance_call(execute)

    @application.post(
        "/api/v1/corporate-governance/annual-closes/{decision_id}/signed-artifacts",
        operation_id="corporateGovernanceAttestAnnualCloseSignedArtifact",
        response_model=AnnualCloseLifecycleWire,
        status_code=201,
        responses={201: {"description": "Signed annual-close artifact attested."} | corporate_governance_success}
        | corporate_governance_errors,
        tags=["corporate-governance"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def attest_annual_close_signed_artifact(
        request: Request,
        decision_id: UUID,
        command: AnnualCloseSignedArtifactWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> AnnualCloseLifecycleWire:
        async def execute() -> AnnualCloseLifecycleWire:
            access_token = bearer_token(credentials)
            actor_id = await governance_actor(access_token)
            domain_command = corporate_governance_input(
                lambda: AttestAnnualCloseSignedArtifactCommand(
                    company_id=CompanyId(str(command.company_id)),
                    actor_id=actor_id,
                    correlation_id=CorrelationId(request.state.request_id),
                    idempotency_key=IdempotencyKey(idempotency_key),
                    decision_id=CorporateDecisionId(str(decision_id)),
                    document_set_id=CorporateDocumentSetId(str(command.document_set_id)),
                    decision_hash=command.decision_hash,
                    unsigned_artifact_id=CorporateArtifactId(
                        str(command.unsigned_artifact_id)
                    ),
                    signed_artifact_id=CorporateArtifactId(
                        str(command.signed_artifact_id)
                    ),
                    signed_document_id=DocumentReference(
                        str(command.signed_document_id)
                    ),
                    artifact_kind=CorporateArtifactKind(command.artifact_kind),
                    filename=command.filename,
                    content_sha256=command.content_sha256,
                    byte_length=command.byte_length,
                )
            )
            return annual_close_lifecycle_wire(
                await corporate_governance_application.attest_annual_close_signed_artifact(
                    access_token, domain_command
                )
            )

        return await corporate_governance_call(execute)

    @application.post(
        "/api/v1/corporate-governance/owner-dividends/{decision_id}/documents",
        operation_id="corporateGovernanceRegisterOwnerDividendDocuments",
        response_model=OwnerDividendLifecycleWire,
        status_code=201,
        responses={
            201: {"description": "Owner-dividend documents registered."}
            | corporate_governance_success
        }
        | corporate_governance_errors,
        tags=["corporate-governance"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def register_owner_dividend_documents(
        request: Request,
        decision_id: UUID,
        command: OwnerDividendDocumentsWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> OwnerDividendLifecycleWire:
        async def execute() -> OwnerDividendLifecycleWire:
            access_token = bearer_token(credentials)
            actor_id = await governance_actor(access_token)
            domain_command = corporate_governance_input(
                lambda: RegisterOwnerDividendDocumentsCommand(
                    company_id=CompanyId(str(command.company_id)),
                    actor_id=actor_id,
                    correlation_id=CorrelationId(request.state.request_id),
                    idempotency_key=IdempotencyKey(idempotency_key),
                    decision_id=CorporateDecisionId(str(decision_id)),
                    document_set_id=CorporateDocumentSetId(
                        str(command.document_set_id)
                    ),
                    decision_hash=command.decision_hash,
                    artifacts=tuple(
                        OwnerDividendArtifactReference(
                            artifact_id=CorporateArtifactId(str(item.artifact_id)),
                            document_id=DocumentReference(str(item.document_id)),
                            artifact_kind=item.artifact_kind,
                            content_sha256=item.content_sha256,
                            byte_length=item.byte_length,
                        )
                        for item in command.artifacts
                    ),
                )
            )
            result = await corporate_governance_application.register_owner_dividend_documents(
                access_token, domain_command
            )
            return dividend_lifecycle_wire(result)

        return await corporate_governance_call(execute)

    @application.post(
        "/api/v1/corporate-governance/owner-dividends/{decision_id}/approvals",
        operation_id="corporateGovernanceApproveOwnerDividend",
        response_model=OwnerDividendLifecycleWire,
        status_code=201,
        responses={
            201: {"description": "Owner-dividend facts approved."}
            | corporate_governance_success
        }
        | corporate_governance_errors,
        tags=["corporate-governance"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def approve_owner_dividend(
        request: Request,
        decision_id: UUID,
        command: OwnerDividendApprovalWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> OwnerDividendLifecycleWire:
        async def execute() -> OwnerDividendLifecycleWire:
            access_token = bearer_token(credentials)
            actor_id = await governance_actor(access_token)
            domain_command = corporate_governance_input(
                lambda: ApproveOwnerDividendCommand(
                    company_id=CompanyId(str(command.company_id)),
                    actor_id=actor_id,
                    correlation_id=CorrelationId(request.state.request_id),
                    idempotency_key=IdempotencyKey(idempotency_key),
                    decision_id=CorporateDecisionId(str(decision_id)),
                    document_set_id=CorporateDocumentSetId(
                        str(command.document_set_id)
                    ),
                    decision_hash=command.decision_hash,
                    approval_event_id=CorporateEventId(str(command.approval_event_id)),
                )
            )
            result = await corporate_governance_application.approve_owner_dividend(
                access_token, domain_command
            )
            return dividend_lifecycle_wire(result)

        return await corporate_governance_call(execute)

    @application.post(
        "/api/v1/corporate-governance/owner-dividends/{decision_id}/events",
        operation_id="corporateGovernanceRecordOwnerDividendEvent",
        response_model=OwnerDividendLifecycleWire,
        status_code=201,
        responses={201: {"description": "Owner-dividend lifecycle event recorded."} | corporate_governance_success}
        | corporate_governance_errors,
        tags=["corporate-governance"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def record_owner_dividend_event(
        request: Request,
        decision_id: UUID,
        command: OwnerDividendEventWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> OwnerDividendLifecycleWire:
        async def execute() -> OwnerDividendLifecycleWire:
            access_token = bearer_token(credentials)
            actor_id = await governance_actor(access_token)
            domain_command = corporate_governance_input(
                lambda: RecordOwnerDividendEventCommand(
                    company_id=CompanyId(str(command.company_id)),
                    actor_id=actor_id,
                    correlation_id=CorrelationId(request.state.request_id),
                    idempotency_key=IdempotencyKey(idempotency_key),
                    decision_id=CorporateDecisionId(str(decision_id)),
                    document_set_id=CorporateDocumentSetId(
                        str(command.document_set_id)
                    ),
                    decision_hash=command.decision_hash,
                    event_id=CorporateEventId(str(command.event_id)),
                    event_kind=command.event_kind,
                    metadata=command.metadata,
                )
            )
            return dividend_lifecycle_wire(
                await corporate_governance_application.record_owner_dividend_event(
                    access_token, domain_command
                )
            )

        return await corporate_governance_call(execute)

    @application.post(
        "/api/v1/corporate-governance/owner-dividends/{decision_id}/signed-artifacts",
        operation_id="corporateGovernanceAttestOwnerDividendSignedArtifact",
        response_model=OwnerDividendLifecycleWire,
        status_code=201,
        responses={201: {"description": "Signed owner-dividend artifact attested."} | corporate_governance_success}
        | corporate_governance_errors,
        tags=["corporate-governance"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def attest_owner_dividend_signed_artifact(
        request: Request,
        decision_id: UUID,
        command: OwnerDividendSignedArtifactWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> OwnerDividendLifecycleWire:
        async def execute() -> OwnerDividendLifecycleWire:
            access_token = bearer_token(credentials)
            actor_id = await governance_actor(access_token)
            domain_command = corporate_governance_input(
                lambda: AttestOwnerDividendSignedArtifactCommand(
                    company_id=CompanyId(str(command.company_id)),
                    actor_id=actor_id,
                    correlation_id=CorrelationId(request.state.request_id),
                    idempotency_key=IdempotencyKey(idempotency_key),
                    decision_id=CorporateDecisionId(str(decision_id)),
                    document_set_id=CorporateDocumentSetId(
                        str(command.document_set_id)
                    ),
                    decision_hash=command.decision_hash,
                    unsigned_artifact_id=CorporateArtifactId(
                        str(command.unsigned_artifact_id)
                    ),
                    signed_artifact_id=CorporateArtifactId(
                        str(command.signed_artifact_id)
                    ),
                    signed_document_id=DocumentReference(
                        str(command.signed_document_id)
                    ),
                    artifact_kind=CorporateArtifactKind(command.artifact_kind),
                    filename=command.filename,
                    content_sha256=command.content_sha256,
                    byte_length=command.byte_length,
                )
            )
            return dividend_lifecycle_wire(
                await corporate_governance_application.attest_owner_dividend_signed_artifact(
                    access_token, domain_command
                )
            )

        return await corporate_governance_call(execute)

    @application.post(
        "/api/v1/corporate-governance/owner-dividends/{decision_id}/finalizations",
        operation_id="corporateGovernanceFinalizeOwnerDividend",
        response_model=OwnerDividendLifecycleWire,
        status_code=201,
        responses={
            201: {"description": "Owner dividend finalized and declared in Ledger."}
            | corporate_governance_success
        }
        | corporate_governance_errors,
        tags=["corporate-governance"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def finalize_owner_dividend(
        request: Request,
        decision_id: UUID,
        command: OwnerDividendFinalizationWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> OwnerDividendLifecycleWire:
        async def execute() -> OwnerDividendLifecycleWire:
            access_token = bearer_token(credentials)
            actor_id = await governance_actor(access_token)
            domain_command = corporate_governance_input(
                lambda: FinalizeOwnerDividendCommand(
                    company_id=CompanyId(str(command.company_id)),
                    actor_id=actor_id,
                    correlation_id=CorrelationId(request.state.request_id),
                    idempotency_key=IdempotencyKey(idempotency_key),
                    income_year=IncomeYear(command.income_year),
                    decision_id=CorporateDecisionId(str(decision_id)),
                    document_set_id=CorporateDocumentSetId(
                        str(command.document_set_id)
                    ),
                    decision_hash=command.decision_hash,
                    finalization_id=CorporateFinalizationId(
                        str(command.finalization_id)
                    ),
                    holding_action_id=CorporateEventId(str(command.holding_action_id)),
                    ledger_entry_id=CorporateAccountingEntryReference(
                        str(command.ledger_entry_id)
                    ),
                )
            )
            result = await corporate_governance_application.finalize_owner_dividend(
                access_token, domain_command
            )
            return dividend_lifecycle_wire(result)

        return await corporate_governance_call(execute)

    @application.post(
        "/api/v1/corporate-governance/owner-dividends/{decision_id}/payments",
        operation_id="corporateGovernanceRecordOwnerDividendPayment",
        response_model=OwnerDividendLifecycleWire,
        status_code=201,
        responses={
            201: {
                "description": "Owner-dividend payment recorded in Ledger and Banking."
            }
            | corporate_governance_success
        }
        | corporate_governance_errors,
        tags=["corporate-governance"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def record_owner_dividend_payment(
        request: Request,
        decision_id: UUID,
        command: OwnerDividendPaymentWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> OwnerDividendLifecycleWire:
        async def execute() -> OwnerDividendLifecycleWire:
            access_token = bearer_token(credentials)
            actor_id = await governance_actor(access_token)
            domain_command = corporate_governance_input(
                lambda: CorporateRecordOwnerDividendPaymentCommand(
                    company_id=CompanyId(str(command.company_id)),
                    actor_id=actor_id,
                    correlation_id=CorrelationId(request.state.request_id),
                    idempotency_key=IdempotencyKey(idempotency_key),
                    income_year=IncomeYear(command.income_year),
                    decision_id=CorporateDecisionId(str(decision_id)),
                    document_set_id=CorporateDocumentSetId(
                        str(command.document_set_id)
                    ),
                    decision_hash=command.decision_hash,
                    payment_event_id=CorporateEventId(str(command.payment_event_id)),
                    holding_action_id=CorporateEventId(str(command.holding_action_id)),
                    ledger_entry_id=CorporateAccountingEntryReference(
                        str(command.ledger_entry_id)
                    ),
                    bank_transaction_id=BankTransactionReference(
                        str(command.bank_transaction_id)
                    ),
                )
            )
            result = (
                await corporate_governance_application.record_owner_dividend_payment(
                    access_token, domain_command
                )
            )
            return dividend_lifecycle_wire(result)

        return await corporate_governance_call(execute)

    @application.post(
        "/api/v1/corporate-governance/shareholder-loans",
        operation_id="corporateGovernanceRecordShareholderLoan",
        response_model=RecordedShareholderLoanWire,
        status_code=201,
        responses={
            201: {
                "description": "Shareholder loan recorded in Corporate Governance and Ledger."
            }
            | corporate_governance_success
        }
        | corporate_governance_errors,
        tags=["corporate-governance"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def record_corporate_shareholder_loan(
        request: Request,
        command: ShareholderLoanWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> RecordedShareholderLoanWire:
        async def execute() -> RecordedShareholderLoanWire:
            access_token = bearer_token(credentials)
            actor_id = await governance_actor(access_token)
            domain_command = corporate_governance_input(
                lambda: CorporateRecordShareholderLoanCommand(
                    company_id=CompanyId(str(command.company_id)),
                    actor_id=actor_id,
                    correlation_id=CorrelationId(request.state.request_id),
                    idempotency_key=IdempotencyKey(idempotency_key),
                    income_year=IncomeYear(command.income_year),
                    action_id=CorporateEventId(str(command.action_id)),
                    ledger_entry_id=CorporateAccountingEntryReference(
                        str(command.ledger_entry_id)
                    ),
                    loan_date=LocalDate(command.loan_date),
                    amount=command.amount.to_domain(),
                    direction=command.direction,
                    counterparty_name=command.counterparty_name,
                    document_status=command.document_status,
                    interest_modelled=command.interest_modelled,
                    related_party_security=command.related_party_security,
                    bank_transaction_id=(
                        BankTransactionReference(str(command.bank_transaction_id))
                        if command.bank_transaction_id
                        else None
                    ),
                    document_id=(
                        DocumentReference(str(command.document_id))
                        if command.document_id
                        else None
                    ),
                )
            )
            result = await corporate_governance_application.record_shareholder_loan(
                access_token, domain_command
            )
            return shareholder_loan_wire(result)

        return await corporate_governance_call(execute)

    @application.get(
        "/api/v1/corporate-governance/supported-events",
        operation_id="corporateGovernanceListSupportedEvents",
        response_model=list[RecordedSupportedCorporateEventWire],
        responses={
            200: {"description": "Supported capital, financing and group events."}
            | corporate_governance_success
        }
        | corporate_governance_errors,
        tags=["corporate-governance"],
    )
    async def list_corporate_supported_events(
        company_ids: Annotated[
            list[UUID], Query(alias="companyId", min_length=1, max_length=100)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> list[RecordedSupportedCorporateEventWire]:
        async def execute() -> list[RecordedSupportedCorporateEventWire]:
            values = await corporate_governance_application.list_supported_events(
                bearer_token(credentials),
                tuple(CompanyId(str(company_id)) for company_id in company_ids),
            )
            return [supported_event_wire(value) for value in values]

        return await corporate_governance_call(execute)

    @application.post(
        "/api/v1/corporate-governance/supported-events",
        operation_id="corporateGovernanceRecordSupportedEvent",
        response_model=RecordedSupportedCorporateEventWire,
        status_code=201,
        responses={
            201: {
                "description": "Supported corporate event recorded atomically with Ledger."
            }
            | corporate_governance_success
        }
        | corporate_governance_errors,
        tags=["corporate-governance"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def record_corporate_supported_event(
        request: Request,
        command: SupportedCorporateEventWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> RecordedSupportedCorporateEventWire:
        async def execute() -> RecordedSupportedCorporateEventWire:
            access_token = bearer_token(credentials)
            actor_id = await governance_actor(access_token)
            domain_command = corporate_governance_input(
                lambda: RecordSupportedCorporateEventCommand(
                    company_id=CompanyId(str(command.company_id)),
                    actor_id=actor_id,
                    correlation_id=CorrelationId(request.state.request_id),
                    idempotency_key=IdempotencyKey(idempotency_key),
                    income_year=IncomeYear(command.income_year),
                    event_id=SupportedCorporateEventId(str(command.event_id)),
                    event_reference=SupportedCorporateEventReference(
                        str(command.event_reference)
                    ),
                    event_date=LocalDate(command.event_date),
                    event_kind=command.event_kind,
                    phase=command.phase,
                    facts=supported_event_facts(command.facts),
                    document_facts=tuple(
                        SupportedCorporateDocumentFact(
                            document_id=DocumentReference(str(item.document_id)),
                            evidence_kind=item.evidence_kind,
                            revision=item.revision,
                            content_sha256=item.content_sha256,
                        )
                        for item in command.document_facts
                    ),
                    bank_fact=(
                        SupportedCorporateBankFact(
                            transaction_id=BankTransactionReference(
                                str(command.bank_fact.transaction_id)
                            ),
                            transaction_date=LocalDate(
                                command.bank_fact.transaction_date
                            ),
                            signed_amount=command.bank_fact.signed_amount.to_domain(),
                            source_sha256=command.bank_fact.source_sha256,
                        )
                        if command.bank_fact
                        else None
                    ),
                    shareholder_register_fact=(
                        SupportedCorporateSourceFact(
                            record_id=CorporateSourceReference(
                                str(command.shareholder_register_fact.record_id)
                            ),
                            revision=command.shareholder_register_fact.revision,
                            fact_sha256=command.shareholder_register_fact.fact_sha256,
                        )
                        if command.shareholder_register_fact
                        else None
                    ),
                    tax_calculation_fact=(
                        SupportedCorporateSourceFact(
                            record_id=CorporateSourceReference(
                                str(command.tax_calculation_fact.record_id)
                            ),
                            revision=command.tax_calculation_fact.revision,
                            fact_sha256=command.tax_calculation_fact.fact_sha256,
                        )
                        if command.tax_calculation_fact
                        else None
                    ),
                )
            )
            result = await corporate_governance_application.record_supported_event(
                access_token, domain_command
            )
            return supported_event_wire(result)

        return await corporate_governance_call(execute)

    @application.post(
        "/api/v1/corporate-governance/supported-events/{event_id}/reversal",
        operation_id="corporateGovernanceReverseSupportedEvent",
        response_model=ReversedSupportedCorporateEventWire,
        status_code=201,
        responses={
            201: {
                "description": "Supported event reversed with immutable Ledger lineage."
            }
            | corporate_governance_success
        }
        | corporate_governance_errors,
        tags=["corporate-governance"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def reverse_corporate_supported_event(
        event_id: UUID,
        request: Request,
        command: ReverseSupportedCorporateEventWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> ReversedSupportedCorporateEventWire:
        async def execute() -> ReversedSupportedCorporateEventWire:
            access_token = bearer_token(credentials)
            actor_id = await governance_actor(access_token)
            fact = command.correction_document_fact
            domain_command = corporate_governance_input(
                lambda: ReverseSupportedCorporateEventCommand(
                    company_id=CompanyId(str(command.company_id)),
                    actor_id=actor_id,
                    correlation_id=CorrelationId(request.state.request_id),
                    idempotency_key=IdempotencyKey(idempotency_key),
                    income_year=IncomeYear(command.income_year),
                    original_event_id=SupportedCorporateEventId(str(event_id)),
                    reversal_date=LocalDate(command.reversal_date),
                    reason=command.reason,
                    correction_document_fact=SupportedCorporateDocumentFact(
                        document_id=DocumentReference(str(fact.document_id)),
                        evidence_kind=fact.evidence_kind,
                        revision=fact.revision,
                        content_sha256=fact.content_sha256,
                    ),
                )
            )
            result = await corporate_governance_application.reverse_supported_event(
                access_token, domain_command
            )
            return reversed_supported_event_wire(result)

        return await corporate_governance_call(execute)

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
            accounting_classification=value.accounting_classification,
            tax_treatment=value.tax_treatment,
            org_number=value.org_number,
            fund_equity_ratio_basis_points=value.fund_equity_ratio_basis_points,
            fund_tax_statement_reference=value.fund_tax_statement_reference,
            share_count=format(value.share_count.amount, ".12f"),
            cost_basis=_money_wire(value.cost_basis),
            tax_basis=_money_wire(value.tax_basis),
            lot_history_status=value.lot_history_status,
            movement_count=value.movement_count,
            movements=[
                InvestmentPositionMovementWire.model_validate(dict(movement))
                for movement in value.movements
            ],
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
            original_share_count=format(value.original_share_count.amount, ".12f"),
            remaining_share_count=format(value.remaining_share_count.amount, ".12f"),
            original_cost_basis=_money_wire(value.original_cost_basis),
            remaining_cost_basis=_money_wire(value.remaining_cost_basis),
            original_tax_basis=_money_wire(value.original_tax_basis),
            remaining_tax_basis=_money_wire(value.remaining_tax_basis),
            acquisition_year_fund_equity_ratio_basis_points=(
                value.acquisition_year_fund_equity_ratio_basis_points
            ),
            fund_tax_statement_reference=value.fund_tax_statement_reference,
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
            accounting_classification=value.accounting_classification,
            tax_treatment=value.tax_treatment,
            org_number=value.org_number,
            fund_equity_ratio_basis_points=value.fund_equity_ratio_basis_points,
            fund_tax_statement_reference=value.fund_tax_statement_reference,
            acquisition_lot_id=(
                UUID(str(value.acquisition_lot_id))
                if value.acquisition_lot_id else None
            ),
            share_count=(
                format(value.share_count.amount, ".12f")
                if value.share_count is not None else None
            ),
            purchase_amount=(
                _money_wire(value.purchase_amount) if value.purchase_amount else None
            ),
            transaction_costs=(
                _money_wire(value.transaction_costs)
                if value.transaction_costs else None
            ),
            capitalized_cost=(
                _money_wire(value.capitalized_cost)
                if value.capitalized_cost else None
            ),
            sold_share_count=(
                format(value.sold_share_count.amount, ".12f")
                if value.sold_share_count is not None else None
            ),
            proceeds=_money_wire(value.proceeds) if value.proceeds else None,
            net_proceeds=(
                _money_wire(value.net_proceeds) if value.net_proceeds else None
            ),
            fifo_cost_basis_reduction=(
                _money_wire(value.fifo_cost_basis_reduction)
                if value.fifo_cost_basis_reduction else None
            ),
            fifo_tax_basis_reduction=(
                _money_wire(value.fifo_tax_basis_reduction)
                if value.fifo_tax_basis_reduction else None
            ),
            remaining_share_count=(
                format(value.remaining_share_count.amount, ".12f")
                if value.remaining_share_count is not None else None
            ),
            remaining_cost_basis=(
                _money_wire(value.remaining_cost_basis)
                if value.remaining_cost_basis else None
            ),
            remaining_tax_basis=(
                _money_wire(value.remaining_tax_basis)
                if value.remaining_tax_basis else None
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
            book_gain_or_loss=(
                _money_wire(value.book_gain_or_loss)
                if value.book_gain_or_loss else None
            ),
            tax_gain_or_loss=(
                _money_wire(value.tax_gain_or_loss)
                if value.tax_gain_or_loss else None
            ),
            exempt_gain=(
                _money_wire(value.exempt_gain) if value.exempt_gain else None
            ),
            taxable_gain=(
                _money_wire(value.taxable_gain) if value.taxable_gain else None
            ),
            non_deductible_loss=(
                _money_wire(value.non_deductible_loss)
                if value.non_deductible_loss else None
            ),
            deductible_loss=(
                _money_wire(value.deductible_loss)
                if value.deductible_loss else None
            ),
            lawful_dividend_confirmed=value.lawful_dividend_confirmed,
            group_exception_claimed=value.group_exception_claimed,
            group_exception_applied=value.group_exception_applied,
            year_end_ownership_basis_points=value.year_end_ownership_basis_points,
            year_end_voting_basis_points=value.year_end_voting_basis_points,
            group_evidence_reference=value.group_evidence_reference,
            fund_name=value.fund_name,
            entitlement_date=(
                value.entitlement_date.value if value.entitlement_date else None
            ),
            opening_fund_equity_ratio_basis_points=(
                value.opening_fund_equity_ratio_basis_points
            ),
            dividend_portion=(
                _money_wire(value.dividend_portion)
                if value.dividend_portion else None
            ),
            interest_portion=(
                _money_wire(value.interest_portion)
                if value.interest_portion else None
            ),
            total_taxable_income=(
                _money_wire(value.total_taxable_income)
                if value.total_taxable_income else None
            ),
            bank_transaction_id=(
                UUID(str(value.bank_transaction_id))
                if value.bank_transaction_id else None
            ),
            document_id=(
                UUID(str(value.document_id)) if value.document_id else None
            ),
            document_status=value.document_status,
            evidence_mode=value.evidence_mode,
            evidence_reference=value.evidence_reference,
            evidence_digest=value.evidence_digest,
            calculation_id=value.calculation_id,
            owner_attested=value.owner_attested,
            accounting_entry_id=(
                UUID(str(value.accounting_entry_id))
                if value.accounting_entry_id else None
            ),
            created_by=UUID(str(value.created_by.subject)),
            created_at=value.created_at.value,
        )

    def investment_lifecycle_event_wire(
        value: InvestmentLifecycleEventView,
    ) -> InvestmentLifecycleEventWire:
        def fact_wire(fact: InvestmentFactReference) -> InvestmentFactReferenceWire:
            return InvestmentFactReferenceWire(
                capability=fact.capability,
                record_id=UUID(str(fact.record_id)),
                revision=fact.revision,
                fact_sha256=fact.fact_sha256,
            )

        return InvestmentLifecycleEventWire(
            id=UUID(str(value.event_id)),
            company_id=UUID(str(value.company_id)),
            income_year=int(value.income_year),
            activity_kind=value.activity_kind,
            recognition_date=value.recognition_date.value,
            position_id=UUID(str(value.position_id)),
            investment_key=value.investment_key,
            investment_name=value.investment_name,
            investment_kind=value.investment_kind,
            accounting_classification=value.accounting_classification,
            tax_treatment=value.tax_treatment,
            org_number=value.org_number,
            fund_equity_ratio_basis_points=value.fund_equity_ratio_basis_points,
            fund_tax_statement_reference=value.fund_tax_statement_reference,
            acquisition_lot_id=(
                UUID(str(value.acquisition_lot_id))
                if value.acquisition_lot_id else None
            ),
            position_created=value.position_created,
            share_count=(
                format(value.share_count.amount, ".12f")
                if value.share_count is not None else None
            ),
            purchase_amount=(
                _money_wire(value.purchase_amount)
                if value.purchase_amount else None
            ),
            transaction_costs=(
                _money_wire(value.transaction_costs)
                if value.transaction_costs else None
            ),
            capitalized_cost=(
                _money_wire(value.capitalized_cost)
                if value.capitalized_cost else None
            ),
            sold_share_count=(
                format(value.sold_share_count.amount, ".12f")
                if value.sold_share_count is not None else None
            ),
            proceeds=_money_wire(value.proceeds) if value.proceeds else None,
            net_proceeds=(
                _money_wire(value.net_proceeds) if value.net_proceeds else None
            ),
            fifo_cost_basis_reduction=(
                _money_wire(value.fifo_cost_basis_reduction)
                if value.fifo_cost_basis_reduction else None
            ),
            fifo_tax_basis_reduction=(
                _money_wire(value.fifo_tax_basis_reduction)
                if value.fifo_tax_basis_reduction else None
            ),
            remaining_share_count=(
                format(value.remaining_share_count.amount, ".12f")
                if value.remaining_share_count is not None else None
            ),
            remaining_cost_basis=(
                _money_wire(value.remaining_cost_basis)
                if value.remaining_cost_basis else None
            ),
            remaining_tax_basis=(
                _money_wire(value.remaining_tax_basis)
                if value.remaining_tax_basis else None
            ),
            book_gain_or_loss=(
                _money_wire(value.book_gain_or_loss)
                if value.book_gain_or_loss else None
            ),
            tax_gain_or_loss=(
                _money_wire(value.tax_gain_or_loss)
                if value.tax_gain_or_loss else None
            ),
            exempt_gain=(
                _money_wire(value.exempt_gain) if value.exempt_gain else None
            ),
            taxable_gain=(
                _money_wire(value.taxable_gain) if value.taxable_gain else None
            ),
            non_deductible_loss=(
                _money_wire(value.non_deductible_loss)
                if value.non_deductible_loss else None
            ),
            deductible_loss=(
                _money_wire(value.deductible_loss)
                if value.deductible_loss else None
            ),
            paying_company_name=value.paying_company_name,
            lawful_dividend_confirmed=value.lawful_dividend_confirmed,
            group_exception_claimed=value.group_exception_claimed,
            group_exception_applied=value.group_exception_applied,
            year_end_ownership_basis_points=value.year_end_ownership_basis_points,
            year_end_voting_basis_points=value.year_end_voting_basis_points,
            group_evidence_reference=value.group_evidence_reference,
            fund_name=value.fund_name,
            entitlement_date=(
                value.entitlement_date.value if value.entitlement_date else None
            ),
            opening_fund_equity_ratio_basis_points=(
                value.opening_fund_equity_ratio_basis_points
            ),
            gross_amount=(
                _money_wire(value.gross_amount) if value.gross_amount else None
            ),
            taxable_add_back=(
                _money_wire(value.taxable_add_back)
                if value.taxable_add_back else None
            ),
            dividend_portion=(
                _money_wire(value.dividend_portion)
                if value.dividend_portion else None
            ),
            interest_portion=(
                _money_wire(value.interest_portion)
                if value.interest_portion else None
            ),
            total_taxable_income=(
                _money_wire(value.total_taxable_income)
                if value.total_taxable_income else None
            ),
            expected_settlement_amount=_money_wire(
                value.expected_settlement_amount
            ),
            settlement_balance_kind=value.settlement_balance_kind,
            recognition_accounting_entry_id=UUID(
                str(value.recognition_accounting_entry_id)
            ),
            document_facts=[fact_wire(fact) for fact in value.document_facts],
            evidence_mode=value.evidence_mode,
            evidence_reference=value.evidence_reference,
            evidence_digest=value.evidence_digest,
            calculation_id=value.calculation_id,
            owner_attested=value.owner_attested,
            settlement_id=(
                UUID(str(value.settlement_id)) if value.settlement_id else None
            ),
            settlement_date=(
                value.settlement_date.value if value.settlement_date else None
            ),
            settlement_amount=(
                _money_wire(value.settlement_amount)
                if value.settlement_amount else None
            ),
            bank_fact=(fact_wire(value.bank_fact) if value.bank_fact else None),
            settlement_accounting_entry_id=(
                UUID(str(value.settlement_accounting_entry_id))
                if value.settlement_accounting_entry_id else None
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
            allocated_share_count=format(
                value.allocated_share_count.amount, ".12f"
            ),
            allocated_cost_basis=_money_wire(value.allocated_cost_basis),
            allocated_book_cost_basis=_money_wire(
                value.allocated_book_cost_basis
            ),
            allocated_tax_basis=_money_wire(value.allocated_tax_basis),
            allocated_net_proceeds=_money_wire(value.allocated_net_proceeds),
            average_fund_equity_ratio_basis_points=(
                value.average_fund_equity_ratio_basis_points
            ),
            tax_gain_or_loss=_money_wire(value.tax_gain_or_loss),
            exempt_gain=_money_wire(value.exempt_gain),
            taxable_gain=_money_wire(value.taxable_gain),
            non_deductible_loss=_money_wire(value.non_deductible_loss),
            deductible_loss=_money_wire(value.deductible_loss),
            created_by=UUID(str(value.created_by.subject)),
            created_at=value.created_at.value,
        )

    def investment_correction_wire(
        value: InvestmentCorrectionView,
    ) -> InvestmentCorrectionWire:
        return InvestmentCorrectionWire(
            id=UUID(str(value.correction_id)),
            company_id=UUID(str(value.company_id)),
            income_year=int(value.income_year),
            target_kind=value.target_kind,
            original_record_id=UUID(str(value.original_record_id)),
            original_activity_kind=value.original_activity_kind,
            reversal_accounting_entry_id=UUID(
                str(value.reversal_accounting_entry_id)
            ),
            replacement_record_id=UUID(str(value.replacement_record_id)),
            replacement_activity_kind=value.replacement_activity_kind,
            replacement_accounting_entry_id=UUID(
                str(value.replacement_accounting_entry_id)
            ),
            reason=value.reason,
            document_facts=[
                InvestmentFactReferenceWire(
                    capability=fact.capability,
                    record_id=UUID(str(fact.record_id)),
                    revision=fact.revision,
                    fact_sha256=fact.fact_sha256,
                )
                for fact in value.document_facts
            ],
            legacy_bank_transaction_id=(
                UUID(str(value.legacy_bank_transaction_id))
                if value.legacy_bank_transaction_id else None
            ),
            legacy_document_id=(
                UUID(str(value.legacy_document_id))
                if value.legacy_document_id else None
            ),
            legacy_document_status=value.legacy_document_status,
            legacy=value.legacy,
            evidence_mode=value.evidence_mode,
            evidence_reference=value.evidence_reference,
            evidence_digest=value.evidence_digest,
            owner_attested=value.owner_attested,
            created_by=UUID(str(value.created_by.subject)),
            created_at=value.created_at.value,
        )

    def investment_measurement_wire(
        value: InvestmentYearEndMeasurementView,
    ) -> InvestmentYearEndMeasurementViewWire:
        return InvestmentYearEndMeasurementViewWire(
            id=UUID(str(value.measurement_id)),
            company_id=UUID(str(value.company_id)),
            income_year=int(value.income_year),
            position_id=UUID(str(value.position_id)),
            as_of=value.as_of.value,
            measurement_rule=value.measurement_rule,
            quantity=format(value.quantity.amount, ".12f"),
            source_book_cost=_money_wire(value.source_book_cost),
            pre_measurement_book_value=_money_wire(
                value.pre_measurement_book_value
            ),
            observed_or_recoverable_value=_money_wire(
                value.observed_or_recoverable_value
            ),
            impairment_amount=_money_wire(value.impairment_amount),
            reversal_amount=_money_wire(value.reversal_amount),
            closing_book_value=_money_wire(value.closing_book_value),
            tax_basis=_money_wire(value.tax_basis),
            tax_value=_money_wire(value.tax_value),
            evidence_digest=value.evidence_digest,
            calculation_id=value.calculation_id,
            accounting_entry_id=(
                UUID(str(value.accounting_entry_id))
                if value.accounting_entry_id else None
            ),
            created_by=UUID(str(value.created_by.subject)),
            created_at=value.created_at.value,
        )

    @application.get(
        "/api/v1/investments/year-end-measurements",
        operation_id="investmentsListYearEndMeasurements",
        response_model=InvestmentYearEndMeasurementPageWire,
        responses={200: {"description": "Visible year-end investment measurements."} | investments_success}
        | investments_errors,
        tags=["investments"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def list_investment_year_end_measurements(
        request: Request,
        company_ids: Annotated[list[UUID], Query(alias="companyId", min_length=1, max_length=100)],
        cursor: str | None = Query(default=None, min_length=1, max_length=80),
        limit: int = Query(default=100, ge=1, le=100),
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> InvestmentYearEndMeasurementPageWire:
        async def execute() -> InvestmentYearEndMeasurementPageWire:
            session = await investments_application.session(bearer_token(credentials))
            page = await session.list_year_end_measurements(
                company_ids=tuple(
                    investments_input(lambda value=value: CompanyId(str(value)))
                    for value in company_ids
                ),
                correlation_id=CorrelationId(request.state.request_id),
                cursor=(investments_input(lambda: InvestmentCursor(cursor)) if cursor else None),
                limit=limit,
            )
            return InvestmentYearEndMeasurementPageWire(
                items=[investment_measurement_wire(item) for item in page.items],
                page=InvestmentsPageWire(
                    next_cursor=str(page.next_cursor) if page.next_cursor else None,
                    has_more=page.has_more,
                ),
            )
        return await investments_call(execute)

    @application.get(
        "/api/v1/investments/economic-events",
        operation_id="investmentsListEconomicEvents",
        response_model=InvestmentLifecycleEventPageWire,
        responses={
            200: {
                "description": (
                    "Visible investment economic events and settlement state."
                )
            }
            | investments_success
        }
        | investments_errors,
        tags=["investments"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def list_investment_economic_events(
        request: Request,
        company_ids: Annotated[
            list[UUID],
            Query(alias="companyId", min_length=1, max_length=100),
        ],
        cursor: str | None = Query(default=None, min_length=1, max_length=80),
        limit: int = Query(default=100, ge=1, le=100),
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> InvestmentLifecycleEventPageWire:
        async def execute() -> InvestmentLifecycleEventPageWire:
            session = await investments_application.session(
                bearer_token(credentials)
            )
            page = await session.list_lifecycle_events(
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
            return InvestmentLifecycleEventPageWire(
                items=[
                    investment_lifecycle_event_wire(item)
                    for item in page.items
                ],
                page=InvestmentsPageWire(
                    next_cursor=(
                        str(page.next_cursor) if page.next_cursor else None
                    ),
                    has_more=page.has_more,
                ),
            )

        return await investments_call(execute)

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

    @application.get(
        "/api/v1/investments/corrections",
        operation_id="investmentsListCorrections",
        response_model=InvestmentCorrectionPageWire,
        responses={
            200: {"description": "Visible immutable investment correction lineage."}
            | investments_success
        }
        | investments_errors,
        tags=["investments"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def list_investment_corrections(
        request: Request,
        company_ids: Annotated[
            list[UUID], Query(alias="companyId", min_length=1, max_length=100)
        ],
        cursor: str | None = Query(default=None, min_length=1, max_length=80),
        limit: int = Query(default=100, ge=1, le=100),
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> InvestmentCorrectionPageWire:
        async def execute() -> InvestmentCorrectionPageWire:
            session = await investments_application.session(bearer_token(credentials))
            page = await session.list_corrections(
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
            return InvestmentCorrectionPageWire(
                items=[investment_correction_wire(item) for item in page.items],
                page=InvestmentsPageWire(
                    next_cursor=str(page.next_cursor) if page.next_cursor else None,
                    has_more=page.has_more,
                ),
            )

        return await investments_call(execute)

    async def compatibility_bank_transaction(
        *,
        command,
        access_token: str,
        actor_id,
        correlation_id: CorrelationId,
    ) -> BankTransaction | None:
        if command.bank_transaction_id is None:
            return None
        return await resolve_investment_bank_transaction(
            access_token,
            actor_id=actor_id,
            company_id=CompanyId(str(command.company_id)),
            correlation_id=correlation_id,
            transaction_id=command.bank_transaction_id,
        )

    def compatibility_accounting_entry(event, settlement) -> UUID:
        reference = (
            settlement.settlement_accounting_entry_id
            if settlement is not None
            else event.recognition_accounting_entry_id
        )
        return UUID(str(reference))

    @application.post(
        "/api/v1/investments/share-purchases",
        operation_id="investmentsRecordSharePurchase",
        response_model=InvestmentsSharePurchaseResultWire,
        status_code=201,
        deprecated=True,
        responses={
            201: {"description": "Share purchase recorded through lifecycle compatibility."}
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
        async def execute() -> InvestmentsSharePurchaseResultWire:
            access_token = bearer_token(credentials)
            correlation_id = CorrelationId(request.state.request_id)
            session = await investments_session_with_bank_validation(credentials)
            bank = await compatibility_bank_transaction(
                command=command,
                access_token=access_token,
                actor_id=session.actor_id,
                correlation_id=correlation_id,
            )
            result = await session.record_legacy_action(LegacySharePurchase(
                company_id=CompanyId(str(command.company_id)),
                correlation_id=correlation_id,
                idempotency_key=IdempotencyKey(idempotency_key),
                income_year=IncomeYear(command.income_year),
                event_id=InvestmentEconomicEventId(str(command.action_id)),
                investment_key=command.investment_key,
                investment_name=command.investment_name,
                investment_kind=command.investment_kind,
                accounting_classification=command.accounting_classification,
                tax_treatment=command.tax_treatment,
                acquisition_date=LocalDate(command.acquisition_date),
                share_count=InvestmentUnits.of(str(command.share_count)),
                purchase_amount=command.purchase_amount.to_domain(),
                transaction_costs=command.transaction_costs.to_domain(),
                org_number=command.org_number,
                fund_equity_ratio_basis_points=command.fund_equity_ratio_basis_points,
                fund_tax_statement_reference=command.fund_tax_statement_reference,
                trading_profile=command.trading_profile,
                non_active_trading_confirmed=command.non_active_trading_confirmed,
                share_class_code=command.share_class_code,
                single_share_class_confirmed=command.single_share_class_confirmed,
                equal_share_rights_confirmed=command.equal_share_rights_confirmed,
                unusual_share_rights_absent_confirmed=(
                    command.unusual_share_rights_absent_confirmed
                ),
                evidence=LegacyInvestmentEvidence(
                    mode=command.evidence_mode,
                    reference=command.evidence_reference,
                    owner_attested=command.owner_attested,
                    document_id=(
                        InvestmentSourceReference(str(command.document_id))
                        if command.document_id else None
                    ),
                    document_status=command.document_status,
                ),
            ), bank)
            view = result.lifecycle
            if view.acquisition_lot_id is None or view.position_created is None:
                raise InvestmentsError.unavailable()
            return InvestmentsSharePurchaseResultWire(
                action_id=command.action_id,
                position_id=UUID(str(view.position_id)),
                acquisition_lot_id=UUID(str(view.acquisition_lot_id)),
                accounting_entry_id=compatibility_accounting_entry(
                    result.event, result.settlement
                ),
                position_created=view.position_created,
                replayed=result.event.replayed and (
                    result.settlement is None or result.settlement.replayed
                ),
            )

        return await investments_call(execute)

    @application.post(
        "/api/v1/investments/share-sales",
        operation_id="investmentsRecordShareSale",
        response_model=InvestmentsShareSaleResultWire,
        status_code=201,
        deprecated=True,
        responses={
            201: {"description": "Share sale recorded through lifecycle compatibility."}
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
            access_token = bearer_token(credentials)
            correlation_id = CorrelationId(request.state.request_id)
            session = await investments_session_with_bank_validation(credentials)
            bank = await compatibility_bank_transaction(
                command=command, access_token=access_token,
                actor_id=session.actor_id, correlation_id=correlation_id,
            )
            result = await session.record_legacy_action(LegacyShareSale(
                company_id=CompanyId(str(command.company_id)),
                correlation_id=correlation_id,
                idempotency_key=IdempotencyKey(idempotency_key),
                income_year=IncomeYear(command.income_year),
                event_id=InvestmentEconomicEventId(str(command.action_id)),
                position_id=InvestmentPositionId(str(command.position_id)),
                sale_date=LocalDate(command.sale_date),
                sold_share_count=InvestmentUnits.of(str(command.sold_share_count)),
                proceeds=command.proceeds.to_domain(),
                transaction_costs=command.transaction_costs.to_domain(),
                sale_year_fund_equity_ratio_basis_points=(
                    command.sale_year_fund_equity_ratio_basis_points
                ),
                fund_tax_statement_reference=command.fund_tax_statement_reference,
                evidence=LegacyInvestmentEvidence(
                    mode=command.evidence_mode,
                    reference=command.evidence_reference,
                    owner_attested=command.owner_attested,
                    document_id=(
                        InvestmentSourceReference(str(command.document_id))
                        if command.document_id else None
                    ),
                    document_status=command.document_status,
                ),
            ), bank)
            return InvestmentsShareSaleResultWire(
                action_id=command.action_id,
                position_id=UUID(str(result.event.position_id)),
                accounting_entry_id=compatibility_accounting_entry(
                    result.event, result.settlement
                ),
                replayed=result.event.replayed and (
                    result.settlement is None or result.settlement.replayed
                ),
            )

        return await investments_call(execute)

    @application.post(
        "/api/v1/investments/received-dividends",
        operation_id="investmentsRecordReceivedDividend",
        response_model=InvestmentsReceivedDividendResultWire,
        status_code=201,
        deprecated=True,
        responses={
            201: {"description": "Dividend recorded through lifecycle compatibility."}
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
            access_token = bearer_token(credentials)
            correlation_id = CorrelationId(request.state.request_id)
            session = await investments_session_with_bank_validation(credentials)
            bank = await compatibility_bank_transaction(
                command=command, access_token=access_token,
                actor_id=session.actor_id, correlation_id=correlation_id,
            )
            result = await session.record_legacy_action(LegacyReceivedDividend(
                company_id=CompanyId(str(command.company_id)),
                correlation_id=correlation_id,
                idempotency_key=IdempotencyKey(idempotency_key),
                income_year=IncomeYear(command.income_year),
                event_id=InvestmentEconomicEventId(str(command.action_id)),
                position_id=InvestmentPositionId(str(command.position_id)),
                paying_company_name=command.paying_company_name,
                declared_date=LocalDate(command.declared_date),
                paid_date=LocalDate(command.paid_date),
                gross_amount=command.gross_amount.to_domain(),
                tax_treatment=command.tax_treatment,
                lawful_dividend_confirmed=command.lawful_dividend_confirmed,
                group_exception_claimed=command.group_exception_claimed,
                year_end_ownership_basis_points=command.year_end_ownership_basis_points,
                year_end_voting_basis_points=command.year_end_voting_basis_points,
                group_evidence_reference=command.group_evidence_reference,
                evidence=LegacyInvestmentEvidence(
                    mode=command.evidence_mode,
                    reference=command.evidence_reference,
                    owner_attested=command.owner_attested,
                    document_id=(
                        InvestmentSourceReference(str(command.document_id))
                        if command.document_id else None
                    ),
                    document_status=command.document_status,
                ),
            ), bank)
            view = result.lifecycle
            if view.taxable_add_back is None:
                raise InvestmentsError.unavailable()
            return InvestmentsReceivedDividendResultWire(
                action_id=command.action_id,
                position_id=UUID(str(result.event.position_id)),
                accounting_entry_id=compatibility_accounting_entry(
                    result.event, result.settlement
                ),
                taxable_add_back=_money_wire(view.taxable_add_back),
                replayed=result.event.replayed and (
                    result.settlement is None or result.settlement.replayed
                ),
            )

        return await investments_call(execute)

    @application.post(
        "/api/v1/investments/received-fund-distributions",
        operation_id="investmentsRecordReceivedFundDistribution",
        response_model=InvestmentsReceivedFundDistributionResultWire,
        status_code=201,
        deprecated=True,
        responses={
            201: {"description": "Fund distribution recorded through lifecycle compatibility."}
            | investments_success
        }
        | investments_errors,
        tags=["investments"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def record_investments_received_fund_distribution(
        request: Request,
        command: InvestmentsReceivedFundDistributionWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> InvestmentsReceivedFundDistributionResultWire:
        async def execute() -> InvestmentsReceivedFundDistributionResultWire:
            access_token = bearer_token(credentials)
            correlation_id = CorrelationId(request.state.request_id)
            session = await investments_session_with_bank_validation(credentials)
            bank = await compatibility_bank_transaction(
                command=command, access_token=access_token,
                actor_id=session.actor_id, correlation_id=correlation_id,
            )
            result = await session.record_legacy_action(
                LegacyReceivedFundDistribution(
                company_id=CompanyId(str(command.company_id)),
                correlation_id=correlation_id,
                idempotency_key=IdempotencyKey(idempotency_key),
                income_year=IncomeYear(command.income_year),
                event_id=InvestmentEconomicEventId(str(command.action_id)),
                position_id=InvestmentPositionId(str(command.position_id)),
                fund_name=command.fund_name,
                entitlement_date=LocalDate(command.entitlement_date),
                paid_date=LocalDate(command.paid_date),
                gross_amount=command.gross_amount.to_domain(),
                opening_fund_equity_ratio_basis_points=(
                    command.opening_fund_equity_ratio_basis_points
                ),
                fund_tax_statement_reference=command.fund_tax_statement_reference,
                evidence=LegacyInvestmentEvidence(
                    mode=command.evidence_mode,
                    reference=command.evidence_reference,
                    owner_attested=command.owner_attested,
                    document_id=(
                        InvestmentSourceReference(str(command.document_id))
                        if command.document_id else None
                    ),
                    document_status=command.document_status,
                ),
            ),
                bank,
            )
            view = result.lifecycle
            if (
                view.dividend_portion is None
                or view.interest_portion is None
                or view.taxable_add_back is None
                or view.total_taxable_income is None
            ):
                raise InvestmentsError.unavailable()
            return InvestmentsReceivedFundDistributionResultWire(
                action_id=command.action_id,
                position_id=UUID(str(result.event.position_id)),
                accounting_entry_id=compatibility_accounting_entry(
                    result.event, result.settlement
                ),
                dividend_portion=_money_wire(view.dividend_portion),
                interest_portion=_money_wire(view.interest_portion),
                taxable_add_back=_money_wire(view.taxable_add_back),
                total_taxable_income=_money_wire(view.total_taxable_income),
                replayed=result.event.replayed and (
                    result.settlement is None or result.settlement.replayed
                ),
            )

        return await investments_call(execute)

    def economic_event_result_wire(result) -> InvestmentsEconomicEventResultWire:
        return InvestmentsEconomicEventResultWire(
            event_id=UUID(str(result.event_id)),
            position_id=UUID(str(result.position_id)),
            recognition_accounting_entry_id=UUID(
                str(result.recognition_accounting_entry_id)
            ),
            expected_settlement_amount=_money_wire(
                result.expected_settlement_amount
            ),
            settlement_balance_kind=result.settlement_balance_kind,
            replayed=result.replayed,
        )

    @application.post(
        "/api/v1/investments/share-purchase-recognitions",
        operation_id="investmentsRecognizeSharePurchase",
        response_model=InvestmentsEconomicEventResultWire,
        status_code=201,
        responses={
            201: {"description": "Share purchase recognized without cash settlement."}
            | investments_success
        }
        | investments_errors,
        tags=["investments"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def recognize_investments_share_purchase(
        request: Request,
        command: InvestmentsRecognizeSharePurchaseWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> InvestmentsEconomicEventResultWire:
        async def execute() -> InvestmentsEconomicEventResultWire:
            session = await investments_application.session(bearer_token(credentials))
            result = await session.recognize_share_purchase(
                RecognizeSharePurchaseCommand(
                    company_id=CompanyId(str(command.company_id)),
                    actor_id=session.actor_id,
                    correlation_id=CorrelationId(request.state.request_id),
                    idempotency_key=IdempotencyKey(idempotency_key),
                    income_year=IncomeYear(command.income_year),
                    event_id=InvestmentEconomicEventId(str(command.event_id)),
                    investment_key=command.investment_key,
                    investment_name=command.investment_name,
                    investment_kind=command.investment_kind,
                    accounting_classification=command.accounting_classification,
                    acquisition_date=LocalDate(command.acquisition_date),
                    share_count=InvestmentUnits.of(command.share_count),
                    purchase_amount=command.purchase_amount.to_domain(),
                    transaction_costs=command.transaction_costs.to_domain(),
                    org_number=command.org_number,
                    fund_equity_ratio_basis_points=(
                        command.fund_equity_ratio_basis_points
                    ),
                    fund_tax_statement_reference=(
                        command.fund_tax_statement_reference
                    ),
                    trading_profile=command.trading_profile,
                    non_active_trading_confirmed=(
                        command.non_active_trading_confirmed
                    ),
                    share_class_code=command.share_class_code,
                    single_share_class_confirmed=(
                        command.single_share_class_confirmed
                    ),
                    equal_share_rights_confirmed=(
                        command.equal_share_rights_confirmed
                    ),
                    unusual_share_rights_absent_confirmed=(
                        command.unusual_share_rights_absent_confirmed
                    ),
                    evidence=command.evidence_domain(),
                )
            )
            return economic_event_result_wire(result)

        return await investments_call(execute)

    @application.post(
        "/api/v1/investments/share-sale-recognitions",
        operation_id="investmentsRecognizeShareSale",
        response_model=InvestmentsEconomicEventResultWire,
        status_code=201,
        responses={
            201: {"description": "Share sale recognized without cash settlement."}
            | investments_success
        }
        | investments_errors,
        tags=["investments"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def recognize_investments_share_sale(
        request: Request,
        command: InvestmentsRecognizeShareSaleWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> InvestmentsEconomicEventResultWire:
        async def execute() -> InvestmentsEconomicEventResultWire:
            session = await investments_application.session(bearer_token(credentials))
            result = await session.recognize_share_sale(
                RecognizeShareSaleCommand(
                    company_id=CompanyId(str(command.company_id)),
                    actor_id=session.actor_id,
                    correlation_id=CorrelationId(request.state.request_id),
                    idempotency_key=IdempotencyKey(idempotency_key),
                    income_year=IncomeYear(command.income_year),
                    event_id=InvestmentEconomicEventId(str(command.event_id)),
                    position_id=InvestmentPositionId(str(command.position_id)),
                    sale_date=LocalDate(command.sale_date),
                    sold_share_count=InvestmentUnits.of(command.sold_share_count),
                    proceeds=command.proceeds.to_domain(),
                    transaction_costs=command.transaction_costs.to_domain(),
                    sale_year_fund_equity_ratio_basis_points=(
                        command.sale_year_fund_equity_ratio_basis_points
                    ),
                    fund_tax_statement_reference=(
                        command.fund_tax_statement_reference
                    ),
                    evidence=command.evidence_domain(),
                )
            )
            return economic_event_result_wire(result)

        return await investments_call(execute)

    @application.post(
        "/api/v1/investments/received-dividend-recognitions",
        operation_id="investmentsRecognizeReceivedDividend",
        response_model=InvestmentsEconomicEventResultWire,
        status_code=201,
        responses={
            201: {"description": "Received dividend recognized without cash settlement."}
            | investments_success
        }
        | investments_errors,
        tags=["investments"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def recognize_investments_received_dividend(
        request: Request,
        command: InvestmentsRecognizeReceivedDividendWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> InvestmentsEconomicEventResultWire:
        async def execute() -> InvestmentsEconomicEventResultWire:
            session = await investments_application.session(bearer_token(credentials))
            result = await session.recognize_received_dividend(
                RecognizeReceivedDividendCommand(
                    company_id=CompanyId(str(command.company_id)),
                    actor_id=session.actor_id,
                    correlation_id=CorrelationId(request.state.request_id),
                    idempotency_key=IdempotencyKey(idempotency_key),
                    income_year=IncomeYear(command.income_year),
                    event_id=InvestmentEconomicEventId(str(command.event_id)),
                    position_id=InvestmentPositionId(str(command.position_id)),
                    paying_company_name=command.paying_company_name,
                    declared_date=LocalDate(command.declared_date),
                    gross_amount=command.gross_amount.to_domain(),
                    lawful_dividend_confirmed=command.lawful_dividend_confirmed,
                    group_exception_claimed=command.group_exception_claimed,
                    year_end_ownership_basis_points=(
                        command.year_end_ownership_basis_points
                    ),
                    year_end_voting_basis_points=(
                        command.year_end_voting_basis_points
                    ),
                    group_evidence_reference=command.group_evidence_reference,
                    evidence=command.evidence_domain(),
                )
            )
            return economic_event_result_wire(result)

        return await investments_call(execute)

    @application.post(
        "/api/v1/investments/received-fund-distribution-recognitions",
        operation_id="investmentsRecognizeReceivedFundDistribution",
        response_model=InvestmentsEconomicEventResultWire,
        status_code=201,
        responses={
            201: {"description": "Fund distribution recognized without cash settlement."}
            | investments_success
        }
        | investments_errors,
        tags=["investments"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def recognize_investments_received_fund_distribution(
        request: Request,
        command: InvestmentsRecognizeReceivedFundDistributionWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> InvestmentsEconomicEventResultWire:
        async def execute() -> InvestmentsEconomicEventResultWire:
            session = await investments_application.session(bearer_token(credentials))
            result = await session.recognize_received_fund_distribution(
                RecognizeReceivedFundDistributionCommand(
                    company_id=CompanyId(str(command.company_id)),
                    actor_id=session.actor_id,
                    correlation_id=CorrelationId(request.state.request_id),
                    idempotency_key=IdempotencyKey(idempotency_key),
                    income_year=IncomeYear(command.income_year),
                    event_id=InvestmentEconomicEventId(str(command.event_id)),
                    position_id=InvestmentPositionId(str(command.position_id)),
                    fund_name=command.fund_name,
                    entitlement_date=LocalDate(command.entitlement_date),
                    gross_amount=command.gross_amount.to_domain(),
                    opening_fund_equity_ratio_basis_points=(
                        command.opening_fund_equity_ratio_basis_points
                    ),
                    fund_tax_statement_reference=(
                        command.fund_tax_statement_reference
                    ),
                    evidence=command.evidence_domain(),
                )
            )
            return economic_event_result_wire(result)

        return await investments_call(execute)

    @application.post(
        "/api/v1/investments/cash-settlements",
        operation_id="investmentsSettleCash",
        response_model=InvestmentsCashSettlementResultWire,
        status_code=201,
        responses={
            201: {"description": "Investment cash settled against a recognition."}
            | investments_success
        }
        | investments_errors,
        tags=["investments"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def settle_investments_cash(
        request: Request,
        command: InvestmentsSettleCashWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> InvestmentsCashSettlementResultWire:
        async def execute() -> InvestmentsCashSettlementResultWire:
            session = await investments_session_with_bank_validation(credentials)
            result = await session.settle_investment_cash(
                SettleInvestmentCashCommand(
                    company_id=CompanyId(str(command.company_id)),
                    actor_id=session.actor_id,
                    correlation_id=CorrelationId(request.state.request_id),
                    idempotency_key=IdempotencyKey(idempotency_key),
                    income_year=IncomeYear(command.income_year),
                    settlement_id=InvestmentSettlementId(str(command.settlement_id)),
                    event_id=InvestmentEconomicEventId(str(command.event_id)),
                    settlement_date=LocalDate(command.settlement_date),
                    amount=command.amount.to_domain(),
                    evidence=command.evidence_domain(),
                )
            )
            return InvestmentsCashSettlementResultWire(
                settlement_id=UUID(str(result.settlement_id)),
                event_id=UUID(str(result.event_id)),
                settlement_accounting_entry_id=UUID(
                    str(result.settlement_accounting_entry_id)
                ),
                replayed=result.replayed,
            )

        return await investments_call(execute)

    @application.post(
        "/api/v1/investments/year-end-measurements",
        operation_id="investmentsRecordYearEndMeasurement",
        response_model=InvestmentsYearEndMeasurementResultWire,
        status_code=201,
        responses={
            201: {"description": "Investment year-end measurement recorded."}
            | investments_success
        }
        | investments_errors,
        tags=["investments"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def record_investments_year_end_measurement(
        request: Request,
        command: InvestmentsYearEndMeasurementWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> InvestmentsYearEndMeasurementResultWire:
        async def execute() -> InvestmentsYearEndMeasurementResultWire:
            session = await investments_application.session(bearer_token(credentials))
            result = await session.record_year_end_measurement(
                RecordInvestmentYearEndMeasurementCommand(
                    company_id=CompanyId(str(command.company_id)),
                    actor_id=session.actor_id,
                    correlation_id=CorrelationId(request.state.request_id),
                    idempotency_key=IdempotencyKey(idempotency_key),
                    income_year=IncomeYear(command.income_year),
                    measurement_id=InvestmentMeasurementId(
                        str(command.measurement_id)
                    ),
                    position_id=InvestmentPositionId(str(command.position_id)),
                    as_of=LocalDate(command.as_of),
                    observed_or_recoverable_value=(
                        command.observed_or_recoverable_value.to_domain()
                    ),
                    tax_value=command.tax_value.to_domain(),
                    evidence=command.evidence_domain(),
                )
            )
            return InvestmentsYearEndMeasurementResultWire(
                measurement_id=UUID(str(result.measurement_id)),
                position_id=UUID(str(result.position_id)),
                accounting_entry_id=(
                    UUID(str(result.accounting_entry_id))
                    if result.accounting_entry_id else None
                ),
                measurement_rule=result.measurement_rule,
                closing_book_value=_money_wire(result.closing_book_value),
                tax_basis=_money_wire(result.tax_basis),
                tax_value=_money_wire(result.tax_value),
                replayed=result.replayed,
            )
        return await investments_call(execute)

    @application.post(
        "/api/v1/investments/corrections",
        operation_id="investmentsCorrectInvestment",
        response_model=InvestmentsCorrectionResultWire,
        status_code=201,
        responses={
            201: {"description": "Investment corrected by linked reversal and replacement."}
            | investments_success
        }
        | investments_errors,
        tags=["investments"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def correct_investment(
        request: Request,
        command: InvestmentsCorrectionWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> InvestmentsCorrectionResultWire:
        async def execute() -> InvestmentsCorrectionResultWire:
            session = await investments_session_with_bank_validation(credentials)
            replacement_wire = command.replacement
            replacement_record_id = (
                replacement_wire.settlement_id
                if isinstance(replacement_wire, InvestmentsCashSettlementWire)
                else replacement_wire.event_id
            )
            common = {
                "company_id": CompanyId(str(replacement_wire.company_id)),
                "actor_id": session.actor_id,
                "correlation_id": CorrelationId(
                    f"investment-replacement:{replacement_record_id}"
                ),
                "idempotency_key": IdempotencyKey(
                    f"replacement:{replacement_record_id}"
                ),
                "income_year": IncomeYear(replacement_wire.income_year),
                "evidence": replacement_wire.evidence_domain(),
            }
            if isinstance(
                replacement_wire, InvestmentsSharePurchaseRecognitionWire
            ):
                replacement = RecognizeSharePurchaseCommand(
                    **common,
                    event_id=InvestmentEconomicEventId(
                        str(replacement_wire.event_id)
                    ),
                    investment_key=replacement_wire.investment_key,
                    investment_name=replacement_wire.investment_name,
                    investment_kind=replacement_wire.investment_kind,
                    accounting_classification=(
                        replacement_wire.accounting_classification
                    ),
                    acquisition_date=LocalDate(replacement_wire.acquisition_date),
                    share_count=InvestmentUnits.of(replacement_wire.share_count),
                    purchase_amount=replacement_wire.purchase_amount.to_domain(),
                    transaction_costs=(
                        replacement_wire.transaction_costs.to_domain()
                    ),
                    org_number=replacement_wire.org_number,
                    fund_equity_ratio_basis_points=(
                        replacement_wire.fund_equity_ratio_basis_points
                    ),
                    fund_tax_statement_reference=(
                        replacement_wire.fund_tax_statement_reference
                    ),
                    trading_profile=replacement_wire.trading_profile,
                    non_active_trading_confirmed=(
                        replacement_wire.non_active_trading_confirmed
                    ),
                    share_class_code=replacement_wire.share_class_code,
                    single_share_class_confirmed=(
                        replacement_wire.single_share_class_confirmed
                    ),
                    equal_share_rights_confirmed=(
                        replacement_wire.equal_share_rights_confirmed
                    ),
                    unusual_share_rights_absent_confirmed=(
                        replacement_wire.unusual_share_rights_absent_confirmed
                    ),
                )
            elif isinstance(
                replacement_wire, InvestmentsShareSaleRecognitionWire
            ):
                replacement = RecognizeShareSaleCommand(
                    **common,
                    event_id=InvestmentEconomicEventId(
                        str(replacement_wire.event_id)
                    ),
                    position_id=InvestmentPositionId(
                        str(replacement_wire.position_id)
                    ),
                    sale_date=LocalDate(replacement_wire.sale_date),
                    sold_share_count=InvestmentUnits.of(
                        replacement_wire.sold_share_count
                    ),
                    proceeds=replacement_wire.proceeds.to_domain(),
                    transaction_costs=(
                        replacement_wire.transaction_costs.to_domain()
                    ),
                    sale_year_fund_equity_ratio_basis_points=(
                        replacement_wire.sale_year_fund_equity_ratio_basis_points
                    ),
                    fund_tax_statement_reference=(
                        replacement_wire.fund_tax_statement_reference
                    ),
                )
            elif isinstance(replacement_wire, InvestmentsDividendRecognitionWire):
                replacement = RecognizeReceivedDividendCommand(
                    **common,
                    event_id=InvestmentEconomicEventId(
                        str(replacement_wire.event_id)
                    ),
                    position_id=InvestmentPositionId(
                        str(replacement_wire.position_id)
                    ),
                    paying_company_name=replacement_wire.paying_company_name,
                    declared_date=LocalDate(replacement_wire.declared_date),
                    gross_amount=replacement_wire.gross_amount.to_domain(),
                    lawful_dividend_confirmed=(
                        replacement_wire.lawful_dividend_confirmed
                    ),
                    group_exception_claimed=(
                        replacement_wire.group_exception_claimed
                    ),
                    year_end_ownership_basis_points=(
                        replacement_wire.year_end_ownership_basis_points
                    ),
                    year_end_voting_basis_points=(
                        replacement_wire.year_end_voting_basis_points
                    ),
                    group_evidence_reference=(
                        replacement_wire.group_evidence_reference
                    ),
                )
            elif isinstance(
                replacement_wire, InvestmentsFundDistributionRecognitionWire
            ):
                replacement = RecognizeReceivedFundDistributionCommand(
                    **common,
                    event_id=InvestmentEconomicEventId(
                        str(replacement_wire.event_id)
                    ),
                    position_id=InvestmentPositionId(
                        str(replacement_wire.position_id)
                    ),
                    fund_name=replacement_wire.fund_name,
                    entitlement_date=LocalDate(replacement_wire.entitlement_date),
                    gross_amount=replacement_wire.gross_amount.to_domain(),
                    opening_fund_equity_ratio_basis_points=(
                        replacement_wire.opening_fund_equity_ratio_basis_points
                    ),
                    fund_tax_statement_reference=(
                        replacement_wire.fund_tax_statement_reference
                    ),
                )
            else:
                replacement = SettleInvestmentCashCommand(
                    **common,
                    settlement_id=InvestmentSettlementId(
                        str(replacement_wire.settlement_id)
                    ),
                    event_id=InvestmentEconomicEventId(
                        str(replacement_wire.event_id)
                    ),
                    settlement_date=LocalDate(replacement_wire.settlement_date),
                    amount=replacement_wire.amount.to_domain(),
                )
            original_record_id = (
                InvestmentEconomicEventId(str(command.original_record_id))
                if command.target_kind
                is InvestmentCorrectionTargetKind.ECONOMIC_EVENT
                else InvestmentSettlementId(str(command.original_record_id))
            )
            domain = CorrectInvestmentCommand(
                company_id=CompanyId(str(command.company_id)),
                actor_id=session.actor_id,
                correlation_id=CorrelationId(request.state.request_id),
                idempotency_key=IdempotencyKey(idempotency_key),
                income_year=IncomeYear(command.income_year),
                correction_id=InvestmentCorrectionId(str(command.correction_id)),
                target_kind=command.target_kind,
                original_record_id=original_record_id,
                original_activity_kind=command.original_activity_kind,
                correction_date=LocalDate(command.correction_date),
                reason=command.reason,
                evidence=command.evidence_domain(),
                replacement=replacement,
            )
            if command.replacement_settlement is None:
                result = await session.correct_investment(domain)
            else:
                settlement_wire = command.replacement_settlement
                if (
                    command.original_settlement_id is None
                    or command.settlement_correction_id is None
                ):
                    raise InvestmentsError.invalid_input()
                settlement_replacement = SettleInvestmentCashCommand(
                    company_id=CompanyId(str(settlement_wire.company_id)),
                    actor_id=session.actor_id,
                    correlation_id=CorrelationId(
                        f"investment-replacement:{settlement_wire.settlement_id}"
                    ),
                    idempotency_key=IdempotencyKey(
                        f"replacement:{settlement_wire.settlement_id}"
                    ),
                    income_year=IncomeYear(settlement_wire.income_year),
                    settlement_id=InvestmentSettlementId(
                        str(settlement_wire.settlement_id)
                    ),
                    event_id=InvestmentEconomicEventId(
                        str(settlement_wire.event_id)
                    ),
                    settlement_date=LocalDate(settlement_wire.settlement_date),
                    amount=settlement_wire.amount.to_domain(),
                    evidence=settlement_wire.evidence_domain(),
                )
                settlement_domain = CorrectInvestmentCommand(
                    company_id=domain.company_id,
                    actor_id=domain.actor_id,
                    correlation_id=CorrelationId(
                        f"{request.state.request_id}:settlement"
                    ),
                    idempotency_key=IdempotencyKey(
                        str(command.settlement_correction_id)
                    ),
                    income_year=domain.income_year,
                    correction_id=InvestmentCorrectionId(
                        str(command.settlement_correction_id)
                    ),
                    target_kind=InvestmentCorrectionTargetKind.CASH_SETTLEMENT,
                    original_record_id=InvestmentSettlementId(
                        str(command.original_settlement_id)
                    ),
                    original_activity_kind=domain.original_activity_kind,
                    correction_date=domain.correction_date,
                    reason=domain.reason,
                    evidence=domain.evidence,
                    replacement=settlement_replacement,
                )
                result = await session.correct_settled_investment(
                    domain, settlement_domain
                )
            return InvestmentsCorrectionResultWire(
                correction_id=UUID(str(result.correction_id)),
                target_kind=result.target_kind,
                original_record_id=UUID(str(result.original_record_id)),
                replacement_record_id=UUID(str(result.replacement_record_id)),
                reversal_accounting_entry_id=UUID(
                    str(result.reversal_accounting_entry_id)
                ),
                replacement_accounting_entry_id=UUID(
                    str(result.replacement_accounting_entry_id)
                ),
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
            snapshots: OpeningSnapshotPage = await session.list_opening_snapshots(
                actor_id=session.actor_id,
                company_ids=ledger_input(
                    lambda: tuple(CompanyId(str(value)) for value in company_id)
                ),
                correlation_id=ledger_correlation(request),
                cursor=(
                    ledger_input(lambda: OpeningSnapshotCursor(cursor))
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
        "/api/v1/ledger/opening-snapshots/by-year",
        operation_id="ledgerListOpeningSnapshotsForYear",
        response_model=LedgerOpeningSnapshotPageWire,
        responses={200: {"description": "Authorized opening source for one company-year."} | ledger_success}
        | ledger_errors,
        tags=["ledger"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def list_opening_snapshots_for_year(
        request: Request,
        company_id: Annotated[UUID, Query(alias="companyId")],
        income_year: Annotated[int, Query(alias="incomeYear", ge=2000, le=2100)],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> LedgerOpeningSnapshotPageWire:
        async def execute() -> LedgerOpeningSnapshotPageWire:
            session = await ledger_application.session(bearer_token(credentials))
            snapshots = await session.list_opening_snapshots_for_year(
                actor_id=session.actor_id,
                company_id=CompanyId(str(company_id)),
                income_year=IncomeYear(income_year),
                correlation_id=ledger_correlation(request),
            )
            if (snapshots.has_more or snapshots.next_cursor is not None or len(snapshots.items) > 1
                    or any(str(item.company_id) != str(company_id) or item.income_year.value != income_year
                           for item in snapshots.items)):
                raise LedgerError.unavailable()
            return LedgerOpeningSnapshotPageWire(
                items=[_opening_snapshot_wire(item) for item in snapshots.items],
                next_cursor=None,
                has_more=False,
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
            session = await company_tax_application.session(bearer_token(credentials))
            domain = ledger_input(lambda: RecordTaxSettlementCommand(
                company_id=CompanyId(str(command.company_id)), actor_id=session.actor_id,
                correlation_id=ledger_correlation(request), idempotency_key=IdempotencyKey(idempotency_key),
                income_year=IncomeYear(command.income_year), action_id=TaxSettlementId(str(command.action_id)),
                settlement_date=LocalDate(command.settlement_date), amount=command.amount.to_domain(),
                settlement_kind=CompanyTaxSettlementKind(command.settlement_kind), document_status=TaxSettlementDocumentStatus(command.document_status),
                bank_transaction_id=(BankTransactionReference(str(command.bank_transaction_id)) if command.bank_transaction_id else None),
                document_id=(DocumentReference(str(command.document_id)) if command.document_id else None),
            ))
            result = await session.record_tax_settlement(domain)
            return ledger_writer_wire(
                result, company_id=command.company_id, income_year=command.income_year,
                expected_kind=LedgerEntryKind.TAX_SETTLEMENT,
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

    documents_errors: Any = {
        status: {
            "description": "Document request failed.",
            "headers": {"X-Request-ID": REQUEST_ID_HEADER},
            "content": {
                "application/problem+json": {
                    "schema": ProblemDetails.model_json_schema(by_alias=True)
                }
            },
        }
        for status in (401, 403, 404, 409, 422, 503)
    }
    documents_success: dict[str, Any] = {
        "headers": {"X-Request-ID": REQUEST_ID_HEADER}
    }

    @application.post(
        "/api/v1/documents/uploads",
        operation_id="documentsBeginUpload",
        response_model=DocumentUploadTransferWire,
        status_code=201,
        responses={201: {"description": "Exact signed upload transfer staged."} | documents_success}
        | documents_errors,
        tags=["documents"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def begin_document_upload(
        command: DocumentBeginUploadWire,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> DocumentUploadTransferWire:
        async def execute() -> DocumentUploadTransferWire:
            try:
                header = b64decode(command.header_base64, validate=True)
            except (Base64Error, ValueError):
                raise DocumentsError.invalid_input() from None
            session = await documents_application.session(bearer_token(credentials))
            result = await session.begin_upload(
                BeginDocumentUploadCommand(
                    company_id=CompanyId(str(command.company_id)),
                    income_year=IncomeYear(command.income_year),
                    document_id=DocumentId(str(command.document_id)),
                    document_type=command.document_type,
                    linked_to=command.linked_to,
                    file_name=command.file_name,
                    content_type=command.content_type,
                    byte_length=command.byte_length,
                    header=header,
                    final_status=DocumentStatus(command.final_status),
                )
            )
            return _document_upload_transfer_wire(result)

        return await documents_call(execute)

    @application.post(
        "/api/v1/documents/{document_id}/finalize",
        operation_id="documentsFinalizeUpload",
        response_model=DocumentWire,
        responses={200: {"description": "Uploaded object verified and finalized."} | documents_success}
        | documents_errors,
        tags=["documents"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def finalize_document_upload(
        document_id: UUID,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> DocumentWire:
        async def execute() -> DocumentWire:
            session = await documents_application.session(bearer_token(credentials))
            return _document_wire(await session.finalize_upload(DocumentId(str(document_id))))

        return await documents_call(execute)

    @application.get(
        "/api/v1/documents",
        operation_id="documentsList",
        response_model=DocumentListWire,
        responses={200: {"description": "Visible accounting documents."} | documents_success}
        | documents_errors,
        tags=["documents"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def list_documents(
        company_ids: Annotated[list[UUID], Query(alias="companyId", min_length=1, max_length=100)],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> DocumentListWire:
        async def execute() -> DocumentListWire:
            session = await documents_application.session(bearer_token(credentials))
            values = await session.list_documents(tuple(CompanyId(str(value)) for value in company_ids))
            return DocumentListWire(documents=[_document_wire(value) for value in values])

        return await documents_call(execute)

    @application.post(
        "/api/v1/documents/{document_id}/transfers",
        operation_id="documentsCreateTransfer",
        response_model=DocumentTransferWire,
        responses={200: {"description": "Integrity-checked exact-object transfer."} | documents_success}
        | documents_errors,
        tags=["documents"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def create_document_transfer(
        document_id: UUID,
        command: DocumentTransferRequestWire,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> DocumentTransferWire:
        async def execute() -> DocumentTransferWire:
            session = await documents_application.session(bearer_token(credentials))
            return _document_transfer_wire(
                await session.create_transfer(DocumentId(str(document_id)), command.kind)
            )

        return await documents_call(execute)

    @application.post(
        "/api/v1/documents/{document_id}/remove",
        operation_id="documentsRemove",
        response_model=DocumentWire,
        responses={200: {"description": "Unlinked document safely removed."} | documents_success}
        | documents_errors,
        tags=["documents"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def remove_document(
        document_id: UUID,
        command: DocumentRemovalRequestWire,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> DocumentWire:
        async def execute() -> DocumentWire:
            session = await documents_application.session(bearer_token(credentials))
            return _document_wire(
                await session.remove_document(DocumentId(str(document_id)), reason=command.reason)
            )

        return await documents_call(execute)

    @application.get(
        "/api/v1/documents/backup-projection",
        operation_id="documentsBackupProjection",
        response_model=DocumentBackupProjectionWire,
        responses={200: {"description": "Document-owned backup object projection."} | documents_success}
        | documents_errors,
        tags=["documents"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def document_backup_projection(
        company_id: UUID,
        income_year: int = Query(ge=2000, le=2100),
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> DocumentBackupProjectionWire:
        async def execute() -> DocumentBackupProjectionWire:
            session = await documents_application.session(bearer_token(credentials))
            values = await session.backup_projection(CompanyId(str(company_id)), IncomeYear(income_year))
            return DocumentBackupProjectionWire(
                company_id=company_id,
                income_year=income_year,
                objects=[_document_backup_wire(value) for value in values],
            )

        return await documents_call(execute)

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

    authority_errors: Any = {
        status: {
            "description": "Authority Connections request failed.",
            "headers": {"X-Request-ID": REQUEST_ID_HEADER},
            "content": {"application/problem+json": {"schema": ProblemDetails.model_json_schema(by_alias=True)}},
        } for status in (401, 403, 404, 409, 422, 503)
    }

    @application.get(
        "/api/v1/authority-connections/system-user-requests",
        operation_id="authorityConnectionsListSystemUserRequests", response_model=SystemUserListWire,
        responses=authority_errors, tags=["authority-connections"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def list_system_user_requests(
        company_ids: Annotated[list[UUID], Query(alias="companyIds", min_length=1, max_length=100)],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> SystemUserListWire:
        async def execute():
            session, service = await authority_connections_service(credentials)
            records = await service.list_requests(
                company_ids=tuple(CompanyId(str(value)) for value in company_ids), actor_id=session.actor_id,
            )
            return SystemUserListWire(requests=[system_user_record_wire(value) for value in records])
        return await authority_connections_call(execute)

    @application.post(
        "/api/v1/authority-connections/system-user-requests",
        operation_id="authorityConnectionsStartSystemUserRequest", response_model=SystemUserResultWire,
        responses=authority_errors, tags=["authority-connections"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def start_system_user_request(
        body: SystemUserCommandWire,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> SystemUserResultWire:
        async def execute():
            session, service = await authority_connections_service(credentials)
            if not callback_transport.configured:
                raise AuthorityConnectionsError(
                    AuthorityConnectionsErrorCode.CALLBACK_NOT_VERIFIED,
                    ErrorCategory.PRECONDITION_FAILED,
                )
            return system_user_result_wire(await service.start(StartSystemUserRequestCommand(
                CompanyId(str(body.company_id)), session.actor_id, str(body.request_id),
            )))
        return await authority_connections_call(execute)

    @application.post(
        "/api/v1/authority-connections/system-user-requests/retries",
        operation_id="authorityConnectionsRetrySystemUserRequest", response_model=SystemUserResultWire,
        responses=authority_errors, tags=["authority-connections"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def retry_system_user_request(
        body: SystemUserCommandWire,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> SystemUserResultWire:
        async def execute():
            session, service = await authority_connections_service(credentials)
            command = ReconcileSystemUserRequestCommand(
                CompanyId(str(body.company_id)), session.actor_id, str(body.request_id),
            )
            if not callback_transport.configured:
                stored = await service.read(command)
                if stored.status is SystemUserRequestStatus.CREATING:
                    raise AuthorityConnectionsError(AuthorityConnectionsErrorCode.CALLBACK_NOT_VERIFIED)
            return system_user_result_wire(await service.retry(command))
        return await authority_connections_call(execute)

    @application.post(
        "/api/v1/authority-connections/system-user-requests/reconciliations",
        operation_id="authorityConnectionsReconcileSystemUserRequest", response_model=SystemUserResultWire,
        responses=authority_errors, tags=["authority-connections"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def reconcile_system_user_request(
        body: SystemUserCommandWire,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> SystemUserResultWire:
        async def execute():
            session, service = await authority_connections_service(credentials)
            return system_user_result_wire(await service.reconcile(ReconcileSystemUserRequestCommand(
                CompanyId(str(body.company_id)), session.actor_id, str(body.request_id),
            )))
        return await authority_connections_call(execute)

    @application.post(
        "/api/v1/authority-connections/system-user-callbacks",
        operation_id="authorityConnectionsReconcileSystemUserCallback", response_model=SystemUserResultWire,
        responses=authority_errors, tags=["authority-connections"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def reconcile_system_user_callback(
        body: SystemUserCallbackWire,
        callback_proof: Annotated[str, Header(alias="X-Talli-Authority-Callback-Proof", max_length=128)] = "",
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> SystemUserResultWire:
        async def execute():
            token = bearer_token(credentials)
            if not callback_transport.verify(request_id=str(body.request_id), bearer=token, proof=callback_proof):
                raise AuthorityConnectionsAuthenticationError()
            session, service = await authority_connections_service(credentials)
            owner = await service.resolve_owner(str(body.request_id), session.actor_id)
            return system_user_result_wire(await service.reconcile(ReconcileSystemUserRequestCommand(
                owner.company_id, session.actor_id, str(body.request_id), require_fresh_mfa=False,
            )))
        return await authority_connections_call(execute)

    @application.get(
        "/api/v1/authority-connections/operations",
        operation_id="authorityConnectionsListOperations", response_model=AuthorityOperationListWire,
        responses=authority_errors, tags=["authority-connections"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def list_authority_operations(
        limit: Annotated[int, Query(ge=1, le=10)] = 10,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> AuthorityOperationListWire:
        async def execute():
            _, workflow = await authority_operations_workflow(credentials)
            records = await workflow.list_operations(limit)
            return AuthorityOperationListWire(operations=[authority_operation_wire(value) for value in records])
        return await authority_connections_call(execute)

    @application.post(
        "/api/v1/authority-connections/operations",
        operation_id="authorityConnectionsRunOperation", response_model=AuthorityOperationRecordWire,
        responses=authority_errors, tags=["authority-connections"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def run_authority_operation(
        body: AuthorityOperationCommandWire,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> AuthorityOperationRecordWire:
        async def execute():
            session, workflow = await authority_operations_workflow(credentials)
            return authority_operation_wire(await workflow.run(RunAuthorityOperationCommand(
                session.actor_id, str(body.operation_id), body.operation, body.confirmation,
            )))
        return await authority_connections_call(execute)

    @application.get(
        "/api/v1/operator-controls/launch-signoffs",
        operation_id="operatorControlsListLaunchSignoffs", response_model=LaunchSignoffListWire,
        responses=authority_errors, tags=["operator-controls"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def list_launch_signoffs(
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> LaunchSignoffListWire:
        async def execute():
            workflow = await launch_signoff_workflow(credentials)
            return LaunchSignoffListWire(signoffs=[launch_signoff_wire(value) for value in await workflow.list_signoffs()])
        return await authority_connections_call(execute)

    @application.post(
        "/api/v1/operator-controls/launch-signoffs",
        operation_id="operatorControlsRecordLaunchSignoff", response_model=LaunchSignoffRecordWire,
        responses=authority_errors, tags=["operator-controls"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def record_launch_signoff(
        body: LaunchSignoffCommandWire,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> LaunchSignoffRecordWire:
        async def execute():
            workflow = await launch_signoff_workflow(credentials)
            return launch_signoff_wire(await workflow.record_signoff(RecordLaunchSignoff(
                body.key, body.status, body.reviewer, body.reviewed_at, body.evidence_link, body.decision,
            )))
        return await authority_connections_call(execute)

    @application.get(
        "/api/v1/shareholder-register-filings/archive-source",
        operation_id="rf1086GetArchiveSource", response_model=Rf1086ArchiveSourceWire,
        responses=authority_errors, tags=["shareholder-register-filings"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def rf1086_archive_source(
        company_id: Annotated[UUID, Query(alias="companyId")],
        income_year: Annotated[int, Query(alias="incomeYear", ge=2000, le=2100)],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> Rf1086ArchiveSourceWire:
        async def execute():
            workflow = await shareholder_register_filing_workflow(credentials)
            result = await workflow.archive_source(Rf1086ArchiveQuery(
                company_id=CompanyId(str(company_id)), income_year=IncomeYear(income_year), actor_id=workflow.actor_id,
            ))
            try:
                return Rf1086ArchiveSourceWire(
                    company_id=UUID(str(result.company_id)), income_year=int(result.income_year),
                    previews=[Rf1086PreviewWire.model_validate(row, from_attributes=True) for row in result.previews],
                    simulations=[Rf1086SimulationWire.model_validate(row, from_attributes=True) for row in result.simulations],
                    review_comments=[Rf1086ReviewCommentWire.model_validate(row, from_attributes=True) for row in result.review_comments],
                    permissions=[Rf1086PermissionWire.model_validate(row, from_attributes=True) for row in result.permissions],
                    test_evidence=[Rf1086TestEvidenceWire.model_validate(row, from_attributes=True) for row in result.test_evidence],
                )
            except ValidationError:
                raise ShareholderRegisterFilingError.unavailable() from None
        return await shareholder_register_filing_call(execute)

    @application.get(
        "/api/v1/shareholder-register-filings/workspace",
        operation_id="rf1086Workspace", response_model=Rf1086WorkspaceWire,
        responses=authority_errors, tags=["shareholder-register-filings"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def rf1086_workspace(
        company_id: Annotated[UUID, Query(alias="companyId")],
        income_year: Annotated[int | None, Query(alias="incomeYear", ge=2000, le=2100)] = None,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> Rf1086WorkspaceWire:
        async def execute():
            workflow = await shareholder_register_filing_workflow(credentials)
            result = await workflow.workspace(Rf1086WorkspaceQuery(
                CompanyId(str(company_id)), workflow.actor_id,
                IncomeYear(income_year) if income_year is not None else None,
            ))
            try:
                return Rf1086WorkspaceWire(
                    company_id=UUID(str(result.company_id)),
                    income_year=int(result.income_year) if result.income_year is not None else None,
                    previews=[Rf1086PreviewWire.model_validate(row, from_attributes=True) for row in result.previews],
                    simulations=[Rf1086SimulationWire.model_validate(row, from_attributes=True) for row in result.simulations],
                    overrides=[Rf1086OverrideWire.model_validate(row, from_attributes=True) for row in result.overrides],
                    review_comments=[Rf1086ReviewCommentWire.model_validate(row, from_attributes=True) for row in result.review_comments],
                    permissions=[Rf1086PermissionWire.model_validate(row, from_attributes=True) for row in result.permissions],
                    test_evidence=[Rf1086TestEvidenceWire.model_validate(row, from_attributes=True) for row in result.test_evidence],
                    approvals=[Rf1086ApprovalWire.model_validate(row, from_attributes=True).model_copy(
                        update={"manifest": rf1086_json_wire(row.manifest)},
                    ) for row in result.approvals],
                    production_submissions=[Rf1086ProductionSubmissionWire.model_validate(row, from_attributes=True) for row in result.production_submissions],
                    feedback_artifacts=[Rf1086FeedbackArtifactWire.model_validate(row, from_attributes=True) for row in result.feedback_artifacts],
                    actions=[Rf1086ActionAvailabilityWire.model_validate(row, from_attributes=True) for row in result.actions],
                )
            except ValidationError:
                raise ShareholderRegisterFilingError.unavailable() from None
        return await shareholder_register_filing_call(execute)

    @application.get(
        "/api/v1/shareholder-register-filings/previews/{previewId}",
        operation_id="rf1086Preview", response_model=Rf1086PreviewWire,
        responses=authority_errors, tags=["shareholder-register-filings"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def rf1086_preview(
        previewId: UUID,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> Rf1086PreviewWire:
        async def execute():
            workflow = await shareholder_register_filing_workflow(credentials)
            result = await workflow.read_preview(ReadRf1086PreviewQuery(
                PreviewId(str(previewId)), workflow.actor_id,
            ))
            if result is None:
                raise ShareholderRegisterFilingError.not_found()
            return Rf1086PreviewWire.model_validate(result, from_attributes=True)
        return await shareholder_register_filing_call(execute)

    @application.post(
        "/api/v1/shareholder-register-filings/previews",
        operation_id="rf1086GeneratePreview", response_model=Rf1086RecordedResultWire,
        responses=authority_errors, tags=["shareholder-register-filings"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def rf1086_generate_preview(
        body: Rf1086GeneratePreviewWire, request: Request,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> Rf1086RecordedResultWire:
        async def execute():
            workflow = await shareholder_register_filing_workflow(credentials)
            return rf1086_recorded_wire(await workflow.generate_preview(GenerateRf1086PreviewCommand(
                company_id=CompanyId(str(body.company_id)), opening_snapshot_id=OpeningSnapshotId(str(body.opening_snapshot_id)),
                actor_id=workflow.actor_id, correlation_id=CorrelationId(request.state.request_id),
            )))
        return await shareholder_register_filing_call(execute)

    @application.post(
        "/api/v1/shareholder-register-filings/overrides",
        operation_id="rf1086RecordOverride", response_model=Rf1086RecordedResultWire,
        responses=authority_errors, tags=["shareholder-register-filings"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def rf1086_record_override(
        body: Rf1086OverrideCommandWire, request: Request,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> Rf1086RecordedResultWire:
        async def execute():
            workflow = await shareholder_register_filing_workflow(credentials)
            return rf1086_recorded_wire(await workflow.record_override(RecordRf1086OverrideCommand(
                preview_id=PreviewId(str(body.preview_id)), field_target=body.field_target, old_value=body.old_value,
                new_value=body.new_value, reason=body.reason, risk_level=body.risk_level, owner_confirmed=body.owner_confirmed,
                actor_id=workflow.actor_id, correlation_id=CorrelationId(request.state.request_id),
            )))
        return await shareholder_register_filing_call(execute)

    @application.post(
        "/api/v1/shareholder-register-filings/review-comments",
        operation_id="rf1086AddReviewComment", response_model=Rf1086RecordedResultWire,
        responses=authority_errors, tags=["shareholder-register-filings"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def rf1086_add_review_comment(
        body: Rf1086ReviewCommentCommandWire, request: Request,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> Rf1086RecordedResultWire:
        async def execute():
            workflow = await shareholder_register_filing_workflow(credentials)
            return rf1086_recorded_wire(await workflow.add_review_comment(AddRf1086ReviewCommentCommand(
                preview_id=PreviewId(str(body.preview_id)), severity=body.severity, body=body.body,
                actor_id=workflow.actor_id, correlation_id=CorrelationId(request.state.request_id),
            )))
        return await shareholder_register_filing_call(execute)

    @application.post(
        "/api/v1/shareholder-register-filings/review-comment-acknowledgements",
        operation_id="rf1086AcknowledgeReviewComment", response_model=Rf1086RecordedResultWire,
        responses=authority_errors, tags=["shareholder-register-filings"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def rf1086_acknowledge_review_comment(
        body: Rf1086ReviewAcknowledgementWire, request: Request,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> Rf1086RecordedResultWire:
        async def execute():
            workflow = await shareholder_register_filing_workflow(credentials)
            return rf1086_recorded_wire(await workflow.acknowledge_review_comment(AcknowledgeRf1086ReviewCommentCommand(
                comment_id=ReviewCommentId(str(body.comment_id)),
                actor_id=workflow.actor_id, correlation_id=CorrelationId(request.state.request_id),
            )))
        return await shareholder_register_filing_call(execute)

    @application.post(
        "/api/v1/shareholder-register-filings/simulations",
        operation_id="rf1086ConfirmSimulation", response_model=Rf1086RecordedResultWire,
        responses=authority_errors, tags=["shareholder-register-filings"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def rf1086_confirm_simulation(
        body: Rf1086SimulationCommandWire, request: Request,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> Rf1086RecordedResultWire:
        async def execute():
            workflow = await shareholder_register_filing_workflow(credentials)
            return rf1086_recorded_wire(await workflow.confirm_simulation(ConfirmRf1086SimulationCommand(
                preview_id=PreviewId(str(body.preview_id)), authority_confirmed=body.authority_confirmed, preview_confirmed=body.preview_confirmed,
                actor_id=workflow.actor_id, correlation_id=CorrelationId(request.state.request_id),
            )))
        return await shareholder_register_filing_call(execute)

    @application.post(
        "/api/v1/shareholder-register-filings/filing-permissions",
        operation_id="rf1086ConfirmFilingPermission", response_model=Rf1086RecordedResultWire,
        responses=authority_errors, tags=["shareholder-register-filings"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def rf1086_confirm_filing_permission(
        body: Rf1086PermissionCommandWire, request: Request,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> Rf1086RecordedResultWire:
        async def execute():
            workflow = await shareholder_register_filing_workflow(credentials)
            return rf1086_recorded_wire(await workflow.confirm_filing_permission(ConfirmRf1086FilingPermissionCommand(
                company_id=CompanyId(str(body.company_id)), production_enabled=body.production_enabled,
                actor_id=workflow.actor_id, correlation_id=CorrelationId(request.state.request_id),
            )))
        return await shareholder_register_filing_call(execute)

    @application.post(
        "/api/v1/shareholder-register-filings/test-evidence",
        operation_id="rf1086RecordTestEvidence", response_model=Rf1086RecordedResultWire,
        responses=authority_errors, tags=["shareholder-register-filings"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def rf1086_record_test_evidence(
        body: Rf1086TestEvidenceCommandWire, request: Request,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> Rf1086RecordedResultWire:
        async def execute():
            workflow = await shareholder_register_filing_workflow(credentials)
            return rf1086_recorded_wire(await workflow.record_test_evidence(RecordRf1086TestEvidenceCommand(
                company_id=CompanyId(str(body.company_id)), environment=body.environment, status=body.status,
                test_reference=body.test_reference, feedback_summary=body.feedback_summary, receipt_reference=body.receipt_reference,
                archive_reference=body.archive_reference, evidence_url=body.evidence_url, payload_hash=body.payload_hash,
                actor_id=workflow.actor_id, correlation_id=CorrelationId(request.state.request_id),
            )))
        return await shareholder_register_filing_call(execute)

    @application.post(
        "/api/v1/shareholder-register-filings/production-approvals",
        operation_id="rf1086ApproveProduction", response_model=Rf1086RecordedResultWire,
        responses=authority_errors, tags=["shareholder-register-filings"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def rf1086_approve_production(
        body: Rf1086ProductionApprovalCommandWire, request: Request,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> Rf1086RecordedResultWire:
        async def execute():
            workflow = await shareholder_register_filing_workflow(credentials)
            return rf1086_recorded_wire(await workflow.approve_production(ApproveRf1086ProductionCommand(
                preview_id=PreviewId(str(body.preview_id)), entitlement_id=str(body.entitlement_id), real_filing_confirmed=body.real_filing_confirmed,
                actor_id=workflow.actor_id, correlation_id=CorrelationId(request.state.request_id),
            )))
        return await shareholder_register_filing_call(execute)

    @application.post(
        "/api/v1/legacy-rf1086/production-filings",
        operation_id="legacyRf1086SendApprovedFiling", response_model=LegacyRf1086SendResultWire,
        responses=authority_errors, tags=["legacy-rf1086"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def send_legacy_rf1086(
        body: LegacyRf1086SendCommandWire,
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> LegacyRf1086SendResultWire:
        async def execute():
            workflow = await shareholder_register_filing_workflow(credentials)
            result = await workflow.send_approved_filing(SendApprovedRf1086Command(
                ApprovalId(str(body.approval_id)), workflow.actor_id, CorrelationId(request.state.request_id),
            ))
            return LegacyRf1086SendResultWire(submission_id=UUID(result.submission_id))
        return await shareholder_register_filing_call(execute)

    @application.post(
        "/api/v1/legacy-rf1086/feedback-reconciliations",
        operation_id="legacyRf1086ReconcileFeedback", response_model=LegacyRf1086ReconcileResultWire,
        responses=authority_errors, tags=["legacy-rf1086"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def reconcile_legacy_rf1086(
        body: LegacyRf1086ReconcileCommandWire,
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> LegacyRf1086ReconcileResultWire:
        async def execute():
            workflow = await shareholder_register_filing_workflow(credentials)
            result = await workflow.reconcile_feedback(ReconcileRf1086FeedbackCommand(
                SubmissionId(str(body.submission_id)), workflow.actor_id, CorrelationId(request.state.request_id),
            ))
            return LegacyRf1086ReconcileResultWire(state=result.state,error_code=result.error_code,
                requires_manual_retry=result.requires_manual_retry)
        return await shareholder_register_filing_call(execute)

    billing_errors: Any = {
        status: {
            "description": "Billing request failed.",
            "headers": {"X-Request-ID": REQUEST_ID_HEADER},
            "content": {
                "application/problem+json": {
                    "schema": ProblemDetails.model_json_schema(by_alias=True)
                }
            },
        }
        for status in (400, 401, 403, 404, 409, 422, 503)
    }
    billing_success = {"headers": {"X-Request-ID": REQUEST_ID_HEADER}}

    def billing_metadata(workflow: BillingWorkflow, request: Request, key: str):
        return {
            "actor_id": workflow.actor_id,
            "correlation_id": CorrelationId(request.state.request_id),
            "idempotency_key": IdempotencyKey(key),
        }

    def annual_offer_wire(offer) -> AnnualBillingOfferWire:
        return AnnualBillingOfferWire(
            company_id=UUID(str(offer.company_id)), income_year=offer.income_year.value,
            **{name: getattr(offer, name) for name in ("offer_version", "terms_digest", "terms_text", "currency",
                "gross_minor", "net_minor", "vat_minor", "vat_basis_points", "paid_through", "export_through",
                "renewal_date", "renewal_reminder_by", "price_change_notice_by")},
        )

    def annual_checkout_wire(value: AnnualCheckout) -> AnnualCheckoutWire:
        offer = value.offer
        observation = value.observation
        return AnnualCheckoutWire(
            purchase_id=UUID(str(value.purchase_id)), company_id=UUID(str(offer.company_id)),
            income_year=offer.income_year.value, status=value.status,
            offer=annual_offer_wire(offer),
            captured_minor=observation.captured_minor if observation else 0,
            refunded_minor=observation.refunded_minor if observation else 0,
            checkout_url=observation.checkout_url if observation and value.status is AnnualPurchaseStatus.PENDING else None,
        )

    @application.get(
        "/api/v1/billing/annual/checkout-preparation",
        operation_id="billingPrepareAnnualCheckout", response_model=AnnualCheckoutPreparationWire,
        responses={200: {"description": "Read-only transient checkout availability or existing purchase; not a reservation."} | billing_success} | billing_errors,
        tags=["billing"], openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def prepare_annual_checkout(
        response: Response, company_id: UUID, income_year: int = Query(ge=2000, le=2100),
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> AnnualCheckoutPreparationWire:
        async def execute():
            workflow = await annual_checkout_workflow(credentials)
            result = await workflow.prepare_checkout(AnnualCheckoutPreparationQuery(
                CompanyId(str(company_id)), IncomeYear(income_year), workflow.actor_id,
            ))
            response.headers["Cache-Control"] = "no-store"
            return AnnualCheckoutPreparationWire(
                company_id=UUID(str(result.company_id)), income_year=result.income_year.value,
                state="existing" if result.existing_purchase else "available",
                offer=annual_offer_wire(result.offer) if result.offer else None,
                consent_version=result.consent_version,
                purchase_id=UUID(str(result.existing_purchase.purchase_id)) if result.existing_purchase else None,
            )
        return await billing_call(execute)

    @application.post(
        "/api/v1/billing/annual/checkouts",
        operation_id="billingStartAnnualCheckout", response_model=AnnualCheckoutWire,
        responses={200: {"description": "Stored annual checkout; only confirmed full capture is paid."} | billing_success} | billing_errors,
        tags=["billing"], openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def start_annual_checkout(
        request: Request, response: Response, command: AnnualCheckoutCommandWire,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> AnnualCheckoutWire:
        async def execute():
            workflow = await annual_checkout_workflow(credentials)
            result = await workflow.start_checkout(billing_input(lambda: StartAnnualCheckoutCommand(
                company_id=CompanyId(str(command.company_id)), income_year=IncomeYear(command.income_year),
                offer_version=command.offer_version, terms_digest=command.terms_digest,
                purchase_accepted=command.purchase_accepted, recurring_consent=command.recurring_consent,
                consent_version=command.consent_version,
                **billing_metadata(workflow, request, idempotency_key),
            )))
            response.headers["Cache-Control"] = "no-store"
            return annual_checkout_wire(result)
        return await billing_call(execute)

    @application.post(
        "/api/v1/billing/annual/checkout-withdrawals",
        operation_id="billingWithdrawAnnualCheckoutRequest", response_model=AnnualCheckoutRequestResolutionWire,
        responses={200: {"description": "Original purchase reference or committed withdrawal; no provider effect."} | billing_success} | billing_errors,
        tags=["billing"], openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def withdraw_annual_checkout_request(
        request: Request, response: Response, command: AnnualCheckoutCommandWire,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> AnnualCheckoutRequestResolutionWire:
        async def execute():
            workflow = await annual_checkout_workflow(credentials)
            result = await workflow.withdraw_checkout_request(billing_input(lambda: StartAnnualCheckoutCommand(
                company_id=CompanyId(str(command.company_id)), income_year=IncomeYear(command.income_year),
                offer_version=command.offer_version, terms_digest=command.terms_digest,
                purchase_accepted=command.purchase_accepted, recurring_consent=command.recurring_consent,
                consent_version=command.consent_version,
                **billing_metadata(workflow, request, idempotency_key),
            )))
            response.headers["Cache-Control"] = "no-store"
            return AnnualCheckoutRequestResolutionWire(
                company_id=UUID(str(result.company_id)), income_year=result.income_year.value,
                state="existing" if result.purchase_id is not None else "withdrawn",
                purchase_id=UUID(str(result.purchase_id)) if result.purchase_id else None,
                withdrawal_id=UUID(str(result.withdrawal_id)) if result.withdrawal_id else None,
                withdrawn_at=result.withdrawn_at.value if result.withdrawn_at else None,
            )
        return await billing_call(execute)

    @application.post(
        "/api/v1/billing/annual/provider-notifications",
        operation_id="billingReceiveAnnualProviderNotification",
        response_model=AnnualNotificationAcknowledgementWire,
        responses={200: {"description": "Authenticated delivery receipt committed; no payment or refund confirmation."} | billing_success,
                   **{status: {"description": description, "headers": {"X-Request-ID": REQUEST_ID_HEADER},
                               "content": {"application/problem+json": {"schema": ProblemDetails.model_json_schema(by_alias=True)}}}
                      for status, description in ((400, "Invalid delivery"), (401, "Authentication rejected"),
                                                  (408, "Delivery timed out"), (413, "Delivery too large"),
                                                  (503, "Receipt unavailable; retry delivery"))}},
        tags=["billing"],
        openapi_extra={
            "parameters": [REQUEST_ID_PARAMETER],
            "requestBody": {"required": True, "description": "Exact signed JSON bytes, at most 64 KiB; reserialization invalidates authentication.",
                            "content": {"application/json": {"schema": {"type": "object", "additionalProperties": True}}}},
        },
    )
    async def receive_annual_provider_notification(
        request: Request,
        _signature: str | None = Depends(APIKeyHeader(
            name="Authorization", scheme_name="annualNotificationHmac", auto_error=False,
            description="Provider HMAC over the exact body, signed date and configured callback target; customer bearer tokens are not accepted.",
        )),
    ) -> AnnualNotificationAcknowledgementWire:
        # Only the explicitly composed intake accepts authenticated provider deliveries.
        if annual_notification_intake is None:
            raise ApiProblem(status=503, code="ANNUAL_NOTIFICATION_UNAVAILABLE", title="Delivery unavailable", detail="The receipt service is unavailable.")
        try:
            headers: dict[str, str] = {}
            for key, value in request.scope["headers"]:
                name = key.decode("latin-1").lower()
                if name in headers:
                    raise AnnualNotificationRejected()
                headers[name] = value.decode("latin-1")
            body = bytearray()
            async with asyncio.timeout(2):
                async for chunk in request.stream():
                    if len(body) + len(chunk) > 65536:
                        raise ApiProblem(status=413, code="ANNUAL_NOTIFICATION_TOO_LARGE", title="Delivery too large", detail="The delivery exceeds the receipt limit.")
                    body.extend(chunk)
            await annual_notification_intake.receive(bytes(body), headers, at=datetime.now(UTC))
        except AnnualNotificationRejected:
            raise ApiProblem(status=401, code="ANNUAL_NOTIFICATION_REJECTED", title="Delivery rejected", detail="The delivery could not be authenticated.") from None
        except AnnualNotificationUnavailable:
            raise ApiProblem(status=503, code="ANNUAL_NOTIFICATION_UNAVAILABLE", title="Delivery unavailable", detail="The receipt could not be confirmed. Retry the delivery.") from None
        except TimeoutError:
            raise ApiProblem(status=408, code="ANNUAL_NOTIFICATION_TIMEOUT", title="Delivery timed out", detail="Retry the complete delivery.") from None
        except ClientDisconnect:
            raise ApiProblem(status=400, code="ANNUAL_NOTIFICATION_INCOMPLETE", title="Incomplete delivery", detail="Retry the complete delivery.") from None
        return AnnualNotificationAcknowledgementWire(status="received")

    @application.post(
        "/api/v1/billing/annual/checkout-observations",
        operation_id="billingObserveAnnualCheckout", response_model=AnnualCheckoutWire,
        responses={200: {"description": "Reconciles the original stored intent; never creates another agreement or charge."} | billing_success} | billing_errors,
        tags=["billing"], openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def observe_annual_checkout(
        response: Response, command: AnnualCheckoutObservationCommandWire,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> AnnualCheckoutWire:
        async def execute():
            workflow = await annual_checkout_workflow(credentials)
            result = await workflow.observe_checkout(AnnualCheckoutQuery(
                company_id=CompanyId(str(command.company_id)), purchase_id=AnnualPurchaseId(str(command.purchase_id)), actor_id=workflow.actor_id,
            ))
            response.headers["Cache-Control"] = "no-store"
            return annual_checkout_wire(result)
        return await billing_call(execute)

    @application.post(
        "/api/v1/billing/annual/agreement-cleanups",
        operation_id="billingCleanupAnnualAgreement", response_model=AnnualAgreementCleanupWire,
        responses={200: {"description": "Recover a recorded renewal stop; deferred or unknown is not confirmation."} | billing_success} | billing_errors,
        tags=["billing"], openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def cleanup_annual_agreement(
        response: Response, command: AnnualAgreementCleanupCommandWire,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> AnnualAgreementCleanupWire:
        async def execute():
            workflow = await annual_cleanup_workflow(credentials)
            result = await workflow.cleanup(AnnualCheckoutQuery(
                company_id=CompanyId(str(command.company_id)), purchase_id=AnnualPurchaseId(str(command.purchase_id)),
                actor_id=workflow.actor_id,
            ))
            response.headers["Cache-Control"] = "no-store"
            return AnnualAgreementCleanupWire(
                company_id=command.company_id, purchase_id=command.purchase_id,
                status="deferred" if result is None else result.observation.status.value if result.observation else "pending",
            )
        return await billing_call(execute)

    @application.post(
        "/api/v1/billing/annual/refund-recoveries",
        operation_id="billingRecoverAnnualRefund", response_model=AnnualRefundRecoveryWire,
        responses={200: {"description": "Original refund operation status; confirmation does not mean all purchase liability is refunded."} | billing_success} | billing_errors,
        tags=["billing"], openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def recover_annual_refund(
        response: Response, command: AnnualRefundRecoveryCommandWire,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> AnnualRefundRecoveryWire:
        async def execute():
            workflow = AnnualRefundRecoveryWorkflow(
                await annual_billing_sessions.session(bearer_token(credentials)), annual_billing_provider,
            )
            result = await workflow.recover_refund(AnnualRefundRecoveryQuery(
                company_id=CompanyId(str(command.company_id)), purchase_id=AnnualPurchaseId(str(command.purchase_id)),
                refund_request_id=AnnualRefundRequestId(str(command.refund_request_id)), actor_id=workflow.actor_id,
            ))
            resolution = result.resolution
            return AnnualRefundRecoveryWire(
                company_id=UUID(str(resolution.request.company_id)),
                purchase_id=UUID(str(resolution.request.purchase_id)),
                refund_request_id=UUID(str(result.refund_request_id)), income_year=resolution.facts.income_year.value,
                status=resolution.operation.observation.status.value,
            )

        response.headers["Cache-Control"] = "no-store"
        return await billing_call(execute)

    @application.post(
        "/api/v1/billing/annual/support/refund-recoveries",
        operation_id="billingRecoverAnnualSupportRefund", response_model=AnnualSupportRefundRecoveryWire,
        responses={200: {"description": "Reconcile a recorded refund under an opened billing case; confirmation applies to that operation only."} | billing_success} | billing_errors,
        tags=["billing"], openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def recover_annual_support_refund(
        response: Response, command: AnnualSupportRefundRecoveryCommandWire,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> AnnualSupportRefundRecoveryWire:
        async def execute():
            workflow = AnnualSupportRefundRecoveryWorkflow(
                await annual_billing_sessions.session(bearer_token(credentials)), annual_billing_provider,
            )
            result = await workflow.recover_refund(AnnualSupportRefundRecoveryQuery(
                company_id=CompanyId(str(command.company_id)), purchase_id=AnnualPurchaseId(str(command.purchase_id)),
                refund_request_id=AnnualRefundRequestId(str(command.refund_request_id)),
                support_case_id=AnnualSupportCaseId(str(command.support_case_id)), actor_id=workflow.actor_id,
            ))
            resolution = result.resolution
            return AnnualSupportRefundRecoveryWire(
                company_id=UUID(str(resolution.request.company_id)),
                purchase_id=UUID(str(resolution.request.purchase_id)),
                refund_request_id=UUID(str(result.refund_request_id)), income_year=resolution.facts.income_year.value,
                support_case_id=command.support_case_id, status=resolution.operation.observation.status.value,
            )

        response.headers["Cache-Control"] = "no-store"
        return await billing_call(execute)

    @application.post(
        "/api/v1/billing/annual/support/agreement-cleanup-recoveries",
        operation_id="billingRecoverAnnualSupportCleanup", response_model=AnnualSupportCleanupRecoveryWire,
        responses={200: {"description": "Observe the one recorded agreement stop under an opened billing case; no new cleanup or provider execution."} | billing_success} | billing_errors,
        tags=["billing"], openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def recover_annual_support_cleanup(
        response: Response, command: AnnualSupportCleanupRecoveryCommandWire,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> AnnualSupportCleanupRecoveryWire:
        async def execute():
            workflow = AnnualSupportCleanupRecoveryWorkflow(
                await annual_billing_sessions.session(bearer_token(credentials)), annual_billing_provider,
            )
            result = await workflow.recover_cleanup(AnnualSupportCleanupRecoveryQuery(
                company_id=CompanyId(str(command.company_id)), purchase_id=AnnualPurchaseId(str(command.purchase_id)),
                support_case_id=AnnualSupportCaseId(str(command.support_case_id)), actor_id=workflow.actor_id,
            ))
            return AnnualSupportCleanupRecoveryWire(
                company_id=UUID(str(result.intent.company_id)), purchase_id=UUID(str(result.purchase_id)),
                support_case_id=command.support_case_id, operation_id=UUID(str(result.intent.operation_id)),
                income_year=result.intent.income_year.value, status=result.observation.status.value,
            )

        response.headers["Cache-Control"] = "no-store"
        return await billing_call(execute)

    def annual_purchase_refund_wire(value: AnnualPurchaseSummary) -> AnnualPurchaseRefundSummaryWire:
        return AnnualPurchaseRefundSummaryWire(
            purchase_id=UUID(str(value.purchase_id)), company_id=UUID(str(value.company_id)),
            income_year=value.income_year.value, accepted_at=value.accepted_at.value,
            captured_at=value.captured_at.value if value.captured_at else None,
            renewal_canceled_at=value.renewal_canceled_at.value if value.renewal_canceled_at else None,
            latest_refund_requested_at=value.latest_refund_requested_at.value if value.latest_refund_requested_at else None,
            refund_operations=AnnualOperationCountsWire(**{
                name: getattr(value.refund_operations,name) for name in ("created","pending","unknown","confirmed","failed")}),
            **{name: getattr(value,name) for name in ("status","offer_version","terms_digest","terms_text",
                "currency","gross_minor","net_minor","vat_minor","vat_basis_points","captured_minor",
                "refunded_minor","recurring_consent","paid_through","export_through","renewal_date",
                "recorded_refund_minor","remaining_refund_minor","refund_initiate_by","refund_request_count")},
        )

    async def annual_billing_snapshot_response(
        response: Response, company_id: UUID, income_year: int,
        before_purchase_id: UUID | None, credentials: HTTPAuthorizationCredentials | None,
    ) -> AnnualBillingRefundSnapshotWire:
        async def execute():
            workflow = await annual_billing_workflow(credentials)
            result = await workflow.snapshot(AnnualBillingSnapshotQuery(
                CompanyId(str(company_id)), IncomeYear(income_year), workflow.actor_id,
                AnnualPurchaseId(str(before_purchase_id)) if before_purchase_id else None,
            ))
            offer = result.offer
            response.headers["Cache-Control"] = "no-store"
            return AnnualBillingRefundSnapshotWire(
                offer=AnnualBillingOfferWire(
                    company_id=UUID(str(offer.company_id)), income_year=offer.income_year.value,
                    **{name: getattr(offer,name) for name in ("offer_version","terms_digest","terms_text","currency",
                        "gross_minor","net_minor","vat_minor","vat_basis_points","paid_through","export_through",
                        "renewal_date","renewal_reminder_by","price_change_notice_by")},
                ),
                purchases=[annual_purchase_refund_wire(value) for value in result.purchases.purchases],
                next_purchase_id=UUID(str(result.purchases.next_purchase_id)) if result.purchases.next_purchase_id else None,
            )
        return await billing_call(execute)

    @application.get(
        "/api/v1/billing/annual/snapshot",
        operation_id="billingReadAnnualSnapshot", response_model=AnnualBillingSnapshotWire,
        responses={200: {"description": "Stored annual billing facts and published offer; no charge authority."} | billing_success} | billing_errors,
        tags=["billing"], openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def read_annual_billing_snapshot(
        response: Response,
        company_id: UUID = Query(alias="companyId"),
        income_year: int = Query(alias="incomeYear", ge=2000, le=2100),
        before_purchase_id: UUID | None = Query(default=None, alias="beforePurchaseId"),
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> AnnualBillingSnapshotWire:
        result = await annual_billing_snapshot_response(response, company_id, income_year, before_purchase_id, credentials)
        # Preserve the predecessor response exactly: its generated clients reject
        # extra fields. The expanded projection has a separate read contract.
        return AnnualBillingSnapshotWire(
            offer=result.offer, next_purchase_id=result.next_purchase_id,
            purchases=[AnnualPurchaseSummaryWire(**value.model_dump(include=set(AnnualPurchaseSummaryWire.model_fields)))
                       for value in result.purchases],
        )

    @application.get(
        "/api/v1/billing/annual/refund-snapshot",
        operation_id="billingReadAnnualRefundSnapshot", response_model=AnnualBillingRefundSnapshotWire,
        responses={200: {"description": "Stored owner billing facts with recorded refund evidence, not new refund eligibility."} | billing_success} | billing_errors,
        tags=["billing"], openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def read_annual_billing_refund_snapshot(
        response: Response,
        company_id: UUID = Query(alias="companyId"),
        income_year: int = Query(alias="incomeYear", ge=2000, le=2100),
        before_purchase_id: UUID | None = Query(default=None, alias="beforePurchaseId"),
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> AnnualBillingRefundSnapshotWire:
        return await annual_billing_snapshot_response(response, company_id, income_year, before_purchase_id, credentials)

    @application.get(
        "/api/v1/billing/annual/refund-recovery-targets",
        operation_id="billingReadAnnualRefundRecoveryTargets", response_model=AnnualRefundRecoveryTargetPageWire,
        responses={200: {"description": "Same-owner stored bound refund receipts for one purchase; no refund adjudication or provider action."} | billing_success} | billing_errors,
        tags=["billing"], openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def read_annual_refund_recovery_targets(
        response: Response,
        company_id: UUID = Query(alias="companyId"),
        purchase_id: UUID = Query(alias="purchaseId"),
        before_refund_request_id: UUID | None = Query(default=None, alias="beforeRefundRequestId"),
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> AnnualRefundRecoveryTargetPageWire:
        async def execute():
            workflow = await annual_billing_workflow(credentials)
            page = await workflow.refund_recovery_targets(AnnualRefundRecoveryTargetsQuery(
                CompanyId(str(company_id)), AnnualPurchaseId(str(purchase_id)), workflow.actor_id,
                AnnualRefundRequestId(str(before_refund_request_id)) if before_refund_request_id else None,
            ))
            response.headers["Cache-Control"] = "no-store"
            return AnnualRefundRecoveryTargetPageWire(
                company_id=company_id, purchase_id=purchase_id, income_year=page.income_year.value,
                targets=[AnnualRefundRecoveryTargetWire(
                    refund_request_id=UUID(str(value.refund_request_id)),
                    requested_at=value.requested_at.value, status=value.status,
                ) for value in page.targets],
                next_refund_request_id=UUID(str(page.next_refund_request_id)) if page.next_refund_request_id else None,
            )
        return await billing_call(execute)

    @application.get(
        "/api/v1/billing/annual/purchases",
        operation_id="billingReadAnnualPurchaseHistory", response_model=AnnualPurchaseHistoryWire,
        responses={200: {"description": "Stored owner purchase history across years, independent of current admission; no offer or charge authority."} | billing_success} | billing_errors,
        tags=["billing"], openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def read_annual_purchase_history(
        response: Response,
        company_id: UUID = Query(alias="companyId"),
        before_purchase_id: UUID | None = Query(default=None, alias="beforePurchaseId"),
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> AnnualPurchaseHistoryWire:
        async def execute():
            workflow = await annual_billing_workflow(credentials)
            page = await workflow.purchase_history(AnnualPurchaseHistoryQuery(
                CompanyId(str(company_id)), workflow.actor_id,
                AnnualPurchaseId(str(before_purchase_id)) if before_purchase_id else None,
            ))
            response.headers["Cache-Control"] = "no-store"
            return AnnualPurchaseHistoryWire(
                company_id=company_id, purchases=[annual_purchase_refund_wire(value) for value in page.purchases],
                next_purchase_id=UUID(str(page.next_purchase_id)) if page.next_purchase_id else None,
            )
        return await billing_call(execute)

    @application.get(
        "/api/v1/billing/annual/support/refund-recovery-targets",
        operation_id="billingReadAnnualSupportRefundRecoveryTargets", response_model=AnnualSupportRefundRecoveryTargetPageWire,
        responses={200: {"description": "Stored bound refund receipts under an explicitly opened billing case; no new refund or provider action."} | billing_success} | billing_errors,
        tags=["billing"], openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def read_annual_support_refund_recovery_targets(
        response: Response,
        company_id: UUID = Query(alias="companyId"),
        purchase_id: UUID = Query(alias="purchaseId"),
        support_case_id: UUID = Query(alias="supportCaseId"),
        before_refund_request_id: UUID | None = Query(default=None, alias="beforeRefundRequestId"),
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> AnnualSupportRefundRecoveryTargetPageWire:
        async def execute():
            workflow = AnnualSupportWorkflow(await annual_billing_sessions.session(bearer_token(credentials)))
            page = await workflow.refund_recovery_targets(AnnualSupportRefundRecoveryTargetsQuery(
                company_id=CompanyId(str(company_id)), purchase_id=AnnualPurchaseId(str(purchase_id)),
                support_case_id=AnnualSupportCaseId(str(support_case_id)), actor_id=workflow.actor_id,
                before_refund_request_id=AnnualRefundRequestId(str(before_refund_request_id)) if before_refund_request_id else None,
            ))
            return AnnualSupportRefundRecoveryTargetPageWire(
                company_id=company_id, purchase_id=purchase_id, support_case_id=support_case_id,
                income_year=page.income_year.value,
                targets=[AnnualRefundRecoveryTargetWire(
                    refund_request_id=UUID(str(value.refund_request_id)),
                    requested_at=value.requested_at.value, status=value.status,
                ) for value in page.targets],
                next_refund_request_id=UUID(str(page.next_refund_request_id)) if page.next_refund_request_id else None,
            )

        response.headers["Cache-Control"] = "no-store"
        return await billing_call(execute)

    @application.get(
        "/api/v1/billing/annual/support/purchases",
        operation_id="billingReadAnnualSupportPurchases", response_model=AnnualSupportPageWire,
        responses={200: {"description": "Recorded annual evidence for the current opened admin billing support case."} | billing_success} | billing_errors,
        tags=["billing"], openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def read_annual_support_purchases(
        response: Response,
        company_id: UUID = Query(alias="companyId"),
        support_case_id: UUID = Query(alias="supportCaseId"),
        before_purchase_id: UUID | None = Query(default=None, alias="beforePurchaseId"),
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> AnnualSupportPageWire:
        async def execute():
            workflow = AnnualSupportWorkflow(await annual_billing_sessions.session(bearer_token(credentials)))
            page = await workflow.purchases(AnnualSupportQuery(
                CompanyId(str(company_id)), AnnualSupportCaseId(str(support_case_id)), workflow.actor_id,
                AnnualPurchaseId(str(before_purchase_id)) if before_purchase_id else None,
            ))
            response.headers["Cache-Control"] = "no-store"
            return AnnualSupportPageWire(
                company_id=company_id, support_case_id=support_case_id,
                purchases=[AnnualSupportPurchaseWire(
                    purchase_id=UUID(str(value.purchase_id)), company_id=UUID(str(value.company_id)),
                    income_year=value.income_year.value, accepted_at=value.accepted_at.value,
                    updated_at=value.updated_at.value,
                    renewal_canceled_at=value.renewal_canceled_at.value if value.renewal_canceled_at else None,
                    latest_refund_requested_at=value.latest_refund_requested_at.value if value.latest_refund_requested_at else None,
                    refund_operations=AnnualOperationCountsWire(**{name: getattr(value.refund_operations,name)
                        for name in ("created","pending","unknown","confirmed","failed")}),
                    **{name: getattr(value,name) for name in ("status","currency","gross_minor","captured_minor",
                        "refunded_minor","paid_through","export_through","recurring_consent","refund_case_count","recorded_refund_minor",
                        "remaining_refund_minor","refund_initiate_by","refund_request_count","cleanup_status")},
                ) for value in page.purchases],
                next_purchase_id=UUID(str(page.next_purchase_id)) if page.next_purchase_id else None,
            )
        return await billing_call(execute)

    @application.post(
        "/api/v1/billing/annual/renewal-cancellations",
        operation_id="billingCancelAnnualRenewal", response_model=AnnualRenewalCancellationWire,
        responses={200: {"description": "Durable local renewal cancellation; purchased access is preserved."} | billing_success} | billing_errors,
        tags=["billing"], openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def cancel_annual_billing_renewal(
        request: Request, response: Response, command: AnnualRenewalCancellationCommandWire,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> AnnualRenewalCancellationWire:
        async def execute():
            workflow = await annual_billing_workflow(credentials)
            result = await workflow.cancel_renewal(billing_input(lambda: CancelAnnualRenewalCommand(
                company_id=CompanyId(str(command.company_id)), purchase_id=AnnualPurchaseId(str(command.purchase_id)),
                **billing_metadata(workflow, request, idempotency_key),
            )))
            response.headers["Cache-Control"] = "no-store"
            return AnnualRenewalCancellationWire(
                cancellation_id=UUID(str(result.cancellation_id)), purchase_id=UUID(str(result.purchase_id)),
                company_id=UUID(str(result.company_id)), income_year=result.income_year.value,
                requested_at=result.requested_at.value, effective_at=result.effective_at.value,
                paid_through=result.paid_through, export_through=result.export_through,
            )
        return await billing_call(execute)

    @application.get(
        "/api/v1/billing/snapshot",
        operation_id="billingReadSnapshot",
        response_model=BillingSnapshotWire,
        responses={200: {"description": "Canonical billing snapshot."} | billing_success}
        | billing_errors,
        tags=["billing"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def read_billing_snapshot(
        request: Request,
        company_ids: Annotated[list[UUID], Query(alias="companyIds", min_length=1, max_length=100)],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> BillingSnapshotWire:
        async def execute() -> BillingSnapshotWire:
            workflow = await billing_workflow(credentials)
            query = billing_input(
                lambda: BillingSnapshotQuery(
                    company_ids=tuple(CompanyId(str(value)) for value in company_ids),
                    actor_id=workflow.actor_id,
                    correlation_id=CorrelationId(request.state.request_id),
                )
            )
            return billing_snapshot_wire(await workflow.snapshot(query))

        return await billing_call(execute)

    @application.get(
        "/api/v1/billing/entitlement",
        operation_id="billingReadEntitlement",
        response_model=BillingEntitlementDecisionWire,
        responses={200: {"description": "Server-side filing entitlement decision."} | billing_success}
        | billing_errors,
        tags=["billing"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def read_billing_entitlement(
        request: Request,
        company_id: Annotated[UUID, Query(alias="companyId")],
        income_year: Annotated[int, Query(alias="incomeYear", ge=2000, le=2100)],
        obligation: BillingObligation,
        case_profile: Annotated[str | None, Query(alias="caseProfile", max_length=100)] = None,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> BillingEntitlementDecisionWire:
        async def execute() -> BillingEntitlementDecisionWire:
            workflow = await billing_workflow(credentials)
            query = billing_input(
                lambda: BillingEntitlementQuery(
                    company_id=CompanyId(str(company_id)),
                    actor_id=workflow.actor_id,
                    correlation_id=CorrelationId(request.state.request_id),
                    income_year=IncomeYear(income_year),
                    obligation=obligation,
                    case_profile=case_profile,
                )
            )
            return billing_decision_wire(await workflow.entitlement(query))

        return await billing_call(execute)

    @application.post(
        "/api/v1/billing/accounts/configuration",
        operation_id="billingConfigureAccount",
        deprecated=True,
        response_model=BillingAccountWire,
        responses={200: {"description": "Retired configuration endpoint; new configuration is rejected."} | billing_success}
        | billing_errors,
        tags=["billing"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def configure_billing_account(
        request: Request,
        command: BillingConfigureWire,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=255)],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> BillingAccountWire:
        async def execute() -> BillingAccountWire:
            workflow = await billing_workflow(credentials)
            domain = billing_input(lambda: ConfigureBillingAccountCommand(
                company_id=CompanyId(str(command.company_id)),
                **billing_metadata(workflow, request, idempotency_key),
                pricing_plan=command.pricing_plan,
                founder_cohort_number=command.founder_cohort_number,
            ))
            return billing_account_wire(await workflow.configure_account(domain))

        return await billing_call(execute)

    @application.post(
        "/api/v1/billing/subscriptions/activation",
        operation_id="billingActivateSubscription",
        deprecated=True,
        response_model=BillingPaymentEventWire,
        responses={200: {"description": "Historical subscription outcome recovered; new acquisition is retired."} | billing_success} | billing_errors,
        tags=["billing"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def activate_billing_subscription(
        request: Request,
        command: BillingCompanyWire,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=255)],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> BillingPaymentEventWire:
        async def execute() -> BillingPaymentEventWire:
            workflow = await billing_workflow(credentials)
            domain = billing_input(lambda: ActivateSubscriptionCommand(
                company_id=CompanyId(str(command.company_id)),
                **billing_metadata(workflow, request, idempotency_key),
            ))
            return billing_event_wire(await workflow.activate_subscription(domain))

        return await billing_call(execute)

    @application.post(
        "/api/v1/billing/subscriptions/cancellation",
        operation_id="billingCancelSubscription",
        response_model=BillingPaymentEventWire,
        responses={200: {"description": "Subscription cancellation completed."} | billing_success} | billing_errors,
        tags=["billing"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def cancel_billing_subscription(
        request: Request,
        command: BillingCompanyWire,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=255)],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> BillingPaymentEventWire:
        async def execute() -> BillingPaymentEventWire:
            workflow = await billing_workflow(credentials)
            domain = billing_input(lambda: CancelSubscriptionCommand(
                company_id=CompanyId(str(command.company_id)),
                **billing_metadata(workflow, request, idempotency_key),
            ))
            return billing_event_wire(await workflow.cancel_subscription(domain))

        return await billing_call(execute)

    @application.post(
        "/api/v1/billing/filing-package/purchase",
        operation_id="billingPurchaseFilingPackage",
        deprecated=True,
        response_model=BillingPaymentEventWire,
        responses={200: {"description": "Historical filing-package outcome recovered; new acquisition is retired."} | billing_success} | billing_errors,
        tags=["billing"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def purchase_billing_filing_package(
        request: Request,
        command: BillingFilingPackageWire,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=255)],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> BillingPaymentEventWire:
        async def execute() -> BillingPaymentEventWire:
            workflow = await billing_workflow(credentials)
            domain = billing_input(lambda: PurchaseFilingPackageCommand(
                company_id=CompanyId(str(command.company_id)),
                **billing_metadata(workflow, request, idempotency_key),
                income_year=IncomeYear(command.income_year),
                obligation=command.obligation,
            ))
            return billing_event_wire(await workflow.purchase_filing_package(domain))

        return await billing_call(execute)

    @application.post(
        "/api/v1/billing/filing-package/refund",
        operation_id="billingRefundFilingPackage",
        response_model=BillingPaymentEventWire,
        responses={200: {"description": "Eligible simulated refund completed."} | billing_success} | billing_errors,
        tags=["billing"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def refund_billing_filing_package(
        request: Request,
        command: BillingFilingPackageWire,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=255)],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> BillingPaymentEventWire:
        async def execute() -> BillingPaymentEventWire:
            workflow = await billing_workflow(credentials)
            domain = billing_input(lambda: RefundFilingPackageCommand(
                company_id=CompanyId(str(command.company_id)),
                **billing_metadata(workflow, request, idempotency_key),
                income_year=IncomeYear(command.income_year),
            ))
            return billing_event_wire(await workflow.refund_filing_package(domain))

        return await billing_call(execute)

    @application.post(
        "/api/v1/billing/unsupported",
        operation_id="billingMarkUnsupported",
        response_model=BillingAccountWire,
        responses={200: {"description": "Case marked unsupported and no-charge."} | billing_success} | billing_errors,
        tags=["billing"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def mark_billing_unsupported(
        request: Request,
        command: BillingUnsupportedWire,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=255)],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> BillingAccountWire:
        async def execute() -> BillingAccountWire:
            workflow = await billing_workflow(credentials)
            domain = billing_input(lambda: MarkBillingUnsupportedCommand(
                company_id=CompanyId(str(command.company_id)),
                **billing_metadata(workflow, request, idempotency_key),
                reason=command.reason,
            ))
            return billing_account_wire(await workflow.mark_unsupported(domain))

        return await billing_call(execute)

    @application.post(
        "/api/v1/billing/pilot-entitlements",
        operation_id="billingManagePilotEntitlement",
        response_model=BillingPilotEntitlementWire,
        responses={200: {"description": "Production pilot entitlement managed."} | billing_success} | billing_errors,
        tags=["billing"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def manage_billing_pilot_entitlement(
        request: Request,
        command: BillingPilotEntitlementCommandWire,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=255)],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> BillingPilotEntitlementWire:
        async def execute() -> BillingPilotEntitlementWire:
            workflow = await billing_workflow(credentials)
            domain = billing_input(lambda: ManageProductionPilotEntitlementCommand(
                company_id=CompanyId(str(command.company_id)),
                **billing_metadata(workflow, request, idempotency_key),
                entitlement_id=(ProductionPilotEntitlementId(str(command.entitlement_id)) if command.entitlement_id else None),
                user_id=UserId(str(command.user_id)),
                income_year=IncomeYear(command.income_year),
                status=command.status,
                billing_exempt=command.billing_exempt,
                system_user_request_id=SystemUserRequestReference(str(command.system_user_request_id)),
                starts_at=Timestamp(command.starts_at),
                expires_at=Timestamp(command.expires_at),
                evidence_reference=command.evidence_reference,
            ))
            return billing_pilot_wire(await workflow.manage_pilot_entitlement(domain))

        return await billing_call(execute)

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
