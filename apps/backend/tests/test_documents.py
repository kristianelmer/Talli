from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256

import pytest

from talli_backend.modules.documents.public import (
    BeginDocumentUploadCommand,
    DocumentId,
    DocumentRecord,
    DocumentsError,
    DocumentStatus,
    DocumentTransferKind,
    StoredDocumentObject,
    RetainedDocumentOriginalReceipt, document_metadata_sha256,
)
from talli_backend.modules.documents.service import (
    DocumentsService,
    document_storage_key,
    validated_document_name,
    validated_pdf_name,
)
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, UserId


COMPANY_ID = CompanyId("10000000-0000-4000-8000-000000000001")
TARGET_COMPANY_ID = CompanyId("10000000-0000-4000-8000-000000000002")
DOCUMENT_ID = DocumentId("20000000-0000-4000-8000-000000000001")
ACTOR = ActorId(ActorKind.USER, UserId("30000000-0000-4000-8000-000000000001"))
PDF = b"%PDF-1.7\ncanonical"


def record(status: DocumentStatus = DocumentStatus.STAGED) -> DocumentRecord:
    return DocumentRecord(
        document_id=DOCUMENT_ID,
        company_id=COMPANY_ID,
        income_year=IncomeYear(2026),
        document_type="accounting_document",
        name="Bilag.pdf",
        linked_to="workspace",
        status=status,
        retention_years=5,
        storage_key=f"{COMPANY_ID}/2026/{DOCUMENT_ID}/Bilag.pdf",
        content_type="application/pdf",
        byte_length=(len(PDF) if status is DocumentStatus.ATTACHED else None),
        content_sha256=(sha256(PDF).hexdigest() if status is DocumentStatus.ATTACHED else None),
        created_by=ACTOR,
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
        removed_at=None,
        removal_reason=None,
    )


class Persistence:
    actor_id = ACTOR

    def __init__(self, *, aal2: bool = True, linked: bool = False) -> None:
        self.aal2 = aal2
        self.linked = linked
        self.current: DocumentRecord | None = None
        self.quarantine_reason: str | None = None
        self.restored = False
        self.staged_command = None

    async def actor_role(self, company_id):
        return "owner" if company_id in {COMPANY_ID, TARGET_COMPANY_ID} else None

    async def refresh_actor_role(self, company_id):
        return await self.actor_role(company_id)

    async def stage_upload(self, command, *, name, storage_key):
        self.staged_command = command
        self.current = record()
        return self.current

    async def quarantine_upload(self, document_id, reason):
        self.quarantine_reason = reason

    async def finalize_upload(self, document_id, *, byte_length, content_sha256):
        self.current = record(DocumentStatus.ATTACHED)
        assert byte_length == len(PDF)
        assert content_sha256 == sha256(PDF).hexdigest()
        return self.current

    async def retain_verified_original(self, document, content):
        assert document == self.current
        assert len(content) == document.byte_length and sha256(content).hexdigest() == document.content_sha256
        self.retained_content = bytes(content)
        return RetainedDocumentOriginalReceipt("40000000-0000-4000-8000-000000000001", document.document_id,
            document.company_id, document.income_year, document_metadata_sha256(document), document.content_sha256,
            document.byte_length, datetime(2026, 9, 24, tzinfo=UTC))

    async def get_document(self, document_id):
        return self.current

    async def list_documents(self, company_ids):
        return (self.current,) if self.current else ()

    async def has_evidence_references(self, document_id):
        return self.linked

    async def mark_removed(self, document_id, *, reason):
        assert self.current is not None
        self.current = record(DocumentStatus.REMOVED)
        return self.current

    async def restore_after_storage_failure(self, document_id):
        self.restored = True
        self.current = record(DocumentStatus.ATTACHED)


