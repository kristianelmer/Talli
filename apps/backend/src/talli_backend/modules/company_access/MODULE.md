# Company access backend capability

<!-- architecture-inventory
{"dependencies":[],"ownedTables":["public.companies","public.company_cancellations","public.company_deletion_reviews","public.company_invitations","public.company_memberships"],"ports":["CompanyAccessGateway"],"publicEntryPoints":["talli_backend.modules.company_access.public"]}
-->

## Purpose

`company_access` owns authenticated company context, company invitations,
reviewer/read-only membership administration, and the cancellation-to-deletion
lifecycle. It independently validates the Supabase session, preserves that
bearer's RLS scope, and owns fresh-AAL2 owner and deletion-review policy,
recipient binding, expiry, supported roles, atomic transitions, and concealment.

## Owns and must not own

It owns `public.companies`, `public.company_cancellations`,
`public.company_deletion_reviews`, `public.company_invitations`, and
`public.company_memberships`, with the latest ownership migration declared as
`20260808120000_company_access_cancellation_lifecycle.sql`. The backend system owns
`public.company_access_command_receipts` as technical idempotency state. It must not own onboarding,
agreement acceptance, physical business-data deletion, or general support-operator workflows.
It must not use service-role access or bypass RLS for ordinary business calls.

## Public interface

Import only `talli_backend.modules.company_access.public`.

- Queries: company context, invitation/cancellation listing, membership listing,
  and actor-derived pending side-effect continuations
- Commands: invite, accept, revoke, resend, reviewer/read-only membership
  transitions, owner cancellation request/resume, independent deletion review,
  and owner finalization
- Error: `CompanyAccessError`
- Port: `CompanyAccessGateway`

Business request contracts are immutable, reject undeclared fields, and live in
this public entry point rather than the composition root. The public names include
`CreateCompanyInvitationRequest`, `InvitationTokenRequest`, `AcceptCompanyInvitationRequest`,
`CompanyInvitationCommandRequest`, `AdministerCompanyMembershipRequest`,
`CompanyAccessService`, `CompanyContext`,
`CompanyContextResponse`, `CompanyInvitation`, `CompanyInvitationResponse`,
`CompanyInvitationListResponse`, `InvitationLookup`, `CompanyMembership`,
`CompanyMembershipResponse`, `CompanyMembershipListResponse`, `InvitationRole`,
`MembershipState`, `InvitationSideEffectContinuation`,
`InvitationSideEffectContinuationList`, `InvitationSideEffectCompletion`, and
`company_access_adapter`.

Cancellation contracts add `CompanyCancellation`, `CompanyCancellationListResponse`,
`CompanyDeletionReview`, `RequestCompanyCancellationRequest`,
`ResumeCompanyCancellationRequest`, `ReviewCompanyDeletionRequest`, and
`FinalizeCompanyDeletionRequest`. During the expand/deploy overlap, query
responses continue to decode legacy `export_required` rows; new requests never
create that state. Resume advances the exact revision-bound legacy row only after
a current authoritative archive receipt exists.

The system boundary injects `SupabaseCompanyAccessAdapter`; capability policy
never constructs Supabase or HTTP infrastructure. Owner context and administration
require accepted owner membership and AAL2. Invitation lookup and acceptance bind
the validated subject and normalized Auth email to a pending, unexpired token hash.
Acceptance and every role/removal transition execute in one database transaction
as the restricted `company_access_executor` NOLOGIN/NOINHERIT/NOBYPASSRLS role.
Pending recovery and completion use the separate restricted
`company_access_recovery_executor` role with only actor-owned receipt, exact audit
evidence, and workspace-invitation outbox policies. Explicit RLS policies remain
the authorization boundary even though the RPCs are security definers; neither
executor owns a table, inherits another role, or bypasses RLS.
Supabase's migration role cannot delegate `auth` schema usage. Versioned
migration-owned claim wrappers expose only the current request UID and JWT to
authenticated company-access policies and the two executor roles; public and
anonymous execution, direct Auth helper execution, Auth schema usage, and
executor schema creation remain denied. Function ownership transfer grants the
migration role only transient `SET` membership and grants the executors only
transient `CREATE` on `public`, revoking both in the same atomic block.
Forced RLS applies only to the technical command-receipt table; invitation and
membership RLS is genuine because the command executor is a non-owner with
NOBYPASSRLS.
Durable operation receipts replay consequential commands and optimistic expected
revisions reject competing resend, revoke, and membership changes. If a command's
transport outcome is unknown, the adapter retries the identical operation once;
the receipt returns the committed result instead of repeating the mutation.
Cancellation commands and their reconciliation RPC share an actor+operation
transaction lock. Reconciliation recomputes the normalized request fingerprint
from the original typed inputs, so an absent receipt is definitive before the
backend retries the exact operation ID and payload.
Invitation commands atomically leave their receipt continuation pending until the
web's exact actor+operation+purpose UUIDv8 audit evidence exists. The
recovery endpoint derives the actor from Auth, returns at most twenty of that
actor's continuations, never invokes a business command, and completion locks the
receipt, reauthorizes the actor's current accepted membership (and owner AAL2 for
owner commands), and verifies audit evidence. It then captures one advancing
post-lock timestamp for both the outbox RLS check and persistence decision, so it
atomically inserts/reconciles outbox evidence only while the receipt remains
unexpired. Even an already-completed retry must pass current authorization before
idempotent success. Completion clears the sole receipt token and scrubs legacy
delivery fields. Expired continuations
remain recoverable for audit evidence, but their token is cleared and obsolete
delivery is not queued; a new invite/resend is required if delivery is still
wanted.
Owner creation, demotion, and removal are not exposed. Public responses never
contain token hashes.

