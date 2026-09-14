"""Verified-session PostgreSQL adapter for Accounts-owned filing projections."""
from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
import os
import json
from dataclasses import asdict
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

from talli_backend.adapters.supabase_ledger import (
    LedgerSupabaseConfiguration, SupabaseLedgerAdapter, _VerifiedActor,
)
from talli_backend.application.annual_accounts_session import AnnualAccountsSessionFactory
from talli_backend.application.annual_accounts_workflow import AnnualAccountsApplication
from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsSourceQuery, AnnualAccountsSourceSnapshot, AnnualAccountsSourcePersistence,
    AnnualAccountsCompanyIdentity, AnnualAccountsEvidencePersistence, AnnualAccountsEvidenceProjection,
    AnnualAccountsRecordId, AnnualAccountsRecordQuery, RecordAnnualAccountsOverride, AddAnnualAccountsReviewComment,
    ConfirmAnnualAccountsPermission, RecordAnnualAccountsTestEvidence, AnnualAccountsRecordedResult,
    AnnualAccountsPreparationPersistence,
    AnnualAccountsError, AnnualAccountsWorkspacePersistence, AnnualAccountsWorkspaceQuery,
    AnnualAccountsFilingRows, annual_accounts_persistence_adapter,
)
from talli_backend.modules.ledger.public import LedgerError
from talli_backend.shared.kernel import ActorId, CompanyId, IncomeYear, Timestamp


def _accounts_database_error(error: psycopg.DatabaseError):
    factory = {
        'company_access_forbidden': AnnualAccountsError.forbidden,
        'company_access_not_found': AnnualAccountsError.not_found,
        'annual_accounts_hard_review_block': AnnualAccountsError.hard_review_block,
        'annual_accounts_mfa_required': AnnualAccountsError.mfa_required,
        'annual_accounts_forbidden': AnnualAccountsError.forbidden,
        'annual_accounts_not_found': AnnualAccountsError.not_found,
        'annual_accounts_invalid_input': AnnualAccountsError.invalid_input,
        'annual_accounts_unavailable': AnnualAccountsError.unavailable,
    }.get(error.diag.message_primary or '', AnnualAccountsError.unavailable)
    return factory()


class PostgresAnnualAccountsAdapter:
    def __init__(self, configuration: LedgerSupabaseConfiguration):
        self._configuration = configuration
        self._authentication = SupabaseLedgerAdapter(configuration)

    @classmethod
    def from_environment(cls):
        return cls(LedgerSupabaseConfiguration(
            url=os.environ.get('SUPABASE_URL', ''), anon_key=os.environ.get('SUPABASE_ANON_KEY', ''),
            database_url=os.environ.get('TALLI_LEDGER_DATABASE_URL', ''),
        ))

    async def session(self, access_token: str) -> PostgresAnnualAccountsSession:
        authenticated = await self._authentication.session(access_token)
        return PostgresAnnualAccountsSession(self._configuration.database_url, authenticated._verified)


class PostgresAnnualAccountsSession:
    def __init__(self, database_url: str, verified: _VerifiedActor):
        self._database_url, self._verified = database_url, verified

    @property
    def actor_id(self):
        return self._verified.actor_id

    @asynccontextmanager
    async def transaction(self, *, snapshot: bool = False) -> AsyncIterator[PostgresAnnualAccountsTransaction]:
        if not self._database_url:
            raise AnnualAccountsError.unavailable()
        try:
            async with await psycopg.AsyncConnection.connect(
                self._database_url, connect_timeout=5, row_factory=dict_row,
            ) as connection, connection.transaction():
                if snapshot:
                    await connection.execute('set transaction isolation level repeatable read')
                await connection.execute('set local role annual_accounts_filing_workflow_executor')
                await connection.execute("select set_config('talli.verified_actor_id', %s, true)", (str(self.actor_id.subject),))
                await connection.execute("select set_config('talli.verified_actor_claims', %s, true)", (self._verified.claims_json,))
                yield PostgresAnnualAccountsTransaction(self._verified, connection)
        except (AnnualAccountsError, LedgerError):
            raise
        except psycopg.OperationalError:
            raise AnnualAccountsError.unavailable() from None
        except psycopg.DatabaseError as error:
            raise _accounts_database_error(error) from None


