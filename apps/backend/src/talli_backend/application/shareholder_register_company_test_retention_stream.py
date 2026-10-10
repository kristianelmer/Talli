"""Bounded standalone framing; portable integrity never establishes source origin."""
from dataclasses import asdict
from hashlib import sha256
import json
from typing import BinaryIO, Iterator

from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId

CODEC = 'rf1086-company-test-retention-stream-v1'
ARTIFACT_CODEC = 'rf1086-company-test-retention-v1'
SCOPE = 'company_no_intrinsic_income_year'
MAX_BYTES = 72 * 1024 * 1024
HEADER_BYTES = 4096
RECORD_BYTES = 256 * 1024 + 64
FOOTER_BYTES = 1024
HEADER_KEYS = frozenset(('codec', 'artifactCodec', 'companyId', 'scope', 'observedAt',
    'recordCount', 'recordsSha256', 'artifactSha256'))


def _require(condition: bool) -> None:
    if not condition:
        raise rf.Rf1086ArchiveError('rf1086_company_test_retention_stream_invalid')


def _frame(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
        separators=(',', ':')) + '\n').encode('utf-8')


def _digest(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def stream_company_test_retention(snapshot: rf.Rf1086CompanyTestRetentionSnapshot) -> Iterator[bytes]:
    """Validate the entire immutable capture before emitting its first frame."""
    artifact = rf.serialize_rf1086_company_test_retention(snapshot).encode('utf-8')
    _require(snapshot.coverage == 'complete')
    header = _frame({'codec': CODEC, 'artifactCodec': ARTIFACT_CODEC,
        'companyId': str(snapshot.company_id), 'scope': SCOPE, 'observedAt': snapshot.observed_at,
        'recordCount': snapshot.record_count, 'recordsSha256': snapshot.records_sha256,
        'artifactSha256': sha256(artifact).hexdigest()})
    _require(len(header) <= HEADER_BYTES)
    digest, total = sha256(header), len(header)
    yield header
    for record in snapshot.records:
        frame = _frame({'kind': 'record', 'record': asdict(record)})
        total += len(frame)
        _require(len(frame) <= RECORD_BYTES and total <= MAX_BYTES - FOOTER_BYTES)
        digest.update(frame)
        yield frame
    footer = _frame({'kind': 'complete', 'recordCount': snapshot.record_count,
        'sha256': digest.hexdigest()})
    _require(len(footer) <= FOOTER_BYTES and total + len(footer) <= MAX_BYTES)
    yield footer


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


class _Frames:
    def __init__(self, source: BinaryIO):
        self.source, self.total = source, 0

    def read(self, limit: int) -> tuple[dict, bytes]:
        raw = self.source.readline(min(limit, MAX_BYTES - self.total) + 1)
        self.total += len(raw)
        _require(type(raw) is bytes and 0 < len(raw) <= limit and self.total <= MAX_BYTES
            and raw.endswith(b'\n'))
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique,
            parse_constant=lambda _: _require(False))
        _require(type(value) is dict and _frame(value) == raw)
        return value, raw


def verify_company_test_retention_stream(source: BinaryIO, *, company_id: CompanyId) -> rf.Rf1086CompanyTestRetentionSnapshot:
    """Return a structural capture only after completion and exact EOF."""
    try:
        frames = _Frames(source)
        header, raw = frames.read(HEADER_BYTES)
        _require(set(header) == HEADER_KEYS and header['codec'] == CODEC
            and header['artifactCodec'] == ARTIFACT_CODEC and header['scope'] == SCOPE
            and header['companyId'] == str(company_id))
        bounds = rf.rf1086_company_test_retention_bounds()
        _require(type(header['recordCount']) is int and 0 <= header['recordCount'] <= bounds.max_records
            and _digest(header['recordsSha256']) and _digest(header['artifactSha256']))
        capture = rf.create_rf1086_company_test_retention_capture(company_id, header['observedAt'])
        digest = sha256(raw)
        for _ in range(header['recordCount']):
            value, raw = frames.read(RECORD_BYTES)
            _require(set(value) == {'kind', 'record'} and value['kind'] == 'record'
                and type(value['record']) is dict)
            capture.add(rf.Rf1086TestEvidenceRecord(**value['record']))
            digest.update(raw)
        footer, _ = frames.read(FOOTER_BYTES)
        _require(set(footer) == {'kind', 'recordCount', 'sha256'} and footer['kind'] == 'complete'
            and type(footer['recordCount']) is int and footer['recordCount'] == header['recordCount']
            and footer['sha256'] == digest.hexdigest() and source.read(1) == b'')
        snapshot = capture.complete()
        artifact = rf.serialize_rf1086_company_test_retention(snapshot).encode('utf-8')
        _require(snapshot.records_sha256 == header['recordsSha256']
            and sha256(artifact).hexdigest() == header['artifactSha256'])
        return snapshot
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise rf.Rf1086ArchiveError('rf1086_company_test_retention_stream_invalid') from None
