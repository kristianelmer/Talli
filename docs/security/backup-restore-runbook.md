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
5. For the legacy fixture, verify its target company ID differs. For full-year RF,
   isolate the target database and object store while preserving captured company,
   actor and source identities; do not rewrite historical approvals or claims.
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
V2 company archives include all scoped source versions and observations, including
unapproved history, previews, bridges and original capture/idempotency records.
They do not replace a full owner database/object backup or perform restoration.

`20260930160335_rf1086_retained_archive_generations.sql` extends the existing
generation protocol to the eight RF source-history/head/binding tables and both
Documents retention tables. New evidence invalidates earlier export receipts;
Documents retention is company-scoped because a prior-year original can support
a later filing. Existing before-write company guards remain. Documents tracks
actual changes after the write so an identical retained-copy read does not
invalidate a receipt. First activation invalidates affected companies' existing
generations once. Replay preserves generations, source content, roles, grants and
RLS settings. Application rollback keeps these invalidation triggers. This does
not establish complete cancellation/deletion inventory or retention-expiry policy.

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
versioned v2 record preserves all captured source versions and observations,
original capture records, previews, review bridges and retained freshness/Governance
evidence; it is the authoritative RF input for recovery.
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
apps/backend/.venv/bin/python apps/backend/scripts/verify_rf1086_archive.py company-archive.json --company-id COMPANY_UUID --income-year 2025 --require-source-history --require-source-originals
```

The history flag rejects v1 archives that only captured approved lineage. A v2
pass reports `sourceHistoryIncluded: true`, source-version and observation counts,
and additionally `sourceOriginalBytesVerified: true` and the number
of distinct retained source versions. Any missing, duplicate, changed or surplus
original fails. With or without the flag, an included `sourceOriginals` field is
always checked. A bare canonical record remains usable for RF-only diagnosis
without the flag; its result does not claim source-byte verification. The inline
transport allows up to 128 MiB of retained original bytes; larger bundles fail
closed. Use the authenticated streaming RF download for larger bundles, as below.
Feedback originals and other company objects are not covered by the source-byte
result alone. `objectBytesVerified` and `databaseRestorePerformed` remain false.
Actual restoration and retention/expiry coverage still need proof.

### Verify a streaming RF download and feedback originals

The owner-facing RF archive download uses NDJSON and verifies each retained
original separately, with a 1 GiB aggregate original-byte limit. Verify the
complete file using the expected company and year supplied independently:

```sh
apps/backend/.venv/bin/python apps/backend/scripts/verify_rf1086_archive.py rf-archive.ndjson --stream --company-id COMPANY_UUID --income-year 2025 --require-source-history --require-feedback-originals
```

Streaming verification always requires every retained source original. The
feedback flag additionally rejects historical feedback without a bound original;
omitting it does not establish that legacy feedback is complete. A passing strict
result reports `sourceOriginalBytesVerified: true`,
`feedbackOriginalBytesVerified: true` and `feedbackOriginalsComplete: true`, with
separate original counts. The required terminal counts and hash reject truncated,
changed or surplus records. They are integrity checks, not an independent
signature or proof of provenance.

For inline JSON, add `--require-feedback-originals` to the preceding source-history
and source-original command to require the same feedback completeness. In either
format, verification performs no database or object-store writes. It does not
replace an isolated restore of owner-held records and actual stored bytes;
`databaseRestorePerformed` and the broader `objectBytesVerified` remain false.

### Rehearse the owned local database restore

The RF browser suite invokes `scripts/rehearse-rf1086-owned-restore.py` after
creating an accepted or rejected filing, an accepted correction and an unknown
send through the application. It supplies the downloaded NDJSON archive, company, year and
owner, together with the disposable runner's explicit `DATABASE_URL`,
`TALLI_SUPABASE_WORKDIR` and existing `TALLI_LEDGER_DATABASE_URL` for owner reads.
The command rejects targets outside that owned local
workdir/container boundary, including a connection not observed in the pinned
container. Do not use it against a hosted database.

The rehearsal takes a custom-format `pg_dump`, restores it into a fresh randomly
named database in the same disposable cluster, and preserves database ownership
and grants. It compares the restored RF owner-policy archive with the browser
download and reads the retained source and feedback bytes through Documents.
Unrelated actors must be denied both reads. Cleanup removes only the newly
created database; source RF history and cluster role memberships must remain
unchanged.

A pass reports `databaseRestorePerformed: true` and
`retainedOriginalBytesRestored: true`. These retained originals are database
bytes. By default `objectStorageRestorePerformed` remains false.

The rejected-predecessor browser case additionally selects `--restore-storage`.
It pins the owned file-backed Storage container and its cached image, copies the
file tree into a fresh volume, and starts a separate Storage API against the
cloned database. BusyBox tar omits Linux extended attributes, so the runner also
captures, restores and compares the attributes with the image's installed
`fs-xattr` library. Content type, cache control and etag attributes must survive;
copying only file contents can produce unreadable objects.

The real Documents adapter verifies the browser's existing local Auth sessions,
reads Company Access and document metadata from the restored database, checks
owner/MFA policy, and downloads all eight ordinary source/feedback objects. Bytes
must equal the retained originals and metadata must equal the source. An unrelated
actor and the owner's pre-MFA session cannot download. Direct owner, outsider and
unauthenticated Storage reads remain denied. The original gateway's opaque key
and Storage's internal JWT are kept distinct; neither is logged.

This optional proof reports `objectStorageRestorePerformed: true`,
`storageAttributesRestored: true` and the ordinary object count. Cleanup removes
only the created container, volume and database. Source files, extended attributes,
document metadata, RF history and cluster memberships must remain unchanged.

This is a quiescent local file-store rehearsal. The original local Auth service
still verifies sessions; independent Auth/cluster-role recovery and hosted object
storage are not covered. The browser saves an additional unapproved source and
preview backed by a prior-year original, then restores four source versions,
three approvals/submissions and eight ordinary objects. Existing sources,
previews, approvals, submissions, claims, feedback and provider calls remain
unchanged when that draft is saved. The canonical archive includes the unreviewed
preview even though the approval workspace does not materialize it.

That case also downloads the full company archive through the authenticated Next
route, which records its actual export receipt, then requests cancellation through
Company Access. The request and its idempotent replay must return `retention_hold`;
RF history and provider calls remain unchanged. The restore runner receives
`--cancellation-id` and compares the complete cancellation record before, within
and after restoration through Company Access using the browser's real owner
session. An unrelated owner's query must return no cancellation. A pass reports
`cancellationRestored: true` and `cancellationStatus: "retention_hold"`, alongside
the RF and eight-object checks. It does not seed an export receipt or cancellation
row to establish this result.

The same browser case then opens a scoped support case for a separate synthetic
admin reviewer. Review fails before the case is opened. The independent approval
and its replay succeed; finalization rejects the now-stale archive receipt until
the owner downloads a fresh full archive. Finalization and its replay return
`deleted`, while a new RF production review is denied. Retained RF history and
provider calls remain unchanged.

A second database/object restoration passes `--cancellation-status deleted`,
`--support-case-id` and `--deletion-review-id`. The reviewer's real Auth session
reads the restored Company Access support case. Its complete projection,
independent approval and `deleted_retention_record` company marker must equal the
source, alongside the owner cancellation, RF history and all eight objects.
`deletionReviewRestored` and `deletedCompanyRestored` report those additional
checks. The source case must remain unchanged after recovery. Both restorations
are required; the second does not replace the `retention_hold` proof.

Expiry and retained-original generation scenarios still need restored histories
before the broader restore signoff can pass. These proofs do not establish a full
retention inventory or change retention policy. Finalization retains business
records; it does not purge them.
