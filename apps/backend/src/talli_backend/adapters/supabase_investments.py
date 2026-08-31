"""Private Supabase persistence for the investments capability."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

import psycopg
from psycopg.rows import dict_row

from talli_backend.adapters.supabase_ledger import (
    LedgerSupabaseConfiguration,
    SupabaseLedgerAdapter,
    SupabaseLedgerSession,
    SupabaseLedgerWorkflowTransaction,
    _VerifiedActor,
    _actor,
    _map_database_error,
    _money,
    _timestamp,
)
from talli_backend.application.investments_session import (
    InvestmentsAuthenticationError,
    InvestmentsSessionFactory,
)
from talli_backend.application.investments_workflow import InvestmentsApplication
from talli_backend.application.ledger_workflow import LedgerAuthenticationError
from talli_backend.modules.investments.public import (
    AccountingEntryReference,
    AcquisitionLotPage,
    AcquisitionLotId,
    AcquisitionLotView,
    InvestmentActionId,
    InvestmentActivityKind,
    InvestmentActivityPage,
    InvestmentActivityView,
    InvestmentCursor,
    InvestmentDocumentStatus,
    InvestmentKind,
    InvestmentLotHistoryStatus,
    InvestmentPositionPage,
    InvestmentPositionId,
    InvestmentPositionView,
    InvestmentSourceReference,
    InvestmentTaxTreatment,
    InvestmentsError,
    InvestmentsErrorCode,
    InvestmentsPersistence,
    PreparedReceivedDividend,
    PreparedSharePurchase,
    PreparedShareSale,
    RecordReceivedDividendCommand,
    RecordSharePurchaseCommand,
    RecordShareSaleCommand,
    RecordedReceivedDividend,
    RecordedSharePurchase,
    RecordedShareSale,
    ShareSaleAllocationId,
    ShareSaleAllocationPage,
    ShareSaleAllocationView,
    investments_persistence_adapter,
)
from talli_backend.modules.ledger.public import LedgerError
from talli_backend.modules.ledger.service import LedgerService
from talli_backend.shared.kernel import (
    ActorId,
    CompanyId,
    CorrelationId,
    IncomeYear,
    LocalDate,
    Money,
)


def _request_payload(
    command: RecordSharePurchaseCommand | RecordShareSaleCommand | RecordReceivedDividendCommand,
) -> dict[str, object]:
    common: dict[str, object] = {
        "companyId": str(command.company_id),
        "incomeYear": int(command.income_year),
        "actionId": str(command.action_id),
        "idempotencyKey": str(command.idempotency_key),
        "correlationId": str(command.correlation_id),
        "bankTransactionId": (
            str(command.bank_transaction_id) if command.bank_transaction_id else None
        ),
        "documentId": str(command.document_id) if command.document_id else None,
        "documentStatus": command.document_status.value,
    }
    if isinstance(command, RecordReceivedDividendCommand):
        return {
            **common,
            "positionId": str(command.position_id),
            "payingCompanyName": command.paying_company_name,
            "declaredDate": command.declared_date.value.isoformat(),
            "paidDate": command.paid_date.value.isoformat(),
            "grossAmount": format(command.gross_amount.amount, "f"),
            "taxTreatment": command.tax_treatment.value,
        }
    if isinstance(command, RecordShareSaleCommand):
        return {
            **common,
            "positionId": str(command.position_id),
            "saleDate": command.sale_date.value.isoformat(),
            "soldShareCount": command.sold_share_count,
            "proceeds": format(command.proceeds.amount, "f"),
        }
    return {
        **common,
        "investmentKey": command.investment_key,
        "investmentName": command.investment_name,
        "investmentKind": command.investment_kind.value,
        "taxTreatment": command.tax_treatment.value,
        "acquisitionDate": command.acquisition_date.value.isoformat(),
        "shareCount": command.share_count,
        "purchaseAmount": format(command.purchase_amount.amount, "f"),
        "orgNumber": command.org_number,
    }


def _map_investments_database_error(message: str) -> InvestmentsError | Exception:
    definitions = (
        (
            "investments_idempotency_key_reused",
            InvestmentsError.conflict(InvestmentsErrorCode.IDEMPOTENCY_KEY_REUSED),
        ),
        (
            "investments_idempotency_in_progress",
            InvestmentsError.conflict(InvestmentsErrorCode.IDEMPOTENCY_IN_PROGRESS),
        ),
        ("investments_forbidden", InvestmentsError.forbidden()),
        ("investments_invalid_input", InvestmentsError.invalid_input()),
        ("investments_dependency_unavailable", InvestmentsError.unavailable()),
    )
    for marker, mapped in definitions:
        if marker in message:
            return mapped
    return _map_database_error(message)


class SupabaseInvestmentsAdapter:
    """Authenticate one bearer and bind investments to a short DB transaction."""

    def __init__(self, configuration: LedgerSupabaseConfiguration) -> None:
        self._configuration = configuration
        self._ledger_authentication = SupabaseLedgerAdapter(configuration)

    @classmethod
    def from_environment(cls) -> SupabaseInvestmentsAdapter:
        return cls(
            LedgerSupabaseConfiguration(
                url=os.environ.get("SUPABASE_URL", ""),
                anon_key=os.environ.get("SUPABASE_ANON_KEY", ""),
                database_url=os.environ.get("TALLI_LEDGER_DATABASE_URL", ""),
            )
        )

    async def session(self, access_token: str) -> SupabaseInvestmentsSession:
        try:
            ledger_session: SupabaseLedgerSession = (
                await self._ledger_authentication.session(access_token)
            )
        except LedgerAuthenticationError:
            raise InvestmentsAuthenticationError from None
        return SupabaseInvestmentsSession(
            self._configuration.database_url,
            ledger_session._verified,
        )


@investments_persistence_adapter(InvestmentsPersistence)
class SupabaseInvestmentsSession:
    def __init__(self, database_url: str, verified: _VerifiedActor) -> None:
        self._database_url = database_url
        self._verified = verified

    @property
    def actor_id(self):
        return self._verified.actor_id

    async def _query_rows(
        self,
        query: str,
        parameters: tuple[object, ...],
    ) -> list[Mapping[str, object]]:
        if not self._database_url:
            raise InvestmentsError.unavailable()
        try:
            async with await psycopg.AsyncConnection.connect(
                self._database_url,
                connect_timeout=5,
                row_factory=dict_row,
            ) as connection, connection.transaction():
                await connection.execute("set local role investments_executor")
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
        except InvestmentsError:
            raise
        except psycopg.OperationalError:
            raise InvestmentsError.unavailable() from None
        except psycopg.DatabaseError as error:
            raise _map_investments_database_error(str(error)) from None

    def _query_input(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        limit: int,
    ) -> None:
        if (
            actor_id != self.actor_id
            or not 1 <= len(company_ids) <= 100
            or not 1 <= limit <= 100
            or not str(correlation_id)
        ):
            raise InvestmentsError.invalid_input()

    async def list_positions(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: InvestmentCursor | None,
        limit: int,
    ) -> InvestmentPositionPage:
        self._query_input(
            actor_id=actor_id,
            company_ids=company_ids,
            correlation_id=correlation_id,
            limit=limit,
        )
        rows = await self._query_rows(
            """
            select id, company_id, investment_key, name, kind, tax_treatment,
              org_number, share_count, cost_basis, lot_history_status,
              pg_catalog.jsonb_array_length(movements) as movement_count, movements,
              created_by, created_at, updated_at
            from investments.positions
            where company_id = any(%s::uuid[])
              and (%s::uuid is null or id > %s::uuid)
            order by id
            limit %s
            """,
            (
                [str(company_id) for company_id in company_ids],
                str(cursor) if cursor else None,
                str(cursor) if cursor else None,
                limit + 1,
            ),
        )
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        items = tuple(_position(row) for row in page_rows)
        return InvestmentPositionPage(
            items=items,
            next_cursor=(
                InvestmentCursor(str(page_rows[-1]["id"])) if has_more else None
            ),
            has_more=has_more,
        )

    async def list_activity(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: InvestmentCursor | None,
        limit: int,
    ) -> InvestmentActivityPage:
        self._query_input(
            actor_id=actor_id,
            company_ids=company_ids,
            correlation_id=correlation_id,
            limit=limit,
        )
        rows = await self._query_rows(
            """
            select activity.* from (
              select purchase.action_id as id, purchase.company_id,
                purchase.income_year, 'share_purchase'::text as activity_kind,
                purchase.acquisition_date as action_date, purchase.position_id,
                position.investment_key, position.name as investment_name,
                position.kind as investment_kind, position.tax_treatment,
                position.org_number, purchase.acquisition_lot_id,
                purchase.share_count, purchase.purchase_amount,
                null::bigint as sold_share_count, null::numeric as proceeds,
                null::numeric as fifo_cost_basis_reduction,
                null::bigint as remaining_share_count,
                null::numeric as remaining_cost_basis,
                null::text as paying_company_name, null::date as declared_date,
                null::numeric as gross_amount, null::numeric as taxable_add_back,
                null::numeric as gain_or_loss, purchase.bank_transaction_id,
                purchase.document_id, purchase.document_status,
                purchase.accounting_entry_id,
                purchase.created_by, purchase.created_at
              from investments.share_purchases purchase
              join investments.positions position on position.id = purchase.position_id
              where purchase.accounting_entry_id is not null
              union all
              select sale.action_id, sale.company_id, sale.income_year,
                'share_sale'::text, sale.sale_date, sale.position_id,
                position.investment_key, position.name, position.kind,
                position.tax_treatment, position.org_number, null::uuid,
                null::bigint, null::numeric, sale.sold_share_count,
                sale.proceeds, sale.fifo_cost_basis_reduction,
                sale.remaining_share_count, sale.remaining_cost_basis,
                null::text, null::date, null::numeric, null::numeric,
                sale.gain_or_loss, sale.bank_transaction_id,
                sale.document_id, sale.document_status, sale.accounting_entry_id,
                sale.created_by, sale.created_at
              from investments.share_sales sale
              join investments.positions position on position.id = sale.position_id
              where sale.accounting_entry_id is not null
              union all
              select dividend.action_id, dividend.company_id,
                dividend.income_year, 'dividend_received'::text,
                dividend.paid_date, dividend.position_id,
                position.investment_key, position.name, position.kind,
                dividend.tax_treatment, position.org_number, null::uuid,
                null::bigint, null::numeric, null::bigint, null::numeric,
                null::numeric, null::bigint, null::numeric,
                dividend.paying_company_name, dividend.declared_date,
                dividend.gross_amount, dividend.taxable_add_back, null::numeric,
                dividend.bank_transaction_id, dividend.document_id,
                dividend.document_status,
                dividend.accounting_entry_id, dividend.created_by,
                dividend.created_at
              from investments.received_dividends dividend
              join investments.positions position on position.id = dividend.position_id
              where dividend.accounting_entry_id is not null
            ) activity
            where activity.company_id = any(%s::uuid[])
              and (%s::uuid is null or activity.id > %s::uuid)
            order by activity.id
            limit %s
            """,
            (
                [str(company_id) for company_id in company_ids],
                str(cursor) if cursor else None,
                str(cursor) if cursor else None,
                limit + 1,
            ),
        )
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        items = tuple(_activity(row) for row in page_rows)
        return InvestmentActivityPage(
            items=items,
            next_cursor=(
                InvestmentCursor(str(page_rows[-1]["id"])) if has_more else None
            ),
            has_more=has_more,
        )

    async def list_acquisition_lots(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: InvestmentCursor | None,
        limit: int,
    ) -> AcquisitionLotPage:
        self._query_input(
            actor_id=actor_id,
            company_ids=company_ids,
            correlation_id=correlation_id,
            limit=limit,
        )
        rows = await self._query_rows(
            """
            select id, company_id, position_id, acquisition_action_id,
              acquisition_date, original_share_count, remaining_share_count,
              original_cost_basis, remaining_cost_basis, created_by, created_at
            from investments.acquisition_lots
            where company_id = any(%s::uuid[])
              and (%s::uuid is null or id > %s::uuid)
            order by id
            limit %s
            """,
            (
                [str(company_id) for company_id in company_ids],
                str(cursor) if cursor else None,
                str(cursor) if cursor else None,
                limit + 1,
            ),
        )
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        items = tuple(_lot(row) for row in page_rows)
        return AcquisitionLotPage(
            items=items,
            next_cursor=(
                InvestmentCursor(str(page_rows[-1]["id"])) if has_more else None
            ),
            has_more=has_more,
        )

    async def list_share_sale_allocations(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: InvestmentCursor | None,
        limit: int,
    ) -> ShareSaleAllocationPage:
        self._query_input(
            actor_id=actor_id,
            company_ids=company_ids,
            correlation_id=correlation_id,
            limit=limit,
        )
        rows = await self._query_rows(
            """
            select id, company_id, position_id,
              acquisition_lot_id as lot_id, sale_action_id,
              allocation_order, acquisition_date,
              allocated_share_count, allocated_cost_basis,
              created_by, created_at
            from investments.share_sale_allocations
            where company_id = any(%s::uuid[])
              and (%s::uuid is null or id > %s::uuid)
            order by id
            limit %s
            """,
            (
                [str(company_id) for company_id in company_ids],
                str(cursor) if cursor else None,
                str(cursor) if cursor else None,
                limit + 1,
            ),
        )
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        items = tuple(_allocation(row) for row in page_rows)
        return ShareSaleAllocationPage(
            items=items,
            next_cursor=(
                InvestmentCursor(str(page_rows[-1]["id"])) if has_more else None
            ),
            has_more=has_more,
        )

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[SupabaseInvestmentsTransaction]:
        if not self._database_url:
            raise InvestmentsError.unavailable()
        try:
            async with await psycopg.AsyncConnection.connect(
                self._database_url,
                connect_timeout=5,
                row_factory=dict_row,
            ) as connection, connection.transaction():
                await connection.execute("set local role investments_workflow_executor")
                await connection.execute(
                    "select pg_catalog.set_config('talli.verified_actor_id', %s, true)",
                    (str(self.actor_id.subject),),
                )
                await connection.execute(
                    "select pg_catalog.set_config('talli.verified_actor_claims', %s, true)",
                    (self._verified.claims_json,),
                )
                yield SupabaseInvestmentsTransaction(
                    self._database_url,
                    self._verified,
                    connection,
                )
        except (InvestmentsError, LedgerError):
            raise
        except psycopg.OperationalError:
            raise InvestmentsError.unavailable() from None
        except psycopg.DatabaseError as error:
            raise _map_investments_database_error(str(error)) from None


class SupabaseInvestmentsTransaction(SupabaseLedgerWorkflowTransaction):
    async def _database_rows(
        self,
        query: str,
        parameters: tuple[object, ...] = (),
    ) -> list[Mapping[str, object]]:
        try:
            cursor = await self._connection.execute(query, parameters)
            return list(await cursor.fetchall())
        except psycopg.OperationalError:
            raise InvestmentsError.unavailable() from None
        except psycopg.DatabaseError as error:
            raise _map_investments_database_error(str(error)) from None

    async def _investment_result(
        self,
        query: str,
        command: RecordSharePurchaseCommand | RecordShareSaleCommand | RecordReceivedDividendCommand,
        extra: tuple[object, ...] = (),
        request_extra: Mapping[str, object] | None = None,
    ) -> Mapping[str, object] | None:
        if command.actor_id != self.actor_id:
            raise InvestmentsError.forbidden()
        rows = await self._database_rows(
            query,
            (
                json.dumps(
                    {**_request_payload(command), **(request_extra or {})},
                    separators=(",", ":"),
                ),
                *extra,
                str(command.actor_id.subject),
            ),
        )
        if len(rows) != 1:
            raise InvestmentsError.unavailable()
        result = rows[0].get("result")
        if result is None:
            return None
        if not isinstance(result, Mapping):
            raise InvestmentsError.unavailable()
        return result

    async def get_received_dividend_replay(
        self, command: RecordReceivedDividendCommand
    ) -> RecordedReceivedDividend | None:
        result = await self._investment_result(
            "select investments.get_received_dividend_replay_v1(%s::jsonb, %s::text) as result",
            command,
        )
        return _recorded_dividend(result) if result is not None else None

    async def prepare_received_dividend(
        self,
        command: RecordReceivedDividendCommand,
        *,
        taxable_add_back: Money,
    ) -> PreparedReceivedDividend:
        result = await self._investment_result(
            "select investments.prepare_received_dividend_v1(%s::jsonb, %s::text) as result",
            command,
            request_extra={
                "taxableAddBack": format(taxable_add_back.amount, "f")
            },
        )
        if result is None:
            raise InvestmentsError.unavailable()
        return PreparedReceivedDividend(
            position_id=InvestmentPositionId(str(result["positionId"])),
            investment_name=str(result["investmentName"]),
            paying_company_name=str(result["payingCompanyName"]),
            taxable_add_back=_money(result["taxableAddBack"]),
        )

    async def complete_received_dividend(
        self,
        command: RecordReceivedDividendCommand,
        *,
        prepared: PreparedReceivedDividend,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedReceivedDividend:
        result = await self._investment_result(
            """
            select investments.complete_received_dividend_v1(
              %s::jsonb, %s::uuid, %s::text
            ) as result
            """,
            command,
            (str(accounting_entry_id),),
            request_extra={
                "taxableAddBack": format(prepared.taxable_add_back.amount, "f")
            },
        )
        if result is None:
            raise InvestmentsError.unavailable()
        return _recorded_dividend(result)

    async def get_share_purchase_replay(
        self, command: RecordSharePurchaseCommand
    ) -> RecordedSharePurchase | None:
        result = await self._investment_result(
            "select investments.get_share_purchase_replay_v1(%s::jsonb, %s::text) as result",
            command,
        )
        return _recorded(result) if result is not None else None

    async def prepare_share_purchase(
        self, command: RecordSharePurchaseCommand
    ) -> PreparedSharePurchase:
        result = await self._investment_result(
            "select investments.prepare_share_purchase_v1(%s::jsonb, %s::text) as result",
            command,
        )
        if result is None:
            raise InvestmentsError.unavailable()
        return PreparedSharePurchase(
            position_id=InvestmentPositionId(str(result["positionId"])),
            lot_id=AcquisitionLotId(str(result["lotId"])),
            position_created=bool(result["positionCreated"]),
            investment_name=str(result["investmentName"]),
            purchase_amount=command.purchase_amount,
        )

    async def complete_share_purchase(
        self,
        command: RecordSharePurchaseCommand,
        *,
        prepared: PreparedSharePurchase,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedSharePurchase:
        result = await self._investment_result(
            """
            select investments.complete_share_purchase_v1(
              %s::jsonb, %s::uuid, %s::jsonb, %s::text
            ) as result
            """,
            command,
            (
                str(accounting_entry_id),
                json.dumps(
                    {
                        "positionId": str(prepared.position_id),
                        "lotId": str(prepared.lot_id),
                        "positionCreated": prepared.position_created,
                    },
                    separators=(",", ":"),
                ),
            ),
        )
        if result is None:
            raise InvestmentsError.unavailable()
        return _recorded(result)

    async def get_share_sale_replay(
        self, command: RecordShareSaleCommand
    ) -> RecordedShareSale | None:
        result = await self._investment_result(
            "select investments.get_share_sale_replay_v1(%s::jsonb, %s::text) as result",
            command,
        )
        return _recorded_sale(result) if result is not None else None

    async def prepare_share_sale(
        self, command: RecordShareSaleCommand
    ) -> PreparedShareSale:
        result = await self._investment_result(
            "select investments.prepare_share_sale_v1(%s::jsonb, %s::text) as result",
            command,
        )
        if result is None:
            raise InvestmentsError.unavailable()
        return PreparedShareSale(
            position_id=InvestmentPositionId(str(result["positionId"])),
            investment_name=str(result["investmentName"]),
            fifo_cost_basis_reduction=_money(result["fifoCostBasisReduction"]),
        )

    async def complete_share_sale(
        self,
        command: RecordShareSaleCommand,
        *,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedShareSale:
        result = await self._investment_result(
            """
            select investments.complete_share_sale_v1(
              %s::jsonb, %s::uuid, %s::text
            ) as result
            """,
            command,
            (str(accounting_entry_id),),
        )
        if result is None:
            raise InvestmentsError.unavailable()
        return _recorded_sale(result)


def _recorded(value: Mapping[str, object]) -> RecordedSharePurchase:
    return RecordedSharePurchase(
        action_id=InvestmentActionId(str(value["actionId"])),
        position_id=InvestmentPositionId(str(value["positionId"])),
        lot_id=AcquisitionLotId(str(value["lotId"])),
        accounting_entry_id=AccountingEntryReference(str(value["accountingEntryId"])),
        position_created=bool(value["positionCreated"]),
        replayed=bool(value["replayed"]),
    )


def _recorded_dividend(value: Mapping[str, object]) -> RecordedReceivedDividend:
    return RecordedReceivedDividend(
        action_id=InvestmentActionId(str(value["actionId"])),
        position_id=InvestmentPositionId(str(value["positionId"])),
        accounting_entry_id=AccountingEntryReference(str(value["accountingEntryId"])),
        taxable_add_back=_money(value["taxableAddBack"]),
        replayed=bool(value["replayed"]),
    )


def _recorded_sale(value: Mapping[str, object]) -> RecordedShareSale:
    return RecordedShareSale(
        action_id=InvestmentActionId(str(value["actionId"])),
        position_id=InvestmentPositionId(str(value["positionId"])),
        accounting_entry_id=AccountingEntryReference(str(value["accountingEntryId"])),
        replayed=bool(value["replayed"]),
    )


def _position(value: Mapping[str, object]) -> InvestmentPositionView:
    return InvestmentPositionView(
        position_id=InvestmentPositionId(str(value["id"])),
        company_id=CompanyId(str(value["company_id"])),
        investment_key=str(value["investment_key"]),
        name=str(value["name"]),
        kind=InvestmentKind(str(value["kind"])),
        tax_treatment=InvestmentTaxTreatment(str(value["tax_treatment"])),
        org_number=str(value["org_number"]) if value["org_number"] else None,
        share_count=int(value["share_count"]),
        cost_basis=_money(value["cost_basis"]),
        lot_history_status=InvestmentLotHistoryStatus(
            str(value["lot_history_status"])
        ),
        movement_count=int(value["movement_count"]),
        movements=tuple(value["movements"]),
        created_by=_actor(value["created_by"]),
        created_at=_timestamp(value["created_at"]),
        updated_at=_timestamp(value["updated_at"]),
    )


def _lot(value: Mapping[str, object]) -> AcquisitionLotView:
    return AcquisitionLotView(
        lot_id=AcquisitionLotId(str(value["id"])),
        company_id=CompanyId(str(value["company_id"])),
        position_id=InvestmentPositionId(str(value["position_id"])),
        acquisition_action_id=InvestmentActionId(
            str(value["acquisition_action_id"])
        ),
        acquisition_date=LocalDate(value["acquisition_date"]),
        original_share_count=int(value["original_share_count"]),
        remaining_share_count=int(value["remaining_share_count"]),
        original_cost_basis=_money(value["original_cost_basis"]),
        remaining_cost_basis=_money(value["remaining_cost_basis"]),
        created_by=_actor(value["created_by"]),
        created_at=_timestamp(value["created_at"]),
    )


def _activity(value: Mapping[str, object]) -> InvestmentActivityView:
    return InvestmentActivityView(
        activity_id=InvestmentActionId(str(value["id"])),
        company_id=CompanyId(str(value["company_id"])),
        income_year=IncomeYear(int(value["income_year"])),
        activity_kind=InvestmentActivityKind(str(value["activity_kind"])),
        action_date=LocalDate(value["action_date"]),
        position_id=InvestmentPositionId(str(value["position_id"])),
        investment_key=str(value["investment_key"]),
        investment_name=str(value["investment_name"]),
        investment_kind=InvestmentKind(str(value["investment_kind"])),
        tax_treatment=InvestmentTaxTreatment(str(value["tax_treatment"])),
        org_number=str(value["org_number"]) if value["org_number"] else None,
        acquisition_lot_id=(
            AcquisitionLotId(str(value["acquisition_lot_id"]))
            if value["acquisition_lot_id"] is not None
            else None
        ),
        share_count=int(value["share_count"]) if value["share_count"] is not None else None,
        purchase_amount=(
            _money(value["purchase_amount"])
            if value["purchase_amount"] is not None
            else None
        ),
        sold_share_count=(
            int(value["sold_share_count"])
            if value["sold_share_count"] is not None
            else None
        ),
        proceeds=_money(value["proceeds"]) if value["proceeds"] is not None else None,
        fifo_cost_basis_reduction=(
            _money(value["fifo_cost_basis_reduction"])
            if value["fifo_cost_basis_reduction"] is not None
            else None
        ),
        remaining_share_count=(
            int(value["remaining_share_count"])
            if value["remaining_share_count"] is not None
            else None
        ),
        remaining_cost_basis=(
            _money(value["remaining_cost_basis"])
            if value["remaining_cost_basis"] is not None
            else None
        ),
        paying_company_name=(
            str(value["paying_company_name"])
            if value["paying_company_name"] is not None
            else None
        ),
        declared_date=(
            LocalDate(value["declared_date"])
            if value["declared_date"] is not None
            else None
        ),
        gross_amount=_money(value["gross_amount"]) if value["gross_amount"] is not None else None,
        taxable_add_back=(
            _money(value["taxable_add_back"])
            if value["taxable_add_back"] is not None else None
        ),
        gain_or_loss=_money(value["gain_or_loss"]) if value["gain_or_loss"] is not None else None,
        bank_transaction_id=(
            InvestmentSourceReference(str(value["bank_transaction_id"]))
            if value["bank_transaction_id"] is not None
            else None
        ),
        document_id=(
            InvestmentSourceReference(str(value["document_id"]))
            if value["document_id"] is not None
            else None
        ),
        document_status=InvestmentDocumentStatus(str(value["document_status"])),
        accounting_entry_id=(
            AccountingEntryReference(str(value["accounting_entry_id"]))
            if value["accounting_entry_id"] is not None else None
        ),
        created_by=_actor(value["created_by"]),
        created_at=_timestamp(value["created_at"]),
    )


def _allocation(value: Mapping[str, object]) -> ShareSaleAllocationView:
    return ShareSaleAllocationView(
        allocation_id=ShareSaleAllocationId(str(value["id"])),
        company_id=CompanyId(str(value["company_id"])),
        position_id=InvestmentPositionId(str(value["position_id"])),
        lot_id=AcquisitionLotId(str(value["lot_id"])),
        sale_action_id=InvestmentActionId(str(value["sale_action_id"])),
        allocation_order=int(value["allocation_order"]),
        acquisition_date=LocalDate(value["acquisition_date"]),
        allocated_share_count=int(value["allocated_share_count"]),
        allocated_cost_basis=_money(value["allocated_cost_basis"]),
        created_by=_actor(value["created_by"]),
        created_at=_timestamp(value["created_at"]),
    )


def compose_investments_application(
    sessions: InvestmentsSessionFactory | None = None,
) -> InvestmentsApplication:
    return InvestmentsApplication(
        sessions or SupabaseInvestmentsAdapter.from_environment(),
        LedgerService,
    )


__all__ = [
    "SupabaseInvestmentsAdapter",
    "SupabaseInvestmentsSession",
    "SupabaseInvestmentsTransaction",
    "compose_investments_application",
]
