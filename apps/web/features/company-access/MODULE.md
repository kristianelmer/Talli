# Company access web feature

<!-- architecture-inventory
{"apiOperations":["companyAccessGetSelectedContext"],"dependencies":[],"publicEntryPoints":["@/features/company-access","apps/web/features/company-access","apps/web/features/company-access/index.ts"],"routes":["/companies/[companyId]/annual-reporting/[incomeYear]","/connections","/dashboard","/workspace"]}
-->

## Purpose

This feature loads authenticated company context for Norwegian owner presentation
through `companyAccessGetSelectedContext` in the committed generated client.

## Owns and must not own

It owns the listed owner route integration, no-store transport mapping, and its
feature-owned presentation model derived from the generated company context. It must not decide membership, role,
resource-scope, AAL2, or tenant concealment; those policies belong to the backend
capability. It must not access Supabase business persistence, call a business
endpoint with `fetch`, import Supabase persistence DTOs, or deep-import the
client.

## Public interface and collaboration

Other web code imports `@/features/company-access`; the declared compiled paths
are `apps/web/features/company-access` and
`apps/web/features/company-access/index.ts`. The web establishes the Supabase
session, then passes its access token only as generated-client transport headers.
The feature has no web-feature dependency. It consumes the root
`@talli/talli-api-client` package and the same package-private
`#backend-configuration` helper as system boundary, preserving one typed,
fail-closed origin contract without exposing configuration values.

## Cache, browser, and tests

Authenticated company context defaults to `no-store`; the complete context is
available only after the backend's server-owned owner/AAL2 policy, and the
generated decoder rejects any broader role, scope, or assurance value. No cache exception or
direct browser business-data flow is approved. Feature coverage is in
`apps/web/tests/company-access-presentation.test.mjs`; architecture coverage is
in `tests/architecture_foundation.test.mjs`.

## Compatibility and change rule

There are no compatibility exceptions for selected company context. Change this
document and `module.json` together when routes, operation, public imports,
cache policy, or responsibilities change.

The backend capability's ownership of `public.companies` and
`public.company_memberships` is authoritative. Separately, legacy callers
registered by exact path, rule, and resource remain temporary compatibility
adapters: invitations and membership administration exit in #160, cancellation
and deletion exit in #161, and onboarding plus final stage exit complete in
#138. They do not belong to this feature and cannot serve authenticated
company-context reads.
