# Production Launch Rehearsal

Status: local rehearsal passed; production launch remains blocked on named human and deployed-environment evidence
Last updated: 2026-07-14
Blocks: #88, live authority filing, and the corporate-document feature remain blocked until their named external gates are evidenced

This runbook is the repeatable pre-launch rehearsal for Talli. It does not
permit live direct filing. It proves the local product gates and documents the
remaining authority/HITL blockers.

## Latest Rehearsal Run (2026-07-14)

Code-under-test commit:
`aa3afaf5bd3bd7e100e108b74e2a8eb03354fd4c` (`fix: harden corporate decision accounting boundary`).

The local automated command set completed as follows:

| Command | Result |
| --- | --- |
| `uv run python -m unittest discover -s tests -p 'test_*.py'` | exit 0 — 68 tests, 0 failures |
| `npm run test:launch-rehearsal` | exit 0 — every chained suite passed; corporate suite included a fresh PostgreSQL 16 migration/RPC rehearsal |
| `npm run test:web` | exit 0 — 4 tests, 0 failures |
| `npm run test:supabase` | exit 0 with 1 intentional skip — configured Supabase URL/keys or usable `DATABASE_URL` were absent, so deployed authenticated RLS/storage is still pending |
| `npm run typecheck` | exit 0 |
| `npm run build` | exit 0 — Next.js 16.2.9 production build, 18 static pages generated and the route table completed |
| `npm audit --audit-level=high` | exit 0 — 0 vulnerabilities |

One company-tax-return XML test intentionally skipped official XSD validation
because the pinned official XSD bundle was not supplied to this workspace. This
is not counted as a pass and remains part of the authority/schema evidence gate.

This proves the local automated product, filing-simulation, security, billing,
copy, corporate-lifecycle, and policy guards are green on the tested commit. It
does **not** prove deployed tenant isolation, live authority integration,
Norwegian legal/accounting approval, or restore readiness. The launch state
therefore stays `production_disabled`, and
`TALLI_CORPORATE_DOCUMENTS_ENABLED=false` remains unchanged.

Detailed corporate artifact evidence, PDF hashes, renderer versions, and the
explicitly pending external gates are recorded in
`docs/launch/evidence/corporate-document-local-rehearsal.md`.

## Automated Rehearsal Command

Run:

```bash
npm run test:launch-rehearsal
npm run test:web
npm run test:supabase
npm run typecheck
npm run build
npm audit --audit-level=high
```

The rehearsal command covers:

- onboarding/opening balance;
- documents and archive metadata;
- bank import/reconciliation and manual journal;
- holding actions;
- annual data and annual readiness;
- RF-1086 preview/submission simulation;
- annual accounts payload;
- company tax return payload;
- reviewer workflow;
- billing/refund/cancellation/operator support;
- deadlines;
- archive and backup/restore;
- security step-up;
- corporate document generation, canonical hashes, immutable lifecycle,
  database-enforced persisted facts, owner-attested signed-copy handling,
  declaration/payable accounting, payment matching, period locks, and archive
  integrity;
- filing release gates;
- launch copy, launch signoff, and legal policy guards.

## Manual Rehearsal Checklist

| Area | Evidence | Current status |
| --- | --- | --- |
| Company setup | `npm run test:opening` | Automated |
| Documents | `npm run test:documents`, `npm run test:archive` | Automated metadata/archive coverage |
| Bank/import/manual entries | `npm run test:bank`, `npm run test:manual-journal` | Automated |
| Holding actions | share/dividend/loan/tax-settlement tests | Automated |
| Annual data/readiness | `npm run test:annual-data`, `npm run test:annual-readiness` | Automated |
| Filing previews/submissions | RF-1086 simulation, annual accounts payload, company tax return payload | Automated simulation/payload only |
| Review | `npm run test:review` | Automated |
| Billing/refund | `npm run test:billing` | Automated test-mode provider only |
| Cancellation/retention | `npm run test:cancellation` | Automated retained-deletion state |
| Operator support | `npm run test:operator-support` | Automated read-only summary |
| Backup/restore | `npm run test:backup-restore` | Automated fixture restore; real restore target still needs reviewer record |
| Security | `npm run test:security` | Automated step-up gate |
| Corporate documents | `npm run test:corporate-documents`, `npm run test:corporate-decision-workflow`, `npm run test:owner-dividend-payment` | Local deterministic and fresh-PostgreSQL evidence passed; six external gates in `docs/launch/corporate-document-release-gate.md` remain pending and the feature flag stays off |
| Launch copy/legal | `npm run test:launch-copy`, `npm run test:launch-signoff`, `npm run test:legal-policy` | Automated copy/policy/signoff guard; legal signoff pending |

