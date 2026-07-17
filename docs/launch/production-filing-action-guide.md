# Production filing action guide

Status: production filing is off
Scope: one controlled RF-1086 production pilot

Use this guide one stage at a time. Do not skip a stage. A later stage does not
fix a missing earlier stage.

This guide does not approve a filing. It explains how to collect the proof and
approvals that Talli requires before the first filing.

Start with the [one-page checklist](./production-filing-checklist.md).

> **Stop rule:** If a required check is missing, old, unclear, or rejected, stop here. Do not enable production filing.

> **Evidence rule:** Do not save tokens, private keys, raw personal data, or raw filing XML in an evidence document.

This guide does not unlock public self-service filing, corrections, expanded RF-1086 profiles, annual accounts, or company tax returns.

## Glossary

- **Evidence** is a saved file or link that proves a check was done.
- **Signoff** is a named reviewer's dated decision about saved evidence.
- **AAL2** is a recent sign-in with an approved second factor.
- **Systembruker** is the Altinn access that lets Talli act for one approved company.
- **Pilot entitlement** is a short-lived record that allows one exact pilot case.
- **Unknown outcome** means Talli cannot prove whether the authority received a send.
- **DPA** is the agreement that says how Talli handles personal data for a company.
- **Git SHA** is the exact code version that is deployed.
- **SHA-256** is a check value used to prove that saved bytes have not changed.
- **Immutable** means a saved record cannot be changed later.
- **Delegated preflight** is a read-only check that the exact Systembruker access works.
- **GET** is a read request that must not change authority data.
- **POST** is a send request that may create or change authority data.
- **UUID idempotency key** is a unique send ID used to detect the same request again.
- **Append-only journal** is an event log where old entries cannot be changed.
- **Artifact persistence** means saving a receipt or feedback file so it can be read later.

## Sources used by this guide

- [Legal draft pack](../legal/README.md)
- [Hosted tenant-isolation audit](../security/supabase-rls-storage-audit.md)
- [Backup and restore runbook](../security/backup-restore-runbook.md)
- [Production security baseline](../security/production-security-baseline.md)
- [RF-1086 controlled production pilot runbook](../filing/rf1086-production-pilot-runbook.md)

<a id="approve-the-legal-pack"></a>
## 1. Approve the legal pack

### Objective

Approve the legal pack against the service that is deployed now.

### Responsible roles

The founder owns this stage. A legal reviewer and a security reviewer must review it.

### Preconditions

The legal drafts are complete enough to review. The deployed suppliers and hosted
security facts are known.

### Exact actions

1. Open the [legal draft pack](../legal/README.md).
2. Record the deployed service name and Git SHA.
3. List the current subprocessors.
4. Ask the founder to approve the commercial terms.
5. Ask the founder to approve the subprocessor list.
6. Ask the legal reviewer to approve the acceptance method.
7. Ask the legal reviewer to approve the DPA.
8. Ask the legal reviewer to approve the legal bases.
9. Ask the legal reviewer to approve retention.
10. Ask the legal reviewer to approve liability and remedies.
11. Ask the legal reviewer to approve transfer wording.
12. Ask the legal reviewer to approve governing law.
13. Ask the legal reviewer to approve jurisdiction.
14. Ask the security reviewer to compare the stated measures with hosted facts.
15. Save each reviewer's decision.

### Evidence to retain

Save a sanitized legal review file or durable link. Include the reviewer, review
date, deployed Git SHA, evidence links, decision, and open points. Save the final
document versions and SHA-256 digests. The founder keeps the file. The legal and
security reviewers review it.

### Pass criteria

The founder approved the commercial terms and subprocessors. The legal reviewer
approved acceptance, the DPA, legal bases, retention, liability, transfers,
governing law, and jurisdiction. The security reviewer approved the stated
measures against hosted facts. No draft point remains open.

### Stop conditions

Stop if any draft point is unresolved. Stop if a reviewer is missing. Stop if an
evidence link is missing. The draft pack alone is not approval.

### Runtime signoff or record

Record approved `legal_policy_pack` evidence. Also confirm the existing
`launch_legal_name_public_copy` signoff is approved and current.

### Capability unlocked

