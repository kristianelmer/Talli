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
import math
import os
import re
from urllib.parse import quote, urlencode
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

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
    VerifiedDocumentEvidence, RetainedDocumentOriginalReceipt, document_metadata_sha256,
)
from talli_backend.modules.ledger.public import LedgerError
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ActorId, ActorKind, UserId, CompanyId, IncomeYear, Timestamp


def _id(row, name):
    return str(row[name]) if row.get(name) is not None else ""


def _record_value(value):
    from uuid import UUID
    if isinstance(value, (UUID, datetime)):
        return str(value) if isinstance(value, UUID) else value.isoformat()
    return value


def _validate_retained_correction_query(query, submission_id):
    """Reject malformed scope before opening a connection or taking a guard."""
    try:
        if (type(query) is not rf.Rf1086SourceQuery
                or type(query.actor_id) is not ActorId
                or query.actor_id.kind is not ActorKind.USER
                or type(query.actor_id.subject) is not UserId
                or type(query.company_id) is not CompanyId
                or type(query.income_year) is not IncomeYear
                or type(query.income_year.value) is not int
                or not 2000 <= query.income_year.value <= 2100
                or type(submission_id) is not rf.SubmissionId):
            raise ValueError()
        for value in (query.company_id.value, query.actor_id.subject.value, submission_id.value):
            if type(value) is not str or str(UUID(value)) != value:
                raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None


def _source_digest(value):
    # This versioned persistence comparison is not a statutory payload hash.
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        default=str, ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _parse_retained_year_source(value):
    """Select a frozen codec without reconstructing or upgrading retained bytes."""
    try:
        if type(value) is not str:
            raise ValueError()
        envelope = json.loads(value)
        if type(envelope) is not dict:
            raise ValueError()
        codec = envelope.get("codec")
    except (ValueError, TypeError, RecursionError):
        raise rf.Rf1086YearSourceError("rf1086_source_storage_invalid") from None
    # The selected parser receives the original text, including duplicate keys,
    # and enforces its own exact envelope and closed record registry.
    if codec == "rf1086-year-source-v1":
        return rf.parse_rf1086_year_source(value)
    if codec == "rf1086-year-source-v2":
        return rf.parse_rf1086_year_source_v2(value)
    raise rf.Rf1086YearSourceError("rf1086_source_storage_invalid")


def _assert_retained_year_source_replay(source, command):
    if type(source) is rf.Rf1086YearSourceSnapshot:
        rf.assert_rf1086_year_source_replay(source, command)
    elif type(source) is rf.Rf1086YearSourceSnapshotV2:
        rf.assert_rf1086_year_source_replay_v2(source, command)
    else:
        raise rf.Rf1086YearSourceError("rf1086_source_storage_invalid")


class _PersistenceError(Exception):
    """Only a SQLSTATE is retained for the frozen feedback retry classifier."""
    def __init__(self, code=""):
        self.code = code
        super().__init__("RF1086_PERSISTENCE_UNAVAILABLE")


def _error(error):
    if "production_filing_fresh_owner_step_up_required" in str(error):
        return Rf1086ProductionError("step_up_required")
    return _PersistenceError(getattr(error, "sqlstate", "") or "")


