"""Retained original bytes are distinct from current metadata or filing authority."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest
from psycopg.pq import TransactionStatus

from talli_backend.adapters.postgres_document_originals import PostgresDocumentOriginals
from talli_backend.modules.documents.public import DocumentsError, DocumentStatus
from talli_backend.modules.documents.service import DocumentsService
from test_documents import ACTOR, DOCUMENT_ID, PDF, Persistence, Storage, record


def test_verification_returns_immutable_copy_receipt_without_filing_reference():
    persistence=Persistence();persistence.current=record(DocumentStatus.ATTACHED)
    storage=Storage();service=DocumentsService(persistence,storage)
    evidence=asyncio.run(service.verify_document_evidence(DOCUMENT_ID))
    storage.content=b'replacement bytes'
    assert persistence.retained_content==PDF
    assert evidence.retained_original.content_sha256==evidence.content_sha256
    assert evidence.retained_original.byte_length==len(PDF)
    assert persistence.linked is False
    with pytest.raises(DocumentsError):asyncio.run(service.verify_document_evidence(DOCUMENT_ID))
    assert persistence.retained_content==PDF


@pytest.mark.parametrize('field,value',[('content_sha256','e'*64),('byte_length',2),('metadata_sha256','f'*64)])
def test_unbound_retention_receipt_cannot_be_returned_as_verified_evidence(field,value):
    class Incorrect(Persistence):
        async def retain_verified_original(self,document,content):
            return replace(await super().retain_verified_original(document,content),**{field:value})
    persistence=Incorrect();persistence.current=record(DocumentStatus.ATTACHED)
    with pytest.raises(DocumentsError,match='Document integrity'):
        asyncio.run(DocumentsService(persistence,Storage()).verify_document_evidence(DOCUMENT_ID))


def test_owner_revoked_at_retention_cannot_return_verified_evidence():
    class Revoked(Persistence):
        async def retain_verified_original(self,document,content):
            raise DocumentsError.forbidden()
    persistence=Revoked();persistence.current=record(DocumentStatus.ATTACHED)
    with pytest.raises(DocumentsError) as caught:
        asyncio.run(DocumentsService(persistence,Storage()).verify_document_evidence(DOCUMENT_ID))
    assert caught.value.code=='DOCUMENT_FORBIDDEN'


@pytest.mark.parametrize('status',[TransactionStatus.IDLE,TransactionStatus.INERROR,TransactionStatus.UNKNOWN])
def test_original_adapter_requires_callers_live_transaction(status):
    connection=SimpleNamespace(info=SimpleNamespace(transaction_status=status))
    adapter=PostgresDocumentOriginals(connection,ACTOR)
    with pytest.raises(DocumentsError):
        asyncio.run(adapter.retain_verified_original(record(DocumentStatus.ATTACHED),PDF))
