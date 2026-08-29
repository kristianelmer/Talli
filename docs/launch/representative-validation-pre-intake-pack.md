# Representative Validation Pre-Intake Pack

Status: blank, no-contact preparation only; #197 is unclaimed and intake is
blocked

Owning route: #196 prepares the gate; #197 may be claimed only after #196 closes

Date: 2026-08-29

## Purpose and Hard Boundary

This pack makes the founder-approved 2+8 validation design executable once every
entry gate is actually approved. It is not participant terms, a DPA, a privacy
approval, a recruitment list, a data store or validation evidence.

Do not put a person's name, email, phone number, organization number, company
name, bank, account, document, filing, ledger, support message, consent record,
authority record or other real-company material in Git, GitHub issues, chat or
these templates. Filled identity, authority, agreement, consent, withdrawal,
export, deletion and incident records belong in a named human-controlled
protected store selected and approved before intake.

No recruitment, outreach, named-company intake, provider action, production
filing, deployment, charge or public launch is authorized by this pack.

## Gate Board

Every row must have a named human owner, exact evidence link or digest, approval
date, review/expiry date and `approved` decision before the dependent action.
`Prepared`, `tested locally`, `drafted`, or `sent` is not `approved`.

| Gate | Current state | Opens only when |
| --- | --- | --- |
| #196 public recruitment/privacy lane | **Blocked — issue open / ready-for-human** | Exact notice/consent and all #196 human gates are approved; immutable evidence is current; issue is genuinely closed. |
| Lawful recruitment channel | **Design approved; action not authorized** | The exact opt-in/public/community/partner route is selected for this run, channel copy is approved and the outreach action is separately authorized. No named cold outreach. |
| Participant information and terms | **Draft/pending** | Plain-language validation purpose, scope, confidentiality, independence, support, withdrawal, export, deletion, retention, incident, exit and no-accounting-service boundaries are versioned and approved. |
| Business Terms and DPA | **Draft/pending human review** | Current versions/digests are approved and an authorized company representative can accept them with immutable evidence. |
| Controller/processor and privacy basis | **Pending** | Purpose-by-purpose roles, bases, data categories, recipients, rights and retention are approved for the validation program and the exact deployed stack. |
| Temporary pilot observation mode | **Design approved; implementation/activation blocked** | The exact normal product is proven behaviorally identical with observation on/off; the only difference is a bounded post-outcome log write. Server-side named pilot entitlement, approved run ID, automatic expiry, protected case-code evidence and launch-time `off` proof are implemented and reviewed. A URL, browser state or client field cannot enable it. |
| Protected participant register | **Not selected** | A named human-controlled store with least privilege, MFA, audit, backup, retention and deletion is approved. Git/issues/chat are forbidden stores. |
| Hosted tenant isolation/private storage | **Pending current target evidence** | Owner/member/outsider tests and private-object access checks pass against the exact target and are signed by the security reviewer. |
| MFA and privileged/operator access | **Pending current target evidence** | Enrollment, recovery, fresh step-up, least-privilege operator access and audit are rehearsed and approved. |
| Backup and restore | **Pending current target evidence** | An isolated row-and-object restore with matching hashes passes; evidence is no older than 30 days. |
| Logging, monitoring and incident response | **Pending current target evidence** | Logs are redacted, access-controlled and retained as approved; alert, contact, containment, notification and rollback paths are rehearsed. |
| Export, withdrawal and deletion | **Draft/local behavior only** | Participant-facing expectations, legal holds, export contents, response owners, deletion verification and backup expiry are approved and rehearsed. |
| Bank tranche | **Blocked by #189 external A9** | One provider configuration passes role/licence, coverage, cost, contract/privacy/security/reliability/exit and representative evidence; activation is separately approved. |
| Filing and other capability tranches | **Blocked by their owning route gates** | Each owning issue and its credential/data/production/human gates are green for the exact immutable release. |
| Spend | **Not authorized** | Kristian approves provider, amount/estimate, recurrence or usage basis and a practical cheaper/free alternative before the action. |

## Packet to Approve Before Recruitment

The participant-facing packet must be one pinned set. Keep filled copies in the
protected register, not this repository.

1. Validation description: Talli is deterministic owner-controlled software;
   the participant makes every accounting and filing decision.
2. Exact supported/unsupported boundary and stop/escalation behavior.
3. What the participant will do in the historical and/or current-year flow.
4. What evidence is requested, why, and which items are optional or mandatory.
5. Business Terms, DPA, privacy information and validation-specific purpose.
6. Confidentiality and publication rule: no identifiable case is published
   without a separate explicit basis and approval.
7. Support boundary: help with the software, never customer-specific accounting,
   tax or legal judgment.
8. Withdrawal, export, deletion, retention/legal-hold and incident contacts.
9. Provider/filing actions that are disabled until their separate gates pass.
10. No-fee validation statement and any later commercial separation.

## Protected Register Schema

The approved protected store may record the following. This is a schema, not
permission to collect it:

| Record | Minimum fields | Access |
| --- | --- | --- |
| Participant | internal case code, identity/contact, company, eligibility result, recruitment source, status | Named validation operator; identity separated from working evidence where practical. |
| Authority | signer identity/role, authority basis/evidence, company, scope, date, reviewer | Named validation operator and legal reviewer. |
| Agreement | exact terms/DPA/privacy/participant-info versions and digests, signer, action, timestamp | Append-only; named validation operator and legal reviewer. |
| Data receipt | case code, requested category, received item manifest/digests, purpose, store, access, retention class | No source file in Git/issues/chat. |
| Withdrawal/export/delete | request, timestamp, scope, owner, legal hold, export receipt, deletion/backup result, closure | Named validation operator plus privacy/security reviewer as needed. |
| Incident | severity, affected case codes/data, containment, notification decision, actions, closure | Restricted incident store; no incident details in public issue comments. |

## Pseudonymous Repository Evidence Index

Only after #196 closes and #197 is properly claimed may `docs/validation/**`
contain a redacted index. Use case codes `V-01` through `V-12`; never include the
identity-key mapping. A future index may contain only:

- case code and coarse `historical` / `current-year` tranche;
- bounded accepted-pattern codes and sanitized near-boundary code;
- immutable release/evidence digests and test dates;
- bounded pass/fail/blocked states;
- intervention count and duration totals;
- bounded difference classification and materiality;
- rerun/closure evidence digest; and
- gate expiry or recheck date.

Do not include free text copied from participants, company facts, exact bank,
exact dates/amounts, filenames, document text, filing payloads, receipts, support
messages or combinations that make a company reasonably identifiable.

## Bounded Working Templates

### Case readiness

| Field | Allowed value |
| --- | --- |
| Case code | `V-01` … `V-12` |
| Tranche | `historical`, `current-year`, `sanitized-rejection` |
| Eligibility | `definitive-supported`, `blocked`, `clarify` |
| Entry gates | `green`, `blocked` |
| Release digest pinned | `yes`, `no` |
| Participant authority/agreements | `verified`, `blocked` |
| Data receipt | `not-started`, `complete`, `withdrawn` |
| Outcome | `not-started`, `passed`, `failed`, `stopped` |
| Observation mode | `off`, `invited-pilot` |
| Pilot entitlement | `verified`, `expired`, `revoked`, `blocked` |
| Approved run ID | bounded non-identifying run code, or `blocked` |

### Difference register

| Field | Allowed value |
| --- | --- |
| Stage | `eligibility`, `reconstruction`, `banking`, `ledger`, `governance`, `filing`, `archive`, `journey` |
| Classification | `talli-defect`, `source-defect`, `presentation-only`, `unresolved-judgment` |
| Materiality | `material`, `non-material`, `unknown` |
| Action | `stop-and-fix`, `correct-source`, `fix-presentation`, `human-escalation`, `rerun` |
| State | `open`, `resolved`, `accepted-with-evidence` |

`unresolved-judgment` and `unknown` always stop the affected acceptance. Talli
staff or agents must not decide the participant's accounting treatment.

### Independence and support log

Record only case code, bounded task code, `completed-without-help` or
`intervention`, intervention reason (`navigation`, `copy`, `technical-failure`,
`evidence-location`, `unsupported-question`), duration in seconds and rerun
result. Store any participant wording outside Git in the protected register.

The final scoreboard requires every critical journey to complete, at least 90%
of core tasks without intervention, median support below 30 minutes per
company-year, zero unexplained material differences or duplicates, and genuine
final outcomes across RF-1086, company tax and annual accounts. These thresholds
measure the completed protected evidence; a blank template cannot pass them.

### Incident / withdrawal / unsupported exit index

Record case code, bounded event type, timestamp rounded as approved, stop state,
protected-record reference and immutable closure digest. Never copy the event
narrative or affected data into the repository.

## Run Order Once Gates Open

1. Freeze the exact release and gate evidence; create the protected register.
2. Obtain authorized acceptance before any named data or upload.
3. Run the two anchors and fix/rerun material defects.
4. Obtain explicit tranche authority before live bank/provider/filing actions.
5. Add the eight varied cases only after anchor evidence capture is stable.
6. Run the six sanitized boundary rejections without real-company material.
7. Reconcile every difference and repeated confusion; extend to 12 when the
   approved saturation rules require it.
8. Record named human conclusions and immutable redacted evidence only after the
   underlying protected records are complete.
9. Before full public launch, prove the observation mode is `off`, every pilot
   entitlement is expired or revoked and no public request can re-enable it.
10. Compare observation `off` and `invited-pilot` on the same representative
    normal actions; product responses, business writes and external calls must be
    identical, with only the bounded observation-log write added.

## Automatic Stop Rules

Stop intake or the affected action immediately if a legal/privacy/DPA/authority,
hosted isolation/storage/MFA/logging/restore, provider, accounting, filing,
security, UX or release gate is red, stale or ambiguous. Preserve read/export,
honor withdrawal/delete obligations, quarantine unknown effects, record the
incident in the protected store, fix the owning capability and rerun. A schedule,
participant expectation or founder desire never converts a failed gate to green.

## Current Honest Result

The blank packet, bounded templates and stop rules are prepared. Every gate board
row keeps its current non-green state. The next permissible action is named
founder/legal/privacy/security review of the exact documents and hosted facts—not
recruitment or data intake.
