# Skattemelding/Næringsspesifikasjon Schema Evidence Register

Status: deterministic XML accepted through TT02 signing, receipt, and archive; production adapters remain disabled

Research date: 2026-06-16  
Last updated: 2026-07-14
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
- The official TT02 test flow has completed for a supported AS fixture with
  Talli test credentials and delegated rights. Production release remains
  blocked by deployed evidence/state integration, permissions, security/restore
  review, and named approval.

## Candidate Mapping for Simple Holding AS

These mappings are evidence-backed candidates for issue #86. On 2026-07-13 the
builder was corrected to use the generic v6 occurrence structure (`id`, `type`,
and nested `beloep`) rather than semantic paths that do not exist in the 2025
XSD. Representative rendered documents now validate locally against the pinned
official XSD snapshot. The supported no-activity fixture was accepted by the
Skatteetaten validation service and completed the TT02 submission flow on
2026-07-14. This is test evidence, not production authorization.

| Talli concept | Authority surface | Candidate path/code | Evidence file | Decision |
| --- | --- | --- | --- | --- |
| Company/org/year | Skattemelding AS | root `skattemelding.partsnummer`, `skattemelding.inntektsaar` | `skattemeldingUpersonlig_v5_ekstern.xsd` plus current TT02 draft | Accepted for the supported TT02 fixture. `partsnummer` is the current draft's internal ten-digit party number, not the nine-digit organization number; it is used in memory only. |
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
| No-activity AS | Skattemelding + Næringsspesifikasjon | Minimal valid documents with party/year, required `virksomhet`, `skalBekreftesAvRevisor=false`, zero result/balance where valid | XSD roots, validation service, and TT02 receipt/archive evidence | Accepted for the supported 2025 TT02 fixture; production still gated |

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
   checksum in CI; local representative-fixture validation already passes.
2. Keep the test-only Skatteetaten/Altinn3 transport behind the disabled
   production interface and enforce the no-attachment support boundary.
3. Import the sanitized TT02 evidence in the deployed runtime and persist
   structured official feedback and final filing state.
4. Obtain production credentials plus the required named authority,
   security, and restore signoffs.

## Code and TT02 Gate Verification (2026-07-14)

Latest run of the skattemelding/tax-return code-side evidence (all green):

| Suite | Result |
| --- | --- |
| `npm run test:company-tax-return` | 8 passed |
| `TALLI_SKATTE_XSD_DIR=<official-v1.62.47>/src/resources/xsd npm run test:company-tax-return-xml` | 2 passed, including both official XSD validations |
| `TALLI_SKATTE_XSD_DIR=<official-v1.62.47>/src/resources/xsd npm run test:company-tax-return-authority` | 15 passed, including current party-number parsing, safe envelope replacement, combined envelope schema, and fail-closed transport behavior |
| `npm run test:company-tax-return-authority-script` | 2 passed, including exact test-write guards and resumable owner boundary |
| `node --test tests/company_tax_return_tt02_evidence.test.mjs` | 1 passed, requiring submitted/receipted evidence, matching receipt/archive metadata, and no secrets or raw identifiers |
| `npm run authority:company-tax-test` | TT02 preflight and asynchronous validation returned `validertOK`; high-assurance owner confirmation completed; official feedback receipt and archive were retrieved and independently verified |
| `node --experimental-strip-types --test tests/tax_settlement.test.mjs` | 4 passed |
| `uv run python -m unittest tests.test_annual tests.test_annual_validation` (tax settlement + validation) | 13 passed |

This proves the deterministic 2025 calculation, leaf-field mapping, XML ordering,
local XSD validity, test-scope access, and authority validation for the
representative supported fixture and proves an accepted TT02 Altinn filing with
owner signing, official feedback receipt, and archive evidence. It does not
prove production authorization or deployed runtime integration. Deployed
evidence import, structured final feedback/state, production permission and
credentials, security/restore approval, and the approved
`tax_return_authority` signoff keep `buildFilingReleaseGates` fail-closed.
