"""Invocation-equivalent RF persistence, scoped to the two approved coordinators.

This retains RF ownership until #151. It has no service-role database session,
no Authority Connections table writer, and no Documents metadata/storage owner.
"""

from __future__ import annotations

from asyncio import timeout
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
import os
from urllib.parse import quote, urlencode
from uuid import uuid4

import httpx
import psycopg
from psycopg.rows import dict_row

from talli_backend.adapters.maskinporten import MaskinportenClient, MaskinportenConfiguration, SYSTEM_USER_TAX_SCOPE
from talli_backend.adapters.rf1086_authority import Rf1086AuthorityAdapter, Rf1086ReadOnlyAuthorityAdapter
from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration, SupabaseLedgerAdapter, _VerifiedActor, _validated_origin
from talli_backend.application.ledger_workflow import LedgerAuthenticationError
from talli_backend.compatibility.rf1086_authority_workflow import (
    LegacyRf1086AuthenticationError, LegacyRf1086Error, ProductionOperation, ProductionOperationFailure,
    Rf1086Approval, Rf1086Connection, Rf1086FeedbackArtifactPersistenceError, Rf1086MutationBinding,
    Rf1086Preview, Rf1086ReadOnlyBinding, Rf1086ReconciliationArtifact, Rf1086ReconciliationSnapshot,
    Rf1086Submission, create_rf1086_feedback_artifact_persistence_error, resume_production_operation,
)
from talli_backend.modules.billing.public import BillingQueries
from talli_backend.modules.company_access.public import CompanyAccessError, CompanyAccessService
from talli_backend.modules.documents.public import (
    BeginDocumentUploadCommand, DocumentId, DocumentsError, DocumentsSessionFactory, DocumentStatus,
)
from talli_backend.modules.ledger.public import LedgerError
from talli_backend.shared.kernel import CompanyId, IncomeYear


def _id(row, name):
    return str(row[name]) if row.get(name) is not None else ""


class _PersistenceError(Exception):
    """Only a SQLSTATE is retained for the frozen feedback retry classifier."""
    def __init__(self, code=""):
        self.code = code
        super().__init__("RF1086_PERSISTENCE_UNAVAILABLE")


def _error(error):
    if "production_filing_fresh_owner_step_up_required" in str(error):
        return LegacyRf1086Error("step_up_required")
    return _PersistenceError(getattr(error, "sqlstate", "") or "")


class PostgresLegacyRf1086AuthorityAdapter:
    def __init__(self, configuration: LedgerSupabaseConfiguration, *,
            billing_queries_factory: Callable[[str], Awaitable[BillingQueries]],
            documents_session_factory: DocumentsSessionFactory, company_access_service: CompanyAccessService,
            environment: Mapping[str, str] | None = None, maskinporten: MaskinportenClient | None = None,
            rf_transport: httpx.AsyncBaseTransport | None = None, storage_transport: httpx.AsyncBaseTransport | None = None):
        self._configuration = configuration
        self._authentication = SupabaseLedgerAdapter(configuration)
        self._billing = billing_queries_factory
        self._documents = documents_session_factory
        self._company_access = company_access_service
        self._environment = environment
        self._maskinporten = maskinporten
        self._rf_transport = rf_transport
        self._storage_transport = storage_transport

    @classmethod
    def from_environment(cls, *, billing_queries_factory, documents_session_factory, company_access_service):
        return cls(LedgerSupabaseConfiguration(os.environ.get("SUPABASE_URL", ""),
            os.environ.get("SUPABASE_ANON_KEY", ""), os.environ.get("TALLI_LEDGER_DATABASE_URL", "")),
            billing_queries_factory=billing_queries_factory, documents_session_factory=documents_session_factory,
            company_access_service=company_access_service)

    async def session(self, access_token: str) -> PostgresLegacyRf1086AuthoritySession:
        try:
            verified_session = await self._authentication.session(access_token)
        except LedgerAuthenticationError:
            raise LegacyRf1086AuthenticationError() from None
        except LedgerError:
            raise LegacyRf1086Error("status_unavailable") from None
        return PostgresLegacyRf1086AuthoritySession(self._configuration, verified_session._verified,
            access_token=access_token, billing=await self._billing(access_token), documents=self._documents,
            company_access=self._company_access, environment=self._environment, maskinporten=self._maskinporten,
            rf_transport=self._rf_transport, storage_transport=self._storage_transport)


