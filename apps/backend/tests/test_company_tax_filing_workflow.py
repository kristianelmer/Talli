"""Capture boundaries and historical replay order, independent of HTTP/SQL."""
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import date, datetime, timezone
import asyncio

import pytest

from talli_backend.application.company_tax_filing_workflow import CompanyTaxApplication
from talli_backend.modules.company_tax_filing.public import (
    BankTransactionReference, CompanyTaxError, DocumentReference, RecordTaxSettlementCommand,
    TaxSettlementDocumentStatus, TaxSettlementId, TaxSettlementKind,
)
from talli_backend.modules.ledger.public import LedgerEntryId, PostedLedgerEntry
from talli_backend.modules.ledger.service import LedgerService
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, CorrelationId, IdempotencyKey, IncomeYear, LocalDate, Money, Timestamp, UserId

ACTOR = ActorId(ActorKind.USER, UserId('00000000-0000-0000-0000-000000000011'))
COMPANY = CompanyId('10000000-0000-0000-0000-000000000001')
ACTION = TaxSettlementId('70000000-0000-4000-8000-000000000001')
ENTRY = LedgerEntryId('70000000-0000-4000-8000-000000000002')
NOW = Timestamp(datetime(2026, 9, 13, tzinfo=timezone.utc))


def command(kind=TaxSettlementKind.PAYMENT):
    return RecordTaxSettlementCommand(COMPANY, ACTOR, CorrelationId(str(ACTION)), IdempotencyKey(str(ACTION)), IncomeYear(2026), ACTION, LocalDate(date(2026,4,15)), Money.nok('125.50'), kind, TaxSettlementDocumentStatus.ATTACHED, BankTransactionReference('70000000-0000-4000-8000-000000000003') if kind is not TaxSettlementKind.PAYABLE else None, DocumentReference('70000000-0000-4000-8000-000000000004'))


class Transaction:
    actor_id = ACTOR
    def __init__(self, replay=None, fail=None):
        self.replay, self.fail, self.events, self.pending, self.committed = replay, fail, [], [], []

    async def session(self, _token): return self

    @asynccontextmanager
    async def transaction(self):
        self.events.append('begin')
        try:
            yield self
        except Exception:
            self.pending.clear()
            self.events.append('rollback')
            raise
        else:
            self.committed += self.pending
            self.pending.clear()
            self.events.append('commit')

    async def prepare_settlement(self, _command):
        self.events.append('prepare')
        return self.replay

    async def prepare_tax_settlement_bank(self, command):
        self.events.append(('bank-lock', command.expected_signed_amount.amount))

    async def lock_document_binding(self, query):
        assert query.company_id == COMPANY and query.actor_id == ACTOR
        self.events.append('document-lock')

    async def post_entry(self, command, **posting):
        self.events.append('post')
        self.pending.append(('entry', posting))
        return PostedLedgerEntry(ENTRY, COMPANY, command.income_year, posting['entry_kind'], NOW, False)

    async def claim_tax_settlement_bank(self, command):
        self.events.append('bank-claim')
        assert str(command.action_reference) == str(ACTION)
        if self.fail == 'bank': raise CompanyTaxError.unavailable()
        self.pending.append(('bank', str(command.action_reference)))

    async def complete_settlement(self, command, entry):
        assert str(entry) == str(ENTRY)
        self.events.append('complete')
        if self.fail == 'complete': raise CompanyTaxError.unavailable()
        self.pending.append(('action', str(command.action_id)))
        return dict(actionId=str(ACTION), auditRequired=True, auditAction='tax_settlement_recorded')


def record(transaction, value=None):
    async def execute():
        session = await CompanyTaxApplication(transaction, LedgerService).session('fixture')
        return await session.record_tax_settlement(value or command())
    return asyncio.run(execute())


@pytest.mark.parametrize('kind', list(TaxSettlementKind))
def test_capture_uses_original_action_identity_and_one_transaction(kind):
    tx = Transaction()
    result = record(tx, command(kind))
    assert result.posted_entry.entry_id == ENTRY and not result.replayed
    assert result.result['auditRequired'] is True
    assert tx.events[0:2] == ['begin', 'prepare']
    assert tx.events[-1] == 'commit'
    expected = ['entry', 'action'] if kind is TaxSettlementKind.PAYABLE else ['entry', 'bank', 'action']
    assert [event[0] for event in tx.committed] == expected
    if kind is not TaxSettlementKind.PAYABLE:
        assert tx.events[2][1] == Money.nok('-125.50' if kind is TaxSettlementKind.PAYMENT else '125.50').amount
    assert tx.events.index('document-lock') < tx.events.index('post') < tx.events.index('complete')


@pytest.mark.parametrize('failure', ['bank', 'complete'])
def test_late_failure_rolls_back_all_three_effects(failure):
    tx = Transaction(fail=failure)
    with pytest.raises(CompanyTaxError): record(tx)
    assert tx.committed == [] and tx.pending == [] and tx.events[-1] == 'rollback'


def test_historical_replay_precedes_new_input_and_dependency_checks():
    payload = dict(entryId=str(ENTRY), companyId=str(COMPANY), incomeYear=2026, entryKind='TAX_SETTLEMENT', postedAt=NOW.value.isoformat(), actionId=str(ACTION), auditRequired=True, auditAction='tax_settlement_recorded')
    tx = Transaction(replay=payload)
    result = record(tx, replace(command(), amount=Money.nok('-1'), settlement_date=LocalDate(date(2025,1,1))))
    assert result.replayed and result.result == payload
    assert tx.events == ['begin', 'prepare', 'commit'] and tx.committed == []


def test_replay_cannot_substitute_another_action():
    tx = Transaction(replay=dict(entryId=str(ENTRY), companyId=str(COMPANY), incomeYear=2026, entryKind='TAX_SETTLEMENT', postedAt=NOW.value.isoformat(), actionId='70000000-0000-4000-8000-000000000099'))
    with pytest.raises(CompanyTaxError): record(tx)
    assert tx.events == ['begin', 'prepare', 'rollback']


def test_forged_actor_never_opens_transaction():
    tx = Transaction()
    with pytest.raises(CompanyTaxError): record(tx, replace(command(), actor_id=ActorId(ActorKind.USER,UserId('00000000-0000-0000-0000-000000000022'))))
    assert tx.events == []
