"""Real RLS regression for the historical receipt-policy overwrite.

Only the exact historical SELECT-policy block is reinstalled. Policy and local
test-authority changes roll back; no complete lifecycle or RF schema teardown.
"""
import json
from pathlib import Path

import psycopg
from psycopg import sql
import pytest

from governance_completion_rehearsal import read_rehearsal_migration
from test_company_access_rf_admission_database import (
    DATABASE_URL, RECEIPT_COMMANDS, RECEIPT_DB_OPTIONS,
    company_year_receipts, receipt_actor,
)


pytestmark = pytest.mark.authority_database
ROOT = Path(__file__).resolve().parents[3]
REPAIR = '20261016134500_company_year_receipt_replay.sql'


def update_guard(db):
    return db.execute("""select polcmd,polpermissive,polroles::text,
        pg_get_expr(polqual,polrelid),pg_get_expr(polwithcheck,polrelid)
        from pg_policy where polrelid='public.company_access_command_receipts'::regclass
          and polname='company year receipts reject updates'""").fetchone()


def test_historical_select_reset_then_registered_successor_restores_immutable_own_receipts(company_year_receipts):
    fixture = company_year_receipts
    historical = (ROOT / 'supabase/migrations/20260830091341_case_bound_support_access.sql').read_text()
    start = historical.index('drop policy if exists "company access commands read receipts"')
    end = historical.index('\ncreate or replace function', start)
    historical_select = historical[start:end]
    layers = json.loads((ROOT / 'scripts/rf-consequential-successors.json').read_text())
    layer, = [entry for entry in layers if entry['migration'] == REPAIR]
    query = 'select to_jsonb(r) from public.company_access_command_receipts r where operation_id=%s'

    with psycopg.connect(DATABASE_URL, **RECEIPT_DB_OPTIONS) as db:
        with db.transaction(force_rollback=True):
            # Real restricted-role RLS, even when this owned stack's migration
            # login needs temporary SET authority. The outer rollback removes it.
            principal = db.execute('select current_user').fetchone()[0]
            if not db.execute("select pg_has_role(current_user,'company_access_executor','SET')").fetchone()[0]:
                db.execute(sql.SQL('grant company_access_executor to {} with inherit false,set true granted by {}').format(
                    sql.Identifier(principal), sql.Identifier(principal)))
            baseline = {command: db.execute(query, (fixture['operations'][command],)).fetchone()
                        for command in RECEIPT_COMMANDS}
            assert all(baseline.values())
            guard = update_guard(db)
            assert guard is not None and guard[0:2] == ('w', False)

            db.execute(historical_select, prepare=False)
            assert update_guard(db) == guard
            # Installed-marker TRUE deliberately does not assert SELECT health.
            assert db.execute(layer['presenceQuery']).fetchone() == (True,)
            with receipt_actor(db, fixture, fixture['owner']):
                assert db.execute('select current_user').fetchone() == ('company_access_executor',)
                assert db.execute('select rolbypassrls from pg_roles where rolname=current_user').fetchone() == (False,)
                for command in RECEIPT_COMMANDS:
                    assert db.execute(query, (fixture['operations'][command],)).fetchone() is None

            # Both normal replay consumers execute this registered source after
            # historical bodies. A second replay must not hit duplicate policy.
            for _ in range(2):
                db.execute(read_rehearsal_migration(ROOT, layer['migration']), prepare=False)
                assert update_guard(db) == guard
                for actor in (fixture['owner'], fixture['outsider'], None):
                    with receipt_actor(db, fixture, actor):
                        for command in RECEIPT_COMMANDS:
                            operation = fixture['operations'][command]
                            expected = baseline[command] if actor == fixture['owner'] else None
                            assert db.execute(query, (operation,)).fetchone() == expected
                            for change in ('result=result', "result='{}'::jsonb", "command_name='accept_invitation'"):
                                assert db.execute(sql.SQL(
                                    'update public.company_access_command_receipts set {} where operation_id=%s'
                                ).format(sql.SQL(change)), (operation,)).rowcount == 0
                            assert db.execute(query + ' for update', (operation,)).fetchall() == []
