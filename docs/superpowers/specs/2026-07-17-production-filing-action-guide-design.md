# Production Filing Action Guide Design

Status: approved design
Date: 2026-07-17
Scope: first controlled RF-1086 production pilot

## Purpose

Turn Talli's production-filing release gates into instructions a founder/operator
can follow without reconstructing the process from code, evidence registers, and
technical runbooks. The documentation must make it obvious what to do next, what
evidence to save, who must approve it, and when work must stop.

The guide does not authorize a production filing and does not weaken any existing
release gate. The source of truth remains the fail-closed runtime gate and its
underlying evidence.

## Audience

- Founder/operator coordinating the first filing.
- Customer owner approving the exact filing.
- Legal, security, accounting, and authority reviewers.
- On-call observer supervising the filing window.

## Deliverables

Create two linked documents:

1. `docs/launch/production-filing-checklist.md` — a one-page control sheet for
   tracking sequence, owner, status, and evidence.
2. `docs/launch/production-filing-action-guide.md` — the detailed operating guide
   for completing and evidencing every checklist stage.

The short checklist links to the matching detailed section. The detailed guide
links back to the checklist and to existing authoritative runbooks rather than
duplicating low-level recovery procedures.

## Guide Structure

Every detailed stage uses the same template:

1. Objective.
2. Responsible roles.
3. Preconditions.
4. Exact actions with checkboxes.
5. Evidence to retain.
6. Pass criteria.
7. Stop conditions.
8. Runtime signoff or record.
9. Capability unlocked.
10. Next stage.

The checklist uses one row per stage with these fields:

- number and stage;
- accountable owner;
- status (`Not started`, `In progress`, `Blocked`, or `Passed`);
- evidence link;
- reviewer and review date; and
- detailed-guide link.

## Ordered Stages

The documentation covers these stages in order:

1. Approve the legal pack.
2. Verify hosted tenant isolation and private storage.
3. Complete a fresh production backup/restore rehearsal.
4. Verify monitoring, incident response, and rollback readiness.
5. Select an eligible `rf1086_no_activity_v1` pilot company.
6. Capture valid Business Terms and DPA acceptance.
7. Compare Talli and Fiken outputs and resolve discrepancies.
8. Verify the production Systemregister callback.
9. Complete customer Systembruker approval and delegated preflight.
10. Record the required launch signoffs.
11. Create the exact time-bounded pilot entitlement and billing path.
12. Capture the owner's fresh-AAL2 immutable preview approval.
13. Conduct the founder-assisted production filing window.
14. Archive the official receipt, final feedback, and closeout evidence.
15. Decide whether to stop, repeat a controlled pilot, or prepare cohort
    expansion.

## Safety Model

The guide preserves these fail-closed rules:

- No named-company data enters Talli before approved legal and hosted-security
  evidence is current.
- Unsupported company facts stop the pilot; a disclaimer cannot override scope.
- A statutory filing is never used as a connectivity test.
- `TALLI_AUTHORITY_OPS_ENABLED` is enabled only for the fixed callback maintenance
  operation and returned to `false` immediately.
- `TALLI_RF1086_PRODUCTION_ENABLED` is enabled only for the separately approved
  filing window and returned to `false` at closeout.
- No production entitlement exists before accepted delegation and preflight.
- The owner approves the exact preview and hashes using fresh trusted AAL2.
- A transport reference is not final acceptance.
- An unknown write outcome is quarantined and never blindly retried.
- Secrets, tokens, private keys, raw personal data, and raw filing XML are never
  copied into evidence records.

## Evidence Model

Each stage identifies a durable, sanitized evidence artifact. Evidence records
must include the deployed Git SHA or environment where relevant, named reviewer,
review date, evidence reference, decision, and expiry where applicable.

The guide distinguishes three kinds of proof:

- automated proof, such as CI and deterministic tests;
- hosted runtime proof, such as RLS, private storage, restore, and callback
  verification; and
- human approval, such as legal, security, accounting, authority, and founder
  decisions.

One category cannot substitute for another. In particular, automated tests do
not satisfy a named human signoff.

## Runtime Gate Mapping

The guide maps actions to the existing `launch_signoffs` keys:

- `launch_legal_name_public_copy`;
- `legal_policy_pack`;
- `security_restore`;
- `billing_refund`, unless the exact pilot is billing-exempt;
- `support_rollback`;
- `rf1086_authority`; and
- `founder_production_go_live`.

It also maps the case-specific requirements enforced outside those signoffs:
production authority permission, accepted authority-test evidence, fresh AAL2,
exact pilot entitlement, filing readiness, billing or billing exemption, and an
implemented and enabled production adapter.

## Scope Boundary

This guide unlocks at most one founder-assisted RF-1086 production pilot for the
strict no-activity profile. It does not unlock public self-service filing,
corrections, expanded RF-1086 profiles, annual accounts, or company tax returns.
Those obligations require separate authority evidence, signoffs, adapter states,
and pilot decisions.

## Verification

Documentation review must confirm:

- every runtime gate appears in the checklist and detailed guide;
- every stage has objective pass and stop criteria;
- links resolve to current repository sources;
- the switch and unknown-outcome instructions match the controlled pilot runbook;
- the legal guide states that the pack is pending professional approval;
- the free pilot path uses an exact `billing_exempt=true` entitlement rather than
  implying that billing controls are removed; and
- no wording represents production filing as currently enabled.