class Storage:
    def __init__(self, *, content: bytes = PDF, fail_remove: bool = False) -> None:
        self.content = content
        self.fail_remove = fail_remove
        self.removed = False

    async def create_upload_transfer(self, *, bucket, storage_key):
        return "https://storage.invalid/upload", "signed-token"

    async def read_object(self, *, bucket, storage_key):
        return StoredDocumentObject(self.content, "application/pdf")

    async def create_download_transfer(self, *, bucket, storage_key, expires_in_seconds):
        return "https://storage.invalid/download"

    async def remove_object(self, *, bucket, storage_key):
        if self.fail_remove:
            raise DocumentsError.storage_unavailable()
        self.removed = True


def command(**overrides):
    values = dict(
        company_id=COMPANY_ID,
        income_year=IncomeYear(2026),
        document_id=DOCUMENT_ID,
        document_type="accounting_document",
        linked_to="workspace",
        file_name="Bilag.pdf",
        content_type="application/pdf",
        byte_length=len(PDF),
        header=PDF[:5],
    )
    values.update(overrides)
    return BeginDocumentUploadCommand(**values)


def test_pdf_validation_and_storage_key_are_canonical() -> None:
    assert validated_pdf_name(
        name="../Bank utskrift.pdf", content_type="application/octet-stream",
        byte_length=len(PDF), header=PDF[:5],
    ) == "Bank utskrift.pdf"
    assert document_storage_key(COMPANY_ID, IncomeYear(2026), DOCUMENT_ID, "Bank utskrift.pdf") == (
        f"{COMPANY_ID}/2026/{DOCUMENT_ID}/Bank-utskrift.pdf"
    )
    with pytest.raises(DocumentsError):
        validated_pdf_name(name="fake.pdf", content_type="application/pdf", byte_length=5, header=b"html!")


def test_staged_upload_is_signed_then_finalized_from_verified_object_bytes() -> None:
    persistence, storage = Persistence(), Storage()
    service = DocumentsService(persistence, storage)
    transfer = asyncio.run(service.begin_upload(command()))
    assert transfer.bucket == "company-documents"
    assert transfer.token == "signed-token"
    finalized = asyncio.run(service.finalize_upload(DOCUMENT_ID))
    assert finalized.status is DocumentStatus.ATTACHED
    assert finalized.content_sha256 == sha256(PDF).hexdigest()


def test_finalization_replay_returns_the_verified_existing_result() -> None:
    persistence = Persistence()
    persistence.current = record(DocumentStatus.ATTACHED)
    finalized = asyncio.run(
        DocumentsService(persistence, Storage()).finalize_upload(DOCUMENT_ID)
    )
    assert finalized.status is DocumentStatus.ATTACHED
    assert finalized.content_sha256 == sha256(PDF).hexdigest()


def test_pdf_octet_stream_is_normalized_before_metadata_is_staged() -> None:
    persistence = Persistence()
    asyncio.run(DocumentsService(persistence, Storage()).begin_upload(
        command(content_type="application/octet-stream")
    ))
    assert persistence.staged_command.content_type == "application/pdf"


def test_generic_producer_artifacts_have_narrow_relationship_and_content_rules() -> None:
    xml = b"<?xml version='1.0'?><feedback/>"
    assert validated_document_name(
        name="feedback.xml",
        content_type="application/xml",
        byte_length=len(xml),
        header=xml[:32],
    ) == "feedback.xml"
    persistence = Persistence()
    asyncio.run(DocumentsService(persistence, Storage()).begin_upload(command(
        document_type="authority_feedback",
        linked_to="production_filing_submission:40000000-0000-4000-8000-000000000001",
        file_name="feedback.xml",
        content_type="application/xml",
        byte_length=len(xml),
        header=xml[:32],
        final_status=DocumentStatus.STORED,
    )))
    assert persistence.staged_command.final_status is DocumentStatus.STORED
    with pytest.raises(DocumentsError):
        asyncio.run(DocumentsService(Persistence(), Storage()).begin_upload(command(
            document_type="authority_feedback",
            linked_to="workspace",
            file_name="feedback.xml",
            content_type="application/xml",
            byte_length=len(xml),
            header=xml[:32],
            final_status=DocumentStatus.STORED,
        )))


