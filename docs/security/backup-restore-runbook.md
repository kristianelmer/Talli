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

## RF retention inventory and current deletion limits

The [30 September RF inventory](../../architecture/evidence/issues/193/rf/retention-inventory-20260930.json)
classifies all 20 declared RF business tables and three technical tables against
the database catalog. It also records Documents' metadata, retention references,
immutable copies and ordinary objects, plus the relevant owner dependencies.
This is an inventory of the RF slice, not the entire Talli service.

The approved customer-content rule is documented choice after the agreed access
and export period, unless a direct Talli duty or lawful instruction justifies
retention. A `retention_years` value, technical table, cancellation hold or deleted
marker is not itself proof of that duty. Cancellation finalization preserves
business data; it does not implement physical deletion or backup expiry.

The 30 September audit recorded these gaps: RF overrides were not portable-exported;
authority-test export includes only evidence linked to selected-year simulations;
unreferenced retained copies and migration quarantine need attributed inventory
and disposition; documented-choice/access-deadline/hold-expiry purge and hosted
backup rotation remain unimplemented or unverified. Quarantine can contain full
original customer rows despite being technical. Do not expose unattributed rows
through another company's export or treat successful restoration as deletion
compliance. Independent Auth/role recovery and deleted-actor handling were also
unproved. The current RF integration work below must record actual recovery
results before changing any finding's disposition.

The lifecycle UI describes a retained deletion marker and states that data remains
stored. These findings keep retention/deletion and real-customer signoff open.

## Full-year RF evidence

### October integration: override and independent identity verification

Codec v4 captures RF override history through its owning capability. An empty
list means captured and empty; older codecs mean uncaptured, never an inferred
empty history. Require `--require-override-history` together with the existing
source-history and original-byte flags when accepting a current complete RF
download. The additive `/archive-source/production-v4` and
`/archive-source/production-stream-v4` endpoints capture overrides. The original
`/archive-source/production` and `/archive-source/production-stream` endpoints
intentionally retain their old response shape and v1–v3 codec for older web
deployments. A new web falls back only when the newer endpoint is absent; that
legacy response cannot satisfy the additional override-completeness check.

Current company exports use the additive `/archive-source/production-v6` JSON
source. Its canonical V6 record preserves V2 sources and captured source,
override and withdrawal sections, together with exact source and feedback
originals. Missing sections, mismatched company/year scope and altered originals
fail the export checks. Older endpoints retain their original formats; only an
absent endpoint permits compatibility fallback. This export does not prove a
database, Auth or object-store restore.

The owned restore runner's optional `--restore-identity` mode restores a complete
database and cluster roles into a fresh pinned-image cluster, then starts a
separate Auth service from captured local configuration. Its checks must prove
owners/grants/RLS and Auth rows, live authentication, revoked membership/session
denial, soft-deleted actor denial, unchanged historical actor identifiers, and
read/export by an independently authenticated synthetic recovery owner. That
owner is provisioned only in the disposable target; this is not production
successor-authority approval. Physical Auth-user erasure remains a distinct
foreign-key/retention question. Copied local signing configuration is not proof
of hosted key recovery.

For Colima installations without working automatic port forwarding, the local
rehearsal accepts `TALLI_RF_RESTORE_SSH_CONFIG` and `TALLI_RF_RESTORE_SSH_HOST`.
These must designate the existing local VM; only this invocation's loopback
ports and SSH process are used. Omit both on normal local Docker/Linux CI.
Source ownership checks remain mandatory. Never reuse the old private harness's
container-restart or Colima-stop inventory against current unrelated resources.

Current status and measurable exits are tracked in the
[release integration plan](../../architecture/evidence/issues/193/rf/release-plan-20261009.md).
Implementation or unit tests alone do not close RF-RET-001/RF-RET-005, A1–A7, the
hosted restore gate, or the all-three launch gate.

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

