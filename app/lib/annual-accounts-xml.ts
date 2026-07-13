import { createHash } from "node:crypto";

const FORBIDDEN_TEXT_PATTERN = /[\u0000-\u0008\u000B\u000C\u000E-\u001F]/u;
const ORG_NUMBER_PATTERN = /^\d{9}$/u;
const ISO_DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/u;
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/u;
const MAX_WHOLE_KRONER = 999_999_999_999;
const ORG_NUMBER_WEIGHTS = [3, 2, 7, 6, 5, 4, 3, 2] as const;

export const ANNUAL_ACCOUNTS_XML_CONTRACT = {
  application: "brg/aarsregnskap-vanlig-202406",
  mainFormDataType: "Hovedskjema",
  accountsFormDataType: "Underskjema",
  mainForm: {
    namespace: "http://schema.brreg.no/regnsys/aarsregnskap_vanlig",
    dataFormatId: "1266",
    dataFormatVersion: "51820",
    liveSchemaSha256: "3776336fa2f7e1ef4773e8cb2800d7930415b9b1c028a59a338327f68b8b4f68",
  },
  accountsForm: {
    namespace: "http://schema.brreg.no/regnsys/aarsregnskap_vanlig/underskjema",
    dataFormatId: "758",
    dataFormatVersion: "51980",
    version: "1.1",
    liveSchemaSha256: "e17fc7f6cb45984f5ab74dc614955199610deab9b12f9eb1012772f2e0e7c931",
  },
} as const;

export type AnnualAccountsWholeKronerFigures = {
  operatingCosts: number;
  financialIncome: number;
  financialCosts: number;
  resultBeforeTax: number;
  annualResult: number;
  investmentSharesAndUnits: number;
  bank: number;
  totalAssets: number;
  paidInEquity: number;
  retainedEquity: number;
  totalEquity: number;
  shortTermDebt: number;
  totalDebt: number;
  totalEquityAndDebt: number;
};

export type AnnualAccountsXmlInput = {
  organization: {
    number: string;
    name: string;
    form: "AS";
    contactEmail: string;
  };
  incomeYear: number;
  adoption: {
    date: string;
    confirmingRepresentative: string;
  };
  declarations: {
    isSmallEnterprise: boolean;
    isParentCompany: boolean;
    usesIfrs: boolean;
    auditRequired: boolean;
    preparedByAuthorizedAccountant: boolean;
    externalAuthorizedAccountantAssistance: boolean;
  };
  current: AnnualAccountsWholeKronerFigures;
  prior: AnnualAccountsWholeKronerFigures;
  annualFullTimeEquivalents: number;
  investmentDescription: string;
  retainedEquityDescription: string;
};

export class AnnualAccountsXmlError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "AnnualAccountsXmlError";
    this.code = code;
  }
}

function fail(code: string, message: string): never {
  throw new AnnualAccountsXmlError(code, message);
}

function record(value: unknown, code: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    fail(code, "Annual-accounts XML input is incomplete.");
  }
  return value as Record<string, unknown>;
}

function textValue(value: unknown, maximum: number, code = "annual_accounts_xml_text_invalid"): string {
  if (typeof value !== "string") {
    fail(code, "Annual-accounts XML text is invalid.");
  }
  const normalized = value.trim();
  if (!normalized || normalized.length > maximum || FORBIDDEN_TEXT_PATTERN.test(normalized)) {
    fail(code, "Annual-accounts XML text is invalid.");
  }
  return normalized;
}

