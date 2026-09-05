"""Stable public contract for plans, payments, refunds, and filing entitlement."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
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


@dataclass(frozen=True, slots=True)
class ProductionPilotEntitlement:
    entitlement_id: ProductionPilotEntitlementId
    company_id: CompanyId
    user_id: UserId
    income_year: IncomeYear
    obligation: BillingObligation
    case_profile: str
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
            raise BillingError.invalid()


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
    case_profile: str = "rf1086_no_activity_v1"

    def __post_init__(self) -> None:
        evidence = self.evidence_reference.strip()
        if (
            self.starts_at.value >= self.expires_at.value
            or not evidence
            or len(evidence) > 1000
            or self.obligation is not BillingObligation.SHAREHOLDER_REGISTER
            or self.case_profile != "rf1086_no_activity_v1"
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


@runtime_checkable
class BillingPaymentProvider(Protocol):
    provider: str
    production_enabled: bool

    async def execute(self, intent: BillingProviderIntent) -> BillingProviderResult: ...


class BillingPersistence(Protocol):
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
    ) -> BillingPaymentEvent | None: ...

    async def configure_account(
        self, command: ConfigureBillingAccountCommand, pricing: BillingPricing
    ) -> BillingAccount: ...

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
