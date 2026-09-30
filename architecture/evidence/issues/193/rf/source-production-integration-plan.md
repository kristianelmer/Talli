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

The isolated full Supabase rehearsal then passed installation and Ledger/Banking
lifecycle but exposed an Investments fixture applying the Banking successor before
its deferred claim routine existed. The fixture now installs the guard immediately
after that prerequisite. Its complete PostgreSQL lifecycle passes and verifies all
22 Banking wrappers remain installed at the end. The full rehearsal is rerunning.

## Guarded annual input checkpoint — 29 September

RF admission now has complete exact-year Banking reconciliation evidence,
Ledger opening-bank inputs and period-lock history, the frozen annual interview,
active Documents metadata, and RF-owned opening/holder evidence on the same
held connection. Documents visibility is derived from the current Company Access
admission after the company guard, replacing empty or stale session role maps.
Opening evidence commits lock/creation timestamps, attribution and all holder
fields without rendering a no-activity case. The existing RF owner queries retain
their migration-quarantine refusal. These inputs are implemented; final policy
composition and removal of the stored annual readiness prerequisite remain open.

The next implementation must preserve the RF conditions in the frozen annual
readiness consumer: exact-year locked opening, unmatched unaccepted bank items,
unsupported unpaid items and annual authority confirmation, plus period-lock,
interview, bank-confirmation and Documents warnings. Missing interview remains
an RF warning under that source policy; it must not erase the separate current
Authority permission check. Bind the Ledger bank-input snapshot ID to the
matching RF opening identity. Do not equate an onboarding opening with statutory
start-of-year capital for a formation case or infer statement coverage from a
successful empty Banking enumeration.

Compose a versioned RF-owned immutable proof through the thin application
workflow. Bind scope, source/preview and exact input identities/digests, recheck
inside approval and first-send admission, and preserve historical approval/claim
and archive verification. Current review/overrides, warning acknowledgements,
Authority, Billing and the six technical signoffs remain independent release
requirements. Replace the stored-ready SQL seam only when this entire path has
positive and negative database coverage; keep legacy profiles and frozen annual
writers unchanged. Full-year dispatch/recovery follows that replacement.

## RF annual decision checkpoint — 29 September

The read-only annual composition is implemented as
`Rf1086AnnualReadinessInputs` / `Rf1086AnnualReadinessProof`. It binds the exact
source/preview and five owner-evidence digests, preserves annual blockers and
warnings, requires the Ledger opening-bank identity to match RF's opening, and
uses RF policy after all sequential reads on the held admission. Source-only V1
proofs and historical approval manifests remain unchanged. Tests cover all seven
supported source-event profiles, changed same-count metadata, unavailable/foreign
owner reads, current interview changes, accepted Documents warnings and exact
proof tampering. A real database composition moves missing → warning → ready →
blocked without changing the immutable filing source.

This closes the missing read-side annual decision. It does not replace
`rf1086_stored_release_inputs_v1`, change approval/review SQL, or expose sending.
The next step is a versioned consequential binding: retain the annual proof in
new approvals, combine its exact warning set with review, and rebuild it at
approval and the first durable claim/send. Preserve old manifest/archive hashes
and historical recovery while rejecting stale annual evidence for new effects.
The SQL/application boundary must require this RF-owned proof and independently
preserve overrides, Authority, Billing and technical gates before the browser-
written stored-ready prerequisite can be removed.

## Guarded annual approval and claim — 29 September

Full-year review and approval now rebuild RF annual policy from all five owner
inputs inside source admission. Manifest V2 retains that exact proof and required
warning acknowledgements. First claim repeats those owner reads and requires the
same proof, review and manifest bytes; even a same-value metadata change requires
a new approval. A committed exact claim remains recoverable without fresh annual
facts. Unclaimed V1 approvals must be replaced by a current V2 approval, while
historical V1 manifests, archives and committed claims keep their original hashes.

