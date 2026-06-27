# Skattemelding/Næringsspesifikasjon Schema Evidence Register

Status: payload builder + validation feedback loop implemented (#86, closed); evidence ready for Skatteetaten/Altinn3 test flow  
Research date: 2026-06-16  
Last updated: 2026-06-27  
Target launch filing: 2025 income-year `skattemelding` for simple Norwegian holding AS  
Target issue: #86 (payload + validation, closed) / #87 (test-environment submission flow)  
Official source snapshot: Skatteetaten `skattemeldingen` repository tag `v1.62.47`, commit `7ac8c6a32238dd0d53e7ac01a6949bb3376f2bba`

## Official Sources

- Skatteetaten system-supplier repository: https://github.com/Skatteetaten/skattemeldingen
- Snapshot used for this register: https://github.com/Skatteetaten/skattemeldingen/tree/7ac8c6a32238dd0d53e7ac01a6949bb3376f2bba
- System-supplier README: https://github.com/Skatteetaten/skattemeldingen/blob/7ac8c6a32238dd0d53e7ac01a6949bb3376f2bba/README.md
- API v2 docs: https://github.com/Skatteetaten/skattemeldingen/blob/7ac8c6a32238dd0d53e7ac01a6949bb3376f2bba/docs/api-v2/README.md
- Test flow docs: https://github.com/Skatteetaten/skattemeldingen/blob/7ac8c6a32238dd0d53e7ac01a6949bb3376f2bba/docs/test/README.md
- Altinn3 helper script: https://github.com/Skatteetaten/skattemeldingen/blob/7ac8c6a32238dd0d53e7ac01a6949bb3376f2bba/docs/test/testinnsending/altinn3.py

## Version Decision

For the 2025 income-year filing, Talli must use the 2025-specific schema/code-list generation, not the newest 2026 model unless filing 2026 data.

| Income year | Skattemelding AS XSD | Næringsspesifikasjon XSD | Code-list year |
| --- | --- | --- | --- |
| 2024 example in repo | `skattemeldingUpersonlig_v4_ekstern.xsd` | `naeringsspesifikasjon_v5_ekstern.xsd` | 2024 |
| 2025 launch target | `skattemeldingUpersonlig_v5_ekstern.xsd` | `naeringsspesifikasjon_v6_ekstern.xsd` | 2025 |
| 2026 future | `skattemeldingUpersonlig_v6_ekstern.xsd` | `naeringsspesifikasjon_v7_ekstern.xsd` | 2026 |

Evidence:

- `skattemeldingUpersonlig_v5_ekstern.xsd` has namespace `urn:no:skatteetaten:fastsetting:formueinntekt:skattemelding:upersonlig:ekstern:v5`, generated `2026-03-11`, version `5.0`.
- `naeringsspesifikasjon_v6_ekstern.xsd` has namespace `urn:no:skatteetaten:fastsetting:formueinntekt:naeringsspesifikasjon:ekstern:v6`, generated `2026-01-16`, version `6.0`.
- Both 2025 XSDs reference 2025 code lists such as `2025_resultatregnskapOgBalanse.xml`, `2025_permanentForskjellstype.xml`, `2025_egenkapitalendringstype.xml`, and `2025_vedleggskategori.xml`.

## Submission Flow Evidence

Skatteetaten separates the flow into two surfaces:

- Skatteetaten API v2: fetch current tax return, validate tax return plus business specification, fetch submitted/current data, and retrieve feedback documents.
- Altinn3 app `skd/formueinntekt-skattemelding-v2`: instantiate filing, upload metadata, upload `skattemelding`, upload `naeringsspesifikasjon`, upload attachments if needed, advance process, and retrieve instance/receipt.

Authentication and authorization evidence:

- ID-porten is used for personal login.
- Maskinporten can be used by systems/organizations; Skatteetaten documents systembruker support for these APIs.
- Relevant ID-porten/Maskinporten scope in API docs: `skatteetaten:formueinntekt/skattemelding`.
- Relevant Altinn scopes in test helper: `altinn:instances.read` and `altinn:instances.write`.
- Systembruker resource documented in API v2 docs: `app_skd_formueinntekt-skattemelding-v2`.

Implementation consequence:

- Talli direct filing cannot be a single Skatteetaten POST. It needs a validation adapter and an Altinn3 submission adapter.
- Production release remains blocked until we run the official test flow with Talli credentials, delegated rights, and a supported AS test subject.

## Candidate Mapping for Simple Holding AS

These mappings are evidence-backed candidates for issue #86. They are not yet production-valid until an XML fixture validates against the official XSD and Skatteetaten validation service.

| Talli concept | Authority surface | Candidate path/code | Evidence file | Decision |
| --- | --- | --- | --- | --- |
| Company/org/year | Skattemelding AS | root `skattemelding.partsnummer`, `skattemelding.inntektsaar` | `skattemeldingUpersonlig_v5_ekstern.xsd` | Candidate |
| Dividend/security positions from Aksjonærregisteret | Skattemelding AS | `spesifikasjonAvForholdRelevanteForBeskatning.aksjeIAksjonaerregisteret.*` with `utbytte`, `erOmfattetAvFritaksmetoden`, gain/loss fields | `skattemeldingUpersonlig_v5_ekstern.xsd`, `tekster_upersonlig.json` | Candidate for holdings in Aksjonærregisteret |
| Non-register shares | Skattemelding AS | `spesifikasjonAvForholdRelevanteForBeskatning.aksjeIkkeIAksjonaerregisteret.*` with `utbytte`, `erOmfattetAvFritaksmetoden` | `skattemeldingUpersonlig_v5_ekstern.xsd`, `tekster_upersonlig.json` | Escalate unless public/security evidence is clear |
| Bank balance | Næringsspesifikasjon | `balanseregnskap` using `resultatregnskapOgBalanse` code `1920` (`Bankinnskudd`) | `2025_resultatregnskapOgBalanse.xml` | Candidate |
| Positive equity / retained earnings | Næringsspesifikasjon | `balanseregnskap.gjeldOgEgenkapital.egenkapital.kapital.beloep`, code `2050` (`Positiv egenkapital`) | `2025_resultatregnskapOgBalanse.xml`, `tekster_naering.json` | Candidate |
| Short-term bank debt | Næringsspesifikasjon | `balanseregnskap.gjeldOgEgenkapital.kortsiktigGjeld.gjeld.beloep`, code `2380` | `2025_resultatregnskapOgBalanse.xml`, `tekster_naering.json` | Candidate |
| Other short-term debt/shareholder payable | Næringsspesifikasjon | code `2990` (`Annen kortsiktig gjeld`) | `2025_resultatregnskapOgBalanse.xml` | Candidate, but shareholder/intercompany loans remain escalation |
| Admin costs | Næringsspesifikasjon | `resultatregnskap.driftskostnad.annenDriftskostnad.kostnad.beloep`, code `7700` (`Andre kostnader`) or more specific 2025 result/balance code where available | `naeringsspesifikasjon_v6_ekstern.xsd`, `tekster_naering.json`, `2025_resultatregnskapOgBalanse.xml` | Candidate; use narrow supported categories only |
| Dividend income / other investment income | Næringsspesifikasjon | code `8090` (`Inntekt av andre investeringer/utbytte`) where business-spec result line is needed | `2025_resultatregnskapOgBalanse.xml` | Candidate |
| Fritaksmetoden 3 percent add-back | Næringsspesifikasjon | `permanentForskjell` with `permanentForskjellstype=skattepliktigDelAvUtbytterOgUtdelinger`; code-list text: 3 percent of net tax-free income under exemption method | `2025_permanentForskjellstype.xml` | Candidate |
| Taxable dividend outside exemption method | Næringsspesifikasjon | `permanentForskjellstype=skattepliktigUtbyttePaaAksjerMv` | `2025_permanentForskjellstype.xml` | Unsupported for launch unless accountant-reviewed |
| Owner dividend/equity movement | Næringsspesifikasjon | `egenkapitalendringstype=avsattEllerForventetUtbytte`, `tilleggsutbytte`, `ekstraordinaertUtbytte` when applicable | `2025_egenkapitalendringstype.xml` | Candidate for later; launch tax-return payload should block owner-dividend complexity |
| No-activity AS | Skattemelding + Næringsspesifikasjon | Minimal valid documents with org/year, required `virksomhet`, `skalBekreftesAvRevisor=false`, zero result/balance where valid | XSD roots plus validation service | Candidate only after validation fixture |

## Unsupported/Escalation Decisions

Block before tax-return payload generation:

- Foreign dividends, foreign withholding tax, credit deduction, NOKUS, or low-tax-country cases.
- Securities with unclear `erOmfattetAvFritaksmetoden`.
- Realized gains/losses where inside/outside exemption method cannot be deterministically classified.
- Group contribution, interest limitation, controlled transactions, rederi, petroleum, power, aquaculture, SkatteFUNN, IFRS, bank/insurance, or auditor-dependent cases.
- Company-to-personal-shareholder loans and other related-party loans unless reviewed.
- Non-calendar fiscal year, missing prior-year figures, missing Skatteetaten draft/prefill, or validation service warnings the app cannot explain.

Warn/escalate before submission:

- Manual journal entries affecting tax fields.
- Missing supporting document for dividend decision/payment, security purchase/sale, or material admin cost.
- Difference between Talli calculated 3 percent add-back and Skatteetaten validation/pre-filled draft.

## Next Implementation Slice

Issue #86 built (closed):

1. A 2025-only payload builder using `skattemeldingUpersonlig_v5_ekstern.xsd` and `naeringsspesifikasjon_v6_ekstern.xsd`.
2. XML fixture generation for no-activity and ordinary holding activity.
3. Local XSD validation against the official XSDs.
4. A disabled Skatteetaten validation adapter that persists validation feedback into `filing_submissions.feedback_items`.
5. Readiness blocks for every unsupported case listed above.

## Code Gate Verification (2026-06-27)

Latest run of the skattemelding/tax-return code-side evidence (all green):

| Suite | Result |
| --- | --- |
| `npm run test:company-tax-return` | 5 passed |
| `node --experimental-strip-types --test tests/tax_settlement.test.mjs` | 4 passed |
| `uv run python -m unittest tests.test_annual tests.test_annual_validation` (tax settlement + validation) | 12 passed |

This proves the deterministic 2025 payload, tax-settlement, and validation-feedback
logic is ready for the Skatteetaten/Altinn3 test flow. It does not substitute for the
remaining external work for #87: running the official test flow with Talli credentials,
delegated rights, and a supported AS test subject; persisting official feedback/receipt/
archive references; and the approved `tax_return_authority` launch signoff. Those keep
`buildFilingReleaseGates` fail-closed for `skattemelding`.