function xml(value: string | number): string {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

function leaf(tag: string, orid: string, value: string | number): string {
  return `<${tag} orid="${orid}">${xml(value)}</${tag}>`;
}

function pair(
  tag: string,
  currentOrid: string,
  priorOrid: string,
  current: number,
  prior: number,
): string {
  return `<${tag}>${leaf("aarets", currentOrid, current)}${leaf("fjoraarets", priorOrid, prior)}</${tag}>`;
}

function booleanAnswer(value: boolean): "ja" | "nei" {
  return value ? "ja" : "nei";
}

function assertIncomeYear(value: unknown): number {
  if (!Number.isInteger(value) || (value as number) < 2000 || (value as number) > 2100) {
    fail("annual_accounts_xml_income_year_invalid", "Annual-accounts income year is invalid.");
  }
  return value as number;
}

function hasValidOrganizationNumberChecksum(value: string): boolean {
  const sum = ORG_NUMBER_WEIGHTS.reduce((total, weight, index) => total + weight * Number(value[index]), 0);
  const remainder = 11 - (sum % 11);
  const checksum = remainder === 11 ? 0 : remainder;
  return checksum !== 10 && checksum === Number(value[8]);
}

function assertDate(value: unknown, code: string): string {
  if (typeof value !== "string") {
    fail(code, "Annual-accounts date is invalid.");
  }
  const match = ISO_DATE_PATTERN.exec(value);
  if (!match) {
    fail(code, "Annual-accounts date is invalid.");
  }
  const date = new Date(`${value}T00:00:00.000Z`);
  if (Number.isNaN(date.getTime()) || date.toISOString().slice(0, 10) !== value) {
    fail(code, "Annual-accounts date is invalid.");
  }
  return value;
}

function assertWholeKroner(value: unknown, field: string, nonnegative: boolean): number {
  if (!Number.isSafeInteger(value) || Math.abs(value as number) > MAX_WHOLE_KRONER) {
    fail(
      "annual_accounts_xml_whole_kroner_required",
      `Annual-accounts ${field} must use bounded whole kroner.`,
    );
  }
  if (nonnegative && (value as number) < 0) {
    fail("annual_accounts_xml_amount_invalid", `Annual-accounts ${field} cannot be negative.`);
  }
  return value as number;
}

function assertFigures(value: unknown, period: "current" | "prior"): AnnualAccountsWholeKronerFigures {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    fail(
      period === "prior" ? "annual_accounts_xml_prior_figures_missing" : "annual_accounts_xml_current_figures_missing",
      `Annual-accounts ${period}-year figures are required.`,
    );
  }
  const candidate = value as Partial<AnnualAccountsWholeKronerFigures>;
  const figures: AnnualAccountsWholeKronerFigures = {
    operatingCosts: assertWholeKroner(candidate.operatingCosts, `${period}.operatingCosts`, true),
    financialIncome: assertWholeKroner(candidate.financialIncome, `${period}.financialIncome`, true),
    financialCosts: assertWholeKroner(candidate.financialCosts, `${period}.financialCosts`, true),
    resultBeforeTax: assertWholeKroner(candidate.resultBeforeTax, `${period}.resultBeforeTax`, false),
    annualResult: assertWholeKroner(candidate.annualResult, `${period}.annualResult`, false),
    investmentSharesAndUnits: assertWholeKroner(
      candidate.investmentSharesAndUnits,
      `${period}.investmentSharesAndUnits`,
      true,
    ),
    bank: assertWholeKroner(candidate.bank, `${period}.bank`, true),
    totalAssets: assertWholeKroner(candidate.totalAssets, `${period}.totalAssets`, true),
    paidInEquity: assertWholeKroner(candidate.paidInEquity, `${period}.paidInEquity`, true),
    retainedEquity: assertWholeKroner(candidate.retainedEquity, `${period}.retainedEquity`, false),
    totalEquity: assertWholeKroner(candidate.totalEquity, `${period}.totalEquity`, false),
    shortTermDebt: assertWholeKroner(candidate.shortTermDebt, `${period}.shortTermDebt`, true),
    totalDebt: assertWholeKroner(candidate.totalDebt, `${period}.totalDebt`, true),
    totalEquityAndDebt: assertWholeKroner(
      candidate.totalEquityAndDebt,
      `${period}.totalEquityAndDebt`,
      true,
    ),
  };

  if (figures.resultBeforeTax !== figures.financialIncome - figures.operatingCosts - figures.financialCosts) {
    fail(
      "annual_accounts_xml_result_unreconciled",
      `Annual-accounts ${period}-year result before tax is not reconciled.`,
    );
  }
  if (figures.annualResult !== figures.resultBeforeTax) {
    fail(
      "annual_accounts_xml_tax_cost_unsupported",
      `Annual-accounts ${period}-year tax cost is outside the supported no-tax-cost path.`,
    );
  }
  const assetsReconcile = figures.totalAssets === figures.investmentSharesAndUnits + figures.bank;
  const equityReconciles = figures.totalEquity === figures.paidInEquity + figures.retainedEquity;
  const debtReconciles = figures.totalDebt === figures.shortTermDebt;
  const balanceReconciles =
    figures.totalEquityAndDebt === figures.totalEquity + figures.totalDebt &&
    figures.totalAssets === figures.totalEquityAndDebt;
  if (!assetsReconcile || !equityReconciles || !debtReconciles || !balanceReconciles) {
    fail(
      "annual_accounts_xml_balance_unreconciled",
      `Annual-accounts ${period}-year balance is not reconciled.`,
    );
  }
  return figures;
}