Private V2 SQL replaces the stored-ready snapshot prerequisite for these new
full-year effects. It preserves RF and non-RF blocking overrides, review comments,
Authority/Billing linkage, post-wait MFA/expiry and technical signoffs. The HTTP
contract accepts no caller proof or ready flag. RF Python remains the policy owner;
SQL binds server-computed proof bytes and validates identity, held locks and the
independent authorization/release requirements. Direct browser and old V1 effect
RPC grants are closed. Rollback suspends new effects without discarding history
or reopening V1; historical successor rehearsal restores V2.

This does not expose full-year provider dispatch. Its profile-specific send,
uncertain-outcome recovery and final acceptance verification remain next. Local
unit/database and restricted migration-authority evidence is recorded separately;
full Supabase CI at the final revision is still required. All seven RF acceptance
criteria remain pending.


## Retained dispatch position — 29 September

The RF-owned dispatch assessment now distinguishes current admission, retry
admission, uncertain recovery, blocked, old approval, and confirmed states from
complete retained claim/payload/journal evidence. It retains the exact original
key and attempt without incrementing either in memory. Confirmed feedback
recovery uses this assessment before obtaining credentials. It rejects conflicting
or gapped attempt histories and downstream mutation intents without predecessor
success. Synthetic coverage includes all seven supported source profiles,
crash/unknown at each mutation, retry exhaustion, malformed lineage and correction
ancestry. This closes a recovery-validation gap, not provider dispatch admission.

## Durable operation admission — 29 September

The versioned initial/retry intent command now commits one prepared event before
provider I/O. It serializes concurrent callers under company, year and submission
locks, requires the exact failed event before retry, and preserves the original
key and payload. Only `newlyPrepared=true` grants a new operation. Prepared,
unknown, blocked, exhausted and already-successful operations cannot grant another
POST. An unexplained unknown submission projection also requires recovery.

Initial main-document admission rechecks the retained V2 annual proof and current
review. Subsequent documents retain the original approved bytes while rechecking
current owner/MFA, Authority, Billing, overrides and technical release gates.
Each document requires persisted predecessor success. The outcome command binds
the exact intent, accepts identical replay and rejects conflicting or stale
outcomes. Rollback closes new intent admission but preserves in-flight outcome
recording. Generic full-year mutation journal commands cannot bypass this path.

Thin application dispatch integration remains next. It must rebuild current annual
facts under admission before the initial intent, commit before external I/O,
consume `newlyPrepared` explicitly, and discard its provider binding afterward.
An existing claim alone never grants send authority. Cover this integration's crash
windows and authority changes with a synthetic provider before exposing any route.
All seven RF acceptance criteria remain pending.

## Synthetic application dispatch — 29 September

The thin full-year dispatch component now consumes durable operation grants. It
validates retained claim/payload/history, acquires a disposable Authority binding
outside the database guard, rebuilds current annual evidence before main-document
admission, and returns a send grant only after the intent transaction commits.
Continuation keeps original approved bytes and keys while rechecking current
authorization. Confirmed replay needs neither current source bytes nor another
provider binding. An uncertain intent or response never grants another POST.

The versioned intent RPC also binds the acquired Authority request ID and external
reference to the current locked Billing/Authority linkage. A reconnect during
credential acquisition therefore cannot authorize a POST with the old binding.
Old intent RPC execution is revoked, including after rollback; in-flight outcome
recording remains available.

Synthetic tests cover all seven source profiles, competing sends, known retries,
commit failure, cancellation, lost responses and outcome persistence failures.
Actual PostgreSQL tests use a second connection during each synthetic POST to
prove that its prepared intent is committed and its company guard released.
The complete source-capture → original verification → approval → claim → dispatch
flow uses real RF, Billing and Documents persistence with synthetic storage and
Authority. Changed original bytes or annual facts during binding block dispatch;
confirmed replay uses the retained evidence after current storage bytes change.

This component is not yet composed into HTTP. Route/UI integration, uncertain
outcome reconciliation, actual database/object restore, retention generations,
streaming archives and final security/browser/recovery acceptance remain. Local
PostgreSQL Auth/Storage shims do not substitute for exact-revision Supabase CI.
All seven RF acceptance criteria remain pending; no real AS or provider was used.


## Authenticated dispatch and owner status — 30 September

