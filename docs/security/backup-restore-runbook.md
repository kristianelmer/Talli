# Backup, Restore, and Export Launch Gate

Production direct filing is blocked until Talli has a recent passing restore test.

## Launch-Critical Data

The launch restore fixture must cover:

- `companies`
- `company_memberships`
- `annual_data`
- `opening_balance_setups`
- `opening_shareholders`
- `ledger_entries`
- `bank_transactions`
- `bank_suggestion_acceptances`
- `holding_actions`
- `investments.positions`
- `investments.acquisition_lots`
- `investments.share_purchases`
- `investments.share_sales`
- `investments.share_sale_allocations`
- `investments.received_dividends`
- `documents`
- `filing_previews`
- `filing_submissions`
- `filing_readiness_snapshots`
- `filing_overrides`
- `filing_review_comments`
- `billing_accounts`
- `authority_permissions`
- `audit_events`

Document object storage is represented by document metadata plus `storage_key`. A restore test may restore metadata before object bytes, but must produce explicit warnings for missing object content.

## Required Restore Test

1. Export one company-year archive from persisted workspace data.
2. Build a backup manifest from the archive.
3. Restore the archive into an isolated workspace/test schema or fixture target.
4. Verify ledger entries, holding actions, document metadata, filing previews, filing submissions, receipts, review comments, billing, and audit events are present.
5. Verify restored data uses a different target company id for isolation.
6. Record restore test date, target, operator, result, and missing-object warnings.

## Launch Gate

Production direct filing remains blocked if:

- no restore test has passed, or
- the latest passing restore test is older than 30 days, or
- restore integrity reports missing launch-critical rows.

Automated coverage:

- `npm run test:backup-restore`
- `npm run test:archive`

Machine-checkable signoff gate:

- Implementation: `app/lib/launch-signoff.ts`
- Test: `npm run test:launch-signoff`
- Required key: `security_restore`
- Closure rule: reviewer, review date, evidence link, and decision must be
  recorded as `approved`; the review date must be 30 days old or newer.

## Full-year RF evidence

Include the RF register observations, source versions and heads, source previews,
review bridges, approval bindings, submission bindings and managed filing heads,
as well as Documents' `retained_originals`, in the database backup inventory.
The company archive's approved lineage is not a replacement for a database backup
of all source versions, including unapproved history and independent observations.

The archive restore fixture preserves captured source-company identities rather
than rewriting historical approvals or claim actors to the target company's ID.
Its full-year checks verify retained manifest/review text hashes, XML and preview
text commitments, linked source/preview/bridge identities, claim/approval/actor
relationships, complete ancestry ending at the managed head, and source-original
object metadata. Missing, duplicate or changed originals fail these checks even
when other non-filing missing objects can produce warnings.

A passing fixture is not a completed restore rehearsal: it does not write a
restored database or retrieve object bytes, and it does not reconstruct the full
source case through Python's RF policy. Before signing off, restore the complete
owner-held source records and retained originals, verify those records through
the RF owner and verify actual original bytes through Documents. Include prior
reporting-year documents, approved and unapproved source history, corrections,
unknown outcomes, cancellation/expiry and company deletion. Keep release signoff
pending until that evidence exists.

### Verify the canonical RF record

New production archives include `rf1086Production.canonicalArchive`. This closed,
versioned record preserves the complete captured source facts and their retained
freshness/Governance evidence; it is the authoritative RF input for recovery.
The surrounding readable projections are not a substitute for it. Run the local
owner-policy verifier with the expected company and year, supplied independently:

```sh
apps/backend/.venv/bin/python apps/backend/scripts/verify_rf1086_archive.py company-archive.json --company-id COMPANY_UUID --income-year 2025
```

The verifier also accepts an RF endpoint export or the canonical record itself.
It reconstructs the captured typed records and checks their source, approval,
claim, journal and correction integrity. A pass reports
`verified_rf_canonical_record`, with `databaseRestorePerformed: false` and
`objectBytesVerified: false`. It checks the canonical record rather than treating
editable display projections as authority. Changed facts fail even if the outer
container checksum is recomputed. The checksum is not an independent signature
or proof of provenance. Keep the actual database and object-byte recovery gate
pending until its separate rehearsal succeeds.


### Verify retained source-original bytes

New endpoint exports and company downloads include `sourceOriginals` alongside
the canonical RF record. Each entry preserves an exact Documents-owned metadata
version and immutable original bytes, including evidence from prior years. The
current-year document projection is not a replacement for these records. Require
complete source originals when verifying a downloaded bundle:

```sh
apps/backend/.venv/bin/python apps/backend/scripts/verify_rf1086_archive.py company-archive.json --company-id COMPANY_UUID --income-year 2025 --require-source-originals
```

A pass additionally reports `sourceOriginalBytesVerified: true` and the number
of distinct retained source versions. Any missing, duplicate, changed or surplus
original fails. With or without the flag, an included `sourceOriginals` field is
always checked. A bare canonical record remains usable for RF-only diagnosis
without the flag; its result does not claim source-byte verification. The inline
transport allows up to 128 MiB of original source bytes; larger bundles fail
closed and require a future streaming export. Feedback originals and other
company objects are not covered by this source-byte result, and
`objectBytesVerified` and `databaseRestorePerformed` remain false. Actual
restoration, unapproved history and retention/expiry coverage still need proof.
