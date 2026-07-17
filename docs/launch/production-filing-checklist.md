# First production filing checklist

Status: production filing is off
Scope: one controlled RF-1086 production pilot

Use this page to track the work. Follow each link for the full instructions.
Complete the rows in order. Do not mark a row `Passed` without an evidence link,
a named reviewer, and a review date.

Allowed status values: `Not started`, `In progress`, `Blocked`, `Passed`.

<!-- markdownlint-disable-next-line MD013 -->
This checklist does not unlock public self-service filing, corrections, expanded RF-1086 profiles, annual accounts, or company tax returns.

> If any row is not `Passed`, stop here. Do not enable production filing.

| # | Stage | Owner | Status | Evidence | Reviewer and date |
| --- | --- | --- | --- | --- | --- |
| 1 | [Approve the legal pack](./production-filing-action-guide.md#approve-the-legal-pack) — confirm `legal_policy_pack` and `launch_legal_name_public_copy`. | Founder + legal + security | Not started | — | — |
| 2 | [Verify hosted tenant isolation and private storage](./production-filing-action-guide.md#verify-hosted-tenant-isolation-and-private-storage). | Security reviewer | Not started | — | — |
| 3 | [Complete a fresh production backup and restore rehearsal](./production-filing-action-guide.md#complete-a-fresh-production-backup-and-restore-rehearsal) — record `security_restore`. | Security reviewer + operator | Not started | — | — |
| 4 | [Verify monitoring, incident response, and rollback](./production-filing-action-guide.md#verify-monitoring-incident-response-and-rollback) — record `support_rollback`. | Operator + on-call observer | Not started | — | — |
| 5 | [Select an eligible pilot company](./production-filing-action-guide.md#select-an-eligible-pilot-company) — only `rf1086_no_activity_v1`. | Founder + accounting reviewer | Not started | — | — |
| 6 | [Capture Business Terms and DPA acceptance](./production-filing-action-guide.md#capture-business-terms-and-dpa-acceptance). | Customer representative + founder | Not started | — | — |
| 7 | [Compare Talli and Fiken](./production-filing-action-guide.md#compare-talli-and-fiken). | Founder + accounting reviewer | Not started | — | — |
| 8 | [Verify the production Systemregister callback](./production-filing-action-guide.md#verify-the-production-systemregister-callback). | Founder/operator | Not started | — | — |
| 9 | [Complete Systembruker approval and preflight](./production-filing-action-guide.md#complete-systembruker-approval-and-preflight). Production authority permission is required. Accepted authority-test evidence is required. | Customer owner + founder/operator | Not started | — | — |
| 10 | [Record the required launch signoffs](./production-filing-action-guide.md#record-the-required-launch-signoffs) — `launch_legal_name_public_copy`, `legal_policy_pack`, `security_restore`, `billing_refund`, `support_rollback`, `rf1086_authority`, and `founder_production_go_live`. | Named reviewers + founder | Not started | — | — |
| 11 | [Create the pilot entitlement and billing path](./production-filing-action-guide.md#create-the-pilot-entitlement-and-billing-path). An active exact pilot entitlement is required. Billing or an exact billing exemption is required. Record `billing_exempt=true` only for the approved exact exemption. | Founder/operator | Not started | — | — |
| 12 | [Capture the owner's final approval](./production-filing-action-guide.md#capture-the-owners-final-approval). Fresh AAL2 is required. Filing readiness is required. | Customer owner | Not started | — | — |
| 13 | [Run the production filing window](./production-filing-action-guide.md#run-the-production-filing-window). The production adapter must be implemented and enabled. | Founder/operator + customer owner + observer | Not started | — | — |
| 14 | [Save the final result and closeout evidence](./production-filing-action-guide.md#save-the-final-result-and-closeout-evidence). | Founder/operator + observer | Not started | — | — |
| 15 | [Make the post-pilot decision](./production-filing-action-guide.md#make-the-post-pilot-decision). | Founder + named reviewers | Not started | — | — |

## Ready-to-file check

- [ ] Every row is `Passed`.
- [ ] `security_restore` is no more than 30 days old.
- [ ] The exact entitlement is active.
- [ ] Owner AAL2 and approval are fresh.
- [ ] Both switches are false before the approved window.
- [ ] The observer, kill switch, and alternative route are ready.
- [ ] `founder_production_go_live` was recorded after the supporting evidence.

Only the named founder/operator may start the approved filing window.
