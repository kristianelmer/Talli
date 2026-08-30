# Company access web feature

<!-- architecture-inventory
{"apiOperations":["companyAccessAcceptInvitation","companyAccessAdministerMembership","companyAccessAdmitCompanyYear","companyAccessCompleteInvitationSideEffect","companyAccessCreateInvitation","companyAccessEligibilityDefinitive","companyAccessEligibilityPrecheck","companyAccessFinalizeDeletion","companyAccessGetCompanyRecord","companyAccessGetOperatorContext","companyAccessGetSelectedContext","companyAccessGrantSupportAccess","companyAccessListCancellations","companyAccessListInvitations","companyAccessListMemberships","companyAccessListPendingInvitationSideEffects","companyAccessLookupInvitation","companyAccessOpenSupportCase","companyAccessReadSupportCase","companyAccessReacceptAgreement","companyAccessRecheckCompanyYearEligibility","companyAccessRequestCancellation","companyAccessResendInvitation","companyAccessResumeCancellation","companyAccessReviewDeletion","companyAccessRevokeInvitation","companyAccessRevokeSupportAccess"],"dependencies":[],"publicEntryPoints":["@/features/company-access","apps/web/features/company-access","apps/web/features/company-access/index.ts"],"routes":["/companies/[companyId]/annual-reporting/[incomeYear]","/connections","/dashboard","/invite/accept","/onboarding","/operator","/selskapsgrense","/sjekk-selskapet","/workspace"]}
-->

## Purpose

This feature carries the public provisional and definitive eligibility check,
authenticated immutable company-year admission and safety rechecks, company and
operator context, and bounded operator company search. It also carries
agreement reacceptance, invitation and reviewer/read-only membership administration,
owner cancellation request/resume/finalization, and independent support deletion
review through the committed generated client.

## Owns and must not own

It owns the listed route integration, no-store transport mapping, and presentation
derived from generated contracts. It must not decide eligibility,
agreement evidence, invitation, membership, cancellation evidence, role,
fresh-AAL2, or tenant-concealment policy; those belong
to the backend capability. It must
not access Supabase business persistence, use business `fetch`, import persistence
DTOs, or deep-import the client.

## Public interface and collaboration

Other web code imports `@/features/company-access`. The web establishes the
Supabase session, then passes its access token only as generated-client headers.
The free `/sjekk-selskapet` journey uses `companyAccessEligibilityPrecheck` and
`companyAccessEligibilityDefinitive` without an account. It retains only a
short-lived HTTP-only continuation after definitive support. Authenticated
`companyAccessAdmitCompanyYear` sends the displayed authority, legal, privacy,
capability, public-fact, and material-answer evidence. The backend owns identity
lookup, authorization, current-version validation, and atomic persistence.
`companyAccessRecheckCompanyYearEligibility` appends the current safety state
after a material fact changes through `/selskapsgrense`, or when the owner
refreshes public/manifest evidence, while preserving the accepted promise and
read access. The `before_payment` and `before_filing` triggers are generated
contracts for their serialized capability migrations; this stage does not alter
those future capability writers.
Company facts and the caller's accepted membership role come from the
tenant-concealed company-record operation. Operator authorization and bounded
company discovery come from their generated operator operations.
Invitation lookup/acceptance and owner administration use the same thin transport
with ten-second deadlines and the root `@talli/talli-api-client` package.
Cancellation request, legacy resume, and finalization use durable operation IDs
and server-issued revisions. The workspace exposes resume only for an active
legacy `export_required` row and preserves the exact command after an indeterminate
transport outcome. The operator review form records an approval or rejection with
an evidence reference; the workspace exposes finalization only after approval.
The cancellation transport documents a 35-second backend worst-case path and uses
a 45-second outer deadline, leaving ten seconds for framework and network margin;
unknown outcomes still preserve the exact operation for reconciliation.

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
`public.company_deletion_reviews`, `public.company_invitations`,
`public.company_memberships`, and `public.customer_agreement_acceptances`.
Invitation delivery no longer uses the #156
direct-web exception; the temporary #155 invitation-audit exception remains exact
and bounded. Cancellation/deletion no longer has a direct-web compatibility
adapter. The #138 onboarding, agreement-acceptance, and BRREG web facades have
exited. The deprecated HTTP shape fails closed, and its internal AS-only writer
and web caller are absent; no direct-web compatibility adapter remains.