Strict full-year send HTTP and generated client contracts now compose the guarded
dispatch path. Only approval ID, exact manifest hash and expected predecessor
are accepted. Unknown/blocked operations retain distinct errors; a lost response
never causes a transport retry. A separate authenticated read publishes validated
retained dispatch position without a claim, configuration requirement, current
original download or provider credentials. Existing API contracts are unchanged.

The source screen lists retained full-year approvals independently of current
source availability. Approval and send are separate owner actions. The server
action rechecks scope and exact retained identity; the backend alone authorizes
each effect. The screen clears send controls after every attempt until a new
status read. Unknown and blocked positions expose no send control. Confirmed
positions use the existing read-only feedback flow. A synthetic browser check
caught a misleading default “Sent” feedback label on uncertain history; feedback
labels now appear only after confirmation. This isolated component check is not
the authenticated full-stack browser acceptance journey.

Predecessor CI cf0ae48d passed Application and 700 Authority/RF database cases.
The following database lane stopped after 496 passes: its rollback rehearsal
stripped COMMIT but did not emulate ON COMMIT DROP, leaving migration-local
temporary tables across boundaries. The rehearsal helper now cleans only tables
declared ON COMMIT DROP by that migration. All 110 affected lifecycle and durable
operation cases pass locally. Exact-revision Supabase CI still remains required.

Remaining RF work includes uncertain-operation reconciliation, full authenticated
browser/security/recovery journeys, legacy feedback backfill, actual database and
object restoration, retention generations, streaming archive bundles and the two
immutable acceptance gates. All seven acceptance criteria remain pending. No
production setting, actual provider operation or real AS data was used.


## Streaming retained originals and recovery research — 30 September

An additive authenticated `archive-source/production-stream` GET now returns the
validated canonical record, each exact retained source/feedback original, and a
mandatory terminal count/hash commitment. It fetches one original at a time,
retains the Documents per-record bound, and caps combined original content at
1 GiB. The existing 128 MiB inline JSON contract is unchanged. The generated
client leaves the response body unconsumed; HTTP 200 alone is not completeness.
The offline verifier's `--stream` mode verifies bounded lines in order, exact
metadata/bytes, completeness and the terminal commitment without extracting or
writing anything. Legacy unbound feedback remains explicitly incomplete.

Local checks cover corruption even with a recomputed transport hash, truncation,
wrong scope/attribution, unavailable originals, actor mismatch, cancellation,
non-buffering client behavior and scaled aggregate limits. A full 1 GiB load
rehearsal, browser download integration and database/object restoration remain.

Public provider research found documented same-key/body main/child replay but
no specified retention window or deduplication scope, plus a confirmation-header
discrepancy between prose and OpenAPI. Unknown operations remain stopped; no
replay window or negative discovery proof was invented. See
`unknown-outcome-recovery-research-20260930.md` for pinned primary evidence and
remaining provider clarification/conformance requirements. This does not require
an AS to continue independent software work. All seven RF acceptance criteria
remain pending; no live business-provider action or production setting changed.


## Owner archive download and allocation profile — 30 September

The owner source screen now links a separate RF archive download. Its route
validates exact company/year, requires accepted ownership and the existing
archive-export MFA check, and forwards the backend stream without materializing
it. It keeps only local attachment/security headers; cancellation and a bounded
five-minute lifetime reach the backend. The download remains available when the
current editable source cannot be read. Existing company-wide exports are unchanged.

Executable tests import the actual route with explicit identity/dependency stubs;
they cover authorization order, missing login, wrong company, non-owner roles,
MFA failure, malformed/duplicate scope, safe errors, cancellation and body failure.
They do not establish authenticated full-stack browser acceptance. The Next
production build checks route integration.

The committed manual load regression sends exactly 1 GiB/103 synthetic retained
originals through an OS pipe with strict history/feedback verification. It passes
its 256 MiB live Python-allocation ceiling: measured export peak ~70 MB and
verification ~81 MB. macOS peak RSS remains ~0.8–0.9 GB, including fixture/application
imports. Stable live allocations across records argue against retained document
collections; platform/native memory and real HTTP/browser concurrency sizing remain
open. No allocator workaround or weaker byte verification was introduced.


## Authenticated archive browser verification — 30 September

