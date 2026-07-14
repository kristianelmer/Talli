# Skatteetaten Production-Access Application Packet — Skattemelding for AS

Status: copy-ready except for production client ID and dated external acceptances; not submitted
Prepared: 2026-07-14
Applicant organization: ELMER WELFIS, organization number 930835978
Product: Talli

This packet is the controlled input for Skatteetaten's authenticated support
application. Submitting it requests production access; it does not enable a
production adapter or authorize a production filing. The runtime stays
`production_disabled` until the complete release boundary in
`skatteetaten-production-access-research.md` is evidenced.

## Current Application Route

1. A leader or main administrator for ELMER WELFIS delegates the Altinn access
   package **Teknisk samhandling med Skatteetaten**, or the documented
   support-administration single service, to the applicant.
2. The support administrator creates the applicant's user through
   Skatteetaten's user-administration tool.
3. The applicant signs in to the authenticated support service and opens the
   form for access to reporting services.
4. Select **Skattemeldingen** and **Produksjon** and confirm acceptance of the
   current SBS terms.

Official entry points:

- <https://www.skatteetaten.no/deling/brukeradministrasjon/>
- <https://www.skatteetaten.no/samarbeidspartnere/sluttbrukersystemer/sbs-nyheter/her-kan-du-soke-om-tilgang-til-tjenester-for-innrapportering-til-skatteetaten/>
- <https://eksternjira.sits.no/plugins/servlet/desk/site/global>
- <https://www.skatteetaten.no/samarbeidspartnere/sluttbrukersystemer/bruksvilkar/>

Do not use the former transition email for this production request.

## Preconditions to Record Before Submission

| Evidence | Required value | Current state |
| --- | --- | --- |
| Applicant can sign in to External Jira support | Dated successful login | Not evidenced |
| Current SBS terms accepted by authorized person | Date and accepting person/role | Not evidenced |
| Production client-management right delegated | `Selvbetjening av klienter i ID-porten/Maskinporten` | Not evidenced |
| Production Maskinporten client created for ELMER WELFIS | Client ID and creation date | Not created |
| Production-only public key registered | `kid`, algorithm, owner, expiry; never the private key | Not created |
| Production client is separate from TT02 | Must not equal `7166e743-978e-4a60-8a2d-0a5c00fe6ad0` | Pending client creation |
| TT02 test evidence selected for attachment | Narrative and machine evidence listed below | Ready |

Missing preconditions are not guessed. The application may be drafted, but it
must not claim a production client or accepted terms until the dated evidence
exists.

## Copy-Ready Application Text (Norwegian)

### Sammendrag

ELMER WELFIS (org.nr. 930835978) søker som leverandør av
sluttbrukersystemet Talli om produksjonstilgang til Skattemeldingen.

Tjeneste: Innrapportering skattemelding

Miljø: Produksjon

Maskinporten-scope:
`skatteetaten:formueinntekt/skattemelding`

Altinn-scopes for instansbehandling:
`altinn:instances.read` og `altinn:instances.write`

Altinn-ressurs for Systembruker:
`app_skd_formueinntekt-skattemelding-v2`

Produksjonsklient-ID: **fylles inn fra Digdir Selvbetjening før innsending**

### Brukstilfelle og avgrensning

Talli er et sluttbrukersystem for norske holdingselskaper som leverer
skattemeldingen for sin egen virksomhet. Kunden godkjenner en standard
Systembruker for eget system i Altinn. Talli opptrer ikke som regnskapsfører
eller agent for kundens klienter.

Systembrukeren skal hente gjeldende skattemelding, validere den komplette
skattemeldingen og næringsspesifikasjonen, opprette en Altinn-instans og laste
opp filene. Talli stopper i steget Bekreftelse. En person med nødvendig rett
logger inn via ID-porten, gjennomgår visningen og utfører den endelige
innsendingen. Etter personlig innsending gjenopptar Talli flyten skrivebeskyttet
for å hente `tilbakemelding`, status og arkivreferanser.

Første støttede produksjonsomfang er et enkelt norsk holdingselskap (AS) uten
revisorkrav, kompliserte skatteforhold eller ekstra vedlegg. Manglende, ukjent
eller positivt behov for ekstra vedlegg skal blokkere automatisk klargjøring.
Produksjonsadapteren er deaktivert inntil alle avtalte tilganger, kontroller og
godkjenninger foreligger.

### Gjennomført TT02-test

Den 14. juli 2026 gjennomførte Talli en ende-til-ende-test i TT02 med syntetisk
Tenor-virksomhet. Følgende ble verifisert:

- Maskinporten-token med Systembruker og påkrevde scopes;
- henting av gjeldende utkast;
- lokal validering mot de tre fastlåste offisielle 2025-XSD-ene;
- `validertest` med resultat `validertOK`;
- opprettelse av Altinn-instans, opplasting og ren filskann;
- asynkron validering med `validertOK`;
- stopp ved personlig bekreftelse;
- personlig innsending med TestID på høyt nivå;
- uthenting og uavhengig kontroll av offisiell `tilbakemelding`; og
- verifisering av arkivert instans og dokumentreferanser.

Rå XML, tokens, privat nøkkel, dokumentreferanse, internt partsnummer og
personidentifikatorer er ikke lagret i vedlagt dokumentasjon.

### Spørsmål som ønskes bekreftet skriftlig

1. Oppfyller vedlagt TT02-evidence kravet om gjennomført test for
   produksjonstilgang, eller ønsker Skatteetaten ytterligere testdokumentasjon?
2. Skal Maskinporten-tokenet for Altinn-operasjoner byttes via
   `https://platform.altinn.no/authentication/api/v1/exchange/maskinporten` for
   denne appen i produksjon?
3. Bekrefter dere at Systembruker skal stoppe i Bekreftelse og at en person må
   utføre endelig innsending via ID-porten?
4. Kan samme godkjente Systembruker etter personlig innsending brukes
   skrivebeskyttet til å hente `tilbakemelding` fra instansen?
5. Krever Skatteetaten en koordinert første produksjonsinnsending, ytterligere
   sertifisering eller andre vilkår før ordinær bruk?
6. Hvilken dokumentasjon skal brukes for å klassifisere `tilbakemelding` som
   endelig akseptert når den inneholder veilednings- eller avvikskoder?

### Bekreftelser

ELMER WELFIS bekrefter ved innsending av søknaden at gjeldende bruksvilkår og
eventuell tjenestebeskrivelse er lest og akseptert av en person med nødvendig
fullmakt. Virksomheten vil ha gyldige kundeavtaler og databehandleravtaler,
tilgangsstyring, informasjonssikkerhet, internkontroll, hendelseshåndtering,
brukerstøtte, beredskap og abonnement på relevante driftsvarsler før
produksjonsbruk.

## Attachments

Attach only sanitized evidence:

1. `docs/filing/evidence/company-tax-tt02-2026-07-14.md`
2. `docs/filing/evidence/company-tax-tt02-2026-07-14.json`
3. If requested, the applicable test commands and pinned-schema register in
   `docs/filing/company-tax-return-schema-evidence-register.md`

Do not attach a private key, token, raw source/current-return XML, receipt XML,
personal identifier, internal Altinn party ID, or unredacted screenshot.

## Post-Submission Record

After submitting, append a dated record here with:

- External Jira case ID;
- submission date and applicant role (not personal credentials);
- production client ID and public `kid` only;
- the exact attachments sent;
- Skatteetaten's written answers to the six questions;
- approval/rejection date and scope grant state; and
- any required pilot or follow-up action.

An application or scope grant alone must not change a Talli runtime flag,
authority-test decision, or launch signoff.
