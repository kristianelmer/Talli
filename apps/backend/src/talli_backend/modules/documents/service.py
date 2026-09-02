"""Canonical accounting-document policy."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
import re
import unicodedata

from talli_backend.modules.documents.public import (
    BeginDocumentUploadCommand,
    DocumentBackupObject,
    DocumentId,
    DocumentObjectStorage,
    DocumentObjectTransfer,
    DocumentRecord,
    DocumentRestoreObject,
    DocumentRestorePlan,
    DocumentsError,
    DocumentsPersistence,
    DocumentStatus,
    DocumentTransferKind,
    DocumentUploadTransfer,
)
from talli_backend.shared.kernel import CompanyId, IncomeYear


COMPANY_DOCUMENTS_BUCKET = "company-documents"
MAX_DOCUMENT_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_DOCUMENT_TYPES = frozenset({"bank_statement", "accounting_document", "corporate_document", "authority_feedback"})
ALLOWED_LINKS = frozenset({"workspace", "aksjonaerregisteroppgaven", "skattemelding", "aarsregnskap"})
ALLOWED_CONTENT_TYPES = frozenset({
    "application/pdf", "application/octet-stream", "application/xml", "text/xml", "text/plain",
})


def validated_pdf_name(*, name: str, content_type: str, byte_length: int, header: bytes) -> str:
    normalized = re.split(r"[\\/]", name)[-1].strip()
    if not normalized or not normalized.lower().endswith(".pdf"):
        raise DocumentsError.invalid_input()
    if byte_length <= 0 or byte_length > MAX_DOCUMENT_UPLOAD_BYTES:
        raise DocumentsError.invalid_input()
    if content_type not in {"application/pdf", "application/octet-stream", ""}:
        raise DocumentsError.invalid_input()
    if header[:5] != b"%PDF-":
        raise DocumentsError.invalid_input()
    return normalized


def validated_document_name(*, name: str, content_type: str, byte_length: int, header: bytes) -> str:
    normalized = re.split(r"[\\/]", name)[-1].strip()
    normalized_type = content_type.split(";", 1)[0].strip().lower() or "application/octet-stream"
    if not normalized or byte_length <= 0 or byte_length > MAX_DOCUMENT_UPLOAD_BYTES:
        raise DocumentsError.invalid_input()
    if normalized_type not in ALLOWED_CONTENT_TYPES:
        raise DocumentsError.invalid_input()
    if normalized_type in {"application/pdf", "application/octet-stream"}:
        return validated_pdf_name(
            name=normalized,
            content_type=normalized_type,
            byte_length=byte_length,
            header=header,
        )
    if normalized_type in {"application/xml", "text/xml"}:
        if not normalized.lower().endswith(".xml") or not header.lstrip().startswith(b"<"):
            raise DocumentsError.invalid_input()
    elif normalized_type == "text/plain" and not normalized.lower().endswith(".txt"):
        raise DocumentsError.invalid_input()
    return normalized


def document_storage_key(company_id: CompanyId, income_year: IncomeYear, document_id: DocumentId, name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", ascii_name)
    safe_name = re.sub(r"^\.+", "", safe_name)
    safe_name = re.sub(r"-+", "-", safe_name).strip("-")[:120] or "document"
    return f"{company_id}/{int(income_year)}/{document_id}/{safe_name}"


class DocumentsService:
    def __init__(self, persistence: DocumentsPersistence, storage: DocumentObjectStorage) -> None:
        self._persistence = persistence
        self._storage = storage

    @property
    def actor_id(self):
        return self._persistence.actor_id

    async def _require_owner(self, company_id: CompanyId) -> None:
        if await self._persistence.actor_role(company_id) != "owner":
            raise DocumentsError.forbidden()

    async def begin_upload(self, command: BeginDocumentUploadCommand) -> DocumentUploadTransfer:
        await self._require_owner(command.company_id)
        is_feedback_link = bool(re.fullmatch(r"production_filing_submission:[0-9a-fA-F-]{36}", command.linked_to))
        is_corporate_link = bool(re.fullmatch(r"corporate_decision:[0-9a-fA-F-]{36}", command.linked_to))
        if command.document_type not in ALLOWED_DOCUMENT_TYPES:
            raise DocumentsError.invalid_input()
        if command.document_type == "authority_feedback":
            valid_relationship = is_feedback_link and command.final_status is DocumentStatus.STORED
        elif command.document_type == "corporate_document":
            valid_relationship = (command.linked_to in ALLOWED_LINKS and command.final_status is DocumentStatus.ATTACHED) or (
                is_corporate_link and command.final_status in {
                    DocumentStatus.GENERATED_UNSIGNED, DocumentStatus.SIGNED_OWNER_ATTESTED,
                }
            )
        else:
            valid_relationship = command.linked_to in ALLOWED_LINKS and command.final_status is DocumentStatus.ATTACHED
        if not valid_relationship:
            raise DocumentsError.invalid_input()
        name = validated_document_name(
            name=command.file_name,
            content_type=command.content_type,
            byte_length=command.byte_length,
            header=command.header,
        )
        normalized_type = command.content_type.split(";", 1)[0].strip().lower()
        if normalized_type in {"", "application/octet-stream"}:
            normalized_type = "application/pdf"
        command = replace(command, content_type=normalized_type)
        storage_key = document_storage_key(command.company_id, command.income_year, command.document_id, name)
        document = await self._persistence.stage_upload(command, name=name, storage_key=storage_key)
        try:
            signed_url, token = await self._storage.create_upload_transfer(
                bucket=COMPANY_DOCUMENTS_BUCKET, storage_key=storage_key
            )
        except DocumentsError:
            await self._persistence.quarantine_upload(command.document_id, "upload_transfer_unavailable")
            raise
        return DocumentUploadTransfer(document, COMPANY_DOCUMENTS_BUCKET, storage_key, token, signed_url)

    async def finalize_upload(self, document_id: DocumentId) -> DocumentRecord:
        document = await self._persistence.get_document(document_id)
        if document is None:
            raise DocumentsError.not_found()
        await self._require_owner(document.company_id)
        final_statuses = {
            DocumentStatus.ATTACHED,
            DocumentStatus.GENERATED_UNSIGNED,
            DocumentStatus.SIGNED_OWNER_ATTESTED,
            DocumentStatus.STORED,
        }
        if document.status is not DocumentStatus.STAGED and document.status not in final_statuses:
            raise DocumentsError.conflict()
        try:
            stored = await self._storage.read_object(bucket=COMPANY_DOCUMENTS_BUCKET, storage_key=document.storage_key)
        except DocumentsError:
            await self._persistence.quarantine_upload(document_id, "uploaded_object_unavailable")
            raise
        normalized_type = stored.content_type.split(";", 1)[0].strip().lower()
        expected_type = document.content_type.split(";", 1)[0].strip().lower()
        compatible_type = normalized_type == expected_type or (
            expected_type == "application/pdf" and normalized_type == "application/octet-stream"
        )
        invalid_signature = (
            expected_type == "application/pdf" and stored.content[:5] != b"%PDF-"
        ) or (
            expected_type in {"application/xml", "text/xml"}
            and not stored.content.lstrip().startswith(b"<")
        )
        if (
            len(stored.content) <= 0
            or len(stored.content) > MAX_DOCUMENT_UPLOAD_BYTES
            or normalized_type not in ALLOWED_CONTENT_TYPES
            or not compatible_type
            or invalid_signature
        ):
            await self._persistence.quarantine_upload(document_id, "uploaded_object_integrity_failed")
            raise DocumentsError.integrity_failed()
        content_sha256 = sha256(stored.content).hexdigest()
        if document.status in final_statuses:
            if document.byte_length != len(stored.content) or document.content_sha256 != content_sha256:
                raise DocumentsError.integrity_failed()
            return document
        return await self._persistence.finalize_upload(
            document_id,
            byte_length=len(stored.content),
            content_sha256=content_sha256,
        )

    async def list_documents(self, company_ids: tuple[CompanyId, ...]) -> tuple[DocumentRecord, ...]:
        if not 1 <= len(company_ids) <= 100:
            raise DocumentsError.invalid_input()
        for company_id in company_ids:
            if await self._persistence.actor_role(company_id) is None:
                raise DocumentsError.forbidden()
        return await self._persistence.list_documents(company_ids)

    async def create_transfer(self, document_id: DocumentId, kind: DocumentTransferKind) -> DocumentObjectTransfer:
        document = await self._persistence.get_document(document_id)
        if document is None or document.status not in {
            DocumentStatus.ATTACHED,
            DocumentStatus.GENERATED_UNSIGNED,
            DocumentStatus.SIGNED_OWNER_ATTESTED,
            DocumentStatus.STORED,
        }:
            raise DocumentsError.not_found()
        await self._require_owner(document.company_id)
        if kind is DocumentTransferKind.DOWNLOAD and not self._persistence.aal2:
            raise DocumentsError.step_up_required()
        if kind is DocumentTransferKind.PREVIEW and document.content_type != "application/pdf":
            raise DocumentsError.not_found()
        stored = await self._storage.read_object(bucket=COMPANY_DOCUMENTS_BUCKET, storage_key=document.storage_key)
        if (
            document.byte_length != len(stored.content)
            or document.content_sha256 != sha256(stored.content).hexdigest()
            or (document.content_type == "application/pdf" and stored.content[:5] != b"%PDF-")
        ):
            raise DocumentsError.integrity_failed()
        expires = 300
        signed_url = await self._storage.create_download_transfer(
            bucket=COMPANY_DOCUMENTS_BUCKET,
            storage_key=document.storage_key,
            expires_in_seconds=expires,
        )
        return DocumentObjectTransfer(document, kind, signed_url, expires)

    async def remove_document(self, document_id: DocumentId, *, reason: str) -> DocumentRecord:
        document = await self._persistence.get_document(document_id)
        if document is None or document.status not in {
            DocumentStatus.ATTACHED,
            DocumentStatus.GENERATED_UNSIGNED,
            DocumentStatus.SIGNED_OWNER_ATTESTED,
            DocumentStatus.STORED,
        }:
            raise DocumentsError.not_found()
        await self._require_owner(document.company_id)
        if await self._persistence.has_evidence_references(document_id):
            raise DocumentsError.evidence_linked()
        removed = await self._persistence.mark_removed(document_id, reason=reason.strip() or "owner_requested")
        try:
            await self._storage.remove_object(bucket=COMPANY_DOCUMENTS_BUCKET, storage_key=document.storage_key)
        except DocumentsError:
            await self._persistence.restore_after_storage_failure(document_id)
            raise
        return removed

    async def backup_projection(self, company_id: CompanyId, income_year: IncomeYear) -> tuple[DocumentBackupObject, ...]:
        if await self._persistence.actor_role(company_id) is None:
            raise DocumentsError.forbidden()
        documents = await self._persistence.list_documents((company_id,))
        return tuple(
            DocumentBackupObject(
                document_id=item.document_id,
                document_type=item.document_type,
                name=item.name,
                linked_to=item.linked_to,
                storage_key=item.storage_key,
                status=item.status,
                retention_years=item.retention_years,
                content_type=item.content_type,
                byte_length=item.byte_length,
                content_sha256=item.content_sha256,
                created_by=item.created_by,
                created_at=item.created_at,
                removed_at=item.removed_at,
                removal_reason=item.removal_reason,
            )
            for item in documents
            if item.income_year == income_year
        )

    async def prepare_isolated_restore(
        self,
        company_id: CompanyId,
        income_year: IncomeYear,
        target_company_id: CompanyId,
    ) -> DocumentRestorePlan:
        await self._require_owner(company_id)
        await self._require_owner(target_company_id)
        projection = await self.backup_projection(company_id, income_year)
        seen_ids: set[str] = set()
        seen_keys: set[str] = set()
        restore_objects: list[DocumentRestoreObject] = []
        digest_rows: list[dict[str, object]] = []
        object_statuses = {
            DocumentStatus.ATTACHED,
            DocumentStatus.GENERATED_UNSIGNED,
            DocumentStatus.SIGNED_OWNER_ATTESTED,
            DocumentStatus.STORED,
        }
        for item in projection:
            document_id = str(item.document_id)
            expected_source_key = document_storage_key(company_id, income_year, item.document_id, item.name)
            if document_id in seen_ids or item.storage_key in seen_keys or item.storage_key != expected_source_key:
                raise DocumentsError.integrity_failed()
            seen_ids.add(document_id)
            seen_keys.add(item.storage_key)
            if item.retention_years < 5 or item.content_type not in ALLOWED_CONTENT_TYPES:
                raise DocumentsError.integrity_failed()
            if item.status in object_statuses and (
                item.byte_length is None
                or item.byte_length <= 0
                or item.byte_length > MAX_DOCUMENT_UPLOAD_BYTES
                or item.content_sha256 is None
                or re.fullmatch(r"[0-9a-f]{64}", item.content_sha256) is None
            ):
                raise DocumentsError.integrity_failed()
            target_key = document_storage_key(target_company_id, income_year, item.document_id, item.name)
            restore_objects.append(DocumentRestoreObject(item, target_key))
            digest_rows.append({
                "documentId": document_id,
                "sourceStorageKey": item.storage_key,
                "targetStorageKey": target_key,
                "status": item.status.value,
                "retentionYears": item.retention_years,
                "contentType": item.content_type,
                "byteLength": item.byte_length,
                "contentSha256": item.content_sha256,
            })
        digest = sha256(
            json.dumps(digest_rows, sort_keys=True, separators=(",", ":")).encode("utf8")
        ).hexdigest()
        return DocumentRestorePlan(
            source_company_id=company_id,
            target_company_id=target_company_id,
            income_year=income_year,
            objects=tuple(restore_objects),
            projection_sha256=digest,
        )
