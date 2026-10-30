# System boundary backend technical module

<!-- architecture-inventory
{"dependencies":[],"ownedTables":[],"ports":["SystemBoundaryTransport"],"publicEntryPoints":["talli_backend.modules.system_boundary.public"]}
-->

## Purpose

This module owns Talli's deterministic boundary-availability contract. It is a
technical representative module only: it owns no business rule, business table,
provider operation, or authoritative write.
Its manifest kind is `backend-technical-module`, so it is part of the backend
system and is not one of ADR-0011's business capabilities.

## Owns and must not own

It owns the `SYSTEM_BOUNDARY_AVAILABLE` public contract and the
`SystemBoundaryTransport` port. It owns no Postgres schema, table, bucket,
projection, or migration. It must not own accounting, filing, billing,
authorization, direct persistence, provider operations, or cross-module
implementation imports.

## Public interface

Import only `talli_backend.modules.system_boundary.public`.

- Query contract: `SYSTEM_BOUNDARY_AVAILABLE`
- Stable error code: `BOUNDARY_UNAVAILABLE`
- Port protocol: `SystemBoundaryTransport`
- Adapter registration: `adapter_for`

The FastAPI adapter is selected by backend composition and registered in source
with `adapter_for(SystemBoundaryTransport)`, not selected by callers.

## Collaboration, ports, and tests

The module has no capability dependency, so it cannot introduce a cycle.
`SystemBoundaryTransport` is bound to `talli_backend.main.create_app` in
`architecture/backend-system.json`. Contract coverage is in
`apps/backend/tests/test_system_boundary.py`; manifest and import enforcement is
in `tests/architecture_foundation.test.mjs`.

## Compatibility and change rule

There are no compatibility exceptions. Change this document and `module.json`
together whenever its public interface, dependencies, port, ownership, or
forbidden responsibilities change.


## Operational health composition

`/health/live` is process-only. `/health/ready` uses the backend-system adapter
`talli_backend.adapters.dependency_readiness`, injected by `create_app` from
its selected HTTP infrastructure. The tracer's `AVAILABLE` constant is not a
readiness probe. Unit/custom applications may explicitly inject `readiness_probe`;
injected business adapters are not inferred to be healthy.

The default composition probes Supabase `/auth/v1/settings` with the actual
`SUPABASE_ANON_KEY` and read-only `select 1` after setting every required executor
role on the actual restricted DSNs: Ledger (including composed Tax, Accounts,
Investments, Corporate Governance, Documents, Billing, RF, launch-signoff and
Authority Connections executors), Company Access, Banking, and Marketing
Measurement. Banking uses its existing ledger fallback only when its setting
is absent; an explicit empty value fails. Marketing is always composed for HTTP
and retention maintenance. Enabled default `vipps-mt` notification intake adds
its notification DSN/executor. Exact `TALLI_COMPANY_TEST_RETENTION_MODE=postgres`
adds the dedicated history DSN and `shareholder_register_filing_executor`, plus
shared Auth, even when general RF is injected. Missing/off remains closed; an
explicit history factory bypasses ambient history settings and owns its probe.
No history DSN fallback exists. It never uses privileged `DATABASE_URL`.

Each probe has a two-second deadline, inside a three-second total deadline.
Checks run concurrently; database connections close on cancellation. Shared
in-flight work and a two-second success/failure cache limit public probe load.
Shutdown cancels/drains outstanding work. All responses are `no-store`, with
only `ready` (200) or `not_ready` (503), never upstream diagnostics or secrets.
Auth responses are capped at 16 KiB and must match settings; redirects fail.
The settings endpoint is protected by Supabase gateway key-auth, unlike a
health-only probe: see the primary
[gateway configuration](https://github.com/supabase/supabase/blob/master/docker/volumes/api/kong.yml)
and [Auth settings contract](https://github.com/supabase/auth/blob/master/internal/api/settings.go).

These probes attest connectivity, credentials and SET ROLE grants, not function
or table-level privileges, migration completeness, business authorization,
filing readiness, object storage integrity, or external provider availability.
Standalone reconciliation/renewal workers and optional best-effort validation
observations (which cannot change HTTP outcomes) are excluded. No business or
provider operation runs as part of readiness. Regression tests are in
`apps/backend/tests/test_dependency_readiness.py`.

Auth settings checks the HTTP service and gateway key, not Auth's own database
connection or a user login. SET ROLE checks do not attest that the configured
login lacks superuser or BYPASSRLS privileges; provisioning remains a separate
deployment control.
