from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from talli_backend.adapters.simulation_billing import SimulationBillingProvider
from talli_backend.modules.billing.public import (
    ActivateSubscriptionCommand,
    BillingAccount,
    BillingEntitlementQuery,
    BillingError,
    BillingErrorCode,
    BillingObligation,
    BillingPaymentEvent,
    BillingPaymentEventId,
    BillingPaymentKind,
    BillingPaymentStatus,
    BillingPlan,
    BillingPricing,
    BillingProviderResult,
    BillingSnapshot,
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
    expected_payment_status,
)
from talli_backend.modules.billing.service import BillingService
from talli_backend.shared.kernel import (
    ActorId,
    ActorKind,
    CompanyId,
    CorrelationId,
    IdempotencyKey,
    IncomeYear,
    Timestamp,
    UserId,
)


COMPANY_ID = CompanyId("10000000-0000-4000-8000-000000000001")
USER_ID = UserId("20000000-0000-4000-8000-000000000001")
ACTOR = ActorId(ActorKind.USER, USER_ID)
NOW = Timestamp(datetime(2026, 9, 5, tzinfo=UTC))


def metadata(key: str) -> dict[str, object]:
    return {
        "company_id": COMPANY_ID,
        "actor_id": ACTOR,
        "correlation_id": CorrelationId(f"request-{key}"),
        "idempotency_key": IdempotencyKey(f"billing-test-{key}-00000001"),
    }


def account(**changes: object) -> BillingAccount:
    return replace(
        BillingAccount(
            company_id=COMPANY_ID,
            pricing=BillingPricing(BillingPlan.STANDARD, 49, 499),
            founder_cohort_number=None,
            subscription_active=False,
            filing_package_paid=False,
            supported_case=True,
            refund_eligible=False,
            refund_completed=False,
            no_charge_reason=None,
            provider_customer_reference=None,
            subscription_provider_reference=None,
            filing_package_payment_reference=None,
            refund_provider_reference=None,
            updated_by=USER_ID,
            created_at=NOW,
            updated_at=NOW,
        ),
        **changes,
    )