The actual owner browser journey now downloads the RF NDJSON archive from the
source page through Next, FastAPI and real isolated Supabase Auth/Storage. The
offline verifier confirms exact company/year, the filing record and both retained
feedback originals, including the terminal commitment. The same journey checks
MFA and cross-company denial, mobile layout, no extra provider mutations, no
egress violations and a clean browser console. It uses a synthetic legacy
no-activity submission; full-year source capture, review, approval and send still
need their authenticated browser acceptance journey.

This exposed duplicate React sibling keys on the source page: the editor and
submission panel both used company/year. Distinct panel prefixes preserve scoped
state reset and remove the console error. The browser assertion failed twice
before that fix and passed afterwards. The final focused command passed all 16
cases (one complete journey plus 15 fixture checks); 74 focused web and 88 CI
control checks also passed. The 1 GiB allocation regression is now included in
the launch rehearsal so the next Linux CI run measures it.

One earlier local database run rejected exact completed-operation replay with a
redacted persistence error. It did not recur in 60 isolated repetitions, another
60 repetitions following the real Supabase predecessor sequence, or CI at
78c19b38. The diagnostic RF/Authority suite passed 619 cases. Its cause remains
unresolved; a test-only exception note now retains SQLSTATE without exposing SQL
or credentials. No runtime behavior was changed based on that observation.

CI at 78c19b38 passed Application, Database isolation and Release gate; immutable
evidence was skipped. The corrected browser was verified against final contracts
in a focused local run; it is not a claim that the entire ordered local rehearsal
passed after the fix. Current-revision CI remains required. See
`authenticated-archive-browser-20260930.json`. All seven RF acceptance criteria
remain pending; restoration, retention generations, full-year browser/recovery
acceptance and both immutable gates remain open.


## Full-year authenticated browser journey — 30 September

The synthetic 2026 owner journey now uploads a real original through Documents,
captures two shareholders and a share transfer, previews and approves current
annual evidence, sends through the guarded source path to the loopback authority
mock, reads accepted feedback, and downloads/verifies the retained RF archive.
Only admission, opening facts, a pilot entitlement and local release prerequisites
are prepared; no source, approval, submission or provider receipt is seeded.
The legacy no-activity journey still runs in the same command. All 16 cases pass,
with 200 focused web/fixture checks and 83 CI control checks also passing.

The browser exposed three integration defects: the web review gate used a frozen
legacy readiness flag; the non-RF override receiver still referenced the generic
table after Accounts retired it; and a new approval did not update the send
panel's initial selection. Review now discovers the exact exempt pilot before
backend assessment; the receiver follows the existing owned override contract
after cutover; and a newly approved ID resets selection/status/consent. Annual
warnings also have distinct explanatory text. Current backend approval/send
checks remain authoritative. A canonical blocking override still prevents review
in the final topology, and legacy readiness is deliberately false throughout.

The archive verifier confirms one source version/approval/claim/submission,
one source original and two feedback originals. Sent main/child XML hashes match
the approved preview. Reload, mobile widths, clean browser/egress checks and
fixture cleanup are included. This proves a mock happy path, not correction,
crash/unknown-outcome acceptance, external conformance or a real AS pilot.

CI at 242cb29f passed all required jobs, including the Linux allocation rehearsal;
immutable evidence was skipped. Current-revision CI remains required, including
the new receiver's pre-cutover/rollback regression and the full ordered topology.
See `full-year-source-browser-20260930.json`. All seven RF acceptance criteria
remain pending. No production setting, hosted database or genuine filing changed.

## Historical fixture successor restoration — 30 September

CI at 87549d59 passed Application and 560 RF/Authority database tests, then failed
the full-year browser review with 503. The historical V1 approval fixture's
teardown replayed the original annual migration, overwriting the newer override
receiver before Accounts retired the generic table. A real database regression
reproduced this replacement in 1.21 seconds. The fixture now records installed
successors before its rewind and restores them in registry order.

