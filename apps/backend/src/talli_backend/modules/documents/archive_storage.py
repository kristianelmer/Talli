"""Portable immutable originals; verifies evidence, never authenticates or restores it."""
from base64 import b64decode, b64encode
from dataclasses import fields
from datetime import datetime
from hashlib import sha256
import json
from uuid import UUID

from .evidence import metadata_text
from .public import (
    DocumentId, DocumentRecord, DocumentStatus, DocumentsError, RetainedDocumentOriginal,
    RetainedDocumentOriginalQuery, RetainedDocumentOriginalReceipt, RetainedDocumentOriginalSnapshot,
)
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, UserId

CODEC = 'documents-retained-original-v1'
MAX_RECORD_BYTES = 16 * 1024 * 1024


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError()
        result[key] = value
    return result


def _validate(snapshot, query):
    d, original = snapshot.document, snapshot.original
    r = original.receipt
    if (r.document_id != query.document_id or r.company_id != query.company_id
            or r.source_income_year != query.source_income_year or r.metadata_sha256 != query.metadata_sha256
            or r.content_sha256 != query.content_sha256 or type(r.byte_length) is not int or r.byte_length != query.byte_length
            or d.document_id != query.document_id or d.company_id != query.company_id or d.income_year != query.source_income_year
            or sha256(metadata_text(d).encode()).hexdigest() != query.metadata_sha256
            or d.content_sha256 != query.content_sha256 or d.byte_length != query.byte_length
            or d.status not in {DocumentStatus.ATTACHED, DocumentStatus.STORED, DocumentStatus.GENERATED_UNSIGNED, DocumentStatus.SIGNED_OWNER_ATTESTED}
            or d.removed_at is not None or r.retained_at.utcoffset() is None
            or str(UUID(r.original_id)) != r.original_id or type(original.content) is not bytes
            or len(original.content) != query.byte_length or sha256(original.content).hexdigest() != query.content_sha256):
        raise ValueError()


def serialize(snapshot, *, query):
    try:
        _validate(snapshot, query)
        r = snapshot.original.receipt
        value = {'codec': CODEC, 'documentText': metadata_text(snapshot.document),
            'receipt': {'originalId': r.original_id, 'documentId': str(r.document_id), 'companyId': str(r.company_id),
                'sourceIncomeYear': int(r.source_income_year), 'metadataSha256': r.metadata_sha256,
                'contentSha256': r.content_sha256, 'byteLength': r.byte_length, 'retainedAt': r.retained_at.isoformat()},
            'contentBase64': b64encode(snapshot.original.content).decode('ascii')}
        text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        if len(text.encode()) > MAX_RECORD_BYTES: raise ValueError()
        return text
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError, DocumentsError):
        raise DocumentsError.integrity_failed() from None


def parse(value, *, query):
    try:
        if not isinstance(value, str) or len(value) > MAX_RECORD_BYTES or len(value.encode()) > MAX_RECORD_BYTES: raise ValueError()
        envelope = json.loads(value, object_pairs_hook=_unique)
        if set(envelope) != {'codec', 'documentText', 'receipt', 'contentBase64'} or envelope['codec'] != CODEC: raise ValueError()
        d = json.loads(envelope['documentText'], object_pairs_hook=_unique)
        if set(d) != {f.name for f in fields(DocumentRecord)}: raise ValueError()
        document = DocumentRecord(**{**d, 'document_id': DocumentId(d['document_id']['value']),
            'company_id': CompanyId(d['company_id']['value']), 'income_year': IncomeYear(d['income_year']['value']),
            'status': DocumentStatus(d['status']), 'created_by': ActorId(ActorKind(d['created_by']['kind']), UserId(d['created_by']['subject']['value'])),
            'created_at': datetime.fromisoformat(d['created_at']),
            'removed_at': datetime.fromisoformat(d['removed_at']) if d['removed_at'] is not None else None})
        # Exact round trip rejects ignored nested fields, alternate primitive types
        # and noncanonical metadata, independently of the expected commitment.
        if metadata_text(document) != envelope['documentText']: raise ValueError()
        r = envelope['receipt']
        if set(r) != {'originalId', 'documentId', 'companyId', 'sourceIncomeYear', 'metadataSha256', 'contentSha256', 'byteLength', 'retainedAt'}: raise ValueError()
        receipt = RetainedDocumentOriginalReceipt(r['originalId'], DocumentId(r['documentId']), CompanyId(r['companyId']),
            IncomeYear(r['sourceIncomeYear']), r['metadataSha256'], r['contentSha256'], r['byteLength'], datetime.fromisoformat(r['retainedAt']))
        content = b64decode(envelope['contentBase64'], validate=True)
        if b64encode(content).decode('ascii') != envelope['contentBase64']: raise ValueError()
        result = RetainedDocumentOriginalSnapshot(document, RetainedDocumentOriginal(receipt, content))
        _validate(result, query)
        return result
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError, DocumentsError):
        raise DocumentsError.integrity_failed() from None
