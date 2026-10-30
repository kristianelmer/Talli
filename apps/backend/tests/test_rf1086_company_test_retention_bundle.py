"""Portable commitment, strict ZIP boundaries and independent inventory expectations."""
from dataclasses import asdict, replace
from hashlib import sha256
from io import BytesIO
import json
import struct
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest

from talli_backend.application import shareholder_register_company_test_retention_bundle as bundle
from talli_backend.application import shareholder_register_company_test_retention_stream as stream
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId
from test_rf1086_company_test_retention import COMPANY, capture, record, wire


def verify(raw, company=COMPANY):
    return bundle.verify_company_test_retention_bundle(BytesIO(raw), company_id=company)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
        separators=(',', ':')).encode()


def unpack(raw):
    with ZipFile(BytesIO(raw)) as archive:
        return [archive.read(name) for name in bundle.NAMES]


def repack(contents, *, names=bundle.NAMES, change=None, comment=b''):
    output = BytesIO()
    with ZipFile(output, 'w', allowZip64=False) as archive:
        archive.comment = comment
        for index, (name, content) in enumerate(zip(names, contents, strict=True)):
            entry = ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            entry.create_system, entry.create_version, entry.extract_version = 3, 20, 20
            entry.external_attr = 0o100600 << 16
            if change and index == 0:
                setattr(entry, change[0], change[1])
            archive.writestr(entry, content)
    return output.getvalue()


@pytest.mark.parametrize('payload_hash', [None, '', 'A'*64, 'sha256:opaque/ø', ' original hash '])
def test_deterministic_roundtrip_preserves_all_originals_and_source_bytes(payload_hash):
    source = capture(record(payload_hash=payload_hash), record(4, status='historic',
        environment='unknown-original', recorded_by='00000000-0000-0000-0000-000000000007'))
    raw = bundle.pack_company_test_retention(source)
    assert raw == bundle.pack_company_test_retention(source) == repack(unpack(raw))
    parsed = verify(raw)
    rf.assert_company_test_retention_source_capture_matches(parsed, source)
    manifest, artifact = unpack(raw)
    assert artifact == wire(source).encode()
    assert json.loads(artifact)['records'] == [asdict(row) for row in source.records]
    assert json.loads(manifest)['artifact']['sha256'] == sha256(artifact).hexdigest()
    assert json.loads(manifest)['sourceCapture']['observedAt'] == source.observed_at
    from_stream = stream.verify_company_test_retention_stream(
        BytesIO(b''.join(stream.stream_company_test_retention(source))), company_id=COMPANY)
    assert bundle.pack_company_test_retention(from_stream) == raw


def test_complete_zero_unavailable_and_malformed_capture():
    assert verify(bundle.pack_company_test_retention(capture())) == capture()
    for value in [rf.Rf1086CompanyTestRetentionSnapshot(COMPANY, 'unavailable', None, None, None, None),
            replace(capture(record()), records_sha256='0'*64)]:
        with pytest.raises(rf.Rf1086ArchiveError):
            bundle.pack_company_test_retention(value)


@pytest.mark.parametrize('source,size,digest', [
    (capture(), 1080, '6b4943bf08b4d1753911b1bbfb232faabf34e2d60c2c3e809c781feca20b8130'),
    (capture(record()), 1590, '52b81dca5213d253caad2aa93883cc32b8990937d928bbf755d893b2eaf9cc23'),
])
def test_fixed_portable_v1_bytes(source, size, digest):
    raw = bundle.pack_company_test_retention(source)
    assert len(raw) == size and sha256(raw).hexdigest() == digest
    assert verify(raw) == source


def test_recomputed_omission_does_not_establish_origin_or_completeness():
    independently_obtained = capture(record(), record(4))
    omitted = capture(record())
    parsed = verify(bundle.pack_company_test_retention(omitted))
    assert parsed == omitted
    with pytest.raises(rf.Rf1086ArchiveError):
        rf.assert_company_test_retention_source_capture_matches(parsed, independently_obtained)
    with pytest.raises(rf.Rf1086ArchiveError):
        rf.assert_company_test_retention_target_inventory_matches(independently_obtained, parsed)