Production archives include `rf1086Production.canonicalArchive`. This closed,
versioned record preserves captured source versions and observations from v2 onward,
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
Actual restoration and retention/expiry coverage are separate checks described below.

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
owner/MFA policy, and downloads all eight ordinary source/feedback objects. Each
object is matched to its retained generation by the complete current Documents
metadata hash, never by the latest retention timestamp. Missing, ambiguous or
conflicting matches fail. Downloaded bytes must equal that generation; all
historical generations are separately read and compared through Documents in the
database restore. Current metadata must equal the source. An unrelated
actor and the owner's pre-MFA session cannot download. Direct owner, outsider and
unauthenticated Storage reads remain denied. The original gateway's opaque key
and Storage's internal JWT are kept distinct; neither is logged.

This optional proof reports `objectStorageRestorePerformed: true`,
`storageAttributesRestored: true`, the ordinary object count, the number of retained
generations and the number of documents with multiple generations. Cleanup removes
only the created container, volume and database. Source files, extended attributes,
document metadata, RF history and cluster memberships must remain unchanged.

This is a quiescent local file-store rehearsal. The original local Auth service
still verifies sessions; independent Auth/cluster-role recovery and hosted object
storage are not covered. The browser saves an additional unapproved source and
preview backed by a prior-year original, then restores four source versions,
three approvals/submissions and eight ordinary objects. Existing sources,
previews, approvals, submissions, claims, feedback and provider calls remain
unchanged when that draft is saved. A bounded Documents fixture renames the first
original after its initial filing; the real owner UI re-verifies it before approving
the correction. This produces two retained generations for the same document ID.
Both restores must retain all nine original generations across eight ordinary
objects, including the older name and unchanged bytes. This fixture models metadata
maintenance; it is not a public metadata-edit feature. The canonical archive includes the unreviewed
preview even though the approval workspace does not materialize it.

Before cancellation, that case expires the exact synthetic full-year pilot through
the existing Billing admin command. The status stays `active` and the expiry is
in the past, so the check exercises the time boundary independently of revocation.
The exact command replay must match; the owner retains the expired receipt, loses
the active entitlement and cannot charge. RF history, payment events and filing
provider calls must remain unchanged.

Both restorations receive `--expired-pilot-id`. Billing's authenticated application
workflow compares the complete snapshot and denied entitlement decision before,
within and after restoration. The unrelated owner must see no Billing records for
that company. `expiredPilotRestored: true` reports these additional assertions;
it does not establish production provider conformance.

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

These proofs do not establish a full retention inventory or change retention
policy. Independent Auth/role recovery, hosted Storage and legacy feedback
backfill remain outside this local rehearsal. Finalization retains business
records; it does not purge them.


## Local encrypted generation controller

The opt-in `talli_backend.adapters.local_backup_generations.LocalBackupGenerations` implements the finite local publication/rotation controller. Its interface is `create(capture=..., minimum=...)`, `readiness(minimum=...)`, `rotate(minimum=...)` and `restore(generation=..., destination=..., recovery_key=..., minimum=...)`. Construction is explicit; no environment discovery, scheduler or hosted factory is provided.

Use distinct owner-private paths for encrypted generations, the independent completion catalog, plaintext scratch, the external deletion journal/held Documents exports and the separate RSA-3072 recovery key. The capture callback receives a nonexistent snapshot path and must use the approved owned-native DB/roles/config/object capture. Capture must be quiescent and must preserve the observed admitted journal cut; packaging is not a replacement for source consistency or a restore drill. Plaintext scratch is removed after a normal attempt and reconciled after interruption. Filesystem unlink is not forensic media erasure.

The checked local policy is 30-minute intended frequency, completion within 15 minutes, maximum usable age 1 hour and initial 7-day rotation. These are controller values, not a deployed schedule or accepted recovery promise. At most 512 attempts and 256MiB per native bundle are supported; capacity exhaustion fails readiness. A generation is not complete until encrypted readback verification and catalog commit. Age uses source capture time. A failed/incomplete generation preserves the prior verified backup and cannot reset its age. `control/readiness.json` is a sampled local test sink, not delivered paging.

Rotation physically removes only catalog-owned expired generations while a verified survivor remains. A lone expired survivor is protected and reported stale/overdue; this is not successful retention compliance. The journal and original held Documents export bytes remain independent and are never pruned by generation rotation. Current independently held journal identity/sequence/hash and every required export must be available for recovery. Missing or substituted custody fails closed.