class MemoryPersistence:
    def __init__(self, value: BillingAccount | None = None, *, ready: bool = False) -> None:
        self.account = value
        self.ready = ready
        self.owner_authorized = True
        self.admin_authorized = True
        self.entitlement_authorized = True
        self.entitlement_authorizations = 0
        self.account_reads = 0
        self.events: dict[str, BillingPaymentEvent] = {}
        self.pilot: ProductionPilotEntitlement | None = None

    async def authorize_owner_command(self, _company_id: CompanyId) -> None:
        if not self.owner_authorized:
            raise BillingError.forbidden()

    async def authorize_admin_command(self) -> None:
        if not self.admin_authorized:
            raise BillingError.forbidden()

    async def authorize_entitlement_query(self, _company_id: CompanyId) -> None:
        self.entitlement_authorizations += 1
        if not self.entitlement_authorized:
            raise BillingError.forbidden()

    async def find_account(self, company_id: CompanyId):
        assert company_id == COMPANY_ID
        self.account_reads += 1
        return self.account

    async def filing_ready(self, company_id, income_year, obligation):
        assert company_id == COMPANY_ID
        assert income_year == IncomeYear(2025)
        assert obligation == BillingObligation.SHAREHOLDER_REGISTER
        return self.ready

    async def find_active_pilot_entitlement(self, **kwargs):
        if self.pilot is None:
            return None
        at = kwargs["at"]
        return self.pilot if self.pilot.starts_at.value <= at < self.pilot.expires_at.value else None

    async def snapshot(self, _query):
        return BillingSnapshot(
            accounts=(() if self.account is None else (self.account,)),
            payment_events=tuple(self.events.values()),
            pilot_entitlements=(() if self.pilot is None else (self.pilot,)),
        )

    async def find_payment_event(
        self, *, company_id, idempotency_key, kind, income_year, obligation=None
    ):
        event = self.events.get(str(idempotency_key))
        if event is None:
            return None
        if (
            event.company_id != company_id
            or event.kind is not kind
            or event.income_year != income_year
            or event.obligation != obligation
        ):
            raise BillingError.conflict(BillingErrorCode.IDEMPOTENCY_KEY_REUSED)
        return replace(event, replayed=True)

    async def configure_account(self, command, pricing):
        self.account = account(
            pricing=pricing,
            founder_cohort_number=command.founder_cohort_number,
        )
        return self.account

    async def begin_provider_event(self, command, provider, amount_nok):
        replay = self.events.get(str(command.idempotency_key))
        if replay is not None:
            return replace(replay, replayed=True)
        return await self.complete_provider_event(command, BillingProviderResult(
            provider=provider,
            provider_reference=f"intent_{command.idempotency_key}",
            status=BillingPaymentStatus.CREATED,
        ), amount_nok)

    async def complete_provider_event(self, command, result, amount_nok):
        key = str(command.idempotency_key)
        previous = self.events.get(key)
        if previous is not None and previous.status is expected_payment_status(previous.kind):
            return replace(previous, replayed=True)
        event = BillingPaymentEvent(
            event_id=previous.event_id if previous else BillingPaymentEventId(str(uuid4())),
            company_id=command.company_id,
            provider=result.provider,
            provider_reference=result.provider_reference,
            idempotency_key=command.idempotency_key,
            kind={
                ActivateSubscriptionCommand: BillingPaymentKind.SUBSCRIPTION,
                CancelSubscriptionCommand: BillingPaymentKind.SUBSCRIPTION_CANCELLATION,
                PurchaseFilingPackageCommand: BillingPaymentKind.FILING_PACKAGE,
                RefundFilingPackageCommand: BillingPaymentKind.REFUND,
            }[type(command)],
            status=result.status,
            amount_nok=amount_nok,
            income_year=getattr(command, "income_year", None),
            created_by=command.actor_id.subject,
            created_at=NOW,
            obligation=getattr(command, "obligation", None),
        )
        self.events[key] = event
        assert self.account is not None
        expected_status = expected_payment_status(event.kind)
        if event.status is not expected_status:
            return event
        if event.kind is BillingPaymentKind.SUBSCRIPTION_CANCELLATION:
            self.account = replace(
                self.account, subscription_active=False,
                subscription_provider_reference=event.provider_reference,
            )
        elif event.kind is BillingPaymentKind.REFUND:
            self.account = replace(
                self.account, refund_eligible=False, refund_completed=True,
                refund_provider_reference=event.provider_reference,
            )
        return event

    async def mark_unsupported(self, command):
        assert self.account is not None
        self.account = replace(
            self.account,
            supported_case=False,
            filing_package_paid=False,
            filing_package_payment_reference=None,
            no_charge_reason=command.reason,
        )
        return self.account

    async def manage_pilot_entitlement(self, command):
        entitlement_id = command.entitlement_id or ProductionPilotEntitlementId(str(uuid4()))
        self.pilot = ProductionPilotEntitlement(
            entitlement_id=entitlement_id,
            company_id=command.company_id,
            user_id=command.user_id,
            income_year=command.income_year,
            obligation=command.obligation,
            case_profile=command.case_profile,
            status=command.status,
            billing_exempt=command.billing_exempt,
            system_user_request_id=command.system_user_request_id,
            system_user_external_reference="system-user-ref",
            starts_at=command.starts_at,
            expires_at=command.expires_at,
            evidence_reference=command.evidence_reference,
            approved_by=command.actor_id.subject,
            created_at=NOW,
            updated_at=NOW,
        )
        return self.pilot


def query(*, case_profile: str | None = None) -> BillingEntitlementQuery:
    return BillingEntitlementQuery(
        company_id=COMPANY_ID,
        actor_id=ACTOR,
        correlation_id=CorrelationId("billing-entitlement-query"),
        income_year=IncomeYear(2025),
        obligation=BillingObligation.SHAREHOLDER_REGISTER,
        case_profile=case_profile,
    )


def seed_historical_event(persistence, command, *, status=BillingPaymentStatus.CREATED, provider="simulation"):
    """Represent a payment intent committed by the predecessor before cutover."""
    kind = BillingPaymentKind.SUBSCRIPTION if isinstance(command, ActivateSubscriptionCommand) else BillingPaymentKind.FILING_PACKAGE
    event = BillingPaymentEvent(
        event_id=BillingPaymentEventId(str(uuid4())), company_id=command.company_id,
        provider=provider, provider_reference=f"historical_{command.idempotency_key}",
        idempotency_key=command.idempotency_key, kind=kind, status=status,
        amount_nok=49 if kind is BillingPaymentKind.SUBSCRIPTION else 499,
        income_year=getattr(command, "income_year", None),
        created_by=command.actor_id.subject, created_at=NOW,
        obligation=getattr(command, "obligation", None),
    )
    persistence.events[str(command.idempotency_key)] = event
    return event


