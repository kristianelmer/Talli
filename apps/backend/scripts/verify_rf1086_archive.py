"""Verify a downloaded RF canonical record locally, without database/provider access."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from talli_backend.application.shareholder_register_archive import verify_source_originals
from talli_backend.modules.documents.public import DocumentsError
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, UserId


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--company-id', required=True)
    parser.add_argument('--income-year', required=True, type=int)
    parser.add_argument('--require-source-originals', action='store_true', help='Require all captured source document bytes in a downloaded bundle.')
    parser.add_argument('--require-source-history', action='store_true', help='Require the complete versioned source and observation history.')
    args = parser.parse_args()
    source_originals_verified = False
    original_count = 0
    try:
        with args.archive.open('rb') as stream:
            content = stream.read(256 * 1024 * 1024 + 1)
        if len(content) > 256 * 1024 * 1024:
            raise ValueError()
        text = content.decode('utf-8')
        document = json.loads(text, object_pairs_hook=unique)
        if type(document) is not dict:
            raise ValueError()
        if document.get('codec') in ('rf1086-production-archive-v1', 'rf1086-production-archive-v2'):
            canonical = text
            section = {}
        else:
            section = document.get('rf1086Production', document)
            if type(section) is not dict:
                raise ValueError()
            canonical = section.get('canonicalArchive')
        # This identity marks a local diagnostic only. Parsing performs no
        # authentication, persistence, current admission, or provider operation.
        query = rf.Rf1086ArchiveQuery(CompanyId(args.company_id), IncomeYear(args.income_year),
            ActorId(ActorKind.SYSTEM, UserId('00000000-0000-0000-0000-000000000000')))
        archive = rf.parse_rf1086_archive(canonical, query=query)
        if args.require_source_history and archive.source_history is None:
            raise ValueError()
        if args.require_source_originals or 'sourceOriginals' in section:
            originals = verify_source_originals(archive, section.get('sourceOriginals'))
            source_originals_verified = True
            original_count = len(originals)
    except (OSError, ValueError, TypeError, KeyError, RecursionError, DocumentsError):
        print(json.dumps({'status': 'invalid', 'code': 'rf1086_archive_verification_failed'}))
        return 1
    print(json.dumps({'status': 'verified_rf_canonical_record',
        'companyId': str(archive.company_id), 'incomeYear': int(archive.income_year),
        'approvals': len(archive.approvals), 'submissions': len(archive.production_submissions),
        'sourceApprovals': len(archive.source_approval_lineage),
        'sourceHistoryIncluded': archive.source_history is not None,
        'sourceVersions': None if archive.source_history is None else len(archive.source_history.year_sources),
        'registerObservations': None if archive.source_history is None else len(archive.source_history.register_observations),
        'sourceClaims': len(archive.source_submission_claims),
        'feedbackArtifacts': len(archive.feedback_artifacts),
        'databaseRestorePerformed': False, 'objectBytesVerified': False,
        'sourceOriginalBytesVerified': source_originals_verified, 'sourceOriginals': original_count}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
