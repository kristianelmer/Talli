# Remaining source-backed RF production integration

Status: implementation plan, not acceptance evidence. All full RF criteria remain
pending. These software slices can be implemented with synthetic companies; only
genuine-company records, authority and the final production pilot need a recruited AS.

## Intake and owner review

Keep canonical hashing on the backend. An omitted event digest in an HTTP capture
request is derived from the typed canonical event at its declared index. An
explicit digest still has to match, and invalid or duplicate indices still fail.
The internal source command always contains all event digests. This is implemented.

`rf1086ReadSourceIntakeBasis` now exposes typed public Governance reporting-year
evidence, including unresolved, superseded and amended records, receipt IDs,
dates, economics, original-document IDs and independent register references.
It preserves blockers and never certifies source capture or filing readiness.
The customer UI should use this policy-owned projection. Current source details
are available as an editable typed
draft through `rf1086ReadCurrentYearSource`, with confirmations reset and exact
predecessor identity retained. Capture verifies all evidence again after these
preparatory reads. The customer annual-source screen now provides scoped production review, explicit
warning acknowledgement, approval confirmation and exact-command uncertain retry.
Approval does not send. It also edits typed company,
shareholder, opening/closing and event facts, binds document roles, preserves
correction ancestry, and generates a separate preview after capture. Amounts stay
decimal strings and event times stay civil times. Content edits reset reviews;
uncertain captures retain an identical request and key even after a later
validation refusal. Independent register-observation intake now supports owner-scoped history,
current-version correction, before/after holdings, all three evidence roles and
stable retry requests. The capital-event UI selects an actual current observation
and the server action rereads its exact ID/version/hash instead of treating a
document as a register fact. Authenticated full-stack browser journeys remain
pending. Direct Governance API admission now resolves the exact current RF
observation, checks its scope/date/economics and verifies current originals through
Documents before Ledger recognition. Completed exact replay precedes these new
live checks. The successor implementation verifies bytes outside the guard, then reasserts
the exact current observation and retained-original receipts on the final guarded
Governance transaction connection before Ledger recognition. Unit/adapter checks
pass; database migration, concurrency and permission execution remain pending CI.
Explicit register withdrawal and its downstream invalidation also remain pending. Increased
nominal-value events remain visibly unavailable for complete source capture until
Governance support is implemented.

## Consequential freshness

The internal guarded source admission scope now composes Company Access, RF,
Documents and complete Governance/Ledger public projections on one short
connection after byte preflight. The capture/admission policy is shared, and the
yielded scope expires on exit. It has unit/adapter verification and collected
database tests, and bounded PostgreSQL approval verification. Complete database integration
remains pending. Approval now persists inside this scope; submission still needs
the same admission discipline.
Independent rereads followed by an RF write leave a race. The owner queries and
all writes affecting their projections must participate in company-scoped guards:
Company Access membership/identity, Governance records including cross-year
decisions, Ledger amendments, Documents retained metadata and RF source/review
state. Document a common lock order, preserving existing Authority-request before
Billing-entitlement ordering. Acquire guards before reading their projections.

Do not give RF access to other owners' tables. Compose narrow public adapters on
one authenticated connection. Keep byte downloads and provider I/O outside this
transaction. Documents now retains bounded immutable copies of verified original
bytes and supplies exact receipt/read/assert contracts. Approval binds and consumes those receipts; submission still needs
the same checks. Archive, backup, expiry and deletion handling
must include the new copies before production use. A copied original is not a
filing reference or approval.

Two-session tests must cover insertion into a previously empty year, prior-year
decisions, Ledger amendments, evidence changes, source corrections and membership
revocation. A writer either commits before admission and invalidates stale facts,
or waits until admission has committed. RF's source writers now acquire the
company guard before their year/document locks, with row-trigger backstops;
successor migrations now add Company Access, Documents, Governance, Ledger and
RF review/approval writer guards. Company Access supplies a narrow guarded
admission projection, and Governance consumes exact RF/retained-original
assertions in its final transaction. These successor migrations still require
database execution proof. Full-year RF approval composition is implemented; submission remains pending.
The legacy direct readiness upsert still computes outside an owned guarded
command; its row backstop alone cannot make that payload fresh.
The concrete owner interface and writer
inventory is in [consequential-freshness-write-inventory-20260924.md](consequential-freshness-write-inventory-20260924.md).

