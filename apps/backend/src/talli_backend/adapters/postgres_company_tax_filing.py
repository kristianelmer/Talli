"""Request-scoped PostgreSQL composition for Company Tax settlement capture."""
from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
import json
import os

import psycopg
from psycopg.rows import dict_row

from talli_backend.adapters.supabase_ledger import (
    LedgerSupabaseConfiguration, SupabaseLedgerAdapter,
    _VerifiedActor, _line_payload, _map_database_error, _posted_entry,
)
from talli_backend.application.company_tax_filing_session import CompanyTaxSessionFactory
from talli_backend.application.company_tax_filing_workflow import CompanyTaxApplication
from talli_backend.modules.audit.public import AuditEventDraft, AuditInclusion, audit_inclusion_adapter
from talli_backend.shared.kernel import ActorId, CompanyId
from talli_backend.modules.banking.public import (
    TaxSettlementBankCommand, TaxSettlementBankingPersistence,
    bank_transaction_claim_persistence_adapter,
)
from talli_backend.modules.company_tax_filing.public import (
    AccountingEntryReference, CompanyTaxError, RecordTaxSettlementCommand,
    CompanyTaxCompanyIdentity, CompanyTaxReturnPersistence, CompanyTaxEvidenceProjection,
    ImportedCompanyTaxEvidence, TaxAuthorityEvidenceId, TaxFilingSubmissionId,
    CompanyTaxWorkspaceQuery, CompanyTaxFilingRows, CompanyTaxWorkspacePersistence,
    TaxSettlementPersistence, TaxSettlementArchivePersistence, TaxSettlementArchiveQuery, tax_settlement_persistence_adapter,
)
from talli_backend.modules.documents.public import (
    DocumentBindingPersistence, DocumentBindingQuery, document_binding_persistence_adapter,
)
from talli_backend.modules.ledger.public import (
    LedgerEntryKind, LedgerError, LedgerPersistence, LedgerSourceCapability,
    PostTaxSettlementCommand, ledger_persistence_adapter,
)
from talli_backend.modules.ledger.service import LedgerService


def _company_tax_database_error(error: psycopg.DatabaseError):
    known = {
        'company_tax_return_forbidden': CompanyTaxError.forbidden,
        'company_tax_return_not_found': CompanyTaxError.not_found,
        'company_tax_return_invalid_input': CompanyTaxError.invalid_input,
        'company_tax_return_unavailable': CompanyTaxError.unavailable,
    }
    message = error.diag.message_primary or ''
    if message == 'company_tax_evidence_mfa_required':
        return CompanyTaxError.mfa_required()
    if message in ('company_tax_evidence_authentication_required', 'company_tax_evidence_owner_required', 'company_access_forbidden'):
        return CompanyTaxError.forbidden()
    if message == 'company_access_not_found':
        return CompanyTaxError.not_found()
    if message in ('company_tax_evidence_invalid_payload', 'company_tax_evidence_forbidden_content', 'company_tax_evidence_conflict'):
        return CompanyTaxError.invalid_input()
    factory = known.get(message)
    return factory() if factory else _map_database_error(str(error))


def _json_value(value):
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _request(command: RecordTaxSettlementCommand) -> dict[str, object]:
    # These original names, decimal representation and correlation identity are
    # the immutable PostgreSQL JSONB receipt fingerprint across deployment phases.
    return {
        'companyId': str(command.company_id), 'incomeYear': int(command.income_year),
        'idempotencyKey': str(command.idempotency_key), 'correlationId': str(command.correlation_id),
        'actionId': str(command.action_id), 'settlementDate': command.settlement_date.value.isoformat(),
        'amount': format(command.amount.amount, 'f'), 'settlementKind': command.settlement_kind.value,
        'documentStatus': command.document_status.value,
        'bankTransactionId': str(command.bank_transaction_id) if command.bank_transaction_id else None,
        'documentId': str(command.document_id) if command.document_id else None,
    }


def _bank_request(command: TaxSettlementBankCommand) -> dict[str, object]:
    return {
        'companyId': str(command.company_id), 'incomeYear': int(command.income_year),
        'transactionId': str(command.transaction_id),
        'signedAmount': format(command.expected_signed_amount.amount, 'f'),
        'actionReference': str(command.action_reference),
    }


class PostgresCompanyTaxAdapter:
    def __init__(self, configuration: LedgerSupabaseConfiguration):
        self._configuration = configuration
        self._authentication = SupabaseLedgerAdapter(configuration)

    @classmethod
    def from_environment(cls):
        return cls(LedgerSupabaseConfiguration(
            url=os.environ.get('SUPABASE_URL', ''), anon_key=os.environ.get('SUPABASE_ANON_KEY', ''),
            database_url=os.environ.get('TALLI_LEDGER_DATABASE_URL', ''),
        ))

    async def session(self, access_token: str) -> PostgresCompanyTaxSession:
        authenticated = await self._authentication.session(access_token)
        return PostgresCompanyTaxSession(self._configuration.database_url, authenticated._verified)


