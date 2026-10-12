"""Company-scoped test history: integrity values, never filing authority."""
from dataclasses import fields
from datetime import datetime
from hashlib import sha256
import json
from uuid import UUID

from . import public as rf

CODEC = 'rf1086-company-test-retention-v1'
SCOPE = 'company_no_intrinsic_income_year'
MAX_BYTES = 64 * 1024 * 1024
MAX_RECORDS = 100_000
MAX_RECORD_BYTES = 256 * 1024
MAX_TEXT_BYTES = 64 * 1024
RECORD_KEYS = ('id', 'company_id', 'obligation', 'environment', 'status',
    'test_reference', 'feedback_summary', 'receipt_reference', 'archive_reference',
    'evidence_url', 'payload_hash', 'recorded_by', 'recorded_at')
TEXT_KEYS = ('obligation', 'environment', 'status', 'test_reference', 'feedback_summary',
    'receipt_reference', 'archive_reference', 'evidence_url', 'payload_hash')
OPTIONAL_KEYS = frozenset(('receipt_reference', 'archive_reference', 'evidence_url', 'payload_hash'))
BASE_KEYS = frozenset(('codec', 'companyId', 'scope', 'coverage'))
COMPLETE_KEYS = BASE_KEYS | {'observedAt', 'recordCount', 'recordsSha256', 'records'}


def _require(condition):
    if not condition:
        raise rf.Rf1086ArchiveError('rf1086_company_test_retention_invalid')


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _uuid(value):
    _require(type(value) is str and len(value) == 36)
    try:
        _require(str(UUID(value)) == value)
    except ValueError:
        raise rf.Rf1086ArchiveError('rf1086_company_test_retention_invalid') from None


def _time(value):
    _require(type(value) is str and len(value) <= 64)
    try:
        _require(datetime.fromisoformat(value).utcoffset() is not None)
    except ValueError:
        raise rf.Rf1086ArchiveError('rf1086_company_test_retention_invalid') from None


def _utf8(value):
    try:
        return value.encode('utf-8')
    except UnicodeEncodeError:
        raise rf.Rf1086ArchiveError('rf1086_company_test_retention_invalid') from None


def record_wire(record, company_id):
    _require(type(record) is rf.Rf1086TestEvidenceRecord)
    _require(tuple(field.name for field in fields(record)) == RECORD_KEYS)
    value = {key: getattr(record, key) for key in RECORD_KEYS}
    for key in ('id', 'company_id', 'recorded_by'):
        _uuid(value[key])
    _require(value['company_id'] == str(company_id) and value['obligation'] == 'aksjonaerregisteroppgaven')
    _time(value['recorded_at'])
    for key in TEXT_KEYS:
        text = value[key]
        if text is None and key in OPTIONAL_KEYS:
            continue
        _require(type(text) is str and len(text) <= MAX_TEXT_BYTES)
        _require(len(_utf8(text)) <= MAX_TEXT_BYTES)
    _require(bool(value['environment']) and bool(value['status']) and bool(value['test_reference']))
    _require(len(_utf8(_json(value))) <= MAX_RECORD_BYTES)
    return value


def prepare(company_id, observed_at, records):
    """Pure structural capture value; only the owning query establishes origin."""
    _require(type(records) is tuple and len(records) <= MAX_RECORDS)
    capture = Capture(company_id, observed_at)
    for record in records:
        capture.add(record)
    return capture.complete()


