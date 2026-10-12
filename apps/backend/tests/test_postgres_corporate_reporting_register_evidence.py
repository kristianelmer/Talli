"""Both actual adapter paths decode one guarded, company-wide SQL projection."""
import asyncio
from collections.abc import Mapping
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import psycopg
from psycopg.pq import TransactionStatus
import pytest

from talli_backend.adapters.postgres_corporate_reporting_evidence import PostgresCorporateReportingEvidence
from talli_backend.application.corporate_governance_workflow import CorporateGovernanceApplication
from talli_backend.modules.corporate_governance import public as gov
from talli_backend.shared.kernel import ErrorCategory
from test_corporate_governance_reporting_register_evidence import query, original, snapshot, build, manifest, digest
from test_corporate_register_evidence_amendment import fixture, follow, identifier
from test_postgres_corporate_reporting_evidence import payload as old_payload, Connection as ExistingConnection
from test_supabase_corporate_governance import bound_transaction
from test_supabase_corporate_register_evidence_amendment import chain_payload


def payload(anchors=(), histories=(), *, rows=None, amendments=(), year=2026):
    histories = histories or ((),) * len(anchors)
    chains = tuple(snapshot(anchor, history) for anchor, history in zip(anchors, histories))
    inputs = old_payload(events=tuple(a.original for a in anchors) if rows is None else rows, amendments=amendments)
    inputs.update(companyId=str(query().company_id), incomeYear=year)
    # The old test wire helper intentionally leaves frozen canonical Mapping
    # values intact. SQL JSON decoding supplies ordinary objects instead.
    def plain(value):
        if isinstance(value, Mapping): return {key:plain(item) for key,item in value.items()}
        if isinstance(value, (tuple,list)): return [plain(item) for item in value]
        return value
    inputs = plain(inputs)
    return dict(codec='corporate-reporting-register-evidence-v1', company_id=str(query().company_id), income_year=year,
        reporting_inputs=inputs, register_chains=[chain_payload(a, h) for a, h in sorted(zip(anchors, histories), key=lambda pair:str(pair[0].original.event.event_id))],
        chain_count=len(chains), chain_enumeration_sha256=manifest(chains, year=year))


class Connection(ExistingConnection):
    async def fetchall(self): return [{'result':self.value}]


def reader(value, path='same_connection', *, status=TransactionStatus.INTRANS, error=None, actor=None):
    conn = Connection(value, status=status, error=error)
    q = query()
    if path == 'same_connection':
        target = PostgresCorporateReportingEvidence(conn, actor or q.actor_id)
    else:
        target = bound_transaction()
        target._verified = replace(target._verified, actor_id=actor or q.actor_id)
        target._connection = conn
    return target, conn


def read(target):
    return asyncio.run(target.read_reporting_year_register_evidence(query()))


@pytest.mark.parametrize('path', ['same_connection', 'workflow_transaction'])
@pytest.mark.parametrize('count', [0, 1, 2])
def test_both_adapters_use_one_named_query_exact_scope_and_complete_original_chains(path, count):
    anchor, _, _, first = fixture(); history = (first, follow(first))[:count]
    target, conn = reader(payload((anchor,), (history,)), path)
    result = read(target)
    assert result == build((anchor.original,), (snapshot(anchor, history),))
    assert len(conn.calls) == 1
    assert conn.calls[0][0].startswith('select corporate_governance.read_guarded_reporting_register_evidence_v1(')
    assert conn.calls[0][1] == (str(query().company_id), 2026, str(query().actor_id.subject))


@pytest.mark.parametrize('status', [TransactionStatus.IDLE, TransactionStatus.INERROR, TransactionStatus.UNKNOWN])
def test_same_connection_reader_requires_existing_transaction_without_opening_one(status):
    target, conn = reader(payload(), status=status)
    with pytest.raises(gov.CorporateGovernanceError): read(target)
    assert not conn.calls


@pytest.mark.parametrize('path', ['same_connection', 'workflow_transaction'])
def test_mismatched_verified_actor_never_queries(path):
    target, conn = reader(payload(), path, actor=replace(query().actor_id, subject=type(query().actor_id.subject)(identifier(998))))
    with pytest.raises(gov.CorporateGovernanceError) as failure: read(target)
    assert failure.value.category is ErrorCategory.FORBIDDEN and not conn.calls


@pytest.mark.parametrize('path', ['same_connection', 'workflow_transaction'])
@pytest.mark.parametrize('attack', ['null', 'unknown_codec', 'extra', 'missing', 'bool_year', 'float_count', 'bool_count',
    'wrong_scope', 'wrong_year', 'wrong_count', 'wrong_digest', 'missing_chain', 'duplicate_chain', 'extra_chain',
    'wrong_original', 'wrong_inner_scope', 'missing_receipt', 'wrong_head', 'wrong_effective', 'malformed_old_inputs'])
