"""Supabase persistence and object-storage adapters for accounting documents."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import psycopg
from psycopg.rows import dict_row

from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration, SupabaseLedgerAdapter
from talli_backend.adapters.supabase_company_access import SupabaseCompanyAccessAdapter, SupabaseConfiguration
from talli_backend.application.ledger_session import LedgerAuthenticationError
from talli_backend.modules.company_access.public import CompanyAccessError, CompanyAccessGateway
from talli_backend.modules.documents.public import (
    BeginDocumentUploadCommand,
    DocumentId,
    DocumentObjectStorage,
    DocumentRecord,
    DocumentsError,
    DocumentsAuthorization,
    DocumentsPersistence,
    DocumentsSessionFactory,
    DocumentStatus,
    StoredDocumentObject,
    RetainedDocumentOriginal, RetainedDocumentOriginalReceipt,
    document_object_storage_adapter,
    documents_authorization_adapter,
    documents_persistence_adapter,
)
from talli_backend.modules.documents.service import DocumentsService
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, Timestamp, UserId


@dataclass(frozen=True, slots=True)
class DocumentsSupabaseConfiguration:
    url: str
    anon_key: str
    service_role_key: str
    database_url: str
    company_access_database_url: str


def _document(row: dict[str, Any]) -> DocumentRecord:
    created_at = row["created_at"]
    removed_at = row.get("removed_at")
    return DocumentRecord(
        document_id=DocumentId(str(row["id"])),
        company_id=CompanyId(str(row["company_id"])),
        income_year=IncomeYear(int(row["income_year"])),
        document_type=str(row["document_type"]),
        name=str(row["name"]),
        linked_to=str(row["linked_to"]),
        status=DocumentStatus(str(row["status"])),
        retention_years=int(row["retention_years"]),
        storage_key=str(row["storage_key"]),
        content_type=str(row.get("content_type") or "application/pdf"),
        byte_length=(int(row["byte_length"]) if row.get("byte_length") is not None else None),
        content_sha256=(str(row["content_sha256"]) if row.get("content_sha256") else None),
        created_by=ActorId(ActorKind.USER, UserId(str(row["created_by"]))),
        created_at=Timestamp(created_at if created_at.tzinfo else created_at.replace(tzinfo=UTC)).value,
        removed_at=(Timestamp(removed_at if removed_at.tzinfo else removed_at.replace(tzinfo=UTC)).value if removed_at else None),
        removal_reason=(str(row["removal_reason"]) if row.get("removal_reason") else None),
    )


@document_object_storage_adapter(DocumentObjectStorage)
class SupabaseDocumentObjectStorage(DocumentObjectStorage):
    """Policy-free HTTP adapter for one exact private object at a time."""

    def __init__(self, url: str, service_role_key: str) -> None:
        self._url = url.rstrip("/")
        self._key = service_role_key

    def _request_sync(self, method: str, path: str, payload: dict[str, object] | None = None) -> tuple[bytes, str]:
        if not self._url or not self._key:
            raise DocumentsError.storage_unavailable()
        body = json.dumps(payload).encode() if payload is not None else None
        request = Request(
            f"{self._url}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self._key}",
                "apikey": self._key,
                **({"Content-Type": "application/json"} if body is not None else {}),
            },
        )
        try:
            with urlopen(request, timeout=15) as response:
                return response.read(), response.headers.get_content_type()
        except (HTTPError, URLError, TimeoutError):
            raise DocumentsError.storage_unavailable() from None

    async def create_upload_transfer(self, *, bucket: str, storage_key: str) -> tuple[str, str]:
        path = f"/storage/v1/object/upload/sign/{quote(bucket)}/{quote(storage_key, safe='/')}"
        raw, _ = await asyncio.to_thread(self._request_sync, "POST", path, {})
        try:
            response = json.loads(raw)
            token = str(response["token"])
            signed_url = str(response.get("url") or response.get("signedURL") or "")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise DocumentsError.storage_unavailable() from None
        if not token or not signed_url:
            raise DocumentsError.storage_unavailable()
        if signed_url.startswith("/"):
            signed_url = f"{self._url}/storage/v1{signed_url}"
        return signed_url, token

    async def read_object(self, *, bucket: str, storage_key: str) -> StoredDocumentObject:
        path = f"/storage/v1/object/authenticated/{quote(bucket)}/{quote(storage_key, safe='/')}"
        raw, content_type = await asyncio.to_thread(self._request_sync, "GET", path)
        return StoredDocumentObject(raw, content_type)

    async def create_download_transfer(self, *, bucket: str, storage_key: str, expires_in_seconds: int) -> str:
        path = f"/storage/v1/object/sign/{quote(bucket)}/{quote(storage_key, safe='/')}"
        raw, _ = await asyncio.to_thread(
            self._request_sync, "POST", path, {"expiresIn": expires_in_seconds}
        )
        try:
            response = json.loads(raw)
            signed_url = str(response.get("signedURL") or response.get("signedUrl") or "")
        except (TypeError, ValueError, json.JSONDecodeError):
            raise DocumentsError.storage_unavailable() from None
        if not signed_url:
            raise DocumentsError.storage_unavailable()
        return f"{self._url}/storage/v1{signed_url}" if signed_url.startswith("/") else signed_url

    async def remove_object(self, *, bucket: str, storage_key: str) -> None:
        path = f"/storage/v1/object/{quote(bucket)}"
        await asyncio.to_thread(self._request_sync, "DELETE", path, {"prefixes": [storage_key]})


@documents_persistence_adapter(DocumentsPersistence)
class SupabaseDocumentsPersistence(DocumentsPersistence):
    def __init__(self, database_url: str, verified: Any, roles: dict[CompanyId, str], *,
                 role_refresher: Callable[[], Awaitable[Mapping[CompanyId, str]]] | None = None) -> None:
        self._database_url = database_url
        self._verified = verified
        self._roles = roles
        self._role_refresher = role_refresher

    @property
    def actor_id(self) -> ActorId:
        return self._verified.actor_id

    @property
    def aal2(self) -> bool:
        try:
            claims = json.loads(self._verified.claims_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            return False
        return claims.get("aal") == "aal2"

    @asynccontextmanager
    async def _transaction(self):
        if not self._database_url:
            raise DocumentsError.storage_unavailable()
        try:
            async with await psycopg.AsyncConnection.connect(
                self._database_url, connect_timeout=5, row_factory=dict_row,
                options="-c statement_timeout=5000 -c lock_timeout=1000",
            ) as connection, connection.transaction():
                await connection.execute("set local role documents_executor")
                await connection.execute(
                    "select pg_catalog.set_config('talli.verified_actor_id', %s, true)",
                    (str(self.actor_id.subject),),
                )
                await connection.execute(
                    "select pg_catalog.set_config('talli.verified_actor_claims', %s, true)",
                    (self._verified.claims_json,),
                )
                await connection.execute(
                    "select pg_catalog.set_config('talli.authorized_company_roles', %s, true)",
                    (json.dumps({str(key): value for key, value in self._roles.items()}),),
                )
                yield connection
        except DocumentsError:
            raise
        except psycopg.OperationalError:
            raise DocumentsError.storage_unavailable() from None
        except psycopg.DatabaseError as error:
            message = str(error)
            if "documents_forbidden" in message:
                raise DocumentsError.forbidden() from None
            if "documents_invalid_input" in message:
                raise DocumentsError.invalid_input() from None
            if "documents_not_found" in message:
                raise DocumentsError.not_found() from None
            if "documents_evidence_linked" in message:
                raise DocumentsError.evidence_linked() from None
            if "documents_conflict" in message or "documents_evidence_mismatch" in message:
                raise DocumentsError.conflict() from None
            raise DocumentsError.storage_unavailable() from None

    async def _rows(self, query: str, parameters: tuple[object, ...]) -> list[dict[str, Any]]:
        async with self._transaction() as connection:
            cursor = await connection.execute(query, parameters)
            return [dict(row) for row in await cursor.fetchall()]

    async def retain_verified_original(self, document: DocumentRecord, content: bytes) -> RetainedDocumentOriginalReceipt:
        from talli_backend.adapters.postgres_document_originals import PostgresDocumentOriginals
        async with self._transaction() as connection:
            return await PostgresDocumentOriginals(connection, self.actor_id).retain_verified_original(document, content)

    async def read_retained_original(self, original_id: str, company_id: CompanyId) -> RetainedDocumentOriginal:
        from talli_backend.adapters.postgres_document_originals import PostgresDocumentOriginals
        async with self._transaction() as connection:
            return await PostgresDocumentOriginals(connection, self.actor_id).read_retained_original(original_id, company_id)

    async def actor_role(self, company_id: CompanyId) -> str | None:
        return self._roles.get(company_id)

    async def refresh_actor_role(self, company_id: CompanyId) -> str | None:
        # Evidence verification explicitly requests live accepted membership.
        # Never reuse a stale owner after a refresh fails or access is revoked.
        self._roles = {}
        if self._role_refresher is None:
            raise DocumentsError.storage_unavailable()
        self._roles = dict(await self._role_refresher())
        return self._roles.get(company_id)

    async def stage_upload(self, command: BeginDocumentUploadCommand, *, name: str, storage_key: str) -> DocumentRecord:
        payload = {
            "documentId": str(command.document_id), "companyId": str(command.company_id),
            "incomeYear": int(command.income_year), "documentType": command.document_type,
            "linkedTo": command.linked_to, "name": name, "storageKey": storage_key,
            "contentType": command.content_type.split(";", 1)[0] or "application/octet-stream",
            "declaredByteLength": command.byte_length, "finalStatus": command.final_status.value,
        }
        rows = await self._rows(
            "select * from documents.stage_upload_v1(%s::jsonb, %s)",
            (json.dumps(payload), str(self.actor_id.subject)),
        )
        return _document(rows[0])

    async def quarantine_upload(self, document_id: DocumentId, reason: str) -> None:
        await self._rows(
            "select documents.quarantine_upload_v1(%s, %s, %s)",
            (str(document_id), reason, str(self.actor_id.subject)),
        )

    async def finalize_upload(self, document_id: DocumentId, *, byte_length: int, content_sha256: str) -> DocumentRecord:
        rows = await self._rows(
            "select * from documents.finalize_upload_v1(%s, %s, %s, %s)",
            (str(document_id), byte_length, content_sha256, str(self.actor_id.subject)),
        )
        return _document(rows[0])

    async def get_document(self, document_id: DocumentId) -> DocumentRecord | None:
        rows = await self._rows(
            "select * from documents.get_document_v1(%s, %s)",
            (str(document_id), str(self.actor_id.subject)),
        )
        return _document(rows[0]) if rows else None

    async def list_documents(self, company_ids: tuple[CompanyId, ...]) -> tuple[DocumentRecord, ...]:
        rows = await self._rows(
            "select * from documents.list_documents_v1(%s::uuid[], %s)",
            ([str(value) for value in company_ids], str(self.actor_id.subject)),
        )
        return tuple(_document(row) for row in rows)

    async def has_evidence_references(self, document_id: DocumentId) -> bool:
        rows = await self._rows(
            "select documents.has_evidence_references_v1(%s) as linked", (str(document_id),)
        )
        return bool(rows[0]["linked"])

    async def mark_removed(self, document_id: DocumentId, *, reason: str) -> DocumentRecord:
        rows = await self._rows(
            "select * from documents.mark_removed_v1(%s, %s, %s)",
            (str(document_id), reason, str(self.actor_id.subject)),
        )
        return _document(rows[0])

    async def restore_after_storage_failure(self, document_id: DocumentId) -> None:
        await self._rows(
            "select documents.restore_after_storage_failure_v1(%s, %s)",
            (str(document_id), str(self.actor_id.subject)),
        )


@documents_authorization_adapter(DocumentsAuthorization)
class SupabaseDocumentsAuthorization(DocumentsAuthorization):
    def __init__(self, gateway: CompanyAccessGateway) -> None:
        self._gateway = gateway

    async def accepted_roles(self, access_token: str) -> dict[CompanyId, str]:
        try:
            subject = await self._gateway.session_subject(access_token)
            memberships = await self._gateway.memberships(access_token, subject)
        except CompanyAccessError:
            raise DocumentsError.forbidden() from None
        return {
            CompanyId(str(item["company_id"])): str(item["role"])
            for item in memberships
            if item.get("accepted_at") is not None
            and item.get("role") in {"owner", "reviewer", "read_only"}
        }


class SupabaseDocumentsAdapter(DocumentsSessionFactory):
    def __init__(self, configuration: DocumentsSupabaseConfiguration) -> None:
        self._configuration = configuration
        self._authentication = SupabaseLedgerAdapter(
            LedgerSupabaseConfiguration(
                url=configuration.url,
                anon_key=configuration.anon_key,
                database_url=configuration.database_url,
            )
        )
        self._storage = SupabaseDocumentObjectStorage(configuration.url, configuration.service_role_key)
        self._authorization = SupabaseDocumentsAuthorization(SupabaseCompanyAccessAdapter(
            SupabaseConfiguration(
                url=configuration.url,
                anon_key=configuration.anon_key,
                database_url=configuration.company_access_database_url,
            )
        ))

    @classmethod
    def from_environment(cls) -> SupabaseDocumentsAdapter:
        return cls(DocumentsSupabaseConfiguration(
            url=os.environ.get("SUPABASE_URL", ""),
            anon_key=os.environ.get("SUPABASE_ANON_KEY", ""),
            service_role_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
            database_url=os.environ.get("TALLI_LEDGER_DATABASE_URL", ""),
            company_access_database_url=os.environ.get(
                "TALLI_COMPANY_ACCESS_DATABASE_URL", ""
            ),
        ))

    async def session(self, access_token: str) -> DocumentsService:
        try:
            ledger_session = await self._authentication.session(access_token)
        except LedgerAuthenticationError:
            raise DocumentsError.forbidden() from None
        async def refresh_roles():
            return await self._authorization.accepted_roles(access_token)
        roles = dict(await refresh_roles())
        return DocumentsService(
            SupabaseDocumentsPersistence(
                self._configuration.database_url,
                ledger_session._verified,
                roles,
                role_refresher=refresh_roles,
            ),
            self._storage,
        )
