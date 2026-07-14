# Skattemelding for AS Authority Map

Status: source-backed map for simulation and validation  
Research date: 2026-06-16  
Target filing: `skattemelding for AS` / company tax return

This map defines what Talli can validate from public sources before production company-tax-return filing. It is not a complete production integration spec.

Detailed schema/code-list evidence for the 2025 income-year launch path is now recorded in `docs/filing/company-tax-return-schema-evidence-register.md`. That register is authoritative for issue #86 payload work: 2025 must use `skattemeldingUpersonlig_v5_ekstern.xsd`, `naeringsspesifikasjon_v6_ekstern.xsd`, and 2025 code lists.

Correction note (2026-07-13): the deterministic candidate now uses the exact
generic occurrence structure from the v6 XSD and reconciles interest, supported
costs, exempt gains, non-deductible losses, dividend reversal, and the 3 percent
inclusion. XML rendering and local official-XSD validation are still missing and
must not be described as complete.

## Sources

Primary sources:

- Skatteetaten company tax return page: https://www.skatteetaten.no/bedrift-og-organisasjon/skatt/skattemelding-naringsdrivende/selskap/
- Skatteetaten `skattemelding upersonlig` API docs: https://skatteetaten.github.io/api-dokumentasjon/api/skattemeldingupersonlig
- Raw Skatteetaten API docs: https://raw.githubusercontent.com/Skatteetaten/api-dokumentasjon/main/docs/api/skattemeldingupersonlig.md
- Skatteetaten `skattemeldingen` specification repository: https://github.com/Skatteetaten/skattemeldingen
- Talli schema evidence register: `docs/filing/company-tax-return-schema-evidence-register.md`
- Altinn legacy/company tax return overview: https://info.altinn.no/skjemaoversikt/skatteetaten/skattemelding-for-formues-og-inntektsskatt-aksjeselskap-mv/

## Public Filing Surface

Skatteetaten states that companies must retrieve and submit the tax return with business specification through an accounting or year-end system.

The public `skattemelding upersonlig` API documentation describes a data API that delivers information in a business tax return. It is not a direct filing API for Talli's production submission flow, but it is useful for data shape and authority vocabulary.

The Skatteetaten `skattemeldingen` repository contains system-supplier material for tax return and business specification integration. Its README states that it covers persons, sole proprietorships, and companies, and that it contains:

- Docs for information model, API, test, validations, and texts.
- Source files for XSDs, code lists, request/response envelopes, calculations, and examples.
- `skattemeldingUpersonlig_v1` XSD for AS 2021.
- Request and response envelope XSDs.
- Validation result XSDs.
- Example file for `upersonligSkattemeldingV1.xml`.

Altinn's legacy overview states that company tax return consists of a main tax-return form and several attachment forms, for example business specification/næringsoppgave. It also states role requirements for filling, signing, and auditor cases.

## API and Access Notes

The `skattemelding upersonlig` API docs state:

- API v4 delivers tax returns for 2024 and 2025.
- OpenAPI is in SwaggerHub and is authoritative if it differs from the docs page.
- Scope: `skatteetaten:skattemeldingupersonlig`.
- Access requires Skatteetaten approval/right package and legal basis; the API contains confidential information.
- The API is not adapted for system-user solution and display in an end-user system.
- Error codes include authentication, authorization, validation input, data-format, missing tax return, missing organization, and unsupported format cases.
- Test data is listed for the service in Skatteetaten's external test environment.

Production implication:

- Talli's current tax return preview cannot be treated as a production filing payload.
- The `skattemelding upersonlig` API is useful for model/validation research but does not by itself prove direct filing capability.
- Production filing must use the current Skatteetaten system-supplier submission flow and current schemas, not the simplified preview model.

## Submission flow and scope (confirmed 2026-06-30)

The correct submission service is **"Innrapportering skattemelding"** (`Tjeneste for innsending av
skattemelding`), distinct from the restricted `skattemelding upersonlig` data API.

- **Maskinporten scope:** `skatteetaten:formueinntekt/skattemelding`
  (source: Skatteetaten/api-dokumentasjon `docs/api/innrapportering-skattemelding.md`,
  verified 2026-06-30). There is **no separate validering vs. innsending scope** — this one scope
  covers hent/forhåndsutfylt, valider, and the Altinn3 instance upload. A `…/skattemelding/eiendom`
  variant exists but is not needed for a simple holding AS.
