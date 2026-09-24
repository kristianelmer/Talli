"""Canonical RF persistence and verified, disposable authority bindings."""

from __future__ import annotations

from asyncio import timeout
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from dataclasses import fields
from datetime import datetime
import hashlib
import json
import os
import re
from urllib.parse import quote, urlencode
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx
import psycopg
from psycopg.rows import dict_row

from talli_backend.adapters.postgres_document_evidence import PostgresDocumentEvidenceRetention
from talli_backend.modules.documents.public import DocumentEvidenceRetentionCommand, DocumentId, DocumentStatus
from talli_backend.adapters.maskinporten import MaskinportenClient, MaskinportenConfiguration, SYSTEM_USER_TAX_SCOPE, SYSTEM_USER_DIALOGPORTEN_SCOPE
from talli_backend.adapters.rf1086_dialogporten import Rf1086DialogportenAdapter
from talli_backend.adapters.rf1086_authority import Rf1086AuthorityAdapter, Rf1086ReadOnlyAuthorityAdapter
from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration, SupabaseLedgerAdapter, _VerifiedActor, _validated_origin
from talli_backend.application.ledger_workflow import LedgerAuthenticationError
from talli_backend.modules.shareholder_register_filing.public import (
    Rf1086ProductionError, ProductionOperation, ProductionOperationFailure,
    Rf1086Approval, Rf1086Connection, Rf1086FeedbackArtifactPersistenceError,
    Rf1086Preview, Rf1086ReconciliationArtifact, Rf1086ReconciliationSnapshot,
    Rf1086Submission, create_rf1086_feedback_artifact_persistence_error, resume_production_operation,
)
from talli_backend.application.shareholder_register_filing_session import (
    ShareholderRegisterFilingAuthenticationError, Rf1086MutationBinding, Rf1086ReadOnlyBinding,
)
from talli_backend.modules.billing.public import BillingQueries
from talli_backend.modules.company_access.public import CompanyAccessError, CompanyAccessService
from talli_backend.modules.documents.public import (
    BeginDocumentUploadCommand, DocumentId, DocumentsError, DocumentsSessionFactory, DocumentStatus,
)
from talli_backend.modules.ledger.public import LedgerError
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId, IncomeYear, Timestamp


def _id(row, name):
    return str(row[name]) if row.get(name) is not None else ""


def _record_value(value):
    from uuid import UUID
    if isinstance(value, (UUID, datetime)):
        return str(value) if isinstance(value, UUID) else value.isoformat()
    return value


def _source_digest(value):
    # This versioned persistence comparison is not a statutory payload hash.
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        default=str, ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


class _PersistenceError(Exception):
    """Only a SQLSTATE is retained for the frozen feedback retry classifier."""
    def __init__(self, code=""):
        self.code = code
        super().__init__("RF1086_PERSISTENCE_UNAVAILABLE")


def _error(error):
    if "production_filing_fresh_owner_step_up_required" in str(error):
        return Rf1086ProductionError("step_up_required")
    return _PersistenceError(getattr(error, "sqlstate", "") or "")


class PostgresShareholderRegisterFilingAdapter:
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

    async def session(self, access_token: str) -> PostgresShareholderRegisterFilingSession:
        try:
            verified_session = await self._authentication.session(access_token)
        except LedgerAuthenticationError:
            raise ShareholderRegisterFilingAuthenticationError() from None
        except LedgerError:
            raise Rf1086ProductionError("status_unavailable") from None
        return PostgresShareholderRegisterFilingSession(self._configuration, verified_session._verified,
            access_token=access_token, billing=await self._billing(access_token), documents=self._documents,
            company_access=self._company_access, environment=self._environment, maskinporten=self._maskinporten,
            rf_transport=self._rf_transport, storage_transport=self._storage_transport)