def _require_company_test_retention_live_session(access_token, verified):
    """Only signed-claim correspondence after canonical server authentication."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError()
            result[key] = value
        return result
    def reject_constant(value):
        raise ValueError()
    def finite_float(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError()
        return parsed
    try:
        if type(access_token) is not str or len(access_token) > 65536 or len(access_token.split('.')) != 3:
            raise ValueError()
        import base64
        payload = access_token.split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)),
            object_pairs_hook=unique, parse_constant=reject_constant, parse_float=finite_float)
        if type(claims) is not dict or claims.get('sub') != str(verified.actor_id.subject):
            raise ValueError()
        session_id = claims.get('session_id')
        if type(session_id) is not str or str(UUID(session_id)) != session_id or UUID(session_id).int == 0:
            raise ValueError()
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError):
        raise ShareholderRegisterFilingAuthenticationError() from None


class PostgresCompanyTestRetentionSessionFactory:
    """Explicit composition only; current Auth with no mutable producer bindings."""
    def __init__(self, configuration: LedgerSupabaseConfiguration):
        self._configuration = configuration
        self._authentication = SupabaseLedgerAdapter(configuration)

    async def session(self, access_token: str) -> PostgresShareholderRegisterFilingSession:
        try:
            authenticated = await self._authentication.session(access_token)
        except LedgerAuthenticationError:
            raise ShareholderRegisterFilingAuthenticationError() from None
        except LedgerError:
            raise rf.ShareholderRegisterFilingError.unavailable() from None
        _require_company_test_retention_live_session(access_token, authenticated._verified)
        return PostgresShareholderRegisterFilingSession(self._configuration, authenticated._verified,
            access_token=access_token, billing=None, documents=None, company_access=None,
            environment={})


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
@rf.rf1086_adapter(rf.Rf1086CompanyTestRetentionPersistence)
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
    async def _transaction(self, *, snapshot=False, read_only=False):
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
                if read_only:
                    await connection.execute("set transaction read only")
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
                         "rf1086_source_preview_stale", "rf1086_source_preview_storage_invalid", "rf1086_source_register_observation_stale"):
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
            if "rf1086_source_dispatch_binding_changed" in str(error):
                raise Rf1086ProductionError("connection_unavailable") from None
            if any(code in str(error) for code in ("rf1086_source_review_changed", "rf1086_source_claim_head_changed",
                    "rf1086_source_claim_mismatch", "rf1086_managed_submission_head_required")):
                raise Rf1086ProductionError("payload_changed") from None
            if any(code in str(error) for code in ("rf1086_source_approval_blocked", "rf1086_source_approval_manifest_invalid",
                    "rf1086_source_production_admission_required", "rf1086_source_approval_guard_required",
                    "rf1086_submission_history_ambiguous")):
                raise Rf1086ProductionError("basis_unavailable") from None
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
            # Documents' unchanged owner query uses this transaction-local map.
            # Derive it only from the current Company Access admission under the
            # company guard, replacing any empty or stale session role cache.
            await connection.execute(
                "select pg_catalog.set_config('talli.authorized_company_roles',%s,true)",
                (json.dumps({str(query.company_id): 'owner'}, separators=(',', ':')),),
            )
            await connection.execute('select shareholder_register_filing.lock_year_source_v1(%s::uuid,%s)',
                (str(query.company_id), int(query.income_year)))
            scoped = _SourceAdmission(self, connection, query, identity)
            try:
                yield scoped
            finally:
                scoped.close()

    @asynccontextmanager
    async def source_claim_recovery_v3(self, approval_id, manifest_sha256):
        """Approval-derived historical locks; no fresh admission or owner proof."""
        async with self._transaction() as connection:
            row = await (await connection.execute(
                'select shareholder_register_filing.lock_source_claim_recovery_v3(%s::uuid,%s,%s) as scope',
                (approval_id.value, manifest_sha256, str(self.actor_id.subject)),
            )).fetchone()
            value = row['scope'] if row else None
            try:
                if (type(value) is not dict or set(value) != {'companyId', 'incomeYear'}
                        or type(value['companyId']) is not str or str(UUID(value['companyId'])) != value['companyId']
                        or type(value['incomeYear']) is not int or not 2000 <= value['incomeYear'] <= 2100):
                    raise ValueError()
                query = rf.Rf1086SourceQuery(CompanyId(value['companyId']), IncomeYear(value['incomeYear']), self.actor_id)
            except (ValueError, TypeError, KeyError, AttributeError):
                raise rf.Rf1086ProductionError('basis_unavailable') from None
            scoped = _SourceClaimRecoveryV3(self, connection, query, approval_id, manifest_sha256)
            try:
                yield scoped
            finally:
                scoped.close()

    @asynccontextmanager
    async def source_operation_recovery_v3(self, claim):
        """Owned committed-claim historical scope; no fresh admission or I/O."""
        if type(claim) is not rf.Rf1086SourceSubmissionClaim:
            raise rf.Rf1086ProductionError('basis_unavailable')
        rf.assert_rf1086_source_submission_claim(claim, approval_id=claim.approval_id,
            manifest_sha256=claim.manifest_sha256, expected_head=claim.predecessor_submission_id,
            actor_id=self.actor_id)
        async with self._transaction() as connection:
            row = await (await connection.execute(
                'select shareholder_register_filing.lock_source_claim_recovery_v3(%s::uuid,%s,%s) as scope',
                (claim.approval_id.value, claim.manifest_sha256, str(self.actor_id.subject)),
            )).fetchone()
            value = row['scope'] if row else None
            if (type(value) is not dict or set(value) != {'companyId', 'incomeYear'}
                    or type(value['companyId']) is not str or value['companyId'] != str(claim.company_id)
                    or type(value['incomeYear']) is not int or value['incomeYear'] != int(claim.income_year)):
                raise rf.Rf1086ProductionError('basis_unavailable')
            query = rf.Rf1086SourceQuery(claim.company_id, claim.income_year, self.actor_id)
            scoped = _SourceOperationRecoveryV3(self, connection, query, claim)
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
        source = _parse_retained_year_source(row["snapshot_text"])
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

    async def read_company_test_retention(self, query):
        self._command_actor(query)
        bounds = rf.rf1086_company_test_retention_bounds()
        params = (str(query.company_id),)
        try:
            async with self._transaction(snapshot=True, read_only=True) as connection:
                await connection.execute('select shareholder_register_filing.assert_member_v1(%s::uuid)', params)
                row = await (await connection.execute(
                    "select count(*) as total, transaction_timestamp() as observed_at "
                    "from shareholder_register_filing.authority_test_runs "
                    "where company_id=%s::uuid and obligation='aksjonaerregisteroppgaven'", params)).fetchone()
                if row is None or type(row['total']) is not int or not 0 <= row['total'] <= bounds.max_records:
                    raise rf.ShareholderRegisterFilingError.unavailable()
                capture = rf.create_rf1086_company_test_retention_capture(
                    query.company_id, _record_value(row['observed_at']))
                consumed = 0
                async with connection.cursor(name='rf_company_test_retention_' + uuid4().hex) as cursor:
                    cursor.itersize = bounds.cursor_batch_size
                    await cursor.execute(_company_test_retention_read_sql(bounds), params)
                    async for value in cursor:
                        if value.get('_retention_oversize') is not False:
                            raise rf.ShareholderRegisterFilingError.unavailable()
                        capture.add(self._wire_record(rf.Rf1086TestEvidenceRecord, value))
                        consumed += 1
                if consumed != row['total']:
                    raise rf.ShareholderRegisterFilingError.unavailable()
                return capture.complete()
        except (rf.Rf1086ArchiveError, ValueError, TypeError, KeyError, AttributeError):
            raise rf.ShareholderRegisterFilingError.unavailable() from None

    async def read_source_claim_approval(self, approval_id):
        async with self._transaction(snapshot=True) as connection:
            return await self._read_source_claim_approval(connection, approval_id)

    async def _read_source_claim_approval(self, connection, approval_id):
        row = await (await connection.execute(
            'select a.*,b.manifest_text from shareholder_register_filing.filing_approval_snapshots a '
            'join shareholder_register_filing.source_approval_bindings b on b.approval_id=a.id '
            'and b.company_id=a.company_id and b.income_year=a.income_year and b.preview_id=a.preview_id '
            'and b.approved_by=a.user_id and b.manifest_sha256=a.manifest_hash and b.payload_sha256=a.payload_hash '
            'where a.id=%s::uuid and a.user_id=shareholder_register_filing.actor_v1() '
            'and public.company_access_is_accepted_owner_v1(a.company_id)', (approval_id.value,),
        )).fetchone()
        if row is None:return None
        try:
            value = rf.Rf1086RetainedSourceApproval(self._wire_record(rf.Rf1086ApprovalRecord,row),row['manifest_text'])
            rf.inspect_rf1086_retained_source_approval(value,approval_id=approval_id,
                manifest_sha256=value.approval.manifest_hash,actor_id=self.actor_id)
            return value
        except (ValueError,TypeError,KeyError):
            raise rf.Rf1086ProductionError('basis_unavailable') from None

    async def read_source_claim_approval_v3(self, approval_id):
        async with self._transaction(snapshot=True) as connection:
            return await self._read_source_claim_approval_v3(connection, approval_id)

    async def _read_source_claim_approval_v3(self, connection, approval_id):
        row = await (await connection.execute(
            'select a.*,b.manifest_text from shareholder_register_filing.filing_approval_snapshots a '
            'join shareholder_register_filing.source_approval_bindings b on b.approval_id=a.id '
            'and b.company_id=a.company_id and b.income_year=a.income_year and b.preview_id=a.preview_id '
            'and b.approved_by=a.user_id and b.manifest_sha256=a.manifest_hash and b.payload_sha256=a.payload_hash '
            'where a.id=%s::uuid and a.user_id=shareholder_register_filing.actor_v1() '
            'and public.company_access_is_accepted_owner_v1(a.company_id)', (approval_id.value,),
        )).fetchone()
        if row is None:
            return None
        try:
            value = rf.Rf1086RetainedSourceApproval(self._wire_record(rf.Rf1086ApprovalRecord, row), row['manifest_text'])
            rf.inspect_rf1086_retained_source_approval_v3(value, approval_id=approval_id,
                manifest_sha256=value.approval.manifest_hash, actor_id=self.actor_id)
            return value
        except (ValueError, TypeError, KeyError):
            raise rf.Rf1086ProductionError('basis_unavailable') from None

    async def read_source_operation_approval_v3(self, approval_id):
        """Fixed stored-version selection for owned historical V1/V2/V3 reads."""
        async with self._transaction(snapshot=True) as connection:
            row = await (await connection.execute(
                'select a.*,b.manifest_text from shareholder_register_filing.filing_approval_snapshots a '
                'join shareholder_register_filing.source_approval_bindings b on b.approval_id=a.id '
                'and b.company_id=a.company_id and b.income_year=a.income_year and b.preview_id=a.preview_id '
                'and b.approved_by=a.user_id and b.manifest_sha256=a.manifest_hash and b.payload_sha256=a.payload_hash '
                'where a.id=%s::uuid and a.user_id=shareholder_register_filing.actor_v1() '
                'and public.company_access_is_accepted_owner_v1(a.company_id)', (approval_id.value,),
            )).fetchone()
            if row is None:
                return None
            try:
                retained = rf.Rf1086RetainedSourceApproval(
                    self._wire_record(rf.Rf1086ApprovalRecord, row), row['manifest_text'])
                inspect = (rf.inspect_rf1086_retained_source_approval_v3
                    if retained.approval.manifest.get('schemaVersion') == 'production-source-approval-v3'
                    else rf.inspect_rf1086_retained_source_approval)
                inspect(retained, approval_id=approval_id,
                    manifest_sha256=retained.approval.manifest_hash, actor_id=self.actor_id)
                return retained
            except (ValueError, TypeError, KeyError, AttributeError):
                raise rf.Rf1086ProductionError('basis_unavailable') from None

    async def read_source_submission_claim(self, approval_id, manifest_sha256, expected_head):
        async with self._transaction(snapshot=True) as connection:
            return await self._read_source_submission_claim(connection,approval_id,manifest_sha256,expected_head)

    async def _read_source_submission_claim(self, connection, approval_id, manifest_sha256, expected_head):
        row = await (await connection.execute(
            'select * from shareholder_register_filing.read_source_submission_claim_v1(%s::uuid,%s,%s)',
            (approval_id.value,manifest_sha256,str(self.actor_id.subject)),
        )).fetchone()
        if row is None:return None
        if set(row)==_SOURCE_CLAIM_FIELDS and all(value is None for value in row.values()):return None
        return _source_claim_record(row,approval_id,manifest_sha256,expected_head,self.actor_id)

    async def read_correction_predecessor(self, query, submission_id):
        self._command_actor(query)
        async with self._transaction(snapshot=True) as connection:
            await connection.execute('select shareholder_register_filing.assert_member_v1(%s::uuid)',
                (str(query.company_id),))
            return await self._correction_predecessor(connection,query,submission_id,lock=False)

    async def read_retained_correction_archive(self, query, submission_id):
        """Read a complete raw archive after selected-parent access is established.

        The result still requires the retained correction projector. This read
        confers neither correction authority nor proof of Documents bytes.
        """
        _validate_retained_correction_query(query, submission_id)
        self._command_actor(query)
        async with self._transaction(snapshot=True, read_only=True) as connection:
            return await self._retained_correction_archive_on_connection(
                connection, query, submission_id, lock=False)

    async def _retained_correction_archive_on_connection(self, connection, query, submission_id, *, lock):
        if lock:
            # The enclosing admission already holds company then RF-year guards.
            # The owner RPC asserts original-actor/current-owner access and locks
            # the exact parent before any archive enumeration on this connection.
            row = await (await connection.execute(
                'select * from shareholder_register_filing.lock_correction_predecessor_v1(%s::uuid,%s::uuid,%s,%s)',
                (submission_id.value, str(query.company_id), int(query.income_year), str(self.actor_id.subject)),
            )).fetchone()
        else:
            await connection.execute('select shareholder_register_filing.assert_submission_v1(%s::uuid)',
                (submission_id.value,))
            row = await (await connection.execute(
                'select * from shareholder_register_filing.production_filing_submissions '
                'where id=%s::uuid and company_id=%s::uuid and income_year=%s',
                (submission_id.value, str(query.company_id), int(query.income_year)),
            )).fetchone()
        try:
            if row is None:
                raise ValueError()
            selected = self._wire_record(rf.Rf1086ProductionSubmissionRecord, row)
            if (selected.id != submission_id.value or selected.company_id != str(query.company_id)
                    or type(selected.income_year) is not int or selected.income_year != int(query.income_year)
                    or selected.user_id != str(self.actor_id.subject)
                    or selected.submitted_by != str(self.actor_id.subject)):
                raise ValueError()
            archive = await self._archive_source_on_connection(connection,
                rf.Rf1086ArchiveQuery(query.company_id, query.income_year, query.actor_id), include_production=True)
            # Preserve every actor/profile in the company/year history. Only the
            # selected parent's identity is checked here; the pure projector must
            # validate the complete archive before returning a correction basis.
            parents = tuple(item for item in archive.production_submissions if item.id == submission_id.value)
            if (archive.company_id != query.company_id or archive.income_year != query.income_year
                    or parents != (selected,)):
                raise ValueError()
            return archive
        except (ValueError, TypeError, KeyError, AttributeError):
            raise rf.Rf1086ProductionError('basis_unavailable') from None

    async def _correction_predecessor(self, connection, query, submission_id, *, lock):
        if lock:
            # Owner RPC checks the already-held company/year guards and locks the
            # parent before reading children. Runtime has no direct UPDATE grant.
            row = await (await connection.execute(
                'select * from shareholder_register_filing.lock_correction_predecessor_v1(%s::uuid,%s::uuid,%s,%s)',
                (submission_id.value,str(query.company_id),int(query.income_year),str(self.actor_id.subject)),
            )).fetchone()
        else:
            row = await (await connection.execute(
                'select * from shareholder_register_filing.production_filing_submissions '
                'where id=%s::uuid and company_id=%s::uuid and income_year=%s',
                (submission_id.value,str(query.company_id),int(query.income_year)),
            )).fetchone()
        if row is None:
            raise rf.Rf1086ProductionError('basis_unavailable')
        try:
            submission = self._wire_record(rf.Rf1086ProductionSubmissionRecord,row)
            approval_row = await (await connection.execute(
                'select * from shareholder_register_filing.filing_approval_snapshots '
                'where id=%s::uuid and company_id=%s::uuid and income_year=%s',
                (submission.approval_id,str(query.company_id),int(query.income_year)),
            )).fetchone()
            if approval_row is None:
                raise rf.Rf1086ProductionError('basis_unavailable')
            approval = self._wire_record(rf.Rf1086ApprovalRecord,approval_row)
            preview = await self._preview_record(connection,rf.PreviewId(approval.preview_id))
            artifact_rows = await (await connection.execute(
                'select * from shareholder_register_filing.production_feedback_artifacts '
                'where submission_id=%s::uuid order by document_id,id', (submission_id.value,),
            )).fetchall()
            event_rows = await (await connection.execute(
                "select * from shareholder_register_filing.production_filing_events "
                "where submission_id=%s::uuid and operation_name like 'reconciliation:%%' "
                "and operation_state='succeeded' order by created_at,id", (submission_id.value,),
            )).fetchall()
            lineage = claim = None
            if submission.case_profile == 'rf1086_full_year_v1':
                binding = await (await connection.execute(
                    'select * from shareholder_register_filing.source_approval_bindings '
                    'where approval_id=%s::uuid and company_id=%s::uuid and income_year=%s',
                    (approval.id,str(query.company_id),int(query.income_year)),
                )).fetchone()
                if binding is None:
                    raise rf.Rf1086ProductionError('basis_unavailable')
                lineage = await self._retained_source_approval_lineage(
                    connection,binding,str(query.company_id),int(query.income_year))
                claim = await self._read_source_submission_claim(connection,rf.ApprovalId(approval.id),
                    approval.manifest_hash,None if submission.supersedes_submission_id is None
                    else rf.SubmissionId(submission.supersedes_submission_id))
                if claim is None:
                    raise rf.Rf1086ProductionError('basis_unavailable')
            return rf.Rf1086CorrectionPredecessorSnapshot(query.company_id,query.income_year,submission,approval,preview,
                tuple(self._wire_record(rf.Rf1086ArchiveFeedbackArtifactRecord,item) for item in artifact_rows),
                tuple(self._wire_record(rf.Rf1086ArchiveProductionEventRecord,item) for item in event_rows),
                source_approval_lineage=lineage,source_claim=claim)
        except (TypeError,ValueError,KeyError):
            raise rf.Rf1086ProductionError('basis_unavailable') from None

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

    async def _capture_receipt_row(self, command, idempotency_key, *, table):
        self._command_actor(command)
        if table not in {"year_source_versions", "register_observations"}:
            raise ValueError("Unknown RF capture kind")
        async with self._transaction(snapshot=True, read_only=True) as connection:
            owner = await (await connection.execute(
                "select public.company_access_is_accepted_owner_v1(%s::uuid) as allowed",
                (str(command.company_id),))).fetchone()
            if owner is None or owner["allowed"] is not True:
                raise rf.ShareholderRegisterFilingError.not_found()
            # A concurrent uncommitted capture may be absent from this snapshot.
            # Absence is observational, never permission to issue a new command.
            return await (await connection.execute(
                f"select * from shareholder_register_filing.{table} where company_id=%s::uuid "
                "and income_year=%s and actor_id=%s::uuid and idempotency_key=%s",
                (str(command.company_id), int(command.income_year), str(self.actor_id.subject), str(idempotency_key)),
            )).fetchone()

    async def read_year_source_capture_receipt(self, command, *, idempotency_key):
        row = await self._capture_receipt_row(command, idempotency_key, table="year_source_versions")
        if row is None:
            return None
        original = self._year_source(row)
        _assert_retained_year_source_replay(original, command)
        return original

    async def read_register_observation_capture_receipt(self, command, *, idempotency_key):
        request_sha = rf.rf1086_register_observation_request_digest(command)
        row = await self._capture_receipt_row(command, idempotency_key, table="register_observations")
        if row is None:
            return None
        original = self._register_observation(row)
        if row["request_sha256"] != request_sha:
            raise rf.Rf1086RegisterObservationError("rf1086_register_idempotency_conflict")
        return original

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
                _assert_retained_year_source_replay(original, command)
                return original
            previous = await self._current_year_source(connection, command.company_id, command.income_year)
            if type(previous) is rf.Rf1086YearSourceSnapshotV2:
                # Fresh writes stay v1 until every v2 consumer is released.
                # A retained v2 head must never be fed to the legacy preparer.
                raise rf.Rf1086YearSourceError("rf1086_source_codec_downgrade")
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

    async def record_year_source_v2(self, command, *, originals, idempotency_key, correlation_id):
        """Atomic staged writer; all owner proof and append use this connection."""
        if type(command) is not rf.RecordRf1086YearSource:
            raise rf.Rf1086YearSourceError('rf1086_source_owner_required')
        self._command_actor(command)
        from dataclasses import replace
        from talli_backend.application.shareholder_register_source_capture_v2 import assert_source_capture_originals_v2
        from talli_backend.application.shareholder_register_source_context_v2 import build_verified_source_context_v2
        query = rf.Rf1086SourceQuery(command.company_id, command.income_year, self.actor_id)
        async with self._transaction() as connection:
            # This closed guard checks current owner and lock order, without
            # refreshing year eligibility before the original receipt lookup.
            await connection.execute(
                'select shareholder_register_filing.lock_year_source_capture_v2(%s::uuid,%s::integer)',
                (str(command.company_id), int(command.income_year)))
            replay = await (await connection.execute(
                'select * from shareholder_register_filing.year_source_versions where company_id=%s::uuid '
                'and income_year=%s and actor_id=%s::uuid and idempotency_key=%s',
                (str(command.company_id), int(command.income_year), str(self.actor_id.subject), str(idempotency_key)),
            )).fetchone()
            if replay is not None:
                source = self._year_source(replay)
                _assert_retained_year_source_replay(source, command)
                return source
            row = await (await connection.execute(
                'select public.company_access_read_rf_admission_v1(%s::uuid,%s,%s) as admission',
                (str(command.company_id), int(command.income_year), str(self.actor_id.subject)),
            )).fetchone()
            identity = _source_admission_company(row['admission'] if row else None, query)
            await connection.execute(
                "select pg_catalog.set_config('talli.authorized_company_roles',%s,true)",
                (json.dumps({str(command.company_id): 'owner'}, separators=(',', ':')),))
            scope = _SourceAdmission(self, connection, query, identity)
            try:
                assert_source_capture_originals_v2(command, originals)
                for original in sorted(originals, key=lambda item: item.document_id.value):
                    await scope.assert_original(original)
                company = replace(command.case.company, org_number=identity.company.org_number,
                    name=identity.company.name, address=identity.company.address,
                    postal_code=identity.company.postal_code, city=identity.company.city,
                    income_year=identity.company.income_year)
                identity_sha = rf.rf1086_year_source_digest({'company_id': str(command.company_id),
                    'company': company, 'entity_type': 'AS',
                    'identity_confirmed_at': identity.identity_confirmed_at,
                    'identity_locked_at': identity.identity_locked_at})
                view = await scope.governance_register_evidence(correlation_id)
                context = await build_verified_source_context_v2(scope, command,
                    company, identity_sha, command.documents, view)
                previous = await scope.current_source()
                now = (await (await connection.execute(
                    'select pg_catalog.clock_timestamp() as now')).fetchone())['now']
                source = rf.prepare_rf1086_year_source_v2(command, context=context,
                    source_id=rf.Rf1086YearSourceId(str(uuid4())), confirmed_at=now, previous=previous)
                await self._retain_source_documents(connection, 'rf1086_year_source',
                    source.source_id.value, source.command.documents)
                await scope.prepare_source_governance_proof(source)
                encoded = rf.serialize_rf1086_year_source_v2(source)
                await connection.execute(
                    'select shareholder_register_filing.append_year_source_v2(%s::uuid,%s::uuid,%s,%s,%s,%s,%s,%s::uuid,%s,%s,%s,%s)',
                    (source.source_id.value, str(source.company_id), int(source.income_year), source.version,
                     source.source_sha256, rf.rf1086_year_source_digest(command), str(idempotency_key),
                     previous.source_id.value if previous else None, previous.source_sha256 if previous else None,
                     command.correction_reason, encoded, now))
                saved = await scope.current_source()
                if (type(saved) is not rf.Rf1086YearSourceSnapshotV2
                        or rf.serialize_rf1086_year_source_v2(saved) != encoded):
                    raise rf.Rf1086YearSourceError('rf1086_source_storage_invalid')
                return saved
            finally:
                scope.close()

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
               "where successor.predecessor_id=v.id) "
               "and not exists(select 1 from shareholder_register_filing.register_observation_withdrawals withdrawal "
               "where withdrawal.observation_id=v.id)" if current else ""),
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

    async def read_register_observation_lifecycle_snapshot(self, query):
        self._command_actor(query)
        async with self._transaction(snapshot=True) as connection:
            owner = await (await connection.execute(
                "select public.company_access_is_accepted_owner_v1(%s::uuid) as allowed",
                (str(query.company_id),))).fetchone()
            if owner is None or owner["allowed"] is not True:
                raise rf.ShareholderRegisterFilingError.forbidden()
            rows = {}
            for table in ('register_observations', 'register_observation_withdrawals'):
                rows[table] = await (await connection.execute(
                    f'select * from shareholder_register_filing.{table} '
                    'where company_id=%s::uuid and income_year=%s order by id',
                    (str(query.company_id), int(query.income_year)),)).fetchall()
                count = await (await connection.execute(
                    f'select count(*) as count from shareholder_register_filing.{table} '
                    'where company_id=%s::uuid and income_year=%s',
                    (str(query.company_id), int(query.income_year)),)).fetchone()
                if count is None or type(count.get('count')) is not int or count['count'] != len(rows[table]):
                    raise rf.ShareholderRegisterFilingError.unavailable()
            try:
                observations = tuple(self._register_observation(row) for row in rows['register_observations'])
                withdrawals = []
                for row in rows['register_observation_withdrawals']:
                    receipt = rf.parse_rf1086_register_observation_withdrawal(row['snapshot_text'])
                    command = receipt.command
                    if (receipt.withdrawal_id.value, str(command.company_id), int(command.income_year),
                        str(command.actor_id.subject), command.observation_id.value, command.observation_version,
                        command.observation_fact_sha256, command.reason, receipt.request_sha256,
                        receipt.withdrawal_sha256, receipt.withdrawn_at) != (
                        str(row['id']), str(row['company_id']), row['income_year'], str(row['actor_id']),
                        str(row['observation_id']), row['observation_version'], row['observation_fact_sha256'],
                        row['reason'], row['request_sha256'], row['withdrawal_sha256'], row['withdrawn_at']):
                        raise ValueError('withdrawal row mismatch')
                    withdrawals.append(receipt)
                lifecycle = rf.derive_rf1086_register_observation_lifecycle(company_id=query.company_id,
                    income_year=query.income_year, observations=observations, withdrawals=tuple(withdrawals))
                observed = await (await connection.execute(
                    'select pg_catalog.clock_timestamp() as observed_at', ())).fetchone()
                return rf.Rf1086RegisterObservationLifecycleSnapshot(query.company_id, query.income_year,
                    Timestamp(observed['observed_at']), tuple(sorted(lifecycle,
                        key=lambda item: (item.observation.confirmed_at, item.observation.observation_id.value))))
            except (ValueError, TypeError, KeyError):
                raise rf.ShareholderRegisterFilingError.unavailable() from None

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
        source = _parse_retained_year_source(row["source_snapshot_text"])
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

    async def _retained_source_preview_on_connection(self, connection, query, preview_id):
        row = await (await connection.execute(
            'select p.*,v.snapshot_text as source_snapshot_text '
            'from shareholder_register_filing.source_previews p '
            'join shareholder_register_filing.year_source_versions v on v.id=p.source_id '
            'where p.id=%s::uuid and p.company_id=%s::uuid and p.income_year=%s',
            (str(preview_id), str(query.company_id), int(query.income_year)),
        )).fetchone()
        preview = self._source_preview(row)
        capture = rf.Rf1086ArchiveSourcePreview(preview, row['payload_text'], row['payload_sha256'],
            str(row['created_by']), _record_value(row['created_at']))
        rf.build_rf1086_retained_source_readiness_v2(
            _parse_retained_year_source(row['source_snapshot_text']), capture)
        return capture

    async def retained_source_preview(self, query, preview_id):
        self._command_actor(query)
        async with self._transaction(snapshot=True, read_only=True) as connection:
            return await self._retained_source_preview_on_connection(connection, query, preview_id)

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

    async def _retained_source_approval_lineage(self, connection, binding, company_id, year):
        """Read captured lineage on the caller's snapshot or held admission connection."""
        try:
            source_row = await (await connection.execute(
                'select * from shareholder_register_filing.year_source_versions '
                'where id=%s::uuid and company_id=%s::uuid and income_year=%s',
                (binding['source_id'], company_id, year),
            )).fetchone()
            bridge_row = await (await connection.execute(
                'select * from shareholder_register_filing.source_review_bridges '
                'where preview_id=%s::uuid and company_id=%s::uuid and income_year=%s',
                (binding['preview_id'], company_id, year),
            )).fetchone()
            source = self._year_source(source_row)
            preview = await self._read_source_preview(connection, rf.PreviewId(str(binding['preview_id'])))
            if source is None or bridge_row is None:
                raise ValueError('incomplete retained source approval')
            return rf.Rf1086ArchiveSourceApprovalLineage(
                **{field.name: _record_value(binding[field.name])
                   for field in fields(rf.Rf1086ArchiveSourceApprovalLineage)
                   if field.name not in ('source', 'source_preview', 'bridge')},
                source=source, source_preview=preview,
                bridge=self._wire_record(rf.Rf1086ArchiveSourceReviewBridge, bridge_row),
            )
        except (TypeError, ValueError, KeyError, rf.Rf1086YearSourceError):
            raise rf.ShareholderRegisterFilingError.unavailable() from None

    async def legacy_archive_source(self, query):
        return await self._archive_source(query, include_production=False)

    async def archive_source(self, query):
        return await self._archive_source(query, include_production=True)

    async def _archive_source_history(self, connection, company_id, year):
        """All retained history on the caller's repeatable snapshot, without admission."""
        rows = {}
        for table, ordering in (
            ('year_source_versions', 'version,id'), ('year_source_heads', 'source_id'),
            ('register_observations', 'confirmed_at,id'), ('source_previews', 'created_at,id'),
            ('source_review_bridges', 'created_at,preview_id'),
        ):
            rows[table] = await (await connection.execute(
                f'select * from shareholder_register_filing.{table} '
                f'where company_id=%s::uuid and income_year=%s order by {ordering}',
                (company_id, year),
            )).fetchall()
        try:
            sources = tuple(self._year_source(row) for row in rows['year_source_versions'])
            source_rows = {str(row['id']): row for row in rows['year_source_versions']}
            heads = rows['year_source_heads']
            if len(heads) > 1:
                raise ValueError('multiple source heads')
            head = None
            if heads:
                row = heads[0]
                if type(row['version']) is not int or type(row['income_year']) is not int:
                    raise ValueError('invalid source head')
                head = rf.Rf1086ArchiveYearSourceHead(CompanyId(str(row['company_id'])),
                    IncomeYear(row['income_year']), rf.Rf1086YearSourceId(str(row['source_id'])),
                    row['version'], row['source_sha256'])
            previews = tuple(rf.Rf1086ArchiveSourcePreview(
                self._source_preview({**row, 'source_snapshot_text': source_rows[str(row['source_id'])]['snapshot_text']}),
                row['payload_text'], row['payload_sha256'], str(row['created_by']), _record_value(row['created_at']))
                for row in rows['source_previews'])
            def capture_records(table):
                return tuple(rf.Rf1086ArchiveCaptureRecord(str(row['id']), row['idempotency_key'],
                    row['request_sha256'], row['snapshot_text']) for row in rows[table])
            return rf.Rf1086ArchiveSourceHistory(sources, head,
                tuple(self._register_observation(row) for row in rows['register_observations']), previews,
                tuple(self._wire_record(rf.Rf1086ArchiveSourceReviewBridge, row) for row in rows['source_review_bridges']),
                capture_records('year_source_versions'), capture_records('register_observations'))
        except (ValueError, TypeError, KeyError, rf.Rf1086YearSourceError, rf.Rf1086RegisterObservationError):
            raise rf.ShareholderRegisterFilingError.unavailable() from None

    async def _archive_source(self, query, *, include_production):
        self._command_actor(query)
        async with self._transaction(snapshot=True) as connection:
            return await self._archive_source_on_connection(connection, query, include_production=include_production)

    async def _archive_source_on_connection(self, connection, query, *, include_production):
        self._command_actor(query)
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
        override_rows = await (await connection.execute(
            'select * from shareholder_register_filing.filing_overrides '
            'where company_id=%s::uuid and income_year=%s order by created_at,id',
            (company_id, year),
        )).fetchall()
        try:
            values['overrides'] = tuple(self._wire_record(rf.Rf1086OverrideRecord, row) for row in override_rows)
        except (TypeError, ValueError, KeyError):
            raise rf.ShareholderRegisterFilingError.unavailable() from None
        values['source_history'] = await self._archive_source_history(connection, company_id, year)
        # Captured-empty is established by a complete, scoped database read on
        # the same snapshot as the retained observations. Old HTTP projections
        # explicitly omit this field and retain their historical codecs.
        withdrawal_rows = await (await connection.execute(
            'select id,idempotency_key,request_sha256,snapshot_text '
            'from shareholder_register_filing.register_observation_withdrawals '
            'where company_id=%s::uuid and income_year=%s order by withdrawn_at,id',
            (company_id, year),
        )).fetchall()
        try:
            values['withdrawal_capture_records'] = tuple(rf.Rf1086ArchiveCaptureRecord(
                str(row['id']), row['idempotency_key'], row['request_sha256'], row['snapshot_text'])
                for row in withdrawal_rows)
        except (TypeError, ValueError, KeyError):
            raise rf.ShareholderRegisterFilingError.unavailable() from None
        # Historical approval lineage uses retained versions, never current
        # heads, current Documents status or today's review permissions.
        lineage = []
        if any(row.case_profile == 'rf1086_full_year_v1' for row in values['approvals']):
            bindings = await (await connection.execute(
                'select * from shareholder_register_filing.source_approval_bindings '
                'where company_id=%s::uuid and income_year=%s order by approval_id',
                (company_id, year),
            )).fetchall()
            for binding in bindings:
                lineage.append(await self._retained_source_approval_lineage(
                    connection, binding, company_id, year))
        values['source_approval_lineage'] = tuple(lineage)
        # Claims and the managed head are captured in the same repeatable
        # snapshot as approvals/journal rows, including historical actors.
        claim_rows = await (await connection.execute(
            'select * from shareholder_register_filing.source_submission_bindings '
            'where company_id=%s::uuid and income_year=%s order by submission_id',
            (company_id,year),
        )).fetchall()
        head_rows = await (await connection.execute(
            'select * from shareholder_register_filing.submission_heads '
            'where company_id=%s::uuid and income_year=%s order by obligation,environment',
            (company_id,year),
        )).fetchall()
        try:
            values['source_submission_claims'] = tuple(_source_claim_record(row,
                rf.ApprovalId(str(row['approval_id'])),row['manifest_sha256'],
                None if row['predecessor_submission_id'] is None else rf.SubmissionId(str(row['predecessor_submission_id'])),
                ActorId(ActorKind.USER,UserId(str(row['claimed_by'])))) for row in claim_rows)
            if len(head_rows)>1:raise ValueError('multiple managed heads')
            values['submission_head'] = None
            if head_rows:
                head=head_rows[0]
                if type(head['income_year']) is not int:raise ValueError('invalid head year')
                values['submission_head'] = rf.Rf1086SubmissionHead(CompanyId(str(head['company_id'])),
                    IncomeYear(head['income_year']),head['obligation'],head['environment'],
                    rf.SubmissionId(str(head['submission_id'])),_record_value(head['updated_at']))
        except (ValueError,TypeError,KeyError,rf.Rf1086ProductionError,rf.ShareholderRegisterFilingError):
            raise rf.ShareholderRegisterFilingError.unavailable() from None
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
        values = {field.name: _record_value(row.get(field.name) if record_type is rf.Rf1086ArchiveFeedbackArtifactRecord
            and field.name.startswith('original_') else row[field.name]) for field in fields(record_type)}
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
        if preview.source == 'rf1086-full-year-v1':
            raise rf.Rf1086ProductionError('basis_unavailable')
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
            archive = await self._archive_source_on_connection(connection,
                rf.Rf1086ArchiveQuery(query.company_id, query.income_year, query.actor_id), include_production=True)
            # Independent counts expose truncated/new-family enumeration. The
            # same repeatable snapshot and accepted-owner completeness apply.
            family_counts = {}
            for table in ('year_source_versions','year_source_heads','register_observations','register_observation_withdrawals',
                          'source_previews','source_review_bridges','source_approval_bindings',
                          'source_submission_bindings','submission_heads'):
                count = await (await connection.execute(
                    f'select count(*) as count from shareholder_register_filing.{table} '
                    'where company_id=%s::uuid and income_year=%s',
                    (str(query.company_id), int(query.income_year)),
                )).fetchone()
                family_counts[table] = count['count']
            as_of = await (await connection.execute(
                'select pg_catalog.transaction_timestamp() as observed_at,public.company_access_is_accepted_owner_v1(%s::uuid) as complete',
                (str(query.company_id),),
            )).fetchone()
            return rf.Rf1086SourceSnapshot(workspace,inventory,journal,tuple(bases),Timestamp(as_of['observed_at']),as_of['complete'] is True,tuple(opening_sources),archive,family_counts)

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

    async def finish_source_operation(self, submission_id, intent_id, *, state, reference=None, failure=None):
        rows = await self._rows(
            'select * from shareholder_register_filing.finish_source_operation_v1(%s::uuid,%s::uuid,%s,%s,%s,%s)',
            (submission_id.value, intent_id, state, reference, failure, str(self.actor_id.subject)))
        if not rows:
            raise rf.Rf1086ProductionError('basis_unavailable')
        return self._wire_record(rf.Rf1086ArchiveProductionEventRecord, rows[0])

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