function assertDeclarations(value: unknown): AnnualAccountsXmlInput["declarations"] {
  const declarations = record(value, "annual_accounts_xml_declarations_missing");
  const required = [
    "isSmallEnterprise",
    "isParentCompany",
    "usesIfrs",
    "auditRequired",
    "preparedByAuthorizedAccountant",
    "externalAuthorizedAccountantAssistance",
  ] as const;
  for (const key of required) {
    if (typeof declarations[key] !== "boolean") {
      fail("annual_accounts_xml_declarations_invalid", "Annual-accounts declarations must be explicit booleans.");
    }
  }
  const typed = declarations as AnnualAccountsXmlInput["declarations"];
  if (!typed.isSmallEnterprise) {
    fail("annual_accounts_xml_not_small_enterprise", "Only small enterprises are supported.");
  }
  if (typed.isParentCompany) {
    fail("annual_accounts_xml_parent_company_unsupported", "Parent-company annual accounts are not supported.");
  }
  if (typed.usesIfrs) {
    fail("annual_accounts_xml_ifrs_unsupported", "IFRS annual accounts are not supported.");
  }
  if (typed.auditRequired) {
    fail("annual_accounts_xml_audit_unsupported", "Audited annual accounts are not supported.");
  }
  return typed;
}

function assertInput(value: unknown) {
  const input = record(value, "annual_accounts_xml_input_invalid");
  const organization = record(input.organization, "annual_accounts_xml_organization_missing");
  const organizationNumber = textValue(
    organization.number,
    9,
    "annual_accounts_xml_org_number_invalid",
  );
  if (!ORG_NUMBER_PATTERN.test(organizationNumber) || !hasValidOrganizationNumberChecksum(organizationNumber)) {
    fail(
      "annual_accounts_xml_org_number_invalid",
      "Annual-accounts organization number must have nine digits and a valid checksum.",
    );
  }
  if (organization.form !== "AS") {
    fail("annual_accounts_xml_entity_form_unsupported", "Only Norwegian AS entities are supported.");
  }
  const contactEmail = textValue(organization.contactEmail, 254, "annual_accounts_xml_contact_email_invalid");
  if (!EMAIL_PATTERN.test(contactEmail)) {
    fail("annual_accounts_xml_contact_email_invalid", "Annual-accounts contact email is invalid.");
  }
  const incomeYear = assertIncomeYear(input.incomeYear);
  const adoption = record(input.adoption, "annual_accounts_xml_adoption_missing");
  const adoptionDate = assertDate(adoption.date, "annual_accounts_xml_adoption_date_invalid");
  if (!adoptionDate.startsWith(`${incomeYear + 1}-`)) {
    fail(
      "annual_accounts_xml_adoption_date_invalid",
      "Annual-accounts adoption date must be in the year after the supported calendar year.",
    );
  }
  const declarations = assertDeclarations(input.declarations);
  const current = assertFigures(input.current, "current");
  const prior = assertFigures(input.prior, "prior");
  const annualFullTimeEquivalents = input.annualFullTimeEquivalents;
  if (
    typeof annualFullTimeEquivalents !== "number" ||
    !Number.isFinite(annualFullTimeEquivalents) ||
    annualFullTimeEquivalents < 0 ||
    annualFullTimeEquivalents > 999_999 ||
    !/^\d+(?:\.\d{1,3})?$/u.test(String(annualFullTimeEquivalents))
  ) {
    fail(
      "annual_accounts_xml_full_time_equivalents_invalid",
      "Annual-accounts full-time equivalents must be a non-negative number with at most three decimals.",
    );
  }

  return {
    organization: {
      number: organizationNumber,
      name: textValue(organization.name, 175),
      form: "AS" as const,
      contactEmail,
    },
    incomeYear,
    adoption: {
      date: adoptionDate,
      confirmingRepresentative: textValue(adoption.confirmingRepresentative, 70),
    },
    declarations,
    current,
    prior,
    annualFullTimeEquivalents,
    investmentDescription: textValue(input.investmentDescription, 175),
    retainedEquityDescription: textValue(input.retainedEquityDescription, 175),
  };
}

