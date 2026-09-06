"""Stable public contract for plans, payments, refunds, and filing entitlement."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from typing import Protocol, TypeVar, runtime_checkable
from uuid import UUID

from talli_backend.shared.kernel import (
    ActorId,
    CompanyId,
    CorrelationId,
    DomainError,
    ErrorCategory,
    IdempotencyKey,
    IncomeYear,
    Timestamp,
    UserId,
)


@dataclass(frozen=True, slots=True)
class _UuidId:
    value: str

    def __post_init__(self) -> None:
        try:
            canonical = str(UUID(self.value))
        except (ValueError, AttributeError, TypeError):
            raise ValueError("identifier must be a UUID") from None
        object.__setattr__(self, "value", canonical)

    def __str__(self) -> str:
        return self.value


class BillingPaymentEventId(_UuidId):
    pass


class ProductionPilotEntitlementId(_UuidId):
    pass


class SystemUserRequestReference(_UuidId):
    pass


class BillingPlan(StrEnum):
    FOUNDER = "founder"
    STANDARD = "standard"


class BillingStatus(StrEnum):
    ANNUAL_BILLING_UNAVAILABLE = "annual_billing_unavailable"
    ACTIVE = "active"
    SUBSCRIPTION_REQUIRED = "subscription_required"
    FILING_PACKAGE_REQUIRED = "filing_package_required"
    READY_FOR_PRODUCTION_FILING = "ready_for_production_filing"
    UNSUPPORTED_CASE = "unsupported_case"
    REFUND_ELIGIBLE = "refund_eligible"
    PILOT_ENTITLEMENT_ACTIVE = "pilot_entitlement_active"


class BillingPaymentKind(StrEnum):
    SUBSCRIPTION = "subscription"
    SUBSCRIPTION_CANCELLATION = "subscription_cancellation"
    FILING_PACKAGE = "filing_package"
    REFUND = "refund"


class BillingPaymentStatus(StrEnum):
    CREATED = "created"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"
    CANCELED = "canceled"


def expected_payment_status(kind: BillingPaymentKind) -> BillingPaymentStatus:
    return {
        BillingPaymentKind.SUBSCRIPTION_CANCELLATION: BillingPaymentStatus.CANCELED,
        BillingPaymentKind.REFUND: BillingPaymentStatus.REFUNDED,
    }.get(kind, BillingPaymentStatus.SUCCEEDED)


class BillingPilotCaseProfile(StrEnum):
    RF1086_NO_ACTIVITY_V1 = "rf1086_no_activity_v1"


class ProductionPilotStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    COMPLETED = "completed"
    REVOKED = "revoked"


class BillingObligation(StrEnum):
    SHAREHOLDER_REGISTER = "aksjonaerregisteroppgaven"
    COMPANY_TAX = "skattemelding"
    ANNUAL_ACCOUNTS = "aarsregnskap"


class BillingErrorCode(StrEnum):
    LEGACY_ACQUISITION_RETIRED = "BILLING_LEGACY_ACQUISITION_RETIRED"
    INVALID_INPUT = "BILLING_INVALID_INPUT"
    NOT_FOUND = "BILLING_NOT_FOUND"
    FORBIDDEN = "BILLING_FORBIDDEN"
    STEP_UP_REQUIRED = "BILLING_STEP_UP_REQUIRED"
    IDEMPOTENCY_KEY_REUSED = "BILLING_IDEMPOTENCY_KEY_REUSED"
    IDEMPOTENCY_IN_PROGRESS = "BILLING_IDEMPOTENCY_IN_PROGRESS"
    SUBSCRIPTION_REQUIRED = "BILLING_SUBSCRIPTION_REQUIRED"
    FILING_NOT_READY = "BILLING_FILING_NOT_READY"
    FILING_PACKAGE_REQUIRED = "BILLING_FILING_PACKAGE_REQUIRED"
    UNSUPPORTED_CASE = "BILLING_UNSUPPORTED_CASE"
    REFUND_NOT_ALLOWED = "BILLING_REFUND_NOT_ALLOWED"
    PROVIDER_DISABLED = "BILLING_PROVIDER_DISABLED"
    PROVIDER_OUTCOME_UNKNOWN = "BILLING_PROVIDER_OUTCOME_UNKNOWN"
    DEPENDENCY_UNAVAILABLE = "BILLING_DEPENDENCY_UNAVAILABLE"


class BillingError(DomainError):
    @classmethod
    def invalid(cls) -> BillingError:
        return cls(code=BillingErrorCode.INVALID_INPUT, category=ErrorCategory.INVALID_INPUT)

    @classmethod
    def not_found(cls) -> BillingError:
        return cls(code=BillingErrorCode.NOT_FOUND, category=ErrorCategory.NOT_FOUND)

    @classmethod
    def forbidden(cls) -> BillingError:
        return cls(code=BillingErrorCode.FORBIDDEN, category=ErrorCategory.FORBIDDEN)

    @classmethod
    def step_up_required(cls) -> BillingError:
        return cls(code=BillingErrorCode.STEP_UP_REQUIRED, category=ErrorCategory.FORBIDDEN)

    @classmethod
    def conflict(cls, code: BillingErrorCode) -> BillingError:
        return cls(code=code, category=ErrorCategory.CONFLICT)

    @classmethod
    def precondition(cls, code: BillingErrorCode) -> BillingError:
        return cls(code=code, category=ErrorCategory.PRECONDITION_FAILED)

    @classmethod
    def unavailable(cls, code: BillingErrorCode = BillingErrorCode.DEPENDENCY_UNAVAILABLE) -> BillingError:
        return cls(code=code, category=ErrorCategory.DEPENDENCY_UNAVAILABLE)


@dataclass(frozen=True, slots=True)
class BillingPricing:
    plan: BillingPlan
    monthly_nok: int
    filing_package_nok: int

    def __post_init__(self) -> None:
        if self.monthly_nok <= 0 or self.filing_package_nok <= 0:
            raise BillingError.invalid()


@dataclass(frozen=True, slots=True)
class BillingAccount:
    company_id: CompanyId
    pricing: BillingPricing
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
    updated_by: UserId
    created_at: Timestamp
    updated_at: Timestamp


@dataclass(frozen=True, slots=True)
class BillingPaymentEvent:
    event_id: BillingPaymentEventId
    company_id: CompanyId
    provider: str
    provider_reference: str
    idempotency_key: IdempotencyKey
    kind: BillingPaymentKind
    status: BillingPaymentStatus
    amount_nok: int
    income_year: IncomeYear | None
    created_by: UserId
    created_at: Timestamp
    replayed: bool = False
    obligation: BillingObligation | None = None


@dataclass(frozen=True, slots=True)
class ProductionPilotEntitlement:
    entitlement_id: ProductionPilotEntitlementId
    company_id: CompanyId
    user_id: UserId
    income_year: IncomeYear
    obligation: BillingObligation
    case_profile: BillingPilotCaseProfile
    status: ProductionPilotStatus
    billing_exempt: bool
    system_user_request_id: SystemUserRequestReference
    system_user_external_reference: str
    starts_at: Timestamp
    expires_at: Timestamp
    evidence_reference: str
    approved_by: UserId
    created_at: Timestamp
    updated_at: Timestamp


@dataclass(frozen=True, slots=True)
class BillingEntitlementDecision:
    company_id: CompanyId
    income_year: IncomeYear
    obligation: BillingObligation
    status: BillingStatus
    allowed: bool
    charge_allowed: bool
    readiness_allowed: bool
    billing_exempt: bool
    message: str
    pilot_entitlement_id: ProductionPilotEntitlementId | None = None


@dataclass(frozen=True, slots=True)
class BillingSnapshot:
    accounts: tuple[BillingAccount, ...]
    payment_events: tuple[BillingPaymentEvent, ...]
    pilot_entitlements: tuple[ProductionPilotEntitlement, ...]
    pricing: tuple[BillingPricing, ...] = ()


@dataclass(frozen=True, slots=True)
class _BillingCommand:
    company_id: CompanyId
    actor_id: ActorId
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey


@dataclass(frozen=True, slots=True)
class ConfigureBillingAccountCommand(_BillingCommand):
    pricing_plan: BillingPlan
    founder_cohort_number: int | None = None

    def __post_init__(self) -> None:
        valid_founder = (
            self.pricing_plan is BillingPlan.FOUNDER
            and self.founder_cohort_number is not None
            and 1 <= self.founder_cohort_number <= 100
        )
        if self.pricing_plan is BillingPlan.FOUNDER and not valid_founder:
            raise BillingError.invalid()
        if self.pricing_plan is BillingPlan.STANDARD and self.founder_cohort_number is not None:
            object.__setattr__(self, "founder_cohort_number", None)


@dataclass(frozen=True, slots=True)
class ActivateSubscriptionCommand(_BillingCommand):
    pass


@dataclass(frozen=True, slots=True)
class CancelSubscriptionCommand(_BillingCommand):
    pass


@dataclass(frozen=True, slots=True)
class PurchaseFilingPackageCommand(_BillingCommand):
    income_year: IncomeYear
    obligation: BillingObligation = BillingObligation.SHAREHOLDER_REGISTER


@dataclass(frozen=True, slots=True)
class RefundFilingPackageCommand(_BillingCommand):
    income_year: IncomeYear


@dataclass(frozen=True, slots=True)
class MarkBillingUnsupportedCommand(_BillingCommand):
    reason: str

    def __post_init__(self) -> None:
        reason = self.reason.strip()
        if not reason or len(reason) > 500:
            raise BillingError.invalid()
        object.__setattr__(self, "reason", reason)


@dataclass(frozen=True, slots=True)
class ManageProductionPilotEntitlementCommand(_BillingCommand):
    entitlement_id: ProductionPilotEntitlementId | None
    user_id: UserId
    income_year: IncomeYear
    status: ProductionPilotStatus
    billing_exempt: bool
    system_user_request_id: SystemUserRequestReference
    starts_at: Timestamp
    expires_at: Timestamp
    evidence_reference: str
    obligation: BillingObligation = BillingObligation.SHAREHOLDER_REGISTER
    case_profile: BillingPilotCaseProfile = BillingPilotCaseProfile.RF1086_NO_ACTIVITY_V1

    def __post_init__(self) -> None:
        evidence = self.evidence_reference.strip()
        if (
            self.starts_at.value >= self.expires_at.value
            or not evidence
            or len(evidence) > 1000
            or self.obligation is not BillingObligation.SHAREHOLDER_REGISTER
            or self.case_profile is not BillingPilotCaseProfile.RF1086_NO_ACTIVITY_V1
        ):
            raise BillingError.invalid()
        object.__setattr__(self, "evidence_reference", evidence)


@dataclass(frozen=True, slots=True)
class BillingEntitlementQuery:
    company_id: CompanyId
    actor_id: ActorId
    correlation_id: CorrelationId
    income_year: IncomeYear
    obligation: BillingObligation
    # Queries accept future/unknown profiles and fall back to ordinary billing.
    case_profile: str | None = None


@dataclass(frozen=True, slots=True)
class BillingSnapshotQuery:
    company_ids: tuple[CompanyId, ...]
    actor_id: ActorId
    correlation_id: CorrelationId

    def __post_init__(self) -> None:
        if not 1 <= len(self.company_ids) <= 100 or len(set(self.company_ids)) != len(self.company_ids):
            raise BillingError.invalid()


@dataclass(frozen=True, slots=True)
class BillingProviderIntent:
    company_id: CompanyId
    idempotency_key: IdempotencyKey
    kind: BillingPaymentKind
    amount_nok: int
    income_year: IncomeYear | None
    obligation: BillingObligation | None = None

    def __post_init__(self) -> None:
        if self.amount_nok < 0:
            raise BillingError.invalid()


@dataclass(frozen=True, slots=True)
class BillingProviderResult:
    provider: str
    provider_reference: str
    status: BillingPaymentStatus

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.provider_reference.strip():
            raise BillingError.unavailable()


class AnnualRefundReason(StrEnum):
    CHANGE_OF_MIND = "change_of_mind"
    TALLI_ACCEPTANCE_FAILURE = "talli_acceptance_failure"
    TALLI_DELIVERY_FAILURE = "talli_delivery_failure"
    NEW_UNSUPPORTED_CONDITION = "new_unsupported_condition"
    CUSTOMER_UNRESOLVED = "customer_unresolved"


@dataclass(frozen=True, slots=True)
class AnnualBillingOffer:
    company_id: CompanyId
    income_year: IncomeYear
    offer_version: str
    terms_digest: str
    terms_text: str
    currency: str
    gross_minor: int
    net_minor: int
    vat_minor: int
    vat_basis_points: int
    paid_through: date
    export_through: date
    renewal_date: date
    renewal_reminder_by: date
    price_change_notice_by: date

    def __post_init__(self) -> None:
        if (
            self.currency != "NOK"
            or any(type(value) is not int for value in (
                self.gross_minor, self.net_minor, self.vat_minor, self.vat_basis_points
            ))
            or self.gross_minor <= 0
            or self.net_minor < 0
            or self.vat_minor < 0
            or self.gross_minor != self.net_minor + self.vat_minor
            or self.vat_basis_points != 2500
            or self.vat_minor != (self.gross_minor + 2) // 5
            or self.export_through < self.paid_through + timedelta(days=90)
            or not self.offer_version
            or len(self.terms_digest) != 64
            or not 1 <= len(self.terms_text) <= 20000
            or sha256(self.terms_text.encode()).hexdigest() != self.terms_digest
        ):
            raise BillingError.invalid()


@dataclass(frozen=True, slots=True)
class AnnualRefundFacts:
    reason: AnnualRefundReason
    purchased_at: Timestamp
    first_purchased_at: Timestamp
    accepted_at: Timestamp
    discovered_at: Timestamp
    condition_effective_at: Timestamp
    blocked_at: Timestamp
    income_year: IncomeYear
    gross_minor: int
    refunded_minor: int
    production_submission_at: Timestamp | None
    evidence_reference: str

    def __post_init__(self) -> None:
        if (
            any(type(value) is not int for value in (self.gross_minor, self.refunded_minor))
            or self.gross_minor <= 0
            or not 0 <= self.refunded_minor <= self.gross_minor
            or self.discovered_at.value < self.purchased_at.value
            or self.first_purchased_at.value > self.purchased_at.value
            or self.accepted_at.value > self.purchased_at.value
            or self.condition_effective_at.value > self.discovered_at.value
            or not self.purchased_at.value <= self.blocked_at.value <= self.discovered_at.value
            or not self.evidence_reference.strip()
            or len(self.evidence_reference) > 1000
        ):
            raise BillingError.invalid()
        if (
            self.reason is AnnualRefundReason.NEW_UNSUPPORTED_CONDITION
            and self.condition_effective_at.value <= self.accepted_at.value
        ):
            # A pre-existing condition is never labelled as a new customer fact.
            raise BillingError.invalid()


@dataclass(frozen=True, slots=True)
class AnnualRefundDecision:
    reason: AnnualRefundReason
    total_entitlement_minor: int
    amount_due_minor: int
    vat_due_minor: int
    unused_whole_months: int
    initiate_by: date
    cancel_renewal: bool
    export_available: bool
    message: str


@dataclass(frozen=True, slots=True)
class AnnualRenewalFacts:
    recurring_consent: bool
    renewal_canceled: bool
    reminder_recorded_at: Timestamp | None
    price_change_recorded_at: Timestamp | None
    prior_gross_minor: int
    target_offer: AnnualBillingOffer
    target_definitively_eligible: bool
    target_filing_ready: bool
    collection_due_date: date
    at: Timestamp


@dataclass(frozen=True, slots=True)
class AnnualRenewalDecision:
    allowed: bool
    reason: str


class AnnualProviderOperation(StrEnum):
    CHECKOUT = "checkout"
    RENEWAL = "renewal"
    STOP_AGREEMENT = "stop_agreement"
    CANCEL_CHARGE = "cancel_charge"
    REFUND = "refund"


class AnnualProviderStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AnnualProviderIntent:
    operation_id: BillingPaymentEventId
    company_id: CompanyId
    income_year: IncomeYear
    operation: AnnualProviderOperation
    amount_minor: int
    created_at: Timestamp
    agreement_external_reference: str
    charge_reference: str
    return_url: str
    management_url: str
    agreement_reference: str | None = None
    due_date: date | None = None
    recurring_consent: bool = False
    original_charge_minor: int = 149000
    original_charge_is_renewal: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.amount_minor) is not int
            or self.amount_minor < 0
            or type(self.original_charge_minor) is not int
            or self.original_charge_minor <= 0
            or not isinstance(self.operation, AnnualProviderOperation)
            or type(self.original_charge_is_renewal) is not bool
            or type(self.recurring_consent) is not bool
            or (self.operation is AnnualProviderOperation.CHECKOUT and self.original_charge_is_renewal)
            or (self.operation is AnnualProviderOperation.RENEWAL and not self.original_charge_is_renewal)
            or (self.operation in {AnnualProviderOperation.CHECKOUT, AnnualProviderOperation.RENEWAL} and self.amount_minor != self.original_charge_minor)
            or (self.operation is AnnualProviderOperation.REFUND and self.amount_minor == 0)
            or (self.operation in {AnnualProviderOperation.STOP_AGREEMENT, AnnualProviderOperation.CANCEL_CHARGE} and self.amount_minor != 0)
            or (self.operation is AnnualProviderOperation.REFUND and self.amount_minor > self.original_charge_minor)
            or not self.agreement_external_reference
            or len(self.agreement_external_reference) > 64
            or not self.charge_reference
            or len(self.charge_reference) > 64
            or any(not (char.isascii() and (char.isalnum() or char == "-")) for char in self.charge_reference)
            or (self.operation is not AnnualProviderOperation.CHECKOUT and not self.agreement_reference)
            or (self.operation is AnnualProviderOperation.RENEWAL and self.due_date is None)
        ):
            raise BillingError.invalid()


@dataclass(frozen=True, slots=True)
class AnnualProviderObservation:
    """Verified totals; captured_at identifies the first successful capture."""

    provider: str
    operation: AnnualProviderOperation
    status: AnnualProviderStatus
    agreement_reference: str | None
    charge_reference: str
    amount_minor: int
    captured_minor: int = 0
    refunded_minor: int = 0
    checkout_url: str | None = None
    captured_at: Timestamp | None = None


class AnnualPurchaseStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


class AnnualPurchaseId(_UuidId):
    pass


class AnnualSupportCaseId(_UuidId):
    """Reference to an explicitly opened Company Access billing support case."""


class AnnualOperationStatus(StrEnum):
    CREATED = "created"
    PENDING = "pending"
    UNKNOWN = "unknown"
    CONFIRMED = "confirmed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class AnnualSupportQuery:
    company_id: CompanyId
    support_case_id: AnnualSupportCaseId
    actor_id: ActorId
    before_purchase_id: AnnualPurchaseId | None = None


@dataclass(frozen=True, slots=True)
class AnnualOperationCounts:
    created: int
    pending: int
    unknown: int
    confirmed: int
    failed: int


@dataclass(frozen=True, slots=True)
class AnnualSupportPurchase:
    """Recorded purchase evidence, not an adjudication of new refund rights."""

    purchase_id: AnnualPurchaseId
    company_id: CompanyId
    income_year: IncomeYear
    status: AnnualPurchaseStatus
    accepted_at: Timestamp
    updated_at: Timestamp
    currency: str
    gross_minor: int
    captured_minor: int
    refunded_minor: int
    renewal_canceled_at: Timestamp | None
    paid_through: date
    export_through: date
    recurring_consent: bool
    refund_case_count: int
    recorded_refund_minor: int
    refund_initiate_by: date | None
    refund_request_count: int
    latest_refund_requested_at: Timestamp | None
    refund_operations: AnnualOperationCounts
    cleanup_status: AnnualOperationStatus | None

    @property
    def remaining_refund_minor(self) -> int:
        # Case entitlements are cumulative for the same purchase. Persistence
        # projects their maximum, never their sum, against current settled money.
        return max(0, self.recorded_refund_minor - self.refunded_minor)


@dataclass(frozen=True, slots=True)
class AnnualSupportPage:
    purchases: tuple[AnnualSupportPurchase, ...]
    next_purchase_id: AnnualPurchaseId | None = None


@runtime_checkable
class AnnualSupportReadPersistence(Protocol):
    @property
    def actor_id(self) -> ActorId: ...

    async def read_support_purchases(self, query: AnnualSupportQuery) -> AnnualSupportPage:
        """Recheck current active-admin, opened billing case and fresh MFA.

        Return at most 50 purchases across recorded years in descending
        accepted-at/ID order, with a company-scoped cursor. Authorize empty
        results too. Read totals and related evidence from one database snapshot.
        No owner fallback, case opening, raw source/merchant facts or side effects.
        """
        ...


@dataclass(frozen=True, slots=True)
class StartAnnualCheckoutCommand(_BillingCommand):
    income_year: IncomeYear
    offer_version: str
    terms_digest: str
    purchase_accepted: bool
    recurring_consent: bool
    consent_version: str

    def __post_init__(self) -> None:
        if (
            self.purchase_accepted is not True
            or type(self.recurring_consent) is not bool
            or not self.offer_version or not self.consent_version
            or len(self.terms_digest) != 64
            or any(char not in "0123456789abcdef" for char in self.terms_digest)
            or len(str(self.idempotency_key)) > 200
        ):
            raise BillingError.invalid()


@dataclass(frozen=True, slots=True)
class AnnualCheckoutQuery:
    company_id: CompanyId
    actor_id: ActorId
    purchase_id: AnnualPurchaseId


@dataclass(frozen=True, slots=True)
class AnnualAcceptanceBasisReference:
    company_id: CompanyId
    income_year: IncomeYear
    assessment_id: str
    legal_acceptance_id: str
    admission_id: str
    promise_digest: str
    manifest_digest: str

    def __post_init__(self) -> None:
        try:
            for value in (self.assessment_id, self.legal_acceptance_id, self.admission_id):
                UUID(value)
        except (ValueError, TypeError, AttributeError):
            raise BillingError.invalid() from None
        if any(len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
               for value in (self.promise_digest, self.manifest_digest)):
            raise BillingError.invalid()


@dataclass(frozen=True, slots=True)
class AnnualCheckoutPrerequisites:
    """Server-owned evidence; persistence must verify its current source identity."""

    basis: AnnualAcceptanceBasisReference
    readiness_reference: str
    readiness_digest: str
    evaluated_at: Timestamp
    ready: bool

    def __post_init__(self) -> None:
        if (not self.readiness_reference or len(self.readiness_reference) > 200
                or len(self.readiness_digest) != 64
                or any(char not in "0123456789abcdef" for char in self.readiness_digest)
                or type(self.ready) is not bool):
            raise BillingError.invalid()


@dataclass(frozen=True, slots=True)
class AnnualCheckout:
    purchase_id: AnnualPurchaseId
    offer: AnnualBillingOffer
    accepted_by: UserId
    request_fingerprint: str
    idempotency_key: IdempotencyKey
    provider: str
    provider_account: str
    intent: AnnualProviderIntent
    status: AnnualPurchaseStatus
    observation: AnnualProviderObservation | None = None
    renewal_canceled_at: Timestamp | None = None


@dataclass(frozen=True, slots=True)
class AnnualBillingSnapshotQuery:
    company_id: CompanyId
    income_year: IncomeYear
    actor_id: ActorId
    before_purchase_id: AnnualPurchaseId | None = None


@dataclass(frozen=True, slots=True)
class AnnualPurchaseHistoryQuery:
    company_id: CompanyId
    actor_id: ActorId
    before_purchase_id: AnnualPurchaseId | None = None


@dataclass(frozen=True, slots=True)
class AnnualPurchaseSummary:
    """Stored customer billing facts; no merchant or acceptance-source material."""

    purchase_id: AnnualPurchaseId
    company_id: CompanyId
    income_year: IncomeYear
    status: AnnualPurchaseStatus
    accepted_at: Timestamp
    offer_version: str
    terms_digest: str
    terms_text: str
    currency: str
    gross_minor: int
    net_minor: int
    vat_minor: int
    vat_basis_points: int
    captured_minor: int
    refunded_minor: int
    captured_at: Timestamp | None
    recurring_consent: bool
    renewal_canceled_at: Timestamp | None
    paid_through: date
    export_through: date
    renewal_date: date
    recorded_refund_minor: int
    refund_initiate_by: date | None
    refund_request_count: int
    latest_refund_requested_at: Timestamp | None
    refund_operations: AnnualOperationCounts

    @property
    def remaining_refund_minor(self) -> int:
        return max(0, self.recorded_refund_minor - self.refunded_minor)


@dataclass(frozen=True, slots=True)
class AnnualPurchasePage:
    purchases: tuple[AnnualPurchaseSummary, ...]
    next_purchase_id: AnnualPurchaseId | None = None


@dataclass(frozen=True, slots=True)
class AnnualBillingSnapshot:
    offer: AnnualBillingOffer
    purchases: AnnualPurchasePage


def annual_billing_offer(company_id: CompanyId, income_year: IncomeYear) -> AnnualBillingOffer:
    """Published offer only; availability is not eligibility or charge authority."""
    from talli_backend.modules.billing.annual_policy import annual_offer

    return annual_offer(company_id, income_year)


@runtime_checkable
class AnnualBillingReadPersistence(Protocol):
    @property
    def actor_id(self) -> ActorId: ...

    async def read_purchases(self, query: AnnualBillingSnapshotQuery) -> AnnualPurchasePage:
        """Authorize owner/fresh MFA even for an empty company-year result.

        Read at most 50 stored summaries in descending accepted-at/ID order;
        return a next-purchase cursor when more rows exist. Cursor scope is the
        same company/year. No writes, readiness checks, provider calls or raw
        intent/merchant/acceptance-basis fields belong in this projection.
        Project purchase money and recorded refund evidence in one database
        snapshot. Case entitlements are cumulative: take their maximum, never
        their sum. Requests and operation outcomes do not establish settlement.
        """
        ...

    async def read_purchase_history(self, query: AnnualPurchaseHistoryQuery) -> AnnualPurchasePage:
        """Read stored purchases across years under current owner/fresh MFA.

        Apply the same bounded, provider-free stored-fact projection as
        read_purchases, with a company-scoped cursor and no current-admission
        requirement. History is not an offer or authority to admit another year.
        """
        ...

    async def read_refund_recovery_targets(
        self, query: AnnualRefundRecoveryTargetsQuery,
    ) -> AnnualRefundRecoveryTargetPage:
        """Read at most 50 distinct stored refund operations for one purchase.

        Require current accepted-owner/fresh-MFA authority and filter bound
        receipts to this actor before choosing the earliest receipt per operation.
        Order operation groups by descending immutable created-at/ID. A request
        cursor resolves to its scoped operation, even if its representative has
        changed. No provider/source calls, writes, or current admission checks.
        Targets are selectable receipts, not a statement of refund liability.
        """
        ...


class AnnualCancellationId(_UuidId):
    pass


class AnnualRefundRequestId(_UuidId):
    pass


@dataclass(frozen=True, slots=True)
class AnnualRefundRecoveryTargetsQuery:
    company_id: CompanyId
    purchase_id: AnnualPurchaseId
    actor_id: ActorId
    before_refund_request_id: AnnualRefundRequestId | None = None


@dataclass(frozen=True, slots=True)
class AnnualRefundRecoveryTarget:
    refund_request_id: AnnualRefundRequestId
    requested_at: Timestamp
    status: AnnualOperationStatus


@dataclass(frozen=True, slots=True)
class AnnualRefundRecoveryTargetPage:
    company_id: CompanyId
    purchase_id: AnnualPurchaseId
    income_year: IncomeYear
    targets: tuple[AnnualRefundRecoveryTarget, ...]
    next_refund_request_id: AnnualRefundRequestId | None = None


@dataclass(frozen=True, slots=True)
class CancelAnnualRenewalCommand(_BillingCommand):
    purchase_id: AnnualPurchaseId

    def __post_init__(self) -> None:
        if len(str(self.idempotency_key)) > 200:
            raise BillingError.invalid()


@dataclass(frozen=True, slots=True)
class AnnualRenewalCancellation:
    """Durable local renewal stop; this is not a provider acknowledgement."""

    cancellation_id: AnnualCancellationId
    purchase_id: AnnualPurchaseId
    company_id: CompanyId
    income_year: IncomeYear
    requested_by: UserId
    requested_at: Timestamp
    effective_at: Timestamp
    paid_through: date
    export_through: date


@runtime_checkable
class AnnualCancellationPersistence(Protocol):
    @property
    def actor_id(self) -> ActorId: ...

    async def cancel_renewal(self, command: CancelAnnualRenewalCommand) -> AnnualRenewalCancellation:
        """Atomically preserve request evidence and disable renewal, before I/O.

        Require current owner authority and fresh MFA, but no new eligibility or
        readiness approval. Preserve original consent, purchase state, money and
        paid/export dates. Each command key has an immutable scoped receipt;
        different keys for one purchase retain the original cancellation time.
        """
        ...


@dataclass(frozen=True, slots=True)
class AnnualAgreementCleanup:
    """One durable agreement-stop intent, separate from purchase settlement."""

    purchase_id: AnnualPurchaseId
    cancellation_id: AnnualCancellationId | None
    provider: str
    provider_account: str
    intent: AnnualProviderIntent
    observation: AnnualProviderObservation | None = None
    refund_request_id: AnnualRefundRequestId | None = None

    def __post_init__(self) -> None:
        if ((self.cancellation_id is None) == (self.refund_request_id is None)
                or (self.cancellation_id is not None and not isinstance(self.cancellation_id, AnnualCancellationId))
                or (self.refund_request_id is not None and not isinstance(self.refund_request_id, AnnualRefundRequestId))):
            raise BillingError.invalid()


@dataclass(frozen=True, slots=True)
class AnnualAgreementCleanupClaim:
    cleanup: AnnualAgreementCleanup
    newly_claimed: bool


@runtime_checkable
class AnnualAgreementCleanupPersistence(Protocol):
    @property
    def actor_id(self) -> ActorId: ...

    async def claim_agreement_cleanup(
        self, company_id: CompanyId, purchase_id: AnnualPurchaseId,
    ) -> AnnualAgreementCleanupClaim | None:
        """Require current owner and fresh MFA; lock purchase before operation.

        Bind exactly one persisted cancellation or refund request to the actual
        same-purchase renewal stop. Require a terminal original checkout or exact
        confirmed full cumulative refund evidence for that original charge.
        Neither receipt alone nor an unresolved payment/refund authorizes STOP.
        Defer unsafe unconfirmed cleanup, competing charges or shared agreements
        by returning None; preserve already confirmed cleanup evidence. Never infer
        future agreement/year lineage. Commit one immutable STOP_AGREEMENT
        operation per purchase before returning; all retries reuse its identity,
        provider/account and original references. No eligibility/readiness gate
        may obstruct cancellation. No worker may fabricate an owner session.
        """
        ...

    async def settle_agreement_cleanup(
        self, cleanup: AnnualAgreementCleanup, observation: AnnualProviderObservation,
    ) -> AnnualAgreementCleanup:
        """Reauthorize, lock purchase then operation, and validate latest state.

        Use settle_annual_agreement_cleanup; preserve confirmed terminal state.
        Update only the cleanup operation, never purchase money/status/access.
        Reject changes to the stored intent, receipt, provider or account.
        """
        ...


def settle_annual_agreement_cleanup(
    cleanup: AnnualAgreementCleanup, observation: AnnualProviderObservation,
) -> AnnualAgreementCleanup:
    """Validate cleanup evidence without applying it to financial state."""
    from talli_backend.modules.billing.annual_cleanup import settle_cleanup

    return settle_cleanup(cleanup, observation)


class AnnualAgreementCleanupOperations(Protocol):
    async def cleanup(self, query: AnnualCheckoutQuery) -> AnnualAgreementCleanup | None: ...


def annual_agreement_cleanup_operations(
    persistence: AnnualAgreementCleanupPersistence, provider: AnnualBillingProvider | None,
) -> AnnualAgreementCleanupOperations:
    """Recover the stored agreement stop; absent providers cannot execute it."""
    from talli_backend.modules.billing.annual_cleanup import AnnualAgreementCleanupService

    return AnnualAgreementCleanupService(persistence, provider)


@dataclass(frozen=True, slots=True)
class AnnualCheckoutClaim:
    checkout: AnnualCheckout
    newly_claimed: bool


def settle_annual_checkout(
    checkout: AnnualCheckout, observation: AnnualProviderObservation, at: Timestamp,
) -> AnnualCheckout:
    """Apply billing settlement policy to the latest locked purchase snapshot."""
    from talli_backend.modules.billing.annual_settlement import settle

    return settle(checkout, observation, at)


class AnnualCheckoutOperations(Protocol):
    async def start_checkout(
        self, command: StartAnnualCheckoutCommand,
        prerequisites: Callable[[], Awaitable[AnnualCheckoutPrerequisites]],
    ) -> AnnualCheckout: ...

    async def poll_checkout(self, query: AnnualCheckoutQuery) -> AnnualCheckout: ...


def annual_checkout_operations(
    persistence: AnnualCheckoutPersistence, provider: AnnualBillingProvider | None,
    *, return_url: str, management_url: str,
) -> AnnualCheckoutOperations:
    """Compose the single checkout policy path; an absent provider fails closed."""
    from talli_backend.modules.billing.annual_service import AnnualCheckoutService

    return AnnualCheckoutService(
        persistence, provider, return_url=return_url, management_url=management_url,
    )


@runtime_checkable
class AnnualCheckoutPersistence(Protocol):
    @property
    def actor_id(self) -> ActorId: ...

    async def authorize_owner_command(self, company_id: CompanyId) -> None: ...

    async def find_checkout(self, company_id: CompanyId, key: IdempotencyKey) -> AnnualCheckout | None: ...

    async def claim_checkout(
        self, checkout: AnnualCheckout, prerequisites: AnnualCheckoutPrerequisites,
    ) -> AnnualCheckoutClaim:
        """Commit purchase and original operation atomically; only one caller wins."""
        ...

    async def load_checkout(self, company_id: CompanyId, purchase_id: AnnualPurchaseId) -> AnnualCheckout: ...

    async def settle_checkout(
        self, checkout: AnnualCheckout, observation: AnnualProviderObservation,
    ) -> AnnualCheckout:
        """Lock purchase then operation and validate against that latest state.

        Preserve terminal states, bound agreement references and reject stale totals/timestamps. Confirmed
        full capture refunded in full produces REFUNDED; partial captures stay
        unresolved even when refunded so far. Only confirmed full capture with an
        outstanding paid balance produces PAID. Never return stale caller state.
        """
        ...


class AnnualRefundCaseId(_UuidId):
    pass


@dataclass(frozen=True, slots=True)
class RequestAnnualRefundCommand(_BillingCommand):
    purchase_id: AnnualPurchaseId
    source_reference: str

    def __post_init__(self) -> None:
        # A lookup key only, never caller-supplied refund eligibility or money.
        if (not isinstance(self.source_reference, str) or not self.source_reference.strip()
                or len(self.source_reference) > 1000 or len(str(self.idempotency_key)) > 200):
            raise BillingError.invalid()


@dataclass(frozen=True, slots=True)
class AnnualRefundOperation:
    """Immutable claim-time capture basis; later observation totals may grow."""

    purchase_id: AnnualPurchaseId
    captured_minor: int
    provider: str
    provider_account: str
    intent: AnnualProviderIntent
    previous_refunded_minor: int
    captured_at: Timestamp
    observation: AnnualProviderObservation | None = None


@dataclass(frozen=True, slots=True)
class AnnualRefundResolution:
    case_id: AnnualRefundCaseId
    request: RequestAnnualRefundCommand
    source_digest: str
    facts: AnnualRefundFacts
    decision: AnnualRefundDecision
    operation: AnnualRefundOperation | None = None


@dataclass(frozen=True, slots=True)
class AnnualRefundClaim:
    resolution: AnnualRefundResolution
    newly_claimed: bool


@dataclass(frozen=True, slots=True)
class AnnualRefundRecoveryQuery:
    company_id: CompanyId
    purchase_id: AnnualPurchaseId
    refund_request_id: AnnualRefundRequestId
    actor_id: ActorId


@dataclass(frozen=True, slots=True)
class AnnualRefundRecovery:
    refund_request_id: AnnualRefundRequestId
    resolution: AnnualRefundResolution


class AnnualRefundRecoveryPersistence(Protocol):
    @property
    def actor_id(self) -> ActorId: ...

    async def load_refund_recovery(self, query: AnnualRefundRecoveryQuery) -> AnnualRefundRecovery:
        """Load this current accepted owner's already operation-bound request.

        Require fresh MFA and owner authority, including after lock waits; opened
        support access cannot substitute. Lock purchase before request/operation.
        Bind request ID, actor, company, purchase, year, case, fingerprint and
        original provider intent. Validate immutable source digest/facts/decision.
        Preserve stored source, key and correlation; never resolve current source
        facts, insert a case/request/operation, or assign an unbound operation.
        Historical owner-role provenance is not inferred from requested_by.
        """
        ...

    async def settle_refund_recovery(
        self, recovery: AnnualRefundRecovery, observation: AnnualProviderObservation,
    ) -> AnnualRefundRecovery:
        """Reauthorize the same owner with fresh MFA, reload and lock exact identity.

        Reject immutable envelope changes; only stored observation may advance.
        Apply settle_annual_refund against current state and atomically preserve
        monotonic purchase money and terminal operation evidence. No allocation,
        source resolution or support fallback is permitted, including on retry.
        """
        ...


class AnnualRefundRecoveryOperations(Protocol):
    async def recover_refund(self, query: AnnualRefundRecoveryQuery) -> AnnualRefundRecovery: ...


def annual_refund_recovery_operations(
    persistence: AnnualRefundRecoveryPersistence, provider: AnnualBillingProvider | None,
) -> AnnualRefundRecoveryOperations:
    """Reconcile only the original operation of a stored owner request."""
    from talli_backend.modules.billing.annual_refund import AnnualRefundRecoveryService

    return AnnualRefundRecoveryService(persistence, provider)


class AnnualRefundPersistence(Protocol):
    @property
    def actor_id(self) -> ActorId: ...

    async def claim_refund(self, command: RequestAnnualRefundCommand) -> AnnualRefundClaim:
        """Reauthorize current owner or explicitly opened billing support case, with fresh MFA.

        Support additionally needs an active admin and current same-company billing
        grant/opening; a case ID alone grants nothing. Owner-created cases remain
        limited to change of mind; creating other reasons requires support-case
        authority. An owner may recover a previously recorded case without
        re-adjudicating its immutable liability.

        Resolve the lookup reference to immutable source-owned incident, purchase,
        first-purchase and production-submission facts; never trust browser facts
        or mutable legacy readiness. Unavailable source authority fails closed.
        Claim under purchase-before-operation locks. Revalidate source identity,
        company/year, original capture and current refund balance before commit.
        Billing's annual_refund_decision owns policy; retain source digest/facts,
        liability, five-business-day initiation deadline and an immediate local
        renewal stop even when no provider can execute. Retain export/records.

        Exact command replay preserves the original case and intent, rejecting a
        reused key with changed actor/company/purchase/source. A unique source case
        must not create duplicate liability. Reserve against every pending/unknown
        refund and current cumulative refunds; return no operation when no amount
        is owed or another operation defers it. No operation is NOT settlement.
        Cap the reserved amount at actual captured money as well as policy entitlement;
        a partial capture keeps the original full charge identity. Failed operations
        retain terminal evidence and outstanding liability; a later authorized
        attempt requires a distinct operation and a fresh balance/reservation check.
        Only the caller winning a newly committed operation may execute it.
        No worker may fabricate an owner session; worker and support-case authority
        need their own explicit implementations before those callers are wired.
        """
        ...

    async def settle_refund(
        self, resolution: AnnualRefundResolution, observation: AnnualProviderObservation,
    ) -> AnnualRefundResolution:
        """Reauthorize, lock purchase then operation, and settle against latest state.

        Use settle_annual_refund. Commit operation evidence and monotonic original
        purchase totals atomically; do not increment money from the caller's stale
        snapshot or duplicate operation success. Preserve the first capture,
        original money, cancellation, liability and export dates. Only confirmed
        full cumulative refund changes paid purchase status to refunded.
        Unknown effects and overdue initiation remain actionable, never a waiver.
        """
        ...


def annual_refund_decision(facts: AnnualRefundFacts) -> AnnualRefundDecision:
    from talli_backend.modules.billing.annual_policy import annual_refund

    return annual_refund(facts)


def settle_annual_refund(
    resolution: AnnualRefundResolution, observation: AnnualProviderObservation,
    at: Timestamp,
) -> AnnualRefundResolution:
    from talli_backend.modules.billing.annual_refund import settle_refund

    return settle_refund(resolution, observation, at)


@runtime_checkable
class AnnualBillingProvider(Protocol):
    provider: str
    account_reference: str
    production_enabled: bool

    async def execute(self, intent: AnnualProviderIntent) -> AnnualProviderObservation:
        """Execute only after durable single-winner intent claim."""
        ...

    async def reconcile(self, intent: AnnualProviderIntent) -> AnnualProviderObservation:
        """Observe original references using reads only; absence remains unknown."""
        ...


@runtime_checkable
class BillingPaymentProvider(Protocol):
    provider: str
    production_enabled: bool

    async def execute(self, intent: BillingProviderIntent) -> BillingProviderResult: ...

    async def reconcile(self, intent: BillingProviderIntent) -> BillingProviderResult | None:
        """Read the outcome for the original key without issuing another payment.

        None means that the provider cannot yet establish an outcome. Implementations
        must never interpret an absent response as permission to execute again.
        """
        ...


class BillingPersistence(Protocol):
    async def authorize_entitlement_query(self, company_id: CompanyId) -> None: ...

    async def authorize_owner_command(self, company_id: CompanyId) -> None: ...

    async def authorize_admin_command(self) -> None: ...

    async def find_account(self, company_id: CompanyId) -> BillingAccount | None: ...

    async def filing_ready(
        self, company_id: CompanyId, income_year: IncomeYear, obligation: BillingObligation
    ) -> bool: ...

    async def find_active_pilot_entitlement(
        self,
        *,
        company_id: CompanyId,
        user_id: UserId,
        income_year: IncomeYear,
        obligation: BillingObligation,
        case_profile: str,
        at: datetime,
    ) -> ProductionPilotEntitlement | None: ...

    async def snapshot(self, query: BillingSnapshotQuery) -> BillingSnapshot: ...

    async def find_payment_event(
        self,
        *,
        company_id: CompanyId,
        idempotency_key: IdempotencyKey,
        kind: BillingPaymentKind,
        income_year: IncomeYear | None,
        obligation: BillingObligation | None = None,
    ) -> BillingPaymentEvent | None: ...

    async def configure_account(
        self, command: ConfigureBillingAccountCommand, pricing: BillingPricing
    ) -> BillingAccount: ...

    async def begin_provider_event(
        self,
        command: ActivateSubscriptionCommand | CancelSubscriptionCommand | PurchaseFilingPackageCommand | RefundFilingPackageCommand,
        provider: str,
        amount_nok: int,
    ) -> BillingPaymentEvent:
        """Commit the intent before I/O; an existing key returns replayed=True."""
        ...

    async def complete_provider_event(
        self,
        command: ActivateSubscriptionCommand | CancelSubscriptionCommand | PurchaseFilingPackageCommand | RefundFilingPackageCommand,
        result: BillingProviderResult,
        amount_nok: int,
    ) -> BillingPaymentEvent: ...

    async def mark_unsupported(
        self, command: MarkBillingUnsupportedCommand
    ) -> BillingAccount: ...

    async def manage_pilot_entitlement(
        self, command: ManageProductionPilotEntitlementCommand
    ) -> ProductionPilotEntitlement: ...


class BillingCommands(Protocol):
    async def configure_account(self, command: ConfigureBillingAccountCommand) -> BillingAccount: ...

    async def activate_subscription(self, command: ActivateSubscriptionCommand) -> BillingPaymentEvent: ...

    async def cancel_subscription(self, command: CancelSubscriptionCommand) -> BillingPaymentEvent: ...

    async def purchase_filing_package(self, command: PurchaseFilingPackageCommand) -> BillingPaymentEvent: ...

    async def refund_filing_package(self, command: RefundFilingPackageCommand) -> BillingPaymentEvent: ...

    async def mark_unsupported(self, command: MarkBillingUnsupportedCommand) -> BillingAccount: ...

    async def manage_pilot_entitlement(
        self, command: ManageProductionPilotEntitlementCommand
    ) -> ProductionPilotEntitlement: ...


class BillingQueries(Protocol):
    async def snapshot(self, query: BillingSnapshotQuery) -> BillingSnapshot: ...

    async def entitlement(self, query: BillingEntitlementQuery) -> BillingEntitlementDecision: ...


Adapter = TypeVar("Adapter", bound=Callable[..., object])


def billing_persistence_adapter(port: type[object]) -> Callable[[Adapter], Adapter]:
    def register(adapter: Adapter) -> Adapter:
        setattr(adapter, "__talli_port__", port)  # noqa: B010
        return adapter

    return register


def billing_provider_adapter(port: type[object]) -> Callable[[Adapter], Adapter]:
    def register(adapter: Adapter) -> Adapter:
        setattr(adapter, "__talli_port__", port)  # noqa: B010
        return adapter

    return register


__all__ = [
    "AnnualBillingSnapshotQuery",
    "AnnualPurchaseHistoryQuery",
    "AnnualPurchaseSummary",
    "AnnualPurchasePage",
    "AnnualSupportCaseId",
    "AnnualOperationStatus",
    "AnnualOperationCounts",
    "AnnualSupportQuery",
    "AnnualSupportPurchase",
    "AnnualSupportPage",
    "AnnualSupportReadPersistence",
    "AnnualBillingSnapshot",
    "annual_billing_offer",
    "AnnualBillingReadPersistence",
    "AnnualAgreementCleanup",
    "AnnualAgreementCleanupClaim",
    "AnnualAgreementCleanupPersistence",
    "AnnualAgreementCleanupOperations",
    "annual_agreement_cleanup_operations",
    "settle_annual_agreement_cleanup",
    "AnnualCancellationId",
    "AnnualRefundRequestId",
    "AnnualCancellationPersistence",
    "AnnualRenewalCancellation",
    "CancelAnnualRenewalCommand",
    "settle_annual_checkout",
    "AnnualCheckoutOperations",
    "annual_checkout_operations",
    "AnnualPurchaseStatus",
    "AnnualCheckoutPersistence",
    "AnnualCheckoutClaim",
    "AnnualCheckout",
    "AnnualCheckoutPrerequisites",
    "AnnualAcceptanceBasisReference",
    "AnnualCheckoutQuery",
    "StartAnnualCheckoutCommand",
    "AnnualPurchaseId",
    "AnnualBillingProvider",
    "AnnualBillingOffer",
    "AnnualRefundDecision",
    "AnnualRefundCaseId",
    "RequestAnnualRefundCommand",
    "AnnualRefundOperation",
    "AnnualRefundResolution",
    "AnnualRefundClaim",
    "AnnualRefundRecoveryTargetsQuery",
    "AnnualRefundRecoveryTarget",
    "AnnualRefundRecoveryTargetPage",
    "AnnualRefundRecoveryQuery",
    "AnnualRefundRecovery",
    "AnnualRefundRecoveryPersistence",
    "AnnualRefundRecoveryOperations",
    "annual_refund_recovery_operations",
    "AnnualRefundPersistence",
    "annual_refund_decision",
    "settle_annual_refund",
    "AnnualRefundFacts",
    "AnnualRefundReason",
    "AnnualRenewalDecision",
    "AnnualRenewalFacts",
    "AnnualProviderIntent",
    "AnnualProviderObservation",
    "AnnualProviderOperation",
    "AnnualProviderStatus",
    "ActivateSubscriptionCommand",
    "BillingAccount",
    "BillingCommands",
    "BillingEntitlementDecision",
    "BillingEntitlementQuery",
    "BillingError",
    "BillingErrorCode",
    "BillingObligation",
    "BillingPaymentEvent",
    "BillingPaymentEventId",
    "BillingPaymentKind",
    "BillingPaymentProvider",
    "BillingPaymentStatus",
    "BillingPersistence",
    "BillingPlan",
    "BillingPilotCaseProfile",
    "BillingPricing",
    "BillingProviderIntent",
    "BillingProviderResult",
    "BillingQueries",
    "BillingSnapshot",
    "BillingSnapshotQuery",
    "BillingStatus",
    "CancelSubscriptionCommand",
    "ConfigureBillingAccountCommand",
    "ManageProductionPilotEntitlementCommand",
    "MarkBillingUnsupportedCommand",
    "ProductionPilotEntitlement",
    "ProductionPilotEntitlementId",
    "ProductionPilotStatus",
    "PurchaseFilingPackageCommand",
    "RefundFilingPackageCommand",
    "SystemUserRequestReference",
    "billing_persistence_adapter",
    "billing_provider_adapter",
    "expected_payment_status",
]
