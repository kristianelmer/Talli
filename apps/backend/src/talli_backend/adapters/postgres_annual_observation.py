"""Account-bound observation of committed checkout operations; never owner claims."""

from asyncio import timeout
from datetime import UTC, date, datetime

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from talli_backend.adapters.postgres_annual_checkout import _checkout, _record
from talli_backend.modules.billing.public import (
    AnnualCheckoutObservationBinding, AnnualCheckoutObservationLease,
    AnnualCheckoutObservationPersistence, AnnualPurchaseId, BillingPaymentEventId,
    BillingError, billing_persistence_adapter, settle_annual_checkout,
    validate_annual_checkout_observation,
)
from talli_backend.shared.kernel import CompanyId, IncomeYear, Timestamp, UserId


def _validated_checkout(record):
    purchase, operation = dict(record["purchase"]), record["operation"]
    for field in ("paid_through", "export_through", "renewal_date"):
        purchase[field] = date.fromisoformat(purchase[field])
    for field in ("captured_at", "renewal_canceled_at"):
        if purchase[field]:
            purchase[field] = datetime.fromisoformat(purchase[field])
    if (str(operation["purchase_id"]) != str(purchase["id"])
            or operation["company_id"] != purchase["company_id"]
            or operation["income_year"] != purchase["income_year"]
            or operation["operation"] != "checkout"):
        raise BillingError.unavailable()
    checkout = _checkout(purchase, operation)
    validate_annual_checkout_observation(checkout, AnnualCheckoutObservationBinding(
        purchase_id=AnnualPurchaseId(str(operation["purchase_id"])),
        operation_id=BillingPaymentEventId(str(operation["id"])),
        company_id=CompanyId(str(operation["company_id"])),
        income_year=IncomeYear(operation["income_year"]),
        created_by=UserId(str(operation["created_by"])),
        accepted_at=Timestamp(datetime.fromisoformat(purchase["accepted_at"])),
        created_at=Timestamp(datetime.fromisoformat(operation["created_at"])),
        amount_minor=operation["amount_minor"],
        agreement_external_reference=purchase["agreement_external_reference"],
        charge_reference=purchase["charge_reference"],
        recurring_consent=purchase["recurring_consent"],
        consent_version=purchase["consent_version"],
    ))
    return checkout


@billing_persistence_adapter(AnnualCheckoutObservationPersistence)
class PostgresAnnualCheckoutObservationStore:
    def __init__(self, database_url: str, provider: str, provider_account: str):
        self._database_url = database_url
        self._provider = provider
        self._provider_account = provider_account

    @property
    def provider(self):
        return self._provider

    @property
    def provider_account(self):
        return self._provider_account

    async def _transaction(self, work):
        if not self._database_url or not self.provider or not self.provider_account:
            raise BillingError.unavailable()
        try:
            async with (
                timeout(10),
                await psycopg.AsyncConnection.connect(
                    self._database_url, connect_timeout=5, row_factory=dict_row,
                    options="-c statement_timeout=5000 -c lock_timeout=1000",
                ) as connection,
                connection.transaction(),
            ):
                await connection.execute("set transaction isolation level read committed")
                await connection.execute("set local role annual_checkout_observer_executor")
                # No JWT, verified actor GUC, owner role, or source callback exists.
                return await work(connection)
        except BillingError:
            raise
        except Exception:
            raise BillingError.unavailable() from None

    async def claim_checkout_observation(self):
        async def work(connection):
            # Bad immutable records receive only a technical retry marker. Bounded
            # scanning permits a later valid checkout to progress in the same pass.
            for _ in range(10):
                row = await (await connection.execute(
                    "select billing.annual_observer_candidate_v1(%s,%s) as record",
                    (self.provider, self.provider_account),
                )).fetchone()
                record = row["record"]
                if record is None:
                    return None
                try:
                    checkout = _validated_checkout(record)
                    valid = checkout.provider == self.provider and checkout.provider_account == self.provider_account
                except (BillingError, ValueError, KeyError, TypeError):
                    valid = False
                claimed = await (await connection.execute(
                    "select billing.annual_observer_admit_v1(%s,%s,%s) as lease",
                    (record["operation"]["id"], record["epoch"], valid),
                )).fetchone()
                if valid:
                    lease = AnnualCheckoutObservationLease(checkout, claimed["lease"]["token"], claimed["lease"]["fence"])
                    await self._authorize(connection, lease)
                    return lease
            return None
        return await self._transaction(work)

    async def _authorize(self, connection, lease):
        await connection.execute("select billing.annual_observer_authorize_v1(%s,%s,%s)",
                                 (str(lease.checkout.intent.operation_id), lease.token, lease.fence))

    async def authorize_checkout_observation(self, lease):
        async def work(connection):
            await self._authorize(connection, lease)
        await self._transaction(work)

    async def settle_checkout_observation(self, lease, observation):
        async def work(connection):
            parameters = (str(lease.checkout.intent.operation_id), lease.token, lease.fence)
            row = await (await connection.execute(
                "select billing.annual_observer_lock_v1(%s,%s,%s) as record", parameters,
            )).fetchone()
            current = _validated_checkout(row["record"])
            if (current.intent != lease.checkout.intent
                    or current.request_fingerprint != lease.checkout.request_fingerprint
                    or current.provider != self.provider or current.provider_account != self.provider_account):
                raise BillingError.unavailable()
            result = (settle_annual_checkout(current, observation, Timestamp(datetime.now(UTC)))
                      if observation is not None else current)
            # A stale observation or owner-won terminal state is an immutable replay.
            saved = Jsonb(_record(result.observation)) if result != current else None
            await connection.execute(
                "select billing.annual_observer_finish_v1(%s,%s,%s,%s,%s)",
                (*parameters, result.status.value, saved),
            )
            return result
        return await self._transaction(work)