@annual_accounts_persistence_adapter(AnnualAccountsSourcePersistence)
@annual_accounts_persistence_adapter(AnnualAccountsEvidencePersistence)
@annual_accounts_persistence_adapter(AnnualAccountsWorkspacePersistence)
@annual_accounts_persistence_adapter(AnnualAccountsPreparationPersistence)
class PostgresAnnualAccountsTransaction:
    def __init__(self, verified: _VerifiedActor, connection: psycopg.AsyncConnection):
        self._verified, self._connection = verified, connection

    @property
    def actor_id(self):
        return self._verified.actor_id

    async def _database_rows(self, query: str, parameters: tuple[object, ...] = ()):
        try:
            cursor = await self._connection.execute(query, parameters)
            return list(await cursor.fetchall())
        except psycopg.OperationalError:
            raise AnnualAccountsError.unavailable() from None
        except psycopg.DatabaseError as error:
            raise _accounts_database_error(error) from None

    async def _one_row(self, query: str, parameters: tuple[object, ...]):
        rows = await self._database_rows(query, parameters)
        if len(rows) != 1:
            raise AnnualAccountsError.unavailable()
        return rows[0]
    async def filing_workspace(self, query: AnnualAccountsWorkspaceQuery) -> AnnualAccountsFilingRows:
        if query.actor_id != self.actor_id:
            raise AnnualAccountsError.forbidden()
        row = await self._one_row(
            'select annual_accounts_filing.read_workspace_v1(%s::uuid,%s::integer,%s::text) as result',
            (str(query.company_id), int(query.income_year) if query.income_year is not None else None,
             str(self.actor_id.subject)),
        )
        result = row.get('result')
        try:
            if not isinstance(result, Mapping):
                raise ValueError()
            return AnnualAccountsFilingRows(query.company_id, query.income_year,
                **{name: result[name] for name in ('previews', 'submissions', 'overrides',
                                                  'review_comments', 'permissions', 'test_evidence')})
        except (KeyError, TypeError, ValueError):
            raise AnnualAccountsError.unavailable() from None

    async def filing_source_snapshot(self, query: AnnualAccountsSourceQuery) -> AnnualAccountsSourceSnapshot:
        if query.actor_id != self.actor_id:
            raise AnnualAccountsError.forbidden()
        row = await self._one_row(
            'select annual_accounts_filing.read_source_snapshot_v1(%s::uuid,%s::integer,%s::text) as result',
            (str(query.company_id), int(query.income_year), str(self.actor_id.subject)),
        )
        value = row.get('result')
        try:
            if (not isinstance(value, Mapping) or value['companyId'] != str(query.company_id)
                    or type(value['incomeYear']) is not int or value['incomeYear'] != int(query.income_year)
                    or type(value['completeEnumeration']) is not bool):
                raise ValueError()
            rows = AnnualAccountsFilingRows(query.company_id, query.income_year,
                **{name: value['workspace'][name] for name in ('previews', 'submissions', 'overrides',
                    'review_comments', 'permissions', 'test_evidence')})
            return AnnualAccountsSourceSnapshot(rows, value['coverage'],
                Timestamp(datetime.fromisoformat(value['asOf'].replace('Z', '+00:00'))), value['completeEnumeration'])
        except (KeyError, TypeError, ValueError, AttributeError):
            raise AnnualAccountsError.unavailable() from None

    async def filing_preview(self, query: AnnualAccountsRecordQuery) -> Mapping[str, object] | None:
        if query.actor_id != self.actor_id:
            raise AnnualAccountsError.forbidden()
        row = await self._one_row(
            'select annual_accounts_filing.read_preview_v1(%s::uuid,%s::text) as result',
            (str(query.record_id), str(query.actor_id.subject)),
        )
        result = row.get('result')
        if result is None:
            return None
        try:
            if (not isinstance(result, Mapping) or result.get('id') != str(query.record_id)
                    or not isinstance(result.get('company_id'), str) or type(result.get('income_year')) is not int):
                raise ValueError()
            snapshot = AnnualAccountsFilingRows(CompanyId(result['company_id']), IncomeYear(result['income_year']),
                previews=[result], submissions=[], overrides=[], review_comments=[], permissions=[], test_evidence=[])
            return snapshot.previews[0]
        except (KeyError, TypeError, ValueError):
            raise AnnualAccountsError.unavailable() from None

    async def _preparation_result(self, query: str, parameters: tuple[object, ...], actor_id: ActorId) -> AnnualAccountsRecordedResult:
        if actor_id != self.actor_id:
            raise AnnualAccountsError.forbidden()
        row = await self._one_row(query, (*parameters, str(actor_id.subject)))
        result = row.get('result')
        try:
            if (not isinstance(result, Mapping) or not isinstance(result.get('id'), str)
                    or not isinstance(result.get('company_id'), str)
                    or result.get('income_year') is not None and type(result.get('income_year')) is not int):
                raise ValueError()
            return AnnualAccountsRecordedResult(AnnualAccountsRecordId(result['id']), CompanyId(result['company_id']),
                IncomeYear(result['income_year']) if result.get('income_year') is not None else None)
        except (KeyError, TypeError, ValueError):
            raise AnnualAccountsError.unavailable() from None

    async def record_override(self, command: RecordAnnualAccountsOverride) -> AnnualAccountsRecordedResult:
        return await self._preparation_result(
            'select annual_accounts_filing.record_override_v1(%s::uuid,%s::text,%s::text,%s::text,%s::text,%s::text,%s::boolean,%s::text) as result',
            (str(command.preview_id), command.field_target, command.old_value, command.new_value,
             command.reason, command.risk_level, command.owner_confirmed), command.actor_id,
        )

    async def add_review_comment(self, command: AddAnnualAccountsReviewComment) -> AnnualAccountsRecordedResult:
        return await self._preparation_result(
            'select annual_accounts_filing.add_review_comment_v1(%s::uuid,%s::text,%s::text,%s::text) as result',
            (str(command.preview_id), command.severity, command.body), command.actor_id,
        )

    async def acknowledge_review_comment(self, query: AnnualAccountsRecordQuery) -> AnnualAccountsRecordedResult:
        return await self._preparation_result(
            'select annual_accounts_filing.acknowledge_review_comment_v1(%s::uuid,%s::text) as result',
            (str(query.record_id),), query.actor_id,
        )

    async def confirm_filing_permission(self, command: ConfirmAnnualAccountsPermission) -> AnnualAccountsRecordedResult:
        return await self._preparation_result(
            'select annual_accounts_filing.confirm_filing_permission_v1(%s::uuid,%s::boolean,%s::text) as result',
            (str(command.company_id), command.production_enabled), command.actor_id,
        )

    async def record_test_evidence(self, command: RecordAnnualAccountsTestEvidence) -> AnnualAccountsRecordedResult:
        return await self._preparation_result(
            'select annual_accounts_filing.record_test_evidence_v1(%s::uuid,%s::jsonb,%s::text) as result',
            (str(command.company_id), json.dumps({key: getattr(command, key) for key in (
                'environment', 'status', 'test_reference', 'feedback_summary', 'receipt_reference',
                'archive_reference', 'evidence_url', 'payload_hash')}, ensure_ascii=True)), command.actor_id,
        )


    async def filing_company_identity(self, company_id: CompanyId, actor_id: ActorId) -> AnnualAccountsCompanyIdentity:
        if actor_id != self.actor_id:
            raise AnnualAccountsError.forbidden()
        row = await self._one_row(
            'select public.company_access_read_rf_company_identity_v1(%s::uuid,%s::text) as result',
            (str(company_id), str(actor_id.subject)),
        )
        result = row.get('result')
        if (not isinstance(result, Mapping) or result.get('id') != str(company_id)
                or not isinstance(result.get('org_number'), str)):
            raise AnnualAccountsError.unavailable()
        return AnnualAccountsCompanyIdentity(company_id, result['org_number'])

    async def import_tt02_evidence(self, projection: AnnualAccountsEvidenceProjection, actor_id: ActorId) -> AnnualAccountsRecordId:
        if actor_id != self.actor_id or projection.recorded_by != str(actor_id.subject):
            raise AnnualAccountsError.forbidden()
        row = await self._one_row(
            'select annual_accounts_filing.import_tt02_evidence_v1(%s::jsonb,%s::text) as result',
            (json.dumps(asdict(projection), ensure_ascii=True, allow_nan=False), str(actor_id.subject)),
        )
        try:
            result = row.get('result')
            if not isinstance(result, Mapping) or result.get('company_id') != projection.company_id:
                raise ValueError()
            return AnnualAccountsRecordId(result['id'])
        except (KeyError, TypeError, ValueError):
            raise AnnualAccountsError.unavailable() from None



def compose_annual_accounts_application(
    sessions: AnnualAccountsSessionFactory | None = None,
) -> AnnualAccountsApplication:
    return AnnualAccountsApplication(sessions if sessions is not None else PostgresAnnualAccountsAdapter.from_environment())