This stage allows hosted safety checks to continue. It does not allow named-company
data, billing, an entitlement, or a filing.

### Next stage

Go to [stage 2](#verify-hosted-tenant-isolation-and-private-storage).

<a id="verify-hosted-tenant-isolation-and-private-storage"></a>
## 2. Verify hosted tenant isolation and private storage

### Objective

Prove that one company cannot read another company's hosted data or private files.

### Responsible roles

The security reviewer owns and reviews this stage. An operator runs the checks.

### Preconditions

Stage 1 passed. The exact production deployment and Git SHA are known. Two real
non-customer test accounts exist in separate test companies.

### Exact actions

1. Open the [hosted tenant-isolation audit](../security/supabase-rls-storage-audit.md).
2. Record the production domain.
3. Record the deployed Git SHA.
4. Sign in with the first non-customer account.
5. Try to read the second test company's rows.
6. Try to read the second test company's file metadata.
7. Try to read the second test company's object bytes.
8. Try to create a signed URL for the second test company's object.
9. Try to read the second test company's private filing feedback.
10. Repeat the checks with the accounts reversed.
11. Save sanitized results.

### Evidence to retain

Save a hosted test report or durable link. Include both test case IDs, the deployed
Git SHA, the environment, timestamps, commands, expected denials, actual results,
operator, and reviewer. Do not save account secrets, signed URLs, file bytes, or
private feedback. The security reviewer reviews the report.

### Pass criteria

Every cross-company row, metadata, byte, signed URL, and private-feedback attempt
is denied in both directions. The report names the deployed Git SHA.

### Stop conditions

Stop if any cross-tenant read works. Stop if any private-object access works. Stop
if a signed URL can be made for the other company. Stop if the deployed Git SHA is
unknown.

### Runtime signoff or record

This evidence feeds `security_restore`. It does not approve `security_restore` by
itself.

### Capability unlocked

This stage allows an isolated restore rehearsal. It does not allow named-company
data or production filing.

### Next stage

Go to [stage 3](#complete-a-fresh-production-backup-and-restore-rehearsal).

<a id="complete-a-fresh-production-backup-and-restore-rehearsal"></a>
## 3. Complete a fresh production backup and restore rehearsal

### Objective

Prove that required production data and private objects can be restored safely.

### Responsible roles

The security reviewer owns and reviews this stage. An operator runs the restore.

### Preconditions

Stage 2 passed. An isolated database target and an isolated private-storage target
are ready. Neither target serves live users.

### Exact actions

1. Open the [backup and restore runbook](../security/backup-restore-runbook.md).
2. Record the source environment.
3. Record the isolated restore target.
4. Record the operator.
5. Record the start time.
6. Export the required company-year fixture.
7. Build the backup manifest.
8. Restore the archive to the isolated target.
9. Compare every required row group.
10. Compare each private-object count.
11. Compare each private-object byte size.
12. Compare each private-object SHA-256 hash.
13. Record any missing-object warning.
14. Record the end time.
15. Record the result.

### Evidence to retain

Save a sanitized restore report or durable link. Include the source, isolated
target, operator, start time, end time, row comparison, object counts, byte sizes,
SHA-256 results, warnings, and result. The security reviewer reviews it.

### Pass criteria

The restore uses only isolated targets. All required rows are present. Object
counts, byte sizes, and SHA-256 hashes match. The passing review is no more than
30 days old.

### Stop conditions

Stop if the restore touches live data. Stop if a required row is missing. Stop if
an object count, byte size, or hash differs. Stop if the evidence is over 30 days
old.

### Runtime signoff or record

Record the approved evidence as `security_restore`. Include its review date and
evidence link.

### Capability unlocked

This stage allows hosted safety work to continue. It does not allow named-company
data until stage 4 also passes.

### Next stage

Go to [stage 4](#verify-monitoring-incident-response-and-rollback).

<a id="verify-monitoring-incident-response-and-rollback"></a>
## 4. Verify monitoring, incident response, and rollback

### Objective

Prove that the team can see a problem, stop sends, recover, and use another route.

### Responsible roles

The operator owns this stage. The on-call observer reviews it. The founder approves
the fallback route.

### Preconditions

Stages 1 through 3 passed. Production filing remains off. No live filing is used
for this rehearsal.

### Exact actions

1. Name the on-call owner.
2. Name the filing-window observer.
3. Test each required alert with safe test data.
4. Check that logs omit restricted data.
5. Check that `TALLI_AUTHORITY_OPS_ENABLED=false` is visible after deployment.
6. Check that `TALLI_RF1086_PRODUCTION_ENABLED=false` is visible after deployment.
7. Rehearse the immediate kill switch.
8. Rehearse Vercel rollback to a known deployment.
9. Rehearse database recovery from the isolated proof.
10. Record the authority-approved alternative filing route.
11. Record the support route and deadline.
12. Ask the founder to approve the fallback route.
13. Save the founder's decision.
14. Save the rehearsal result.

### Evidence to retain

Save a monitoring and rollback report or durable link. Include alert results, safe
log samples, switch checks, Vercel rollback proof, database recovery proof, named
owner, named observer, alternative route, support route, and reviewer decision.
Include the founder's fallback-route decision. The on-call observer reviews it.

### Pass criteria

Alerts work. Logs are safe. Both kill switches can be checked and changed. Vercel
rollback works. Database recovery works. An observer and alternative filing route
are named. The founder approved the fallback route.

### Stop conditions

Stop if logs leak restricted data. Stop if no observer exists. Stop if no fallback
exists. Stop if either switch state cannot be verified. Stop if rollback or recovery
cannot be shown.

### Runtime signoff or record

Record the approved evidence as `support_rollback`.

### Capability unlocked

Stages 1 through 4 allow named-company pilot work to start. They do not allow a
production send.

### Next stage

Go to [stage 5](#select-an-eligible-pilot-company).

<a id="select-an-eligible-pilot-company"></a>
## 5. Select an eligible pilot company

### Objective

Choose one company that fits the exact supported pilot profile.

### Responsible roles

The founder owns this stage. The company owner supplies the facts. An accounting
reviewer reviews them.

### Preconditions

Stages 1 through 4 passed. Their evidence is approved and current.

Named-company data must not be uploaded until legal approval and hosted
tenant-isolation, private-storage, and restore evidence are current.

### Exact actions

1. Record the exact legal company.
2. Record the exact owner user.
3. Record the income year.
4. Select only `rf1086_no_activity_v1`.
5. Confirm that the company has one share class.
6. Confirm that every shareholder is Norwegian.
7. Confirm that no share purchase occurred.
8. Confirm that no share sale occurred.
9. Confirm that no dividend occurred.
10. Confirm that this is not a correction.
11. Check for any other unsupported complexity.
12. Ask the company owner to sign the facts.
13. Ask the accounting reviewer to decide eligibility.

### Evidence to retain

Save a signed eligibility review or durable link. Include the company, owner,
income year, profile, each included and excluded fact, reviewer, date, and decision.
Use references instead of raw personal data. The accounting reviewer reviews it.

### Pass criteria

The exact company, owner, year, and `rf1086_no_activity_v1` profile are named. The
company has one share class and only Norwegian shareholders. No purchase, sale,
dividend, correction, or unsupported complexity is present.

### Stop conditions

Stop if an excluded fact is present. Stop if any company fact is uncertain. A
disclaimer cannot override the supported profile.

### Runtime signoff or record

Keep the signed eligibility review in the pilot evidence case.

### Capability unlocked

This stage identifies the only company, owner, year, obligation, and profile that
later approvals may cover.

### Next stage

Go to [stage 6](#capture-business-terms-and-dpa-acceptance).

<a id="capture-business-terms-and-dpa-acceptance"></a>
## 6. Capture Business Terms and DPA acceptance

### Objective

Capture valid acceptance for the exact pilot company.

### Responsible roles

The company owner owns the acceptance. The founder checks the evidence. The legal
reviewer resolves any question about authority or versioning.

### Preconditions

Stage 5 passed. The current approved Business Terms and DPA versions and SHA-256
digests are pinned in the service.

### Exact actions

1. Open the named company's owner workspace.
2. Show the current Business Terms version.
3. Show the current DPA version.
4. Show the statement about authority to bind the company.
5. Ask the authorized representative to accept the Business Terms.
6. Ask the authorized representative to accept the DPA.
7. Check the saved company legal name.
8. Check the saved organization number.
9. Check the saved accepting user.
10. Check both saved versions and SHA-256 digests.
11. Check the saved authority-statement version.
12. Check the saved timestamp and acceptance method.
13. Save the immutable evidence reference.

### Evidence to retain

Retain the immutable agreement acceptance for the named company. Save a durable
reference to it in the pilot case. The founder reviews it. Do not copy raw personal
data into the pilot evidence file.

### Pass criteria

An authorized representative accepted the current pinned Business Terms and DPA
versions. The saved digests match. The acceptance belongs to the named company.

### Stop conditions

Stop if acceptance is missing, stale, fabricated, or made by someone without
authority. Stop if a version or digest differs. Do not backfill acceptance.

### Runtime signoff or record

Use the append-only agreement acceptance record. Do not edit old evidence.

### Capability unlocked

This stage allows the named company to continue through pilot checks. It does not
grant filing authority or an entitlement.

### Next stage

Go to [stage 7](#compare-talli-and-fiken).

<a id="compare-talli-and-fiken"></a>
## 7. Compare Talli and Fiken

### Objective

Find and resolve material differences before authority work begins.

### Responsible roles

The operator makes both outputs. A named accounting reviewer owns the decision.
The founder accepts any written residual risk.

### Preconditions

Stage 6 passed. Talli and Fiken use the same company, period, and source facts.

### Exact actions

1. Record the shared company and period.
2. Record the shared input facts.
3. Generate the Talli output.
4. Generate the Fiken output.
5. Compare every material figure.
6. Compare every material document.
7. List each difference.
8. Resolve each difference that can be corrected.
9. Explain each remaining difference.
10. Ask the accounting reviewer for a decision.
11. Ask the founder for written risk acceptance when needed.
12. Save the final comparison.

### Evidence to retain

Save a sanitized comparison table and reviewer decision. Include the shared inputs,
material figures, document references, differences, resolutions, reviewer, date,
and decision. The accounting reviewer reviews it.

### Pass criteria

Both outputs use the same period and facts. Every material figure and document was
compared. No unexplained material difference remains. A named accounting reviewer
approved the result or the founder recorded written risk acceptance.

### Stop conditions

Stop if inputs differ. Stop if an unexplained material difference remains. Stop if
the reviewer will not approve. Stop if the founder will not accept a stated risk.

### Runtime signoff or record

Keep the comparison table and reviewer decision in the pilot evidence case.

### Capability unlocked

This stage allows the fixed production callback check to begin. It does not permit
a real filing. Do not use a real filing as a connection test.

### Next stage

Go to [stage 8](#verify-the-production-systemregister-callback).

<a id="verify-the-production-systemregister-callback"></a>
## 8. Verify the production Systemregister callback

### Objective

Verify only the fixed production callback in a short maintenance window.

### Responsible roles

The founder/operator runs this stage. A security reviewer watches and reviews it.

### Preconditions

Stage 7 passed. Fresh AAL2 is active. The deployed Git SHA is approved. Both
production switches are false.

### Exact actions

1. Record `TALLI_AUTHORITY_OPS_ENABLED=false`.
2. Record `TALLI_RF1086_PRODUCTION_ENABLED=false`.
3. Open a separately approved maintenance window.
4. Enable only `TALLI_AUTHORITY_OPS_ENABLED`.
5. Deploy the approved Git SHA.
6. Run only the fixed Systemregister callback operation.
7. Read the exact callback with the required GET.
8. Record `callback_already_verified` or `callback_updated_and_verified`.
9. Set `TALLI_AUTHORITY_OPS_ENABLED=false`.
10. Redeploy the same approved Git SHA.
11. Verify the deployed switch is false.
12. Save the redacted audit reference.

Do not use a real filing as a connection test.

### Evidence to retain

Save a redacted authority-operation audit link. Include the operator, reviewer,
fresh-AAL2 window, deployed Git SHA, exact operation, allowlisted result, timestamps,
and final switch proof. Do not save the token or private key. The security reviewer
reviews it.

### Pass criteria

Only the fixed callback operation ran. The exact GET returned
`callback_already_verified` or `callback_updated_and_verified`. The deployed
authority-operations switch returned to false.

### Stop conditions

If any action fails after `TALLI_AUTHORITY_OPS_ENABLED` is enabled, do these
actions in order. This includes a changed callback, a result that is not
allowlisted, an unexpected endpoint, or an unclear switch state.

1. Set `TALLI_AUTHORITY_OPS_ENABLED=false`.
2. Set `TALLI_RF1086_PRODUCTION_ENABLED=false`.
3. Redeploy the approved Git SHA.
4. Verify both deployed values are false.
5. Stop the callback window.
6. Escalate the failure.

### Runtime signoff or record

Retain the redacted authority-operation audit. This stage does not grant a customer
Systembruker or production entitlement.

### Capability unlocked

This stage allows the exact customer Systembruker request. Production filing stays
off.

### Next stage

Go to [stage 9](#complete-systembruker-approval-and-preflight).

<a id="complete-systembruker-approval-and-preflight"></a>
## 9. Complete Systembruker approval and preflight

### Objective

Bind accepted Altinn access to the exact company, owner, right, and request.

### Responsible roles

The company owner approves the request. The operator checks the saved result. The
authority reviewer reviews the evidence.

### Preconditions

Stage 8 passed. Both production switches are false. The company and owner match
stage 5.

### Exact actions

1. Start one standard Systembruker request for the exact company.
2. Record its external reference.
3. Ask the customer owner to open the exact Altinn request.
4. Ask the customer owner to approve that request.
5. Select **Sjekk status på nytt**.
6. Check that the saved request status is accepted.
7. Run the read-only delegated preflight.
8. Check the exact company.
9. Check the exact owner user.
10. Check the exact RF-1086 right.
11. Check the exact external reference.
12. Check that the short-lived token was discarded.
13. Save the accepted and verified request reference.

Production authority permission is required.

Accepted authority-test evidence is required.

### Evidence to retain

Save a sanitized link to the accepted and preflight-verified Systembruker request.
Include the company reference, owner reference, right, external reference, request
status, preflight time, operator, reviewer, and decision. The authority reviewer
reviews it.

### Pass criteria

The customer approved the exact request. Read-only preflight confirmed the company,
user, right, and external reference. The delegation is still active. Production
authority permission and accepted authority-test evidence are current.

### Stop conditions

Stop for a pending or duplicate request. Stop for an identity mismatch. Stop for
a failed preflight. Stop if delegation is lost. Do not create another request until
the first request is reconciled.

### Runtime signoff or record

Retain the accepted and verified Systembruker request. This evidence supports
`rf1086_authority` but does not replace that signoff.

### Capability unlocked

This stage allows launch signoffs to be recorded. It does not create an entitlement.

### Next stage

Go to [stage 10](#record-the-required-launch-signoffs).

<a id="record-the-required-launch-signoffs"></a>
## 10. Record the required launch signoffs

### Objective

Record every named human and environment approval required by the RF-1086 gate.

### Responsible roles

The founder owns this stage. Each named reviewer owns their decision. The operator
records approved decisions without changing their meaning.

### Preconditions

Stage 9 passed. Every evidence link is durable and sanitized. The latest
`security_restore` review is no more than 30 days old.

### Exact actions

1. Record reviewer, date, evidence link, and decision for `launch_legal_name_public_copy`.
2. Record reviewer, date, evidence link, and decision for `legal_policy_pack`.
3. Record reviewer, date, evidence link, and decision for `security_restore`.
4. Record reviewer, date, evidence link, and decision for `support_rollback`.
5. Record reviewer, date, evidence link, and decision for `rf1086_authority`.
6. Record reviewer, date, evidence link, and decision for `founder_production_go_live`.
7. Choose the paid path or the exact billing-exempt path.
8. Record an approved `billing_refund` signoff for the paid path.
9. Record the founder's decision to create an exact billing-exempt pilot for the free path.
10. Record the billing reviewer's approval of the chosen path.
11. Check the expiry of every signoff that can expire.
12. Check that every unconditional decision is approved.
13. Save the chosen billing path with the gate result.

### Evidence to retain

Retain the source evidence behind every recorded `launch_signoffs` row. Save a
sanitized gate report that lists each unconditional key, reviewer, review date,
evidence link, decision, and expiry. Add either the approved `billing_refund`
record or the founder and billing reviewer decisions to use an exact billing-exempt
pilot. The founder reviews the full set.

### Pass criteria

The six unconditional signoffs exist and are approved. Every recorded signoff has
a reviewer, date, evidence link, and decision. `security_restore` is current. The
paid path has an approved `billing_refund`, or the free path has a documented
decision to create one exact billing-exempt pilot in stage 11.

### Stop conditions

Stop if any unconditional signoff is missing. Stop if any decision is rejected.
Stop if any evidence link is missing. Stop if `security_restore` is stale. Stop if
neither an approved `billing_refund` nor a documented exact billing-exempt path
exists.

### Runtime signoff or record

The RF-1086 `launch_signoffs` keys used by the release gate are:

- `launch_legal_name_public_copy`
- `legal_policy_pack`
- `security_restore`
- `billing_refund`
- `support_rollback`
- `rf1086_authority`
- `founder_production_go_live`

`billing_refund` is conditional. At this stage, it may be left unrecorded only when
the founder and billing reviewer have approved creating one exact billing-exempt
pilot in stage 11. No other signoff may be skipped for a free pilot.

### Capability unlocked

This stage allows the operator to create the exact pilot entitlement. It does not
claim that the final release gate is ready.

### Next stage

Go to [stage 11](#create-the-pilot-entitlement-and-billing-path).

<a id="create-the-pilot-entitlement-and-billing-path"></a>
## 11. Create the pilot entitlement and billing path

### Objective

Allow only the exact approved case for a short time.

### Responsible roles

The founder approves the case. The operator creates the record. A billing reviewer
reviews the paid or exempt path.

### Preconditions

Stage 10 passed. The accepted and preflight-verified Systembruker request is still
active. The exact case facts match stage 5.

### Exact actions

1. Record the exact company ID.
2. Record the exact owner user ID.
3. Record the exact income year.
4. Select only the RF-1086 obligation.
5. Select only `rf1086_no_activity_v1`.
6. Link the accepted Systembruker request.
7. Set a short start time.
8. Set a short expiry time.
9. Read the billing path approved in stage 10.
10. Set `billing_exempt=true` only for the approved free pilot.
11. Set `billing_exempt=false` for the paid pilot.
12. Check the approved `billing_refund` for the paid pilot.
13. Create the entitlement only after preflight.
14. Read the saved entitlement back.
15. Run the full filing release gate for the exact case.
16. Save the release-gate result.
17. Save the entitlement's immutable reference.

An active exact pilot entitlement is required.

Billing or an exact billing exemption is required.

### Evidence to retain

Save a sanitized production pilot entitlement link. Include the exact company,
user, year, obligation, profile, Systembruker request, validity window, status,
and billing path. The founder and billing reviewer review it.

### Pass criteria

The active entitlement matches the exact company, user, year, obligation, and
profile. Its validity window is short. It was created after accepted delegation
and preflight. The paid path has billing and an approved `billing_refund`, or the
exact free pilot has `billing_exempt=true`. The final full filing release gate is
ready for the exact case.

### Stop conditions

Stop if the entitlement is broad, expired, or mismatched. Stop if it was created
before preflight. Stop if neither billing nor an exact exemption is valid. Stop if
the full filing release gate is not ready for the exact case.

### Runtime signoff or record

Retain the production pilot entitlement. `billing_exempt=true` skips only the
billing-account requirement and `billing_refund` for this exact active pilot.

### Capability unlocked

This stage allows the owner to approve an exact immutable preview. It does not
allow Send.

### Next stage

Go to [stage 12](#capture-the-owners-final-approval).

<a id="capture-the-owners-final-approval"></a>
## 12. Capture the owner's final approval

### Objective

Bind the owner's fresh approval to the exact preview and hashes.

### Responsible roles

The named company owner approves. The operator checks the immutable record. The
founder reviews the result.

### Preconditions

Stage 11 passed. The exact entitlement is active. The final preview is ready and
will not be edited during review.

### Exact actions

1. Ask the named owner to sign in with fresh AAL2.
2. Show the exact human-readable preview.
3. Show the exact filing payload summary.
4. Show every submitted-document hash.
5. Show the payload hash.
6. Show the adapter version and hash.
7. Ask the owner to read the full preview.
8. Ask the owner to approve the exact preview.
9. Save the immutable approval.
10. Read the saved hashes back.
11. Compare the saved hashes with the approved artifacts.
12. Save the approval reference.

Fresh AAL2 is required.

Filing readiness is required.

### Evidence to retain

Save a sanitized link to the immutable production approval. Include the owner,
approval time, preview reference, payload hash, document hashes, adapter hash,
entitlement reference, and deployed Git SHA. The founder reviews it.

### Pass criteria

The owner used fresh AAL2. Filing readiness passed. The owner read the exact
preview. The immutable approval matches the payload, document, and adapter hashes.

### Stop conditions

Stop if the preview changes. Stop if AAL2 is stale. Stop if filing readiness fails.
Stop if any saved hash differs.

### Runtime signoff or record

Retain the immutable production approval and exact artifact hashes. A later change
requires a new preview and a new approval.

### Capability unlocked

This stage allows the separately approved filing window to be prepared.

### Next stage

Go to [stage 13](#run-the-production-filing-window).

<a id="run-the-production-filing-window"></a>
## 13. Run the production filing window

### Objective

Send the one approved filing once under direct observation.

### Responsible roles

The founder/operator runs the window. The company owner approves Send. The named
observer watches the journal and switches.

### Preconditions

Stage 12 passed. The statutory deadline, support route, alternative route, and
approved window are recorded. Both production switches are false before the window.

### Exact actions

1. Name the operator.
2. Name the company owner.
3. Name the observer.
4. Record the statutory deadline.
5. Record the authority-approved alternative route.
6. Record the approved start and end time.
7. Verify every release gate again.
8. Verify the exact entitlement again.
9. Verify the immutable approval hashes again.
10. Verify the immediate kill switch.
11. Verify that no unexpected authority endpoint is present.
12. Enable only `TALLI_RF1086_PRODUCTION_ENABLED` for the approved window.
13. Deploy the approved Git SHA.
14. Verify the filing gate is ready for only the exact case.
15. Prepare one UUID idempotency key.
16. Ask the owner to press Send once.
17. Watch the append-only journal.
18. Record the operator case reference.

The production adapter must be implemented and enabled.

### Evidence to retain

Save a sanitized journal link and operator case. Include the operator, owner,
observer, window, deployed Git SHA, gate result, entitlement reference, approval
reference, idempotency reference, safe authority reference, and timestamps. The
observer reviews it.

### Pass criteria

Every gate stayed ready. The exact entitlement matched. The approved window was
active. The production adapter was implemented and enabled. Send happened once.
The journal recorded the attempt.

### Stop conditions

If any action fails after `TALLI_RF1086_PRODUCTION_ENABLED` is enabled, do these
actions in order. This includes a changed gate, an entitlement mismatch, an
unavailable kill switch, an unexpected endpoint, or an expired window.

1. Set `TALLI_AUTHORITY_OPS_ENABLED=false`.
2. Set `TALLI_RF1086_PRODUCTION_ENABLED=false`.
3. Redeploy the approved Git SHA.
4. Verify both deployed values are false.
5. Stop the filing window.
6. Do not send twice.

### Runtime signoff or record

Retain the append-only journal and operator case. A transport reference is not
final acceptance.

### Capability unlocked

This stage allows read-only status checks and evidence closeout. It does not allow
another send.

### Next stage

Go to [stage 14](#save-the-final-result-and-closeout-evidence).

<a id="save-the-final-result-and-closeout-evidence"></a>
## 14. Save the final result and closeout evidence

### Objective

Get explicit official final feedback and leave both production switches off.

### Responsible roles

The operator reconciles the result. The observer checks the evidence. The founder
owns any escalation.

### Preconditions

Stage 13 recorded one send. The idempotency record, journal, and approval remain
unchanged.

### Exact actions

1. Treat `received` as incomplete.
2. Treat `processing` as incomplete.
3. Poll only the documented read endpoints within the bounded window.
4. Save the official receipt.
5. Save explicit official `accepted` or `rejected` final feedback.
6. Save the private artifact in private storage.
7. Save only a safe summary in the evidence file.
8. Compare the stored byte size and SHA-256 hash.
9. Set `TALLI_AUTHORITY_OPS_ENABLED=false`.
10. Set `TALLI_RF1086_PRODUCTION_ENABLED=false`.
11. Redeploy the approved Git SHA.
12. Verify both deployed switches are false.
13. Export the closeout evidence package.
14. Verify that the package can be restored.

If the outcome is unknown, follow these instructions exactly:

1. Stop the filing window.
2. Set both production switches to false.
3. Do not send again.
4. Keep the idempotency record and journal.
5. Reconcile the result through read-only authority calls and support.
6. Redeploy the approved Git SHA.
7. Verify both deployed values are false.

A transport reference is not final acceptance.

### Evidence to retain

Save a closeout evidence package. Include the entitlement, immutable approval,
submitted-document hashes, journal events, safe authority references, official
receipt, official final feedback, deployed Git SHA, actor timestamps, operator
case, switch proof, and restore proof. The observer and founder review it.

### Pass criteria

Explicit official final `accepted` or `rejected` feedback is archived with the
receipt. Artifact persistence passed. The evidence package restores. Both deployed
switches are false.

### Stop conditions

For an `unknown` outcome, use the exact steps above before stopping and escalating.

If artifact persistence fails or final feedback is absent, do these actions in
order:

1. Set `TALLI_AUTHORITY_OPS_ENABLED=false`.
2. Set `TALLI_RF1086_PRODUCTION_ENABLED=false`.
3. Redeploy the approved Git SHA.
4. Verify both deployed values are false.
5. Stop the filing window.
6. Escalate the failure.
7. Never repeat the filing POST.

Use the same seven actions if any other closeout action fails before both deployed
switches have been verified false.

For a failed read-and-persist step, use **Sjekk status på nytt** only after storage
health is restored and the existing object's byte size and SHA-256 hash are checked.

### Runtime signoff or record

Retain the closeout evidence package. Confirm
`TALLI_AUTHORITY_OPS_ENABLED=false` and
`TALLI_RF1086_PRODUCTION_ENABLED=false` in the deployed environment.

### Capability unlocked

This stage allows a post-pilot review. It does not allow a second pilot or wider
filing scope.

### Next stage

Go to [stage 15](#make-the-post-pilot-decision).

<a id="make-the-post-pilot-decision"></a>
## 15. Make the post-pilot decision

### Objective

Decide whether to stop or prepare one more controlled pilot.

### Responsible roles

The founder owns the decision. The legal, security, accounting, authority, and
support reviewers provide their findings.

### Preconditions

Stage 14 has explicit final feedback or a fully reconciled incident. Both production
switches are false. The closeout package is available.

### Exact actions

1. Review the official final result.
2. Review every incident.
3. Review support load.
4. Review Talli and Fiken discrepancies.
5. Review the restored closeout evidence.
6. Review reviewer concerns.
7. Decide whether to stop.
8. Decide whether to prepare one more controlled pilot.
9. Record the exact scope of any next pilot.
10. Record every required new approval.
11. Save the founder and reviewer decision.

### Evidence to retain

Save a written founder and reviewer decision. Include the final result, incidents,
support load, discrepancies, restore result, concerns, decision, date, and any
conditions for another controlled pilot. Each named reviewer checks their part.

### Pass criteria

The decision uses the official final result and all closeout evidence. Every issue
has an owner and resolution. Any repeat starts again at stage 1 with fresh evidence
where required.

### Stop conditions

Do not expand after one transport reference. Do not expand while any issue is
unresolved. Do not treat one accepted filing as general production approval.

### Runtime signoff or record

Retain the written founder and reviewer decision. Keep both production switches
false unless a new, separately approved window is opened.

### Capability unlocked

The decision may permit preparation for one more controlled
`rf1086_no_activity_v1` pilot. It does not unlock public self-service filing, corrections, expanded RF-1086 profiles, annual accounts, or company tax returns.

### Next stage

If the decision is to repeat, return to [stage 1](#approve-the-legal-pack). If the
decision is to stop, keep production filing off and close the pilot record.
