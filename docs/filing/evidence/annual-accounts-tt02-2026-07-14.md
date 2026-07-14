# Annual accounts RR0002 TT02 validation — 2026-07-14

Status: signed, submitted, and archived in TT02; processing decision pending; production remains disabled
Machine evidence: `annual-accounts-tt02-2026-07-14.json`

Talli used the accepted Altinn system user for the Tenor synthetic holding
company `LOGISK ØDE TIGER AS` (`310279617`) with scopes
`altinn:instances.read` and `altinn:instances.write`. The Maskinporten token was
exchanged for an Altinn token in memory.

The guarded rehearsal generated the 2025 RR0002 main form and company-accounts
XML from a balanced synthetic ledger. It created exactly one `Hovedskjema` and
one `Underskjema`, uploaded both, and called Altinn's instance validation. TT02
returned no validation issues. Talli then moved the instance to the signing task
using `action=confirm`.

A person authenticated through TestID at high assurance signed and submitted on
behalf of the synthetic company. Altinn ended the process at
`2026-07-14T10:37:41.935543Z`, created a distinct signature data element, and
archived the instance.

The TT02 receipt page displayed reference `a1b7e8a20f51`. Read-only API
polling found the official `ref-data-as-pdf` receipt and its platform archive
reference. The 109,275-byte PDF downloaded by the operator was byte-for-byte
identical to that API data element (SHA-256
`efcc42bafd11ef2960ed755534f47e6ed00e77d4a2aba812d2cdaae83987febc`).
The two downloaded JSON artifacts also match the recorded main-form and
company-accounts data IDs.

The linked TT02 inbox dialog was checked at `2026-07-14T10:51:21Z`. It showed
`Til behandling` and confirmed that the submission was received. This is an
inbox receipt state, not the later Regnskapsregisteret processing decision.

The evidence stores only identifiers, SHA-256 hashes, state transitions, and
TT02 references. It excludes access tokens, private keys, raw payloads, contact
details, local paths, and personal identifiers.

This proves the supported XML shape, system-user authority, instance creation,
upload, validation, hybrid person signing/submission, and receipt/archive
behavior in TT02. It does not prove a later Regnskapsregisteret processing
decision, production credentials, deployed-runtime persistence, or dated
production approval. Those remain hard launch gates.
