"""Read bounded annual evidence under an existing, explicitly opened billing case."""

from talli_backend.adapters.postgres_annual_refund_targets import _read_refund_recovery_targets
from talli_backend.adapters.postgres_annual_checkout import PostgresAnnualCheckoutSession
from talli_backend.modules.billing.public import (
    AnnualOperationCounts, AnnualOperationStatus, AnnualPurchaseId, AnnualPurchaseStatus,
    AnnualSupportPage, AnnualSupportPurchase, AnnualSupportQuery, AnnualSupportReadPersistence,
    AnnualSupportRefundRecoveryTargetsQuery, AnnualRefundRecoveryTargetPage,
    BillingError, billing_persistence_adapter,
)
from talli_backend.shared.kernel import CompanyId, IncomeYear, Timestamp


async def _authorize_support(connection, company_id, support_case_id):
    """Require an active admin and its explicit current billing case, even for an owner."""
    await connection.execute(
        "select set_config('talli.support_case_id', %s, true)", (str(support_case_id),),
    )
    authority = await (await connection.execute(
        """select public.company_access_is_active_admin_v1() as admin,
        public.company_access_has_fresh_mfa_v1() as fresh,
        public.company_access_has_open_support_case_v1(
            public.company_access_current_support_case_id_v1(), %s::uuid, 'billing') as allowed""",
        (str(company_id),),
    )).fetchone()
    if not authority['admin']:
        raise BillingError.forbidden()
    if not authority['fresh']:
        raise BillingError.step_up_required()
    if not authority['allowed']:
        raise BillingError.forbidden()


@billing_persistence_adapter(AnnualSupportReadPersistence)
class PostgresAnnualSupportReadSession:
    def __init__(self, checkout_session: PostgresAnnualCheckoutSession):
        self._database = checkout_session

    @property
    def actor_id(self):
        return self._database.actor_id

    async def read_support_purchases(self, query: AnnualSupportQuery) -> AnnualSupportPage:
        if query.actor_id != self.actor_id:
            raise BillingError.forbidden()

        async def work(connection):
            await connection.execute(
                "select set_config('talli.support_case_id', %s, true)", (str(query.support_case_id),),
            )
            # Authorization, cursor scope, current money and related summaries
            # use one statement snapshot. The authority row survives an empty
            # result, so denied access cannot masquerade as an empty history.
            rows = await (await connection.execute(
                """with authority as materialized (
                    select public.company_access_has_fresh_mfa_v1() as fresh,
                    public.company_access_is_active_admin_v1() as admin,
                    (public.company_access_is_active_admin_v1() and
                     public.company_access_has_open_support_case_v1(
                       public.company_access_current_support_case_id_v1(), %(company)s::uuid, 'billing')) as allowed
                ), cursor as materialized (
                    select accepted_at,id from billing.annual_purchases
                    where id=%(before)s::uuid and company_id=%(company)s::uuid
                ), purchases as materialized (
                    select p.id,p.company_id,p.income_year,p.status,p.accepted_at,p.updated_at,
                    p.currency,p.gross_minor,p.captured_minor,p.refunded_minor,p.renewal_canceled_at,
                    p.paid_through,p.export_through,p.recurring_consent
                    from billing.annual_purchases p cross join authority a
                    where a.allowed and a.fresh and p.company_id=%(company)s::uuid
                    and (%(before)s::uuid is null or (p.accepted_at,p.id)<(select accepted_at,id from cursor))
                    order by p.accepted_at desc,p.id desc limit 51
                )
                select a.fresh,a.admin,a.allowed,
                  (%(before)s::uuid is null or exists(select 1 from cursor)) as cursor_valid,
                  p.*,c.refund_case_count,c.recorded_refund_minor,c.refund_initiate_by,
                  r.refund_request_count,r.latest_refund_requested_at,
                  o.created,o.pending,o.unknown,o.confirmed,o.failed,o.cleanup_status
                from authority a left join purchases p on true
                left join lateral (
                    select count(*) as refund_case_count,
                    coalesce(max(total_entitlement_minor),0) as recorded_refund_minor,
                    min(initiate_by) filter (where total_entitlement_minor>p.refunded_minor) as refund_initiate_by
                    from billing.annual_refund_cases where purchase_id=p.id and company_id=p.company_id
                ) c on true
                left join lateral (
                    select count(*) as refund_request_count,max(requested_at) as latest_refund_requested_at
                    from billing.annual_refund_requests where purchase_id=p.id and company_id=p.company_id
                ) r on true
                left join lateral (
                    select
                    count(*) filter (where operation='refund' and status='created') as created,
                    count(*) filter (where operation='refund' and status='pending') as pending,
                    count(*) filter (where operation='refund' and status='unknown') as unknown,
                    count(*) filter (where operation='refund' and status='confirmed') as confirmed,
                    count(*) filter (where operation='refund' and status='failed') as failed,
                    max(status) filter (where operation='stop_agreement') as cleanup_status
                    from billing.annual_operations where purchase_id=p.id and company_id=p.company_id
                ) o on true order by p.accepted_at desc,p.id desc""",
                {"company": str(query.company_id), "before": str(query.before_purchase_id) if query.before_purchase_id else None},
            )).fetchall()
            authority = rows[0]
            if not authority['admin']:
                raise BillingError.forbidden()
            if not authority['fresh']:
                raise BillingError.step_up_required()
            if not authority['allowed']:
                raise BillingError.forbidden()
            if not authority['cursor_valid']:
                raise BillingError.not_found()
            values = []
            for row in rows[:50]:
                if row['id'] is None:
                    continue
                value = {name: row[name] for name in (
                    'recurring_consent', 'currency', 'gross_minor', 'captured_minor', 'refunded_minor', 'paid_through', 'export_through',
                    'refund_case_count', 'recorded_refund_minor', 'refund_initiate_by', 'refund_request_count',
                )}
                values.append(AnnualSupportPurchase(
                    **value, purchase_id=AnnualPurchaseId(str(row['id'])), company_id=CompanyId(str(row['company_id'])),
                    income_year=IncomeYear(row['income_year']), status=AnnualPurchaseStatus(row['status']),
                    accepted_at=Timestamp(row['accepted_at']), updated_at=Timestamp(row['updated_at']),
                    renewal_canceled_at=Timestamp(row['renewal_canceled_at']) if row['renewal_canceled_at'] else None,
                    latest_refund_requested_at=Timestamp(row['latest_refund_requested_at']) if row['latest_refund_requested_at'] else None,
                    refund_operations=AnnualOperationCounts(**{name: row[name] for name in ('created', 'pending', 'unknown', 'confirmed', 'failed')}),
                    cleanup_status=AnnualOperationStatus(row['cleanup_status']) if row['cleanup_status'] else None,
                ))
            return AnnualSupportPage(tuple(values), values[-1].purchase_id if len(rows)>50 else None)

        return await self._database._transaction(work)

    async def read_refund_recovery_targets(
        self, query: AnnualSupportRefundRecoveryTargetsQuery,
    ) -> AnnualRefundRecoveryTargetPage:
        if query.actor_id != self.actor_id:
            raise BillingError.forbidden()

        async def work(connection):
            await _authorize_support(connection, query.company_id, query.support_case_id)
            try:
                return await _read_refund_recovery_targets(connection, query, requester_id=None)
            finally:
                # A denied or empty projection cannot retain earlier authority.
                await _authorize_support(connection, query.company_id, query.support_case_id)

        return await self._database._transaction(work)
