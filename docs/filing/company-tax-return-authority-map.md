# Skattemelding for AS Authority Map

Status: source-backed TT02 flow with persisted pending feedback; production disabled
Research date: 2026-07-14
Target filing: `skattemelding for AS` / company tax return

This map defines what Talli can validate from public sources before production company-tax-return filing. It is not a complete production integration spec.

Detailed schema/code-list evidence for the 2025 income-year launch path is now recorded in `docs/filing/company-tax-return-schema-evidence-register.md`. That register is authoritative for issue #86 payload work: 2025 must use `skattemeldingUpersonlig_v5_ekstern.xsd`, `naeringsspesifikasjon_v6_ekstern.xsd`, and 2025 code lists.

Correction note (2026-07-14): the deterministic candidate uses the exact generic
occurrence structure from the v6 XSD and reconciles interest, supported costs,
exempt gains, non-deductible losses, dividend reversal, and the 3 percent
inclusion. XML rendering, local official-XSD validation, and the supported TT02
prepare/sign/feedback/archive rehearsal are complete. The sanitized evidence now
has a deployed-capable, idempotent and RLS-protected persistence path, plus owner
and year-archive visibility. The official feedback outcome is not yet
classified, and production remains gated.

## Sources

Primary sources:

- Skatteetaten company tax return page: https://www.skatteetaten.no/bedrift-og-organisasjon/skatt/skattemelding-naringsdrivende/selskap/
- Skatteetaten `skattemelding upersonlig` API docs: https://skatteetaten.github.io/api-dokumentasjon/api/skattemeldingupersonlig
- Raw Skatteetaten API docs: https://raw.githubusercontent.com/Skatteetaten/api-dokumentasjon/main/docs/api/skattemeldingupersonlig.md
- Skatteetaten `skattemeldingen` specification repository: https://github.com/Skatteetaten/skattemeldingen
- Talli schema evidence register: `docs/filing/company-tax-return-schema-evidence-register.md`
- Talli production-access research: `docs/filing/skatteetaten-production-access-research.md`
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
- **Order service access:** use Skatteetaten's authenticated support-service application for test
  or production access to Skattemeldingen. The old transition email is retained only in the
  historical TT02 log. After Skatteetaten grants the scope, it must be **explicitly added to the
  matching Maskinporten client** in Digdir self-service. Production uses a separate client and
  separate approval; see `docs/filing/skatteetaten-production-access-application.md`.
- `buildFilingReleaseGates` must remain `production_disabled` until accepted
  `authority_test_runs` evidence for `skattemelding` has receipt and archive
  refs, and the persisted `launch_signoffs` key `tax_return_authority` is
  approved with reviewer/date/evidence/decision.

## TT02 submission evidence (2026-07-14)

The shared test client successfully minted a system-user token for synthetic
holding company `310279617` with scope
`skatteetaten:formueinntekt/skattemelding`. Talli's deterministic no-activity
2025 candidate passed all three pinned local schemas, and Skatteetaten's
`validertest` endpoint returned `validertOK`. Sanitized machine evidence is in
`docs/filing/evidence/company-tax-tt02-2026-07-14.json`.

The two Altinn instance scopes were added to the same client and a combined-scope
token was successfully exchanged for an Altinn token. Following Skatteetaten's
official test-data procedure, the synthetic company was initialized for income
year 2025 through the ID-porten `opprettpart` endpoint. The person-token and
scope-resolved system-user current-document calls returned the same
`skattemeldingUpersonligUtkast`.

The supported no-activity payload was uploaded to Altinn instance
`51549454/5cb600d9-b525-45e9-a506-ebb45b70af31`. The current draft required a
separate internal ten-digit party number rather than the organization number;
Talli extracted it only in memory and replaced the rejected envelope in the
same instance. The corrected payload passed the file scan, preflight, and
asynchronous validation with `validertOK`. The system user stopped at personal
confirmation, the owner signed with high-assurance TestID, and the instance
ended and archived. The official `tilbakemelding` was retrieved and independently
matched by byte length, SHA-256, data reference, and archive reference. No raw
XML, document reference, internal party number, token, key, or personal
identifier was persisted. Narrative and machine evidence are under
`docs/filing/evidence/company-tax-tt02-2026-07-14.*`.

