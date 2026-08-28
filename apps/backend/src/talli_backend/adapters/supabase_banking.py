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
    AcceptBankFileCommand,
    AcceptedBankSuggestion,
    AccountingEntryReference,
    BankAccount,
    BankAccountId,
    BankAccountStatus,
    BankConnection,
    BankConnectionList,
    BankConnectionId,
    BankConnectionStatus,
    BankConnectorId,
    BankConsentRedirect,
    BankFilePreview,
    BankFilePreviewCommand,
    BankProviderConnection,
    BankStatementImportResult,
    BankSuggestion,
    BankSuggestionAcceptanceId,
    BankSuggestionAcceptancePage,
    BankSuggestionKind,
    BankTransaction,
    BankTransactionId,
    BankTransactionPage,
    BankSyncAttemptId,
    BankSyncCommand,
    BankSyncContext,
    BankSyncPageResult,
    BankSyncResult,
    BankSourceFileId,
    BankingCursor,
    BankingError,
    BankingErrorCode,
    BankingPage,
    BankingPersistence,
    ExternalActionReference,
    CompleteBankConnectionCommand,
    ImportBankStatementCommand,
    ImportedBankTransaction,
    PreparedBankSuggestion,
    PersistedBankFilePreview,
    RevokeBankConnectionCommand,
    StartBankConnectionCommand,
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

    encryption_key: str = ""


def _actor(value: object) -> ActorId:
    return ActorId(ActorKind.USER, UserId(str(value)))


def _timestamp(value: object) -> Timestamp:
    return Timestamp(datetime.fromisoformat(str(value).replace("Z", "+00:00")))


def _optional_timestamp(value: object) -> Timestamp | None:
    return _timestamp(value) if value is not None else None


