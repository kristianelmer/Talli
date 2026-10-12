# Independent register observations for RF year sources

Historical foundation design, originally recorded 2026-09-23. Subsequent changes
added owned immutable persistence, verified original capture, current-lineage
reads and customer register entry/correction. See the evidence indexed by
`requirements.json`. This design still records the required explicit withdrawal,
Governance admission binding and shared freshness guarantees; those are not
established by the customer UI. No production enablement or full RF acceptance
is claimed.

## Why another RF source contract is required

`Rf1086SourceEvidence` hashes a filing source snapshot, including opening facts
and filing workspace/journal evidence. It is not an event-specific observation
of registered capital and ownership. `Rf1086OpeningFacts` describes the opening
position for one year; changing it to represent a later capital event would
misstate its meaning. Neither can substantiate a Governance post-event register
reference.

Governance's existing `SupportedCorporateSourceFact` validates a UUID, revision,
and SHA but a caller-supplied reference does not establish that the referenced
register observation exists. Existing references must not be relabeled as
verified evidence. The new workflow must resolve and verify them or fail closed.

## Public foundation now implemented

`RecordRf1086RegisterObservation` records company, owner actor, income year,
civil effective timestamp, supported event kind, and complete before/after
registered states. Each state includes exact Decimal registered capital and
nominal value, integer total share count, and every holder's stable existing ID,
name, Norwegian legal identity and share count. Capture requires explicit
complete-register, registration and single-share-class confirmations. No holder
or class ID is synthesized. Unsupported multiple-class registers fail the
single-class capture requirement. Identity digit shape validation is not an
external identity verification service.

Cash issues increase count at unchanged nominal value without removing any
existing holder's shares. Nominal cash increases and loss-cover reductions keep
holder counts unchanged and move nominal value in the required direction. Both
states require exact count × nominal = capital and the supported existing-AS
minimum capital. The contract does not support formation or simultaneous share
transfers hidden inside a capital event. Tax paid-in capital and premium remain
separate facts: neither is inferred from these registered amounts.

Every observation carries original Documents references with company, content version (= original SHA-256),
content SHA-256, byte length, original document type/integrity status/creation
time, complete Documents metadata digest and reviewed roles: before register, after register and
registration. One document may support multiple roles only with the exact same
content version/metadata/hash/length. Trusted `Rf1086VerifiedRegisterObservationContext` must
attest the same actor/company/year and exact document tuple after the Documents
owner has reread original bytes and the application has established independent
provenance. It is not a browser DTO. This proves bytes and owner-reviewed facts;
it does not parse, legally certify, or assert signedness of document contents.
A Boolean attestation is meaningful only at that trusted binding.

`prepare_rf1086_register_observation` yields an immutable UUID/version/command/
UTC capture-time/fact-hash snapshot, using schema-tagged canonical hashing.
Holder/document order, Decimal trailing zeroes and ambient Decimal precision do
not change the fact hash. New corrections need a new UUID, exact predecessor
UUID/hash, same company/year/event identity, later capture and nonblank reason.
The pure function checks the supplied predecessor, not the actual store head.
Integrity verification detects changed retained content; a hash is not an
issuer signature or proof of storage provenance.

`Rf1086RegisterObservationMatchQuery` and
`verify_rf1086_register_observation` match the exact persisted UUID/revision/hash,
company/year/effective time/event kind and full before/after economics. This
prevents reusing an equal capital delta from another register history. The
function returns the exact immutable snapshot and does not claim it is current,
unwithdrawn or still backed by live Documents authority.

## Minimum remaining trusted implementation

1. Add RF-owned immutable observation versions and current heads with owner
   authorization, append-only correction, explicit withdrawal, idempotency and
   transactional compare-and-set against the actual current predecessor. A
   public RF read query must return the exact observation plus currentness or
   withdrawal state. Retain history and reject missing/unbacked references.
2. Bind register capture to Documents `verify_document_evidence` for every
   original. Preserve its actual original status; do not invent signedness.
   Verify company ownership, document content version/metadata/hash/length and independent
   provenance, and collect owner's complete single-class before/after review.
   Do not admit the candidate year-source, filing-generated output or Governance
   finalization as the independent source. Capture may precede Governance and
   contains no year-source or Governance-receipt dependency.
3. During Governance finalization resolve `shareholder_register_fact` through
   that RF public query and match its record ID, revision and fact SHA exactly.
   Check active/current status and the event's complete registered before/after
   economics, company, year and effective time. Persist the resolved binding in
   the canonical finalization receipt. Never manufacture a match from opening
   facts or an unverified client UUID.
4. During full-year source capture independently enumerate finalized Governance
   events, resolve their exact retained register references, verify the same
   economics and current status, and bind the observation ID/hash into the
   trusted `Rf1086YearGovernanceReceipt`. Require its capture timestamp to precede
   the new year-source capture. Thus the dependency runs independent originals →
   RF observation → Governance finalization → RF year source, without a cycle.
5. Define cross-capability freshness/lease semantics. Rechecking Documents owner
   and bytes before/after IO does not close a revocation or document-change race
   after return. Pure snapshots cannot establish live currentness. Withdrawals,
   corrections or changed original references must invalidate affected capture.

Public behavioral tests cover transitions, complete holdings, exact Decimal
arithmetic, original document coverage/binding, trusted-owner attestations,
immutable correction links, integrity and exact reference/economic matching.
They call only the documented public entrypoint and make no provider calls.