## Filing Gate State

RF-1086, årsregnskap, and skattemelding must each show one of:

- `production_ready` from `buildFilingReleaseGates`, with authority, billing,
  accepted authority test evidence, receipt/archive refs, security, credential,
  readiness, and filing-specific launch signoff gates passed; or
- `production_disabled` with public copy restricted to preview/simulation.

Current launch state is `production_disabled` until official authority
test-environment evidence and named human release signoff exist.

The corporate-document workflow has a separate fail-closed release gate. Local
evidence is complete for this rehearsal, but the templates, accounting policy,
PDF goldens, deployed RLS/private storage, production restore, and corporate
public copy all still require named reviewers and immutable evidence before the
feature flag may be enabled.

## Required Human Signoffs

Record reviewer, date, evidence link, decision. The machine-checkable model is
`app/lib/launch-signoff.ts`; it blocks launch unless every required decision is
approved with reviewer, date, evidence link, and decision text. The
`security_restore` signoff must be 30 days old or newer. Operator admins record
these decisions in `launch_signoffs`; active operators can read the resulting
gate state in the app operator section.

| Decision | Reviewer | Date | Evidence link | Decision |
| --- | --- | --- | --- | --- |
| Launch/legal/name/public copy | Pending | Pending | `docs/launch/talli-clearance-evidence-register.md` | Pending |
| Legal/privacy/DPA/retention/incident | Pending | Pending | `docs/legal/` | Pending |
| Security/restore | Pending | Pending | `docs/security/` and restore command output | Pending |
| Billing/refund | Pending | Pending | Billing provider/test-mode evidence | Pending |
| RF-1086 authority filing | Pending | Pending | `docs/filing/rf1086-live-release-gate.md` | Pending |
| Årsregnskap authority filing | Pending | Pending | `docs/filing/annual-accounts-authority-map.md` | Pending |
| Skattemelding authority filing | Pending | Pending | `docs/filing/company-tax-return-authority-map.md` | Pending |
| Support/rollback | Pending | Pending | Operator dashboard and backup/restore evidence | Pending |

## Founder Pre-Launch Attestations (2026-06-24, Kristian Elmer)

Scope: private/limited pre-launch with direct filing in preview/simulation mode
(`production_disabled`). The three authority filing signoffs (RF-1086,
årsregnskap, skattemelding) are intentionally NOT addressed here; they remain
blocked on official authority test-environment onboarding and are required only
for live direct filing (full public launch).

Operational signoffs attested by the founder for the pre-launch:

- `billing_refund` — approved; see `docs/billing/founder-pricing-gate.md`
  (live charging OFF, Vipps MobilePay test mode).
- `support_rollback` — approved; support boundary per
  `docs/legal/terms-of-service-draft.md` (no legal/tax advice; needs-accountant
  cases blocked/escalated/exported); rollback via Vercel previous-deployment
  rollback for releases and the backup/restore runbook for data.
- `security_restore` — PENDING a real restore test against the deployed Supabase,
  recorded with date/target/operator/result (must be 30 days old or newer). See
  `docs/security/backup-restore-runbook.md`.

Remaining step for each: an admin operator records the signoff in
`launch_signoffs` via the app operator form. These attestations are the
version-controlled evidence; the machine gate flips only when recorded at runtime.

## Stop Conditions

Stop rehearsal and keep public copy restricted if:

- any automated command fails;
- restore evidence is older than 30 days;
- any filing gate is not `production_ready`;
- any row in `docs/launch/corporate-document-release-gate.md` is pending;
- public copy claims direct live filing without authority receipt evidence;
- legal/security/billing/authority reviewer signoff is missing.