def _optional_date(value: object) -> LocalDate | None:
    return LocalDate(date.fromisoformat(str(value))) if value else None


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
        (
            "banking_consent_callback_invalid",
            BankingError.invalid_input(BankingErrorCode.CONSENT_CALLBACK_INVALID),
        ),
        (
            "banking_provider_response_invalid",
            BankingError.invalid_input(BankingErrorCode.PROVIDER_RESPONSE_INVALID),
        ),
        (
            "banking_connection_not_available",
            BankingError.precondition_failed(BankingErrorCode.CONSENT_EXPIRED),
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


def _connection_payload(
    command: StartBankConnectionCommand | CompleteBankConnectionCommand,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "companyId": str(command.company_id),
        "incomeYear": int(command.income_year),
        "connectionId": str(command.connection_id),
        "idempotencyKey": str(command.idempotency_key),
        "correlationId": str(command.correlation_id),
    }
    if isinstance(command, StartBankConnectionCommand):
        payload.update(
            connectorId=str(command.connector_id),
            bankKey=command.bank_key,
        )
    else:
        payload["callbackState"] = (
            command.callback_parameters.get("state")
            or command.callback_parameters.get("resource_id")
            or ""
        )
    return payload


def _sync_payload(command: BankSyncCommand) -> dict[str, object]:
    return {
        "companyId": str(command.company_id),
        "incomeYear": int(command.income_year),
        "connectionId": str(command.connection_id),
        "accountId": str(command.account_id),
        "dateFrom": command.date_from.value.isoformat(),
        "dateTo": command.date_to.value.isoformat(),
        "mode": command.mode.value,
        "idempotencyKey": str(command.idempotency_key),
        "correlationId": str(command.correlation_id),
    }


def _file_payload(
    command: BankFilePreviewCommand | AcceptBankFileCommand,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "companyId": str(command.company_id),
        "incomeYear": int(command.income_year),
        "sourceFileId": str(command.source_file_id),
        "idempotencyKey": str(command.idempotency_key),
        "correlationId": str(command.correlation_id),
    }
    if isinstance(command, BankFilePreviewCommand):
        payload.update(
            accountId=str(command.account_id),
            dataFormat=command.data_format.value,
            filename=command.filename,
        )
    else:
        payload["documentSha256"] = command.document_sha256
    return payload


class _BankingOperations:
    actor_id: ActorId

    async def _banking_rows(
        self, query: str, parameters: tuple[object, ...]
    ) -> list[Mapping[str, object]]:
        raise NotImplementedError

    def _require_actor(self, actor_id: ActorId) -> None:
        if actor_id != self.actor_id:
            raise BankingError.forbidden()

    @staticmethod
    def _result(rows: list[Mapping[str, object]]) -> Mapping[str, object]:
        result = rows[0].get("result") if len(rows) == 1 else None
        if not isinstance(result, Mapping):
            raise BankingError.unavailable()
        return result

    @staticmethod
    def _connection(value: Mapping[str, object]) -> BankConnection:
        raw_accounts = value.get("accounts")
        if not isinstance(raw_accounts, list):
            raise BankingError.unavailable()
        connection_id = BankConnectionId(str(value["connectionId"]))
        accounts = tuple(
            BankAccount(
                account_id=BankAccountId(str(item["accountId"])),
                connection_id=connection_id,
                masked_account=str(item["maskedAccount"]),
                currency=str(item["currency"]),
                account_kind=str(item["accountKind"]),
                display_name=str(item.get("displayName") or ""),
                status=BankAccountStatus(str(item["status"])),
                earliest_covered_date=_optional_date(item.get("earliestCoveredDate")),
                latest_covered_date=_optional_date(item.get("latestCoveredDate")),
                last_success_at=_optional_timestamp(item.get("lastSuccessAt")),
            )
            for item in raw_accounts
            if isinstance(item, Mapping)
        )
        if len(accounts) != len(raw_accounts):
            raise BankingError.unavailable()
        return BankConnection(
            connection_id=connection_id,
            company_id=CompanyId(str(value["companyId"])),
            connector_id=BankConnectorId(str(value["connectorId"])),
            status=BankConnectionStatus(str(value["status"])),
            consent_expires_on=_optional_date(value.get("consentExpiresOn")),
            accounts=accounts,
            last_success_at=_optional_timestamp(value.get("lastSuccessAt")),
            last_failure_code=(
                str(value["lastFailureCode"])
                if value.get("lastFailureCode") is not None
                else None
            ),
        )

    async def begin_connection(self, command: StartBankConnectionCommand) -> None:
        self._require_actor(command.actor_id)
        await self._banking_rows(
            "select banking.begin_connection_v1(%s::jsonb, %s::text) as result",
            (
                json.dumps(_connection_payload(command), separators=(",", ":")),
                str(self.actor_id.subject),
            ),
        )

    async def get_connection_completion_replay(
        self,
        command: CompleteBankConnectionCommand,
    ) -> BankConnection | None:
        self._require_actor(command.actor_id)
        connections = await self.list_connections(
            actor_id=command.actor_id,
            company_id=command.company_id,
            correlation_id=command.correlation_id,
        )
        return next(
            (
                connection
                for connection in connections.items
                if connection.connection_id == command.connection_id
                and connection.status is BankConnectionStatus.ACTIVE
            ),
            None,
        )

    async def list_connections(
        self,
        *,
        actor_id: ActorId,
        company_id: CompanyId,
        correlation_id: CorrelationId,
    ) -> BankConnectionList:
        _ = correlation_id
        self._require_actor(actor_id)
        rows = await self._banking_rows(
            "select banking.list_connections_v1("
            "%s::uuid, %s::text) as result",
            (str(company_id), str(self.actor_id.subject)),
        )
        result = rows[0].get("result") if len(rows) == 1 else None
        if not isinstance(result, list):
            raise BankingError.unavailable()
        return BankConnectionList(
            tuple(
                self._connection(item)
                for item in result
                if isinstance(item, Mapping)
            )
        )

    async def record_consent_redirect(
        self,
        command: StartBankConnectionCommand,
        redirect: BankConsentRedirect,
    ) -> BankConsentRedirect:
        self._require_actor(command.actor_id)
        await self._banking_rows(
            "select banking.record_consent_redirect_v1("
            "%s::uuid, %s::uuid, %s::text, %s::text)",
            (
                str(command.connection_id),
                str(command.company_id),
                redirect.state,
                str(self.actor_id.subject),
            ),
        )
        return redirect

    async def complete_connection(
        self,
        command: CompleteBankConnectionCommand,
        provider_connection: BankProviderConnection,
    ) -> BankConnection:
        self._require_actor(command.actor_id)
        provider_payload = {
            "connectorId": str(provider_connection.connector_id),
            "adapterConnectionReference": (
                provider_connection.adapter_connection_reference
            ),
            "consentExpiresOn": (
                provider_connection.consent_expires_on.value.isoformat()
                if provider_connection.consent_expires_on
                else None
            ),
            "accounts": [
                {
                    "adapterReference": item.adapter_account_reference,
                    "maskedAccount": item.masked_account,
                    "currency": item.currency,
                    "accountKind": item.account_kind,
                    "displayName": item.display_name,
                }
                for item in provider_connection.accounts
            ],
        }
        rows = await self._provider_rows(
            "select banking.complete_connection_v1("
            "%s::jsonb, %s::jsonb, %s::text, %s::text) as result",
            (
                json.dumps(_connection_payload(command), separators=(",", ":")),
                json.dumps(provider_payload, separators=(",", ":")),
                str(self.actor_id.subject),
                self._encryption_key,
            ),
        )
        return self._connection(self._result(rows))

    async def fail_connection(
        self,
        command: StartBankConnectionCommand | CompleteBankConnectionCommand,
        *,
        error_code: str,
    ) -> None:
        self._require_actor(command.actor_id)
        await self._banking_rows(
            "select banking.fail_connection_v1("
            "%s::uuid, %s::uuid, %s::text, %s::text)",
            (
                str(command.connection_id),
                str(command.company_id),
                error_code,
                str(self.actor_id.subject),
            ),
        )

    async def begin_revocation(self, command: RevokeBankConnectionCommand) -> str:
        self._require_actor(command.actor_id)
        rows = await self._provider_rows(
            "select banking.begin_connection_revocation_v1("
            "%s::uuid, %s::uuid, %s::text, %s::text) as result",
            (
                str(command.connection_id),
                str(command.company_id),
                str(self.actor_id.subject),
                self._encryption_key,
            ),
        )
        result = rows[0].get("result") if len(rows) == 1 else None
        if not isinstance(result, str) or not result:
            raise BankingError.unavailable()
        return result

    async def complete_revocation(self, command: RevokeBankConnectionCommand) -> None:
        self._require_actor(command.actor_id)
        await self._banking_rows(
            "select banking.complete_connection_revocation_v1("
            "%s::uuid, %s::uuid, %s::text)",
            (
                str(command.connection_id),
                str(command.company_id),
                str(self.actor_id.subject),
            ),
        )

    async def prepare_sync(self, command: BankSyncCommand) -> BankSyncContext:
        self._require_actor(command.actor_id)
        rows = await self._provider_rows(
            "select banking.prepare_sync_v1("
            "%s::jsonb, %s::text, %s::text) as result",
            (
                json.dumps(_sync_payload(command), separators=(",", ":")),
                str(self.actor_id.subject),
                self._encryption_key,
            ),
        )
        result = self._result(rows)
        replayed_result = None
        if bool(result.get("replayed")):
            replayed_result = BankSyncResult(
                attempt_id=BankSyncAttemptId(str(result["attemptId"])),
                page_count=int(result["pageCount"]),
                imported_count=int(result["importedCount"]),
                updated_count=int(result["updatedCount"]),
                duplicate_count=int(result["duplicateCount"]),
                replayed=True,
            )
        return BankSyncContext(
            attempt_id=BankSyncAttemptId(str(result["attemptId"])),
            connector_id=BankConnectorId(str(result["connectorId"])),
            adapter_connection_reference=str(
                result["adapterConnectionReference"]
            ),
            adapter_account_reference=str(result["adapterAccountReference"]),
            resume_cursor=(
                str(result["resumeCursor"])
                if result.get("resumeCursor") is not None
                else None
            ),
            replayed_result=replayed_result,
        )

    async def apply_sync_page(
        self,
        command: BankSyncCommand,
        *,
        context: BankSyncContext,
        transactions: tuple[ImportedBankTransaction, ...],
        next_cursor: str | None,
    ) -> BankSyncPageResult:
        self._require_actor(command.actor_id)
        page = [
            {
                "transactionDate": item.transaction_date.value.isoformat(),
                "valueDate": item.value_date.value.isoformat()
                if item.value_date
                else None,
                "text": item.text,
                "amount": str(item.amount.amount),
                "balance": str(item.balance.amount) if item.balance else None,
                "sourceHash": item.source_hash,
                "state": item.state.value,
                "adapterReference": item.adapter_transaction_reference,
            }
            for item in transactions
        ]
        rows = await self._provider_rows(
            "select banking.apply_sync_page_v1("
            "%s::jsonb, %s::uuid, %s::jsonb, %s::text, %s::text, %s::text) as result",
            (
                json.dumps(_sync_payload(command), separators=(",", ":")),
                str(context.attempt_id),
                json.dumps(page, separators=(",", ":")),
                next_cursor,
                str(self.actor_id.subject),
                self._encryption_key,
            ),
        )
        result = self._result(rows)
        return BankSyncPageResult(
            imported_count=int(result["importedCount"]),
            updated_count=int(result["updatedCount"]),
            duplicate_count=int(result["duplicateCount"]),
        )

    async def complete_sync(
        self,
        command: BankSyncCommand,
        *,
        context: BankSyncContext,
        pages: int,
        imported_count: int,
        updated_count: int,
        duplicate_count: int,
    ) -> BankSyncResult:
        self._require_actor(command.actor_id)
        _ = pages, imported_count, updated_count, duplicate_count
        rows = await self._banking_rows(
            "select banking.complete_sync_v1("
            "%s::jsonb, %s::uuid, %s::text) as result",
            (
                json.dumps(_sync_payload(command), separators=(",", ":")),
                str(context.attempt_id),
                str(self.actor_id.subject),
            ),
        )
        result = self._result(rows)
        return BankSyncResult(
            attempt_id=BankSyncAttemptId(str(result["attemptId"])),
            page_count=int(result["pageCount"]),
            imported_count=int(result["importedCount"]),
            updated_count=int(result["updatedCount"]),
            duplicate_count=int(result["duplicateCount"]),
            replayed=bool(result.get("replayed")),
        )

    async def fail_sync(
        self,
        command: BankSyncCommand,
        *,
        context: BankSyncContext,
        error_code: str,
    ) -> None:
        self._require_actor(command.actor_id)
        await self._banking_rows(
            "select banking.fail_sync_v1("
            "%s::jsonb, %s::uuid, %s::text, %s::text)",
            (
                json.dumps(_sync_payload(command), separators=(",", ":")),
                str(context.attempt_id),
                error_code,
                str(self.actor_id.subject),
            ),
        )

    async def persist_file_preview(
        self,
        command: BankFilePreviewCommand,
        preview: BankFilePreview,
    ) -> PersistedBankFilePreview:
        self._require_actor(command.actor_id)
        preview_payload = {
            "documentSha256": preview.document_sha256,
            "accountMask": preview.account_mask,
            "intervalStart": preview.interval_start.value.isoformat(),
            "intervalEnd": preview.interval_end.value.isoformat(),
            "currency": preview.currency,
            "openingBalance": str(preview.opening_balance.amount)
            if preview.opening_balance
            else None,
            "closingBalance": str(preview.closing_balance.amount)
            if preview.closing_balance
            else None,
            "transactionCount": preview.transaction_count,
            "duplicateCount": preview.duplicate_count,
            "correctionCount": preview.correction_count,
            "ignoredCount": preview.ignored_count,
            "transactions": [
                {
                    "transactionDate": item.transaction_date.value.isoformat(),
                    "valueDate": item.value_date.value.isoformat()
                    if item.value_date
                    else None,
                    "text": item.text,
                    "amount": str(item.amount.amount),
                    "balance": str(item.balance.amount) if item.balance else None,
                    "sourceHash": item.source_hash,
                    "state": item.state.value,
                }
                for item in preview.transactions
            ],
        }
        rows = await self._provider_rows(
            "select banking.preview_source_file_v1("
            "%s::jsonb, %s::jsonb, %s::text, %s::text, %s::text) as result",
            (
                json.dumps(_file_payload(command), separators=(",", ":")),
                json.dumps(preview_payload, separators=(",", ":")),
                command.content,
                str(self.actor_id.subject),
                self._encryption_key,
            ),
        )
        result = self._result(rows)
        return PersistedBankFilePreview(
            source_file_id=BankSourceFileId(str(result["sourceFileId"])),
            preview=preview,
            replayed=bool(result.get("replayed")),
        )

    async def accept_file(
        self,
        command: AcceptBankFileCommand,
    ) -> BankStatementImportResult:
        self._require_actor(command.actor_id)
        rows = await self._banking_rows(
            "select banking.accept_source_file_v1("
            "%s::jsonb, %s::text) as result",
            (
                json.dumps(_file_payload(command), separators=(",", ":")),
                str(self.actor_id.subject),
            ),
        )
        result = self._result(rows)
        return BankStatementImportResult(
            imported_count=int(result["importedCount"]),
            duplicate_count=int(result["duplicateCount"]),
            transactions=(),
            replayed=bool(result.get("replayed")),
        )

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
    def __init__(
        self,
        database_url: str,
        verified: _VerifiedActor,
        encryption_key: str = "",
    ) -> None:
        self._database_url = database_url
        self._verified = verified
        self._encryption_key = encryption_key
        self.actor_id = verified.actor_id

    async def _banking_rows(self, query, parameters):
        return await self._rows_with_role("banking_executor", query, parameters)

    async def _provider_rows(self, query, parameters):
        if not self._encryption_key:
            raise BankingError.unavailable()
        return await self._rows_with_role(
            "banking_provider_executor", query, parameters
        )

    async def _rows_with_role(self, role, query, parameters):
        if not self._database_url:
            raise BankingError.unavailable()
        if role not in {"banking_executor", "banking_provider_executor"}:
            raise BankingError.unavailable()
        try:
            async with await psycopg.AsyncConnection.connect(
                self._database_url,
                connect_timeout=5,
                row_factory=dict_row,
            ) as connection, connection.transaction():
                await connection.execute(f"set local role {role}")
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
                encryption_key=os.environ.get("TALLI_BANKING_ENCRYPTION_KEY", ""),
            )
        )

    async def session(self, access_token: str) -> SupabaseBankingSession:
        try:
            verified = await self._verified_actor(access_token)
        except LedgerAuthenticationError:
            raise BankingAuthenticationError from None
        return SupabaseBankingSession(
            self._configuration.database_url,
            verified,
            self._configuration.encryption_key,
        )


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
