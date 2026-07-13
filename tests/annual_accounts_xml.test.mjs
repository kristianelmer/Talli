import assert from "node:assert/strict";
import test from "node:test";

import { XMLParser, XMLValidator } from "fast-xml-parser";

import {
  AnnualAccountsXmlError,
  buildAnnualAccountsXmlDocuments,
} from "../app/lib/annual-accounts-xml.ts";

const parser = new XMLParser({
  ignoreAttributes: false,
  attributeNamePrefix: "@",
  parseTagValue: false,
  trimValues: false,
});

const baseInput = {
  organization: {
    number: "310279617",
    name: "LOGISK & ØDE <TIGER> AS",
    form: "AS",
    contactEmail: "post+talli@example.no",
  },
  incomeYear: 2025,
  adoption: {
    date: "2026-06-15",
    confirmingRepresentative: "Viktig & Rosin <styreleder>",
  },
  declarations: {
    isSmallEnterprise: true,
    isParentCompany: false,
    usesIfrs: false,
    auditRequired: false,
    preparedByAuthorizedAccountant: false,
    externalAuthorizedAccountantAssistance: false,
  },
  current: {
    operatingCosts: 1_490,
    financialIncome: 100_000,
    financialCosts: 0,
    resultBeforeTax: 98_510,
    annualResult: 98_510,
    investmentSharesAndUnits: 30_000,
    bank: 128_510,
    totalAssets: 158_510,
    paidInEquity: 30_000,
    retainedEquity: 128_510,
    totalEquity: 158_510,
    shortTermDebt: 0,
    totalDebt: 0,
    totalEquityAndDebt: 158_510,
  },
  prior: {
    operatingCosts: 1_000,
    financialIncome: 0,
    financialCosts: 0,
    resultBeforeTax: -1_000,
    annualResult: -1_000,
    investmentSharesAndUnits: 30_000,
    bank: 1_000,
    totalAssets: 31_000,
    paidInEquity: 30_000,
    retainedEquity: 1_000,
    totalEquity: 31_000,
    shortTermDebt: 0,
    totalDebt: 0,
    totalEquityAndDebt: 31_000,
  },
  annualFullTimeEquivalents: 0,
  investmentDescription: "Aksjer & andeler <holding>",
  retainedEquityDescription: "Annen & opptjent egenkapital",
};

test("builds deterministic current-contract RR0002 XML with escaped metadata and current/prior figures", () => {
  const documents = buildAnnualAccountsXmlDocuments(baseInput);

  assert.equal(XMLValidator.validate(documents.mainFormXml), true);
  assert.equal(XMLValidator.validate(documents.accountsFormXml), true);
  assert.equal(documents.schema.application, "brg/aarsregnskap-vanlig-202406");
  assert.equal(documents.schema.mainFormDataType, "Hovedskjema");
  assert.equal(documents.schema.accountsFormDataType, "Underskjema");
  assert.match(documents.mainFormSha256, /^[a-f0-9]{64}$/u);
  assert.match(documents.accountsFormSha256, /^[a-f0-9]{64}$/u);
  assert.equal(
    buildAnnualAccountsXmlDocuments(baseInput).accountsFormSha256,
    documents.accountsFormSha256,
  );
  assert.match(documents.mainFormXml, /LOGISK &amp; ØDE &lt;TIGER&gt; AS/u);
  assert.match(documents.mainFormXml, /Viktig &amp; Rosin &lt;styreleder&gt;/u);
  assert.match(documents.accountsFormXml, /Aksjer &amp; andeler &lt;holding&gt;/u);

  const main = parser.parse(documents.mainFormXml).melding;
  assert.equal(main["@xmlns"], "http://schema.brreg.no/regnsys/aarsregnskap_vanlig");
  assert.equal(main["@dataFormatId"], "1266");
  assert.equal(main["@dataFormatVersion"], "51820");
  assert.equal(main.Innsender.enhet.organisasjonsnummer["@orid"], "18");
  assert.equal(main.Innsender.enhet.organisasjonsnummer["#text"], "310279617");
  assert.equal(main.Innsender.opplysningerInnsending.systemNavn["#text"], "Talli");
  assert.equal(main.Skjemainnhold.regnskapsperiode.regnskapsaar["#text"], "2025");
  assert.equal(main.Skjemainnhold.konsern.morselskap["#text"], "nei");
  assert.equal(main.Skjemainnhold.regnskapsprinsipper.smaaForetak["#text"], "ja");
  assert.equal(main.Skjemainnhold.regnskapsprinsipper.regnskapsreglerSelskap["#text"], "nei");
  assert.equal(main.Skjemainnhold.revisjonRegnskapsfoerer.aarsregnskapIkkeRevideres["#text"], "ja");

  const accounts = parser.parse(documents.accountsFormXml).melding;
  const content = accounts["Skjemainnhold-RR0002U"];
  assert.equal(accounts["@xmlns"], "http://schema.brreg.no/regnsys/aarsregnskap_vanlig/underskjema");
  assert.equal(accounts["@dataFormatId"], "758");
  assert.equal(accounts["@dataFormatVersion"], "51980");
  assert.equal(accounts["@versjon"], "1.1");
  assert.equal(accounts["Rapport-RR0002U"].aarsregnskap.valoer["#text"], "H");
  assert.deepEqual(
    content.resultatregnskapDriftsresultat.kostnad.sumDriftskostnad,
    {
      aarets: { "#text": "1490", "@orid": "17126" },
      fjoraarets: { "#text": "1000", "@orid": "17127" },
    },
  );
  assert.equal(
    content.resultatregnskapFinansinntekt.finansinntekt.sumFinansinntekter.aarets["@orid"],
    "153",
  );
  assert.equal(
    content.resultatregnskapResultat.resultat.resultatFoerSkattekostnad.fjoraarets["#text"],
    "-1000",
  );
  assert.equal(content.balanseAnleggsmidlerOmloepsmidler.sumEiendeler.aarets["#text"], "158510");
  assert.equal(
    content.balanseAnleggsmidlerOmloepsmidler.balanseAnleggsmidler.balanseFinansielleAnleggsmidler
      .investeringAksjerAndeler.aarets["@orid"],
    "7100",
  );
  assert.equal(
    content.balanseEgenkapitalGjeld.balanseEgenkapitalInnskuttOpptjentEgenkapital
      .opptjentEgenkaiptal.sumOpptjentEgenkapital.aarets["#text"],
    "128510",
  );
  assert.equal(content.balanseEgenkapitalGjeld.sumEgenkapitalGjeld.aarets["@orid"], "251");
  assert.equal(content.noter.noteAarsverkTjenestePensjon.antallAarsverk["#text"], "0");
});

