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


def historical_query(document=None):
    from talli_backend.modules.documents.public import RetainedDocumentOriginalQuery, document_metadata_sha256
    document = document or record(DocumentStatus.ATTACHED)
    return RetainedDocumentOriginalQuery(document.document_id, document.company_id, document.income_year,
        document_metadata_sha256(document), document.content_sha256, document.byte_length)


def historical_snapshot():
    from datetime import UTC, datetime
    from talli_backend.modules.documents.public import RetainedDocumentOriginal, RetainedDocumentOriginalReceipt, RetainedDocumentOriginalSnapshot
    document = record(DocumentStatus.ATTACHED)
    query = historical_query(document)
    receipt = RetainedDocumentOriginalReceipt('40000000-0000-4000-8000-000000000001', query.document_id,
        query.company_id, query.source_income_year, query.metadata_sha256, query.content_sha256,
        query.byte_length, datetime(2026, 9, 28, tzinfo=UTC))
    return RetainedDocumentOriginalSnapshot(document, RetainedDocumentOriginal(receipt, PDF))


class HistoricalPersistence(Persistence):
    def __init__(self, *, roles=('owner', 'owner'), aal2=True, result=None):
        super().__init__(aal2=aal2)
        self.roles = iter(roles)
        self.result = result or historical_snapshot()
        self.reads = 0

    async def refresh_actor_role(self, company_id):
        return next(self.roles)

    async def read_retained_evidence(self, query):
        self.reads += 1
        return self.result

    async def get_document(self, document_id):
        pytest.fail('Historical recovery must not require mutable document metadata')


class UnavailableStorage(Storage):
    async def read_object(self, **kwargs):
        pytest.fail('Historical recovery must not read a mutable bucket object')


def test_historical_recovery_returns_exact_captured_metadata_and_bytes_without_current_original():
    persistence = HistoricalPersistence()
    recovered = asyncio.run(DocumentsService(persistence, UnavailableStorage()).read_retained_evidence(historical_query()))
    assert recovered == historical_snapshot()
    assert persistence.reads == 1


@pytest.mark.parametrize('roles,aal2,code,reads', [
    ((None,), True, 'DOCUMENT_FORBIDDEN', 0),
    (('accountant',), True, 'DOCUMENT_FORBIDDEN', 0),
    (('owner', None), True, 'DOCUMENT_FORBIDDEN', 1),
    (('owner',), False, 'DOCUMENT_STEP_UP_REQUIRED', 0),
])
def test_historical_recovery_requires_live_owner_and_step_up(roles, aal2, code, reads):
    persistence = HistoricalPersistence(roles=roles, aal2=aal2)
    with pytest.raises(DocumentsError) as caught:
        asyncio.run(DocumentsService(persistence, UnavailableStorage()).read_retained_evidence(historical_query()))
    assert caught.value.code == code
    assert persistence.reads == reads


@pytest.mark.parametrize('kind', ['bytes', 'metadata', 'year', 'receipt-hash', 'receipt-company', 'receipt-length'])
def test_historical_recovery_rejects_unbound_adapter_output(kind):
    from test_documents import TARGET_COMPANY_ID
    from talli_backend.shared.kernel import IncomeYear
    result = historical_snapshot()
    if kind == 'bytes':
        result = replace(result, original=replace(result.original, content=b'changed'))
    elif kind == 'metadata':
        result = replace(result, document=replace(result.document, name='Changed.pdf'))
    elif kind == 'year':
        result = replace(result, document=replace(result.document, income_year=IncomeYear(2024)))
    else:
        field, value = {'receipt-hash': ('metadata_sha256', 'f'*64),
                        'receipt-company': ('company_id', TARGET_COMPANY_ID),
                        'receipt-length': ('byte_length', 1)}[kind]
        result = replace(result, original=replace(result.original, receipt=replace(result.original.receipt, **{field: value})))
    with pytest.raises(DocumentsError) as caught:
        asyncio.run(DocumentsService(HistoricalPersistence(result=result), UnavailableStorage()).read_retained_evidence(historical_query()))
    assert caught.value.code == 'DOCUMENT_INTEGRITY_FAILED'


@pytest.mark.parametrize('field,value', [
    ('metadata_sha256', 'A'*64), ('metadata_sha256', None), ('content_sha256', 'f'*63),
    ('byte_length', 0), ('byte_length', 10485761), ('byte_length', True),
    ('byte_length', 1.0), ('source_income_year', 2025), ('document_id', 'arbitrary'), ('company_id', 'arbitrary'),
])
def test_historical_query_rejects_invalid_identity_or_commitment(field, value):
    with pytest.raises(DocumentsError):
        replace(historical_query(), **{field: value})


@pytest.mark.parametrize('status', [TransactionStatus.IDLE, TransactionStatus.INERROR, TransactionStatus.UNKNOWN])
def test_historical_adapter_requires_live_transaction(status):
    adapter = PostgresDocumentOriginals(SimpleNamespace(info=SimpleNamespace(transaction_status=status)), ACTOR)
    with pytest.raises(DocumentsError):
        asyncio.run(adapter.read_retained_evidence(historical_query()))


@pytest.mark.parametrize('change', [None, 'document', 'receipt', 'content', 'missing', 'timestamp'])
def test_historical_adapter_checks_database_response_commitments(change):
    result = historical_snapshot()
    document = result.document
    receipt = result.original.receipt
    row = {'document': {
        'id': str(document.document_id), 'company_id': str(document.company_id), 'income_year': int(document.income_year),
        'document_type': document.document_type, 'name': document.name, 'linked_to': document.linked_to,
        'status': document.status.value, 'retention_years': document.retention_years, 'storage_key': document.storage_key,
        'content_type': document.content_type, 'byte_length': document.byte_length, 'content_sha256': document.content_sha256,
        'created_by': str(document.created_by.subject), 'created_at': document.created_at.isoformat(),
        'removed_at': None, 'removal_reason': None,
    }, 'receipt': {
        'originalId': receipt.original_id, 'documentId': str(receipt.document_id), 'companyId': str(receipt.company_id),
        'sourceIncomeYear': int(receipt.source_income_year), 'metadataSha256': receipt.metadata_sha256,
        'contentSha256': receipt.content_sha256, 'byteLength': receipt.byte_length, 'retainedAt': receipt.retained_at.isoformat(),
    }, 'content': PDF}
    if change == 'document': row['document']['name'] = 'Changed.pdf'
    if change == 'receipt': row['receipt']['metadataSha256'] = 'f'*64
    if change == 'content': row['content'] = b'changed'
    if change == 'timestamp': row['document']['created_at'] = None
    if change == 'missing': row = None
    class Connection:
        info = SimpleNamespace(transaction_status=TransactionStatus.INTRANS)
        async def execute(self, statement, parameters):
            assert statement.startswith('select * from documents.read_retained_evidence_v1(')
            assert parameters[-1] == str(ACTOR.subject)
            return self
        async def fetchone(self):
            return row
    adapter = PostgresDocumentOriginals(Connection(), ACTOR)
    if change is None:
        assert asyncio.run(adapter.read_retained_evidence(historical_query())) == result
    else:
        with pytest.raises(DocumentsError) as caught:
            asyncio.run(adapter.read_retained_evidence(historical_query()))
        assert caught.value.code == ('DOCUMENT_NOT_FOUND' if change == 'missing' else 'DOCUMENT_INTEGRITY_FAILED')
