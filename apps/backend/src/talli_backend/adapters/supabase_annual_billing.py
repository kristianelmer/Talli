"""Verified-owner annual billing projections and local cancellation composition."""

from dataclasses import dataclass
import os

from talli_backend.adapters.postgres_annual_checkout import (
    PostgresAnnualCheckoutSession,
    PostgresAnnualCancellationSession,
)
from talli_backend.adapters.postgres_annual_cleanup import PostgresAnnualCleanupSession
from talli_backend.adapters.postgres_annual_support import PostgresAnnualSupportReadSession
from talli_backend.adapters.postgres_annual_refund import PostgresAnnualRefundRecoverySession
from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration, SupabaseLedgerAdapter
from talli_backend.application.billing_session import BillingAuthenticationError
from talli_backend.application.ledger_workflow import LedgerAuthenticationError
from talli_backend.modules.billing.public import (
    AnnualAgreementCleanupPersistence,
    AnnualSupportReadPersistence,
    AnnualRefundRecoveryPersistence,
    AnnualRefundRecoveryTargetsQuery,
    AnnualRefundRecoveryTarget,
    AnnualRefundRecoveryTargetPage,
    AnnualRefundRequestId,
    AnnualBillingReadPersistence,
    AnnualBillingSnapshotQuery,
    AnnualCancellationPersistence,
    AnnualCheckoutPersistence,
    AnnualOperationCounts,
    AnnualOperationStatus,
    AnnualPurchaseId,
    AnnualPurchaseHistoryQuery,
    AnnualPurchasePage,
    AnnualPurchaseStatus,
    AnnualPurchaseSummary,
    BillingError,
    billing_persistence_adapter,
)
from talli_backend.shared.kernel import ActorId, CompanyId, IncomeYear, Timestamp