def test_legacy_snapshot_preserves_historical_prices_without_advertising_retired_plans():
    from talli_backend.modules.billing.public import BillingSnapshotQuery
    original = account(pricing=BillingPricing(BillingPlan.FOUNDER, 29, 299))
    persistence = MemoryPersistence(original)
    snapshot = asyncio.run(BillingService(persistence, SimulationBillingProvider()).snapshot(
        BillingSnapshotQuery(company_ids=(COMPANY_ID,), actor_id=ACTOR, correlation_id=CorrelationId("historical-snapshot"))
    ))
    assert snapshot.accounts == (original,)
    assert snapshot.pricing == ()


def test_entitlement_authorizes_company_scope_before_reading_billing_state() -> None:
    persistence = MemoryPersistence(account(subscription_active=True), ready=True)
    persistence.entitlement_authorized = False
    service = BillingService(persistence, SimulationBillingProvider(), now=lambda: NOW.value)

    with pytest.raises(BillingError) as denied:
        asyncio.run(service.entitlement(query()))

    assert denied.value.code == BillingErrorCode.FORBIDDEN
    assert persistence.entitlement_authorizations == 1
    assert persistence.account_reads == 0


def test_exact_active_pilot_can_exempt_billing_without_activating_provider() -> None:
    persistence = MemoryPersistence(ready=True)
    service = BillingService(persistence, SimulationBillingProvider(), now=lambda: NOW.value)
    starts = Timestamp(NOW.value - timedelta(hours=1))
    expires = Timestamp(NOW.value + timedelta(hours=1))
    managed = asyncio.run(service.manage_pilot_entitlement(
        ManageProductionPilotEntitlementCommand(
            **metadata("pilot"),
            entitlement_id=None,
            user_id=USER_ID,
            income_year=IncomeYear(2025),
            status=ProductionPilotStatus.ACTIVE,
            billing_exempt=True,
            system_user_request_id=SystemUserRequestReference(
                "30000000-0000-4000-8000-000000000001"
            ),
            starts_at=starts,
            expires_at=expires,
            evidence_reference="approved-validation-run",
        )
    ))
    decision = asyncio.run(service.entitlement(query(case_profile="rf1086_no_activity_v1")))
    assert decision.status is BillingStatus.PILOT_ENTITLEMENT_ACTIVE
    assert decision.allowed is True
    assert decision.billing_exempt is True
    assert decision.pilot_entitlement_id == managed.entitlement_id

    persistence.ready = False
    readiness_revoked = asyncio.run(
        service.entitlement(query(case_profile="rf1086_no_activity_v1"))
    )
    assert readiness_revoked.status is BillingStatus.ACTIVE
    assert readiness_revoked.allowed is False
    assert readiness_revoked.billing_exempt is True


def test_cancellation_unsupported_and_refund_preserve_safe_states() -> None:
    persistence = MemoryPersistence(
        account(subscription_active=True, filing_package_paid=True), ready=True
    )
    service = BillingService(persistence, SimulationBillingProvider(), now=lambda: NOW.value)
    refund = asyncio.run(service.refund_filing_package(
        RefundFilingPackageCommand(**metadata("refund"), income_year=IncomeYear(2025))
    ))
    assert refund.status is BillingPaymentStatus.REFUNDED
    assert persistence.account is not None and persistence.account.refund_completed
    persistence.account = replace(
        persistence.account,
        pricing=BillingPricing(BillingPlan.FOUNDER, 29, 299),
    )
    replay = asyncio.run(service.refund_filing_package(
        RefundFilingPackageCommand(**metadata("refund"), income_year=IncomeYear(2025))
    ))
    assert replay.event_id == refund.event_id
    assert replay.amount_nok == 499
    assert replay.replayed is True

    canceled = asyncio.run(service.cancel_subscription(
        CancelSubscriptionCommand(**metadata("cancel"))
    ))
    assert canceled.status is BillingPaymentStatus.CANCELED
    assert persistence.account is not None and not persistence.account.subscription_active

    unsupported = asyncio.run(service.mark_unsupported(
        MarkBillingUnsupportedCommand(**metadata("unsupported"), reason="Outside support")
    ))
    assert unsupported.supported_case is False
    assert unsupported.filing_package_paid is False