For restore, independently recover the private key and catalog/journal custody, decrypt into a new isolated directory, verify its native backup commitment, then bind the explicit captured cut through `NativeDispositionRecovery.bind_prefix(..., captured=...)`. Captured obligations require exact terminal owner receipts; current later obligations still replay through the owning Documents seam before the fresh target can publish Auth/Storage. The decrypt receipt itself never authorizes publication.

This narrows the local implementation gap only. Approved paid/offsite resources, new backup-principal/access approval, actual scheduled execution, delivered alerts/human acknowledgment, operating RPO/RTO/load and hosted/full-service signoff remain outstanding. Original RF retention and strict-constructor findings above are historical evidence and are not reclassified by this controller.

## Opt-in managed logical recovery operator (31 October)

Run `talli-recover-hosted` only for an independently reviewed, freshly designated
Supabase destination. It imports the bounded managed logical capture under
quarantine. It does not create a backup, provision a project, pause another
project, publish recovered service traffic, schedule captures, or approve a
release. The earlier hosted rehearsal is separate evidence. The new reader/compiler also
accepts its sealed 228-table input in an offline compile check; the new command's
SQL execution proof uses synthetic local PostgreSQL. No new hosted rehearsal or
outage is implied.

The managed format is distinct from `LocalBackupGenerations`' native disposition
bundle. Nonempty native disposition tables, managed encryption-key tables and
queued provider work fail closed. A missing deletion-journal adapter remains a
current dependency for captures containing those obligations. This command
issues no deletion-replay receipt and changes no launch or publication gate.

### Private inputs and designation

