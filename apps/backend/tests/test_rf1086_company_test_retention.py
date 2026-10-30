"""Company inventory integrity and acquisition; portable bytes are not origin proof."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from types import SimpleNamespace
from uuid import UUID

import pytest

from talli_backend.adapters.postgres_shareholder_register_filing import PostgresShareholderRegisterFilingSession
from talli_backend.application.shareholder_register_company_test_retention import ShareholderRegisterCompanyTestRetention
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, UserId

COMPANY = CompanyId('00000000-0000-0000-0000-000000000001')
ACTOR = ActorId(ActorKind.USER, UserId('00000000-0000-0000-0000-000000000002'))
OBSERVED = '2026-10-11T00:00:00+02:00'


def record(number=3, **changes):
    return replace(rf.Rf1086TestEvidenceRecord(
        id=str(UUID(int=number)), company_id=str(COMPANY), obligation='aksjonaerregisteroppgaven',
        environment='manual_evidence', status='accepted', test_reference='Original ø reference',
        feedback_summary='Exact\nfeedback', receipt_reference=None, archive_reference='opaque/archive',
        evidence_url='https://unreachable.invalid/original?opaque=yes', payload_hash=None,
        recorded_by=str(ACTOR.subject), recorded_at='2025-12-31T23:59:59+00:00'), **changes)


def capture(*records, observed_at=OBSERVED):
    return rf.prepare_rf1086_company_test_retention(COMPANY, observed_at, tuple(records))


def wire(snapshot):
    return rf.serialize_rf1086_company_test_retention(snapshot)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def test_exact_thirteen_original_fields_and_no_intrinsic_year():
    original = record(status='historic-status', environment='historic-environment', payload_hash='a'*64)
    snapshot = capture(original)
    value = json.loads(wire(snapshot))
    assert value['records'] == [asdict(original)] and len(value['records'][0]) == 13
    assert value['scope'] == 'company_no_intrinsic_income_year'
    assert 'incomeYear' not in value and 'income_year' not in value['records'][0]
    assert value['recordCount'] == 1
    assert value['recordsSha256'] == sha256(canonical([asdict(original)]).encode()).hexdigest()
    assert rf.parse_rf1086_company_test_retention(wire(snapshot), company_id=COMPANY) == snapshot


def test_complete_zero_and_unavailable_are_distinct():
    zero = capture()
    unavailable = rf.Rf1086CompanyTestRetentionSnapshot(COMPANY, 'unavailable', None, None, None, None)
    assert zero.record_count == 0 and zero.records == ()
    assert zero.records_sha256 == sha256(b'[]').hexdigest()
    assert set(json.loads(wire(unavailable))) == {'codec', 'companyId', 'scope', 'coverage'}
    assert rf.parse_rf1086_company_test_retention(wire(unavailable), company_id=COMPANY) == unavailable
    for value in [zero, unavailable]:
        assert rf.parse_rf1086_company_test_retention(wire(value), company_id=COMPANY) == value
    with pytest.raises(rf.Rf1086ArchiveError):
        wire(replace(unavailable, record_count=0))


def test_recomputed_omission_is_structural_only_and_fails_independent_expectation():
    expected = capture(record(), record(4))
    omitted = capture(record())
    parsed = rf.parse_rf1086_company_test_retention(wire(omitted), company_id=COMPANY)
    assert parsed == omitted
    with pytest.raises(rf.Rf1086ArchiveError):
        rf.assert_company_test_retention_source_capture_matches(parsed, expected)
    with pytest.raises(rf.Rf1086ArchiveError):
        rf.assert_company_test_retention_target_inventory_matches(expected, parsed)


def test_fresh_target_observation_preserves_inventory_without_rewriting_source_time():
    source = capture(record())
    target = capture(record(), observed_at='2026-10-12T01:02:03+00:00')
    assert wire(source) != wire(target)
    rf.assert_company_test_retention_target_inventory_matches(source, target)
    with pytest.raises(rf.Rf1086ArchiveError):
        rf.assert_company_test_retention_source_capture_matches(target, source)
    assert source.observed_at == OBSERVED
    rf.assert_company_test_retention_source_capture_matches(source, source)


@pytest.mark.parametrize('field,value', [
    ('id', 'invalid-uuid'), ('id', 'x'*36), ('company_id', str(UUID(int=9))), ('recorded_by', 'invalid-uuid'),
    ('recorded_at', 'invalid-time'), ('recorded_at', '2026-10-11T00:00:00'),
    ('obligation', 'another-obligation'), ('environment', ''), ('status', ''),
    ('test_reference', ''), ('feedback_summary', None), ('receipt_reference', 123),
    ('payload_hash', 123), ('feedback_summary', '\ud800'),
])
def test_invalid_original_record_is_a_typed_domain_error(field, value):
    with pytest.raises(rf.Rf1086ArchiveError):
        capture(record(**{field: value}))


@pytest.mark.parametrize('original', [None, 'a'*64, 'A'*64, 'sha256:provider/ø', 'x', '', ' original hash '])
def test_original_nullable_payload_hash_is_opaque_and_preserved(original):
    snapshot = capture(record(payload_hash=original))
    parsed = rf.parse_rf1086_company_test_retention(wire(snapshot), company_id=COMPANY)
    assert parsed.records[0].payload_hash == original
    assert json.loads(wire(parsed))['records'][0]['payload_hash'] == original
    rf.assert_company_test_retention_source_capture_matches(parsed, snapshot)


@pytest.mark.parametrize('mutation', ['scope', 'company', 'codec', 'extra', 'count', 'bool-count',
    'digest', 'row-extra', 'row-missing', 'order', 'duplicate-id', 'observed-naive'])
def test_malformed_inventory_denies_even_when_other_metadata_is_retained(mutation):
    value = json.loads(wire(capture(record(), record(4))))
    if mutation == 'scope': value['scope'] = 'income_year'
    elif mutation == 'company': value['companyId'] = str(UUID(int=9))
    elif mutation == 'codec': value['codec'] = 'rf1086-archive-v6'
    elif mutation == 'extra': value['incomeYear'] = 2025
    elif mutation == 'count': value['recordCount'] = 1
    elif mutation == 'bool-count': value['recordCount'] = True
    elif mutation == 'digest': value['recordsSha256'] = '0'*64
    elif mutation == 'row-extra': value['records'][0]['income_year'] = 2025
    elif mutation == 'row-missing': del value['records'][0]['recorded_by']
    elif mutation == 'order': value['records'].reverse()
    elif mutation == 'duplicate-id': value['records'][1]['id'] = value['records'][0]['id']
    else: value['observedAt'] = '2026-10-11T00:00:00'
    with pytest.raises(rf.Rf1086ArchiveError):
        rf.parse_rf1086_company_test_retention(canonical(value), company_id=COMPANY)


@pytest.mark.parametrize('text', ['{}', '[]', '{"codec":NaN}', '{"codec":1,"codec":2}',
    '{"records":Infinity}', '\ud800'])
def test_unparseable_duplicate_and_nonfinite_inputs_are_typed(text):
    with pytest.raises(rf.Rf1086ArchiveError):
        rf.parse_rf1086_company_test_retention(text, company_id=COMPANY)


def test_noncanonical_bytes_and_forged_snapshot_denied():
    snapshot = capture(record())
    with pytest.raises(rf.Rf1086ArchiveError):
        rf.parse_rf1086_company_test_retention(wire(snapshot)+'\n', company_id=COMPANY)
    with pytest.raises(rf.Rf1086ArchiveError): wire(replace(snapshot, records_sha256='0'*64))
    with pytest.raises(rf.Rf1086ArchiveError): capture(record(4), record())
    with pytest.raises(rf.Rf1086ArchiveError): capture(record(), record())


@pytest.mark.parametrize('text', ['x'*65536, 'ø'*32768])
def test_exact_text_utf8_boundary_and_plus_one(text):
    capture(record(feedback_summary=text))
    with pytest.raises(rf.Rf1086ArchiveError): capture(record(feedback_summary=text+'x'))


def test_control_escape_expansion_is_bounded_after_raw_text_validation():
    # Each field is under64KiB raw, but its JSON escape expansion exceeds256KiB.
    with pytest.raises(rf.Rf1086ArchiveError): capture(record(feedback_summary='\x00'*50000))


def test_artifact_accumulation_stops_at_fixed_budget_before_complete():
    accumulator = rf.create_rf1086_company_test_retention_capture(COMPANY, OBSERVED)
    count = 0
    with pytest.raises(rf.Rf1086ArchiveError):
        for number in range(3, 2003):
            accumulator.add(record(number, feedback_summary='x'*65536))
            count += 1
    assert 900 < count < 1100
    # No complete value is returned by the owning query on an add failure.


def test_closed_capture_cannot_append_or_complete_twice():
    accumulator = rf.create_rf1086_company_test_retention_capture(COMPANY, OBSERVED)
    accumulator.add(record()); snapshot = accumulator.complete()
    assert snapshot == capture(record())
    with pytest.raises(rf.Rf1086ArchiveError): accumulator.add(record(4))
    with pytest.raises(rf.Rf1086ArchiveError): accumulator.complete()
    assert rf.rf1086_company_test_retention_bounds().max_records == 100000


@pytest.mark.parametrize('failure', ['duplicate','oversize'])
def test_failed_capture_cannot_later_label_its_partial_inventory_complete(failure):
    accumulator = rf.create_rf1086_company_test_retention_capture(COMPANY, OBSERVED)
    accumulator.add(record())
    bad = record() if failure == 'duplicate' else record(4, feedback_summary='x'*65537)
    with pytest.raises(rf.Rf1086ArchiveError): accumulator.add(bad)
    with pytest.raises(rf.Rf1086ArchiveError): accumulator.complete()


class ForbiddenDependency:
    def __getattr__(self, name):
        raise AssertionError('Historical inventory accessed mutable dependency: '+name)


def acquisition(rows, *, total=None, failure=None):
    traces = []
    class Result:
        async def fetchone(self):
            return {'total': len(rows) if total is None else total,
                'observed_at': datetime(2026, 10, 11, tzinfo=timezone.utc)}
    class Cursor:
        async def __aenter__(self): traces.append('cursor-open'); return self
        async def __aexit__(self, *args): traces.append('cursor-closed')
        async def execute(self, sql, params):
            traces.append(('inventory', sql, params, self.itersize))
        def __aiter__(self):
            async def values():
                if failure: raise failure
                for row in rows: yield row
            return values()
    class Database:
        async def execute(self, sql, params): traces.append(('execute', sql, params)); return Result()
        def cursor(self, *, name):
            assert name.startswith('rf_company_test_retention_')
            return Cursor()
    @asynccontextmanager
    async def transaction(**options):
        traces.append(('transaction', options))
        try: yield Database()
        finally: traces.append('transaction-closed')
    store = PostgresShareholderRegisterFilingSession(SimpleNamespace(database_url='unused'),
        SimpleNamespace(actor_id=ACTOR), access_token='synthetic', billing=ForbiddenDependency(),
        documents=ForbiddenDependency(), company_access=ForbiddenDependency())
    store._transaction = transaction
    return store, traces


def raw_record(number=3):
    value = asdict(record(number))
    for key in ('id', 'company_id', 'recorded_by'): value[key] = UUID(value[key])
    value['recorded_at'] = datetime.fromisoformat(value['recorded_at'])
    value['_retention_oversize'] = False
    return value


def read(store, actor=ACTOR):
    return asyncio.run(store.read_company_test_retention(rf.Rf1086CompanyTestRetentionQuery(COMPANY, actor)))


def test_adapter_reads_full_fixed_scope_in_readonly_snapshot_without_mutable_io():
    store, traces = acquisition([raw_record(), raw_record(4)])
    snapshot = read(store)
    assert snapshot.records == (record(), record(4))
    assert traces[0] == ('transaction', {'snapshot': True, 'read_only': True})
    assert 'assert_member_v1' in traces[1][1]
    query = next(item for item in traces if isinstance(item, tuple) and item[0] == 'inventory')
    assert query[2:] == ((str(COMPANY),), 32)
    assert "where t.company_id=%s::uuid and t.obligation='aksjonaerregisteroppgaven' order by t.id asc" in query[1]
    assert all(term not in query[1].lower() for term in ('income_year', ' limit ', 'recorded_by=', 'status=', 'environment='))
    assert traces[-2:] == ['cursor-closed', 'transaction-closed']


@pytest.mark.parametrize('rows,total', [([], 100001), ([], -1), ([], True),
    ([raw_record()], 2), ([dict(raw_record(), _retention_oversize=True)], 1),
    ([dict(raw_record(), _retention_oversize=None)], 1)])
def test_adapter_cannot_emit_complete_for_count_or_transfer_failure(rows, total):
    store, traces = acquisition(rows, total=total)
    with pytest.raises(rf.ShareholderRegisterFilingError) as denied: read(store)
    assert denied.value.code == rf.ShareholderRegisterFilingErrorCode.DEPENDENCY_UNAVAILABLE
    assert traces[-1] == 'transaction-closed'
    if total in (-1,100001) or type(total) is bool: assert 'cursor-open' not in traces


def test_adapter_actor_mismatch_denies_before_database():
    store, traces = acquisition([])
    other = ActorId(ActorKind.USER, UserId(str(UUID(int=9))))
    with pytest.raises(rf.ShareholderRegisterFilingError): read(store, other)
    assert traces == []


def test_acquisition_cancellation_propagates_and_closes_cursor_and_transaction():
    store, traces = acquisition([raw_record()], failure=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError): read(store)
    assert traces[-2:] == ['cursor-closed', 'transaction-closed']


def test_application_derives_actor_from_authenticated_session_and_reads_company_only():
    store, traces = acquisition([])
    class Sessions:
        async def session(self, token): assert token == 'synthetic-token'; return store
    result = asyncio.run(ShareholderRegisterCompanyTestRetention(Sessions()).read(
        'synthetic-token', company_id=COMPANY))
    assert result.record_count == 0 and result.company_id == COMPANY
    assert traces[-1] == 'transaction-closed'
