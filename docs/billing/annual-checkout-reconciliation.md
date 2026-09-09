# One-pass annual checkout observation

`apps/backend/scripts/run_annual_checkout_reconciliation.py` is an explicit
automation entry point for observing one existing annual checkout. It invokes
the public `annual_checkout_observation_operations` factory and one `run_once()`
call. Its MT provider can reconcile the original provider intent; this entry
point never calls provider execution to create an agreement, charge, cancellation
or refund.

The default is an **offline preflight**. It parses configuration and reports
missing setting names without constructing the worker or making database/network
calls. No background task starts with FastAPI, and this command has no loop or
hosted scheduler configuration.

## Configuration and authority

Use the designated test merchant **535717** with its backend-only test settings:

- `TALLI_ANNUAL_CHECKOUT_RECONCILIATION_MODE=vipps-mt`
- `TALLI_ANNUAL_CHECKOUT_RECONCILIATION_DATABASE_URL`
- `TALLI_VIPPS_MT_MERCHANT_SERIAL_NUMBER=535717`
- `TALLI_VIPPS_MT_CLIENT_ID`
- `TALLI_VIPPS_MT_CLIENT_SECRET`
- `TALLI_VIPPS_MT_SUBSCRIPTION_KEY`
- `TALLI_VIPPS_MT_CONFIRMATION_ORIGINS`

The worker mode defaults to `off`. The HTTP runtime's
`TALLI_ANNUAL_BILLING_MODE` does not enable this worker, and worker mode does not
enable the HTTP provider or webhook intake. Webhook credentials and the inbox
database URL are not needed for a worker pass. Neither command automatically
loads `.env` files; provide secrets through the backend process environment.

The separate database principal must be a dedicated `LOGIN NOINHERIT` role,
provisioned by an authorized operator with only the
`annual_checkout_observer_executor` membership (`SET` enabled, `INHERIT` and
`ADMIN` disabled). It must have no superuser, bypass-RLS, role/database creation
or replication privilege. Its actual database
`session_user` must have the enabled provider/account registration in
`billing.annual_checkout_observation_principals`. The adapter enforces that
identity, its authorization epoch and the lease fence. Configuration alone does
not establish database authority. This command neither provisions the principal
nor accepts owner claims or a caller-selected company/purchase identifier.

Use a dedicated login and connection string, not an HTTP business/inbox connection
or a migration/service-role principal. Keep its password and MT keys out of
command arguments, checked-in files and logs. The shared configuration loader
accepts only the designated MT account and the existing provider fixes the API
origin to `https://apitest.vipps.no`.

## Run explicitly

From the repository root, perform an offline check:

```sh
uv run --project apps/backend python apps/backend/scripts/run_annual_checkout_reconciliation.py
```

`configuration_valid` checks syntax/completeness only. It does not test credential
validity, connectivity, worker grants or lease availability. Preflight exits with
status 0 after producing its report, including when `configuration_valid` is false.

Once the intended database and worker authority are configured, request one pass:

```sh
uv run --project apps/backend python apps/backend/scripts/run_annual_checkout_reconciliation.py --run-once
```

The overall command pass is bounded to 45 seconds. It emits only a technical
outcome, with no company, purchase, provider-resource, amount, lease or secret:

| Outcome | Meaning |
| --- | --- |
| `idle` | No eligible checkout observation was claimed. |
| `reconciled` | The claimed checkout reached a terminal locally recorded state. |
| `retry` | The observation remains unresolved and a later pass may retry. |

These pass outcomes exit with status 0. During `--run-once`, disabled/invalid configuration, unavailable
storage, revoked authority, malformed outcomes or overall timeouts exit with
status 2 and a fixed error code. A `retry` outcome is not payment confirmation.
The stored fenced lease and retry state govern subsequent invocations. There is
no automatic repeat, and a timeout does not authorize a second provider mutation.

Stopping invocation or setting worker mode to `off` disables future passes.
Database principal revocation remains the authority control for a running pass;
an environment change cannot retroactively change a process's configuration.

## Limits and local verification

This entry point observes committed checkout intent. It supplies no new-sale
readiness, paid filing entitlement, renewal scheduling, refund initiation,
operator support authority, or provider production activation. It does not
establish actual MT execution or complete #192 acceptance merely by passing its
local tests.

```sh
uv run --project apps/backend pytest -c apps/backend/pyproject.toml \
  apps/backend/tests/test_annual_checkout_reconciliation_cli.py \
  apps/backend/tests/test_annual_billing_runtime_configuration.py -q
```

Those tests use local constructor/HTTP fixtures and the real public observation
service. The account-bound PostgreSQL adapter's separate mandatory database
suite owns transaction, privilege, lease and rollback proof.