def test_ambiguous_provider_outcome_is_quarantined_without_granting_entitlement() -> None:
    class AmbiguousProvider:
        provider = "ambiguous"
        production_enabled = False

        async def execute(self, _intent):
            return BillingProviderResult(
                provider=self.provider,
                provider_reference="ambiguous-result",
                status=BillingPaymentStatus.FAILED,
            )

    persistence = MemoryPersistence(account(subscription_active=True), ready=True)
    service = BillingService(persistence, AmbiguousProvider(), now=lambda: NOW.value)
    command = CancelSubscriptionCommand(**metadata("ambiguous"))
    with pytest.raises(BillingError) as first:
        asyncio.run(service.cancel_subscription(command))
    assert first.value.code == BillingErrorCode.PROVIDER_OUTCOME_UNKNOWN
    event = persistence.events[str(command.idempotency_key)]
    assert event.status is BillingPaymentStatus.FAILED
    assert persistence.account is not None and not persistence.account.filing_package_paid
    with pytest.raises(BillingError) as replay:
        asyncio.run(service.cancel_subscription(command))
    assert replay.value.code == BillingErrorCode.PROVIDER_OUTCOME_UNKNOWN
    assert len(persistence.events) == 1


def test_provider_exception_is_quarantined_without_retrying_the_provider() -> None:
    class FailingProvider:
        provider = "failing"
        production_enabled = False

        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, _intent):
            self.calls += 1
            raise RuntimeError("unknown remote outcome")

    persistence = MemoryPersistence(account())
    provider = FailingProvider()
    service = BillingService(persistence, provider, now=lambda: NOW.value)
    command = CancelSubscriptionCommand(**metadata("provider-exception"))
    for _attempt in range(2):
        with pytest.raises(BillingError) as error:
            asyncio.run(service.cancel_subscription(command))
        assert error.value.code == BillingErrorCode.PROVIDER_OUTCOME_UNKNOWN
    event = persistence.events[str(command.idempotency_key)]
    assert event.status is BillingPaymentStatus.CREATED
    assert event.provider_reference.startswith("intent_")
    assert provider.calls == 1


def test_sensitive_authorization_precedes_provider_calls_and_event_replay() -> None:
    class RecordingProvider:
        provider = "recording"
        production_enabled = False

        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, _intent):
            self.calls += 1
            return BillingProviderResult(
                provider=self.provider,
                provider_reference="recording-subscription",
                status=BillingPaymentStatus.CANCELED,
            )

    persistence = MemoryPersistence(account())
    provider = RecordingProvider()
    service = BillingService(persistence, provider, now=lambda: NOW.value)
    command = CancelSubscriptionCommand(**metadata("authorized-first"))
    first = asyncio.run(service.cancel_subscription(command))
    assert first.status is BillingPaymentStatus.CANCELED
    assert provider.calls == 1

    persistence.owner_authorized = False
    with pytest.raises(BillingError) as replay_error:
        asyncio.run(service.cancel_subscription(command))
    assert replay_error.value.code == BillingErrorCode.FORBIDDEN
    with pytest.raises(BillingError) as new_error:
        asyncio.run(
            service.cancel_subscription(
                CancelSubscriptionCommand(**metadata("unauthorized-new"))
            )
        )
    assert new_error.value.code == BillingErrorCode.FORBIDDEN
    assert provider.calls == 1


def test_public_commands_reject_invalid_founder_and_pilot_ranges() -> None:
    with pytest.raises(BillingError):
        ConfigureBillingAccountCommand(
            **metadata("bad-founder"),
            pricing_plan=BillingPlan.FOUNDER,
            founder_cohort_number=101,
        )
    with pytest.raises(BillingError):
        ManageProductionPilotEntitlementCommand(
            **metadata("bad-pilot"),
            entitlement_id=None,
            user_id=USER_ID,
            income_year=IncomeYear(2025),
            status=ProductionPilotStatus.ACTIVE,
            billing_exempt=True,
            system_user_request_id=SystemUserRequestReference(str(UUID(int=3))),
            starts_at=Timestamp(datetime(2026, 9, 6, tzinfo=UTC)),
            expires_at=Timestamp(datetime(2026, 9, 5, tzinfo=UTC)),
            evidence_reference="evidence",
        )


