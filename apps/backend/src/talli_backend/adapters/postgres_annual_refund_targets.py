"""Bounded stored-receipt projection inside an already authorized transaction."""

from talli_backend.modules.billing.public import (
    AnnualOperationStatus, AnnualPurchaseId, AnnualRefundRequestId,
    AnnualRefundRecoveryTarget, AnnualRefundRecoveryTargetPage, BillingError,
)
from talli_backend.shared.kernel import CompanyId, IncomeYear, Timestamp


async def _read_refund_recovery_targets(connection, query, *, requester_id):
    # The owner caller supplies its verified requester. The separately authorized
    # support caller can see bound receipts across requesters in its opened case.
    # One statement observes the purchase, authorized receipts and cursor.
    # Cursor order belongs to immutable operations, not representatives:
    # binding an older deferred receipt cannot move an existing group.
    rows = await (await connection.execute(
        """with purchase as materialized (
            select id,company_id,income_year from billing.annual_purchases
            where company_id=%s::uuid and id=%s::uuid
        ), eligible as materialized (
            select r.id as refund_request_id,r.requested_at,o.id as operation_id,
                o.created_at as operation_created_at,o.status
            from purchase p
            join billing.annual_refund_requests r on r.company_id=p.company_id
                and r.purchase_id=p.id and r.income_year=p.income_year
            join billing.annual_refund_cases c on c.id=r.refund_case_id
                and c.company_id=p.company_id and c.purchase_id=p.id and c.income_year=p.income_year
            join billing.annual_operations o on o.id=r.operation_id and o.refund_case_id=c.id
                and o.company_id=p.company_id and o.purchase_id=p.id and o.income_year=p.income_year
                and o.operation='refund'
            where (%s::uuid is null or r.requested_by=%s::uuid)
        ), cursor as (
            select operation_created_at,operation_id from eligible where refund_request_id=%s::uuid
        ), representatives as (
            select distinct on (operation_id) * from eligible
            order by operation_id,requested_at,refund_request_id
        ), targets as (
            select * from representatives
            where %s::uuid is null or (operation_created_at,operation_id)<(
                select operation_created_at,operation_id from cursor)
            order by operation_created_at desc,operation_id desc limit 51
        ) select p.id as purchase_id,p.company_id,p.income_year,
            (%s::uuid is null or exists(select 1 from cursor)) as cursor_valid,
            t.refund_request_id,t.requested_at,t.status
        from purchase p left join targets t on true
        order by t.operation_created_at desc,t.operation_id desc""",
        (str(query.company_id), str(query.purchase_id), str(requester_id) if requester_id else None, str(requester_id) if requester_id else None,
         str(query.before_refund_request_id) if query.before_refund_request_id else None,
         str(query.before_refund_request_id) if query.before_refund_request_id else None,
         str(query.before_refund_request_id) if query.before_refund_request_id else None),
    )).fetchall()
    if not rows or not rows[0]['cursor_valid']:
        raise BillingError.not_found()
    targets = tuple(AnnualRefundRecoveryTarget(
        AnnualRefundRequestId(str(row['refund_request_id'])), Timestamp(row['requested_at']),
        AnnualOperationStatus(row['status']),
    ) for row in rows[:50] if row['refund_request_id'] is not None)
    return AnnualRefundRecoveryTargetPage(
        CompanyId(str(rows[0]['company_id'])), AnnualPurchaseId(str(rows[0]['purchase_id'])),
        IncomeYear(rows[0]['income_year']), targets,
        targets[-1].refund_request_id if len(rows) > 50 else None,
    )
