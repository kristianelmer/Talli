"""Project recorded Billing periods for Company Access disposition policy.

The caller must drain the owning company-wide purchase read. No offer dates,
selected-year cancellation marker or refund request shortens recorded access.
"""
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from uuid import UUID

from talli_backend.modules.billing.public import AnnualPurchasePage, AnnualPurchaseStatus


@dataclass(frozen=True)
class DispositionAccessPeriod:
    paid_expires_at: datetime
    read_export_until: datetime


def disposition_access_period(purchases: AnnualPurchasePage, *, company_id: UUID,
                               all_company_years: tuple[int, ...]) -> DispositionAccessPeriod:
    rows = purchases.purchases
    if (purchases.next_purchase_id is not None or not rows
            or any(str(p.company_id) != str(company_id) for p in rows)
            or any(int(p.income_year) not in all_company_years for p in rows)
            or any(p.status is AnnualPurchaseStatus.PENDING or p.refund_operations.created or p.refund_operations.pending
                   or p.refund_operations.unknown or (p.recurring_consent and p.renewal_canceled_at is None) for p in rows)):
        raise ValueError('disposition_billing_history_incomplete')
    paid = tuple(p for p in rows if p.status in {AnnualPurchaseStatus.PAID, AnnualPurchaseStatus.REFUNDED}
                 and p.captured_at is not None and p.captured_minor > 0)
    if {int(p.income_year) for p in paid} != set(all_company_years):
        raise ValueError('disposition_billing_history_incomplete')
    # Billing's through-dates are inclusive. Expiry is the next UTC midnight;
    # Company Access separately enforces its approved minimum90day period.
    return DispositionAccessPeriod(
        datetime.combine(max(p.paid_through for p in paid) + timedelta(days=1), time.min, UTC),
        datetime.combine(max(p.export_through for p in paid) + timedelta(days=1), time.min, UTC),
    )
