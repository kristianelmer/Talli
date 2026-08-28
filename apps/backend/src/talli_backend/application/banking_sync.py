"""Durable external-I/O workflow for provider-neutral bank transaction sync."""

from __future__ import annotations

from talli_backend.modules.banking.public import (
    BankDataProvider,
    BankSyncCommand,
    BankSyncMode,
    BankSyncPersistence,
    BankSyncResult,
    BankingError,
    BankingErrorCode,
    FetchBankTransactionsRequest,
)
from talli_backend.modules.banking.service import BankingService


class BankingSyncWorkflow:
    def __init__(
        self,
        persistence: BankSyncPersistence,
        provider: BankDataProvider,
    ) -> None:
        self._persistence = persistence
        self._provider = provider

    async def sync(self, command: BankSyncCommand) -> BankSyncResult:
        context = await self._persistence.prepare_sync(command)
        if context.replayed_result is not None:
            return context.replayed_result
        if context.connector_id != self._provider.connector_id:
            await self._persistence.fail_sync(
                command,
                context=context,
                error_code=BankingErrorCode.PROVIDER_RESPONSE_INVALID.value,
            )
            raise BankingError.invalid_input(BankingErrorCode.PROVIDER_RESPONSE_INVALID)
        cursor = context.resume_cursor
        seen_cursors: set[str] = set()
        pages = 0
        imported_count = 0
        updated_count = 0
        duplicate_count = 0
        try:
            while True:
                if pages >= 1000 or (cursor is not None and cursor in seen_cursors):
                    raise BankingError.invalid_input(BankingErrorCode.PROVIDER_RESPONSE_INVALID)
                if cursor is not None:
                    seen_cursors.add(cursor)
                provider_page = await self._provider.fetch_transactions(
                    FetchBankTransactionsRequest(
                        connection_id=command.connection_id,
                        company_id=command.company_id,
                        adapter_connection_reference=context.adapter_connection_reference,
                        adapter_account_reference=context.adapter_account_reference,
                        date_from=command.date_from,
                        date_to=command.date_to,
                        cursor=cursor,
                        mode=command.mode,
                        owner_present=command.mode
                        in {
                            BankSyncMode.INITIAL_BACKFILL,
                            BankSyncMode.ON_DEMAND,
                            BankSyncMode.ANNUAL_CLOSE,
                        },
                    )
                )
                normalized = BankingService.normalize_provider_transactions(
                    command.account_id,
                    provider_page.transactions,
                )
                page_result = await self._persistence.apply_sync_page(
                    command,
                    context=context,
                    transactions=normalized,
                    next_cursor=provider_page.next_cursor,
                )
                pages += 1
                imported_count += page_result.imported_count
                updated_count += page_result.updated_count
                duplicate_count += page_result.duplicate_count
                cursor = provider_page.next_cursor
                if cursor is None:
                    break
        except BankingError as error:
            await self._persistence.fail_sync(
                command,
                context=context,
                error_code=error.code,
            )
            raise
        return await self._persistence.complete_sync(
            command,
            context=context,
            pages=pages,
            imported_count=imported_count,
            updated_count=updated_count,
            duplicate_count=duplicate_count,
        )


__all__ = ["BankingSyncWorkflow"]
