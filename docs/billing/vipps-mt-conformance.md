# Vipps Merchant Test provider conformance

The standalone runner exercises the existing `VippsTestBillingProvider` against
the designated **Talli Recurring MT TEST sales unit, MSN 535717**. Its default
action is an offline configuration check. Every provider action requires both a
named action and `--allow-mt`; the adapter only calls `https://apitest.vipps.no`.

This runner uses a synthetic company identifier and local JSON state. It neither
grants paid entitlement nor writes billing database records. Its evidence covers
provider observations only. It does not establish webhook delivery/replay,
database receipt atomicity, trusted readiness, automatic worker behavior,
customer browser/mobile completion, or whole-issue #192 acceptance.

## Prepare existing test access

Use the existing designated test sales unit; verify its Norwegian/NOK market and
Recurring/Direct Capture configuration. Obtain its test sales-unit keys through
the business portal's **For developers → API keys → Test environment** view.
The shared loader rejects other merchant serial numbers. Use only this unit's
test credentials; local validation cannot establish which environment issued a key.

Supply these variables to the backend process through a local secret mechanism:

- `TALLI_VIPPS_MT_MERCHANT_SERIAL_NUMBER=535717`
- `TALLI_VIPPS_MT_CLIENT_ID`
- `TALLI_VIPPS_MT_CLIENT_SECRET`
- `TALLI_VIPPS_MT_SUBSCRIPTION_KEY`
- `TALLI_VIPPS_MT_CONFIRMATION_ORIGINS`: comma-separated verified HTTPS origins,
  with no path, query, fragment or trailing slash.

The runner does not read `.env` automatically and accepts no secrets as command
arguments. It does not require the production runtime mode, database connection,
or webhook secret. Do not loosen the confirmation origin check to accept an
unverified redirect.

