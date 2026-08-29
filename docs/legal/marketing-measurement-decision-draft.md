# Marketing Measurement Decision Draft

Status: founder product directions approved; exact text and deployed facts still
require legal/privacy review

Issue: #196

Last checked: 2026-08-29

Current implementation evidence: source revision
`a43a0d24db65001741356fdd9fffc8ea6c442aef`

This document separates official-source requirements from product-design
inference. It does not approve publication, change the digest-pinned privacy
notice, authorize tracking, or replace legal review.

## Recorded Founder Product Decision

Kristian Elmer approved the recommended **no longitudinal marketing cohort for
launch** direction on 2026-08-29. This approval means:

- the optional marketing session remains limited to 30 minutes;
- marketing measurement is not joined to an account, company, purchase,
  company-year, support case or refund;
- later operational outcomes may be reported only as separately governed coarse
  totals, without source attribution or a reversible cohort key; and
- source-attributed company-year/refund rates and purchase-to-completion timing
  remain `null`.

This is a product-minimization decision. It is not approval of the exact notice,
the processor schedule, a legal classification, publication, deployment or
activation. Those gates remain below.

## Recorded Founder Checklist Decision

On 2026-08-29 Kristian Elmer approved the product direction for all twelve
plain-language review points presented for this measurement boundary:

- use measurement only to learn where the public company check and onboarding
  succeed or stop;
- keep the service fully usable after refusal and do nothing optional before
  affirmative consent;
- keep the public measurement payload to a random session identifier and fixed,
  bounded event fields, with no name, email, organization number, free text,
  documents, bank, accounting or financial data;
- describe the identifier as a random session ID rather than claiming the
  measurement is anonymous;
- keep the browser session at 30 minutes, raw events at no more than 90 days and
  the withdrawal tombstone at no more than 30 minutes;
- add a minimized consent proof containing time, consent/notice version and
  digest, and the random session hash, without an account or company link;
- stop collection and request raw-session deletion on withdrawal, with a safe
  retry if the first deletion request fails;
- suppress repeated-signal reporting below five separate sessions rather than
  the previously implemented threshold of two;
- give acceptance and refusal equal visual prominence and one action each;
- never link public marketing measurement to account, company, purchase,
  company-year, support or refund data;
- keep activation blocked until the exact deployed provider, logging, backup,
  region, recipient, transfer and privileged-access facts have been verified;
  and
- identify ELMER WELFIS / Talli as controller and `post@talli.no` as the privacy
  contact, subject to the final legal-name/contact and DPO applicability check.

This records founder product choices and required launch conditions. It does not
assert that the provider facts have been verified, approve a legal
classification, approve the exact notice text/digests, or authorize activation.

## Temporary Invited-Pilot Evaluation Mode

Kristian also approved a separate, higher-resolution evaluation mode for the
first invited testing phase so Talli can determine whether the product works
sufficiently. This is validation evidence, not an expansion of public marketing
analytics, and it must be disabled for full public launch.

The implementation and operating design must enforce all of these conditions:

- the pilot runs the exact normal production product: the same build, routes,
  screens, calculations, eligibility rules, authorization checks, capability
  gates, provider adapters and error behavior; there is no test-product branch;
- the setting controls only whether a passive observer writes a bounded log
  after a normal product outcome; it cannot unlock, block, alter, retry, replace
  or simulate a product action;
- mode is deny-by-default and has only `off` and `invited-pilot` states;
- `invited-pilot` requires a server-side named pilot entitlement, an approved
  validation run ID, a start time and a mandatory expiry; a browser flag, query
  parameter or client request cannot enable it;
- evidence uses case codes `V-01` through `V-12`; any mapping to a participant or
  company stays only in the approved protected participant register and never in
  the public marketing-measurement store;
- the bounded evaluation record may capture critical task started/completed/
  failed/blocked state, step and reason code, elapsed duration, intervention
  count/type/duration, defect or difference classification, rerun result and
  final filing-package outcome;
