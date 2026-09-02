const companyYearPromise = {
  mode: "atomic_company_year",
  startsOn: "2026-01-01",
  endsOn: "2026-12-31",
  reconstructFrom: "2026-01-01",
  earlierYearsIncluded: false,
  onlyAccountingAndFilingProduct: true,
  capabilities: [
    "current_year_reconstruction",
    "year_round_bookkeeping",
    "required_corporate_documents",
    "rf1086_direct_filing",
    "company_tax_direct_filing",
    "annual_accounts_direct_filing",
    "bank_connection_with_hardened_file_fallback",
    "saft_1_40",
    "company_year_archive",
    "corrections",
    "official_outcomes",
    "receipts",
  ],
  customerClaims: [
    "Komplett gjenoppbygging av selskapsåret fra 1. januar",
    "Bokføring gjennom hele selskapsåret",
    "Nødvendige selskapsdokumenter",
    "Direkte innsending av aksjonærregisteroppgaven (RF-1086)",
    "Direkte innsending av skattemeldingen for selskapet",
    "Direkte innsending av årsregnskapet",
    "Banktilkobling med robust filimport som reserve",
    "SAF-T 1.40",
    "Komplett selskapsårsarkiv",
    "Sporbare rettelser",
    "Henting av offisielle utfall",
    "Kvitteringer for innsendingene",
  ],
} as const;

const refundPromise =
  "Hvis Talli bekrefter at selskapsåret støttes, men ikke kan fullføre det på grunn av feil i Tallis egen logikk eller tilkobling, får kunden hele beløpet tilbake. Betaling er ikke åpnet nå.";

const proofLinks = [
  { label: "Se selskapsgrensen", href: "/passer-talli" },
  { label: "Se pris og refusjon", href: "/pris" },
  { label: "Få hjelp", href: "/hjelp" },
  { label: "Les personvern", href: "/personvern" },
  { label: "Les vilkår og refusjon", href: "/vilkar" },
] as const;

const faq = [
  {
    question: "Hvilke selskaper passer?",
    answer:
      "Små, eierstyrte norske holding-AS med kalenderår og vanlig holdingaktivitet kan passe. Gratissjekken gir alltid det konkrete svaret.",
  },
  {
    question: "Hva er inkludert?",
    answer:
      "Når hele tilbudet åpner, inngår det komplette versjonerte selskapsåret som er listet på siden, inkludert banktilkobling og alle tre innsendingene.",
  },
  {
    question: "Trenger jeg et annet regnskapsprogram?",
    answer:
      "Et selskapsår som får endelig svaret «passer», er laget for at Talli skal være det eneste regnskaps- og innsendingsproduktet for året. Rekrutteringsmodus gir ikke produksjonsbruk.",
  },
  {
    question: "Kan jeg starte etter 1. januar?",
    answer:
      "Ja, hvis hele kalenderåret kan gjenoppbygges fra 1. januar og alle bevegelser, saldoer og dokumenter kan avstemmes. Tidligere år inngår ikke.",
  },
  {
    question: "Hva skjer hvis banken eller importen har hull?",
    answer:
      "Hele tilbudet omfatter banktilkobling med robust filimport som reserve. Manglende eller uforklarte bevegelser blokkerer året til de er avklart.",
  },
  {
    question: "Hvem kontrollerer og sender inn?",
    answer:
      "Eieren eller en juridisk representant kontrollerer, bekrefter og sender inn. Produksjonsinnsending er ikke åpnet i rekrutteringsmodus.",
  },
  {
    question: "Hva skjer når noe er uklart eller ikke støttes?",
    answer:
      "Talli stopper, forklarer hva som må avklares og lar ikke betaling eller innsending gå videre. Ukjente fakta behandles aldri som null.",
  },
  {
    question: "Hva koster det, og hvordan fungerer fornyelse og oppsigelse?",
    answer:
      "Prisen er NOK 1 490 per selskapsår. Merverdiavgift er inkludert når den gjelder etter loven. Betaling, automatisk fornyelse og belastning er ikke åpnet. Eventuelle fremtidige regler vises tydelig før kunden kan betale.",
  },
  {
    question: "Hvordan fungerer refusjon?",
    answer: refundPromise,
  },
  {
    question: "Hvordan håndterer Talli sikkerhet, personvern og hjelp?",
    answer:
      "Talli bruker bare data som trengs for tjenesten. Frivillig bruksmåling krever et eget ja og kobles ikke til konto, selskap, bank, regnskap, dokumenter eller innsendinger. Les personvernerklæringen eller kontakt post@talli.no.",
  },
] as const;

