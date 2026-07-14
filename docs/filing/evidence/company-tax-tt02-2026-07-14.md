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
personal signing, receipt/archive retrieval, or production access.

Later on 2026-07-14, both Altinn instance scopes were active and a combined
system-user token was exchanged successfully. Skatteetaten's official
ID-porten test-data initializer returned HTTP 200 with `status: OK` for income
year 2025. A person-token read and an unpinned, scope-resolved system-user read
then returned the same current draft and document-reference SHA-256
`a2e9e47dd5bc62e12a355368d7ba8dbd94bf0711d555689057b01033f5653fd7`.
The initializer response, tokens, raw XML, and raw reference were not stored.

The next hard gate is the separately approved test write that creates and
uploads the Altinn instance. Personal confirmation, the official feedback
receipt, persisted runtime evidence, and dated human approvals also remain
required. Production remains disabled.
