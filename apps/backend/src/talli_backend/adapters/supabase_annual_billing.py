"""Verified-owner annual billing projections and local cancellation composition."""

from dataclasses import dataclass
import os

from talli_backend.adapters.postgres_annual_checkout import (
    PostgresAnnualCheckoutSession,
    PostgresAnnualCancellationSession,
)
from talli_backend.adapters.postgres_annual_cleanup import PostgresAnnualCleanupSession
from talli_backend.adapters.postgres_annual_refund_targets import _read_refund_recovery_targets
from talli_backend.adapters.postgres_annual_support import PostgresAnnualSupportReadSession
from talli_backend.adapters.postgres_annual_support_cleanup import PostgresAnnualSupportCleanupRecoverySession
from talli_backend.adapters.postgres_annual_refund import (
    PostgresAnnualRefundRecoverySession, PostgresAnnualSupportRefundRecoverySession,
)
from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration, SupabaseLedgerAdapter
from talli_backend.application.billing_session import BillingAuthenticationError
from talli_backend.application.ledger_workflow import LedgerAuthenticationError
from talli_backend.modules.billing.public import (
    AnnualAgreementCleanupPersistence,
    AnnualSupportReadPersistence,
    AnnualRefundRecoveryPersistence, AnnualSupportRefundRecoveryPersistence,
    AnnualSupportCleanupRecoveryPersistence,
    AnnualRefundRecoveryTargetsQuery,
    AnnualRefundRecoveryTargetPage,
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
            try:
                return await _read_refund_recovery_targets(connection, query, requester_id=self.actor_id.subject)
            finally:
                await self._database._authorize(connection, query.company_id)

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
    support_refund_recovery: AnnualSupportRefundRecoveryPersistence
    support_cleanup_recovery: AnnualSupportCleanupRecoveryPersistence

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
            PostgresAnnualSupportRefundRecoverySession(checkout),
            PostgresAnnualSupportCleanupRecoverySession(checkout),
        )
