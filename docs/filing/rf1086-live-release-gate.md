# RF-1086 Live Release Gate

Status: HITL release checklist  
Last updated: 2026-06-16  
Target issue: #81  
Blocked by: #76 real payment collection, #80 code evidence decision

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
| Authority access | Maskinporten/Altinn/system-user or equivalent flow tested for Talli organization and supported company | Pending |
| Test submission | Test-environment RF-1086 hovedskjema, underskjema, bekreft, dokumenter/feedback retrieval recorded | Pending |
| Live scope | K/S/U excluded, stiftelse/no-activity only | Done in #80 |
| Billing | Real subscription/payment/filing-package gate implemented and test charged/refunded | Pending #76 |
| Security | Fresh MFA/step-up, human security review, production credential gate | Step-up implemented; human review pending |
| Authority confirmation | Owner confirms authority for obligation/company before submission | Implemented as model/UI gate; live flow pending |
| Final preview confirmation | Owner confirms final preview before API calls | Implemented as submission state; live flow pending |
| Idempotency | Endpoint/body hash/idempotency key persisted for each authority call | Implemented in submission model/tests |
| Feedback/receipt archive | Official references, feedback document ids, receipt id persisted | Simulation seam implemented; official evidence pending |
| Human signoff | Named reviewer signs production release decision | Pending |

## Required Test Run

Before release signoff:

```bash
uv run python -m unittest tests.test_rf1086 tests.test_rf1086_submission tests.test_submission_and_billing
npm run test:rf1086:submission
npm run test:security
npm run test:supabase
npm run test:backup-restore
```

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
