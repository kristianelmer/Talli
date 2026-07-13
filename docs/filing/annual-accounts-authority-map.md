# Årsregnskap Authority Map

Status: source-backed map, payload field slice, and test-only Altinn boundary
Research date: 2026-07-13
Target filing: `årsregnskap` / RR-0002

This map defines what Talli can validate from public sources before production annual-accounts filing. It is not a complete production integration spec.

## Sources

Primary sources:

- Altinn RR-0002 form page: https://info.altinn.no/skjemaoversikt/bronnoysundregistrene/arsregnskap/
- Brønnøysundregistrene annual accounts page: https://www.brreg.no/en/submission-of-annual-accounts/
- Altinn annual accounts guidance: https://info.altinn.no/en/start-and-run-business/accounts-and-auditing/accounting/annual-accounts/
- Brønnøysund API documentation index for Regnskapsregisteret: https://brreg.github.io/docs/apidokumentasjon/regnskapsregisteret/
- Brønnøysund system-submission docs: https://brreg.github.io/docs/apidokumentasjon/regnskapsregisteret/maskinell-innrapportering/hvordan-sende-inn/
- Brønnøysund official Postman examples: https://brreg.github.io/docs/apidokumentasjon/regnskapsregisteret/maskinell-innrapportering/eksempler-paa-registrering/API-eksempler-Postman.zip
- Digdir/Altinn 3 update for annual accounts system submission: https://samarbeid.digdir.no/altinn/nytt-fra-programmet-nye-altinn/2723
- Digdir system-user setup: https://docs.altinn.studio/nb/altinn-studio/v8/guides/integration/sbs/setup/
- Digdir App API flow: https://docs.altinn.studio/nb/altinn-studio/v8/guides/integration/sbs/apis/
- Altinn validation API: https://docs.altinn.studio/en/api/apps/validation/
- RR0002 evidence register: [annual-accounts-rr0002-evidence-register.md](./annual-accounts-rr0002-evidence-register.md)
- TT02 boundary runbook: [annual-accounts-tt02-runbook.md](./annual-accounts-tt02-runbook.md)

## Public Filing Surface

RR-0002 is the Altinn annual-accounts form used to submit annual accounts to Regnskapsregisteret. Altinn states that complete annual accounts must be submitted by companies with accounting obligations, normally no later than 31 July to avoid late filing fees.

Altinn states that RR-0002 consists of:

- Hovedskjema.
- Regnskapsskjema with accounting currency and accounting figures for income statement and balance sheet.
- Notes for small enterprises, including at minimum number of annual full-time equivalents.
- Attachments where relevant.

Altinn annual-accounts guidance states that a complete annual-account set normally includes:

- Income statement.
- Balance sheet.
- Notes.
- Annual report, not for small enterprises.
- Sustainability reporting, only when required.
- Cash-flow analysis, not for small enterprises.
- Auditor's report, if audit obligation applies.

Brønnøysund states that after processing, the enterprise receives a decision in Altinn inbox, and that annual accounts and tax return are separate reporting obligations.

## Machine Submission Surface

Brønnøysund documentation links Regnskapsregisteret machine reporting documentation. Digdir states that a new machine submission API for annual accounts has been developed and documented, supports system user, ID-porten, and a combination where a system user can automate data filling before a person signs.

Production implications:

- Talli can model annual-account data and readiness from public sources.
- Talli now has a narrow RR0002 field evidence pack for a simple holding AS, but cannot claim production RR-0002 filing until generated payloads, attachment rules, signing flow, feedback, and receipt behavior are validated in TT02 or equivalent test environment.
- Brønnøysund docs state system user can fill/upload/lock, but signature requires ID-porten; owner-managed filing therefore needs an ID-porten-only or hybrid system-user/person signing flow.
- `buildFilingReleaseGates` must remain `production_disabled` until
  accepted `authority_test_runs` evidence for `aarsregnskap` has receipt and
  archive refs, and the persisted `launch_signoffs` key
  `annual_accounts_authority` is approved with reviewer/date/evidence/decision.

Pinned system-user sequence for the current test boundary:

1. request `altinn:instances.read` and `altinn:instances.write` for a system user
   delegated the `app_brg_aarsregnskap` resource;
2. exchange the system-user Maskinporten token for an Altinn token;
3. create an instance in `brg/aarsregnskap-vanlig-202406`;
4. replace the generated hovedskjema/underskjema data elements;
5. validate the whole instance;
6. lock the unchanged valid draft with `{"action":"confirm"}`; and
7. stop for personal ID-porten signing, which also submits the form.

Talli now implements steps 2–6 as a fixed-host TT02 client tested with an
injected fake transport. It has no signing method and has not created a live
instance.

## Talli Launch Subset

Supported for validation:

- Small Norwegian holding AS.
- No audit obligation.
- One accounting year.
- Balance sheet and income statement totals from posted ledger.
- Notes represented as checklist/metadata, not full legal note generation.
- General meeting approval confirmed.
- Annual accounts not yet production-submitted.

Blocked or unsupported:

- Audit obligation.
- Annual report obligation.
- Sustainability reporting.
- Cash-flow statement obligation.
- Complex notes beyond small holding AS.
- Replacement of already submitted annual accounts.
- Non-Norwegian language annual accounts without dispensation.