class _SourceClaimRecoveryV3:
    """Historical read scope; only the fixed transition yields fresh write ports."""
    def __init__(self, store, connection, query, approval_id, manifest_sha256):
        self._store, self._connection, self._query = store, connection, query
        self._approval_id, self._manifest_sha256 = approval_id, manifest_sha256
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

    async def read_source_submission_claim(self, approval_id, manifest_sha256, expected_head):
        self._require_active()
        if approval_id != self._approval_id or manifest_sha256 != self._manifest_sha256:
            raise rf.Rf1086ProductionError('payload_changed')
        value = await self._store._read_source_submission_claim(
            self._connection, approval_id, manifest_sha256, expected_head)
        if value is not None and (value.company_id != self._query.company_id or value.income_year != self._query.income_year):
            raise rf.Rf1086ProductionError('basis_unavailable')
        return value

    async def read_source_claim_approval_v3(self, approval_id):
        self._require_active()
        if approval_id != self._approval_id:
            raise rf.Rf1086ProductionError('payload_changed')
        value = await self._store._read_source_claim_approval_v3(self._connection, approval_id)
        if value is not None and (value.approval.company_id != str(self._query.company_id)
                or value.approval.income_year != int(self._query.income_year)):
            raise rf.Rf1086ProductionError('basis_unavailable')
        return value

    @asynccontextmanager
    async def fresh_admission_v3(self):
        self._require_active()
        row = await (await self._connection.execute(
            'select public.company_access_read_rf_admission_v1(%s::uuid,%s,%s) as admission',
            (str(self._query.company_id), int(self._query.income_year), str(self.actor_id.subject)),
        )).fetchone()
        identity = _source_admission_company(row['admission'] if row else None, self._query)
        await self._connection.execute("select pg_catalog.set_config('talli.authorized_company_roles',%s,true)",
            (json.dumps({str(self._query.company_id): 'owner'}, separators=(',', ':')),))
        await self._connection.execute('select shareholder_register_filing.lock_year_source_v1(%s::uuid,%s)',
            (str(self._query.company_id), int(self._query.income_year)))
        scoped = _SourceAdmission(self._store, self._connection, self._query, identity)
        try:
            yield scoped
        finally:
            scoped.close()


