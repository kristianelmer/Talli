"""Actual Governance adapter with adversarial SQL output; no database execution."""
import asyncio
from dataclasses import replace
from hashlib import sha256
import json

import pytest

from talli_backend.adapters.supabase_corporate_governance import _map_governance_database_error
from talli_backend.modules.corporate_governance import public as gov
from talli_backend.modules.corporate_governance import register_evidence_amendment as codec
from talli_backend.shared.kernel import ErrorCategory, IdempotencyKey
from test_corporate_register_evidence_amendment import fixture, follow, identifier
from test_supabase_corporate_governance import bound_transaction

KEY = IdempotencyKey('owned-amendment-request-001')


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def chain_payload(anchor, amendments=()):
    chain = gov.derive_corporate_register_evidence_chain(anchor, amendments=tuple(amendments))
    body = dict(codec='corporate-register-evidence-chain-v1', company_id=str(anchor.original.event.company_id),
        income_year=int(anchor.original.event.income_year), event_id=str(anchor.original.event.event_id),
        anchor=codec._anchor_payload(anchor), amendments=[gov.serialize_corporate_register_evidence_amendment(a) for a in amendments],
        amendment_count=len(amendments), head=codec._head(chain.head),
        effective_register_fact=codec._source(chain.effective_register_fact))
    return body | {'enumeration_sha256': sha256(dumps(['corporate-register-evidence-chain-v1', body]).encode()).hexdigest()}


def query(command):
    return gov.CorporateRegisterEvidenceQuery(command.company_id, command.income_year, command.actor_id, command.event_id)


def transaction(value, *, rows=None):
    tx = bound_transaction()
    _, cmd, _, _ = fixture()
    tx._verified = replace(tx._verified, actor_id=cmd.actor_id)
    calls = []
    async def database_rows(sql, params=()):
        calls.append((sql, params))
        if isinstance(value, Exception): raise value
        return rows if rows is not None else [{'result': value}]
    tx._database_rows = database_rows
    return tx, calls


def run(tx, operation, cmd=None, originals=None):
    _, default, default_originals, _ = fixture()
    cmd = cmd or default
    if operation == 'append':
        return asyncio.run(tx.append_register_evidence_amendment(cmd, originals=originals or default_originals, idempotency_key=KEY))
    if operation == 'prepare':
        return asyncio.run(tx.prepare_register_evidence_amendment(cmd, idempotency_key=KEY))
    if operation == 'lookup':
        return asyncio.run(tx.lookup_register_evidence_amendment(query(cmd), idempotency_key=KEY,
            request_sha256=gov.corporate_register_evidence_amendment_request_digest(cmd)))
    return asyncio.run(tx.read_register_evidence_chain(query(cmd)))


@pytest.mark.parametrize('operation', ['prepare', 'append', 'lookup', 'chain'])
def test_only_named_public_contract_with_exact_verified_scope_and_request(operation):
    anchor, cmd, originals, receipt = fixture()
    encoded = gov.serialize_corporate_register_evidence_amendment(receipt)
    value = {'prepare': {'status': 'ready', 'chain': chain_payload(anchor)}, 'append': encoded,
        'lookup': {'status': 'recorded', 'receipt_text': encoded}, 'chain': chain_payload(anchor, (receipt,))}[operation]
    tx, calls = transaction(value)
    result = run(tx, operation)
    assert len(calls) == 1
    sql, parameters = calls[0]
    expected_name = {'prepare': 'prepare_register_evidence_amendment_v1', 'append': 'append_register_evidence_amendment_v1',
        'lookup': 'lookup_register_evidence_amendment_v1', 'chain': 'read_register_evidence_chain_v1'}[operation]
    assert 'corporate_governance.' + expected_name in sql
    assert parameters[-1] == str(cmd.actor_id.subject)
    if operation in ('prepare', 'append'):
        assert parameters[0] == gov.serialize_corporate_register_evidence_amendment_command(cmd)
        assert str(KEY) in parameters
    if operation == 'append':
        wire = parameters[1].obj if hasattr(parameters[1], 'obj') else json.loads(parameters[1]) if isinstance(parameters[1], str) else parameters[1]
        assert wire == [codec._original_commitment(row) for row in originals]
        assert result == receipt
    elif operation == 'lookup':
        assert result.status == 'recorded' and result.receipt == receipt
        assert parameters[:-1] == (str(cmd.company_id), int(cmd.income_year), str(cmd.event_id), str(KEY), receipt.request_sha256)
    elif operation == 'prepare':
        assert result.status == 'ready' and result.receipt is None and result.snapshot.chain.anchor == anchor
    else:
        assert result.chain.amendments == (receipt,) and result.amendment_count == 1


