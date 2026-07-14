# Company tax return TT02 validation — 2026-07-14

Status: accepted validation evidence; no return was submitted; production remains disabled  
Code under test: `b545dde` (transport introduced in `6b8b146`)  
Machine evidence: `company-tax-tt02-2026-07-14.json`

Talli acquired a test Maskinporten system-user token in memory for the Tenor
synthetic holding company `LOGISK ØDE TIGER AS` (`310279617`) and scope
`skatteetaten:formueinntekt/skattemelding`.

Before the authority call, the generated 2025 no-activity documents passed the
pinned official schemas for `skattemeldingUpersonlig` v5,
`naeringsspesifikasjon` v6, and the combined request envelope v2. Skatteetaten's
TT02 `validertest` endpoint then returned `validertOK`.

The response also contained three non-blocking guidance codes for equity
reconciliation, company information, and share value. These are preserved as
codes only. The evidence stores SHA-256 hashes, schema names, status codes, and
response size; it excludes the access token, private key, raw input XML, raw
calculated response documents, and personal identifiers.

This proves access to the tax scope and authority validation of the supported
payload shape. It does not prove Altinn instance creation, file-scan handling,
personal signing, receipt/archive retrieval, or production access. The shared
Maskinporten client still needs `altinn:instances.read` and
`altinn:instances.write` before the TT02 instance flow can run. Those steps and
the dated human approvals remain hard launch gates.
