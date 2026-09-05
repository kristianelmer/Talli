from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Never

import pytest

from talli_backend.adapters.simulation_billing import SimulationBillingProvider
from talli_backend.modules.billing.public import (
    ActivateSubscriptionCommand,
    BillingAccount,
    BillingError,
    BillingErrorCode,
    BillingPaymentKind,
    BillingPaymentStatus,
    BillingPlan,
    BillingStatus,
    CancelSubscriptionCommand,
    ConfigureBillingAccountCommand,
    ProductionPilotEntitlement,
    ProductionPilotEntitlementId,
    ProductionPilotStatus,
    PurchaseFilingPackageCommand,
    RefundFilingPackageCommand,
    SystemUserRequestReference,
)
from talli_backend.modules.billing.service import BillingService, billing_entitlement_decision
from talli_backend.shared.kernel import IncomeYear, Timestamp

from test_billing import COMPANY_ID, USER_ID, MemoryPersistence, NOW, account, metadata, query


# Frozen semantic oracle from the exact migration baseline
# 4f807fe4239a208c573054b14cbed478277d1a2e:
# apps/web/app/lib/billing.ts and apps/web/app/lib/production-pilot.ts.
# It remains test-only so the predecessor cannot become an application path.
@dataclass(frozen=True)
class _LegacyAccount:
    company_id: str
    pricing_plan: str
    monthly_nok: int
    filing_package_nok: int
    founder_cohort_number: int | None
    subscription_active: bool
    filing_package_paid: bool
    supported_case: bool
    refund_eligible: bool
    refund_completed: bool = False
    no_charge_reason: str | None = None
    provider_customer_ref: str | None = None
    subscription_provider_ref: str | None = None
    filing_package_payment_ref: str | None = None
    refund_provider_ref: str | None = None


@dataclass(frozen=True)
class _LegacyEvent:
    provider: str
    provider_reference: str
    idempotency_key: str
    kind: str
    status: str
    amount_nok: int
    income_year: int | None


class _LegacyValidationError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


def _legacy_pricing(plan: str) -> tuple[int, int]:
    return (29, 299) if plan == "founder" else (49, 499)


def _legacy_build_account(
    *,
    company_id: str = str(COMPANY_ID),
    pricing_plan: str,
    founder_cohort_number: int | None = None,
    subscription_active: bool = False,
    filing_package_paid: bool = False,
    supported_case: bool | None = None,
    refund_eligible: bool = False,
    no_charge_reason: str | None = None,
) -> _LegacyAccount:
    if not company_id:
        raise _LegacyValidationError("missing_company")
    if pricing_plan not in ("founder", "standard"):
        raise _LegacyValidationError("invalid_pricing_plan")
    cohort = founder_cohort_number if pricing_plan == "founder" else None
    if pricing_plan == "founder" and not (
        isinstance(cohort, int) and not isinstance(cohort, bool) and 1 <= cohort <= 100
    ):
        raise _LegacyValidationError("founder_cohort_limit")
    monthly_nok, filing_package_nok = _legacy_pricing(pricing_plan)
    return _LegacyAccount(
        company_id=company_id,
        pricing_plan=pricing_plan,
        monthly_nok=monthly_nok,
        filing_package_nok=filing_package_nok,
        founder_cohort_number=cohort,
        subscription_active=subscription_active,
        filing_package_paid=filing_package_paid,
        supported_case=True if supported_case is None else supported_case,
        refund_eligible=refund_eligible,
        no_charge_reason=no_charge_reason,
    )


