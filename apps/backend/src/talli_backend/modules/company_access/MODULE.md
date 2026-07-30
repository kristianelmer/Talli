# Company access backend capability

<!-- architecture-inventory
{"dependencies":[],"ownedTables":["public.companies","public.company_memberships"],"ports":[],"publicEntryPoints":["talli_backend.modules.company_access.public"]}
-->

## Purpose

`company_access` owns the authenticated company context. It independently
validates the Supabase session, reads only through that session's RLS scope, and
decides accepted membership, role, resource scope, AAL2, and tenant concealment.

## Owns and must not own

It owns `public.companies` and `public.company_memberships` for this selected
context query, sourced from `supabase/migrations/0001_authenticated_workspace.sql`.
It must not own onboarding, invitations, agreement acceptance, cancellation, or
support-operator workflows; those remain in later company-access slices. It must
not use service-role access or bypass RLS for ordinary business reads.

## Public interface

Import only `talli_backend.modules.company_access.public`.

- Queries: `CompanyAccessService`, `CompanyContextResponse`
- Error: `CompanyAccessError`
- Identifier: `CompanyContext`

This complete owner context has one server-owned `owner_sensitive` policy and
always requires `aal2`; callers cannot choose or downgrade its resource scope.
The backend validates the Supabase session before checking that session's RLS
scope. A foreign company or outsider receives the tenant-concealed
`COMPANY_CONTEXT_NOT_FOUND` response.

## Collaboration and tests

The backend-system `company-access-context` workflow serves the generated
contract. The web feature consumes that contract and never reads company or
membership persistence directly. Focused policy and hermetic Auth/PostgREST
gateway coverage is in `apps/backend/tests/test_company_access.py`; the
non-skippable fresh-PostgreSQL RLS rehearsal is
`tests/company_access_database_runtime.test.mjs`.

## Compatibility and change rule

There are no compatibility exceptions for the selected company-context path.
Change this document and `module.json` together when its public interface,
ownership, authorization policy, or dependencies change.