## Launch Schema Decisions

These decisions are the source-backed launch schema for a simple holding AS. A row marked `blocked` must not be treated as production-ready.

| Authority requirement | Source evidence | Talli source data | Launch decision |
| --- | --- | --- | --- |
| Reporting obligation and deadline | Brønnøysund states reporting-obligated enterprises must submit a complete annual-account set by 31 July, and the tax return is a separate obligation. | `companies`, `annual_data`, `filing_readiness_snapshots` | Supported as readiness/deadline data. |
| RR-0002 main form | Brønnøysund official Postman example exposes `dataFormatId=1266`, `dataFormatVersion=51820`, and key hovedskjema orids. | `companies`, `annual_data`, `authority_permissions`, future accountant/auditor metadata | Evidence mapped for simple holding AS; production still blocked until TT02 validation. |
| Accounting currency and scale | Official Postman example exposes `valuta` orid `34984`. | Ledger amounts currently stored as NOK numeric values. | Supported for NOK/whole-kroner launch only; other currencies/scales blocked. |
| Income statement figures | Official Postman example exposes result tags/orids including `sumDriftskostnad`, `sumFinansinntekter`, `resultatFoerSkattekostnad`, and `aarsresultat`. | `ledger_entries.lines`, annual preview totals | Evidence mapped for aggregate launch fields; implementation slice needed. |
| Balance-sheet figures | Official Postman example exposes balance tags/orids for investments, bank/cash, equity, and debt. | `ledger_entries.lines`, opening balance, investment register | Evidence mapped for simple holding AS fields; implementation slice needed. |
| Small-enterprise notes | Official Postman example exposes `antallAarsverk` orid `37467`. | `annual_data`, future note records | Evidence mapped; implementation needs annual full-time equivalents field, default `0` for no employees/payroll. |
| Attachments | Altinn says small enterprises with no audit obligation generally do not need annual report/cash-flow attachments, while non-small cases require notes, annual report, cash-flow statement and usually auditor report as file attachments. | `documents` metadata/object references | Supported only as readiness metadata; production attachment payload is blocked. |
| Confirmation/signing | Altinn says sender confirms the annual accounts are approved by the competent body; it then goes to signing/submission. | `annual_data.general_meeting_approved`, `authority_permissions` | Readiness supported; production signing flow blocked until Altinn 3/Regnskapsregisteret flow is tested. |
| Receipt/decision | Altinn/Brønnøysund state the enterprise receives electronic feedback/decision in Altinn inbox after processing. | `filing_submissions`, archive receipt state | Simulation only; official receipt retrieval/storage is blocked. |

## Mapping to Current Engine

Current engine coverage:

- Balance preview: partial.
- Income statement preview: partial.
- General meeting approval readiness: covered.
- Bank/document warnings: partial.
- Simulated receipt: covered for simulation only.
- RR-0002 field payload map: implemented for the narrow simple-holding slice.
- Altinn instance/token/data/validation/confirm boundary: implemented for TT02
  only; local fake-transport contract evidence only.

Missing before a live TT02 rehearsal:

- Complete RR-0002 XML rendering from the mapped fields.
- Annual-account note model.
- Attachment payload handling.
- Crash-safe orchestration and a private evidence journal.

Missing before production:

- Accepted live TT02 validation of mapped fields.
- Proven hybrid owner review/ID-porten signing.
- Official receipt storage.

Current annual preview field decisions:

| Current preview field | Authority mapping decision |
| --- | --- |
| Bank balance | Mapped to `sumBankinnskuddKontanter/aarets` / orid `29042`; live TT02 validation pending. |
| Share investments | Narrow fallback mapped to `investeringAksjerAndeler/aarets` / orid `7100`; unclear classifications remain blocked. |
| Share capital | Aggregate mapped to `sumInnskuttEgenkapital/aarets` / orid `3730`; detailed capital/note rendering remains pending. |
| Retained earnings | Mapped to `annenEgenkapital/aarets` / orid `3274`; result allocation and prior-year confirmation remain blocking controls. |
| Dividend/gain income | Aggregate mapped to `sumFinansinntekter/aarets` / orid `153`; detailed classification remains conservative. |
| Admin costs | Aggregate mapped to `sumDriftskostnad/aarets` / orid `17126`; detailed rendering remains pending. |
| Result before tax | Derived display value only; not enough for production payload. |
| General meeting approval | Supported readiness confirmation; not enough for production signature. |

## Production Blockers

- Confirm exact Altinn 3/Regnskapsregisteret machine-submission API contract.
- Confirm whether owner-managed direct filing can use ID-porten-only, system-user-only, or hybrid flow.
- Confirm required payload schemas and attachment restrictions for a small holding AS.
- Confirm feedback and receipt retrieval behavior.
- Validate in test environment before production.

## Follow-Up Implementation Slices

1. Add complete RR-0002 XML rendering and schema/evidence fixtures for the narrow payload map.
2. Add annual-account note model, starting with annual full-time equivalents and small-enterprise note confirmations.
3. Add attachment rules for no-audit small AS versus non-small/audit cases.
4. Add crash-safe orchestration/private journaling around the TT02-only adapter.
5. Run the documented TT02 hybrid-flow rehearsal after explicit scope/right/customer approval, then persist validation and archive evidence.
