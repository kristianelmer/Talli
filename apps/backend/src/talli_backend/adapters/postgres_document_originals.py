"""Documents-owned immutable originals, bound to an existing verified transaction."""
from datetime import datetime
from hashlib import sha256
from uuid import UUID

from psycopg.pq import TransactionStatus

from talli_backend.adapters.supabase_documents import _document
from talli_backend.modules.documents.public import (
    DocumentId, DocumentOriginalPersistence, DocumentsError, RetainedDocumentOriginal,
    RetainedDocumentOriginalReceipt, document_metadata_sha256, document_original_persistence_adapter,
)
from talli_backend.shared.kernel import ActorId, CompanyId, IncomeYear


def _receipt(value):
    try:
        result = RetainedDocumentOriginalReceipt(str(UUID(value['originalId'])), DocumentId(value['documentId']),
            CompanyId(value['companyId']), IncomeYear(value['sourceIncomeYear']), value['metadataSha256'],
            value['contentSha256'], value['byteLength'], datetime.fromisoformat(value['retainedAt']))
        if result.retained_at.tzinfo is None or not 0 < result.byte_length <= 10485760:
            raise ValueError()
        return result
    except (KeyError, TypeError, ValueError):
        raise DocumentsError.storage_unavailable() from None


def _metadata(value):
    if not isinstance(value, dict):
        return None
    try:
        row = dict(value)
        for key in ('created_at', 'removed_at'):
            if row.get(key) is not None:
                row[key] = datetime.fromisoformat(row[key])
        return document_metadata_sha256(_document(row))
    except (KeyError, TypeError, ValueError, DocumentsError):
        return None


@document_original_persistence_adapter(DocumentOriginalPersistence)
class PostgresDocumentOriginals(DocumentOriginalPersistence):
    def __init__(self, connection, actor_id: ActorId):
        self._connection = connection
        self._actor_id = actor_id

    def _require_transaction(self):
        if self._connection.info.transaction_status != TransactionStatus.INTRANS:
            raise DocumentsError.conflict()

    async def retain_verified_original(self, document, content):
        self._require_transaction()
        metadata = document_metadata_sha256(document)
        row = await (await self._connection.execute(
            'select documents.retain_original_v1(%s::uuid,%s::uuid,%s,%s,%s,%s,%s) as result',
            (document.document_id.value, str(document.company_id), metadata, document.content_sha256,
             document.byte_length, content, str(self._actor_id.subject)),
        )).fetchone()
        value = row['result'] if row else None
        await self._connection.execute('select documents.assert_retained_metadata_v1(%s,%s)',
            (_metadata(value.get('document')) if isinstance(value, dict) else None, metadata))
        return _receipt(value['receipt'])

    async def read_retained_original(self, original_id, company_id):
        self._require_transaction()
        row = await (await self._connection.execute(
            'select * from documents.read_retained_original_v1(%s::uuid,%s::uuid,%s)',
            (original_id, str(company_id), str(self._actor_id.subject)),
        )).fetchone()
        if row is None:
            raise DocumentsError.not_found()
        receipt = _receipt(row['receipt'])
        content = bytes(row['content'])
        if (receipt.original_id != original_id or receipt.company_id != company_id
                or len(content) != receipt.byte_length or sha256(content).hexdigest() != receipt.content_sha256):
            raise DocumentsError.integrity_failed()
        return RetainedDocumentOriginal(receipt, content)

    async def assert_retained_original(self, receipt):
        self._require_transaction()
        row = await (await self._connection.execute(
            'select documents.assert_retained_original_v1(%s::uuid,%s::uuid,%s::uuid,%s,%s,%s,%s,%s,%s) as document',
            (receipt.original_id, receipt.document_id.value, str(receipt.company_id), int(receipt.source_income_year),
             receipt.metadata_sha256, receipt.content_sha256, receipt.byte_length, receipt.retained_at, str(self._actor_id.subject)),
        )).fetchone()
        await self._connection.execute('select documents.assert_retained_metadata_v1(%s,%s)',
            (_metadata(row['document']) if row else None, receipt.metadata_sha256))
