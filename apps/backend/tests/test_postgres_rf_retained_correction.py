"""Supplemental input/selected-row boundaries; fake archive proves routing only."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import fields, replace
from types import SimpleNamespace
from uuid import UUID

from psycopg.pq import TransactionStatus
import pytest

from talli_backend.adapters.postgres_shareholder_register_filing import _SourceAdmission
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear
from test_postgres_shareholder_register_filing import session
from test_rf1086_source_correction import predecessor_snapshot
from test_rf1086_year_source import ACTOR


def harness():
    prior = predecessor_snapshot()
    store = session({})
    store._verified = _VerifiedActor(ACTOR, '{}')
    query = rf.Rf1086SourceQuery(prior.company_id, prior.income_year, ACTOR)
    identity = rf.SubmissionId(prior.submission.id)
    state = SimpleNamespace(sql=[], transactions=[], archives=[],
        parent={field.name: getattr(prior.submission, field.name) for field in fields(prior.submission)},
        archive=rf.Rf1086ArchiveSnapshot(prior.company_id, prior.income_year,
            production_submissions=(prior.submission,)))

    class Connection:
        info = SimpleNamespace(transaction_status=TransactionStatus.INTRANS)

        async def execute(self, sql, args):
            state.sql.append((sql, args))
            return self

        async def fetchone(self):
            return state.parent

    connection = Connection()

    @asynccontextmanager
    async def transaction(**options):
        state.transactions.append(options)
        yield connection

    async def archive(active, archive_query, *, include_production):
        assert active is connection and include_production is True
        assert archive_query == rf.Rf1086ArchiveQuery(query.company_id, query.income_year, ACTOR)
        state.archives.append(archive_query)
        return state.archive

    store._transaction = transaction
    store._archive_source_on_connection = archive
    scope = _SourceAdmission(store, connection, query, None)
    return state, store, scope, query, identity


@pytest.mark.parametrize('mode', ['preflight', 'held'])
@pytest.mark.parametrize('shape', ['string-kind', 'system-kind', 'noncanonical-id', 'nonstring-id',
    'noncanonical-company', 'noncanonical-user', 'invalid-year'])
def test_forged_or_loose_identity_values_fail_before_sql(mode, shape):
    state, store, scope, query, identity = harness()
    if shape == 'string-kind':
        query = replace(query, actor_id=ActorId('USER', ACTOR.subject))
    elif shape == 'system-kind':
        query = replace(query, actor_id=ActorId(ActorKind.SYSTEM, ACTOR.subject))
    elif shape == 'invalid-year':
        year = IncomeYear(2025)
        object.__setattr__(year, 'value', 2101)
        query = replace(query, income_year=year)
    elif shape == 'noncanonical-company':
        company = CompanyId(str(query.company_id))
        object.__setattr__(company, 'value', '{' + str(company) + '}')
        query = replace(query, company_id=company)
    elif shape == 'noncanonical-user':
        subject = replace(ACTOR.subject)
        object.__setattr__(subject, 'value', '{' + str(subject) + '}')
        query = replace(query, actor_id=ActorId(ActorKind.USER, subject))
    else:
        object.__setattr__(identity, 'value', ('{' + identity.value + '}')
            if shape == 'noncanonical-id' else UUID(identity.value))
    target = store if mode == 'preflight' else scope
    with pytest.raises(rf.Rf1086ProductionError, match='^basis_unavailable$'):
        asyncio.run(target.read_retained_correction_archive(query, identity))
    assert state.sql == state.transactions == state.archives == []


@pytest.mark.parametrize('mode', ['preflight', 'held'])
@pytest.mark.parametrize('change', ['submitted-by', 'numeric-year', 'missing-field'])
def test_malformed_selected_row_cannot_reach_archive_enumerator(mode, change):
    state, store, scope, query, identity = harness()
    if change == 'submitted-by':
        state.parent['submitted_by'] = str(UUID(int=123456))
    elif change == 'numeric-year':
        state.parent['income_year'] = float(query.income_year.value)
    else:
        del state.parent['approval_id']
    target = store if mode == 'preflight' else scope
    with pytest.raises(rf.Rf1086ProductionError, match='^basis_unavailable$'):
        asyncio.run(target.read_retained_correction_archive(query, identity))
    assert state.sql and not state.archives


@pytest.mark.parametrize('mode', ['preflight', 'held'])
@pytest.mark.parametrize('scope_field', ['company_id', 'income_year'])
def test_archive_scope_mismatch_is_rejected_even_with_matching_selected_parent(mode, scope_field):
    state, store, scope, query, identity = harness()
    other = CompanyId(str(UUID(int=123456))) if scope_field == 'company_id' else IncomeYear(2024)
    state.archive = replace(state.archive, **{scope_field: other})
    target = store if mode == 'preflight' else scope
    with pytest.raises(rf.Rf1086ProductionError, match='^basis_unavailable$'):
        asyncio.run(target.read_retained_correction_archive(query, identity))
    assert len(state.archives) == 1