## Versioned manifest and existing journal

The pure `production-source-approval-v1` manifest builder is implemented. It binds
company/year/actor, source ID/version/hash, case hash, source preview and XML
hashes/order, complete freshness commitments, review acknowledgments,
entitlement/profile/adapter and optional correction ancestry. Stable shareholder
IDs use UTF-8 ordering and bounded hashed journal keys. Historical
`production-approval-v1` manifests, hashes and UUID ordering remain unchanged.
The builder does not persist approval or authorize sending.

The Billing full-year prerequisite now admits exactly `rf1086_full_year_v1`
through domain/HTTP/operator/generated contracts and the Billing CHECK. Omitted
profile preserves the historical default; unknown/null grant profiles fail.
Profile remains part of immutable entitlement identity and replay fingerprints.

The RF-owned immutable review bridge now projects a retained source preview into
`filing_previews` with the same UUID and no opening setup. A composite foreign
key binds company/year/source/source-hash/payload-hash. Review text, issues and
XML derive from stored preview bytes; shareholder keys match the versioned
source manifest. Application `prepare_review` performs that write inside held
source admission after original-byte checks. Exact replay requires a current
source; historical reads survive correction. The authenticated source-production review route materializes the bridge inside admission.
Legacy approval paths reject these previews. Full-year approval requires an
exact immutable source binding; full-year submission remains blocked.
Rollback suspends new bridges while retaining evidence and barriers.

Full-year approval now has a separate authenticated command. It requires
fresh source admission, exact review hash and warning acknowledgments, filing
permission, active exact-profile pilot, accepted preflighted Authority identity
and existing release inputs. Authority request locks precede Billing entitlement
locks; MFA and entitlement time checks use the clock after waiting. Hard review
comments remain blockers after acknowledgement. The canonical manifest and exact
historical review text are retained in immutable approval bindings; exact replay
rechecks current admission. Legacy approval cannot use source previews.

Historical full-year approvals are exported with source, preview, bridge, raw
review and canonical manifest lineage. Archive validation rebuilds the captured
identity without consulting the current source head. Predecessor approval binds
an exact terminal submission and its verified journal artifact set. Correction
approval now verifies every retained feedback original through Documents before
admission and compares the complete predecessor snapshot and receipts under the
final company/year and submission locks. Full-year send must repeat this check;
full-year predecessor submissions require their future archive contract.

The guarded database claim now persists an immutable source binding and one
company/year submission head, with exact historical recovery and legacy barriers.
Application send, original-byte revalidation and full-year recovery/archive
integration remain pending; no source send endpoint is exposed. The legacy stored-readiness gate is
still a prerequisite and must be replaced with owned full-year readiness based
on the verified source; it cannot substitute for those source checks.

Repeat all consequential checks in the transaction that persists the submit-once
claim. That commit is the admission point: later source changes require a
correction and cannot rewrite the claimed payload. Keep the existing production
journal, operation keys and unknown-outcome recovery. A company/year submission
head guard must prevent two different approvals from independently submitting
the first filing. Never automatically retry a provider POST after a timeout.

## Corrections and archive

A replacement binds the exact predecessor submission/manifest and an owner-reviewed
reason. Permit only supported terminal predecessor states with verified feedback;
sending, processing and unknown outcomes require reconciliation. Populate immutable
`supersedes_submission_id` under the company/year guard and reject forks, stale
predecessors, cycles and duplicate replacements. A source correction alone never
authorizes another POST.

