"""Reconcile existing STOP evidence under a current opened billing support case."""

from dataclasses import replace
from hashlib import sha256
import json

from talli_backend.adapters.postgres_annual_checkout import PostgresAnnualCheckoutSession, _record
from talli_backend.adapters.postgres_annual_cleanup import _cleanup
from talli_backend.adapters.postgres_annual_support import _authorize_support
from talli_backend.modules.billing.public import (
    AnnualProviderOperation, AnnualSupportCleanupRecoveryPersistence,
    BillingError, billing_persistence_adapter, settle_annual_agreement_cleanup,
)


@billing_persistence_adapter(AnnualSupportCleanupRecoveryPersistence)
class PostgresAnnualSupportCleanupRecoverySession:
    def __init__(self, checkout_session: PostgresAnnualCheckoutSession):
        self._database = checkout_session

    @property
    def actor_id(self):
        return self._database.actor_id

    async def _support_transaction(self, query, work):
        if query.actor_id != self.actor_id:
            raise BillingError.forbidden()

        async def authorized(connection):
            await _authorize_support(connection, query.company_id, query.support_case_id)
            try:
                result = await work(connection)
            except BillingError:
                await _authorize_support(connection, query.company_id, query.support_case_id)
                raise
            # Do not query aborted SQL transactions. Successful reads/replays and
            # writes require the same case even when the operator is also an owner.
            await _authorize_support(connection, query.company_id, query.support_case_id)
            return result

        return await self._database._transaction(authorized)

    async def _load_locked(self, connection, query):
        checkout = await self._database._load(connection, query.company_id, query.purchase_id, lock=True)
        row = await (await connection.execute(
            """select * from billing.annual_operations where company_id=%s::uuid
            and purchase_id=%s::uuid and operation='stop_agreement' for update""",
            (str(query.company_id), str(query.purchase_id)),
        )).fetchone()
        await _authorize_support(connection, query.company_id, query.support_case_id)
        if row is None:
            raise BillingError.not_found()
        try:
            cleanup = _cleanup(row)
            intent = cleanup.intent
            fingerprint = sha256(json.dumps(row['intent'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            if (cleanup.purchase_id != query.purchase_id or intent.company_id != query.company_id
                    or intent.income_year != checkout.offer.income_year
                    or row['income_year'] != intent.income_year.value
                    or str(row['id']) != str(intent.operation_id) or row['created_at'] != intent.created_at.value
                    or row['amount_minor'] != 0 or intent.amount_minor != 0
                    or intent.operation is not AnnualProviderOperation.STOP_AGREEMENT
                    or fingerprint != row['request_fingerprint']
                    or row['idempotency_key'] != f'annual-stop-{query.purchase_id}'
                    or cleanup.provider != checkout.provider or cleanup.provider_account != checkout.provider_account
                    or not checkout.observation or not intent.agreement_reference
                    or intent.agreement_reference != checkout.observation.agreement_reference
                    or checkout.renewal_canceled_at is None):
                raise BillingError.unavailable()
            for field in ('company_id', 'income_year', 'agreement_external_reference', 'charge_reference',
                          'return_url', 'management_url', 'recurring_consent', 'original_charge_minor',
                          'original_charge_is_renewal'):
                if getattr(intent, field) != getattr(checkout.intent, field):
                    raise BillingError.unavailable()
            if cleanup.observation is not None:
                settle_annual_agreement_cleanup(replace(cleanup, observation=None), cleanup.observation)
                if row['status'] != cleanup.observation.status.value:
                    raise BillingError.unavailable()
            elif row['status'] != 'created':
                raise BillingError.unavailable()
        except (ValueError, TypeError, KeyError):
            raise BillingError.unavailable() from None
        # The existing STOP insertion guard bound its exact cancellation/refund
        # receipt to this purchase and renewal stop. That binding and its digest
        # are immutable. Recovery preserves it without reopening the receipt or
        # broadening the owner-only cancellation-receipt read policy.
        return cleanup

    async def load_cleanup_recovery(self, query):
        async def work(connection):
            return await self._load_locked(connection, query)
        return await self._support_transaction(query, work)

    async def settle_cleanup_recovery(self, query, cleanup, observation):
        async def work(connection):
            current = await self._load_locked(connection, query)
            if replace(current, observation=None) != replace(cleanup, observation=None):
                raise BillingError.unavailable()
            result = settle_annual_agreement_cleanup(current, observation)
            if result != current:
                updated = await connection.execute(
                    """update billing.annual_operations set status=%s,observation=%s::jsonb,
                    updated_at=statement_timestamp() where id=%s::uuid and company_id=%s::uuid
                    and purchase_id=%s::uuid and operation='stop_agreement'""",
                    (result.observation.status.value, json.dumps(_record(result.observation)),
                     str(current.intent.operation_id), str(query.company_id), str(query.purchase_id)),
                )
                if updated.rowcount != 1:
                    raise BillingError.unavailable()
            return result
        return await self._support_transaction(query, work)
