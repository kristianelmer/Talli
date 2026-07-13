# Årsregnskap RR-0002 Evidence Register

Status: narrow XML renderer and test-only Altinn boundary implemented
Last updated: 2026-07-13
Target issue: #82

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

Evidence extraction source:

- `NYDOK/TT02 - RR0002 - Vanlig - AS.postman_environment.json`
- `schema_type = aarsregnskap-vanlig-202406`
- hovedskjema root: `dataFormatId="1266"`, `dataFormatVersion="51820"`,
  `tjenestehandling="aarsregnskap_vanlig"`, `tjeneste="regnskap"`
- selskapsregnskap root: `dataFormatId="758"`, `dataFormatVersion="51980"`,
  `versjon="1.1"`, `tjenestehandling="aarsregnskap_vanlig_underskjema"`,
  `tjeneste="regnskap"`

Live TT02 contract snapshot inspected on 2026-07-13:

- application: `brg/aarsregnskap-vanlig-202406`;
- Hovedskjema JSON schema SHA-256:
  `3776336fa2f7e1ef4773e8cb2800d7930415b9b1c028a59a338327f68b8b4f68`;
- Underskjema JSON schema SHA-256:
  `e17fc7f6cb45984f5ab74dc614955199610deab9b12f9eb1012772f2e0e7c931`;
- application metadata SHA-256:
  `45da74344955265ede80e42726a29ce33c8efa81090cf45ab6739f00a3ad7aa6`;
- custom OpenAPI SHA-256:
  `23f3dc34915a469d031a5ffb9f17fdebf7e548d12211b2019534717156ea38f9`.

The two schema fingerprints are pinned by the renderer. They are evidence of the
contract inspected, not a substitute for provider validation in an Altinn
instance.

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
- Production adapter remains disabled until TT02 test evidence proves instance
  creation, data upload, lock, signing, receipt/inbox behavior, and archive
  references for the supported simple holding AS path.

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
| Dividend/gain financial income | `sumFinansinntekter/aarets` | `153` | Supported for aggregate financial income preview; detailed classification remains conservative. |
| Financial costs | `sumFinanskostnader/aarets` | `17130` | Supported as zero or simple finance-cost aggregate. |
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
The implemented renderer requires explicit prior-year values and blocks rather
than copying or inventing them.

## Implemented XML Guardrails

`app/lib/annual-accounts-xml.ts` renders deterministic Hovedskjema and
Underskjema XML only for the launch case documented here. Before rendering it:

- verifies the organization number format and checksum and restricts the entity
  form to `AS`;
- requires an explicit next-year adoption date and confirming representative;
- rejects parent companies, IFRS, audit obligation, and non-small enterprises;
- requires current and prior figures in whole kroner;
- reconciles result before tax, annual result, assets, equity, debt, and both
  sides of the balance for both periods;
- supports only the no-tax-cost, one-investment, bank, paid-in/retained equity,
  and short-term-debt path;
- escapes XML text, rejects forbidden control characters, and bounds identifiers,
  descriptions, email, amounts, and annual full-time equivalents;
- emits content hashes for both generated documents.

The focused suite parses both outputs, verifies exact namespaces, versions,
paths, `orid` values, current/prior values, and XML escaping, and exercises every
fail-closed boundary above. It does not call Altinn.

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

- Validate the rendered Hovedskjema and Underskjema with the provider in TT02;
  well-formedness and pinned local contract assertions are already covered.
- Add crash-safe orchestration and a private evidence journal around the
  implemented TT02-only Altinn client.
- Validate generated XML/data elements in TT02.
- Prove hybrid system-user/ID-porten owner signing.
- Persist official receipt/inbox/archive references.
- Complete human release signoff.

The test-only client contract and live-rehearsal stop conditions are recorded in
[annual-accounts-tt02-runbook.md](./annual-accounts-tt02-runbook.md).