Approval now checks the complete retained company/year submission chain inside
source admission. Initial approval requires empty history; corrections must
name its exact terminal leaf. All submitters and profiles are enumerated, and
ambiguous or incomplete chains fail instead of selecting the latest timestamp.
The database claim repeats this complete-history check and advances the managed
head atomically with claim insertion. Bounded PostgreSQL checks include an observed
two-session race, competing roots/forks, terminal full-year correction, populated
rollback and ordered predecessor replay. Maintained full-stack cases still await
CI. The application now connects the claim to source admission: scope comes
from the retained approval, exact source/review/manifest and predecessor receipts
are rechecked inside the guard, and retries recover the durable claim without
authorizing another POST. Provider dispatch remains unconnected.

A versioned archive includes source versions, previews, bridge bindings,
approvals and submission ancestry. Verify historical artifacts against their
captured immutable evidence, so an earlier archive remains valid after a genuine
correction. Missing or changed originals/receipts fail closed.

## Acceptance still required

Positive synthetic tests must reach full-year approval, journaled send, feedback
and correction/archive completion. Race, crash and unknown-outcome tests must
preserve exact original bytes and prevent duplicate logical submissions.
Nominal-increase Governance support, typed opening-anchor amendment visibility,
historical fund-issued capital and distribution clearance remain part of the
accepted scope. Broader service conformance, customer/browser/mobile journeys,
security/privacy/load/recovery validation, removal of obsolete generic writers
and two immutable complete gates remain outstanding independently of recruitment.

## Source readiness prerequisite

`rf1086-source-readiness-v1` now binds the selected full-year source and canonical
preview after guarded current-owner and original-byte checks. Its pure proof
explicitly excludes release prerequisites. Existing `source_facts` v1 still uses
opening-only readiness and twelve-family historical coverage; full-year
enumeration and the new source/preview/bridge/approval families remain to integrate.

Replacing the caller-written annual readiness snapshot must preserve opening
balance, unmatched bank items, unsupported unpaid items and annual authority
confirmation, plus period/interview/document warnings. These require complete
Banking/Ledger/annual-data owner projections and participating writer guards. A
ready RF source alone cannot silently remove those conditions. The six technical
release signoffs remain separate.

Full-year correction predecessor validation now rebuilds the retained source
approval and binds its durable claim to the exact submission, payload, actor and
parent. The approval and claim workflows share this policy and still verify
feedback originals before admission and retained receipts inside the guard.
This resolves the predecessor-profile limitation; complete archive export still
requires full-year claim/head coverage and historical journal verification.

## Full-year archive source and download checkpoint

The production archive now validates and exports source approval lineage, exact
submission claims, the managed filing head, complete correction ancestry, and
original document/confirmation journal commitments. Terminal results require
retained feedback and reconciliation; unknown outcomes remain unknown. API and
web transport retain these records, and company downloads reject missing or
changed source-original objects. This supersedes earlier statements that the
full-year archive source contract is absent. Consolidated restore, complete
retention generation and cross-year original-object inclusion remain pending.
See `source-submission-archive-20260928.json` for bounded verification.

## Canonical RF archive recovery record

The production endpoint and company download now retain `canonicalArchive`, a
closed versioned snapshot containing full typed sources, freshness/Governance
evidence and original filing history. The local Python verifier reconstructs and
checks that record through RF policy, including correction ancestry and unknown
outcomes. This closes the missing policy-verifiable source record in the export;
it does not close actual database/object restore, unapproved source/observation
history export, retention generations, expiry/cancellation or deletion.


## Exact historical document recovery primitive

Documents now exposes an owner/AAL2-protected query for an exact retained
original by document/company/source year, metadata hash, content hash and length.
The returned snapshot includes captured metadata and verified bytes, independently
of current metadata or mutable bucket availability. PostgreSQL evidence proves
multiple retained versions, source-year separation, closed mismatches, narrow
executor permissions and lossless lookup rollback/replay. This removes the need
for RF to know an internal Documents receipt ID in order to request historical
originals. Company archive composition and portable cross-year byte bundles are
still pending; no database/object restore is claimed. See
`historical-original-recovery-20260928.json`.


## Portable approved-source originals

