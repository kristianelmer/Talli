"""Annual claims and settlement in short, verified-actor PostgreSQL transactions.

No runtime binds this adapter yet. The readiness verifier defaults to unavailable;
fixtures may supply a verifier, but cannot provide real-company charge authority.
"""

from asyncio import timeout
from collections.abc import Awaitable, Callable
from dataclasses import fields, replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
import json

import psycopg
from psycopg.rows import dict_row

from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.modules.billing.public import (
    AnnualBillingOffer,
    AnnualCancellationId,
    AnnualCancellationPersistence,
    AnnualRenewalCancellation,
    CancelAnnualRenewalCommand,
    AnnualCheckout,
    AnnualCheckoutClaim,
    AnnualCheckoutPersistence,
    AnnualCheckoutPrerequisites,
    AnnualCheckoutPurchaseReference,
    AnnualCheckoutRequestResolution,
    AnnualCheckoutWithdrawalId,
    StartAnnualCheckoutCommand,
    AnnualProviderIntent,
    AnnualProviderObservation,
    AnnualProviderOperation,
    AnnualProviderStatus,
    AnnualPurchaseId,
    AnnualPurchaseStatus,
    BillingError,
    BillingErrorCode,
    BillingPaymentEventId,
    billing_persistence_adapter,
    settle_annual_checkout,
    annual_billing_consent_version,
)
from talli_backend.shared.kernel import CompanyId, IdempotencyKey, IncomeYear, Timestamp, UserId


def _json_value(value):
    if isinstance(value, (Timestamp, IncomeYear)):
        return _json_value(value.value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return str(value)


def _record(value):
    return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}


def _timestamp(value):
    return (
        Timestamp(value if isinstance(value, datetime) else datetime.fromisoformat(value)) if value else None
    )


def _provider_intent(value):
    return AnnualProviderIntent(
        **(
            value
            | {
                "operation_id": BillingPaymentEventId(value["operation_id"]),
                "company_id": CompanyId(value["company_id"]),
                "income_year": IncomeYear(value["income_year"]),
                "operation": AnnualProviderOperation(value["operation"]),
                "created_at": _timestamp(value["created_at"]),
                "due_date": date.fromisoformat(value["due_date"]) if value["due_date"] else None,
            }
        )
    )


def _checkout(purchase, operation):
    saved = operation["intent"]
    intent = saved["provider_intent"]
    offer = AnnualBillingOffer(
        company_id=CompanyId(str(purchase["company_id"])),
        income_year=IncomeYear(purchase["income_year"]),
        **{
            key: purchase[key]
            for key in (
                "offer_version",
                "terms_digest",
                "terms_text",
                "currency",
                "gross_minor",
                "net_minor",
                "vat_minor",
                "vat_basis_points",
                "paid_through",
                "export_through",
                "renewal_date",
            )
        },
        renewal_reminder_by=date.fromisoformat(saved["renewal_reminder_by"]),
        price_change_notice_by=date.fromisoformat(saved["price_change_notice_by"]),
    )
    observation = operation["observation"]
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
        # Purchase totals can advance through another durable operation (refund).
        observation = replace(
            observation,
            captured_minor=purchase["captured_minor"],
            refunded_minor=purchase["refunded_minor"],
            agreement_reference=purchase["agreement_reference"],
            captured_at=Timestamp(purchase["captured_at"]) if purchase["captured_at"] else None,
        )
    return AnnualCheckout(
        purchase_id=AnnualPurchaseId(str(purchase["id"])),
        offer=offer,
        accepted_by=UserId(str(purchase["accepted_by"])),
        request_fingerprint=operation["request_fingerprint"],
        idempotency_key=IdempotencyKey(operation["idempotency_key"]),
        provider=purchase["provider"],
        provider_account=purchase["provider_account"],
        intent=_provider_intent(intent),
        status=AnnualPurchaseStatus(purchase["status"]),
        observation=observation,
        renewal_canceled_at=_timestamp(purchase["renewal_canceled_at"]),
    )


async def _unavailable_readiness(evidence: AnnualCheckoutPrerequisites) -> bool:
    return False


