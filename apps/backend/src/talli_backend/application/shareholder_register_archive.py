"""Compose RF's captured source identities with Documents-owned portable originals."""
from talli_backend.modules.documents.public import (
    DocumentId, RetainedDocumentOriginalQuery, DocumentsError,
    serialize_retained_document_original, parse_retained_document_original,
)
from talli_backend.modules.shareholder_register_filing import public as rf

MAX_SOURCE_ORIGINAL_BYTES = 128 * 1024 * 1024


def source_document_evidence(archive):
    """Keep every captured reference, including independently recorded observations."""
    records = [line.source for line in archive.source_approval_lineage]
    if archive.source_history is not None:
        records.extend(archive.source_history.year_sources)
        records.extend(archive.source_history.register_observations)
    return tuple(document for record in records for document in record.command.documents)


def source_original_queries(archive):
    queries = {}
    for source in source_document_evidence(archive):
        query = RetainedDocumentOriginalQuery(DocumentId(source.document_id), source.company_id,
            source.source_income_year, source.metadata_sha256, source.content_sha256, source.byte_length)
        if query.company_id != archive.company_id: raise DocumentsError.integrity_failed()
        queries[query] = query
    if sum(query.byte_length for query in queries) + sum(q.byte_length for q in feedback_original_queries(archive)) > MAX_SOURCE_ORIGINAL_BYTES:
        raise DocumentsError.integrity_failed()
    return tuple(sorted(queries, key=lambda q: (str(q.document_id), int(q.source_income_year), q.metadata_sha256, q.content_sha256)))


def original_wire(query, canonical):
    return {'documentId': str(query.document_id), 'companyId': str(query.company_id),
        'sourceIncomeYear': int(query.source_income_year), 'metadataSha256': query.metadata_sha256,
        'contentSha256': query.content_sha256, 'byteLength': query.byte_length, 'canonicalOriginal': canonical}


def _assert_source_metadata(archive, query, original):
    document = original.document
    for source in source_document_evidence(archive):
        if (source.document_id == str(query.document_id) and source.company_id == query.company_id
                and source.source_income_year == query.source_income_year and source.metadata_sha256 == query.metadata_sha256
                and source.content_sha256 == query.content_sha256 and source.byte_length == query.byte_length):
            if (source.document_type != document.document_type or source.integrity_status != document.status.value
                    or source.created_at != document.created_at or source.content_version_sha256 != document.content_sha256):
                raise DocumentsError.integrity_failed()


async def archive_source_originals(archive, *, documents_factory, access_token, actor_id):
    try:
        queries = source_original_queries(archive)
        if not queries: return []
        documents = await documents_factory.session(access_token)
        if documents.actor_id != actor_id: raise DocumentsError.forbidden()
        result = []
        for query in queries:
            original = await documents.read_retained_evidence(query)
            _assert_source_metadata(archive, query, original)
            result.append(original_wire(query, serialize_retained_document_original(original, query=query)))
        return result
    except DocumentsError:
        raise rf.ShareholderRegisterFilingError.unavailable() from None


def verify_source_originals(archive, values):
    """Offline verification requires exactly all retained source versions, no extras."""
    if type(values) is not list: raise DocumentsError.integrity_failed()
    expected = source_original_queries(archive)
    if len(values) != len(expected): raise DocumentsError.integrity_failed()
    remaining = list(values)
    originals = []
    for query in expected:
        identity = original_wire(query, None)
        matches = [item for item in remaining if type(item) is dict and set(item) == set(identity)
            and all(item[key] == value for key, value in identity.items() if key != 'canonicalOriginal')]
        if len(matches) != 1: raise DocumentsError.integrity_failed()
        item = matches[0]
        original = parse_retained_document_original(item['canonicalOriginal'], query=query)
        _assert_source_metadata(archive, query, original)
        originals.append(original)
        remaining.remove(item)
    return tuple(originals)


def feedback_original_queries(archive, *, require_complete=False):
    queries = []
    for artifact in archive.feedback_artifacts:
        if artifact.original_id is None:
            if require_complete: raise DocumentsError.integrity_failed()
            continue
        queries.append(RetainedDocumentOriginalQuery(DocumentId(artifact.document_id), archive.company_id,
            type(archive.income_year)(artifact.original_source_income_year), artifact.original_metadata_sha256,
            artifact.sha256, artifact.byte_length))
    if sum(query.byte_length for query in queries) > MAX_SOURCE_ORIGINAL_BYTES:
        raise DocumentsError.integrity_failed()
    return tuple(sorted(queries, key=lambda q: str(q.document_id)))


def _assert_feedback_metadata(archive, query, original):
    from datetime import datetime
    from talli_backend.shared.kernel import ActorKind
    artifact = next(row for row in archive.feedback_artifacts if row.document_id == str(query.document_id))
    submission = next(row for row in archive.production_submissions if row.id == artifact.submission_id)
    document, receipt = original.document, original.original.receipt
    if (receipt.original_id != artifact.original_id
            or receipt.retained_at != datetime.fromisoformat(artifact.original_retained_at)
            or document.document_type != 'authority_feedback' or document.status.value != 'stored'
            or document.content_type != artifact.content_type
            or document.linked_to != 'production_filing_submission:' + artifact.submission_id
            or document.created_by.kind != ActorKind.USER or str(document.created_by.subject) != submission.user_id):
        raise DocumentsError.integrity_failed()


async def archive_feedback_originals(archive, *, documents_factory, access_token, actor_id):
    try:
        queries = feedback_original_queries(archive)
        source_original_queries(archive)  # Enforce the shared inline byte budget.
        if not queries: return []
        documents = await documents_factory.session(access_token)
        if documents.actor_id != actor_id: raise DocumentsError.forbidden()
        values = []
        for query in queries:
            original = await documents.read_retained_evidence(query)
            _assert_feedback_metadata(archive, query, original)
            values.append(original_wire(query, serialize_retained_document_original(original, query=query)))
        return values
    except DocumentsError:
        raise rf.ShareholderRegisterFilingError.unavailable() from None


def verify_feedback_originals(archive, values, *, require_complete=False):
    if type(values) is not list: raise DocumentsError.integrity_failed()
    expected = feedback_original_queries(archive, require_complete=require_complete)
    source_original_queries(archive)
    if len(values) != len(expected): raise DocumentsError.integrity_failed()
    remaining, originals = list(values), []
    for query in expected:
        identity = original_wire(query, None)
        matches = [item for item in remaining if type(item) is dict and set(item) == set(identity)
            and all(item[key] == value for key, value in identity.items() if key != 'canonicalOriginal')]
        if len(matches) != 1: raise DocumentsError.integrity_failed()
        item = matches[0]
        original = parse_retained_document_original(item['canonicalOriginal'], query=query)
        _assert_feedback_metadata(archive, query, original)
        originals.append(original)
        remaining.remove(item)
    return tuple(originals)
