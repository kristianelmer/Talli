"""Durable preview-first orchestration for bank file fallbacks."""

from __future__ import annotations

from talli_backend.modules.banking.public import (
    AcceptBankFileCommand,
    BankFilePersistence,
    BankFilePreviewCommand,
    BankStatementImportResult,
    PersistedBankFilePreview,
)
from talli_backend.modules.banking.service import BankingService


class BankingFileWorkflow:
    def __init__(self, persistence: BankFilePersistence) -> None:
        self._persistence = persistence

    async def preview(self, command: BankFilePreviewCommand) -> PersistedBankFilePreview:
        preview = BankingService.preview_file(command)
        return await self._persistence.persist_file_preview(command, preview)

    async def accept(self, command: AcceptBankFileCommand) -> BankStatementImportResult:
        return await self._persistence.accept_file(command)


__all__ = ["BankingFileWorkflow"]