The regression passes, preserving the exact receiver, role memberships and
successor topology. The subsequent final contracts and combined legacy/full-year
browser pass all 16 cases; 89 CI-control checks also pass. CI at e985ebd9 then
passed Application and 497 RF/Authority cases, but the historical lifecycle
exposed the receiver's missing rollback file. See
`historical-source-fixture-restoration-20260930.json`. This changes test cleanup;
all seven RF acceptance criteria remain pending.

## Accepted full-year correction browser journey — 30 September

The authenticated full-year journey now continues from accepted feedback through
a correction. It uploads a distinct original for corrected share-transfer
consideration, captures a second source version, previews and reviews current
evidence, selects the accepted predecessor and saves an explicit replacement
approval. The guarded send and feedback paths produce a second accepted filing.

The browser proves the first approval and preview are unchanged, the new payload
is selected after server revalidation, the replacement points to the accepted
predecessor, and the old approval remains readable without a resend action.
Offline archive verification checks both versions, approvals, claims and filings,
two source originals and four feedback originals. All 16 combined browser checks
pass. No application behavior changed. See
`full-year-correction-browser-20260930.json`; exact-revision CI remains required.

This covers an accepted-predecessor correction against a loopback authority mock.
Rejected-predecessor, crash/uncertain-response and adversarial full-year browser
cases, external conformance and the remaining restore/retention/acceptance work
remain open. All seven RF acceptance criteria remain pending.

## Override receiver rollback and full RF lifecycle — 30 September

The missing receiver rollback now closes the override prerequisite while keeping
retained approvals, claims and outcomes readable. It preserves owner/grant state
and never reopens the retired generic table. Forward replay restores the current
owned query. A fast registry check catches a missing forward/rollback pair before
the database lane reaches its historical lifecycle.

The complete local RF/Authority suite passes 562 cases, followed by 15 reporting
clone cases. An additional durable-operation regression verifies that an in-flight
outcome can still be recorded, the next intent is blocked without a journal
append, and forward replay restores admission. After those checks, final contracts
and all 16 legacy/full-year/correction browser checks pass. All 90 CI-control
checks pass. See `override-receiver-rollback-20260930.json`. Complete ordered CI
at the new revision remains required; all seven RF acceptance criteria are pending.

## Full-year lost-response browser journey — 30 September

The correction journey now adds a third source version and explicit replacement
approval, then loses the main-form response after the loopback mock records its
mutation. The owner sees an unknown outcome with no send, continue or feedback
action. Two repeated exact commands return 409; status rereads and reloads add no
provider call or token acquisition and leave the claim, head and journal unchanged.

The journal retains one prepared intent and its unknown result with the same key,
approved XML hash and attempt. No receipt or feedback is invented. The downloaded
archive verifies three source versions, approvals, claims, submissions and source
originals, plus the four feedback originals from the two earlier accepted filings.
All 16 combined browser cases and 15 fixture-safety cases pass; owned-environment
cleanup passes. See `full-year-unknown-browser-20260930.json`. Exact-revision CI
remains required.

This covers a lost main-form response, not lost child/confirmation responses or
external recovery conformance. Remaining crash, rejected-predecessor, security,
restore, retention and immutable-acceptance work stays open. All seven RF
acceptance criteria remain pending.

## Lost child and confirmation response journeys — 30 September

The browser command now runs fresh full-year histories for lost main, child and
confirmation responses. In each case the loopback mock records its mutation before
disconnecting. Received main/child references survive; the unknown operation gains
no receipt. The journal preserves exact keys, approved payload hashes, confirmation
commitment and attempt 1. Two exact retries, reloads and status reads leave provider
calls and durable state unchanged. The owner has no send/continue/feedback action.

All 20 browser/fixture cases pass, including strict archive verification for each
unknown stage. All 90 CI controls pass. Base CI at dacb9bd3 passes Application,
Database isolation and Release gate; immutable evidence is skipped. Its database
job took 27m05s. The job limit is now 45 minutes to accommodate two additional
sequential browser histories; each scenario still has a six-minute limit. See
`full-year-all-unknown-browser-20260930.json`. Current-revision CI remains required.

This closes the three lost-response browser scenarios. Process crashes, prepared
intents, rejected-predecessor correction and remaining security/conformance cases
still need browser evidence. Actual restore, retention and both immutable
acceptance gates remain open. All seven RF acceptance criteria remain pending.

