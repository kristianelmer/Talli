# Corporate Document Artifacts Design

Status: approved under the user's autonomous-completion mandate

Date: 2026-07-14

Source requirements:

- `docs/remarks/holdingswift_produktkrav.md`
- `docs/prd/holdingswift-product-requirements-implementation-plan.md`

## Objective

Replace the current owner-dividend text placeholders with deterministic,
versioned PDF artifacts and add the corresponding annual-close artifacts for a
simple holding AS. Every artifact must be generated from reviewed facts, stored
privately, traceable to one immutable source decision, safe to retry, and
incapable of representing itself as signed or approved before the owner records
that state.

This is a templated corporate-document capability, not custom legal advice.

## Supported launch scope

The generated path supports only:

- a Norwegian AS inside Talli's existing simple holding-company boundary;
- one share class;
- cash dividends based on the latest approved annual accounts;
- proportional allocation from the shareholder register;
- all board members participating in the board treatment;
- all shares represented at the general meeting;
- unanimous board and shareholder decisions;
- a calendar financial year and a small-enterprise annual-account model;
- owner-attested upload of the final signed PDF after every required signer has
  signed outside Talli.

The system fails closed for interim-balance or extraordinary dividends,
non-cash or unequal distributions, proxies, absent shares, dissent, conflicts
of interest, missing participants, multiple share classes, missing annual
accounts, or an amount that exceeds the available-distribution or liquidity
checks. Those cases require accountant or legal review.

## Legal and authority basis

The templates and validation rules are grounded in the current primary sources:

- Aksjeloven section 8-1 limits distributions to available equity and requires
  prudent equity and liquidity:
  <https://lovdata.no/dokument/NL/lov/1997-06-13-44/KAPITTEL_8-1>
- Aksjeloven section 8-2 requires a board proposal before the general meeting
  decides a dividend, and prevents a higher decision than the board proposes or
  accepts:
  <https://lovdata.no/nav/lov/1997-06-13-44/kap8>
- Aksjeloven section 6-29 requires board minutes to state time, place,
  participants, treatment method, and decisions, with participating members'
  signatures:
  <https://lovdata.no/dokument/LTI/lov/1997-06-13-44/KAPITTEL_6-2>
- Aksjeloven sections 5-5 and 5-16 require the ordinary general meeting to
  decide the annual accounts/result allocation and require minutes containing
  meeting facts, attendance/share representation, decisions, voting outcomes,
  and signatures:
  <https://lovdata.no/nav/lov/1997-06-13-44/kap5>
- Regnskapsloven section 3-5 separately requires the annual accounts to be
  signed by all board members and any managing director. The generated board
  minutes do not replace that signature:
  <https://lovdata.no/lov/1998-07-17-56/%C2%A73-5>
- Brønnøysundregistrene states that complete annual accounts must be submitted
  within one month after adoption by the general meeting:
  <https://www.brreg.no/registersok/kunngjoringer/om-kunngjoringer/kunngjoringer-fra-regnskapsregisteret/>

These sources are evidence for deterministic minimum fields, not a claim that
Talli can resolve unusual company-law questions.

## Artifact set

### Owner dividend

1. `dividend_board_proposal`
   - Board-meeting facts and quorum.
   - Latest approved annual-accounts basis year.
   - Available distribution amount and proposed cash dividend.
   - Explicit prudent-equity and liquidity determination.
   - Proposed record/decision date, payment date, and proportional allocation.
   - Unanimous board decision and signature lines for all participants.
2. `dividend_general_meeting_minutes`
   - Meeting facts, chair, co-signer, shareholders, shares represented, and
     voting result.
   - Reference to the board proposal.
   - Exact dividend decision no higher than the proposal.
   - Payment date, allocations, unanimous result, and signature lines.

### Annual close

1. `annual_board_minutes`
   - Board treatment of the annual accounts and notes.
   - Result and proposed allocation or loss coverage.
   - Confirmation that the separate annual accounts require the statutory
     signatures.
   - Decision to submit the proposal to the ordinary general meeting.
