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

Full-year submission constraints, claim and journal visibility remain blocked
pending their independent guarded command. The legacy stored-readiness gate is
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
