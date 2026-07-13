# Produktkrav og Arkitekturspesifikasjon: "Holdingswift" (Fiken-erstatter for passive holdingselskaper)

Dette dokumentet definerer kravene for en spesialisert regnskaps- og rapporteringsplattform utviklet utelukkende for **passive holdingselskaper (AS)** i Norge. Målet er å eliminere behovet for tradisjonelle driftssystemer (som Fiken eller Tripletex) ved å automatisere årsavslutningen og den løpende bokføringen av minimale transaksjoner gjennom dype API-integrasjoner mot bank og myndigheter.

---

## 1. Strategisk Plassering & Verdiforslag

Tradisjonelle systemer er bygget for selskaper med daglig drift (fakturering, mva, lønn, reiseregninger). Et passivt holdingselskap har typisk mellom **5 og 25 transaksjoner i året**.

### Hva vi *ikke* skal bygge (Sperret funksjonalitet):
*   Fakturamodul (EHF, PDF-fakturaer, purringer)
*   MVA-håndtering og MVA-melding (Holdingselskaper har ikke mva-pliktig omsetning)
*   Lønnsmodul, A-melding, OTP (tjenestepensjon) og arbeidsgiveravgift
*   Lager- og logistikkstyring
*   Timeføring og prosjektmoduler

### Verdiforslag til kunden:
*"Logg inn én gang i året, verifiser banktransaksjonene dine med tre klikk, og la systemet sende inn aksjonærregisteroppgave, skattemelding og årsregnskap automatisk via Altinn."*

---

## 2. Kjernemoduler og Funksjonelle Krav

### Modul 1: Bank og Smart Automatisk Bokføring (PSD2/Open Banking)
Siden volumet er minimalt, skal brukeren aldri trenge å punche debet/kredit manuelt.

*   **Bankintegrasjon (API):** Kontinuerlig synkronisering av bankbevegelser via en Open Banking-aggregator (f.eks. Neonomics eller MasterCard Open Banking).
*   **Kategoriseringsmotor (Rule Engine):** Automatisert matching av kjente transaksjonstyper basert på tekst og faste intervaller:
    *   *Tekst match:* "Årsgebyr", "Bankgebyr" $ightarrow$ **Debet 7770 (Bankomkostninger) / Kredit 1920 (Bank)**
    *   *Tekst match:* "Systemabonnement" $ightarrow$ **Debet 6700 (Fremmede tjenester) / Kredit 1920**
    *   *Tekst match:* "Renter" $ightarrow$ **Debet 1920 / Kredit 8050 (Annen renteinntekt)**
*   **Bilagsvedlegg via e-post/drag-and-drop:** For eksterne fakturaer (f.eks. fra revisor eller advokat) må brukeren kunne laste opp en PDF. AI/OCR (f.eks. via Base64-parsing til en lettvekt LLM/OCR API) skal automatisk foreslå beløp, dato og motkonto (typisk 6700 eller 7790).

### Modul 2: Investeringsboken (Asset Management)
Dette er systemets kjerne og der Fiken krever manuell kompetanse. Systemet må spore aksjeposter over tid.

*   **Anskaffelseskost-register:** Spore kjøpsdato, antall aksjer, eierandel (%) og total anskaffelseskost for hvert underliggende selskap (Drift AS, Eiendom AS, etc.).
*   **Fritaksmetoden-logikk:** Sortering av inntekter i to strictly adskilte løp:
    1.  **Innenfor Fritaksmetoden (Konto 8070/8071):** Utbytte og gevinster fra selskaper innenfor EØS. Systemet må automatisk beregne **3 %-sjablongregelen** for utbytte (som er skattepliktig inntekt for holdingselskapet) og holde gevinster 100 % skattefrie.
    2.  **Utenfor Fritaksmetoden (Konto 8000/8060):** Investeringer utenfor EØS eller derivater som er ordinært skattepliktige med **22 %**.
*   **Realisasjon og Tap:** Ved registrering av salg av aksjer må systemet beregne gevinst/tap basert på FIFO-prinsippet (Først inn, først ut) og generere korrekte posteringer automatisk.

### Modul 3: Selskapsstyring og Dokumentgenerator
Holdingselskaper glemmer ofte dokumentasjonskravene i Aksjeloven. Tjenesten løser dette programmatisk.