Prepare a Norwegian test user's generated phone number and national identity
number, and finish its registration in the MT app. Real personal users do not
work in MT. The test-only force-accept endpoint also requires app registration;
this runner uses ordinary user approval. See the official [test environment
instructions](https://developer.vippsmobilepay.com/docs/knowledge-base/test-environment/)
and [Recurring quick start](https://developer.vippsmobilepay.com/docs/APIs/recurring-api/recurring-api-quick-start/).

Check configuration without creating local state, requesting a token, or making
any provider request:

```sh
uv run --project apps/backend python apps/backend/scripts/run_vipps_mt_conformance.py
```

`configuration_valid: false` identifies an incomplete or invalid setup. Output
contains missing variable names, never their values. A successful preflight only
checks local configuration; it does not prove that the keys work or that the
sales unit has the required capabilities.

## Start one durable run

Choose a private, persistent state path outside Git and keep it for every retry:

```sh
export TALLI_MT_RUN_STATE="$HOME/.local/state/talli/vipps-mt/run-01.json"
uv run --project apps/backend python apps/backend/scripts/run_vipps_mt_conformance.py \
  --action execute --allow-mt --stage checkout --state "$TALLI_MT_RUN_STATE" \
  --return-url https://YOUR-TEST-HOST/billing-return \
  --management-url https://YOUR-TEST-HOST/billing-management \
  --open-confirmation
```

Replace both URLs with the intended HTTPS test pages. URLs may not contain
credentials, queries or fragments. They become part of the immutable run and
provider agreement. The amount is **149000 øre / NOK 1490** and the agreement has
a yearly interval. This is a test-environment provider scenario, not approval to
charge a company or bypass Talli's sold-path eligibility/readiness gates.

`--open-confirmation` opens only an allowlisted provider URL in the default
browser. The capability URL is never printed or saved in the state/evidence.
Approve the agreement with the MT user, then reconcile the same run:

```sh
uv run --project apps/backend python apps/backend/scripts/run_vipps_mt_conformance.py \
  --action reconcile --allow-mt --stage checkout --state "$TALLI_MT_RUN_STATE"
```

Add `--open-confirmation` to that command if a pending agreement needs reopening.
Only a confirmed full captured amount permits the dependent scenarios below.

## Exercise each scenario

For each row, use the same command with `--action execute --allow-mt`, the named
`--stage`, and the original `--state`. Supply `--due-date YYYY-MM-DD` when first
creating either renewal stage, replacing the placeholder with a date at least
one calendar day ahead in Europe/Oslo.

| Stage | Required observation | Provider effect / evidence |
| --- | --- | --- |
| `checkout` | New run | Create yearly agreement and initial charge; user approves, then reconcile full capture. |
| `renewal` | Confirmed initial capture | Schedule a distinct recurring charge of 149000 øre. Reconcile after its actual due-date processing until captured. |
| `partial-refund` | Initial capture with zero refunded | Refund 37250 øre of the initial charge. |
| `remaining-refund` | Confirmed partial refund of 37250 øre | Refund the remaining 111750 øre of the initial charge. |
| `full-refund` | Confirmed recurring capture with zero refunded | Refund the recurring charge's full 149000 øre in one operation. |
| `cancel-renewal` | Confirmed initial capture | Schedule a second, separately identified recurring charge for a future date. |
| `cancel-charge` | Second recurring charge pending with zero captured | Cancel that charge and reconcile its cancellation. |
| `stop` | Original charge terminal; any scheduled renewals refunded, canceled, or terminal with zero captured/refunded | Stop the agreement; reconcile the stopped status. |

Run `stop` last. New scenarios cannot start once the stop stage exists. A stop
does not silently cancel an unresolved renewal: a scheduled `renewal` requires
its confirmed `full-refund`, and `cancel-renewal` requires confirmed
`cancel-charge`. These restrictions keep each scenario's evidence explicit.
An observed terminal failed/canceled charge with zero captured and refunded
also permits stop, so a failed test cannot strand its active agreement. Its
failure remains in the evidence; cleanup does not convert the scenario to a pass.

Provider scheduling uses real MT processing time. The runner does not advance
the clock or fabricate a recurring capture. Pending/unknown results are evidence
of an unfinished observation, not a pass. Use bounded manual reconciliation;
there is no background polling loop. The [official Recurring
checklist](https://developer.vippsmobilepay.com/docs/APIs/recurring-api/recurring-api-checklist/)
requires actual ACTIVE/STOPPED agreements and CHARGED/REFUNDED recurring charges.

## Retry, recovery and evidence

An ordinary repeated `execute` becomes **reconciliation** once that stage has
been started. It keeps the original intent, operation UUID, charge reference,
due date and provider idempotency key. A state lock serializes concurrent
invocations. Atomic, fsynced state writes record dispatch before any network
request, including token acquisition, so a lost response or crash cannot cause
an ordinary rerun to create a second operation.

For a deliberate provider idempotency test, use `--action repeat-execute` on an
existing stage whose latest completed result is pending or confirmed. This
resubmits the exact stored request and provider key. It is rejected after an
unknown result or interrupted attempt; use `reconcile` in those cases. Do not
delete the state or create a fresh run to recover a lost response.

The private state file retains bounded typed observations, timestamps, source
revision, intent digests and operation keys. It contains no API credentials,
access tokens, webhook secrets, raw response bodies or confirmation URLs.
Standard output is a sanitized JSON record for the current attempt; error output
uses fixed diagnostic codes. Keep the state plus command output as test evidence
and inspect it before deliberately publishing a sanitized acceptance artifact.
The state checksum detects accidental edits; it is not a signature or a trusted
business authorization record. Do not edit it to manufacture prerequisite proof.

Real webhook evidence additionally requires registering the exact public callback,
retaining its registration secret, exercising signed delivery/replay and verifying
durable intake. The runner neither registers nor consumes callbacks. See the
[Webhooks quick start](https://developer.vippsmobilepay.com/docs/APIs/webhooks-api/quick-start/).
MT also has no bank settlement reports; its resource observations cannot prove
production settlement. Source readiness, authorized reconciliation/renewal/refund
workers and the final customer/operator flows remain separate acceptance work.

## Local verification

The focused suite injects `httpx.MockTransport` into the actual provider adapter:

```sh
uv run --project apps/backend pytest -c apps/backend/pyproject.toml \
  apps/backend/tests/test_vipps_mt_conformance_runner.py -q
```

It covers the complete scenario sequence, duplicate provider keys, concurrent
commands, response loss, interrupted evidence writes, blocked prerequisites,
immutable intent conflicts, missing opt-in/configuration and secret redaction.
These tests make no requests to MT or any other third-party target.