class PostgresShareholderRegisterSourceDispatchV3Adapter(PostgresShareholderRegisterFilingAdapter):
    """Staged composition; reuse current Auth and own the fixed correction receiver."""
    async def session(self, access_token: str) -> PostgresShareholderRegisterFilingSession:
        session = await super().session(access_token)
        if self._documents is not None:
            from talli_backend.application.shareholder_register_source_correction import ShareholderRegisterSourceCorrection
            session._source_correction_v3 = ShareholderRegisterSourceCorrection(self, self._documents)
        return session


class _SourceOperationRecoveryV3:
    """Historical read-only scope, physically bound to one guarded connection."""
    def __init__(self, store, connection, query, claim):
        self._store, self._connection, self._query, self._claim = store, connection, query, claim
        self._binding = connection, query, claim, store.actor_id
        self._active = True

    @property
    def actor_id(self):
        return self._store.actor_id

    def close(self):
        self._active = False

    def _require_active(self):
        from psycopg.pq import TransactionStatus
        if (not self._active or self._connection.info.transaction_status != TransactionStatus.INTRANS
                or self._connection is not self._binding[0] or self._query != self._binding[1]
                or self._claim != self._binding[2] or self.actor_id != self._binding[3]
                or self._claim.claimed_by != self.actor_id
                or self._query.actor_id != self.actor_id):
            raise rf.ShareholderRegisterFilingError.unavailable()

    async def read_operation_recovery(self):
        self._require_active()
        claim = await self._store._read_source_submission_claim(self._connection,
            self._claim.approval_id, self._claim.manifest_sha256, self._claim.predecessor_submission_id)
        self._require_active()
        if claim != self._claim:
            raise rf.Rf1086ProductionError('basis_unavailable')
        archive_query = rf.Rf1086ArchiveQuery(claim.company_id, claim.income_year, self.actor_id)
        archive = await self._store._archive_source_on_connection(self._connection,
            archive_query, include_production=True)
        self._require_active()
        assessment = rf.assess_rf1086_retained_source_dispatch(archive,
            query=archive_query, submission_id=claim.submission_id)
        if assessment.claim != claim:
            raise rf.Rf1086ProductionError('basis_unavailable')
        return rf.Rf1086SourceOperationRecoveryV3(claim, archive, assessment)


    @asynccontextmanager
    async def fresh_operation_admission_v3(self):
        """History first, then fixed current admission on the same connection."""
        observed = await self.read_operation_recovery()
        assessment = observed.assessment
        if assessment.disposition == 'recovery_required':
            raise rf.Rf1086UnknownProductionOutcomeError(assessment.pending_operation)
        if assessment.disposition == 'blocked':
            raise rf.Rf1086BlockedProductionOperationError(assessment.pending_operation)
        if assessment.disposition == 'current_approval_required':
            raise rf.Rf1086ProductionError('payload_changed')
        if assessment.disposition not in ('current_admission_required', 'retry_admission_required'):
            raise rf.Rf1086ProductionError('basis_unavailable')
        try:
            approval = next(row for row in observed.retained_archive.approvals
                if row.id == self._claim.approval_id.value)
            lineage = next(row for row in observed.retained_archive.source_approval_lineage
                if row.approval_id == approval.id)
        except StopIteration:
            raise rf.Rf1086ProductionError('basis_unavailable') from None
        # Read compatibility never authorizes a fresh legacy first effect.
        rf.inspect_rf1086_source_operation_identity_v3(self._claim,
            rf.Rf1086RetainedSourceApproval(approval, lineage.manifest_text), actor_id=self.actor_id)
        self._require_active()
        row = await (await self._connection.execute(
            'select public.company_access_read_rf_admission_v1(%s::uuid,%s,%s) as admission',
            (str(self._query.company_id), int(self._query.income_year), str(self.actor_id.subject)),
        )).fetchone()
        self._require_active()
        identity = _source_admission_company(row['admission'] if row else None, self._query)
        await self._connection.execute("select pg_catalog.set_config('talli.authorized_company_roles',%s,true)",
            (json.dumps({str(self._query.company_id): 'owner'}, separators=(',', ':')),))
        self._require_active()
        await self._connection.execute('select shareholder_register_filing.lock_year_source_v1(%s::uuid,%s)',
            (str(self._query.company_id), int(self._query.income_year)))
        self._require_active()
        scoped = _SourceOperationAdmissionV3(self,
            _SourceAdmission(self._store, self._connection, self._query, identity))
        try:
            yield scoped
        finally:
            scoped.close()


