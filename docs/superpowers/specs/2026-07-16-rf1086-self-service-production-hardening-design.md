# RF-1086 Self-Service Production Hardening Design

Status: approved design
Date: 2026-07-16
Scope: first controlled production beta for `rf1086_no_activity_v1`

## Goal

Make the first supported RF-1086 production beta self-service for the company
owner from Systembruker approval through durable filing reconciliation, without
weakening Talli's existing production gates or adding paid infrastructure.

This design does not enable production filing by itself. The production adapter,
pilot entitlement, authority permission, launch signoffs, fresh AAL2, and founder
go-live gates remain mandatory.

## Supported Boundary

The first production profile remains:

- one Norwegian AS filing for itself;
- `rf1086_no_activity_v1` only;
- one share class;
- Norwegian shareholders only;
- no purchase, sale, dividend, correction, or replacement event;
- an owner-managed filing with explicit final approval.

Årsregnskap and Skattemelding production submission are outside this design.

## Official Contracts

The implementation follows these authority contracts:

- Altinn standard, vendor-controlled Systembruker requests:
  https://docs.altinn.studio/en/api/authentication/systemuserapi/systemuserrequest/external/
- Altinn Systemregister redirect allowlist:
  https://docs.altinn.studio/en/api/authentication/systemuserapi/systemregister/model/
- Altinn Systembruker token selection using `externalRef`:
  https://docs.altinn.studio/en/authorization/guides/system-vendor/system-user/usetoken/
- Skatteetaten RF-1086 endpoints and feedback-document guidance:
  https://skatteetaten.github.io/api-dokumentasjon/api/innrapportering-aksjonaerregisteroppgave

Talli uses a standard Systembruker for the company's own organisation. It must
not use Altinn's agent/accountant request endpoint.

## Architecture

### Systembruker request client

A focused server-only module owns Altinn request operations:

- create a standard request with
  `altinn:authentication/systemuser.request.write`;
- retrieve a request by ID or external reference with
  `altinn:authentication/systemuser.request.read`;
- query the resulting Systembruker where needed;
- validate exact system ID, company organisation number, RF-1086 right,
  `externalRef`, status, and redirect URL;
- validate confirmation URLs against exact Altinn HTTPS hosts;
- cap response sizes and map authority errors to allowlisted internal codes.

Every request uses:

- system ID `930835978_talli`;
- right `ske-innrapportering-aksjonaerregisteroppgave`;
- a cryptographically random opaque `externalRef` that contains no organisation
  number, user ID, email, or other customer identifier;
- fixed callback URL `https://talli.no/auth/systembruker/confirm`.

No Maskinporten token, assertion, private key, or raw authority response is
stored or logged.

### Persistent request state

Add a tenant-isolated `system_user_requests` table with:

- local request ID;
- company ID and initiating owner user ID;
- obligation fixed to `aksjonaerregisteroppgaven`;
- opaque `external_ref`;
- Altinn request ID;
- allowlisted status: `creating`, `new`, `accepted`, `rejected`, `denied`,
  `timedout`, `verification_failed`;
- validated confirmation URL;
- request, status-check, acceptance, and preflight timestamps;
- safe failure code and operator evidence reference.

Owners may read requests for companies they own. Creation and state transitions
go through security-definer functions that recheck owner membership, signed AAL2,
allowed transitions, and exact company/request relationships. Operators may read
safe metadata. Service-role writes are limited to authority reconciliation.

An accepted request is not sufficient by itself: `preflight_verified_at` must be
set after Talli successfully obtains a short-lived Systembruker token for the
exact company, system, right, and `externalRef`. The token is immediately
discarded.

### Owner flow

1. The owner selects **Koble til Altinn** for the company.
2. Talli requires fresh signed AAL2 and creates a durable local `creating` row.
3. Talli creates the Altinn request, validates the response, stores only safe
   request metadata, changes the state to `new`, and sets a short-lived secure,
   HTTP-only, SameSite=Lax cookie containing only the local request UUID.
4. Talli redirects the owner to Altinn's returned `confirmUrl`.
5. Altinn returns the browser to the fixed Talli callback.
6. The callback requires the authenticated Talli session and resolves the exact
   cookie-selected request after rechecking that the user owns its company. If
   the cookie is missing or stale, Talli redirects to the company's connection
   page and requires the owner to select **Kontroller status**; it never guesses
   among pending requests. Callback parameters are never treated as proof.
7. Talli independently reads the request from Altinn and verifies all fixed
   identifiers and rights.
8. If accepted, Talli requests the exact delegated Systembruker token as a
   read-only preflight, discards it, stores the verification timestamp, and
   presents **Tilkoblet**.
9. Rejected, denied, timed-out, malformed, or mismatched requests remain blocked
   with a clear recovery path. Renewal creates a new opaque external reference;
   it never mutates a terminal request into a new request.

The company connection state shown to the owner is:

`Ikke tilkoblet -> Venter på godkjenning -> Verifiserer -> Tilkoblet`

Terminal failures show `Avvist`, `Avslått`, `Utløpt`, or `Må kontrolleres` with a
safe explanation and a retry action where Altinn permits it.

### Systemregister callback update

Talli's production Systemregister definition must contain exactly the callback
URL in `allowedRedirectUrls`. Updating the definition is a separate
operator-only operation requiring an admin grant, fresh AAL2, the existing
operations environment gate, explicit typed confirmation, and an audit record.

The operation may perform a production `PUT` only when the existing definition
matches Talli's fixed system, vendor, names, descriptions, RF-1086 right, client
ID, empty access-package list, and visibility. The only permitted difference is
the exact callback allowlist. Any other drift returns `definition_conflict` and
does not write.

## Production Filing Reconciliation

### Submission boundary

