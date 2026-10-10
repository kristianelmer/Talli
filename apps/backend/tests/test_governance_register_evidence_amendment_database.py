"""Closed amendment persistence on the owned, fully migrated real database.

Collecting these cases is not execution evidence. Positive originals use public
owner commands and actual local retained bytes. No provider or object-store IO.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
import json
from queue import Queue
import time
from types import SimpleNamespace
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
import pytest

from talli_backend.adapters.postgres_document_originals import _receipt, _snapshot_document
from talli_backend.modules.documents.public import document_metadata_sha256
from talli_backend.modules.corporate_governance import public as gov
from talli_backend.modules.corporate_governance import register_evidence_amendment as codec
from talli_backend.shared.kernel import ActorId, ActorKind, IncomeYear, UserId
from governance_register_evidence_amendment_fixture import (
    admitted, amendment_fixture_authority, withdrawal_fixture_role, connection,
    original_document, register_capture, withdrawal, fact, document_fact,
    document_commitment, record_original, DATABASE_URL, ROOT,
)

pytestmark = pytest.mark.authority_database
MIGRATION = '20261009234529_governance_register_evidence_amendments.sql'
APPLICATION_MIGRATION = '20261010001936_governance_register_evidence_application.sql'
REPORTING_PROJECTION = '20261010005413_governance_reporting_register_evidence.sql'
SCHEMA = 'corporate_governance'
TABLE = SCHEMA + '.register_evidence_amendments'
APPEND = SCHEMA + '.append_register_evidence_amendment_v1(text,jsonb,text,text)'
CHAIN = SCHEMA + '.read_register_evidence_chain_v1(uuid,integer,uuid,text)'
LOOKUP = SCHEMA + '.lookup_register_evidence_amendment_v1(uuid,integer,uuid,text,text,text)'
ERROR = 'corporate_register_evidence_'
UNSET = object()


def grant_fixture(db, role):
    db.execute('set local role corporate_governance_store_owner')
    db.execute(sql.SQL('grant usage on schema corporate_governance to {}').format(sql.Identifier(role)))
    db.execute(sql.SQL('grant execute on function ' + ','.join((APPEND, CHAIN, LOOKUP)) + ' to {}').format(sql.Identifier(role)))
    db.execute('reset role')


@pytest.fixture(scope='module')
def amendment_role(amendment_fixture_authority):
    role = 'gov_amendment_fixture_' + uuid4().hex
    with psycopg.connect(DATABASE_URL) as db:
        db.execute(sql.SQL('create role {} nologin noinherit nobypassrls').format(sql.Identifier(role)))
        db.execute(sql.SQL('grant {} to {} with inherit false,set true').format(sql.Identifier(role), sql.Identifier(amendment_fixture_authority)))
        grant_fixture(db, role)
    try: yield role
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('set local role corporate_governance_store_owner')
            db.execute(sql.SQL('revoke all on function ' + ','.join((APPEND, CHAIN, LOOKUP)) + ' from {}').format(sql.Identifier(role)))
            db.execute(sql.SQL('revoke usage on schema corporate_governance from {}').format(sql.Identifier(role)))
            db.execute('reset role')
            db.execute(sql.SQL('drop role {}').format(sql.Identifier(role)))


def prepare_fixture(seed, role, withdrawal_role, *, kind='loss_coverage_capital_reduction', phase='first_recognized_after_registration'):
    rf_kind = 'cash_issue' if kind == 'cash_capital_increase' else 'loss_covering_reduction'
    original_observation, original_rf_docs = register_capture(seed, kind=rf_kind)
    gov_docs = tuple(original_document(seed, label) for label in ('Signed decision', 'Amended articles', 'Registration receipt') + (('Contribution confirmation',) if kind == 'cash_capital_increase' else ()))
    original = record_original(seed, original_observation, gov_docs, kind=kind, phase=phase)
    withdrawn = withdrawal(seed, withdrawal_role, original_observation)
    replacement, replacement_docs = register_capture(seed, kind=rf_kind)
    memo = original_document(seed, 'Correction memo')
    command = gov.AmendSupportedCorporateRegisterEvidence(original['command'].company_id,
        original['command'].income_year, original['command'].actor_id, original['command'].event_id,
        original['anchor'].anchor_sha256, None,
        gov.CorporateRegisterWithdrawalReference(gov.CorporateSourceReference(withdrawn.withdrawal_id.value), withdrawn.withdrawal_sha256, fact(original_observation)),
        fact(replacement), document_fact(memo, gov.SupportedCorporateEvidenceKind.CORRECTION_MEMO), '  Replace withdrawn independent register original.\n')
    documents = (*gov_docs, memo, *replacement_docs)
    return dict(seed=seed, role=role, withdrawal_role=withdrawal_role, **original,
        amendment_command=command, originals=tuple(document_commitment(doc) for doc in documents), documents=documents,
        original_observation=original_observation, original_rf_docs=original_rf_docs,
        replacement=replacement, replacement_docs=replacement_docs, memo=memo, withdrawn=withdrawn, key=str(uuid4()))


@pytest.fixture
def ready(admitted, amendment_role, withdrawal_fixture_role):
    return prepare_fixture(admitted, amendment_role, withdrawal_fixture_role)


def dumps(value): return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
def command_payload(item): return codec._command_payload(item['amendment_command'])
def originals_payload(item): return [codec._original_commitment(row) for row in item['originals']]


def append(db, item, *, raw=None, originals=UNSET, key=None, subject=UNSET):
    return db.execute('select corporate_governance.append_register_evidence_amendment_v1(%s,%s,%s,%s)',
        (raw if raw is not None else dumps(command_payload(item)),
         Jsonb(originals_payload(item) if originals is UNSET else originals), key or item['key'],
         str(item['amendment_command'].actor_id.subject) if subject is UNSET else subject)).fetchone()[0]


def save(item, **kwargs):
    with connection(item['seed'], item['role']) as db: return append(db, item, **kwargs)


def lookup(db, item, **changes):
    values = dict(company=item['seed']['company'], year=2026, event=item['command'].event_id.value,
        key=item['key'], digest=gov.corporate_register_evidence_amendment_request_digest(item['amendment_command']),
        subject=str(item['amendment_command'].actor_id.subject)) | changes
    return db.execute('select corporate_governance.lookup_register_evidence_amendment_v1(%s,%s,%s,%s,%s,%s)', tuple(values.values())).fetchone()[0]


def read_chain(db, item, **changes):
    values = dict(company=item['seed']['company'], year=2026, event=item['command'].event_id.value,
        subject=str(item['amendment_command'].actor_id.subject)) | changes
    value = db.execute('select corporate_governance.read_register_evidence_chain_v1(%s,%s,%s,%s)', tuple(values.values())).fetchone()[0]
    body = {key: item for key, item in value.items() if key != 'enumeration_sha256'}
    assert value['codec'] == 'corporate-register-evidence-chain-v1'
    assert value['enumeration_sha256'] == sha256(dumps(['corporate-register-evidence-chain-v1', body]).encode()).hexdigest()
    assert value['amendment_count'] == len(value['amendments'])
    return value


def count(item):
    with connection(item['seed'], 'corporate_governance_store_owner') as db:
        return db.execute('select count(*) from ' + TABLE + ' where company_id=%s', (item['seed']['company'],)).fetchone()[0]


def immutable_inputs(item):
    result = {}
    for owner, tables in (
        ('corporate_governance', ('supported_events',)), ('ledger', ('entries', 'entry_contexts', 'entry_sources')),
        ('documents', ('retained_originals',)), ('shareholder_register_filing', ('register_observations', 'register_observation_withdrawals'))):
        with connection(item['seed'], owner + '_store_owner') as db:
            for table in tables:
                result[owner + '.' + table] = db.execute(sql.SQL("select coalesce(jsonb_agg(to_jsonb(r) order by to_jsonb(r)::text),'[]'::jsonb) from {} r where company_id=%s").format(sql.Identifier(owner, table)), (item['seed']['company'],)).fetchone()[0]
    return result


@pytest.mark.parametrize('kind,phase', [('loss_coverage_capital_reduction', 'first_recognized_after_registration'), ('loss_coverage_capital_reduction', 'registered'), ('cash_capital_increase', 'registered')])
def test_actual_owner_proofs_mint_exact_pure_receipt_without_rewriting_originals(admitted, amendment_role, withdrawal_fixture_role, kind, phase):
    item = prepare_fixture(admitted, amendment_role, withdrawal_fixture_role, kind=kind, phase=phase)
    before = immutable_inputs(item)
    with connection(admitted, amendment_role) as db:
        empty = read_chain(db, item)
        assert empty['amendments'] == [] and empty['head'] is None
        assert lookup(db, item) == {'status': 'not_observed'}
    text = save(item); receipt = gov.parse_corporate_register_evidence_amendment(text)
    expected = gov.prepare_supported_corporate_register_evidence_amendment(item['amendment_command'], anchor=item['anchor'],
        amendment_id=receipt.amendment_id, recorded_at=receipt.recorded_at, originals=item['originals'])
    assert receipt == expected and text == gov.serialize_corporate_register_evidence_amendment(expected)
    assert immutable_inputs(item) == before and count(item) == 1
    with connection(admitted, amendment_role) as db:
        chain = read_chain(db, item)
        assert chain['anchor'] == codec._anchor_payload(item['anchor'])
        assert chain['amendments'] == [text] and chain['head'] == codec._head(receipt.head)
        assert chain['effective_register_fact'] == codec._source(item['amendment_command'].replacement)
        assert lookup(db, item) == {'status': 'recorded', 'receipt_text': text}


@pytest.mark.parametrize('proof', [None, {}, ['not-an-original']])
def test_committed_replay_ignores_fresh_original_material_after_withdrawal_reversal_and_mfa_expiry(ready, proof):
    text = save(ready)
    withdrawal(ready['seed'], ready['withdrawal_role'], ready['replacement'])
    reverse_original(ready)
    with connection(ready['seed'], ready['role'], fresh=False) as db:
        assert append(db, ready, originals=proof) == text
        assert lookup(db, ready) == {'status': 'recorded', 'receipt_text': text}
        assert read_chain(db, ready)['amendments'] == [text]
    assert count(ready) == 1


@pytest.mark.parametrize('change', ['reason', 'anchor', 'head', 'replacement', 'target', 'withdrawal', 'memo'])
def test_same_transport_key_cannot_replay_different_business_request(ready, change):
    text = save(ready); payload = command_payload(ready)
    if change == 'reason': payload['reason'] += 'different'
    elif change == 'anchor': payload['expected_anchor_sha256'] = 'f' * 64
    elif change == 'head': payload['expected_head'] = codec._head(gov.parse_corporate_register_evidence_amendment(text).head)
    elif change == 'replacement': payload['replacement']['fact_sha256'] = 'f' * 64
    elif change == 'target': payload['withdrawal']['target']['fact_sha256'] = 'f' * 64
    elif change == 'withdrawal': payload['withdrawal']['withdrawal_id'] = str(uuid4())
    else: payload['correction_memo']['content_sha256'] = 'f' * 64
    with connection(ready['seed'], ready['role']) as db:
        with pytest.raises(psycopg.Error, match=ERROR + 'replay_conflict'): append(db, ready, raw=dumps(payload))
    assert count(ready) == 1


@pytest.mark.parametrize('case', ['verified_flag', 'prepared_receipt', 'missing_reason', 'duplicate_key', 'wrong_actor', 'null_actor', 'bool_year', 'float_revision', 'unknown_source_key'])
def test_direct_sql_does_not_accept_claimed_verification_or_malformed_command(ready, case):
    payload = command_payload(ready)
    if case == 'verified_flag': payload['verified'] = True
    elif case == 'prepared_receipt': payload = {'codec': 'corporate-register-evidence-amendment-v1', 'amendment': payload}
    elif case == 'missing_reason': del payload['reason']
    elif case == 'wrong_actor': payload['actor_id']['subject'] = str(ready['seed']['outsider'])
    elif case == 'null_actor': payload['actor_id'] = None
    elif case == 'bool_year': payload['income_year'] = True
    elif case == 'float_revision': payload['replacement']['revision'] = 1.0
    elif case == 'unknown_source_key': payload['replacement']['verified'] = True
    raw = dumps(payload)
    if case == 'duplicate_key': raw = raw[:-1] + ',"reason":"second reason"}'
    with connection(ready['seed'], ready['role']) as db:
        with pytest.raises(psycopg.Error, match=ERROR + 'invalid_input|corporate_governance_forbidden'): append(db, ready, raw=raw)
    assert count(ready) == 0


@pytest.mark.parametrize('attack', ['missing_governance', 'missing_memo', 'missing_rf', 'extra', 'duplicate', 'wrong_metadata', 'wrong_content', 'wrong_length', 'wrong_retention', 'wrong_revision', 'wrong_year'])
def test_complete_exact_original_union_is_verified_by_owners(ready, attack):
    originals = originals_payload(ready)
    index = 0 if attack == 'missing_governance' else 3 if attack == 'missing_memo' else 4
    if attack.startswith('missing_'): originals.pop(index)
    elif attack == 'duplicate': originals.append(deepcopy(originals[0]))
    elif attack == 'extra': originals.append(codec._original_commitment(document_commitment(original_document(ready['seed'], 'Unrelated extra'))))
    else:
        field, value = {'wrong_metadata': ('metadata_sha256', 'f' * 64), 'wrong_content': ('content_sha256', 'f' * 64),
            'wrong_length': ('byte_length', 1), 'wrong_retention': ('retained_at', '2026-01-01T00:00:00+00:00'),
            'wrong_revision': ('revision', 2), 'wrong_year': ('source_income_year', 2025)}[attack]
        originals[4 if attack == 'wrong_revision' else 0][field] = value
    with connection(ready['seed'], ready['role']) as db:
        with pytest.raises(psycopg.Error, match=ERROR + '(evidence_mismatch|invalid_input)|documents_evidence_mismatch'):
            append(db, ready, originals=originals)
    assert count(ready) == 0


def test_matching_forged_document_receipt_labels_do_not_prove_metadata(ready):
    original = ready['documents'][0]; digest = 'f' * 64
    with connection(ready['seed'], 'documents_executor') as db:
        value = db.execute('select documents.retain_original_v1(%s,%s,%s,%s,%s,%s,%s)',
            (original.document.document_id.value, ready['seed']['company'], digest, original.document.content_sha256,
             len(original.content), original.content, str(ready['seed']['owner']))).fetchone()[0]
        forged = _receipt(value['receipt'])
    originals = originals_payload(ready)
    originals[0].update(original_id=forged.original_id, metadata_sha256=digest, retained_at=codec._time(forged.retained_at))
    with connection(ready['seed'], ready['role']) as db:
        with pytest.raises(psycopg.Error, match='documents_evidence_mismatch'): append(db, ready, originals=originals)
    assert count(ready) == 0


@pytest.mark.parametrize('state', ['withdrawn', 'superseded', 'wrong_economics', 'wrong_date', 'wrong_kind'])
def test_replacement_requires_current_exact_event_correspondence(ready, state):
    changed = ready
    if state == 'withdrawn': withdrawal(ready['seed'], ready['withdrawal_role'], ready['replacement'])
    elif state == 'superseded': register_capture(ready['seed'], documents=ready['replacement_docs'], predecessor=ready['replacement'])
    else:
        changes = {'effective_at': ready['replacement'].command.effective_at + timedelta(days=1)} if state == 'wrong_date' else {}
        if state == 'wrong_economics':
            before = ready['replacement'].command.before
            changes['before'] = replace(before, share_capital=before.share_capital + 10000, nominal_value=before.nominal_value + 100)
        replacement, docs = register_capture(ready['seed'], kind='cash_nominal_increase' if state == 'wrong_kind' else 'loss_covering_reduction', changes=changes)
        changed = ready | {'amendment_command': replace(ready['amendment_command'], replacement=fact(replacement)),
            'originals': (*ready['originals'][:4], *(document_commitment(doc) for doc in docs))}
    with connection(ready['seed'], ready['role']) as db:
        with pytest.raises(psycopg.Error, match='rf1086_register_predecessor_mismatch|' + ERROR + 'evidence_mismatch'): append(db, changed)
    assert count(ready) == 0


def reverse_original(item, *, db=None, entry_id=None):
    entry_id = entry_id or item['original'].accounting_entry_id.value
    def execute(conn):
        return conn.execute('select * from ledger.reverse_supported_entry_v1(%s,%s,2026,%s,%s,%s,%s,%s,%s)',
            ('amendment-reversal-' + entry_id, item['seed']['company'], entry_id,
             'Owned actual reversal', 'owned-amendment-reversal', str(item['seed']['owner']), item['command'].event_date.value,
             Jsonb({'role': 'CORROBORATING', 'capability': 'DOCUMENTS', 'recordId': item['memo'].document.document_id.value, 'revision': 1,
                    'factSha256': item['memo'].document.content_sha256}))).fetchone()
    if db is not None: return execute(db)
    with connection(item['seed'], 'ledger_executor') as conn: return execute(conn)


def test_fresh_amendment_rejects_actual_ledger_reversal(ready):
    reverse_original(ready)
    with connection(ready['seed'], ready['role']) as db:
        with pytest.raises(psycopg.Error, match='ledger_governance_entry_amended'): append(db, ready)
    assert count(ready) == 0


@pytest.mark.parametrize('phase', ['binding_subscription', 'restricted_payment'])
@pytest.mark.parametrize('committed', [False, True])
def test_cash_earlier_phase_reversal_blocks_only_fresh_admission(admitted, amendment_role, withdrawal_fixture_role, phase, committed):
    item = prepare_fixture(admitted, amendment_role, withdrawal_fixture_role, kind='cash_capital_increase', phase='registered')
    text = save(item) if committed else None
    with connection(item['seed'], 'corporate_governance_store_owner') as db:
        entry = str(db.execute('select accounting_entry_id from corporate_governance.supported_events where company_id=%s and event_reference=%s and phase=%s',
            (item['seed']['company'], item['command'].event_reference.value, phase)).fetchone()[0])
    assert entry != item['original'].accounting_entry_id.value
    reverse_original(item, entry_id=entry)
    with connection(item['seed'], item['role']) as db:
        if committed:
            assert append(db, item, originals=None) == text
            assert lookup(db, item) == {'status': 'recorded', 'receipt_text': text}
            assert read_chain(db, item)['amendments'] == [text]
        else:
            with pytest.raises(psycopg.Error, match=ERROR + 'lifecycle_amended'): append(db, item)
    assert count(item) == (1 if committed else 0)


@pytest.mark.parametrize('attack', ['actor', 'cutoff', 'document_fact'])
def test_self_consistent_forged_original_anchor_still_requires_actual_ledger_provenance(ready, attack):
    """Privileged original-row corruption is rolled back, never a positive seed."""
    original = ready['original']; actor = ready['command'].actor_id.subject
    changes = {}; originals = ready['originals']
    if attack == 'actor': actor = UserId(str(ready['seed']['outsider'])); changes['created_by'] = actor.value
    elif attack == 'cutoff':
        original = replace(original, recorded_at=original.recorded_at - timedelta(days=1)); changes['created_at'] = original.recorded_at
    else:
        facts = deepcopy(ready['original_request']['canonicalFacts'])
        facts['documentFacts'][0]['revision'] = 2
        digest = sha256(dumps(facts).encode()).hexdigest()
        original = replace(original, event=replace(original.event, canonical_facts=facts, facts_sha256=digest))
        outer = deepcopy(ready['original_request']['documentFacts']); identity = facts['documentFacts'][0]['document_id']['value']
        for doc in outer:
            if doc['documentId'] == identity: doc['revision'] = 2
        changes.update(canonical_facts=Jsonb(facts), facts_sha256=digest, document_facts=Jsonb(outer))
        originals = tuple(replace(doc, revision=2) if doc.document_id.value == identity else doc for doc in originals)
    forged = gov.anchor_supported_corporate_event_evidence(original, original_actor_id=actor)
    item = ready | {'amendment_command': replace(ready['amendment_command'], expected_anchor_sha256=forged.anchor_sha256), 'originals': originals}
    with connection(ready['seed'], 'corporate_governance_store_owner') as db:
        try:
            db.execute('alter table corporate_governance.supported_events no force row level security')
            db.execute('alter table corporate_governance.supported_events disable trigger supported_events_immutable')
            db.execute(sql.SQL('update corporate_governance.supported_events set {} where event_id=%s').format(
                sql.SQL(',').join(sql.SQL('{}=%s').format(sql.Identifier(key)) for key in changes)), (*changes.values(), ready['command'].event_id.value))
            db.execute(sql.SQL('set local role {}').format(sql.Identifier(ready['role'])))
            with pytest.raises(psycopg.Error, match='ledger_governance_entry_after_cutoff' if attack == 'cutoff' else 'ledger_governance_entry_mismatch'):
                append(db, item)
        finally: db.rollback()
    assert count(ready) == 0


@pytest.mark.parametrize('case', ['outsider', 'reader', 'pending', 'removed', 'subject', 'missing_subject', 'expired_mfa', 'repeatable_read', 'serializable'])
def test_current_owner_subject_mfa_and_fresh_snapshot_required(ready, case):
    if case in ('reader', 'pending', 'removed'):
        with psycopg.connect(DATABASE_URL) as db:
            if case == 'removed': db.execute('delete from public.company_memberships where company_id=%s', (ready['seed']['company'],))
            elif case == 'pending': db.execute('update public.company_memberships set accepted_at=null where company_id=%s', (ready['seed']['company'],))
            else: db.execute("update public.company_memberships set role='read_only' where company_id=%s", (ready['seed']['company'],))
    with connection(ready['seed'], ready['role'], actor=ready['seed']['outsider'] if case == 'outsider' else None,
        fresh=case != 'expired_mfa', isolation=case.replace('_', ' ') if case in ('repeatable_read', 'serializable') else None) as db:
        with pytest.raises(psycopg.Error, match='forbidden|fresh_mfa_required|required.*read_committed|requires_read_committed'):
            append(db, ready, subject=None if case == 'missing_subject' else str(uuid4()) if case == 'subject' else UNSET)
    assert count(ready) == 0


@pytest.mark.parametrize('field', ['year', 'event', 'digest'])
def test_lookup_existing_actor_company_key_reports_mismatched_original_scope_as_conflict(ready, field):
    save(ready)
    with connection(ready['seed'], ready['role']) as db:
        change = {'year': 2025, 'event': str(uuid4()), 'digest': 'f' * 64}[field]
        assert lookup(db, ready, **{field: change}) == {'status': 'conflict'}


def test_another_current_owner_cannot_discover_original_actors_attempt_key(ready):
    text = save(ready)
    with psycopg.connect(DATABASE_URL) as db:
        db.execute("insert into public.company_memberships(company_id,user_id,role,accepted_at) values(%s,%s,'owner',clock_timestamp())", (ready['seed']['company'], ready['seed']['outsider']))
    with connection(ready['seed'], ready['role'], actor=ready['seed']['outsider']) as db:
        assert lookup(db, ready, subject=str(ready['seed']['outsider'])) == {'status': 'not_observed'}
        assert read_chain(db, ready, subject=str(ready['seed']['outsider']))['amendments'] == [text]


@pytest.mark.parametrize('operation', ['append', 'lookup', 'chain'])
def test_revoked_owner_cannot_recover_or_enumerate_committed_receipts(ready, operation):
    save(ready)
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('delete from public.company_memberships where company_id=%s', (ready['seed']['company'],))
    with connection(ready['seed'], ready['role']) as db:
        with pytest.raises(psycopg.Error, match='forbidden'):
            {'append': append, 'lookup': lookup, 'chain': read_chain}[operation](db, ready)


def test_accepted_other_company_scope_does_not_disclose_original_attempt_or_chain(ready):
    save(ready)
    other = admitted.__wrapped__(SimpleNamespace())
    with psycopg.connect(DATABASE_URL) as db:
        db.execute("insert into public.company_memberships(company_id,user_id,role,accepted_at) values(%s,%s,'owner',clock_timestamp())", (other['company'], ready['seed']['owner']))
    with connection(ready['seed'], ready['role']) as db:
        assert lookup(db, ready, company=other['company']) == {'status': 'not_observed'}
        with pytest.raises(psycopg.Error, match=ERROR + 'not_found'): read_chain(db, ready, company=other['company'])


@pytest.mark.parametrize('field,value', [('income_year', 2025), ('event_id', None)])
def test_same_actor_company_key_cannot_create_second_scope_on_append(ready, field, value):
    save(ready); payload = command_payload(ready); payload[field] = value or str(uuid4())
    with connection(ready['seed'], ready['role']) as db:
        with pytest.raises(psycopg.Error, match=ERROR + 'replay_conflict'): append(db, ready, raw=dumps(payload))
    assert count(ready) == 1


def test_absent_lookup_does_not_write_or_prove_previous_transaction_finished(ready):
    before = immutable_inputs(ready)
    with connection(ready['seed'], ready['role']) as db:
        assert lookup(db, ready) == {'status': 'not_observed'}
    assert count(ready) == 0 and immutable_inputs(ready) == before


def successor(item, prior, *, actor=None):
    seed = item['seed'] if actor is None else item['seed'] | {'owner': actor}
    withdrawn = withdrawal(seed, item['withdrawal_role'], item['replacement'])
    replacement, docs = register_capture(seed, kind=item['replacement'].command.event_kind)
    command = replace(item['amendment_command'], expected_head=prior.head,
        actor_id=item['amendment_command'].actor_id if actor is None else ActorId(ActorKind.USER, UserId(str(actor))),
        withdrawal=gov.CorporateRegisterWithdrawalReference(gov.CorporateSourceReference(withdrawn.withdrawal_id.value), withdrawn.withdrawal_sha256, fact(item['replacement'])),
        replacement=fact(replacement))
    return item | {'seed': seed, 'amendment_command': command, 'replacement': replacement, 'replacement_docs': docs,
        'originals': (*item['originals'][:4], *(document_commitment(doc) for doc in docs)), 'key': str(uuid4())}


def test_linear_history_keeps_original_actor_and_all_versions_under_new_current_owner(ready):
    first_text = save(ready); first = gov.parse_corporate_register_evidence_amendment(first_text)
    with psycopg.connect(DATABASE_URL) as db:
        db.execute("insert into public.company_memberships(company_id,user_id,role,accepted_at) values(%s,%s,'owner',clock_timestamp())", (ready['seed']['company'], ready['seed']['outsider']))
        db.execute('delete from public.company_memberships where company_id=%s and user_id=%s', (ready['seed']['company'], ready['seed']['owner']))
    changed = successor(ready, first, actor=ready['seed']['outsider'])
    second_text = save(changed); second = gov.parse_corporate_register_evidence_amendment(second_text)
    expected = gov.prepare_supported_corporate_register_evidence_amendment(changed['amendment_command'], anchor=ready['anchor'],
        amendment_id=second.amendment_id, recorded_at=second.recorded_at, originals=changed['originals'], previous=(first,))
    assert second == expected and second.anchor.original_actor_id == ready['command'].actor_id.subject
    assert second.command.actor_id != first.command.actor_id
    with connection(changed['seed'], changed['role']) as db:
        chain = read_chain(db, changed)
        assert chain['amendments'] == [first_text, second_text] and chain['amendment_count'] == 2
        assert chain['head'] == codec._head(second.head)
        assert lookup(db, changed) == {'status': 'recorded', 'receipt_text': second_text}
    with connection(ready['seed'], ready['role']) as db:
        with pytest.raises(psycopg.Error, match='forbidden'): append(db, ready)


@pytest.mark.parametrize('attack', ['fresh_key_old_head', 'wrong_head_hash', 'wrong_head_id', 'skipped_revision', 'reused_ancestor'])
def test_fresh_write_requires_exact_linear_head_and_never_reactivates_ancestors(ready, attack):
    first = gov.parse_corporate_register_evidence_amendment(save(ready))
    changed = successor(ready, first)
    command = changed['amendment_command']
    if attack == 'fresh_key_old_head': command = replace(command, expected_head=None)
    elif attack == 'wrong_head_hash': command = replace(command, expected_head=replace(first.head, amendment_sha256='f' * 64))
    elif attack == 'wrong_head_id': command = replace(command, expected_head=replace(first.head, amendment_id=gov.CorporateRegisterEvidenceAmendmentId(str(uuid4()))))
    elif attack == 'skipped_revision': command = replace(command, expected_head=replace(first.head, revision=3))
    else: command = replace(command, replacement=fact(ready['original_observation']))
    with connection(ready['seed'], ready['role']) as db:
        with pytest.raises(psycopg.Error, match=ERROR + 'lineage_mismatch|rf1086_register_predecessor_mismatch'):
            append(db, changed | {'amendment_command': command})
    assert count(ready) == 1


@contextmanager
def changed_current_document(item, change):
    """Owned privileged current metadata mutation, always rolled back."""
    with connection(item['seed'], 'documents_store_owner') as db:
        try:
            doc = item['documents'][0].document.document_id.value
            db.execute(sql.SQL('update public.documents set {} where id=%s').format(
                sql.SQL(',').join(sql.SQL('{}=%s').format(sql.Identifier(key)) for key in change)), (*change.values(), doc))
            db.execute(sql.SQL('set local role {}').format(sql.Identifier(item['role'])))
            yield db
        finally: db.rollback()


@pytest.mark.parametrize('change', [dict(status='removed', removal_reason='Owned removal'), dict(status='quarantined'),
    dict(name='Current metadata changed'), dict(content_sha256='f' * 64), dict(byte_length=1)])
@pytest.mark.parametrize('committed', [False, True])
def test_current_documents_gate_fresh_admission_but_never_hide_committed_recovery(ready, change, committed):
    text = save(ready) if committed else None
    with changed_current_document(ready, change) as db:
        if committed:
            assert append(db, ready, originals=None) == text
            assert lookup(db, ready) == {'status': 'recorded', 'receipt_text': text}
            assert read_chain(db, ready)['amendments'] == [text]
        else:
            with pytest.raises(psycopg.Error, match='documents_evidence_mismatch'): append(db, ready)
    assert count(ready) == (1 if committed else 0)


@pytest.mark.parametrize('status', ['staged', 'quarantined', 'removed', 'missing_accepted', 'missing_accepted_warning', 'not_required', 'attached_removed_at'])
@pytest.mark.parametrize('committed', [False, True])
def test_self_consistent_unusable_document_proofs_do_not_authorize_fresh_amendment(ready, status, committed):
    """Privileged current/retained metadata corruption targets Gov eligibility;
    both actual Documents proofs pass, and all corruption rolls back.
    """
    text = save(ready) if committed else None
    originals = originals_payload(ready)
    doc = ready['documents'][0].document.document_id.value
    with connection(ready['seed'], 'documents_store_owner') as db:
        try:
            db.execute('alter table documents.retained_originals no force row level security')
            db.execute('alter table documents.retained_originals disable trigger retained_original_immutable')
            if status == 'attached_removed_at':
                db.execute('update public.documents set removed_at=clock_timestamp() where id=%s', (doc,))
            else:
                db.execute('update public.documents set status=%s where id=%s', (status, doc))
            snapshot = db.execute('select to_jsonb(d) from public.documents d where id=%s', (doc,)).fetchone()[0]
            digest = document_metadata_sha256(_snapshot_document(snapshot))
            proof = originals[0] | {'metadata_sha256': digest}
            originals[0] = proof
            db.execute('update documents.retained_originals set document_snapshot=%s,metadata_sha256=%s where id=%s',
                (Jsonb(snapshot), digest, proof['original_id']))
            args = (proof['original_id'], doc, ready['seed']['company'], proof['source_income_year'], digest,
                proof['content_sha256'], proof['byte_length'], proof['retained_at'])
            subject = str(ready['seed']['owner'])
            assert db.execute('select documents.assert_retained_original_v1(%s,%s,%s,%s,%s,%s,%s,%s,%s)', (*args, subject)).fetchone()[0] == snapshot
            assert db.execute('select document_text from documents.assert_historical_original_integrity_v1(%s,%s,%s,%s,%s,%s,%s,%s,clock_timestamp(),%s)', (*args, subject)).fetchone()[0]
            db.execute(sql.SQL('set local role {}').format(sql.Identifier(ready['role'])))
            if committed:
                assert append(db, ready, originals=originals) == text
                assert lookup(db, ready) == {'status': 'recorded', 'receipt_text': text}
                assert read_chain(db, ready)['amendments'] == [text]
            else:
                with pytest.raises(psycopg.Error, match=ERROR + 'evidence_mismatch'): append(db, ready, originals=originals)
        finally: db.rollback()
    assert count(ready) == (1 if committed else 0)


@contextmanager
def corrupt_amendment(item, identifier, *, delete=False, **changes):
    """Explicit owner corruption; row/constraint/trigger/RLS edits roll back atomically."""
    with connection(item['seed'], 'corporate_governance_store_owner') as db:
        try:
            db.execute('alter table ' + TABLE + ' no force row level security')
            db.execute('alter table ' + TABLE + ' disable trigger register_evidence_amendments_immutable')
            if delete:
                db.execute('alter table ' + TABLE + ' drop constraint register_evidence_amendments_predecessor_fk')
                db.execute('delete from ' + TABLE + ' where id=%s', (identifier,))
            else:
                db.execute(sql.SQL('update ' + TABLE + ' set {} where id=%s').format(
                    sql.SQL(',').join(sql.SQL('{}=%s').format(sql.Identifier(key)) for key in changes)), (*changes.values(), identifier))
            db.execute(sql.SQL('set local role {}').format(sql.Identifier(item['role'])))
            yield db
        finally: db.rollback()


@pytest.mark.parametrize('column', ['snapshot_text', 'request_sha256', 'anchor_sha256', 'amendment_sha256', 'withdrawal_id', 'replacement_id', 'recorded_at', 'actor_id'])
def test_complete_history_and_recovery_validate_retained_row_bindings(ready, column):
    text = save(ready); receipt = gov.parse_corporate_register_evidence_amendment(text)
    changed = ('{}' if column == 'snapshot_text' else str(uuid4()) if column in ('withdrawal_id', 'replacement_id')
        else receipt.recorded_at + timedelta(microseconds=1) if column == 'recorded_at'
        else ready['seed']['outsider'] if column == 'actor_id' else 'f' * 64)
    with corrupt_amendment(ready, receipt.amendment_id.value, **{column: changed}) as db:
        with pytest.raises(psycopg.Error, match=ERROR + 'storage_invalid'): read_chain(db, ready)
    with connection(ready['seed'], ready['role']) as db: assert read_chain(db, ready)['amendments'] == [text]


def test_recomputed_receipt_hash_cannot_hide_changed_original_anchor(ready):
    text = save(ready); payload = json.loads(text); body = payload['amendment']
    body['anchor']['original_actor_id'] = str(ready['seed']['outsider'])
    anchor_body = {key: value for key, value in body['anchor'].items() if key != 'anchor_sha256'}
    digest = sha256(dumps(['corporate-supported-event-evidence-anchor-v1', anchor_body]).encode()).hexdigest()
    body['anchor']['anchor_sha256'] = digest; body['command']['expected_anchor_sha256'] = digest
    body['request_sha256'] = sha256(dumps(['corporate-register-evidence-amendment-request-v1', body['command']]).encode()).hexdigest()
    body['amendment_sha256'] = sha256(dumps(['corporate-register-evidence-amendment-v1', {key: value for key, value in body.items() if key != 'amendment_sha256'}]).encode()).hexdigest()
    assert gov.parse_corporate_register_evidence_amendment(dumps(payload)).anchor.original_actor_id == UserId(str(ready['seed']['outsider']))
    with corrupt_amendment(ready, body['amendment_id'], snapshot_text=dumps(payload), anchor_sha256=digest,
        request_sha256=body['request_sha256'], amendment_sha256=body['amendment_sha256']) as db:
        with pytest.raises(psycopg.Error, match=ERROR + 'storage_invalid'): read_chain(db, ready)


def test_full_enumeration_rejects_missing_ancestor_and_keeps_two_exact_receipts(ready):
    first_text = save(ready); first = gov.parse_corporate_register_evidence_amendment(first_text)
    next_item = successor(ready, first); second_text = save(next_item)
    with corrupt_amendment(ready, first.amendment_id.value, delete=True) as db:
        with pytest.raises(psycopg.Error, match=ERROR + '(storage_invalid|lineage_mismatch)'): read_chain(db, ready)
    with connection(ready['seed'], ready['role']) as db:
        assert read_chain(db, ready)['amendments'] == [first_text, second_text]
        assert lookup(db, ready) == {'status': 'recorded', 'receipt_text': first_text}


@pytest.mark.parametrize('statement', ['update ' + TABLE + ' set snapshot_text=snapshot_text where company_id=%s',
    'delete from ' + TABLE + ' where company_id=%s', 'truncate ' + TABLE])
def test_append_only_history_blocks_even_direct_owner_mutation(ready, statement):
    text = save(ready)
    with connection(ready['seed'], 'corporate_governance_store_owner') as db:
        db.execute('alter table ' + TABLE + ' no force row level security')
        with pytest.raises(psycopg.Error, match='immutable'):
            db.execute(statement, (ready['seed']['company'],) if '%s' in statement else None)
    with connection(ready['seed'], ready['role']) as db: assert read_chain(db, ready)['amendments'] == [text]


def catalog(db):
    return dict(functions=db.execute("select oid,to_jsonb(p) from pg_proc p where pronamespace='corporate_governance'::regnamespace order by oid").fetchall(),
        memberships=db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall(),
        relations=db.execute("select oid,relacl::text,relrowsecurity,relforcerowsecurity from pg_class where relnamespace='corporate_governance'::regnamespace order by oid").fetchall(),
        schemas=db.execute("select nspname,nspowner,nspacl::text from pg_namespace where nspname in ('corporate_governance','documents','ledger','shareholder_register_filing') order by nspname").fetchall())


def test_staged_closed_grants_reapply_and_retentive_rollback_preserve_exact_catalog_history(ready):
    text = save(ready); before_rows = immutable_inputs(ready)
    try:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute((ROOT / 'supabase/migrations' / MIGRATION).read_text())
            db.execute('set local role corporate_governance_store_owner'); before = catalog(db)
            functions = db.execute("select oid,proacl from pg_proc where pronamespace='corporate_governance'::regnamespace and (proname like 'register_evidence_%_internal_v1' or proname in ('append_register_evidence_amendment_v1','read_register_evidence_chain_v1','lookup_register_evidence_amendment_v1'))").fetchall()
            assert len(functions) > 3
            roles = db.execute("select rolname from pg_roles where rolname in ('anon','authenticated','service_role') or rolname like '%executor' or rolname like '%store_owner' or rolname like '%bridge_owner'").fetchall()
            for identity, _ in functions:
                assert not db.execute('select exists(select 1 from pg_proc p cross join lateral aclexplode(p.proacl) a where p.oid=%s and a.grantee=0)', (identity,)).fetchone()[0]
                for (role,) in roles:
                    if role != 'corporate_governance_store_owner':
                        assert not db.execute("select has_function_privilege(%s,%s::oid,'EXECUTE')", (role, identity)).fetchone()[0]
            for (role,) in roles:
                if role != 'corporate_governance_store_owner':
                    assert not db.execute("select has_table_privilege(%s,%s,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')", (role, TABLE)).fetchone()[0]
            assert db.execute('select relrowsecurity,relforcerowsecurity from pg_class where oid=%s::regclass', (TABLE,)).fetchone() == (True, True)
            assert db.execute("""select c.contype,c.convalidated,c.confdeltype,
                array(select a.attname from unnest(c.conkey) with ordinality k(number,position)
                  join pg_attribute a on a.attrelid=c.conrelid and a.attnum=k.number order by k.position),
                array(select a.attname from unnest(c.confkey) with ordinality k(number,position)
                  join pg_attribute a on a.attrelid=c.confrelid and a.attnum=k.number order by k.position)
                from pg_constraint c where c.conrelid=%s::regclass and c.confrelid=c.conrelid
                  and c.conname='register_evidence_amendments_predecessor_fk'""", (TABLE,)).fetchone() == (
                'f', True, 'r',
                ['company_id', 'income_year', 'event_id', 'predecessor_id', 'predecessor_revision', 'predecessor_sha256'],
                ['company_id', 'income_year', 'event_id', 'id', 'revision', 'amendment_sha256'])
            assert not db.execute("select has_function_privilege(%s,%s,'EXECUTE')", (ready['role'], APPEND)).fetchone()[0]
            db.execute('reset role'); db.execute((ROOT / 'supabase/migrations' / MIGRATION).read_text())
            db.execute('set local role corporate_governance_store_owner'); assert catalog(db) == before
            db.execute('reset role'); db.execute((ROOT / 'supabase/rollback' / MIGRATION).read_text())
            db.execute('set local role corporate_governance_store_owner'); assert catalog(db) == before
            db.execute('reset role'); grant_fixture(db, ready['role'])
    finally:
        # The predecessor intentionally closes its three contracts. Always
        # restore the reviewed application suffix before the next fixture.
        with psycopg.connect(DATABASE_URL) as db:
            db.execute((ROOT / 'supabase/migrations' / APPLICATION_MIGRATION).read_text())
            db.execute((ROOT / 'supabase/migrations' / REPORTING_PROJECTION).read_text())
            db.execute('set local role corporate_governance_store_owner')
            grant_fixture(db, ready['role'])
    assert immutable_inputs(ready) == before_rows
    with connection(ready['seed'], ready['role']) as db: assert read_chain(db, ready)['amendments'] == [text]


def wait_for_company_lock(pid):
    for _ in range(200):
        with psycopg.connect(DATABASE_URL) as db:
            if db.execute("select exists(select 1 from pg_stat_activity where pid=%s and wait_event='advisory')", (pid,)).fetchone()[0]: return
        time.sleep(.01)
    raise AssertionError('Owned competing connection did not wait on company guard')


def test_concurrent_exact_replays_mint_one_original_identity(ready):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: save(ready), range(2)))
    assert results[0] == results[1] and count(ready) == 1


def test_competing_new_keys_cannot_fork_the_same_expected_head(ready):
    def attempt(key):
        try: return ('recorded', save(ready, key=key))
        except psycopg.Error as error:
            assert ERROR + 'lineage_mismatch' in str(error)
            return ('conflict', None)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [str(uuid4()), str(uuid4())]))
    assert sorted(result[0] for result in results) == ['conflict', 'recorded'] and count(ready) == 1


@pytest.mark.parametrize('commit', [False, True])
def test_lookup_waits_for_original_company_transaction_then_distinguishes_commit_from_not_observed(ready, commit):
    queued = Queue()
    def compete():
        with connection(ready['seed'], ready['role']) as db:
            queued.put(db.execute('select pg_backend_pid()').fetchone()[0]); return lookup(db, ready)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with connection(ready['seed'], ready['role']) as db:
            text = append(db, ready)
            pending = pool.submit(compete); wait_for_company_lock(queued.get(timeout=5)); assert not pending.done()
            if not commit: db.rollback()
        observed = pending.result(timeout=10)
    assert observed == ({'status': 'recorded', 'receipt_text': text} if commit else {'status': 'not_observed'})
    assert count(ready) == int(commit)


@pytest.mark.parametrize('mutation', ['withdrawal', 'reversal'])
@pytest.mark.parametrize('amendment_first', [True, False])
def test_both_company_lock_orders_fence_fresh_admission_and_preserve_committed_history(ready, mutation, amendment_first):
    queued = Queue()
    mutation_role = ready['withdrawal_role'] if mutation == 'withdrawal' else 'ledger_executor'
    def mutate(db):
        if mutation == 'withdrawal': return withdrawal(ready['seed'], ready['withdrawal_role'], ready['replacement'], db=db)
        return reverse_original(ready, db=db)
    def compete():
        role = mutation_role if amendment_first else ready['role']
        with connection(ready['seed'], role) as db:
            queued.put(db.execute('select pg_backend_pid()').fetchone()[0])
            if amendment_first: return mutate(db)
            return append(db, ready)
    first_role = ready['role'] if amendment_first else mutation_role
    with ThreadPoolExecutor(max_workers=1) as pool:
        with connection(ready['seed'], first_role) as db:
            if amendment_first: recorded = append(db, ready)
            else: mutate(db)
            pending = pool.submit(compete); wait_for_company_lock(queued.get(timeout=5)); assert not pending.done()
        if amendment_first: pending.result(timeout=10); assert save(ready) == recorded
        else:
            with pytest.raises(psycopg.Error, match='rf1086_register_predecessor_mismatch|ledger_governance_entry_amended'): pending.result(timeout=10)
    assert count(ready) == (1 if amendment_first else 0)


@pytest.mark.parametrize('revoked', [False, True])
def test_owner_and_mfa_are_rechecked_after_actual_company_lock_wait(ready, revoked):
    queued = Queue()
    def compete():
        with connection(ready['seed'], ready['role']) as db:
            now = db.execute('select clock_timestamp()').fetchone()[0].timestamp()
            claims = dict(sub=str(ready['seed']['owner']), role='authenticated', aal='aal2', amr=[dict(method='totp', timestamp=now - 898)])
            db.execute("select set_config('talli.verified_actor_claims',%s,true),set_config('request.jwt.claims',%s,true)", (json.dumps(claims), json.dumps(claims)))
            queued.put((db.execute('select pg_backend_pid()').fetchone()[0], now + 2))
            return append(db, ready)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('select public.company_archive_lock_company_v1(%s)', (ready['seed']['company'],))
            pending = pool.submit(compete); pid, expiry = queued.get(timeout=5); wait_for_company_lock(pid)
            if revoked:
                db.execute("update public.company_memberships set role='read_only' where company_id=%s", (ready['seed']['company'],))
            else:
                row = db.execute("select provolatile,prosrc from pg_proc where oid='public.company_access_has_fresh_mfa_v1()'::regprocedure").fetchone()
                assert row[0] == 'v' and row[1].count('clock_timestamp()') == 2
                while db.execute('select extract(epoch from clock_timestamp())').fetchone()[0] <= expiry + .05: time.sleep(.02)
            assert not pending.done()
        with pytest.raises(psycopg.Error, match='forbidden' if revoked else ERROR + 'fresh_mfa_required'):
            pending.result(timeout=10)
    assert count(ready) == 0
