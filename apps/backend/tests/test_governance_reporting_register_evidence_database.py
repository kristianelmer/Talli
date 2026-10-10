"""Real restricted reporting/append serialization; local collection is not proof.

Positive data uses released RF, Documents, Ledger and Governance writers through
the shared owned fixture. Privileged corruption is explicit and rolled back.
No external byte store, provider, HTTP or RF-consumer activation is exercised.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from queue import Queue
from types import SimpleNamespace

import psycopg
from psycopg import sql
import pytest

from talli_backend.adapters.postgres_corporate_reporting_evidence import PostgresCorporateReportingEvidence
from talli_backend.adapters.supabase_corporate_governance import SupabaseCorporateGovernanceSession
from talli_backend.modules.corporate_governance import public as gov
from talli_backend.shared.kernel import CompanyId, IncomeYear
from governance_register_evidence_amendment_fixture import (
    admitted, amendment_fixture_authority, withdrawal_fixture_role, connection, verified, DATABASE_URL, ROOT,
)
from test_governance_register_evidence_amendment_database import (
    prepare_fixture, save, append, successor, reverse_original, immutable_inputs, count,
    corrupt_amendment, wait_for_company_lock,
)

pytestmark = pytest.mark.authority_database
ROLE = 'corporate_governance_workflow_executor'
SIGNATURE = 'corporate_governance.read_guarded_reporting_register_evidence_v1(uuid,integer,text)'
MIGRATION = '20261010005413_governance_reporting_register_evidence.sql'
UNSET = object()


@pytest.fixture
def ready(admitted, amendment_fixture_authority, withdrawal_fixture_role):
    return prepare_fixture(admitted, ROLE, withdrawal_fixture_role)


def guard(db, item, *, raw=False):
    if raw:
        # Negative reader tests deliberately establish only the required lock;
        # they must still fail the reader's own isolation/identity checks.
        db.execute('select pg_advisory_xact_lock(hashtextextended(%s::text,157))', (str(item['seed']['company']),))
    else:
        db.execute('select corporate_governance.acquire_company_write_guard_v1(%s,%s)',
            (item['seed']['company'], str(item['seed']['owner'])))


def projection(db, item, *, year=2026, subject=UNSET, company=None):
    return db.execute('select corporate_governance.read_guarded_reporting_register_evidence_v1(%s,%s,%s)',
        (company or item['seed']['company'], year,
         str(item['seed']['owner']) if subject is UNSET else subject)).fetchone()[0]


def read(item, *, year=2026, actor=None):
    with connection(item['seed'], ROLE, actor=actor, fresh=False) as db:
        guard(db, item)
        return projection(db, item, year=year, subject=str(actor) if actor else UNSET)


def adapter(item, *, same_connection=False, year=2026):
    async def run():
        identity = verified(item['seed'], fresh=False)
        q = gov.CorporateReportingRegisterEvidenceQuery(CompanyId(str(item['seed']['company'])), IncomeYear(year), identity.actor_id)
        session = SupabaseCorporateGovernanceSession(DATABASE_URL, identity)
        async with session.transaction(guarded_company_id=q.company_id) as tx:
            reader = PostgresCorporateReportingEvidence(tx._connection, identity.actor_id) if same_connection else tx
            return await reader.read_reporting_year_register_evidence(q)
    return asyncio.run(run())


@pytest.mark.parametrize('kind,phase', [('loss_coverage_capital_reduction','first_recognized_after_registration'),
    ('loss_coverage_capital_reduction','registered'), ('cash_capital_increase','registered')])
def test_real_released_originals_have_complete_zero_one_two_amendment_history(admitted, amendment_fixture_authority, withdrawal_fixture_role, kind, phase):
    item = prepare_fixture(admitted, ROLE, withdrawal_fixture_role, kind=kind, phase=phase)
    original = adapter(item); before = immutable_inputs(item)
    assert original.chain_count == 1 and original.register_chains[0].amendment_count == 0
    assert adapter(item, same_connection=True) == original
    assert immutable_inputs(item) == before
    first = gov.parse_corporate_register_evidence_amendment(save(item))
    one = adapter(item, same_connection=True)
    assert one.original == original.original and one.register_chains[0].chain.amendments == (first,)
    # Shared successor helper's four-original convention is specific to loss;
    # cash already proves its distinct required document union in persistence.
    if kind == 'loss_coverage_capital_reduction':
        later = successor(item, first)
        second = gov.parse_corporate_register_evidence_amendment(save(later))
        two = adapter(item)
        assert two.original == original.original and two.register_chains[0].chain.amendments == (first,second)
        assert two.register_chains[0].chain.effective_register_fact == second.command.replacement
    assert immutable_inputs(item)['corporate_governance.supported_events'] == before['corporate_governance.supported_events']
    assert one.enumeration_sha256 != original.enumeration_sha256


def test_complete_company_scope_keeps_off_year_original_and_matches_untouched_old_inputs(ready):
    with connection(ready['seed'], 'corporate_governance_store_owner', fresh=False) as db:
        guard(db, ready)
        old = db.execute('select corporate_governance.read_guarded_reporting_year_inputs_v1(%s,%s,%s)',
            (ready['seed']['company'], 2025, str(ready['seed']['owner']))).fetchone()[0]
        result = projection(db, ready, year=2025)
    assert result['reporting_inputs'] == old and result['chain_count'] == 1
    assert result['register_chains'][0]['income_year'] == 2026
    assert not adapter(ready, year=2025).original.supported_events


def test_real_ledger_reversal_preserves_register_chain_and_released_status(ready):
    receipt = gov.parse_corporate_register_evidence_amendment(save(ready))
    reverse_original(ready)
    result = adapter(ready)
    assert result.original.supported_events[0].status == 'reversed'
    assert result.register_chains[0].chain.amendments == (receipt,)
    assert result.register_chains[0].chain.anchor.original == ready['original']


def test_empty_company_is_explicitly_empty_not_missing_projection(admitted, amendment_fixture_authority):
    item = {'seed':admitted}
    value = read(item)
    assert value['chain_count'] == 0 and value['register_chains'] == []
    assert adapter(item).chain_count == 0


def test_another_accepted_company_is_empty_and_never_discloses_original_chain(ready):
    save(ready)
    # Seed another owned fixture scope, then explicitly accept the current actor
    # there. A successful empty read must not accidentally reuse its first scope.
    other = admitted.__wrapped__(SimpleNamespace())
    with psycopg.connect(DATABASE_URL) as db:
        db.execute("insert into public.company_memberships(company_id,user_id,role,accepted_at) values(%s,%s,'owner',clock_timestamp())",
            (other['company'], ready['seed']['owner']))
    scoped = {'seed':other | {'owner':ready['seed']['owner']}}
    value = read(scoped)
    assert value['company_id'] == str(other['company']) and value['chain_count'] == 0
    assert value['register_chains'] == [] and value['reporting_inputs']['supportedEvents'] == []
    assert read(ready)['chain_count'] == 1


@pytest.mark.parametrize('isolation', ['repeatable read','serializable'])
def test_reader_rejects_non_read_committed_even_with_company_guard(ready, isolation):
    with connection(ready['seed'], ROLE, isolation=isolation) as db:
        guard(db, ready, raw=True)
        with pytest.raises(psycopg.Error, match='reporting_guard_required'): projection(db, ready)


def test_reader_requires_existing_guard_does_not_silently_acquire_it(ready):
    with connection(ready['seed'], ROLE) as db:
        with pytest.raises(psycopg.Error, match='reporting_guard_required'): projection(db, ready)


@pytest.mark.parametrize('identity', ['outsider','wrong_subject','missing_subject','revoked'])
def test_verified_subject_and_live_accepted_owner_are_required(ready, identity):
    with connection(ready['seed'], ROLE, actor=ready['seed']['outsider'] if identity == 'outsider' else None) as db:
        guard(db, ready, raw=True)
        if identity == 'revoked':
            # Privileged mutation in this one transaction only; restore by rollback.
            db.execute('reset role')
            db.execute("update public.company_memberships set role='read_only' where company_id=%s", (ready['seed']['company'],))
            db.execute('set local role corporate_governance_workflow_executor')
        subject = None if identity == 'missing_subject' else str(ready['seed']['outsider']) if identity in ('outsider','wrong_subject') else UNSET
        with pytest.raises(psycopg.Error, match='forbidden'): projection(db, ready, subject=subject)
        db.rollback()


@pytest.mark.parametrize('year', [None, 1999, 2101])
def test_invalid_requested_year_fails_closed(ready, year):
    with connection(ready['seed'], ROLE) as db:
        guard(db, ready)
        with pytest.raises(psycopg.Error, match='invalid_input'): projection(db, ready, year=year)


@contextmanager
def corrupt_supported(item, *, missing_anchor=False, off_year=False):
    """Rollback-only historical-row corruption; never a legitimate source writer."""
    with connection(item['seed'], 'corporate_governance_store_owner') as db:
        try:
            db.execute('alter table corporate_governance.supported_events no force row level security')
            db.execute('alter table corporate_governance.supported_events disable trigger supported_events_immutable')
            if missing_anchor:
                db.execute("update corporate_governance.supported_events set shareholder_register_source_id=null,canonical_facts=canonical_facts-'shareholderRegisterFact' where event_id=%s", (item['command'].event_id.value,))
            if off_year:
                db.execute("update corporate_governance.supported_events set income_year=2025,event_date='2025-09-01' where event_id=%s", (item['command'].event_id.value,))
            db.execute('set local role corporate_governance_workflow_executor')
            guard(db, item)
            yield db
        finally: db.rollback()


@pytest.mark.parametrize('off_year', [False, True])
def test_eligible_legacy_original_without_valid_anchor_is_never_skipped(ready, off_year):
    with corrupt_supported(ready, missing_anchor=True, off_year=off_year) as db:
        with pytest.raises(psycopg.Error, match='storage_invalid|evidence_mismatch'): projection(db, ready)


@pytest.mark.parametrize('corruption', ['snapshot_text','anchor_sha256','missing_ancestor'])
def test_complete_reader_rejects_corrupt_or_omitted_committed_history(ready, corruption):
    first = gov.parse_corporate_register_evidence_amendment(save(ready))
    if corruption == 'missing_ancestor':
        save(successor(ready, first))
        context = corrupt_amendment(ready, first.amendment_id.value, delete=True)
    else: context = corrupt_amendment(ready, first.amendment_id.value, **{corruption:'{}' if corruption == 'snapshot_text' else 'f'*64})
    with context as db:
        guard(db, ready)
        with pytest.raises(psycopg.Error, match='storage_invalid'): projection(db, ready)


@pytest.mark.parametrize('commit', [False, True])
def test_append_first_reader_waits_and_observes_only_committed_complete_chain(ready, commit):
    queued = Queue()
    def compete():
        with connection(ready['seed'], ROLE, fresh=False) as db:
            queued.put(db.execute('select pg_backend_pid()').fetchone()[0])
            guard(db, ready)
            return projection(db, ready)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with connection(ready['seed'], ROLE) as db:
            append(db, ready)
            pending = pool.submit(compete); wait_for_company_lock(queued.get(timeout=5))
            assert not pending.done()
            if commit: db.commit()
            else: db.rollback()
        result = pending.result(timeout=10)
    assert result['register_chains'][0]['amendment_count'] == int(commit)
    assert count(ready) == int(commit)


def test_reader_first_blocks_append_until_unchanged_snapshot_finishes(ready):
    queued = Queue()
    def compete():
        with connection(ready['seed'], ROLE) as db:
            queued.put(db.execute('select pg_backend_pid()').fetchone()[0])
            return append(db, ready)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with connection(ready['seed'], ROLE, fresh=False) as db:
            guard(db, ready); before = projection(db, ready)
            pending = pool.submit(compete); wait_for_company_lock(queued.get(timeout=5))
            assert not pending.done() and projection(db, ready) == before
        receipt = gov.parse_corporate_register_evidence_amendment(pending.result(timeout=10))
    assert adapter(ready).register_chains[0].chain.amendments == (receipt,)


def test_revocation_committed_while_waiting_is_seen_despite_stale_role_map(ready):
    queued = Queue()
    def compete():
        with connection(ready['seed'], ROLE, fresh=False) as db:
            queued.put(db.execute('select pg_backend_pid()').fetchone()[0])
            guard(db, ready)
            return projection(db, ready)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('select public.company_archive_lock_company_v1(%s)', (ready['seed']['company'],))
            pending = pool.submit(compete); wait_for_company_lock(queued.get(timeout=5))
            db.execute("update public.company_memberships set role='read_only' where company_id=%s", (ready['seed']['company'],))
        with pytest.raises(psycopg.Error, match='forbidden'): pending.result(timeout=10)


def catalog(db):
    return dict(roles=db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by roleid,member,grantor').fetchall(),
        schemas=db.execute("select oid,nspacl::text from pg_namespace where nspname in ('corporate_governance','ledger','documents','shareholder_register_filing') order by oid").fetchall(),
        functions=db.execute("select oid,to_jsonb(p) from pg_proc p where pronamespace='corporate_governance'::regnamespace order by oid").fetchall(),
        tables=db.execute("select oid,relacl::text,relrowsecurity,relforcerowsecurity from pg_class where relnamespace='corporate_governance'::regnamespace order by oid").fetchall())


def test_only_governance_runtime_gets_new_reader_and_old_rf_contract_stays_unchanged(ready):
    with connection(ready['seed'], 'corporate_governance_store_owner') as db:
        oid = db.execute('select %s::regprocedure::oid', (SIGNATURE,)).fetchone()[0]
        assert db.execute("select has_function_privilege(%s,%s::oid,'EXECUTE')", (ROLE,oid)).fetchone()[0]
        for role in ('anon','authenticated','service_role','shareholder_register_filing_executor','shareholder_register_filing_store_owner','documents_store_owner','ledger_store_owner'):
            assert not db.execute("select has_function_privilege(%s,%s::oid,'EXECUTE')", (role,oid)).fetchone()[0]
        assert not db.execute('select exists(select 1 from pg_proc p cross join lateral aclexplode(p.proacl) a where p.oid=%s and a.grantee=0)', (oid,)).fetchone()[0]
        assert db.execute("select has_function_privilege('shareholder_register_filing_executor','corporate_governance.read_guarded_reporting_year_inputs_v1(uuid,integer,text)','EXECUTE')").fetchone()[0]
    with connection(ready['seed'], 'shareholder_register_filing_executor') as db:
        with pytest.raises(psycopg.errors.InsufficientPrivilege): projection(db, ready)


def test_migration_reapply_and_retentive_rollback_preserve_history_and_other_authority(ready):
    saved = save(ready); before = read(ready)
    with connection(ready['seed'], 'corporate_governance_store_owner') as db: prior = catalog(db)
    try:
        with psycopg.connect(DATABASE_URL, autocommit=True) as db:
            db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text(), prepare=False)
        with connection(ready['seed'], 'corporate_governance_store_owner') as db: assert catalog(db) == prior
        assert read(ready) == before
        with psycopg.connect(DATABASE_URL, autocommit=True) as db:
            db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text(), prepare=False)
        with connection(ready['seed'], 'corporate_governance_store_owner') as db:
            guard(db, ready)
            assert projection(db, ready) == before
            assert not db.execute("select has_function_privilege(%s,%s,'EXECUTE')", (ROLE,SIGNATURE)).fetchone()[0]
        assert save(ready) == saved
    finally:
        with psycopg.connect(DATABASE_URL, autocommit=True) as db:
            db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text(), prepare=False)
    with connection(ready['seed'], 'corporate_governance_store_owner') as db: assert catalog(db) == prior