The runtime persistence slice validates the same company/year/evidence contract
and atomically records an `authority_test_runs` row in `pending` plus a linked
`filing_submissions` row in `test_authority` / `feedback_ready`. The owner filing
page labels this evidence explicitly as a test submission and presents the
outcome as awaiting classification. The company-year archive exposes sanitized
hashes, references, feedback metadata and call journal separately from simulated
receipts. The write path requires an owner at AAL2, is retry-idempotent, is
protected by RLS outside its dedicated RPC, and cannot enable a production
permission, adapter or launch signoff.

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
| Filing via system | Skatteetaten states company tax returns for AS must be retrieved and submitted through an accounting or year-end system. | Talli app/backend | Test-only system-supplier transport completed a supported TT02 instance, personal signing, feedback, and archive cycle. Deployed-capable persistence is implemented, but direct production filing remains blocked until the deployed import, outcome classification, approvals, and production adapter are complete. |
| Deadline | Skatteetaten states the ordinary deadline is 31 May each year. | `deadlines`, `filing_readiness_snapshots` | Supported as deadline/readiness data. |
| No-activity companies | Skatteetaten states the tax return must be filed even if the company has had no turnover. | `annual_data.no_activity_confirmed` | Minimum 2025 payload is locally schema-valid and completed the TT02 Altinn/signing/receipt leg for the supported fixture. |
| Tax return plus business specification | Skatteetaten states the company must retrieve and submit the tax return with `næringsspesifikasjon` through the system. | `ledger_entries`, `holding_actions`, `annual_data` | 2025 schema/code-list mapping exists for the supported holding subset; unsupported cases fail closed. |
| Validation before submission | Skatteetaten states validation checks the tax return and business specification before submission and returns feedback. | test-only validation client; company-bound `authority_test_runs` importer; `filing_submissions.feedback_items` | TT02 returned `validertOK`; the importer rejects incomplete evidence and atomically records completed evidence as `pending` with structured warning code `COMPANY_TAX_AUTHORITY_OUTCOME_PENDING`. Explicit outcome classification remains blocked. |
| Altinn feedback/archive | Skatteetaten states feedback and submitted information are available in Altinn archive after signed submission. | test-only feedback client; `authority_test_runs`; `filing_submissions`; archive export | Official TT02 feedback/archive evidence is captured and machine-checked. Sanitized archive visibility is implemented; deployed import execution and final outcome classification remain gated. |
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
- Completed the supported TT02 Altinn instance, owner-signing handoff, official
  feedback receipt, and archive cycle without enabling production.
- Persists the sanitized evidence atomically and idempotently behind owner-AAL2
  and RLS boundaries, exposes the pending warning to the owner, and includes it
  in the company-year archive without classifying it as simulation or production.

Missing before production:

- Actual evidence-import execution against the deployed Supabase project.
- Explicit classification of the official feedback outcome.
- Approval and implementation of the separate attachment/no-attachment boundary.
- Production credentials, security/restore review, and dated named authority approval.
- Production adapter implementation and enablement.

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
- Validate generated payloads against official schemas and test environment. **(Schema, `validertest`, Altinn instance, owner signing, receipt, and archive acceptance complete in TT02 on 2026-07-14.)**
- Obtain separate production access and written answers for the remaining exchange, human-submit,
  receipt-resume, and pilot questions in
  `docs/filing/skatteetaten-production-access-application.md`.

## Follow-Up Implementation Slices

1. Add the two Altinn instance scopes to the shared TT02 client. **Done 2026-07-14.**
2. Initialize the supported synthetic company and verify its current 2025 draft. **Done 2026-07-14.**
3. Run instance creation, envelope upload, file-scan polling, async validation,
   owner signing, receipt retrieval, and archive verification. **Done in TT02 on
   2026-07-14 for the supported no-activity fixture.**
4. Execute the company/year-bound evidence import, then connect final authority
   feedback to the persisted filing state machine and structured feedback
   records. **The atomic importer, structured pending feedback, owner UI and
   archive mapping are implemented; deployed import execution and explicit
   outcome classification remain pending.**
5. Obtain approval for, then implement, the separate attachment/no-attachment
   support boundary.
6. Complete production credentials and security/restore review, record dated
   named authority approval, and separately implement and enable the production
   adapter.
