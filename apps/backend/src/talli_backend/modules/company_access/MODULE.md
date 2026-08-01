# Company access backend capability

<!-- architecture-inventory
{"dependencies":[],"ownedTables":["public.companies","public.company_memberships"],"ports":["CompanyAccessGateway"],"publicEntryPoints":["talli_backend.modules.company_access.public"]}
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
- Identifiers: `CompanyAccessGateway`, `CompanyContext`, `company_access_adapter`

`CompanyAccessGateway` is the narrow outbound port for validated session identity
and bearer-scoped membership/company reads. The system boundary injects the
registered `SupabaseCompanyAccessAdapter`; capability policy never constructs
Supabase or HTTP infrastructure.

This complete owner context has one server-owned `owner_sensitive` policy,
always requires `aal2`, and accepts only an active `owner` membership; callers
cannot choose or downgrade its role, resource scope, or assurance level. These
three values are fixed literals in the response contract.
The backend validates the Supabase session before checking that session's RLS
scope. A foreign company, outsider, reviewer, or read-only member receives the
tenant-concealed `COMPANY_CONTEXT_NOT_FOUND` response.

Ownership of `public.companies` and `public.company_memberships` is authoritative
here. Temporary web callers used by onboarding are explicitly registered by
path, rule, and resource in `architecture/compatibility.json` under #138; they
are adapters during migration, not co-owners, and authenticated context reads
have no compatibility exception.

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
