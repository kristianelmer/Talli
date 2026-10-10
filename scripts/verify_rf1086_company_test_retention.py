#!/usr/bin/env python3
"""Offline, bounded structural verification; supplied expectations are not origin proof."""
import argparse
from contextlib import contextmanager
from hashlib import sha256
import json
import os
import stat
import sys
from uuid import UUID

from talli_backend.application.shareholder_register_company_test_retention_stream import (
    ARTIFACT_CODEC, HEADER_BYTES, verify_company_test_retention_stream)
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId


@contextmanager
def local_file(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise rf.Rf1086ArchiveError('local_regular_file_required')
        yield source


def artifact_capture(source, company_id):
    limit = rf.rf1086_company_test_retention_bounds().max_artifact_bytes
    raw = source.read(limit + 1)
    if len(raw) > limit:
        raise rf.Rf1086ArchiveError('company_test_retention_artifact_too_large')
    return rf.parse_rf1086_company_test_retention(raw.decode('utf-8'), company_id=company_id)


def verify(args):
    if str(UUID(args.company_id)) != args.company_id:
        raise rf.Rf1086ArchiveError('canonical_company_id_required')
    company_id = CompanyId(args.company_id)
    with local_file(args.input) as source:
        prefix = source.read(HEADER_BYTES)
        source.seek(0)
        if prefix.startswith(('{' + '"codec":"' + ARTIFACT_CODEC + '"').encode()):
            snapshot = artifact_capture(source, company_id)
        elif prefix.startswith(('{' + '"artifactCodec":"' + ARTIFACT_CODEC + '",').encode()):
            snapshot = verify_company_test_retention_stream(source, company_id=company_id)
        else:
            raise rf.Rf1086ArchiveError('unsupported_company_test_retention_codec')
    result = {'status': ['STRUCTURAL_INTEGRITY_ONLY'], 'sourceOrigin': 'UNVERIFIED',
        'coverage': snapshot.coverage,
        'artifactSha256': sha256(rf.serialize_rf1086_company_test_retention(snapshot).encode('utf-8')).hexdigest()}
    if snapshot.coverage == 'complete':
        result.update(observedAt=snapshot.observed_at, recordCount=snapshot.record_count,
            recordsSha256=snapshot.records_sha256)
    if args.expected_source_capture:
        with local_file(args.expected_source_capture) as source:
            expected = artifact_capture(source, company_id)
        rf.assert_company_test_retention_source_capture_matches(snapshot, expected)
        result['status'].append('EXPECTED_CAPTURE_MATCH')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--company-id', required=True)
    parser.add_argument('--expected-source-capture')
    args = parser.parse_args()
    try:
        result = verify(args)
    except (OSError, ValueError, TypeError, OverflowError, RecursionError):
        print('company_test_retention_verification_failed', file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
