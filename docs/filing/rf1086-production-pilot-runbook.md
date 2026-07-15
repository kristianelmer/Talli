# RF-1086 controlled production pilot runbook

Status: transport implemented, production disabled by default

Owner: founder/operator
Immediate kill switch: set `TALLI_RF1086_PRODUCTION_ENABLED=false` and redeploy

Disabling transport must preserve every preview, entitlement, approval, submission,
journal event, and authority reference. Never delete state to stop a send.

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
