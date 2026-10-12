"""Complete owner projections must never degrade to a ready-looking empty page."""
import asyncio
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from test_supabase_banking import ACTOR_ID, COMPANY_ID, bound_session
from talli_backend.modules.banking.public import BankYearReconciliation, BankingError
from talli_backend.modules.banking.service import BankingService
from talli_backend.shared.kernel import ActorId, ActorKind, CorrelationId, IncomeYear, Timestamp, UserId

YEAR = IncomeYear(2026)
QUERY = dict(actor_id=ACTOR_ID, company_id=COMPANY_ID, income_year=YEAR,
             correlation_id=CorrelationId('bank-year-test'))


def row():
    return dict(company_id=UUID(str(COMPANY_ID)), income_year=2026,
                observed_at=datetime(2026, 9, 29, tzinfo=UTC),
                transaction_count=503, unmatched_count=501, accepted_warning_count=1)


def test_owned_read_is_unpaginated_scoped_and_reaches_service():
    session = bound_session()
    calls = []
    async def read(sql, parameters):
        calls.append((sql, parameters))
        return [row()]
    session._banking_rows = read
    result = asyncio.run(BankingService(session).read_year_reconciliation(**QUERY))
    assert result == BankYearReconciliation(COMPANY_ID, YEAR, Timestamp(row()['observed_at']), 503, 501, 1)
    assert calls == [('select * from banking.read_year_reconciliation_v1(%s::uuid, %s::integer, %s::text)',
                      (str(COMPANY_ID), 2026, str(ACTOR_ID.subject)))]
    with pytest.raises(FrozenInstanceError):
        result.unmatched_count = 0


@pytest.mark.parametrize('field,value', [
    ('company_id', UUID('10000000-0000-0000-0000-000000000099')),
    ('income_year', 2025), ('income_year', '2026'), ('income_year', True),
    ('observed_at', None), ('observed_at', '2026-01-01'),
    ('transaction_count', -1), ('transaction_count', True), ('transaction_count', '503'),
    ('unmatched_count', 504), ('unmatched_count', None), ('unmatched_count', 0.0),
    ('accepted_warning_count', 3), ('accepted_warning_count', -1),
])
def test_malformed_or_wrong_scope_does_not_become_empty_or_ready(field, value):
    session = bound_session()
    async def read(*args):
        return [row() | {field: value}]
    session._banking_rows = read
    with pytest.raises(BankingError) as error:
        asyncio.run(session.read_year_reconciliation(**QUERY))
    assert error.value.code == 'BANKING_DEPENDENCY_UNAVAILABLE'


@pytest.mark.parametrize('rows', [[], [row(), row()], [{}], [None]])
def test_missing_or_duplicate_projection_is_unavailable(rows):
    session = bound_session()
    async def read(*args):
        return rows
    session._banking_rows = read
    with pytest.raises(BankingError) as error:
        asyncio.run(session.read_year_reconciliation(**QUERY))
    assert error.value.code == 'BANKING_DEPENDENCY_UNAVAILABLE'


def test_wrong_actor_is_rejected_before_database_io():
    session = bound_session()
    async def read(*args):
        pytest.fail('foreign actor must not query')
    session._banking_rows = read
    other = ActorId(ActorKind.USER, UserId('20000000-0000-0000-0000-000000000099'))
    with pytest.raises(BankingError) as error:
        asyncio.run(session.read_year_reconciliation(**(QUERY | {'actor_id': other})))
    assert error.value.code == 'BANKING_FORBIDDEN'


def test_explicit_zero_counts_are_valid_but_not_filing_authority():
    summary = BankYearReconciliation(COMPANY_ID, YEAR, Timestamp(row()['observed_at']), 0, 0, 0)
    assert not hasattr(summary, 'ready')
    assert replace(summary, transaction_count=1, accepted_warning_count=1).unmatched_count == 0


def test_exact_evidence_read_reaches_service_and_preserves_original_count_api():
    from talli_backend.modules.banking.public import BankYearReconciliationEvidence
    session = bound_session()
    calls = []
    async def read(sql, parameters):
        calls.append((sql, parameters))
        return [row() | {'source_sha256': 'a' * 64,
                         'schema_version': 'banking-year-reconciliation-evidence-v1'}]
    session._banking_rows = read
    result = asyncio.run(BankingService(session).read_year_reconciliation_evidence(**QUERY))
    assert isinstance(result, BankYearReconciliationEvidence)
    assert result.reconciliation == BankYearReconciliation(COMPANY_ID, YEAR, Timestamp(row()['observed_at']), 503, 501, 1)
    assert result.source_sha256 == 'a' * 64
    assert calls == [('select * from banking.read_year_reconciliation_evidence_v1(%s::uuid, %s::integer, %s::text)',
                      (str(COMPANY_ID), 2026, str(ACTOR_ID.subject)))]
    with pytest.raises(FrozenInstanceError): result.source_sha256 = 'b' * 64
    assert not hasattr(result, 'ready')


@pytest.mark.parametrize('field,value', [
    ('source_sha256', None), ('source_sha256', 'a' * 63), ('source_sha256', 'A' * 64),
    ('source_sha256', 1), ('schema_version', None), ('schema_version', 'v2'),
    ('transaction_count', True), ('unmatched_count', -1), ('accepted_warning_count', 503),
    ('company_id', UUID('10000000-0000-0000-0000-000000000099')), ('income_year', True),
    ('observed_at', '2026-01-01'),
])
def test_invalid_exact_evidence_is_never_admitted(field, value):
    session = bound_session()
    async def read(*args):
        return [row() | {'source_sha256': 'a' * 64,
                         'schema_version': 'banking-year-reconciliation-evidence-v1', field: value}]
    session._banking_rows = read
    with pytest.raises(BankingError) as error:
        asyncio.run(session.read_year_reconciliation_evidence(**QUERY))
    assert error.value.code == 'BANKING_DEPENDENCY_UNAVAILABLE'


@pytest.mark.parametrize('rows', [[], [row(), row()], [{}], [None]])
def test_missing_exact_evidence_fails_closed(rows):
    session = bound_session()
    async def read(*args): return rows
    session._banking_rows = read
    with pytest.raises(BankingError): asyncio.run(session.read_year_reconciliation_evidence(**QUERY))


def test_foreign_actor_cannot_request_exact_evidence():
    session = bound_session()
    async def read(*args): pytest.fail('foreign actor must not query')
    session._banking_rows = read
    other = ActorId(ActorKind.USER, UserId('20000000-0000-0000-0000-000000000099'))
    with pytest.raises(BankingError) as error:
        asyncio.run(session.read_year_reconciliation_evidence(**(QUERY | {'actor_id': other})))
    assert error.value.code == 'BANKING_FORBIDDEN'
