import type { AnnualAccountsPayloadField } from "./annual-accounts.ts";

type AnnualAccountsPayload = {
  schemaType: string;
  hovedskjemaDataFormatId: string;
  hovedskjemaDataFormatVersion: string;
  selskapsregnskapDataFormatId: string;
  selskapsregnskapDataFormatVersion: string;
  fields: AnnualAccountsPayloadField[];
  feedback: Array<{ level: "block" | "warning"; code: string }>;
};

export type AnnualAccountsXmlInput = {
  payload: AnnualAccountsPayload;
  companyOrgNumber: string;
  companyName: string;
  contactEmail: string;
  approvalDate: string;
  confirmingRepresentative: string;
};

const OFFICIAL_ORIDS = {
  regnskapsaar: "17102",
  regnskapsstart: "17103",
  regnskapsslutt: "17104",
  valuta: "34984",
  "sumDriftskostnad/aarets": "17126",
  "sumFinansinntekter/aarets": "153",
  "sumFinanskostnader/aarets": "17130",
  "resultatFoerSkattekostnad/aarets": "167",
  "skattekostnad/aarets": "11835",
  "aarsresultat/aarets": "172",
  "investeringAksjerAndeler/aarets": "7100",
  "sumFinansielleAnleggsmidler/aarets": "5267",
  "sumBankinnskuddKontanter/aarets": "29042",
  "sumEiendeler/aarets": "219",
  "sumInnskuttEgenkapital/aarets": "3730",
  "annenEgenkapital/aarets": "3274",
  "sumEgenkapital/aarets": "250",
  "betalbarSkatt/aarets": "2483",
  "sumKortsiktigGjeld/aarets": "85",
  "sumGjeld/aarets": "1119",
  antallAarsverk: "37467",
} as const;

type OfficialTag = keyof typeof OFFICIAL_ORIDS;

export function renderAnnualAccountsXml(input: AnnualAccountsXmlInput) {
  validatePayloadHeader(input.payload);
  const fields = officialFields(input.payload.fields);
  const blockedCodes = input.payload.feedback
    .filter((item) => item.level === "block")
    .map((item) => item.code)
    .sort();
  if (blockedCodes.length) {
    throw new Error(`Årsregnskap har blokkerende avvik: ${blockedCodes.join(", ")}.`);
  }

  const organizationNumber = requiredPattern(
    input.companyOrgNumber,
    /^\d{9}$/u,
    "Organisasjonsnummer må inneholde 9 siffer.",
  );
  const companyName = requiredText(input.companyName, 175, "Virksomhetsnavn");
  const contactEmail = requiredPattern(
    input.contactEmail,
    /^[^\s@]+@[^\s@]+\.[^\s@]+$/u,
    "Kontakt-e-post er ugyldig.",
  );
  const approvalDate = requiredIsoDate(input.approvalDate, "Fastsettelsesdato");
  const confirmingRepresentative = requiredText(
    input.confirmingRepresentative,
    70,
    "Bekreftende selskapsrepresentant",
  );

  const year = wholeNumber(fields.regnskapsaar, "regnskapsaar");
  if (fields.regnskapsstart !== `${year}-01-01` || fields.regnskapsslutt !== `${year}-12-31`) {
    throw new Error("RR0002-rendereren støtter bare komplett kalenderår.");
  }
  if (approvalDate < `${year}-12-31`) {
    throw new Error("Fastsettelsesdato kan ikke være før regnskapsperioden er avsluttet.");
  }
  if (fields.valuta !== "NOK") {
    throw new Error("RR0002-rendereren støtter bare NOK.");
  }

  const values = financialValues(fields);
  validateFinancialConsistency(values);

  return {
    mainFormXml: renderMainForm({
      organizationNumber,
      companyName,
      contactEmail,
      approvalDate,
      confirmingRepresentative,
      year,
    }),
    companyAccountsXml: renderCompanyAccounts(values),
  };
}

function validatePayloadHeader(payload: AnnualAccountsPayload) {
  const expected = {
    schemaType: "aarsregnskap-vanlig-202406",
    hovedskjemaDataFormatId: "1266",
    hovedskjemaDataFormatVersion: "51820",
    selskapsregnskapDataFormatId: "758",
    selskapsregnskapDataFormatVersion: "51980",
  } as const;
  for (const [key, value] of Object.entries(expected)) {
    if (payload[key as keyof typeof expected] !== value) {
      throw new Error(`RR0002 ${key} må være ${value}.`);
    }
  }
}

