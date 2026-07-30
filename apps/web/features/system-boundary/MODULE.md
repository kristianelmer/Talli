# System boundary web feature

<!-- architecture-inventory
{"apiOperations":["systemBoundaryGetTracerStatus"],"dependencies":[],"publicEntryPoints":["@/features/system-boundary","apps/web/features/system-boundary","apps/web/features/system-boundary/index.ts"],"routes":["/system-boundary"]}
-->

## Purpose

This feature presents the FastAPI system-boundary tracer in Norwegian. It maps
transport outcomes to safe presentation without recreating backend policy.

## Owns and must not own

It owns the `/system-boundary` route, presentation state, typed configuration,
and the generated-client mapping for `systemBoundaryGetTracerStatus`. It must not
own business policy, handwritten business DTOs, direct Supabase business
persistence, direct business-endpoint `fetch` calls, or generated-client deep
imports.

## Public interface and collaboration

Other web code imports `@/features/system-boundary`; the currently compiled
relative equivalent is explicitly declared as
`apps/web/features/system-boundary`. The Node health-route test environment uses
the declared `apps/web/features/system-boundary/index.ts`; no transport or
view-model deep import is public. This feature has no feature dependency, so its
declared graph is acyclic. It consumes only the root
`@talli/talli-api-client` generated client package.

## Cache, browser, and tests

Authenticated data defaults to `no-store`; no cache exception or direct browser
business-data flow is approved. Feature coverage is in
`apps/web/tests/system-boundary-presentation.test.mjs`; architecture coverage is
in `tests/architecture_foundation.test.mjs`.

## Compatibility and change rule

There are no compatibility exceptions. Change this document and `module.json`
together whenever routes, operations, public imports, cache policy, browser
flows, dependencies, or forbidden responsibilities change.