## Owned local RF database restore — 30 September

The full-year browser journey now restores a custom-format database dump into a
fresh database in the same owned disposable cluster. Recovered RF source history,
approvals, claims, journals and filings must equal the strict browser archive.
Documents reads and validates all three source originals and four feedback
originals, including their captured metadata and bytes. An unrelated actor is
denied both RF history and Documents originals. The clone is removed, with source
history and cluster role memberships unchanged.

Owner reads use the existing restricted backend login, with its endpoint checked
against the owned source. The maintenance login is used only for source identity
verification and backup/restore operations. No role grants are added. The initial
rehearsal correctly failed when its owner reader used the maintenance login; that
runner wiring is corrected and 13 boundary/cleanup tests pass.

This proves recovery of this synthetic full-year history and database-retained
original bytes. It does not recover ordinary Storage objects or roles into a new
cluster, nor cover restored prior-year/unapproved history, cancellation, expiry or
deletion. The broader restore signoff and all seven RF acceptance criteria remain
pending. No product behavior or production enablement changes.

The broader architecture unit suite also exposed a missing RF archive condition:
its exact-body exception did not require retired Tax/Accounts facades and
exclusive Accounts ownership of all six shared filing sources. The existing
negative regression reproduced the gap. The RF exception now preserves both
requirements, and CI runs that regression suite as well as the current-state
architecture check. This changes the RF architecture guard, not Tax or Accounts
business behavior.

## Process-crash browser recovery — 30 September

The full-year browser now covers actual backend process loss after main-form,
child-form and confirmation mutations. The loopback mock records each selected
mutation and holds its response. The browser observes the committed prepared
intent, kills its owned backend with SIGKILL, verifies the exit signal, and starts
a new process against the same durable database.

After restart, the submission remains `sending` with a prepared intent and no
fabricated outcome. The owner sees `recovery_required` and has no send, continue
or feedback action. Initial reads, reloads and two exact retries produce no token
or provider calls; the retries return 409. Claims, head, journal, references and
feedback remain identical to the pre-crash snapshot. The strict archive keeps
all three source versions and submissions, three source originals and four
earlier feedback originals. The confirmation crash does not invent a receipt.

All six lost-response/crash journeys and 20 fixture checks pass (26 total). A
focused main-crash rerun also passes after adding actual database restoration for
that prepared-intent history, including retained bytes and unrelated-actor denial.
These are synthetic provider effects. Before-I/O process-loss browser coverage,
rejected-predecessor and remaining security/conformance cases, broader object
restore/retention and both immutable acceptance gates remain open. All seven RF
acceptance criteria stay pending.

## Process loss before provider mutation — 30 September

The browser now also kills the owned backend after its real operation intent has
committed, before the sender receives its grant for main, child or confirmation
POST. A nonce-bound, one-use private file arms a barrier in the local test launcher;
there is no production hook or new HTTP endpoint. Eight barrier tests verify
commit ordering, arm matching/consumption and cancellation without grant delivery.

All nine full-year browser histories and 20 fixture checks pass (29 total). In each
new case, the selected POST never reaches the loopback provider. Restart preserves
the exact prepared intent, keys, approved hashes, successful earlier references,
claims and history. Two exact retries return 409; status reads and reloads acquire
no tokens and make no provider calls. The owner remains in `recovery_required`.
All three main-stage histories also pass actual same-cluster database restoration
and retained-original byte verification. See
`prepared-before-mutation-browser-20260930.json`.

This closes the three browser scenarios for process loss after intent commit but
before provider mutation. Rejected-predecessor correction, remaining security and
provider conformance, unknown-operation reconciliation, broader object/role
restore and retention, legacy feedback backfill, HTTP/concurrency sizing and both
immutable acceptance gates remain. All seven RF acceptance criteria stay pending.

## Rejected-predecessor correction — 30 September

The browser now receives a real loopback rejection through the shipped XML and
Dialogporten adapters, then captures corrected source evidence, explicitly
approves replacement of that rejected submission and receives acceptance for the
new filing. The original remains `rejected` with its exact feedback artifacts and
journal. Reloading the old approval still shows `Avvist` without a send/continue
action; the new approval identifies the accepted replacement.

