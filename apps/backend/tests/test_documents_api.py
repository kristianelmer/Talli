from __future__ import annotations

from base64 import b64encode
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from talli_backend.main import create_app
from talli_backend.modules.documents.public import (
    DocumentBackupObject,
    DocumentId,
    DocumentObjectTransfer,
    DocumentRecord,
    DocumentStatus,
    DocumentTransferKind,
    DocumentUploadTransfer,
)
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, UserId


ACTOR = ActorId(ActorKind.USER, UserId("30000000-0000-4000-8000-000000000001"))
COMPANY = CompanyId("10000000-0000-4000-8000-000000000001")
DOCUMENT = DocumentId("20000000-0000-4000-8000-000000000001")


def document(status: DocumentStatus = DocumentStatus.ATTACHED) -> DocumentRecord:
    return DocumentRecord(
        document_id=DOCUMENT,
        company_id=COMPANY,
        income_year=IncomeYear(2026),
        document_type="accounting_document",
        name="Bilag.pdf",
        linked_to="workspace",
        status=status,
        retention_years=5,
        storage_key=f"{COMPANY}/2026/{DOCUMENT}/Bilag.pdf",
        content_type="application/pdf",
        byte_length=16,
        content_sha256="a" * 64,
        created_by=ACTOR,
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
        removed_at=None,
        removal_reason=None,
    )


class DocumentsStub:
    actor_id = ACTOR

    def __init__(self) -> None:
        self.tokens: list[str] = []
        self.commands: list[object] = []

    async def session(self, token: str):
        self.tokens.append(token)
        return self

    async def begin_upload(self, command):
        self.commands.append(command)
        return DocumentUploadTransfer(
            document(DocumentStatus.STAGED), "company-documents",
            document().storage_key, "signed-token", "https://storage.invalid/upload",
        )

    async def finalize_upload(self, document_id):
        self.commands.append(document_id)
        return document()

    async def list_documents(self, company_ids):
        self.commands.append(company_ids)
        return (document(),)

    async def create_transfer(self, document_id, kind):
        self.commands.append((document_id, kind))
        return DocumentObjectTransfer(document(), kind, "https://storage.invalid/download", 300)

    async def remove_document(self, document_id, *, reason):
        self.commands.append((document_id, reason))
        return document(DocumentStatus.REMOVED)

    async def backup_projection(self, company_id, income_year):
        self.commands.append((company_id, income_year))
        item = document()
        return (DocumentBackupObject(
            item.document_id, item.document_type, item.name, item.linked_to,
            item.storage_key, item.status, item.retention_years,
            item.content_type, item.byte_length, item.content_sha256,
            item.created_by, item.created_at, item.removed_at, item.removal_reason,
        ),)


def client(stub: DocumentsStub) -> TestClient:
    return TestClient(create_app(documents_session_factory=stub))


def headers() -> dict[str, str]:
    return {"Authorization": "Bearer owner-token", "X-Request-ID": "documents-test"}


def test_begin_and_finalize_upload_use_typed_fastapi_contract() -> None:
    stub = DocumentsStub()
    response = client(stub).post(
        "/api/v1/documents/uploads",
        headers=headers(),
        json={
            "companyId": str(COMPANY), "incomeYear": 2026,
            "documentId": str(DOCUMENT), "documentType": "accounting_document",
            "linkedTo": "workspace", "fileName": "Bilag.pdf",
            "contentType": "application/pdf", "byteLength": 16,
            "headerBase64": b64encode(b"%PDF-").decode(),
        },
    )
    assert response.status_code == 201
    assert response.json()["bucket"] == "company-documents"
    assert response.json()["document"]["status"] == "staged"
    assert stub.tokens == ["owner-token"]
    assert stub.commands[0].header == b"%PDF-"

    finalized = client(stub).post(
        f"/api/v1/documents/{DOCUMENT}/finalize", headers=headers()
    )
    assert finalized.status_code == 200
    assert finalized.json()["contentSha256"] == "a" * 64


def test_list_transfer_remove_and_backup_are_backend_owned() -> None:
    stub = DocumentsStub()
    api = client(stub)
    listed = api.get(
        "/api/v1/documents", headers=headers(), params=[("companyId", str(COMPANY))]
    )
    assert listed.status_code == 200
    assert listed.json()["documents"][0]["id"] == str(DOCUMENT)

    transfer = api.post(
        f"/api/v1/documents/{DOCUMENT}/transfers",
        headers=headers(), json={"kind": "download"},
    )
    assert transfer.status_code == 200
    assert transfer.json()["expiresInSeconds"] == 300

    removed = api.post(
        f"/api/v1/documents/{DOCUMENT}/remove",
        headers=headers(), json={"reason": "owner_requested"},
    )
    assert removed.status_code == 200
    assert removed.json()["status"] == "removed"

    backup = api.get(
        "/api/v1/documents/backup-projection",
        headers=headers(), params={"company_id": str(COMPANY), "income_year": 2026},
    )
    assert backup.status_code == 200
    assert backup.json()["objects"][0]["contentSha256"] == "a" * 64


def test_documents_require_bearer_authentication() -> None:
    response = client(DocumentsStub()).get(
        "/api/v1/documents", params=[("companyId", str(COMPANY))]
    )
    assert response.status_code == 401
    assert response.json()["code"] == "AUTHENTICATION_REQUIRED"