def _legacy_gate(value: _LegacyAccount, filing_ready: bool) -> dict[str, object]:
    if value.refund_eligible:
        return {
            "status": "refund_eligible",
            "allowed": False,
            "charge_allowed": False,
            "message": "Filingpakken er markert refusjonsberettiget etter støttet feil.",
        }
    if not value.supported_case:
        return {
            "status": "unsupported_case",
            "allowed": False,
            "charge_allowed": False,
            "message": value.no_charge_reason
            or "Saken er utenfor Talli-støtte. Ikke ta betalt for filingpakke.",
        }
    if not value.subscription_active:
        return {
            "status": "subscription_required",
            "allowed": False,
            "charge_allowed": False,
            "message": "Aktivt abonnement kreves før produksjonsfiling.",
        }
    if not filing_ready:
        return {
            "status": "active",
            "allowed": False,
            "charge_allowed": False,
            "message": "Filing readiness må være klar før filingpakke kan betales.",
        }
    if not value.filing_package_paid:
        return {
            "status": "filing_package_required",
            "allowed": False,
            "charge_allowed": True,
            "message": "Filingpakke må betales før produksjonsinnsending.",
        }
    return {
        "status": "ready_for_production_filing",
        "allowed": True,
        "charge_allowed": False,
        "message": "Billing og filing readiness er klare.",
    }


def _legacy_event(
    value: _LegacyAccount,
    *,
    kind: str,
    amount_nok: int,
    income_year: int | None = None,
    status: str | None = None,
) -> _LegacyEvent:
    year_part = f"-{income_year}" if income_year else ""
    reference_year_part = f"_{income_year}" if income_year else ""
    return _LegacyEvent(
        provider="simulation",
        provider_reference=f"sim_{kind}_{value.company_id}{reference_year_part}",
        idempotency_key=f"billing-{value.company_id}-{kind}{year_part}",
        kind=kind,
        status=status or "succeeded",
        amount_nok=amount_nok,
        income_year=income_year,
    )


def _legacy_apply(value: _LegacyAccount, event: _LegacyEvent) -> _LegacyAccount:
    if event.kind == "subscription":
        return replace(
            value,
            provider_customer_ref=value.provider_customer_ref
            or f"sim_customer_{value.company_id}",
            subscription_provider_ref=event.provider_reference,
            subscription_active=event.status == "succeeded",
        )
    if event.kind == "subscription_cancellation":
        if event.status not in ("canceled", "succeeded"):
            return value
        return replace(
            value,
            subscription_active=False,
            subscription_provider_ref=event.provider_reference,
        )
    if event.kind == "filing_package":
        if event.status != "succeeded":
            return replace(value, filing_package_paid=False)
        return replace(
            value,
            filing_package_payment_ref=event.provider_reference,
            filing_package_paid=True,
            refund_eligible=False,
        )
    if event.status not in ("refunded", "succeeded"):
        return value
    return replace(
        value,
        refund_provider_ref=event.provider_reference,
        refund_completed=True,
        refund_eligible=False,
    )


def _legacy_pilot_allowed(
    entitlement: ProductionPilotEntitlement | None,
    *,
    at: Timestamp = NOW,
) -> bool:
    if entitlement is None:
        return False
    return (
        entitlement.company_id == COMPANY_ID
        and entitlement.user_id == USER_ID
        and entitlement.income_year == IncomeYear(2025)
        and entitlement.obligation.value == "aksjonaerregisteroppgaven"
        and entitlement.case_profile == "rf1086_no_activity_v1"
        and entitlement.status is ProductionPilotStatus.ACTIVE
        and entitlement.starts_at.value <= at.value < entitlement.expires_at.value
    )


def _canonical_account_facts(value: BillingAccount) -> dict[str, object]:
    return {
        "company_id": str(value.company_id),
        "pricing_plan": value.pricing.plan.value,
        "monthly_nok": value.pricing.monthly_nok,
        "filing_package_nok": value.pricing.filing_package_nok,
        "founder_cohort_number": value.founder_cohort_number,
        "subscription_active": value.subscription_active,
        "filing_package_paid": value.filing_package_paid,
        "supported_case": value.supported_case,
        "refund_eligible": value.refund_eligible,
        "refund_completed": value.refund_completed,
        "no_charge_reason": value.no_charge_reason,
        "provider_customer_ref": value.provider_customer_reference,
        "subscription_provider_ref": value.subscription_provider_reference,
        "filing_package_payment_ref": value.filing_package_payment_reference,
        "refund_provider_ref": value.refund_provider_reference,
    }