class PostgresLegacyRf1086AuthoritySession:
    def __init__(self, configuration, verified: _VerifiedActor, *, access_token, billing, documents,
                 company_access, environment=None, maskinporten=None, rf_transport=None, storage_transport=None):
        self._configuration = configuration
        self._verified = verified
        self._access_token = access_token
        self._billing = billing
        self._documents = documents
        self._company_access = company_access
        self._environment = environment
        self._maskinporten = maskinporten
        self._rf_transport = rf_transport
        self._storage_transport = storage_transport
        self._roles = {}

    @property
    def actor_id(self):
        return self._verified.actor_id

    @property
    def billing(self):
        return self._billing

    def require_configuration(self):
        environment = self._environment if self._environment is not None else os.environ
        if environment.get("TALLI_RF1086_PRODUCTION_ENABLED") != "true" or environment.get("TALLI_PROD_RF1086_SCOPE") != SYSTEM_USER_TAX_SCOPE:
            raise LegacyRf1086Error("configuration_unavailable")
        try:
            # Validation is lazy, backend-only and performed for both existing
            # coordinators before any provider business effect.
            configuration = MaskinportenConfiguration.production(environment)
            if self._maskinporten is None:
                self._maskinporten = MaskinportenClient(configuration)
        except Exception:
            raise LegacyRf1086Error("configuration_unavailable") from None

    async def _rows(self, query, parameters=()):
        import json
        if not self._configuration.database_url:
            raise _PersistenceError()
        try:
            async with timeout(10), await psycopg.AsyncConnection.connect(self._configuration.database_url,
                    connect_timeout=5, row_factory=dict_row,
                    options="-c statement_timeout=5000 -c lock_timeout=1000") as connection, connection.transaction():
                await connection.execute("set local role legacy_rf1086_executor")
                await connection.execute(
                    "select pg_catalog.set_config('talli.verified_actor_id',%s,true), "
                    "pg_catalog.set_config('talli.verified_actor_claims',%s,true), "
                    "pg_catalog.set_config('request.jwt.claims',%s,true), "
                    "pg_catalog.set_config('talli.authorized_company_roles',%s,true)",
                    (str(self.actor_id.subject), self._verified.claims_json, self._verified.claims_json,
                     json.dumps(self._roles, separators=(",", ":"))),
                )
                cursor = await connection.execute(query, parameters)
                return list(await cursor.fetchall())
        except (TimeoutError, psycopg.OperationalError) as error:
            raise _PersistenceError(getattr(error, "sqlstate", "") or "") from None
        except psycopg.DatabaseError as error:
            raise _error(error) from None

    async def read_approval(self, approval_id):
        rows = await self._rows("select id,entitlement_id,preview_id,company_id,user_id,income_year,obligation,"
            "case_profile,invalidated_at,manifest_hash,manifest from public.filing_approval_snapshots where id=%s::uuid", (approval_id,))
        if not rows:
            return None
        row = rows[0]
        return Rf1086Approval(*(_id(row, name) for name in ("id", "entitlement_id", "preview_id", "company_id", "user_id")),
            int(row["income_year"]), str(row["obligation"]), str(row["case_profile"]), row["invalidated_at"] is not None, str(row["manifest_hash"]), row["manifest"])

    async def read_preview(self, preview_id):
        rows = await self._rows("select id,company_id,income_year,filing,hovedskjema_xml,underskjema_xml,issues "
            "from public.filing_previews where id=%s::uuid", (preview_id,))
        if not rows:
            return None
        row = rows[0]
        documents = row["underskjema_xml"]
        if not isinstance(documents, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in documents.items()):
            raise LegacyRf1086Error("basis_unavailable")
        issues = row["issues"] if isinstance(row["issues"], list) else []
        return Rf1086Preview(_id(row, "id"), _id(row, "company_id"), int(row["income_year"]), str(row["filing"]),
            str(row["hovedskjema_xml"] or ""), documents, tuple(str(issue["message"]) for issue in issues
                if isinstance(issue, dict) and issue.get("level") == "warning" and isinstance(issue.get("message"), str)))

    async def read_submission(self, submission_id):
        rows = await self._rows("select id,approval_id,entitlement_id,company_id,user_id,income_year,obligation,"
            "case_profile,environment,feedback_state from public.production_filing_submissions where id=%s::uuid", (submission_id,))
        if not rows:
            return None
        row = rows[0]
        return Rf1086Submission(*(_id(row, name) for name in ("id", "approval_id", "entitlement_id", "company_id", "user_id")),
            int(row["income_year"]), str(row["obligation"]), str(row["case_profile"]), str(row["environment"]), str(row["feedback_state"]))

    async def company_record(self, company_id):
        try:
            record = (await self._company_access.company_record(self._access_token, company_id=company_id)).company
        except CompanyAccessError:
            return None
        self._roles[company_id] = record.role
        return record

    async def read_connection(self, request_id, company_id):
        rows = await self._rows("select * from authority_connections.read_rf_request_v1(%s::uuid,%s::uuid,%s::uuid)",
            (request_id, company_id, str(self.actor_id.subject)))
        if not rows:
            return None
        row = rows[0]
        return Rf1086Connection(_id(row, "id"), _id(row, "company_id"), _id(row, "initiating_owner_user_id"),
            str(row["obligation"]), str(row["external_ref"]), str(row["status"]), row["preflight_verified_at"] is not None)

    async def require_fresh_production_owner(self, company_id):
        await self._rows("select legacy_rf1086.assert_fresh_owner_v1(%s::uuid)", (company_id,))

    async def _token(self, company, connection):
        self.require_configuration()
        return await self._maskinporten.request_token(SYSTEM_USER_TAX_SCOPE,
            system_user_org_number=company.org_number, system_user_external_ref=connection.external_ref)

    async def bind_mutation_authority(self, company, connection):
        token = await self._token(company, connection)
        try:
            return Rf1086MutationBinding(Rf1086AuthorityAdapter(token, transport=self._rf_transport),
                Rf1086ReadOnlyAuthorityAdapter(token, transport=self._rf_transport), token.discard)
        except BaseException:
            token.discard()
            raise

    async def bind_read_only_authority(self, company, connection):
        token = await self._token(company, connection)
        try:
            return Rf1086ReadOnlyBinding(Rf1086ReadOnlyAuthorityAdapter(token, transport=self._rf_transport), token.discard)
        except BaseException:
            token.discard()
            raise

    async def begin_production_filing(self, approval_id):
        rows = await self._rows("select id from public.begin_production_filing(%s::uuid)", (approval_id,))
        if not rows:
            raise LegacyRf1086Error("send_unavailable")
        return _id(rows[0], "id")

    def operation_journal(self, submission_id):
        return _OperationJournal(self, submission_id)

    async def claim_feedback_lease(self, submission_id, lease_id):
        rows = await self._rows("select public.claim_production_feedback_reconciliation(%s::uuid,%s::uuid) as claimed", (submission_id, lease_id))
        return bool(rows and rows[0]["claimed"] is True)

    async def read_claimed_reference(self, submission_id, lease_id):
        rows = await self._rows("select feedback_forsendelse_id from public.production_filing_submissions "
            "where id=%s::uuid and feedback_reconciliation_lease_id=%s::uuid", (submission_id, lease_id))
        if not rows or rows[0]["feedback_forsendelse_id"] is None:
            raise LegacyRf1086Error("status_unavailable")
        return str(rows[0]["feedback_forsendelse_id"])

    async def release_feedback_lease(self, submission_id, lease_id):
        try:
            await self._rows("select public.release_production_feedback_reconciliation(%s::uuid,%s::uuid)", (submission_id, lease_id))
        except _PersistenceError:
            # Original release is best effort; the unchanged five-minute lease
            # expiry permits later recovery after a failed release request.
            pass

    def feedback_journal(self, *, submission_id, company_id, income_year, forsendelse_id, lease_id):
        return _FeedbackJournal(self, submission_id, company_id, income_year, forsendelse_id, lease_id)