def test_target_observation_is_independent_and_source_is_never_rewritten():
    source = capture(record())
    original = bundle.pack_company_test_retention(source)
    target = capture(record(), observed_at='2026-10-12T01:02:03+00:00')
    rf.assert_company_test_retention_target_inventory_matches(source, verify(bundle.pack_company_test_retention(target)))
    with pytest.raises(rf.Rf1086ArchiveError):
        rf.assert_company_test_retention_source_capture_matches(target, source)
    assert bundle.pack_company_test_retention(source) == original


@pytest.mark.parametrize('field,value', [
    ('profile', 'unknown'), ('companyId', '00000000-0000-0000-0000-000000000009'),
    ('scope', 'income_year'), ('coverage', 'unavailable'), ('incomeYear', 2026),
    ('artifact.path', '../company-test-retention.json'), ('artifact.codec', 'unknown'),
    ('artifact.byteLength', True), ('artifact.byteLength', 0), ('artifact.byteLength', 67*1024*1024),
    ('artifact.sha256', 'A'*64), ('artifact.sha256', '0'*64), ('artifact.extra', None),
    ('sourceCapture.observedAt', '2026-10-12T00:00:00+00:00'),
    ('sourceCapture.recordCount', True), ('sourceCapture.recordCount', 2),
    ('sourceCapture.recordsSha256', '0'*64), ('sourceCapture.extra', 'x'),
])
def test_manifest_binding_and_exact_key_types(field, value):
    manifest, artifact = unpack(bundle.pack_company_test_retention(capture(record())))
    data = json.loads(manifest)
    target = data
    parts = field.split('.')
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value
    with pytest.raises(rf.Rf1086ArchiveError):
        verify(repack([canonical(data), artifact]))


@pytest.mark.parametrize('mutate', [
    lambda raw: raw + b' ', lambda raw: b' '+raw,
    lambda raw: raw.replace(b'"coverage":"complete"', b'"coverage":"complete","coverage":"complete"'),
    lambda raw: raw.replace(b'"recordCount":1', b'"recordCount":1e999'),
    lambda raw: raw.replace(b'"recordCount":1', b'"recordCount":NaN'),
    lambda raw: raw.replace(b'"recordCount":1', b'"recordCount":1.0'),
    lambda raw: raw[:-1], lambda raw: raw.replace(b'"profile"', b'"prof\xffile"'),
])
def test_noncanonical_duplicate_nonfinite_and_invalid_utf8_manifest(mutate):
    manifest, artifact = unpack(bundle.pack_company_test_retention(capture(record())))
    with pytest.raises(rf.Rf1086ArchiveError):
        verify(repack([mutate(manifest), artifact]))


@pytest.mark.parametrize('field,value', [
    ('compress_type', ZIP_DEFLATED), ('external_attr', 0o120600 << 16),
    ('external_attr', 0o100644 << 16), ('internal_attr', 1),
    ('create_system', 0), ('create_version', 21), ('extract_version', 45),
    ('date_time', (2026, 1, 1, 0, 0, 0)), ('extra', b'\x01\x00\x00\x00'),
    ('comment', b'comment'),
])
def test_unknown_zip_metadata_and_compression_rejected_before_member_read(monkeypatch, field, value):
    contents = unpack(bundle.pack_company_test_retention(capture(record())))
    raw = repack(contents, change=(field, value))
    def forbidden(*args, **kwargs):
        pytest.fail('rejected ZIP metadata reached member I/O')
    monkeypatch.setattr(ZipFile, 'open', forbidden)
    with pytest.raises(rf.Rf1086ArchiveError):
        verify(raw)


@pytest.mark.parametrize('version', [64, 255])
def test_unsupported_dependency_zip_version_is_a_finite_rf_error_before_member_read(monkeypatch, version):
    raw = bytearray(bundle.pack_company_test_retention(capture(record())))
    offset = raw.find(b'PK\x01\x02')
    raw[offset + 6:offset + 8] = struct.pack('<H', version)
    def forbidden(*args, **kwargs):
        pytest.fail('unsupported ZIP version reached member I/O')
    monkeypatch.setattr(ZipFile, 'open', forbidden)
    with pytest.raises(rf.Rf1086ArchiveError, match='^rf1086_company_test_retention_bundle_invalid$'):
        verify(bytes(raw))


