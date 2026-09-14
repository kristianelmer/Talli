"""Positive history evidence, conservative production facts and immutable binding."""
import copy
from dataclasses import replace
from datetime import datetime, timedelta
import json
from pathlib import Path

import pytest

from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError, CompanyTaxFilingRows, CompanyTaxSourceQuery, CompanyTaxSourceSnapshot,
    project_company_tax_source, verify_company_tax_source,
)
from talli_backend.shared.kernel import ActorId, ActorKind, UserId, CompanyId, IncomeYear, Timestamp

FIXTURE = json.loads((Path(__file__).resolve().parents[3] / 'architecture/evidence/issues/152/source-handoff/local-source-snapshot.json').read_text())


def source(empty=False):
    return copy.deepcopy(FIXTURE['emptyYearSnapshot' if empty else 'snapshot'])


def parse(raw):
    query = CompanyTaxSourceQuery(CompanyId(raw['companyId']), IncomeYear(raw['incomeYear']),
                                 ActorId(ActorKind.USER, UserId('00000000-0000-0000-0000-000000000152')))
    snapshot = CompanyTaxSourceSnapshot(CompanyTaxFilingRows(query.company_id, query.income_year, **raw['workspace']),
        raw['coverage'], Timestamp(datetime.fromisoformat(raw['asOf'])), raw['completeEnumeration'])
    return query, snapshot


def test_positive_complete_source_keeps_test_receipts_out_of_production_history():
    query, snapshot = parse(source())
    facts = project_company_tax_source(query, snapshot)
    assert facts.history_coverage.status == 'complete'
    assert facts.history_coverage.reasons == ()
    assert facts.recorded_submissions
    assert facts.production_attempts == ()
    assert all(row.effect_status == 'not_production' for row in facts.recorded_submissions)
    assert facts.readiness_status == 'blocked'
    assert facts.hard_blocks == ('company_tax_production_disabled',)
    assert verify_company_tax_source(query, facts.evidence, snapshot)


def test_empty_year_requires_positive_coverage_before_no_production_is_reported():
    query, snapshot = parse(source(True))
    complete = project_company_tax_source(query, snapshot)
    assert complete.history_coverage.status == 'complete'
    assert complete.production_attempts == complete.recorded_submissions == ()
    missing = project_company_tax_source(query, replace(snapshot, coverage=None))
    assert missing.history_coverage.status == 'unavailable'
    assert missing.readiness_status == 'unavailable'
    assert not verify_company_tax_source(query, complete.evidence, replace(snapshot, coverage=None))


@pytest.mark.parametrize('mutate', [
    lambda r: r['coverage'].update(companyId='00000000-0000-0000-0000-000000000199'),
    lambda r: r['coverage'].update(incomeYear=2024),
    lambda r: r['coverage'].update(scope='all_authority_filings'),
    lambda r: r['coverage'].update(phase='expanded'),
    lambda r: r['coverage'].update(sourceRevision='unknown'),
    *[lambda r, flag=flag: r['coverage'].update({flag: False}) for flag in (
        'inventoryValid', 'quarantineClear', 'sourceRowsValid', 'legacyFencesValid', 'modeChecksValid', 'declaredExtentValid')],
    lambda r: r['coverage'].update(reconciledFamilies=[]),
    lambda r: r['coverage']['familyCounts'].pop('filing_previews'),
    lambda r: r['coverage']['familyCounts'].update(filing_previews=999),
    lambda r: r['coverage']['familyCounts'].update(authority_test_runs=True),
    lambda r: r['coverage']['familyDigests'].update(filing_submissions='invalid'),
    lambda r: r['coverage']['inventory'].pop('table:public.filing_submissions'),
    lambda r: r['coverage'].update(retainedSubmissionIds=['00000000-0000-0000-0000-000000000199']),
    lambda r: r.update(completeEnumeration=False),
])
def test_missing_or_mismatched_coverage_never_proves_complete_history(mutate):
    raw = source()
    mutate(raw)
    query, snapshot = parse(raw)
    facts = project_company_tax_source(query, snapshot)
    assert facts.history_coverage.status == 'incomplete'
    assert facts.history_coverage.reasons
    assert not verify_company_tax_source(query, facts.evidence, snapshot)