- **Submission is two-legged (Skatteetaten API + Altinn3 app).** The Maskinporten grant additionally
  requests `altinn:instances.read altinn:instances.write` and a systembruker
  `authorization_details` (`type=urn:altinn:systemuser`), then exchanges the Maskinporten token for an
  Altinn token. The Altinn3 app is **`skd/formueinntekt-skattemelding-v2`**.
- **Systembruker resource (Altinn authorization):** `app_skd_formueinntekt-skattemelding-v2`
  (source: Skatteetaten/skattemeldingen `docs/api-v2/README.md`). No named delegatable "tilgangspakke"
  is documented for this service; it uses the systembruker resource directly.
- **Test endpoints:** Maskinporten test `api-test.sits.no`; Altinn3 test `platform.tt02.altinn.no`
  and `skd.apps.tt02.altinn.no` (instance: `…/skd/formueinntekt-skattemelding-v2/instances`);
  Maskinporten test token `https://test.maskinporten.no/token`.
- **Why not `skatteetaten:skattemeldingupersonlig`:** its docs state it is taushetsbelagt, "krever
  eksplisitt lovregulering for tilgang … behandlingsgrunnlag … bygget på hjemmel i lov, ikke samtykke"
  and is "ikke tilrettelagt for systembrukerløsningen" — a data-read API, not a submission path.
- **Owner-managed signing caveat:** the final confirmation/signing step (`process/next` →
  BankID) cannot be performed by the systembruker; a person (daglig leder/styreleder) must sign in the
  Altinn UI. This shapes Talli's owner-managed UX (systembruker fills/locks, owner signs).
- **Order test access:** SKD brukerstøtte (`eksternjira.sits.no`) under Innrapportering → Skattemelding,
  or the overgangsfase email `altinnreetablering@skatteetaten.no`, for scope
  `skatteetaten:formueinntekt/skattemelding` in test for the org. After SKD grants it, the scope must be
  **explicitly added to the Maskinporten client** in the Digdir self-service portal.
- `buildFilingReleaseGates` must remain `production_disabled` until accepted
  `authority_test_runs` evidence for `skattemelding` has receipt and archive
  refs, and the persisted `launch_signoffs` key `tax_return_authority` is
  approved with reviewer/date/evidence/decision.

## TT02 validation evidence (2026-07-14)

The shared test client successfully minted a system-user token for synthetic
holding company `310279617` with scope
`skatteetaten:formueinntekt/skattemelding`. Talli's deterministic no-activity
2025 candidate passed all three pinned local schemas, and Skatteetaten's
`validertest` endpoint returned `validertOK`. Sanitized machine evidence is in
`docs/filing/evidence/company-tax-tt02-2026-07-14.json`.

This closes the scope-access and authority-validation questions only. The
client does not yet have `altinn:instances.read` and
`altinn:instances.write`, so the Altinn instance/upload leg has not been run.
The selected synthetic company also has no current tax-return draft available
from the current-document endpoint. Full TT02 submission acceptance therefore
still requires the two client scopes, a suitable tax-populated Tenor company,
instance/upload validation, owner signing handoff, and receipt/archive proof.

## Talli Launch Subset

Supported for validation:

- Simple Norwegian holding AS.
- Dividend income under clear `fritaksmetoden`.
- 3 percent income-recognition add-back for qualifying dividends.
- Simple admin costs.
- No VAT/payroll/customer invoicing.
- No group contribution.
- No foreign tax credit.
- No complex shareholder loan case.

Blocked or unsupported:

- Unclear `fritaksmetoden` classification.
- Group contributions.
- Advanced loss carry-forward workflows.
- Foreign withholding/tax credit.
- Controlled transactions requiring advanced reporting.
- Company-to-personal-shareholder loans without accountant review.
- Audit or auditor-signature-dependent cases.

## Launch Schema Decisions

These decisions are the source-backed launch schema for simple holding AS tax return work. A row marked `blocked` must not be treated as production-ready.

