"""Final Governance SQL consumes RF public identity/time proof on the owned DB.

These cases exercise actual restricted routines, not original-byte or economics
validation. The RF observation fixture and frozen Governance facts are independent.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
import hashlib
import json
from queue import Queue
from types import SimpleNamespace
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
import pytest

from talli_backend.adapters.supabase_corporate_governance import _supported_event_request
from talli_backend.modules.corporate_governance import public as gov
from talli_backend.modules.corporate_governance.service import CorporateGovernanceService
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId, IdempotencyKey
from test_corporate_governance_supported_events import command, capital_facts, reduction_facts, document, bank
from test_corporate_reporting_year_database_runtime import add_entry
from test_governance_ledger_company_guard_database import disposable_guard_role_access
from test_rf1086_register_observation_withdrawal_database import (
    staged, connection, observed, withdraw, append, old_correction, wait_for_lock,
    admitted, backend_url, cleanup_owned_fixture, rf_fixture_admin_access, DATABASE_URL, ROOT,
)

pytestmark = pytest.mark.authority_database
# The frozen completion body is installed by the full predecessor chain. Its
# exact drift sentinel must not be replayed over the repaired successor.
MIGRATION = '20261010032531_governance_supported_event_replay_visibility.sql'
ROLE = 'corporate_governance_workflow_executor'
V2 = 'shareholder_register_filing.assert_current_register_observation_v2(uuid,uuid,integer,integer,text,timestamptz,text)'


@pytest.fixture
def completion(staged, disposable_guard_role_access):
    with psycopg.connect(DATABASE_URL) as db:
        db.execute((ROOT / 'supabase/migrations' / MIGRATION).read_text())
    try:
        yield staged
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('set local role corporate_governance_store_owner')
            db.execute('alter table corporate_governance.supported_events disable trigger supported_events_immutable')
            db.execute('alter table corporate_governance.supported_events no force row level security')
            db.execute('delete from corporate_governance.supported_events where company_id=%s', (staged['seed']['company'],))
            db.execute('alter table corporate_governance.supported_events force row level security')
            db.execute('alter table corporate_governance.supported_events enable trigger supported_events_immutable')
            db.execute('set local role ledger_store_owner')
            db.execute('alter table ledger.entries no force row level security')
            db.execute('delete from ledger.entries where company_id=%s', (staged['seed']['company'],))
            db.execute('alter table ledger.entries force row level security')


def request_for(fixture, observation, *, kind='loss_coverage_capital_reduction', phase='registered', entry=None):
    reference = None if observation is None else gov.SupportedCorporateSourceFact(
        gov.CorporateSourceReference(observation.observation_id.value), observation.version, observation.fact_sha256)
    evidence = gov.SupportedCorporateEvidenceKind
    docs = (document(evidence.SIGNED_DECISION, 1), document(evidence.AMENDED_ARTICLES, 2),
            document(evidence.REGISTRATION_RECEIPT, 3))
    cash = kind == 'cash_capital_increase'
    if cash:
        docs += (document(evidence.CONTRIBUTION_CONFIRMATION, 4),)
    if phase == 'binding_subscription':
        docs = (docs[0],)
    cmd = replace(command(kind=gov.SupportedCorporateEventKind(kind), phase=gov.SupportedCorporateEventPhase(phase),
        facts=capital_facts() if cash else reduction_facts(), documents=docs,
        bank_fact=bank('15000.00') if cash and phase == 'registered' else None,
        shareholder_register_fact=reference), company_id=fixture['command'].company_id,
        actor_id=fixture['store'].actor_id, event_id=gov.SupportedCorporateEventId(str(uuid4())),
        event_reference=gov.SupportedCorporateEventReference(str(uuid4())), idempotency_key=IdempotencyKey(str(uuid4())))
    event = CorporateGovernanceService().prepare_supported_event(cmd)
    if entry is None:
        entry = uuid4()
        with connection(fixture, role='ledger_store_owner') as db:
            db.execute('alter table ledger.entries no force row level security')
            add_entry(db, fixture['seed']['owner'], fixture['seed']['company'], entry)
            db.execute('alter table ledger.entries force row level security')
    request = _supported_event_request(cmd, event, accounting_entry_id=gov.AccountingEntryReference(str(entry)))
    # The direct SQL contract only needs an admitted entry, not Banking evidence;
    # no Banking row is fabricated. Full owner workflow verifies bank provenance.
    request['bankTransactionId'] = None
    return request


def call(db, request, *, prepare=False, subject=None):
    subject = subject or db.execute("select current_setting('talli.verified_actor_id')").fetchone()[0]
    name = 'prepare' if prepare else 'complete'
    return db.execute(sql.SQL('select corporate_governance.{}_supported_event_v1(%s,%s)').format(sql.SQL(name)),
                      (Jsonb(request), subject)).fetchone()[0]


def saved_count(fixture):
    with connection(fixture, role='corporate_governance_store_owner') as db:
        return db.execute('select count(*) from corporate_governance.supported_events where company_id=%s',
                          (fixture['seed']['company'],)).fetchone()[0]


@pytest.mark.parametrize('kind,phase', [
    ('cash_capital_increase', 'registered'), ('loss_coverage_capital_reduction', 'registered'),
    ('loss_coverage_capital_reduction', 'first_recognized_after_registration')])
def test_old_completion_accepts_current_exact_rf_identity_and_records_statement_time(completion, kind, phase):
    original = observed(completion)
    request = request_for(completion, original, kind=kind, phase=phase)
    with connection(completion, role=ROLE) as db:
        # One SQL statement binds the clock even when a transaction began earlier.
        value, timestamp = db.execute('select corporate_governance.complete_supported_event_v1(%s,%s),statement_timestamp()',
            (Jsonb(request), str(completion['store'].actor_id.subject))).fetchone()
        assert datetime.fromisoformat(value['recordedAt']) == timestamp
        assert not value['replayed']
    assert saved_count(completion) == 1


@pytest.mark.parametrize('terminal', ['withdrawn', 'superseded'])
def test_fresh_old_completion_rejects_terminal_observation_without_writing(completion, terminal):
    original = observed(completion)
    request = request_for(completion, original)
    if terminal == 'withdrawn': withdraw(completion, original)
    else:
        with connection(completion) as db: old_correction(db, completion, original)
    with connection(completion, role=ROLE) as db:
        with pytest.raises(psycopg.Error, match='rf1086_register_predecessor_mismatch'): call(db, request)
    assert saved_count(completion) == 0
    independent = request_for(completion, observed(completion))
    with connection(completion, role=ROLE) as db: assert not call(db, independent)['replayed']


@pytest.mark.parametrize('prepare', [False, True])
def test_committed_replay_survives_withdrawal_without_fresh_evidence(completion, prepare):
    original = observed(completion); request = request_for(completion, original)
    with connection(completion, role=ROLE) as db: result = call(db, request)
    withdraw(completion, original)
    with connection(completion, role=ROLE) as db:
        replay = call(db, request, prepare=prepare)
        if prepare: replay = replay['replay']
        assert replay == dict(result, replayed=True)
    assert saved_count(completion) == 1


def test_committed_replay_uses_select_visibility_without_update_authority(completion):
    original = observed(completion)
    request = request_for(completion, original)
    with connection(completion, role=ROLE) as db:
        recorded = call(db, request)
    with connection(completion, role='corporate_governance_store_owner') as db:
        assert db.execute("select relrowsecurity,relforcerowsecurity from pg_class where oid='corporate_governance.supported_events'::regclass").fetchone() == (True, True)
        assert db.execute("select polcmd from pg_policy where polrelid='corporate_governance.supported_events'::regclass order by polcmd").fetchall() == [('a',), ('r',)]
        # The actor can read the immutable row; a row lock applies the absent
        # UPDATE policy and hides it. Completion must use SELECT under its
        # existing company/event advisory guards, without adding UPDATE access.
        assert db.execute('select event_id from corporate_governance.supported_events where event_id=%s', (request['eventId'],)).fetchone() is not None
        assert db.execute('select event_id from corporate_governance.supported_events where event_id=%s for update', (request['eventId'],)).fetchone() is None
    withdraw(completion, original)
    with connection(completion, role=ROLE) as db:
        assert call(db, request) == dict(recorded, replayed=True)



@pytest.mark.parametrize('field', ['companyId','incomeYear','eventId','eventReference','eventDate','eventKind','phase','policyVersion'])
@pytest.mark.parametrize('shape', ['different', 'missing', 'null'])
def test_fresh_completion_rejects_divergent_canonical_identity_before_discriminator(completion, field, shape):
    request = request_for(completion, observed(completion))
    if shape == 'missing': del request['canonicalFacts'][field]
    else: request['canonicalFacts'][field] = None if shape == 'null' else ('owner_loan' if field == 'eventKind' else 'different')
    with connection(completion, role=ROLE) as db:
        with pytest.raises(psycopg.Error, match='corporate_governance_invalid_input'): call(db, request)
    assert saved_count(completion) == 0


@pytest.mark.parametrize('attack', ['absent','null','missing_id','bare_id','upper_hash','bool_revision','float_revision',
    'zero_revision','overflow_revision','missing_hash','extra_key','outer_missing','outer_other','wrong_version','wrong_hash'])
def test_required_frozen_reference_is_strict_and_exact(completion, attack):
    request = request_for(completion, observed(completion)); fact = request['canonicalFacts']['shareholderRegisterFact']
    if attack == 'absent': del request['canonicalFacts']['shareholderRegisterFact']
    elif attack == 'null': request['canonicalFacts']['shareholderRegisterFact'] = None
    elif attack == 'missing_id': del fact['record_id']
    elif attack == 'bare_id': fact['record_id'] = fact['record_id']['value']
    elif attack == 'upper_hash': fact['fact_sha256'] = 'A' * 64
    elif attack == 'bool_revision': fact['revision'] = True
    elif attack == 'float_revision': fact['revision'] = 1.0
    elif attack == 'zero_revision': fact['revision'] = 0
    elif attack == 'overflow_revision': fact['revision'] = 2147483648
    elif attack == 'missing_hash': del fact['fact_sha256']
    elif attack == 'extra_key': fact['extra'] = 'not frozen'
    elif attack == 'outer_missing': del request['shareholderRegisterSourceId']
    elif attack == 'outer_other': request['shareholderRegisterSourceId'] = str(uuid4())
    elif attack == 'wrong_version': fact['revision'] += 1
    elif attack == 'wrong_hash': fact['fact_sha256'] = '0' * 64
    expected = 'rf1086_register_predecessor_mismatch' if attack.startswith('wrong_') else 'corporate_governance_invalid_input'
    with connection(completion, role=ROLE) as db:
        with pytest.raises(psycopg.Error, match=expected): call(db, request)
    assert saved_count(completion) == 0


def test_earlier_cash_phase_without_register_reference_keeps_existing_behavior(completion):
    request = request_for(completion, None, kind='cash_capital_increase', phase='binding_subscription')
    with connection(completion, role=ROLE) as db: assert not call(db, request)['replayed']


@pytest.mark.parametrize('prepare,fields', [(False, ['factsSha256','accountingEntryId']),
    (True, ['incomeYear','eventReference','eventDate','eventKind','phase','factsSha256'])])
@pytest.mark.parametrize('missing', [True, False])
def test_replay_rejects_missing_or_null_existing_immutable_comparison_fields(completion, prepare, fields, missing):
    request = request_for(completion, observed(completion))
    with connection(completion, role=ROLE) as db: call(db, request)
    for field in fields:
        altered = deepcopy(request)
        if missing: del altered[field]
        else: altered[field] = None
        with connection(completion, role=ROLE) as db:
            with pytest.raises(psycopg.Error, match='corporate_governance_(idempotency_conflict|invalid_input|forbidden)'):
                call(db, altered, prepare=prepare)
    assert saved_count(completion) == 1


def admit_prior_year(fixture):
    """Owned second admission so replay's year comparison is actually reached."""
    seed = fixture['seed']
    with psycopg.connect(DATABASE_URL) as db:
        assessment, admission, acceptance = (str(uuid4()) for _ in range(3))
        promise = deepcopy(seed['promise'])
        promise.update(accountingYear=2025, startsOn='2025-01-01', endsOn='2025-12-31', reconstructionRequiredFrom='2025-01-01')
        digest = hashlib.sha256(json.dumps(promise, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        for table, original, changes in (
            ('company_eligibility_assessments', seed['current'], dict(id=assessment, accounting_year=2025, operation_id=str(uuid4()), previous_assessment_id=None)),
            ('company_year_admissions', seed['admission'], dict(id=admission, accounting_year=2025, eligibility_assessment_id=assessment,
                company_year_promise=promise, company_year_promise_sha256=digest, reconstruct_from='2025-01-01')),
            ('company_year_acceptances', seed['acceptance'], dict(id=acceptance, accounting_year=2025, company_year_admission_id=admission)),
        ):
            db.execute(sql.SQL('insert into public.{0} select (jsonb_populate_record(null::public.{0},to_jsonb(original)||%s::jsonb)).* from public.{0} original where id=%s').format(sql.Identifier(table)), (Jsonb(changes), original))
    with connection(fixture, role='corporate_governance_store_owner') as db:
        assert db.execute('select public.company_access_company_year_allows_consequential_v1(%s,2025)', (seed['company'],)).fetchone()[0]


@pytest.mark.parametrize('prepare', [False, True])
@pytest.mark.parametrize('foreign', ['company', 'year'])
def test_replay_cannot_disclose_event_under_other_accepted_scope(completion, prepare, foreign):
    request = request_for(completion, observed(completion))
    with connection(completion, role=ROLE) as db: call(db, request)
    altered = deepcopy(request)
    if foreign == 'year':
        admit_prior_year(completion)
        altered['incomeYear'] = 2025
    else:
        other = admitted.__wrapped__(SimpleNamespace())
        with psycopg.connect(DATABASE_URL) as db:
            db.execute("insert into public.company_memberships(company_id,user_id,role,accepted_at) values(%s,%s,'owner',clock_timestamp())",
                       (other['company'], completion['seed']['owner']))
        altered['companyId'] = str(other['company'])
    with connection(completion, role=ROLE) as db:
        with pytest.raises(psycopg.Error, match='corporate_governance_idempotency_conflict'): call(db, altered, prepare=prepare)


@pytest.mark.parametrize('failure', ['outsider', 'revoked', 'subject', 'repeatable_read'])
def test_completion_keeps_owner_verified_subject_and_read_committed_policy(completion, failure):
    request = request_for(completion, observed(completion))
    if failure == 'revoked':
        with psycopg.connect(DATABASE_URL) as db:
            db.execute("update public.company_memberships set role='read_only' where company_id=%s", (completion['seed']['company'],))
    with connection(completion, role=ROLE, actor=completion['seed']['outsider'] if failure == 'outsider' else None,
                    repeatable_read=failure == 'repeatable_read') as db:
        expected = 'rf193_company_guard_requires_read_committed' if failure == 'repeatable_read' else 'corporate_governance_forbidden'
        with pytest.raises(psycopg.Error, match=expected):
            call(db, request, subject=str(uuid4()) if failure == 'subject' else None)


def pending_completion(fixture, request, ready):
    with connection(fixture, role=ROLE) as db:
        ready.put(db.execute('select pg_backend_pid()').fetchone()[0])
        return call(db, request)


@pytest.mark.parametrize('first', ['withdrawal', 'completion'])
def test_company_lock_serializes_both_completion_and_withdrawal_orders(completion, first):
    original = observed(completion); request = request_for(completion, original); ready = Queue()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with connection(completion, role=None if first == 'withdrawal' else ROLE) as db:
            if first == 'withdrawal':
                append(db, original)
                future = pool.submit(pending_completion, completion, request, ready)
            else:
                call(db, request)
                def withdrawing():
                    with connection(completion) as second:
                        ready.put(second.execute('select pg_backend_pid()').fetchone()[0])
                        return append(second, original)
                future = pool.submit(withdrawing)
            wait_for_lock(ready.get(timeout=3))
            assert not future.done()
        if first == 'withdrawal':
            with pytest.raises(psycopg.Error, match='rf1086_register_predecessor_mismatch'): future.result(timeout=6)
        else: assert rf.parse_rf1086_register_observation_withdrawal(future.result(timeout=6)).command.observation_id == original.observation_id
    assert saved_count(completion) == (0 if first == 'withdrawal' else 1)
    if first == 'completion':
        with connection(completion, role=ROLE) as db: assert call(db, request)['replayed']


def test_statement_start_cutoff_conservatively_rejects_capture_after_company_wait_began(completion):
    ready = Queue()
    request = request_for(completion, observed(completion))
    with ThreadPoolExecutor(max_workers=1) as pool:
        with connection(completion) as db:
            db.execute('select public.company_archive_lock_company_v1(%s)', (completion['seed']['company'],))
            at = db.execute("select clock_timestamp()+interval '1 second'").fetchone()[0]
            original = rf.prepare_rf1086_register_observation(completion['command'], context=completion['context'],
                observation_id=rf.Rf1086RegisterObservationId(str(uuid4())), confirmed_at=at)
            request = request_for(completion, original, entry=request['accountingEntryId'])
            future = pool.submit(pending_completion, completion, request, ready)
            wait_for_lock(ready.get(timeout=3))
            db.execute('select pg_sleep(greatest(0,extract(epoch from (%s::timestamptz-clock_timestamp()))))', (at,))
            db.execute('select shareholder_register_filing.append_register_observation_v1(%s,%s,%s,%s,%s,%s,%s,null,null,null,%s,%s)',
                (original.observation_id.value, original.command.company_id.value, original.command.income_year.value,
                 original.version, original.fact_sha256, rf.rf1086_register_observation_request_digest(original.command),
                 str(uuid4()), rf.serialize_rf1086_register_observation(original), at))
        with pytest.raises(psycopg.Error, match='rf1086_register_observation_after_cutoff'): future.result(timeout=6)
    assert saved_count(completion) == 0


def catalogs(db):
    return db.execute("select to_jsonb(p) from pg_proc p where oid in ('corporate_governance.prepare_supported_event_v1(jsonb,text)'::regprocedure,'corporate_governance.complete_supported_event_v1(jsonb,text)'::regprocedure) order by oid").fetchall()


def test_reinstall_and_retaining_rollback_preserve_all_catalog_attributes_and_role_edges(completion):
    with psycopg.connect(DATABASE_URL) as db:
        before = catalogs(db)
        edges = db.execute('select * from pg_auth_members order by roleid,member,grantor').fetchall()
        policies = db.execute("select to_jsonb(p) from pg_policy p where polrelid='corporate_governance.supported_events'::regclass order by oid").fetchall()
        schemas = db.execute("select oid,nspowner,nspacl from pg_namespace where nspname='corporate_governance'").fetchall()
        db.execute((ROOT / 'supabase/migrations' / MIGRATION).read_text())
        db.execute((ROOT / 'supabase/rollback' / MIGRATION).read_text())
        assert catalogs(db) == before
        assert db.execute("select to_jsonb(p) from pg_policy p where polrelid='corporate_governance.supported_events'::regclass order by oid").fetchall() == policies
        assert db.execute("select oid,nspowner,nspacl from pg_namespace where nspname='corporate_governance'").fetchall() == schemas
        assert db.execute('select * from pg_auth_members order by roleid,member,grantor').fetchall() == edges
        assert db.execute("select has_schema_privilege('corporate_governance_store_owner','shareholder_register_filing','USAGE'),has_function_privilege('corporate_governance_store_owner',%s,'EXECUTE')", (V2,)).fetchone() == (True, True)
        for role in ('anon','authenticated','service_role','corporate_governance_workflow_executor'):
            assert not db.execute("select has_function_privilege(%s,%s,'EXECUTE')", (role,V2)).fetchone()[0]
        for table in ('register_observations','register_observation_withdrawals'):
            assert not db.execute("select has_table_privilege('corporate_governance_store_owner',%s,'SELECT')", ('shareholder_register_filing.'+table,)).fetchone()[0]
