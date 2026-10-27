"""Independent Accounts archive reconstruction; no network or persistence writes."""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'apps/backend/src'))

from talli_backend.adapters.annual_accounts_schemas import PinnedAnnualAccountsSchemas
from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsSourceQuery, parse_annual_accounts_company_archive, build_annual_accounts_company_archive,
    annual_accounts_delivery_originals, project_annual_accounts_source,
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
    schemas = PinnedAnnualAccountsSchemas()
    restored = parse_annual_accounts_company_archive(wire['canonicalJson'], query=query, expected_sha256=args.expected_sha256, schemas=schemas)
    archive = build_annual_accounts_company_archive(query, restored, schemas=schemas)
    if (archive.canonical_json != wire['canonicalJson'] or archive.sha256 != args.expected_sha256
            or wire['codec'] != archive.codec or wire['sourceSha256'] != archive.source_sha256
            or any(type(wire[key]) is not int or wire[key] != count for key, count in
                (('draftCount',archive.draft_count),('eventCount',archive.event_count),('originalCount',archive.original_count)))):
        raise ValueError('Accounts isolated reconstruction changed original bytes.')
    originals = [dict(filingId=stored.draft.filing_id, key=value.key, purpose=value.purpose,
        sha256=value.sha256, byteLength=len(base64.b64decode(value.body_base64, validate=True)))
        for stored in restored.delivery_drafts for value in annual_accounts_delivery_originals(stored,
            tuple(row for row in restored.delivery_events if row.record.binding.filing_id == stored.draft.filing_id))]
    print(json.dumps({'schema':'accounts-isolated-company-archive-copy-v1','status':'pass','companyId':args.company_id,
        'incomeYear':args.income_year,'archiveSha256':archive.sha256,
        'sourceSha256':project_annual_accounts_source(query, restored).evidence.digest,
        'draftCount':archive.draft_count,'eventCount':archive.event_count,'originalCount':len(originals),'originals':originals}, separators=(',',':')))


if __name__ == '__main__':
    main()
