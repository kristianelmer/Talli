# Company tax return TT02 submission evidence — 2026-07-14

Status: submitted, receipted, and archived in TT02; production remains disabled
Machine evidence: `company-tax-tt02-2026-07-14.json`

Talli completed the owner-managed TT02 flow for a supported 2025 no-activity
holding-company fixture. The run used the exact test scopes
`skatteetaten:formueinntekt/skattemelding`, `altinn:instances.read`, and
`altinn:instances.write`, together with the system-user resource
`app_skd_formueinntekt-skattemelding-v2`.

Before creating the filing, both generated documents and their combined
request envelope passed the pinned official schemas from Skatteetaten tag
`v1.62.47`. The current draft exposed a separate internal ten-digit party
number. The first envelope used the organization number and was rejected with
`UgyldigPartsnummer`; Talli then extracted the current party number in memory,
rebuilt the two linked party fields, and replaced the envelope in the same
instance. The party number was never logged or persisted.

The corrected envelope passed the Altinn malware scan and both Skatteetaten
preflight and asynchronous validation with `validertOK`. The system user moved
the instance only to the personal-confirmation task. The owner then reviewed
and signed the filing in the official TT02 viewer using high-assurance TestID.
Altinn recorded the completed process at `2026-07-14T19:10:21.8787146Z`.

The read-only resume phase retrieved the official `tilbakemelding` XML and
archived instance. The sanitized evidence records only stable metadata:

- Instance: `51549454/5cb600d9-b525-45e9-a506-ebb45b70af31`
- Receipt data id: `bc7ecc16-45af-4eb3-b00f-667217f034aa`
- Receipt content type and size: `text/xml`, 5,050 bytes
- Receipt SHA-256: `2930acdc547f10591979ace5467a37f5d6095864bd2fe8be2399b3507aea99ac`
- Receipt reference: `https://platform.tt02.altinn.no/storage/api/v1/instances/51549454/5cb600d9-b525-45e9-a506-ebb45b70af31/data/bc7ecc16-45af-4eb3-b00f-667217f034aa`
- Archive reference: `https://platform.tt02.altinn.no/storage/api/v1/instances/51549454/5cb600d9-b525-45e9-a506-ebb45b70af31`

The receipt was downloaded again in memory and its byte length, SHA-256, data
reference, and archive reference were independently matched to the machine
evidence. Tokens, private keys, raw current/source/receipt XML, calculated
documents, the internal party number, and personal identifiers were not stored.

This proves a complete test-environment prepare, personal sign, submit,
feedback-receipt, and archive cycle for the supported fixture. It does not
enable production. Remaining gates are deployed evidence import, persisted
structured authority feedback and final filing state, the explicit
no-attachment support boundary, production permission and credentials,
security/restore review, and dated approval of `tax_return_authority`.