@billing_persistence_adapter(AnnualCheckoutPersistence)
class PostgresAnnualCheckoutSession:
    def __init__(
        self,
        database_url: str,
        verified: _VerifiedActor,
        *,
        readiness_is_current: Callable[
            [AnnualCheckoutPrerequisites], Awaitable[bool]
        ] = _unavailable_readiness,
    ) -> None:
        self._database_url = database_url
        self._verified = verified
        # Must validate the exact source-owned identity, scope and digest. No
        # browser field or legacy readiness snapshot is an acceptable binding.
        self._readiness_is_current = readiness_is_current

    @property
    def actor_id(self):
        return self._verified.actor_id

    async def _transaction(self, work):
        if not self._database_url:
            raise BillingError.unavailable()
        try:
            async with (
                timeout(10),
                await psycopg.AsyncConnection.connect(
                    self._database_url,
                    connect_timeout=5,
                    row_factory=dict_row,
                    options="-c statement_timeout=5000 -c lock_timeout=1000",
                ) as connection,
                connection.transaction(),
            ):
                await connection.execute("set local role billing_store_owner")
                await connection.execute(
                    "select set_config('talli.verified_actor_id', %s, true), set_config('talli.verified_actor_claims', %s, true)",
                    (str(self.actor_id.subject), self._verified.claims_json),
                )
                return await work(connection)
        except BillingError:
            raise
        except psycopg.errors.UniqueViolation:
            # Global key constraints never reveal another tenant's purchase.
            raise BillingError.conflict(BillingErrorCode.IDEMPOTENCY_KEY_REUSED) from None
        except psycopg.errors.InsufficientPrivilege:
            raise BillingError.forbidden() from None
        except (TimeoutError, psycopg.DatabaseError):
            raise BillingError.unavailable() from None

    async def _authorize(self, connection, company_id):
        row = await (
            await connection.execute(
                "select public.company_access_is_accepted_owner_v1(%s::uuid) as owner, public.company_access_has_fresh_mfa_v1() as fresh",
                (str(company_id),),
            )
        ).fetchone()
        if not row["owner"]:
            raise BillingError.forbidden()
        if not row["fresh"]:
            raise BillingError.step_up_required()

    async def authorize_owner_command(self, company_id: CompanyId) -> None:
        await self._transaction(lambda connection: self._authorize(connection, company_id))

    async def _owner_transaction(self, company_id, work):
        async def authorized(connection):
            await connection.execute("select set_config('talli.support_case_id', '', true)")
            await self._authorize(connection, company_id)
            try:
                result = await work(connection)
            except BillingError:
                # RLS can hide a row after authority changes. SQL errors instead
                # go directly to rollback; an aborted transaction cannot recheck.
                await self._authorize(connection, company_id)
                raise
            await self._authorize(connection, company_id)
            return result

        return await self._transaction(authorized)

    async def _find(self, connection, company_id, key):
        row = await (
            await connection.execute(
                """select to_jsonb(p) as purchase, to_jsonb(o) as operation
            from billing.annual_operations o join billing.annual_purchases p on p.id=o.purchase_id
            where o.company_id=%s::uuid and o.idempotency_key=%s and o.operation='checkout'""",
                (str(company_id), str(key)),
            )
        ).fetchone()
        if row is None:
            return None
        # to_jsonb serializes date/timestamp purchase columns; restore their types.
        purchase = row["purchase"]
        for key in ("paid_through", "export_through", "renewal_date"):
            purchase[key] = date.fromisoformat(purchase[key])
        if purchase["captured_at"]:
            purchase["captured_at"] = datetime.fromisoformat(purchase["captured_at"])
        return _checkout(purchase, row["operation"])

    async def _withdrawal(self, connection, company_id, key):
        return await (await connection.execute(
            """select * from billing.annual_checkout_withdrawals
            where company_id=%s::uuid and idempotency_key=%s""",
            (str(company_id), str(key)),
        )).fetchone()

    async def _reject_withdrawal(self, connection, company_id, key, fingerprint):
        receipt = await self._withdrawal(connection, company_id, key)
        await self._authorize(connection, company_id)
        if receipt is not None:
            code = (BillingErrorCode.CHECKOUT_REQUEST_WITHDRAWN
                    if receipt["request_fingerprint"] == fingerprint
                    else BillingErrorCode.IDEMPOTENCY_KEY_REUSED)
            raise BillingError.conflict(code)

    async def find_checkout(
        self, company_id: CompanyId, key: IdempotencyKey, request_fingerprint: str,
    ) -> AnnualCheckout | None:
        async def work(connection):
            await self._authorize(connection, company_id)
            existing = await self._find(connection, company_id, key)
            if existing is None:
                await self._reject_withdrawal(connection, company_id, key, request_fingerprint)
            await self._authorize(connection, company_id)
            return existing

        return await self._transaction(work)

    async def _lock_original_key(self, connection, company_id, key):
        await connection.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s, 192))",
            (f"annual-checkout-key|{key}",),
        )
        await self._authorize(connection, company_id)

    async def withdraw_checkout_request(
        self, command: StartAnnualCheckoutCommand, request_fingerprint: str,
    ) -> AnnualCheckoutRequestResolution:
        async def work(connection):
            company, year, key = command.company_id, command.income_year, command.idempotency_key
            if command.actor_id != self.actor_id:
                raise BillingError.forbidden()
            await self._authorize(connection, company)
            await self._lock_original_key(connection, company, key)
            await self._lock_company_year(connection, company, year)
            existing = await (await connection.execute(
                """select purchase_id, income_year, created_by, request_fingerprint
                from billing.annual_operations where company_id=%s::uuid
                and idempotency_key=%s and operation='checkout'""",
                (str(company), str(key)),
            )).fetchone()
            if existing is not None:
                if (existing["income_year"] != year.value
                        or str(existing["created_by"]) != str(self.actor_id.subject)
                        or existing["request_fingerprint"] != request_fingerprint):
                    raise BillingError.conflict(BillingErrorCode.IDEMPOTENCY_KEY_REUSED)
                await self._authorize(connection, company)
                return AnnualCheckoutRequestResolution(
                    company, year, AnnualPurchaseId(str(existing["purchase_id"])), None, None,
                )
            receipt = await self._withdrawal(connection, company, key)
            if receipt is None:
                receipt = await (await connection.execute(
                    """insert into billing.annual_checkout_withdrawals
                    (company_id,income_year,requested_by,idempotency_key,request_fingerprint,
                     offer_version,terms_digest,purchase_accepted,recurring_consent,consent_version)
                    values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *""",
                    (str(company), year.value, str(self.actor_id.subject), str(key), request_fingerprint,
                     command.offer_version, command.terms_digest, command.purchase_accepted,
                     command.recurring_consent, command.consent_version),
                )).fetchone()
            expected = {
                "income_year": year.value, "request_fingerprint": request_fingerprint,
                "offer_version": command.offer_version, "terms_digest": command.terms_digest,
                "purchase_accepted": command.purchase_accepted, "recurring_consent": command.recurring_consent,
                "consent_version": command.consent_version,
            }
            if (str(receipt["requested_by"]) != str(self.actor_id.subject)
                    or any(receipt[field] != value for field, value in expected.items())):
                raise BillingError.conflict(BillingErrorCode.IDEMPOTENCY_KEY_REUSED)
            await self._authorize(connection, company)
            return AnnualCheckoutRequestResolution(
                company, year, None, AnnualCheckoutWithdrawalId(str(receipt["id"])),
                Timestamp(receipt["requested_at"]),
            )

        return await self._transaction(work)

    async def _find_active(self, connection, company_id, income_year):
        row = await (
            await connection.execute(
                """select id, status from billing.annual_purchases
                where company_id=%s::uuid and income_year=%s and status in ('pending','paid')""",
                (str(company_id), income_year.value),
            )
        ).fetchone()
        return (AnnualCheckoutPurchaseReference(
            company_id, income_year, AnnualPurchaseId(str(row["id"])), AnnualPurchaseStatus(row["status"]),
        ) if row is not None else None)

    async def find_active_checkout(
        self, company_id: CompanyId, income_year: IncomeYear,
    ) -> AnnualCheckoutPurchaseReference | None:
        async def work(connection):
            await self._authorize(connection, company_id)
            result = await self._find_active(connection, company_id, income_year)
            await self._authorize(connection, company_id)
            return result

        return await self._transaction(work)

    async def _lock_company_year(self, connection, company_id, income_year):
        await connection.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s, 192))",
            (f"annual-checkout|{company_id}|{income_year.value}",),
        )
        await self._authorize(connection, company_id)

    async def _read_purchase_basis(self, connection, company_id, income_year, basis):
        row = await (
            await connection.execute(
                "select public.company_access_purchase_basis_v1(%s::uuid, %s, %s::uuid, %s::uuid) as basis",
                (str(company_id), income_year.value, basis.assessment_id, basis.legal_acceptance_id),
            )
        ).fetchone()
        await self._authorize(connection, company_id)
        return row["basis"]

    async def _verified_purchase_basis(self, connection, company_id, income_year, prerequisites):
        # Call only after the company/year lock. The Company Access contract
        # acquires its own eligibility lock and owns the assessment/legal policy.
        basis = prerequisites.basis
        if basis.company_id != company_id or basis.income_year != income_year:
            raise BillingError.precondition(BillingErrorCode.FILING_NOT_READY)
        raw = await self._read_purchase_basis(connection, company_id, income_year, basis)
        if raw is None or (
            raw["admission_id"], raw["company_year_promise_sha256"], raw["capability_manifest_sha256"],
        ) != (basis.admission_id, basis.promise_digest, basis.manifest_digest):
            raise BillingError.precondition(BillingErrorCode.UNSUPPORTED_CASE)
        if (
            prerequisites.ready is not True
            or await self._readiness_is_current(prerequisites) is not True
            or not timedelta(0)
            <= datetime.now(UTC) - prerequisites.evaluated_at.value
            <= timedelta(minutes=5)
        ):
            raise BillingError.precondition(BillingErrorCode.FILING_NOT_READY)
        # Match the claim's INSERT RLS comparison after the verifier await.
        # Eligibility freshness or the latest legal acceptance may have changed
        # even while the eligibility lock remains held.
        current = await self._read_purchase_basis(connection, company_id, income_year, basis)
        if current != raw:
            raise BillingError.precondition(BillingErrorCode.UNSUPPORTED_CASE)
        return raw

    async def verify_checkout_preparation(
        self, company_id: CompanyId, income_year: IncomeYear, prerequisites: AnnualCheckoutPrerequisites,
    ) -> AnnualCheckoutPurchaseReference | None:
        async def work(connection):
            await self._authorize(connection, company_id)
            await self._lock_company_year(connection, company_id, income_year)
            occupied = await self._find_active(connection, company_id, income_year)
            if occupied is None:
                await self._verified_purchase_basis(connection, company_id, income_year, prerequisites)
            await self._authorize(connection, company_id)
            return occupied

        return await self._transaction(work)

    async def _load(self, connection, company_id, purchase_id, *, lock=False):
        suffix = " for update" if lock else ""
        purchase = await (
            await connection.execute(
                "select * from billing.annual_purchases where company_id=%s::uuid and id=%s::uuid" + suffix,
                (str(company_id), str(purchase_id)),
            )
        ).fetchone()
        if purchase is None:
            raise BillingError.not_found()
        operation = await (
            await connection.execute(
                "select * from billing.annual_operations where purchase_id=%s::uuid and operation='checkout'"
                + suffix,
                (str(purchase_id),),
            )
        ).fetchone()
        if operation is None:
            raise BillingError.unavailable()
        return _checkout(purchase, operation)

    async def load_checkout(self, company_id: CompanyId, purchase_id: AnnualPurchaseId) -> AnnualCheckout:
        async def work(connection):
            # Also serialize reads, so purchase totals and operation observation
            # cannot come from different committed settlements.
            return await self._load(connection, company_id, purchase_id, lock=True)

        return await self._owner_transaction(company_id, work)

    async def claim_checkout(
        self, checkout: AnnualCheckout, prerequisites: AnnualCheckoutPrerequisites
    ) -> AnnualCheckoutClaim:
        async def work(connection):
            offer, intent = checkout.offer, checkout.intent
            await self._authorize(connection, offer.company_id)
            if (
                checkout.accepted_by != self.actor_id.subject
                or checkout.status is not AnnualPurchaseStatus.PENDING
                or checkout.observation is not None
                or intent.operation is not AnnualProviderOperation.CHECKOUT
                or intent.company_id != offer.company_id
                or intent.income_year != offer.income_year
                or intent.amount_minor != offer.gross_minor
                or intent.agreement_reference is not None
            ):
                raise BillingError.invalid()
            await self._lock_original_key(connection, offer.company_id, checkout.idempotency_key)
            await self._lock_company_year(connection, offer.company_id, offer.income_year)
            existing = await self._find(connection, offer.company_id, checkout.idempotency_key)
            if existing:
                if existing.request_fingerprint != checkout.request_fingerprint:
                    raise BillingError.conflict(BillingErrorCode.IDEMPOTENCY_KEY_REUSED)
                return AnnualCheckoutClaim(existing, False)
            await self._reject_withdrawal(
                connection, offer.company_id, checkout.idempotency_key, checkout.request_fingerprint,
            )
            raw = await self._verified_purchase_basis(connection, offer.company_id, offer.income_year, prerequisites)
            occupied = await (
                await connection.execute(
                    "select id from billing.annual_purchases where company_id=%s::uuid and income_year=%s and status in ('pending','paid')",
                    (str(offer.company_id), offer.income_year.value),
                )
            ).fetchone()
            if occupied:
                raise BillingError.conflict(BillingErrorCode.IDEMPOTENCY_IN_PROGRESS)
            await connection.execute(
                """insert into billing.annual_purchases (id,company_id,income_year,accepted_by,accepted_at,
                offer_version,terms_digest,terms_text,currency,gross_minor,net_minor,vat_minor,vat_basis_points,
                paid_through,export_through,renewal_date,accepted_basis,recurring_consent,consent_version,
                provider,provider_account,agreement_external_reference,charge_reference)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s)""",
                (
                    str(checkout.purchase_id),
                    str(offer.company_id),
                    offer.income_year.value,
                    str(checkout.accepted_by),
                    intent.created_at.value,
                    offer.offer_version,
                    offer.terms_digest,
                    offer.terms_text,
                    offer.currency,
                    offer.gross_minor,
                    offer.net_minor,
                    offer.vat_minor,
                    offer.vat_basis_points,
                    offer.paid_through,
                    offer.export_through,
                    offer.renewal_date,
                    json.dumps(raw),
                    intent.recurring_consent,
                    annual_billing_consent_version(),
                    checkout.provider,
                    checkout.provider_account,
                    intent.agreement_external_reference,
                    intent.charge_reference,
                ),
            )
            saved = {
                "provider_intent": _record(intent),
                "readiness": {
                    "reference": prerequisites.readiness_reference,
                    "digest": prerequisites.readiness_digest,
                    "evaluated_at": prerequisites.evaluated_at.value.isoformat(),
                    "ready": prerequisites.ready,
                },
                "renewal_reminder_by": offer.renewal_reminder_by.isoformat(),
                "price_change_notice_by": offer.price_change_notice_by.isoformat(),
            }
            await connection.execute(
                """insert into billing.annual_operations
                (id,purchase_id,company_id,income_year,created_by,created_at,idempotency_key,request_fingerprint,operation,amount_minor,intent)
                values (%s,%s,%s,%s,%s,%s,%s,%s,'checkout',%s,%s::jsonb)""",
                (
                    str(intent.operation_id),
                    str(checkout.purchase_id),
                    str(offer.company_id),
                    offer.income_year.value,
                    str(checkout.accepted_by),
                    intent.created_at.value,
                    str(checkout.idempotency_key),
                    checkout.request_fingerprint,
                    offer.gross_minor,
                    json.dumps(saved),
                ),
            )
            return AnnualCheckoutClaim(
                await self._load(connection, offer.company_id, checkout.purchase_id), True
            )

        return await self._transaction(work)

    async def settle_checkout(
        self, checkout: AnnualCheckout, observation: AnnualProviderObservation
    ) -> AnnualCheckout:
        async def work(connection):
            current = await self._load(connection, checkout.offer.company_id, checkout.purchase_id, lock=True)
            await self._authorize(connection, checkout.offer.company_id)
            if (
                current.intent != checkout.intent
                or current.request_fingerprint != checkout.request_fingerprint
                or current.provider != checkout.provider
                or current.provider_account != checkout.provider_account
            ):
                raise BillingError.conflict(BillingErrorCode.IDEMPOTENCY_KEY_REUSED)
            result = settle_annual_checkout(current, observation, Timestamp(datetime.now(UTC)))
            if result == current:
                return current
            purchase_update = await connection.execute(
                """update billing.annual_purchases set status=%s,agreement_reference=%s,captured_minor=%s,
                refunded_minor=%s,captured_at=%s,updated_at=statement_timestamp() where id=%s::uuid""",
                (
                    result.status.value,
                    observation.agreement_reference,
                    observation.captured_minor,
                    observation.refunded_minor,
                    observation.captured_at.value if observation.captured_at else None,
                    str(current.purchase_id),
                ),
            )
            if purchase_update.rowcount != 1:
                raise BillingError.unavailable()
            operation_update = await connection.execute(
                """update billing.annual_operations set status=%s,observation=%s::jsonb,
                updated_at=statement_timestamp() where id=%s::uuid""",
                (
                    observation.status.value,
                    json.dumps(_record(observation)),
                    str(current.intent.operation_id),
                ),
            )
            if operation_update.rowcount != 1:
                raise BillingError.unavailable()
            return result

        return await self._owner_transaction(checkout.offer.company_id, work)


