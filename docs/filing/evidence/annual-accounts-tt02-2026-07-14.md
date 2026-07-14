# Annual accounts RR0002 TT02 validation — 2026-07-14

Status: accepted and locked for person signing; not signed or submitted; production remains disabled  
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

The evidence stores only identifiers, SHA-256 payload hashes, state transitions,
and the direct TT02 signing handoff. It excludes access tokens, private keys,
raw XML, contact details, and personal identifiers. The record deliberately says
`signed: false` and `submitted: false`.

This proves the supported XML shape, system-user authority, instance creation,
upload, validation, and lock-for-signing steps. It does not yet prove the
ID-porten signature/submission, receipt or inbox/archive behavior, production
credentials, or dated production approval. Those remain hard launch gates.
