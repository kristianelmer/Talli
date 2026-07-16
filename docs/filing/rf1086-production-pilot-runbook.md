# RF-1086 controlled production pilot runbook

Status: transport implemented, production disabled by default

Owner: founder/operator
Default and post-verification state:

- `TALLI_AUTHORITY_OPS_ENABLED=false`
- `TALLI_RF1086_PRODUCTION_ENABLED=false`

Immediate kill switch: set both values above to `false` and redeploy.

Disabling transport must preserve every preview, entitlement, approval, submission,
journal event, and authority reference. Never delete state to stop a send.

## Activation order

The founder/operator performs these steps in order. A later step never substitutes
for an earlier one:

1. Deploy the reviewed schema and code with
   `TALLI_AUTHORITY_OPS_ENABLED=false` and
   `TALLI_RF1086_PRODUCTION_ENABLED=false`.
2. Under a separately approved, fresh-AAL2 maintenance window, execute only the
   fixed Systemregister callback operation. Close the authority-operations switch
   immediately afterward.
3. Require the audited exact-GET projection and one of the allowlisted callback
   results: `callback_already_verified` or `callback_updated_and_verified`.
4. With both deployed switches still false, run the local mocked proof for the
   owner/company Systembruker and reconciliation path. This mocked/local flow is
   regression evidence; it does not authorize a live action.
5. Only after the earlier gates pass, record an explicit, time-bounded pilot
   entitlement linked to the accepted and preflight-verified request.
6. Separately authorize any production filing under this runbook, then require
   the immutable owner approval and founder-assisted Send procedure below.

The local mock is not evidence of a production callback and does not prove a production callback. The browser scenario uses synthetic identities and a
loopback authority server. This implementation did not make a live request, change Systemregister, enable a switch, grant an entitlement, or submit a filing.

## First-filing pre-flight

Record all of the following in the pilot evidence case before the owner presses
Send:

1. deployed Git SHA and production domain;
2. named customer, organization number, named owner user, and income year;
3. exact `rf1086_no_activity_v1` supported profile and confirmation that purchase,
   sale, dividend, foreign shareholder, multiple share classes, and correction are absent;
4. active exact entitlement, customer agreement/DPA, Systembruker delegation, and
   Skatteetaten production permission;
5. production Maskinporten client/key fingerprint, rotation owner, revocation path,
   and secret-store evidence—never the key itself;
6. current TT02 accepted/rejected evidence, tenant-isolation evidence, restore
   rehearsal, support/rollback signoff, RF authority signoff, and founder signoff;
7. statutory deadline and an authority-approved alternative/support route if the
   controlled filing cannot complete;
8. the immutable owner approval hash, document hashes, adapter version, and the
   exact human-readable preview the owner reviewed.

The first production filing is founder-assisted from approval through final
feedback. A statutory filing is never used as a connectivity probe.

## Observe and classify

- `sending`: watch the append-only journal; every POST must have a prepared UUID
  idempotency key before the network request.
- `received`: Skatteetaten returned a transport reference. This is not content
  acceptance.
- `processing`: submitted documents are retrievable or processing continues. This
  is not final acceptance.
- `accepted` or `rejected`: use only explicit official final feedback. Preserve the
  raw private feedback and expose only a safe summary plus appropriate receipt.
- `unknown`: stop. Do not repeat a POST. Turn off the kill switch if duplicate risk
  is systemic, record the correlation ID/failure class (never XML, tokens, personal
  identifiers, or organization numbers in logs), and reconcile read-only with
  Skatteetaten/support before any retry decision.

Escalate authentication/delegation failures immediately. Alert when `sending`
lasts 10 minutes, receipt retrieval fails after its bounded polling window, or an
`unknown` event exists. Escalate rejection/schema-error clusters to the filing
owner and suspend affected entitlements.

## Recovery matrix

| Failure state | Recovery action |
| --- | --- |
| stale callback | Keep both switches false. Re-run the fixed callback verification in a new approved maintenance window; never infer success from an old audit row. |
| duplicate/pending request | Select only the request bound to the signed owner cookie and company. Do not create another request until the pending request is read and reconciled. |
| failed preflight | Do not grant or retain an entitlement. Reconcile the exact Altinn request and Systembruker projection read-only; start a new approval only after the cause is understood. |
| processing archive | Poll the documented read endpoints within the bounded window. Do not re-submit or repeat a POST. |
| unknown feedback | Quarantine the submission, keep its idempotency state, disable the filing switch if the risk is systemic, and escalate to Skatteetaten/support. |
| failed artifact persistence | Keep the authority outcome and hashes immutable, block closeout, restore private storage/database health, then repeat only the read-and-persist step. |

## Monitoring and on-call questions

- Are both deployed switches in their approved state, and did either change
  outside its maintenance window?
- Is any request pending beyond the approval window, or did preflight fail after
  Altinn reported acceptance?
- Is any submission stuck in `sending`, `processing`, or `unknown`, and what is
  the last safe read-only reconciliation event?
- Do the database artifact hash, object hash, private classification, and owner
  access agree? Can another owner obtain either metadata or bytes?
- Is there any indication of a duplicate POST, entitlement mismatch, or callback
  selecting a request other than the cookie-bound owner/company request?

## Stop conditions

Stop activation or the pilot immediately for a stale/unverified callback,
duplicate/pending request ambiguity, failed preflight, entitlement mismatch,
missing fresh AAL2, failed immutable approval, unknown write outcome, processing
archive outside the bounded window, unknown feedback, failed artifact
persistence, tenant-isolation failure, or any unexpected authority endpoint.

## Rollback steps

1. Set `TALLI_AUTHORITY_OPS_ENABLED=false` and
   `TALLI_RF1086_PRODUCTION_ENABLED=false`; redeploy and verify both values.
2. Revoke or expire the exact pilot entitlement without deleting its evidence.
3. Stop all POSTs. Reconcile already-started requests and submissions read-only.
4. Preserve audit, approval, journal, callback, receipt, and private artifact
   records; capture a sanitized incident reference and notify the filing owner.
5. Use the authority-approved alternative/support route before the statutory
   deadline. Re-activation requires a new reviewed decision through the full
   activation order.

## Evidence closeout

Export entitlement, immutable approval manifest/hash, exact submitted-document
hashes, journal events, sanitized authority references, official receipt/final
feedback, deployed SHA, actor timestamps, and operator case reference. Verify the
backup includes production entitlement → approval → submission → events and that
private objects restore with matching hashes.

## Correction

A correction never overwrites the original. Generate a new preview and approval,
create a new production submission with `supersedes_submission_id` pointing to the
prior submission, repeat owner review, and preserve both evidence packages. The
initial beta does not send corrections until a separate TT02 and production-scope
decision explicitly activates that case profile.
