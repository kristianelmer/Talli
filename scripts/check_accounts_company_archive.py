"""Independent Accounts archive reconstruction; no network or persistence writes."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'apps/backend/src'))

from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsSourceQuery, parse_annual_accounts_company_archive, build_annual_accounts_company_archive,
    verify_annual_accounts_company_archive,
)
from talli_backend.shared.kernel import ActorId, ActorKind, UserId, CompanyId, IncomeYear


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--company-id', required=True)
    parser.add_argument('--income-year', type=int, required=True)
    parser.add_argument('--actor-id', required=True)
    parser.add_argument('--expected-sha256', required=True)
    args = parser.parse_args()
    incoming = sys.stdin.buffer.read(200 * 1024 * 1024 + 1)
    if len(incoming) > 200 * 1024 * 1024:
        raise ValueError('Accounts copy input exceeds its bound.')
    wire = json.loads(incoming)
    if (type(wire) is not dict or set(wire) != {'companyId','incomeYear','codec','canonicalJson','sha256','sourceSha256','draftCount','eventCount','originalCount'}
            or wire['companyId'] != args.company_id or wire['incomeYear'] != args.income_year or wire['sha256'] != args.expected_sha256):
        raise ValueError('Accounts copy requested scope or receipt differs.')
    query = AnnualAccountsSourceQuery(CompanyId(args.company_id), IncomeYear(args.income_year), ActorId(ActorKind.USER, UserId(args.actor_id)))
    restored = parse_annual_accounts_company_archive(wire['canonicalJson'], query=query, expected_sha256=args.expected_sha256)
    archive = build_annual_accounts_company_archive(query, restored)
    if (archive.canonical_json != wire['canonicalJson'] or archive.sha256 != args.expected_sha256
            or wire['codec'] != archive.codec or wire['sourceSha256'] != archive.source_sha256
            or any(type(wire[key]) is not int or wire[key] != count for key, count in
                (('draftCount',archive.draft_count),('eventCount',archive.event_count),('originalCount',archive.original_count)))):
        raise ValueError('Accounts isolated reconstruction changed original bytes.')
    proof = verify_annual_accounts_company_archive(wire['canonicalJson'], query=query, expected_sha256=args.expected_sha256)
    def transport(value):
        if isinstance(value, dict):
            return {key.split('_')[0] + ''.join(part.title() for part in key.split('_')[1:]): transport(child) for key, child in value.items()}
        if isinstance(value, (list, tuple)):
            return [transport(child) for child in value]
        return value
    print(json.dumps(transport(asdict(proof)), separators=(',',':')))



if __name__ == '__main__':
    main()
