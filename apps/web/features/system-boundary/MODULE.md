# System boundary web feature

<!-- architecture-inventory
{"apiOperations":["systemBoundaryGetTracerStatus"],"dependencies":[],"publicEntryPoints":["@/features/system-boundary","apps/web/features/system-boundary","apps/web/features/system-boundary/index.ts"],"routes":["/health/live","/health/ready","/system-boundary"]}
-->

## Purpose

This feature presents the FastAPI system-boundary tracer in Norwegian. It maps
transport outcomes to safe presentation without recreating backend policy.

## Owns and must not own

It owns the `/system-boundary` route, presentation state, and the generated-client
mapping for `systemBoundaryGetTracerStatus`. It must not
own business policy, handwritten business DTOs, direct Supabase business
persistence, direct business-endpoint `fetch` calls, or generated-client deep
imports.

## Public interface and collaboration

Other web code imports `@/features/system-boundary`; the currently compiled
relative equivalent is explicitly declared as
`apps/web/features/system-boundary`. The Node health-route test environment uses
the declared `apps/web/features/system-boundary/index.ts`; no transport or
view-model deep import is public. This feature has no feature dependency, so its
declared graph is acyclic. It consumes the root `@talli/talli-api-client`
generated client package and the package-private `#backend-configuration`
boundary shared by both generated-client transports. That boundary owns the
typed `BackendConfigurationError` codes and fail-closed origin rules.

## Cache, browser, and tests

Authenticated data defaults to `no-store`; the operational boolean cache is the only exception. No direct browser
business-data flow is approved. Feature coverage is in
`apps/web/tests/system-boundary-presentation.test.mjs`; architecture coverage is
in `tests/architecture_foundation.test.mjs`.

## Compatibility and change rule

There are no compatibility exceptions. Change this document and `module.json`
together whenever routes, operations, public imports, cache policy, browser
flows, dependencies, or forbidden responsibilities change.


## Operational health

The feature owns `/health/live` and `/health/ready`. Liveness is process-only.
Readiness concurrently probes the configured `TALLI_BACKEND_URL` at `/health/ready`
and `SUPABASE_URL` at `/auth/v1/settings` with the actual `SUPABASE_ANON_KEY`
used by web sessions. Neither the tracer nor Auth `/health` proves dependency
readiness. Operational HTTP probes are not business-endpoint fetches.
Missing/invalid configuration, unavailable DNS, timeout, invalid key, redirects,
non-JSON, malformed/oversized bodies, or an unexpected response fail closed.
A shared in-flight check has a three-second total deadline; both success and
failure booleans are cached in-process for two seconds. This contains no user
information. HTTP responses always have `Cache-Control: no-store` and only
`ready` (200) or `not_ready` (503), without upstream details.

The Auth settings contract and key enforcement follow the primary
[Supabase gateway configuration](https://github.com/supabase/supabase/blob/master/docker/volumes/api/kong.yml)
and [Auth settings response](https://github.com/supabase/auth/blob/master/internal/api/settings.go).
The `/auth/v1/` catch-all has key-auth; the explicitly open Auth routes do not
include settings. The probe does not log in, refresh a session, or call a provider.
Readiness does not establish business authorization, filing permission, storage
object integrity, or external-provider availability.

Auth settings proves the Auth HTTP service and gateway API key path, not an Auth
database operation or a successful user login. Database probes do not attest
that supplied login roles are least-privileged; role provisioning remains a
separate deployment control.
