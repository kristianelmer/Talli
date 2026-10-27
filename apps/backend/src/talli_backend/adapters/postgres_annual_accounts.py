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
    LedgerSupabaseConfiguration, SupabaseLedgerAdapter, _VerifiedActor, SupabaseLedgerSnapshotQueries, _verified_snapshot_rows,
)
from talli_backend.adapters.supabase_corporate_governance import SupabaseCorporateGovernanceSnapshotQueries
from talli_backend.application.annual_accounts_session import AnnualAccountsSessionFactory
from talli_backend.application.annual_accounts_workflow import AnnualAccountsApplication
from talli_backend.application.annual_accounts_delivery_rehearsal import loopback_accounts_database_scope
from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsSourceQuery, AnnualAccountsSourceSnapshot, AnnualAccountsSourcePersistence,
    AnnualAccountsCompanyIdentity, AnnualAccountsEvidencePersistence, AnnualAccountsEvidenceProjection,
    AnnualAccountsRecordId, AnnualAccountsRecordQuery, RecordAnnualAccountsOverride, AddAnnualAccountsReviewComment,
    ConfirmAnnualAccountsPermission, RecordAnnualAccountsTestEvidence, AnnualAccountsRecordedResult,
    AnnualAccountsPreparationPersistence,
    AnnualAccountsError, AnnualAccountsWorkspacePersistence, AnnualAccountsWorkspaceQuery,
    AnnualAccountsFilingRows, annual_accounts_persistence_adapter,
    AnnualAccountsDeliveryDraftPersistence, StoredAnnualAccountsDeliveryDraft, decode_annual_accounts_delivery_draft,
    AnnualAccountsDeliveryJournalPersistence, StoredAnnualAccountsDeliveryEvent, decode_annual_accounts_delivery_record_v2,
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
        'annual_accounts_delivery_draft_conflict': AnnualAccountsError.draft_conflict,
        'annual_accounts_delivery_record_conflict': AnnualAccountsError.draft_conflict,
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

    @property
    def delivery_rehearsal_target(self):
        try:
            from psycopg.conninfo import conninfo_to_dict
            value=conninfo_to_dict(self._database_url)
            # libpq's hostaddr/service/options can override or augment a
            # nominal loopback host. A rehearsal target admits only explicit,
            # single-host connection fields and no ambient routing service.
            if (set(value)-{'host','port','dbname','user','password','sslmode','connect_timeout','application_name'}
                    or any(os.environ.get(key) for key in ('PGHOSTADDR','PGSERVICE','PGSERVICEFILE','PGOPTIONS',
                        'PGLOADBALANCEHOSTS','PGTARGETSESSIONATTRS'))):return None
            return loopback_accounts_database_scope(value.get('host'),int(value.get('port','0')),
                value.get('dbname'),value.get('user'))
        except (ValueError,TypeError,psycopg.Error):return None

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
@annual_accounts_persistence_adapter(AnnualAccountsDeliveryDraftPersistence)
@annual_accounts_persistence_adapter(AnnualAccountsDeliveryJournalPersistence)
class PostgresAnnualAccountsTransaction:
    def __init__(self, verified: _VerifiedActor, connection: psycopg.AsyncConnection):
        self._verified, self._connection = verified, connection

    @property
    def actor_id(self):
        return self._verified.actor_id

    @property
    def delivery_ledger_queries(self):
        return SupabaseLedgerSnapshotQueries('', self._verified, self._connection)

    @property
    def delivery_corporate_queries(self):
        return SupabaseCorporateGovernanceSnapshotQueries('', self._verified, self._connection)

    async def delivery_annual_interview_history(self, query):
        if query.actor_id != self.actor_id:
            raise AnnualAccountsError.forbidden()
        try:
            rows = await _verified_snapshot_rows(self._verified, self._connection,
                'corporate_governance_workflow_executor',
                'select backend_system.list_annual_data_legacy_v1(%s::uuid,%s::integer,%s::text) as items',
                (str(query.company_id), int(query.income_year), str(self.actor_id.subject)))
            if len(rows) != 1 or type(rows[0]['items']) is not list:
                raise ValueError()
            return rows[0]['items']
        except (ValueError, KeyError, TypeError, psycopg.DatabaseError):
            raise AnnualAccountsError.unavailable() from None

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
        installed=await self._one_row("select case when pg_catalog.to_regprocedure('annual_accounts_filing.read_source_snapshot_v4(uuid,integer,text)') is not null then 4 when pg_catalog.to_regprocedure('annual_accounts_filing.read_source_snapshot_v3(uuid,integer,text)') is not null then 3 when pg_catalog.to_regprocedure('annual_accounts_filing.read_source_snapshot_v2(uuid,integer,text)') is not null then 2 else 1 end as version",())
        version=installed.get('version')
        if type(version) is not int or version not in (1,2,3,4):raise AnnualAccountsError.unavailable()
        successor=version>=2
        row = await self._one_row(
            f'select annual_accounts_filing.read_source_snapshot_v{version}(%s::uuid,%s::integer,%s::text) as result',
            (str(query.company_id), int(query.income_year), str(self.actor_id.subject)),
        )
        value = row.get('result')
        try:
            if (not isinstance(value, Mapping) or value['companyId'] != str(query.company_id)
                    or type(value['incomeYear']) is not int or value['incomeYear'] != int(query.income_year)
                    or type(value['completeEnumeration']) is not bool):
                raise ValueError()
            if successor and (value.get('contractVersion')!=f'annual-accounts-source-v{version}'
                    or type(value.get('deliveryDrafts')) is not list):raise ValueError()
            if version>=3 and type(value.get('deliveryEvents')) is not list:raise ValueError()
            rows = AnnualAccountsFilingRows(query.company_id, query.income_year,
                **{name: value['workspace'][name] for name in ('previews', 'submissions', 'overrides',
                    'review_comments', 'permissions', 'test_evidence')})
            return AnnualAccountsSourceSnapshot(rows, value['coverage'],
                Timestamp(datetime.fromisoformat(value['asOf'].replace('Z', '+00:00'))), value['completeEnumeration'],
                value['contractVersion'] if successor else 'annual-accounts-source-v1',
                tuple(self._stored_delivery_draft(row) for row in value['deliveryDrafts']) if successor else (),
                tuple(self._stored_delivery_event(row) for row in value['deliveryEvents']) if version>=3 else ())
        except (KeyError, TypeError, ValueError, AttributeError):
            raise AnnualAccountsError.unavailable() from None

    @staticmethod
    def _stored_delivery_draft(row):
        try:
            if (not isinstance(row,Mapping) or set(row)!={'id','company_id','income_year','prepared_by',
                    'command_key','canonical_json','draft_sha256','recorded_at'} or type(row['income_year']) is not int):raise ValueError()
            draft=decode_annual_accounts_delivery_draft(row['canonical_json'],row['draft_sha256'])
            if (row['id']!=draft.filing_id or row['company_id']!=str(draft.source.company_id)
                    or row['income_year']!=int(draft.source.income_year) or row['prepared_by']!=str(draft.prepared_by.subject)
                    or row['command_key']!=str(draft.command_key)):raise ValueError()
            return StoredAnnualAccountsDeliveryDraft(draft,Timestamp(datetime.fromisoformat(row['recorded_at'].replace('Z','+00:00'))))
        except (ValueError,TypeError,KeyError,AttributeError):raise AnnualAccountsError.unavailable() from None

    async def lock_delivery_archive(self,query):
        if query.actor_id!=self.actor_id:raise AnnualAccountsError.forbidden()
        await self._one_row('select annual_accounts_filing.lock_delivery_archive_v1(%s::uuid,%s::integer,%s::text) as result',
            (str(query.company_id),int(query.income_year),str(query.actor_id.subject)))

    async def lock_company_year_archive(self, query):
        if query.actor_id != self.actor_id:
            raise AnnualAccountsError.forbidden()
        await self._one_row('select annual_accounts_filing.lock_company_year_archive_v1(%s::uuid,%s::integer,%s::text) as result',
            (str(query.company_id), int(query.income_year), str(query.actor_id.subject)))

    async def delivery_draft_by_key(self,query,key):
        if query.actor_id!=self.actor_id:raise AnnualAccountsError.forbidden()
        row=await self._one_row('select annual_accounts_filing.read_delivery_draft_v1(%s::uuid,%s::integer,%s::text,%s::text) as result',
            (str(query.company_id),int(query.income_year),str(key),str(query.actor_id.subject)))
        if row['result'] is None:return None
        stored=self._stored_delivery_draft(row['result']);draft=stored.draft
        if (draft.source.company_id!=query.company_id or draft.source.income_year!=query.income_year
                or draft.prepared_by!=query.actor_id or draft.command_key!=key):raise AnnualAccountsError.unavailable()
        return stored

    async def store_delivery_draft(self,draft):
        if draft.prepared_by!=self.actor_id:raise AnnualAccountsError.forbidden()
        row=await self._one_row('select annual_accounts_filing.store_delivery_draft_v1(%s::text,%s::text,%s::text) as result',
            (draft.canonical_json,draft.sha256,str(self.actor_id.subject)))
        stored=self._stored_delivery_draft(row['result'])
        if stored.draft!=draft:raise AnnualAccountsError.unavailable()
        return stored

    @staticmethod
    def _stored_delivery_event(row):
        try:
            if (not isinstance(row,Mapping) or set(row)!={'sequence','filing_id','company_id','income_year',
                    'recorded_by','slot','canonical_json','event_sha256','recorded_at'}
                    or type(row['sequence']) is not int or type(row['income_year']) is not int):raise ValueError()
            record=decode_annual_accounts_delivery_record_v2(row['canonical_json'],row['event_sha256'])
            binding=record.binding
            if (row['filing_id']!=binding.filing_id or row['company_id']!=str(binding.company_id)
                    or row['income_year']!=int(binding.income_year) or row['recorded_by']!=str(binding.actor_id.subject)
                    or row['slot']!=record.slot):raise ValueError()
            return StoredAnnualAccountsDeliveryEvent(row['sequence'],record,
                Timestamp(datetime.fromisoformat(row['recorded_at'].replace('Z','+00:00'))))
        except (ValueError,TypeError,KeyError,AttributeError):raise AnnualAccountsError.unavailable() from None

    async def append_delivery_event(self,record):
        if record.binding.actor_id!=self.actor_id:raise AnnualAccountsError.forbidden()
        installed=await self._one_row("select pg_catalog.to_regprocedure('annual_accounts_filing.append_delivery_event_v2(text,text,text)') is not null as successor",())
        version=2 if installed.get('successor') is True else 1
        row=await self._one_row(f'select annual_accounts_filing.append_delivery_event_v{version}(%s::text,%s::text,%s::text) as result',
            (record.canonical_json,record.sha256,str(self.actor_id.subject)))
        result=row.get('result')
        if not isinstance(result,Mapping) or set(result)!={'event','inserted'} or type(result['inserted']) is not bool:
            raise AnnualAccountsError.unavailable()
        stored=self._stored_delivery_event(result['event'])
        if stored.record!=record:raise AnnualAccountsError.unavailable()
        return stored,result['inserted']

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
    *, preparation=None,delivery=None,
) -> AnnualAccountsApplication:
    return AnnualAccountsApplication(sessions if sessions is not None else PostgresAnnualAccountsAdapter.from_environment(),preparation=preparation,delivery=delivery)
