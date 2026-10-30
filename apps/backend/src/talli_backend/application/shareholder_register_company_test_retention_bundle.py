"""Fixed portable inventory framing. Integrity never establishes source origin."""
from hashlib import sha256
from io import BytesIO
import json
import struct
from typing import BinaryIO
from zipfile import BadZipFile, LargeZipFile, ZIP_STORED, ZipFile, ZipInfo

from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId

PROFILE = 'rf1086-company-test-retention-bundle-v1'
ARTIFACT_CODEC = 'rf1086-company-test-retention-v1'
SCOPE = 'company_no_intrinsic_income_year'
MAX_BYTES = 67 * 1024 * 1024
MANIFEST_BYTES = 4096
NAMES = ('manifest.json', 'company-test-retention.json')
DIRECTORY_BYTES = sum(46 + len(name) for name in NAMES)


def _require(condition: bool) -> None:
    if not condition:
        raise rf.Rf1086ArchiveError('rf1086_company_test_retention_bundle_invalid')


def _manifest(snapshot: rf.Rf1086CompanyTestRetentionSnapshot, artifact: bytes) -> bytes:
    value = {'profile': PROFILE, 'companyId': str(snapshot.company_id), 'scope': SCOPE,
        'coverage': 'complete', 'artifact': {'path': NAMES[1], 'codec': ARTIFACT_CODEC,
            'byteLength': len(artifact), 'sha256': sha256(artifact).hexdigest()},
        'sourceCapture': {'observedAt': snapshot.observed_at, 'recordCount': snapshot.record_count,
            'recordsSha256': snapshot.records_sha256}}
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
        separators=(',', ':')).encode('utf-8')
    _require(len(raw) <= MANIFEST_BYTES)
    return raw


def _entry(name: str) -> ZipInfo:
    entry = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    entry.create_system, entry.create_version, entry.extract_version = 3, 20, 20
    entry.compress_type, entry.flag_bits, entry.volume = ZIP_STORED, 0, 0
    entry.internal_attr, entry.external_attr = 0, 0o100600 << 16
    entry.extra, entry.comment = b'', b''
    return entry


def pack_company_test_retention(snapshot: rf.Rf1086CompanyTestRetentionSnapshot) -> bytes:
    """Package one complete RF capture; no paths, extraction or authority values."""
    artifact = rf.serialize_rf1086_company_test_retention(snapshot).encode('utf-8')
    _require(snapshot.coverage == 'complete')
    output = BytesIO()
    with ZipFile(output, 'w', compression=ZIP_STORED, allowZip64=False) as archive:
        for name, content in zip(NAMES, (_manifest(snapshot, artifact), artifact), strict=True):
            archive.writestr(_entry(name), content)
    raw = output.getvalue()
    _require(len(raw) <= MAX_BYTES)
    return raw


def _read_package(source: BinaryIO) -> bytes:
    chunks, total = [], 0
    while True:
        limit = min(1024 * 1024, MAX_BYTES - total + 1)
        raw = source.read(limit)
        _require(type(raw) is bytes and len(raw) <= limit)
        if not raw:
            return b''.join(chunks)
        total += len(raw)
        _require(total <= MAX_BYTES)
        chunks.append(raw)


def _inspect_entries(raw: bytes, archive: ZipFile, directory_offset: int) -> tuple[ZipInfo, ...]:
    entries = tuple(archive.infolist())
    _require(len(entries) == 2 and archive.comment == b'')
    offset = 0
    limits = (MANIFEST_BYTES, rf.rf1086_company_test_retention_bounds().max_artifact_bytes)
    for entry, name, limit in zip(entries, NAMES, limits, strict=True):
        expected = _entry(name)
        _require(entry.filename == entry.orig_filename == name
            and entry.header_offset == offset and 0 < entry.file_size <= limit
            and entry.compress_size == entry.file_size and entry.reserved == 0)
        for field in ('date_time', 'create_system', 'create_version', 'extract_version',
                'compress_type', 'flag_bits', 'volume', 'internal_attr', 'external_attr', 'extra', 'comment'):
            _require(getattr(entry, field) == getattr(expected, field))
        # Check local sizes/flags/names BEFORE opening an entry. No descriptors or ZIP64.
        header = struct.pack('<4s5H3I2H', b'PK\x03\x04', 20, 0, 0, 0, 33,
            entry.CRC, entry.file_size, entry.file_size, len(name), 0) + name.encode('ascii')
        _require(raw[offset:offset + len(header)] == header)
        offset += len(header) + entry.file_size
        _require(offset <= directory_offset)
    _require(offset == directory_offset)
    return entries


def verify_company_test_retention_bundle(source: BinaryIO, *, company_id: CompanyId) -> rf.Rf1086CompanyTestRetentionSnapshot:
    """Return structural integrity only after bounded CRC, RF and exact-byte checks."""
    try:
        raw = _read_package(source)
        directory_offset = len(raw) - DIRECTORY_BYTES - 22
        _require(directory_offset > 0)
        end = struct.pack('<4s4H2IH', b'PK\x05\x06', 0, 0, 2, 2,
            DIRECTORY_BYTES, directory_offset, 0)
        _require(raw[-22:] == end)
        with ZipFile(BytesIO(raw), 'r', allowZip64=False) as archive:
            entries = _inspect_entries(raw, archive, directory_offset)
            contents = []
            for entry in entries:
                with archive.open(entry) as member:
                    content = member.read(entry.file_size + 1)
                    _require(len(content) == entry.file_size and member.read(1) == b'')
                    contents.append(content)
        snapshot = rf.parse_rf1086_company_test_retention(contents[1].decode('utf-8'), company_id=company_id)
        _require(snapshot.coverage == 'complete')
        # Exact derived canonical bytes also reject duplicate/nonfinite/extra manifest keys,
        # boolean counts, changed scope, whitespace and every metadata disagreement.
        _require(contents[0] == _manifest(snapshot, contents[1]))
        _require(raw == pack_company_test_retention(snapshot))
        return snapshot
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError,
            OSError, BadZipFile, LargeZipFile, NotImplementedError, struct.error):
        raise rf.Rf1086ArchiveError('rf1086_company_test_retention_bundle_invalid') from None
