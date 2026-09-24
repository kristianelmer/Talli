from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
from hashlib import sha256

import pytest
from types import SimpleNamespace

from talli_backend.adapters.supabase_documents import (
    SupabaseDocumentObjectStorage,
    SupabaseDocumentsAdapter,
    SupabaseDocumentsAuthorization,
    SupabaseDocumentsPersistence,
    _document,
)
from talli_backend.modules.documents.public import (
    BeginDocumentUploadCommand,
    DocumentId,
    DocumentStatus,
    DocumentsError,
    StoredDocumentObject,
    RetainedDocumentOriginalReceipt, document_metadata_sha256,
)
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, UserId


COMPANY_ID = CompanyId("10000000-0000-4000-8000-000000000001")
DOCUMENT_ID = DocumentId("20000000-0000-4000-8000-000000000001")
USER_ID = UserId("30000000-0000-4000-8000-000000000001")
ACTOR = ActorId(ActorKind.USER, USER_ID)


def row() -> dict[str, object]:
    return {
        "id": str(DOCUMENT_ID),
        "company_id": str(COMPANY_ID),
        "income_year": 2026,
        "document_type": "accounting_document",
        "name": "Bilag.pdf",
        "linked_to": "workspace",
        "status": "attached",
        "retention_years": 5,
        "storage_key": f"{COMPANY_ID}/2026/{DOCUMENT_ID}/Bilag.pdf",
        "content_type": "application/pdf",
        "byte_length": 10,
        "content_sha256": "a" * 64,
        "created_by": str(USER_ID),
        "created_at": datetime(2026, 9, 1, tzinfo=UTC),
        "removed_at": None,
        "removal_reason": None,
    }


def test_row_mapping_keeps_capability_types_at_the_adapter_boundary() -> None:
    value = _document(row())
    assert value.document_id == DOCUMENT_ID
    assert value.company_id == COMPANY_ID
    assert value.status is DocumentStatus.ATTACHED
    assert value.created_by == ACTOR


def test_object_storage_adapter_uses_only_exact_bucket_and_key_requests() -> None:
    adapter = SupabaseDocumentObjectStorage("https://supabase.invalid", "service-key")
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def request(method: str, path: str, payload: dict[str, object] | None = None):
        calls.append((method, path, payload))
        if "/upload/sign/" in path:
            return json.dumps({"token": "token", "url": "/object/upload/sign/exact"}).encode(), "application/json"
        if method == "GET":
            return b"%PDF-data", "application/pdf"
        if "/object/sign/" in path:
            return json.dumps({"signedURL": "/object/sign/exact"}).encode(), "application/json"
        return b"{}", "application/json"

    adapter._request_sync = request  # type: ignore[method-assign]
    key = f"{COMPANY_ID}/2026/{DOCUMENT_ID}/Bilag.pdf"
    signed_url, token = asyncio.run(adapter.create_upload_transfer(bucket="company-documents", storage_key=key))
    stored = asyncio.run(adapter.read_object(bucket="company-documents", storage_key=key))
    download = asyncio.run(adapter.create_download_transfer(
        bucket="company-documents", storage_key=key, expires_in_seconds=300,
    ))
    asyncio.run(adapter.remove_object(bucket="company-documents", storage_key=key))

    assert token == "token"
    assert signed_url.endswith("/storage/v1/object/upload/sign/exact")
    assert stored.content == b"%PDF-data"
    assert download.endswith("/storage/v1/object/sign/exact")
    assert calls[-1] == ("DELETE", "/storage/v1/object/company-documents", {"prefixes": [key]})
    assert all("list" not in path for _, path, _ in calls)


def test_persistence_adapter_calls_only_restricted_documents_functions() -> None:
    verified = SimpleNamespace(actor_id=ACTOR, claims_json='{"aal":"aal2"}')
    adapter = SupabaseDocumentsPersistence("postgresql://unused", verified, {COMPANY_ID: "owner"})
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def rows(query: str, parameters: tuple[object, ...]):
        calls.append((query, parameters))
        return [row()]

    adapter._rows = rows  # type: ignore[method-assign]
    command = BeginDocumentUploadCommand(
        company_id=COMPANY_ID,
        income_year=IncomeYear(2026),
        document_id=DOCUMENT_ID,
        document_type="accounting_document",
        linked_to="workspace",
        file_name="Bilag.pdf",
        content_type="application/pdf",
        byte_length=10,
        header=b"%PDF-",
    )
    staged = asyncio.run(adapter.stage_upload(
        command,
        name="Bilag.pdf",
        storage_key=f"{COMPANY_ID}/2026/{DOCUMENT_ID}/Bilag.pdf",
    ))
    assert staged.document_id == DOCUMENT_ID
    assert adapter.aal2 is True
    assert calls[0][0].startswith("select * from documents.stage_upload_v1")
    payload = json.loads(str(calls[0][1][0]))
    assert payload["storageKey"].endswith("/Bilag.pdf")
    assert payload["finalStatus"] == "attached"
    assert ".from(" not in calls[0][0]


