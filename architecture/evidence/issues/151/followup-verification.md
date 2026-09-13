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

The [independent opening review](opening-contract-independent-review.md) found
no material issue in final disposal/reconstruction and verified the actual
database receipt's source and log hashes. The
[independent production review](production-coordinator-independent-review.md)
compared27 functions with the #150 baseline:22 were AST-identical, four changed
only canonical type names, and one adapts immutable approved-manifest containers
while preserving validation. Neither reviewer certifies their own code.

The retained workspace now passes on RF canonical overlap with ordinary Ledger
storage. Its [source-bound receipt](followup/workspace-fixture-runtime-proof.json)
covers real Auth, generated HTTP transport and canonical RF commands, while
preserving all nine Ledger assertions and the sibling tax, audit, notification,
storage and archive checks. The actual read path exposed two missing EXECUTE
grants for `ledger_executor`; the correction grants only those reads, with
mutation authority still denied. Final schema revalidation remains separate.

The fixture helper now preserves FORCE RLS and internal foreign keys while
temporarily disabling only captured USER triggers under exact owner authority.
It restores original ACLs, memberships and trigger modes on success and rollback.
The retained workspace, sixteen fixture guards and two actual standalone cleanup
cases pass with no skips. Earlier twenty-case feedback and hydrated historical
recovery results retain their original source hashes and are explicitly marked
intermediate. The complete web boundary rerun passes225 checks with zero skips.
The additional contract boundary passes53 checks. Both application builds,
the canonical production-artifact smoke and a fresh installed-wheel smoke pass;
the [build receipt](followup/builds/receipt.json) binds495 unchanged source inputs,
logs and package digests. Installed RF schemas and a fixed synthetic payload match
their expected hashes without importing the old root package. This does not
claim the build gate's separate public-acquisition browser subcheck.

The updated [final database run](followup/final-db/final-combined-108.json)
passes108 cases with zero skips after the read-role and bank archive corrections.
Its263 source hashes matched at handoff. The later workspace-only runner
correction below has separate evidence; the tested product sources are unchanged. The bank-only write advances the
export generation, transaction rollback restores it, and full rollback preserves
the original bank amount. The final catalog verifies retired-table absence,
enabled archive tracking, allowed opening reads and denied writes.

The preceding Ledger authority rehearsal passes1 case, governance passes26,
and Billing passes699 Python cases plus its separate Node lifecycle. Host-clock
MFA fixtures were several milliseconds ahead of the database, so five Python
and two Node timestamps now use its existing clock-minus-one-second pattern.
Independent whole-file comparisons verify all other assertions are unchanged.
The first Billing aggregate's Node failure and the later corrected success remain
separate logs with their actual exit codes; the
[phase report](followup/final-db/final-verification-report.md) discloses the
earlier wrapper inventory omissions and their explicitly timed supplements.

The complete runner now requires the fresh RF browser after historical recovery.
All62 orchestration/cancellation checks pass, including stop-on-failure behavior
and retention of every original database test. The
[corrected runner receipt](followup/orchestration-au-overlap.json) supersedes the
earlier mock-only result after actual workspace restoration exposed an AU
contract ordering error. The workspace phase retains the AU view while the
ordinary Billing pilot coordinator still depends on it. Final recutover still
contracts AU after Billing retires that dependency; no product guard changed.
The [corrective review](workspace-au-overlap-corrective-review.md) verifies the
small source delta and the actual successful rollback/workspace receipt. This
proves the corrected phase, not the whole aggregate or pending fresh RF flow.

The [updated final HTTP/browser receipt](followup/final-web/final-browser-read-verification.json)
records22 feedback/schema passes, five actual Supabase-auth opening HTTP checks,
and one hydrated historical authority/recovery browser pass, all without skips.
The HTTP checks retain exact share/bank identity and provenance, year filtering,
other-owner concealment and denied bank mutation/direct-table access. All owned
fixtures were cleaned, runtime logins disabled and generated Next files restored.

The [shared fixture receipt](followup/owner-fixture/owner-fixture-verification.json)
records34 passes in each of the predecessor and overlap layouts, the unchanged
onboarding browser, and an actual late cleanup failure that restores rows, ACLs,
USER triggers, schema permissions and memberships while retaining FORCE RLS and
internal foreign keys. The
[whole-source comparison](followup/owner-fixture/retained-scenario-preservation.json)
preserves every original owner journey and assertion outside the exact historical
seed bindings, helper import and Ledger read name. These checks do not replace
the full owner journey. Corrected workspace restoration ends at RF canonical
overlap, with zero company/user residue and disabled runtime logins.

The fresh RF fixture safety suite passes11 checks after correcting mirror cleanup
and the required creator attribution; the
[independent review](fresh-browser-independent-review.md) closes both fixture
findings. Its actual fresh filing journey remains pending.

Log hashes are in [followup/manifest.json](followup/manifest.json). Remaining
fresh-browser checks, the pending16-tuple decision, full review and the two
immutable complete gates remain open. No stage or #192 completion is claimed.
