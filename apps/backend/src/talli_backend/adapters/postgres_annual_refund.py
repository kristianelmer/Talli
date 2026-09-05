"""Durable refund claims under current owner or explicitly opened support authority.

The source resolver is unavailable by default. No HTTP or worker binds this
adapter; test resolvers are synthetic and cannot establish production authority.
"""

from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
import json
from uuid import UUID, uuid4

from talli_backend.adapters.postgres_annual_checkout import (
    PostgresAnnualCheckoutSession, _provider_intent, _record, _timestamp,
)
from talli_backend.modules.billing.public import (
    AnnualProviderObservation, AnnualProviderOperation, AnnualProviderStatus,
    AnnualPurchaseId, AnnualRefundCaseId, AnnualRefundClaim, AnnualRefundFacts,
    AnnualRefundOperation, AnnualRefundPersistence, AnnualRefundReason,
    AnnualRefundResolution, BillingError, BillingErrorCode, BillingPaymentEventId,
    RequestAnnualRefundCommand, annual_refund_decision, billing_persistence_adapter,
    settle_annual_refund,
)
from talli_backend.shared.kernel import (
    ActorId, ActorKind, CompanyId, CorrelationId, IdempotencyKey, IncomeYear, Timestamp, UserId,
)


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _fingerprint(command):
    return _digest({
        'scope': 'annual_refund', 'company': str(command.company_id),
        'purchase': str(command.purchase_id), 'actor': str(command.actor_id.subject),
        'source': command.source_reference,
    })


def _source_digest(command, facts):
    return _digest({'company': str(command.company_id), 'purchase': str(command.purchase_id), 'facts': _record(facts)})


def _facts(saved):
    return AnnualRefundFacts(**(saved | {
        'reason': AnnualRefundReason(saved['reason']), 'income_year': IncomeYear(saved['income_year']),
        **{name: _timestamp(saved[name]) for name in (
            'purchased_at', 'first_purchased_at', 'accepted_at', 'discovered_at',
            'condition_effective_at', 'blocked_at', 'production_submission_at',
        )},
    }))


def _operation(row):
    if row is None:
        return None
    saved = row['intent']
    raw = row['observation']
    result = None if raw is None else AnnualProviderObservation(**(raw | {
        'operation': AnnualProviderOperation(raw['operation']),
        'status': AnnualProviderStatus(raw['status']), 'captured_at': _timestamp(raw['captured_at']),
    }))
    return AnnualRefundOperation(
        purchase_id=AnnualPurchaseId(str(row['purchase_id'])),
        captured_minor=saved['captured_minor'], provider=saved['provider'],
        provider_account=saved['provider_account'], intent=_provider_intent(saved['provider_intent']),
        previous_refunded_minor=saved['previous_refunded_minor'], captured_at=_timestamp(saved['captured_at']),
        observation=result,
    )


async def _unavailable_source(connection, command) -> AnnualRefundFacts | None:
    return None