export const publicRecruitmentOffer = {
  brand: "Talli",
  mode: "recruitment",
  checkoutEnabled: false,
  capabilityManifestVersion: "2026.1",
  companyYearPromise,
  includedCapabilityKeys: companyYearPromise.capabilities,
  includedCapabilityClaims: companyYearPromise.customerClaims,
  metadata: {
    title: "Talli – regnskap og årsoppgjør for holdingselskap",
    description:
      "Sjekk gratis om Talli passer for holdingselskapet før konto eller betaling.",
  },
  recruitmentNotice:
    "Gratis rekrutterings- og valideringsmodus. Betaling, banktilkobling og produksjonsinnsending er ikke åpnet.",
  eyebrow: "For vanlige norske holding-AS",
  title: "Hele selskapsåret i ett rolig løp",
  supportingLine:
    "Skriv inn organisasjonsnummeret først. Talli sjekker offentlige fakta, spør bare om det som mangler, og gir deg et endelig svar før konto eller betaling.",
  primaryAction: {
    label: "Sjekk selskapet gratis",
    href: "/sjekk-selskapet",
  },
  includedTitle: "Dette inngår når hele tilbudet åpner",
  filings: [
    "Aksjonærregisteroppgaven (RF-1086)",
    "Skattemeldingen for selskapet",
    "Årsregnskapet",
  ],
  reconstruction:
    "Komplett gjenoppbygging av det valgte kalenderåret fra 1. januar.",
  scope: {
    title: "Passer Talli?",
    supported:
      "Talli er laget for små, eierstyrte norske holding-AS med kalenderår, én ordinær aksjeklasse, regnskap i NOK og vanlig holdingaktivitet.",
    blocked:
      "Revisjon, konsernregnskap, lønn, MVA, kundefakturering, eiendom, krypto, derivater, utenlandsk skatt og komplekse selskapsendringer støttes ikke.",
    nextStep:
      "Den gratis sjekken bruker den versjonerte selskapsgrensen og skiller mellom passer, må avklares og passer ikke.",
  },
  steps: [
    {
      title: "Sjekk offentlige fakta",
      body: "Start med organisasjonsnummeret. Svaret er tydelig merket som foreløpig.",
    },
    {
      title: "Svar på det som mangler",
      body: "Du får ett vanlig spørsmål om gangen og et endelig svar før du går videre.",
    },
    {
      title: "Bestem når du er klar",
      body: "Ingen betaling opprettes i rekrutteringsmodus.",
    },
  ],
  priceTitle: "Én pris når betaling åpner",
  priceLine:
    "NOK 1 490 per selskapsår. Merverdiavgift er inkludert når den gjelder etter loven. Banktilkobling og alle tre innsendingene er inkludert.",
  priceRestriction:
    "Du kan ikke bestille eller betale nå. Betaling åpner først etter full lanseringsklarering.",
  refundTitle: "Trygg vei ut",
  refundPromise,
  proofTitle: "Se hva løftet bygger på",
  proofBody:
    "Selskapsgrensen, vilkårene og personvernet er synlige før du bestemmer deg.",
  proofLinks,
  faqTitle: "Kort fortalt",
  faq,
  finalTitle: "Start med gratissjekken",
  finalBody:
    "Du får et tydelig foreløpig svar, og ingen konto eller betaling kreves. Den endelige sjekken må være ferdig før du kan gå videre.",
  operator:
    "Talli drives av ELMER WELFIS, org.nr. 930 835 978, Fjøsangerveien 32D, 5053 Bergen. Kontakt: post@talli.no.",
  nonAffiliation:
    "Talli er ikke tilknyttet, godkjent av eller drevet av Fiken, Altinn, Skatteetaten eller Brønnøysundregistrene.",
} as const;

export type PublicRecruitmentOffer = typeof publicRecruitmentOffer;
