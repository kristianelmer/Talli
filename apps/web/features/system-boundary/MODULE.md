# System boundary web feature

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

Other web code imports only `@/features/system-boundary`. This feature has no
feature dependency, so its declared graph is acyclic. It consumes only the root
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
