# RF-1086 Live Release Gate

Status: HITL release checklist  
Last updated: 2026-07-15
Target issue: #81  
Blockers resolved: #76 real payment collection (closed), #80 code evidence decision (closed)

This checklist must pass before Talli can enable live RF-1086 submission. It does
not enable production by itself.

## Live Scope

Allowed candidate scope:

- stiftelse/no-activity RF-1086 only;
- no purchase/sale/dividend event types in live filing;
- one share class;
- Norwegian shareholders only;
- owner-managed direct filing with explicit authority confirmation.

Excluded live scope:

- `kjop=K`
- `salg=S`
- `utbytte=U`
- foreign shareholders;
- multiple share classes;
- correction/replacement submissions not tested in authority flow;
- any case with readiness hard blocks, review hard blocks, or filing override blocks.

## Release Evidence

| Gate | Evidence required | Current status |
| --- | --- | --- |
| Authority access | Maskinporten/Altinn/system-user or equivalent flow tested for Talli organization and supported company | **Done in TT02 2026-07-14** — system-user token issued for Tenor org 310279617 with RF-1086 scope |
| Test submission | Test-environment RF-1086 hovedskjema, underskjema, bekreft, dokumenter/feedback retrieval recorded | **Done 2026-07-14** — accepted no-activity filing and two archived documents; `evidence/rf1086-tt02-2026-07-14.md` |
| Live scope | K/S/U excluded, stiftelse/no-activity only | Done in #80 |
| Billing | Real subscription/payment/filing-package gate implemented and test charged/refunded | Implemented in #76 (`productionBillingGate` + payment/refund workflow, #76 closed); live test charge/refund evidence still to attach |
| Security | Fresh MFA/step-up, human security review, production credential gate | Step-up (#73) and RLS/storage audit (#74) implemented and closed; human security review signoff pending |
| Authority confirmation | Owner confirms authority for obligation/company before submission | Implemented as model/UI gate; live flow pending |
| Final preview confirmation | Owner confirms final preview before API calls | Implemented as submission state; live flow pending |
| Idempotency | Endpoint/body hash/idempotency key persisted for each authority call | Implemented and exercised in TT02; resumable journal was persisted before each POST |
| Feedback/receipt archive | Official references, feedback document ids, receipt id persisted | TT02 delivery/dialog/transmission refs and two archive-document hashes recorded; runtime Supabase row still pending |
| Human signoff | Named reviewer signs production release decision | Pending (`rf1086_authority` launch signoff) |
| Production adapter | Real RF-1086 transport implementation; simulation must never satisfy this row | **Implemented, disabled** (`currentAuthorityAdapterCapabilities`); test-only CLI refuses production |
| Exact pilot entitlement | Operator-approved company/user/year/obligation/profile interval | Implemented; no entitlement is active by default |
| Immutable production approval | Exact payload/document hashes, adapter version and fresh owner AAL2 | Implemented; approval and Send are separate |
| Durable production journal | Append-only prepared/succeeded/unknown events and stable UUID idempotency keys | Implemented; ambiguous writes quarantine instead of retrying |

Code and evidence gate anchors:

- `buildFilingReleaseGates` requires accepted `authority_test_runs` evidence
  with receipt and archive refs for `aksjonaerregisteroppgaven`.
- `buildFilingReleaseGates` requires approved `launch_signoffs` key
  `rf1086_authority` with reviewer, date, evidence link, and decision.
- `buildFilingReleaseGates` independently requires an implemented and enabled
  production adapter. The legacy `TALLI_ENABLE_RF1086_PRODUCTION_ADAPTER`
  environment flag cannot route production to the simulation adapter. The only
  live switch is `TALLI_RF1086_PRODUCTION_ENABLED=true` with complete production-
  only inline secret configuration.
- `tests/rf1086_tt02_evidence.test.mjs` checks that accepted evidence has the
  required references/hashes and contains no token, private key, raw XML, or
  synthetic personal identifier.

## Required Test Run

Before release signoff:

```bash
uv run python -m unittest tests.test_rf1086 tests.test_rf1086_submission tests.test_submission_and_billing
npm run test:rf1086:submission
npm run test:security
npm run test:supabase
npm run test:backup-restore
```

## Code Gate Verification (2026-06-27)

Latest run of the code-side release evidence (all green):

| Suite | Result |
| --- | --- |
| `uv run python -m unittest tests.test_rf1086 tests.test_rf1086_submission tests.test_submission_and_billing` | 25 passed |
| `npm run test:rf1086:submission` (bridge; `TALLI_PYTHON_BIN=.venv/bin/python`) | 7 passed |
| `npm run test:security` | 4 passed |
| `npm run test:filing-release-gate` | 3 passed |
| `npm run test:backup-restore` | 4 passed |

`npm run test:supabase` requires Supabase env and is run in an environment with
credentials. This code-gate verification proves the deterministic logic is release-ready;
it does **not** substitute for the external authority access, test submission, and human
release signoff rows above, which keep production disabled.

## Release Decision Template

```text
Reviewer:
Date:
Environment:
Authority test evidence link:
Billing evidence link:
Security review link:
Restore test link:
Supported live scope:
Excluded live scope:
Decision: approve / reject / defer
Notes:
```

## Fail-Closed Rule

If any gate is pending, stale, or unclear, production RF-1086 submission remains
disabled. Talli may still provide simulation, XML export, archive export, and
support-boundary guidance.

The operator procedure for the first hand-held filing, unknown-outcome quarantine,
kill switch, evidence closeout, and correction boundary is in
[`rf1086-production-pilot-runbook.md`](rf1086-production-pilot-runbook.md).