The production RF endpoint and company download now compose exact historical
source-original metadata and bytes via Documents public contracts. Prior-year
source evidence is preserved without substituting the current-year document
projection. The local verifier checks these records against canonical RF source
commitments, and `--require-source-originals` rejects incomplete bundles. This
supersedes the pending approved-source byte-composition item above. Actual
DB/object hydration, feedback and other document byte bundles, unapproved source
history, streaming bundles beyond the bounded inline limit, and complete
retention/expiry/cancellation coverage still need implementation and proof.
See `source-original-bundle-20260928.json` for the bounded evidence.


## Guard recutover validator and archive composition checks

CI run 36398579593 identified the exact final recutover failure: PostgreSQL's
language validator rejects replacing a routine as its owner when that owner's
EXECUTE privilege was previously revoked. The guard migration now temporarily
borrows that exact owner permission and restores it after replacement. A bounded
PostgreSQL replay/rollback probe preserves routine and role identity and keeps
admission fail-closed. The web composition harness also loads the real RF archive
verifier, resolving two missing-dependency failures. Full final-revision CI remains
pending. See `recutover-validator-20260928.json`; no acceptance criterion changes.


## Complete retained source-history export

The production adapter now reads every scoped source version and head, register
observation/correction, source preview and review bridge on the same repeatable
snapshot as the filing journal. V2 canonical archives retain original capture
text, idempotency keys and request hashes, as well as historical renderer output
and creator/time. Approved and unapproved evidence contributes exact historical
Documents originals. The offline verifier can require complete source history
and source bytes separately; v1 archives remain byte-exact and explicitly partial.

This supersedes earlier pending items for unapproved source/observation history
export. It does not complete database/object restoration, feedback/other object
bundles, streaming, retention generations, expiry/cancellation/deletion or the
remaining dispatch/readiness/recovery and release gates. See
`complete-source-history-20260928.json` for bounded verification.


## New feedback original retention

New feedback uploads now pass Documents original-byte verification and retention
before RF records their artifact metadata. RF checks the exact metadata and byte
commitments; an ambiguous retention error preserves the uploaded record and does
not acknowledge the artifact. Existing canonical artifacts retain idempotent reuse.
Older artifact backfill, durable RF-to-original receipt linkage and portable
feedback bundles remain pending. See `feedback-original-retention-20260928.json`.

Previous-revision CI run 36400398886 passed Application but Database isolation
timed out after a failure in the RF lane. Complete final-revision CI remains
pending; this is no longer an active run or passing database evidence.


## Atomic feedback original linkage

The owned RF writer now stores the exact Documents original identity, metadata
digest, source year and retention time with each new feedback artifact in one
transaction. It reasserts the receipt under the company guard; RF gains no byte
read privilege. Bound records reject mutation. Legacy canonical rows retain
explicitly absent bindings. This supersedes the new-record binding item above;
legacy recovery/backfill and canonical/portable feedback archive composition
remain pending. See `feedback-original-binding-20260928.json`.

Run 36411282456 at 85cae057 passed Application and real feedback retention/recovery
cases, then failed at year-scoped archive reading. The disposable test now exposes
the underlying SQL diagnostic while production keeps its safe error boundary.
That archive failure and final-revision database/release verification remain open.


## Portable feedback originals

The v3 canonical record and HTTP/download composition now preserve exact retained
feedback bindings and original bytes. Offline strict verification rejects legacy
unbound artifacts; source and feedback bundles share the 128 MiB limit. Current
bucket metadata cannot replace a bound historical original. Older codecs remain
byte-exact round-trippable. This completes the portable feedback composition item
above, but not legacy backfill, database/object restoration or release acceptance.
See `feedback-original-export-20260928.json`.

Run 36413115758 at ae0b2a0c failed at the new retained-feedback writer and a stale
Application test expecting the old writer name. The corrected isolated probe
reproduced missing Documents schema USAGE for the RF store owner, and passes with
the explicit schema grant. The static expectation is updated. The older archive
read failure was not reached; final-revision CI and all RF acceptance criteria
remain pending.


