# Production Launch Rehearsal

Status: prepared for final HITL rehearsal  
Last updated: 2026-06-20  
Blocks: #88 remains open until named reviewer signoff and authority test evidence exist

This runbook is the repeatable pre-launch rehearsal for Talli. It does not
permit live direct filing. It proves the local product gates and documents the
remaining authority/HITL blockers.

## Automated Rehearsal Command

Run:

```bash
npm run test:launch-rehearsal
npm run typecheck
npm run build
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
| Launch copy/legal | `npm run test:launch-copy`, `npm run test:launch-signoff`, `npm run test:legal-policy` | Automated copy/policy/signoff guard; legal signoff pending |

## Filing Gate State

RF-1086, årsregnskap, and skattemelding must each show one of:

- `production_ready` from `buildFilingReleaseGates`, with authority, billing,
  accepted authority test evidence, receipt/archive refs, security, credential,
  readiness, and filing-specific launch signoff gates passed; or
- `production_disabled` with public copy restricted to preview/simulation.

Current launch state is `production_disabled` until official authority
test-environment evidence and named human release signoff exist.

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
- public copy claims direct live filing without authority receipt evidence;
- legal/security/billing/authority reviewer signoff is missing.
