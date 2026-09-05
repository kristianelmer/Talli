from dataclasses import replace
from datetime import date, datetime

import pytest

from talli_backend.modules.billing.annual_policy import annual_offer, annual_refund, annual_renewal
from talli_backend.modules.billing.public import (
    AnnualRefundFacts,
    AnnualRefundReason,
    AnnualRenewalFacts,
    BillingError,
)
from talli_backend.shared.kernel import CompanyId, IncomeYear, Timestamp


COMPANY = CompanyId("10000000-0000-4000-8000-000000000001")


def at(value: str) -> Timestamp:
    return Timestamp(datetime.fromisoformat(value))


def refund_facts(**changes):
    return replace(AnnualRefundFacts(
        reason=AnnualRefundReason.CHANGE_OF_MIND,
        purchased_at=at("2026-01-01T10:00:00+01:00"),
        first_purchased_at=at("2026-01-01T10:00:00+01:00"),
        accepted_at=at("2026-01-01T09:00:00+01:00"),
        discovered_at=at("2026-01-31T10:00:00+01:00"),
        condition_effective_at=at("2026-01-02T10:00:00+01:00"),
        blocked_at=at("2026-01-31T10:00:00+01:00"),
        income_year=IncomeYear(2026),
        gross_minor=149000,
        refunded_minor=0,
        production_submission_at=None,
        evidence_reference="incident:immutable-123",
    ), **changes)


def renewal_facts(**changes):
    return replace(AnnualRenewalFacts(
        recurring_consent=True,
        renewal_canceled=False,
        reminder_recorded_at=at("2026-12-02T00:00:00+01:00"),
        price_change_recorded_at=None,
        prior_gross_minor=149000,
        target_offer=annual_offer(COMPANY, IncomeYear(2027)),
        target_definitively_eligible=True,
        target_filing_ready=True,
        at=at("2027-01-01T00:00:00+01:00"),
    ), **changes)


def test_exact_offer_pins_calendar_scope_vat_and_access():
    offer = annual_offer(COMPANY, IncomeYear(2026))
    assert (offer.currency, offer.gross_minor, offer.net_minor, offer.vat_minor) == (
        "NOK", 149000, 119200, 29800
    )
    assert offer.company_id == COMPANY
    assert offer.paid_through == date(2027, 12, 31)
    assert (offer.export_through - offer.paid_through).days == 90
    assert offer.renewal_date == date(2027, 1, 1)
    assert offer.renewal_reminder_by == date(2026, 12, 2)
    assert offer.price_change_notice_by == date(2026, 11, 2)
    assert len(offer.terms_digest) == 64
    with pytest.raises(BillingError):
        replace(offer, gross_minor=149001)
    with pytest.raises(BillingError):
        replace(offer, net_minor=149000, vat_minor=0)
    with pytest.raises(BillingError):
        replace(offer, export_through=date(2028, 1, 1))


def test_thirty_day_boundary_and_submission_are_exact():
    assert annual_refund(refund_facts()).amount_due_minor == 149000
    assert annual_refund(refund_facts(
        discovered_at=at("2026-01-31T10:00:01+01:00")
    )).amount_due_minor == 0
    assert annual_refund(refund_facts(
        production_submission_at=at("2026-01-30T12:00:00+01:00")
    )).amount_due_minor == 0


@pytest.mark.parametrize("reason", [
    AnnualRefundReason.TALLI_ACCEPTANCE_FAILURE,
    AnnualRefundReason.TALLI_DELIVERY_FAILURE,
])
def test_talli_failure_refund_survives_age_submission_and_provider_limit(reason):
    decision = annual_refund(refund_facts(
        reason=reason,
        discovered_at=at("2028-02-01T12:00:00+01:00"),
        production_submission_at=at("2026-05-01T12:00:00+02:00"),
        refunded_minor=37250,
    ))
    assert decision.total_entitlement_minor == 149000
    assert decision.amount_due_minor == 111750
    assert decision.vat_due_minor == 22350
    assert decision.export_available and decision.cancel_renewal