function officialFields(rawFields: AnnualAccountsPayloadField[]): Record<OfficialTag, string | number> {
  const grouped = new Map<string, AnnualAccountsPayloadField[]>();
  for (const field of rawFields) {
    grouped.set(field.tag, [...(grouped.get(field.tag) ?? []), field]);
  }
  const result = {} as Record<OfficialTag, string | number>;
  for (const [tag, expectedOrid] of Object.entries(OFFICIAL_ORIDS) as Array<[OfficialTag, string]>) {
    const matches = grouped.get(tag) ?? [];
    if (matches.length !== 1) {
      throw new Error(`RR0002-felt ${tag} må finnes nøyaktig én gang.`);
    }
    if (matches[0].orid !== expectedOrid) {
      throw new Error(`RR0002-felt ${tag} må bruke offisiell orid ${expectedOrid}.`);
    }
    result[tag] = matches[0].value;
  }
  return result;
}

function financialValues(fields: Record<OfficialTag, string | number>) {
  return {
    operatingCosts: wholeNumber(fields["sumDriftskostnad/aarets"], "sumDriftskostnad/aarets"),
    financialIncome: wholeNumber(fields["sumFinansinntekter/aarets"], "sumFinansinntekter/aarets"),
    financialCosts: wholeNumber(fields["sumFinanskostnader/aarets"], "sumFinanskostnader/aarets"),
    resultBeforeTax: wholeNumber(fields["resultatFoerSkattekostnad/aarets"], "resultatFoerSkattekostnad/aarets"),
    taxExpense: wholeNumber(fields["skattekostnad/aarets"], "skattekostnad/aarets"),
    annualResult: wholeNumber(fields["aarsresultat/aarets"], "aarsresultat/aarets"),
    investments: wholeNumber(fields["investeringAksjerAndeler/aarets"], "investeringAksjerAndeler/aarets"),
    financialFixedAssets: wholeNumber(fields["sumFinansielleAnleggsmidler/aarets"], "sumFinansielleAnleggsmidler/aarets"),
    bank: wholeNumber(fields["sumBankinnskuddKontanter/aarets"], "sumBankinnskuddKontanter/aarets"),
    assets: wholeNumber(fields["sumEiendeler/aarets"], "sumEiendeler/aarets"),
    contributedEquity: wholeNumber(fields["sumInnskuttEgenkapital/aarets"], "sumInnskuttEgenkapital/aarets"),
    retainedEquity: wholeNumber(fields["annenEgenkapital/aarets"], "annenEgenkapital/aarets"),
    equity: wholeNumber(fields["sumEgenkapital/aarets"], "sumEgenkapital/aarets"),
    taxPayable: wholeNumber(fields["betalbarSkatt/aarets"], "betalbarSkatt/aarets"),
    shortTermDebt: wholeNumber(fields["sumKortsiktigGjeld/aarets"], "sumKortsiktigGjeld/aarets"),
    debt: wholeNumber(fields["sumGjeld/aarets"], "sumGjeld/aarets"),
    annualFullTimeEquivalents: wholeNumber(fields.antallAarsverk, "antallAarsverk"),
  };
}

function validateFinancialConsistency(values: ReturnType<typeof financialValues>) {
  for (const [label, value] of Object.entries(values)) {
    if (["resultBeforeTax", "annualResult", "retainedEquity"].includes(label)) continue;
    if (value < 0) throw new Error(`RR0002-felt ${label} kan ikke være negativt i støttet løype.`);
  }
  if (values.financialFixedAssets !== values.investments) {
    throw new Error("Sum finansielle anleggsmidler må samsvare med støttede investeringer.");
  }
  if (values.resultBeforeTax !== values.financialIncome - values.operatingCosts - values.financialCosts) {
    throw new Error("Resultat før skattekostnad stemmer ikke med resultatpostene.");
  }
  if (values.annualResult !== values.resultBeforeTax - values.taxExpense) {
    throw new Error("Årsresultat stemmer ikke med resultat før skatt og skattekostnad.");
  }
  if (values.assets !== values.investments + values.bank) {
    throw new Error("Sum eiendeler stemmer ikke med støttede eiendeler.");
  }
  if (values.equity !== values.contributedEquity + values.retainedEquity) {
    throw new Error("Sum egenkapital stemmer ikke med egenkapitalpostene.");
  }
  if (values.debt !== values.shortTermDebt || values.taxPayable > values.shortTermDebt) {
    throw new Error("Sum gjeld stemmer ikke med støttet kortsiktig gjeld.");
  }
  if (values.assets !== values.equity + values.debt) {
    throw new Error("RR0002-balanse: eiendeler er ikke lik egenkapital og gjeld.");
  }
}

