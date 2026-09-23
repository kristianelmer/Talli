# Remaining source-backed RF production integration

Status: implementation plan, not acceptance evidence. All full RF criteria remain
pending. These software slices can be implemented with synthetic companies; only
genuine-company records, authority and the final production pilot need a recruited AS.

## Intake and owner review

Keep canonical hashing on the backend. An omitted event digest in an HTTP capture
request is derived from the typed canonical event at its declared index. An
explicit digest still has to match, and invalid or duplicate indices still fail.
The internal source command always contains all event digests.

Expose a typed intake projection from existing public Governance reporting-year
evidence, including unresolved, superseded and amended records. Return selectable
receipt IDs, dates, economics, original-document IDs and independent register
observation requirements. Do not make the customer UI reproduce completeness or
eligibility policy. Expose current source details as an editable typed draft,
without using the internal tagged storage codec as a transport format. Capture
must verify all evidence again after these preparatory reads.

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
transaction. Documents must pin an immutable verified object version; a metadata
row lock alone cannot prevent an object overwrite. Prove that storage invariant
before treating its digest as consequential authority.

Two-session tests must cover insertion into a previously empty year, prior-year
decisions, Ledger amendments, evidence changes, source corrections and membership
revocation. A writer either commits before admission and invalidates stale facts,
or waits until admission has committed.

## Versioned manifest and existing journal

Preserve historical `production-approval-v1` manifests and hashes. Introduce a
separate source manifest binding company/year/actor, source ID/version/hash, case
hash, source preview and XML hashes/order, complete freshness commitments, review
acknowledgments, entitlement/profile/adapter and optional correction ancestry.
Stable shareholder IDs need a versioned document ordering rule; the legacy UUID
ordering must remain unchanged for historical receipts.

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
