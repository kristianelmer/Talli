"""Documents-owned retention using the caller's already authenticated transaction."""
from psycopg.pq import TransactionStatus

from talli_backend.adapters.supabase_documents import _document
from talli_backend.modules.documents.public import (
    DocumentEvidenceRetentionCommand, DocumentEvidenceRetentionPersistence,
    DocumentsError, document_evidence_retention_adapter, document_metadata_sha256,
)
from talli_backend.shared.kernel import ActorId


@document_evidence_retention_adapter(DocumentEvidenceRetentionPersistence)
class PostgresDocumentEvidenceRetention(DocumentEvidenceRetentionPersistence):
    def __init__(self, connection, actor_id: ActorId):
        self._connection = connection
        self._actor_id = actor_id

    async def retain_verified_evidence(self, command: DocumentEvidenceRetentionCommand) -> None:
        if self._connection.info.transaction_status != TransactionStatus.INTRANS:
            raise DocumentsError.conflict()
        # The SQL function locks the original and returns its complete row. This
        # adapter never reads the Documents table from the caller's capability.
        row = await (await self._connection.execute(
            "select * from documents.retain_verified_rf_evidence_v1("
            "%s,%s::uuid,%s::uuid,%s::uuid,%s,%s,%s,%s,%s,%s::uuid)",
            (command.source_record_type, command.source_record_id, command.document_id.value,
             str(command.company_id), int(command.source_income_year), str(command.status),
             command.content_sha256, command.byte_length, command.metadata_sha256,
             str(self._actor_id.subject)),
        )).fetchone()
        try:
            actual = document_metadata_sha256(_document(row)) if row else None
        except (KeyError, TypeError, ValueError, DocumentsError):
            actual = None
        # A SQL error poisons the transaction even if an outer caller mistakenly
        # catches the exception. A Python-only mismatch could accidentally commit
        # the already inserted reference and a caller's subsequent source writes.
        await self._connection.execute(
            "select documents.assert_retained_metadata_v1(%s,%s)",
            (actual, command.metadata_sha256),
        )
