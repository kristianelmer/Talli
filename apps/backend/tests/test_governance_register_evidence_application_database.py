"""Restricted prepare/application contracts on the owned disposable database.

Collection is not runtime evidence. Fixtures use actual released owner writers;
no external byte/provider IO is performed by this database suite.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from queue import Queue
import time
from uuid import uuid4

import psycopg
import pytest

from talli_backend.adapters.supabase_corporate_governance import SupabaseCorporateGovernanceSession
from talli_backend.modules.corporate_governance import public as gov
from talli_backend.shared.kernel import IdempotencyKey, IncomeYear
from governance_register_evidence_amendment_fixture import (
    admitted, amendment_fixture_authority, withdrawal_fixture_role, connection, verified, withdrawal, DATABASE_URL, ROOT,
)
from test_annual_purchase_basis_runtime import insert
from test_governance_register_evidence_amendment_database import (
    prepare_fixture, count, immutable_inputs, reverse_original, wait_for_company_lock, APPEND, CHAIN, LOOKUP, TABLE,
)

pytestmark = pytest.mark.authority_database
ROLE = 'corporate_governance_workflow_executor'
MIGRATION = '20261010001936_governance_register_evidence_application.sql'
PREPARE = 'corporate_governance.prepare_register_evidence_amendment_v1(text,text,text)'


@pytest.fixture
def ready(admitted, amendment_fixture_authority, withdrawal_fixture_role):
    return prepare_fixture(admitted, ROLE, withdrawal_fixture_role)


def block_admission(db, item):
    """Privileged test-only successor assessment, rolled back by each caller."""
    db.execute('reset role')
    now = db.execute('select clock_timestamp()').fetchone()[0]
    insert(db, 'public.company_eligibility_assessments', item['seed']['assessment'] | {
        'id': uuid4(), 'operation_id': uuid4(), 'previous_assessment_id': item['seed']['current'],
        'trigger': 'before_filing', 'decision': 'blocked', 'consequential_operations_allowed': False,
        'assessed_at': now,
    })
    db.execute('set local role corporate_governance_workflow_executor')


def prepare(db, item, *, raw=None, key=None, subject=None):
    command = item['amendment_command']
    return db.execute('select corporate_governance.prepare_register_evidence_amendment_v1(%s,%s,%s)',
        (raw if raw is not None else gov.serialize_corporate_register_evidence_amendment_command(command),
         key or item['key'], subject or str(command.actor_id.subject))).fetchone()[0]


def query(item):
    cmd = item['amendment_command']
    return gov.CorporateRegisterEvidenceQuery(cmd.company_id, cmd.income_year, cmd.actor_id, cmd.event_id)


def adapter(item, operation, *, fresh=True):
    async def run():
        session = SupabaseCorporateGovernanceSession(DATABASE_URL, verified(item['seed'], fresh=fresh))
        async with session.transaction(guarded_company_id=item['amendment_command'].company_id) as tx:
            if operation == 'prepare':
                return await tx.prepare_register_evidence_amendment(item['amendment_command'], idempotency_key=IdempotencyKey(item['key']))
            if operation == 'append':
                return await tx.append_register_evidence_amendment(item['amendment_command'], originals=item['originals'], idempotency_key=IdempotencyKey(item['key']))
            if operation == 'lookup':
                return await tx.lookup_register_evidence_amendment(query(item), idempotency_key=IdempotencyKey(item['key']),
                    request_sha256=gov.corporate_register_evidence_amendment_request_digest(item['amendment_command']))
            return await tx.read_register_evidence_chain(query(item))
    return asyncio.run(run())


@pytest.mark.parametrize('kind,phase', [('loss_coverage_capital_reduction','first_recognized_after_registration'),
    ('loss_coverage_capital_reduction','registered'), ('cash_capital_increase','registered')])
def test_actual_workflow_executor_adapter_roundtrip_preserves_originals(admitted, amendment_fixture_authority, withdrawal_fixture_role, kind, phase):
    item = prepare_fixture(admitted, ROLE, withdrawal_fixture_role, kind=kind, phase=phase)
    before = immutable_inputs(item)
    prepared = adapter(item, 'prepare')
    assert prepared.status == 'ready' and prepared.snapshot.chain.anchor == item['anchor'] and count(item) == 0
    recorded = adapter(item, 'append')
    assert gov.serialize_corporate_register_evidence_amendment(recorded)
    assert recorded.command == item['amendment_command']
    assert adapter(item, 'prepare').receipt == recorded
    assert adapter(item, 'lookup').receipt == recorded
    assert adapter(item, 'chain').chain.amendments == (recorded,)
    assert immutable_inputs(item) == before and count(item) == 1


@pytest.mark.parametrize('mutation', ['mfa', 'withdrawal', 'reversal', 'admission'])
def test_committed_prepare_recovers_before_mutable_admission_or_owner_evidence(ready, mutation):
    recorded = adapter(ready, 'append')
    if mutation == 'withdrawal': withdrawal(ready['seed'], ready['withdrawal_role'], ready['replacement'])
    if mutation == 'reversal': reverse_original(ready)
    if mutation == 'admission':
        # Explicit rollback-only admission fixture; no immutable history removed.
        with connection(ready['seed'], ROLE, fresh=False) as db:
            block_admission(db, ready)
            result = prepare(db, ready)
            assert result == {'status':'recorded','receipt_text':gov.serialize_corporate_register_evidence_amendment(recorded)}
            db.rollback()
    else:
        result = adapter(ready, 'prepare', fresh=False)
        assert result.status == 'recorded' and result.receipt == recorded
    assert count(ready) == 1


@pytest.mark.parametrize('invalid', ['expired', 'no_amr', 'aal1', 'wrong_subject', 'not_admitted'])
def test_fresh_prepare_requires_actual_mfa_subject_and_admitted_owner(ready, invalid):
    with connection(ready['seed'], ROLE, fresh=invalid != 'expired') as db:
        if invalid in ('no_amr', 'aal1'):
            now = db.execute('select extract(epoch from clock_timestamp())').fetchone()[0]
            claims = dict(sub=str(ready['seed']['owner']), role='authenticated', aal='aal1' if invalid == 'aal1' else 'aal2',
                amr=[] if invalid == 'no_amr' else [dict(method='totp',timestamp=float(now)-1)])
            db.execute("select set_config('talli.verified_actor_claims',%s,true),set_config('request.jwt.claims',%s,true)", (json.dumps(claims),json.dumps(claims)))
        if invalid == 'not_admitted':
            block_admission(db, ready)
        with pytest.raises(psycopg.Error, match='fresh_mfa_required|forbidden|company_year_not_admitted'):
            prepare(db, ready, subject=str(ready['seed']['outsider']) if invalid == 'wrong_subject' else None)
        db.rollback()
    assert count(ready) == 0


@pytest.mark.parametrize('change', ['reason', 'head', 'actor', 'year'])
def test_prepare_conflicting_committed_request_never_returns_ready(ready, change):
    adapter(ready, 'append')
    command = ready['amendment_command']
    if change == 'reason': command = replace(command, reason='Different exact request')
    elif change == 'head': command = replace(command, expected_anchor_sha256='f'*64)
    elif change == 'year': command = replace(command, income_year=IncomeYear(2025))
    else: command = replace(command, actor_id=replace(command.actor_id, subject=type(command.actor_id.subject)(str(ready['seed']['outsider']))))
    with connection(ready['seed'], ROLE, fresh=False) as db:
        with pytest.raises(psycopg.Error, match='replay_conflict|forbidden'):
            prepare(db, ready, raw=gov.serialize_corporate_register_evidence_amendment_command(command))
    assert count(ready) == 1


@pytest.mark.parametrize('change', ['mfa', 'withdrawal', 'reversal', 'revocation'])
def test_prepare_ready_does_not_lease_final_admission(ready, change):
    assert adapter(ready, 'prepare').status == 'ready'
    if change == 'withdrawal': withdrawal(ready['seed'], ready['withdrawal_role'], ready['replacement'])
    elif change == 'reversal': reverse_original(ready)
    elif change == 'revocation':
        with psycopg.connect(DATABASE_URL) as db:
            db.execute("update public.company_memberships set role='read_only' where company_id=%s", (ready['seed']['company'],))
    with pytest.raises(gov.CorporateGovernanceError): adapter(ready, 'append', fresh=change != 'mfa')
    # Owner revocation intentionally prevents a post-failure scoped count read.
    if change != 'revocation': assert count(ready) == 0


@pytest.mark.parametrize('revoke', [False, True])
def test_prepare_rechecks_public_clock_mfa_and_owner_after_company_lock_wait(ready, revoke):
    queued = Queue()
    def compete():
        with connection(ready['seed'], ROLE) as db:
            now = float(db.execute('select extract(epoch from clock_timestamp())').fetchone()[0])
            claims = dict(sub=str(ready['seed']['owner']),role='authenticated',aal='aal2',amr=[dict(method='totp',timestamp=now-898)])
            db.execute("select set_config('talli.verified_actor_claims',%s,true),set_config('request.jwt.claims',%s,true)", (json.dumps(claims),json.dumps(claims)))
            queued.put((db.execute('select pg_backend_pid()').fetchone()[0],now+2))
            return prepare(db, ready)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('select public.company_archive_lock_company_v1(%s)', (ready['seed']['company'],))
            pending = pool.submit(compete); pid, expiry = queued.get(timeout=5); wait_for_company_lock(pid)
            if revoke:
                db.execute("update public.company_memberships set role='read_only' where company_id=%s", (ready['seed']['company'],))
            else:
                while float(db.execute('select extract(epoch from clock_timestamp())').fetchone()[0]) <= expiry+.05: time.sleep(.02)
            assert not pending.done()
        with pytest.raises(psycopg.Error, match='forbidden' if revoke else 'fresh_mfa_required'): pending.result(timeout=10)


def test_only_four_governance_contracts_are_granted_without_foreign_or_table_access(ready):
    with connection(ready['seed'], 'corporate_governance_store_owner') as db:
        contracts = (PREPARE,APPEND,CHAIN,LOOKUP)
        for signature in contracts:
            oid = db.execute('select %s::regprocedure::oid', (signature,)).fetchone()[0]
            assert db.execute("select has_function_privilege(%s,%s::oid,'EXECUTE')", (ROLE,oid)).fetchone()[0]
            for other in ('anon','authenticated','service_role','shareholder_register_filing_store_owner','documents_store_owner','ledger_store_owner'):
                assert not db.execute("select has_function_privilege(%s,%s::oid,'EXECUTE')", (other,oid)).fetchone()[0]
            assert not db.execute('select exists(select 1 from pg_proc p cross join lateral aclexplode(p.proacl) a where p.oid=%s and a.grantee=0)', (oid,)).fetchone()[0]
        assert not db.execute("select has_table_privilege(%s,%s,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')", (ROLE,TABLE)).fetchone()[0]
        helpers = db.execute("select oid from pg_proc where pronamespace='corporate_governance'::regnamespace and proname like 'register_evidence_%_internal_v1'").fetchall()
        assert helpers
        assert all(not db.execute("select has_function_privilege(%s,%s::oid,'EXECUTE')", (ROLE,row[0])).fetchone()[0] for row in helpers)
        # Catalog OIDs avoid requiring foreign schema USAGE merely to inspect ACLs.
        foreign = db.execute("select p.oid from pg_proc p join pg_namespace n on n.oid=p.pronamespace where (n.nspname,p.proname) in (('ledger','assert_unamended_governance_entry_v1'),('documents','assert_historical_original_integrity_v1'),('shareholder_register_filing','read_current_register_observation_evidence_v1'))").fetchall()
        assert len(foreign) == 3
        assert all(not db.execute("select has_function_privilege(%s,%s::oid,'EXECUTE')", (ROLE,row[0])).fetchone()[0] for row in foreign)


def test_application_suffix_reapply_and_rollback_preserve_receipts_and_restore_only_its_grants(ready):
    receipt = adapter(ready, 'append')
    def functions(db):
        db.execute('set local role corporate_governance_store_owner')
        return db.execute("select oid,to_jsonb(p) from pg_proc p where pronamespace='corporate_governance'::regnamespace order by oid").fetchall()
    try:
        with psycopg.connect(DATABASE_URL) as db:
            before = functions(db); db.execute('reset role')
            members = db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall()
            db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
            assert functions(db) == before
            db.execute('reset role')
            db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
            closed = functions(db)
            assert [(oid,{k:v for k,v in row.items() if k != 'proacl'}) for oid,row in closed] == [
                (oid,{k:v for k,v in row.items() if k != 'proacl'}) for oid,row in before]
            for signature in (PREPARE,APPEND,CHAIN,LOOKUP):
                assert not db.execute("select has_function_privilege(%s,%s,'EXECUTE')", (ROLE,signature)).fetchone()[0]
            assert db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall() == members
        with connection(ready['seed'], 'corporate_governance_store_owner') as db:
            retained = db.execute('select corporate_governance.read_register_evidence_chain_v1(%s,%s,%s,%s)',
                (str(ready['command'].company_id),int(ready['command'].income_year),str(ready['command'].event_id),str(ready['seed']['owner']))).fetchone()[0]
            assert retained['amendments'] == [gov.serialize_corporate_register_evidence_amendment(receipt)]
    finally:
        # Restore the installed suffix even if a deliberate rollback assertion fails.
        with psycopg.connect(DATABASE_URL) as db:
            db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
    assert adapter(ready, 'prepare').receipt == receipt
    assert adapter(ready, 'lookup').receipt == receipt