class _SourceOperationAdmissionV3:
    """Only required held reads; each checks both lifetimes and physical identity."""
    def __init__(self, recovery, held):
        self._recovery, self._held = recovery, held
        self._active = True

    @property
    def actor_id(self):
        return self._recovery.actor_id

    def close(self):
        self._active = False
        self._held.close()

    def _require_active(self):
        self._recovery._require_active()
        if (not self._active or self._held._connection is not self._recovery._binding[0]
                or self._held._query != self._recovery._binding[1]
                or self._held.actor_id != self.actor_id):
            raise rf.ShareholderRegisterFilingError.unavailable()
        self._held._require_active()

    async def _held_read(self, name, *args):
        self._require_active()
        result = await getattr(self._held, name)(*args)
        self._require_active()
        return result

    async def company_identity(self):
        return await self._held_read('company_identity')

    async def current_source(self):
        return await self._held_read('current_source')

    async def retained_source_preview(self, preview_id):
        return await self._held_read('retained_source_preview', preview_id)

    async def assert_original(self, receipt):
        return await self._held_read('assert_original', receipt)

    async def assert_historical_original(self, receipt):
        return await self._held_read('assert_historical_original', receipt)

    async def governance_register_evidence(self, correlation_id):
        return await self._held_read('governance_register_evidence', correlation_id)

    async def read_current_register_observation(self, query, observation_id):
        return await self._held_read('read_current_register_observation', query, observation_id)

    async def read_retained_correction_archive(self, query, submission_id):
        return await self._held_read('read_retained_correction_archive', query, submission_id)

    async def submission_history(self):
        return await self._held_read('submission_history')

    async def read_source_approval_context_v3(self, preview_id, entitlement_id, correlation_id):
        return await self._held_read('read_source_approval_context_v3', preview_id, entitlement_id, correlation_id)

    async def annual_opening_inputs(self):
        return await self._held_read('annual_opening_inputs')

    async def annual_ledger_inputs(self, correlation_id):
        return await self._held_read('annual_ledger_inputs', correlation_id)

    async def bank_year_evidence(self, correlation_id):
        return await self._held_read('bank_year_evidence', correlation_id)

    async def annual_interview(self):
        return await self._held_read('annual_interview')

    async def annual_document_inputs(self):
        return await self._held_read('annual_document_inputs')

    async def _owned_operation_binding_v3(self, claim):
        self._require_active()
        if type(claim) is not rf.Rf1086SourceSubmissionClaim or claim != self._recovery._claim:
            raise rf.Rf1086ProductionError('basis_unavailable')
        observed = await self._recovery.read_operation_recovery()
        self._require_active()
        try:
            approval = next(row for row in observed.retained_archive.approvals
                if row.id == claim.approval_id.value)
            lineage = next(row for row in observed.retained_archive.source_approval_lineage
                if row.approval_id == approval.id)
        except StopIteration:
            raise rf.Rf1086ProductionError('basis_unavailable') from None
        retained = rf.Rf1086RetainedSourceApproval(approval, lineage.manifest_text)
        prior = rf.inspect_rf1086_source_operation_identity_v3(claim, retained, actor_id=self.actor_id)
        return retained, lineage, prior

    async def prepare_main_operation_v3(self, prepared, *, idempotency_key,
            expected_event_id, connection, correlation_id):
        """Derive the complete current proof from owned inputs on this scope."""
        from talli_backend.application.shareholder_register_source_dispatch_v3 import PreparedRf1086MainOperationV3
        from talli_backend.application.shareholder_register_source_admission_v2 import PreparedRf1086SourceAdmissionV2
        from talli_backend.application.shareholder_register_source_capture_v2 import assert_source_capture_originals_v2
        from talli_backend.application.shareholder_register_source_correction import (
            ShareholderRegisterSourceCorrection, VerifiedRf1086Correction)
        self._require_active()
        if (type(prepared) is not PreparedRf1086MainOperationV3
                or type(prepared.preview) is not PreparedRf1086SourceAdmissionV2):
            raise rf.Rf1086ProductionError('basis_unavailable')
        claim = prepared.claim
        retained, lineage, prior = await self._owned_operation_binding_v3(claim)
        if prior is None:
            if prepared.correction is not None:
                raise rf.Rf1086ProductionError('basis_unavailable')
        else:
            correction = prepared.correction
            receiver = getattr(self._held._store, '_source_correction_v3', None)
            if (type(correction) is not VerifiedRf1086Correction
                    or correction.company_id != claim.company_id or correction.income_year != claim.income_year
                    or correction.actor_id != self.actor_id or correction.predecessor != prior
                    or type(receiver) is not ShareholderRegisterSourceCorrection):
                raise rf.Rf1086ProductionError('basis_unavailable')
            await receiver.assert_admitted(correction, self)
            self._require_active()
        if retained != prepared.retained or lineage.source != prepared.preview.source:
            raise rf.Rf1086ProductionError('payload_changed')
        rf.assert_rf1086_source_main_preflight_v3(claim, retained, prepared.preview.source,
            prepared.preview.retained_preview, actor_id=self.actor_id)
        assert_source_capture_originals_v2(prepared.preview.source.command, prepared.preview.originals)
        for receipt in prepared.preview.originals:
            await self.assert_original(receipt)
        rf.assert_rf1086_source_operation_history_v3(claim, retained,
            await self.submission_history(), actor_id=self.actor_id)
        source, capture, annual, review = await self._held._source_approval_state_v3(
            rf.PreviewId(retained.approval.preview_id), retained.approval.entitlement_id, correlation_id)
        self._require_active()
        if (source != prepared.preview.source or capture != prepared.preview.retained_preview
                or not review.can_approve):
            raise rf.Rf1086ProductionError('payload_changed')
        basis = rf.Rf1086SourceApprovalManifestBasisV3(source, capture.preview, annual, self.actor_id,
            retained.approval.entitlement_id, review.review_sha256, review.warning_codes, prior)
        rebuilt = rf.build_rf1086_retained_source_approval_manifest_v3(basis, capture)
        if (rf.serialize_rf1086_source_approval_manifest_v3(rebuilt) != retained.manifest_text
                or rebuilt.manifest_sha256 != claim.manifest_sha256):
            raise rf.Rf1086ProductionError('payload_changed')
        # The payload digest is the saved main-body digest, not the package hash.
        body_sha = next(item['sha256'] for item in retained.approval.manifest['documentHashes']
            if item['name'] == 'hovedskjema')
        return await self._prepare_operation_v3(claim, 'post_hovedskjema', body_sha,
            idempotency_key, expected_event_id, connection,
            rf.serialize_rf1086_retained_annual_readiness_v2(annual, source, capture))

    async def _prepare_saved_operation_v3(self, claim, operation_name, body_sha256,
            idempotency_key, expected_event_id, connection):
        _, lineage, _ = await self._owned_operation_binding_v3(claim)
        # Saved source only: no current source head, annual reads or original I/O.
        await self._held.prepare_source_governance_proof(lineage.source)
        self._require_active()
        return await self._prepare_operation_v3(claim, operation_name, body_sha256,
            idempotency_key, expected_event_id, connection, None)

    async def prepare_child_operation_v3(self, claim, *, document_name, body_sha256,
            idempotency_key, expected_event_id, connection, correlation_id):
        if type(document_name) is not str or not document_name.startswith('underskjema_'):
            raise rf.Rf1086ProductionError('basis_unavailable')
        return await self._prepare_saved_operation_v3(claim,
            'post_underskjema:' + document_name[len('underskjema_'):], body_sha256,
            idempotency_key, expected_event_id, connection)

    async def prepare_confirm_operation_v3(self, claim, *, body_sha256,
            idempotency_key, expected_event_id, connection, correlation_id):
        return await self._prepare_saved_operation_v3(claim, 'confirm', body_sha256,
            idempotency_key, expected_event_id, connection)

    async def _prepare_operation_v3(self, claim, name, body_sha, key, expected_event, connection, annual_text):
        self._require_active()
        if (type(connection) is not rf.Rf1086Connection
                or connection.company_id != str(claim.company_id)
                or connection.initiating_owner_user_id != str(self.actor_id.subject)
                or connection.obligation != 'aksjonaerregisteroppgaven'
                or connection.status != 'accepted' or not connection.preflight_verified):
            raise rf.Rf1086ProductionError('basis_unavailable')
        row = await (await self._held._connection.execute(
            'select shareholder_register_filing.prepare_source_operation_v3(%s::uuid,%s,%s,%s,%s::uuid,%s::uuid,%s,%s::uuid,%s,%s) as result',
            (claim.submission_id.value, claim.manifest_sha256, name, body_sha, key,
             expected_event, annual_text, connection.id, connection.external_ref, str(self.actor_id.subject)),
        )).fetchone()
        self._require_active()
        value = row['result'] if row else None
        if (type(value) is not dict or set(value) != {'operation', 'newlyPrepared'}
                or type(value['newlyPrepared']) is not bool or type(value['operation']) is not dict):
            raise rf.Rf1086ProductionError('basis_unavailable')
        operation = dict(value['operation'])
        try:
            operation['created_at'] = Timestamp(datetime.fromisoformat(operation['created_at'])).value
            event = self._held._store._wire_record(rf.Rf1086ArchiveProductionEventRecord, operation)
        except (KeyError, TypeError, ValueError):
            raise rf.Rf1086ProductionError('basis_unavailable') from None
        if (event.submission_id != claim.submission_id.value or event.operation_name != name
                or event.company_id != str(claim.company_id) or event.income_year != int(claim.income_year)
                or event.body_hash != body_sha or event.idempotency_key is None
                or type(event.attempt) is not int or not 1 <= event.attempt <= 20
                or (value['newlyPrepared'] and (event.operation_state != 'prepared'
                    or event.idempotency_key != key and expected_event is None))):
            raise rf.Rf1086ProductionError('basis_unavailable')
        return rf.Rf1086SourceOperationPreparation(event, value['newlyPrepared'])


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

    async def bank_year_evidence(self, correlation_id):
        self._require_active()
        from talli_backend.adapters.supabase_banking import SupabaseBankingWorkflowTransaction
        banking = SupabaseBankingWorkflowTransaction(
            self._store._configuration.database_url, self._store._verified, self._connection)
        return await banking.read_year_reconciliation_evidence(
            actor_id=self.actor_id, company_id=self._query.company_id,
            income_year=self._query.income_year, correlation_id=correlation_id)

    async def annual_ledger_inputs(self, correlation_id):
        self._require_active()
        from talli_backend.adapters.supabase_ledger import SupabaseLedgerWorkflowTransaction
        from talli_backend.application.shareholder_register_annual_ledger import read_annual_ledger_inputs
        ledger = SupabaseLedgerWorkflowTransaction(
            self._store._configuration.database_url, self._store._verified, self._connection)
        return await read_annual_ledger_inputs(ledger, self._query, correlation_id)

    async def annual_document_inputs(self):
        self._require_active()
        from talli_backend.adapters.supabase_documents import SupabaseDocumentMetadataTransaction
        from talli_backend.application.shareholder_register_annual_documents import annual_document_inputs
        documents = SupabaseDocumentMetadataTransaction(self._connection, self.actor_id)
        return annual_document_inputs(await documents.list_documents((self._query.company_id,)), self._query)

    async def annual_opening_inputs(self):
        self._require_active()
        from talli_backend.application.shareholder_register_annual_opening import annual_opening_inputs
        args = (str(self._query.company_id), int(self._query.income_year), str(self.actor_id.subject))
        openings = await (await self._connection.execute(
            'select * from shareholder_register_filing.read_opening_snapshots_v1(%s::uuid,%s,%s)', args)).fetchall()
        shareholders = await (await self._connection.execute(
            'select * from shareholder_register_filing.read_opening_shareholders_v1(%s::uuid,%s,%s)', args)).fetchall()
        return annual_opening_inputs(openings, shareholders, self._query)

    async def annual_interview(self):
        self._require_active()
        from talli_backend.adapters.postgres_rf_annual_interview import annual_interview_for_year
        rows = await (await self._connection.execute(
            'select backend_system.list_annual_data_legacy_v1(%s::uuid,%s::integer,%s::text) as items',
            (str(self._query.company_id), int(self._query.income_year), str(self.actor_id.subject)),
        )).fetchall()
        if len(rows) != 1 or 'items' not in rows[0]:
            raise rf.ShareholderRegisterFilingError.unavailable()
        return annual_interview_for_year(rows[0]['items'], self._query)

    async def governance_evidence(self, correlation_id):
        self._require_active()
        from talli_backend.adapters.postgres_corporate_reporting_evidence import PostgresCorporateReportingEvidence
        return await PostgresCorporateReportingEvidence(self._connection, self.actor_id).read_reporting_year_evidence(
            company_id=self._query.company_id, income_year=self._query.income_year, correlation_id=correlation_id)

    async def governance_register_evidence(self, correlation_id):
        self._require_active()
        from talli_backend.adapters.postgres_corporate_reporting_evidence import PostgresCorporateReportingEvidence
        from talli_backend.modules.corporate_governance.public import CorporateReportingRegisterEvidenceQuery
        query = CorporateReportingRegisterEvidenceQuery(
            self._query.company_id, self._query.income_year, self.actor_id)
        return await PostgresCorporateReportingEvidence(
            self._connection, self.actor_id).read_reporting_year_register_evidence(query)

    async def prepare_source_governance_proof(self, source):
        """Call the closed owner producer; no Python value confers SQL authority."""
        self._require_active()
        if (type(source) is not rf.Rf1086YearSourceSnapshotV2
                or source.company_id != self._query.company_id
                or source.income_year != self._query.income_year):
            raise rf.Rf1086YearSourceError('rf1086_source_company_year_mismatch')
        rf.assert_rf1086_year_source_integrity_v2(source)
        from talli_backend.adapters.postgres_corporate_reporting_evidence import PostgresCorporateReportingEvidence
        await PostgresCorporateReportingEvidence(
            self._connection, self.actor_id).prepare_rf_year_source_governance_proof(
                company_id=self._query.company_id, income_year=self._query.income_year,
                source_sha256=source.source_sha256)

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

    async def retained_source_preview(self, preview_id):
        self._require_active()
        capture = await self._store._retained_source_preview_on_connection(
            self._connection, self._query, preview_id)
        if (capture.preview.company_id != self._query.company_id
                or capture.preview.income_year != self._query.income_year):
            raise rf.Rf1086YearSourceError('rf1086_source_preview_not_found')
        return capture

    async def capture_source_preview_v2(self, prepared):
        """Append only on this held owner scope, using the closed SQL proof."""
        self._require_active()
        if type(prepared) is not rf.Rf1086PreparedSourcePreview:
            raise rf.Rf1086YearSourceError('rf1086_source_preview_invalid')
        source = prepared.source
        if (type(source) is not rf.Rf1086YearSourceSnapshotV2
                or source.company_id != self._query.company_id
                or source.income_year != self._query.income_year):
            raise rf.Rf1086YearSourceError('rf1086_source_company_year_mismatch')
        rf.assert_rf1086_year_source_integrity_v2(source)
        current = await self.current_source()
        if (type(current) is not rf.Rf1086YearSourceSnapshotV2
                or rf.serialize_rf1086_year_source_v2(current) != rf.serialize_rf1086_year_source_v2(source)):
            raise rf.Rf1086YearSourceError('rf1086_source_changed')
        if type(prepared.rendered) is not rf.Rf1086RenderedPreview:
            raise rf.Rf1086YearSourceError('rf1086_source_preview_invalid')
        # Full prepared correspondence includes filing, which contributes to
        # the UUID identity but is absent from the saved preview DTO.
        # Only deterministic in-memory RF rendering runs under this guard.
        rf.assert_rf1086_prepared_source_preview_matches(prepared, source)
        rendered = prepared.rendered
        identity = "rf1086-source-preview:full-year-v1:" + source.source_id.value + ":" + source.source_sha256 + ":" + rf.rf1086_year_source_digest(rendered)
        preview = rf.Rf1086SourcePreview(
            preview_id=rf.PreviewId(str(uuid5(NAMESPACE_URL, identity))),
            company_id=source.company_id, income_year=source.income_year, source_id=source.source_id,
            source_sha256=source.source_sha256, case_sha256=source.case_sha256,
            readiness_status=rendered.status, readiness_issues=rendered.issues, preview_text=rendered.preview,
            hovedskjema_xml=rendered.hovedskjema_xml, underskjema_xml=rendered.underskjema_xml)
        encoded = rf.serialize_rf1086_source_preview(preview)
        payload_sha = hashlib.sha256(encoded.encode('utf-8')).hexdigest()
        await self.prepare_source_governance_proof(source)
        saved = await (await self._connection.execute(
            'select shareholder_register_filing.append_source_preview_v1('
            '%s::uuid,%s::uuid,%s,%s::uuid,%s,%s,%s,%s) as id',
            (str(preview.preview_id), str(source.company_id), int(source.income_year),
             source.source_id.value, source.source_sha256, source.case_sha256, payload_sha, encoded),
        )).fetchone()
        if saved is None or str(saved['id']) != str(preview.preview_id):
            raise rf.Rf1086YearSourceError('rf1086_source_preview_storage_invalid')
        retained = await self.retained_source_preview(preview.preview_id)
        if (retained.preview != preview or retained.payload_text != encoded
                or retained.payload_sha256 != payload_sha):
            raise rf.Rf1086YearSourceError('rf1086_source_preview_storage_invalid')
        return retained

    async def assert_original(self, receipt):
        self._require_active()
        if receipt.company_id != self._query.company_id:
            raise rf.ShareholderRegisterFilingError.forbidden()
        from talli_backend.adapters.postgres_document_originals import PostgresDocumentOriginals
        await PostgresDocumentOriginals(self._connection, self.actor_id).assert_retained_original(receipt)

    async def assert_historical_original(self, receipt):
        self._require_active()
        if receipt.company_id != self._query.company_id:
            raise rf.ShareholderRegisterFilingError.forbidden()
        from talli_backend.adapters.postgres_document_originals import PostgresDocumentOriginals
        await PostgresDocumentOriginals(self._connection, self.actor_id).assert_historical_original(receipt)

    async def read_correction_predecessor(self, query, submission_id):
        self._require_active()
        if query != self._query:
            raise rf.ShareholderRegisterFilingError.forbidden()
        return await self._store._correction_predecessor(self._connection,query,submission_id,lock=True)

    async def read_retained_correction_archive(self, query, submission_id):
        """Read under the existing guards; never open a second transaction."""
        self._require_active()
        _validate_retained_correction_query(query, submission_id)
        self._store._command_actor(query)
        if query != self._query:
            raise rf.ShareholderRegisterFilingError.forbidden()
        return await self._store._retained_correction_archive_on_connection(
            self._connection, query, submission_id, lock=True)

    async def submission_history(self):
        self._require_active()
        # The enclosing company/year guards serialize all journal writers.
        # Enumerate every owner's row: actor or profile filtering could hide a
        # competing first filing. Existing company-member SELECT/RLS applies.
        rows = await (await self._connection.execute(
            'select * from shareholder_register_filing.production_filing_submissions '
            'where company_id=%s::uuid and income_year=%s '
            "and obligation='aksjonaerregisteroppgaven' and environment='production' order by id",
            (str(self._query.company_id), int(self._query.income_year)),
        )).fetchall()
        return tuple(self._store._wire_record(rf.Rf1086ProductionSubmissionRecord, row) for row in rows)

    async def bridge_source_preview(self, preview):
        self._require_active()
        if (preview.company_id != self._query.company_id or preview.income_year != self._query.income_year
                or await self.source_preview(preview.preview_id) != preview):
            raise rf.Rf1086YearSourceError('rf1086_source_preview_mismatch')
        payload_sha = hashlib.sha256(rf.serialize_rf1086_source_preview(preview).encode('utf-8')).hexdigest()
        row = await (await self._connection.execute(
            'select shareholder_register_filing.bridge_source_preview_v1(%s::uuid,%s,%s) as id',
            (preview.preview_id.value, payload_sha, str(self.actor_id.subject)),
        )).fetchone()
        if row is None or str(row['id']) != preview.preview_id.value:
            raise rf.Rf1086YearSourceError('rf1086_source_preview_storage_invalid')
        return preview.preview_id

    async def read_source_claim_approval(self, approval_id):
        self._require_active()
        value = await self._store._read_source_claim_approval(self._connection,approval_id)
        if value is not None and (value.approval.company_id!=str(self._query.company_id)
                or value.approval.income_year!=int(self._query.income_year)):
            raise rf.Rf1086ProductionError('basis_unavailable')
        return value

    async def read_source_submission_claim(self, approval_id, manifest_sha256, expected_head):
        self._require_active()
        value = await self._store._read_source_submission_claim(self._connection,approval_id,manifest_sha256,expected_head)
        if value is not None and (value.company_id!=self._query.company_id or value.income_year!=self._query.income_year):
            raise rf.Rf1086ProductionError('basis_unavailable')
        return value

    async def claim_source_submission(self, approval_id, manifest_sha256, expected_head, annual):
        self._require_active()
        row = await (await self._connection.execute(
            'select shareholder_register_filing.claim_source_submission_v2(%s::uuid,%s,%s::uuid,%s,%s) as result',
            (approval_id.value,manifest_sha256,None if expected_head is None else expected_head.value,
             await self._annual_proof_text(annual),str(self.actor_id.subject)),
        )).fetchone()
        value = row['result'] if row else None
        if type(value) is not dict or set(value)!={'claim','newlyClaimed'} or type(value['newlyClaimed']) is not bool:
            raise rf.Rf1086ProductionError('basis_unavailable')
        claim = _source_claim_record(value['claim'],approval_id,manifest_sha256,expected_head,self.actor_id)
        if claim.company_id!=self._query.company_id or claim.income_year!=self._query.income_year:
            raise rf.Rf1086ProductionError('basis_unavailable')
        return rf.Rf1086SourceSubmissionClaimResult(claim,value['newlyClaimed'])

    async def claim_source_submission_v3(self, approval_id, manifest_sha256, expected_head, correlation_id):
        """Recover first; rebuild annual/review/manifest from held owned inputs."""
        self._require_active()
        existing = await self.read_source_submission_claim(approval_id, manifest_sha256, expected_head)
        if existing is not None:
            return rf.Rf1086SourceSubmissionClaimResult(existing, False)
        retained = await self._store._read_source_claim_approval_v3(self._connection, approval_id)
        prior = rf.inspect_rf1086_retained_source_approval_v3(retained, approval_id=approval_id,
            manifest_sha256=manifest_sha256, actor_id=self.actor_id)
        approval = retained.approval
        if (approval.company_id != str(self._query.company_id) or approval.income_year != int(self._query.income_year)
                or approval.invalidated_at is not None or (None if prior is None else prior.submission_id) != expected_head):
            raise rf.Rf1086ProductionError('payload_changed')
        rf.assert_rf1086_submission_predecessor(await self.submission_history(),
            company_id=self._query.company_id, income_year=self._query.income_year, predecessor=prior)
        source, capture, annual, review = await self._source_approval_state_v3(
            rf.PreviewId(approval.preview_id), approval.entitlement_id, correlation_id)
        if not review.can_approve:
            raise rf.Rf1086ProductionError('basis_unavailable')
        basis = rf.Rf1086SourceApprovalManifestBasisV3(source, capture.preview, annual,
            self.actor_id, approval.entitlement_id, review.review_sha256, review.warning_codes, prior)
        rebuilt = rf.build_rf1086_retained_source_approval_manifest_v3(basis, capture)
        if (rf.serialize_rf1086_source_approval_manifest_v3(rebuilt) != retained.manifest_text
                or rebuilt.manifest_sha256 != manifest_sha256 or capture.payload_sha256 != approval.payload_hash):
            raise rf.Rf1086ProductionError('payload_changed')
        row = await (await self._connection.execute(
            'select shareholder_register_filing.claim_source_submission_v3(%s::uuid,%s,%s::uuid,%s,%s) as result',
            (approval_id.value, manifest_sha256, None if expected_head is None else expected_head.value,
             rf.serialize_rf1086_retained_annual_readiness_v2(annual, source, capture), str(self.actor_id.subject)),
        )).fetchone()
        value = row['result'] if row else None
        if type(value) is not dict or set(value) != {'claim', 'newlyClaimed'} or type(value['newlyClaimed']) is not bool:
            raise rf.Rf1086ProductionError('basis_unavailable')
        claim = _source_claim_record(value['claim'], approval_id, manifest_sha256, expected_head, self.actor_id)
        if (claim.company_id != self._query.company_id or claim.income_year != self._query.income_year
                or claim.payload_sha256 != approval.payload_hash):
            raise rf.Rf1086ProductionError('basis_unavailable')
        return rf.Rf1086SourceSubmissionClaimResult(claim, value['newlyClaimed'])

    async def _annual_proof_text(self, annual):
        self._require_active()
        if not isinstance(annual, rf.Rf1086AnnualReadinessProof):
            raise rf.Rf1086ProductionError('basis_unavailable')
        source = await self.current_source()
        preview = await self.source_preview(annual.source.evidence.preview_id)
        return rf.serialize_rf1086_annual_readiness(annual, source, preview)

    async def prepare_source_operation(self, claim, *, operation_name, body_sha256,
            idempotency_key, connection, expected_event_id=None, annual=None):
        self._require_active()
        if (not isinstance(claim, rf.Rf1086SourceSubmissionClaim)
                or claim.company_id != self._query.company_id or claim.income_year != self._query.income_year
                or claim.claimed_by != self.actor_id or not isinstance(connection, rf.Rf1086Connection)
                or connection.company_id != str(claim.company_id)
                or connection.initiating_owner_user_id != str(self.actor_id.subject)
                or connection.obligation != 'aksjonaerregisteroppgaven'
                or connection.status != 'accepted' or not connection.preflight_verified):
            raise rf.Rf1086ProductionError('basis_unavailable')
        annual_text = None if annual is None else await self._annual_proof_text(annual)
        row = await (await self._connection.execute(
            'select shareholder_register_filing.prepare_source_operation_v2(%s::uuid,%s,%s,%s,%s::uuid,%s::uuid,%s,%s::uuid,%s,%s) as result',
            (claim.submission_id.value, claim.manifest_sha256, operation_name, body_sha256,
             idempotency_key, expected_event_id, annual_text, connection.id, connection.external_ref, str(self.actor_id.subject)),
        )).fetchone()
        value = row['result'] if row else None
        if (type(value) is not dict or set(value) != {'operation', 'newlyPrepared'}
                or type(value['newlyPrepared']) is not bool):
            raise rf.Rf1086ProductionError('basis_unavailable')
        # PostgreSQL JSON trims trailing fractional zeroes; direct row reads
        # return datetime. Keep both paths identical to the retained archive.
        operation = dict(value['operation'])
        operation['created_at'] = Timestamp(datetime.fromisoformat(operation['created_at'])).value
        event = self._store._wire_record(rf.Rf1086ArchiveProductionEventRecord, operation)
        if (event.submission_id != claim.submission_id.value or event.operation_name != operation_name
                or event.company_id != str(claim.company_id) or event.income_year != int(claim.income_year)
                or event.body_hash != body_sha256 or event.idempotency_key is None
                or type(event.attempt) is not int or not 1 <= event.attempt <= 20
                or (value['newlyPrepared'] and event.operation_state != 'prepared')):
            raise rf.Rf1086ProductionError('basis_unavailable')
        return rf.Rf1086SourceOperationPreparation(event, value['newlyPrepared'])

    async def _source_approval_state_v3(self, preview_id, entitlement_id, correlation_id):
        self._require_active()
        source = await self.current_source()
        if type(source) is not rf.Rf1086YearSourceSnapshotV2:
            raise rf.Rf1086ProductionError('basis_unavailable')
        capture = await self.retained_source_preview(preview_id)
        from talli_backend.application.shareholder_register_source_admission_v2 import read_rf1086_current_annual_inputs_v2
        inputs = await read_rf1086_current_annual_inputs_v2(self, source, correlation_id)
        annual = rf.build_rf1086_retained_annual_readiness_v2(source, capture, inputs)
        annual_text = rf.serialize_rf1086_retained_annual_readiness_v2(annual, source, capture)
        await self.prepare_source_governance_proof(source)
        await self.bridge_source_preview(capture.preview)
        row = await (await self._connection.execute(
            'select shareholder_register_filing.read_source_approval_context_v3(%s::uuid,%s::uuid,%s,%s) as context',
            (preview_id.value, entitlement_id, annual_text, str(self.actor_id.subject)),
        )).fetchone()
        review = _source_approval_review(row['context'] if row else None,
            self._query, capture.preview, entitlement_id)
        if review.warning_codes != annual.required_warning_codes:
            raise rf.Rf1086ProductionError('basis_unavailable')
        return source, capture, annual, review

    async def read_source_approval_context_v3(self, preview_id, entitlement_id, correlation_id):
        _, _, annual, review = await self._source_approval_state_v3(preview_id, entitlement_id, correlation_id)
        return rf.Rf1086SourceApprovalContextV3(annual, review)

    async def append_source_approval_v3(self, preview_id, entitlement_id, manifest, expected_review_sha256, correlation_id):
        source, capture, annual, review = await self._source_approval_state_v3(preview_id, entitlement_id, correlation_id)
        if not review.can_approve:
            raise rf.Rf1086ProductionError('basis_unavailable')
        if expected_review_sha256 != review.review_sha256:
            raise rf.Rf1086ProductionError('payload_changed')
        try:
            declared = manifest.manifest.get('predecessor')
            predecessor = None
            if declared is not None:
                if (not isinstance(declared, Mapping) or set(declared) != {'submissionId','manifestSha256','reason'}):
                    raise ValueError()
                predecessor = rf.Rf1086SourceCorrectionPredecessor(rf.SubmissionId(declared['submissionId']),
                    declared['manifestSha256'], declared['reason'])
            basis = rf.Rf1086SourceApprovalManifestBasisV3(source, capture.preview, annual,
                self.actor_id, entitlement_id, review.review_sha256, review.warning_codes, predecessor)
            rf.assert_rf1086_retained_source_approval_manifest_matches_v3(manifest, basis, capture)
            manifest_text = rf.serialize_rf1086_source_approval_manifest_v3(manifest)
        except (ValueError, TypeError, AttributeError, KeyError):
            raise rf.Rf1086ProductionError('payload_changed') from None
        try:
            row = await (await self._connection.execute(
                'select * from shareholder_register_filing.append_source_approval_v3(%s::uuid,%s::uuid,%s,%s,%s,%s)',
                (preview_id.value, entitlement_id, manifest_text, manifest.manifest_sha256,
                 expected_review_sha256, str(self.actor_id.subject)),
            )).fetchone()
        except psycopg.Error as error:
            if 'rf1086_source_predecessor_mismatch' in str(error):
                raise rf.Rf1086ProductionError('payload_changed') from None
            raise
        if not row:
            raise rf.Rf1086ProductionError('basis_unavailable')
        result = self._store._recorded(row)
        if result.company_id != self._query.company_id or result.income_year != self._query.income_year:
            raise rf.Rf1086ProductionError('basis_unavailable')
        return result

    async def read_source_approval_context(self, preview_id, entitlement_id, annual):
        self._require_active()
        preview = await self.source_preview(preview_id)
        if annual.source.evidence.preview_id != preview_id:
            raise rf.Rf1086ProductionError('basis_unavailable')
        row = await (await self._connection.execute(
            'select shareholder_register_filing.read_source_approval_context_v2(%s::uuid,%s::uuid,%s,%s) as context',
            (preview_id.value, entitlement_id, await self._annual_proof_text(annual), str(self.actor_id.subject)),
        )).fetchone()
        return _source_approval_review(row['context'] if row else None, self._query, preview, entitlement_id)

    async def append_source_approval(self, preview, entitlement_id, manifest, review_sha256):
        self._require_active()
        if (await self.source_preview(preview.preview_id) != preview
                or manifest.manifest.get('entitlementId') != entitlement_id
                or manifest.manifest.get('userId') != str(self.actor_id.subject)
                or manifest.manifest.get('preview', {}).get('id') != preview.preview_id.value
                or manifest.manifest.get('review', {}).get('sha256') != review_sha256):
            raise rf.Rf1086ProductionError('basis_unavailable')
        manifest_text = rf.serialize_rf1086_source_approval_manifest(manifest)
        try:
            row = await (await self._connection.execute(
                'select * from shareholder_register_filing.append_source_approval_v2(%s::uuid,%s::uuid,%s,%s,%s,%s)',
                (preview.preview_id.value, entitlement_id, manifest_text, manifest.manifest_sha256,
                 review_sha256, str(self.actor_id.subject)),
            )).fetchone()
        except psycopg.Error as error:
            # Capture correction and production correction share an SQL error
            # name. Translate only this approval operation, preserving capture.
            if 'rf1086_source_predecessor_mismatch' in str(error):
                raise rf.Rf1086ProductionError('payload_changed') from None
            raise
        if not row:
            raise rf.Rf1086ProductionError('basis_unavailable')
        result = self._store._recorded(row)
        if result.company_id != self._query.company_id or result.income_year != self._query.income_year:
            raise rf.Rf1086ProductionError('basis_unavailable')
        return result

    async def read_current_register_observation(self, query, observation_id):
        self._require_active()
        if query != self._query:
            raise rf.ShareholderRegisterFilingError.forbidden()
        return await self._store._read_register_observation(self._connection, query, observation_id, current=True)