@pytest.mark.parametrize('mode,adapter_mode', [('simulation','production'),('test_authority','production'),('unknown','unknown')])
def test_production_label_without_a_journal_is_an_unknown_attempt(mode, adapter_mode):
    raw = source()
    row = raw['workspace']['submissions'][0]
    row.update(mode=mode, adapter_mode=adapter_mode, status='receipt_stored', failure_code='SYNTHETIC_FAILURE')
    query, snapshot = parse(raw)
    facts = project_company_tax_source(query, snapshot)
    assert facts.history_coverage.status == 'incomplete'
    assert 'production_journal_unavailable' in facts.history_coverage.reasons
    assert facts.production_attempts[0].effect_status == 'unknown'
    assert facts.outcomes[0].outcome == 'unknown'
    assert facts.incidents[0].failure_code == 'SYNTHETIC_FAILURE'
    assert facts.incidents[0].attribution == 'unknown'
    assert facts.production_attempts[0].observed_at == row['updated_at']
    assert facts.production_attempts[0].submitted_by == row['submitted_by']


def test_correction_link_requires_the_recorded_parent_and_is_not_guessed():
    raw = source()
    raw['workspace']['submissions'][0]['supersedes_submission_id'] = '00000000-0000-0000-0000-000000000199'
    query, snapshot = parse(raw)
    facts = project_company_tax_source(query, snapshot)
    assert facts.correction_links[0].supersedes_source_id.endswith('199')
    assert 'correction_history_missing' in facts.history_coverage.reasons


def test_snapshot_and_evidence_are_detached_scope_bound_and_stale_after_source_change():
    raw = source()
    query, snapshot = parse(raw)
    facts = project_company_tax_source(query, snapshot)
    raw['coverage']['familyCounts']['filing_submissions'] = 123
    assert snapshot.coverage['familyCounts']['filing_submissions'] != 123
    with pytest.raises(TypeError):
        snapshot.coverage['familyCounts']['filing_submissions'] = 123
    later = replace(snapshot, as_of=Timestamp(snapshot.as_of.value + timedelta(seconds=5)))
    assert verify_company_tax_source(query, facts.evidence, later)
    assert facts.evidence.digest == project_company_tax_source(query, later).evidence.digest
    assert not verify_company_tax_source(query, replace(facts.evidence, evaluated_at=later.as_of), snapshot)
    assert not verify_company_tax_source(query, replace(facts.evidence, obligation='aarsregnskap'), snapshot)
    changed = source()
    changed['workspace']['submissions'][0]['failure_code'] = 'NEW_SOURCE_FACT'
    _, changed_snapshot = parse(changed)
    assert not verify_company_tax_source(query, facts.evidence, changed_snapshot)
    with pytest.raises(CompanyTaxError):
        project_company_tax_source(replace(query, income_year=IncomeYear(2024)), snapshot)


def test_source_http_authenticates_and_uses_a_repeatable_owner_snapshot():
    from contextlib import asynccontextmanager
    from fastapi.testclient import TestClient
    from talli_backend.main import create_app
    from talli_backend.application.ledger_session import LedgerAuthenticationError

    query, snapshot = parse(source())

    class Sessions:
        actor_id = query.actor_id
        expected_snapshot = snapshot
        calls = []

        async def session(self, token):
            if token != 'synthetic-fixture':
                raise LedgerAuthenticationError()
            return self

        @asynccontextmanager
        async def transaction(self, *, snapshot=False):
            assert snapshot is True
            self.calls.append('repeatable_snapshot')
            yield self

        async def filing_source_snapshot(self, selected):
            assert selected == query
            return self.expected_snapshot

    sessions = Sessions()
    client = TestClient(create_app(company_tax_session_factory=sessions))
    path = f'/api/v1/company-tax/source-facts?companyId={query.company_id}&incomeYear={int(query.income_year)}'
    assert client.get(path).status_code == 401
    response = client.get(path, headers={'Authorization':'Bearer synthetic-fixture'})
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['evidence']['companyId'] == str(query.company_id)
    assert value['evidence']['incomeYear'] == int(query.income_year)
    assert value['historyCoverage']['status'] == 'complete'
    assert value['productionAttempts'] == []
    assert value['readinessStatus'] == 'blocked'
    assert sessions.calls == ['repeatable_snapshot']
    sessions.expected_snapshot = replace(snapshot, coverage=None)
    response = client.get(path, headers={'Authorization':'Bearer synthetic-fixture'})
    assert response.json()['historyCoverage']['status'] == 'unavailable'
    assert response.json()['readinessStatus'] == 'unavailable'
    sessions.expected_snapshot = replace(snapshot, rows=replace(snapshot.rows, income_year=None))
    assert client.get(path, headers={'Authorization':'Bearer synthetic-fixture'}).status_code == 503
    assert client.get(path.replace('incomeYear=2025','incomeYear=1999'), headers={'Authorization':'Bearer synthetic-fixture'}).status_code == 422
