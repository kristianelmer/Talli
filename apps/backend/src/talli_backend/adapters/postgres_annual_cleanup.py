"""Receipt-bound original agreement cleanup in verified-owner transactions."""

from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
import json
from uuid import uuid4

from talli_backend.adapters.postgres_annual_checkout import (
    PostgresAnnualCheckoutSession,
    _provider_intent,
    _record,
    _timestamp,
)
from talli_backend.modules.billing.public import (
    AnnualAgreementCleanup,
    AnnualAgreementCleanupClaim,
    AnnualAgreementCleanupPersistence,
    AnnualCancellationId,
    AnnualProviderObservation,
    AnnualProviderOperation,
    AnnualProviderStatus,
    AnnualPurchaseId,
    AnnualPurchaseStatus,
    BillingError,
    BillingErrorCode,
    BillingPaymentEventId,
    billing_persistence_adapter,
    settle_annual_agreement_cleanup,
)
from talli_backend.shared.kernel import Timestamp


def _cleanup(row):
    saved = row["intent"]
    observation = row["observation"]
    if observation is not None:
        observation = AnnualProviderObservation(
            **(
                observation
                | {
                    "operation": AnnualProviderOperation(observation["operation"]),
                    "status": AnnualProviderStatus(observation["status"]),
                    "captured_at": _timestamp(observation["captured_at"]),
                }
            )
        )
    return AnnualAgreementCleanup(
        purchase_id=AnnualPurchaseId(str(row["purchase_id"])),
        cancellation_id=AnnualCancellationId(saved["cancellation_id"]),
        provider=saved["provider"],
        provider_account=saved["provider_account"],
        intent=_provider_intent(saved["provider_intent"]),
        observation=observation,
    )


@billing_persistence_adapter(AnnualAgreementCleanupPersistence)
class PostgresAnnualCleanupSession:
    def __init__(self, checkout_session: PostgresAnnualCheckoutSession):
        self._database = checkout_session

    @property
    def actor_id(self):
        return self._database.actor_id

    async def _find(self, connection, purchase_id):
        return await (
            await connection.execute(
                "select * from billing.annual_operations where purchase_id=%s::uuid and operation='stop_agreement' for update",
                (str(purchase_id),),
            )
        ).fetchone()

    async def claim_agreement_cleanup(self, company_id, purchase_id):
        async def work(connection):
            await self._database._authorize(connection, company_id)
            checkout = await self._database._load(connection, company_id, purchase_id, lock=True)
            existing = await self._find(connection, purchase_id)
            if existing:
                return AnnualAgreementCleanupClaim(_cleanup(existing), False)
            previous = checkout.observation
            if (
                checkout.renewal_canceled_at is None
                or previous is None
                or not previous.agreement_reference
                or checkout.status is AnnualPurchaseStatus.PENDING
                or (
                    checkout.status in {AnnualPurchaseStatus.PAID, AnnualPurchaseStatus.REFUNDED}
                    and (
                        previous.status is not AnnualProviderStatus.CONFIRMED
                        or previous.captured_minor != checkout.offer.gross_minor
                    )
                )
                or (
                    checkout.status is AnnualPurchaseStatus.FAILED
                    and (previous.status is not AnnualProviderStatus.FAILED or previous.captured_minor != 0)
                )
            ):
                return None
            receipt = await (
                await connection.execute(
                    """select id from billing.annual_cancellation_requests where purchase_id=%s::uuid
                and company_id=%s::uuid and effective_at=%s order by requested_at,id limit 1""",
                    (str(purchase_id), str(company_id), checkout.renewal_canceled_at.value),
                )
            ).fetchone()
            if receipt is None:
                return None
            # Only original checkout agreements are supported. Future shared
            # agreements require explicit year lineage and worker authority.
            competing = await (
                await connection.execute(
                    """select 1 from billing.annual_operations where purchase_id=%s::uuid
                and operation='renewal' union all select 1 from billing.annual_purchases
                where id<>%s::uuid and provider=%s and provider_account=%s and agreement_reference=%s limit 1""",
                    (
                        str(purchase_id),
                        str(purchase_id),
                        checkout.provider,
                        checkout.provider_account,
                        previous.agreement_reference,
                    ),
                )
            ).fetchone()
            if competing:
                return None
            intent = replace(
                checkout.intent,
                operation_id=BillingPaymentEventId(str(uuid4())),
                operation=AnnualProviderOperation.STOP_AGREEMENT,
                amount_minor=0,
                created_at=Timestamp(datetime.now(UTC)),
                agreement_reference=previous.agreement_reference,
            )
            saved = {
                "provider_intent": _record(intent),
                "cancellation_id": str(receipt["id"]),
                "provider": checkout.provider,
                "provider_account": checkout.provider_account,
            }
            key = f"annual-stop-{purchase_id}"
            fingerprint = sha256(
                json.dumps(saved, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            await connection.execute(
                """insert into billing.annual_operations
                (id,purchase_id,company_id,income_year,created_by,created_at,idempotency_key,request_fingerprint,operation,amount_minor,intent)
                values (%s::uuid,%s::uuid,%s::uuid,%s,%s::uuid,%s,%s,%s,'stop_agreement',0,%s::jsonb)""",
                (
                    str(intent.operation_id),
                    str(purchase_id),
                    str(company_id),
                    checkout.offer.income_year.value,
                    str(self.actor_id.subject),
                    intent.created_at.value,
                    key,
                    fingerprint,
                    json.dumps(saved),
                ),
            )
            return AnnualAgreementCleanupClaim(_cleanup(await self._find(connection, purchase_id)), True)

        return await self._database._transaction(work)

    async def settle_agreement_cleanup(self, cleanup, observation):
        async def work(connection):
            await self._database._authorize(connection, cleanup.intent.company_id)
            await self._database._load(connection, cleanup.intent.company_id, cleanup.purchase_id, lock=True)
            row = await self._find(connection, cleanup.purchase_id)
            if row is None:
                raise BillingError.not_found()
            current = _cleanup(row)
            if (
                current.intent != cleanup.intent
                or current.cancellation_id != cleanup.cancellation_id
                or current.provider != cleanup.provider
                or current.provider_account != cleanup.provider_account
            ):
                raise BillingError.conflict(BillingErrorCode.IDEMPOTENCY_KEY_REUSED)
            result = settle_annual_agreement_cleanup(current, observation)
            if result == current:
                return current
            await connection.execute(
                """update billing.annual_operations set status=%s,observation=%s::jsonb,
                updated_at=statement_timestamp() where id=%s::uuid""",
                (
                    result.observation.status.value,
                    json.dumps(_record(result.observation)),
                    str(current.intent.operation_id),
                ),
            )
            return result

        return await self._database._transaction(work)