def _cancellation(row):
    return AnnualRenewalCancellation(
        cancellation_id=AnnualCancellationId(str(row["id"])),
        purchase_id=AnnualPurchaseId(str(row["purchase_id"])),
        company_id=CompanyId(str(row["company_id"])),
        income_year=IncomeYear(row["income_year"]),
        requested_by=UserId(str(row["requested_by"])),
        requested_at=Timestamp(row["requested_at"]),
        effective_at=Timestamp(row["effective_at"]),
        paid_through=row["paid_through"],
        export_through=row["export_through"],
    )


@billing_persistence_adapter(AnnualCancellationPersistence)
class PostgresAnnualCancellationSession:
    """Local cancellation receipts share the checkout session's verified DB context.

    Provider cleanup is a separate, still pending workflow. In particular this
    command never abandons an unresolved initial checkout or declares a refund.
    """

    def __init__(self, checkout_session: PostgresAnnualCheckoutSession) -> None:
        self._database = checkout_session

    @property
    def actor_id(self):
        return self._database.actor_id

    async def cancel_renewal(self, command: CancelAnnualRenewalCommand) -> AnnualRenewalCancellation:
        if command.actor_id != self.actor_id:
            raise BillingError.forbidden()
        fingerprint = sha256(
            json.dumps(
                {
                    "scope": "stop_renewal",
                    "company": str(command.company_id),
                    "purchase": str(command.purchase_id),
                    "actor": str(command.actor_id.subject),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

        async def work(connection):
            await self._database._authorize(connection, command.company_id)
            # Serializes the command key before checking its immutable receipt.
            # Cross-company uniqueness failures roll back the entire mutation.
            await connection.execute(
                "select pg_advisory_xact_lock(hashtextextended(%s, 192))",
                (f"annual-cancellation-key|{command.idempotency_key}",),
            )
            existing = await (
                await connection.execute(
                    """
                select r.*,p.paid_through,p.export_through from billing.annual_cancellation_requests r
                join billing.annual_purchases p on p.id=r.purchase_id
                where r.company_id=%s::uuid and r.idempotency_key=%s
            """,
                    (str(command.company_id), str(command.idempotency_key)),
                )
            ).fetchone()
            if existing:
                if existing["request_fingerprint"] != fingerprint:
                    raise BillingError.conflict(BillingErrorCode.IDEMPOTENCY_KEY_REUSED)
                return _cancellation(existing)
            purchase = await (
                await connection.execute(
                    """
                select id,income_year,paid_through,export_through from billing.annual_purchases
                where id=%s::uuid and company_id=%s::uuid for update
            """,
                    (str(command.purchase_id), str(command.company_id)),
                )
            ).fetchone()
            if purchase is None:
                raise BillingError.not_found()
            row = await (
                await connection.execute(
                    """
                insert into billing.annual_cancellation_requests
                  (id,purchase_id,company_id,income_year,requested_by,idempotency_key,request_fingerprint)
                values (gen_random_uuid(),%s::uuid,%s::uuid,%s,%s::uuid,%s,%s) returning *
            """,
                    (
                        str(command.purchase_id),
                        str(command.company_id),
                        purchase["income_year"],
                        str(self.actor_id.subject),
                        str(command.idempotency_key),
                        fingerprint,
                    ),
                )
            ).fetchone()
            return _cancellation(
                row | {"paid_through": purchase["paid_through"], "export_through": purchase["export_through"]}
            )

        return await self._database._transaction(work)