test("rejects unsupported annual-account declarations before XML generation", () => {
  for (const [field, value, code] of [
    ["isSmallEnterprise", false, "annual_accounts_xml_not_small_enterprise"],
    ["isParentCompany", true, "annual_accounts_xml_parent_company_unsupported"],
    ["usesIfrs", true, "annual_accounts_xml_ifrs_unsupported"],
    ["auditRequired", true, "annual_accounts_xml_audit_unsupported"],
  ]) {
    assert.throws(
      () =>
        buildAnnualAccountsXmlDocuments({
          ...baseInput,
          declarations: { ...baseInput.declarations, [field]: value },
        }),
      (error) => error instanceof AnnualAccountsXmlError && error.code === code,
    );
  }
});

test("rejects incomplete, fractional, or unreconciled current and prior whole-kroner figures", () => {
  const invalidInputs = [
    {
      input: { ...baseInput, prior: undefined },
      code: "annual_accounts_xml_prior_figures_missing",
    },
    {
      input: { ...baseInput, current: { ...baseInput.current, bank: 128_510.25 } },
      code: "annual_accounts_xml_whole_kroner_required",
    },
    {
      input: { ...baseInput, current: { ...baseInput.current, totalAssets: 158_511 } },
      code: "annual_accounts_xml_balance_unreconciled",
    },
    {
      input: { ...baseInput, prior: { ...baseInput.prior, resultBeforeTax: -999 } },
      code: "annual_accounts_xml_result_unreconciled",
    },
  ];

  for (const item of invalidInputs) {
    assert.throws(
      () => buildAnnualAccountsXmlDocuments(item.input),
      (error) => error instanceof AnnualAccountsXmlError && error.code === item.code,
    );
  }
});

test("rejects invalid identity, dates, notes, and unsafe XML text", () => {
  const invalidInputs = [
    {
      input: { ...baseInput, organization: { ...baseInput.organization, number: "123" } },
      code: "annual_accounts_xml_org_number_invalid",
    },
    {
      input: { ...baseInput, organization: { ...baseInput.organization, number: "123456789" } },
      code: "annual_accounts_xml_org_number_invalid",
    },
    {
      input: { ...baseInput, adoption: { ...baseInput.adoption, date: "2025-12-31" } },
      code: "annual_accounts_xml_adoption_date_invalid",
    },
    {
      input: { ...baseInput, annualFullTimeEquivalents: -1 },
      code: "annual_accounts_xml_full_time_equivalents_invalid",
    },
    {
      input: { ...baseInput, investmentDescription: "unsafe\u0001text" },
      code: "annual_accounts_xml_text_invalid",
    },
  ];

  for (const item of invalidInputs) {
    assert.throws(
      () => buildAnnualAccountsXmlDocuments(item.input),
      (error) => error instanceof AnnualAccountsXmlError && error.code === item.code,
    );
  }
});
