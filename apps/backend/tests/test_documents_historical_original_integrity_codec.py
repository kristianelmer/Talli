"""Frozen Documents metadata bytes used by the isolated SQL parity probe.

These tests exercise unchanged Python projection/digests, not SQL authorization,
retained bytes or consumer eligibility. The SQL-only fields remain outside hash.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from talli_backend.adapters.postgres_document_originals import _snapshot_document
from talli_backend.modules.documents.evidence import metadata_text
from talli_backend.modules.documents.public import DocumentStatus, document_metadata_sha256

VECTORS = json.loads((Path(__file__).parent / 'fixtures/documents_historical_original_integrity_v1.json').read_text())['vectors']


@pytest.mark.parametrize('vector', VECTORS, ids=lambda value: value['name'])
def test_unchanged_captured_projection_metadata_bytes_and_digest(vector):
    document = _snapshot_document(vector['snapshot'])
    assert document is not None
    assert metadata_text(document) == vector['document_text']
    assert document_metadata_sha256(document) == vector['metadata_sha256']
    assert sha256(vector['document_text'].encode()).hexdigest() == vector['metadata_sha256']
    assert len(json.loads(vector['document_text'])) == 16
    assert len(vector['snapshot']) == 23


def test_integrity_projection_preserves_all_statuses_and_removal_metadata():
    assert {vector['snapshot']['status'] for vector in VECTORS} == {status.value for status in DocumentStatus}
    removed = next(vector for vector in VECTORS if vector['name'] == 'removed')
    assert json.loads(removed['document_text'])['removed_at'] == '2025-07-02T12:30:45.654321+00:00'


def test_seven_sql_only_columns_do_not_acquire_historical_hash_protection():
    base = VECTORS[0]
    changed = next(vector for vector in VECTORS if vector['name'] == 'unhashed_sql_fields')
    assert base['document_text'] == changed['document_text']
    assert base['metadata_sha256'] == changed['metadata_sha256']


@pytest.mark.parametrize('key,value', [
    ('id', '00000000-0000-0000-0000-000000000014'),
    ('company_id', '00000000-0000-0000-0000-000000000014'), ('income_year', 2024),
    ('document_type', 'signed_minutes'), ('name', 'Different.pdf'), ('linked_to', 'different'),
    ('status', 'stored'), ('retention_years', 10), ('storage_key', 'different.pdf'),
    ('content_type', 'application/octet-stream'), ('byte_length', 17), ('content_sha256', 'f' * 64),
    ('created_by', '00000000-0000-0000-0000-000000000014'), ('created_at', '2025-07-01T12:30:46+00:00'),
    ('removed_at', '2025-07-02T12:30:45+00:00'), ('removal_reason', 'Different reason'),
])
def test_each_public_metadata_field_remains_digest_bound(key, value):
    row = deepcopy(VECTORS[0]['snapshot']); row[key] = value
    document = _snapshot_document(row)
    assert document is not None
    assert document_metadata_sha256(document) != VECTORS[0]['metadata_sha256']