function renderMainForm(input: {
  organizationNumber: string;
  companyName: string;
  contactEmail: string;
  approvalDate: string;
  confirmingRepresentative: string;
  year: number;
}) {
  return `<?xml version="1.0" encoding="UTF-8"?>
<melding xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns="http://schema.brreg.no/regnsys/aarsregnskap_vanlig" dataFormatId="1266" dataFormatVersion="51820" tjenestehandling="aarsregnskap_vanlig" tjeneste="regnskap">
  <Innsender>
    <enhet>
      <organisasjonsnummer orid="18">${escapeXml(input.organizationNumber)}</organisasjonsnummer>
      <organisasjonsform orid="756">AS</organisasjonsform>
      <navn orid="1">${escapeXml(input.companyName)}</navn>
    </enhet>
    <kontaktperson>
      <e-post orid="19022">${escapeXml(input.contactEmail)}</e-post>
    </kontaktperson>
    <opplysningerInnsending>
      <noteMaskinellBehandling orid="37499">20</noteMaskinellBehandling>
      <systemNavn orid="39007">Talli</systemNavn>
    </opplysningerInnsending>
  </Innsender>
  <Skjemainnhold>
    <regnskapsperiode>
      <regnskapsaar orid="17102">${input.year}</regnskapsaar>
      <regnskapsstart orid="17103">${input.year}-01-01</regnskapsstart>
      <regnskapsslutt orid="17104">${input.year}-12-31</regnskapsslutt>
    </regnskapsperiode>
    <konsern>
      <morselskap orid="4168">nei</morselskap>
    </konsern>
    <regnskapsprinsipper>
      <smaaForetak orid="8079">ja</smaaForetak>
      <regnskapsreglerSelskap orid="25021">nei</regnskapsreglerSelskap>
    </regnskapsprinsipper>
    <fastsettelse>
      <fastsettelsedato orid="17105">${escapeXml(input.approvalDate)}</fastsettelsedato>
      <bekreftendeSelskapsrepresentant orid="19023">${escapeXml(input.confirmingRepresentative)}</bekreftendeSelskapsrepresentant>
    </fastsettelse>
    <revisjonRegnskapsfoerer>
      <aarsregnskapIkkeRevideres orid="34669">ja</aarsregnskapIkkeRevideres>
      <aarsregnskapUtarbeidetAutorisertRegnskapsfoerer orid="34670">nei</aarsregnskapUtarbeidetAutorisertRegnskapsfoerer>
      <tjenestebistandEksternAutorisertRegnskapsfoerer orid="34671">nei</tjenestebistandEksternAutorisertRegnskapsfoerer>
    </revisjonRegnskapsfoerer>
  </Skjemainnhold>
</melding>
`;
}