class Capture:
    """Bounded RF-owned accumulation; no partial value is a complete snapshot."""
    def __init__(self, company_id, observed_at):
        _uuid(str(company_id))
        _time(observed_at)
        self._company_id, self._observed_at = company_id, observed_at
        self._records = []
        self._digest, self._total, self._closed = sha256(b'['), 2, False
        largest = rf.Rf1086CompanyTestRetentionSnapshot(company_id, 'complete', observed_at,
            (), MAX_RECORDS, '0' * 64)
        self._envelope_bytes = len(_json(_complete_wire(largest, [])).encode('utf-8')) - 2

    def add(self, record):
        try:
            _require(not self._closed and len(self._records) < MAX_RECORDS)
            value = record_wire(record, self._company_id)
            _require(not self._records or self._records[-1].id < record.id)
            encoded = _json(value).encode('utf-8')
            extra = len(encoded) + bool(self._records)
            _require(self._total + extra + self._envelope_bytes <= MAX_BYTES)
            if self._records:
                self._digest.update(b',')
            self._digest.update(encoded)
            self._total += extra
            self._records.append(record)
        except rf.Rf1086ArchiveError:
            self._closed = True
            raise

    def complete(self):
        _require(not self._closed)
        self._closed = True
        self._digest.update(b']')
        return rf.Rf1086CompanyTestRetentionSnapshot(self._company_id, 'complete', self._observed_at,
            tuple(self._records), len(self._records), self._digest.hexdigest())


def _complete_wire(snapshot, records):
    return {'codec': CODEC, 'companyId': str(snapshot.company_id), 'scope': SCOPE,
        'coverage': 'complete', 'observedAt': snapshot.observed_at,
        'recordCount': snapshot.record_count, 'recordsSha256': snapshot.records_sha256,
        'records': records}


def serialize(snapshot):
    _require(type(snapshot) is rf.Rf1086CompanyTestRetentionSnapshot)
    _uuid(str(snapshot.company_id))
    if snapshot.coverage == 'unavailable':
        _require(all(getattr(snapshot, name) is None for name in
            ('observed_at', 'records', 'record_count', 'records_sha256')))
        return _json({'codec': CODEC, 'companyId': str(snapshot.company_id), 'scope': SCOPE,
            'coverage': 'unavailable'})
    _require(snapshot.coverage == 'complete' and type(snapshot.record_count) is int)
    rebuilt = prepare(snapshot.company_id, snapshot.observed_at, snapshot.records)
    _require(rebuilt == snapshot)
    return _json(_complete_wire(snapshot, [record_wire(row, snapshot.company_id) for row in snapshot.records]))


def parse(text, *, company_id):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result)
            result[key] = value
        return result
    try:
        _require(type(text) is str and len(text) <= MAX_BYTES and len(text.encode('utf-8')) <= MAX_BYTES)
        value = json.loads(text, object_pairs_hook=unique,
            parse_constant=lambda _: (_require(False)))
        _require(type(value) is dict and value.get('codec') == CODEC and value.get('scope') == SCOPE)
        _require(value.get('companyId') == str(company_id))
        if value.get('coverage') == 'unavailable':
            _require(set(value) == BASE_KEYS)
            result = rf.Rf1086CompanyTestRetentionSnapshot(company_id, 'unavailable', None, None, None, None)
        else:
            _require(set(value) == COMPLETE_KEYS and value['coverage'] == 'complete')
            _require(type(value['records']) is list and len(value['records']) <= MAX_RECORDS)
            records = []
            for row in value['records']:
                _require(type(row) is dict and set(row) == set(RECORD_KEYS))
                records.append(rf.Rf1086TestEvidenceRecord(**row))
            result = prepare(company_id, value['observedAt'], tuple(records))
            _require(type(value['recordCount']) is int and value['recordCount'] == result.record_count
                and value['recordsSha256'] == result.records_sha256)
        _require(serialize(result) == text)
        return result
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise rf.Rf1086ArchiveError('rf1086_company_test_retention_invalid') from None


def assert_source_matches(candidate, expected):
    left, right = serialize(candidate), serialize(expected)
    _require(candidate.coverage == expected.coverage == 'complete')
    _require(left == right)


def assert_target_matches(source, target):
    # Verify each complete value independently; target metadata is its own.
    serialize(source)
    serialize(target)
    _require(source.coverage == target.coverage == 'complete')
    _require(all(getattr(source, name) == getattr(target, name) for name in
        ('company_id', 'records', 'record_count', 'records_sha256')))