function buildMainForm(input: ReturnType<typeof assertInput>): string {
  const { organization, incomeYear, adoption, declarations } = input;
  const start = `${incomeYear}-01-01`;
  const end = `${incomeYear}-12-31`;
  return `<?xml version="1.0" encoding="UTF-8"?>\n<melding xmlns="${ANNUAL_ACCOUNTS_XML_CONTRACT.mainForm.namespace}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" dataFormatId="${ANNUAL_ACCOUNTS_XML_CONTRACT.mainForm.dataFormatId}" dataFormatVersion="${ANNUAL_ACCOUNTS_XML_CONTRACT.mainForm.dataFormatVersion}" tjenestehandling="aarsregnskap_vanlig" tjeneste="regnskap"><Innsender><enhet>${leaf("organisasjonsnummer", "18", organization.number)}${leaf("organisasjonsform", "756", organization.form)}${leaf("navn", "1", organization.name)}</enhet><kontaktperson>${leaf("e-post", "19022", organization.contactEmail)}</kontaktperson><opplysningerInnsending>${leaf("noteMaskinellBehandling", "37499", "20")}${leaf("systemNavn", "39007", "Talli")}</opplysningerInnsending></Innsender><Skjemainnhold><regnskapsperiode>${leaf("regnskapsaar", "17102", incomeYear)}${leaf("regnskapsstart", "17103", start)}${leaf("regnskapsslutt", "17104", end)}</regnskapsperiode><konsern>${leaf("morselskap", "4168", "nei")}${leaf("konsernregnskap", "25943", "nei")}</konsern><regnskapsprinsipper>${leaf("smaaForetak", "8079", "ja")}${leaf("regnskapsreglerSelskap", "25021", "nei")}${leaf("forenkletIFRS", "36639", "nei")}</regnskapsprinsipper><fastsettelse>${leaf("fastsettelsedato", "17105", adoption.date)}${leaf("bekreftendeSelskapsrepresentant", "19023", adoption.confirmingRepresentative)}</fastsettelse><revisjonRegnskapsfoerer>${leaf("aarsregnskapIkkeRevideres", "34669", "ja")}${leaf("aarsregnskapUtarbeidetAutorisertRegnskapsfoerer", "34670", booleanAnswer(declarations.preparedByAuthorizedAccountant))}${leaf("tjenestebistandEksternAutorisertRegnskapsfoerer", "34671", booleanAnswer(declarations.externalAuthorizedAccountantAssistance))}</revisjonRegnskapsfoerer></Skjemainnhold></melding>`;
}