## Confirmed full-year feedback recovery

Read-only recovery now accepts the full-year profile only after reconstructing
its retained source approval, immutable claim, complete POST journal and exact
confirmation/dialog relationship. It uses approved source document keys and XML,
keeps owner/submitter/connection checks, and permits historical recovery after
pilot expiry or approval invalidation. Missing or altered evidence stops before
token acquisition and releases the lease. An unknown unconfirmed POST remains
unknown. Legacy send explicitly rejects the full-year profile. See
`source-feedback-recovery-20260928.json` for bounded local/API evidence; actual
full-schema recovery execution and final-revision CI remain pending.

Run 36415185712 stopped in the disposable Ledger bootstrap before RF: readiness
accepted the temporary socket-only initialization server. TCP readiness fixes
that observed race; the actual complete Ledger lifecycle rehearsal passes locally.
Application subsequently passed, including the complete launch rehearsal and
production dependency audit. Database did not reach RF. Run 36417395568 at
7e7382c7 now verifies the TCP readiness fix and confirmed source recovery.

## Exact historical correction originals

Correction admission now reads each bound feedback artifact's exact historical
Documents original. It verifies captured metadata, bytes, attribution and every
receipt binding before admission. The final transaction compares the complete
predecessor snapshot and reasserts that same historical receipt under the company
guard. Current metadata changes cannot substitute a different original. Legacy
unbound feedback continues its current-evidence check without claiming historical
coverage. The Documents assertion requires READ COMMITTED and rechecks live
ownership after waiting; it grants RF no byte or table access. Bounded PostgreSQL
verification covers exact identity, stale snapshots, revocation during guard wait,
rollback/replay and preserved grants. Full-schema execution remains pending.
See `historical-correction-originals-20260928.json`. Source send, owned annual
readiness, retention generations and actual restoration remain open.


## Full-year facts and predecessor rehearsal restoration

The source-facts projection now uses `rf1086-source-v2` for complete retained
full-year history. It shares one repeatable database snapshot with legacy facts,
validates original archive lineage and checks independent counts for all eight
new families. Historical v1 hashes remain unchanged. Complete coverage does not
imply current full-year readiness; that status explicitly remains unevaluated
until owned annual and fresh admission composition is completed.

Run 36417395568 at 7e7382c7 passed Application and reached RF in Database. The
retained-feedback writer was absent (SQLSTATE 42883) because the earlier Authority
predecessor fixture restored only older RF layers after dropping the schema.
The fixture now captures installed successors from the migration inventory shared
with the final harness and restores them after the RF contract. It refuses
populated new binding/head families and bound feedback before teardown. The
local orchestration tests verify restoration even when the predecessor test
raises; actual full-schema restoration remains pending CI. See
`full-year-facts-rehearsal-20260929.json` for the bounded validation checkpoint.


## Banking year observation and archive chronology

Banking now exposes an owner-authorized, unpaginated year reconciliation
projection. One statement counts canonical facts, unmatched facts and accepted
warnings, explicitly distinguishing an empty year from forbidden access. This
is a read input for future annual readiness, not a filing decision or proof that
all bank statements were imported. Banking writer guard coverage, current
opening/annual interview checks and consequential RF composition remain open.

Actual PostgreSQL execution exposed a full-year archive validator bug: review
projections retain transaction timestamps, while their subsequent bridge rows
retain wall-clock timestamps. Validation now preserves both originals and checks
ordering instead of requiring equality. Retained review binding/hash checks are
unchanged. The legacy year-scoped archive case also passes locally.

Run 36536926077 at 5e3a03a5 failed because the Documents predecessor rehearsal
left the newer historical assertion installed before schema rollback, and an
Application assertion expected an older Documents migration inventory. Both
are corrected. The rehearsal restores the assertion only if originally present
and checks runtime/browser grants. Full-year approval database fixtures now use
valid Authority reference encoding, real owner context for RLS-backed triggers,
and exact public error outcomes. See `bank-year-archive-repair-20260929.json`.
Final-revision CI and all seven RF acceptance criteria remain pending.

