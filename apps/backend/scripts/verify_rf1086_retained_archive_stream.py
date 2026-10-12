"""Verify an explicit RF retained stream locally; no authentication or restore."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from talli_backend.application.shareholder_register_archive import verify_retained_archive_stream
from talli_backend.modules.documents.public import DocumentsError
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, UserId


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--company-id', required=True)
    parser.add_argument('--income-year', required=True, type=int)
    parser.add_argument('--require-feedback-originals', action='store_true',
        help='Reject legacy feedback without retained original bindings.')
    args = parser.parse_args()
    try:
        # Diagnostic scope only; this identity grants no access or filing authority.
        query = rf.Rf1086ArchiveQuery(CompanyId(args.company_id), IncomeYear(args.income_year),
            ActorId(ActorKind.SYSTEM, UserId('00000000-0000-0000-0000-000000000000')))
        with args.archive.open('rb') as stream:
            archive, sources, feedback = verify_retained_archive_stream(stream, query=query,
                require_feedback_originals=args.require_feedback_originals)
    except (OSError, ValueError, TypeError, KeyError, RecursionError, DocumentsError):
        print(json.dumps({'status': 'invalid', 'code': 'rf1086_archive_verification_failed'}))
        return 1
    print(json.dumps({'status': 'verified_rf_retained_stream',
        'streamCodec': 'rf1086-production-stream-v2', 'archiveCodec': 'rf1086-production-archive-v6',
        'companyId': str(archive.company_id), 'incomeYear': int(archive.income_year),
        'sourceHistoryIncluded': True, 'overrideHistoryIncluded': True,
        'registerWithdrawalHistoryIncluded': True,
        'sourceVersions': len(archive.source_history.year_sources),
        'registerObservations': len(archive.source_history.register_observations),
        'registerWithdrawals': len(archive.withdrawal_capture_records), 'overrides': len(archive.overrides),
        'approvals': len(archive.approvals), 'submissions': len(archive.production_submissions),
        'sourceOriginalBytesVerified': True, 'sourceOriginals': sources,
        'feedbackOriginalBytesVerified': True, 'feedbackOriginals': feedback,
        'feedbackOriginalsComplete': all(row.original_id is not None for row in archive.feedback_artifacts),
        'databaseRestorePerformed': False, 'authenticatedOriginVerified': False,
        'authoritativeEnumerationVerified': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