2. `annual_general_meeting_minutes`
   - Meeting facts, representation, voting result, and signatures.
   - Adoption of annual accounts and notes.
   - Adoption of result allocation or loss coverage.
   - Any supported ordinary dividend already represented by the same reviewed
     facts.

## Immutable input model

One `CorporateDecisionInput` is canonicalized and hashed before any document or
accounting action exists. It contains:

- request ID, company ID, organization number, legal name, and income year;
- decision kind (`owner_dividend` or `annual_close`) and an optional immutable
  annual-close source ID;
- template family and version;
- annual-account basis year and the exact financial totals used;
- board meeting date, time, place, and treatment method;
- ordered board participants with name and role;
- general-meeting date, time, place, meeting form, chair, and co-signer;
- ordered shareholders with stable ID, name, share count, represented share
  count, and vote;
- total company shares and one-share-class confirmation;
- dividend amount, payment date, available equity, post-payment liquidity, and
  ordered allocations when relevant;
- explicit confirmations for full participation, full representation,
  unanimity, proportionality, and supported dividend basis.

No generated-at timestamp enters the canonical input or PDF. User-supplied
meeting timestamps are facts and therefore do enter both. The decision hash is
the source identity for every artifact, approval, signature attestation, and
accounting finalization that follows.

## Rendering module

`holding_core/corporate_documents.py` is the single rendering boundary. It:

1. validates the supported scope with machine-readable blocker codes;
2. serializes the input as canonical UTF-8 JSON with stable key and list order;
3. calculates the SHA-256 input hash;
4. renders each artifact with pinned ReportLab in invariant mode;
5. uses repository-bundled Noto Sans regular/bold font files and their OFL
   license so Norwegian and shareholder names are rendered exactly;
6. sets stable PDF metadata derived from artifact kind and template version;
7. returns PDF bytes, byte length, content SHA-256, artifact kind, filename,
   template version, and input hash.

The precise ReportLab version is locked in `uv.lock`. A dependency or font
change is a template-version change and intentionally changes the content hash.

The CLI exposes `render-corporate-documents --stdin-json`. The Next.js server
uses the existing Python-runtime resolver and treats any malformed output,
hash mismatch, or missing artifact as a hard failure.

## Persistence model

Migration `0004_corporate_document_artifacts.sql` adds five append-only
lifecycle tables plus one immutable accounting-policy registry.

### `corporate_accounting_policies`

- immutable policy version
- declaration debit, dividend-payable, and bank account numbers
- named reviewer, review timestamp, evidence reference, and recorded-by actor
- enabled state fixed at insert time; a replacement version supersedes rather
  than mutates an existing policy
- no authenticated read or write grant; security-definer finalization/payment
  functions resolve the enabled version internally

### `corporate_decisions`

- immutable decision ID / idempotency request ID
- company, income year, and decision kind
- optional annual-close source ID and source hash
- canonical decision input JSON and decision hash
- optional `supersedes_decision_id`
- lifecycle status is derived from events and finalization, never updated here
- created by/at
- unique request ID; decision-hash indexes support lookup but do not prevent an
  immutable replacement decision with unchanged reviewed facts

### `corporate_document_sets`

- immutable set ID and decision ID
- company and income year, repeated for RLS and cross-company validation
- template family/version
- decision hash
- optional `supersedes_set_id`
- created by/at
- unique set request ID; decision/template indexes support lookup but do not
  prevent an immutable replacement set with unchanged meeting facts

### `corporate_document_artifacts`

- immutable artifact ID and set ID
- artifact kind and variant (`unsigned` or `signed_owner_attested`)
- document row ID
- content hash, byte length, MIME type, and storage key
- optional superseded artifact ID
- created by/at
- unique set/kind/variant and unique storage key

### `corporate_document_events`

- decision, set, and optional artifact ID
- event kind: `generated`, `facts_approved`, `signing_requested`,
  `signed_copy_attested`, `finalized`, `superseded`, or `rejected`