def test_provider_observes_persisted_intent_before_any_io() -> None:
    class ObservingProvider(SimulationBillingProvider):
        saw_intent = False

        async def execute(self, intent):
            event = persistence.events.get(str(intent.idempotency_key))
            self.saw_intent = event is not None and event.status is BillingPaymentStatus.CREATED
            return await super().execute(intent)

    persistence = MemoryPersistence(account())
    provider = ObservingProvider()
    command = CancelSubscriptionCommand(**metadata("durable-intent"))
    asyncio.run(BillingService(persistence, provider).cancel_subscription(command))
    assert provider.saw_intent, "provider I/O ran before the intent was persisted"


def test_lost_provider_response_reconciles_same_key_without_second_execution() -> None:
    class LostResponseProvider(SimulationBillingProvider):
        executions = 0
        reconciliations = 0
        result = None
        original_intent = None

        async def execute(self, intent):
            self.executions += 1
            self.original_intent = intent
            self.result = await super().execute(intent)
            raise TimeoutError("response lost after provider success")

        async def reconcile(self, intent):
            self.reconciliations += 1
            assert intent == self.original_intent
            return self.result

    persistence = MemoryPersistence(account(subscription_active=True))
    provider = LostResponseProvider()
    command = CancelSubscriptionCommand(**metadata("lost-response"))
    with pytest.raises(BillingError) as failure:
        asyncio.run(BillingService(persistence, provider).cancel_subscription(command))
    assert failure.value.code == BillingErrorCode.PROVIDER_OUTCOME_UNKNOWN
    assert persistence.account.subscription_active
    # A new request/service must recover even after pricing has changed.
    persistence.account = replace(persistence.account, pricing=BillingPricing(BillingPlan.FOUNDER, 29, 299))
    recovered = asyncio.run(BillingService(persistence, provider).cancel_subscription(command))
    assert recovered.status is BillingPaymentStatus.CANCELED
    assert recovered.amount_nok == 0
    assert not persistence.account.subscription_active
    assert provider.executions == provider.reconciliations == 1


def test_recovery_rejects_changed_filing_obligation_before_provider_lookup() -> None:
    class UnknownProvider(SimulationBillingProvider):
        lookups = 0

        async def execute(self, intent):
            raise TimeoutError("unknown")

        async def reconcile(self, intent):
            self.lookups += 1
            return None

    persistence = MemoryPersistence(account(subscription_active=True), ready=True)
    provider = UnknownProvider()
    service = BillingService(persistence, provider)
    command = PurchaseFilingPackageCommand(**metadata("recovery-scope"), income_year=IncomeYear(2025))
    seed_historical_event(persistence, command)
    changed = replace(command, obligation=BillingObligation.COMPANY_TAX)
    with pytest.raises(BillingError) as mismatch:
        asyncio.run(service.purchase_filing_package(changed))
    assert mismatch.value.code == BillingErrorCode.IDEMPOTENCY_KEY_REUSED
    assert provider.lookups == 0
    assert not persistence.account.filing_package_paid


def test_unknown_reconciliation_keeps_original_intent_without_executing_again() -> None:
    class UnknownProvider(SimulationBillingProvider):
        executions = 0
        lookups = 0

        async def execute(self, intent):
            self.executions += 1
            raise TimeoutError("unknown")

        async def reconcile(self, intent):
            self.lookups += 1
            return None

    persistence = MemoryPersistence(account())
    provider = UnknownProvider()
    command = ActivateSubscriptionCommand(**metadata("unknown-recovery"))
    seed_historical_event(persistence, command)
    for _ in range(3):
        with pytest.raises(BillingError) as error:
            asyncio.run(BillingService(persistence, provider).activate_subscription(command))
        assert error.value.code == BillingErrorCode.PROVIDER_OUTCOME_UNKNOWN
    assert provider.executions == 0
    assert provider.lookups == 3
    assert len(persistence.events) == 1
    assert not persistence.account.subscription_active
