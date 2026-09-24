# Full-year submission claim integration

Implementation contract derived from the current RF journal and approval code on
24 September 2026. This is remaining work, not acceptance evidence.

The guarded command should accept only approval ID, exact manifest SHA, expected
company/year head submission ID and verified subject. Source identity, statutory
bytes, correction parent/hash/reason and document order come from immutable
`source_approval_bindings`, not caller reconstruction. Return the immutable claim
identity, payload/manifest hashes, predecessor and whether the claim is new.

Before insertion, hold company then RF-year guards on one READ COMMITTED
connection. Reverify original bytes outside that transaction, then compare their
retained receipts and complete predecessor snapshot inside it. Lock the scoped
submission head and parent before Authority request, then Billing entitlement.
Verify current source/Governance/Documents, exact review and warning commitment,
permission and independently owned annual and technical prerequisites. Evaluate
MFA and entitlement time after lock waits. Claim commit is the admission point;
provider I/O happens afterward through the existing durable journal.

Add immutable `source_submission_bindings` and one company/year/obligation/
production head. The existing unique approval ID does not prevent separate
approvals from each creating a first filing. Initialize from all historical
legacy and full-year submissions; ambiguous leaves must fail rather than choosing
by timestamp. Replacement requires the exact terminal accepted/rejected head,
its manifest and verified feedback. Sending, processing, unknown and
`action_required` require reconciliation. Reject forks, stale parents and cycles.
Once a managed head exists, legacy insertion cannot create an unmanaged competitor;
existing legacy claim replay and ordinary unmanaged legacy behavior remain intact.

Before relaxing the submission profile CHECK and shared source barrier, reject
source approvals in legacy `begin_production_filing` immediately after its exact
80249 company-guard prefix, preserving replay. Allow source submissions only with
the exact immutable binding; an ambient GUC must never confer authority. Extend
historical submission reads only for the verified source binding, preserving
same-owner relationship rules and recovery after pilot expiry or stale MFA.

A separate historical claim lookup may return an exact existing approval/manifest
claim before fresh source admission. This lookup does not authorize a new POST.
Prepared/unknown journal mutations remain uncertain and cannot be blindly retried;
succeeded operations retain their original references and explicitly retryable
operations reuse the stored key. Later source corrections cannot alter an already
claimed payload or create another logical first submission.

Python send and reconciliation currently assume the legacy profile and manifest.
Add explicit source-profile dispatch and the immutable `source_` document keys
before enabling the source path. Complete full-year submission/archive lineage
and repeat predecessor byte checks at send. Rollback must retain claim/head/data
and historical recovery, revoking new claims without narrowing populated CHECKs.
Replay earlier RF capability/recovery and 80249/85227/91015 predecessors before
the new claim successor; 94631 supplies the company-first journal prerequisite.
