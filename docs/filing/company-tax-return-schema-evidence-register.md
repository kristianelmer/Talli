# Skattemelding/Næringsspesifikasjon Schema Evidence Register

Status: deterministic XML candidate validates against pinned official XSDs; live adapters remain disabled

Research date: 2026-06-16  
Last updated: 2026-07-13
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

These mappings are evidence-backed candidates for issue #86. On 2026-07-13 the
builder was corrected to use the generic v6 occurrence structure (`id`, `type`,
and nested `beloep`) rather than semantic paths that do not exist in the 2025
XSD. Representative rendered documents now validate locally against the pinned
official XSD snapshot. They are not production-valid until accepted by the
Skatteetaten validation service and TT02 submission flow.

| Talli concept | Authority surface | Candidate path/code | Evidence file | Decision |
| --- | --- | --- | --- | --- |
| Company/org/year | Skattemelding AS | root `skattemelding.partsnummer`, `skattemelding.inntektsaar` | `skattemeldingUpersonlig_v5_ekstern.xsd` | Candidate |
| Dividend/security positions from Aksjonærregisteret | Skattemelding AS | `spesifikasjonAvForholdRelevanteForBeskatning.aksjeIAksjonaerregisteret.*` with `utbytte`, `erOmfattetAvFritaksmetoden`, gain/loss fields | `skattemeldingUpersonlig_v5_ekstern.xsd`, `tekster_upersonlig.json` | Candidate for holdings in Aksjonærregisteret |
| Non-register shares | Skattemelding AS | `spesifikasjonAvForholdRelevanteForBeskatning.aksjeIkkeIAksjonaerregisteret.*` with `utbytte`, `erOmfattetAvFritaksmetoden` | `skattemeldingUpersonlig_v5_ekstern.xsd`, `tekster_upersonlig.json` | Escalate unless public/security evidence is clear |
| Non-market shares | Næringsspesifikasjon | `balanseregnskap.anleggsmiddel.balanseverdiForAnleggsmiddel.balanseverdi[*]`, code `1800` | v6 XSD + `2025_resultatregnskapOgBalanse.xml` | Candidate |
| Bank balance | Næringsspesifikasjon | `balanseregnskap.omloepsmiddel.balanseverdiForOmloepsmiddel.balanseverdi[*]`, code `1920` | v6 XSD + `2025_resultatregnskapOgBalanse.xml` | Candidate |
| Share capital / retained earnings | Næringsspesifikasjon | `balanseregnskap.gjeldOgEgenkapital.egenkapital.kapital[*]`, codes `2000` and `2050` | v6 XSD + `2025_resultatregnskapOgBalanse.xml` | Candidate |
| Other short-term debt | Næringsspesifikasjon | `balanseregnskap.gjeldOgEgenkapital.kortsiktigGjeld.gjeld[*]`, code `2990` | v6 XSD + `2025_resultatregnskapOgBalanse.xml` | Candidate; related-party cases remain escalation |
| Admin costs | Næringsspesifikasjon | `resultatregnskap.driftskostnad.annenDriftskostnad.kostnad[*]` with exact supported codes such as `6700`, `6420`, `7770`, `7790` | v6 XSD + 2025 result/balance code list | Candidate; narrow supported categories only |
| Deposit interest | Næringsspesifikasjon | `resultatregnskap.finansinntekt.inntekt[*]`, code `8050` (`Annen renteinntekt`) | v6 XSD + 2025 result/balance code list | Ordinary taxable income candidate |
| Dividend income | Næringsspesifikasjon | `resultatregnskap.finansinntekt.inntekt[*]`, code `8090` | v6 XSD + 2025 result/balance code list | Candidate |
| Share-sale gain/loss | Næringsspesifikasjon | finance occurrences using codes `8074` and `8174` | v6 XSD + 2025 result/balance code list | Candidate only for action rows explicitly classified `fritaksmetoden` |
| Dividend reversal | Næringsspesifikasjon | `forskjellMellomRegnskapsmessigOgSkattemessigVerdi.permanentForskjell[*]`, type `tilbakefoeringAvInntektsfoertUtbytte` | v6 XSD + 2025 permanent-difference code list | Candidate |
| Fritaksmetoden 3 percent add-back | Næringsspesifikasjon | same occurrence shape, type `skattepliktigDelAvUtbytterOgUtdelinger` | v6 XSD + 2025 permanent-difference code list | Candidate |
| Exempt share gain / non-deductible share loss | Næringsspesifikasjon | types `regnskapsmessigGevinstVedRealisasjonAvFinansielleInstrumenter` and `regnskapsmessigTapVedRealisasjonAvFinansielleInstrumenter` | v6 XSD + 2025 permanent-difference code list | Candidate |
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

## Tax Reconciliation Decision (2026-07-13)

For the supported simple holding case, Talli starts with accounting result and
applies explicit permanent differences: reverse booked exempt dividends, add
the 3 percent inclusion, subtract booked exempt share gains, and add back booked
non-deductible share losses. Ordinary deposit interest remains in the basis and
narrow supported operating costs reduce it.

Sources:

- Skatteetaten, fritaksmetoden: https://www.skatteetaten.no/bedrift-og-organisasjon/skatt/skattemelding-naringsdrivende/fradrag/aksjer/fritaksmetoden/
- Skatte-ABC, 3 percent inclusion independent of actual cost deductions: https://www.skatteetaten.no/rettskilder/type/handboker/skatte-abc/skatte-abc-2024-2025/f-32-fritaksmetoden/F-32.049/F-32.050/
- Skatte-ABC, costs related to shares and the exemption method: https://www.skatteetaten.no/rettskilder/type/handboker/skatte-abc/gjeldende/a-7-aksjeselskap-mv.--allment/A-7.034/A-7.039/

## Remaining Implementation Slice

1. Vendor the exact official 2025 XSD dependency set or fetch it by verified
   checksum in CI, then validate representative fixtures locally.
2. Implement the Skatteetaten validation and Altinn3 adapters behind the
   disabled production interface.
3. Persist structured official feedback, signing handoff, receipt, and archive
   references from a TT02 run.
4. Obtain the required named authority/security signoffs.

## Code Gate Verification (2026-07-13)

Latest run of the skattemelding/tax-return code-side evidence (all green):

| Suite | Result |
| --- | --- |
| `npm run test:company-tax-return` | 6 passed |
| `TALLI_SKATTE_XSD_DIR=<official-v1.62.47>/src/resources/xsd npm run test:company-tax-return-xml` | 2 passed, including both official XSD validations |
| `node --experimental-strip-types --test tests/tax_settlement.test.mjs` | 4 passed |
| `uv run python -m unittest tests.test_annual tests.test_annual_validation` (tax settlement + validation) | 13 passed |

This proves the deterministic 2025 calculation, leaf-field mapping, XML ordering,
and local XSD validity for the representative supported fixture. It does not
prove authority-service acceptance or production submission. The live adapter,
TT02 validation/signing/receipt/archive evidence, and approved
`tax_return_authority` signoff keep `buildFilingReleaseGates` fail-closed.
