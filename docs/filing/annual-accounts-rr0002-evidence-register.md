# Årsregnskap RR-0002 Evidence Register

Status: TT02 payload validated, signed, submitted, and archived; processing decision and production approval pending

Last updated: 2026-07-14
Target issue: #82 (payload map, closed) / #84 (test-environment submission flow)

This register records the public evidence Talli can use to build a narrow
`aarsregnskap-vanlig-202406` payload for a simple holding AS. It does not enable
production filing; test-environment validation and human release approval remain
required.

## Sources

- Brønnøysundregistrene Regnskapsregisteret docs:
  https://brreg.github.io/docs/apidokumentasjon/regnskapsregisteret/
- Brønnøysundregistrene system-submission docs:
  https://brreg.github.io/docs/apidokumentasjon/regnskapsregisteret/maskinell-innrapportering/hvordan-sende-inn/
- Brønnøysundregistrene official Postman examples:
  https://brreg.github.io/docs/apidokumentasjon/regnskapsregisteret/maskinell-innrapportering/eksempler-paa-registrering/API-eksempler-Postman.zip
- Altinn RR-0002 form page:
  https://info.altinn.no/skjemaoversikt/bronnoysundregistrene/arsregnskap/
- Altinn Apps instance API:
  https://docs.altinn.studio/en/api/apps/instances/
- Altinn Apps process API:
  https://docs.altinn.studio/en/api/apps/process/
- Altinn instance model:
  https://docs.altinn.studio/en/api/models/instance/
- Altinn end-user-system receipt retrieval:
  https://docs.altinn.studio/nb/altinn-studio/v8/guides/integration/sbs/apis/#4-hente-kvittering
- Altinn system registration guide:
  https://docs.altinn.studio/en/authorization/guides/system-vendor/system-user/systemregistration/
- Altinn system-register rights update API:
  https://docs.altinn.studio/en/api/authentication/systemuserapi/systemregister/update/
- TT02 Resource Registry record used for the rehearsal:
  https://platform.tt02.altinn.no/resourceregistry/api/v1/resource/app_brg_aarsregnskap-vanlig-202406
- Live TT02 hovedskjema JSON schema:
  https://brg.apps.tt02.altinn.no/brg/aarsregnskap-vanlig-202406/api/jsonschema/Hovedskjema
- Live TT02 underskjema JSON schema:
  https://brg.apps.tt02.altinn.no/brg/aarsregnskap-vanlig-202406/api/jsonschema/Underskjema

Evidence extraction source:

- `NYDOK/TT02 - RR0002 - Vanlig - AS.postman_environment.json`
- `schema_type = aarsregnskap-vanlig-202406`
- hovedskjema root: `dataFormatId="1266"`, `dataFormatVersion="51820"`,
  `tjenestehandling="aarsregnskap_vanlig"`, `tjeneste="regnskap"`
- selskapsregnskap root: `dataFormatId="758"`, `dataFormatVersion="51980"`,
  `tjenestehandling="aarsregnskap_vanlig_underskjema"`, `tjeneste="regnskap"`

## Submission and Signing Flow

Brønnøysund's system-submission docs state:

- `Systembruker` can instantiate, fill, upload files, and lock the form.
- `Systembruker` cannot sign.
- `ID-porten` can sign.
- Signing also submits the form.
- A system-user/person-user hybrid flow is possible: system user fills the form,
  then a person signs with ID-porten.
- Data elements have generated `data_id` values; hovedskjema, selskapsregnskap,
  konsernregnskap, attachments, and signature are distinct data elements.
- Required scopes are `altinn:instances.read` and `altinn:instances.write`.

Talli launch decision:

- Owner-managed annual accounts filing must use hybrid flow or ID-porten-only
  signing. Talli may automate data filling only until the signing step.
- TT02 now proves instance creation, data upload, lock, hybrid person signing,
  submission, receipt retrieval, and archive references for the supported simple
  holding AS path. The production adapter remains disabled until the later
  processing decision, deployed-runtime evidence, and dated release approval
  are recorded.

## Minimal Hovedskjema Map

