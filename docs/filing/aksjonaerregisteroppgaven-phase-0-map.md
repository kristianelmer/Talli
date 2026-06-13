# Aksjonærregisteroppgaven Phase 0 Map

Status: Phase 0 research map  
Research date: 2026-06-12  
Target filing: `aksjonærregisteroppgaven` / RF-1086  
Implementation target: first Python filing-engine milestone for Talli

This document maps the official public surface that is enough to start a filing simulation. It is not a production filing specification. Production filing still requires official test-environment validation and access to Skatteetaten/Altinn/Digdir flows.

## Sources

Primary official sources:

- Skatteetaten API docs: https://skatteetaten.github.io/api-dokumentasjon/api/innrapportering-aksjonaerregisteroppgave
- Raw API docs source: https://raw.githubusercontent.com/Skatteetaten/api-dokumentasjon/main/docs/api/innrapportering-aksjonaerregisteroppgave.md
- Hovedskjema XSD: https://raw.githubusercontent.com/Skatteetaten/api-dokumentasjon/main/static/download/aksjonaerregisteroppgaveHovedskjema.xsd
- Underskjema XSD: https://raw.githubusercontent.com/Skatteetaten/api-dokumentasjon/main/static/download/aksjonaerregisteroppgaveUnderskjema.xsd
- Skatteetaten RF-1086 page: https://www.skatteetaten.no/skjema/rf-1086-aksjonarregisteroppgaven/
- Skatteetaten examples: https://www.skatteetaten.no/bedrift-og-organisasjon/rapportering-og-bransjer/aksjonarregisteroppgaven/eksempler-pa-utfylling-av-aksjonarregisteroppgaven/
- Altinn RF-1086 page: https://info.altinn.no/skjemaoversikt/skatteetaten/aksjonarregisteroppgaven/

Local copied artifacts:

- [aksjonaerregisteroppgaveHovedskjema.xsd](./aksjonaerregisteroppgaveHovedskjema.xsd)
- [aksjonaerregisteroppgaveUnderskjema.xsd](./aksjonaerregisteroppgaveUnderskjema.xsd)

## Current Official Submission Model

Skatteetaten states that from June 2026 all AS companies must submit `aksjonærregisteroppgaven` through an end-user system, and this also applies to correction reports for 2025 and earlier years.

Altinn states that, for the older Altinn flow, deadline is 31 January 2026 and a company may submit as many times as needed, with the latest submitted statement becoming the current statement. That resubmission behavior must be re-verified for the end-user-system API before production launch.

## API Shape

The official API docs describe five endpoints:

1. `POST hovedskjema`
   - Receives RF-1086 hovedskjema.
   - Request body: XML.
   - Validated against `aksjonaerregisteroppgaveHovedskjema.xsd`.
   - Example test URL: `https://api-test.sits.no/api/aksjonaerregister/v1/{inntektsaar}/1086H`
   - Example success response:
     ```json
     {
       "hovedskjemaid": "0193de1a-d956-739e-980e-ab57ae7de73c"
     }
     ```

2. `POST underskjema`
   - Receives one RF-1086-U underskjema per shareholder/share-class context.
   - Request body: XML.
   - Validated against `aksjonaerregisteroppgaveUnderskjema.xsd`.
   - Example test URL: `https://api-test.sits.no/api/aksjonaerregister/v1/{inntektsaar}/{hovedskjemaid}/1086U`
   - Example success response: `200 OK`, no data body.

3. `POST bekreft`
   - Confirms that all underskjema have been submitted and the statement is ready for processing.
   - Example test URL: `https://api-test.sits.no/api/aksjonaerregister/v1/{inntektsaar}/{hovedskjemaid}/bekreft?antall_underskjema={count}`
   - Example success response:
     ```json
     {
       "oppgavegiversLeveranseReferanse": "0193de1a-d956-739e-980e-ab57ae7de73c",
       "dialogId": "0193d51a-ec30-7d58-b727-6ce65964d3d4",
       "forsendelseId": "0193de1b-0483-740a-9e0b-f60a2d519638"
     }
     ```