Use the [configuration example](hosted-recovery-operator.example.json) as a shape
only. Replace every placeholder with independently verified owner evidence.
All input files must be owner-only regular files, without symlink ancestors;
capture/work directories must be owner-only. Use canonical absolute paths
(`/private/tmp`, not macOS's `/tmp` symlink). Keep the work directory outside the
capture and external credential file. Never commit filled configuration,
credentials, decrypted captures, object paths, actor identifiers or work state.

Required capture inputs:

- The verified decrypted `talli-designated-hosted-capture-v1` inventory, its header,
  and an independently held SHA-256 of the header. All pinned members must be
  present, exact and exclusive; role passwords are excluded.
- A separately pinned source-access supplement: `sourceProject`,
  `sourceCatalogStillExactToOriginal: true`, `access: {schemas, relations}`,
  and `databaseAccess: {database: "postgres", owner: "postgres", grants}`.
  Schema/relation rows are the named owner/grantor/grantee/privilege/grant-option
  observations returned by `hosted_recovery_access.ACCESS_SQL`; database grants
  use `DATABASE_ACCESS_SQL`. They must be collected by the authorized capture
  process, with evidence that the original source catalog stayed exact. Merely
  setting the boolean or recomputing a checksum supplies no provenance.
- Source profile: timezone-aware `capturedAt`, project reference, complete table
  inventory, seven database facts (version, locale provider, encoding, collation,
  ctype, locale, owner), and ordered extension identity/version/owner/schema rows.
- External credential JSON with exactly `project`, `databaseUrl`,
  `managementToken`, `serviceRoleKey`. The bounded profile requires the target's
  legacy service-role JWT; newer secret-key formats are not supported here.
  Supply the independently pinned official database CA separately. DSNs must
  name this target directly or through the session pooler on port 5432;
  connections always use TLS `verify-full`. Nonempty inherited `PG*` environment
  settings are rejected; use a clean shell with this explicit config. The CA file
  is rechecked before each connection. Credentials never enter CLI output
  or the work journal.

Metadata must match project, organization, name and region, report
`ACTIVE_HEALTHY`, and show creation after the capture. Database version/locale,
extensions, managed Auth/Storage definitions and empty destination checks must
pass before import. The owner must designate an unused project; this command
does not resolve free-project capacity by pausing another service.

The finite profile supports lowercase PostgreSQL identifiers, at most 512 tables,
32 private files of at most 8 MiB each, 256 Auth users, 64 MiB per capture member
and 256 MiB total. Application procedures/materialized data, custom triggers on
managed tables, non-owner ACL grantor chains, unsupported role grantor chains
and foreign keys to Storage transport IDs fail closed. Native provider migration
history is preserved. Storage IDs, versions and timestamps are recreated by the
Storage API, while bucket/path and file bytes are preserved.

### Plan, restore/resume, inspect and contain

Install the backend project with the locked dependencies. Pin the actual
`pg_restore` executable path in the reviewed configuration. Obtain the config
digest from its reviewed bytes, independently from the command that consumes it.

```sh
uv run --project apps/backend talli-recover-hosted plan --config /absolute/private/operator.json --expected-config-sha256 CONFIG_SHA
uv run --project apps/backend talli-recover-hosted restore --config /absolute/private/operator.json --expected-config-sha256 CONFIG_SHA --expected-plan-sha256 REVIEWED_PLAN_SHA
uv run --project apps/backend talli-recover-hosted inspect --config /absolute/private/operator.json --expected-config-sha256 CONFIG_SHA
uv run --project apps/backend talli-recover-hosted contain --config /absolute/private/operator.json --expected-config-sha256 CONFIG_SHA --expected-plan-sha256 REVIEWED_PLAN_SHA
```

Review the returned plan digest and exact target before restore. The plan binds
the capture/supplement hashes, target designation, schemas, role inventory and
quarantine policy. The plan command performs provider metadata reads only;
native archive inspection runs locally.

SQL import, ACL repair, row verification, Auth bans, runtime `NOLOGIN` and the
private `_talli_recovery.attempt` marker commit in one transaction. Membership
grantors/options are compared exactly; source LOGIN deliberately becomes false.
Sequence counters include managed Auth counters. PostgreSQL `setval` is
nontransactional: an aborted import can leave an advanced counter on the empty
quarantined target. Containment does not claim counter rollback.

An unknown database commit response stops with private state retained. Repeat
the same restore command to reconcile its marker; it never blindly replays DDL
over committed data. Private object POSTs use no overwrite; resume reads and
hashes existing bytes. Wrong existing content, changed public bucket state or
an unexpected marker stops for inspection. Do not delete state or substitute a
target to bypass these checks.

`verified_quarantined` means row/ACL/object checks passed with recovered users
banned and runtime logins disabled. It grants no service publication authority,
nor a claim that source Auth tokens or managed encryption keys were recovered.
The target's keys, Auth configuration and existing token trust need separate
review before any later publication. Real signing, payment, provider activation
and all existing release gates remain closed.

`contain` reasserts bans and `NOLOGIN` and is repeatable. It can use the
reviewed plan stored in private state even after capture scratch is lost; target
credentials and the independently held plan digest are still required. After
reboot or interruption, first inspect/contain with the same private work state.
A mismatched or missing marker with unrelated imported data is never treated as
an empty rollback. Retain state until containment is independently checked.
Containment preserves forensic data and private objects; it does not pause or
delete the project, revoke owner API credentials, or remove owner-held input
files. Expire/rotate temporary credentials and remove decrypted scratch through
the approved custody procedure after the evidence is sealed.

### Changed-seam regression

The fast unit suite covers binding, COPY framing, provider HTTP contracts,
readback after a lost upload response, marker reconciliation and capture-loss
containment:

```sh
uv run --project apps/backend pytest apps/backend/tests/test_hosted_backup_recovery.py -q
```

For actual SQL behavior, run the explicit disposable Docker regression with the
cached pinned PostgreSQL 17 image and a local `pg_restore` (17 or newer):

```sh
uv run --project apps/backend python scripts/test-hosted-recovery-owned.py --pg-restore /absolute/path/pg_restore
```

It creates one labeled container with an ephemeral database and loopback-only
port, uses synthetic data, and removes that exact container in `finally`.
It verifies rollback before commit, cross-schema owners, fresh-project default
ACL repair, role grantors/options, managed custom usage, Auth sequence 132,
quarantine, lost-commit reconciliation and repeatable containment. Its Storage
port is a local fixture; HTTP behavior is verified separately by the unit suite.
Neither result constitutes a new hosted replay, continuous RPO, whole-service
RTO, offsite key custody or delivered incident alert.
