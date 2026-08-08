# Company access web feature

<!-- architecture-inventory
{"apiOperations":["companyAccessAcceptInvitation","companyAccessAdministerMembership","companyAccessCompleteInvitationSideEffect","companyAccessCreateInvitation","companyAccessFinalizeDeletion","companyAccessGetSelectedContext","companyAccessListCancellations","companyAccessListInvitations","companyAccessListMemberships","companyAccessListPendingInvitationSideEffects","companyAccessLookupInvitation","companyAccessRequestCancellation","companyAccessResendInvitation","companyAccessReviewDeletion","companyAccessRevokeInvitation"],"dependencies":[],"publicEntryPoints":["@/features/company-access","apps/web/features/company-access","apps/web/features/company-access/index.ts"],"routes":["/companies/[companyId]/annual-reporting/[incomeYear]","/connections","/dashboard","/invite/accept","/operator","/workspace"]}
-->

## Purpose

This feature loads authenticated company context and carries invitation,
reviewer/read-only membership administration, owner cancellation/finalization,
and independent support deletion review through the committed generated client.

## Owns and must not own

It owns the listed route integration, no-store transport mapping, and presentation
derived from generated contracts. It must not decide invitation, membership,
cancellation evidence, role, fresh-AAL2, or tenant-concealment policy; those belong
to the backend capability. It must
not access Supabase business persistence, use business `fetch`, import persistence
DTOs, or deep-import the client.

## Public interface and collaboration

Other web code imports `@/features/company-access`. The web establishes the
Supabase session, then passes its access token only as generated-client headers.
Invitation lookup/acceptance and owner administration use the same thin transport
with ten-second deadlines and the root `@talli/talli-api-client` package.
Cancellation request/finalization use durable operation IDs and server-issued
revisions. The operator review form records an approval or rejection with an
evidence reference; the workspace exposes finalization only after approval.

## Cache, browser, and tests

Calls default to `no-store`; generated decoders reject every undeclared response
field, including all token/hash spellings at invitation boundaries. Consequential
forms carry durable operation IDs and expected revisions. The retained #155 audit
write uses a deterministic UUIDv8 derived from the authenticated actor, original
operation ID, and command/purpose. The backend receipt atomically owns a pending
side-effect continuation, so the no-input recovery form can finish the original
operation without issuing another business command. The restricted completion
RPC locks the receipt, reauthorizes current owner AAL2 or accepted membership even
for completed retries, verifies exact audit evidence, and captures one advancing
post-lock timestamp. That same timestamp governs both outbox RLS and persistence,
so it atomically inserts or reconciles the deterministic invitation outbox row
only before expiry, then completes and scrubs the receipt. Recovery remains
available after invitation expiry for audit evidence, but an expired delivery
token is cleared and no obsolete email is queued; the owner must issue a new
invite/resend if delivery is still wanted.
Feature coverage is in the company-access web tests and architecture coverage is in
`tests/architecture_foundation.test.mjs`.

## Compatibility and change rule

The backend owns `public.companies`, `public.company_cancellations`,
`public.company_deletion_reviews`, `public.company_invitations`, and
`public.company_memberships`. Invitation delivery no longer uses the #156
direct-web exception; the temporary #155 invitation-audit exception remains exact
and bounded. Cancellation/deletion no longer has a direct-web compatibility
adapter. Onboarding compatibility remains scoped to its later serialized ticket.