_SOURCE_CLAIM_FIELDS = {'submission_id','approval_id','company_id','income_year','manifest_sha256',
                        'payload_sha256','predecessor_submission_id','claimed_by','claimed_at'}


def _source_claim_record(row,approval_id,manifest_sha256,expected_head,actor_id):
    try:
        if (not isinstance(row,dict) or set(row)!=_SOURCE_CLAIM_FIELDS
                or type(row['income_year']) is not int or str(row['claimed_by'])!=str(actor_id.subject)):
            raise ValueError()
        claimed_at = row['claimed_at']
        if isinstance(claimed_at,str):
            # PostgreSQL JSON trims trailing fractional zeros; native row reads
            # preserve six digits. Normalize only this typed timestamp, keeping
            # every microsecond and refusing precision we cannot represent.
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})',claimed_at) is None:
                raise ValueError()
            claimed_at = datetime.fromisoformat(claimed_at)
        if not isinstance(claimed_at,datetime):
            raise ValueError()
        claimed_at = Timestamp(claimed_at).value.isoformat()
        value = rf.Rf1086SourceSubmissionClaim(rf.SubmissionId(str(row['submission_id'])),
            rf.ApprovalId(str(row['approval_id'])),CompanyId(str(row['company_id'])),IncomeYear(row['income_year']),
            row['manifest_sha256'],row['payload_sha256'],
            None if row['predecessor_submission_id'] is None else rf.SubmissionId(str(row['predecessor_submission_id'])),
            actor_id,claimed_at)
        rf.assert_rf1086_source_submission_claim(value,approval_id=approval_id,manifest_sha256=manifest_sha256,
            expected_head=expected_head,actor_id=actor_id)
        return value
    except (ValueError,TypeError,KeyError,AttributeError,rf.ShareholderRegisterFilingError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None


def _source_approval_review(value, query, preview, entitlement_id):
    """Reject malformed owner projections before treating their digest as review."""
    try:
        from uuid import UUID
        keys = {'companyId', 'incomeYear', 'previewId', 'sourceId', 'sourceSha256',
                'entitlementId', 'reviewSha256', 'warningCodes', 'blockers'}
        if (not isinstance(value, dict) or set(value) != keys
                or value['companyId'] != str(query.company_id)
                or type(value['incomeYear']) is not int or value['incomeYear'] != int(query.income_year)
                or value['previewId'] != preview.preview_id.value
                or value['sourceId'] != preview.source_id.value
                or value['sourceSha256'] != preview.source_sha256
                or value['entitlementId'] != entitlement_id
                or str(UUID(entitlement_id)) != entitlement_id
                or type(value['reviewSha256']) is not str
                or re.fullmatch('[a-f0-9]{64}', value['reviewSha256']) is None):
            raise ValueError()
        for name in ('warningCodes', 'blockers'):
            codes = value[name]
            if (type(codes) is not list or any(type(code) is not str or not code.strip() for code in codes)
                    or codes != sorted(set(codes))):
                raise ValueError()
        return rf.Rf1086SourceApprovalReview(query.company_id, query.income_year, preview.preview_id,
            preview.source_id, preview.source_sha256, entitlement_id, value['reviewSha256'],
            tuple(value['warningCodes']), tuple(value['blockers']), not value['blockers'])
    except (ValueError, TypeError, KeyError, AttributeError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None


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
        # Preserve the exact verified original before RF acknowledges its new
        # metadata row. A successful upload alone is not retained byte evidence.
        documents = await self._document_session(
            _DocumentOperation(document_id, 'rf1086-feedback-retain:' + document_id), 'retain')
        try:
            evidence = await documents.verify_document_evidence(DocumentId(document_id))
        except DocumentsError as error:
            # Retention may have committed before a read/transport failure. Keep
            # the uploaded record; do not turn ambiguity into destructive cleanup.
            raise create_rf1086_feedback_artifact_persistence_error(error) from None
        receipt = evidence.retained_original if isinstance(evidence, VerifiedDocumentEvidence) else None
        if (not isinstance(receipt, RetainedDocumentOriginalReceipt) or evidence.document != stored
                or evidence.content_sha256 != artifact.sha256 or evidence.byte_length != artifact.byte_length
                or evidence.integrity_status != DocumentStatus.STORED
                or receipt.document_id != stored.document_id or receipt.company_id != stored.company_id
                or receipt.source_income_year != stored.income_year
                or receipt.metadata_sha256 != document_metadata_sha256(stored)
                or receipt.content_sha256 != artifact.sha256 or receipt.byte_length != artifact.byte_length):
            raise create_rf1086_feedback_artifact_persistence_error(None, integrity_failure=True)
        try:
            rows = await self._session._rows("select id from shareholder_register_filing.record_retained_feedback_artifact_v1("
                "%s::uuid,%s::uuid,%s::uuid,%s::text,%s::text,%s::bigint,%s::text,%s::text,%s::uuid,%s::text,%s::timestamptz)",
                (self._company_id, self._submission_id, document_id, artifact.authority_reference,
                 artifact.content_type, artifact.byte_length, artifact.sha256, artifact.classification,
                 receipt.original_id, receipt.metadata_sha256, receipt.retained_at))
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


def _company_test_retention_read_sql(bounds):
    """Fixed inventory; CASE prevents oversized historical TEXT transfer."""
    columns = ('id', 'company_id', 'obligation', 'environment', 'status',
        'test_reference', 'feedback_summary', 'receipt_reference', 'archive_reference',
        'evidence_url', 'payload_hash', 'recorded_by', 'recorded_at')
    text_columns = ('obligation', 'environment', 'status', 'test_reference', 'feedback_summary',
        'receipt_reference', 'archive_reference', 'evidence_url', 'payload_hash')
    lengths = [f"octet_length(coalesce(t.{name},''))" for name in text_columns]
    allowed = ' and '.join(f'{length}<={bounds.max_text_bytes}' for length in lengths)
    allowed += ' and (' + '+'.join(lengths) + f'+256)<={bounds.max_raw_transfer_bytes}'
    projection = ','.join(f'case when g.allowed then t.{name} else null end as {name}' for name in columns)
    return (f'select not g.allowed as _retention_oversize,{projection} '
        'from shareholder_register_filing.authority_test_runs t '
        f'cross join lateral (select ({allowed}) as allowed) g '
        "where t.company_id=%s::uuid and t.obligation='aksjonaerregisteroppgaven' order by t.id asc")
