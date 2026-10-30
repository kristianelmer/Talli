# Talli backend

Independent FastAPI application for Talli's production HTTP boundary.

Company Tax preserves WHATWG URL parsing with `ada-url==4.0.0` (the Ada version
used by the pinned predecessor Node runtime) and Norwegian collation with
`PyICU==2.16.2`. On Debian/Ubuntu install `pkg-config libicu-dev g++` before
`uv sync`. On macOS install `pkg-config icu4c` and expose ICU's `bin` and
`lib/pkgconfig` directories during the build. Use standalone CPython with one
consistent compiler/library environment; a Conda interpreter can mix its older
C++/ICU runtime with Homebrew headers. Existing environments must rebuild PyICU
when changing the underlying ICU runtime.

These libraries perform local parsing/sorting and make no network requests.
See the [Ada Python documentation](https://ada-url.readthedocs.io/) and
[PyICU installation instructions](https://pypi.org/project/pyicu/). The frozen
Company Tax tests cover URL canonicalization, Norwegian text ordering, stable
collation ties and UTF-16 truncation.

```bash
uv sync --project apps/backend --locked
uv run --project apps/backend uvicorn talli_backend.main:app \
  --app-dir apps/backend/src --host 127.0.0.1 --port 8000
```

The committed OpenAPI artifact is generated from this application:

```bash
uv run --project apps/backend python apps/backend/scripts/generate_openapi.py
```

Annual billing provider recovery and webhook intake are disabled by default.
To configure the designated Vipps test merchant **535717**, set
`TALLI_ANNUAL_BILLING_MODE=vipps-mt` and every `TALLI_VIPPS_MT_*` setting plus
`TALLI_ANNUAL_NOTIFICATION_DATABASE_URL` documented in `.env.example`.
Use the merchant's test credentials and registered webhook secret. The callback
must be an HTTPS URL ending exactly in
`/api/v1/billing/annual/provider-notifications`, without a query or fragment.
Confirmation origins must be verified from that merchant's test response and
listed as exact HTTPS origins without trailing slashes. Incomplete or malformed
enabled settings stop startup with the setting name; values are never reported.

The notification connection needs its own backend login that can set only
`annual_notification_executor`. Configuration constructs adapters without network
calls. Requests use the existing `https://apitest.vipps.no` adapter; production
Vipps has no configuration mode. Enabling merchant-test transport leaves trusted
checkout readiness and its current-source verifier unavailable, so new purchases
remain blocked until those source-owned dependencies are implemented. Existing
recorded operations can use their recovery routes, and authenticated notifications
are stored as delivery receipts. Restart with mode `off` to disable both transports.

Checkout observation also has a separate standalone entry point. It defaults to
an offline configuration check, with no database/provider calls:

```bash
uv run --project apps/backend python apps/backend/scripts/run_annual_checkout_reconciliation.py
```

Set `TALLI_ANNUAL_CHECKOUT_RECONCILIATION_MODE=vipps-mt`, the shared designated
`TALLI_VIPPS_MT_*` provider settings, and the separate
`TALLI_ANNUAL_CHECKOUT_RECONCILIATION_DATABASE_URL` before explicitly passing
`--run-once`. This runs one bounded observation of an existing committed checkout
and exits with only `idle`, `reconciled` or `retry` in its JSON outcome. Errors
contain fixed codes and no tenant/payment data. It does not start a loop, schedule
a task, create an owner session, or enable new checkout/source authority.

The worker connection requires an independently provisioned, account-bound
principal with only `annual_checkout_observer_executor` membership. It must not
reuse the HTTP business, notification, migration or service-role connection.
The worker mode is independent of `TALLI_ANNUAL_BILLING_MODE`; neither setting
enables the other. See [the worker runbook](../../docs/billing/annual-checkout-reconciliation.md).

Company-wide RF test history defaults to `TALLI_COMPANY_TEST_RETENTION_MODE=off`.
After the target has been admitted, `postgres` selects the existing dedicated
reader using shared `SUPABASE_URL` / `SUPABASE_ANON_KEY` and the backend-only
`TALLI_COMPANY_TEST_RETENTION_DATABASE_URL`. It never falls back to `DATABASE_URL`
or `TALLI_LEDGER_DATABASE_URL`. Missing/off ignores unused history settings;
unknown modes or incomplete/malformed enabled settings stop startup with only
the setting name. Configuration constructs the reader without Auth/database I/O.
Explicit `company_test_retention_session_factory` injection bypasses ambient
history settings and retains responsibility for its own readiness probe.

Before enabling, verify owner-designated Auth/key and database provenance,
alignment with CompanyAccess's identity/company target, the restricted login's
`SET ROLE shareholder_register_filing_executor` grant, and the installed RF
membership function, retained-history schema and permissions. Use neither a
migration/service-role principal nor a superuser/BYPASSRLS login. A dedicated
setting does not prove target isolation or least privilege; different pooler
URLs can address the same database. Current server Auth and a canonical session
claim remain required, but configuration does not establish persisted session
or revocation behavior. No schema, role or session is provisioned automatically.

The reader keeps its read-only snapshot and current accepted-member check.
Downloads additionally repeat CompanyAccess's current-session and fifteen-minute
MFA check before and after capture. Internally composed history adds its actual
DSN/executor and shared Auth to `/health/ready`, including when general RF is
injected. These existing bounded probes establish Auth-settings/key access and
connectivity/SET ROLE, not schema completeness, least privilege, retained records,
user-session persistence, download authorization or hosted readiness. An explicit
`readiness_probe` still takes precedence. Restart with mode `off` to close both
history routes again; general RF configuration cannot enable them.
