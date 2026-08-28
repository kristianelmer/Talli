# Marketing Measurement Decision Draft

Status: decision aid for founder/legal/privacy review; not approved legal text  
Issue: #196  
Last checked: 2026-08-28  
Current implementation evidence: source revision
`99c845b332522998278827510a7d30220a2a3137`

This document separates official-source requirements from product-design
inference. It does not approve publication, change the digest-pinned privacy
notice, authorize tracking, or replace legal review.

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

## Recommended Founder Decision

Choose **no longitudinal marketing cohort for launch**:

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

The following Norwegian text is a review draft only. Bracketed facts must be
verified against the actual deployed provider contracts and configuration.

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
> Opplysningene behandles av Talli og de verifiserte leverandørene som drifter
> [database/hosting/logging]. Endelig leverandørliste, behandlingssteder og
> eventuelle overføringsgrunnlag må godkjennes mot produksjonsavtalene før
> publisering. Målingen brukes ikke til automatiserte avgjørelser eller
> individuell profilering.
>
> Du kan kontakte post@talli.no om innsyn, retting, sletting, begrensning eller
> andre personvernspørsmål, og du kan klage til Datatilsynet.

## Founder/Legal/Privacy Signoff Checklist

- [ ] Confirm the controller's legal name, contact route and DPO/contact if
      applicable.
- [ ] Inventory browser keys, IDs, payload fields, HTTP metadata and logs,
      database rows, reports, backups, recipients and processors.
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
- [ ] Choose explicitly: no longitudinal marketing cohort, restricted aggregate
      join, or durable consented bridge.
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
