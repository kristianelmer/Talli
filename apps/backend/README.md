# Talli backend

Independent FastAPI application for Talli's production HTTP boundary.

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