Both accepted- and rejected-predecessor browser journeys pass, including a later
unknown main response, strict three-version archives, actual same-cluster database
restore and retained-original bytes. The 21 RF and seven existing Authority
fixture checks pass. The full CI matrix now contains ten browser histories; its
new-revision result remains required. See
`rejected-predecessor-browser-20260930.json`.

The rejection fixture consumes its selected outcome at confirmation and returns
to acceptance for the next filing. No production behavior changes. Remaining
security/conformance, unknown-operation reconciliation, broader object/role
restore and retention, legacy feedback backfill, HTTP/concurrency sizing and both
immutable acceptance gates stay open. All seven RF acceptance criteria remain
pending.

## Ordinary document Storage restoration — 30 September

The rejected-predecessor browser journey now restores its seven ordinary source
and feedback objects into a separate volume and Storage API paired with the
cloned database. It preserves file bytes and Linux extended attributes; a focused
probe reproduced `ENODATA` when plain tar lost those attributes, then returned the
exact original bytes after the fix. The runner uses only the owned source, a
pinned cached image, private temporary configuration and loopback ports.

The actual Documents adapter verifies real browser sessions through the original
local Auth service, then reads restored Company Access and Documents data. Owner
downloads match all seven retained originals. Cross-owner and pre-MFA downloads
are denied; direct owner, outsider and unauthenticated Storage reads stay denied.
The source file tree/attributes, metadata, RF history and cluster memberships
remain unchanged. All created restore containers, volumes and databases are
removed. The complete targeted browser journey, 39 runner tests and 21 RF fixture
checks pass. See `owned-object-restore-20260930.json`.

This covers the synthetic, quiescent file-backed store. Independent Auth/role
recovery, hosted object storage, prior-year/unapproved history, cancellation,
expiry, deletion and retention generations remain outside this proof. Remaining
security/conformance, unknown-operation reconciliation, legacy feedback backfill,
HTTP/concurrency sizing and both immutable acceptance gates stay open. All seven
RF acceptance criteria remain pending.

## Prior-year original and unapproved source restoration — 30 September

The rejected-predecessor browser journey now saves a fourth source with a
prior-year original supporting its opening basis, generates an unreviewed preview
and downloads the complete archive. The source retains the document's actual
year and hash. Earlier sources/previews, approvals, submission claims, head,
journal and feedback remain unchanged; no provider call occurs.

The actual database and file-backed Storage restoration passes with four source
versions, three approvals/submissions, four source originals, four feedback
originals and eight ordinary objects. The canonical history preserves the
unreviewed preview, which is not materialized in the approval workspace. Owner
downloads, MFA and unrelated-actor denial, original-byte comparisons, extended
attributes and unchanged source state all pass. The targeted browser journey,
38 fixture checks, architecture and credential checks pass. See
`prior-year-unapproved-restore-20260930.json`.

This supersedes the prior-year/unapproved-source gap in the preceding ordinary
Storage proof. It does not establish independent Auth/cluster-role or hosted
object-store recovery. Cancellation, expiry, deletion, retention generations,
remaining security/conformance, unknown-operation reconciliation, legacy
feedback backfill, HTTP/concurrency sizing and both immutable acceptance gates
remain. All seven RF acceptance criteria stay pending.

## Retained evidence invalidates stale archive receipts — 30 September

The existing company-archive generation inventory omitted eight RF source-history,
head and binding tables plus Documents' two retention tables. Their company locks
serialized writes but did not invalidate an earlier completed export receipt.
The additive `20260930160335_rf1086_retained_archive_generations.sql` migration
connects those sources to the existing generation tracker. It invalidates affected
companies' pre-activation generations once and preserves source content, exact
role/grant/RLS settings and the existing cancellation policy. Application rollback
keeps the safety triggers; the ordered local recutover reapplies the migration.