def _legacy_account_facts(value: _LegacyAccount) -> dict[str, object]:
    return dict(value.__dict__)


def _canonical_error(action) -> str | None:
    try:
        action()
    except BillingError as error:
        return str(error.code)
    return None


def _legacy_error(action) -> str | None:
    try:
        action()
    except _LegacyValidationError as error:
        return error.code
    return None


@pytest.mark.parametrize(
    ("plan", "cohort"),
    [
        (BillingPlan.FOUNDER, 1),
        (BillingPlan.FOUNDER, 100),
        (BillingPlan.STANDARD, None),
        (BillingPlan.STANDARD, 100),
    ],
)
def test_predecessor_and_successor_match_plan_prices_and_defaults(
    plan: BillingPlan, cohort: int | None
) -> None:
    predecessor = _legacy_build_account(
        pricing_plan=plan.value, founder_cohort_number=cohort
    )
    persistence = MemoryPersistence(
        account(
            subscription_active=True,
            filing_package_paid=True,
            supported_case=False,
            refund_eligible=True,
            refund_completed=True,
            no_charge_reason="stale",
            provider_customer_reference="stale-customer",
            subscription_provider_reference="stale-subscription",
            filing_package_payment_reference="stale-package",
            refund_provider_reference="stale-refund",
        )
    )
    successor = asyncio.run(
        BillingService(
            persistence, SimulationBillingProvider(), now=lambda: NOW.value
        ).configure_account(
            ConfigureBillingAccountCommand(
                **metadata(f"equivalence-{plan.value}-{cohort}"),
                pricing_plan=plan,
                founder_cohort_number=cohort,
            )
        )
    )

    assert _canonical_account_facts(successor) == _legacy_account_facts(predecessor)


@pytest.mark.parametrize(
    ("cohort", "legacy_code"),
    [(None, "founder_cohort_limit"), (0, "founder_cohort_limit"), (101, "founder_cohort_limit")],
)
def test_predecessor_validation_errors_map_to_one_public_billing_code(
    cohort: int | None, legacy_code: str
) -> None:
    predecessor = _legacy_error(
        lambda: _legacy_build_account(
            pricing_plan="founder", founder_cohort_number=cohort
        )
    )
    successor = _canonical_error(
        lambda: ConfigureBillingAccountCommand(
            **metadata(f"equivalence-invalid-{cohort}"),
            pricing_plan=BillingPlan.FOUNDER,
            founder_cohort_number=cohort,
        )
    )

    assert predecessor == legacy_code
    assert successor == BillingErrorCode.INVALID_INPUT


_NORWEGIAN_SUCCESSOR_MESSAGES = {
    "Filingpakken er markert refusjonsberettiget etter støttet feil.": (
        "Innsendingspakken kan refunderes etter en støttet feil."
    ),
    "Saken er utenfor Talli-støtte. Ikke ta betalt for filingpakke.": (
        "Saken er utenfor Talli-støtte."
    ),
    "Aktivt abonnement kreves før produksjonsfiling.": (
        "Aktivt abonnement kreves før produksjonsinnsending."
    ),
    "Filing readiness må være klar før filingpakke kan betales.": (
        "Innsendingskontrollen må være klar før innsendingspakken kan betales."
    ),
    "Filingpakke må betales før produksjonsinnsending.": (
        "Innsendingspakken må betales før produksjonsinnsending."
    ),
    "Billing og filing readiness er klare.": "Fakturering og innsendingsrett er klare.",
}


