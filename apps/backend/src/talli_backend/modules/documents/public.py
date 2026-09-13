"""Stable public contract for accounting documents and private object transfers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from collections.abc import Callable, Mapping
from typing import Protocol, TypeVar
from uuid import UUID

from talli_backend.shared.kernel import ActorId, CompanyId, DomainError, ErrorCategory, IncomeYear


@dataclass(frozen=True, slots=True)
class DocumentId:
    value: str

    def __post_init__(self) -> None:
        try:
            value = str(UUID(self.value))
        except (ValueError, AttributeError, TypeError):
            raise ValueError("document id must be a UUID") from None
        object.__setattr__(self, "value", value)

    def __str__(self) -> str:
        return self.value


class DocumentStatus(StrEnum):
    STAGED = "staged"
    ATTACHED = "attached"
    QUARANTINED = "quarantined"
    REMOVED = "removed"
    GENERATED_UNSIGNED = "generated_unsigned"
    SIGNED_OWNER_ATTESTED = "signed_owner_attested"
    MISSING_ACCEPTED = "missing_accepted"
    MISSING_ACCEPTED_WARNING = "missing_accepted_warning"
    NOT_REQUIRED = "not_required"
    STORED = "stored"


class DocumentTransferKind(StrEnum):
    PREVIEW = "preview"
    DOWNLOAD = "download"


class DocumentErrorCode(StrEnum):
    INVALID_INPUT = "DOCUMENT_INVALID_INPUT"
    FORBIDDEN = "DOCUMENT_FORBIDDEN"
    NOT_FOUND = "DOCUMENT_NOT_FOUND"
    CONFLICT = "DOCUMENT_CONFLICT"
    EVIDENCE_LINKED = "DOCUMENT_EVIDENCE_LINKED"
    INTEGRITY_FAILED = "DOCUMENT_INTEGRITY_FAILED"
    STEP_UP_REQUIRED = "DOCUMENT_STEP_UP_REQUIRED"
    STORAGE_UNAVAILABLE = "DOCUMENT_STORAGE_UNAVAILABLE"


class DocumentsError(DomainError):
    @classmethod
    def invalid_input(cls) -> DocumentsError:
        return cls(code=DocumentErrorCode.INVALID_INPUT, category=ErrorCategory.INVALID_INPUT, message="Document input is invalid.")

    @classmethod
    def forbidden(cls) -> DocumentsError:
        return cls(code=DocumentErrorCode.FORBIDDEN, category=ErrorCategory.FORBIDDEN, message="Document access is not allowed.")

    @classmethod
    def not_found(cls) -> DocumentsError:
        return cls(code=DocumentErrorCode.NOT_FOUND, category=ErrorCategory.NOT_FOUND, message="Document was not found.")

    @classmethod
    def conflict(cls) -> DocumentsError:
        return cls(code=DocumentErrorCode.CONFLICT, category=ErrorCategory.CONFLICT, message="Document state conflicts with the request.")

    @classmethod
    def evidence_linked(cls) -> DocumentsError:
        return cls(code=DocumentErrorCode.EVIDENCE_LINKED, category=ErrorCategory.PRECONDITION_FAILED, message="Document is linked evidence and cannot be removed.")

    @classmethod
    def integrity_failed(cls) -> DocumentsError:
        return cls(code=DocumentErrorCode.INTEGRITY_FAILED, category=ErrorCategory.PRECONDITION_FAILED, message="Document integrity could not be verified.")

    @classmethod
    def step_up_required(cls) -> DocumentsError:
        return cls(code=DocumentErrorCode.STEP_UP_REQUIRED, category=ErrorCategory.FORBIDDEN, message="Fresh step-up authentication is required.")

    @classmethod
    def storage_unavailable(cls) -> DocumentsError:
        return cls(code=DocumentErrorCode.STORAGE_UNAVAILABLE, category=ErrorCategory.DEPENDENCY_UNAVAILABLE, message="Private document storage is unavailable.")


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    document_id: DocumentId
    company_id: CompanyId
    income_year: IncomeYear
    document_type: str
    name: str
    linked_to: str
    status: DocumentStatus
    retention_years: int
    storage_key: str
    content_type: str
    byte_length: int | None
    content_sha256: str | None
    created_by: ActorId
    created_at: datetime
    removed_at: datetime | None
    removal_reason: str | None


@dataclass(frozen=True, slots=True)
class BeginDocumentUploadCommand:
    company_id: CompanyId
    income_year: IncomeYear
    document_id: DocumentId
    document_type: str
    linked_to: str
    file_name: str
    content_type: str
    byte_length: int
    header: bytes
    final_status: DocumentStatus = DocumentStatus.ATTACHED


@dataclass(frozen=True, slots=True)
class DocumentUploadTransfer:
    document: DocumentRecord
    bucket: str
    storage_key: str
    token: str
    signed_url: str


@dataclass(frozen=True, slots=True)
class DocumentObjectTransfer:
    document: DocumentRecord
    kind: DocumentTransferKind
    signed_url: str
    expires_in_seconds: int


@dataclass(frozen=True, slots=True)
class StoredDocumentObject:
    content: bytes
    content_type: str


@dataclass(frozen=True, slots=True)
class DocumentBackupObject:
    document_id: DocumentId
    document_type: str
    name: str
    linked_to: str
    storage_key: str
    status: DocumentStatus
    retention_years: int
    content_type: str
    byte_length: int | None
    content_sha256: str | None
    created_by: ActorId
    created_at: datetime
    removed_at: datetime | None
    removal_reason: str | None


@dataclass(frozen=True, slots=True)
class DocumentRestoreObject:
    document: DocumentBackupObject
    target_storage_key: str


@dataclass(frozen=True, slots=True)
class DocumentRestorePlan:
    source_company_id: CompanyId
    target_company_id: CompanyId
    income_year: IncomeYear
    objects: tuple[DocumentRestoreObject, ...]
    projection_sha256: str


class DocumentsPersistence(Protocol):
    @property
    def actor_id(self) -> ActorId: ...

    @property
    def aal2(self) -> bool: ...

    async def actor_role(self, company_id: CompanyId) -> str | None: ...
    async def stage_upload(self, command: BeginDocumentUploadCommand, *, name: str, storage_key: str) -> DocumentRecord: ...
    async def quarantine_upload(self, document_id: DocumentId, reason: str) -> None: ...
    async def finalize_upload(self, document_id: DocumentId, *, byte_length: int, content_sha256: str) -> DocumentRecord: ...
    async def get_document(self, document_id: DocumentId) -> DocumentRecord | None: ...
    async def list_documents(self, company_ids: tuple[CompanyId, ...]) -> tuple[DocumentRecord, ...]: ...
    async def has_evidence_references(self, document_id: DocumentId) -> bool: ...
    async def mark_removed(self, document_id: DocumentId, *, reason: str) -> DocumentRecord: ...
    async def restore_after_storage_failure(self, document_id: DocumentId) -> None: ...


class DocumentObjectStorage(Protocol):
    async def create_upload_transfer(self, *, bucket: str, storage_key: str) -> tuple[str, str]: ...
    async def read_object(self, *, bucket: str, storage_key: str) -> StoredDocumentObject: ...
    async def create_download_transfer(self, *, bucket: str, storage_key: str, expires_in_seconds: int) -> str: ...
    async def remove_object(self, *, bucket: str, storage_key: str) -> None: ...


class DocumentsAuthorization(Protocol):
    async def accepted_roles(self, access_token: str) -> Mapping[CompanyId, str]: ...


class DocumentsSession(Protocol):
    @property
    def actor_id(self) -> ActorId: ...

    async def begin_upload(self, command: BeginDocumentUploadCommand) -> DocumentUploadTransfer: ...
    async def finalize_upload(self, document_id: DocumentId) -> DocumentRecord: ...
    async def list_documents(self, company_ids: tuple[CompanyId, ...]) -> tuple[DocumentRecord, ...]: ...
    async def create_transfer(self, document_id: DocumentId, kind: DocumentTransferKind) -> DocumentObjectTransfer: ...
    async def remove_document(self, document_id: DocumentId, *, reason: str) -> DocumentRecord: ...
    async def backup_projection(self, company_id: CompanyId, income_year: IncomeYear) -> tuple[DocumentBackupObject, ...]: ...
    async def prepare_isolated_restore(
        self,
        company_id: CompanyId,
        income_year: IncomeYear,
        target_company_id: CompanyId,
    ) -> DocumentRestorePlan: ...


class DocumentsSessionFactory(Protocol):
    async def session(self, access_token: str) -> DocumentsSession: ...


DocumentsAdapter = TypeVar("DocumentsAdapter", bound=type[object])


def documents_persistence_adapter(
    contract: type[object],
) -> Callable[[DocumentsAdapter], DocumentsAdapter]:
    """Declare a document-metadata adapter without registering global state."""

    def declare(adapter: DocumentsAdapter) -> DocumentsAdapter:
        _ = contract
        return adapter

    return declare


DocumentStorageAdapter = TypeVar("DocumentStorageAdapter", bound=type[object])


def document_object_storage_adapter(
    contract: type[object],
) -> Callable[[DocumentStorageAdapter], DocumentStorageAdapter]:
    """Declare a private-object adapter without registering global state."""

    def declare(adapter: DocumentStorageAdapter) -> DocumentStorageAdapter:
        _ = contract
        return adapter

    return declare


DocumentsAuthorizationAdapter = TypeVar("DocumentsAuthorizationAdapter", bound=type[object])


def documents_authorization_adapter(
    contract: type[object],
) -> Callable[[DocumentsAuthorizationAdapter], DocumentsAuthorizationAdapter]:
    """Declare the accepted-membership fact adapter used by document policy."""

    def declare(adapter: DocumentsAuthorizationAdapter) -> DocumentsAuthorizationAdapter:
        _ = contract
        return adapter

    return declare




@dataclass(frozen=True, slots=True)
class DocumentBindingQuery:
    actor_id: ActorId
    company_id: CompanyId
    income_year: IncomeYear
    document_id: DocumentId


class DocumentBindingPersistence(Protocol):
    async def lock_document_binding(self, query: DocumentBindingQuery) -> None:
        """Lock a same-company/year metadata reference until its caller commits."""
        ...


def document_binding_persistence_adapter(
    contract: type[object],
) -> Callable[[DocumentsAdapter], DocumentsAdapter]:
    def declare(adapter: DocumentsAdapter) -> DocumentsAdapter:
        _ = contract
        return adapter
    return declare


__all__ = [
    "BeginDocumentUploadCommand",
    "DocumentBackupObject",
    "DocumentErrorCode",
    "DocumentId",
    "DocumentObjectStorage",
    "DocumentObjectTransfer",
    "DocumentRecord",
    "DocumentRestoreObject",
    "DocumentRestorePlan",
    "DocumentsError",
    "DocumentsAuthorization",
    "DocumentsPersistence",
    "DocumentsSession",
    "DocumentsSessionFactory",
    "DocumentStatus",
    "DocumentTransferKind",
    "DocumentUploadTransfer",
    "StoredDocumentObject",
    "document_object_storage_adapter",
    "documents_authorization_adapter",
    "documents_persistence_adapter",
    "DocumentBindingQuery",
    "DocumentBindingPersistence",
    "document_binding_persistence_adapter"
]