@pytest.mark.parametrize('names', [
    ('manifest.json', 'manifest.json'), tuple(reversed(bundle.NAMES)),
    ('../manifest.json', bundle.NAMES[1]), ('manifest.json/', bundle.NAMES[1]),
    ('other.json', bundle.NAMES[1]),
])
@pytest.mark.filterwarnings('ignore:Duplicate name:UserWarning')
def test_duplicate_order_unknown_and_directory_names(names):
    with pytest.raises(rf.Rf1086ArchiveError):
        verify(repack(unpack(bundle.pack_company_test_retention(capture(record()))), names=names))


@pytest.mark.parametrize('mutation', ['local-flags', 'local-size', 'crc', 'disk', 'count', 'offset',
    'prefix', 'trailing', 'truncated', 'archive-comment', 'concatenated'])
def test_local_central_crc_eof_and_multidisk_boundaries(mutation):
    raw = bytearray(bundle.pack_company_test_retention(capture(record())))
    if mutation == 'local-flags':
        raw[6:8] = struct.pack('<H', 8)
    elif mutation == 'local-size':
        raw[18:22] = struct.pack('<I', 1)
    elif mutation == 'crc':
        raw[30 + len('manifest.json') + 1] ^= 1
    elif mutation == 'disk':
        raw[-18:-16] = struct.pack('<H', 1)
    elif mutation == 'count':
        raw[-12:-10] = struct.pack('<H', 3)
    elif mutation == 'offset':
        raw[-6:-2] = struct.pack('<I', 0)
    elif mutation == 'prefix':
        raw = b'prefix' + raw
    elif mutation == 'trailing':
        raw += b'x'
    elif mutation == 'truncated':
        raw = raw[:-1]
    elif mutation == 'archive-comment':
        raw = repack(unpack(raw), comment=b'x')
    else:
        raw = bytes(raw) * 2
    with pytest.raises(rf.Rf1086ArchiveError):
        verify(bytes(raw))


def test_cross_company_artifact_changes_and_unavailable_are_closed():
    raw = bundle.pack_company_test_retention(capture(record()))
    with pytest.raises(rf.Rf1086ArchiveError):
        verify(raw, CompanyId('00000000-0000-0000-0000-000000000009'))
    manifest, artifact = unpack(raw)
    for changed in [artifact + b' ', artifact.replace(b'Original', b'Changed!'),
            wire(rf.Rf1086CompanyTestRetentionSnapshot(COMPANY, 'unavailable', None, None, None, None)).encode()]:
        with pytest.raises(rf.Rf1086ArchiveError):
            verify(repack([manifest, changed]))


def test_oversized_manifest_and_declared_artifact_rejected_before_member_read(monkeypatch):
    raw = bundle.pack_company_test_retention(capture(record()))
    oversized_manifest = repack([b'x'*4097, unpack(raw)[1]])
    declared = bytearray(raw)
    with ZipFile(BytesIO(raw)) as archive:
        entry = archive.infolist()[1]
    central_offset = raw.find(b'PK\x01\x02', raw.find(b'PK\x01\x02') + 1)
    for offset in (entry.header_offset + 18, central_offset + 20):
        declared[offset:offset + 8] = struct.pack('<II', 64*1024*1024 + 1, 64*1024*1024 + 1)
    def forbidden(*args, **kwargs):
        pytest.fail('oversized entry reached member I/O')
    monkeypatch.setattr(ZipFile, 'open', forbidden)
    for value in [oversized_manifest, bytes(declared)]:
        with pytest.raises(rf.Rf1086ArchiveError):
            verify(value)


def test_whole_package_bound_and_partial_binary_reads(monkeypatch):
    raw = bundle.pack_company_test_retention(capture())
    class Partial:
        def __init__(self):
            self.source = BytesIO(raw)
        def read(self, limit):
            assert limit > 0
            return self.source.read(min(limit, 7))
    assert bundle.verify_company_test_retention_bundle(Partial(), company_id=COMPANY) == capture()
    monkeypatch.setattr(bundle, 'MAX_BYTES', 1024)
    source = BytesIO(b'x'*2048)
    with pytest.raises(rf.Rf1086ArchiveError):
        bundle.verify_company_test_retention_bundle(source, company_id=COMPANY)
    assert source.tell() == 1025