- the evaluation stream must not contain names, email addresses, organization
  numbers, free text, document contents, filenames, bank/account facts, ledger
  values, exact monetary amounts or source marketing attribution;
- invited participants receive the exact validation information and agreement
  before the mode observes their work, including purpose, fields, retention,
  withdrawal, export and deletion expectations;
- raw pilot observations have a separately approved retention period, access is
  limited to named validation reviewers, and reporting uses the approved case
  matrix rather than public marketing reports;
- an observation-write failure never changes, rolls back or hides the normal
  product result. It marks that test observation incomplete and must be resolved
  or rerun before the affected acceptance can pass;
- withdrawal stops new observation and follows the protected-register deletion
  workflow without weakening legal-hold or incident obligations; and
- the full-launch gate must prove the mode is `off`, all pilot entitlements are
  expired or revoked, no public request can enable it, and disabling it preserves
  only the evidence whose retention was explicitly approved.

Before pilot intake, an equivalence test must run the same representative normal
product actions with observation `off` and `invited-pilot` and prove identical
product responses, persisted business state and external calls. The sole permitted
difference is the additional bounded observation-log write. Turning the setting
off for full launch therefore removes only that write, not product functionality.

The 2+8 validation plan defines whether the product is sufficient: every
critical journey completes, at least 90% of core tasks complete without help,
median support is below 30 minutes per company-year, and no unexplained material
difference, duplicate or incident remains. The temporary mode may gather the
bounded observations needed for those decisions; it must not silently invent a
different success standard.

## Current Implemented Boundary

The current local implementation:

- stores a consent record and random session identifier in `sessionStorage`
  only after an affirmative choice;
- links one allowlisted event sequence for at most 30 minutes;
- sends bounded event, surface, source, reason and consent-version fields to a
  first-party endpoint;
- rejects personal, company, financial, document, page-address and free-text
  fields;
- retains raw measurement rows for no more than 90 days;
- stops collection on withdrawal, retries deletion and keeps a short-lived
  tombstone so late requests cannot recreate withdrawn rows; and
- exposes aggregates rather than raw identifiers to operators.

The implementation intentionally returns `null` for company-year completion,
refund and purchase-to-completion cohort measures. A 30-minute session cannot
truthfully link a months-long company-year lifecycle.

## Implementation-Derived Data Inventory

This inventory is derived from source revision
`a43a0d24db65001741356fdd9fffc8ea6c442aef`. It describes application-controlled
behavior only. It does not establish what a deployed CDN, hosting platform,
database provider, proxy, backup system or incident tool logs or retains.

