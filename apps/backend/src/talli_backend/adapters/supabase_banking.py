"""Verified-actor PostgreSQL adapter for the banking capability."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime

import psycopg
from psycopg.rows import dict_row

from talli_backend.adapters.supabase_ledger import (
    LedgerSupabaseConfiguration,
    SupabaseLedgerAdapter,
    SupabaseLedgerWorkflowTransaction,
    _VerifiedActor,
)
from talli_backend.application.banking_session import (
    BankingAuthenticationError,
    BankingSessionFactory,
)
from talli_backend.application.banking_workflow import BankingApplication
from talli_backend.application.ledger_session import LedgerAuthenticationError
from talli_backend.modules.banking.public import (
    AcceptBankSuggestionCommand,
    AcceptedBankSuggestion,
    AccountingEntryReference,
    BankStatementImportResult,
    BankSuggestion,
    BankSuggestionAcceptanceId,
    BankSuggestionAcceptancePage,
    BankSuggestionKind,
    BankTransaction,
    BankTransactionId,
    BankTransactionPage,
    BankingCursor,
    BankingError,
    BankingErrorCode,
    BankingPage,
    BankingPersistence,
    ExternalActionReference,
    ImportBankStatementCommand,
    ImportedBankTransaction,
    PreparedBankSuggestion,
    banking_persistence_adapter,
)
from talli_backend.modules.ledger.service import LedgerService
from talli_backend.shared.kernel import (
    ActorId,
    ActorKind,
    CompanyId,
    CorrelationId,
    IncomeYear,
    LocalDate,
    Money,
    Timestamp,
    UserId,
)


@dataclass(frozen=True)
class BankingSupabaseConfiguration(LedgerSupabaseConfiguration):
    """Banking-specific environment binding for the shared verified-actor client."""


def _actor(value: object) -> ActorId:
    return ActorId(ActorKind.USER, UserId(str(value)))


def _timestamp(value: object) -> Timestamp:
    return Timestamp(datetime.fromisoformat(str(value).replace("Z", "+00:00")))


def _banking_error(message: str) -> BankingError:
    definitions = (
        (
            "banking_statement_invalid",
            BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID),
        ),
        (
            "banking_invalid_cursor",
            BankingError.invalid_input(BankingErrorCode.INVALID_CURSOR),
        ),
        (
            "banking_invalid_input",
            BankingError.invalid_input(BankingErrorCode.INVALID_INPUT),
        ),
        (
            "banking_company_year_not_admitted",
            BankingError.precondition_failed(
                BankingErrorCode.COMPANY_YEAR_NOT_ADMITTED
            ),
        ),
        ("banking_transaction_not_found", BankingError.not_found()),
        (
            "banking_transaction_already_reconciled",
            BankingError.conflict(BankingErrorCode.TRANSACTION_ALREADY_RECONCILED),
        ),
        (
            "banking_suggestion_acceptance_conflict",
            BankingError.conflict(BankingErrorCode.SUGGESTION_ACCEPTANCE_CONFLICT),
        ),
        (
            "banking_idempotency_key_reused",
            BankingError.conflict(BankingErrorCode.IDEMPOTENCY_KEY_REUSED),
        ),
        (
            "banking_idempotency_in_progress",
            BankingError.conflict(BankingErrorCode.IDEMPOTENCY_IN_PROGRESS),
        ),
        ("banking_forbidden", BankingError.forbidden()),
    )
    for marker, error in definitions:
        if marker in message:
            return error
    return BankingError.unavailable()


def _command_payload(command: AcceptBankSuggestionCommand) -> dict[str, object]:
    return {
        "companyId": str(command.company_id),
        "incomeYear": int(command.income_year),
        "acceptanceId": str(command.acceptance_id),
        "bankTransactionId": str(command.bank_transaction_id),
        "expectedSuggestion": command.expected_suggestion.value,
        "expectedRuleVersion": command.expected_rule_version,
        "idempotencyKey": str(command.idempotency_key),
        "correlationId": str(command.correlation_id),
    }


class _BankingOperations:
    actor_id: ActorId

    async def _banking_rows(
        self, query: str, parameters: tuple[object, ...]
    ) -> list[Mapping[str, object]]:
        raise NotImplementedError

    async def import_transactions(
        self,
        command: ImportBankStatementCommand,
        *,
        transactions: tuple[ImportedBankTransaction, ...],
    ) -> BankStatementImportResult:
        if command.actor_id != self.actor_id:
            raise BankingError.forbidden()
        request = {
            "companyId": str(command.company_id),
            "incomeYear": int(command.income_year),
            "idempotencyKey": str(command.idempotency_key),
            "correlationId": str(command.correlation_id),
            "transactions": [
                {
                    "transactionDate": item.transaction_date.value.isoformat(),
                    "text": item.text,
                    "amount": str(item.amount.amount),
                    "balance": str(item.balance.amount) if item.balance else None,
                    "sourceHash": item.source_hash,
                }
                for item in transactions
            ],
        }
        rows = await self._banking_rows(
            "select banking.import_statement_v1(%s::jsonb, %s::text) as result",
            (json.dumps(request, separators=(",", ":")), str(self.actor_id.subject)),
        )
        if len(rows) != 1 or not isinstance(rows[0].get("result"), Mapping):
            raise BankingError.unavailable()
        result = rows[0]["result"]
        return BankStatementImportResult(
            imported_count=int(result["importedCount"]),
            duplicate_count=int(result["duplicateCount"]),
            transactions=(),
            replayed=bool(result.get("replayed")),
        )

    @staticmethod
    def _transaction(value: Mapping[str, object]) -> BankTransaction:
        matched = value.get("matchedEntryId")
        action = value.get("matchedActionReference")
        return BankTransaction(
            transaction_id=BankTransactionId(str(value["transactionId"])),
            company_id=CompanyId(str(value["companyId"])),
            income_year=IncomeYear(int(value["incomeYear"])),
            transaction_date=LocalDate(
                date.fromisoformat(str(value["transactionDate"]))
            ),
            text=str(value["text"]),
            amount=Money.nok(str(value["amount"])),
            balance=(
                Money.nok(str(value["balance"]))
                if value.get("balance") is not None
                else None
            ),
            source_hash=str(value["sourceHash"]),
            matched_entry_id=AccountingEntryReference(str(matched)) if matched else None,
            matched_action_reference=(
                ExternalActionReference(str(action)) if action else None
            ),
            warning_accepted=bool(value.get("warningAccepted")),
            suggestion=None,
            created_at=_timestamp(value["createdAt"]),
        )

    @staticmethod
    def _acceptance(value: Mapping[str, object]) -> AcceptedBankSuggestion:
        suggestion = BankSuggestion(
            kind=BankSuggestionKind(str(value["suggestionKind"])),
            rule_version=str(value["ruleVersion"]),
            reason=str(value["reason"]),
        )
        return AcceptedBankSuggestion(
            acceptance_id=BankSuggestionAcceptanceId(str(value["acceptanceId"])),
            bank_transaction_id=BankTransactionId(str(value["bankTransactionId"])),
            accounting_entry_id=AccountingEntryReference(str(value["accountingEntryId"])),
            suggestion=suggestion,
            accepted_by=_actor(value["acceptedBy"]),
            accepted_at=_timestamp(value["acceptedAt"]),
            replayed=bool(value.get("replayed")),
        )

    async def get_suggestion_acceptance_replay(self, command: AcceptBankSuggestionCommand):
        rows = await self._banking_rows(
            "select banking.suggestion_acceptance_replay_v1(%s::jsonb, %s::text) as result",
            (
                json.dumps(_command_payload(command), separators=(",", ":")),
                str(self.actor_id.subject),
            ),
        )
        result = rows[0].get("result") if len(rows) == 1 else None
        if result is None:
            return None
        if not isinstance(result, Mapping):
            raise BankingError.unavailable()
        return self._acceptance(result)

    async def get_transaction_for_acceptance(self, command: AcceptBankSuggestionCommand):
        rows = await self._banking_rows(
            "select banking.prepare_suggestion_acceptance_v1(%s::jsonb, %s::text) as result",
            (
                json.dumps(_command_payload(command), separators=(",", ":")),
                str(self.actor_id.subject),
            ),
        )
        result = rows[0].get("result") if len(rows) == 1 else None
        if not isinstance(result, Mapping):
            raise BankingError.unavailable()
        return self._transaction(result)

    async def complete_suggestion_acceptance(
        self,
        command,
        *,
        prepared,
        accounting_entry_id,
    ):
        rows = await self._banking_rows(
            "select banking.complete_suggestion_acceptance_v1("
            "%s::jsonb, %s::uuid, %s::text, %s::text) as result",
            (
                json.dumps(_command_payload(command), separators=(",", ":")),
                str(accounting_entry_id),
                prepared.suggestion.reason,
                str(self.actor_id.subject),
            ),
        )
        result = rows[0].get("result") if len(rows) == 1 else None
        if not isinstance(result, Mapping):
            raise BankingError.unavailable()
        return self._acceptance(result)

    async def _list(self, resource, company_ids, cursor, limit):
        rows = await self._banking_rows(
            "select * from banking.list_records_v1(%s::text, %s::uuid[], %s::text, %s::integer, %s::text)",
            (
                resource,
                [str(item) for item in company_ids],
                str(cursor) if cursor else None,
                limit,
                str(self.actor_id.subject),
            ),
        )
        if len(rows) != 1 or not isinstance(rows[0].get("items"), list):
            raise BankingError.unavailable()
        return rows[0]

    async def list_transactions(
        self, *, actor_id, company_ids, correlation_id, cursor, limit
    ):
        _ = correlation_id
        if actor_id != self.actor_id:
            raise BankingError.forbidden()
        row = await self._list("transactions", company_ids, cursor, limit)
        return BankTransactionPage(
            items=tuple(self._transaction(item) for item in row["items"]),
            page=BankingPage(
                BankingCursor(str(row["next_cursor"]))
                if row.get("next_cursor")
                else None,
                bool(row.get("has_more")),
            ),
        )

    async def list_suggestion_acceptances(
        self, *, actor_id, company_ids, correlation_id, cursor, limit
    ):
        _ = correlation_id
        if actor_id != self.actor_id:
            raise BankingError.forbidden()
        row = await self._list("suggestion_acceptances", company_ids, cursor, limit)
        return BankSuggestionAcceptancePage(
            items=tuple(self._acceptance(item) for item in row["items"]),
            page=BankingPage(
                BankingCursor(str(row["next_cursor"]))
                if row.get("next_cursor")
                else None,
                bool(row.get("has_more")),
            ),
        )


@banking_persistence_adapter(BankingPersistence)
class SupabaseBankingSession(_BankingOperations):
    def __init__(self, database_url: str, verified: _VerifiedActor) -> None:
        self._database_url = database_url
        self._verified = verified
        self.actor_id = verified.actor_id

    async def _banking_rows(self, query, parameters):
        if not self._database_url:
            raise BankingError.unavailable()
        try:
            async with await psycopg.AsyncConnection.connect(
                self._database_url,
                connect_timeout=5,
                row_factory=dict_row,
            ) as connection, connection.transaction():
                await connection.execute("set local role banking_executor")
                await connection.execute(
                    "select pg_catalog.set_config("
                    "'talli.verified_actor_id', %s, true)",
                    (str(self.actor_id.subject),),
                )
                await connection.execute(
                    "select pg_catalog.set_config('talli.verified_actor_claims', %s, true)",
                    (self._verified.claims_json,),
                )
                cursor = await connection.execute(query, parameters)
                return list(await cursor.fetchall())
        except BankingError:
            raise
        except psycopg.OperationalError:
            raise BankingError.unavailable() from None
        except psycopg.DatabaseError as error:
            raise _banking_error(str(error)) from None

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[SupabaseBankingWorkflowTransaction]:
        if not self._database_url:
            raise BankingError.unavailable()
        try:
            async with await psycopg.AsyncConnection.connect(
                self._database_url,
                connect_timeout=5,
                row_factory=dict_row,
            ) as connection, connection.transaction():
                await connection.execute("set local role banking_workflow_executor")
                await connection.execute(
                    "select pg_catalog.set_config('talli.verified_actor_id', %s, true)",
                    (str(self.actor_id.subject),),
                )
                await connection.execute(
                    "select pg_catalog.set_config('talli.verified_actor_claims', %s, true)",
                    (self._verified.claims_json,),
                )
                yield SupabaseBankingWorkflowTransaction(
                    self._database_url,
                    self._verified,
                    connection,
                )
        except BankingError:
            raise
        except psycopg.OperationalError:
            raise BankingError.unavailable() from None
        except psycopg.DatabaseError as error:
            raise _banking_error(str(error)) from None


class SupabaseBankingWorkflowTransaction(_BankingOperations, SupabaseLedgerWorkflowTransaction):
    async def _banking_rows(self, query, parameters):
        try:
            cursor = await self._connection.execute(query, parameters)
            return list(await cursor.fetchall())
        except psycopg.OperationalError:
            raise BankingError.unavailable() from None
        except psycopg.DatabaseError as error:
            raise _banking_error(str(error)) from None


class SupabaseBankingAdapter(SupabaseLedgerAdapter):
    @classmethod
    def from_environment(cls):
        return cls(
            BankingSupabaseConfiguration(
                url=os.environ.get("SUPABASE_URL", ""),
                anon_key=os.environ.get("SUPABASE_ANON_KEY", ""),
                database_url=os.environ.get(
                    "TALLI_BANKING_DATABASE_URL",
                    os.environ.get("TALLI_LEDGER_DATABASE_URL", ""),
                ),
            )
        )

    async def session(self, access_token: str) -> SupabaseBankingSession:
        try:
            verified = await self._verified_actor(access_token)
        except LedgerAuthenticationError:
            raise BankingAuthenticationError from None
        return SupabaseBankingSession(self._configuration.database_url, verified)


def compose_banking_application(
    sessions: BankingSessionFactory | None = None,
) -> BankingApplication:
    """Bind banking and ledger implementations outside the transport seam."""

    return BankingApplication(
        sessions or SupabaseBankingAdapter.from_environment(),
        LedgerService,
    )


__all__ = [
    "BankingSupabaseConfiguration",
    "SupabaseBankingAdapter",
    "SupabaseBankingSession",
    "compose_banking_application",
]
