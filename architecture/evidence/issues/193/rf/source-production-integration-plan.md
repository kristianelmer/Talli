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
preparatory reads. The customer annual-source screen now edits typed company,
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

Approval and send need a shared short transaction with public owner queries.
Independent rereads followed by an RF write leave a race. The owner queries and
all writes affecting their projections must participate in company-scoped guards:
Company Access membership/identity, Governance records including cross-year
decisions, Ledger amendments, Documents retained metadata and RF source/review
state. Document a common lock order, preserving existing Authority-request before
Billing-entitlement ordering. Acquire guards before reading their projections.

Do not give RF access to other owners' tables. Compose narrow public adapters on
one authenticated connection. Keep byte downloads and provider I/O outside this
transaction. Documents now retains bounded immutable copies of verified original
bytes and supplies exact receipt/read/assert contracts. Approval/send still need
to bind and consume those receipts. Archive, backup, expiry and deletion handling
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
database execution proof. Full-year RF approval/send composition remains pending.
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

Add an explicit full-year profile across Billing commands/transports/SQL and RF
approval, submission and journal visibility. Do not label eventful cases as
no-activity. Unknown profiles remain denied. An immutable RF-owned bridge from
source previews to existing filing previews can preserve the existing approval
foreign key without inventing an opening setup. The old approval route must
reject bridge previews. Readiness must use the verified full-year source binding
instead of regenerating an opening-only case.

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
