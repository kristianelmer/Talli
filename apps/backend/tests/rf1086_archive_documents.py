"""Synthetic original whose retained metadata/bytes match archived RF source facts."""
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from talli_backend.modules.documents.public import (
    DocumentId, DocumentRecord, DocumentStatus, RetainedDocumentOriginal, RetainedDocumentOriginalReceipt,
    RetainedDocumentOriginalSnapshot, document_metadata_sha256,
)
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import IncomeYear
from test_rf1086_year_source import COMPANY, ACTOR, DOCUMENT, NOW

CONTENT = b'%PDF-1.7\nretained RF shareholder evidence\x00\xff'


def document():
    return DocumentRecord(DocumentId(DOCUMENT), COMPANY, IncomeYear(2024), 'shareholder_source', 'Source.pdf',
        'workspace', DocumentStatus.STORED, 10, f'{COMPANY}/2024/{DOCUMENT}/Source.pdf', 'application/pdf',
        len(CONTENT), sha256(CONTENT).hexdigest(), ACTOR, NOW, None, None)


def evidence():
    d = document()
    return rf.Rf1086YearDocumentEvidence(DOCUMENT, COMPANY, d.content_sha256, d.content_sha256, d.document_type,
        d.status.value, d.byte_length, d.created_at, document_metadata_sha256(d), d.income_year)


def retained():
    d = document()
    receipt = RetainedDocumentOriginalReceipt(str(UUID(int=810)), d.document_id, COMPANY, d.income_year,
        document_metadata_sha256(d), d.content_sha256, d.byte_length, NOW)
    return RetainedDocumentOriginalSnapshot(d, RetainedDocumentOriginal(receipt, CONTENT))


class Documents:
    actor_id = ACTOR
    async def read_retained_evidence(self, query):
        return retained()


class DocumentsFactory:
    async def session(self, token):
        assert token == 'token'
        return Documents()