| Layer | Application-controlled fields and behavior | Retention / access | Review state |
| --- | --- | --- | --- |
| Browser consent state | `sessionStorage` key `talli.marketing-consent.v1` contains consent version, random UUID session ID, allowlisted campaign source, expiry timestamp and whether `home_view` was queued. It is created only after affirmative consent. | One browser tab; expires after 30 minutes and is removed by expiry or withdrawal. | Implemented and tested. Treat the UUID as pseudonymous/personal pending the Recital 26 assessment. |
| Browser withdrawal retry | `sessionStorage` key `talli.marketing-withdrawal.v1` contains only the random session UUID while deletion confirmation is pending. | Removed after confirmed deletion; otherwise retained in the tab for retry. | Implemented and tested. Legal review must confirm the retry state is strictly necessary for honoring withdrawal and how long an abandoned tab may retain it. |
| Campaign input | The application reads only the `source` query parameter and maps it to `organic`, `community`, `partner`, `approved_campaign`, `direct` or `unknown`. The raw value and full page URL are not included in the measurement payload. | The bounded value follows the 30-minute session and event retention below. | Application minimization is implemented. Deployed access logs may still contain the original URL/query and remain unverified. Campaign URLs must never contain identity or company data. |
| Same-origin browser request | POST payload fields are `clientEventId`, `anonymousSessionId`, literal `consent: true`, `consentVersion`, bounded `event`, nullable bounded `reason`, bounded `surface` and bounded `campaignSource`. Withdrawal sends only the session UUID. Bodies are JSON and limited to 2,048 bytes. | Sent only after consent to `/api/marketing-events`; responses are `no-store`. | Implemented and tested. The application rejects unknown fields, free text, page address and personal/company/financial/document fields. |
| HTTP/runtime metadata | The Next route checks Origin, Content-Type and Content-Length. The application does not read or persist IP address, User-Agent, Referer, cookies or account identity for measurement. | Unknown at CDN, hosting, proxy, runtime and security-log layers. | Must be verified from deployed configuration and contracts. “Not used by application code” is not a no-log claim. |
| Internal transport | The Next server hashes the random session UUID with SHA-256 and sends the hash, client event UUID, consent version and bounded event/reason/surface/source through the generated client to the FastAPI backend. An internal server key authenticates this hop. | Request-time only unless infrastructure logs it. | Implemented and tested. Raw UUID should remain at the browser/Next boundary; log redaction and secret handling require deployed verification. |
| Raw database event | Private `backend_system.marketing_funnel_events` rows contain an identity key, client event UUID, 64-character session hash, consent version, event, reason, surface, source, receive time and expiry time. Direct `anon`, `authenticated` and `service_role` access is revoked; forced RLS applies. | Each row expires no later than 90 days after receipt; purge runs during ingest/report/maintenance. Only restricted ingest/report roles execute typed functions. | Local database/runtime evidence passed. Hosted migration, backup copies, privileged access and purge scheduling/monitoring remain separate gates. |
| Withdrawal tombstone | Private `backend_system.marketing_funnel_withdrawals` contains session hash, withdrawal time and expiry. Withdrawal deletes matching raw events before writing/updating the tombstone. | Tombstone lifetime is at most 30 minutes and is purged by the same maintenance function. | Implemented and tested. It prevents a late request from recreating the withdrawn session during the active window. |
| Operator report | Counts by bounded event, short-session conversion/unsupported rates, one short-session median, support counts by surface and repeated bounded reason signals. Raw session hashes and event rows are not returned. Company-year/refund/long-cycle fields remain `null`. | Computed from live retained rows; no separate report table is implemented. Operator access requires verified active-operator status. | Implemented and tested. Founder-approved repeated-signal suppression now requires at least five observations. Broader report privacy review remains required before activation. |
| Consent evidence | Each accepted event carries `marketing-analytics-v1`; the browser consent object records version and expiry. There is no separate durable consent-action record binding the exact first-layer/full-notice digest to the action. | Browser state lasts at most 30 minutes; event rows at most 90 days. | Insufficient for a final demonstrability claim until legal/privacy review approves a minimized proof design and the released notice digest/version is bound and tested. |
| Backups, provider logs and recipients | No application source establishes production backup retention, CDN/platform/database log fields, processor identities, processing regions or transfer mechanisms. | Unknown. | Must remain explicitly pending until checked against the exact deployed services, settings and contracts. |

### Data-flow boundary

`browser tab → same-origin Next route → generated internal API client → FastAPI
backend → private PostgreSQL functions/table → aggregate-only operator view`

No application-controlled step joins the session to login, account, company,
purchase, support case, refund, filing or company-year identity. This statement
does not extend to unverified infrastructure logs. Until the hosted facts and
Recital 26 assessment are approved, customer-facing copy must use “frivillig
bruksmåling med tilfeldig økt-ID”, not “anonym måling”.

## Official-Source Requirements

These are source findings, not product recommendations:

1. Ekomloven § 3-15 requires prior GDPR-valid consent before storing or reading
   information on user equipment unless a narrow transmission or strictly
   necessary exception applies. The requirement is technology-neutral.
   Sources: [Lovdata § 3-15](https://lovdata.no/lov/2024-12-13-76/%C2%A73-15),
   [Nkom guidance](https://nkom.no/internett/informasjonskapsler-cookies), and
   [Datatilsynet tracking guidance](https://www.datatilsynet.no/personvern-pa-ulike-omrader/internett-og-apper/bruk-av-informasjonskapsler-og-andre-sporingsteknologier/).
2. Consent must be voluntary, specific, informed, unambiguous, affirmative and
   demonstrable. Refusal and withdrawal must be as easy as acceptance, and an
   optional measurement choice cannot gate access to the service. Sources:
   [GDPR Article 7](https://eur-lex.europa.eu/eli/reg/2016/679/art_7/oj/eng),
   [Datatilsynet consent guidance](https://www.datatilsynet.no/rettigheter-og-plikter/virksomhetenes-plikter/om-behandlingsgrunnlag/samtykke/), and
   [EDPB Guidelines 05/2020](https://www.edpb.europa.eu/our-work-tools/our-documents/guidelines/guidelines-052020-consent-under-regulation-2016679_en).
3. The first layer must communicate the material consequence of the choice.
   The full notice must cover the controller, purpose and legal basis, data
   categories, recipients, transfers, retention, rights, withdrawal, complaint
   route, whether provision is optional, consequences of refusal and any
   profiling or automated decision-making. Sources:
   [GDPR Article 13](https://eur-lex.europa.eu/eli/reg/2016/679/art_13/oj/eng),
   [Datatilsynet information requirements](https://www.datatilsynet.no/rettigheter-og-plikter/virksomhetenes-plikter/informasjon-og-apenhet/hva-skal-virksomheten-gi-informasjon-om/), and
   [Datatilsynet layered-notice guidance](https://www.datatilsynet.no/personvern-pa-ulike-omrader/internett-og-apper/bruk-av-informasjonskapsler-og-andre-sporingsteknologier/1-gi-klar-og-forstaelig-informasjon-i-samtykkeboksen/).
4. Consent evidence must show when and how consent was obtained and which
   information was presented, while remaining data-minimized. Material changes
   to purpose or processing require renewed consideration and ordinarily a new
   consent/notice version. Source: EDPB Guidelines 05/2020, especially
   paragraphs 104–123.
5. A random or hashed identifier is not automatically anonymous.
   Pseudonymous data remains personal data where singling out or attribution is
   reasonably possible. Sources:
   [GDPR Article 4 and Recital 26](https://eur-lex.europa.eu/eli/reg/2016/679/oj)
   and [EDPB anonymisation/pseudonymisation overview](https://www.edpb.europa.eu/topics/ai-and-technology/anonymisation-pseudonymisation_en).
6. Purpose limitation, minimization, storage limitation and accountability
   still apply to first-party or aggregate-facing analytics. A later join of
   acquisition data to operational outcomes is secondary processing even when
   the operator sees only aggregates. Sources:
   [GDPR Articles 5–6](https://eur-lex.europa.eu/eli/reg/2016/679/oj) and
   [Datatilsynet purpose-limitation guidance](https://www.datatilsynet.no/rettigheter-og-plikter/personvernprinsippene/grunnleggende-personvernprinsipper/formalsbegrensning/).

## Current Review Gaps

The following are product/legal-review findings inferred from those sources:

- The public privacy notice currently says that Talli uses only necessary
  cookies and no marketing tracking. That is inconsistent with the optional
  measurement implementation even though measurement is consent-gated.
- The label “anonym” has not been supported by a written Recital 26 assessment
  covering session and event identifiers, timestamps, event sequences,
  allowlisted source, IP/User-Agent exposure and platform/runtime logs. Until
  that assessment passes, “frivillig bruksmåling med tilfeldig økt-ID” is the
  safer description.
- “Tillat anonym måling” uses the visually primary button while “Nei takk” uses
  a secondary treatment. Both are one click, but legal review must confirm or
  require equal visual prominence under Datatilsynet's guidance.
- The first-layer copy states data exclusions and retention but does not state
  the precise acquisition/onboarding measurement purpose.
- The linked full notice does not enumerate the actual measurement fields,
  processor/runtime-log boundary, consent basis, withdrawal effect or exact
  retention.
- Withdrawal is available wherever the global consent component is mounted,
  but the approved notice must distinguish raw-event deletion from any
  separately lawful logs, backups or irreversibly anonymized aggregates.

## Approved Founder Product Direction

The approved direction is **no longitudinal marketing cohort for launch**:

- keep the current 30-minute consented measurement session;
- keep company-year, purchase, service, support and refund records in their
  separately governed operational capabilities;
- report coarse weekly or monthly operational totals separately, suppressing
  small cells where appropriate;
- use #197 representative validation for end-to-end completion, refund and
  support evidence; and
- keep marketing-attributed company-year completion/refund rates and the
  purchase-to-completion median `null`.

This option preserves the approved minimization boundary. It produces honest
operational outcomes, but it does not claim individual or source-attributed
purchase-to-completion cohorts. The #178/#196 requirement should be explicitly
interpreted or amended accordingly by the decision owner.

### Alternative requiring separate approval and implementation

If source-attributed long-lived cohorts are mandatory, approve a new restricted
backend aggregation design before implementation:

- define a precise purpose and lawful basis for the acquisition-to-company-year
  join;
- use only a coarse purchase cohort and allowlisted source, not the browser
  session identifier;
- perform the join in a restricted job, publish thresholded aggregates and
  destroy join material as soon as the approved calculation permits;
- define small-cell suppression, retention, consent/withdrawal and deletion
  behavior; and
- update the notice, consent version, data inventory, threat/privacy assessment
  and immutable evidence.

This still processes linked data during the join. Calling it operational,
hashing a key, or exposing only aggregates does not by itself remove the legal
and privacy review. A durable browser-to-company token has the highest linkage
and deletion burden and is not recommended for launch.

## Proposed Additive Notice Section

The following Norwegian text is the exact candidate for legal/privacy review. It
contains no provider name or location claim because the production processor
schedule is not yet verified. That schedule must be completed and approved before
publication.

> ### Frivillig måling av den offentlige kundereisen
>
> Hvis du velger «Tillat bruksmåling», bruker ELMER WELFIS frivillig måling for
> å se hvor den offentlige selskapsjekken og oppstarten lykkes eller stopper.
> Talli behandler samtykkeversjon, tilfeldige økt- og hendelses-ID-er, faste
> koder for hendelse, steg, kilde og årsak, og tidspunkt. Talli sender ikke
> navn, e-post, organisasjonsnummer, fritekst, sideadresse, regnskapsdata,
> bankdata eller dokumentopplysninger til denne målingen.
>
> Målingen bruker lagring i nettleserfanen. Ingenting valgfritt lagres eller
> sendes før du samtykker. En tilfeldig økt-ID brukes i høyst 30 minutter, og
> råhendelser slettes senest etter 90 dager. Behandlingsgrunnlaget er samtykke,
> jf. personvernforordningen artikkel 6 nr. 1 bokstav a og ekomloven § 3-15.
>
> Tjenesten virker også hvis du velger «Nei takk». Du kan når som helst trekke
> samtykket tilbake i samme grensesnitt. Da stopper ny måling umiddelbart, og
> Talli ber om sletting av råhendelsene for den tilfeldige økten. Tilbaketrekking
> påvirker ikke lovligheten av behandling som skjedde før samtykket ble trukket.
>
> Opplysningene behandles av ELMER WELFIS og databehandlere som leverer database,
> hosting og nødvendig teknisk logging. Navn, behandlingssteder, lagringstider og
> eventuelle overføringsgrunnlag skal stå i den gjeldende leverandøroversikten i
> denne personvernerklæringen før målingen tas i bruk. Målingen brukes ikke til
> automatiserte avgjørelser eller individuell profilering.
>
> Du kan kontakte post@talli.no om innsyn, retting, sletting, begrensning eller
> andre personvernspørsmål, og du kan klage til Datatilsynet.

## Exact First-Layer Consent Candidate

This is the exact short-form candidate to review together with the full section:

> **Hjelp oss forbedre selskapsjekken**
>
> Hvis du vil, kan Talli måle hvor den offentlige selskapsjekken og oppstarten
> lykkes eller stopper. Målingen bruker en tilfeldig økt-ID i høyst 30 minutter
> og faste koder for hendelse, steg, kilde og årsak. Den inneholder ikke navn,
> e-post, organisasjonsnummer, sideadresse, fritekst, bank-, dokument- eller
> regnskapsdata. Råhendelser slettes senest etter 90 dager.
>
> Ingenting valgfritt lagres eller sendes før du velger «Tillat bruksmåling».
> Talli virker på samme måte hvis du velger «Nei takk». Du kan trekke samtykket
> tilbake når som helst. Les mer i personvernerklæringen.

Controls, with equal visual prominence and one action each:

- `Tillat bruksmåling`
- `Nei takk`
- `Les personvernerklæringen` → `/personvern`

## Founder/Legal/Privacy Signoff Checklist

- [ ] Confirm the controller's legal name, contact route and DPO/contact if
      applicable.
- [x] Inventory application-controlled browser keys, IDs, payload fields,
      database rows, reports, retention and access paths in the table above.
- [ ] Confirm deployed HTTP/CDN/proxy/runtime/database logs, backups, recipients,
      processors, regions, transfers and privileged access against current
      settings and contracts; application source cannot prove these facts.
- [ ] Classify each layer as anonymous, pseudonymous or personal through a
      written Recital 26 singling-out/reidentification assessment.
- [ ] Approve one precise purpose and lawful basis for every event, report and
      retention layer.
- [ ] Record why each device access requires consent or satisfies a narrow
      § 3-15 exception.
- [ ] Approve the exact first-layer text and complete privacy-notice section.
- [ ] Confirm refusal is as visible and easy as acceptance, service access does
      not depend on consent, and no optional storage/request precedes consent.
- [ ] Approve a data-minimized consent proof binding time, action, consent
      version, exact notice digest and released workflow.
- [ ] Verify withdrawal is always findable, stops collection immediately,
      retries deletion safely and has an approved deletion expectation.
- [ ] Approve exact retention for events, tombstones, consent proof, logs,
      backups and aggregates, with automated-purge evidence.
- [ ] Name every processor/recipient, processing region, transfer mechanism and
      access role from current production contracts and configuration.
- [ ] Verify that URLs, query strings, raw payloads and identifiers do not leak
      into application, proxy, platform or provider logs.
- [x] Choose explicitly: no longitudinal marketing cohort for launch (founder
      product decision recorded 2026-08-29).
- [x] Approve the temporary higher-resolution invited-pilot evaluation direction,
      with protected case-code evidence and a hard `off` requirement for full
      public launch (founder product decision recorded 2026-08-29).
- [ ] Record approver names/roles, date, approved notice and consent digests,
      conditions, review/expiry date and launch/no-launch decision.

## Implementation Only After Approval

An approved notice change requires at least:

- a new privacy-notice version, effective date and SHA-256 digest in
  `apps/web/app/lib/customer-agreements.ts`;
- approved copy in `apps/web/app/lib/copy.ts` and consent UI copy/version updates;
- tests proving exact digest/version, equal choice, no pre-consent activity,
  withdrawal and retention;
- any approved lifecycle-aggregation design and database/runtime evidence; and
- a new immutable release gate on the exact resulting revision.

No existing acceptance or historical notice evidence may be rewritten.