The existing immutable owner approval, exact pilot entitlement, production
release gates, stable idempotency keys, and append-only journal remain in force.
The Systembruker request table does not replace those controls. A production send
also requires an accepted and preflight-verified request matching the filing's
owner, company, and entitlement `externalRef`.

### Initial bounded polling

After `POST bekreft`, Talli performs up to five read-only archive lookups with a
two-second interval. It treats the observed `GLD_021 / GLD_1017` response and an
empty document collection as processing, not rejection. This matches the accepted
TT02 evidence.

If documents do not appear in that window, the submission remains `processing`.
Talli must not repeat any POST merely because feedback is delayed.

### Resumable reconciliation

Reconciliation is a separate idempotent read-only operation:

- it runs while the filing result screen remains open;
- it can be resumed by the owner on refresh or a later visit;
- it reuses the stored `forsendelseId` and exact Systembruker identity;
- it appends an event only when the observed safe state or artifact set changes;
- it never turns a read timeout into an authority mutation retry.

This first-beta design does not require a cron service. If the browser closes,
the next authenticated visit resumes reconciliation. This avoids new paid
infrastructure and keeps the first filing observable by the owner and founder.

### Feedback artifacts and final states

Skatteetaten recommends the individual-document endpoint for feedback. Talli
retrieves individual feedback artifacts when references are available and stores
the private bytes in the existing `company-documents` bucket. Database metadata
contains the company/submission relationship, authority reference, content type,
byte length, SHA-256 hash, retrieval time, and classification result. Raw XML,
tokens, personal identifiers, and company data are prohibited from logs and safe
audit fields.

The user-facing states are:

- `sent`: the mutation sequence returned transport references;
- `processing`: final feedback is not yet available;
- `accepted`: an explicit recognised authority response proves acceptance;
- `rejected`: an explicit recognised authority response proves rejection;
- `action_required`: feedback exists but is malformed, unrecognised, ambiguous,
  or requires human classification;
- `unknown`: a mutation outcome is ambiguous and all automatic writes stop.

Talli must never present `sent`, document availability, or transport receipt as
authority acceptance. Unrecognised feedback fails closed to `action_required` and
preserves the artifact for owner/operator review.

## Failure Handling

- Network failure before an Altinn request is created leaves a recoverable local
  `creating` row; a retry first checks by external reference before creating.
- Altinn duplicate/pending responses are reconciled by external reference rather
  than creating parallel requests.
- Terminal rejected, denied, or timed-out requests are immutable evidence; a
  renewal uses a new external reference.
- Authority identity, right, company, or redirect mismatches are security
  failures and cannot be overridden by the owner.
- A known retryable read failure remains `processing`; a mutation timeout remains
  `unknown` and requires read-only reconciliation.
- Malformed or oversized responses fail closed without persisting raw content.
- The production kill switch continues to stop new sends while preserving all
  request, approval, submission, event, and artifact records.

## Security and Privacy

- Owner membership and fresh signed AAL2 are checked server-side before request
  creation and production filing actions.
- Callback correlation uses the authenticated session and durable owner-scoped
  request state. Query parameters never authorize or approve anything.
- Redirect and confirmation URLs require HTTPS and exact host/path validation.
- Maskinporten credentials remain server-only managed secrets.
- Authority access tokens are held only in memory for the current operation.
- RLS prevents cross-company reads; service-role actions recheck company and
  request identity before writes.
- Private authority artifacts use the existing isolated storage bucket and
  short-lived signed download flow.
- Audit events contain only allowlisted status, hashes, fixed operation names,
  authority HTTP status, timestamps, and opaque references.

## Testing Strategy

All behavior changes follow red-green-refactor. Automated tests never create a
production Systembruker request or production filing.

Required coverage:

1. Altinn client request payloads, scopes, response validation, response limits,
   URL allowlists, error mapping, and lookup by external reference.
2. Systemregister update projection: exact callback-only drift is writable;
   unrelated definition drift is blocked.
3. Database table constraints, RLS, owner-only creation, signed-AAL2 enforcement,
   allowed state transitions, terminal immutability, and tenant isolation.
4. Owner actions and callback: create, redirect, independently refresh status,
   accepted-token preflight, terminal failures, and duplicate/pending recovery.
5. Production send boundary rejects missing, mismatched, or unverified
   Systembruker state.
6. Journaled RF-1086 polling handles delayed documents, observed TT02 eventual
   consistency, empty responses, restart/resume, and no duplicate POSTs.
7. Feedback artifact validation, hashing, private storage, final-state
   classification, and fail-closed unknown feedback.
8. Browser tests for the complete mocked connection state machine and resumable
   filing-result UX.
9. Existing typecheck, build, security, Supabase, controlled-production, backup,
   and RF-1086 suites remain green.

## Production Activation and Cost Boundary

After implementation and verification, production activation remains explicit:

1. deploy with filing disabled;
2. record fresh security/restore and reviewer evidence;
3. enable the one-time operator Systemregister operation;
4. update and verify the exact callback allowlist, then disable the operations
   gate again;
5. complete one customer Systembruker connection and read-only preflight;
6. create the exact pilot entitlement and finish the production signoffs;
7. enable filing only for the named, founder-assisted first submission.

No paid service, plan upgrade, certificate, or scheduler is part of this design.
Any future step that could incur a charge requires separate explicit approval
under the repository cost guardrail.

## Success Criteria

The design is complete when a supported company owner can:

1. start the Systembruker connection in Talli;
2. approve the exact RF-1086 right in Altinn;
3. return automatically to Talli and see a verified connection;
4. review and approve an immutable supported RF-1086 filing;
5. send exactly once under all production gates;
6. see truthful durable progress and resume read-only reconciliation;
7. receive an accepted/rejected result only when explicit authority feedback
   proves it, with the private receipt available from Talli.
