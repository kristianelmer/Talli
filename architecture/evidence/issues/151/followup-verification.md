# RF migration follow-up verification

After implementation checkpoint `3e8bf5187d614a3a2d02437f12186d90dbd19078`.
This is focused working-tree evidence, not a #151 exit or either complete gate.

The reviewer preview lock, transitive quarantined-preview classification,
case-bound support permission/test currentness and purpose filtering, and stale
simulation failure text found in the [SQL review](sql-access-review.md) have
regressions in the mandatory RF database lifecycle lane. Its latest retained
interim-topology run passed 32 cases with unchanged source hashes during the run.
The [receipt](followup/lifecycle-retained-run2.json) records exact tested hashes
and times; it does not claim the later final opening-table disposal.

The later [combined database receipt](followup/combined-runtime-run2.json)
records104 passes, zero skips and zero failures on the final schema. It covers
the37-case RF lifecycle,24 RF runtime cases and retained Authority Connections,
operator and launch-signoff behavior. The old public opening tables are absent;
literal rollback reconstruction restores the captured original schema and
permissions. Old/new backend begins bind the same journal record. The retired
Ledger setup link remains absent. Source hashes and raw transcript digest are
recorded; this is focused database evidence rather than a full immutable gate.

The [opening-year review](archive-opening-year-review.md) found that an unrelated
invalid year could block an archive after the opening-table read was replaced.
The archive now uses the additive `ledgerListOpeningSnapshotsForYear` generated
operation. Both owner reads filter by company/year before validation. Existing
list behavior and HTTP contracts remain unchanged. Actual database cases prove
valid2025 succeeds beside quarantined2024, affected-year/all-year reads still
fail, and cursors cannot cross the year boundary. API, adapter and workflow
checks passed113; archive and actual generated-transport checks passed60.
TypeScript checking passed. These counts describe overlapping focused suites.

Six retired current RF scopes are removed from the registry with committed-source
proof in [active-scope-retirements.json](active-scope-retirements.json). No future
scope amendment or immutable-baseline edit is included. The wholly RF-owned
archive holder read is retired with final physical ownership and zero-call
source proof. The historical opening setup read combines RF shares and Ledger
bank amounts; it has no false single-owner alias and is the one additional
pending tuple in [revision2 of the finite amendment](compatibility-amendment-v2-proposal.md).

The [independent source review](source-facts-independent-review.md) identified
missing accepted-warning attribution and reconciliation outcome timing. Those
corrections now pass the92-case focused integration suite and independent
reproductions close both findings. Warnings retain source identity, risk and
acceptance actor/time; known reconciliation outcomes retain their observation
time separately from transport incidents and the first mutation.

The archive also uses an exact-year RF source query before nested evidence
decoding. Company-wide comments/permissions and exactly referenced test evidence
retain their original scope. Source integration passed120 overlapping cases;
web archive/generated-transport checks passed43. The
[independent backend review](archive-source-independent-review.md) found no
additional issue in that slice. Selected malformed nested receipts now return
sanitized503 with no-store in both archive and workspace reads; actual HTTP
regressions reproduced the former500 before correction. The final focused RF API
run passed108 cases, following the130-case combined RF/Ledger API run.
The [year integration review](year-api-integration-review.md) and adjacent
workspace recheck close those error-path findings.

The original historical RF input and both XML copies were located and verified
against the original recorded hashes. The canonical generator reproduces both
documents byte for byte, including repeated generation and bundled XSD checks.
The [redacted deterministic receipt](tt02-deterministic-replay.json) resolves the
missing-input A1 blocker without a new provider run. Existing OpenAPI contracts
are unchanged; the complete migration adds27 schemas and12 paths.

The broader backend boundary run passed2,808 tests with two pre-existing optional
skips and803 database cases deselected. Mandatory database coverage is the
separate104-pass, zero-skip result above. The credential test/scanner command
also passed. These focused runs do not replace either complete gate.

Log hashes are in [followup/manifest.json](followup/manifest.json). Remaining
browser/receiver checks, the pending16-tuple decision, full review and the two
immutable complete gates remain open. No stage or #192 completion is claimed.
