# RF full-year source snapshot

Status: deterministic validation, immutable persistence and internal trusted capture are being integrated for issue #193; customer workflow and complete service conformance remain pending. This design does not narrow the accepted #172 launch boundary or claim any RF release criterion complete.

## Ownership and data flow

RF owns the reporting company's shareholder identities, ownership movements, opening and closing share facts, and immutable full-year source versions. Corporate Governance continues to own corporate decisions and their finalization. Documents continues to own source-document bytes, immutable content identities and current metadata. Ledger continues to own accounting entries. RF never writes or reads another owner's tables.

A named application workflow reads immutable public projections from Company Access, Corporate Governance and Documents, validates the actor/company/year, and passes those projections into RF. The RF capability has no dependency on Corporate Governance, Documents, Ledger, or a future Annual Compliance implementation. No Annual Compliance writer is introduced. These application dependencies and adapter bindings require backend-system manifest and architecture-test updates under ADR-0011.

## Proposed RF contracts

- `Rf1086YearSourceId`: UUID identity of one immutable snapshot.
- `RecordRf1086YearSourceCommand`: company, actor, correlation and idempotency identities; income year; explicit complete case; owner completeness confirmations; source-document references; event evidence; optional predecessor snapshot and mandatory correction reason.
- `Rf1086YearSourceSnapshot`: source ID, company/year, positive version, canonical case, canonical payload digest, source digest, owner confirmation identity/time, evidence digests, predecessor ID/digest and correction reason. All nested values are immutable. Creation timestamps come from the trusted persistence clock.
- `Rf1086YearDocumentEvidence`: document UUID, company, original document year, content-version SHA256, content SHA256, document kind, status, byte length, creation time and complete metadata digest. Each reference must be corroborated by the Documents public projection before capture. No arbitrary URL or unverified browser hash serves as proof.
- `Rf1086YearEventEvidence`: stable event index and event digest; document references; optional finalized governance event/decision receipt reference and hash. An index is scoped to one immutable source, not an identifier reused across corrections.
- `Rf1086GovernanceCorroboration`: RF-owned input projection containing company/year, event type and civil timestamp, finalization ID/hash, exact economic facts/allocations digest, signed-document hashes and correction/reversal status. Its values are assembled from verified public Governance receipts by the workflow; they are never trusted from browser input.
- `Rf1086YearSourceFreshness`: source ID/version/digest, company identity digest, Documents metadata/content digests, Governance finalized evidence digest and complete year-enumeration digest. A changed, reversed, missing or newly added relevant event invalidates readiness.

The existing RF case format is reused for deterministic rendering. Its opening/closing registered share capital, share count and nominal value are independent from tax paid-in share capital and premium. All four paid-in values must be explicit inputs, including zero; neither nominal capital nor an omitted premium is a default for statutory paid-in facts. Every holder active at opening, during an event, or at closing must appear exactly once with an appropriate national/company identifier. Events remain civil local whole-second times in strict chronological order.

## Capture and correction rules

The owner confirms that the shareholder identities, complete full-year event enumeration, supporting source documents, and opening/closing tax paid-in amounts were reviewed. An empty event list requires an explicit no-activity confirmation; absence of captured events cannot establish no activity. The application actor must be an accepted owner. Capture does not replace the existing fresh-owner AAL2 requirement at consequential production approval/send.

Opening and closing facts need verified source evidence even when no events exist. Each movement needs source documents and complete dated allocations. Ordinary dividends and registered cash capital changes/loss-covering reductions additionally require current finalized Corporate Governance corroboration. Formation and simple ownership transfer require their own source documents and statutory validation; an Investments share sale is never evidence of ownership in the reporting company.

Corporate Governance may require RF register evidence to finalize registered capital events. Avoid a cycle by distinguishing an independently captured RF shareholder/register observation from a filing-ready full-year source. The former can corroborate Governance finalization; the latter references the resulting immutable finalized Governance receipt. No command auto-finalizes the other owner, and a draft/year snapshot cannot be used to prove its own prerequisite. The workflow fails closed if existing public contracts cannot establish that lineage.

