"""Deterministic company-year offer, notice and safe-exit policy for #177."""

from datetime import date, datetime, time, timedelta
from hashlib import sha256
from zoneinfo import ZoneInfo

from talli_backend.modules.billing.public import (
    AnnualBillingOffer,
    AnnualRefundDecision,
    AnnualRefundFacts,
    AnnualRefundReason,
    AnnualRenewalDecision,
    AnnualRenewalFacts,
)
from talli_backend.shared.kernel import CompanyId, IncomeYear


ANNUAL_TERMS = """Talli annual company-year offer, version 2026-09-05.
NOK 1490 including 25% VAT (NOK 1192 net, NOK 298 VAT) per company-year.
One supported calendar company-year: reconstruction, bookkeeping, bank connection
and file fallback, corporate documents, all three filings, receipts, SAF-T and archive.
Definitive eligibility and accepted exact scope precede payment.
Recurring renewal requires separate explicit consent; cancellation stops renewal
immediately and preserves paid access. Renewal buys the next calendar company-year
on 1 January, only after that year's definitive eligibility and readiness pass.
Paid access lasts through 31 December following the named accounting year;
read-only access and export continue for at least 90 days afterwards.
Renewal notice is required 30 days before charge, price-change notice 60 days.
Full refund within 30 days of first purchase if no production filing was submitted.
Mistaken Talli acceptance or Talli/provider delivery failure receives a full refund
regardless of age. A genuinely new unsupported condition receives the full refund
within 30 days before submission, otherwise unused whole accounting-year months.
Customer-unresolved evidence or authority receives no automatic refund after 30 days.
Refunds initiate within five business days; provider settlement is a separate status.
Records/export survive unsupported exit. Provider limits never erase refunds owed.
Free validation is separate and creates no recurring or future payment obligation.
"""
ANNUAL_TERMS_DIGEST = sha256(ANNUAL_TERMS.encode()).hexdigest()
_OSLO = ZoneInfo("Europe/Oslo")


def annual_offer(company_id: CompanyId, income_year: IncomeYear) -> AnnualBillingOffer:
    renewal = date(income_year.value + 1, 1, 1)
    paid_through = date(income_year.value + 1, 12, 31)
    return AnnualBillingOffer(
        company_id=company_id,
        income_year=income_year,
        offer_version="annual-company-year-2026-09-05",
        terms_digest=ANNUAL_TERMS_DIGEST,
        terms_text=ANNUAL_TERMS,
        currency="NOK",
        gross_minor=149000,
        net_minor=119200,
        vat_minor=29800,
        vat_basis_points=2500,
        paid_through=paid_through,
        export_through=paid_through + timedelta(days=90),
        renewal_date=renewal,
        renewal_reminder_by=renewal - timedelta(days=30),
        price_change_notice_by=renewal - timedelta(days=60),
    )


def _initiation_deadline(discovered: date) -> date:
    # Weekday-only counting is conservative: holidays can only make this earlier
    # than a five-business-day deadline, never later.
    remaining = 5
    while remaining:
        discovered += timedelta(days=1)
        if discovered.weekday() < 5:
            remaining -= 1
    return discovered


def annual_refund(facts: AnnualRefundFacts) -> AnnualRefundDecision:
    reason = facts.reason
    first_30_days = facts.discovered_at.value <= facts.first_purchased_at.value + timedelta(days=30)
    no_submission = facts.production_submission_at is None
    full = reason in {
        AnnualRefundReason.TALLI_ACCEPTANCE_FAILURE,
        AnnualRefundReason.TALLI_DELIVERY_FAILURE,
    } or (first_30_days and no_submission)
    months = 0
    if full:
        total = facts.gross_minor
        message = "Du får hele årsbeløpet tilbake."
    elif reason is AnnualRefundReason.NEW_UNSUPPORTED_CONDITION:
        effective_at = facts.blocked_at.value.astimezone(_OSLO)
        effective = effective_at.date()
        # A month is unused only when the condition applies by its first day.
        starts_month = effective.day == 1 and effective_at.time().isoformat() == "00:00:00"
        first_unused = effective.month if starts_month else effective.month + 1
        months = max(0, min(12, (facts.income_year.value - effective.year) * 12 + 13 - first_unused))
        total = (facts.gross_minor * months + 6) // 12
        message = "Du får tilbake beløpet for ubrukte hele måneder i regnskapsåret."
    else:
        total = 0
        message = "Vilkårene gir ikke automatisk refusjon. Du beholder tilgang til opplysninger og eksport."
    amount_due = max(0, total - facts.refunded_minor)
    return AnnualRefundDecision(
        reason=reason,
        total_entitlement_minor=total,
        amount_due_minor=amount_due,
        vat_due_minor=(amount_due + 2) // 5,
        unused_whole_months=months,
        initiate_by=_initiation_deadline(facts.discovered_at.value.astimezone(_OSLO).date()),
        cancel_renewal=True,
        export_available=True,
        message=message,
    )


def annual_renewal(facts: AnnualRenewalFacts) -> AnnualRenewalDecision:
    charge_date = date(facts.target_offer.income_year.value, 1, 1)
    earliest_collection = datetime.combine(charge_date, time.min, _OSLO)
    scheduling_date = facts.at.value.astimezone(_OSLO).date()
    checks = (
        (facts.recurring_consent, "recurring_consent_required"),
        (not facts.renewal_canceled, "renewal_canceled"),
        (facts.target_definitively_eligible, "definitive_eligibility_required"),
        (facts.target_filing_ready, "filing_readiness_required"),
        (facts.collection_due_date == charge_date, "renewal_date_changed"),
        (scheduling_date < charge_date, "renewal_scheduling_missed"),
        (scheduling_date >= charge_date - timedelta(days=1), "renewal_not_due"),
        (
            facts.reminder_recorded_at is not None
            and facts.reminder_recorded_at.value <= facts.at.value
            and facts.reminder_recorded_at.value + timedelta(days=30) <= earliest_collection,
            "renewal_notice_required",
        ),
        (
            facts.prior_gross_minor == facts.target_offer.gross_minor
            or (
                facts.price_change_recorded_at is not None
                and facts.price_change_recorded_at.value <= facts.at.value
                and facts.price_change_recorded_at.value + timedelta(days=60) <= earliest_collection
            ),
            "price_change_notice_required",
        ),
    )
    return next(
        (AnnualRenewalDecision(False, reason) for allowed, reason in checks if not allowed),
        AnnualRenewalDecision(True, "renewal_ready"),
    )
