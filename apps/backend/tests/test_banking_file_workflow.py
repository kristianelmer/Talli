from __future__ import annotations

import asyncio
from datetime import date

from talli_backend.application.banking_file import BankingFileWorkflow
from talli_backend.modules.banking.public import (
    AcceptBankFileCommand,
    BankAccountId,
    BankFileColumnMapping,
    BankFilePreviewCommand,
    BankSourceFileId,
    BankStatementImportResult,
    PersistedBankFilePreview,
    SupportedBankDataFormat,
)
from talli_backend.shared.kernel import (
    ActorId,
    ActorKind,
    CompanyId,
    CorrelationId,
    IdempotencyKey,
    IncomeYear,
    UserId,
)


COMPANY_ID = CompanyId("10000000-0000-0000-0000-000000000001")
ACTOR_ID = ActorId(ActorKind.USER, UserId("20000000-0000-0000-0000-000000000002"))
ACCOUNT_ID = BankAccountId("30000000-0000-0000-0000-000000000003")
SOURCE_FILE_ID = BankSourceFileId("40000000-0000-0000-0000-000000000004")


class PersistenceStub:
    def __init__(self) -> None:
        self.preview = None
        self.accepted = None

    async def persist_file_preview(self, command, preview):
        self.preview = (command, preview)
        return PersistedBankFilePreview(SOURCE_FILE_ID, preview, False)

    async def accept_file(self, command):
        self.accepted = command
        return BankStatementImportResult(1, 0, (), False)


def metadata() -> dict[str, object]:
    return {
        "company_id": COMPANY_ID,
        "actor_id": ACTOR_ID,
        "correlation_id": CorrelationId("file-workflow"),
        "idempotency_key": IdempotencyKey("50000000-0000-4000-8000-000000000005"),
        "income_year": IncomeYear(2026),
    }


def test_file_fallback_persists_exact_preview_before_explicit_acceptance() -> None:
    persistence = PersistenceStub()
    workflow = BankingFileWorkflow(persistence)
    preview_command = BankFilePreviewCommand(
        **metadata(),
        source_file_id=SOURCE_FILE_ID,
        account_id=ACCOUNT_ID,
        data_format=SupportedBankDataFormat.CSV,
        filename="statement.csv",
        content="date,text,amount\n2026-01-02,Annual fee,-89\n",
        column_mapping=BankFileColumnMapping(
            booking_date="date",
            value_date=None,
            text="text",
            amount="amount",
            balance=None,
            reference=None,
            state=None,
        ),
    )

    receipt = asyncio.run(workflow.preview(preview_command))
    result = asyncio.run(
        workflow.accept(
            AcceptBankFileCommand(
                **metadata(),
                source_file_id=SOURCE_FILE_ID,
                document_sha256=receipt.preview.document_sha256,
            )
        )
    )

    assert persistence.preview is not None
    assert persistence.preview[1].interval_start.value == date(2026, 1, 2)
    assert persistence.accepted.document_sha256 == receipt.preview.document_sha256
    assert result.imported_count == 1