@billing_persistence_adapter(AnnualBillingReadPersistence)
class PostgresAnnualBillingReadSession:
    def __init__(self, checkout_session: PostgresAnnualCheckoutSession):
        self._database = checkout_session

    @property
    def actor_id(self):
        return self._database.actor_id

    async def read_purchases(self, query: AnnualBillingSnapshotQuery) -> AnnualPurchasePage:
        return await self._read_purchases(query.company_id, query.actor_id, query.before_purchase_id, query.income_year)

    async def read_purchase_history(self, query: AnnualPurchaseHistoryQuery) -> AnnualPurchasePage:
        return await self._read_purchases(query.company_id, query.actor_id, query.before_purchase_id, None)

    async def read_refund_recovery_targets(
        self, query: AnnualRefundRecoveryTargetsQuery,
    ) -> AnnualRefundRecoveryTargetPage:
        if query.actor_id != self.actor_id:
            raise BillingError.forbidden()

        async def work(connection):
            await connection.execute("select set_config('talli.support_case_id', '', true)")
            await self._database._authorize(connection, query.company_id)
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
                    where r.requested_by=%s::uuid
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
                (str(query.company_id), str(query.purchase_id), str(self.actor_id.subject),
                 str(query.before_refund_request_id) if query.before_refund_request_id else None,
                 str(query.before_refund_request_id) if query.before_refund_request_id else None,
                 str(query.before_refund_request_id) if query.before_refund_request_id else None),
            )).fetchall()
            if not rows or not rows[0]['cursor_valid']:
                raise BillingError.not_found()
            await self._database._authorize(connection, query.company_id)
            targets = tuple(AnnualRefundRecoveryTarget(
                AnnualRefundRequestId(str(row['refund_request_id'])), Timestamp(row['requested_at']),
                AnnualOperationStatus(row['status']),
            ) for row in rows[:50] if row['refund_request_id'] is not None)
            return AnnualRefundRecoveryTargetPage(
                CompanyId(str(rows[0]['company_id'])), AnnualPurchaseId(str(rows[0]['purchase_id'])),
                IncomeYear(rows[0]['income_year']), targets,
                targets[-1].refund_request_id if len(rows) > 50 else None,
            )

        return await self._database._transaction(work)

    async def _read_purchases(self, company_id: CompanyId, actor_id: ActorId,
                              before_purchase_id: AnnualPurchaseId | None, income_year: IncomeYear | None) -> AnnualPurchasePage:
        if actor_id != self.actor_id:
            raise BillingError.forbidden()
        year = income_year.value if income_year else None

        async def work(connection):
            await self._database._authorize(connection, company_id)
            cursor = None
            if before_purchase_id:
                cursor = await (
                    await connection.execute(
                        """select accepted_at,id from billing.annual_purchases
                    where id=%s::uuid and company_id=%s::uuid and (%s::integer is null or income_year=%s)""",
                        (str(before_purchase_id), str(company_id), year, year),
                    )
                ).fetchone()
                if cursor is None:
                    raise BillingError.not_found()
            # One observation of stored public facts. Never load source-owned
            # acceptance/legal JSON, merchant identity or provider-operation data.
            rows = await (
                await connection.execute(
                    """with purchases as materialized (
                    select id,company_id,income_year,status,accepted_at,offer_version,terms_digest,terms_text,
                    currency,gross_minor,net_minor,vat_minor,vat_basis_points,captured_minor,refunded_minor,
                    captured_at,recurring_consent,renewal_canceled_at,paid_through,export_through,renewal_date
                    from billing.annual_purchases where company_id=%s::uuid and (%s::integer is null or income_year=%s)
                    and (%s::timestamptz is null or (accepted_at,id)<(%s::timestamptz,%s::uuid))
                    order by accepted_at desc,id desc limit 51
                ) select p.*,c.recorded_refund_minor,c.refund_initiate_by,
                    r.refund_request_count,r.latest_refund_requested_at,
                    o.created,o.pending,o.unknown,o.confirmed,o.failed
                from purchases p
                left join lateral (
                    select coalesce(max(total_entitlement_minor),0) as recorded_refund_minor,
                    min(initiate_by) filter (where total_entitlement_minor>p.refunded_minor) as refund_initiate_by
                    from billing.annual_refund_cases where purchase_id=p.id and company_id=p.company_id
                ) c on true
                left join lateral (
                    select count(*) as refund_request_count,max(requested_at) as latest_refund_requested_at
                    from billing.annual_refund_requests where purchase_id=p.id and company_id=p.company_id
                ) r on true
                left join lateral (
                    select
                    count(*) filter (where status='created') as created,
                    count(*) filter (where status='pending') as pending,
                    count(*) filter (where status='unknown') as unknown,
                    count(*) filter (where status='confirmed') as confirmed,
                    count(*) filter (where status='failed') as failed
                    from billing.annual_operations
                    where purchase_id=p.id and company_id=p.company_id and operation='refund'
                ) o on true order by p.accepted_at desc,p.id desc""",
                    (
                        str(company_id),
                        year,
                        year,
                        cursor["accepted_at"] if cursor else None,
                        cursor["accepted_at"] if cursor else None,
                        str(cursor["id"]) if cursor else None,
                    ),
                )
            ).fetchall()
            # Remove the database key name before constructing the public value.
            values = []
            for row in rows[:50]:
                value = dict(row)
                value["purchase_id"] = AnnualPurchaseId(str(value.pop("id")))
                value["company_id"] = CompanyId(str(value["company_id"]))
                value["income_year"] = IncomeYear(value["income_year"])
                value["status"] = AnnualPurchaseStatus(value["status"])
                for name in ("accepted_at", "captured_at", "renewal_canceled_at", "latest_refund_requested_at"):
                    value[name] = Timestamp(value[name]) if value[name] else None
                value["refund_operations"] = AnnualOperationCounts(**{
                    name: value.pop(name) for name in ("created", "pending", "unknown", "confirmed", "failed")
                })
                values.append(AnnualPurchaseSummary(**value))
            return AnnualPurchasePage(tuple(values), values[-1].purchase_id if len(rows) > 50 else None)

        return await self._database._transaction(work)


@dataclass(frozen=True, slots=True)
class _AnnualBillingSession:
    reads: AnnualBillingReadPersistence
    cancellation: AnnualCancellationPersistence
    checkout: AnnualCheckoutPersistence
    cleanup: AnnualAgreementCleanupPersistence
    support_reads: AnnualSupportReadPersistence
    refund_recovery: AnnualRefundRecoveryPersistence

    @property
    def actor_id(self):
        return self.reads.actor_id


class SupabaseAnnualBillingAdapter:
    def __init__(self, configuration: LedgerSupabaseConfiguration):
        self._configuration = configuration
        self._authentication = SupabaseLedgerAdapter(configuration)

    @classmethod
    def from_environment(cls):
        return cls(
            LedgerSupabaseConfiguration(
                url=os.environ.get("SUPABASE_URL", ""),
                anon_key=os.environ.get("SUPABASE_ANON_KEY", ""),
                database_url=os.environ.get("TALLI_LEDGER_DATABASE_URL", ""),
            )
        )

    async def session(self, access_token: str) -> _AnnualBillingSession:
        try:
            ledger = await self._authentication.session(access_token)
        except LedgerAuthenticationError:
            raise BillingAuthenticationError from None
        checkout = PostgresAnnualCheckoutSession(self._configuration.database_url, ledger._verified)
        return _AnnualBillingSession(
            PostgresAnnualBillingReadSession(checkout), PostgresAnnualCancellationSession(checkout), checkout,
            PostgresAnnualCleanupSession(checkout),
            PostgresAnnualSupportReadSession(checkout), PostgresAnnualRefundRecoverySession(checkout),
        )
