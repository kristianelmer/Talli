"""Strict completion and immutable inventory framing, without origin claims."""
import asyncio
from dataclasses import asdict, replace
from hashlib import sha256
from io import BytesIO
import json

import pytest

from talli_backend.application import shareholder_register_company_test_retention_stream as stream
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId
from test_rf1086_company_test_retention import COMPANY, capture, record, wire


def encoded(snapshot):
    return b''.join(stream.stream_company_test_retention(snapshot))


def verify(raw, company=COMPANY):
    return stream.verify_company_test_retention_stream(BytesIO(raw), company_id=company)


def frame(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
        separators=(',', ':')) + '\n').encode()


def frames(raw):
    return [json.loads(line) for line in raw.splitlines()]


def recompute_framing(values):
    prefix = b''.join(frame(value) for value in values[:-1])
    values[-1]['sha256'] = sha256(prefix).hexdigest()
    return prefix + frame(values[-1])


@pytest.mark.parametrize('payload_hash', [None, '', 'A'*64, 'sha256:opaque/ø', ' original hash '])
def test_roundtrip_preserves_originals_and_source_observation(payload_hash):
    original = capture(record(payload_hash=payload_hash), record(4, status='historic'))
    raw = encoded(original)
    parsed = verify(raw)
    assert parsed == original and wire(parsed) == wire(original)
    value = frames(raw)
    assert value[1]['record'] == asdict(original.records[0])
    assert value[0]['observedAt'] == original.observed_at
    assert value[0]['artifactSha256'] == sha256(wire(original).encode()).hexdigest()
    assert value[-1]['sha256'] == sha256(b''.join(raw.splitlines(keepends=True)[:-1])).hexdigest()
    assert 'incomeYear' not in value[0]


def test_complete_zero_and_unavailable_before_header():
    zero = capture()
    assert verify(encoded(zero)) == zero and len(frames(encoded(zero))) == 2
    unavailable = rf.Rf1086CompanyTestRetentionSnapshot(COMPANY, 'unavailable', None, None, None, None)
    producer = stream.stream_company_test_retention(unavailable)
    with pytest.raises(rf.Rf1086ArchiveError):
        next(producer)


def test_malformed_complete_capture_denied_before_header():
    producer = stream.stream_company_test_retention(replace(capture(record()), records_sha256='0'*64))
    with pytest.raises(rf.Rf1086ArchiveError):
        next(producer)


@pytest.mark.parametrize('text', ['ø'*32768, '\u0001'*40000], ids=['utf8-boundary', 'escaped-control'])
def test_utf8_and_control_escape_roundtrip_with_canonical_byte_bounds(text):
    snapshot = capture(record(feedback_summary=text))
    assert verify(encoded(snapshot)) == snapshot


def test_foreign_company_rejects_without_relabeling_source():
    with pytest.raises(rf.Rf1086ArchiveError):
        verify(encoded(capture(record())), CompanyId('00000000-0000-0000-0000-000000000009'))


def test_recomputed_omission_is_structural_and_expected_source_still_rejects():
    expected, omitted = capture(record(), record(4)), capture(record())
    parsed = verify(encoded(omitted))
    assert parsed == omitted
    with pytest.raises(rf.Rf1086ArchiveError):
        rf.assert_company_test_retention_source_capture_matches(parsed, expected)
    target = capture(record(), observed_at='2026-10-12T01:02:03+00:00')
    rf.assert_company_test_retention_target_inventory_matches(parsed, target)
    with pytest.raises(rf.Rf1086ArchiveError):
        rf.assert_company_test_retention_source_capture_matches(target, parsed)


@pytest.mark.parametrize('mutation', ['codec', 'artifact-codec', 'scope', 'company', 'extra-header',
    'bool-count', 'negative-count', 'large-count', 'count', 'records-digest', 'artifact-digest',
    'time', 'record-kind', 'extra-record', 'record-field', 'missing-record-field', 'duplicate-record',
    'reorder', 'drop', 'footer-kind', 'footer-count', 'footer-bool-count', 'footer-hash', 'extra-footer'])
def test_mutated_frames_rejected_even_after_footer_hash_recomputed(mutation):
    values = frames(encoded(capture(record(), record(4))))
    if mutation == 'codec': values[0]['codec'] = 'rf1086-archive-stream-v2'
    elif mutation == 'artifact-codec': values[0]['artifactCodec'] = 'rf1086-archive-v6'
    elif mutation == 'scope': values[0]['scope'] = 'income_year'
    elif mutation == 'company': values[0]['companyId'] = str(CompanyId('00000000-0000-0000-0000-000000000009'))
    elif mutation == 'extra-header': values[0]['incomeYear'] = 2025
    elif mutation == 'bool-count': values[0]['recordCount'] = True
    elif mutation == 'negative-count': values[0]['recordCount'] = -1
    elif mutation == 'large-count': values[0]['recordCount'] = 100001
    elif mutation == 'count': values[0]['recordCount'] = 1
    elif mutation == 'records-digest': values[0]['recordsSha256'] = '0'*64
    elif mutation == 'artifact-digest': values[0]['artifactSha256'] = '0'*64
    elif mutation == 'time': values[0]['observedAt'] = '2026-10-12T01:02:03+00:00'
    elif mutation == 'record-kind': values[1]['kind'] = 'complete'
    elif mutation == 'extra-record': values[1]['extra'] = True
    elif mutation == 'record-field': values[1]['record']['feedback_summary'] = 'changed'
    elif mutation == 'missing-record-field': del values[1]['record']['payload_hash']
    elif mutation == 'duplicate-record': values[2] = values[1]
    elif mutation == 'reorder': values[1], values[2] = values[2], values[1]
    elif mutation == 'drop': del values[1]
    elif mutation == 'footer-kind': values[-1]['kind'] = 'record'
    elif mutation == 'footer-count': values[-1]['recordCount'] = 1
    elif mutation == 'footer-bool-count': values[-1]['recordCount'] = True
    elif mutation == 'extra-footer': values[-1]['extra'] = True
    raw = recompute_framing(values)
    if mutation == 'footer-hash':
        values[-1]['sha256'] = '0'*64
        raw = b''.join(frame(value) for value in values)
    with pytest.raises(rf.Rf1086ArchiveError):
        verify(raw)


