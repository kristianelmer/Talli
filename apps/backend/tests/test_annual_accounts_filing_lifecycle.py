"""Real Accounts migration lifecycle on the explicitly supplied disposable database.

All fixtures, migrations, role changes and negative probes are rolled back. This
lane runs after Tax's final contract and before Accounts' explicit expansion.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
import pytest

from accounts_database_fixtures import ACTORS, COMPANY, FAMILIES, IDS, seed

pytestmark = pytest.mark.accounts_database
ROOT = Path(__file__).resolve().parents[3]
EXPANSION = (
    '20260914090244_annual_accounts_filing_expand.sql',
    '20260914092018_annual_accounts_filing_read_contracts.sql',
    '20260914092924_annual_accounts_filing_preparation_contracts.sql',
    '20260914093204_annual_accounts_filing_import_contract.sql',
    '20260914101625_annual_accounts_filing_dependency_contracts.sql',
    '20260914110840_annual_accounts_filing_source_contract.sql',
)
CUTOVER = '20260914101805_annual_accounts_filing_cutover.sql'
CONTRACT = '20260914101842_annual_accounts_filing_contract.sql'


def memberships(db):
    return db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall()


def environment(db):
    return db.execute("""select jsonb_build_object(
      'schemas',(select jsonb_agg(jsonb_build_object('name',nspname,'owner',nspowner,'acl',nspacl) order by nspname)
        from pg_namespace where nspname in ('backend_system','documents','company_tax_filing','shareholder_register_filing')),
      'archive',(select jsonb_agg(to_jsonb(g) order by company_id,income_year) from public.company_archive_source_generations g),
      'audit',(select jsonb_agg(to_jsonb(a) order by id) from public.audit_events a))""").fetchone()[0]


def rows(db, schema):
    return {family: db.execute(sql.SQL("select coalesce(jsonb_agg(to_jsonb(r) order by id),'[]'::jsonb) from {}.{} r").format(
        sql.Identifier(schema), sql.Identifier(family))).fetchone()[0] for family in FAMILIES}


def apply(db, name, *, rollback=False):
    path = ROOT / 'supabase' / ('rollback' if rollback else 'contract-migrations') / name
    raw = path.read_text()
    assert raw.endswith('commit;\n') and 'begin;\n' in raw
    before = memberships(db)
    db.execute(raw.replace('begin;\n', '', 1).removesuffix('commit;\n'), prepare=False)
    assert memberships(db) == before
    # Emulate each artifact's ON COMMIT DROP without committing the outer test.
    for schema, table in db.execute("select n.nspname,c.relname from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.oid=pg_my_temp_schema() and c.relkind='r'").fetchall():
        db.execute(sql.SQL('drop table {}.{} cascade').format(sql.Identifier(schema), sql.Identifier(table)))


@pytest.fixture
def database():
    url = os.environ.get('DATABASE_URL')
    assert url and conninfo_to_dict(url).get('host') in ('localhost', '127.0.0.1', '::1'), 'owned disposable loopback database required'
    with psycopg.connect(url, autocommit=True) as db:
        assert db.execute("select to_regnamespace('annual_accounts_filing') is null").fetchone()[0], 'run before Accounts expansion'
        assert db.execute('select phase from backend_system.company_tax_return_migration_state').fetchone()[0] == 'contracted'
        before = memberships(db)
        db.execute('begin isolation level repeatable read')
        try:
            seed(db)
            for artifact in EXPANSION:
                apply(db, artifact)
            yield db
        finally:
            db.execute('rollback')
            assert memberships(db) == before
            assert db.execute("select to_regnamespace('annual_accounts_filing') is null").fetchone()[0]
            assert db.execute('select count(*) from public.companies where id=%s', (COMPANY,)).fetchone()[0] == 0


@contextmanager
def actor(db, name='owner', *, role='annual_accounts_filing_workflow_executor', fresh=True, aal='aal2'):
    """A real executor and verified claims, with the entire call rolled back."""
    db.execute('savepoint accounts_actor')
    try:
        runner = db.execute('select current_user').fetchone()[0]
        db.execute(sql.SQL('grant {} to {} with set true granted by {}').format(sql.Identifier(role), sql.Identifier(runner), sql.Identifier(runner)))
        identity = ACTORS[name]
        timestamp = int(db.execute('select extract(epoch from transaction_timestamp())').fetchone()[0]) - 1
        claims = json.dumps({'sub': identity, 'role': 'authenticated', 'aal': aal,
                             'amr': [{'method': 'totp', 'timestamp': timestamp if fresh else 1}]})
        for key, value in [('request.jwt.claims', claims), ('talli.verified_actor_id', identity), ('talli.verified_actor_claims', claims)]:
            db.execute('select set_config(%s,%s,true)', (key, value))
        db.execute(sql.SQL('set local role {}').format(sql.Identifier(role)))
        yield identity
    finally:
        db.execute('rollback to savepoint accounts_actor')
        db.execute('release savepoint accounts_actor')


def expect_error(db, message, operation):
    with pytest.raises(psycopg.Error) as caught:
        with db.transaction():
            operation()
    assert caught.value.diag.message_primary == message


def test_latest_state_survives_contract_full_rollback_and_recutover(database):
    db = database
    original = rows(db, 'public')
    before = environment(db)
    apply(db, CUTOVER)
    assert environment(db) == before
    with actor(db, role='annual_accounts_filing_store_owner'):
        assert rows(db, 'annual_accounts_filing') == original
    assert all(value == [] for value in rows(db, 'public').values())
    for family in FAMILIES:
        with pytest.raises(psycopg.Error) as rejected:
            with db.transaction():
                db.execute(sql.SQL('insert into public.{} select (jsonb_populate_record(null::public.{},%s)).*').format(
                    sql.Identifier(family), sql.Identifier(family)), (json.dumps(original[family][0]),))
        assert rejected.value.sqlstate == '23514' or rejected.value.diag.message_primary == 'rf1086_legacy_writer_retired'

    # Keep actual owned writes through later phases while restoring caller grants.
    runner = db.execute('select current_user').fetchone()[0]
    before_grants = memberships(db)
    db.execute(sql.SQL('grant annual_accounts_filing_workflow_executor to {} with set true granted by {}').format(sql.Identifier(runner), sql.Identifier(runner)))
    identity = ACTORS['owner']
    claims = json.dumps({'sub': identity, 'role': 'authenticated', 'aal': 'aal2', 'amr': [{'method': 'totp', 'timestamp': int(db.execute('select extract(epoch from transaction_timestamp())').fetchone()[0])-1}]})
    for key, value in [('request.jwt.claims', claims), ('talli.verified_actor_id', identity), ('talli.verified_actor_claims', claims)]:
        db.execute('select set_config(%s,%s,true)', (key, value))
    db.execute('set local role annual_accounts_filing_workflow_executor')
    payload = dict(environment='manual_evidence', status='pending', test_reference='latest-after-cutover', feedback_summary='Synthetic canonical evidence', receipt_reference=None, archive_reference=None, evidence_url=None, payload_hash=None)
    latest = db.execute('select annual_accounts_filing.record_test_evidence_v1(%s,%s::jsonb,%s)', (COMPANY, json.dumps(payload), identity)).fetchone()[0]
    db.execute('select annual_accounts_filing.acknowledge_review_comment_v1(%s,%s)', (IDS['filing_review_comments'], identity))
    db.execute('reset role')
    db.execute(sql.SQL('revoke annual_accounts_filing_workflow_executor from {} granted by {}').format(sql.Identifier(runner), sql.Identifier(runner)))
    assert memberships(db) == before_grants
    changed = environment(db)
    assert changed['archive'] != before['archive']
    assert changed['audit'] == before['audit']
    apply(db, CONTRACT)
    assert all(db.execute('select to_regclass(%s) is null', ('public.' + f,)).fetchone()[0] for f in FAMILIES)
    assert environment(db) == changed
    with actor(db, role='company_tax_filing_workflow_executor') as identity:
        tax = db.execute('select company_tax_filing.read_source_snapshot_v1(%s,2025,%s)', (COMPANY, identity)).fetchone()[0]
        assert tax['coverage']['legacyFencesValid'] is True
    apply(db, CONTRACT, rollback=True)
    assert all(value == [] for value in rows(db, 'public').values())
    assert db.execute('select phase from backend_system.annual_accounts_migration_state').fetchone()[0] == 'cutover'
    apply(db, CUTOVER, rollback=True)
    assert environment(db) == changed
    restored = rows(db, 'public')
    assert latest in restored['authority_test_runs']
    assert next(r for r in restored['filing_review_comments'] if r['id'] == IDS['filing_review_comments'])['acknowledged_by'] == ACTORS['owner']
    with actor(db) as identity:
        expect_error(db, 'annual_accounts_unavailable', lambda: db.execute('select annual_accounts_filing.read_workspace_v1(%s,2025,%s)', (COMPANY, identity)))
    apply(db, CUTOVER)
    with actor(db, role='annual_accounts_filing_store_owner'):
        assert rows(db, 'annual_accounts_filing') == restored
    apply(db, CONTRACT)
    assert environment(db) == changed


@pytest.mark.parametrize('mutation,message', [
    ("insert into public.filing_previews(company_id,income_year,filing,status,preview,created_by) values('15300000-0000-4000-8000-000000000001',2025,'unclassified','ready','Synthetic unknown','15300000-0000-4000-8000-000000000010')", 'annual_accounts_cutover_quarantine'),
    ('alter table public.filing_previews add column unexpected_accounts_probe text', 'annual_accounts_source_schema_changed'),
    ('alter table public.filing_previews disable trigger company_archive_track_filing_previews', 'annual_accounts_source_schema_changed'),
])
def test_cutover_rejects_source_drift_without_mutation(database, mutation, message):
    db = database
    db.execute(mutation)
    before = rows(db, 'public')
    state = environment(db)
    expect_error(db, message, lambda: apply(db, CUTOVER))
    assert rows(db, 'public') == before
    assert environment(db) == state
    assert db.execute('select phase from backend_system.annual_accounts_migration_state').fetchone()[0] == 'expanded'


def test_contract_preserves_first_index_inventory(database):
    db = database
    apply(db, CUTOVER)
    apply(db, CONTRACT)
    apply(db, CONTRACT, rollback=True)
    original = db.execute("select resource,definition,definition_sha256 from backend_system.annual_accounts_migration_inventory where resource like 'contract-indexes:%' order by resource").fetchall()
    db.execute('create index accounts_probe_changed_index on public.authority_permissions(company_id)')
    expect_error(db, 'annual_accounts_contract_index_inventory_changed', lambda: apply(db, CONTRACT))
    assert db.execute("select resource,definition,definition_sha256 from backend_system.annual_accounts_migration_inventory where resource like 'contract-indexes:%' order by resource").fetchall() == original


@pytest.mark.parametrize('phase', ['expanded', 'cutover', 'contracted'])
def test_real_authorization_and_phase_contracts(database, phase):
    db = database
    if phase != 'expanded':
        apply(db, CUTOVER)
    if phase == 'contracted':
        apply(db, CONTRACT)
    for name in ACTORS:
        with actor(db, name) as identity:
            def read_source():
                return db.execute('select annual_accounts_filing.read_source_snapshot_v1(%s,2025,%s)', (COMPANY, identity)).fetchone()[0]
            if name not in ('owner', 'second'):
                expect_error(db, 'annual_accounts_not_found', read_source)
            elif phase == 'expanded':
                expect_error(db, 'annual_accounts_unavailable', read_source)
            else:
                result = read_source()
                assert all(result['coverage'][flag] is True for flag in (
                    'inventoryValid', 'quarantineClear', 'sourceRowsValid', 'legacyFencesValid', 'modeChecksValid', 'declaredExtentValid'))
                expect_error(db, 'annual_accounts_forbidden', lambda: db.execute(
                    'select annual_accounts_filing.read_source_snapshot_v1(%s,2025,%s)', (COMPANY, ACTORS['outsider'])))
    for name in ACTORS:
        with actor(db, name) as identity:
            def read():
                return db.execute('select annual_accounts_filing.read_workspace_v1(%s,2025,%s)', (COMPANY, identity)).fetchone()[0]
            if name in ('unaccepted', 'outsider'):
                expect_error(db, 'annual_accounts_not_found', read)
            elif phase == 'expanded':
                expect_error(db, 'annual_accounts_unavailable', read)
            else:
                assert len(read()['previews']) == 1
    for role in ('anon', 'authenticated', 'service_role'):
        functions = db.execute("select p.oid from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='annual_accounts_filing'").fetchall()
        assert functions
        assert all(not db.execute("select has_function_privilege(%s,%s,'EXECUTE')", (role, oid)).fetchone()[0] for (oid,) in functions)
    for fresh, aal in [(False, 'aal2'), (True, 'aal1')]:
        with actor(db, fresh=fresh, aal=aal) as identity:
            expect_error(db, 'annual_accounts_unavailable' if phase == 'expanded' else 'annual_accounts_mfa_required',
                         lambda: db.execute('select annual_accounts_filing.confirm_filing_permission_v1(%s,false,%s)', (COMPANY, identity)))


@pytest.mark.parametrize('mutation,flag,owned', [
    ('alter table public.filing_submissions drop constraint accounts153_legacy_writer_retired', 'legacyFencesValid', False),
    ('alter table annual_accounts_filing.filing_submissions drop constraint filing_submissions_mode_check', 'modeChecksValid', True),
    ('create table annual_accounts_filing.uncovered_source_probe(id integer)', 'declaredExtentValid', True),
    ("update backend_system.annual_accounts_migration_inventory set definition_sha256=repeat('0',64)", 'inventoryValid', True),
    ("update backend_system.annual_accounts_source_rows set source_sha256=repeat('0',64) where ctid=(select ctid from backend_system.annual_accounts_source_rows order by family,source_id,source_sha256 limit 1)", 'sourceRowsValid', True),
])
def test_source_history_detects_real_database_coverage_drift(database, mutation, flag, owned):
    db = database
    apply(db, CUTOVER)
    runner = db.execute('select current_user').fetchone()[0]
    if owned:
        db.execute(sql.SQL('grant annual_accounts_filing_store_owner to {} with set true granted by {}').format(sql.Identifier(runner), sql.Identifier(runner)))
        db.execute('set local role annual_accounts_filing_store_owner')
    db.execute(mutation)
    db.execute('reset role')
    with actor(db) as identity:
        result = db.execute('select annual_accounts_filing.read_source_snapshot_v1(%s,2025,%s)', (COMPANY, identity)).fetchone()[0]
        assert result['coverage'][flag] is False
        from test_annual_accounts_source_facts import parse
        from talli_backend.modules.annual_accounts_filing.public import project_annual_accounts_source
        query, snapshot = parse(result)
        assert project_annual_accounts_source(query, snapshot).history_coverage.status == 'incomplete'


@pytest.mark.parametrize('mutation', [
    'alter table annual_accounts_filing.filing_previews no force row level security',
    'alter table annual_accounts_filing.filing_previews disable row level security',
    'create policy accounts_probe_unscoped on annual_accounts_filing.filing_previews for select to annual_accounts_filing_store_owner using(true)',
    'alter table annual_accounts_filing.filing_submissions drop constraint filing_submissions_mode_check',
    'grant select on annual_accounts_filing.filing_previews to authenticated',
])
def test_cutover_rejects_target_protection_drift(database, mutation):
    db = database
    runner = db.execute('select current_user').fetchone()[0]
    db.execute(sql.SQL('grant annual_accounts_filing_store_owner to {} with set true granted by {}').format(sql.Identifier(runner), sql.Identifier(runner)))
    db.execute('set local role annual_accounts_filing_store_owner')
    db.execute(mutation)
    db.execute('reset role')
    before = rows(db, 'public')
    expect_error(db, 'annual_accounts_target_schema_changed', lambda: apply(db, CUTOVER))
    assert rows(db, 'public') == before
    assert db.execute('select phase from backend_system.annual_accounts_migration_state').fetchone()[0] == 'expanded'


@pytest.mark.parametrize('mutation', [
    'alter table public.filing_previews disable row level security',
    'alter table public.filing_previews disable trigger company_archive_track_filing_previews',
])
def test_full_rollback_rejects_changed_source_protections(database, mutation):
    db = database
    apply(db, CUTOVER)
    db.execute(mutation)
    before = environment(db)
    expect_error(db, 'annual_accounts_rollback_source_schema_changed', lambda: apply(db, CUTOVER, rollback=True))
    assert environment(db) == before
    assert all(value == [] for value in rows(db, 'public').values())
    assert db.execute('select phase from backend_system.annual_accounts_migration_state').fetchone()[0] == 'cutover'


def test_cutover_rejects_inactive_rows_without_preserved_provenance(database):
    db = database
    runner = db.execute('select current_user').fetchone()[0]
    db.execute(sql.SQL('grant annual_accounts_filing_store_owner to {} with set true granted by {}').format(sql.Identifier(runner), sql.Identifier(runner)))
    db.execute('set local role annual_accounts_filing_store_owner')
    db.execute('create policy accounts_fixture_insert on annual_accounts_filing.authority_test_runs for insert to annual_accounts_filing_store_owner with check(true)')
    db.execute("insert into annual_accounts_filing.authority_test_runs(id,company_id,obligation,status,test_reference,recorded_by) values('15300000-0000-4000-8000-000000000099',%s,'aarsregnskap','pending','Untraceable synthetic row',%s)", (COMPANY, ACTORS['owner']))
    db.execute('drop policy accounts_fixture_insert on annual_accounts_filing.authority_test_runs')
    db.execute('reset role')
    before = rows(db, 'public')
    expect_error(db, 'annual_accounts_unproven_target_rows', lambda: apply(db, CUTOVER))
    assert rows(db, 'public') == before


def test_documents_retention_uses_owned_receipt_and_feedback_references(database):
    db = database
    receipt = '15300000-0000-4000-8000-000000000101'
    feedback = '15300000-0000-4000-8000-000000000102'
    unrelated = '15300000-0000-4000-8000-000000000103'
    # Existing official-reference rows move intact; no new submission writer is
    # introduced just to manufacture a receipt for this retention check.
    changed = db.execute('update public.filing_submissions set receipt_id=%s,feedback_document_ids=%s::jsonb where id=%s', (receipt, json.dumps([feedback]), IDS['filing_submissions']))
    assert changed.rowcount == 1
    apply(db, CUTOVER)
    apply(db, CONTRACT)
    with actor(db, 'outsider', role='documents_executor'):
        for name in ('request.jwt.claims', 'talli.verified_actor_claims'):
            db.execute("select set_config(%s,'{}',true)", (name,))
        assert db.execute('select documents.has_evidence_references_v1(%s)', (receipt,)).fetchone()[0] is True
        assert db.execute('select documents.has_evidence_references_v1(%s)', (feedback,)).fetchone()[0] is True
        assert db.execute('select documents.has_evidence_references_v1(%s)', (unrelated,)).fetchone()[0] is False
