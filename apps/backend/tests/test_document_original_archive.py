"""Portable metadata and bytes must bind to independently captured source evidence."""
from dataclasses import replace
import json

import pytest

from talli_backend.modules.documents.public import (
    DocumentsError, parse_retained_document_original, serialize_retained_document_original,
)
from test_document_originals import historical_query, historical_snapshot


def test_original_codec_round_trips_binary_bytes_and_captured_metadata():
    snapshot = historical_snapshot(); query = historical_query()
    encoded = serialize_retained_document_original(snapshot, query=query)
    assert parse_retained_document_original(encoded, query=query) == snapshot
    assert serialize_retained_document_original(parse_retained_document_original(encoded, query=query), query=query) == encoded


@pytest.mark.parametrize('change', ['codec', 'extra', 'missing', 'bytes', 'base64', 'metadata', 'document-id', 'receipt-year', 'receipt-hash', 'receipt-length', 'receipt-time', 'duplicate', 'nested-extra', 'null'])
def test_original_codec_rejects_changed_or_ambiguous_evidence(change):
    query = historical_query()
    text = serialize_retained_document_original(historical_snapshot(), query=query)
    value = json.loads(text)
    if change == 'codec': value['codec'] = 'unknown'
    if change == 'extra': value['extra'] = True
    if change == 'missing': del value['documentText']
    if change == 'bytes': value['contentBase64'] = 'Y2hhbmdlZA=='
    if change == 'base64': value['contentBase64'] += '\n'
    if change == 'metadata': value['documentText'] += ' '
    if change == 'document-id': value['receipt']['documentId'] = '00000000-0000-0000-0000-000000000009'
    if change == 'receipt-year': value['receipt']['sourceIncomeYear'] = 2024
    if change == 'receipt-hash': value['receipt']['metadataSha256'] = 'f'*64
    if change == 'receipt-length': value['receipt']['byteLength'] = True
    if change == 'receipt-time': value['receipt']['retainedAt'] = '2026-01-01'
    if change == 'nested-extra':
        d = json.loads(value['documentText']);d['company_id']['extra'] = True
        value['documentText'] = json.dumps(d, sort_keys=True, separators=(',', ':'))
    text = json.dumps(value)
    if change == 'duplicate': text = text[:-1]+',"codec":"documents-retained-original-v1"}'
    if change == 'null': text = 'null'
    with pytest.raises(DocumentsError) as caught:
        parse_retained_document_original(text, query=query)
    assert caught.value.code == 'DOCUMENT_INTEGRITY_FAILED'


@pytest.mark.parametrize('field,value', [('content_sha256', 'f'*64), ('metadata_sha256', 'e'*64), ('byte_length', 1)])
def test_original_codec_cannot_be_rebound_to_another_source(field, value):
    text = serialize_retained_document_original(historical_snapshot(), query=historical_query())
    with pytest.raises(DocumentsError):
        parse_retained_document_original(text, query=replace(historical_query(), **{field: value}))


def test_original_codec_refuses_corrupt_snapshot_at_export():
    original = historical_snapshot()
    with pytest.raises(DocumentsError):
        serialize_retained_document_original(replace(original, document=replace(original.document, name='Changed.pdf')), query=historical_query())
