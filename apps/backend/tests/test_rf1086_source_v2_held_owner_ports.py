"""Actual held ports/public codecs; SQL authority and connection state are doubles."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import psycopg
from psycopg.pq import TransactionStatus
import pytest

from talli_backend.adapters.postgres_corporate_reporting_evidence import PostgresCorporateReportingEvidence
from talli_backend.adapters.postgres_shareholder_register_filing import _SourceAdmission
from talli_backend.modules.corporate_governance import public as gov
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CorrelationId, ErrorCategory, UserId
from test_corporate_register_evidence_amendment import fixture, follow, identifier
from test_corporate_governance_reporting_register_evidence import query, build, snapshot
from test_postgres_corporate_reporting_register_evidence import payload, Connection
from test_rf1086_source_context_v2 import coherent, context, prepared
from test_shareholder_register_source_workflow import Harness


def scope(connection, request):
    store = SimpleNamespace(actor_id=request.actor_id)
    return _SourceAdmission(store, connection,
        rf.Rf1086SourceQuery(request.company_id, request.income_year, request.actor_id), None)


@pytest.mark.parametrize('count', [0, 1, 2])
def test_held_reader_decodes_complete_public_chains_on_the_same_connection(count):
    anchor, _, _, first = fixture()
    history = (first, follow(first))[:count]
    connection = Connection(payload((anchor,), (history,)))
    held = scope(connection, query())
    value = asyncio.run(held.governance_register_evidence(CorrelationId('held-complete-register')))
    assert value == build((anchor.original,), (snapshot(anchor, history),))
    assert connection.calls == [(
        'select corporate_governance.read_guarded_reporting_register_evidence_v1(%s::uuid,%s::integer,%s::text) as result',
        (str(query().company_id), int(query().income_year), str(query().actor_id.subject)))]


@pytest.mark.parametrize('attack', ['company', 'year', 'hash', 'missing_chain', 'extra_field'])
def test_held_reader_never_falls_back_after_invalid_complete_projection(attack):
    anchor, _, _, first = fixture()
    value = deepcopy(payload((anchor,), ((first, follow(first)),)))
    if attack == 'company': value['company_id'] = identifier(990)
    elif attack == 'year': value['income_year'] -= 1
    elif attack == 'hash': value['chain_enumeration_sha256'] = 'f' * 64
    elif attack == 'missing_chain': value['register_chains'] = []
    else: value['trusted'] = True
    connection = Connection(value)
    with pytest.raises(gov.CorporateGovernanceError) as failure:
        asyncio.run(scope(connection, query()).governance_register_evidence(CorrelationId('held-register')))
    assert failure.value.category is ErrorCategory.DEPENDENCY_UNAVAILABLE
    assert len(connection.calls) == 1


@pytest.mark.parametrize('action', ['read', 'proof'])
@pytest.mark.parametrize('status', [TransactionStatus.IDLE, TransactionStatus.INERROR, TransactionStatus.UNKNOWN])
def test_held_ports_deny_nontransactional_connections_before_sql(action, status):
    h = coherent()
    source = prepared(h, context(h))
    connection = Connection(None, status=status)
    held = scope(connection, h.command)
    with pytest.raises(rf.ShareholderRegisterFilingError):
        asyncio.run(held.governance_register_evidence(CorrelationId('held-register')) if action == 'read'
            else held.prepare_source_governance_proof(source))
    assert not connection.calls


@pytest.mark.parametrize('action', ['read', 'proof'])
def test_scope_expiry_denies_both_ports_even_if_connection_is_still_live(action):
    h = coherent()
    source = prepared(h, context(h))
    connection = Connection(None)
    held = scope(connection, h.command)
    held.close()
    with pytest.raises(rf.ShareholderRegisterFilingError):
        asyncio.run(held.governance_register_evidence(CorrelationId('held-register')) if action == 'read'
            else held.prepare_source_governance_proof(source))
    assert not connection.calls


def test_proof_uses_current_guard_actor_without_rewriting_historical_source():
    h = coherent(count=2)
    source = prepared(h, context(h))
    before = rf.serialize_rf1086_year_source_v2(source)
    current = replace(h.command.actor_id, subject=UserId(identifier(992)))
    request = replace(h.command, actor_id=current)
    connection = Connection(None)
    assert asyncio.run(scope(connection, request).prepare_source_governance_proof(source)) is None
    assert source.command.actor_id != current
    assert rf.serialize_rf1086_year_source_v2(source) == before
    assert connection.calls == [(
        'select corporate_governance.prepare_rf_year_source_governance_proof_v1(%s::uuid,%s::integer,%s::text,%s::text)',
        (str(source.company_id), int(source.income_year), source.source_sha256, str(current.subject)))]


def test_reader_uses_current_owner_while_preserving_historical_governance_actor():
    anchor, _, _, first = fixture()
    request = replace(query(), actor_id=replace(query().actor_id, subject=UserId(identifier(992))))
    connection = Connection(payload((anchor,), ((first,),)))
    result = asyncio.run(scope(connection, request).governance_register_evidence(CorrelationId('held-current-owner')))
    gov.assert_reporting_year_register_evidence(result, query=request)
    assert result.register_chains[0].chain.anchor == anchor
    assert result.register_chains[0].chain.anchor.original_actor_id != request.actor_id.subject
    assert connection.calls[0][1][-1] == str(request.actor_id.subject)


@pytest.mark.parametrize('action', ['read', 'proof'])
def test_cancellation_propagates_without_retry_or_synthetic_result(action):
    h = coherent()
    source = prepared(h, context(h))
    cancellation = asyncio.CancelledError('owned operation cancelled')
    connection = Connection(None, error=cancellation)
    held = scope(connection, h.command)
    with pytest.raises(asyncio.CancelledError) as failure:
        asyncio.run(held.governance_register_evidence(CorrelationId('held-register')) if action == 'read'
            else held.prepare_source_governance_proof(source))
    assert failure.value is cancellation and len(connection.calls) == 1


@pytest.mark.parametrize('attack', ['legacy', 'company', 'year', 'digest', 'confirmation', 'command'])
def test_invalid_or_out_of_scope_source_cannot_request_proof(attack):
    h = coherent()
    source = prepared(h, context(h))
    request = h.command
    if attack == 'legacy': source = Harness().capture()
    elif attack == 'company': request = replace(request, company_id=type(request.company_id)(identifier(993)))
    elif attack == 'year': request = replace(request, income_year=type(request.income_year)(2027))
    elif attack == 'digest': source = replace(source, source_sha256='f' * 64)
    elif attack == 'confirmation': source = replace(source, confirmed_at=h.original.confirmed_at)
    else: source = replace(source, command=replace(source.command, correction_reason='Modified retained request'))
    connection = Connection(None)
    with pytest.raises(rf.Rf1086YearSourceError):
        asyncio.run(scope(connection, request).prepare_source_governance_proof(source))
    assert not connection.calls


@pytest.mark.parametrize('source_sha', [None, 7, b'a' * 64, '', 'a' * 63, 'a' * 65, 'A' * 64, 'g' * 64, '\u0430' * 64])
def test_owner_adapter_refuses_noncanonical_sha_before_sql(source_sha):
    connection = Connection(None)
    adapter = PostgresCorporateReportingEvidence(connection, query().actor_id)
    with pytest.raises(gov.CorporateGovernanceError):
        asyncio.run(adapter.prepare_rf_year_source_governance_proof(
            company_id=query().company_id, income_year=query().income_year, source_sha256=source_sha))
    assert not connection.calls


@pytest.mark.parametrize('status', [TransactionStatus.IDLE, TransactionStatus.INERROR, TransactionStatus.UNKNOWN])
def test_owner_adapter_requires_its_existing_transaction(status):
    connection = Connection(None, status=status)
    adapter = PostgresCorporateReportingEvidence(connection, query().actor_id)
    with pytest.raises(gov.CorporateGovernanceError):
        asyncio.run(adapter.prepare_rf_year_source_governance_proof(
            company_id=query().company_id, income_year=query().income_year, source_sha256='a' * 64))
    assert not connection.calls


@pytest.mark.parametrize('action', ['read', 'proof'])
@pytest.mark.parametrize('message,category', [
    ('corporate_governance_forbidden', ErrorCategory.FORBIDDEN),
    ('ledger_forbidden', ErrorCategory.FORBIDDEN),
    ('corporate_governance_reporting_guard_required', ErrorCategory.DEPENDENCY_UNAVAILABLE),
    ('rf1086_source_governance_evidence_changed', ErrorCategory.DEPENDENCY_UNAVAILABLE),
    ('permission denied for function prepare_rf_year_source_governance_proof_v1', ErrorCategory.DEPENDENCY_UNAVAILABLE),
])
def test_closed_authority_and_producer_failures_never_retry_or_expose_sql(action, message, category):
    h = coherent()
    source = prepared(h, context(h))
    connection = Connection(None, error=psycopg.DatabaseError(message + ' private-token=synthetic-secret'))
    held = scope(connection, h.command)
    with pytest.raises(gov.CorporateGovernanceError) as failure:
        asyncio.run(held.governance_register_evidence(CorrelationId('held-register')) if action == 'read'
            else held.prepare_source_governance_proof(source))
    assert failure.value.category is category
    assert 'private-token' not in str(failure.value) and 'synthetic-secret' not in str(failure.value)
    assert len(connection.calls) == 1


@pytest.mark.parametrize('message,category', [
    ('rf1086_forbidden', ErrorCategory.FORBIDDEN),
    ('rf1086_source_approval_guard_required', ErrorCategory.DEPENDENCY_UNAVAILABLE),
    ('rf1086_source_storage_invalid', ErrorCategory.DEPENDENCY_UNAVAILABLE),
])
def test_actual_rf_receiver_errors_keep_safe_typed_categories(message, category):
    h = coherent()
    source = prepared(h, context(h))
    connection = Connection(None, error=psycopg.DatabaseError(message + ' private-token=synthetic-secret'))
    with pytest.raises(gov.CorporateGovernanceError) as failure:
        asyncio.run(scope(connection, h.command).prepare_source_governance_proof(source))
    assert failure.value.category is category
    assert 'private-token' not in str(failure.value) and 'synthetic-secret' not in str(failure.value)
    assert len(connection.calls) == 1
