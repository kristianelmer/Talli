"""Private Supabase persistence for the investments capability."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from decimal import Decimal

import psycopg
from psycopg.rows import dict_row

from talli_backend.adapters.supabase_ledger import (
    LedgerSupabaseConfiguration,
    SupabaseLedgerAdapter,
    SupabaseLedgerSession,
    SupabaseLedgerWorkflowTransaction,
    _VerifiedActor,
    _actor,
    _fact_reference_payload,
    _line_payload,
    _map_database_error,
    _money,
    _posted_entry,
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
    CorrectInvestmentCommand,
    InvestmentActionId,
    InvestmentAccountingClassification,
    InvestmentActivityKind,
    InvestmentActivityPage,
    InvestmentActivityView,
    InvestmentCursor,
    InvestmentCorrectionId,
    InvestmentCorrectionPage,
    InvestmentCorrectionView,
    InvestmentDocumentStatus,
    InvestmentEconomicEventId,
    InvestmentEvidenceMode,
    InvestmentKind,
    InvestmentLotHistoryStatus,
    InvestmentPositionPage,
    InvestmentPositionId,
    InvestmentPositionView,
    InvestmentSaleLotFact,
    InvestmentSettlementBalanceKind,
    InvestmentSettlementId,
    InvestmentSourceReference,
    InvestmentTaxTreatment,
    InvestmentsError,
    InvestmentsErrorCode,
    InvestmentsPersistence,
    PreparedReceivedDividend,
    PreparedReceivedDividendFacts,
    PreparedReceivedFundDistribution,
    PreparedReceivedFundDistributionFacts,
    PreparedInvestmentCorrection,
    PreparedInvestmentCashSettlement,
    PreparedSharePurchase,
    PreparedSharePurchaseRecognition,
    PreparedShareSale,
    PreparedShareSaleFacts,
    RecordReceivedDividendCommand,
    RecordReceivedFundDistributionCommand,
    RecordSharePurchaseCommand,
    RecordShareSaleCommand,
    RecognizeSharePurchaseCommand,
    RecordedReceivedDividend,
    RecordedReceivedFundDistribution,
    RecordedInvestmentCorrection,
    RecordedInvestmentCashSettlement,
    RecordedInvestmentEconomicEvent,
    RecordedSharePurchase,
    RecordedShareSale,
    SettleInvestmentCashCommand,
    ShareSaleAllocationId,
    ShareSaleAllocationPage,
    ShareSaleAllocationView,
    investments_persistence_adapter,
)
from talli_backend.modules.ledger.public import (
    LedgerError,
    LedgerSourceCapability,
    RecognizeHoldingActionCommand,
)
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
    command: RecordSharePurchaseCommand | RecordShareSaleCommand | RecordReceivedDividendCommand | RecordReceivedFundDistributionCommand,
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
        "evidenceMode": command.evidence_mode.value,
        "evidenceReference": command.evidence_reference,
        "ownerAttested": command.owner_attested,
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
            "lawfulDividendConfirmed": command.lawful_dividend_confirmed,
            "groupExceptionClaimed": command.group_exception_claimed,
            "yearEndOwnershipBasisPoints": command.year_end_ownership_basis_points,
            "yearEndVotingBasisPoints": command.year_end_voting_basis_points,
            "groupEvidenceReference": command.group_evidence_reference,
        }
    if isinstance(command, RecordReceivedFundDistributionCommand):
        return {
            **common,
            "positionId": str(command.position_id),
            "fundName": command.fund_name,
            "entitlementDate": command.entitlement_date.value.isoformat(),
            "paidDate": command.paid_date.value.isoformat(),
            "grossAmount": format(command.gross_amount.amount, "f"),
            "openingFundEquityRatioBasisPoints": (
                command.opening_fund_equity_ratio_basis_points
            ),
            "fundTaxStatementReference": command.fund_tax_statement_reference,
        }
    if isinstance(command, RecordShareSaleCommand):
        return {
            **common,
            "positionId": str(command.position_id),
            "saleDate": command.sale_date.value.isoformat(),
            "soldShareCount": command.sold_share_count,
            "proceeds": format(command.proceeds.amount, "f"),
            "transactionCosts": format(command.transaction_costs.amount, "f"),
            "saleYearFundEquityRatioBasisPoints": (
                command.sale_year_fund_equity_ratio_basis_points
            ),
            "fundTaxStatementReference": command.fund_tax_statement_reference,
        }
    return {
        **common,
        "investmentKey": command.investment_key,
        "investmentName": command.investment_name,
        "investmentKind": command.investment_kind.value,
        "accountingClassification": command.accounting_classification.value,
        "taxTreatment": command.tax_treatment.value,
        "acquisitionDate": command.acquisition_date.value.isoformat(),
        "shareCount": command.share_count,
        "purchaseAmount": format(command.purchase_amount.amount, "f"),
        "transactionCosts": format(command.transaction_costs.amount, "f"),
        "orgNumber": command.org_number,
        "fundEquityRatioBasisPoints": command.fund_equity_ratio_basis_points,
        "fundTaxStatementReference": command.fund_tax_statement_reference,
    }


def _fact_payload(fact) -> dict[str, object]:
    return {
        "capability": fact.capability.value,
        "recordId": str(fact.record_id),
        "revision": fact.revision,
        "factSha256": fact.fact_sha256,
    }


def _lifecycle_request_payload(
    command: RecognizeSharePurchaseCommand | SettleInvestmentCashCommand,
) -> dict[str, object]:
    common: dict[str, object] = {
        "companyId": str(command.company_id),
        "incomeYear": int(command.income_year),
        "idempotencyKey": str(command.idempotency_key),
        "correlationId": str(command.correlation_id),
        "evidenceMode": command.evidence.mode.value,
        "evidenceReference": command.evidence.reference,
        "ownerAttested": command.evidence.owner_attested,
        "documentFacts": [
            _fact_payload(fact) for fact in command.evidence.document_facts
        ],
        "bankFact": (
            _fact_payload(command.evidence.bank_fact)
            if command.evidence.bank_fact is not None
            else None
        ),
    }
    if isinstance(command, SettleInvestmentCashCommand):
        return {
            **common,
            "settlementId": str(command.settlement_id),
            "eventId": str(command.event_id),
            "settlementDate": command.settlement_date.value.isoformat(),
            "amount": format(command.amount.amount, "f"),
        }
    return {
        **common,
        "eventId": str(command.event_id),
        "investmentKey": command.investment_key,
        "investmentName": command.investment_name,
        "investmentKind": command.investment_kind.value,
        "accountingClassification": command.accounting_classification.value,
        "acquisitionDate": command.acquisition_date.value.isoformat(),
        "shareCount": format(command.share_count.amount, ".12f"),
        "purchaseAmount": format(command.purchase_amount.amount, "f"),
        "transactionCosts": format(command.transaction_costs.amount, "f"),
        "orgNumber": command.org_number,
        "fundEquityRatioBasisPoints": command.fund_equity_ratio_basis_points,
        "fundTaxStatementReference": command.fund_tax_statement_reference,
    }
def _correction_request_payload(command: CorrectInvestmentCommand) -> dict[str, object]:
    replacement = command.replacement
    return {
        "companyId": str(command.company_id),
        "incomeYear": int(command.income_year),
        "correctionId": str(command.correction_id),
        "idempotencyKey": str(command.idempotency_key),
        "correlationId": str(command.correlation_id),
        "originalActionId": str(command.original_action_id),
        "originalActivityKind": command.original_activity_kind.value,
        "replacementActionId": str(replacement.action_id),
        "replacementActivityKind": _replacement_activity_kind(replacement).value,
        "correctionDate": command.correction_date.value.isoformat(),
        "reason": command.reason,
        "bankTransactionId": (
            str(command.bank_transaction_id) if command.bank_transaction_id else None
        ),
        "documentId": str(command.document_id) if command.document_id else None,
        "documentStatus": command.document_status.value,
        "evidenceMode": command.evidence_mode.value,
        "evidenceReference": command.evidence_reference,
        "ownerAttested": command.owner_attested,
        "replacement": _request_payload(replacement),
    }


def _replacement_activity_kind(command) -> InvestmentActivityKind:
    if isinstance(command, RecordSharePurchaseCommand):
        return InvestmentActivityKind.SHARE_PURCHASE
    if isinstance(command, RecordShareSaleCommand):
        return InvestmentActivityKind.SHARE_SALE
    if isinstance(command, RecordReceivedDividendCommand):
        return InvestmentActivityKind.DIVIDEND_RECEIVED
    if isinstance(command, RecordReceivedFundDistributionCommand):
        return InvestmentActivityKind.FUND_DISTRIBUTION_RECEIVED
    raise InvestmentsError.invalid_input()


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
            select id, company_id, investment_key, name, kind,
              accounting_classification, tax_treatment, org_number,
              fund_equity_ratio_basis_points, fund_tax_statement_reference,
              share_count, cost_basis, tax_basis, lot_history_status,
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

    async def list_corrections(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: InvestmentCursor | None,
        limit: int,
    ) -> InvestmentCorrectionPage:
        self._query_input(
            actor_id=actor_id,
            company_ids=company_ids,
            correlation_id=correlation_id,
            limit=limit,
        )
        rows = await self._query_rows(
            """
            select correction_id as id, company_id, income_year,
              original_action_id, original_activity_kind,
              reversal_accounting_entry_id, replacement_action_id,
              replacement_activity_kind, replacement_accounting_entry_id,
              reason, bank_transaction_id, document_id, document_status,
              evidence_mode, evidence_reference, evidence_digest,
              owner_attested, created_by, created_at
            from investments.corrections
            where company_id = any(%s::uuid[])
              and (%s::uuid is null or correction_id > %s::uuid)
            order by correction_id
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
        return InvestmentCorrectionPage(
            items=tuple(_correction(row) for row in page_rows),
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
                position.kind as investment_kind,
                position.accounting_classification, position.tax_treatment,
                position.org_number, position.fund_equity_ratio_basis_points,
                purchase.fund_tax_statement_reference,
                purchase.acquisition_lot_id,
                purchase.share_count, purchase.purchase_amount,
                purchase.transaction_costs, purchase.capitalized_cost,
                null::bigint as sold_share_count, null::numeric as proceeds,
                null::numeric as net_proceeds,
                null::numeric as fifo_cost_basis_reduction,
                null::numeric as fifo_tax_basis_reduction,
                null::bigint as remaining_share_count,
                null::numeric as remaining_cost_basis,
                null::numeric as remaining_tax_basis,
                null::text as paying_company_name, null::date as declared_date,
                null::numeric as gross_amount, null::numeric as taxable_add_back,
                null::numeric as gain_or_loss, null::numeric as book_gain_or_loss,
                null::numeric as tax_gain_or_loss, null::numeric as exempt_gain,
                null::numeric as taxable_gain, null::numeric as non_deductible_loss,
                null::numeric as deductible_loss,
                null::boolean as lawful_dividend_confirmed,
                null::boolean as group_exception_claimed,
                null::boolean as group_exception_applied,
                null::integer as year_end_ownership_basis_points,
                null::integer as year_end_voting_basis_points,
                null::text as group_evidence_reference,
                null::text as fund_name, null::date as entitlement_date,
                null::integer as opening_fund_equity_ratio_basis_points,
                null::numeric as dividend_portion,
                null::numeric as interest_portion,
                null::numeric as total_taxable_income,
                purchase.bank_transaction_id,
                purchase.document_id, purchase.document_status,
                purchase.evidence_mode, purchase.evidence_reference,
                purchase.evidence_digest, purchase.calculation_id,
                purchase.owner_attested,
                purchase.accounting_entry_id,
                purchase.created_by, purchase.created_at
              from investments.share_purchases purchase
              join investments.positions position on position.id = purchase.position_id
              where purchase.accounting_entry_id is not null
              union all
              select sale.action_id, sale.company_id, sale.income_year,
                'share_sale'::text, sale.sale_date, sale.position_id,
                position.investment_key, position.name, position.kind,
                position.accounting_classification, position.tax_treatment,
                position.org_number, sale.sale_year_fund_equity_ratio_basis_points,
                sale.fund_tax_statement_reference,
                null::uuid, null::bigint, null::numeric,
                sale.transaction_costs, null::numeric, sale.sold_share_count,
                sale.proceeds, sale.net_proceeds, sale.fifo_cost_basis_reduction,
                sale.fifo_tax_basis_reduction,
                sale.remaining_share_count, sale.remaining_cost_basis,
                sale.remaining_tax_basis,
                null::text, null::date, null::numeric, null::numeric,
                sale.gain_or_loss, sale.book_gain_or_loss,
                sale.tax_gain_or_loss, sale.exempt_gain, sale.taxable_gain,
                sale.non_deductible_loss, sale.deductible_loss,
                null::boolean, null::boolean, null::boolean,
                null::integer, null::integer, null::text,
                null::text, null::date, null::integer,
                null::numeric, null::numeric, null::numeric,
                sale.bank_transaction_id,
                sale.document_id, sale.document_status,
                sale.evidence_mode, sale.evidence_reference,
                sale.evidence_digest, sale.calculation_id, sale.owner_attested,
                sale.accounting_entry_id,
                sale.created_by, sale.created_at
              from investments.share_sales sale
              join investments.positions position on position.id = sale.position_id
              where sale.accounting_entry_id is not null
              union all
              select dividend.action_id, dividend.company_id,
                dividend.income_year, 'dividend_received'::text,
                dividend.paid_date, dividend.position_id,
                position.investment_key, position.name, position.kind,
                position.accounting_classification, dividend.tax_treatment,
                position.org_number, position.fund_equity_ratio_basis_points,
                null::text,
                null::uuid, null::bigint, null::numeric, null::numeric,
                null::numeric, null::bigint, null::numeric, null::numeric,
                null::numeric, null::numeric, null::bigint, null::numeric,
                null::numeric,
                dividend.paying_company_name, dividend.declared_date,
                dividend.gross_amount, dividend.taxable_add_back, null::numeric,
                null::numeric, null::numeric, null::numeric, null::numeric,
                null::numeric, null::numeric,
                dividend.lawful_dividend_confirmed,
                dividend.group_exception_claimed,
                dividend.group_exception_applied,
                dividend.year_end_ownership_basis_points,
                dividend.year_end_voting_basis_points,
                dividend.group_evidence_reference,
                null::text, null::date, null::integer,
                null::numeric, null::numeric, null::numeric,
                dividend.bank_transaction_id, dividend.document_id,
                dividend.document_status,
                dividend.evidence_mode, dividend.evidence_reference,
                dividend.evidence_digest, dividend.calculation_id,
                dividend.owner_attested,
                dividend.accounting_entry_id, dividend.created_by,
                dividend.created_at
              from investments.received_dividends dividend
              join investments.positions position on position.id = dividend.position_id
              where dividend.accounting_entry_id is not null
              union all
              select distribution.action_id, distribution.company_id,
                distribution.income_year, 'fund_distribution_received'::text,
                distribution.paid_date, distribution.position_id,
                position.investment_key, position.name, position.kind,
                position.accounting_classification, position.tax_treatment,
                position.org_number, position.fund_equity_ratio_basis_points,
                distribution.fund_tax_statement_reference,
                null::uuid, null::bigint, null::numeric, null::numeric,
                null::numeric, null::bigint, null::numeric, null::numeric,
                null::numeric, null::numeric, null::bigint, null::numeric,
                null::numeric,
                null::text, null::date, distribution.gross_amount,
                distribution.taxable_add_back, null::numeric,
                null::numeric, null::numeric, null::numeric, null::numeric,
                null::numeric, null::numeric,
                null::boolean, null::boolean, null::boolean,
                null::integer, null::integer, null::text,
                distribution.fund_name, distribution.entitlement_date,
                distribution.opening_fund_equity_ratio_basis_points,
                distribution.dividend_portion, distribution.interest_portion,
                distribution.total_taxable_income,
                distribution.bank_transaction_id, distribution.document_id,
                distribution.document_status,
                distribution.evidence_mode, distribution.evidence_reference,
                distribution.evidence_digest, distribution.calculation_id,
                distribution.owner_attested,
                distribution.accounting_entry_id, distribution.created_by,
                distribution.created_at
              from investments.received_fund_distributions distribution
              join investments.positions position on position.id = distribution.position_id
              where distribution.accounting_entry_id is not null
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
              original_cost_basis, remaining_cost_basis,
              original_tax_basis, remaining_tax_basis,
              acquisition_year_fund_equity_ratio_basis_points,
              fund_tax_statement_reference, created_by, created_at
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
              allocated_book_cost_basis, allocated_tax_basis,
              allocated_net_proceeds, average_fund_equity_ratio_basis_points,
              tax_gain_or_loss, exempt_gain, taxable_gain,
              non_deductible_loss, deductible_loss,
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
        command: RecordSharePurchaseCommand | RecordShareSaleCommand
        | RecordReceivedDividendCommand | RecordReceivedFundDistributionCommand
        | CorrectInvestmentCommand | RecognizeSharePurchaseCommand
        | SettleInvestmentCashCommand,
        extra: tuple[object, ...] = (),
        request_extra: Mapping[str, object] | None = None,
    ) -> Mapping[str, object] | None:
        if command.actor_id != self.actor_id:
            raise InvestmentsError.forbidden()
        rows = await self._database_rows(
            query,
            (
                json.dumps(
                    {
                        **(
                            _correction_request_payload(command)
                            if isinstance(command, CorrectInvestmentCommand)
                            else _lifecycle_request_payload(command)
                            if isinstance(
                                command,
                                (
                                    RecognizeSharePurchaseCommand,
                                    SettleInvestmentCashCommand,
                                ),
                            )
                            else _request_payload(command)
                        ),
                        **(request_extra or {}),
                    },
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

    async def post_entry(
        self,
        command,
        *,
        entry_kind,
        memo,
        lines,
        risk_flags,
        warning_accepted,
        source_capability,
        source_record_id,
        requested_entry_id=None,
    ):
        if (
            not isinstance(command, RecognizeHoldingActionCommand)
            or requested_entry_id is not None
            or risk_flags
            or warning_accepted
            or source_capability is not LedgerSourceCapability.INVESTMENTS
            or source_record_id != command.primary_source.record_id
        ):
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        sources = (
            _fact_reference_payload(command.primary_source, primary=True),
            *(
                _fact_reference_payload(source, primary=False)
                for source in command.corroborating_sources
            ),
        )
        row = await self._one_idempotent_row(
            """
            select * from ledger.post_investment_lifecycle_entry_v2(
              %s::text, %s::uuid, %s::integer, %s::text, %s::text,
              %s::jsonb, %s::text, %s::text, %s::text, %s::text,
              %s::date, %s::text, %s::jsonb
            )
            """,
            (
                str(command.idempotency_key),
                str(command.company_id),
                int(command.income_year),
                entry_kind.value,
                memo,
                json.dumps(
                    [_line_payload(line) for line in lines],
                    separators=(",", ":"),
                ),
                source_capability.value,
                str(source_record_id),
                str(command.correlation_id),
                str(command.actor_id.subject),
                command.event_date.value,
                "ledger-supported-patterns-2026.1",
                json.dumps(sources, separators=(",", ":")),
            ),
        )
        return _posted_entry(row)

    async def get_share_purchase_recognition_replay(
        self, command: RecognizeSharePurchaseCommand
    ) -> RecordedInvestmentEconomicEvent | None:
        result = await self._investment_result(
            "select investments.get_share_purchase_recognition_replay_v2(%s::jsonb, %s::text) as result",
            command,
        )
        return _recorded_economic_event(result) if result is not None else None

    async def prepare_share_purchase_recognition(
        self,
        command: RecognizeSharePurchaseCommand,
        *,
        capitalized_cost: Money,
        evidence_digest: str,
        calculation_id: str,
    ) -> PreparedSharePurchaseRecognition:
        result = await self._investment_result(
            "select investments.prepare_share_purchase_recognition_v2(%s::jsonb, %s::text) as result",
            command,
            request_extra={
                "acquisitionCost": format(capitalized_cost.amount, "f"),
                "evidenceDigest": evidence_digest,
                "calculationId": calculation_id,
            },
        )
        if result is None:
            raise InvestmentsError.unavailable()
        return PreparedSharePurchaseRecognition(
            position_id=InvestmentPositionId(str(result["positionId"])),
            lot_id=AcquisitionLotId(str(result["lotId"])),
            position_created=bool(result["positionCreated"]),
            investment_name=str(result["investmentName"]),
            accounting_classification=InvestmentAccountingClassification(
                str(result["accountingClassification"])
            ),
            acquisition_cost=_money(result["acquisitionCost"]),
            expected_settlement_amount=_money(
                result["expectedSettlementAmount"]
            ),
            settlement_balance_kind=InvestmentSettlementBalanceKind(
                str(result["settlementBalanceKind"])
            ),
            evidence_digest=evidence_digest,
            calculation_id=calculation_id,
        )

    async def complete_share_purchase_recognition(
        self,
        command: RecognizeSharePurchaseCommand,
        *,
        prepared: PreparedSharePurchaseRecognition,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedInvestmentEconomicEvent:
        result = await self._investment_result(
            """
            select investments.complete_share_purchase_recognition_v2(
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
                        "acquisitionCost": format(
                            prepared.acquisition_cost.amount, "f"
                        ),
                        "expectedSettlementAmount": format(
                            prepared.expected_settlement_amount.amount, "f"
                        ),
                        "settlementBalanceKind": (
                            prepared.settlement_balance_kind.value
                        ),
                        "evidenceDigest": prepared.evidence_digest,
                        "calculationId": prepared.calculation_id,
                    },
                    separators=(",", ":"),
                ),
            ),
        )
        if result is None:
            raise InvestmentsError.unavailable()
        return _recorded_economic_event(result)

    async def get_cash_settlement_replay(
        self, command: SettleInvestmentCashCommand
    ) -> RecordedInvestmentCashSettlement | None:
        result = await self._investment_result(
            "select investments.get_cash_settlement_replay_v2(%s::jsonb, %s::text) as result",
            command,
        )
        return _recorded_cash_settlement(result) if result is not None else None

    async def prepare_cash_settlement(
        self,
        command: SettleInvestmentCashCommand,
        *,
        evidence_digest: str,
    ) -> PreparedInvestmentCashSettlement:
        result = await self._investment_result(
            "select investments.prepare_cash_settlement_v2(%s::jsonb, %s::text) as result",
            command,
            request_extra={"evidenceDigest": evidence_digest},
        )
        if result is None:
            raise InvestmentsError.unavailable()
        return PreparedInvestmentCashSettlement(
            event_id=InvestmentEconomicEventId(str(result["eventId"])),
            recognition_accounting_entry_id=AccountingEntryReference(
                str(result["recognitionAccountingEntryId"])
            ),
            settlement_balance_kind=InvestmentSettlementBalanceKind(
                str(result["settlementBalanceKind"])
            ),
            amount=_money(result["amount"]),
            event_fact_sha256=str(result["eventFactSha256"]),
            evidence_digest=evidence_digest,
        )

    async def complete_cash_settlement(
        self,
        command: SettleInvestmentCashCommand,
        *,
        prepared: PreparedInvestmentCashSettlement,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedInvestmentCashSettlement:
        result = await self._investment_result(
            """
            select investments.complete_cash_settlement_v2(
              %s::jsonb, %s::uuid, %s::jsonb, %s::text
            ) as result
            """,
            command,
            (
                str(accounting_entry_id),
                json.dumps(
                    {
                        "eventId": str(prepared.event_id),
                        "recognitionAccountingEntryId": str(
                            prepared.recognition_accounting_entry_id
                        ),
                        "settlementBalanceKind": (
                            prepared.settlement_balance_kind.value
                        ),
                        "amount": format(prepared.amount.amount, "f"),
                        "eventFactSha256": prepared.event_fact_sha256,
                        "evidenceDigest": prepared.evidence_digest,
                    },
                    separators=(",", ":"),
                ),
            ),
        )
        if result is None:
            raise InvestmentsError.unavailable()
        return _recorded_cash_settlement(result)

    async def get_investment_correction_replay(
        self, command: CorrectInvestmentCommand
    ) -> RecordedInvestmentCorrection | None:
        result = await self._investment_result(
            "select investments.get_correction_replay_v1(%s::jsonb, %s::text) as result",
            command,
        )
        return _recorded_correction(result) if result is not None else None

    async def prepare_investment_correction(
        self,
        command: CorrectInvestmentCommand,
        *,
        evidence_digest: str,
    ) -> PreparedInvestmentCorrection:
        result = await self._investment_result(
            "select investments.prepare_correction_v1(%s::jsonb, %s::text) as result",
            command,
            request_extra={"evidenceDigest": evidence_digest},
        )
        if result is None:
            raise InvestmentsError.unavailable()
        return PreparedInvestmentCorrection(
            original_accounting_entry_id=AccountingEntryReference(
                str(result["originalAccountingEntryId"])
            ),
            original_position_id=InvestmentPositionId(
                str(result["originalPositionId"])
            ),
            evidence_digest=evidence_digest,
        )

    async def complete_investment_correction(
        self,
        command: CorrectInvestmentCommand,
        *,
        prepared: PreparedInvestmentCorrection,
        replacement: RecordedSharePurchase | RecordedShareSale
        | RecordedReceivedDividend | RecordedReceivedFundDistribution,
    ) -> RecordedInvestmentCorrection:
        rows = await self._database_rows(
            """
            select ledger.link_investment_correction_v1(
              %s::uuid, %s::integer, %s::uuid, %s::uuid, %s::uuid,
              %s::uuid, %s::text, %s::text, %s::date, %s::text
            ) as reversal_entry_id
            """,
            (
                str(command.company_id),
                int(command.income_year),
                str(prepared.original_accounting_entry_id),
                str(replacement.accounting_entry_id),
                str(command.original_action_id),
                str(replacement.action_id),
                command.reason,
                str(command.correlation_id),
                command.correction_date.value,
                str(command.actor_id.subject),
            ),
        )
        if len(rows) != 1 or rows[0].get("reversal_entry_id") is None:
            raise InvestmentsError.unavailable()
        reversal_entry_id = str(rows[0]["reversal_entry_id"])
        result = await self._investment_result(
            """
            select investments.complete_correction_v1(
              %s::jsonb, %s::uuid, %s::uuid, %s::uuid, %s::text
            ) as result
            """,
            command,
            (
                str(prepared.original_accounting_entry_id),
                str(replacement.accounting_entry_id),
                reversal_entry_id,
            ),
            request_extra={"evidenceDigest": prepared.evidence_digest},
        )
        if result is None:
            raise InvestmentsError.unavailable()
        return _recorded_correction(result)

    async def get_received_fund_distribution_replay(
        self, command: RecordReceivedFundDistributionCommand
    ) -> RecordedReceivedFundDistribution | None:
        result = await self._investment_result(
            "select investments.get_received_fund_distribution_replay_v1(%s::jsonb, %s::text) as result",
            command,
        )
        return _recorded_fund_distribution(result) if result is not None else None

    async def prepare_received_fund_distribution(
        self,
        command: RecordReceivedFundDistributionCommand,
        *,
        evidence_digest: str,
    ) -> PreparedReceivedFundDistributionFacts:
        result = await self._investment_result(
            "select investments.prepare_received_fund_distribution_v1(%s::jsonb, %s::text) as result",
            command,
            request_extra={"evidenceDigest": evidence_digest},
        )
        if result is None:
            raise InvestmentsError.unavailable()
        return PreparedReceivedFundDistributionFacts(
            position_id=InvestmentPositionId(str(result["positionId"])),
            investment_name=str(result["investmentName"]),
            investment_kind=InvestmentKind(str(result["investmentKind"])),
        )

    async def complete_received_fund_distribution(
        self,
        command: RecordReceivedFundDistributionCommand,
        *,
        prepared: PreparedReceivedFundDistribution,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedReceivedFundDistribution:
        result = await self._investment_result(
            """
            select investments.complete_received_fund_distribution_v1(
              %s::jsonb, %s::uuid, %s::text
            ) as result
            """,
            command,
            (str(accounting_entry_id),),
            request_extra={
                "dividendPortion": format(prepared.dividend_portion.amount, "f"),
                "interestPortion": format(prepared.interest_portion.amount, "f"),
                "taxableAddBack": format(prepared.taxable_add_back.amount, "f"),
                "totalTaxableIncome": format(
                    prepared.total_taxable_income.amount, "f"
                ),
                "evidenceDigest": prepared.evidence_digest,
                "calculationId": prepared.calculation_id,
            },
        )
        if result is None:
            raise InvestmentsError.unavailable()
        return _recorded_fund_distribution(result)

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
        evidence_digest: str,
    ) -> PreparedReceivedDividendFacts:
        result = await self._investment_result(
            "select investments.prepare_received_dividend_v1(%s::jsonb, %s::text) as result",
            command,
            request_extra={
                "evidenceDigest": evidence_digest,
            },
        )
        if result is None:
            raise InvestmentsError.unavailable()
        return PreparedReceivedDividendFacts(
            position_id=InvestmentPositionId(str(result["positionId"])),
            investment_name=str(result["investmentName"]),
            investment_kind=InvestmentKind(str(result["investmentKind"])),
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
                "taxableAddBack": format(prepared.taxable_add_back.amount, "f"),
                "groupExceptionApplied": prepared.group_exception_applied,
                "evidenceDigest": prepared.evidence_digest,
                "calculationId": prepared.calculation_id,
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
        self,
        command: RecordSharePurchaseCommand,
        *,
        capitalized_cost: Money,
        evidence_digest: str,
        calculation_id: str,
    ) -> PreparedSharePurchase:
        result = await self._investment_result(
            "select investments.prepare_share_purchase_v1(%s::jsonb, %s::text) as result",
            command,
            request_extra={
                "capitalizedCost": format(capitalized_cost.amount, "f"),
                "evidenceDigest": evidence_digest,
                "calculationId": calculation_id,
            },
        )
        if result is None:
            raise InvestmentsError.unavailable()
        return PreparedSharePurchase(
            position_id=InvestmentPositionId(str(result["positionId"])),
            lot_id=AcquisitionLotId(str(result["lotId"])),
            position_created=bool(result["positionCreated"]),
            investment_name=str(result["investmentName"]),
            accounting_classification=InvestmentAccountingClassification(
                str(result["accountingClassification"])
            ),
            purchase_amount=_money(result["capitalizedCost"]),
            evidence_digest=str(result["evidenceDigest"]),
            calculation_id=str(result["calculationId"]),
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
                        "capitalizedCost": format(
                            prepared.purchase_amount.amount, "f"
                        ),
                        "evidenceDigest": prepared.evidence_digest,
                        "calculationId": prepared.calculation_id,
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
        self,
        command: RecordShareSaleCommand,
        *,
        net_proceeds: Money,
        evidence_digest: str,
    ) -> PreparedShareSaleFacts:
        result = await self._investment_result(
            "select investments.prepare_share_sale_v1(%s::jsonb, %s::text) as result",
            command,
            request_extra={
                "netProceeds": format(net_proceeds.amount, "f"),
                "evidenceDigest": evidence_digest,
            },
        )
        if result is None:
            raise InvestmentsError.unavailable()
        lot_facts_value = result.get("lotFacts")
        if not isinstance(lot_facts_value, list):
            raise InvestmentsError.unavailable()
        return PreparedShareSaleFacts(
            position_id=InvestmentPositionId(str(result["positionId"])),
            investment_name=str(result["investmentName"]),
            investment_kind=InvestmentKind(str(result["investmentKind"])),
            accounting_classification=InvestmentAccountingClassification(
                str(result["accountingClassification"])
            ),
            fifo_book_cost_basis_reduction=_money(
                result["fifoBookCostBasisReduction"]
            ),
            fifo_tax_basis_reduction=_money(
                result["fifoTaxBasisReduction"]
            ),
            lot_facts=tuple(
                InvestmentSaleLotFact(
                    lot_id=AcquisitionLotId(str(value["lotId"])),
                    allocation_order=int(value["allocationOrder"]),
                    acquisition_date=LocalDate(value["acquisitionDate"]),
                    allocated_share_count=int(value["allocatedShareCount"]),
                    allocated_book_cost_basis=_money(
                        value["allocatedBookCostBasis"]
                    ),
                    allocated_tax_basis=_money(value["allocatedTaxBasis"]),
                    acquisition_year_fund_equity_ratio_basis_points=(
                        int(value["acquisitionYearFundEquityRatioBasisPoints"])
                        if value.get(
                            "acquisitionYearFundEquityRatioBasisPoints"
                        )
                        is not None
                        else None
                    ),
                )
                for value in lot_facts_value
                if isinstance(value, Mapping)
            ),
        )

    async def complete_share_sale(
        self,
        command: RecordShareSaleCommand,
        *,
        prepared: PreparedShareSale,
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
            request_extra={
                "bookGainOrLoss": format(prepared.book_gain_or_loss.amount, "f"),
                "taxGainOrLoss": format(prepared.tax_gain_or_loss.amount, "f"),
                "exemptGain": format(prepared.exempt_gain.amount, "f"),
                "taxableGain": format(prepared.taxable_gain.amount, "f"),
                "nonDeductibleLoss": format(
                    prepared.non_deductible_loss.amount, "f"
                ),
                "deductibleLoss": format(prepared.deductible_loss.amount, "f"),
                "evidenceDigest": prepared.evidence_digest,
                "calculationId": prepared.calculation_id,
                "lotCalculations": [
                    {
                        "lotId": str(value.lot_id),
                        "allocationOrder": value.allocation_order,
                        "allocatedNetProceeds": format(
                            value.allocated_net_proceeds.amount, "f"
                        ),
                        "taxGainOrLoss": format(value.tax_gain_or_loss.amount, "f"),
                        "averageFundEquityRatioBasisPoints": (
                            format(
                                value.average_fund_equity_ratio_basis_points,
                                "f",
                            )
                            if value.average_fund_equity_ratio_basis_points
                            is not None
                            else None
                        ),
                        "exemptGain": format(value.exempt_gain.amount, "f"),
                        "taxableGain": format(value.taxable_gain.amount, "f"),
                        "nonDeductibleLoss": format(
                            value.non_deductible_loss.amount, "f"
                        ),
                        "deductibleLoss": format(
                            value.deductible_loss.amount, "f"
                        ),
                    }
                    for value in prepared.lot_calculations
                ],
            },
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


def _recorded_economic_event(
    value: Mapping[str, object],
) -> RecordedInvestmentEconomicEvent:
    return RecordedInvestmentEconomicEvent(
        event_id=InvestmentEconomicEventId(str(value["eventId"])),
        position_id=InvestmentPositionId(str(value["positionId"])),
        recognition_accounting_entry_id=AccountingEntryReference(
            str(value["recognitionAccountingEntryId"])
        ),
        expected_settlement_amount=_money(value["expectedSettlementAmount"]),
        settlement_balance_kind=InvestmentSettlementBalanceKind(
            str(value["settlementBalanceKind"])
        ),
        replayed=bool(value["replayed"]),
    )


def _recorded_cash_settlement(
    value: Mapping[str, object],
) -> RecordedInvestmentCashSettlement:
    return RecordedInvestmentCashSettlement(
        settlement_id=InvestmentSettlementId(str(value["settlementId"])),
        event_id=InvestmentEconomicEventId(str(value["eventId"])),
        settlement_accounting_entry_id=AccountingEntryReference(
            str(value["settlementAccountingEntryId"])
        ),
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


def _recorded_fund_distribution(
    value: Mapping[str, object],
) -> RecordedReceivedFundDistribution:
    return RecordedReceivedFundDistribution(
        action_id=InvestmentActionId(str(value["actionId"])),
        position_id=InvestmentPositionId(str(value["positionId"])),
        accounting_entry_id=AccountingEntryReference(str(value["accountingEntryId"])),
        dividend_portion=_money(value["dividendPortion"]),
        interest_portion=_money(value["interestPortion"]),
        taxable_add_back=_money(value["taxableAddBack"]),
        total_taxable_income=_money(value["totalTaxableIncome"]),
        replayed=bool(value["replayed"]),
    )


def _recorded_sale(value: Mapping[str, object]) -> RecordedShareSale:
    return RecordedShareSale(
        action_id=InvestmentActionId(str(value["actionId"])),
        position_id=InvestmentPositionId(str(value["positionId"])),
        accounting_entry_id=AccountingEntryReference(str(value["accountingEntryId"])),
        replayed=bool(value["replayed"]),
    )


def _recorded_correction(
    value: Mapping[str, object],
) -> RecordedInvestmentCorrection:
    return RecordedInvestmentCorrection(
        correction_id=InvestmentCorrectionId(str(value["correctionId"])),
        original_action_id=InvestmentActionId(str(value["originalActionId"])),
        replacement_action_id=InvestmentActionId(
            str(value["replacementActionId"])
        ),
        reversal_accounting_entry_id=AccountingEntryReference(
            str(value["reversalAccountingEntryId"])
        ),
        replacement_accounting_entry_id=AccountingEntryReference(
            str(value["replacementAccountingEntryId"])
        ),
        replayed=bool(value["replayed"]),
    )


def _correction(value: Mapping[str, object]) -> InvestmentCorrectionView:
    return InvestmentCorrectionView(
        correction_id=InvestmentCorrectionId(str(value["id"])),
        company_id=CompanyId(str(value["company_id"])),
        income_year=IncomeYear(int(value["income_year"])),
        original_action_id=InvestmentActionId(str(value["original_action_id"])),
        original_activity_kind=InvestmentActivityKind(
            str(value["original_activity_kind"])
        ),
        reversal_accounting_entry_id=AccountingEntryReference(
            str(value["reversal_accounting_entry_id"])
        ),
        replacement_action_id=InvestmentActionId(
            str(value["replacement_action_id"])
        ),
        replacement_activity_kind=InvestmentActivityKind(
            str(value["replacement_activity_kind"])
        ),
        replacement_accounting_entry_id=AccountingEntryReference(
            str(value["replacement_accounting_entry_id"])
        ),
        reason=str(value["reason"]),
        bank_transaction_id=(
            InvestmentSourceReference(str(value["bank_transaction_id"]))
            if value["bank_transaction_id"] else None
        ),
        document_id=(
            InvestmentSourceReference(str(value["document_id"]))
            if value["document_id"] else None
        ),
        document_status=InvestmentDocumentStatus(str(value["document_status"])),
        evidence_mode=InvestmentEvidenceMode(str(value["evidence_mode"])),
        evidence_reference=str(value["evidence_reference"]),
        evidence_digest=str(value["evidence_digest"]),
        owner_attested=bool(value["owner_attested"]),
        created_by=_actor(value["created_by"]),
        created_at=_timestamp(value["created_at"]),
    )


def _position(value: Mapping[str, object]) -> InvestmentPositionView:
    return InvestmentPositionView(
        position_id=InvestmentPositionId(str(value["id"])),
        company_id=CompanyId(str(value["company_id"])),
        investment_key=str(value["investment_key"]),
        name=str(value["name"]),
        kind=InvestmentKind(str(value["kind"])),
        accounting_classification=InvestmentAccountingClassification(
            str(value["accounting_classification"])
        ),
        tax_treatment=InvestmentTaxTreatment(str(value["tax_treatment"])),
        org_number=str(value["org_number"]) if value["org_number"] else None,
        fund_equity_ratio_basis_points=(
            int(value["fund_equity_ratio_basis_points"])
            if value["fund_equity_ratio_basis_points"] is not None
            else None
        ),
        fund_tax_statement_reference=(
            str(value["fund_tax_statement_reference"])
            if value["fund_tax_statement_reference"] is not None
            else None
        ),
        share_count=int(value["share_count"]),
        cost_basis=_money(value["cost_basis"]),
        tax_basis=_money(value["tax_basis"]),
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
        original_tax_basis=_money(value["original_tax_basis"]),
        remaining_tax_basis=_money(value["remaining_tax_basis"]),
        acquisition_year_fund_equity_ratio_basis_points=(
            int(value["acquisition_year_fund_equity_ratio_basis_points"])
            if value["acquisition_year_fund_equity_ratio_basis_points"] is not None
            else None
        ),
        fund_tax_statement_reference=(
            str(value["fund_tax_statement_reference"])
            if value["fund_tax_statement_reference"] is not None
            else None
        ),
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
        accounting_classification=InvestmentAccountingClassification(
            str(value["accounting_classification"])
        ),
        tax_treatment=InvestmentTaxTreatment(str(value["tax_treatment"])),
        org_number=str(value["org_number"]) if value["org_number"] else None,
        fund_equity_ratio_basis_points=(
            int(value["fund_equity_ratio_basis_points"])
            if value["fund_equity_ratio_basis_points"] is not None
            else None
        ),
        fund_tax_statement_reference=(
            str(value["fund_tax_statement_reference"])
            if value["fund_tax_statement_reference"] is not None
            else None
        ),
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
        transaction_costs=(
            _money(value["transaction_costs"])
            if value["transaction_costs"] is not None
            else None
        ),
        capitalized_cost=(
            _money(value["capitalized_cost"])
            if value["capitalized_cost"] is not None
            else None
        ),
        sold_share_count=(
            int(value["sold_share_count"])
            if value["sold_share_count"] is not None
            else None
        ),
        proceeds=_money(value["proceeds"]) if value["proceeds"] is not None else None,
        net_proceeds=(
            _money(value["net_proceeds"])
            if value["net_proceeds"] is not None
            else None
        ),
        fifo_cost_basis_reduction=(
            _money(value["fifo_cost_basis_reduction"])
            if value["fifo_cost_basis_reduction"] is not None
            else None
        ),
        fifo_tax_basis_reduction=(
            _money(value["fifo_tax_basis_reduction"])
            if value["fifo_tax_basis_reduction"] is not None
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
        remaining_tax_basis=(
            _money(value["remaining_tax_basis"])
            if value["remaining_tax_basis"] is not None
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
        book_gain_or_loss=(
            _money(value["book_gain_or_loss"])
            if value["book_gain_or_loss"] is not None else None
        ),
        tax_gain_or_loss=(
            _money(value["tax_gain_or_loss"])
            if value["tax_gain_or_loss"] is not None else None
        ),
        exempt_gain=(
            _money(value["exempt_gain"])
            if value["exempt_gain"] is not None else None
        ),
        taxable_gain=(
            _money(value["taxable_gain"])
            if value["taxable_gain"] is not None else None
        ),
        non_deductible_loss=(
            _money(value["non_deductible_loss"])
            if value["non_deductible_loss"] is not None else None
        ),
        deductible_loss=(
            _money(value["deductible_loss"])
            if value["deductible_loss"] is not None else None
        ),
        lawful_dividend_confirmed=(
            bool(value["lawful_dividend_confirmed"])
            if value["lawful_dividend_confirmed"] is not None else None
        ),
        group_exception_claimed=(
            bool(value["group_exception_claimed"])
            if value["group_exception_claimed"] is not None else None
        ),
        group_exception_applied=(
            bool(value["group_exception_applied"])
            if value["group_exception_applied"] is not None else None
        ),
        year_end_ownership_basis_points=(
            int(value["year_end_ownership_basis_points"])
            if value["year_end_ownership_basis_points"] is not None else None
        ),
        year_end_voting_basis_points=(
            int(value["year_end_voting_basis_points"])
            if value["year_end_voting_basis_points"] is not None else None
        ),
        group_evidence_reference=(
            str(value["group_evidence_reference"])
            if value["group_evidence_reference"] is not None else None
        ),
        fund_name=(
            str(value["fund_name"]) if value["fund_name"] is not None else None
        ),
        entitlement_date=(
            LocalDate(value["entitlement_date"])
            if value["entitlement_date"] is not None else None
        ),
        opening_fund_equity_ratio_basis_points=(
            int(value["opening_fund_equity_ratio_basis_points"])
            if value["opening_fund_equity_ratio_basis_points"] is not None
            else None
        ),
        dividend_portion=(
            _money(value["dividend_portion"])
            if value["dividend_portion"] is not None else None
        ),
        interest_portion=(
            _money(value["interest_portion"])
            if value["interest_portion"] is not None else None
        ),
        total_taxable_income=(
            _money(value["total_taxable_income"])
            if value["total_taxable_income"] is not None else None
        ),
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
        evidence_mode=InvestmentEvidenceMode(str(value["evidence_mode"])),
        evidence_reference=str(value["evidence_reference"]),
        evidence_digest=str(value["evidence_digest"]),
        calculation_id=str(value["calculation_id"]),
        owner_attested=bool(value["owner_attested"]),
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
        allocated_book_cost_basis=_money(value["allocated_book_cost_basis"]),
        allocated_tax_basis=_money(value["allocated_tax_basis"]),
        allocated_net_proceeds=_money(value["allocated_net_proceeds"]),
        average_fund_equity_ratio_basis_points=(
            Decimal(str(value["average_fund_equity_ratio_basis_points"]))
            if value["average_fund_equity_ratio_basis_points"] is not None
            else None
        ),
        tax_gain_or_loss=_money(value["tax_gain_or_loss"]),
        exempt_gain=_money(value["exempt_gain"]),
        taxable_gain=_money(value["taxable_gain"]),
        non_deductible_loss=_money(value["non_deductible_loss"]),
        deductible_loss=_money(value["deductible_loss"]),
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
