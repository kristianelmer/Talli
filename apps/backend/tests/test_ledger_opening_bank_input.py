"""Original opening bank provenance remains independent of RF and current balances."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from talli_backend.adapters.supabase_ledger import SupabaseLedgerSession, _VerifiedActor
from talli_backend.modules.ledger.public import LedgerError, OpeningBankInput, RecordOpeningBankInputCommand
from talli_backend.modules.ledger.service import LedgerService
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, CorrelationId, IdempotencyKey, IncomeYear, Money, Timestamp, UserId

ACTOR = ActorId(ActorKind.USER, UserId("20000000-0000-0000-0000-000000000002"))
OTHER_ACTOR = ActorId(ActorKind.USER, UserId("20000000-0000-0000-0000-000000000003"))
COMPANY = CompanyId("10000000-0000-0000-0000-000000000001")
OTHER_COMPANY = CompanyId("10000000-0000-0000-0000-000000000004")
SNAPSHOT = "30000000-0000-0000-0000-000000000003"
STAMP = Timestamp(datetime(2025, 1, 2, 12, tzinfo=UTC))
CORRELATION = CorrelationId("original-opening-bank")


def command():
    return RecordOpeningBankInputCommand(COMPANY, ACTOR, CORRELATION,
        IdempotencyKey("40000000-0000-4000-8000-000000000004"), IncomeYear(2025),
        SNAPSHOT, Money.nok("9007199254740993.12"))


def recorded():
    return OpeningBankInput(SNAPSHOT, COMPANY, IncomeYear(2025), command().bank_balance, ACTOR, STAMP)


class Persistence:
    def __init__(self, row=None, rows=None):
        self.row = row if row is not None else recorded()
        self.rows = rows if rows is not None else (self.row,)
        self.query = None

    async def record_opening_bank_input(self, value):
        assert value == command()
        return self.row

    async def read_opening_bank_inputs(self, **query):
        self.query = query
        return self.rows


def test_original_recorded_amount_and_attribution_do_not_require_a_current_balance():
    persistence = Persistence()
    service = LedgerService(persistence)
    assert asyncio.run(service.record_opening_bank_input(command())) == recorded()
    result = asyncio.run(service.read_opening_bank_inputs(actor_id=ACTOR, company_id=COMPANY,
        income_year=None, correlation_id=CORRELATION))
    assert result == (recorded(),)
    assert result[0].bank_balance.amount == Decimal("9007199254740993.12")
    assert result[0].recorded_at == STAMP
    assert persistence.query["income_year"] is None


@pytest.mark.parametrize("changed", [
    {"snapshot_id": "30000000-0000-0000-0000-000000000005"},
    {"company_id": OTHER_COMPANY}, {"income_year": IncomeYear(2024)},
    {"bank_balance": Money.nok("10")}, {"recorded_by": OTHER_ACTOR},
])
def test_write_rejects_misbound_provenance(changed):
    service = LedgerService(Persistence(row=replace(recorded(), **changed)))
    with pytest.raises(LedgerError) as failure:
        asyncio.run(service.record_opening_bank_input(command()))
    assert failure.value.code == "LEDGER_DEPENDENCY_UNAVAILABLE"


@pytest.mark.parametrize("rows", [
    (replace(recorded(), company_id=OTHER_COMPANY),),
    (replace(recorded(), income_year=IncomeYear(2024)),),
    (recorded(), recorded()), [recorded()],
])
def test_scoped_read_rejects_cross_company_year_duplicate_and_mutable_results(rows):
    service = LedgerService(Persistence(rows=rows))
    with pytest.raises(LedgerError) as failure:
        asyncio.run(service.read_opening_bank_inputs(actor_id=ACTOR, company_id=COMPANY,
            income_year=IncomeYear(2025), correlation_id=CORRELATION))
    assert failure.value.code == "LEDGER_DEPENDENCY_UNAVAILABLE"


def test_database_adapter_preserves_numeric_precision_and_only_calls_the_owned_port():
    session = SupabaseLedgerSession("unused", _VerifiedActor(ACTOR, "{}"))
    calls = []

    async def rows(sql, parameters=()):
        calls.append((sql, parameters))
        return [{"snapshot_id": SNAPSHOT, "company_id": str(COMPANY), "income_year": 2025,
            "bank_balance_nok": Decimal("9007199254740993.12"), "recorded_by": str(ACTOR.subject),
            "recorded_at": STAMP.value}]

    session._database_rows = rows
    service = LedgerService(session)
    assert asyncio.run(service.record_opening_bank_input(command())) == recorded()
    assert "ledger.record_opening_bank_input_v1" in calls[0][0]
    assert calls[0][1] == (SNAPSHOT, str(COMPANY), 2025, Decimal("9007199254740993.12"), str(ACTOR.subject))
    assert asyncio.run(service.read_opening_bank_inputs(actor_id=ACTOR, company_id=COMPANY,
        income_year=None, correlation_id=CORRELATION)) == (recorded(),)
    assert "ledger.read_opening_bank_inputs_v1" in calls[1][0]
    assert calls[1][1] == (str(COMPANY), None, str(ACTOR.subject))


def test_forged_actor_never_reaches_the_database():
    session = SupabaseLedgerSession("unused", _VerifiedActor(ACTOR, "{}"))

    async def never(*args, **kwargs):
        raise AssertionError("database reached")

    session._database_rows = never
    with pytest.raises(LedgerError) as failure:
        asyncio.run(session.record_opening_bank_input(replace(command(), actor_id=OTHER_ACTOR)))
    assert failure.value.code == "LEDGER_FORBIDDEN"
    with pytest.raises(LedgerError) as failure:
        asyncio.run(session.read_opening_bank_inputs(actor_id=OTHER_ACTOR, company_id=COMPANY,
            income_year=None, correlation_id=CORRELATION))
    assert failure.value.code == "LEDGER_FORBIDDEN"