Before completion, a create/resend delivery token is stored in exactly one receipt
column; receipt JSON contains only token-independent delivery metadata. Atomic
completion builds delivery from that committed metadata and token, inserts the
outbox row, and clears/scrubs the receipt in one transaction. Acceptance,
revocation, newer resend, and expiry recovery apply the same receipt scrub.
Authenticated Data API roles have no receipt-table grant. #160 adds no
clock-driven purge. An expired token is never returned, and a pending-side-effect
recovery read clears it. Until recovery or another clearing command touches the
receipt, the expired token can remain stored at rest. Retention/delivery migration
remains #156. This is delivery-secret persistence, never token-hash disclosure.

Cancellation requests, legacy resume, and finalization require an accepted owner with an AAL2
authentication method no older than fifteen minutes. Independent approval or
rejection requires an active admin support operator with the same fresh MFA; an
owner cannot review their own request. The append-only deletion-review row is the
authoritative company-scoped legal/security evidence. Request and finalization
RPCs re-derive the archive audit, document, and artifact prerequisites while the
transaction is locked, and durable receipts replay an identical outcome after an
unknown transport result. Finalization records the lifecycle marker but never
physically deletes company business data. RLS conceals outsiders and permits only
accepted members or active support operators to list lifecycle evidence.
Legacy duplicate active rows are deterministically ranked by updated time,
request time, and ID. The survivor remains active; each loser becomes the terminal
`superseded` status with structured evidence and deterministic audit evidence.
Legacy authenticated table policies conceal superseded rows, while the generated
query RPC retains complete history.

The rollout is staged. Release A's automatic runner applies `20260801090000` only: it expands the
RPC/RLS boundary while the prior web policies still work. Release B deploys the
backend and generated-client web revision, verifies create/resend receipt replay,
and leaves that overlap in place. The destructive `20260801091000` artifact lives
under `supabase/contract-migrations`, outside the declared automatic runner.
Release C moves that immutable artifact into a later release's migration set; it
contracts only #160's direct invitation and membership policies. Before Release C,
rollback means returning to the prior web/backend revision while retaining the
additive database objects. After Release C, application rollback is bounded to a
generated-client revision; restoring the direct writer would require a reviewed
forward migration that reinstates the overlap and is not an implicit rollback.
The PostgreSQL runtime test executes the old direct writer, contract transition,
and new RPC writer in that exact sequence.

Cancellation follows the same expand/deploy/contract discipline. Release A applies
the additive `20260808120000` migration while the legacy direct writer remains
valid. Release B deploys the generated-client backend/web workflow and verifies
legacy `export_required` reads plus RPC receipt replay. Release C applies the
reviewed `20260808121000` contract artifact, revoking direct authenticated table
access while retaining the query and command RPCs. After that contraction, an
application rollback is bounded to a generated-client revision; restoring direct
persistence requires a new forward migration.

Ownership is authoritative here. Remaining compatibility adapters are registered
by exact path/rule/resource/operation. Until #157 owns published archive
projections, `company_access` consumes the bounded legacy generation/receipt
projection produced only by the existing server-side archive route; it does not
own archive composition or those three projection tables. Every source in
`architecture/company-archive-sources.json` participates in the same locked
generation protocol. A single company advisory-lock namespace serializes all
years and every company-wide source mutation, avoiding cross-year lock inversion.
The route begins the archive attempt before reading the company row and fails
closed if any declared read fails. Completion rejects the attempt if any source,
including company metadata, changed after begin. It
performs no write after receipt completion. Audit events remain archive inputs:
request and review audit writes intentionally stale the preceding receipt, so an
owner must export a new archive after independent approval before finalization.
Until #155 owns the
audit capability, lifecycle RPCs retain the exact append-only audit seam for
observable events, never as deletion authorization. Notification rows remain
owned by their exact technical scopes.

## Collaboration and tests

The backend-system company-access workflows serve the generated contract. Focused
policy and adapter coverage is in `apps/backend/tests/test_company_access.py`;
transactional schema coverage is in
`tests/company_access_invitations_schema.test.mjs` and
`tests/company_access_cancellation_schema.test.mjs`; fresh-PostgreSQL RLS coverage
is in `tests/company_access_database_runtime.test.mjs`.

## Compatibility and change rule

There are no direct-web company-access invitation, membership-administration, or
cancellation persistence exceptions. The manifest truthfully declares the
bounded #155 audit and #157 archive-projection dependencies described above.
Change this document and `module.json` together when its interface, ownership,
policy, or dependencies change.