4. `GET dokumenter`
   - Retrieves multiple documents from a submission.
   - API docs say it can deliver up to 50 forms per call and hovedskjema is always first form on the first page.

5. `GET dokument`
   - Retrieves a single document from a submission, recommended for feedback documents.

## Auth and Access

Scope:

- `skatteetaten:innrapporteringaksjonaerregisteroppgave`

Access requirements from API docs:

- Skatteetaten must grant access to the scope.
- API requires system access with system user in Maskinporten/Digdir.
- System user can use access packages or a single right.

Access packages listed in the API docs:

- `urn:altinn:accesspackage:regnskapsforer-med-signeringsrettighet`
- `urn:altinn:accesspackage:regnskapsforer-uten-signeringsrettighet`
- `urn:altinn:accesspackage:ansvarlig-revisor`
- `urn:altinn:accesspackage:revisormedarbeider`
- `urn:altinn:accesspackage:skattegrunnlag`

Single-right resource listed in the API docs:

- `urn:altinn:resource = ske-innrapportering-aksjonaerregisteroppgave`

Phase 0 implication:

- Filing simulation can ignore auth.
- Production filing cannot proceed until Talli has scope access and a tested system-user flow.

## Idempotency

`idempotencyKey` is required.

Rules from API docs:

- Must be a unique UUID.
- Every new API call gets a new `idempotencyKey`.
- Repeated POST calls with identical request body and identical key return the same response, and only the first is processed.

Engine implication:

- Production submission state must store one idempotency key per API call.
- Retry logic must reuse the same key only for the same body and same logical call.

## Request Content Types

Confirmed from error-code docs:

- `Accept` must be `application/json`.
- `Content-Type` must be `application/xml`.
- Request payload is XML.
- Response metadata is JSON.

## Test Environment Notes

API docs identify test requirements:

- Use `api-test.sits.no` URLs from SwaggerHub/test docs.
- Altinn TT02 is used for Dialogporten, system registration, system users, access management, authorization, and inbox.
- Maskinporten has its own test environment.
- Maskinporten client must be created on a real organization number even in test.
- Test submissions must use synthetic test data from Tenor.
- Real/sharp data must not be used in test due to GDPR requirements.

Phase 0 implication:

- Public-data validation can use anonymized/public fixtures for simulation.
- Official integration tests must use synthetic Tenor data, not real public-company data.

## Filing Structure

RF-1086 is split into:

- `hovedskjema`: company/share-class level statement.
- `underskjema`: shareholder level statement.

The XSD documentation says companies submit one `aksjonærregisteroppgave` per share class. For companies with multiple share classes, separate company/shareholder data must be reported for each class. Talli launch supports one share class only.

## Hovedskjema Launch Subset

Root attributes:

- `skjemanummer="890"`
- `spesifikasjonsnummer="12144"`
- `blankettnummer="RF-1086"`
- `tittel="Aksjonærregisteroppgaven"`
- `gruppeid="2586"`
- `etatid="974761076"`

Required top-level groups in XSD:

- `GenerellInformasjon-grp-2587`
- `Selskapsopplysninger-grp-2589`

Optional top-level groups used by launch subset:

- `Utbytte-grp-3449`
- `UtstedelseAvAksjerIfmStiftelseNyemisjonMv-grp-3452`

Top-level groups intentionally out of launch scope:

- `UtstedelseAvAksjerIfmFondsemisjonSplittMv-grp-3454`
- `SlettingAvAksjerIfmLikvidasjonPartiellLikvidasjonMv-grp-3456`
- `SlettingAvAksjerIfmSpleisSkattefriFusjonFisjon-grp-3458`
- `EndringerIAksjekapitalOgOverkurs-grp-3460`, except later if simple capital increase by nominal-value increase is explicitly supported after modelling.

### Company Identity

`Selskap-grp-2588` fields relevant to launch:

- `EnhetOrganisasjonsnummer-datadef-18`
- `EnhetNavn-datadef-1`
- `EnhetAdresse-datadef-15`
- `EnhetPostnummer-datadef-6673`
- `EnhetPoststed-datadef-6674`
- `AksjeType-datadef-17659`
- `Inntektsar-datadef-692`

Launch assumptions:

- `AksjeType` = ordinary shares.
- No ISIN.
- One share class.
- Company identity comes from Brønnøysund/user-confirmed setup.

### Company Share Data

`Selskapsopplysninger-grp-2589` fields relevant to launch:

- `AksjekapitalForHeleSelskapet-grp-3443`
  - previous year share capital
  - current year share capital
- `AksjekapitalIDenneAksjeklassen-grp-3444`
  - previous/current share capital for the class
- `PalydendePerAksje-grp-3447`
  - previous/current nominal value per share
- `AntallAksjerIDenneAksjeklassen-grp-3445`
  - previous/current number of shares
- `InnbetaltAksjekapitalIDenneAksjeklassen-grp-3446`
  - previous/current paid-in share capital
- `InnbetaltOverkursIDenneAksjeklassen-grp-3448`
  - previous/current paid-in premium

Validation implications:

- Previous/current balances must be explicit, including zero for new companies.
- Sum of shareholder closing share counts must equal company closing share count.
- One share class means whole-company and share-class figures should match.

### Company Dividend Data

`Utbytte-grp-3449` contains one or more `UtdeltSkatterettsligUtbytteILopetAvInntektsaret-grp-3451`.

Fields relevant to launch:

- `AksjeUtbytteISINAksjetype-datadef-17665`
- `AksjeUtbyttePerAksje-datadef-23946`
- `AksjeUtbytteHendelsestype-datadef-36564`
- `AksjeUtbytteTidspunkt-datadef-17667`

XSD help text states this is tax-law dividend, includes transfers from company to shareholder under the relevant dividend rule, and the time is the general meeting decision time. Each dividend distribution must be reported separately.

Launch assumptions:

- Simple cash dividend only.
- Same share class.
- Equal dividend per share.
- General meeting decision timestamp is required.
- Shareholder-level dividend records must match company-level distributions.

### Company Share Issuance / Formation

`UtstedelseAvAksjerIfmStiftelseNyemisjonMv-grp-3452` -> `AntallNyutstedteAksjer-grp-3453`.

Fields relevant to launch:

- `AksjerNyutstedteStiftelseMvAntall-datadef-17668`
- `AksjerStiftelseMvAntall-datadef-17669`
- `AksjerNyutstedteStiftelseMvType-datadef-17670`
- `AksjerNyutstedteStiftelseMvTidspunkt-datadef-17671`
- `AksjerNyutstedteStiftelseMvPalydende-datadef-23947`
- `AksjerNyutstedteStiftelseMvOverkurs-datadef-23948`

Official example uses event code `N` for stiftelse/new issuance in the API XML example. Code lists need verification from rettledning/API examples before implementation hard-codes all event code meanings.

Launch supported:

- Stiftelse with cash share capital.
- Simple capital increase only if it maps cleanly to this group and matching shareholder acquisition rows.

## Underskjema Launch Subset

Root attributes:

- `skjemanummer="923"`
- `spesifikasjonsnummer="12232"`
- `blankettnummer="RF-1086-U"`
- `tittel="Aksjonærregisteroppgaven - underskjema"`
- `gruppeid="3983"`
- `etatid="974761076"`

Launch uses one underskjema per shareholder in the one supported share class.

### Shareholder Identity

`SelskapsOgAksjonaropplysninger-grp-3987` contains:

- `Selskapsidentifikasjon-grp-3986`
- `NorskUtenlandskAksjonar-grp-3988`

Supported shareholder identity fields:

- Norwegian personal shareholder:
  - `AksjonarFodselsnummer-datadef-1156`
- Norwegian corporate shareholder:
  - `AksjonarOrganisasjonsnummer-datadef-7597`

Other fields in XSD but out of launch scope:

- `AksjonarUtenlandskIdenifikasjonsnummer-datadef-26626`
- foreign address/country fields

Launch policy:

- Foreign shareholders are needs-accountant / unsupported for owner-managed direct filing.

### Share Count and Dividend Data

`AntallAksjerUtbytteOgTilbakebetalingAvTidligereInnbetaltKapit-grp-3990` contains:

- `AntallAksjerPerAksjonar-grp-3989`
- `UtdeltUtbyttePerAksjonar-grp-3991`
- `UtdeltUtbytteKildeskatt-grp-9347`
- `TilbakebetalingAvTidligereInnbetaltKapital-grp-7633`

Launch uses:

- `AntallAksjerPerAksjonar-grp-3989`
  - `AksjerAntallFjoraret-datadef-29168`
  - `AksjonarAksjerAntall-datadef-17741`
- `UtdeltUtbyttePerAksjonar-grp-3991`
  - `Aksjeutbytte-datadef-29169`
  - `AksjerUtbytteAntall-datadef-17742`
  - `AksjerUtbytteTidspunkt-datadef-17769`
  - `AutomatiskMotregningOnskerIkke-datadef-37159`

Launch excludes:

- `UtdeltUtbytteKildeskatt-grp-9347`
- `TilbakebetalingAvTidligereInnbetaltKapital-grp-7633`

Validation implications:

- Each shareholder gets previous and current share count.
- Current shareholder share counts must sum to company current share count.
- Dividend per shareholder must reconcile to company dividend event.
- Foreign withholding tax blocks launch filing.

### Share Acquisition Events

`Transaksjoner-grp-3992` -> `KjopArvGaveStiftelseNyemisjonMv-grp-3993` -> `AntallAksjerITilgang-grp-3998`.

Fields relevant to launch:

- `AksjerKjopAntall-datadef-12153`
- `AksjeErvervType-datadef-17745`
- `AksjerErvervsdato-datadef-17746`
- `AksjeAnskaffelsesverdi-datadef-17636`
- `AksjonarTidligereFodselsnummer-datadef-26530`
- `AksjonarTidligereOrganisasjonsnummer-datadef-26531`

Official Skatteetaten examples state:

- Stiftelse is reported on company level post 9 and shareholder level post 23.
- Share sale is reported on seller shareholder post 25 with transaction type `salg`, and buyer shareholder post 23 with transaction type `kjøp`.

Launch supported:

- Stiftelse.
- Simple purchase/acquisition in a share transfer.
- Simple capital increase acquisition if company-level event is supported.

Prototype note:

- The first simulation engine uses `N` for stiftelse because this appears in the official API example.
- The first simulation engine uses provisional `K` for simple kjøp and `S` for simple salg, and `U` for dividend event type.
- These provisional codes are XSD-valid because the current XSD type is text, but they must be verified against rettledning/code lists before production filing.

### Share Disposal Events

`SalgArvGaveLikvidasjonPartiellLikvidasjonMv-grp-3995` -> `AksjerIAvgang-grp-4002`.

Fields relevant to launch:

- `AksjerArvMvOmsattAntall-datadef-17752`
- `AksjerArvMvOmsattType-datadef-17753`
- `AksjerArvMvOmsattTidspunkt-datadef-17754`
- `AksjerArvMvOmsatt-datadef-17755`
- `AksjonarOvertakendeFodselsnummer-datadef-26532`
- `AksjonarOvertakendeOrganisasjonsnummer-datadef-26533`

Launch supported:

- Simple sale between Norwegian shareholders.

Launch excludes:

- inheritance/gift variants,
- liquidation,
- partial liquidation,
- own-share deletion,
- taxable merger/demerger,
- transfer with tax continuity unless explicitly modelled later.

## Launch-Supported Scenarios

### Scenario 1: No Activity Year

Inputs:

- company identity,
- previous/current company share capital,
- previous/current share count,
- previous/current nominal value,
- shareholders,
- previous/current share count per shareholder.

Expected output:

- one hovedskjema,
- one underskjema per shareholder,
- no transaction groups beyond balances,
- readiness confirmation that no share events, dividends, or shareholder loans occurred.

### Scenario 2: Stiftelse

Inputs:

- company identity,
- incorporation/stiftelse date from signed founding document,
- share capital,
- number of shares,
- nominal value,
- paid-in capital,
- paid-in premium,
- founding shareholders and acquisition values.

Expected output:

- hovedskjema with zero previous balances and current balances,
- company-level post 9 issuance,
- shareholder-level post 23 acquisition for each founder,
- one underskjema per founder.

Skatteetaten example note:

- Stiftelse must be reported both on company and shareholder level.
- If only one share class exists, it is registered as ordinary shares.
- Post 1-5 previous balances are zero.
- Date of signing the founding document is decisive, not registration time in Foretaksregisteret.
- A statement is required for the founding year even if the company had no activity.

### Scenario 3: Simple Share Sale

Inputs:

- seller,
- buyer,
- number of shares,
- price/consideration,
- transfer timestamp,
- previous/current ownership.

Expected output:

- seller underskjema post 25 disposal,
- buyer underskjema post 23 acquisition,
- both rows use same number of shares and same timestamp,
- seller/buyer previous/current share counts reconcile to company count.

Skatteetaten example note:

- Sold shares are reported on seller post 25 as disposal with transaction type `salg`.
- Bought shares are reported on buyer post 23 as acquisition with transaction type `kjøp`.
- Number of shares, consideration/acquisition value, and time must be reported.

### Scenario 4: Simple Cash Dividend to Owners

Inputs:

- dividend decision timestamp,
- total dividend,
- dividend per share,
- shareholders/share count at decision/payment basis,
- payment optional for shareholder-register purpose but required in Talli workflow for bank reconciliation.

Expected output:

- company-level dividend distribution in post 8,
- shareholder-level dividend in post 21,
- company total equals sum of shareholder dividends,
- no withholding tax.

### Scenario 5: Simple Capital Increase

Status: launch-candidate, needs further code-list and example verification.

Required before implementation:

- identify exact event code for simple cash capital increase,
- decide whether it belongs under company post 9 or post 15 depending event shape,
- verify matching shareholder-level post 23 or post 29 mapping.

Until verified, simple capital increase should be marked simulation-only or needs-accountant.

## Timing Rules

XSD help text emphasizes identical timestamps between company-level and shareholder-level records for the same event. If timestamps differ, the statement can fail controls in Aksjonærregisteret.

Rule for Talli:

- Store event timestamp as a first-class value.
- Reuse identical timestamp across all generated company/shareholder XML nodes for the same event.
- Default time can be `12:00:00` only where no same-day ordering conflict exists and official guidance permits default time.

## Validation Rules for First Engine

Hard validations:

- company is AS,
- one share class only,
- no foreign shareholders,
- all shareholders have Norwegian fødselsnummer or organisasjonsnummer,
- company previous/current share counts are non-negative integers,
- shareholder previous/current share counts are non-negative integers,
- sum shareholder current share count equals company current share count,
- sum shareholder previous share count equals company previous share count,
- one underskjema per shareholder with shares at year end or who owned shares during the year,
- all event timestamps that represent the same event are identical,
- no unsupported groups are required by input case,
- dividend total reconciles between company and shareholder records,
- `bekreft` count equals number of generated underskjema.

Warnings/escalations:

- capital increase before exact event-code mapping is verified,
- manual override of any filing field,
- shareholder loan flag, until mapping to RF-1086/rettledning is confirmed,
- same-day multiple events without explicit ordering/time,
- prior-year figures missing for existing company.

Blocks:

- multiple share classes,
- foreign shareholder,
- withholding tax,
- inheritance/gift,
- merger/demerger,
- liquidation,
- non-cash consideration,
- own-share transactions,
- capital reductions,
- corrections/amendments.

## Proposed Python Domain Model

First pass models:

```text
Company
  org_number
  name
  address
  postal_code
  city
  income_year
  share_class = ordinary

ShareClassSnapshot
  previous_share_capital
  current_share_capital
  previous_nominal_value
  current_nominal_value
  previous_share_count
  current_share_count
  previous_paid_in_share_capital
  current_paid_in_share_capital
  previous_paid_in_premium
  current_paid_in_premium

Shareholder
  kind = norwegian_person | norwegian_company
  national_id | org_number
  name

ShareholderSnapshot
  shareholder
  previous_share_count
  current_share_count

ShareEvent
  event_id
  type = formation | sale | acquisition | dividend | capital_increase_candidate
  timestamp
  parties
  share_count
  amount
  source_document_refs

DividendEvent
  timestamp
  total_amount
  per_share_amount
  shareholder_allocations

Rf1086Filing
  hovedskjema
  underskjema[]
  readiness_report
```

Generated XML should be a projection from these models, not the primary domain model.

## Proposed CLI Milestone

First CLI should support:

```text
simulate-aksjonaerregister --case tests/fixtures/rf1086/no_activity.json
simulate-aksjonaerregister --case tests/fixtures/rf1086/stiftelse.json
simulate-aksjonaerregister --case tests/fixtures/rf1086/share_sale.json
simulate-aksjonaerregister --case tests/fixtures/rf1086/dividend.json
validate-rf1086-xml --hovedskjema out/1086H.xml --underskjema out/1086U-*.xml
```

Validation should include:

- Pydantic/domain validations.
- XSD validation against local official XSD files.
- golden output snapshots where stable.

## Error Handling Map

API error families from official docs:

- `GLD_004` / `GLD_1007` / `GLD_1008`: authentication/token.
- `GLD_005` / `GLD_1015`: authorization.
- `GLD_006` / `GLD_1022`: request parameter errors.
- `GLD_008`: structural data-format error.
- `GLD_010`: payload validation error.
- `GLD_011`: metadata.
- `GLD_019`: idempotency key used previously.
- `GLD_1016`: hovedskjema id not found or wrong taxpayer/year.
- `GLD_1018`: underskjema count mismatch.
- `GLD_1026`: cannot confirm without at least one underskjema.
- `GLD_1029`: submission already confirmed.
- `GLD_1030`: wrong Accept header.
- `GLD_1031`: wrong Content-Type header.

Product implication:

- Most API errors should become specific unsupported/authorization/retry messages, not generic failure toasts.
- `GLD_1018` maps directly to Talli readiness/submission-state bug.
- `GLD_1029` maps to immutable submission state.

## Open Questions Before Coding Production Paths

These do not block simulation but block production direct filing:

1. SwaggerHub OpenAPI details:
   - exact endpoint paths,
   - headers,
   - parameter names/casing,
   - pagination model for `GET dokumenter`,
   - document response schemas.

2. Code lists:
   - exact code values for `kjøp`, `salg`, `stiftelse`, `nyemisjon`, and dividend event type.
   - whether code lists are only in rettledning/PDF examples or available as machine-readable lists.

3. Capital increase mapping:
   - post 9 vs post 15 and shareholder post 23 vs post 29 for simple cash capital increase.

4. Shareholder loan reporting:
   - exact RF-1086 field implications, if any, for the launch subset.

5. Resubmission/correction behavior:
   - whether latest submission wins under end-user-system API as Altinn page states for older flow.

6. System-user product design:
   - whether Talli can support owner-managed filing directly or needs a system-user/access-package onboarding UX that is too complex for launch.

## Phase 0 Conclusion

There is enough official public information to start `aksjonærregisteroppgaven` filing simulation:

- XSDs are public.
- API flow is public at a high level.
- Example XML is public.
- Skatteetaten examples describe the launch scenarios of stiftelse and simple sale.
- Test environment approach is documented.

The first engine should not implement production API calls yet. It should generate RF-1086/RF-1086-U XML for no-activity, stiftelse, simple sale, and simple dividend cases, validate against XSD, and produce a Norwegian filing preview/readiness report.