def test_no_missing_malformed_or_partial_projection_falls_back_to_old_success(path, attack):
    anchor, _, _, first = fixture(); second = follow(first)
    value = payload((anchor,), ((first, second),))
    if attack == 'null': value = None
    elif attack == 'unknown_codec': value['codec'] = 'future-version'
    elif attack == 'extra': value['trusted'] = True
    elif attack == 'missing': del value['chain_count']
    elif attack == 'bool_year': value['income_year'] = True
    elif attack in ('float_count','bool_count'): value['chain_count'] = 1.0 if attack == 'float_count' else True
    elif attack == 'wrong_scope': value['company_id'] = identifier(998)
    elif attack == 'wrong_year': value['income_year'] = 2025
    elif attack == 'wrong_count': value['chain_count'] = 0
    elif attack == 'wrong_digest': value['chain_enumeration_sha256'] = 'f'*64
    elif attack == 'missing_chain':
        value['register_chains'] = []; value['chain_count'] = 0; value['chain_enumeration_sha256'] = manifest(())
    elif attack == 'duplicate_chain': value['register_chains'] *= 2
    elif attack == 'extra_chain': value['register_chains'].append(chain_payload(original(number=25)))
    elif attack == 'wrong_original': value['reporting_inputs']['supportedEvents'][0]['recordedAt'] = '2026-10-09T12:30:45.123457+00:00'
    elif attack == 'wrong_inner_scope': value['reporting_inputs']['companyId'] = identifier(998)
    elif attack == 'missing_receipt': value['register_chains'][0]['amendments'].pop(0)
    elif attack == 'wrong_head': value['register_chains'][0]['head'] = None
    elif attack == 'wrong_effective': value['register_chains'][0]['effective_register_fact']['fact_sha256'] = 'f'*64
    else: del value['reporting_inputs']['lifecycle']['finalizations']
    target, conn = reader(value, path)
    with pytest.raises(gov.CorporateGovernanceError) as failure: read(target)
    assert failure.value.category is ErrorCategory.DEPENDENCY_UNAVAILABLE
    assert len(conn.calls) == 1


@pytest.mark.parametrize('path', ['same_connection', 'workflow_transaction'])
@pytest.mark.parametrize('message,category', [('corporate_governance_forbidden',ErrorCategory.FORBIDDEN),
    ('corporate_governance_reporting_guard_required',ErrorCategory.DEPENDENCY_UNAVAILABLE),
    ('corporate_register_evidence_storage_invalid',ErrorCategory.DEPENDENCY_UNAVAILABLE),
    ('function corporate_governance.read_guarded_reporting_register_evidence_v1 does not exist',ErrorCategory.DEPENDENCY_UNAVAILABLE)])
def test_auth_guard_storage_and_old_backend_failures_are_safe_and_never_retry(path, message, category):
    target, conn = reader(None, path, error=psycopg.DatabaseError(message + ' private-token=secret'))
    with pytest.raises(gov.CorporateGovernanceError) as failure: read(target)
    assert failure.value.category is category and 'private-token' not in str(failure.value)
    assert len(conn.calls) == 1


def test_old_inputs_are_untouched_including_canonical_json_number_representation():
    anchor = original(kind='cash_capital_increase')
    value = payload((anchor,))
    # JSONB can emit a numeric scalar unrelated to the unchanged old builder.
    # New chain commitments must not demand amendment-codec canonical bytes for
    # arbitrary old facts. Use an ineligible earlier phase for this old shape.
    earlier = original(kind='cash_capital_increase', phase='binding_subscription', number=24, anchored=False)
    facts = dict(earlier.event.canonical_facts); facts['retainedLegacyNumeric'] = 1.0
    earlier = replace(earlier, event=replace(earlier.event, canonical_facts=facts))
    value = payload((anchor,), rows=(anchor.original, earlier))
    before = deepcopy(value['reporting_inputs'])
    result = read(reader(value)[0])
    assert value['reporting_inputs'] == before
    assert result == build((anchor.original, earlier), (snapshot(anchor),))


def application(value, *, actor=None, role='owner', error=None):
    calls = []; active = False
    class Transaction:
        async def actor_role(self, company):
            assert active and company == query().company_id; calls.append('role'); return role
        async def read_reporting_year_register_evidence(self, request):
            assert active and request == query(); calls.append('projection')
            if error: raise error
            return value
    class Session:
        actor_id = actor or query().actor_id
        @asynccontextmanager
        async def transaction(self, *, guarded_company_id):
            nonlocal active
            assert guarded_company_id == query().company_id; calls.append('guard'); active = True
            try: yield Transaction()
            finally: active = False; calls.append('released')
    class Factory:
        async def session(self, token):
            assert token == 'verified-test'; return Session()
    def forbidden_dependency(*args, **kwargs): raise AssertionError('Reporting read must not construct another owner dependency')
    return CorporateGovernanceApplication(Factory(), None, forbidden_dependency), calls


def run_app(app): return asyncio.run(app.read_reporting_year_register_evidence('verified-test', query()))


def test_application_uses_single_guarded_read_without_ledger_or_external_evidence_io():
    value = build(); app, calls = application(value)
    assert run_app(app) == value
    assert calls == ['guard','role','projection','released']


@pytest.mark.parametrize('failure', ['actor','owner','unavailable','typed_digest','typed_scope'])
def test_application_revalidates_typed_result_and_never_falls_back(failure):
    value = build(); options = {}
    if failure == 'actor': options['actor'] = replace(query().actor_id, subject=type(query().actor_id.subject)(identifier(998)))
    elif failure == 'owner': options['role'] = 'read_only'
    elif failure == 'unavailable': options['error'] = gov.CorporateGovernanceError.unavailable()
    elif failure == 'typed_digest': value = replace(value, enumeration_sha256='f'*64)
    else: value = replace(value, query=replace(query(), income_year=type(query().income_year)(2025)))
    app, calls = application(value, **options)
    with pytest.raises(gov.CorporateGovernanceError): run_app(app)
    assert calls.count('projection') <= 1
    if failure in ('actor','owner'): assert 'projection' not in calls