def test_invalid_uploaded_object_is_quarantined() -> None:
    persistence, storage = Persistence(), Storage(content=b"not-a-pdf")
    persistence.current = record()
    service = DocumentsService(persistence, storage)
    with pytest.raises(DocumentsError) as failure:
        asyncio.run(service.finalize_upload(DOCUMENT_ID))
    assert failure.value.code == "DOCUMENT_INTEGRITY_FAILED"
    assert persistence.quarantine_reason == "uploaded_object_integrity_failed"


def test_download_requires_aal2_and_rechecks_integrity() -> None:
    persistence = Persistence(aal2=False)
    persistence.current = record(DocumentStatus.ATTACHED)
    service = DocumentsService(persistence, Storage())
    with pytest.raises(DocumentsError) as failure:
        asyncio.run(service.create_transfer(DOCUMENT_ID, DocumentTransferKind.DOWNLOAD))
    assert failure.value.code == "DOCUMENT_STEP_UP_REQUIRED"

    persistence.aal2 = True
    transfer = asyncio.run(service.create_transfer(DOCUMENT_ID, DocumentTransferKind.DOWNLOAD))
    assert transfer.signed_url.endswith("/download")
    assert transfer.expires_in_seconds == 300


def test_linked_evidence_blocks_removal_without_touching_storage() -> None:
    persistence, storage = Persistence(linked=True), Storage()
    persistence.current = record(DocumentStatus.ATTACHED)
    with pytest.raises(DocumentsError) as failure:
        asyncio.run(DocumentsService(persistence, storage).remove_document(DOCUMENT_ID, reason="owner_requested"))
    assert failure.value.code == "DOCUMENT_EVIDENCE_LINKED"
    assert storage.removed is False


def test_storage_removal_failure_restores_metadata() -> None:
    persistence, storage = Persistence(), Storage(fail_remove=True)
    persistence.current = record(DocumentStatus.ATTACHED)
    with pytest.raises(DocumentsError):
        asyncio.run(DocumentsService(persistence, storage).remove_document(DOCUMENT_ID, reason="owner_requested"))
    assert persistence.restored is True
    assert persistence.current.status is DocumentStatus.ATTACHED


def test_document_backup_projection_retains_hash_and_storage_identity() -> None:
    persistence = Persistence()
    persistence.current = record(DocumentStatus.ATTACHED)
    projection = asyncio.run(
        DocumentsService(persistence, Storage()).backup_projection(COMPANY_ID, IncomeYear(2026))
    )
    assert len(projection) == 1
    assert projection[0].content_sha256 == sha256(PDF).hexdigest()
    assert projection[0].storage_key.endswith("/Bilag.pdf")
    assert projection[0].name == "Bilag.pdf"


def test_isolated_restore_plan_is_deterministic_and_rekeys_only_the_target_company() -> None:
    persistence = Persistence()
    persistence.current = record(DocumentStatus.ATTACHED)
    plan = asyncio.run(
        DocumentsService(persistence, Storage()).prepare_isolated_restore(
            COMPANY_ID,
            IncomeYear(2026),
            TARGET_COMPANY_ID,
        )
    )
    assert plan.source_company_id == COMPANY_ID
    assert plan.target_company_id == TARGET_COMPANY_ID
    assert len(plan.projection_sha256) == 64
    assert plan.objects[0].document.storage_key.startswith(f"{COMPANY_ID}/2026/")
    assert plan.objects[0].target_storage_key.startswith(f"{TARGET_COMPANY_ID}/2026/")
    assert plan.objects[0].document.content_sha256 == sha256(PDF).hexdigest()