class _OperationJournal:
    def __init__(self, session, submission_id):
        self._session, self._submission_id = session, submission_id
        self._operations = {}

    async def prepare(self, *, submission_id, name, body_hash, idempotency_key):
        if submission_id != self._submission_id:
            raise LegacyRf1086Error("basis_unavailable")
        rows = await self._session._rows("select * from legacy_rf1086.prepare_operation_v1(%s::uuid,%s::text,%s::text,%s::uuid)",
            (submission_id, name, body_hash, idempotency_key))
        if not rows:
            raise _PersistenceError()
        row = rows[0]
        operation = ProductionOperation(_id(row, "id"), str(row["operation_name"]), str(row["operation_state"]),
            int(row["attempt"]), row["body_hash"], str(row["idempotency_key"]) if row["idempotency_key"] else None,
            row["authority_reference"], row["failure_class"])
        if not row["newly_prepared"]:
            operation = resume_production_operation(operation, is_mutation=idempotency_key is not None)
        self._operations[operation.id] = operation
        return operation

    async def _append(self, operation_id, *, reference, failure):
        operation = self._operations.get(operation_id)
        if operation is None:
            raise _PersistenceError()
        classification = failure.classification if failure else None
        state = ("unknown" if classification == "unknown" else "failed") if failure else "succeeded"
        status = (("unknown" if classification == "unknown" else "rejected" if classification == "blocked" else "sending")
            if failure else "received" if operation.name == "confirm" else "processing" if operation.name == "list_documents" else "sending")
        rows = await self._session._rows("select id from public.append_production_filing_event("
            "%s::uuid,%s::text,%s::text,%s::integer,%s::text,%s::uuid,%s::text,%s::text,%s::text,false)",
            (self._submission_id, operation.name, state, operation.attempt, operation.body_hash,
             operation.idempotency_key, reference, classification, status))
        if not rows:
            raise _PersistenceError()

    async def succeed(self, operation_id, authority_reference):
        await self._append(operation_id, reference=authority_reference, failure=None)

    async def fail(self, operation_id, failure: ProductionOperationFailure):
        await self._append(operation_id, reference=None, failure=failure)


