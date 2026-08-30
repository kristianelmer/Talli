import {
  inviteOnlyBetaCopy,
  preProductionDirectFilingCopy,
  requiredNonAffiliationCopy,
} from "./launch-copy.ts";

export const operatorAuthorityCopy = {
  systembrukerCallback: {
    title: "Produksjon · Systemregister-callback",
    gateLabel: "Operasjonsport",
    enabled: "Midlertidig aktivert",
    disabled: "Deaktivert",
    body:
      "Denne operasjonen legger bare den faste callback-adressen til den eksisterende Systemregister-definisjonen. Den oppretter ikke en Systembruker og åpner ikke for produksjonsinnsending.",
    callbackLabel: "Fast callback",
    callback: "https://talli.no/auth/systembruker/confirm",
    confirmationLabel: "Skriv SET TALLI SYSTEMBRUKER CALLBACK",
    cta: "Legg til eller verifiser callback",
  },
} as const;

/**
 * Central owner-facing copy — Norwegian first.
 *
 * Every string an owner can read should live here, not inline in components, so
 * the language stays consistent and free of developer/infrastructure jargon.
 * Operator-only surfaces (the (operator) route group) and code/comments may stay
 * in English. See docs/design/copy.md for the terminology guide.
 */
export const ownerCopy = {
  brand: "Talli",
  tagline: "Holding-først årsrapportering for enkle AS.",

  home: {
    metaTitle: "Talli – enkelt årsoppgjør for holdingselskaper",
    metaDescription:
      "Talli veileder deg gjennom aksjonærregisteroppgaven, skattemeldingen og årsregnskapet for enkle norske holdingselskaper – i klartekst.",
    nav: {
      signIn: "Logg inn",
      signUp: "Be om betatilgang",
      toApp: "Gå til Talli",
    },
    hero: {
      eyebrow: inviteOnlyBetaCopy,
      title: "Få kontroll på årsoppgjøret for holdingselskapet",
      lede: "Talli hjelper inviterte betabrukere med å forberede og kontrollere utkast til aksjonærregisteroppgaven, skattemeldingen og årsregnskapet for støttede, enkle norske AS.",
      primaryCta: "Be om betatilgang",
      secondaryCta: "Logg inn",
      reassurance:
        "Produksjonsinnsending og live betaling er ikke tilgjengelig i betaen.",
    },
    features: {
      title: "Forberedelsene samlet på ett sted",
      items: [
        {
          title: "Vi henter dataene",
          body: "Talli henter offisiell selskapsinformasjon fra Brønnøysundregistrene, så du slipper å fylle inn alt manuelt.",
        },
        {
          title: "Veiledet årsoppgjør",
          body: "Aksjonærregisteroppgaven, skattemeldingen og årsregnskapet – forklart steg for steg, uten regnskapssjargong.",
        },
        {
          title: "Tekniske kontroller",
          body: "Talli kontrollerer struktur, summer og støttet sakstype, viser avvik og stopper saker som faller utenfor betaflyten.",
        },
      ],
    },
    steps: {
      title: "Slik fungerer det",
      items: [
        {
          title: "Legg inn grunnlaget",
          body: "Inviterte brukere legger inn organisasjonsnummer, dokumentasjon og regnskapsgrunnlag for holdingselskapet.",
        },
        {
          title: "Talli bygger utkast",
          body: "Talli bruker det lagrede grunnlaget til å bygge forhåndsvisninger for de støttede oppgavene.",
        },
        {
          title: "Du gjennomgår",
          body: "Du ser nøyaktig hva utkastene inneholder, løser avvik og bekrefter selv opplysningene.",
        },
        {
          title: "Test og eksporter",
          body: "I betaen kan du teste den veiledede flyten og hente ut grunnlaget. Direkte produksjonslevering er ikke åpnet.",
        },
      ],
    },
    scope: {
      title: "Laget for enkle holdingselskaper",
      body: "Talli beta er avgrenset til støttede holdingselskaper og enkle AS uten ansatte, lønn, MVA-aktivitet, revisjonsplikt eller komplekse verdipapirer. Mer sammensatte saker blokkeres og må håndteres utenfor betaflyten.",
    },
    closing: {
      title: "Interessert i å prøve betaen?",
      body: "Send oss en kort e-post. Vi inviterer nye testselskaper gradvis og svarer normalt innen to virkedager.",
      cta: "Be om betatilgang",
    },
    disclosures: [
      requiredNonAffiliationCopy,
      preProductionDirectFilingCopy,
      "Produksjonsinnsending og live betaling er ikke tilgjengelig i betaen.",
    ],
    footer: {
      rights: "© 2026 Talli",
    },
  },

  nav: {
    overview: "Årsrapportering",
    actions: "Handlinger",
    transactions: "Transaksjoner",
    yearEnd: "Årsavslutning",
    filing: "Innsending",
    connections: "Selskap",
    eligibility: "Selskapsgrense",
    documents: "Dokumenter",
    billing: "Innstillinger",
    workspace: "Arbeidsflate",
    operator: "Operatør",
    menu: "Meny",
    signOut: "Logg ut",
  },

  connections: {
    title: "Altinn-tilkobling",
    intro:
      "Koble et selskap til Altinn Systembruker, og følg den lagrede statusen før kontrollert innsending.",
    companyHeading: "Velg selskap",
    statusHeading: (companyName: string) => `Status for ${companyName}`,
    noCompaniesTitle: "Sett opp selskapet først",
    noCompaniesBody:
      "Du må sette opp et holdingselskap før du kan opprette en Altinn-tilkobling.",
    noCompaniesCta: "Kom i gang",
    noRequestTitle: "Ingen tilkoblingsforespørsel",
    noRequestBody:
      "Opprett en forespørsel for å godkjenne Talli som Systembruker for selskapet i Altinn.",
    loadErrorTitle: "Statusen er midlertidig utilgjengelig",
    loadErrorBody:
      "Vi kunne ikke hente den lagrede tilkoblingsstatusen. Prøv igjen om litt.",
    states: {
      creating: {
        title: "Vi gjør forespørselen klar",
        body:
          "Forespørselen er lagret, men opprettelsen er ikke ferdig. Sjekk status for å prøve videre.",
      },
      new: {
        title: "Venter på godkjenning i Altinn",
        body:
          "Forespørselen er opprettet, men ikke godkjent. Fortsett til Altinn og godkjenn den der.",
      },
      accepted: {
        title: "Verifiserer tilkoblingen",
        body:
          "Altinn har godkjent forespørselen. Talli kontrollerer at Systembrukeren kan brukes til innsending før tilkoblingen markeres som klar.",
      },
      rejected: {
        title: "Forespørselen ble avslått",
        body:
          "Forespørselen er avsluttet og kan ikke endres. Du kan opprette en ny forespørsel.",
      },
      denied: {
        title: "Altinn nektet forespørselen",
        body:
          "Forespørselen er avsluttet og kan ikke endres. Du kan opprette en ny forespørsel.",
      },
      timedout: {
        title: "Forespørselen utløp",
        body:
          "Godkjenningsfristen er passert. Du kan opprette en ny forespørsel.",
      },
      verification_failed: {
        title: "Godkjent, men kunne ikke verifiseres for innsending",
        body:
          "Altinn har godkjent forespørselen, men Talli kunne ikke bekrefte at Systembrukeren kan brukes til innsending. Prøv verifiseringen på nytt.",
      },
    },
    verified: {
      title: "Tilkoblingen er godkjent og verifisert",
      body:
        "Talli har kontrollert at Systembrukeren kan brukes til kontrollert innsending for selskapet.",
    },
    actions: {
      create: "Opprett tilkobling",
      createPending: "Oppretter …",
      continue: "Fortsett i Altinn",
      refresh: "Sjekk status",
      refreshPending: "Sjekker …",
      retryVerification: "Prøv verifisering på nytt",
      retryVerificationPending: "Verifiserer …",
      createNew: "Opprett ny forespørsel",
      createNewPending: "Oppretter …",
    },
    actionsLabel: "Handlinger for Altinn-tilkoblingen",
    filing: {
      missing: {
        label: "Systembruker mangler",
        body: "Selskapet har ingen aktiv Systembruker-tilkobling i Talli.",
        variant: "danger",
        ready: false,
      },
      waiting: {
        label: "Venter på Altinn",
        body: "Forespørselen venter på godkjenning i Altinn.",
        variant: "warning",
        ready: false,
      },
      ready: {
        label: "Klar for kontrollert innsending",
        body: "Systembruker-tilkoblingen er godkjent og verifisert.",
        variant: "success",
        ready: true,
      },
      action: {
        label: "Tilkoblingen krever handling",
        body: "Åpne tilkoblinger for å se lagret status og gyldige neste steg.",
        variant: "danger",
        ready: false,
      },
    },
    callbackNotices: {
      pending: "Returen fra Altinn er behandlet. Se den lagrede statusen nedenfor.",
      verifying: "Returen fra Altinn er behandlet. Se den lagrede statusen nedenfor.",
      connected: "Returen fra Altinn er behandlet. Se den lagrede statusen nedenfor.",
      rejected: "Returen fra Altinn er behandlet. Se den lagrede statusen nedenfor.",
      denied: "Returen fra Altinn er behandlet. Se den lagrede statusen nedenfor.",
      timedout: "Returen fra Altinn er behandlet. Se den lagrede statusen nedenfor.",
      manual:
        "Vi kunne ikke knytte returen fra Altinn til en aktiv forespørsel. Sjekk den lagrede statusen nedenfor.",
    },
  },

  auth: {
    signInTitle: "Logg inn",
    signInIntro: "Holding-først årsrapportering for enkle AS.",
    signInCta: "Logg inn",
    signInPending: "Logger inn …",
    signUpTitle: "Opprett bruker",
    signUpIntro: "Kom i gang med holdingselskapets årsoppgjør.",
    signUpCta: "Opprett bruker",
    signUpPending: "Oppretter …",
    emailLabel: "E-post",
    passwordLabel: "Passord",
    passwordHelp: "Minst 12 tegn.",
    orDivider: "eller",
    googleCta: "Fortsett med Google",
    googlePending: "Åpner Google …",
    haveAccount: "Har du allerede konto?",
    noAccount: "Ny her?",
    toSignIn: "Logg inn",
    toSignUp: "Opprett bruker",
    unavailableTitle: "Tjenesten er ikke klar",
    unavailable: "Innlogging er midlertidig utilgjengelig. Prøv igjen om litt.",
    termsLink: "Vilkår",
    privacyLink: "Personvern",
  },

  verifyEmail: {
    title: "Bekreft e-posten din",
    intro:
      "Vi har sendt en bekreftelseslenke. Åpne e-posten og klikk lenken for å aktivere kontoen.",
    sentTo: "Sendt til",
    hintTitle: "Finner du den ikke?",
    hint: "Sjekk søppelpost og reklame. Lenken er gyldig en stund – du kan sende en ny under.",
    resendCta: "Send bekreftelseslenken på nytt",
    resendPending: "Sender …",
    resent: "Vi har sendt en ny bekreftelseslenke.",
    backToLogin: "Tilbake til innlogging",
  },

  emailConfirmed: {
    title: "E-posten er bekreftet",
    body: "Takk! Kontoen din er aktivert, og du er logget inn. Da setter vi i gang.",
    cta: "Gå til Talli",
  },

  legal: {
    lastUpdatedLabel: "Sist oppdatert",
    lastUpdated: "30. august 2026",
    backCta: "Tilbake til innlogging",
    backHref: "/login",

    privacy: {
      title: "Personvernerklæring",
      intro:
        "Denne personvernerklæringen forklarer hvilke personopplysninger Talli behandler når du bruker tjenesten på talli.no, hvorfor vi behandler dem, og hvilke rettigheter du har.",
      sections: [
        {
          heading: "Behandlingsansvarlig",
          body: [
            "Talli drives av ELMER WELFIS, org.nr. 930 835 978, Fjøsangerveien 32D, 5053 Bergen. ELMER WELFIS er behandlingsansvarlig for begrensede opplysninger om konto, tilgang, sikkerhet, støtte, frivillig bruksmåling, betaling og egne lovpålagte opptegnelser.",
            "Kundeselskapet er behandlingsansvarlig for personopplysninger i egne selskaps-, aksjonær-, regnskapsdokument-, smal hovedbok- og innsendingsdata. ELMER WELFIS er databehandler for dette innholdet og bruker det bare for å levere og sikre Talli etter kundens instrukser.",
            "Har du spørsmål om personvern, kan du kontakte oss på post@talli.no.",
          ],
          bullets: [],
        },
        {
          heading: "Hvilke opplysninger vi behandler",
          body: ["Vi behandler følgende kategorier av opplysninger:"],
          bullets: [
            "Kontoopplysninger: e-postadresse, navn hvis du oppgir det, og innloggingsinformasjon. Logger du inn med Google, mottar vi e-postadresse og navn fra Google-kontoen din.",
            "Selskapsopplysninger: organisasjonsnummeret du oppgir, og offentlig registerinformasjon vi henter fra Brønnøysundregistrene.",
            "Regnskaps- og innsendingsdata: tall, transaksjoner og dokumenter du legger inn for å forberede årsoppgjør og lovpålagt rapportering.",
            "Teknisk informasjon: innloggings- og øktinformasjon (informasjonskapsler) og enkel loggdata som er nødvendig for drift og sikkerhet.",
            "Opplysninger om aksjonærer, selskapsår, betaling, refusjon, myndighetskvitteringer og sikkerhets- eller revisjonshendelser når de aktuelle funksjonene brukes.",
          ],
        },
        {
          heading: "Hvorfor vi behandler opplysningene",
          body: ["Vi behandler personopplysninger for å:"],
          bullets: [
            "administrere konto og tilgang for bedriftskunden, gi støtte og ivareta vanlig tjenestedrift (berettiget interesse, personvernforordningen artikkel 6 nr. 1 bokstav f),",
            "oppfylle rettslige forpliktelser, for eksempel bokførings- og oppbevaringskrav (artikkel 6 nr. 1 bokstav c),",
            "gjøre det mulig å logge inn med Google når du velger det, som del av vår berettigede interesse i sikker og enkel tilgang,",
            "ivareta sikkerhet, feilretting og misbruksvern (berettiget interesse, artikkel 6 nr. 1 bokstav f), og",
            "måle hvor den offentlige selskapsjekken og oppstarten lykkes eller stopper, men bare når du har samtykket (artikkel 6 nr. 1 bokstav a og ekomloven § 3-15).",
          ],
        },
        {
          heading: "Databehandlere og deling",
          body: [
            "Vi selger aldri personopplysningene dine. Talli bruker ikke selskapsdata, regnskapsdata, bankdata, dokumenter eller innsendingsdata til reklame. Talli kan bruke underleverandører (databehandlere) for funksjoner som autentisering, database, lagring, hosting, valgfri innlogging, betaling og e-post. Endelig leverandørliste, roller og behandlingssteder må verifiseres mot gjeldende produksjonsavtaler og konfigurasjon før de oppgis som produksjonsfakta.",
          ],
          bullets: [],
        },
        {
          heading: "Overføring utenfor EU/EØS",
          body: [
            "Før en eventuell overføring utenfor EU/EØS skal Talli verifisere behandlingssted, gyldig overføringsgrunnlag og nødvendige tilleggstiltak mot gjeldende produksjonsavtaler og konfigurasjon. Denne erklæringen bekrefter ikke at en bestemt overføring, region eller mekanisme er produksjonsverifisert i dag.",
          ],
          bullets: [],
        },
        {
          heading: "Hvor lenge vi lagrer opplysningene",
          body: [
            "Vi lagrer kontoopplysninger så lenge de trengs for aktiv tilgang, sikkerhet og lovlige forretningsopptegnelser. Etter avtalt lese- og eksportperiode returnerer eller sletter Talli kundekontrollert innhold etter kundens dokumenterte valg, med mindre en lov plikter Talli direkte til å beholde det eller kunden gir en lovlig oppbevaringsinstruks. Kundens egen bokføringsplikt gir ikke Talli en generell rett til å beholde alle kundedata.",
            "For frivillig bruksmåling varer den tilfeldige økten i høyst 30 minutter. Råhendelser og minimumsbeviset for samtykke slettes senest etter 90 dager. Den korte posten som hindrer ny lagring etter tilbaketrekking, varer i høyst 30 minutter.",
          ],
          bullets: [],
        },
        {
          heading: "Dine rettigheter",
          body: ["Etter personvernregelverket har du rett til å:"],
          bullets: [
            "få innsyn i hvilke opplysninger vi behandler om deg,",
            "få rettet uriktige opplysninger,",
            "få slettet opplysninger («retten til å bli glemt») når vilkårene er oppfylt,",
            "be om begrensning av behandlingen eller protestere mot den,",
            "få utlevert opplysningene dine i et maskinlesbart format (dataportabilitet).",
          ],
        },
        {
          heading: "Klage til tilsynsmyndighet",
          body: [
            "Mener du at vi behandler personopplysninger i strid med regelverket, kan du klage til Datatilsynet. Vi setter pris på om du tar kontakt med oss først, slik at vi kan rette opp i forholdet.",
          ],
          bullets: [],
        },
        {
          heading: "Frivillig måling av den offentlige kundereisen",
          body: [
            "Hvis du velger «Tillat bruksmåling», måler ELMER WELFIS bare hvor den offentlige selskapsjekken og oppstarten lykkes eller stopper. Målingen behandler samtykkeversjon, tilfeldige økt- og hendelses-ID-er, faste koder for hendelse, steg, kilde og årsak, og tidspunkt. Dette er pseudonyme personopplysninger, ikke anonyme data.",
            "Målingen inneholder ikke navn, e-post, organisasjonsnummer, fritekst, sideadresse, regnskapsdata, bankdata eller dokumentopplysninger. Den kobles ikke til konto, selskap, kjøp, selskapsår, støtte, refusjon eller innsending. Ingenting valgfritt lagres eller sendes før du samtykker. Talli virker på samme måte hvis du velger «Nei takk».",
            "Du kan trekke samtykket i samme grensesnitt. Ny måling stopper med en gang, og Talli ber om sletting av råhendelsene for økten, med trygg gjentakelse hvis slettingen ikke kan bekreftes første gang. Tilbaketrekking endrer ikke lovligheten av behandling som skjedde før samtykket ble trukket.",
            "Målingen behandles av ELMER WELFIS og databehandlere som leverer database, hosting og nødvendig teknisk logging. Navn, behandlingssteder, lagringstider og eventuelle overføringsgrunnlag skal stå i den gjeldende leverandøroversikten før målingen aktiveres. Målingen brukes ikke til automatiserte avgjørelser eller individuell profilering.",
          ],
          bullets: [],
        },
        {
          heading: "Observasjon i invitert pilot",
          body: [
            "En invitert pilot bruker det vanlige Talli-produktet. En separat passiv observatør kan skrive en begrenset valideringspost etter det vanlige produktresultatet. Observasjonen skal ikke endre, prøve på nytt, skjule eller erstatte resultatet. Deltakeren får nøyaktig pilotinformasjon og avtale før observasjonen starter.",
            "Rå pilotobservasjoner slettes senest etter 90 dager. Det separate beskyttede deltakerregisteret slettes 12 måneder etter at valideringen er avsluttet, med mindre en dokumentert hendelse eller et lovkrav krever lengre lagring. Bare navngitte valideringskontrollører får tilgang. Før full offentlig lansering skal observatøren være av og alle pilottillatelser være utløpt eller fjernet.",
          ],
          bullets: [],
        },
        {
          heading: "Personvernombud",
          body: [
            "ELMER WELFIS oppretter ikke et formelt personvernombud ved lansering. Talli er ikke en offentlig myndighet, gjennomfører ikke regelmessig og systematisk sporing i stor skala og har ikke behandling av sensitive eller strafferettslige opplysninger i stor skala som kjerneaktivitet. Vurderingen dokumenteres på nytt hvert år og etter en vesentlig endring i produkt eller skala.",
          ],
          bullets: [],
        },
        {
          heading: "Sikkerhet",
          body: [
            "Talli skal bruke tekniske og organisatoriske tiltak som er tilpasset risikoen, blant annet kontrollmål for tilgang, autentisering, kryptert overføring og hendelseshåndtering. Et kontrollmål beskrives ikke som implementert før det er verifisert i gjeldende produksjonsmiljø. Ingen tjeneste er helt uten risiko, og vi oppfordrer deg til å bruke et sterkt, unikt passord.",
          ],
          bullets: [],
        },
        {
          heading: "Endringer i personvernerklæringen",
          body: [
            "Vi kan oppdatere denne erklæringen ved endringer i tjenesten eller regelverket. Gjeldende versjon ligger alltid på denne siden, med oppdatert dato øverst.",
          ],
          bullets: [],
        },
        {
          heading: "Kontakt",
          body: [
            "Har du spørsmål om personvern eller ønsker å bruke rettighetene dine, kontakt oss på post@talli.no.",
          ],
          bullets: [],
        },
      ],
    },

    terms: {
      title: "Brukervilkår for bedriftskunder",
      intro:
        "Disse vilkårene er avtalen mellom selskapet som uttrykkelig godtar dem ved opprettelse av et selskapsområde (kunden), og ELMER WELFIS, org.nr. 930 835 978 (leverandøren), om kundens bruk av Talli.",
      sections: [
        {
          heading: "Tjenesten og støttet omfang",
          body: [
            "Talli er et holding-først digitalt verktøy som hjelper støttede, enkle norske aksjeselskaper (AS), særlig holdingselskaper, med å forberede årsoppgjør og lovpålagt rapportering. Tjenesten kan avvise eller stoppe saker med forhold den ikke støtter, for eksempel mer sammensatt regnskap, merverdiavgift, lønn eller fakturering.",
            "Kundens pris, plan og tilgang følger planen og funksjonene som vises i tjenesten. Beta, tidlig tilgang og senere generell tilgjengelighet er tjenestetilstander under de samme vilkårene. Betaling eller produksjonsinnsending aktiveres ikke før dette uttrykkelig vises i tjenesten og de tilhørende sikkerhets-, betalings- og myndighetsportene er oppfylt.",
          ],
          bullets: [],
        },
        {
          heading: "Konto, selskap og fullmakt",
          body: [
            "Den som oppretter et selskapsområde, må gi korrekte opplysninger, beskytte innloggingsinformasjonen og ha nødvendig fullmakt til å inngå avtalen på vegne av kunden. En personlig konto, passiv bruk eller en lenke til vilkårene utgjør ikke selskapets aksept.",
          ],
          bullets: [],
        },
        {
          heading: "Kundens kontroll og ansvar",
          body: [
            "Talli er et hjelpemiddel og erstatter ikke regnskapsfører, revisor eller juridisk rådgivning. Kunden skal kontrollere at grunnlag, beregninger, dokumenter og innsendinger er fullstendige og riktige, og at bruken passer kundens forhold.",
            "Kunden er ansvarlig for lokale godkjenninger og for å beslutte om noe skal sendes. At Talli forbereder eller lokalt godkjenner innhold, eller mottar en transportkvittering, betyr ikke at en myndighet har mottatt eller endelig godkjent innholdet. Talli garanterer ikke myndighetsgodkjenning.",
          ],
          bullets: [],
        },
        {
          heading: "Direkte innsending og støtte",
          body: [
            "Direkte innsending er bare tilgjengelig når den aktuelle funksjonen, kundens rettigheter, produksjonslegitimasjon og alle gjeldende lanserings- og myndighetsporter er aktive. Avtaleaksept gir ikke i seg selv rett til produksjonsinnsending eller omgår noen port.",
            "Kunden skal følge opp kvitteringer, avvisninger og frister. Spørsmål om tjenesten kan sendes til post@talli.no. Støtte innebærer ikke at leverandøren overtar kundens kontroll-, arkiv- eller innsendingsansvar.",
          ],
          bullets: [],
        },
        {
          heading: "Pris og betaling",
          body: [
            "Talli bruker ett abonnement på NOK 1 490 per selskapsår. Prisen inkluderer merverdiavgift bare når merverdiavgift gjelder etter loven. Det er ingen månedspris, innsendingspakke, pris per innsending, etableringspris eller automatisk betalt rådgivning. En gratis plan medfører ingen betaling. Før betaling åpnes, viser Talli det nøyaktige selskapsåret, prisen, vilkårene, fullmakten, støttet omfang og trygg vei ut. Avtaleaksept alene utløser ingen betaling.",
            "Hvis Talli bekrefter at et selskapsår støttes, men Talli senere ikke kan fullføre det på grunn av feil i Tallis egen logikk eller tilkobling, får kunden hele beløpet tilbake. Feil i kundeopplysninger, manglende dokumentasjon eller fullmakt, frister kunden ikke følger, og avbrudd hos myndigheter utenfor Tallis kontroll gir ikke automatisk refusjon.",
            "Betaling, automatisk fornyelse og belastning er ikke åpnet. Eventuelle fremtidige regler for fornyelse, oppsigelse og betalingstidspunkt må vises tydelig og godtas uttrykkelig før kunden kan betale.",
          ],
          bullets: [],
        },
        {
          heading: "Akseptabel bruk",
          body: ["Du forplikter deg til ikke å:"],
          bullets: [
            "bruke tjenesten til ulovlige formål eller i strid med disse vilkårene,",
            "forsøke å skaffe deg uautorisert tilgang til tjenesten eller andre brukeres data,",
            "forstyrre eller forsøke å omgå sikkerheten i tjenesten.",
          ],
        },
        {
          heading: "Konfidensialitet, data og tilbakemeldinger",
          body: [
            "Partene skal beskytte hverandres konfidensielle opplysninger og bare bruke dem for avtalen eller der lov krever det. Kunden beholder rettighetene til egne data og dokumenter og gir leverandøren en begrenset rett til å behandle dem for å levere og sikre tjenesten.",
            "Talli, programvaren, designet og varemerkene tilhører leverandøren eller leverandørens lisensgivere. Kunden kan frivillig gi tilbakemeldinger; leverandøren kan bruke generelle ideer uten å offentliggjøre kundens konfidensielle opplysninger eller personopplysninger.",
          ],
          bullets: [],
        },
        {
          heading: "Databehandling",
          body: [
            "Databehandleravtalen på /databehandleravtale er innlemmet i disse vilkårene og gjelder når leverandøren behandler personopplysninger på vegne av kunden. Ved motstrid om slik behandling går databehandleravtalen foran disse vilkårene.",
          ],
          bullets: [],
        },
        {
          heading: "Ansvarsbegrensning",
          body: [
            "Tjenesten leveres med de funksjonene og begrensningene som vises. Så langt loven tillater, er leverandøren ikke ansvarlig for indirekte tap, følgetap eller tap som skyldes uriktige kundeopplysninger, manglende kundekontroll, bruk utenfor støttet omfang eller kundens brudd på vilkårene. Ingenting begrenser ansvar som ikke kan fraskrives etter ufravikelig lov.",
          ],
          bullets: [],
        },
        {
          heading: "Suspensjon, oppsigelse og eksport",
          body: [
            "Kunden kan si opp tjenesten. Leverandøren kan suspendere nødvendig tilgang ved sikkerhetsrisiko, ulovlig bruk eller vesentlig mislighold, og kan si opp avtalen ved vesentlig mislighold etter rimelig mulighet til å rette når det passer.",
            "Etter betalt tilgang får kunden minst 90 dager med lesetilgang og eksport. Deretter returnerer eller sletter Talli kundekontrollerte data etter kundens dokumenterte valg, med mindre en lovplikt som gjelder Talli direkte krever fortsatt lagring. Kundens egen bokføringsplikt gir ikke Talli en generell rett til å beholde alle kundedata.",
          ],
          bullets: [],
        },
        {
          heading: "Endringer i vilkårene",
          body: [
            "Leverandøren kan oppdatere vilkårene ved utvikling av tjenesten eller endringer i regelverket. Enhver vesentlig ny avtaleversjon varsles i tjenesten eller på e-post og må uttrykkelig aksepteres på nytt av en representant med fullmakt før den binder kunden. Talli lagrer uforanderlig akseptbevis med kunde, dokumentversjoner og dokumentavtrykk, akseptmetode og tidspunkt. Passiv bruk er ikke akseptbevis. Gjeldende versjon vises på denne siden.",
          ],
          bullets: [],
        },
        {
          heading: "Lovvalg og verneting",
          body: [
            "Vilkårene reguleres av norsk rett. Tvister skal søkes løst i minnelighet. Fører ikke det frem, kan tvisten bringes inn for de ordinære domstolene etter gjeldende vernetingsregler og ufravikelig lov.",
          ],
          bullets: [],
        },
        {
          heading: "Kontakt",
          body: [
            "Leverandør: ELMER WELFIS, org.nr. 930 835 978, Fjøsangerveien 32D, 5053 Bergen, post@talli.no. ELMER WELFIS er registrert i Enhetsregisteret og er ikke registrert i Merverdiavgiftsregisteret nå. Opplysningene oppdateres når status endres.",
          ],
          bullets: [],
        },
      ],
    },

    dpa: {
      title: "Databehandleravtale",
      intro:
        "Denne databehandleravtalen er del av Talli Brukervilkår for bedriftskunder mellom kunden som behandlingsansvarlig og ELMER WELFIS, org.nr. 930 835 978, som databehandler når Talli behandler personopplysninger på kundens vegne.",
      sections: [
        {
          heading: "1. Roller og omfang",
          body: [
            "Kunden er behandlingsansvarlig for personopplysninger i kundens selskaps-, aksjonær-, regnskapsdokument-, smal hovedbok- og innsendingsdata. Leverandøren er databehandler når opplysningene behandles for å levere Talli etter kundens dokumenterte instrukser.",
            "Leverandøren er selvstendig behandlingsansvarlig for begrenset behandling som er nødvendig for konto og tilgang, tjenestesikkerhet, støtte, frivillig offentlig bruksmåling, betaling, oppfyllelse av rettslige plikter og egne forretningsopptegnelser.",
          ],
          bullets: [],
        },
        {
          heading: "2. Behandlingens detaljer og varighet",
          body: [
            "Formålet og arten er å lagre, organisere, beregne, vise, eksportere og, når særskilt aktivert, overføre opplysninger for å levere kundens regnskaps- og rapporteringsarbeidsflyt. Behandlingen varer mens avtalen og den godkjente lese- og eksportperioden gjelder, og deretter bare så lenge kundens retur- eller slettevalg, verifisert sikkerhetskopirotasjon eller en lovplikt som gjelder Talli direkte krever det.",
            "Registrerte kan være kundens brukere, eiere, styremedlemmer, ansatte, kontaktpersoner og andre personer som inngår i kundens dokumentasjon. Opplysningene kan omfatte identitets- og kontaktopplysninger, konto- og tilgangsdata, eier- og rolleopplysninger, transaksjoner, bilag, dokumentinnhold, rapporterings- og innsendingsdata, kvitteringer og sikkerhets- og revisjonslogger.",
          ],
          bullets: [],
        },
        {
          heading: "3. Dokumenterte instrukser",
          body: [
            "Leverandøren behandler bare personopplysninger etter dokumenterte instrukser fra kunden, herunder denne avtalen og kundens bruk av funksjonene, med mindre lov krever annet. Leverandøren informerer kunden før lovpålagt behandling når loven tillater det, og varsler uten ugrunnet opphold dersom en instruks etter leverandørens vurdering strider mot personvernregelverket.",
          ],
          bullets: [],
        },
        {
          heading: "4. Konfidensialitet og sikkerhet",
          body: [
            "Leverandøren skal sikre at personer med tilgang er underlagt konfidensialitet og bare får nødvendig tilgang. Leverandøren skal gjennomføre egnede tekniske og organisatoriske tiltak vurdert mot risikoen. Kontrollmål kan omfatte tilgangsstyring, autentisering, kryptert transport, revisjonsspor, sikker utvikling, sikkerhetskopiering, gjenoppretting og hendelseshåndtering, men beskrives ikke som implementert før tiltaket er verifisert i gjeldende produksjonsmiljø.",
            "Før ekte kundedata kan brukes, skal ansvarlig eier identifisere de nøyaktige Supabase- og Vercel-systemene, teste selskapsskille og privat dokumentlagring, begrense støttetilgang til en bestemt sak og tidsperiode, teste database- og dokumentgjenoppretting og kontrollere logger, regioner, eksterne tjenester, overføringer, tilgang, sletting, automatisk opprydding, overvåking og hendelseshåndtering.",
            "Kunden er ansvarlig for egne brukere, tilgangstildelinger, enheter, datakvalitet og lovlig behandlingsgrunnlag. Sikkerhetstiltak kan utvikles så lenge beskyttelsesnivået ikke samlet sett svekkes.",
          ],
          bullets: [],
        },
        {
          heading: "5. Underdatabehandlere",
          body: [
            "Kunden gir generell skriftlig tillatelse til å bruke underdatabehandlere som er nødvendige for tjenesten. Leverandøren skal føre en tilgjengelig oversikt og gi forhåndsvarsel om planlagte tillegg eller utskiftninger slik at kunden kan fremsette en saklig personverninnsigelse før endringen.",
            "Leverandøren pålegger underdatabehandlere personvernforpliktelser som i det vesentlige tilsvarer denne avtalen, og er ansvarlig overfor kunden for deres oppfyllelse etter personvernregelverket.",
          ],
          bullets: [],
        },
        {
          heading: "6. Overføringer utenfor EØS",
          body: [
            "Personopplysninger skal bare overføres til et tredjeland eller en internasjonal organisasjon etter kundens dokumenterte instrukser og når kravene i personvernregelverket er oppfylt. Før en aktuell overføring skal leverandøren sikre et gyldig overføringsgrunnlag og nødvendige tilleggstiltak, og gjøre relevant informasjon tilgjengelig for kunden.",
          ],
          bullets: [],
        },
        {
          heading: "7. Bistand og registrertes rettigheter",
          body: [
            "Med hensyn til behandlingens art bistår leverandøren, så langt det er mulig, kunden med egnede tiltak for forespørsler om registrertes rettigheter. Dersom leverandøren mottar en slik forespørsel om kundens data, videresendes den til kunden med mindre lov krever annet.",
            "Leverandøren bistår rimelig med sikkerhetsplikter, vurdering og melding av brudd, personvernkonsekvensvurderinger og forhåndsdrøftelser med tilsynsmyndigheter, hensyntatt informasjonen leverandøren har og behandlingens art.",
          ],
          bullets: [],
        },
        {
          heading: "8. Brudd på personopplysningssikkerheten",
          body: [
            "Leverandøren varsler kunden uten ugrunnet opphold etter å ha blitt kjent med et brudd som berører personopplysninger behandlet på kundens vegne. Varselet skal etter hvert som informasjonen blir tilgjengelig beskrive hendelsen, berørte kategorier, sannsynlige konsekvenser, tiltak og kontaktpunkt. Kunden avgjør egne varsler til registrerte og myndigheter.",
          ],
          bullets: [],
        },
        {
          heading: "9. Dokumentasjon og revisjon",
          body: [
            "Leverandøren gjør informasjon som er nødvendig for å påvise oppfyllelse av artikkel 28 tilgjengelig for kunden og bidrar til rimelige revisjoner og inspeksjoner. Partene skal først bruke relevant dokumentasjon og fjernkontroll der dette gir tilstrekkelig sikkerhet. Revisjon skal varsles rimelig, begrenses til kundens behandling og beskytte andre kunders opplysninger og leverandørens sikkerhet og konfidensialitet.",
          ],
          bullets: [],
        },
        {
          heading: "10. Retur, sletting og opphør",
          body: [
            "Etter den godkjente lese- og eksportperioden skal leverandøren etter kundens dokumenterte valg returnere eller slette personopplysninger og eksisterende kopier, med mindre en lov plikter Talli direkte til fortsatt lagring eller kunden gir en lovlig oppbevaringsinstruks. Kundens egen bokføringsplikt gir ikke Talli en generell rett til å beholde alle kundedata. Tjenestens operative rutiner kan fastsette rimelig tidspunkt og teknisk rekkefølge, men begrenser ikke kundens valg.",
            "Opplysninger som må beholdes etter lov, isoleres fra ordinær behandling og brukes bare for oppbevaringsformålet. Når sikkerhetskopiering og rotasjon er verifisert i gjeldende produksjonsmiljø, skal kopier slettes eller overskrives etter den verifiserte rotasjonen. Forpliktelsene i avtalen gjelder frem til sletting eller anonymisering.",
          ],
          bullets: [],
        },
        {
          heading: "11. Kontakt og prioritet",
          body: [
            "Personvernhenvendelser sendes til post@talli.no. Ved motstrid om behandling av personopplysninger går denne databehandleravtalen foran de generelle brukervilkårene.",
          ],
          bullets: [],
        },
      ],
    },
  },

  obligations: {
    aksjonaerregisteroppgaven: "Aksjonærregisteroppgaven",
    skattemelding: "Skattemelding for AS",
    aarsregnskap: "Årsregnskap",
  },

  status: {
    ready: "Klar",
    notAssessed: "Ikke vurdert",
    blocked: "Blokkert",
    review: "Trenger gjennomgang",
    filed: "Levert",
    draft: "Utkast",
  },

  dashboard: {
    welcomeTitle: "Velkommen til Talli",
    orgLine: (org: string, year: number) =>
      `Org.nr ${org} · Inntektsår ${year}`,
    complianceTitle: (year: number) => `Årsoppgjør ${year}`,
    overviewTitle: "Oversikt",
    deadlinesTitle: "Frister",
    nextStepEyebrow: "Neste steg",
    metrics: {
      documents: "Dokumenter",
      transactions: "Transaksjoner",
      unmatched: "Uavstemte",
      actions: "Holdinghandlinger",
    },
    empty: {
      title: "Sett opp holdingselskapet ditt",
      body: "Hent selskapet fra Brønnøysund, så ordner vi årsoppgjøret sammen — det tar under ett minutt.",
      cta: "Kom i gang",
    },
    nextAction: {
      setupEyebrow: "Kom i gang",
      setupTitle: "Sett opp holdingselskapet ditt",
      setupBody:
        "Hent selskapet fra Brønnøysund og fullfør oppsettet på under ett minutt.",
      setupCta: "Kom i gang",
      pendingEyebrow: (year: number) => `Årsoppgjør ${year}`,
      pendingTitle: "Gjør klar årsoppgjøret",
      pendingBody: (remaining: number, total: number) =>
        `${remaining} av ${total} plikter gjenstår før du kan sende inn.`,
      pendingCta: "Fortsett",
      reconcileEyebrow: "Avstemming",
      reconcileTitle: "Avstem banktransaksjoner",
      reconcileBody: (count: number) =>
        `${count} transaksjoner mangler kobling mot regnskapet.`,
      reconcileCta: "Avstem nå",
      readyEyebrow: "Status",
      readyTitle: "Alt ser klart ut",
      readyBody:
        "Forhåndsvis og send inn når du er klar. Talli holder deg i forhåndsvisning til alt er trygt.",
      readyCta: "Se innsending",
    },
    blockersLabel: "Dette gjenstår:",
    openFilingCta: "Åpne",
  },

  workspace: {
    boundaryEyebrow: "Innsending",
    boundaryTitle: "Holding-først årsrapportering for enkle AS.",
    authorities: "Myndigheter",
    authoritiesValue: "Ikke tilknyttet",
    directFiling: "Direkte innsending",
    directFilingValue: "Åpnes senere",

    introEyebrow: "Arbeidsflate",
    introTitle: "Holdingselskapet ditt",
    introLede:
      "Alle verktøyene for holdingselskapets årsoppgjør samlet på ett sted.",

    statusHeading: "Status",
    signedIn: "Innlogget",
    signedOut: "Ikke innlogget",
    companiesLabel: "Selskaper",
    connectionLabel: "Tilkobling",
    connectionOk: "OK",
    connectionError: "Feil",

    createEyebrow: "Nytt selskap",
    createTitle: "Hent selskapet fra Brønnøysund.",
    createCta: "Hent fra Brønnøysund og opprett",
    onlyAs: "Kun AS går videre. ENK, NUF, ASA og andre selskapsformer stoppes før selskapet opprettes.",
    agreementAcceptance: {
      authority: "Jeg bekrefter at jeg har fullmakt til å inngå avtale på vegne av selskapet, og godtar Talli",
      businessTerms: "Brukervilkår for bedriftskunder",
      conjunction: "og",
      dpa: "Databehandleravtalen.",
    },

    companiesEyebrow: "Dine selskaper",
    companiesTitle: "Selskapene dine.",
    noCompaniesLabel: "Ingen selskap",
    noCompaniesStatus: "Utkast",
    noCompaniesBody: "Opprett ditt første selskap for å komme i gang.",

    security: {
      eyebrow: "Sikkerhet",
      title: "Sensitive handlinger krever ekstra bekreftelse.",
      body: "Innsending, innsendingsrett, invitasjon av gjennomgåer, rolleendring, arkiveksport, faktureringsendring og sletting krever at du bekrefter identiteten din på nytt. Både tillatte og blokkerte forsøk lagres i loggen – uten sensitive detaljer.",
      points: [
        "Sikker pålogging",
        "Eierrolle i selskapet",
        "Hvert selskaps data er adskilt fra andres",
        "Ny identitetsbekreftelse innen 15 minutter for sensitive handlinger",
        "Logg av både tillatte og blokkerte forsøk",
      ],
    },
  },

  onboarding: {
    title: "Kom i gang",
    intro:
      "Vi setter opp holdingselskapet ditt for årsoppgjøret — steg for steg.",
    steps: {
      company: "Selskap",
      balances: "Åpningsbalanse",
      bank: "Bank (valgfritt)",
    },
    lookup: {
      title: "Finn selskapet ditt",
      intro: "Vi henter selskapsdetaljene fra Brønnøysundregistrene.",
      orgLabel: "Organisasjonsnummer",
      orgHelp: "9 sifre. Vi henter navn og adresse automatisk.",
      orgInvalid: "Organisasjonsnummer må ha 9 sifre.",
      boundaryTitle: "Kun for enkle holding-AS",
      boundaryBody:
        "Talli støtter aksjeselskap (AS). Andre selskapsformer som ENK, NUF og ASA, eller selskaper som trenger regnskapsfører, stoppes her.",
      cta: "Hent fra Brønnøysund",
      pending: "Henter …",
    },
    balances: {
      title: "Åpningsbalanse",
      intro: "Registrer aksjekapital, aksjonærer og bankinnskudd ved oppstart.",
      yearLabel: "Regnskapsår",
      bankLabel: "Bankinnskudd (kr)",
      shareCapitalLabel: "Aksjekapital (kr)",
      shareCountLabel: "Antall aksjer",
      nominalLabel: "Pålydende per aksje (kr)",
      shareholdersTitle: "Aksjonærer",
      addShareholder: "Legg til aksjonær",
      removeShareholder: "Fjern",
      nameLabel: "Navn",
      kindLabel: "Type",
      kindPerson: "Person",
      kindCompany: "Selskap",
      nationalIdLabel: "Fødselsnummer (11 sifre)",
      orgNumberLabel: "Organisasjonsnummer (9 sifre)",
      sharesLabel: "Aksjer",
      reconcileTitle: "Avstemming",
      checkCapital: "Aksjekapital = antall aksjer × pålydende",
      checkShares: "Sum aksjer per aksjonær = antall aksjer",
      checkShareholders: "Hver aksjonær har gyldig navn og ID",
      ok: "Stemmer",
      mismatch: "Avvik",
      blockedHint: "Rett opp avvikene før du kan fortsette.",
      cta: "Lagre og fortsett",
      pending: "Lagrer …",
    },
    bank: {
      title: "Importer banktransaksjoner",
      intro:
        "Valgfritt: last opp bankutskrift (CSV) for året, så avstemmer vi senere. Du kan hoppe over og gjøre dette når som helst.",
      csvLabel: "Bank CSV (valgfritt)",
      csvHelp: "Last opp CSV-en fra nettbanken med kolonnene dato, tekst, beløp og saldo.",
      dropLabel: "Slipp CSV-filen her, eller klikk for å velge",
      dropHint: "Kun .csv-filer fra nettbanken.",
      chosen: (fileName: string) => `Valgt fil: ${fileName}`,
      fileError: "Dette ser ikke ut som en CSV-fil. Velg en .csv-fil eksportert fra nettbanken.",
      importedTitle: "Importert",
      importedBody: (count: number) =>
        `${count} banktransaksjoner er registrert.`,
      cta: "Importer",
      pending: "Importerer …",
      persistedPreviewTitle: "Kontoutskriften er klar til kontroll",
      persistedPreviewBody: (n: number) =>
        `${n} ${n === 1 ? "transaksjon er" : "transaksjoner er"} lest inn. Ingenting importeres før du bekrefter.`,
      acceptCta: "Bekreft og importer",
      acceptPending: "Importerer …",
      finish: "Fullfør og gå til oversikt",
      skip: "Hopp over",
    },
  },

  actions: {
    hubTitle: "Holdinghandlinger",
    hubIntro:
      "Registrer kjøp og salg av aksjer, utbytte, lån og skatt — steg for steg, med forhåndsvisning av bokføringen før du bekrefter.",
    needsCompanyTitle: "Sett opp selskapet først",
    needsCompanyBody:
      "Du må sette opp holdingselskapet før du kan registrere handlinger.",
    needsCompanyCta: "Kom i gang",
    chooseTitle: "Hva vil du registrere?",
    recentTitle: "Nylig bokført",
    recentEmpty: "Ingen handlinger er bokført ennå.",
    posted: "Handlingen er bokført. Du finner den i listen under.",
    backToHub: "Tilbake til handlinger",

    previewTitle: "Forhåndsvisning av bokføring",
    previewIntro: "Dette posteres når du bekrefter:",
    blockTitle: "Dette må en regnskapsfører se på",
    confirmCta: "Bekreft og bokfør",
    pending: "Bokfører …",
    fillToPreview: "Fyll ut feltene over for å se bokføringen.",
    debit: "Debet",
    credit: "Kreditt",
    account: "Konto",
    dateHelp: "Format: ÅÅÅÅ-MM-DD",
    yearLabel: "Inntektsår",
    doc: {
      label: "Dokumentasjon",
      attached: "Bilag vedlagt",
      missing: "Mangler bilag (akseptert)",
      notRequired: "Ikke påkrevd",
    },
    taxTreatment: {
      label: "Skattemessig behandling",
      fritak: "Fritaksmetoden (vanlig for holding-AS)",
      outside: "Utenfor fritaksmetoden",
      needsAccountant: "Usikker / annet",
    },
    investmentKind: {
      label: "Type investering",
      norwegianPrivate: "Norsk privat aksjeselskap (AS)",
      listed: "Børsnotert / annet verdipapir",
    },

    accountNames: {
      "1370": "Fordring på aksjonær",
      "1570": "Skatt til gode",
      "1800": "Aksjer og andeler",
      "1920": "Bankinnskudd",
      "2050": "Avsatt utbytte",
      "2255": "Gjeld til aksjonær",
      "2500": "Betalbar skatt",
      "8070": "Finansinntekt (utbytte/gevinst)",
      "8090": "Finanskostnad (tap)",
      "8300": "Skattekostnad",
    } as Record<string, string>,

    typeLabels: {
      share_purchase: "Kjøp aksjer",
      share_sale: "Selg aksjer",
      dividend_received: "Mottatt utbytte",
      dividend_to_owner: "Utbytte til deg",
      shareholder_loan: "Aksjonærlån",
      tax_settlement: "Skatteoppgjør",
    } as Record<string, string>,

    cards: {
      "share-purchase": {
        title: "Kjøp aksjer",
        body: "Registrer kjøp av aksjer i et norsk AS.",
      },
      "share-sale": {
        title: "Selg aksjer",
        body: "Selg fra en eksisterende posisjon, med gevinst eller tap.",
      },
      "dividend-received": {
        title: "Mottatt utbytte",
        body: "Utbytte selskapet har mottatt på sine investeringer.",
      },
      "owner-dividend": {
        title: "Utbytte til deg",
        body: "Del ut utbytte til aksjonær, med selskapsdokumenter.",
      },
      "shareholder-loan": {
        title: "Aksjonærlån",
        body: "Lån mellom selskapet og en aksjonær.",
      },
      "tax-settlement": {
        title: "Skatteoppgjør",
        body: "Betalbar skatt, betaling eller refusjon.",
      },
    } as Record<string, { title: string; body: string }>,

    sharePurchase: {
      title: "Kjøp aksjer",
      intro:
        "Registrer kjøp av aksjer i et norsk aksjeselskap under fritaksmetoden.",
      nameLabel: "Selskapet du kjøper i",
      keyLabel: "Investerings-ID",
      keyHelp: "En kort, fast referanse — f.eks. selskapets kortnavn.",
      orgLabel: "Organisasjonsnummer",
      dateLabel: "Kjøpsdato",
      sharesLabel: "Antall aksjer",
      amountLabel: "Kjøpsbeløp (kr)",
    },
    shareSale: {
      title: "Selg aksjer",
      intro: "Selg fra en eksisterende investeringsposisjon.",
      positionLabel: "Posisjon",
      positionPlaceholder: "Velg posisjon",
      noPositions:
        "Du har ingen investeringsposisjoner å selge fra ennå. Registrer et aksjekjøp først.",
      dateLabel: "Salgsdato",
      sharesLabel: "Antall solgte aksjer",
      proceedsLabel: "Salgsproveny (kr)",
      gainLabel: "Beregnet gevinst",
      lossLabel: "Beregnet tap",
      remainingLabel: "Gjenstående aksjer",
      ofShares: (count: number) => `${count} aksjer tilgjengelig`,
    },
    dividendReceived: {
      title: "Mottatt utbytte",
      intro: "Registrer utbytte selskapet har mottatt på en investering.",
      payerLabel: "Utbetalende selskap",
      investmentLabel: "Investering",
      investmentPlaceholder: "Velg investering",
      noInvestments:
        "Du har ingen investeringer ennå. Registrer et aksjekjøp først.",
      declaredLabel: "Vedtaksdato",
      paidLabel: "Utbetalingsdato",
      amountLabel: "Brutto utbytte (kr)",
      addBackNote: (amount: number) =>
        `3 % av utbyttet (${amount} kr) legges til som skattepliktig inntekt under fritaksmetoden.`,
    },
    ownerDividend: {
      title: "Utbytte til deg",
      intro:
        "Del ut utbytte til en aksjonær. Talli oppretter styreforslag og protokoll som arkivklare dokumenter.",
      shareholderLabel: "Aksjonær",
      shareholderPlaceholder: "Velg aksjonær",
      noShareholders:
        "Du har ingen registrerte aksjonærer ennå. Fullfør oppsettet først.",
      decisionLabel: "Beslutningsdato",
      paymentLabel: "Betalingsdato",
      amountLabel: "Utbyttebeløp (kr)",
      equityLabel: "Fri egenkapital (kr)",
      equityHelp: "Utbyttet kan ikke overstige fri egenkapital.",
      liquidityLabel: "Likviditet etter utbetaling (kr)",
      liquidityHelp: "Må være null eller positiv.",
    },
    shareholderLoan: {
      title: "Aksjonærlån",
      intro: "Registrer lån mellom selskapet og en aksjonær.",
      directionLabel: "Retning",
      dirToCompany: "Aksjonær låner til selskapet",
      dirToCorporate: "Selskapet låner til selskapsaksjonær",
      dirToPersonal: "Selskapet låner til personlig aksjonær",
      personalBlock:
        "Lån fra selskap til personlig aksjonær må håndteres av regnskapsfører.",
      securityBlock:
        "Sikkerhet eller garanti mellom nærstående må vurderes av regnskapsfører.",
      dateLabel: "Lånedato",
      amountLabel: "Lånebeløp (kr)",
      counterpartyLabel: "Motpart",
      securityLabel: "Sikkerhet eller garanti mellom nærstående",
      interestLabel: "Rente er beregnet",
    },
    taxSettlement: {
      title: "Skatteoppgjør",
      intro: "Registrer betalbar skatt, betaling eller refusjon.",
      typeLabel: "Type",
      typePayable: "Betalbar skatt (avsetning)",
      typePayment: "Betaling av skatt",
      typeRefund: "Skatterefusjon",
      dateLabel: "Oppgjørsdato",
      amountLabel: "Beløp (kr)",
    },
  },

  yearEnd: {
    title: (year: number) => `Årsavslutning ${year}`,
    intro:
      "Vi går gjennom året sammen, steg for steg. Svarene dine fyller ut det vi trenger til aksjonærregisteroppgaven, skattemeldingen og årsregnskapet.",
    needsCompanyTitle: "Sett opp selskapet først",
    needsCompanyBody:
      "Du må sette opp holdingselskapet før du kan gjøre årsavslutningen.",
    needsCompanyCta: "Kom i gang",
    resumeNote: "Svarene er lagret og kan endres når som helst.",
    yes: "Ja",
    no: "Nei",
    back: "Tilbake",
    next: "Neste",
    submit: "Lagre og gå til oversikten",
    pending: "Lagrer …",
    steps: {
      activity: "Aktivitet",
      control: "Kontroll",
      approval: "Godkjenning",
      summary: "Oppsummering",
    },
    stepHeads: {
      activity: {
        title: "Hva skjedde i selskapet i år?",
        intro: "Svar så godt du kan – vi sjekker mot det du har registrert.",
      },
      control: {
        title: "Stemmer tallene?",
        intro: "To raske kontroller før vi går videre.",
      },
      approval: {
        title: "Godkjenning og innsendingsrett",
        intro: "Det siste vi trenger for å kunne sende inn.",
      },
      summary: {
        title: "Oppsummering",
        intro: "Slik ser året ut. Lagre når du er klar.",
      },
    },
    fteLabel: "Antall årsverk i selskapet",
    fteHelp: "Et holdingselskap uten ansatte har som regel 0.",
    questions: {
      shares_owned_at_year_end: {
        q: "Eide selskapet aksjer ved årsslutt?",
      },
      bought_or_sold_shares: {
        q: "Kjøpte eller solgte selskapet aksjer i år?",
      },
      received_dividends: {
        q: "Mottok selskapet utbytte på sine investeringer?",
      },
      declared_owner_dividends: {
        q: "Besluttet selskapet å dele ut utbytte til eier?",
      },
      shareholder_loans: {
        q: "Har selskapet lån til eller fra en aksjonær?",
      },
      paid_costs: {
        q: "Betalte selskapet kostnader i år (gebyrer, revisor og lignende)?",
      },
      bank_balance_confirmed: {
        q: "Har du kontrollert at bankbalansen stemmer med kontoutskriften?",
      },
      has_unpaid_items: {
        q: "Har selskapet ubetalte poster (leverandørgjeld eller uoppgjorte krav)?",
      },
      general_meeting_approved: {
        q: "Har generalforsamlingen godkjent årsregnskapet?",
      },
      authority_to_submit_confirmed: {
        q: "Bekrefter du at du har rett til å sende inn på vegne av selskapet?",
      },
    } as Record<string, { q: string; help?: string }>,
    // Inline consistency nudges: an interview answer that implies a registration
    // the owner has not made yet, or a state that blocks a later filing.
    consistency: {
      bought_or_sold_shares:
        "Registrer kjøpet eller salget under Handlinger, slik at aksjonærregisteroppgaven og skattemeldingen stemmer.",
      received_dividends:
        "Registrer mottatt utbytte under Handlinger – det påvirker skattemeldingen med 3 % sjablongskatt.",
      declared_owner_dividends:
        "Registrer utbytte til eier under Handlinger, og kontroller at generalforsamlingen har godkjent det.",
      shareholder_loans:
        "Registrer aksjonærlånet under Handlinger, så det kommer med i årsregnskapet.",
      paid_costs:
        "Sørg for at kostnadene er bokført, slik at årsregnskapet og skattemeldingen blir riktige.",
    } as Record<string, string>,
    warnings: {
      bankNotConfirmed:
        "Bankbalansen bør kontrolleres mot kontoutskriften før innsending.",
    },
    blocks: {
      unpaidItems:
        "Ubetalte poster støttes ikke i den enkle årsavslutningen. Ta kontakt med regnskapsfører.",
      generalMeeting:
        "Generalforsamlingen må godkjenne årsregnskapet før det kan sendes inn.",
      authority:
        "Du må bekrefte innsendingsrett før noe kan sendes inn.",
    },
    summary: {
      activityTitle: "Aktivitet i året",
      noActivity:
        "Dette ser ut som et år uten aktivitet. Talli forbereder en forenklet innsending.",
      noneActive: "Ingen aktivitet registrert i året.",
      blocksTitle: "Dette må løses før innsending",
      remindersTitle: "Husk å registrere",
      allClear: "Alt ser bra ut. Lagre, så finner du neste steg på oversikten.",
      activeLine: (label: string) => label,
    },
    activityLabels: {
      shares_owned_at_year_end: "Eide aksjer ved årsslutt",
      bought_or_sold_shares: "Kjøpte eller solgte aksjer",
      received_dividends: "Mottok utbytte",
      declared_owner_dividends: "Besluttet utbytte til eier",
      shareholder_loans: "Aksjonær- eller konsernlån",
      paid_costs: "Betalte kostnader",
    } as Record<string, string>,
  },

  filing: {
    title: "Innsending",
    previewLabel: "Forhåndsvisning",
    notAffiliated: requiredNonAffiliationCopy,
    preProductionGate: preProductionDirectFilingCopy,
    hubTitle: "Innsending",
    hubLede:
      "Når året er ferdig ryddet, sender du inn herfra. Talli sjekker at alt er klart før noe går ut, og arkiverer en kvittering.",
    needsCompanyTitle: "Sett opp selskapet først",
    needsCompanyBody: "Du må sette opp holdingselskapet før du kan sende inn.",
    needsCompanyCta: "Kom i gang",
    yearLabel: (year: number) => `Inntektsår ${year}`,
    openCta: "Åpne",
    backToHub: "Til innsending",
    status: {
      ready: "Klar til innsending",
      blocked: "Noe gjenstår",
      warning: "Klar – med merknader",
      submitted: "Sendt (simulert)",
      preparing: "Under arbeid",
    },
    production: {
      title: "Reell innsending av aksjonærregisteroppgaven",
      warning:
        "Dette er en reell innsending til Skatteetaten med juridiske konsekvenser. En mottakskvittering betyr ikke at innholdet er endelig godkjent.",
      companyLabel: "Selskap",
      yearLabel: "Inntektsår",
      caseLabel: "Sakstype",
      supportedCase: "Selskap uten aktivitet eller i stiftelsesåret",
      privateFeedback:
        "Tilbakemeldinger lagres privat og kan lastes ned med kortvarig tilgang.",
      approveCheck:
        "Jeg har kontrollert opplysningene og forstår at dette kan bli sendt som en reell aksjonærregisteroppgave.",
      approvePending: "Lagrer godkjenningen …",
      approveCta: "Godkjenn innholdet",
      sendPending: "Sender sikkert …",
      sendCta: "Send aksjonærregisteroppgaven",
      reconciliation: {
        checkPending: "Sjekker status …",
        checkCta: "Sjekk status på nytt",
      },
      states: {
        sending: {
          label: "Sender",
          body: "Vi sender oppgaven og lagrer mottaksstatusen.",
          variant: "warning",
        },
        sent: {
          label: "Mottatt",
          body: "Skatteetaten har mottatt oppgaven. Vi venter på den endelige tilbakemeldingen.",
          variant: "warning",
        },
        processing: {
          label: "Til behandling",
          body: "Skatteetaten behandler oppgaven. Du kan sjekke statusen på nytt.",
          variant: "warning",
        },
        unknown: {
          label: "Vi sjekker statusen på nytt",
          body: "Vi kunne ikke bekrefte statusen nå. Prøv igjen om litt.",
          variant: "warning",
        },
        accepted: {
          label: "Godkjent",
          body: "Skatteetaten har godkjent oppgaven.",
          variant: "success",
        },
        rejected: {
          label: "Avvist",
          body: "Skatteetaten har avvist oppgaven. Se tilbakemeldingen før du går videre.",
          variant: "danger",
        },
        action_required: {
          label: "Trenger oppfølging",
          body: "Tilbakemeldingen må følges opp før saken kan avsluttes.",
          variant: "danger",
        },
        approved: {
          label: "Godkjent av deg",
          body: "Innholdet er godkjent og klart til innsending.",
          variant: "info",
        },
        ready: {
          label: "Klar til gjennomgang",
          body: "Se over innholdet før du godkjenner innsendingen.",
          variant: "info",
        },
      },
      artifacts: {
        accepted: "Last ned godkjent tilbakemelding",
        rejected: "Last ned tilbakemelding om avvisning",
        action_required: "Last ned tilbakemelding som må følges opp",
        unknown: "Last ned tilbakemelding",
      },
      errors: {
        invalid_request: "Forespørselen kunne ikke behandles. Last inn siden på nytt og prøv igjen.",
        authentication_required: "Du må logge inn på nytt før du kan fortsette.",
        configuration_unavailable: "Reell innsending er midlertidig utilgjengelig.",
        approval_expired: "Godkjenningen er utdatert. Se over innholdet og godkjenn på nytt.",
        basis_unavailable: "Grunnlaget for innsendingen er ikke tilgjengelig nå.",
        connection_unavailable: "Altinn-tilkoblingen er ikke klar for innsending.",
        payload_changed: "Dataene er endret. Se over innholdet og godkjenn på nytt.",
        send_unavailable: "Innsendingen kunne ikke fullføres nå. Kontroller statusen før du prøver igjen.",
        status_unavailable: "Statusen kunne ikke kontrolleres nå. Prøv igjen om litt.",
        status_busy: "En statuskontroll pågår allerede. Vent litt før du prøver igjen.",
        unavailable: "Handlingen er midlertidig utilgjengelig. Prøv igjen om litt.",
      },
    },
    obligations: {
      aksjonaerregisteroppgaven: {
        label: "Aksjonærregisteroppgaven",
        short: "RF-1086",
        summary: "Hvem som eier selskapet, og endringer i året.",
        lede:
          "Vi setter sammen aksjonærregisteroppgaven fra åpningsbalansen og handlingene dine. Til slutt arkiverer vi en simulert kvittering.",
      },
      skattemelding: {
        label: "Skattemelding for AS",
        short: "Skattemelding",
        summary: "Selskapets skatt for året.",
        lede:
          "Talli rydder grunnlaget for skattemeldingen. Selve forhåndsvisningen og innsendingen er under arbeid.",
      },
      aarsregnskap: {
        label: "Årsregnskap",
        short: "Årsregnskap",
        summary: "Resultat og balanse for året.",
        lede:
          "Talli rydder grunnlaget for årsregnskapet. Selve forhåndsvisningen og innsendingen er under arbeid.",
      },
    } as Record<
      string,
      { label: string; short: string; summary: string; lede: string }
    >,
    steps: {
      check: "Sjekk",
      preview: "Forhåndsvisning",
      authority: "Innsendingsrett",
      confirm: "Bekreft",
      receipt: "Kvittering",
    },
    check: {
      title: "Er alt klart?",
      readyBody: "Alt ser bra ut. Gå videre til forhåndsvisningen.",
      blockedBody: "Dette må på plass før du kan sende inn:",
      warningBody: "Du kan gå videre, men se over disse merknadene:",
      refreshCta: "Oppdater status",
      refreshPending: "Oppdaterer …",
      fixCta: "Løs",
    },
    preview: {
      title: "Forhåndsvisning",
      intro:
        "Slik ser oppgaven ut. Kontroller at tallene stemmer før du bekrefter.",
      generateIntro:
        "Vi lager forhåndsvisningen fra den låste åpningsbalansen og handlingene dine.",
      generateCta: "Lag forhåndsvisning",
      generatePending: "Lager …",
      notReady:
        "Forhåndsvisningen er ikke klar ennå. Løs punktene over og lag den på nytt.",
      regenerateCta: "Lag på nytt",
      preparing:
        "Forhåndsvisning og innsending for denne oppgaven er under arbeid. Du kan allerede nå rydde alt som må på plass via sjekklisten over.",
      lockedNote: "Fullfør sjekken over for å lage forhåndsvisningen.",
    },
    authority: {
      title: "Innsendingsrett",
      intro:
        "Bekreft at du har rett til å sende inn denne oppgaven på vegne av selskapet.",
      confirmLabel:
        "Jeg bekrefter at jeg har rett til å sende inn for selskapet.",
      cta: "Bekreft innsendingsrett",
      pending: "Bekrefter …",
      confirmed: "Innsendingsrett er bekreftet.",
      lockedNote: "Lag forhåndsvisningen først.",
      connectionTitle: "Altinn-tilkobling",
      connectionCta: "Åpne tilkoblinger",
      connectionLoadError:
        "Vi kunne ikke hente den lagrede tilkoblingsstatusen. Åpne tilkoblinger og prøv igjen.",
    },
    confirm: {
      title: "Bekreft og arkiver",
      intro:
        "Dette arkiverer en simulert kvittering. Ingen live innsending til myndighetene gjøres nå.",
      authorityCheck: "Jeg bekrefter retten til å sende inn for selskapet.",
      previewCheck: "Jeg har kontrollert forhåndsvisningen.",
      cta: "Arkiver simulert kvittering",
      pending: "Arkiverer …",
      lockedNote: "Fullfør stegene over for å kunne arkivere kvitteringen.",
    },
    receipt: {
      title: "Kvittering",
      simulatedNote: "Kun simulering. Ingen live innsending er gjort.",
      receiptLabel: "Kvitteringsnummer",
      statusLabel: "Status",
      none: "Ingen kvittering ennå.",
      exportCta: "Eksporter arkiv",
    },
    posted: "Simulert kvittering er arkivert.",
    blockers: {
      unsupported_entity: {
        message: "Talli støtter foreløpig bare aksjeselskap (AS).",
      },
      opening_balance_missing: {
        message: "Åpningsbalansen må være satt opp og låst for året.",
        fixHref: "/onboarding",
        fixLabel: "Til oppsett",
      },
      period_not_locked: { message: "Inntektsåret er ikke låst ennå." },
      annual_data_missing: {
        message: "Årsavslutningen er ikke fullført.",
        fixHref: "/year-end",
        fixLabel: "Til årsavslutning",
      },
      bank_balance_not_confirmed: {
        message: "Bankbalansen er ikke bekreftet i årsavslutningen.",
        fixHref: "/year-end",
        fixLabel: "Til årsavslutning",
      },
      unpaid_items_not_supported: {
        message:
          "Ubetalte poster støttes ikke i den enkle innsendingen. Ta kontakt med regnskapsfører.",
      },
      annual_authority_not_confirmed: {
        message: "Innsendingsrett er ikke bekreftet i årsavslutningen.",
        fixHref: "/year-end",
        fixLabel: "Til årsavslutning",
      },
      unmatched_bank_transactions: {
        message: "Alle banktransaksjoner må kontrolleres først.",
        fixHref: "/workspace",
        fixLabel: "Til arbeidsflate",
      },
      missing_documents: {
        message: "Det mangler dokumenter for oppgaven.",
        fixHref: "/workspace",
        fixLabel: "Til arbeidsflate",
      },
      blocking_filing_override: {
        message: "En manuell overstyring må løses.",
        fixHref: "/workspace",
        fixLabel: "Til arbeidsflate",
      },
      missing_authority_confirmation: {
        message: "Bekreft innsendingsrett i steget nedenfor.",
      },
      production_disabled: {
        message: "Bekreft innsendingsrett i steget nedenfor for å gå videre.",
      },
      billing_account_missing: {
        message: "Faktureringen er ikke satt opp ennå.",
        fixHref: "/workspace",
        fixLabel: "Til arbeidsflate",
      },
      subscription_required: {
        message: "Abonnementet må aktiveres før innsending.",
        fixHref: "/workspace",
        fixLabel: "Til arbeidsflate",
      },
      unsupported_case: {
        message:
          "Denne saken må håndteres manuelt. Ta kontakt med regnskapsfører.",
      },
      rf1086_preview_not_ready: {
        message: "Forhåndsvisningen er ikke klar ennå.",
      },
      blocking_holding_action: {
        message: "En registrert handling må ryddes først.",
        fixHref: "/actions",
        fixLabel: "Til handlinger",
      },
      tax_settlement_missing: {
        message: "Skatteoppgjør er ikke registrert for året.",
        fixHref: "/actions/tax-settlement",
        fixLabel: "Registrer skatteoppgjør",
      },
      ledger_missing: {
        message: "Det må være bokført åpningsbalanse eller handlinger.",
        fixHref: "/actions",
        fixLabel: "Til handlinger",
      },
      general_meeting_not_approved: {
        message: "Generalforsamlingen må godkjenne årsregnskapet.",
        fixHref: "/year-end",
        fixLabel: "Til årsavslutning",
      },
      manual_journal_warning_unaccepted: {
        message: "En manuell postering med merknad må gjennomgås.",
        fixHref: "/workspace",
        fixLabel: "Til arbeidsflate",
      },
    } as Record<
      string,
      { message: string; fixHref?: string; fixLabel?: string }
    >,
    blockerFallback: "Et punkt gjenstår før innsending.",
  },

  transactions: {
    hubTitle: "Transaksjoner",
    hubLede:
      "Importer kontoutskriften og avstem hver linje. Talli foreslår hva som hører sammen – du bekrefter.",
    needsCompanyTitle: "Sett opp selskapet først",
    needsCompanyBody:
      "Du må sette opp holdingselskapet før du kan importere transaksjoner.",
    needsCompanyCta: "Kom i gang",
    yearLabel: (year: number) => `Inntektsår ${year}`,
    imported: "Kontoutskriften er importert.",
    posted: "Transaksjonen er avstemt.",
    import: {
      title: "Importer kontoutskrift",
      intro:
        "Last opp kontoutskriften som CSV. Første linje må ha kolonnene date, text og amount – balance er valgfritt.",
      formatHint:
        "Format: date,text,amount,balance — én transaksjon per linje, dato som ÅÅÅÅ-MM-DD.",
      dropLabel: "Slipp CSV-filen her, eller klikk for å velge",
      dropHint: "Kun .csv-filer.",
      chosen: (fileName: string) => `Valgt fil: ${fileName}`,
      fileError: "Dette ser ikke ut som en CSV-fil. Velg en .csv-fil eksportert fra nettbanken.",
      previewTitle: "Forhåndsvisning",
      previewEmpty: "Last opp CSV-en for å se en forhåndsvisning.",
      previewCount: (n: number) =>
        `${n} ${n === 1 ? "transaksjon" : "transaksjoner"} klar til import`,
      persistedPreviewTitle: "Kontoutskriften er klar til kontroll",
      persistedPreviewBody: (n: number) =>
        `${n} ${n === 1 ? "transaksjon er" : "transaksjoner er"} lest inn. Ingenting importeres før du bekrefter.`,
      acceptCta: "Bekreft og importer",
      acceptPending: "Importerer …",
      moreRows: (n: number) => `+ ${n} flere`,
      missingColumns:
        "CSV-en mangler kolonnene date, text og amount. Sjekk den første linjen.",
      cta: "Importer",
      pending: "Importerer …",
      cols: { date: "Dato", text: "Tekst", amount: "Beløp", balance: "Saldo" },
    },
    queue: {
      title: "Til avstemming",
      intro: "Disse linjene mangler en kobling. Velg hva hver enkelt gjelder.",
      countLabel: (n: number) => `${n} til avstemming`,
      incoming: "Innbetaling",
      outgoing: "Utbetaling",
      suggestionBadge: "Forslag",
      suggestionTitle: "Talli foreslår denne posteringen",
      suggestionHint:
        "Kontroller kontoene og beløpet. Ingenting bokføres før du godkjenner.",
      suggestionCta: "Godkjenn og avstem",
      suggestionPending: "Godkjenner …",
      resolveCostTitle: "Bokfør som kostnad",
      resolveCostHint: "Gebyrer, regnskap, programvare og lignende.",
      resolveActionTitle: "Registrer som handling",
      resolveActionHint: "Utbytte, kjøp eller salg av aksjer, aksjonærlån.",
      resolveActionCta: "Til handlinger",
      resolveManualTitle: "Noe annet",
      resolveManualHint:
        "Poster som ikke passer over, kan posteres manuelt i arbeidsflaten.",
      resolveManualCta: "Til arbeidsflate",
      categoryLabel: "Kategori",
      payeeLabel: "Mottaker",
      bookCta: "Bokfør og avstem",
      bookPending: "Bokfører …",
      categories: {
        bank_fee: "Bankgebyr",
        accounting_fee: "Regnskap",
        software: "Programvare",
        public_fee: "Offentlig gebyr",
        legal_advisory: "Juridisk rådgivning",
        other_admin_cost: "Annen administrasjon",
      } as Record<string, string>,
    },
    emptyTitle: "Ingen transaksjoner ennå",
    emptyBody:
      "Importer kontoutskriften over for å komme i gang med avstemmingen.",
    allReconciledTitle: "Alt er avstemt",
    allReconciledBody: (n: number) =>
      `Alle ${n} ${n === 1 ? "transaksjon er" : "transaksjoner er"} koblet. Fint jobbet!`,
    reconciledTitle: "Avstemt i år",
    reconciledCount: (n: number) => `${n} avstemt`,
  },
  documents: {
    hubTitle: "Dokumenter",
    hubLede:
      "Last opp bilag og regnskap, last dem trygt ned igjen, og hent ut et komplett arkiv for året.",
    needsCompanyTitle: "Sett opp selskapet først",
    needsCompanyBody:
      "Du må sette opp holdingselskapet før du kan laste opp dokumenter.",
    needsCompanyCta: "Kom i gang",
    yearLabel: (year: number) => `Inntektsår ${year}`,
    uploaded: "Dokumentet er lastet opp.",
    removed: "Feilopplastingen er fjernet. En auditpost er beholdt.",
    upload: {
      title: "Last opp dokument",
      intro:
        "Bankutskrifter, kvitteringer, protokoller og annet som hører til regnskapet.",
      typeLabel: "Type",
      types: {
        bank_statement: "Bankutskrift",
        accounting_document: "Regnskapsbilag",
        corporate_document: "Selskapsdokument",
      } as Record<string, string>,
      linkedToLabel: "Gjelder",
      linkedOptions: {
        workspace: "Generelt",
        aksjonaerregisteroppgaven: "Aksjonærregisteroppgaven",
        skattemelding: "Skattemelding",
        aarsregnskap: "Årsregnskap",
      } as Record<string, string>,
      fileLabel: "Fil",
      fileHint:
        "PDF, maks 10 MB. Filen lagres privat for selskapet og kan bare lastes ned av deg.",
      chooseFile: "Velg en fil for å laste opp",
      cta: "Last opp",
      pending: "Laster opp …",
    },
    list: {
      title: "Dine dokumenter",
      intro: "Alle bilag for selskapet, med trygg nedlasting.",
      download: "Last ned",
      remove: "Fjern feilopplasting",
      removing: "Fjerner …",
      removeConfirm:
        "Filen fjernes permanent fra dokumentlageret. Dette er bare mulig når den ikke brukes som regnskaps- eller innsendingsbevis. Fortsette?",
      secureNote: "Nedlasting er sikret og lenken utløper etter kort tid.",
      missingHint:
        "Dette er en plassholder. Last opp selve filen for å fullføre.",
      missingCta: "Last opp fil",
      statusAttached: "Lastet opp",
      statusMissing: "Mangler fil",
      statusNotRequired: "Ikke påkrevd",
      genericType: "Dokument",
    },
    emptyTitle: "Ingen dokumenter ennå",
    emptyBody:
      "Last opp det første bilaget over for å begynne å bygge selskapsarkivet.",
    archive: {
      title: "Eksporter selskapsarkiv",
      body:
        "Et komplett arkiv for inntektsåret: selskapsdata, åpningsbalanse, posteringer, handlinger, innsendinger og bilagsoversikt – samlet i én fil du kan ta vare på.",
      cta: "Eksporter arkiv",
      secureNote:
        "Eksport kan kreve at du bekrefter identiteten din en ekstra gang.",
      notReadyTitle: "Arkivet er klart etter første innsending",
      notReadyBody:
        "Når du har arkivert en innsending for året, kan du hente ut hele selskapsarkivet her.",
      notReadyCta: "Til innsending",
    },
  },
  billing: {
    hubTitle: "Abonnement",
    hubLede:
      "Se selskapsåret, abonnementsstatusen og betalingen. Du blir ikke belastet før betaling åpnes.",
    needsCompanyTitle: "Sett opp selskapet først",
    needsCompanyBody:
      "Du må sette opp holdingselskapet før du kan se abonnementet.",
    needsCompanyCta: "Kom i gang",
    planTitle: "Prisplan",
    plans: {
      founder: "Founder",
      standard: "Standard",
    } as Record<string, string>,
    currentPlanLabel: "Din plan",
    perMonth: (kr: number) => `${kr} kr/md`,
    packagePrice: (kr: number) => `${kr} kr per innsending`,
    founderCohort: (n: number) => `Founder-plass nr. ${n} av 100`,
    statusTitle: "Status",
    subscription: {
      title: "Abonnement",
      active: "Aktivt",
      inactive: "Ikke aktivert ennå",
      activeHint: "Abonnementet ditt er aktivt.",
      inactiveHint: "Abonnementet aktiveres når betaling åpnes.",
    },
    package: {
      title: "Innsendingspakke",
      paid: "Betalt",
      unpaid: "Ikke betalt ennå",
      paidHint: "Innsendingspakken for året er betalt.",
      unpaidHint: "Innsendingspakken betales per år når du sender inn.",
    },
    refund: {
      eligibleTitle: "Du har krav på refusjon",
      eligibleBody:
        "Vi fant et avvik som Talli dekker, så betalingen for selskapsåret refunderes. Du trenger ikke gjøre noe.",
      completedTitle: "Refusjon fullført",
      completedBody: "Refusjonen er gjennomført.",
    },
    unsupportedTitle: "Utenfor det Talli støtter i dag",
    unsupportedBody:
      "Saken din er mer sammensatt enn det Talli støtter i dag. Du blir ikke belastet for selskapsåret.",
    placeholderTitle: "Betaling er ikke aktivert ennå",
    placeholderBody:
      "Du kan se planen og statusen din her. Betaling åpnes før innsending blir tilgjengelig – du blir ikke belastet før da.",
    noAccountTitle: "Abonnementet settes opp snart",
    noAccountBody:
      "Når selskapet er klart, ser du prisplan og status her. Inntil da kan du se prisene under.",
  },
} as const;

export type OwnerCopy = typeof ownerCopy;
