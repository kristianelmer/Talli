"""Request-scoped PostgreSQL composition for Company Tax settlement capture."""
from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
import json
import os

import psycopg
from psycopg.rows import dict_row

from talli_backend.adapters.supabase_ledger import (
    LedgerSupabaseConfiguration, SupabaseLedgerAdapter, SupabaseLedgerWorkflowTransaction,
    _VerifiedActor, _line_payload, _map_database_error, _posted_entry,
)
from talli_backend.application.company_tax_filing_session import CompanyTaxSessionFactory
from talli_backend.application.company_tax_filing_workflow import CompanyTaxApplication
from talli_backend.modules.banking.public import (
    TaxSettlementBankCommand, TaxSettlementBankingPersistence,
    bank_transaction_claim_persistence_adapter,
)
from talli_backend.modules.company_tax_filing.public import (
    AccountingEntryReference, CompanyTaxError, RecordTaxSettlementCommand,
    TaxSettlementPersistence, tax_settlement_persistence_adapter,
)
from talli_backend.modules.documents.public import (
    DocumentBindingPersistence, DocumentBindingQuery, document_binding_persistence_adapter,
)
from talli_backend.modules.ledger.public import (
    LedgerEntryKind, LedgerError, LedgerPersistence, LedgerSourceCapability,
    PostTaxSettlementCommand, ledger_persistence_adapter,
)
from talli_backend.modules.ledger.service import LedgerService


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
                yield PostgresCompanyTaxTransaction(self._database_url, self._verified, connection)
        except (CompanyTaxError, LedgerError):
            raise
        except psycopg.OperationalError:
            raise CompanyTaxError.unavailable() from None
        except psycopg.DatabaseError as error:
            # Existing receipt, Ledger and input codes remain part of released v1.
            raise _map_database_error(str(error)) from None


@tax_settlement_persistence_adapter(TaxSettlementPersistence)
@ledger_persistence_adapter(LedgerPersistence)
@bank_transaction_claim_persistence_adapter(TaxSettlementBankingPersistence)
@document_binding_persistence_adapter(DocumentBindingPersistence)
class PostgresCompanyTaxTransaction(SupabaseLedgerWorkflowTransaction):
    async def _tax_rows(self, query: str, payload: Mapping[str, object]):
        return await self._database_rows(query, (
            json.dumps(dict(payload), separators=(',', ':')), str(self.actor_id.subject),
        ))

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