@pytest.mark.parametrize(
    ("account_changes", "filing_ready"),
    [
        ({"refund_eligible": True}, True),
        ({"supported_case": False}, True),
        ({}, True),
        ({"subscription_active": True}, False),
        ({"subscription_active": True}, True),
        ({"subscription_active": True, "filing_package_paid": True}, True),
    ],
)
def test_predecessor_and_successor_match_every_entitlement_result(
    account_changes: dict[str, object], filing_ready: bool
) -> None:
    predecessor_account = _legacy_build_account(
        pricing_plan="standard", **account_changes
    )
    predecessor = _legacy_gate(predecessor_account, filing_ready)
    successor = billing_entitlement_decision(
        query(), account(**account_changes), filing_ready=filing_ready
    )

    assert successor.status.value == predecessor["status"]
    assert successor.allowed is predecessor["allowed"]
    assert successor.charge_allowed is predecessor["charge_allowed"]
    assert successor.readiness_allowed is (
        successor.status
        not in (
            BillingStatus.REFUND_ELIGIBLE,
            BillingStatus.UNSUPPORTED_CASE,
            BillingStatus.SUBSCRIPTION_REQUIRED,
        )
    )
    assert successor.billing_exempt is False
    assert successor.pilot_entitlement_id is None
    assert successor.message == _NORWEGIAN_SUCCESSOR_MESSAGES[predecessor["message"]]


@pytest.mark.parametrize(
    ("account_changes", "filing_ready", "legacy_status", "successor_code"),
    [
        ({"refund_eligible": True}, True, "refund_eligible", BillingErrorCode.REFUND_NOT_ALLOWED),
        ({"supported_case": False}, True, "unsupported_case", BillingErrorCode.UNSUPPORTED_CASE),
        ({}, True, "subscription_required", BillingErrorCode.SUBSCRIPTION_REQUIRED),
        ({"subscription_active": True}, False, "active", BillingErrorCode.FILING_NOT_READY),
    ],
)
def test_predecessor_blocked_gates_map_to_successor_coded_errors(
    account_changes: dict[str, object],
    filing_ready: bool,
    legacy_status: str,
    successor_code: BillingErrorCode,
) -> None:
    predecessor = _legacy_gate(
        _legacy_build_account(pricing_plan="standard", **account_changes),
        filing_ready,
    )
    persistence = MemoryPersistence(account(**account_changes), ready=filing_ready)
    service = BillingService(
        persistence, SimulationBillingProvider(), now=lambda: NOW.value
    )
    command = PurchaseFilingPackageCommand(
        **metadata(f"equivalence-gate-{legacy_status}"), income_year=IncomeYear(2025)
    )

    with pytest.raises(BillingError) as blocked:
        asyncio.run(service.purchase_filing_package(command))

    assert predecessor["status"] == legacy_status
    assert predecessor["allowed"] is False
    assert blocked.value.code == successor_code
    assert persistence.events == {}


def test_predecessor_missing_account_failure_maps_to_successor_not_found() -> None:
    predecessor_message = "Billingkonto mangler"
    persistence = MemoryPersistence()
    service = BillingService(
        persistence, SimulationBillingProvider(), now=lambda: NOW.value
    )

    with pytest.raises(BillingError) as missing:
        asyncio.run(
            service.activate_subscription(
                ActivateSubscriptionCommand(**metadata("equivalence-missing-account"))
            )
        )

    assert predecessor_message == "Billingkonto mangler"
    assert missing.value.code == BillingErrorCode.NOT_FOUND
    assert persistence.events == {}