Documents invalidation is company-wide because older originals can support newer
filings. Its existing before-write guard remains; after-change tracking avoids
invalidating exports on an identical retained-copy read. Database checks prove
that a current receipt admits cancellation, new unapproved sources/previews make
both completed and in-flight exports stale, and a prior-year retained original
invalidates a later-year export. Aborted writes and migration rollback undo their
generation changes; replay preserves generations, original source and authority.
All 55 targeted database checks and 101 CI/inventory checks pass. Supabase advisors
report no blocking security/error findings. The complete rejected-predecessor
browser journey and actual database/eight-object restoration also pass. Final-
revision CI remains required. See `retained-archive-generations-20260930.json`.

The preceding CI at `256c3602` passed Application and nine browser histories but
hit the Database job's explicit 45-minute timeout as the tenth history began.
GitHub's annotation confirms that limit. The job now has a 60-minute bound; no
coverage is removed. This is not a successful base release gate.

This closes the missing archive-generation backstops, not the broader retention
policy/inventory or cancellation, expiry and deletion restore histories. All
seven RF acceptance criteria stay pending; no hosted change, genuine provider
operation or production enablement occurred.

### 30 September — actual archive, cancellation and recovery

The rejected-predecessor browser history now downloads the full company archive
through the owner-authenticated Next route before requesting cancellation through
Company Access. Its actual completed export receipt admits `retention_hold`; the
same cancellation operation replays identically. All retained RF projections and
provider calls remain unchanged. The subsequent database/eight-object restore
also compares the complete cancellation record through authenticated Company
Access reads before, within and after restoration, and denies an unrelated owner.
The full browser rehearsal passed in 149.13 seconds. Another 124 focused fixture,
archive and restore-boundary checks, the onboarding database rehearsal, and the
architecture check pass. See `cancellation-restore-20260930.json`.

Base CI `36752628443` failed during onboarding fixture startup: two Unix-socket
readiness probes observed the PostgreSQL image's temporary initialization server,
then the first setup statement met its shutdown. The cached image entrypoint
confirms that temporary server disables TCP. The onboarding probe now requires
loopback TCP readiness; its actual disposable-database rehearsal passes. Final
revision CI remains required.

Expiry, final deletion, complete retention inventory/policy, retained-original
generations and independent Auth/role/hosted recovery remain open. No RF acceptance
criterion is promoted, and no genuine company/provider operation occurred.


### 30 September — independent deletion review and retained recovery

The same application-created history now exercises a separate synthetic admin
reviewer with a scoped support grant. An unopened case cannot approve deletion.
After opening, approval and exact replay succeed. Finalization rejects the stale
archive receipt, then succeeds only after the owner downloads a fresh complete
company archive. Its replay is identical. New consequential RF review is denied
for the deleted company, while retained RF projections and provider calls stay
unchanged.

The browser preserves the existing `retention_hold` restoration and adds another
complete database/eight-object restoration after finalization. Company Access
verifies the owner's full cancellation and the independent reviewer's full case
projection, approved review and `deleted_retention_record` marker before, within
and after recovery. Existing outsider/MFA/direct-Storage denials remain. The
complete journey passed on both Next 16.3.4 (153.44 seconds) and patched 16.3.8
(164.01 seconds). Another 38 fixture checks, 14 restore-boundary checks and the
architecture check pass. See `deletion-restore-20260930.json`.

Expiry, retained-original generations, the full retention inventory/policy and
independent Auth/role/hosted restoration remain open. The lifecycle marker retains
business records; this proof neither implements a purge nor promotes an RF
acceptance criterion.

### 30 September — Next.js security patch after CI audit

CI `36752628443` completed with two failures: the onboarding startup race already
fixed in `e39dbd94`, and the final production dependency audit. All Application
checks before that audit, including production builds and the complete launch
rehearsal, passed. The audit identified `GHSA-vcvr-r3jv-pc5j` in Next 16.3.4.

Both manifests and lockfiles now pin Next 16.3.8 and its matching packages. The
vendor advisory identifies 16.3.6 as the first patched version; the selected patch
preserves the existing React and Node peer requirements. Both production audits
report zero vulnerabilities. The production web build, typecheck, architecture
check and full deletion/recovery browser journey pass. No codemod applies to this
same-16.3 patch update. See `next-security-patch-20260930.json` for official source
links and exact file hashes. A new exact-revision CI run is still required.