class PostgresCompanyTaxSession:
    def __init__(self, database_url: str, verified: _VerifiedActor):
        self._database_url, self._verified = database_url, verified

    @property
    def actor_id(self):
        return self._verified.actor_id

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[PostgresCompanyTaxTransaction]:
        if not self._database_url:
            raise CompanyTaxError.unavailable()
        try:
            async with await psycopg.AsyncConnection.connect(
                self._database_url, connect_timeout=5, row_factory=dict_row,
            ) as connection, connection.transaction():
                await connection.execute('set local role company_tax_filing_workflow_executor')
                await connection.execute("select set_config('talli.verified_actor_id', %s, true)", (str(self.actor_id.subject),))
                await connection.execute("select set_config('talli.verified_actor_claims', %s, true)", (self._verified.claims_json,))
                yield PostgresCompanyTaxTransaction(self._verified, connection)
        except (CompanyTaxError, LedgerError):
            raise
        except psycopg.OperationalError:
            raise CompanyTaxError.unavailable() from None
        except psycopg.DatabaseError as error:
            # Existing receipt, Ledger and input codes remain part of released v1.
            raise _company_tax_database_error(error) from None


@audit_inclusion_adapter(AuditInclusion)
@tax_settlement_persistence_adapter(CompanyTaxReturnPersistence)
@tax_settlement_persistence_adapter(CompanyTaxWorkspacePersistence)
@tax_settlement_persistence_adapter(TaxSettlementArchivePersistence)
@tax_settlement_persistence_adapter(TaxSettlementPersistence)
@ledger_persistence_adapter(LedgerPersistence)
@bank_transaction_claim_persistence_adapter(TaxSettlementBankingPersistence)
@document_binding_persistence_adapter(DocumentBindingPersistence)
class PostgresCompanyTaxTransaction:
    """Only the four public collaborators, bound to an already-open connection."""

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
            raise CompanyTaxError.unavailable() from None
        except psycopg.DatabaseError as error:
            raise _company_tax_database_error(error) from None

    async def _one_idempotent_row(self, query: str, parameters: tuple[object, ...]):
        rows = await self._database_rows(query, parameters)
        if len(rows) != 1:
            raise CompanyTaxError.unavailable()
        return rows[0]

    async def _tax_rows(self, query: str, payload: Mapping[str, object]):
        return await self._database_rows(query, (
            json.dumps(dict(payload), separators=(',', ':')), str(self.actor_id.subject),
        ))

    async def filing_company_identity(self, company_id: CompanyId, actor_id: ActorId) -> CompanyTaxCompanyIdentity:
        if actor_id != self.actor_id:
            raise CompanyTaxError.forbidden()
        row = await self._one_idempotent_row(
            'select public.company_access_read_rf_company_identity_v1(%s::uuid,%s::text) as result',
            (str(company_id), str(actor_id.subject)),
        )
        result = row.get('result')
        if (not isinstance(result, Mapping) or result.get('id') != str(company_id)
                or not isinstance(result.get('org_number'), str)):
            raise CompanyTaxError.unavailable()
        return CompanyTaxCompanyIdentity(company_id, result['org_number'])

    async def import_return_evidence(self, projection: CompanyTaxEvidenceProjection, actor_id: ActorId) -> ImportedCompanyTaxEvidence:
        if actor_id != self.actor_id:
            raise CompanyTaxError.forbidden()
        row = await self._one_idempotent_row(
            'select company_tax_filing.import_tt02_evidence_v1(%s::jsonb,%s::text) as result',
            (json.dumps(_json_value({'authorityRun': projection.authority_run, 'submission': projection.submission}),
                        ensure_ascii=True, allow_nan=False, separators=(',', ':')), str(actor_id.subject)),
        )
        result = row.get('result')
        try:
            if (not isinstance(result, Mapping) or type(result.get('created')) is not bool
                    or not isinstance(result.get('authority_test_run_id'), str)
                    or not isinstance(result.get('filing_submission_id'), str)):
                raise ValueError()
            return ImportedCompanyTaxEvidence(TaxAuthorityEvidenceId(result['authority_test_run_id']),
                TaxFilingSubmissionId(result['filing_submission_id']), result['created'])
        except (KeyError, TypeError, ValueError):
            raise CompanyTaxError.unavailable() from None

    async def include_audit_event(self, event: AuditEventDraft) -> None:
        if event.actor_id != self.actor_id:
            raise CompanyTaxError.forbidden()
        await self._database_rows(
            'select public.audit_include_filing_event_v1(%s::uuid,%s::text,%s::text,%s::text,%s::text)',
            (str(event.company_id), str(event.actor_id.subject), event.category, event.action, event.message),
        )

    async def filing_workspace(self, query: CompanyTaxWorkspaceQuery) -> CompanyTaxFilingRows:
        if query.actor_id != self.actor_id:
            raise CompanyTaxError.forbidden()
        row = await self._one_idempotent_row(
            'select company_tax_filing.read_workspace_v1(%s::uuid,%s::integer,%s::text) as result',
            (str(query.company_id), int(query.income_year) if query.income_year is not None else None,
             str(self.actor_id.subject)),
        )
        result = row.get('result')
        try:
            if not isinstance(result, Mapping):
                raise ValueError()
            return CompanyTaxFilingRows(query.company_id, query.income_year,
                **{name: result[name] for name in ('previews', 'submissions', 'overrides',
                                                  'review_comments', 'permissions', 'test_evidence')})
        except (KeyError, TypeError, ValueError):
            raise CompanyTaxError.unavailable() from None

    async def archive_settlements(self, query: TaxSettlementArchiveQuery) -> tuple[Mapping[str, object], ...]:
        if query.actor_id != self.actor_id:
            raise CompanyTaxError.forbidden()
        row = await self._one_idempotent_row(
            'select company_tax_filing.archive_settlements_v1(%s::uuid,%s::integer,%s::text) as result',
            (str(query.company_id), int(query.income_year), str(self.actor_id.subject)),
        )
        values = row.get('result')
        if not isinstance(values, list) or any(not isinstance(value, Mapping) for value in values):
            raise CompanyTaxError.unavailable()
        return tuple(values)

    async def prepare_settlement(self, command: RecordTaxSettlementCommand) -> Mapping[str, object] | None:
        if command.actor_id != self.actor_id:
            raise CompanyTaxError.forbidden()
        rows = await self._tax_rows('select company_tax_filing.prepare_settlement_v1(%s::jsonb, %s::text) as result', _request(command))
        if len(rows) != 1 or not isinstance(rows[0].get('result'), Mapping):
            raise CompanyTaxError.unavailable()
        result = rows[0]['result']
        if 'replay' not in result or (result['replay'] is not None and not isinstance(result['replay'], Mapping)):
            raise CompanyTaxError.unavailable()
        return result['replay']

    async def complete_settlement(self, command: RecordTaxSettlementCommand, accounting_entry_id: AccountingEntryReference) -> Mapping[str, object]:
        if command.actor_id != self.actor_id:
            raise CompanyTaxError.forbidden()
        rows = await self._database_rows(
            'select company_tax_filing.complete_settlement_v1(%s::jsonb, %s::uuid, %s::text) as result',
            (json.dumps(_request(command), separators=(',', ':')), str(accounting_entry_id), str(self.actor_id.subject)),
        )
        if len(rows) != 1 or not isinstance(rows[0].get('result'), Mapping):
            raise CompanyTaxError.unavailable()
        return dict(rows[0]['result'])

    async def prepare_tax_settlement_bank(self, command: TaxSettlementBankCommand) -> None:
        if command.actor_id != self.actor_id:
            raise CompanyTaxError.forbidden()
        await self._tax_rows('select banking.prepare_tax_settlement_transaction_v1(%s::jsonb, %s::text)', _bank_request(command))

    async def claim_tax_settlement_bank(self, command: TaxSettlementBankCommand) -> None:
        if command.actor_id != self.actor_id:
            raise CompanyTaxError.forbidden()
        await self._tax_rows('select banking.claim_tax_settlement_transaction_v1(%s::jsonb, %s::text)', _bank_request(command))

    async def lock_document_binding(self, query: DocumentBindingQuery) -> None:
        if query.actor_id != self.actor_id:
            raise CompanyTaxError.forbidden()
        await self._database_rows(
            'select documents.lock_metadata_binding_v1(%s::uuid, %s::uuid, %s::integer, %s::text)',
            (str(query.document_id), str(query.company_id), int(query.income_year), str(self.actor_id.subject)),
        )

    async def post_entry(self, command, *, entry_kind, memo, lines, risk_flags, warning_accepted, source_capability, source_record_id, requested_entry_id=None):
        if (not isinstance(command, PostTaxSettlementCommand) or command.actor_id != self.actor_id
                or entry_kind is not LedgerEntryKind.TAX_SETTLEMENT or risk_flags or warning_accepted
                or source_capability is not LedgerSourceCapability.COMPANY_TAX_FILING
                or source_record_id != command.settlement_id or requested_entry_id is not None):
            raise LedgerError.invalid_input('LEDGER_INVALID_INPUT')
        row = await self._one_idempotent_row(
            'select * from ledger.post_company_tax_settlement_v1(%s::text, %s::uuid, %s::integer, %s::text, %s::jsonb, %s::text, %s::text, %s::text)',
            (str(command.idempotency_key), str(command.company_id), int(command.income_year), memo,
             json.dumps([_line_payload(line) for line in lines], separators=(',', ':')),
             str(source_record_id), str(command.correlation_id), str(command.actor_id.subject)),
        )
        return _posted_entry(row)


def compose_company_tax_application(sessions: CompanyTaxSessionFactory | None = None) -> CompanyTaxApplication:
    return CompanyTaxApplication(sessions or PostgresCompanyTaxAdapter.from_environment(), LedgerService)