@pytest.mark.parametrize(
    ("kind", "status", "amount", "year"),
    [
        (BillingPaymentKind.SUBSCRIPTION, BillingPaymentStatus.SUCCEEDED, 49, None),
        (
            BillingPaymentKind.SUBSCRIPTION_CANCELLATION,
            BillingPaymentStatus.CANCELED,
            0,
            None,
        ),
        (BillingPaymentKind.FILING_PACKAGE, BillingPaymentStatus.SUCCEEDED, 499, 2025),
        (BillingPaymentKind.REFUND, BillingPaymentStatus.REFUNDED, 499, 2025),
    ],
)
def test_predecessor_and_successor_match_provider_events_and_database_effects(
    kind: BillingPaymentKind,
    status: BillingPaymentStatus,
    amount: int,
    year: int | None,
) -> None:
    initial = account(
        subscription_active=kind is not BillingPaymentKind.SUBSCRIPTION,
        filing_package_paid=kind is BillingPaymentKind.REFUND,
        refund_eligible=kind is BillingPaymentKind.REFUND,
    )
    predecessor_initial = _legacy_build_account(
        pricing_plan="standard",
        subscription_active=initial.subscription_active,
        filing_package_paid=initial.filing_package_paid,
        refund_eligible=initial.refund_eligible,
    )
    predecessor_event = _legacy_event(
        predecessor_initial,
        kind=kind.value,
        amount_nok=amount,
        income_year=year,
        status=status.value,
    )
    predecessor_after = _legacy_apply(predecessor_initial, predecessor_event)

    persistence = MemoryPersistence(initial, ready=True)
    service = BillingService(
        persistence, SimulationBillingProvider(), now=lambda: NOW.value
    )
    command_by_kind = {
        BillingPaymentKind.SUBSCRIPTION: (
            service.activate_subscription,
            ActivateSubscriptionCommand(**metadata("equivalence-subscription")),
        ),
        BillingPaymentKind.SUBSCRIPTION_CANCELLATION: (
            service.cancel_subscription,
            CancelSubscriptionCommand(**metadata("equivalence-cancellation")),
        ),
        BillingPaymentKind.FILING_PACKAGE: (
            service.purchase_filing_package,
            PurchaseFilingPackageCommand(
                **metadata("equivalence-package"), income_year=IncomeYear(2025)
            ),
        ),
        BillingPaymentKind.REFUND: (
            service.refund_filing_package,
            RefundFilingPackageCommand(
                **metadata("equivalence-refund"), income_year=IncomeYear(2025)
            ),
        ),
    }
    operation, command = command_by_kind[kind]
    successor_event = asyncio.run(operation(command))
    assert persistence.account is not None

    assert successor_event.provider == predecessor_event.provider
    assert successor_event.provider_reference == predecessor_event.provider_reference
    assert successor_event.kind.value == predecessor_event.kind
    assert successor_event.status.value == predecessor_event.status
    assert successor_event.amount_nok == predecessor_event.amount_nok
    assert (
        int(successor_event.income_year)
        if successor_event.income_year is not None
        else None
    ) == predecessor_event.income_year
    assert _canonical_account_facts(persistence.account) == _legacy_account_facts(
        predecessor_after
    )


def test_predecessor_duplicate_suppression_matches_successor_exact_replay() -> None:
    predecessor = _legacy_build_account(pricing_plan="standard")
    predecessor_event = _legacy_event(
        predecessor, kind="subscription", amount_nok=49
    )
    predecessor_after = _legacy_apply(predecessor, predecessor_event)
    predecessor_after_duplicate = _legacy_apply(predecessor_after, predecessor_event)

    class _CountingProvider(SimulationBillingProvider):
        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, intent):
            self.calls += 1
            return await super().execute(intent)

    persistence = MemoryPersistence(account())
    provider = _CountingProvider()
    service = BillingService(persistence, provider, now=lambda: NOW.value)
    command = ActivateSubscriptionCommand(**metadata("equivalence-replay"))
    first = asyncio.run(service.activate_subscription(command))
    replay = asyncio.run(service.activate_subscription(command))

    assert predecessor_after_duplicate == predecessor_after
    assert replay.event_id == first.event_id
    assert replay.replayed is True
    assert provider.calls == 1
    assert len(persistence.events) == 1
    assert persistence.account is not None
    assert _canonical_account_facts(persistence.account) == _legacy_account_facts(
        predecessor_after
    )