@dataclass(frozen=True, slots=True)
class _DocumentOperation:
    document_id: str
    key: str


class _FeedbackJournal:
    def __init__(self, session, submission_id, company_id, income_year, forsendelse_id, lease_id):
        self._session, self._submission_id, self._company_id = session, submission_id, company_id
        self._income_year, self._forsendelse_id, self._lease_id = income_year, forsendelse_id, lease_id

    async def read_reconciliation_state(self):
        try:
            rows = await self._session._rows("select feedback_state,feedback_safe_error_code,feedback_correlation_id "
                "from public.production_filing_submissions where id=%s::uuid and company_id=%s::uuid", (self._submission_id, self._company_id))
            artifacts = await self._session._rows("select sha256 from public.production_feedback_artifacts where submission_id=%s::uuid order by sha256", (self._submission_id,))
            if not rows:
                raise _PersistenceError()
            row = rows[0]
            return Rf1086ReconciliationSnapshot(str(row["feedback_state"]), tuple(str(item["sha256"]) for item in artifacts),
                row["feedback_safe_error_code"], row["feedback_correlation_id"])
        except Exception as error:
            raise create_rf1086_feedback_artifact_persistence_error(error) from None

    async def _existing(self, digest):
        rows = await self._session._rows("select document_id,sha256 from public.production_feedback_artifacts "
            "where submission_id=%s::uuid and sha256=%s::text", (self._submission_id, digest))
        return rows[0] if rows else None

    async def _document_session(self, operation: _DocumentOperation, kind: str):
        # Preserve former transport operation identities. Documents' public
        # Python contract uses the same immutable DocumentId for idempotency;
        # the old HTTP endpoints did not persist Idempotency-Key headers.
        if operation.key != f"rf1086-feedback-{kind}:{operation.document_id}":
            raise _PersistenceError()
        session = await self._session._documents.session(self._session._access_token)
        if session.actor_id != self._session.actor_id:
            raise DocumentsError.forbidden()
        return session

    async def _store(self, document_id, artifact):
        extension = {"application/xml": "xml", "text/xml": "xml", "application/pdf": "pdf", "text/plain": "txt"}.get(artifact.content_type, "bin")
        document_session = await self._document_session(_DocumentOperation(document_id, "rf1086-feedback-stage:" + document_id), "stage")
        transfer = await document_session.begin_upload(BeginDocumentUploadCommand(CompanyId(self._company_id), IncomeYear(self._income_year),
            DocumentId(document_id), "authority_feedback", "production_filing_submission:" + self._submission_id,
            f"authority-feedback-{artifact.sha256[:12]}.{extension}", artifact.content_type, artifact.byte_length,
            artifact.bytes[:5], DocumentStatus.STORED))
        if (str(transfer.document.document_id) != document_id or transfer.document.company_id != CompanyId(self._company_id)
            or transfer.storage_key != transfer.document.storage_key or transfer.bucket != "company-documents"
            or any(part in {"", ".", ".."} for part in transfer.storage_key.split("/"))):
            raise DocumentsError.integrity_failed()
        origin = _validated_origin(self._session._configuration.url)
        if not origin:
            raise DocumentsError.storage_unavailable()
        url = origin + "/storage/v1/object/upload/sign/" + quote(transfer.bucket, safe="") + "/" + quote(transfer.storage_key, safe="/")
        url += "?" + urlencode({"token": transfer.token})
        try:
            async with timeout(20), httpx.AsyncClient(transport=self._session._storage_transport,
                    timeout=20, follow_redirects=False, trust_env=False) as client:
                async with client.stream("PUT", url, content=artifact.bytes, headers={
                        "content-type": artifact.content_type, "cache-control": "max-age=3600", "x-upsert": "false"}) as response:
                    if not response.is_success:
                        raise DocumentsError.storage_unavailable()
        except (httpx.HTTPError, TimeoutError):
            raise DocumentsError.storage_unavailable() from None
        document_session = await self._document_session(_DocumentOperation(document_id, "rf1086-feedback-finalize:" + document_id), "finalize")
        return await document_session.finalize_upload(DocumentId(document_id))

    async def _remove(self, document_id):
        documents = await self._document_session(_DocumentOperation(document_id, "rf1086-feedback-cleanup:" + document_id), "cleanup")
        await documents.remove_document(DocumentId(document_id), reason="producer_rollback")

    async def _remove_best_effort(self, document_id):
        try:
            await self._remove(document_id)
        except Exception:
            pass

    async def record_artifact(self, artifact: Rf1086ReconciliationArtifact):
        if artifact.submission_id != self._submission_id or artifact.company_id != self._company_id:
            raise create_rf1086_feedback_artifact_persistence_error(None, integrity_failure=True)
        try:
            existing = await self._existing(artifact.sha256)
        except Exception as error:
            raise create_rf1086_feedback_artifact_persistence_error(error) from None
        if existing:
            if existing["sha256"] != artifact.sha256:
                raise create_rf1086_feedback_artifact_persistence_error(None, integrity_failure=True)
            return str(existing["sha256"])
        document_id = str(uuid4())
        stored = await self._store(document_id, artifact)
        if stored.content_sha256 != artifact.sha256 or stored.byte_length != artifact.byte_length:
            await self._remove_best_effort(document_id)
            raise create_rf1086_feedback_artifact_persistence_error(None, integrity_failure=True)
        try:
            rows = await self._session._rows("select id from public.record_production_feedback_artifact("
                "%s::uuid,%s::uuid,%s::uuid,%s::text,%s::text,%s::bigint,%s::text,%s::text)",
                (self._company_id, self._submission_id, document_id, artifact.authority_reference,
                 artifact.content_type, artifact.byte_length, artifact.sha256, artifact.classification))
            if not rows:
                raise _PersistenceError()
            return artifact.sha256
        except Exception as error:
            try:
                persisted = await self._existing(artifact.sha256)
            except Exception as unknown:
                # An ambiguous metadata commit must retain the uploaded receipt.
                raise create_rf1086_feedback_artifact_persistence_error(unknown) from None
            if persisted:
                if persisted["sha256"] != artifact.sha256:
                    raise create_rf1086_feedback_artifact_persistence_error(None, integrity_failure=True)
                if str(persisted["document_id"]) != document_id:
                    await self._remove_best_effort(document_id)
                return str(persisted["sha256"])
            try:
                await self._remove(document_id)
            except Exception as cleanup_error:
                raise create_rf1086_feedback_artifact_persistence_error(cleanup_error) from None
            if isinstance(error, Rf1086FeedbackArtifactPersistenceError):
                raise error
            raise create_rf1086_feedback_artifact_persistence_error(error) from None

    async def append_reconciliation(self, event):
        rows = await self._session._rows("select public.append_production_feedback_reconciliation("
            "%s::uuid,%s::uuid,%s::uuid,%s::text,%s::text[],%s::text,%s::text) as changed",
            (self._submission_id, self._lease_id, self._forsendelse_id, event.state, list(event.artifact_hashes),
             event.safe_error_code, event.correlation_id))
        if not rows or type(rows[0]["changed"]) is not bool:
            raise _PersistenceError()
        return rows[0]["changed"]


__all__ = ["PostgresLegacyRf1086AuthorityAdapter", "PostgresLegacyRf1086AuthoritySession"]
