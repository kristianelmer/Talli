# Company access backend capability

<!-- architecture-inventory
{"dependencies":[],"ownedTables":["public.companies","public.company_invitations","public.company_memberships"],"ports":["CompanyAccessGateway"],"publicEntryPoints":["talli_backend.modules.company_access.public"]}
-->

## Purpose

`company_access` owns authenticated company context, company invitations, and
reviewer/read-only membership administration. It independently validates the
Supabase session, preserves that bearer's RLS scope, and owns AAL2 owner policy,
recipient binding, expiry, supported roles, atomic transitions, and concealment.

## Owns and must not own

It owns `public.companies`, `public.company_invitations`, and
`public.company_memberships`, attributed by the manifest to
`20260801090000_company_access_invitations.sql`. The backend system owns
`public.company_access_command_receipts` as technical idempotency state. It must not own onboarding,
agreement acceptance, cancellation, deletion, or support-operator workflows.
It must not use service-role access or bypass RLS for ordinary business calls.

## Public interface

Import only `talli_backend.modules.company_access.public`.

- Queries: company context, invitation lookup/listing, membership listing, and
  actor-derived pending side-effect continuations
- Commands: invite, accept, revoke, resend, and reviewer/read-only membership transitions
- Error: `CompanyAccessError`
- Port: `CompanyAccessGateway`

Business request contracts are immutable, reject undeclared fields, and live in
this public entry point rather than the composition root. The public names include
`CreateCompanyInvitationRequest`, `AcceptCompanyInvitationRequest`,
`CompanyInvitationCommandRequest`, `AdministerCompanyMembershipRequest`,
`CompanyAccessService`, `CompanyContext`,
`CompanyContextResponse`, `CompanyInvitation`, `CompanyInvitationResponse`,
`CompanyInvitationListResponse`, `InvitationLookup`, `CompanyMembership`,
`CompanyMembershipResponse`, `CompanyMembershipListResponse`, `InvitationRole`,
`MembershipState`, `InvitationSideEffectContinuation`,
`InvitationSideEffectContinuationList`, `InvitationSideEffectCompletion`, and
`company_access_adapter`.

The system boundary injects `SupabaseCompanyAccessAdapter`; capability policy
never constructs Supabase or HTTP infrastructure. Owner context and administration
require accepted owner membership and AAL2. Invitation lookup and acceptance bind
the validated subject and normalized Auth email to a pending, unexpired token hash.
Acceptance and every role/removal transition execute in one database transaction
as the restricted `company_access_executor` NOLOGIN/NOBYPASSRLS role. Explicit RLS
policies remain the authorization boundary even though the RPCs are security
definers; the executor neither owns the tables nor bypasses RLS.
Forced RLS applies only to the technical command-receipt table; invitation and
membership RLS is genuine because the command executor is a non-owner with
NOBYPASSRLS.
Durable operation receipts replay consequential commands and optimistic expected
revisions reject competing resend, revoke, and membership changes. If a command's
transport outcome is unknown, the adapter retries the identical operation once;
the receipt returns the committed result instead of repeating the mutation.
Invitation commands atomically leave their receipt continuation pending until the
web's exact actor+operation+purpose UUIDv8 audit/outbox evidence exists. The
recovery endpoint derives the actor from Auth, returns at most twenty of that
actor's continuations, never invokes a business command, and completion verifies
the exact evidence before clearing the delivery token. Expired continuations
remain recoverable for audit evidence, but their token is cleared and obsolete
delivery is not queued; a new invite/resend is required if delivery is still
wanted.
Owner creation, demotion, and removal are not exposed. Public responses never
contain token hashes.

Create/resend delivery tokens are deliberately persisted in two places: the
private command receipt until it is cleared by side-effect completion, acceptance, revocation, or a newer
resend, and the existing `notification_outbox` payload written by the exact #156
compatibility action. Authenticated Data API roles have no receipt-table grant;
outbox readability remains the existing accepted-owner policy. #160 adds no
clock-driven purge. An expired token is never returned, and a pending-side-effect
recovery read clears it. Until recovery or another clearing command touches the
receipt, the expired token can remain stored at rest. Retention/delivery migration
remains #156. This is delivery-secret persistence, never token-hash disclosure.

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

Ownership is authoritative here. Remaining compatibility adapters are registered
by exact path/rule/resource/operation: cancellation/deletion exits in #161 and
onboarding exits in #138. Audit and notification rows remain owned by their exact
legacy/technical scopes while the transaction preserves their observable events.

## Collaboration and tests

The backend-system company-access workflows serve the generated contract. Focused
policy and adapter coverage is in `apps/backend/tests/test_company_access.py`;
transactional schema coverage is in
`tests/company_access_invitations_schema.test.mjs`; fresh-PostgreSQL RLS coverage
is in `tests/company_access_database_runtime.test.mjs`.

## Compatibility and change rule

There are no company-access invitation or membership-administration compatibility
exceptions. Change this document and `module.json` together when its interface,
ownership, policy, or dependencies change.
