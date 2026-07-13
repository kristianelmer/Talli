# Authority Adapter Plans

Status: production adapters unimplemented and disabled
Last updated: 2026-07-13

This document records the minimum real transport sequence for each filing. It
does not authorize production calls. `app/lib/authority-adapters.ts` is the
machine-readable counterpart and `app/lib/filing-release-gate.ts` is the hard
release gate.

## Current Capability

| Obligation | Transport | Production implemented | Production enabled | Personal signing |
| --- | --- | --- | --- | --- |
| RF-1086 | Skatteetaten XML API | No | No | No |
| Skattemelding AS | Skatteetaten validation + Altinn3 | No | No | Yes |
| Årsregnskap | Altinn3 instance | No | No | Yes |

All disabled adapters return the typed error
`production_authority_adapter_disabled`. No environment variable may substitute
simulation for a production transport.

## RF-1086

Ordered outcomes:

1. Post hovedskjema and retain its authority reference.
2. Post every underskjema and retain each reference.
3. Confirm the complete submission.
4. Poll/retrieve feedback documents.
5. Archive official feedback, receipt, request hashes, and authority references.

Enable only after supported-scope TT02 acceptance, idempotent retry evidence,
receipt/archive persistence, production credential review, and named
`rf1086_authority` signoff.

## Skattemelding for AS

Ordered outcomes:

1. Fetch and retain the authority prefill/draft snapshot.
2. Validate the complete skattemelding plus næringsspesifikasjon and persist all
   structured feedback.
3. Create the Altinn3 instance.
4. Upload both data documents and any supported attachments.
5. Hand the instance to a person authenticated through ID-porten for signing;
   a system user must not be treated as the signer.
6. Archive the official receipt and all data/archive references.

Enable only after official 2025 XML XSD validation, TT02 validation/submission,
personal signing proof, receipt/archive persistence, and named
`tax_return_authority` signoff.

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
