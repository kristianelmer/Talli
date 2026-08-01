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
`public.company_memberships`, sourced from the authenticated-workspace schema and
`20260801090000_company_access_invitations.sql`. It must not own onboarding,
agreement acceptance, cancellation, deletion, or support-operator workflows.
It must not use service-role access or bypass RLS for ordinary business calls.

## Public interface

Import only `talli_backend.modules.company_access.public`.

- Queries: company context, invitation lookup/listing, and membership listing
- Commands: invite, accept, revoke, resend, and reviewer/read-only membership transitions
- Error: `CompanyAccessError`
- Port: `CompanyAccessGateway`

The public names are `CompanyAccessService`, `CompanyContext`,
`CompanyContextResponse`, `CompanyInvitation`, `CompanyInvitationResponse`,
`CompanyInvitationListResponse`, `InvitationLookup`, `CompanyMembership`,
`CompanyMembershipResponse`, `CompanyMembershipListResponse`, `InvitationRole`,
`MembershipState`, and `company_access_adapter`.

The system boundary injects `SupabaseCompanyAccessAdapter`; capability policy
never constructs Supabase or HTTP infrastructure. Owner context and administration
require accepted owner membership and AAL2. Invitation lookup and acceptance bind
the validated subject and normalized Auth email to a pending, unexpired token hash.
Acceptance and every role/removal transition execute in one database transaction;
owner creation, demotion, and removal are not exposed. Public responses never
contain token hashes.

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