def test_failed_provider_outcomes_fail_closed_and_successor_quarantines_once() -> None:
    predecessor = _legacy_build_account(pricing_plan="standard")
    failed = _legacy_event(
        predecessor,
        kind="filing_package",
        amount_nok=499,
        income_year=2025,
        status="failed",
    )
    predecessor_after = _legacy_apply(predecessor, failed)

    class _FailingProvider:
        provider = "simulation"
        production_enabled = False

        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, _intent) -> Never:
            self.calls += 1
            raise RuntimeError("fixed injected provider failure")

    persistence = MemoryPersistence(
        account(subscription_active=True), ready=True
    )
    provider = _FailingProvider()
    service = BillingService(persistence, provider, now=lambda: NOW.value)
    command = PurchaseFilingPackageCommand(
        **metadata("equivalence-provider-failure"), income_year=IncomeYear(2025)
    )
    for _attempt in range(2):
        with pytest.raises(BillingError) as error:
            asyncio.run(service.purchase_filing_package(command))
        assert error.value.code == BillingErrorCode.PROVIDER_OUTCOME_UNKNOWN

    assert predecessor_after.filing_package_paid is False
    assert persistence.account is not None
    assert persistence.account.filing_package_paid is False
    assert provider.calls == 1
    assert len(persistence.events) == 1
    quarantine = next(iter(persistence.events.values()))
    assert quarantine.status is BillingPaymentStatus.FAILED


def _pilot(**changes: object) -> ProductionPilotEntitlement:
    return replace(
        ProductionPilotEntitlement(
            entitlement_id=ProductionPilotEntitlementId(
                "30000000-0000-4000-8000-000000000001"
            ),
            company_id=COMPANY_ID,
            user_id=USER_ID,
            income_year=IncomeYear(2025),
            obligation=query().obligation,
            case_profile="rf1086_no_activity_v1",
            status=ProductionPilotStatus.ACTIVE,
            billing_exempt=True,
            system_user_request_id=SystemUserRequestReference(
                "40000000-0000-4000-8000-000000000001"
            ),
            system_user_external_reference="fixed-system-user",
            starts_at=Timestamp(NOW.value - timedelta(minutes=1)),
            expires_at=Timestamp(NOW.value + timedelta(minutes=1)),
            evidence_reference="fixed-equivalence-evidence",
            approved_by=USER_ID,
            created_at=NOW,
            updated_at=NOW,
        ),
        **changes,
    )


@pytest.mark.parametrize(
    "entitlement",
    [
        None,
        _pilot(),
        _pilot(status=ProductionPilotStatus.SUSPENDED),
        _pilot(starts_at=Timestamp(NOW.value + timedelta(seconds=1))),
        _pilot(expires_at=NOW),
        _pilot(case_profile="other"),
    ],
)
def test_predecessor_and_successor_match_fixed_pilot_identity_and_clock(
    entitlement: ProductionPilotEntitlement | None,
) -> None:
    predecessor_allowed = _legacy_pilot_allowed(entitlement)

    class _ExactPilotPersistence(MemoryPersistence):
        async def find_active_pilot_entitlement(self, **kwargs):
            candidate = self.pilot
            if candidate is None:
                return None
            return candidate if (
                candidate.company_id == kwargs["company_id"]
                and candidate.user_id == kwargs["user_id"]
                and candidate.income_year == kwargs["income_year"]
                and candidate.obligation == kwargs["obligation"]
                and candidate.case_profile == kwargs["case_profile"]
                and candidate.status is ProductionPilotStatus.ACTIVE
                and candidate.starts_at.value <= kwargs["at"] < candidate.expires_at.value
            ) else None

    persistence = _ExactPilotPersistence(
        account(subscription_active=True, filing_package_paid=True), ready=True
    )
    persistence.pilot = entitlement
    decision = asyncio.run(
        BillingService(
            persistence, SimulationBillingProvider(), now=lambda: NOW.value
        ).entitlement(query(case_profile="rf1086_no_activity_v1"))
    )

    assert (decision.status is BillingStatus.PILOT_ENTITLEMENT_ACTIVE) is (
        predecessor_allowed and bool(entitlement and entitlement.billing_exempt)
    )
    assert decision.allowed is True
    assert decision.charge_allowed is False
    assert decision.billing_exempt is (
        predecessor_allowed and bool(entitlement and entitlement.billing_exempt)
    )


def test_norwegian_copy_covers_every_predecessor_journey() -> None:
    assert len(_NORWEGIAN_SUCCESSOR_MESSAGES) == 6
    for message in _NORWEGIAN_SUCCESSOR_MESSAGES.values():
        lowered = message.lower()
        assert "billing" not in lowered
        assert "filing" not in lowered
        assert "readiness" not in lowered
