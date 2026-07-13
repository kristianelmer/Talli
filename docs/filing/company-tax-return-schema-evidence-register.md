# Skattemelding/Næringsspesifikasjon Schema Evidence Register

Status: source-backed evidence pack with guarded API v2 validation adapter; local XSD validation passed, TT02 provider acceptance blocked by test-data state
Research date: 2026-06-16  
Target launch filing: 2025 income-year `skattemelding` for simple Norwegian holding AS  
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
- The guarded validation boundary is implemented in
  `app/lib/company-tax-return-authority-client.ts`. It retrieves the current
  company draft, constructs the official v2 envelope, keeps `validertest`
  calculation-only, maps bounded structured feedback, and returns calculated
  authority XML with content hashes. It is not connected to a production
  submission action.
- Exact request, validation-response, and current-draft-response XSDs are
  pinned with hashes and their upstream Apache-2.0 license in
  `docs/filing/authority-contract/`.

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

## Tax Calculation Guardrails

Research confirmation date: 2026-07-13.

- Skatteetaten defines `alminnelig inntekt` as net income after deductible costs and states that the company rate is 22 percent. The launch estimate therefore uses `fritaksmetoden add-back - deductible administration costs`, floors the taxable amount at zero for the tax estimate, and never adds costs to taxable income.
- Skatteetaten states that three percent of qualifying dividend income is normally taxable under `fritaksmetoden`.
- Skatteetaten also states that the three-percent rule does not apply to qualifying group dividends. Talli does not infer this solely from a percentage: the owner must explicitly confirm that the group exemption conditions are satisfied. An unresolved choice blocks the tax-return candidate.
- Legacy dividend actions without an explicit `three_percent_treatment` are blocked from tax-return readiness rather than silently treated as taxable or exempt.

Official sources:

- https://www.skatteetaten.no/satser/alminnelig-inntekt/
- https://www.skatteetaten.no/bedrift-og-organisasjon/skatt/skattemelding-naringsdrivende/fradrag/aksjer/fritaksmetoden/
- https://www.skatteetaten.no/bedrift-og-organisasjon/skatt/skattemelding-naringsdrivende/fradrag/aksjer/aksjer-i-naring-selskapets-aksjer/
- https://www.skatteetaten.no/rettskilder/type/handboker/skatte-abc/gjeldende/a-6-aksjer--utbytte/A-6.011/

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

1. Replace the current field-candidate model with 2025-only XML builders using
   `skattemeldingUpersonlig_v5_ekstern.xsd` and
   `naeringsspesifikasjon_v6_ekstern.xsd`.
2. Generate no-activity and ordinary holding-activity fixtures and validate
   them locally against the complete official XSD import graph.
3. Persist the guarded adapter's validation result, calculated-document hashes,
   and structured feedback in an operator-scoped crash-safe journal.
4. Run current-draft retrieval and filing validation in TT02 for the delegated
   test company; archive the response and require `validertOK` before any
   Altinn instance can be created.
5. Implement the separate Altinn3 submission/receipt adapter only after the
   validation fixture has been accepted.

## Local 2025 No-Activity Contract Fixture

Validation date: 2026-07-13.

The fixture pair under `tests/fixtures/company_tax_return/` is a deliberately
minimal local schema-contract fixture for synthetic organization `310279617`.
It does not claim to be a current Skatteetaten draft. The document builder
preserves the local tax-return fixture byte-for-byte. The generated business specification is
limited to the XSD-required company/year, accounting period, business type,
accounting rules, and auditor-confirmation flag.

Local validation used `xmllint --noout --schema` against the exact XSD files
from upstream commit `7ac8c6a32238dd0d53e7ac01a6949bb3376f2bba`:

| Document | Fixture SHA-256 | XSD SHA-256 | Result |
| --- | --- | --- | --- |
| `2025-no-activity-current-tax-return.xml` | `c4f6250087c40a85c75af3ebcf152045d9a3332f462726b75c4c1d0afe0377f3` | `d8e74eda092540a974efa63cc4608fdf36754dea27f9349b3293f874f9907d52` | Valid |
| `2025-no-activity-business-specification.xml` | `8e3c283aa7fe9868789b76bbceddc40d38c16812b7ca9dc7c9d05cb98ec88610` | `6300d00b31f4cb1ccd45582cef041fb78400a6d9c2d351f6f320872dbb39f8ef` | Valid |

This is not filing-readiness evidence. XSD validity does not prove that a
dormant holding company's opening/closing balances, shares, equity, or
prefilled tax facts are complete. Until the authority validation returns
`validertOK` for a reviewed fixture, the fixture may be used only with the
calculation-only `validertest` boundary. It must never create an Altinn
instance or be treated as a submission candidate.

## TT02 Calculation-Only Evidence

Execution date: 2026-07-13.

The guarded runner obtained a system-user-bound token for only
`skatteetaten:formueinntekt/skattemelding` and posted the locally XSD-valid
fixture pair to the test-only `validertest` endpoint for organization
`310279617`. The provider returned `validertMedFeil` with
`UP_HAR_NÆRINGSSPESIFIKASJON_MANGLER_SKATTEMELDING` (the company lacks a tax
return). A separate read-only request for the current 2025 draft returned HTTP
403. No Altinn instance, submission, or receipt was created.

This proves the client, delegated token, provider endpoint, request envelope,
and calculation-only boundary are reachable. It does not prove that
`310279617` is a usable tax-return test subject. The organization remains a
valid RF-1086 candidate, but company-tax-return testing requires a separate
Tenor organization with an actual 2025 Skatteetaten tax-return draft and a
separately accepted system-user request.