Claim timestamps now decode consistently from PostgreSQL JSON (which trims
fractional zeros) and native row values, retaining every microsecond. Finer
precision is rejected rather than truncated. A complete local 101-case
approval/claim/original run passes. One earlier source capture returned
`rf1086_source_storage_invalid` without a diagnosed cause; retain that lead if
it recurs. The local Auth shim does not replace the full Supabase CI lane.


## Restricted Banking fixture checkpoint

Run 36541117434 at da69cdc9 passed Application. Database passed 83 Python
cases before the Banking fixture attempted a private-table INSERT without
owner authority. The fixture now borrows/restores exact SET membership and
seeds through Banking's FORCE-RLS owner. That revealed an invalid unadmitted
2025 fixture; year isolation now checks that all 504 valid 2026 facts are
excluded from a 2025 query. Two rollback/replays preserve an actual retained
fact and exact authority. The old test reproduces the CI permission failure;
the repaired three cases pass under a non-superuser without direct Banking
INSERT privilege. See `bank-fixture-authority-repair-20260929.json`.
Final Supabase CI, Banking writer guards and annual composition remain open.


## Banking writer admission checkpoint

The 22 canonical Banking mutation/row-locking RPCs now acquire the company
guard before their original body and recheck ownership after waiting. All
eight Banking tables have row backstops. Sync completion/failure also binds
the retained attempt to the requested company before touching its row.
Rollback suspends guarded writers; replay preserves routine identity, ACLs
and facts. The historical Banking workflow rehearsal restores this successor.

Thirty-two new PostgreSQL cases pass, including one actual wait/revocation
case per RPC, and pass again under a restricted migration principal. The
existing Banking lifecycle rehearsal and 101 RF/Documents cases also pass.
See `banking-company-guards-20260929.json`. Raw legacy/browser writes still
need retirement or early admission; their row backstop alone cannot establish
lock ordering. Final owned annual-readiness composition remains open.

The shared Authority/final successor manifest also restores Banking guards.
Tax prepare now restores them after settlement expansion; direct PostgreSQL
verification confirms the historical expansion removes exactly two wrappers
and successor replay restores all 22. Full ordered Tax prepare awaits CI: the
bounded local fixture already removed a Governance table required by its
Investments predecessor. No Tax behavior or scope was expanded.

## Annual interview guard and CI fixture repair

Existing `public.annual_data` INSERT/UPDATE/DELETE now acquire the company guard
through a private infrastructure trigger, including both scopes on reassignment.
The frozen history reader still returns years up to the requested year. RF must
select and validate its exact year. Writer rules, RLS, values and ownership remain
unchanged; this adds no Annual Compliance coordinator or checkout authority.
Rollback suspends writes without losing facts; replay restores them with exact
role and schema authority. Seven PostgreSQL cases also pass under a non-superuser
starting without SET access to the guard owner.

CI run 36548714542 passed Application but its Database job reached the 30-minute
limit. The stack showed a preview test synchronously revoking ownership in a
second transaction while holding the same company guard. Revocation now commits
on the guard-holding transaction; the waiting preview must return FORBIDDEN.
The next bridge test now binds both verified actor fields and positively checks
source visibility before asserting the legacy-production rejection. Its former
incomplete fixture hit a foreign-key failure instead of the intended barrier.
A fresh broader PostgreSQL run passes all 405 RF cases; 70 CI harness tests and
the architecture checker also pass. See
`annual-interview-guard-and-ci-repair-20260929.json` for current verification.
Full Supabase CI and owned annual-readiness composition remain open.


The next full Supabase CI exposed a migration-authority gap before tests: the
annual guard did not borrow SET for the independent backend_system schema owner.
Both expansion and rollback now borrow/restore that role as well as the function
owner. A corrected restricted fixture retains Ledger schema ownership, reproduces
the published failure and passes two repaired rollback/replays plus all seven
annual guard tests. See `annual-guard-schema-owner-repair-20260929.json`.