@pytest.mark.parametrize('mutation', ['empty', 'no-footer', 'no-final-lf', 'extra-lf', 'extra-space',
    'extra-footer', 'garbage', 'duplicate-key', 'nonfinite', 'noncanonical', 'bad-utf8', 'crlf'])
def test_invalid_framing_and_trailing_bytes(mutation):
    raw = encoded(capture(record()))
    if mutation == 'empty': raw = b''
    elif mutation == 'no-footer': raw = b''.join(raw.splitlines(keepends=True)[:-1])
    elif mutation == 'no-final-lf': raw = raw[:-1]
    elif mutation == 'extra-lf': raw += b'\n'
    elif mutation == 'extra-space': raw += b' '
    elif mutation == 'extra-footer': raw += raw.splitlines(keepends=True)[-1]
    elif mutation == 'garbage': raw += b'private-sentinel'
    elif mutation == 'duplicate-key': raw = raw.replace(b'"codec":', b'"codec":"duplicate","codec":', 1)
    elif mutation == 'nonfinite': raw = raw.replace(b'"recordCount":1', b'"recordCount":NaN', 1)
    elif mutation == 'noncanonical': raw = b' ' + raw
    elif mutation == 'bad-utf8': raw = b'\xff' + raw
    elif mutation == 'crlf': raw = raw.replace(b'\n', b'\r\n')
    with pytest.raises(rf.Rf1086ArchiveError):
        verify(raw)


def test_exact_canonical_record_limit_and_wrapper_size():
    base = record(feedback_summary='', test_reference='x', receipt_reference='', archive_reference='')
    fixed = len(frame(asdict(base))) - 1 - 1
    remaining = 256*1024 - fixed - 3*65536
    row = replace(base, feedback_summary='x'*65536, test_reference='x'*65536,
        receipt_reference='x'*65536, archive_reference='x'*remaining)
    assert len(frame(asdict(row))) - 1 == 256*1024
    raw = encoded(capture(row))
    record_frame = raw.splitlines(keepends=True)[1]
    assert len(b'{"kind":"record","record":') == 26
    assert len(record_frame) == 256*1024 + 28
    assert verify(raw).records == (row,)
    with pytest.raises(rf.Rf1086ArchiveError):
        capture(replace(row, archive_reference=row.archive_reference+'x'))
    assert 64*1024*1024 + 100000*28 + 4096 + 1024 == 69913984 < stream.MAX_BYTES


class BoundedReader(BytesIO):
    def readline(self, size=-1):
        assert 0 < size <= stream.RECORD_BYTES + 1
        return super().readline(size)

    def read(self, size=-1):
        assert size == 1
        return super().read(size)


def test_exact_total_and_plus_one_and_early_bounded_read(monkeypatch):
    raw = encoded(capture(record()))
    monkeypatch.setattr(stream, 'MAX_BYTES', len(raw))
    assert stream.verify_company_test_retention_stream(BoundedReader(raw), company_id=COMPANY) == capture(record())
    monkeypatch.setattr(stream, 'MAX_BYTES', len(raw)-1)
    with pytest.raises(rf.Rf1086ArchiveError):
        stream.verify_company_test_retention_stream(BoundedReader(raw), company_id=COMPANY)


@pytest.mark.parametrize('position', ['header', 'record', 'footer'])
def test_oversized_frame_rejected_with_bounded_read(position):
    raw = encoded(capture(record()))
    lines = raw.splitlines(keepends=True)
    index, limit = {'header': (0, stream.HEADER_BYTES), 'record': (1, stream.RECORD_BYTES),
        'footer': (2, stream.FOOTER_BYTES)}[position]
    lines[index] = b'x'*limit + b'\n'
    with pytest.raises(rf.Rf1086ArchiveError):
        stream.verify_company_test_retention_stream(BoundedReader(b''.join(lines)), company_id=COMPANY)


@pytest.mark.parametrize('after_frames', [1, 2])
def test_cancellation_never_emits_completion_footer(after_frames):
    producer = stream.stream_company_test_retention(capture(record(), record(4)))
    emitted = [next(producer) for _ in range(after_frames)]
    with pytest.raises(asyncio.CancelledError):
        producer.throw(asyncio.CancelledError())
    assert all(json.loads(part).get('kind') != 'complete' for part in emitted)
    assert list(producer) == []


def test_generator_budget_failure_has_no_footer(monkeypatch):
    producer = stream.stream_company_test_retention(capture(record()))
    header = next(producer)
    monkeypatch.setattr(stream, 'MAX_BYTES', len(header)+stream.FOOTER_BYTES)
    with pytest.raises(rf.Rf1086ArchiveError):
        next(producer)
    assert list(producer) == []
