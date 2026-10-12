"""Complete metadata hashes through the Documents public entrypoint."""
from dataclasses import fields, replace
from datetime import timedelta, timezone
import pytest
from talli_backend.modules.documents.public import document_metadata_sha256, DocumentStatus, DocumentsError
from talli_backend.modules.shareholder_register_filing.public import rf1086_year_source_digest
from test_documents import record


def test_owned_hash_preserves_existing_complete_utc_source_binding():
    original = record(DocumentStatus.ATTACHED)
    assert document_metadata_sha256(original) == rf1086_year_source_digest(original)
    assert document_metadata_sha256(replace(original, created_at=original.created_at.astimezone(timezone(timedelta(hours=2))))) == document_metadata_sha256(original)


@pytest.mark.parametrize('field,value', [
    ('name','Another.pdf'),('linked_to','aksjonaerregisteroppgaven'),('document_type','corporate_document'),
    ('status',DocumentStatus.STORED),('retention_years',10),('storage_key','different/original.pdf'),
    ('content_type','text/xml'),('byte_length',999),('content_sha256','0'*64),('removal_reason','changed'),
])
def test_every_material_metadata_change_changes_owned_hash(field,value):
    original=record(DocumentStatus.ATTACHED)
    assert document_metadata_sha256(replace(original, **{field:value})) != document_metadata_sha256(original)


def test_naive_metadata_timestamp_is_not_silently_interpreted():
    original=record(DocumentStatus.ATTACHED)
    with pytest.raises(DocumentsError):document_metadata_sha256(replace(original,created_at=original.created_at.replace(tzinfo=None)))
