# RF-1086 Live Release Gate

Status: HITL release checklist  
Last updated: 2026-07-13
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
| Authority access | Maskinporten/Altinn/system-user or equivalent flow tested for Talli organization and supported company | Pass in Test: DM-8 access, system registration, customer approval, request status `Accepted`, and a system-user-bound token for company `310279617` were confirmed on 2026-07-13. Production access is not implied. See `authority-access-evidence-register.md`. |
| Test submission | Test-environment RF-1086 hovedskjema, underskjema, bekreft, dokumenter/feedback retrieval recorded | Pending |
| Live scope | K/S/U excluded, stiftelse/no-activity only | Done in #80 |
| Billing | Real subscription/payment/filing-package gate implemented and test charged/refunded | Pending #76 |
| Security | Fresh MFA/step-up, human security review, production credential gate | Step-up implemented; human review pending |
| Authority confirmation | Owner confirms authority for obligation/company before submission | Implemented as model/UI gate; live flow pending |
| Final preview confirmation | Owner confirms final preview before API calls | Implemented as submission state; live flow pending |
| Idempotency | Endpoint/body hash/idempotency key persisted for each authority call | Implemented in submission model/tests |
| Authority HTTP contract | Fixed hosts, five official paths, bounded transport, strict response validation, and safe per-call idempotency | Implemented and contract-tested; durable database journal and guarded server-only production worker are implemented through `7af781a`; no hosted operator trigger or web route is enabled |
| Crash-safe orchestration | Prepared/sent/accepted journal revisions, XML retry safety, non-idempotent confirmation reconciliation, checkpoint integrity, fresh release-state loading, and mutation sealing during transport | Implemented/tested through `7af781a`; the owner-authenticated workspace client, narrow control client, and service-role journal/lease client remain separated. A 120-second service-only lease blocks concurrent workers and temporarily seals every current release-gate source until the one provider operation finishes. Hosted migration deployment and operational wiring are pending |
| TT02 operator boundary | Test-only system-user token, private atomic file journal, exact customer/year lock, one call per run, explicit final confirmation | Implemented and tested at `2d0822a`; the candidate preview was inspected locally on 2026-07-13 with `nextOperation` equal to `hovedskjema`. No provider write has occurred because the synthetic shareholder allocation still requires explicit acceptance |
| Feedback/receipt archive | Official references, submitted XML, authorized Dialogporten attachment ids, receipt/feedback files, and revisioned private manifest persisted | Fixed-host Dialogporten client and immutable local archive implemented/tested; `digdir:dialogporten` test scope and official artifacts pending |
| Human signoff | Named reviewer signs production release decision | Pending |

Code gate anchors:

- `buildFilingReleaseGates` requires accepted `authority_test_runs` evidence
  with receipt and archive refs for `aksjonaerregisteroppgaven`.
- `buildFilingReleaseGates` requires approved `launch_signoffs` key
  `rf1086_authority` with reviewer, date, evidence link, and decision.

The production worker never trusts the cached readiness snapshot. It reloads
the current tenant rows through the authenticated owner's RLS context, reads the
global launch signoff through a separate narrow control client, audits before
token issuance, reloads and audits again before transport, and limits each
invocation to one authority call. The service role is reserved for the atomic
checkpoint journal and the short-lived production lease. While that lease is
active, database triggers reject changes to the preview, company/year source
rows, review/override state, authority evidence, actor security state, and the
RF-1086 launch signoff. The worker attempts release on both success and failure;
the lease expires automatically 120 seconds after acquisition if a worker
crashes or release itself fails.

## First TT02 Write Gate

The approved system request does not itself authorize the synthetic filing
contents. Before the first provider write, the operator must record this exact
acceptance in the controlled session:

```text
Approve RF-1086 TT02: one synthetic shareholder owns all 500 shares, no 2025 transactions.
```

That acceptance authorizes only the first guarded TT02 progression. When the
journal later reports `bekreft`, confirmation must be authorized separately.

## Required Test Run

Before release signoff:

```bash
uv run python -m unittest tests.test_rf1086 tests.test_rf1086_submission tests.test_submission_and_billing
npm run test:rf1086:submission
npm run test:rf1086:authority
npm run test:rf1086:orchestration
npm run test:rf1086:archive
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
