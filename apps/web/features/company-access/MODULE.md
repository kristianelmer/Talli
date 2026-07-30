# Company access web feature

<!-- architecture-inventory
{"apiOperations":["companyAccessGetSelectedContext"],"dependencies":[],"publicEntryPoints":["@/features/company-access","apps/web/features/company-access","apps/web/features/company-access/index.ts"],"routes":["/companies/[companyId]/annual-reporting/[incomeYear]","/connections","/dashboard","/workspace"]}
-->

## Purpose

This feature loads authenticated company context for Norwegian owner presentation
through `companyAccessGetSelectedContext` in the committed generated client.

## Owns and must not own

It owns the listed owner route integration, no-store transport mapping, and
presentation-ready company context. It must not decide membership, role,
resource-scope, AAL2, or tenant concealment; those policies belong to the backend
capability. It must not access Supabase business persistence, call a business
endpoint with `fetch`, write business DTOs by hand, or deep-import the client.

## Public interface and collaboration

Other web code imports `@/features/company-access`; the declared compiled paths
are `apps/web/features/company-access` and
`apps/web/features/company-access/index.ts`. The web establishes the Supabase
session, then passes its access token only as generated-client transport headers.
The feature has no web-feature dependency and consumes only the root
`@talli/talli-api-client` package.

## Cache, browser, and tests

Authenticated company context defaults to `no-store`; no cache exception or
direct browser business-data flow is approved. Feature coverage is in
`apps/web/tests/company-access-presentation.test.mjs`; architecture coverage is
in `tests/architecture_foundation.test.mjs`.

## Compatibility and change rule

There are no compatibility exceptions for selected company context. Change this
document and `module.json` together when routes, operation, public imports,
cache policy, or responsibilities change.
