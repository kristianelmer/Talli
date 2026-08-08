# Company access web feature

<!-- architecture-inventory
{"apiOperations":["companyAccessAcceptInvitation","companyAccessAdministerMembership","companyAccessCompleteInvitationSideEffect","companyAccessCreateInvitation","companyAccessGetSelectedContext","companyAccessListInvitations","companyAccessListMemberships","companyAccessListPendingInvitationSideEffects","companyAccessLookupInvitation","companyAccessResendInvitation","companyAccessRevokeInvitation"],"dependencies":[],"publicEntryPoints":["@/features/company-access","apps/web/features/company-access","apps/web/features/company-access/index.ts"],"routes":["/companies/[companyId]/annual-reporting/[incomeYear]","/connections","/dashboard","/invite/accept","/workspace"]}
-->

## Purpose

This feature loads authenticated company context and carries invitation and
reviewer/read-only membership administration through the committed generated client.

## Owns and must not own

It owns the listed route integration, no-store transport mapping, and presentation
derived from generated contracts. It must not decide invitation, membership, role,
AAL2, or tenant-concealment policy; those belong to the backend capability. It must
not access Supabase business persistence, use business `fetch`, import persistence
DTOs, or deep-import the client.

## Public interface and collaboration

Other web code imports `@/features/company-access`. The web establishes the
Supabase session, then passes its access token only as generated-client headers.
Invitation lookup/acceptance and owner administration use the same thin transport
with ten-second deadlines and the root `@talli/talli-api-client` package.

## Cache, browser, and tests

Calls default to `no-store`; generated decoders reject every undeclared response
field, including all token/hash spellings at invitation boundaries. Consequential
forms carry durable operation IDs and expected revisions. The retained #156
outbox write uses a deterministic UUIDv8 derived from the authenticated actor,
original operation ID, and command/purpose; the original operation ID remains
correlation data in the payload. Every insert error performs exact immutable-row
reconciliation instead of duplicating delivery. The backend receipt atomically
owns a pending side-effect continuation, so the no-input recovery form can finish
the original outbox/audit identities without issuing another business command.
Completion is accepted only when the database verifies the exact deterministic
evidence rows. Recovery remains available after invitation expiry for audit
evidence, but an expired delivery token is cleared and no obsolete email is
queued; the owner must issue a new invite/resend if delivery is still wanted.
Feature coverage is in the company-access web tests and architecture coverage is in
`tests/architecture_foundation.test.mjs`.

## Compatibility and change rule

The backend owns `public.companies`, `public.company_invitations`, and
`public.company_memberships`. No invitation or membership-administration direct-web
persistence exception remains. Cancellation/deletion and onboarding compatibility
adapters remain scoped to their later serialized tickets.