A first snapshot has version 1 and no predecessor. A correction creates version N+1 for the same company/year, links the exact current predecessor ID/digest, and records a non-empty reason. Predecessor/current-head validation and insertion occur under an RF company-year write lock. Previous versions, previews, approvals, submissions and receipts are never rewritten. A payload-identical retry with the same idempotency key returns the original result; different content under that key is a conflict. Forked corrections and stale predecessor updates fail. A changed document/economic source requires a new source snapshot even if the final rendered XML would be unchanged.

## Preview, approval and send

`GenerateRf1086PreviewCommand` may gain an optional year-source ID for compatibility, but compatibility cannot mean silently constructing an empty-event case with paid-in capital inferred from nominal capital. The legacy opening-only path must fail closed for production and direct the owner to complete a full-year source. Existing historical previews and artifacts remain readable without regeneration or mutation.

Preview generation loads the selected current immutable year source, its verified external corroboration, and current company identity, renders the canonical complete case, and stores the full freshness vector with the XML hashes. Under the RF write lock it verifies that the current source head has not changed. No-activity and eventful cases use the same source-evidence requirements.

Approval requires a newly evaluated exact freshness vector, the selected current source, preview/XML hash equality, readiness, warnings/review controls, entitlement and fresh-owner AAL2. Send repeats those checks immediately before persisting submit-once intent. A preview's age is not a freshness check. External source reads must not occur while holding an RF database transaction; use public version/digest validation and make the remaining concurrent-change behavior explicit. Where external owners offer no atomic conditional read/lease, the workflow cannot claim a cross-owner serializable snapshot: capture reads a complete public projection, and approval/send re-read and compare it before a short RF claim. Any residual race must be closed with a shared transaction-bound public query contract or an owner-issued version lease before production enablement.

Corrections also bind the prior final/rejected submission and owner-reviewed correction reason into a new approval/submission manifest. Existing `supersedes_submission_id` becomes a populated immutable relationship. Unknown prior outcomes must be reconciled before authorizing a possible replacement. A new source snapshot alone never authorizes another provider POST.

## Implementation seams and verification

New deterministic `year_source.py` will validate and freeze source inputs, compute versioned canonical digests, validate corrections and full evidence coverage, and compare freshness. Public re-exports and persistence/transport composition follow separately. SQL stores immutable snapshots and an RF-owned current-head pointer, with company-scoped RLS, accepted-owner capture, idempotency and compare-and-swap correction admission.

Preparation, `source_facts._readiness`, approval basis and production send must switch together to the complete source path. Archive exports include each immutable source/evidence manifest and its preview/submission lineage. Case-profile/Billing/transport/SQL literals must be extended with conformance-backed profiles before enabling eventful production.

Required tests cover explicit paid-in evidence; no-activity completeness; full holder/event coverage; mismatched/reversed Governance receipts; document/company/year mismatch; missing signed evidence; copied mutable input; stable canonical digest; correction forks and idempotency conflicts; changed/new external events; stale preview/approval/send; tenant/owner denial; and preservation of prior immutable records. Provider conformance and genuine-company acceptance are separate outstanding evidence.

## Foundation implementation receipt

The deterministic foundation now lives in `year_source.py` behind the RF public
entry point. Its public-interface tests cover completeness, exact tax paid-in
values, prior-year source documents, full event coverage, finalized signed
Governance evidence, independent register observations, correction lineage,
input immutability, finite decimal hashing, snapshot integrity, idempotency
conflicts and source freshness. No new persistence, transport or application
workflow binding has been installed by this foundation. Those outstanding seams
above must be completed before this can capture a customer's source snapshot or
change production admission. All #172 scope and #193 full completion claims
remain pending.

## September 23 integration checkpoint

The internal authenticated capture workflow now derives trusted owner, company, original-document and Governance facts rather than accepting trusted context from a caller. Governance enumeration includes finalized dividends, pending and superseded decisions, registered capital events, and Ledger reversals/corrections within its coherent read. Immutable year-source storage uses exact-source idempotency, current-predecessor comparison and preserved historical versions. Independent register observations separately describe original registered before/after facts and cannot be replaced by a filing-year snapshot.

Documents-owned retention runs inside each RF capture transaction to recheck verified metadata and protect original documents against deletion. Capture remains a point-in-time observation. Customer routes, cash-nominal Governance composition, complete preview/approval/send freshness and cross-owner action-time concurrency controls remain outstanding; these foundations do not enable production or narrow the accepted launch boundary.