- actor, timestamp, exact input/content hash, and bounded metadata
- append-only unique idempotency key

### `corporate_decision_finalizations`

- immutable finalization ID and decision ID
- finalization kind: `owner_dividend_declared` or `annual_close_adopted`
- owner-dividend holding-action and ledger-entry IDs, or annual-close source ID
- exact decision hash and the signed-artifact hashes accepted at finalization
- accounting-policy version used by an owner-dividend declaration
- created by/at
- one finalization per decision and one decision per resulting action/ledger
  entry, enforced by unique constraints

Current state is derived from ordered events and the finalization row. Generated
and signed object rows are never updated or overwritten. Corrections create a
new decision and set with new request IDs that reference the prior records,
even when the reviewed meeting facts and decision hash are unchanged. A
superseded or rejected decision can never be finalized.

RLS grants company members read access. Only an accepted owner can invoke the
security-definer creation/transition functions. Direct insert, update, and
delete grants are revoked. Cross-company source, document, and storage keys are
rejected inside the functions.

## Storage and idempotency

Artifacts use the existing private `company-documents` bucket and deterministic
keys:

`<company>/<year>/corporate/<set-id>/<kind>/<content-hash>.pdf`

Draft-generation flow:

1. Validate membership, source facts, and period state server-side.
2. Recompute the complete input from persisted facts plus the reviewed meeting
   facts; never trust hidden financial totals.
3. If either request ID already exists, return the existing decision/set only
   when the decision hash matches; otherwise reject an idempotency conflict.
4. Render all required PDFs before any database metadata write.
5. Upload with `upsert: false`. On an existing object, download and compare the
   hash before treating it as a retry.
6. Call one database function that atomically records the immutable decision,
   document rows, artifact set, artifacts, and audit events. Draft generation
   must not create a holding action, ledger entry, payable, or bank posting.
7. If the database function fails, best-effort delete only the objects created
   by this attempt. Existing hash-matched objects are retained.

For annual-close artifacts, the source annual-data/readiness snapshot already
exists and its hash is bound into the decision. It is not marked adopted by
draft generation.

Finalization is a separate step-up-protected database function. It accepts only
the current decision hash, approved facts event, and owner-attested signed copy
of every required artifact. For an owner dividend it atomically records the
declaration holding action, balanced declaration ledger entry, finalization
row, and `finalized` event exactly once. The declaration debits the configured
equity/distribution account and credits a dividend-payable liability; it must
not credit bank. A later bank match records payment by debiting the payable and
crediting bank. Both mappings carry an explicit accounting-policy version
resolved from the immutable server-side registry and remain behind the rollout
flag until a named Norwegian accounting review accepts the exact accounts.
Owner-controlled input can never select or override accounts. For an annual
close, finalization records adoption against the bound annual-close source
without creating an unrelated ledger entry.

## Review and signing workflow

The owner sees the exact template version, input hash, PDF hash, and all facts
before approval. Approval is a step-up-protected event bound to those hashes.
Changing any fact creates a new set and invalidates prior approval.

Talli does not claim to cryptographically validate handwritten or external
electronic signatures. The owner uploads the signed PDF, names the signers,
confirms that every required signer signed, and completes a fresh step-up. The
server validates PDF signature/MIME/size, computes the hash, stores a new
immutable object, and records `signed_owner_attested`. Product copy uses exactly
that status and never says `verified digital signature`.

The generated unsigned document remains available for comparison. A signed
copy cannot replace or mutate it. Only after every required signed variant is
attested can the owner finalize the decision; finalization is bound to the
decision and signed-content hashes so replacing a document requires a new
decision.

## Readiness integration

- An owner-dividend draft is not `ready for signing` until both unsigned
  artifacts exist and the facts are approved. It is not an accounting action
  until both signed copies are owner-attested and the decision is finalized.
- Dividend-payment readiness requires a later payment action that references
  the finalized declaration and clears, but never exceeds, its open payable.
- Annual-account filing readiness blocks if the annual document set does not
  match the current annual-data and annual-account payload hashes.