| Authority requirement | Source evidence | Talli source data | Launch decision |
| --- | --- | --- | --- |
| Filing via system | Skatteetaten states company tax returns for AS must be retrieved and submitted through an accounting or year-end system. | Talli app/backend | Test-only system-supplier transport exists; direct filing remains blocked until persisted instance/signing/receipt integration is complete. |
| Deadline | Skatteetaten states the ordinary deadline is 31 May each year. | `deadlines`, `filing_readiness_snapshots` | Supported as deadline/readiness data. |
| No-activity companies | Skatteetaten states the tax return must be filed even if the company has had no turnover. | `annual_data.no_activity_confirmed` | Minimum 2025 payload is locally schema-valid and TT02 `validertOK`; filing still needs the Altinn/signing leg. |
| Tax return plus business specification | Skatteetaten states the company must retrieve and submit the tax return with `næringsspesifikasjon` through the system. | `ledger_entries`, `holding_actions`, `annual_data` | 2025 schema/code-list mapping exists for the supported holding subset; unsupported cases fail closed. |
| Validation before submission | Skatteetaten states validation checks the tax return and business specification before submission and returns feedback. | test-only validation client; future `filing_submissions.feedback_items` integration | TT02 validation accepted; persisted feedback/state-machine integration remains blocked. |
| Altinn receipt/archive | Skatteetaten states receipt and submitted information are available in Altinn archive after signed submission. | `filing_submissions`, archive export | Simulation only; official receipt/archive retrieval is blocked. |
| Access packages/roles | Skatteetaten lists supported access packages and roles and notes transition from old Altinn roles to access packages. | `authority_permissions` | Readiness supported; production access package/delegation flow blocked. |
| `skattemelding upersonlig` API | Skatteetaten API docs state this service delivers information appearing in a company's tax return. | potential import/pre-fill adapter | Data-reading candidate only; not evidence of production submission. |

## Mapping to Current Engine

Current engine coverage:

- Uses posted ledger entries and structured holding actions: covered for the supported subset.
- Calculates dividend 3 percent add-back and mapped taxable basis/loss: covered for the supported subset.
- Renders deterministic 2025 `skattemeldingUpersonlig` v5 and `naeringsspesifikasjon` v6 XML.
- Validates both documents and the combined v2 envelope against pinned official XSDs.
- Calls TT02 `validertest` through a system-user token and returns sanitized feedback codes.
- Estimates tax at 22 percent for review only; it is not submitted as an authority field.
- Produces no official receipt until the Altinn instance/signing leg is complete.

Missing before production:

- Persisted adapter integration with final preview, immutable body hash, and retry journal.
- Altinn instance scopes and complete instance/upload/file-scan flow in TT02.
- Attachment/vedlegg handling or an enforced no-attachment support boundary.
- Persisted structured Skatteetaten feedback.
- Owner signing handoff and official receipt/status/archive storage.
- Complete TT02 filing acceptance and dated authority/security approval.

Current tax preview field decisions:

| Current preview field | Authority mapping decision |
| --- | --- |
| Result before tax | Derived display value only. Blocked until mapped to current `skattemelding`/`næringsspesifikasjon` field ids. |
| Dividend income under `fritaksmetoden` | Supported as Talli domain concept, but production blocked until mapped to current tax-return/business-specification fields and code lists. |
| 3 percent `fritaksmetoden` add-back | Supported as simulation calculation, but production blocked until exact authority field(s), calculation basis, and rounding rules are confirmed. |
| Admin costs | Supported ledger input, but production blocked until deductible-cost fields in `næringsspesifikasjon` are mapped. |
| Estimated tax at 22 percent | Simulation only. The submitted tax return should not rely on this as an authority payload field. |
| Tax settlement/payment/refund records | Archive/readiness data only. Not a company tax-return payload mapping yet. |
| Company-to-personal-shareholder loan | Blocked before production; requires accountant review and authority field mapping. |

## Production Blockers

- Identify the exact current submission API/flow for company tax return, separate from the `skattemelding upersonlig` data API. **(Resolved 2026-06-30 — see "Submission flow and scope" above: service "Innrapportering skattemelding", scope `skatteetaten:formueinntekt/skattemelding`, Altinn3 app `skd/formueinntekt-skattemelding-v2`.)**
- Confirm the current XSD/JSON schemas and code lists for the relevant income year. **(Resolved for the 2025 launch subset through pinned tag `v1.62.47`.)**
- Map Talli ledger/tax concepts to `skattemelding` and `næringsspesifikasjon` fields. **(Resolved for the explicitly supported subset; other cases remain blocked.)**
- Validate generated payloads against official schemas and test environment. **(Schema and `validertest` acceptance complete 2026-07-14; full Altinn filing acceptance pending.)**
- Confirm access package, Maskinporten/Altinn delegation, signing, feedback, and receipt behavior for owner-managed filing.

## Follow-Up Implementation Slices

1. Add the two Altinn instance scopes to the shared TT02 client.
2. Run instance creation, envelope upload, file-scan polling, and async validation with a tax-populated Tenor company.
3. Connect the test-only transport to the persisted filing state machine and structured feedback records.
4. Implement owner signing handoff and receipt/archive retrieval.
5. Record complete TT02 acceptance and named approvals before enabling production.