def test_isolated_restore_plan_rejects_noncanonical_source_object_identity() -> None:
    persistence = Persistence()
    persistence.current = replace(
        record(DocumentStatus.ATTACHED),
        storage_key=f"{COMPANY_ID}/2026/arbitrary-object.pdf",
    )
    with pytest.raises(DocumentsError) as failure:
        asyncio.run(
            DocumentsService(persistence, Storage()).prepare_isolated_restore(
                COMPANY_ID,
                IncomeYear(2026),
                TARGET_COMPANY_ID,
            )
        )
    assert failure.value.code == "DOCUMENT_INTEGRITY_FAILED"

@pytest.mark.parametrize("status", [
    DocumentStatus.ATTACHED,
    DocumentStatus.GENERATED_UNSIGNED,
    DocumentStatus.SIGNED_OWNER_ATTESTED,
    DocumentStatus.STORED,
])
def test_source_evidence_reverifies_bytes_and_preserves_integrity_classification(status):
    persistence = Persistence()
    persistence.current = replace(record(DocumentStatus.ATTACHED), status=status)
    evidence = asyncio.run(DocumentsService(persistence, Storage()).verify_document_evidence(DOCUMENT_ID))
    assert evidence.document == persistence.current
    assert evidence.content_sha256 == sha256(PDF).hexdigest()
    assert evidence.byte_length == len(PDF)
    assert evidence.integrity_status == status
    assert not hasattr(evidence, "content")


@pytest.mark.parametrize("status", [DocumentStatus.STAGED, DocumentStatus.QUARANTINED])
def test_source_evidence_refuses_unverified_documents_before_storage(status):
    persistence = Persistence()
    persistence.current = record(status)
    class UnreachableStorage(Storage):
        async def read_object(self, **kwargs):
            pytest.fail("Unverified document must not reach private storage")
    with pytest.raises(DocumentsError) as error:
        asyncio.run(DocumentsService(persistence, UnreachableStorage()).verify_document_evidence(DOCUMENT_ID))
    assert error.value.code == "DOCUMENT_NOT_FOUND"


def test_source_evidence_refuses_changed_private_bytes():
    persistence = Persistence()
    persistence.current = record(DocumentStatus.ATTACHED)
    with pytest.raises(DocumentsError) as error:
        asyncio.run(DocumentsService(persistence, Storage(content=b"%PDF-1.7\ntampered")).verify_document_evidence(DOCUMENT_ID))
    assert error.value.code == "DOCUMENT_INTEGRITY_FAILED"


@pytest.mark.parametrize("change", ["removed", "metadata", "owner_revoked"])
def test_source_evidence_rechecks_metadata_and_owner_after_object_io(change):
    class ChangingPersistence(Persistence):
        revoked = False
        async def actor_role(self, company_id):
            return None if self.revoked else await super().actor_role(company_id)
    persistence = ChangingPersistence()
    persistence.current = record(DocumentStatus.ATTACHED)
    class ChangingStorage(Storage):
        async def read_object(self, **kwargs):
            if change == "removed": persistence.current = None
            elif change == "metadata": persistence.current = replace(persistence.current, document_type="changed")
            else: persistence.revoked = True
            return await super().read_object(**kwargs)
    with pytest.raises(DocumentsError) as error:
        asyncio.run(DocumentsService(persistence, ChangingStorage()).verify_document_evidence(DOCUMENT_ID))
    assert error.value.code == ("DOCUMENT_FORBIDDEN" if change == "owner_revoked" else "DOCUMENT_CONFLICT")


def test_source_evidence_requires_owner_before_private_object_read():
    class OtherCompanyPersistence(Persistence):
        async def actor_role(self, company_id): return None
    persistence = OtherCompanyPersistence()
    persistence.current = record(DocumentStatus.ATTACHED)
    class UnreachableStorage(Storage):
        async def read_object(self, **kwargs): pytest.fail("Unauthorized storage read")
    with pytest.raises(DocumentsError) as error:
        asyncio.run(DocumentsService(persistence, UnreachableStorage()).verify_document_evidence(DOCUMENT_ID))
    assert error.value.code == "DOCUMENT_FORBIDDEN"