def test_authorization_adapter_passes_only_accepted_supported_membership_facts() -> None:
    class Gateway:
        async def session_subject(self, access_token: str) -> str:
            assert access_token == "bearer"
            return str(USER_ID)

        async def memberships(self, access_token: str, subject: str):
            assert access_token == "bearer"
            assert subject == str(USER_ID)
            return [
                {"company_id": str(COMPANY_ID), "role": "owner", "accepted_at": "2026-09-01T00:00:00Z"},
                {"company_id": "10000000-0000-4000-8000-000000000002", "role": "reviewer", "accepted_at": None},
                {"company_id": "10000000-0000-4000-8000-000000000003", "role": "operator", "accepted_at": "2026-09-01T00:00:00Z"},
            ]

    roles = asyncio.run(SupabaseDocumentsAuthorization(Gateway()).accepted_roles("bearer"))  # type: ignore[arg-type]
    assert roles == {COMPANY_ID: "owner"}


def test_documents_adapter_keeps_authorization_and_persistence_connections_separate(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://supabase.invalid")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setenv("TALLI_COMPANY_ACCESS_DATABASE_URL", "postgresql://company-access")
    monkeypatch.setenv("TALLI_LEDGER_DATABASE_URL", "postgresql://documents")

    adapter = SupabaseDocumentsAdapter.from_environment()

    assert adapter._configuration.database_url == "postgresql://documents"
    assert (
        adapter._authorization._gateway._configuration.database_url
        == "postgresql://company-access"
    )


@pytest.mark.parametrize("change", ["revoked_before_read", "revoked_during_read", "unavailable_during_read", "unchanged"])
def test_verified_evidence_refreshes_real_adapter_authorization_around_object_io(change):
    # Use the real session factory, persistence and authorization adapters. Only
    # their external authentication, Company Access gateway, DB and storage I/O
    # are replaced; in particular actor_role retains its real cached behavior.
    adapter = SupabaseDocumentsAdapter.from_environment()
    class Authentication:
        async def session(self, access_token):
            assert access_token == "bearer"
            return SimpleNamespace(_verified=SimpleNamespace(actor_id=ACTOR, claims_json='{"aal":"aal2"}'))
    class Gateway:
        revoked = False
        unavailable = False
        membership_reads = 0
        async def session_subject(self, access_token):
            assert access_token == "bearer"
            return str(USER_ID)
        async def memberships(self, access_token, subject):
            assert access_token == "bearer" and subject == str(USER_ID)
            self.membership_reads += 1
            if self.unavailable:
                raise DocumentsError.storage_unavailable()
            return [] if self.revoked else [{"company_id": str(COMPANY_ID), "role": "owner", "accepted_at": "2026-09-01T00:00:00Z"}]
    gateway = Gateway()
    adapter._authentication = Authentication()
    adapter._authorization = SupabaseDocumentsAuthorization(gateway)
    content = b"%PDF-1.7\nverified"
    reads = []
    class Storage:
        async def read_object(self, *, bucket, storage_key):
            reads.append(storage_key)
            if change == "revoked_during_read": gateway.revoked = True
            if change == "unavailable_during_read": gateway.unavailable = True
            return StoredDocumentObject(content, "application/pdf")
    adapter._storage = Storage()
    async def verify():
        service = await adapter.session("bearer")
        assert await service._persistence.actor_role(COMPANY_ID) == "owner"
        async def rows(query, parameters):
            assert query.startswith("select * from documents.get_document_v1")
            assert parameters == (str(DOCUMENT_ID), str(USER_ID))
            return [row() | {"byte_length": len(content), "content_sha256": sha256(content).hexdigest()}]
        service._persistence._rows = rows
        if change == "revoked_before_read": gateway.revoked = True
        if change == "unchanged":
            async def retain(document, original):
                assert original == content
                return RetainedDocumentOriginalReceipt("40000000-0000-4000-8000-000000000001", document.document_id,
                    document.company_id, document.income_year, document_metadata_sha256(document), document.content_sha256,
                    document.byte_length, datetime(2026, 9, 24, tzinfo=UTC))
            service._persistence.retain_verified_original = retain
            evidence = await service.verify_document_evidence(DOCUMENT_ID)
            assert evidence.content_sha256 == sha256(content).hexdigest()
            assert evidence.integrity_status is DocumentStatus.ATTACHED
        else:
            with pytest.raises(DocumentsError) as error:
                await service.verify_document_evidence(DOCUMENT_ID)
            assert error.value.code == ("DOCUMENT_STORAGE_UNAVAILABLE" if change == "unavailable_during_read" else "DOCUMENT_FORBIDDEN")
            assert await service._persistence.actor_role(COMPANY_ID) is None
    asyncio.run(verify())
    assert len(reads) == (0 if change == "revoked_before_read" else 1)
    assert gateway.membership_reads == (2 if change == "revoked_before_read" else 3)


def test_evidence_role_refresh_cannot_fall_back_to_cached_owner_without_live_binding():
    verified = SimpleNamespace(actor_id=ACTOR, claims_json='{"aal":"aal2"}')
    persistence = SupabaseDocumentsPersistence("postgresql://unused", verified, {COMPANY_ID: "owner"})
    assert asyncio.run(persistence.actor_role(COMPANY_ID)) == "owner"
    with pytest.raises(DocumentsError) as error:
        asyncio.run(persistence.refresh_actor_role(COMPANY_ID))
    assert error.value.code == "DOCUMENT_STORAGE_UNAVAILABLE"
    assert asyncio.run(persistence.actor_role(COMPANY_ID)) is None
