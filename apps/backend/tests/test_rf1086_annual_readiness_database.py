"""Composed annual owner reads on one real RF admission connection."""
import asyncio
from decimal import Decimal

import psycopg
from psycopg.types.json import Jsonb
import pytest

from talli_backend.application.shareholder_register_annual_readiness import read_annual_readiness
from talli_backend.application.shareholder_register_source_admission import AdmittedRf1086Source
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId, CorrelationId, IncomeYear
from test_annual_purchase_basis_runtime import admitted, DATABASE_URL
from test_rf1086_database_runtime import backend_url, rf_fixture_admin_access
from test_rf1086_year_source_database import remove_only_owned_source_fixture
from test_rf1086_source_preview_database import remove_only_preview_fixture
from test_rf1086_source_review_bridge_database import prepare
from test_rf_annual_opening_admission_database import add_opening
from test_rf_annual_ledger_admission_database import ledger_fixture_insert_access, add_lock
from test_annual_interview_company_guard_database import fixture_roles, seed, bind

pytestmark = pytest.mark.authority_database


def test_composition_requires_matching_opening_and_observes_current_interview(admitted, backend_url):
    store, _, _, source, preview = prepare(admitted, backend_url)
    async def read():
        query = rf.Rf1086SourceQuery(CompanyId(str(admitted['company'])), IncomeYear(2026), store.actor_id)
        async with store.source_admission(query) as scope:
            return await read_annual_readiness(AdmittedRf1086Source(source, preview, (), scope),
                                              CorrelationId('annual-composition-database'))
    before = asyncio.run(read())
    assert before.readiness_status == 'blocked'
    assert {item.code for item in before.issues} >= {'opening_balance_missing',
        'opening_bank_input_missing_or_mismatched', 'annual_data_missing', 'period_not_locked'}
    with psycopg.connect(DATABASE_URL) as db:
        opening, _ = add_opening(db, admitted)
    assert 'opening_bank_input_missing_or_mismatched' in {item.code for item in asyncio.run(read()).issues}
    with ledger_fixture_insert_access(DATABASE_URL):
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('insert into ledger.opening_bank_inputs(snapshot_id,company_id,income_year,bank_balance_nok,recorded_by,recorded_at) values(%s,%s,2026,%s,%s,clock_timestamp())',
                       (opening, admitted['company'], Decimal('123.45'), admitted['owner']))
            add_lock(db, admitted)
    interview = seed(admitted)
    warning = asyncio.run(read())
    assert warning.readiness_status == 'warning' and warning.required_warning_codes == ('bank_balance_not_confirmed',)
    with psycopg.connect(DATABASE_URL) as db:
        bind(db, admitted)
        db.execute('update public.annual_data set answers=%s where id=%s', (Jsonb({
            'bank_balance_confirmed': True, 'has_unpaid_items': False, 'authority_to_submit_confirmed': True}), interview))
    ready = asyncio.run(read())
    assert ready.readiness_status == 'ready' and ready.proof_sha256 != warning.proof_sha256
    assert ready.annual_inputs.opening_snapshot_ids == ready.annual_inputs.opening_bank_snapshot_ids == (str(opening),)
    assert ready == asyncio.run(read())  # Banking observed_at is not evidence identity.
    with psycopg.connect(DATABASE_URL) as db:
        bind(db, admitted)
        db.execute('update public.annual_data set answers=%s where id=%s', (Jsonb({
            'bank_balance_confirmed': True, 'has_unpaid_items': True, 'authority_to_submit_confirmed': True}), interview))
    blocked = asyncio.run(read())
    assert blocked.readiness_status == 'blocked'
    assert 'unpaid_items_not_supported' in {item.code for item in blocked.issues}
    assert blocked.source == ready.source and blocked.proof_sha256 != ready.proof_sha256