@pytest.mark.parametrize('operation', ['prepare', 'append', 'lookup', 'chain'])
@pytest.mark.parametrize('rows', [[], [{}, {}], [{}], [{'result': None}]])
def test_missing_or_multiple_sql_rows_never_become_empty_history_or_success(operation, rows):
    tx, _ = transaction(None, rows=rows)
    with pytest.raises(gov.CorporateGovernanceError) as error: run(tx, operation)
    assert error.value.category is ErrorCategory.DEPENDENCY_UNAVAILABLE


@pytest.mark.parametrize('status', ['not_observed', 'conflict'])
def test_lookup_absence_and_conflict_are_distinct_typed_results(status):
    tx, calls = transaction({'status': status})
    result = run(tx, 'lookup')
    assert result.status == status and result.receipt is None and len(calls) == 1


@pytest.mark.parametrize('operation', ['prepare', 'lookup'])
@pytest.mark.parametrize('attack', ['unknown_status', 'extra', 'missing_receipt', 'unexpected_receipt', 'wrong_command', 'malformed_receipt'])
def test_tagged_result_cannot_disguise_wrong_receipt_or_unknown_state(operation, attack):
    _, _, _, receipt = fixture()
    encoded = gov.serialize_corporate_register_evidence_amendment(receipt)
    value = {'status': 'recorded', 'receipt_text': encoded}
    if attack == 'unknown_status': value['status'] = 'maybe'
    elif attack == 'extra': value['verified'] = True
    elif attack == 'missing_receipt': del value['receipt_text']
    elif attack == 'unexpected_receipt': value['status'] = 'not_observed' if operation == 'lookup' else 'ready'
    elif attack == 'wrong_command': value['receipt_text'] = gov.serialize_corporate_register_evidence_amendment(follow(receipt))
    else: value['receipt_text'] = '{}'
    tx, _ = transaction(value)
    with pytest.raises(gov.CorporateGovernanceError) as error: run(tx, operation)
    assert error.value.category is ErrorCategory.DEPENDENCY_UNAVAILABLE


@pytest.mark.parametrize('attack', ['missing_count', 'extra', 'bool_count', 'float_count', 'wrong_count', 'wrong_scope',
    'wrong_year', 'wrong_event', 'wrong_head', 'wrong_effective', 'wrong_digest', 'missing_first', 'missing_last', 'reversed',
    'duplicate', 'receipt_corrupt', 'wrong_anchor'])
@pytest.mark.parametrize('operation', ['chain', 'prepare'])
def test_complete_chain_requires_all_envelope_and_pure_history_commitments(attack, operation):
    anchor, _, _, first = fixture(); second = follow(first)
    value = chain_payload(anchor, (first, second))
    if attack == 'missing_count': del value['amendment_count']
    elif attack == 'extra': value['trusted'] = True
    elif attack == 'bool_count': value['amendment_count'] = True
    elif attack == 'float_count': value['amendment_count'] = 2.0
    elif attack == 'wrong_count': value['amendment_count'] = 1
    elif attack == 'wrong_scope': value['company_id'] = identifier(90)
    elif attack == 'wrong_year': value['income_year'] = 2025
    elif attack == 'wrong_event': value['event_id'] = identifier(91)
    elif attack == 'wrong_head': value['head'] = None
    elif attack == 'wrong_effective': value['effective_register_fact'] = codec._source(first.command.replacement)
    elif attack == 'wrong_digest': value['enumeration_sha256'] = '0' * 64
    elif attack == 'missing_first': value['amendments'] = value['amendments'][1:]
    elif attack == 'missing_last': value['amendments'] = value['amendments'][:-1]
    elif attack == 'reversed': value['amendments'].reverse()
    elif attack == 'duplicate': value['amendments'][1] = value['amendments'][0]
    elif attack == 'receipt_corrupt': value['amendments'][0] = '{}'
    else: value['anchor']['original_actor_id'] = identifier(92)
    # Recommit the outer envelope except the intentional hash attack. Shape and
    # cross-field/receipt checks must not rely solely on the enumeration digest.
    if attack != 'wrong_digest':
        body = {k: v for k, v in value.items() if k != 'enumeration_sha256'}
        value['enumeration_sha256'] = sha256(dumps(['corporate-register-evidence-chain-v1', body]).encode()).hexdigest()
    tx, _ = transaction({'status': 'ready', 'chain': value} if operation == 'prepare' else value)
    with pytest.raises(gov.CorporateGovernanceError) as error: run(tx, operation)
    assert error.value.category is ErrorCategory.DEPENDENCY_UNAVAILABLE