@billing_persistence_adapter(AnnualRefundPersistence)
class PostgresAnnualRefundSession:
    def __init__(
        self, checkout_session: PostgresAnnualCheckoutSession, *,
        source_facts: Callable[..., Awaitable[AnnualRefundFacts | None]] = _unavailable_source,
        support_case_id: str | None = None,
    ):
        self._database = checkout_session
        self._source_facts = source_facts
        self._support_case_id = str(UUID(support_case_id)) if support_case_id else None

    @property
    def actor_id(self):
        return self._database.actor_id

    async def _authorize(self, connection, company_id):
        await connection.execute("select set_config('talli.support_case_id', %s, true)", (self._support_case_id or '',))
        row = await (await connection.execute(
            """select public.company_access_has_fresh_mfa_v1() as fresh,
            public.company_access_is_accepted_owner_v1(%s::uuid) as owner,
            (public.company_access_is_active_admin_v1() and
             public.company_access_has_open_support_case_v1(public.company_access_current_support_case_id_v1(), %s::uuid, 'billing')) as support""",
            (str(company_id), str(company_id)),
        )).fetchone()
        if not row['owner'] and not row['support']:
            raise BillingError.forbidden()
        if not row['fresh']:
            raise BillingError.step_up_required()
        return row

    async def _case(self, connection, command):
        return await (await connection.execute(
            "select * from billing.annual_refund_cases where purchase_id=%s::uuid and company_id=%s::uuid and source_reference=%s",
            (str(command.purchase_id), str(command.company_id), command.source_reference),
        )).fetchone()

    def _case_facts(self, case, command):
        try:
            facts = _facts(case['facts']['facts'])
            digest = case['facts']['source_digest']
            decision = annual_refund_decision(facts)
            if (digest != _source_digest(command, facts)
                    or case['reason'] != facts.reason.value
                    or facts.evidence_reference != command.source_reference
                    or case['income_year'] != facts.income_year.value
                    or case['total_entitlement_minor'] != decision.total_entitlement_minor
                    or case['initiate_by'] != decision.initiate_by):
                raise BillingError.unavailable()
            return facts, digest, decision
        except (KeyError, TypeError, ValueError):
            # Legacy/unverified fixture cases cannot become automatic authority.
            raise BillingError.unavailable() from None

    async def _resolution(self, connection, request, case):
        command = RequestAnnualRefundCommand(
            company_id=CompanyId(str(request['company_id'])),
            actor_id=ActorId(ActorKind.USER, UserId(str(request['requested_by']))),
            correlation_id=CorrelationId(request['correlation_id']),
            idempotency_key=IdempotencyKey(request['idempotency_key']),
            purchase_id=AnnualPurchaseId(str(request['purchase_id'])), source_reference=case['source_reference'],
        )
        facts, digest, decision = self._case_facts(case, command)
        operation = None
        if request['operation_id'] is not None:
            operation = await (await connection.execute(
                'select * from billing.annual_operations where id=%s::uuid for update',
                (str(request['operation_id']),),
            )).fetchone()
            if operation is None:
                raise BillingError.unavailable()
        return AnnualRefundResolution(AnnualRefundCaseId(str(case['id'])), command,
                                      digest, facts, decision, _operation(operation))

    async def claim_refund(self, command):
        if command.actor_id != self.actor_id:
            raise BillingError.forbidden()

        async def work(connection):
            authority = await self._authorize(connection, command.company_id)
            await connection.execute('select pg_advisory_xact_lock(hashtextextended(%s, 192))',
                                     (f'annual-refund-key|{command.idempotency_key}',))
            checkout = await self._database._load(connection, command.company_id, command.purchase_id, lock=True)
            request = await (await connection.execute(
                'select * from billing.annual_refund_requests where company_id=%s::uuid and idempotency_key=%s for update',
                (str(command.company_id), str(command.idempotency_key)),
            )).fetchone()
            if request and request['request_fingerprint'] != _fingerprint(command):
                raise BillingError.conflict(BillingErrorCode.IDEMPOTENCY_KEY_REUSED)
            case = await self._case(connection, command)
            if request and request['operation_id'] is not None:
                # No live source dependency may obstruct recovery of a recorded effect.
                if case is None or request['refund_case_id'] != case['id']:
                    raise BillingError.unavailable()
                return AnnualRefundClaim(await self._resolution(connection, request, case), False)
            if case is None:
                facts = await self._source_facts(connection, command)
                observed = checkout.observation
                if facts is None or observed is None or observed.captured_at is None:
                    raise BillingError.unavailable()
                first = await (await connection.execute(
                    'select min(captured_at) as first from billing.annual_purchases where company_id=%s::uuid and captured_at is not null',
                    (str(command.company_id),),
                )).fetchone()
                if (
                    not isinstance(facts, AnnualRefundFacts) or not isinstance(facts.reason, AnnualRefundReason)
                    or facts.evidence_reference != command.source_reference
                    or facts.income_year != checkout.offer.income_year
                    or facts.purchased_at != observed.captured_at
                    or facts.first_purchased_at.value != first['first']
                    or facts.accepted_at != checkout.intent.created_at
                    or facts.gross_minor != checkout.offer.gross_minor
                    or facts.refunded_minor != observed.refunded_minor
                    or facts.discovered_at.value > datetime.now(UTC)
                    or (facts.production_submission_at is not None and facts.production_submission_at.value > datetime.now(UTC))
                ):
                    raise BillingError.invalid()
                if facts.reason is not AnnualRefundReason.CHANGE_OF_MIND and not authority['support']:
                    raise BillingError.forbidden()
                decision = annual_refund_decision(facts)
                case = await (await connection.execute(
                    """insert into billing.annual_refund_cases
                    (id,purchase_id,company_id,income_year,reason,source_reference,facts,total_entitlement_minor,initiate_by,created_by)
                    values (%s::uuid,%s::uuid,%s::uuid,%s,%s,%s,%s::jsonb,%s,%s,%s::uuid) returning *""",
                    (str(uuid4()), str(command.purchase_id), str(command.company_id), facts.income_year.value,
                     facts.reason.value, command.source_reference,
                     json.dumps({'facts': _record(facts), 'source_digest': _source_digest(command, facts)}),
                     decision.total_entitlement_minor, decision.initiate_by, str(self.actor_id.subject)),
                )).fetchone()
            facts, digest, decision = self._case_facts(case, command)
            if request is None:
                request = await (await connection.execute(
                    """insert into billing.annual_refund_requests
                    (id,purchase_id,company_id,income_year,refund_case_id,requested_by,correlation_id,idempotency_key,request_fingerprint)
                    values (%s::uuid,%s::uuid,%s::uuid,%s,%s::uuid,%s::uuid,%s,%s,%s) returning *""",
                    (str(uuid4()), str(command.purchase_id), str(command.company_id), facts.income_year.value,
                     str(case['id']), str(self.actor_id.subject), str(command.correlation_id), str(command.idempotency_key), _fingerprint(command)),
                )).fetchone()
            existing = await (await connection.execute(
                """select * from billing.annual_operations where purchase_id=%s::uuid
                and operation='refund' and status in ('created','pending','unknown') for update""",
                (str(command.purchase_id),),
            )).fetchone()
            newly_claimed = False
            operation_id = None
            if existing:
                # Different cases retain their liability while the original effect resolves.
                if existing['refund_case_id'] == case['id']:
                    operation_id = existing['id']
            else:
                observed = checkout.observation
                if observed and observed.captured_at and observed.agreement_reference:
                    amount = min(decision.total_entitlement_minor, observed.captured_minor) - observed.refunded_minor
                    if amount > 0:
                        intent = replace(checkout.intent, operation_id=BillingPaymentEventId(str(uuid4())),
                            operation=AnnualProviderOperation.REFUND, amount_minor=amount,
                            created_at=Timestamp(datetime.now(UTC)), agreement_reference=observed.agreement_reference)
                        saved = {'provider_intent': _record(intent), 'provider': checkout.provider,
                                 'provider_account': checkout.provider_account, 'captured_minor': observed.captured_minor,
                                 'previous_refunded_minor': observed.refunded_minor, 'captured_at': observed.captured_at.value.isoformat()}
                        operation_id = str(intent.operation_id)
                        await connection.execute(
                            """insert into billing.annual_operations
                            (id,purchase_id,company_id,income_year,created_by,created_at,idempotency_key,request_fingerprint,operation,amount_minor,intent,refund_case_id)
                            values (%s::uuid,%s::uuid,%s::uuid,%s,%s::uuid,%s,%s,%s,'refund',%s,%s::jsonb,%s::uuid)""",
                            (operation_id, str(command.purchase_id), str(command.company_id), facts.income_year.value,
                             str(self.actor_id.subject), intent.created_at.value, f'annual-refund-{operation_id}',
                             _digest(saved), amount, json.dumps(saved), str(case['id'])),
                        )
                        newly_claimed = True
            if operation_id is not None:
                request = await (await connection.execute(
                    'update billing.annual_refund_requests set operation_id=%s::uuid where id=%s::uuid returning *',
                    (str(operation_id), str(request['id'])),
                )).fetchone()
            return AnnualRefundClaim(await self._resolution(connection, request, case), newly_claimed)

        return await self._database._transaction(work)

    async def settle_refund(self, resolution, observation):
        if resolution.request.actor_id != self.actor_id:
            raise BillingError.forbidden()

        async def work(connection):
            command = resolution.request
            await self._authorize(connection, command.company_id)
            checkout = await self._database._load(connection, command.company_id, command.purchase_id, lock=True)
            request = await (await connection.execute(
                'select * from billing.annual_refund_requests where company_id=%s::uuid and idempotency_key=%s for update',
                (str(command.company_id), str(command.idempotency_key)),
            )).fetchone()
            case = await self._case(connection, command)
            if request is None or case is None:
                raise BillingError.not_found()
            current = await self._resolution(connection, request, case)
            if current.operation is None or resolution.operation is None or replace(
                current, operation=replace(current.operation, observation=resolution.operation.observation)
            ) != resolution:
                raise BillingError.conflict(BillingErrorCode.IDEMPOTENCY_KEY_REUSED)
            result = settle_annual_refund(current, observation, Timestamp(datetime.now(UTC)))
            if result == current:
                return current
            result_observation = result.operation.observation
            purchase_observation = checkout.observation
            if purchase_observation is None or purchase_observation.captured_at != result_observation.captured_at:
                raise BillingError.invalid()
            captured = max(purchase_observation.captured_minor, result_observation.captured_minor)
            refunded = max(purchase_observation.refunded_minor, result_observation.refunded_minor)
            status = checkout.status.value
            if (result_observation.status is AnnualProviderStatus.CONFIRMED
                    and captured == checkout.offer.gross_minor and refunded == captured):
                status = 'refunded'
            await connection.execute(
                """update billing.annual_purchases set status=%s,captured_minor=%s,refunded_minor=%s,
                updated_at=statement_timestamp() where id=%s::uuid""",
                (status, captured, refunded, str(command.purchase_id)),
            )
            await connection.execute(
                """update billing.annual_operations set status=%s,observation=%s::jsonb,
                updated_at=statement_timestamp() where id=%s::uuid""",
                (result_observation.status.value, json.dumps(_record(result_observation)), str(result.operation.intent.operation_id)),
            )
            return result

        return await self._database._transaction(work)
