"""Private Supabase persistence for the billing capability."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from hashlib import sha256

import psycopg
from psycopg.rows import dict_row

from talli_backend.adapters.simulation_billing import SimulationBillingProvider
from talli_backend.adapters.supabase_ledger import (
    LedgerSupabaseConfiguration,
    SupabaseLedgerAdapter,
    _VerifiedActor,
    _timestamp,
)
from talli_backend.application.billing_session import BillingAuthenticationError
from talli_backend.application.billing_workflow import BillingWorkflow
from talli_backend.application.ledger_workflow import LedgerAuthenticationError
from talli_backend.modules.billing.public import (
    ActivateSubscriptionCommand,
    BillingAccount,
    BillingError,
    BillingErrorCode,
    BillingObligation,
    BillingPaymentEvent,
    BillingPaymentEventId,
    BillingPaymentKind,
    BillingPaymentStatus,
    BillingPersistence,
    BillingPlan,
    BillingPricing,
    BillingProviderResult,
    BillingSnapshot,
    BillingSnapshotQuery,
    CancelSubscriptionCommand,
    ConfigureBillingAccountCommand,
    ManageProductionPilotEntitlementCommand,
    MarkBillingUnsupportedCommand,
    ProductionPilotEntitlement,
    ProductionPilotEntitlementId,
    ProductionPilotStatus,
    PurchaseFilingPackageCommand,
    RefundFilingPackageCommand,
    SystemUserRequestReference,
    billing_persistence_adapter,
)
from talli_backend.shared.kernel import CompanyId, IdempotencyKey, IncomeYear, UserId


def _account(row: Mapping[str, object]) -> BillingAccount:
    return BillingAccount(
        company_id=CompanyId(str(row["company_id"])),
        pricing=BillingPricing(
            BillingPlan(str(row["pricing_plan"])),
            int(row["monthly_nok"]),
            int(row["filing_package_nok"]),
        ),
        founder_cohort_number=(
            int(row["founder_cohort_number"])
            if row["founder_cohort_number"] is not None
            else None
        ),
        subscription_active=bool(row["subscription_active"]),
        filing_package_paid=bool(row["filing_package_paid"]),
        supported_case=bool(row["supported_case"]),
        refund_eligible=bool(row["refund_eligible"]),
        refund_completed=bool(row["refund_completed"]),
        no_charge_reason=(
            str(row["no_charge_reason"])
            if row["no_charge_reason"] is not None
            else None
        ),
        provider_customer_reference=(
            str(row["provider_customer_ref"])
            if row["provider_customer_ref"] is not None
            else None
        ),
        subscription_provider_reference=(
            str(row["subscription_provider_ref"])
            if row["subscription_provider_ref"] is not None
            else None
        ),
        filing_package_payment_reference=(
            str(row["filing_package_payment_ref"])
            if row["filing_package_payment_ref"] is not None
            else None
        ),
        refund_provider_reference=(
            str(row["refund_provider_ref"])
            if row["refund_provider_ref"] is not None
            else None
        ),
        updated_by=UserId(str(row["updated_by"])),
        created_at=_timestamp(row["created_at"]),
        updated_at=_timestamp(row["updated_at"]),
    )


def _event(row: Mapping[str, object], *, replayed: bool = False) -> BillingPaymentEvent:
    return BillingPaymentEvent(
        event_id=BillingPaymentEventId(str(row["id"])),
        company_id=CompanyId(str(row["company_id"])),
        provider=str(row["provider"]),
        provider_reference=str(row["provider_reference"]),
        idempotency_key=IdempotencyKey(str(row["idempotency_key"])),
        kind=BillingPaymentKind(str(row["kind"])),
        status=BillingPaymentStatus(str(row["status"])),
        amount_nok=int(row["amount_nok"]),
        income_year=(
            IncomeYear(int(row["income_year"]))
            if row["income_year"] is not None
            else None
        ),
        created_by=UserId(str(row["created_by"])),
        created_at=_timestamp(row["created_at"]),
        replayed=replayed,
    )


def _pilot(row: Mapping[str, object]) -> ProductionPilotEntitlement:
    request_id = row.get("system_user_request_id")
    if request_id is None:
        raise BillingError.unavailable()
    return ProductionPilotEntitlement(
        entitlement_id=ProductionPilotEntitlementId(str(row["id"])),
        company_id=CompanyId(str(row["company_id"])),
        user_id=UserId(str(row["user_id"])),
        income_year=IncomeYear(int(row["income_year"])),
        obligation=BillingObligation(str(row["obligation"])),
        case_profile=str(row["case_profile"]),
        status=ProductionPilotStatus(str(row["status"])),
        billing_exempt=bool(row["billing_exempt"]),
        system_user_request_id=SystemUserRequestReference(str(request_id)),
        system_user_external_reference=str(row["system_user_external_reference"]),
        starts_at=_timestamp(row["starts_at"]),
        expires_at=_timestamp(row["expires_at"]),
        evidence_reference=str(row["evidence_reference"]),
        approved_by=UserId(str(row["approved_by"])),
        created_at=_timestamp(row["created_at"]),
        updated_at=_timestamp(row["updated_at"]),
    )


_ACCOUNT_COLUMNS = """company_id, pricing_plan, monthly_nok, filing_package_nok,
founder_cohort_number, subscription_active, filing_package_paid, supported_case,
refund_eligible, refund_completed, no_charge_reason, provider_customer_ref,
subscription_provider_ref, filing_package_payment_ref, refund_provider_ref,
updated_by, created_at, updated_at"""
_EVENT_COLUMNS = """id, company_id, provider, provider_reference, idempotency_key,
kind, status, amount_nok, income_year, created_by, created_at"""
_PILOT_COLUMNS = """id, company_id, user_id, income_year, obligation, case_profile,
status, billing_exempt, system_user_request_id, system_user_external_reference,
starts_at, expires_at, evidence_reference, approved_by, created_at, updated_at"""


def _kind(command) -> BillingPaymentKind:
    return {
        ActivateSubscriptionCommand: BillingPaymentKind.SUBSCRIPTION,
        CancelSubscriptionCommand: BillingPaymentKind.SUBSCRIPTION_CANCELLATION,
        PurchaseFilingPackageCommand: BillingPaymentKind.FILING_PACKAGE,
        RefundFilingPackageCommand: BillingPaymentKind.REFUND,
    }[type(command)]


def _command_fingerprint(operation: str, payload: Mapping[str, object]) -> str:
    canonical = json.dumps(
        {"operation": operation, **payload},
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode()).hexdigest()


def _receipt_result(
    rows: list[Mapping[str, object]], *, operation: str, fingerprint: str
) -> Mapping[str, object]:
    if len(rows) != 1:
        raise BillingError.unavailable()
    row = rows[0]
    if row["operation"] != operation or row["request_fingerprint"] != fingerprint:
        raise BillingError.conflict(BillingErrorCode.IDEMPOTENCY_KEY_REUSED)
    result = row["result"]
    if not isinstance(result, Mapping):
        raise BillingError.unavailable()
    return result


def _map_error(message: str) -> BillingError:
    if "row-level security" in message or "permission denied" in message:
        return BillingError.forbidden()
    if "billing_idempotency_key_reused" in message:
        return BillingError.conflict(BillingErrorCode.IDEMPOTENCY_KEY_REUSED)
    if "billing_system_user_required" in message:
        return BillingError.precondition(BillingErrorCode.INVALID_INPUT)
    return BillingError.unavailable()


class SupabaseBillingAdapter:
    def __init__(self, configuration: LedgerSupabaseConfiguration) -> None:
        self._configuration = configuration
        self._ledger_authentication = SupabaseLedgerAdapter(configuration)

    @classmethod
    def from_environment(cls) -> SupabaseBillingAdapter:
        return cls(
            LedgerSupabaseConfiguration(
                url=os.environ.get("SUPABASE_URL", ""),
                anon_key=os.environ.get("SUPABASE_ANON_KEY", ""),
                database_url=os.environ.get("TALLI_LEDGER_DATABASE_URL", ""),
            )
        )

    async def session(self, access_token: str) -> SupabaseBillingSession:
        try:
            ledger = await self._ledger_authentication.session(access_token)
        except LedgerAuthenticationError:
            raise BillingAuthenticationError from None
        return SupabaseBillingSession(
            self._configuration.database_url, ledger._verified
        )


@billing_persistence_adapter(BillingPersistence)
class SupabaseBillingSession:
    def __init__(self, database_url: str, verified: _VerifiedActor) -> None:
        self._database_url = database_url
        self._verified = verified

    @property
    def actor_id(self):
        return self._verified.actor_id

    def _assert_actor(self, actor_id) -> None:
        if actor_id != self.actor_id:
            raise BillingError.forbidden()

    async def _rows(
        self,
        role: str,
        query: str,
        parameters: tuple[object, ...] = (),
    ) -> list[Mapping[str, object]]:
        if not self._database_url:
            raise BillingError.unavailable()
        try:
            async with await psycopg.AsyncConnection.connect(
                self._database_url, connect_timeout=5, row_factory=dict_row
            ) as connection, connection.transaction():
                await connection.execute(f"set local role {role}")
                await connection.execute(
                    "select pg_catalog.set_config('talli.verified_actor_id', %s, true)",
                    (str(self.actor_id.subject),),
                )
                await connection.execute(
                    "select pg_catalog.set_config('talli.verified_actor_claims', %s, true)",
                    (self._verified.claims_json,),
                )
                cursor = await connection.execute(query, parameters)
                return list(await cursor.fetchall())
        except BillingError:
            raise
        except psycopg.OperationalError:
            raise BillingError.unavailable() from None
        except psycopg.DatabaseError as error:
            raise _map_error(str(error)) from None

    async def _idempotent_command(
        self,
        *,
        command,
        operation: str,
        fingerprint: str,
        mutation: str,
        parameters: tuple[object, ...],
        on_empty: Callable[[], BillingError] = BillingError.unavailable,
    ) -> Mapping[str, object]:
        if not self._database_url:
            raise BillingError.unavailable()
        try:
            async with await psycopg.AsyncConnection.connect(
                self._database_url, connect_timeout=5, row_factory=dict_row
            ) as connection, connection.transaction():
                await connection.execute("set local role billing_store_owner")
                await connection.execute(
                    "select pg_catalog.set_config('talli.verified_actor_id', %s, true)",
                    (str(self.actor_id.subject),),
                )
                await connection.execute(
                    "select pg_catalog.set_config('talli.verified_actor_claims', %s, true)",
                    (self._verified.claims_json,),
                )
                claim_cursor = await connection.execute(
                        """insert into billing.billing_command_receipts (
                          idempotency_key, company_id, operation,
                          request_fingerprint, result, created_by
                        ) values (
                          %s::text, %s::uuid, %s::text, %s::text,
                          'null'::jsonb, %s::uuid
                        )
                        on conflict (idempotency_key) do nothing
                        returning idempotency_key""",
                        (
                            str(command.idempotency_key),
                            str(command.company_id),
                            operation,
                            fingerprint,
                            str(command.actor_id.subject),
                        ),
                    )
                claimed = list(await claim_cursor.fetchall())
                if not claimed:
                    replay_cursor = await connection.execute(
                        """select operation, request_fingerprint, result
                        from billing.billing_command_receipts
                        where idempotency_key = %s::text""",
                        (str(command.idempotency_key),),
                    )
                    replay = list(await replay_cursor.fetchall())
                    return _receipt_result(
                        replay, operation=operation, fingerprint=fingerprint
                    )

                mutation_cursor = await connection.execute(mutation, parameters)
                changed = list(await mutation_cursor.fetchall())
                if len(changed) != 1:
                    raise on_empty()
                result = changed[0]
                completion_cursor = await connection.execute(
                    """update billing.billing_command_receipts
                    set result = %s::jsonb
                    where idempotency_key = %s::text
                    returning idempotency_key""",
                    (
                        json.dumps(result, default=str, separators=(",", ":")),
                        str(command.idempotency_key),
                    ),
                )
                completed = list(await completion_cursor.fetchall())
                if len(completed) != 1:
                    raise BillingError.unavailable()
                return result
        except BillingError:
            raise
        except psycopg.OperationalError:
            raise BillingError.unavailable() from None
        except psycopg.DatabaseError as error:
            raise _map_error(str(error)) from None

    async def find_account(self, company_id: CompanyId) -> BillingAccount | None:
        rows = await self._rows(
            "billing_executor",
            f"select {_ACCOUNT_COLUMNS} from billing.billing_accounts where company_id = %s::uuid",
            (str(company_id),),
        )
        return _account(rows[0]) if rows else None

    async def filing_ready(self, company_id, income_year, obligation) -> bool:
        rows = await self._rows(
            "billing_executor",
            "select billing.read_legacy_filing_readiness_v1(%s::uuid, %s::integer, %s::text) as ready",
            (str(company_id), int(income_year), obligation.value),
        )
        return len(rows) == 1 and bool(rows[0]["ready"])

    async def find_active_pilot_entitlement(
        self, *, company_id, user_id, income_year, obligation, case_profile, at
    ):
        rows = await self._rows(
            "billing_executor",
            f"""select {_PILOT_COLUMNS} from billing.production_pilot_entitlements
                where company_id = %s::uuid and user_id = %s::uuid
                  and income_year = %s::integer and obligation = %s::text
                  and case_profile = %s::text and status = 'active'
                  and starts_at <= %s::timestamptz and expires_at > %s::timestamptz
                limit 1""",
            (
                str(company_id), str(user_id), int(income_year), obligation.value,
                case_profile, at, at,
            ),
        )
        return _pilot(rows[0]) if rows else None

    async def snapshot(self, query: BillingSnapshotQuery) -> BillingSnapshot:
        self._assert_actor(query.actor_id)
        company_ids = [str(value) for value in query.company_ids]
        accounts = await self._rows(
            "billing_executor",
            f"select {_ACCOUNT_COLUMNS} from billing.billing_accounts where company_id = any(%s::uuid[]) order by company_id",
            (company_ids,),
        )
        events = await self._rows(
            "billing_executor",
            f"select {_EVENT_COLUMNS} from billing.billing_payment_events where company_id = any(%s::uuid[]) order by created_at desc, id desc",
            (company_ids,),
        )
        pilots = await self._rows(
            "billing_executor",
            f"select {_PILOT_COLUMNS} from billing.production_pilot_entitlements where company_id = any(%s::uuid[]) order by updated_at desc, id desc",
            (company_ids,),
        )
        return BillingSnapshot(
            accounts=tuple(_account(row) for row in accounts),
            payment_events=tuple(_event(row) for row in events),
            pilot_entitlements=tuple(_pilot(row) for row in pilots),
        )

    async def find_payment_event(
        self, *, company_id, idempotency_key, kind, amount_nok, income_year
    ):
        rows = await self._rows(
            "billing_executor",
            f"select {_EVENT_COLUMNS} from billing.billing_payment_events where idempotency_key = %s::text",
            (str(idempotency_key),),
        )
        if not rows:
            return None
        event = _event(rows[0], replayed=True)
        if (
            event.company_id != company_id
            or event.kind is not kind
            or event.amount_nok != amount_nok
            or event.income_year != income_year
        ):
            raise BillingError.conflict(BillingErrorCode.IDEMPOTENCY_KEY_REUSED)
        return event

    async def configure_account(self, command, pricing):
        self._assert_actor(command.actor_id)
        operation = "configure_account"
        fingerprint = _command_fingerprint(operation, {
            "companyId": str(command.company_id),
            "pricingPlan": pricing.plan.value,
            "monthlyNok": pricing.monthly_nok,
            "filingPackageNok": pricing.filing_package_nok,
            "founderCohortNumber": command.founder_cohort_number,
        })
        result = await self._idempotent_command(
            command=command,
            operation=operation,
            fingerprint=fingerprint,
            mutation="""insert into billing.billing_accounts (
              company_id, pricing_plan, monthly_nok, filing_package_nok,
              founder_cohort_number, updated_by
            ) values (%s::uuid, %s::text, %s::integer, %s::integer, %s::integer, %s::uuid)
            on conflict (company_id) do update set
              pricing_plan = excluded.pricing_plan,
              monthly_nok = excluded.monthly_nok,
              filing_package_nok = excluded.filing_package_nok,
              founder_cohort_number = excluded.founder_cohort_number,
              updated_by = excluded.updated_by,
              updated_at = pg_catalog.now()
            returning billing.billing_accounts.*""",
            parameters=(
                str(command.company_id), pricing.plan.value, pricing.monthly_nok,
                pricing.filing_package_nok, command.founder_cohort_number,
                str(command.actor_id.subject),
            ),
        )
        return _account(result)

    async def complete_provider_event(self, command, result, amount_nok):
        self._assert_actor(command.actor_id)
        kind = _kind(command)
        income_year = getattr(command, "income_year", None)
        payload = json.dumps(
            {
                "companyId": str(command.company_id),
                "correlationId": str(command.correlation_id),
                "kind": kind.value,
                "amountNok": amount_nok,
                "incomeYear": int(income_year) if income_year else None,
                "provider": result.provider,
                "providerReference": result.provider_reference,
                "status": result.status.value,
            },
            separators=(",", ":"),
        )
        rows = await self._rows(
            "billing_store_owner",
            f"""with inserted as (
                  insert into billing.billing_payment_events (
                    company_id, provider, provider_reference, idempotency_key,
                    kind, status, amount_nok, income_year, payload, created_by
                  ) select
                    %s::uuid, %s::text, %s::text, %s::text, %s::text, %s::text,
                    %s::integer, %s::integer, %s::jsonb, %s::uuid
                  from billing.billing_accounts account
                  where account.company_id = %s::uuid
                  on conflict (idempotency_key) do nothing
                  returning {_EVENT_COLUMNS}
                ), selected as (
                  select *, false as replayed from inserted
                  union all
                  select {_EVENT_COLUMNS}, true as replayed
                  from billing.billing_payment_events
                  where idempotency_key = %s::text and not exists (select 1 from inserted)
                ), updated as (
                  update billing.billing_accounts account set
                    subscription_active = case
                      when %s::text = 'subscription' then true
                      when %s::text = 'subscription_cancellation' then false
                      else account.subscription_active end,
                    provider_customer_ref = case when %s::text = 'subscription'
                      then coalesce(account.provider_customer_ref, 'sim_customer_' || account.company_id::text)
                      else account.provider_customer_ref end,
                    subscription_provider_ref = case when %s::text in ('subscription', 'subscription_cancellation')
                      then %s::text else account.subscription_provider_ref end,
                    filing_package_paid = case
                      when %s::text = 'filing_package' then true
                      when %s::text = 'unsupported' then false
                      else account.filing_package_paid end,
                    filing_package_payment_ref = case when %s::text = 'filing_package'
                      then %s::text else account.filing_package_payment_ref end,
                    refund_eligible = case when %s::text in ('filing_package', 'refund')
                      then false else account.refund_eligible end,
                    refund_completed = case when %s::text = 'refund'
                      then true else account.refund_completed end,
                    refund_provider_ref = case when %s::text = 'refund'
                      then %s::text else account.refund_provider_ref end,
                    updated_by = %s::uuid,
                    updated_at = pg_catalog.now()
                  where account.company_id = %s::uuid
                    and exists (select 1 from inserted)
                    and exists (
                      select 1 from inserted event
                      where event.status = case event.kind
                        when 'subscription_cancellation' then 'canceled'
                        when 'refund' then 'refunded'
                        else 'succeeded'
                      end
                    )
                  returning account.company_id
                )
                select * from selected""",
            (
                str(command.company_id), result.provider, result.provider_reference,
                str(command.idempotency_key), kind.value, result.status.value,
                amount_nok, int(income_year) if income_year else None, payload,
                str(command.actor_id.subject), str(command.company_id),
                str(command.idempotency_key),
                kind.value, kind.value, kind.value, kind.value,
                result.provider_reference, kind.value, kind.value,
                result.provider_reference, kind.value, kind.value, kind.value,
                result.provider_reference, str(command.actor_id.subject),
                str(command.company_id),
            ),
        )
        if len(rows) != 1:
            raise BillingError.unavailable()
        event = _event(rows[0], replayed=bool(rows[0]["replayed"]))
        if (
            event.company_id != command.company_id
            or event.kind is not kind
            or event.amount_nok != amount_nok
            or event.income_year != income_year
        ):
            raise BillingError.conflict(BillingErrorCode.IDEMPOTENCY_KEY_REUSED)
        return event

    async def mark_unsupported(self, command: MarkBillingUnsupportedCommand):
        self._assert_actor(command.actor_id)
        operation = "mark_unsupported"
        fingerprint = _command_fingerprint(operation, {
            "companyId": str(command.company_id),
            "reason": command.reason,
        })
        result = await self._idempotent_command(
            command=command,
            operation=operation,
            fingerprint=fingerprint,
            mutation="""update billing.billing_accounts set
              supported_case = false, filing_package_paid = false,
              filing_package_payment_ref = null, no_charge_reason = %s::text,
              updated_by = %s::uuid, updated_at = pg_catalog.now()
              where company_id = %s::uuid
              returning billing.billing_accounts.*""",
            parameters=(
                command.reason, str(command.actor_id.subject), str(command.company_id),
            ),
            on_empty=BillingError.not_found,
        )
        return _account(result)

    async def manage_pilot_entitlement(self, command):
        self._assert_actor(command.actor_id)
        operation = "manage_pilot_entitlement"
        fingerprint = _command_fingerprint(operation, {
            "companyId": str(command.company_id),
            "entitlementId": (
                str(command.entitlement_id) if command.entitlement_id is not None else None
            ),
            "userId": str(command.user_id),
            "incomeYear": int(command.income_year),
            "obligation": command.obligation.value,
            "caseProfile": command.case_profile,
            "status": command.status.value,
            "billingExempt": command.billing_exempt,
            "systemUserRequestId": str(command.system_user_request_id),
            "startsAt": command.starts_at.value.isoformat(),
            "expiresAt": command.expires_at.value.isoformat(),
            "evidenceReference": command.evidence_reference,
        })
        if command.entitlement_id is None:
            statement = """with verified_request as (
              select request.id, request.external_ref
              from public.system_user_requests request
              where request.id = %s::uuid and request.company_id = %s::uuid
                and request.initiating_owner_user_id = %s::uuid
                and request.obligation = 'aksjonaerregisteroppgaven'
                and request.status = 'accepted'
                and request.preflight_verified_at is not null
                and exists (
                  select 1 from public.company_memberships membership
                  where membership.company_id = request.company_id
                    and membership.user_id = request.initiating_owner_user_id
                    and membership.role = 'owner'
                    and membership.accepted_at is not null
                )
            ), changed as (
              insert into billing.production_pilot_entitlements (
              company_id, user_id, income_year, obligation, case_profile, status,
              billing_exempt, system_user_request_id, system_user_external_reference,
              starts_at, expires_at, evidence_reference, approved_by
            ) select
              %s::uuid, %s::uuid, %s::integer, %s::text, %s::text, %s::text,
              %s::boolean, verified_request.id, verified_request.external_ref,
              %s::timestamptz, %s::timestamptz, %s::text, %s::uuid
              from verified_request
              returning billing.production_pilot_entitlements.*
            )
            select * from changed"""
            parameters = (
                str(command.system_user_request_id), str(command.company_id),
                str(command.user_id), str(command.company_id), str(command.user_id),
                int(command.income_year),
                command.obligation.value, command.case_profile, command.status.value,
                command.billing_exempt, command.starts_at.value,
                command.expires_at.value, command.evidence_reference,
                str(command.actor_id.subject),
            )
        else:
            statement = """with verified_request as (
              select request.id, request.external_ref
              from public.system_user_requests request
              where request.id = %s::uuid and request.company_id = %s::uuid
                and request.initiating_owner_user_id = %s::uuid
                and request.obligation = 'aksjonaerregisteroppgaven'
                and request.status = 'accepted'
                and request.preflight_verified_at is not null
                and exists (
                  select 1 from public.company_memberships membership
                  where membership.company_id = request.company_id
                    and membership.user_id = request.initiating_owner_user_id
                    and membership.role = 'owner'
                    and membership.accepted_at is not null
                )
            ), changed as (
              update billing.production_pilot_entitlements entitlement set
              status = %s::text, billing_exempt = %s::boolean,
              system_user_request_id = verified_request.id,
              system_user_external_reference = verified_request.external_ref,
              starts_at = %s::timestamptz, expires_at = %s::timestamptz,
              evidence_reference = %s::text, approved_by = %s::uuid,
              updated_at = pg_catalog.now()
            from verified_request
            where entitlement.id = %s::uuid
              and entitlement.company_id = %s::uuid
              and entitlement.user_id = %s::uuid
              and entitlement.income_year = %s::integer
              and entitlement.obligation = %s::text
              and entitlement.case_profile = %s::text
              returning entitlement.*
            )
            select * from changed"""
            parameters = (
                str(command.system_user_request_id), str(command.company_id),
                str(command.user_id), command.status.value, command.billing_exempt,
                command.starts_at.value, command.expires_at.value, command.evidence_reference,
                str(command.actor_id.subject), str(command.entitlement_id),
                str(command.company_id), str(command.user_id), int(command.income_year),
                command.obligation.value, command.case_profile,
            )
        result = await self._idempotent_command(
            command=command,
            operation=operation,
            fingerprint=fingerprint,
            mutation=statement,
            parameters=parameters,
            on_empty=lambda: BillingError.precondition(BillingErrorCode.INVALID_INPUT),
        )
        return _pilot(result)


async def compose_billing_workflow(access_token: str) -> BillingWorkflow:
    session = await SupabaseBillingAdapter.from_environment().session(access_token)
    return BillingWorkflow(session, SimulationBillingProvider())


__all__ = [
    "SupabaseBillingAdapter",
    "SupabaseBillingSession",
    "compose_billing_workflow",
]
