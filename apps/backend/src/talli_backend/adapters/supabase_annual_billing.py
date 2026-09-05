"""Verified-owner annual billing projections and local cancellation composition."""

from dataclasses import dataclass
import os

from talli_backend.adapters.postgres_annual_checkout import (
    PostgresAnnualCheckoutSession,
    PostgresAnnualCancellationSession,
)
from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration, SupabaseLedgerAdapter
from talli_backend.application.billing_session import BillingAuthenticationError
from talli_backend.application.ledger_workflow import LedgerAuthenticationError
from talli_backend.modules.billing.public import (
    AnnualBillingReadPersistence,
    AnnualBillingSnapshotQuery,
    AnnualCancellationPersistence,
    AnnualCheckoutPersistence,
    AnnualPurchaseId,
    AnnualPurchasePage,
    AnnualPurchaseStatus,
    AnnualPurchaseSummary,
    BillingError,
    billing_persistence_adapter,
)
from talli_backend.shared.kernel import CompanyId, IncomeYear, Timestamp


@billing_persistence_adapter(AnnualBillingReadPersistence)
class PostgresAnnualBillingReadSession:
    def __init__(self, checkout_session: PostgresAnnualCheckoutSession):
        self._database = checkout_session

    @property
    def actor_id(self):
        return self._database.actor_id

    async def read_purchases(self, query: AnnualBillingSnapshotQuery) -> AnnualPurchasePage:
        if query.actor_id != self.actor_id:
            raise BillingError.forbidden()

        async def work(connection):
            await self._database._authorize(connection, query.company_id)
            cursor = None
            if query.before_purchase_id:
                cursor = await (
                    await connection.execute(
                        """select accepted_at,id from billing.annual_purchases
                    where id=%s::uuid and company_id=%s::uuid and income_year=%s""",
                        (str(query.before_purchase_id), str(query.company_id), query.income_year.value),
                    )
                ).fetchone()
                if cursor is None:
                    raise BillingError.not_found()
            # One observation of stored public facts. Never load source-owned
            # acceptance/legal JSON, merchant identity or provider-operation data.
            rows = await (
                await connection.execute(
                    """select id,company_id,income_year,status,accepted_at,offer_version,terms_digest,terms_text,
                currency,gross_minor,net_minor,vat_minor,vat_basis_points,captured_minor,refunded_minor,
                captured_at,recurring_consent,renewal_canceled_at,paid_through,export_through,renewal_date
                from billing.annual_purchases where company_id=%s::uuid and income_year=%s
                and (%s::timestamptz is null or (accepted_at,id)<(%s::timestamptz,%s::uuid))
                order by accepted_at desc,id desc limit 51""",
                    (
                        str(query.company_id),
                        query.income_year.value,
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
                for name in ("accepted_at", "captured_at", "renewal_canceled_at"):
                    value[name] = Timestamp(value[name]) if value[name] else None
                values.append(AnnualPurchaseSummary(**value))
            return AnnualPurchasePage(tuple(values), values[-1].purchase_id if len(rows) > 50 else None)

        return await self._database._transaction(work)


@dataclass(frozen=True, slots=True)
class _AnnualBillingSession:
    reads: AnnualBillingReadPersistence
    cancellation: AnnualCancellationPersistence
    checkout: AnnualCheckoutPersistence

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
            PostgresAnnualBillingReadSession(checkout), PostgresAnnualCancellationSession(checkout), checkout
        )
