# Authority Adapter Plans

Status: all three supported filing paths have sanitized TT02 evidence; all production adapters disabled
Last updated: 2026-07-14

This document records the minimum real transport sequence for each filing. It
does not authorize production calls. `app/lib/authority-adapters.ts` is the
machine-readable counterpart and `app/lib/filing-release-gate.ts` is the hard
release gate.

## Current Capability

| Obligation | Transport | Production implemented | Production enabled | Personal signing |
| --- | --- | --- | --- | --- |
| RF-1086 | Skatteetaten XML API | Yes | No | No |
| Skattemelding AS | Skatteetaten validation + Altinn3 | No | No | Yes |
| Årsregnskap | Altinn3 instance | No | No | Yes |

Production invocation remains fail-closed with the typed error
`production_authority_adapter_disabled`. No environment variable may substitute
simulation for a production transport or enable the implemented RF-1086 client.

## RF-1086

Ordered outcomes:

1. Post hovedskjema and retain its authority reference.
2. Post every underskjema and retain each reference.
3. Confirm the complete submission.
4. Poll/retrieve feedback documents.
5. Archive official feedback, receipt, request hashes, and authority references.

The real Maskinporten and Skatteetaten transport is implemented in
`apps/backend/src/talli_backend/adapters/maskinporten.py` and
`apps/backend/src/talli_backend/adapters/rf1086_authority.py`. The supported
no-activity flow was accepted in TT02 on 2026-07-14, including archive retrieval;
see `evidence/rf1086-tt02-2026-07-14.md`.

Enable only after the accepted evidence is recorded in the runtime gate,
production credentials and restore/security controls are reviewed, and the
named `rf1086_authority` reviewer signs off.

## Skattemelding for AS

The deterministic 2025 documents, combined envelope, test-only authority
client, and guarded rehearsal are implemented. The no-activity fixture completed
TT02 validation with `validertOK`, personal high-assurance submission, official
feedback retrieval, and archive verification on 2026-07-14; see
`evidence/company-tax-tt02-2026-07-14.md`. The company-bound runtime importer
deliberately records this evidence as `pending` until the final authority
outcome is explicitly classified. Production transport remains unimplemented
and disabled.

Ordered outcomes:

1. Fetch and retain the authority prefill/draft snapshot.
2. Validate the complete skattemelding plus næringsspesifikasjon and persist all
   structured feedback.
3. Create the Altinn3 instance.
4. Upload both data documents. Block the case if an additional attachment is
   required until attachment handling has its own approved implementation and
   TT02 evidence.
5. Hand the instance to a person authenticated through ID-porten for signing;
   a system user must not be treated as the signer.
6. Archive the official receipt and all data/archive references.

Enable only after the deployed runtime has accepted evidence with structured
final feedback, the no-attachment support boundary is enforced, production
access/credentials and restore/security controls are reviewed, and the named
`tax_return_authority` reviewer signs off. The pinned 2025 XSD validation and
TT02 submission/signing/receipt/archive evidence are complete but do not satisfy
those remaining production gates. Current official production prerequisites and
the copy-ready, not-yet-submitted application are recorded in
`skatteetaten-production-access-research.md` and
`skatteetaten-production-access-application.md`.

## Årsregnskap

Ordered outcomes:

1. Create the Altinn3 instance.
2. Upload hovedskjema, selskapsregnskap, and supported attachments.
3. Lock the instance for signing.
4. Hand the instance to a person authenticated through ID-porten; system users
   cannot sign.
5. Archive the official receipt and instance/data references.

Enable only after TT02 payload acceptance, personal signing proof,
receipt/archive persistence, and named `annual_accounts_authority` signoff.

## Shared Enablement Rule

An adapter capability may change to implemented/enabled only when all of these
are true for the obligation:

- the real transport exists and has no simulation fallback;
- secrets are stored outside source control and production access is reviewed;
- accepted test evidence includes official receipt and archive references;
- retries use the same idempotency key only for an identical endpoint/body;
- MFA/step-up, billing, supported-case, and final-preview gates pass;
- the named filing-specific human signoff is approved.

Until then public copy must say preview/simulation, never production-ready.