- Production readiness blocks until the annual meeting minutes are signed,
  owner-attested, and the annual decision is finalized as adopted. This is
  separate from the authority's ID-porten signature on the annual-account
  submission.
- Superseded, rejected, mismatched-hash, or unsigned-current artifacts cannot
  satisfy readiness.

## User experience

The existing owner-dividend wizard becomes a review-first flow:

1. choose the supported annual-account basis;
2. review proportional shareholder allocations;
3. enter meeting facts and all board participants;
4. review general-meeting participants, chair, and co-signer;
5. confirm full participation/representation and unanimity;
6. generate and preview the two PDFs;
7. approve exact facts and hashes;
8. download for signing and upload signed copies;
9. complete a fresh owner step-up and finalize the decision;
10. match the later bank payment to the resulting dividend payable.

The year-end flow offers the same sequence for annual board and general-meeting
minutes after the annual payload is ready. Norwegian-first copy consistently
uses `utkast`, `godkjent for signering`, and `signert kopi bekreftet av eier`.

## Error handling

All failures are typed and fail closed. Required blocker codes include:

- `corporate_documents_unsupported_dividend_basis`
- `corporate_documents_incomplete_board`
- `corporate_documents_incomplete_share_representation`
- `corporate_documents_non_unanimous`
- `corporate_documents_allocation_mismatch`
- `corporate_documents_equity_or_liquidity_failed`
- `corporate_documents_source_hash_mismatch`
- `corporate_documents_idempotency_conflict`
- `corporate_documents_render_failed`
- `corporate_documents_storage_hash_mismatch`
- `corporate_documents_stale_approval`
- `corporate_documents_missing_signers`
- `corporate_documents_missing_signed_artifacts`
- `corporate_documents_already_finalized`
- `corporate_documents_accounting_policy_disabled`
- `corporate_documents_payment_exceeds_payable`

Errors shown to owners are Norwegian and actionable. Logs contain IDs, states,
and hashes but no national identifiers, document bodies, tokens, or raw PDFs.

## Verification

The implementation is not complete until evidence covers:

- identical input renders byte-identical PDFs twice;
- Norwegian and non-ASCII company/shareholder names extract correctly;
- all four artifact kinds contain the required reviewed facts;
- canonical input and content hashes match independently recomputed values;
- unsupported dividend/meeting cases produce the intended blocker codes;
- database writes are idempotent and cross-company references fail;
- artifact and event rows cannot be directly changed by authenticated users;
- partial upload/database failure cleanup does not delete prior valid objects;
- signed upload creates a separate immutable variant and rejects missing
  signers, stale hashes, non-PDFs, and oversized files;
- draft generation never creates a holding action, ledger entry, payable, or
  bank posting;
- finalization creates one balanced declaration entry exactly once and a later
  payment clears the payable without exceeding it;
- readiness accepts only the current hash-approved/signed/finalized decision;
- company archive and restore manifests contain decisions, sets, artifacts,
  events, finalizations, and both unsigned and signed storage objects;
- fresh PostgreSQL migrations and RPC rehearsal pass;
- authenticated Supabase RLS/storage integration passes when project
  credentials are available;
- generated PDFs are visually inspected and pass a PDF structural check;
- Python tests, Node tests, typecheck, production build, dependency audit, and
  secret scan pass.

## Rollout and external gates

The feature ships behind `TALLI_CORPORATE_DOCUMENTS_ENABLED=false` until:

1. the four templates and the exact declaration/payment account mappings
   receive a named Norwegian legal/accounting review;
2. the generated PDFs pass golden and visual review;
3. deployed Supabase RLS/storage tests pass;
4. backup/restore and cancellation archive rehearsals include every artifact;
5. public copy accurately distinguishes generation, owner attestation, and
   authority signing.

No signing vendor is required for launch because the supported flow accepts a
separately signed PDF with explicit owner attestation. A future signing-provider
adapter may add cryptographic verification without changing the immutable
artifact/event model.