function renderCompanyAccounts(values: ReturnType<typeof financialValues>) {
  const operatingResult = -values.operatingCosts;
  const netFinance = values.financialIncome - values.financialCosts;
  return `<?xml version="1.0" encoding="UTF-8"?>
<melding xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns="http://schema.brreg.no/regnsys/aarsregnskap_vanlig/underskjema" dataFormatId="758" dataFormatVersion="51980" versjon="1.1" tjenestehandling="aarsregnskap_vanlig_underskjema" tjeneste="regnskap">
  <Rapport-RR0002U>
    <aarsregnskap>
      <regnskapstype orid="25942">S</regnskapstype>
      <valuta orid="34984">NOK</valuta>
      <valoer orid="28974">H</valoer>
    </aarsregnskap>
  </Rapport-RR0002U>
  <Skjemainnhold-RR0002U>
    <resultatregnskapDriftsresultat>
      <driftsresultat><aarets orid="146">${operatingResult}</aarets></driftsresultat>
      <kostnad><sumDriftskostnad><aarets orid="17126">${values.operatingCosts}</aarets></sumDriftskostnad></kostnad>
    </resultatregnskapDriftsresultat>
    <resultatregnskapFinansinntekt>
      <nettoFinans><aarets orid="158">${netFinance}</aarets></nettoFinans>
      <finansinntekt><sumFinansinntekter><aarets orid="153">${values.financialIncome}</aarets></sumFinansinntekter></finansinntekt>
      <finanskostnad><sumFinanskostnader><aarets orid="17130">${values.financialCosts}</aarets></sumFinanskostnader></finanskostnad>
    </resultatregnskapFinansinntekt>
    <resultatregnskapResultat>
      <resultat>
        <resultatFoerSkattekostnad><aarets orid="167">${values.resultBeforeTax}</aarets></resultatFoerSkattekostnad>
        <skattekostnad><aarets orid="11835">${values.taxExpense}</aarets></skattekostnad>
        <aarsresultat><aarets orid="172">${values.annualResult}</aarets></aarsresultat>
      </resultat>
    </resultatregnskapResultat>
    <balanseAnleggsmidlerOmloepsmidler>
      <sumEiendeler><aarets orid="219">${values.assets}</aarets></sumEiendeler>
      <balanseAnleggsmidler>
        <sumAnleggsmidler><aarets orid="217">${values.investments}</aarets></sumAnleggsmidler>
        <balanseFinansielleAnleggsmidler>
          <investeringAksjerAndeler><aarets orid="7100">${values.investments}</aarets></investeringAksjerAndeler>
          <sumFinansielleAnleggsmidler><aarets orid="5267">${values.financialFixedAssets}</aarets></sumFinansielleAnleggsmidler>
        </balanseFinansielleAnleggsmidler>
      </balanseAnleggsmidler>
      <balanseOmloepsmidler>
        <sumOmloepsmidler><aarets orid="194">${values.bank}</aarets></sumOmloepsmidler>
        <balanseOmloepsmidlerInvesteringerBankinnskuddKontanter>
          <bankinnskuddKontanter>
            <sumBankinnskuddKontanter><aarets orid="29042">${values.bank}</aarets></sumBankinnskuddKontanter>
          </bankinnskuddKontanter>
        </balanseOmloepsmidlerInvesteringerBankinnskuddKontanter>
      </balanseOmloepsmidler>
    </balanseAnleggsmidlerOmloepsmidler>
    <balanseEgenkapitalGjeld>
      <sumEgenkapitalGjeld><aarets orid="251">${values.assets}</aarets></sumEgenkapitalGjeld>
      <balanseEgenkapitalInnskuttOpptjentEgenkapital>
        <innskuttEgenkapital>
          <sumInnskuttEgenkapital><aarets orid="3730">${values.contributedEquity}</aarets></sumInnskuttEgenkapital>
        </innskuttEgenkapital>
        <opptjentEgenkaiptal>
          <annenEgenkapital><aarets orid="3274">${values.retainedEquity}</aarets></annenEgenkapital>
          <sumOpptjentEgenkapital><aarets orid="9702">${values.retainedEquity}</aarets></sumOpptjentEgenkapital>
          <sumEgenkapital><aarets orid="250">${values.equity}</aarets></sumEgenkapital>
        </opptjentEgenkaiptal>
      </balanseEgenkapitalInnskuttOpptjentEgenkapital>
      <balanseGjeldOversikt>
        <sumGjeld><aarets orid="1119">${values.debt}</aarets></sumGjeld>
        <balanseKortsiktigGjeld>
          <betalbarSkatt><aarets orid="2483">${values.taxPayable}</aarets></betalbarSkatt>
          <sumKortsiktigGjeld><aarets orid="85">${values.shortTermDebt}</aarets></sumKortsiktigGjeld>
        </balanseKortsiktigGjeld>
      </balanseGjeldOversikt>
    </balanseEgenkapitalGjeld>
    <noter>
      <noteAarsverkTjenestePensjon>
        <antallAarsverk orid="37467">${values.annualFullTimeEquivalents}</antallAarsverk>
      </noteAarsverkTjenestePensjon>
    </noter>
  </Skjemainnhold-RR0002U>
</melding>
`;
}

function wholeNumber(value: string | number, label: string): number {
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isSafeInteger(parsed)) {
    throw new Error(`RR0002-felt ${label} må oppgis i hele kroner.`);
  }
  return parsed;
}

function requiredText(value: string, maxLength: number, label: string): string {
  if (typeof value !== "string" || value !== value.trim() || value.length < 1 || value.length > maxLength) {
    throw new Error(`${label} er påkrevd og kan ha maksimalt ${maxLength} tegn.`);
  }
  if (/[\u0000-\u001f\u007f]/u.test(value)) {
    throw new Error(`${label} inneholder ugyldige kontrolltegn.`);
  }
  return value;
}

function requiredPattern(value: string, pattern: RegExp, message: string): string {
  if (typeof value !== "string" || value !== value.trim() || !pattern.test(value)) {
    throw new Error(message);
  }
  return value;
}

function requiredIsoDate(value: string, label: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/u.exec(value);
  if (!match || value !== value.trim()) {
    throw new Error(`${label} må være en gyldig dato i formatet YYYY-MM-DD.`);
  }
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  if (
    parsed.getUTCFullYear() !== year
    || parsed.getUTCMonth() !== month - 1
    || parsed.getUTCDate() !== day
  ) {
    throw new Error(`${label} må være en gyldig dato i formatet YYYY-MM-DD.`);
  }
  return value;
}

function escapeXml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}