@pytest.mark.parametrize(("effective", "months", "amount"), [
    ("2026-09-05T12:00:00+02:00", 3, 37250),
    ("2026-09-01T00:00:00+02:00", 4, 49667),
    ("2026-09-01T00:00:01+02:00", 3, 37250),
    ("2026-12-15T12:00:00+01:00", 0, 0),
    ("2027-01-01T00:00:00+01:00", 0, 0),
])
def test_new_unsupported_refunds_only_unused_whole_company_year_months(effective, months, amount):
    decision = annual_refund(refund_facts(
        reason=AnnualRefundReason.NEW_UNSUPPORTED_CONDITION,
        condition_effective_at=at(effective),
        blocked_at=at(effective),
        discovered_at=at("2027-01-01T12:00:00+01:00"),
    ))
    assert (decision.unused_whole_months, decision.amount_due_minor) == (months, amount)


def test_new_unsupported_first_thirty_days_is_full_and_existing_fact_cannot_be_relabelled():
    assert annual_refund(refund_facts(
        reason=AnnualRefundReason.NEW_UNSUPPORTED_CONDITION
    )).amount_due_minor == 149000
    with pytest.raises(BillingError):
        refund_facts(
            reason=AnnualRefundReason.NEW_UNSUPPORTED_CONDITION,
        condition_effective_at=at("2025-12-31T12:00:00+01:00"),
        )


def test_refund_never_pays_twice_or_exceeds_the_remaining_paid_amount():
    assert annual_refund(refund_facts(refunded_minor=149000)).amount_due_minor == 0
    with pytest.raises(BillingError):
        refund_facts(refunded_minor=149001)
    with pytest.raises(BillingError):
        refund_facts(refunded_minor=-1)


def test_unresolved_customer_facts_preserve_export_without_post_thirty_day_automatic_refund():
    decision = annual_refund(refund_facts(
        reason=AnnualRefundReason.CUSTOMER_UNRESOLVED,
        discovered_at=at("2026-06-05T12:00:00+02:00"),
    ))
    assert decision.amount_due_minor == 0
    assert decision.export_available and decision.cancel_renewal
    assert decision.initiate_by == date(2026, 6, 12)


def test_renewal_does_not_reset_first_purchase_refund_window():
    decision = annual_refund(refund_facts(
        first_purchased_at=at("2025-01-01T10:00:00+01:00"),
    ))
    assert decision.amount_due_minor == 0


def test_proration_uses_block_date_not_an_earlier_condition_discovery():
    decision = annual_refund(refund_facts(
        reason=AnnualRefundReason.NEW_UNSUPPORTED_CONDITION,
        condition_effective_at=at("2026-09-05T12:00:00+02:00"),
        blocked_at=at("2027-01-01T12:00:00+01:00"),
        discovered_at=at("2027-01-01T12:00:00+01:00"),
    ))
    assert decision.amount_due_minor == 0


@pytest.mark.parametrize(("change", "reason"), [
    ({"recurring_consent": False}, "recurring_consent_required"),
    ({"renewal_canceled": True}, "renewal_canceled"),
    ({"target_definitively_eligible": False}, "definitive_eligibility_required"),
    ({"target_filing_ready": False}, "filing_readiness_required"),
    ({"at": at("2026-12-31T12:00:00+01:00")}, "renewal_not_due"),
    ({"at": at("2029-01-01T12:00:00+01:00")}, "renewal_year_expired"),
    ({"reminder_recorded_at": None}, "renewal_notice_required"),
    ({"reminder_recorded_at": at("2026-12-03T00:00:00+01:00")}, "renewal_notice_required"),
    ({"prior_gross_minor": 139000}, "price_change_notice_required"),
])
def test_each_renewal_precondition_fails_closed(change, reason):
    decision = annual_renewal(renewal_facts(**change))
    assert not decision.allowed and decision.reason == reason


def test_renewal_uses_norwegian_date_and_requires_early_price_change_notice():
    assert annual_renewal(renewal_facts()).allowed
    assert annual_renewal(renewal_facts(
        prior_gross_minor=139000,
        price_change_recorded_at=at("2026-11-02T00:00:00+01:00"),
    )).allowed
    assert not annual_renewal(renewal_facts(
        reminder_recorded_at=at("2026-12-02T23:59:00+01:00"),
    )).allowed
    assert not annual_renewal(renewal_facts(
        prior_gross_minor=139000,
        price_change_recorded_at=at("2026-11-02T23:59:00+01:00"),
    )).allowed
    assert not annual_renewal(renewal_facts(
        prior_gross_minor=139000,
        price_change_recorded_at=at("2026-11-03T00:00:00+01:00"),
    )).allowed