function buildAccountsForm(input: ReturnType<typeof assertInput>): string {
  const { current, prior } = input;
  const operating = `<resultatregnskapDriftsresultat><kostnad>${pair("sumDriftskostnad", "17126", "17127", current.operatingCosts, prior.operatingCosts)}</kostnad></resultatregnskapDriftsresultat>`;
  const finance = `<resultatregnskapFinansinntekt><finansinntekt>${pair("sumFinansinntekter", "153", "7993", current.financialIncome, prior.financialIncome)}</finansinntekt><finanskostnad>${pair("sumFinanskostnader", "17130", "17131", current.financialCosts, prior.financialCosts)}</finanskostnad></resultatregnskapFinansinntekt>`;
  const result = `<resultatregnskapResultat><resultat>${pair("resultatFoerSkattekostnad", "167", "7042", current.resultBeforeTax, prior.resultBeforeTax)}${pair("aarsresultat", "172", "7054", current.annualResult, prior.annualResult)}</resultat></resultatregnskapResultat>`;
  const investment = `<investeringAksjerAndeler>${leaf("beskrivelse", "29024", input.investmentDescription)}${leaf("aarets", "7100", current.investmentSharesAndUnits)}${leaf("fjoraarets", "7101", prior.investmentSharesAndUnits)}</investeringAksjerAndeler>`;
  const fixedAssets = `<balanseAnleggsmidler><sumAnleggsmidler>${leaf("aarets", "217", current.investmentSharesAndUnits)}${leaf("fjoraarets", "7108", prior.investmentSharesAndUnits)}</sumAnleggsmidler><balanseFinansielleAnleggsmidler>${investment}${pair("sumFinansielleAnleggsmidler", "5267", "8014", current.investmentSharesAndUnits, prior.investmentSharesAndUnits)}</balanseFinansielleAnleggsmidler></balanseAnleggsmidler>`;
  const currentAssets = `<balanseOmloepsmidler>${pair("sumOmloepsmidler", "194", "7126", current.bank, prior.bank)}<balanseOmloepsmidlerInvesteringerBankinnskuddKontanter><bankinnskuddKontanter>${pair("sumBankinnskuddKontanter", "29042", "29043", current.bank, prior.bank)}</bankinnskuddKontanter></balanseOmloepsmidlerInvesteringerBankinnskuddKontanter></balanseOmloepsmidler>`;
  const assets = `<balanseAnleggsmidlerOmloepsmidler>${pair("sumEiendeler", "219", "7127", current.totalAssets, prior.totalAssets)}${fixedAssets}${currentAssets}</balanseAnleggsmidlerOmloepsmidler>`;
  const retained = `<opptjentEgenkaiptal><annenEgenkapital>${leaf("beskrivelse", "29034", input.retainedEquityDescription)}${leaf("aarets", "3274", current.retainedEquity)}${leaf("fjoraarets", "7140", prior.retainedEquity)}</annenEgenkapital>${pair("sumOpptjentEgenkapital", "9702", "9985", current.retainedEquity, prior.retainedEquity)}${pair("sumEgenkapital", "250", "7142", current.totalEquity, prior.totalEquity)}</opptjentEgenkaiptal>`;
  const equity = `<balanseEgenkapitalInnskuttOpptjentEgenkapital><innskuttEgenkapital>${pair("sumInnskuttEgenkapital", "3730", "9984", current.paidInEquity, prior.paidInEquity)}</innskuttEgenkapital>${retained}</balanseEgenkapitalInnskuttOpptjentEgenkapital>`;
  const debt = `<balanseGjeldOversikt>${pair("sumGjeld", "1119", "7184", current.totalDebt, prior.totalDebt)}<balanseKortsiktigGjeld>${pair("sumKortsiktigGjeld", "85", "7183", current.shortTermDebt, prior.shortTermDebt)}</balanseKortsiktigGjeld></balanseGjeldOversikt>`;
  const equityAndDebt = `<balanseEgenkapitalGjeld>${pair("sumEgenkapitalGjeld", "251", "7185", current.totalEquityAndDebt, prior.totalEquityAndDebt)}${equity}${debt}</balanseEgenkapitalGjeld>`;
  const notes = `<noter><noteAarsverkTjenestePensjon>${leaf("antallAarsverk", "37467", input.annualFullTimeEquivalents)}</noteAarsverkTjenestePensjon></noter>`;
  return `<?xml version="1.0" encoding="UTF-8"?>\n<melding xmlns="${ANNUAL_ACCOUNTS_XML_CONTRACT.accountsForm.namespace}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" dataFormatId="${ANNUAL_ACCOUNTS_XML_CONTRACT.accountsForm.dataFormatId}" dataFormatVersion="${ANNUAL_ACCOUNTS_XML_CONTRACT.accountsForm.dataFormatVersion}" versjon="${ANNUAL_ACCOUNTS_XML_CONTRACT.accountsForm.version}" tjenestehandling="aarsregnskap_vanlig_underskjema" tjeneste="regnskap"><Rapport-RR0002U><aarsregnskap>${leaf("regnskapstype", "25942", "S")}${leaf("valuta", "34984", "NOK")}${leaf("valoer", "28974", "H")}</aarsregnskap></Rapport-RR0002U><Skjemainnhold-RR0002U>${operating}${finance}${result}${assets}${equityAndDebt}${notes}</Skjemainnhold-RR0002U></melding>`;
}

function sha256(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

export function buildAnnualAccountsXmlDocuments(value: unknown) {
  const input = assertInput(value);
  const mainFormXml = buildMainForm(input);
  const accountsFormXml = buildAccountsForm(input);
  return {
    schema: ANNUAL_ACCOUNTS_XML_CONTRACT,
    mainFormXml,
    accountsFormXml,
    mainFormSha256: sha256(mainFormXml),
    accountsFormSha256: sha256(accountsFormXml),
  };
}
