# Skatteetaten company-tax-return authority contract

Status: immutable source snapshot for Talli validation integration  
Pinned: 2026-07-13  
Upstream repository: `https://github.com/Skatteetaten/skattemeldingen`  
Upstream tag: `v1.62.47`  
Upstream commit: `7ac8c6a32238dd0d53e7ac01a6949bb3376f2bba`

These files are exact copies of the three API v2 envelope schemas used by
`app/lib/company-tax-return-authority-client.ts`. They are retained in the
repository so contract review and drift checks do not depend on a mutable
upstream branch.

| File | SHA-256 |
| --- | --- |
| `skattemeldingognaeringsspesifikasjonrequest_v2_kompakt.xsd` | `7aac32c36117d0a7666ee469eaa94768296337e9e37ceab6f835ba2d8856d669` |
| `skattemeldingognaeringsspesifikasjonresponse_v2.xsd` | `fc9c100462603564198ee27e3f96abacc0be037cf9c10ba6d8d440e14ad1e237` |
| `skattemeldingognaeringsspesifikasjonforespoerselresponse_v2_kompakt.xsd` | `c718010fdf6dc6633f4a4c583c272457c1828a70518c6798ff626e0b809a5839` |

Source URLs:

- `https://github.com/Skatteetaten/skattemeldingen/blob/7ac8c6a32238dd0d53e7ac01a6949bb3376f2bba/src/resources/xsd/skattemeldingognaeringsspesifikasjonrequest_v2_kompakt.xsd`
- `https://github.com/Skatteetaten/skattemeldingen/blob/7ac8c6a32238dd0d53e7ac01a6949bb3376f2bba/src/resources/xsd/skattemeldingognaeringsspesifikasjonresponse_v2.xsd`
- `https://github.com/Skatteetaten/skattemeldingen/blob/7ac8c6a32238dd0d53e7ac01a6949bb3376f2bba/src/resources/xsd/skattemeldingognaeringsspesifikasjonforespoerselresponse_v2_kompakt.xsd`

The upstream material is Apache-2.0 licensed; the copied upstream license is
stored as `LICENSE.upstream` in this directory.

## Contract invariants enforced by Talli

- Filing validation uses `POST /api/skattemelding/v2/valider/{incomeYear}/{organizationNumber}`.
- A filing-validation envelope must include the current Skatteetaten
  `skattemeldingUpersonlig` document reference retrieved from the current-draft endpoint.
- `validertest` is exposed only as calculation without a current draft and can
  never yield `validForSubmission=true`.
- Authority hosts and paths are fixed by environment; caller-controlled URLs
  and redirects are prohibited.
- XML documents and responses are bounded, syntactically validated, UTF-8,
  and rejected if they declare a document type or custom entities.
- Provider bodies and bearer tokens are never copied into thrown errors.
- `validertMedFeil`, validation deviations, reasons, and guidance are mapped to
  bounded structured feedback.

This snapshot proves the adapter contract. It does not prove that Talli's
future 2025 tax-return and business-specification documents satisfy their
separate content XSDs or pass Skatteetaten TT02 validation.