| Talli concept | RR0002 tag | orid | Decision |
| --- | --- | ---: | --- |
| Income year | `regnskapsaar` | `17102` | Supported from company income year. |
| Period start | `regnskapsstart` | `17103` | Supported for full calendar-year launch only. |
| Period end | `regnskapsslutt` | `17104` | Supported for full calendar-year launch only. |
| Not audited | `aarsregnskapIkkeRevideres` | `34669` | Supported only when company has no audit obligation. |
| Prepared by authorized accountant | `aarsregnskapUtarbeidetAutorisertRegnskapsfoerer` | `34670` | Supported as explicit no/yes confirmation; launch defaults to no unless reviewer metadata exists. |
| External authorized accountant assistance | `tjenestebistandEksternAutorisertRegnskapsfoerer` | `34671` | Supported as explicit confirmation; launch defaults to no unless reviewer metadata exists. |

## Minimal Selskapsregnskap Map

| Talli concept | RR0002 tag path | Current-year orid | Decision |
| --- | --- | ---: | --- |
| Currency | `valuta` | `34984` | Supported as `NOK` only. |
| Admin/operating costs | `sumDriftskostnad/aarets` | `17126` | Supported from ledger expense totals; detail rows can follow later. |
| Dividend/gain/interest financial income | `sumFinansinntekter/aarets` | `153` | Supported from internal accounts `8070` and `8050`; detailed authority classification remains conservative. |
| Financial costs | `sumFinanskostnader/aarets` | `17130` | Supported for the launch share-sale loss aggregate from internal account `8090`. |
| Result before tax | `resultatFoerSkattekostnad/aarets` | `167` | Derived from ledger totals. |
| Annual result | `aarsresultat/aarets` | `172` | Derived after tax settlement, if known; otherwise block production. |
| Investments in subsidiaries | `investeringDatterselskap/aarets` | `9686` | Supported for owned subsidiary shares when classification is clear. |
| Investments in associated companies | `investeringTilknyttetSelskap/aarets` | `7726` | Supported only when Talli investment kind maps clearly. |
| Other shares/holdings | `investeringAksjerAndeler/aarets` | `7100` | Supported fallback for simple non-subsidiary holdings; unclear cases block. |
| Sum financial fixed assets | `sumFinansielleAnleggsmidler/aarets` | `5267` | Derived from supported investment rows. |
| Marketable shares/current investments | `markedsbaserteAksjer/aarets` | `7117` | Supported only for simple listed securities if Talli has enough classification. |
| Sum current investments | `sumInvesteringer/aarets` | `6601` | Derived where current investment rows are used. |
| Bank/cash | `sumBankinnskuddKontanter/aarets` | `29042` | Supported from reconciled bank balance. |
| Paid-in/share capital aggregate | `sumInnskuttEgenkapital/aarets` | `3730` | Supported from opening balance/share capital. |
| Retained/other equity | `annenEgenkapital/aarets` | `3274` | Supported from result allocation/retained earnings. |
| Sum retained equity | `sumOpptjentEgenkapital/aarets` | `9702` | Derived. |
| Sum equity | `sumEgenkapital/aarets` | `250` | Derived and must equal assets minus liabilities. |
| Sum debt | `sumGjeld/aarets` | `1119` | Supported for simple current/tax/owner liabilities only. |
| Sum short-term debt | `sumKortsiktigGjeld/aarets` | `85` | Supported for tax payable and simple short-term liabilities. |
| Proposed dividend | `utbytte/aarets` | `235` | Supported only when owner dividend workflow generated corporate documents. |
| Annual full-time equivalents | `antallAarsverk` | `37467` | Required small-enterprise note field; supported, default `0` for no employees/payroll. |

Previous-year fields exist in the official example as sibling `fjoraarets` values.
Talli launch may set them from opening/prior annual accounts where available, or
block production annual accounts until prior-year values are confirmed.

## Notes

Small-enterprise note support starts with:

- annual full-time equivalents: `antallAarsverk` / orid `37467`;
- accounting-principle free text only if reviewed;
- share information note only when own shares/share capital details require it;
- additional notes are blocked/escalated until modelled.

Launch default:

- no payroll and no employees -> `antallAarsverk = 0`;
- audit obligation -> unsupported;
- annual report/cash-flow/sustainability requirements -> unsupported.

## Attachments

The system-submission docs treat attachments as separate data elements. Launch
rules:

- small AS without audit/annual report/cash-flow obligations can proceed without
  those attachments if authority test accepts the payload;
- any required auditor report, annual report, cash-flow statement, or complex
  note attachment blocks launch scope until attachment payload handling is tested.

## Unsupported Annual-Account Cases

Block or escalate:

- audit obligation;
- non-small enterprise requirements;
- annual report obligation;
- cash-flow statement obligation;
- sustainability reporting;
- foreign currency;
- non-calendar fiscal year;
- replacement of already submitted annual accounts;
- complex notes not listed above;
- unclear investment classification;
- missing prior-year figures where required by authority validation.

## Remaining Before Production

- Implement payload builder using this map. — Done in #83 (`holding_core.annual` +
  `app/lib`; covered by the code-gate verification below).
- Implement the test-only stepped Altinn transport through the person-signing
  handoff. — Done 2026-07-14 in `app/lib/annual-accounts-authority-client.ts`.
  It creates the instance, resolves exactly one `Hovedskjema` and one
  `Underskjema`, uploads XML, validates, fails closed on errors, locks with
  `action=confirm`, and returns the person-signing URL. It cannot sign or submit,
  and construction with `environment=production` is refused.
- Add `altinn:instances.read` and `altinn:instances.write` to the TT02
  Maskinporten client. — Done and verified in Digdir Selvbetjening 2026-07-14.
- Register the live TT02 resource `app_brg_aarsregnskap-vanlig-202406` on
  system `930835978_talli`. — Done 2026-07-14 using the rights-only endpoint;
  read-back verified that both existing Skatteetaten rights were preserved.
- Create a matching annual-accounts system-user request for test company
  `310279617`. — Done 2026-07-14; request
  `4f774704-88b8-4053-994b-37073ab4a896` was approved by the company through
  TT02 ID-porten and read back through the vendor API with status `Accepted`.
- Mint and exchange an annual-accounts system-user token with both Altinn
  instance scopes. — Done 2026-07-14; both tokens remained in memory.
- Validate generated XML/data elements in TT02. — Done 2026-07-14; instance
  `51549454/90560530-005d-4f9e-8d8f-a1b7e8a20f51` accepted both XML data
  elements with zero validation issues and moved to the signing task. Evidence:
  [annual-accounts-tt02-2026-07-14.md](./evidence/annual-accounts-tt02-2026-07-14.md).
- Prove hybrid system-user/ID-porten owner signing. — Done 2026-07-14; TestID
  high-assurance signing ended the process and created a distinct signature data
  element.
- Persist official receipt/inbox/archive references. — Done for the TT02 evidence
  pack; read-only polling captured `process.ended`, `status.archived`, the
  platform instance reference, and the official `ref-data-as-pdf` reference.
  The linked inbox dialog confirmed receipt and currently reports
  `Til behandling`.
- Capture the later Regnskapsregisteret processing decision from the TT02 inbox.
- Connect the verified evidence shape to the deployed runtime submission journal.
  — The owner workspace now imports the sanitized JSON through a company-bound,
  step-up-protected action and stores it as `pending`; executing that import in
  the deployed environment remains pending.
- Complete human release signoff.
- Enable the production transport only after all external evidence and signoffs
  above exist; the current client remains test-only.

The generic Altinn system-user setup guide currently shows
`app_brg_aarsregnskap` as an example. A TT02 rights update with that identifier
failed on 2026-07-14 with `AUTH.VLD-00003` because the resource was not found.
The live TT02 Resource Registry returned the versioned, delegable Altinn App
resource `app_brg_aarsregnskap-vanlig-202406`; that exact identifier is the one
registered and read back for this rehearsal.

## Code Gate Verification (2026-07-14)

Latest run of the annual-accounts code-side evidence (all green):

| Suite | Result |
| --- | --- |
| `uv run python -m unittest tests.test_annual tests.test_annual_validation` | 13 passed |
| `npm run test:annual-accounts` | 5 passed |
| `npm run test:annual-accounts-xml` | 5 passed |
| `npm run test:annual-accounts-authority` | 6 passed |
| `npm run test:annual-accounts-authority-script` | 1 passed |
| `npm run test:annual-data` | 2 passed |
| `npm run test:annual-readiness` | 5 passed |
| `npm run test:authority-evidence` | 11 passed |

This proves the deterministic payload/readiness/evidence logic and the full TT02
hybrid submission path through receipt/archive. It does not substitute for the
remaining external rows above (processing decision, deployed-runtime evidence,
and human release signoff), which keep `buildFilingReleaseGates` fail-closed for
`aarsregnskap` (requires accepted `authority_test_runs` evidence + approved
`annual_accounts_authority` signoff).
