from __future__ import annotations

import asyncio

import pytest

from talli_backend.adapters.simulation_billing import SimulationBillingProvider
from talli_backend.modules.billing.public import (
    BillingPlan,
    BillingPricing,
    BillingStatus,
    ConfigureBillingAccountCommand,
)
from talli_backend.modules.billing.service import BillingService, billing_entitlement_decision

from test_billing import MemoryPersistence, NOW, account, metadata, query


@pytest.mark.parametrize(
    ("account_changes", "filing_ready", "expected"),
    [
        ({"refund_eligible": True}, True, (BillingStatus.REFUND_ELIGIBLE, False, False)),
        ({"supported_case": False}, True, (BillingStatus.UNSUPPORTED_CASE, False, False)),
        ({}, True, (BillingStatus.SUBSCRIPTION_REQUIRED, False, False)),
        ({"subscription_active": True}, False, (BillingStatus.ACTIVE, False, False)),
        (
            {"subscription_active": True},
            True,
            (BillingStatus.FILING_PACKAGE_REQUIRED, False, True),
        ),
        (
            {"subscription_active": True, "filing_package_paid": True},
            True,
            (BillingStatus.READY_FOR_PRODUCTION_FILING, True, False),
        ),
    ],
)
def test_canonical_entitlement_matches_fixed_legacy_gate_characterization(
    account_changes: dict[str, object],
    filing_ready: bool,
    expected: tuple[BillingStatus, bool, bool],
) -> None:
    decision = billing_entitlement_decision(
        query(), account(**account_changes), filing_ready=filing_ready
    )

    assert (decision.status, decision.allowed, decision.charge_allowed) == expected


def test_canonical_pricing_matches_fixed_legacy_characterization() -> None:
    for plan, cohort, expected in (
        (BillingPlan.FOUNDER, 100, BillingPricing(BillingPlan.FOUNDER, 29, 299)),
        (BillingPlan.STANDARD, None, BillingPricing(BillingPlan.STANDARD, 49, 499)),
    ):
        persistence = MemoryPersistence()
        configured = asyncio.run(
            BillingService(
                persistence, SimulationBillingProvider(), now=lambda: NOW.value
            ).configure_account(
                ConfigureBillingAccountCommand(
                    **metadata(f"equivalence-{plan.value}"),
                    pricing_plan=plan,
                    founder_cohort_number=cohort,
                )
            )
        )
        assert configured.pricing == expected


def test_entitlement_copy_is_norwegian_for_every_legacy_gate_state() -> None:
    cases = [
        (account(refund_eligible=True), True),
        (account(supported_case=False), True),
        (account(), True),
        (account(subscription_active=True), False),
        (account(subscription_active=True), True),
        (account(subscription_active=True, filing_package_paid=True), True),
    ]
    english_fragments = (
        "billing account",
        "filing readiness",
        "filing package",
        "production filing",
        "exact active validation entitlement",
    )

    for characterized_account, ready in cases:
        message = billing_entitlement_decision(
            query(), characterized_account, filing_ready=ready
        ).message.lower()
        assert all(fragment not in message for fragment in english_fragments)