*   **Automatisert Styreprotokoll:** Hvert regnskapsår må godkjennes av styret. Systemet genererer automatisk en PDF ("Styrets årsberetning og godkjennelse") klar for digital signering.
*   **Utbyttemotor:** Dersom eieren ønsker å tømme holdingselskapet eller ta ut kapital privat:
    *   Systemet sjekker fri egenkapital (Balanse minus bunden egenkapital).
    *   Genererer **Generalforsamlingsprotokoll** for utbytte automatisk.
    *   Klargjør posteringen: **Debet 2080 (Utdelt utbytte) / Kredit 2920 (Gjeld til aksjonær)**.

---

## 3. Myndighetsrapportering (API-drevet)

Dette er den teknisk mest kritiske delen. Systemet skal kommunisere direkte med Skatteetaten og Brønnøysundregistrene via moderne REST/JSON API-er (ikke gammel XML via filopplasting i Altinn).

```
[Holdingswift System]
       │
       ├───► (Januar)  ──► Skatteetaten: Aksjonærregisteroppgaven (SIRI-API)
       │
       ├───► (Mai)     ──► Skatteetaten: Ny Skattemelding for AS (Siri/Skatteetaten REST-API)
       │
       └───► (Juli)    ──► Regnskapsregisteret: Årsregnskap (Regnskapsregisteret API via Altinn3)
```

### 1. Aksjonærregisteroppgaven (RF-1086) – Frist 31. januar
*   **Hva programmet må gjøre:** Sende inn eierstruktur per 31.12, samt eventuelle utbytter utbetalt til personlig aksjonær i løpet av året.
*   **API-grensesnitt:** Skatteetatens SIRI-API for aksjonærregisterdata.

### 2. Temabasert Skattemelding for AS – Frist 31. mai
*   **Hva programmet må gjøre:** Siden holdingselskapet har en ekstremt forenklet balanse, skal systemet oversette regnskapskontoene direkte til Skatteetatens *temabaserte* format (Skatteforhold, Finansielle produkter, Egenkapital).
*   **Flyt:**
    1.  Valider regnskapet via Skatteetatens `valider`-endepunkt.
    2.  Vis eventuelle avvik ( f.eks. uavstemt bankkonto ) til brukeren.
    3.  Send inn via `innsending`-endepunktet med maskin-til-maskin-autentisering (Maskinporten / BankID).

### 3. Årsregnskap med forenklede noter – Frist 31. juli
*   **Hva programmet må gjøre:** Generere et offisielt årsregnskap bestående av Resultat og Balanse.
*   **Notegenerator:** Små holdingselskaper (Små foretak etter regnskapsloven § 1-6) har minimale notekrav. Systemet må automatisk fylle ut:
    *   *Note for aksjespesifikasjon* (hva selskapet eier).
    *   *Note for egenkapitalendring* (viser årets resultatoverføring).
*   **API-grensesnitt:** Altinn 3 / Regnskapsregisterets mottaks-API.

---

## 4. Teknisk Arkitektur & Dataflyt

For å holde driftskostnadene ekstremt lave (slik at produktet kan prises lavt), bør systemet bygges som en moderne, lettvekt web-applikasjon.

### Foreslått Tech Stack:
*   **Backend:** Python (FastAPI) – optimalt for håndtering av finansielle data, matematiske beregninger og integrasjon mot Skatteetatens JSON-API-er.
*   **Database:** PostgreSQL – med streng bruk av unike ID-er og transaksjonssikkerhet (ACID) for regnskapslinjer.
*   **Sikkerhet/Autentisering:** Maskinporten-integrasjon via Digdir for sikker kommunikasjon på vegne av brukerens organisasjonsnummer. BankID for brukerinnlogging.

### Logisk Datamodell (Forenklet):
1.  `Company`: Org.nr, navn, stiftelsesdato, bankkontonummer.
2.  `Transaction`: Dato, beløp, beskrivelse, kontoklasse (Debet/Kredit), koblet bilags-ID.
3.  `Asset`: Selskapets navn, org.nr, antall aksjer, kostpris, historisk mottatt utbytte.
4.  `Document`: Genererte PDF-protokoller og innsendingslogger med Altinn-kvittering.

---

## 5. Prising og Markedsmulighet

*   **Målmarked:** Gründere, konsulenter og investorer som har satt opp et holdingselskap utelukkende for å reinvestere overskudd fra driftsselskaper eller aksjemarkedet, og som opplever at Fiken til ~3000-4000 kr/år er for dyrt og omfattende.
*   **Prisstrategi:** En fast lav årspris (f.eks. 990 kr eks. mva per år), ettersom programmet kjører tilnærmet 100 % passivt gjennom automatiske API-kall 11 av 12 måneder i året.