@pytest.mark.parametrize('operation', ['prepare', 'append', 'lookup', 'chain'])
def test_actor_mismatch_fails_before_sql(operation):
    _, cmd, _, _ = fixture(); tx, calls = transaction(None)
    cmd = replace(cmd, actor_id=replace(cmd.actor_id, subject=type(cmd.actor_id.subject)(identifier(93))))
    with pytest.raises(gov.CorporateGovernanceError) as error: run(tx, operation, cmd)
    assert error.value.category is ErrorCategory.FORBIDDEN and not calls


@pytest.mark.parametrize('code,category', [
    ('corporate_register_evidence_replay_conflict', ErrorCategory.CONFLICT),
    ('corporate_register_evidence_lineage_mismatch', ErrorCategory.PRECONDITION_FAILED),
    ('corporate_register_evidence_evidence_mismatch', ErrorCategory.PRECONDITION_FAILED),
    ('corporate_register_evidence_fresh_mfa_required', ErrorCategory.PRECONDITION_FAILED),
    ('corporate_register_evidence_storage_invalid', ErrorCategory.DEPENDENCY_UNAVAILABLE),
    ('ledger_governance_entry_storage_invalid', ErrorCategory.DEPENDENCY_UNAVAILABLE),
    ('documents_forbidden', ErrorCategory.FORBIDDEN),
])
def test_dependency_errors_keep_safe_meaning_without_raw_details(code, category):
    error = _map_governance_database_error(code + ' private-object-path bearer=secret')
    assert error.category is category
    assert 'private-object-path' not in str(error) and 'bearer=secret' not in str(error)


@pytest.mark.parametrize('database_code,category,code', [
    ('rf1086_register_withdrawal_evidence_mismatch', ErrorCategory.PRECONDITION_FAILED, gov.CorporateGovernanceErrorCode.REGISTER_EVIDENCE_CHANGED),
    ('ledger_forbidden', ErrorCategory.FORBIDDEN, gov.CorporateGovernanceErrorCode.FORBIDDEN),
    ('ledger_company_year_not_admitted', ErrorCategory.PRECONDITION_FAILED, gov.CorporateGovernanceErrorCode.REGISTER_EVIDENCE_CHANGED),
    ('rf1086_register_predecessor_mismatch', ErrorCategory.PRECONDITION_FAILED, gov.CorporateGovernanceErrorCode.CORPORATE_EVENT_EVIDENCE_INCOMPLETE),
    ('rf1086_register_observation_after_cutoff', ErrorCategory.PRECONDITION_FAILED, gov.CorporateGovernanceErrorCode.CORPORATE_EVENT_EVIDENCE_INCOMPLETE),
    ('documents_evidence_mismatch', ErrorCategory.PRECONDITION_FAILED, gov.CorporateGovernanceErrorCode.CORPORATE_EVENT_EVIDENCE_INCOMPLETE),
    ('rf1086_register_withdrawal_storage_invalid', ErrorCategory.DEPENDENCY_UNAVAILABLE, None),
    ('rf1086_register_observation_cutoff_invalid', ErrorCategory.DEPENDENCY_UNAVAILABLE, None),
    ('ledger_governance_evidence_invalid', ErrorCategory.DEPENDENCY_UNAVAILABLE, None),
    ('documents_invalid_input', ErrorCategory.DEPENDENCY_UNAVAILABLE, None),
    ('documents_guard_requires_read_committed', ErrorCategory.DEPENDENCY_UNAVAILABLE, None),
    ('unknown_owner_failure', ErrorCategory.DEPENDENCY_UNAVAILABLE, None),
])
def test_actual_append_sql_error_path_preserves_known_owner_rejections_and_redacts_details(database_code, category, code):
    import psycopg
    tx = bound_transaction()
    _, command, _, _ = fixture()
    tx._verified = replace(tx._verified, actor_id=command.actor_id)
    calls = []
    class Connection:
        async def execute(self, sql, parameters):
            calls.append((sql, parameters))
            raise psycopg.DatabaseError(database_code + ' private-object-path bearer=secret')
    tx._connection = Connection()
    # Exercise real _database_rows, its error mapper and _amendment_result;
    # stubbing _database_rows would conceal Ledger-error flattening here.
    with pytest.raises(gov.CorporateGovernanceError) as failure:
        run(tx, 'append', command)
    assert failure.value.category is category
    if code is not None:
        assert failure.value.code == code
    assert 'private-object-path' not in str(failure.value) and 'bearer=secret' not in str(failure.value)
    assert len(calls) == 1 and 'append_register_evidence_amendment_v1' in calls[0][0]