@rf.rf1086_adapter(rf.Rf1086PreparationPersistence)
@rf.rf1086_adapter(rf.Rf1086YearSourcePersistence)
@rf.rf1086_adapter(rf.Rf1086RegisterObservationPersistence)
@rf.rf1086_adapter(rf.Rf1086SourcePreviewPreparation)
class PostgresShareholderRegisterFilingSession:
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
            raise Rf1086ProductionError("configuration_unavailable")
        try:
            # Validation is lazy, backend-only and performed for both existing
            # coordinators before any provider business effect.
            configuration = MaskinportenConfiguration.production(environment)
            if self._maskinporten is None:
                self._maskinporten = MaskinportenClient(configuration)
        except Exception:
            raise Rf1086ProductionError("configuration_unavailable") from None

    @asynccontextmanager
    async def _transaction(self, *, snapshot=False):
        """One verified actor and consistent source snapshot; no provider I/O."""
        if not self._configuration.database_url:
            raise rf.ShareholderRegisterFilingError.unavailable()
        try:
            async with timeout(10), await psycopg.AsyncConnection.connect(
                self._configuration.database_url, connect_timeout=5, row_factory=dict_row,
                options="-c statement_timeout=5000 -c lock_timeout=1000",
            ) as connection, connection.transaction():
                if snapshot:
                    await connection.execute("set transaction isolation level repeatable read")
                else:
                    await connection.execute("set transaction isolation level read committed")
                await connection.execute("set local role shareholder_register_filing_executor")
                await connection.execute(
                    "select pg_catalog.set_config('talli.verified_actor_id',%s,true), "
                    "pg_catalog.set_config('talli.verified_actor_claims',%s,true), "
                    "pg_catalog.set_config('request.jwt.claims',%s,true), "
                    "pg_catalog.set_config('talli.authorized_company_roles',%s,true)",
                    (str(self.actor_id.subject), self._verified.claims_json, self._verified.claims_json,
                     json.dumps(self._roles, separators=(",", ":"))),
                )
                yield connection
        except psycopg.Error as error:
            for code in ("rf1086_register_predecessor_mismatch", "rf1086_register_idempotency_conflict", "rf1086_register_storage_invalid"):
                if code in str(error):
                    raise rf.Rf1086RegisterObservationError(code) from None
            for code in ("rf1086_source_predecessor_mismatch", "rf1086_source_idempotency_conflict", "rf1086_source_storage_invalid",
                         "rf1086_source_preview_stale", "rf1086_source_preview_storage_invalid"):
                if code in str(error):
                    raise rf.Rf1086YearSourceError(code) from None
            if "company_access_forbidden" in str(error):
                raise rf.ShareholderRegisterFilingError.forbidden() from None
            if any(code in str(error) for code in ("company_access_company_year_not_admitted", "company_access_identity_not_confirmed")):
                raise rf.ShareholderRegisterFilingError.company_year_not_admitted() from None
            if "rf1086_not_found" in str(error) or "production_preview_not_found" in str(error):
                raise rf.ShareholderRegisterFilingError.not_found() from None
            if "rf1086_invalid_input" in str(error):
                raise rf.ShareholderRegisterFilingError.invalid_input() from None
            if "production_filing_fresh_owner_step_up_required" in str(error):
                raise Rf1086ProductionError("step_up_required") from None
            if any(code in str(error) for code in ("rf1086_company_year_not_admitted","production_pilot_entitlement_required")):
                raise rf.ShareholderRegisterFilingError.company_year_not_admitted() from None
            if error.sqlstate == "42501" or "rf1086_forbidden" in str(error):
                raise rf.ShareholderRegisterFilingError.forbidden() from None
            raise rf.ShareholderRegisterFilingError.unavailable() from None
        except TimeoutError:
            raise rf.ShareholderRegisterFilingError.unavailable() from None

    @asynccontextmanager
    async def source_admission(self, query):
        """Yield a single guarded connection; never perform object/provider I/O."""
        self._command_actor(query)
        async with self._transaction() as connection:
            row = await (await connection.execute(
                'select public.company_access_read_rf_admission_v1(%s::uuid,%s,%s) as admission',
                (str(query.company_id), int(query.income_year), str(self.actor_id.subject)),
            )).fetchone()
            identity = _source_admission_company(row['admission'] if row else None, query)
            await connection.execute('select shareholder_register_filing.lock_year_source_v1(%s::uuid,%s)',
                (str(query.company_id), int(query.income_year)))
            scoped = _SourceAdmission(self, connection, query, identity)
            try:
                yield scoped
            finally:
                scoped.close()

    def _command_actor(self, command):
        if command.actor_id != self.actor_id:
            raise rf.ShareholderRegisterFilingError.forbidden()

    @staticmethod
    def _year_source(row):
        if row is None:
            return None
        source = rf.parse_rf1086_year_source(row["snapshot_text"])
        if (source.source_id.value != str(row["id"]) or str(source.company_id) != str(row["company_id"])
                or int(source.income_year) != row["income_year"] or source.version != row["version"]
                or source.source_sha256 != row["source_sha256"]
                or str(source.confirmed_by.subject) != str(row["actor_id"])
                or source.confirmed_at != row["confirmed_at"]
                or (source.command.supersedes_source_id.value if source.command.supersedes_source_id else None)
                    != (str(row["predecessor_id"]) if row["predecessor_id"] else None)
                or source.command.supersedes_source_sha256 != row["predecessor_sha256"]
                or source.command.correction_reason != row["correction_reason"]
                or rf.rf1086_year_source_digest(source.command) != row["request_sha256"]):
            raise rf.Rf1086YearSourceError("rf1086_source_storage_invalid")
        return source

    async def _current_year_source(self, connection, company_id, income_year):
        row = await (await connection.execute(
            "select v.* from shareholder_register_filing.year_source_heads h "
            "join shareholder_register_filing.year_source_versions v on v.id=h.source_id "
            "where h.company_id=%s::uuid and h.income_year=%s", (str(company_id), int(income_year)),
        )).fetchone()
        return self._year_source(row)

    async def read_current_year_source(self, query):
        self._command_actor(query)
        async with self._transaction(snapshot=True) as connection:
            await connection.execute("select shareholder_register_filing.assert_member_v1(%s::uuid)", (str(query.company_id),))
            return await self._current_year_source(connection, query.company_id, query.income_year)

    async def read_year_source(self, query, source_id):
        self._command_actor(query)
        async with self._transaction(snapshot=True) as connection:
            await connection.execute("select shareholder_register_filing.assert_member_v1(%s::uuid)", (str(query.company_id),))
            row = await (await connection.execute(
                "select * from shareholder_register_filing.year_source_versions "
                "where id=%s::uuid and company_id=%s::uuid and income_year=%s",
                (source_id.value, str(query.company_id), int(query.income_year)),
            )).fetchone()
            return self._year_source(row)

    async def _retain_source_documents(self, connection, record_type, record_id, documents):
        retention = PostgresDocumentEvidenceRetention(connection, self.actor_id)
        # Stable ordering prevents two captures from taking document locks in
        # opposite order. All references and the RF append commit together.
        for document in sorted(documents, key=lambda item: item.document_id):
            if document.source_income_year is None:
                raise rf.Rf1086YearSourceError("rf1086_source_document_year_required")
            await retention.retain_verified_evidence(DocumentEvidenceRetentionCommand(
                source_record_type=record_type, source_record_id=record_id,
                document_id=DocumentId(document.document_id), company_id=document.company_id,
                source_income_year=document.source_income_year, status=DocumentStatus(document.integrity_status),
                content_sha256=document.content_sha256, byte_length=document.byte_length,
                metadata_sha256=document.metadata_sha256))

    async def record_year_source(self, command, *, context, idempotency_key):
        self._command_actor(command)
        if (not isinstance(context, rf.Rf1086VerifiedYearSourceContext) or context.accepted_owner is not True
                or context.actor_id != self.actor_id or context.company_id != command.company_id
                or context.income_year != command.income_year):
            raise rf.ShareholderRegisterFilingError.forbidden()
        # The workflow obtained external projections before this short RF-only
        # transaction. Capture is point-in-time; this is not a provider lease.
        async with self._transaction() as connection:
            await connection.execute("select shareholder_register_filing.lock_year_source_v1(%s::uuid,%s)",
                (str(command.company_id), int(command.income_year)))
            replay = await (await connection.execute(
                "select * from shareholder_register_filing.year_source_versions where company_id=%s::uuid "
                "and income_year=%s and actor_id=%s::uuid and idempotency_key=%s",
                (str(command.company_id), int(command.income_year), str(self.actor_id.subject), str(idempotency_key)),
            )).fetchone()
            if replay:
                original = self._year_source(replay)
                rf.assert_rf1086_year_source_replay(original, command)
                return original
            previous = await self._current_year_source(connection, command.company_id, command.income_year)
            now = (await (await connection.execute("select pg_catalog.clock_timestamp() as now")).fetchone())["now"]
            source = rf.prepare_rf1086_year_source(command, context=context,
                source_id=rf.Rf1086YearSourceId(str(uuid4())), confirmed_at=now, previous=previous)
            for receipt in source.governance_receipts:
                if receipt.register_observation_id is not None:
                    observation = await self._read_register_observation(connection, command,
                        rf.Rf1086RegisterObservationId(receipt.register_observation_id), current=True)
                    if (observation is None or observation.fact_sha256 != receipt.register_observation_sha256
                            or observation.confirmed_at >= source.confirmed_at):
                        raise rf.Rf1086YearSourceError("rf1086_source_register_observation_stale")
            await self._retain_source_documents(connection, "rf1086_year_source", source.source_id.value, source.command.documents)
            encoded = rf.serialize_rf1086_year_source(source)
            await connection.execute(
                "select shareholder_register_filing.append_year_source_v1(%s::uuid,%s::uuid,%s,%s,%s,%s,%s,%s::uuid,%s,%s,%s,%s)",
                (source.source_id.value, str(source.company_id), int(source.income_year), source.version,
                 source.source_sha256, rf.rf1086_year_source_digest(command), str(idempotency_key),
                 previous.source_id.value if previous else None, previous.source_sha256 if previous else None,
                 command.correction_reason, encoded, now))
            saved = await self._current_year_source(connection, command.company_id, command.income_year)
            if saved is None or rf.rf1086_year_source_digest(saved) != rf.rf1086_year_source_digest(source):
                raise rf.Rf1086YearSourceError("rf1086_source_storage_invalid")
            return saved

    @staticmethod
    def _register_observation(row):
        if row is None:
            return None
        snapshot = rf.parse_rf1086_register_observation(row["snapshot_text"])
        command = snapshot.command
        if (snapshot.observation_id.value != str(row["id"])
                or str(command.company_id) != str(row["company_id"])
                or int(command.income_year) != row["income_year"] or snapshot.version != row["version"]
                or snapshot.fact_sha256 != row["fact_sha256"]
                or str(command.actor_id.subject) != str(row["actor_id"])
                or snapshot.confirmed_at != row["confirmed_at"]
                or (command.supersedes_observation_id.value if command.supersedes_observation_id else None)
                    != (str(row["predecessor_id"]) if row["predecessor_id"] else None)
                or command.supersedes_observation_sha256 != row["predecessor_sha256"]
                or command.correction_reason != row["correction_reason"]
                or rf.rf1086_register_observation_request_digest(command) != row["request_sha256"]):
            raise rf.Rf1086RegisterObservationError("rf1086_register_storage_invalid")
        return snapshot

    async def _read_register_observation(self, connection, query, observation_id, *, current=False):
        row = await (await connection.execute(
            "select v.* from shareholder_register_filing.register_observations v "
            "where v.id=%s::uuid and v.company_id=%s::uuid and v.income_year=%s "
            + ("and not exists(select 1 from shareholder_register_filing.register_observations successor "
               "where successor.predecessor_id=v.id)" if current else ""),
            (observation_id.value, str(query.company_id), int(query.income_year)),
        )).fetchone()
        return self._register_observation(row)

    async def list_register_observations(self, query):
        self._command_actor(query)
        async with self._transaction(snapshot=True) as connection:
            owner = await (await connection.execute(
                "select public.company_access_is_accepted_owner_v1(%s::uuid) as allowed",
                (str(query.company_id),))).fetchone()
            if owner is None or owner["allowed"] is not True:
                raise rf.ShareholderRegisterFilingError.forbidden()
            rows = await (await connection.execute(
                "select v.* from shareholder_register_filing.register_observations v "
                "where v.company_id=%s::uuid and v.income_year=%s order by v.confirmed_at,v.id",
                (str(query.company_id), int(query.income_year)),)).fetchall()
            snapshots = tuple(self._register_observation(row) for row in rows)
            if any(item.command.company_id != query.company_id or item.command.income_year != query.income_year
                   for item in snapshots):
                raise rf.Rf1086RegisterObservationError("rf1086_register_storage_invalid")
            return snapshots

    async def read_register_observation(self, query, observation_id):
        self._command_actor(query)
        async with self._transaction(snapshot=True) as connection:
            await connection.execute("select shareholder_register_filing.assert_member_v1(%s::uuid)", (str(query.company_id),))
            return await self._read_register_observation(connection, query, observation_id)

    async def read_current_register_observation(self, query, observation_id):
        self._command_actor(query)
        async with self._transaction(snapshot=True) as connection:
            await connection.execute("select shareholder_register_filing.assert_member_v1(%s::uuid)", (str(query.company_id),))
            return await self._read_register_observation(connection, query, observation_id, current=True)

    async def record_register_observation(self, command, *, context, idempotency_key):
        self._command_actor(command)
        if (not isinstance(context, rf.Rf1086VerifiedRegisterObservationContext) or context.accepted_owner is not True
                or context.actor_id != self.actor_id or context.company_id != command.company_id
                or context.income_year != command.income_year):
            raise rf.ShareholderRegisterFilingError.forbidden()
        request_sha = rf.rf1086_register_observation_request_digest(command)
        async with self._transaction() as connection:
            await connection.execute("select shareholder_register_filing.lock_year_source_v1(%s::uuid,%s)",
                (str(command.company_id), int(command.income_year)))
            row = await (await connection.execute(
                "select * from shareholder_register_filing.register_observations where company_id=%s::uuid "
                "and income_year=%s and actor_id=%s::uuid and idempotency_key=%s",
                (str(command.company_id), int(command.income_year), str(self.actor_id.subject), str(idempotency_key)),
            )).fetchone()
            if row:
                original = self._register_observation(row)
                if row["request_sha256"] != request_sha:
                    raise rf.Rf1086RegisterObservationError("rf1086_register_idempotency_conflict")
                return original
            previous = None
            if command.supersedes_observation_id is not None:
                previous = await self._read_register_observation(connection, command,
                    command.supersedes_observation_id, current=True)
                if previous is None:
                    raise rf.Rf1086RegisterObservationError("rf1086_register_predecessor_mismatch")
            now = (await (await connection.execute("select pg_catalog.clock_timestamp() as now")).fetchone())["now"]
            snapshot = rf.prepare_rf1086_register_observation(command, context=context,
                observation_id=rf.Rf1086RegisterObservationId(str(uuid4())), confirmed_at=now, previous=previous)
            await self._retain_source_documents(connection, "rf1086_register_observation", snapshot.observation_id.value, snapshot.command.documents)
            await connection.execute(
                "select shareholder_register_filing.append_register_observation_v1(%s::uuid,%s::uuid,%s,%s,%s,%s,%s,%s::uuid,%s,%s,%s,%s)",
                (snapshot.observation_id.value, str(command.company_id), int(command.income_year), snapshot.version,
                 snapshot.fact_sha256, request_sha, str(idempotency_key),
                 previous.observation_id.value if previous else None, previous.fact_sha256 if previous else None,
                 snapshot.command.correction_reason, rf.serialize_rf1086_register_observation(snapshot), now))
            saved = await self._read_register_observation(connection, command, snapshot.observation_id, current=True)
            if saved != snapshot:
                raise rf.Rf1086RegisterObservationError("rf1086_register_storage_invalid")
            return saved

    @staticmethod
    def _source_preview(row):
        if row is None:
            raise rf.ShareholderRegisterFilingError.not_found()
        preview = rf.parse_rf1086_source_preview(row["payload_text"])
        source = rf.parse_rf1086_year_source(row["source_snapshot_text"])
        if (str(preview.preview_id) != str(row["id"])
                or str(preview.company_id) != str(row["company_id"])
                or int(preview.income_year) != row["income_year"]
                or preview.source_id.value != str(row["source_id"])
                or preview.source_sha256 != row["source_sha256"]
                or preview.case_sha256 != row["case_sha256"]
                or row["profile"] != "rf1086-full-year-v1"
                or row["profile"] != preview.rendering_profile
                or hashlib.sha256(row["payload_text"].encode("utf-8")).hexdigest() != row["payload_sha256"]
                or (preview.source_id, preview.source_sha256, preview.case_sha256,
                    preview.company_id, preview.income_year)
                    != (source.source_id, source.source_sha256, source.case_sha256,
                        source.company_id, source.income_year)):
            raise rf.Rf1086YearSourceError("rf1086_source_preview_storage_invalid")
        # Historical previews retain their original renderer output. Do not
        # rerender an old row using a future implementation when reading it.
        return preview

    async def _read_source_preview(self, connection, preview_id):
        row = await (await connection.execute(
            "select p.*,v.snapshot_text as source_snapshot_text "
            "from shareholder_register_filing.source_previews p "
            "join shareholder_register_filing.year_source_versions v on v.id=p.source_id "
            "where p.id=%s::uuid", (str(preview_id),),
        )).fetchone()
        return self._source_preview(row)

    async def source_preview(self, preview_id):
        async with self._transaction(snapshot=True) as connection:
            return await self._read_source_preview(connection, preview_id)

    async def capture_source_preview(self, command, prepared):
        source = prepared.source
        rf.assert_rf1086_year_source_integrity(source)
        if (command.company_id != source.company_id or command.income_year != source.income_year
                or rf.rf1086_year_source_digest(command.source) != rf.rf1086_year_source_digest(source)):
            raise rf.Rf1086YearSourceError("rf1086_source_preview_stale")
        rendered = prepared.rendered
        identity = "rf1086-source-preview:full-year-v1:" + source.source_id.value + ":" + source.source_sha256 + ":" + rf.rf1086_year_source_digest(rendered)
        preview = rf.Rf1086SourcePreview(
            preview_id=rf.PreviewId(str(uuid5(NAMESPACE_URL, identity))),
            company_id=source.company_id, income_year=source.income_year, source_id=source.source_id,
            source_sha256=source.source_sha256, case_sha256=source.case_sha256,
            readiness_status=rendered.status, readiness_issues=rendered.issues, preview_text=rendered.preview,
            hovedskjema_xml=rendered.hovedskjema_xml, underskjema_xml=rendered.underskjema_xml)
        rf.assert_rf1086_source_preview_matches(preview, source)
        encoded = rf.serialize_rf1086_source_preview(preview)
        payload_sha = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        async with self._transaction() as connection:
            await connection.execute("select shareholder_register_filing.lock_year_source_v1(%s::uuid,%s)",
                (str(source.company_id), int(source.income_year)))
            current = await self._current_year_source(connection, source.company_id, source.income_year)
            if current is None or rf.rf1086_year_source_digest(current) != rf.rf1086_year_source_digest(source):
                raise rf.Rf1086YearSourceError("rf1086_source_preview_stale")
            # The RPC repeats the current-head and owner checks under this same
            # advisory lock, before either new insertion or identical replay.
            saved = await (await connection.execute(
                "select shareholder_register_filing.append_source_preview_v1("
                "%s::uuid,%s::uuid,%s,%s::uuid,%s,%s,%s,%s) as id",
                (str(preview.preview_id), str(source.company_id), int(source.income_year),
                 source.source_id.value, source.source_sha256, source.case_sha256, payload_sha, encoded),
            )).fetchone()
            if saved is None or str(saved["id"]) != str(preview.preview_id):
                raise rf.Rf1086YearSourceError("rf1086_source_preview_storage_invalid")
            retained = await self._read_source_preview(connection, preview.preview_id)
            if retained != preview:
                raise rf.Rf1086YearSourceError("rf1086_source_preview_storage_invalid")
            return retained

    async def _opening_inputs(self, connection, company_id, snapshot_id, *, lock=False):
        actor = str(self.actor_id.subject)
        identity_row = await (await connection.execute(
            "select public.company_access_read_rf_company_identity_v1(%s::uuid,%s::text) as identity",
            (str(company_id), actor),
        )).fetchone()
        row = await (await connection.execute(
            "select * from shareholder_register_filing.opening_balance_setups "
            "where id=%s::uuid and company_id=%s::uuid" + (" for update" if lock else ""),
            (str(snapshot_id), str(company_id)),
        )).fetchone()
        if not row or not identity_row or not identity_row["identity"]:
            raise rf.ShareholderRegisterFilingError.not_found()
        shareholders = await (await connection.execute(
            "select * from shareholder_register_filing.opening_shareholders "
            "where setup_id=%s::uuid and company_id=%s::uuid order by id",
            (str(snapshot_id), str(company_id)),
        )).fetchall()
        return identity_row["identity"], row, shareholders

    async def _opening_basis(self, connection, company_id, snapshot_id, *, lock=False):
        identity, row, shareholders = await self._opening_inputs(connection, company_id, snapshot_id, lock=lock)
        company = rf.Rf1086CompanyFacts(
            CompanyId(str(company_id)), str(identity["org_number"]), str(identity["name"]),
            identity["address"], identity["postal_code"], identity["city"],
        )
        opening = rf.Rf1086OpeningFacts(
            CompanyId(str(company_id)), rf.OpeningSnapshotId(str(snapshot_id)), IncomeYear(row["income_year"]),
            float(row["share_capital"]), row["share_count"], float(row["nominal_value"]),
            tuple(rf.Rf1086OpeningShareholderFact(str(item["id"]), rf.Rf1086ShareholderKind(item["shareholder_kind"]),
                str(item["name"]), item["national_id"], item["org_number"], item["share_count"])
                for item in shareholders),
        )
        digest = _source_digest({"company": identity, "opening": row, "shareholders": shareholders})
        return rf.Rf1086OpeningBasis(CompanyId(str(company_id)), rf.OpeningSnapshotId(str(snapshot_id)),
            IncomeYear(row["income_year"]), rf.build_no_activity_rf1086_case(company=company, opening=opening), digest)

    async def load_opening(self, command):
        self._command_actor(command)
        async with self._transaction(snapshot=True) as connection:
            return await self._opening_basis(connection, command.company_id, command.opening_snapshot_id)

    async def legacy_archive_source(self, query):
        return await self._archive_source(query, include_production=False)

    async def archive_source(self, query):
        return await self._archive_source(query, include_production=True)

    async def _archive_source(self, query, *, include_production):
        self._command_actor(query)
        async with self._transaction(snapshot=True) as connection:
            company_id, year = str(query.company_id), int(query.income_year)
            await connection.execute("select shareholder_register_filing.assert_member_v1(%s::uuid)", (company_id,))
            values = {}
            # Filter parent years before decoding; comments/permissions retain
            # their original company-wide scope, including historical references.
            for name, table, record_type, ordered_at, scoped_year in (
                ("previews", "filing_previews", rf.Rf1086PreviewRecord, "created_at", True),
                ("simulations", "filing_submissions", rf.Rf1086SimulationRecord, "created_at", True),
                ("approvals", "filing_approval_snapshots", rf.Rf1086ApprovalRecord, "approved_at", True),
                ("production_submissions", "production_filing_submissions", rf.Rf1086ProductionSubmissionRecord, "created_at", True),
                ("review_comments", "filing_review_comments", rf.Rf1086ReviewCommentRecord, "created_at", False),
                ("permissions", "authority_permissions", rf.Rf1086FilingPermissionRecord, "updated_at", False),
            ):
                if not include_production and name in ("approvals", "production_submissions"):
                    continue
                where = " and t.income_year=%s::integer" if scoped_year else ""
                rows = await (await connection.execute(
                    f"select t.* from shareholder_register_filing.{table} t where t.company_id=%s::uuid{where} "
                    f"order by t.{ordered_at} desc,t.id desc",
                    (company_id, year) if scoped_year else (company_id,),
                )).fetchall()
                try:
                    values[name] = tuple(self._wire_record(record_type, row) for row in rows)
                except (TypeError, ValueError, KeyError):
                    raise rf.ShareholderRegisterFilingError.unavailable() from None
            evidence_ids = sorted({row.authority_test_run_id for row in values["simulations"]
                if row.mode == "test_authority" and row.authority_test_run_id is not None})
            values["test_evidence"] = ()
            if evidence_ids:
                rows = await (await connection.execute(
                    "select t.* from shareholder_register_filing.authority_test_runs t "
                    "where t.company_id=%s::uuid and t.obligation='aksjonaerregisteroppgaven' "
                    "and t.id=any(%s::uuid[]) order by t.recorded_at desc,t.id desc",
                    (company_id,evidence_ids),
                )).fetchall()
                try:
                    values["test_evidence"] = tuple(self._wire_record(rf.Rf1086TestEvidenceRecord, row) for row in rows)
                except (TypeError, ValueError, KeyError):
                    raise rf.ShareholderRegisterFilingError.unavailable() from None
            if not include_production:
                return rf.Rf1086ArchiveSnapshot(query.company_id, query.income_year, **values)
            for name, table, record_type, ordered_at in (
                ("production_events", "production_filing_events", rf.Rf1086ArchiveProductionEventRecord, "created_at"),
                ("feedback_artifacts", "production_feedback_artifacts", rf.Rf1086ArchiveFeedbackArtifactRecord, "retrieved_at"),
            ):
                rows = await (await connection.execute(
                    f"select t.* from shareholder_register_filing.{table} t "
                    "join shareholder_register_filing.production_filing_submissions s on s.id=t.submission_id "
                    "where s.company_id=%s::uuid and s.income_year=%s::integer and t.company_id=s.company_id "
                    f"order by t.{ordered_at},t.id", (company_id, year),
                )).fetchall()
                try:
                    values[name] = tuple(self._wire_record(record_type, row) for row in rows)
                except (TypeError, ValueError, KeyError):
                    raise rf.ShareholderRegisterFilingError.unavailable() from None
            return rf.Rf1086ArchiveSnapshot(query.company_id, query.income_year, **values)

    async def _workspace(self, connection, query):
        self._command_actor(query)
        company_id = str(query.company_id)
        year = int(query.income_year) if query.income_year is not None else None
        await connection.execute("select shareholder_register_filing.assert_member_v1(%s::uuid)", (company_id,))
        specs = (
            ("previews", "filing_previews", rf.Rf1086PreviewRecord, "created_at", "income_year"),
            ("simulations", "filing_submissions", rf.Rf1086SimulationRecord, "created_at", "income_year"),
            ("overrides", "filing_overrides", rf.Rf1086OverrideRecord, "created_at", "income_year"),
            ("review_comments", "filing_review_comments", rf.Rf1086ReviewCommentRecord, "created_at", None),
            ("permissions", "authority_permissions", rf.Rf1086FilingPermissionRecord, "updated_at", False),
            ("test_evidence", "authority_test_runs", rf.Rf1086TestEvidenceRecord, "recorded_at", False),
            ("approvals", "filing_approval_snapshots", rf.Rf1086ApprovalRecord, "approved_at", "income_year"),
            ("production_submissions", "production_filing_submissions", rf.Rf1086ProductionSubmissionRecord, "created_at", "income_year"),
            ("feedback_artifacts", "production_feedback_artifacts", rf.Rf1086FeedbackArtifactRecord, "retrieved_at", None),
        )
        values = {}
        # The table/order names are a closed implementation inventory, not caller input.
        for name, table, record_type, ordered_at, year_column in specs:
            filter_sql = ""
            params = [company_id]
            if year is not None and year_column:
                filter_sql = " and t.income_year=%s::integer"
                params.append(year)
            elif year is not None and year_column is None:
                parent, key = ("filing_previews", "preview_id") if name == "review_comments" else ("production_filing_submissions", "submission_id")
                filter_sql = f" and exists(select 1 from shareholder_register_filing.{parent} p where p.id=t.{key} and p.company_id=t.company_id and p.income_year=%s::integer)"
                params.append(year)
            rows = await (await connection.execute(
                f"select t.* from shareholder_register_filing.{table} t where t.company_id=%s::uuid{filter_sql} order by t.{ordered_at} desc,t.id desc",
                params,
            )).fetchall()
            values[name] = tuple(self._wire_record(record_type,row) for row in rows)
        return rf.Rf1086WorkspaceSnapshot(query.company_id, query.income_year, **values)

    async def workspace(self, query):
        async with self._transaction(snapshot=True) as connection:
            return await self._workspace(connection, query)

    @staticmethod
    def _wire_record(record_type, row):
        values = {field.name: _record_value(row[field.name]) for field in fields(record_type)}
        if record_type is rf.Rf1086PreviewRecord:
            values['issues'] = tuple(rf.Rf1086ReadinessIssue(**issue) for issue in row['issues'])
        return record_type(**values)

    @staticmethod
    def _recorded(row, *, income_year=None):
        return rf.Rf1086RecordedResult(str(row['id']), CompanyId(str(row['company_id'])),
            IncomeYear(row['income_year']) if row.get('income_year') is not None else income_year)

    async def _execute_record(self, connection, function, parameters):
        # Function identifiers are literals at each owned command call site.
        placeholders = ','.join(['%s'] * len(parameters))
        row = await (await connection.execute(
            f'select shareholder_register_filing.{function}({placeholders}) as result', parameters,
        )).fetchone()
        if not row or not row['result']:
            raise rf.ShareholderRegisterFilingError.unavailable()
        return row['result']

    async def record_preview(self, command, prepared):
        self._command_actor(command)
        async with self._transaction() as connection:
            await connection.execute("select shareholder_register_filing.lock_company_write_v1(%s::uuid,false)", (str(command.company_id),))
            current = await self._opening_basis(connection, command.company_id, command.opening_snapshot_id, lock=True)
            if current != prepared.basis:
                raise rf.ShareholderRegisterFilingError.company_year_not_admitted()
            rendered = prepared.rendered
            from psycopg.types.json import Jsonb
            row = await self._execute_record(connection, 'record_preview_v1', (
                str(command.company_id), str(command.opening_snapshot_id), rendered.status,
                Jsonb([{'level':i.level,'code':i.code,'message':i.message} for i in rendered.issues]),
                rendered.preview, rendered.hovedskjema_xml, Jsonb(dict(rendered.underskjema_xml)),
            ))
            return self._recorded(row)

    async def record_override(self, command):
        self._command_actor(command)
        async with self._transaction() as connection:
            row = await self._execute_record(connection, 'record_override_v1', (
                str(command.preview_id), command.field_target, command.old_value, command.new_value,
                command.reason, command.risk_level, command.owner_confirmed,
            ))
            return self._recorded(row)

    async def add_review_comment(self, command):
        self._command_actor(command)
        async with self._transaction() as connection:
            row = await self._execute_record(connection, 'add_review_comment_v1', (
                str(command.preview_id), command.severity, command.body,
            ))
            preview = await self._preview_record(connection, command.preview_id)
            return self._recorded(row, income_year=IncomeYear(preview.income_year))

    async def acknowledge_review_comment(self, command):
        self._command_actor(command)
        async with self._transaction() as connection:
            row = await self._execute_record(connection, 'acknowledge_review_comment_v1', (str(command.comment_id),))
            preview = await self._preview_record(connection, row['preview_id'])
            return self._recorded(row, income_year=IncomeYear(preview.income_year))

    async def confirm_filing_permission(self, command):
        self._command_actor(command)
        async with self._transaction() as connection:
            return self._recorded(await self._execute_record(connection, 'confirm_filing_permission_v1', (
                str(command.company_id), command.production_enabled,
            )))

    async def record_test_evidence(self, command):
        self._command_actor(command)
        from psycopg.types.json import Jsonb
        data = {name: getattr(command,name) for name in ('environment','status','test_reference',
            'feedback_summary','receipt_reference','archive_reference','evidence_url','payload_hash')}
        async with self._transaction() as connection:
            return self._recorded(await self._execute_record(connection, 'record_test_evidence_v1', (
                str(command.company_id), Jsonb(data),
            )))

    async def preview_record(self, query):
        self._command_actor(query)
        async with self._transaction(snapshot=True) as connection:
            return await self._preview_record(connection, query.preview_id)

    async def _preview_record(self, connection, preview_id, *, lock=False):
        row = await (await connection.execute(
            'select * from shareholder_register_filing.filing_previews where id=%s::uuid' + (' for update' if lock else ''),
            (str(preview_id),),
        )).fetchone()
        if not row:
            raise rf.ShareholderRegisterFilingError.not_found()
        return self._wire_record(rf.Rf1086PreviewRecord, row)

    async def _simulation_basis(self, connection, preview_id, *, lock=False):
        preview = await self._preview_record(connection, preview_id, lock=lock)
        ready = await (await connection.execute(
            'select backend_system.rf1086_annual_readiness_ready_v1(%s::uuid,%s::integer,%s::text) as ready',
            (preview.company_id, preview.income_year, 'aksjonaerregisteroppgaven'),
        )).fetchone()
        comments = await (await connection.execute(
            "select id from shareholder_register_filing.filing_review_comments where preview_id=%s::uuid and severity='hard_block' order by id",
            (preview.id,),
        )).fetchall()
        overrides = await (await connection.execute(
            "select id,field_target from shareholder_register_filing.filing_overrides where company_id=%s::uuid and income_year=%s::integer and filing=%s::text and risk_level='block' order by id",
            (preview.company_id,preview.income_year,preview.filing),
        )).fetchall()
        digest = _source_digest({'preview':{f.name:getattr(preview,f.name) for f in fields(preview)},
            'ready':ready,'comments':comments,'overrides':overrides})
        return rf.Rf1086SimulationBasis(preview,digest,ready['ready'] is True,len(comments),tuple(r['field_target'] for r in overrides))

    async def load_simulation_basis(self, command):
        self._command_actor(command)
        async with self._transaction(snapshot=True) as connection:
            return await self._simulation_basis(connection,command.preview_id)

    async def record_simulation(self, command, prepared):
        self._command_actor(command)
        from psycopg.types.json import Jsonb
        # Public DTO mappings are immutable; convert recursively for psycopg JSON.
        def plain(v):
            if isinstance(v, Mapping): return {k:plain(i) for k,i in v.items()}
            if isinstance(v,(list,tuple)): return [plain(i) for i in v]
            return v
        async with self._transaction() as connection:
            await connection.execute("select shareholder_register_filing.lock_preview_write_v1(%s::uuid,false)", (str(command.preview_id),))
            current = await self._simulation_basis(connection, command.preview_id, lock=True)
            if current != prepared.basis:
                raise rf.ShareholderRegisterFilingError.company_year_not_admitted()
            data = dict(prepared.result) | {name:getattr(prepared,name) for name in (
                'payload_hash','idempotency_key','feedback_items','receipt_metadata','submitted_payload_ref','submitted_payload')}
            return self._recorded(await self._execute_record(connection,'record_simulation_v1',(
                str(command.preview_id),Jsonb(plain(data)),
            )))

    async def _approval_basis(self, connection, preview_id, *, lock=False):
        preview = await self._preview_record(connection,preview_id,lock=lock)
        identity = await (await connection.execute(
            'select public.company_access_read_rf_company_identity_v1(%s::uuid,%s::text) as identity',
            (preview.company_id,str(self.actor_id.subject)),
        )).fetchone()
        org = str(identity['identity']['org_number'])
        return rf.Rf1086ApprovalBasis(preview,org,_source_digest({'preview':{f.name:getattr(preview,f.name) for f in fields(preview)},'org':org}))

    async def load_approval_basis(self, command):
        self._command_actor(command)
        async with self._transaction(snapshot=True) as connection:
            return await self._approval_basis(connection,command.preview_id)

    async def record_approval(self, command, prepared):
        self._command_actor(command)
        from psycopg.types.json import Jsonb
        def plain(v):
            if isinstance(v,Mapping): return {k:plain(i) for k,i in v.items()}
            if isinstance(v,(tuple,list)): return [plain(i) for i in v]
            return v
        async with self._transaction() as connection:
            await connection.execute("select shareholder_register_filing.lock_preview_write_v1(%s::uuid,false)", (str(command.preview_id),))
            current = await self._approval_basis(connection,command.preview_id,lock=True)
            if current != prepared.basis:
                raise rf.ShareholderRegisterFilingError.company_year_not_admitted()
            row = await (await connection.execute(
                'select * from shareholder_register_filing.approve_production_filing(%s::uuid,%s::uuid,%s::jsonb,%s::text,%s::text)',
                (str(command.preview_id),command.entitlement_id,Jsonb(plain(prepared.manifest)),prepared.manifest_hash,prepared.adapter_version),
            )).fetchone()
            if not row: raise rf.ShareholderRegisterFilingError.unavailable()
            return self._recorded(row)

    async def source_snapshot(self, query):
        self._command_actor(query)
        async with self._transaction(snapshot=True) as connection:
            workspace = await self._workspace(connection,rf.Rf1086WorkspaceQuery(query.company_id,query.actor_id,query.income_year))
            raw_inventory = await (await connection.execute(
                'select shareholder_register_filing.read_migration_inventory_v1(%s::uuid,%s::integer) as inventory',
                (str(query.company_id),int(query.income_year)),
            )).fetchone()
            value = raw_inventory['inventory'] if raw_inventory else None
            inventory = None
            if value:
                inventory = rf.Rf1086MigrationInventory(value['reference'],value['version'],_source_digest(value),
                    query.company_id,query.income_year,value['family_counts'],value['family_digests'],
                    value['quarantined_count'],value['reconciled'] is True)
            events = await (await connection.execute(
                'select e.* from shareholder_register_filing.production_filing_events e '
                'join shareholder_register_filing.production_filing_submissions s on s.id=e.submission_id '
                'where s.company_id=%s::uuid and s.income_year=%s::integer order by e.created_at,e.id',
                (str(query.company_id),int(query.income_year)),
            )).fetchall()
            journal = tuple(rf.Rf1086JournalEvent(str(e['id']),str(e['submission_id']),sequence,
                e['operation_name'],e['operation_state'],e['body_hash'],_record_value(e['idempotency_key']),
                e['authority_reference'],e['failure_class'],e['safe_error_code'],e['created_at'].isoformat(),e['attempt'],e['resulting_status'],_source_digest({key: value for key,value in e.items() if key not in {'company_id','income_year'}}))
                for sequence,e in enumerate(events,1))
            openings = await (await connection.execute(
                'select id from shareholder_register_filing.opening_balance_setups where company_id=%s::uuid '
                'and income_year=%s::integer order by id',(str(query.company_id),int(query.income_year)),
            )).fetchall()
            bases=[]
            opening_sources=[]
            for row in openings:
                identity, original, shareholders = await self._opening_inputs(connection,query.company_id,str(row["id"]))
                opening_sources.append(rf.Rf1086OpeningSource(query.company_id,rf.OpeningSnapshotId(str(row["id"])),query.income_year,
                    _source_digest({"company":identity,"opening":original,"shareholders":shareholders}),len(shareholders)))
                try:
                    bases.append(await self._opening_basis(connection,query.company_id,str(row['id'])))
                except rf.ShareholderRegisterFilingError as error:
                    # Invalid current rendering basis does not erase retained filing history.
                    if error.code != 'SHAREHOLDER_REGISTER_FILING_INVALID_INPUT': raise
            as_of = await (await connection.execute(
                'select pg_catalog.transaction_timestamp() as observed_at,public.company_access_is_accepted_owner_v1(%s::uuid) as complete',
                (str(query.company_id),),
            )).fetchone()
            return rf.Rf1086SourceSnapshot(workspace,inventory,journal,tuple(bases),Timestamp(as_of['observed_at']),as_of['complete'] is True,tuple(opening_sources))

    async def _rows(self, query, parameters=()):
        import json
        if not self._configuration.database_url:
            raise _PersistenceError()
        try:
            async with timeout(10), await psycopg.AsyncConnection.connect(self._configuration.database_url,
                    connect_timeout=5, row_factory=dict_row,
                    options="-c statement_timeout=5000 -c lock_timeout=1000") as connection, connection.transaction():
                await connection.execute("set transaction isolation level read committed")
                await connection.execute("set local role shareholder_register_filing_executor")
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
            "case_profile,invalidated_at,manifest_hash,manifest from shareholder_register_filing.filing_approval_snapshots where id=%s::uuid "
            "and user_id=shareholder_register_filing.actor_v1() and public.company_access_is_accepted_owner_v1(company_id)", (approval_id,))
        if not rows:
            return None
        row = rows[0]
        return Rf1086Approval(*(_id(row, name) for name in ("id", "entitlement_id", "preview_id", "company_id", "user_id")),
            int(row["income_year"]), str(row["obligation"]), str(row["case_profile"]), row["invalidated_at"] is not None, str(row["manifest_hash"]), row["manifest"])

    async def read_preview(self, preview_id):
        rows = await self._rows("select id,company_id,income_year,filing,hovedskjema_xml,underskjema_xml,issues "
            "from shareholder_register_filing.filing_previews where id=%s::uuid "
            "and public.company_access_is_accepted_owner_v1(company_id)", (preview_id,))
        if not rows:
            return None
        row = rows[0]
        documents = row["underskjema_xml"]
        if not isinstance(documents, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in documents.items()):
            raise Rf1086ProductionError("basis_unavailable")
        issues = row["issues"] if isinstance(row["issues"], list) else []
        return Rf1086Preview(_id(row, "id"), _id(row, "company_id"), int(row["income_year"]), str(row["filing"]),
            str(row["hovedskjema_xml"] or ""), documents, tuple(str(issue["message"]) for issue in issues
                if isinstance(issue, dict) and issue.get("level") == "warning" and isinstance(issue.get("message"), str)))

    async def read_submission(self, submission_id):
        rows = await self._rows("select id,approval_id,entitlement_id,company_id,user_id,income_year,obligation,"
            "case_profile,environment,feedback_state from shareholder_register_filing.production_filing_submissions where id=%s::uuid "
            "and user_id=shareholder_register_filing.actor_v1() and public.company_access_is_accepted_owner_v1(company_id)", (submission_id,))
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
        await self._rows("select shareholder_register_filing.assert_fresh_owner_v1(%s::uuid)", (company_id,))

    async def _token(self, company, connection):
        self.require_configuration()
        return await self._maskinporten.request_token(SYSTEM_USER_TAX_SCOPE,
            system_user_org_number=company.org_number, system_user_external_ref=connection.external_ref)

    async def _feedback_tokens(self, company, connection):
        token = await self._token(company, connection)
        try:
            dialog_token = await self._maskinporten.request_token(SYSTEM_USER_DIALOGPORTEN_SCOPE,
                system_user_org_number=company.org_number, system_user_external_ref=connection.external_ref)
        except BaseException:
            token.discard()
            raise
        def discard():
            token.discard()
            dialog_token.discard()
        return token, dialog_token, discard

    async def bind_mutation_authority(self, company, connection):
        token, dialog_token, discard = await self._feedback_tokens(company, connection)
        try:
            return Rf1086MutationBinding(Rf1086AuthorityAdapter(token, transport=self._rf_transport),
                Rf1086ReadOnlyAuthorityAdapter(token, transport=self._rf_transport), discard,
                Rf1086DialogportenAdapter(dialog_token, transport=self._rf_transport))
        except BaseException:
            discard()
            raise

    async def bind_read_only_authority(self, company, connection):
        token, dialog_token, discard = await self._feedback_tokens(company, connection)
        try:
            return Rf1086ReadOnlyBinding(Rf1086ReadOnlyAuthorityAdapter(token, transport=self._rf_transport), discard,
                Rf1086DialogportenAdapter(dialog_token, transport=self._rf_transport))
        except BaseException:
            discard()
            raise

    async def begin_production_filing(self, approval_id):
        rows = await self._rows("select id from shareholder_register_filing.begin_production_filing(%s::uuid)", (approval_id,))
        if not rows:
            raise Rf1086ProductionError("send_unavailable")
        return _id(rows[0], "id")

    def operation_journal(self, submission_id):
        return _OperationJournal(self, submission_id)

    async def claim_feedback_lease(self, submission_id, lease_id):
        rows = await self._rows("select shareholder_register_filing.claim_production_feedback_reconciliation(%s::uuid,%s::uuid) as claimed", (submission_id, lease_id))
        return bool(rows and rows[0]["claimed"] is True)

    async def read_claimed_reference(self, submission_id, lease_id):
        rows = await self._rows("select feedback_forsendelse_id from shareholder_register_filing.production_filing_submissions "
            "where id=%s::uuid and feedback_reconciliation_lease_id=%s::uuid", (submission_id, lease_id))
        if not rows or rows[0]["feedback_forsendelse_id"] is None:
            raise Rf1086ProductionError("status_unavailable")
        return str(rows[0]["feedback_forsendelse_id"])

    async def read_claimed_dialog_id(self, submission_id, lease_id):
        rows = await self._rows("select e.authority_reference,s.feedback_forsendelse_id "
            "from shareholder_register_filing.production_filing_submissions s "
            "join shareholder_register_filing.production_filing_events e on e.submission_id=s.id "
            "where s.id=%s::uuid and s.feedback_reconciliation_lease_id=%s::uuid "
            "and e.operation_name='confirm' and e.operation_state='succeeded' "
            "order by e.created_at desc,e.id desc limit 1", (submission_id, lease_id))
        try:
            row = rows[0]
            confirmation = json.loads(row["authority_reference"])
            if (not isinstance(confirmation, dict) or set(confirmation) != {"dialogId", "forsendelseId"}
                    or confirmation["forsendelseId"] != str(row["feedback_forsendelse_id"])
                    or not isinstance(confirmation["dialogId"], str)
                    or not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", confirmation["dialogId"], re.I)):
                raise ValueError()
            return confirmation["dialogId"]
        except (IndexError, KeyError, TypeError, ValueError):
            raise Rf1086ProductionError("status_unavailable") from None

    async def release_feedback_lease(self, submission_id, lease_id):
        try:
            await self._rows("select shareholder_register_filing.release_production_feedback_reconciliation(%s::uuid,%s::uuid)", (submission_id, lease_id))
        except _PersistenceError:
            # Original release is best effort; the unchanged five-minute lease
            # expiry permits later recovery after a failed release request.
            pass

    def feedback_journal(self, *, submission_id, company_id, income_year, forsendelse_id, lease_id):
        return _FeedbackJournal(self, submission_id, company_id, income_year, forsendelse_id, lease_id)


def _source_admission_company(value, query):
    from talli_backend.application.shareholder_register_source_admission import Rf1086AdmissionCompany
    try:
        if (not isinstance(value, dict) or value['companyId'] != str(query.company_id)
                or type(value['incomeYear']) is not int or value['incomeYear'] != int(query.income_year)
                or value['acceptedOwner'] is not True or value['consequentialOperationsAllowed'] is not True
                or value['entityType'] != 'AS'):
            raise ValueError()
        text = ('organizationNumber', 'legalName', 'address', 'postalCode', 'city')
        if any(not isinstance(value[key], str) or not value[key].strip() for key in text):
            raise ValueError()
        times = [datetime.fromisoformat(value[key]) for key in ('identityConfirmedAt', 'identityLockedAt')]
        if any(item.tzinfo is None for item in times):
            raise ValueError()
        company = rf.Rf1086Company(value['organizationNumber'], value['legalName'], value['address'],
                                  value['postalCode'], value['city'], int(query.income_year))
        return Rf1086AdmissionCompany(company, times[0].isoformat(), times[1].isoformat())
    except (KeyError, TypeError, ValueError, AttributeError):
        raise rf.ShareholderRegisterFilingError.unavailable() from None


class _SourceAdmission:
    def __init__(self, store, connection, query, identity):
        self._store, self._connection, self._query, self._identity = store, connection, query, identity
        self._active = True

    @property
    def actor_id(self):
        return self._store.actor_id

    def close(self):
        self._active = False

    def _require_active(self):
        from psycopg.pq import TransactionStatus
        if not self._active or self._connection.info.transaction_status != TransactionStatus.INTRANS:
            raise rf.ShareholderRegisterFilingError.unavailable()

    async def company_identity(self):
        self._require_active()
        return self._identity

    async def governance_evidence(self, correlation_id):
        self._require_active()
        from talli_backend.adapters.postgres_corporate_reporting_evidence import PostgresCorporateReportingEvidence
        return await PostgresCorporateReportingEvidence(self._connection, self.actor_id).read_reporting_year_evidence(
            company_id=self._query.company_id, income_year=self._query.income_year, correlation_id=correlation_id)

    async def current_source(self):
        self._require_active()
        return await self._store._current_year_source(self._connection, self._query.company_id, self._query.income_year)

    async def source_preview(self, preview_id):
        self._require_active()
        preview = await self._store._read_source_preview(self._connection, preview_id)
        if (preview is None or preview.company_id != self._query.company_id
                or preview.income_year != self._query.income_year):
            raise rf.Rf1086YearSourceError('rf1086_source_preview_not_found')
        return preview

    async def assert_original(self, receipt):
        self._require_active()
        if receipt.company_id != self._query.company_id:
            raise rf.ShareholderRegisterFilingError.forbidden()
        from talli_backend.adapters.postgres_document_originals import PostgresDocumentOriginals
        await PostgresDocumentOriginals(self._connection, self.actor_id).assert_retained_original(receipt)

    async def read_current_register_observation(self, query, observation_id):
        self._require_active()
        if query != self._query:
            raise rf.ShareholderRegisterFilingError.forbidden()
        return await self._store._read_register_observation(self._connection, query, observation_id, current=True)


@rf.rf1086_adapter(rf.ProductionOperationJournal)
class _OperationJournal:
    def __init__(self, session, submission_id):
        self._session, self._submission_id = session, submission_id
        self._operations = {}

    async def prepare(self, *, submission_id, name, body_hash, idempotency_key):
        if submission_id != self._submission_id:
            raise Rf1086ProductionError("basis_unavailable")
        rows = await self._session._rows("select * from shareholder_register_filing.prepare_operation_v1(%s::uuid,%s::text,%s::text,%s::uuid)",
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
        rows = await self._session._rows("select id from shareholder_register_filing.append_production_filing_event("
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


@rf.rf1086_adapter(rf.Rf1086ProductionJournal)
class _FeedbackJournal:
    def __init__(self, session, submission_id, company_id, income_year, forsendelse_id, lease_id):
        self._session, self._submission_id, self._company_id = session, submission_id, company_id
        self._income_year, self._forsendelse_id, self._lease_id = income_year, forsendelse_id, lease_id

    async def read_reconciliation_state(self):
        try:
            rows = await self._session._rows("select feedback_state,feedback_safe_error_code,feedback_correlation_id "
                "from shareholder_register_filing.production_filing_submissions where id=%s::uuid and company_id=%s::uuid", (self._submission_id, self._company_id))
            artifacts = await self._session._rows("select sha256 from shareholder_register_filing.production_feedback_artifacts where submission_id=%s::uuid order by sha256", (self._submission_id,))
            if not rows:
                raise _PersistenceError()
            row = rows[0]
            return Rf1086ReconciliationSnapshot(str(row["feedback_state"]), tuple(str(item["sha256"]) for item in artifacts),
                row["feedback_safe_error_code"], row["feedback_correlation_id"])
        except Exception as error:
            raise create_rf1086_feedback_artifact_persistence_error(error) from None

    async def _existing(self, digest):
        rows = await self._session._rows("select document_id,sha256 from shareholder_register_filing.production_feedback_artifacts "
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
            rows = await self._session._rows("select id from shareholder_register_filing.record_production_feedback_artifact("
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
        rows = await self._session._rows("select shareholder_register_filing.append_production_feedback_reconciliation("
            "%s::uuid,%s::uuid,%s::uuid,%s::text,%s::text[],%s::text,%s::text) as changed",
            (self._submission_id, self._lease_id, self._forsendelse_id, event.state, list(event.artifact_hashes),
             event.safe_error_code, event.correlation_id))
        if not rows or type(rows[0]["changed"]) is not bool:
            raise _PersistenceError()
        return rows[0]["changed"]


__all__ = ["PostgresShareholderRegisterFilingAdapter", "PostgresShareholderRegisterFilingSession"]
