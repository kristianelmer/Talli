import assert from "node:assert/strict";
import test from "node:test";

import { buildAnnualAccountsPayload } from "../apps/web/app/lib/annual-accounts.ts";
import { renderAnnualAccountsXml } from "../apps/web/app/lib/annual-accounts-xml.ts";

const annualData = {
  id: "annual-data-id",
  company_id: "company-id",
  income_year: 2025,
  answers: {
    shares_owned_at_year_end: true,
    bought_or_sold_shares: false,
    received_dividends: true,
    declared_owner_dividends: false,
    shareholder_loans: false,
    paid_costs: true,
    bank_balance_confirmed: true,
    has_unpaid_items: false,
    general_meeting_approved: true,
    authority_to_submit_confirmed: true,
  },
  confirmations: ["bank_balance_confirmed", "general_meeting_approved", "authority_to_submit_confirmed"],
  no_activity_confirmed: false,
  annual_full_time_equivalents: 0,
  completed_by: "owner",
  completed_at: "2026-01-01T00:00:00Z",
  updated_by: "owner",
  updated_at: "2026-01-01T00:00:00Z",
};

function payload() {
  return buildAnnualAccountsPayload({
    incomeYear: 2025,
    annualData,
    ledgerEntries: [
      {
        id: "entry-id",
        company_id: "company-id",
        setup_id: "setup-id",
        income_year: 2025,
        entry_type: "annual",
        memo: "Annual",
        lines: [
          { account: "1920", debit: 128510, credit: 0 },
          { account: "8070", debit: 0, credit: 100000 },
          { account: "7770", debit: 1490, credit: 0 },
          { account: "8300", debit: 20000, credit: 0 },
          { account: "2500", debit: 0, credit: 20000 },
          { account: "2000", debit: 0, credit: 30000 },
        ],
        risk_flags: [],
        warning_accepted_by: null,
        warning_accepted_at: null,
        created_by: "owner",
        created_at: "2026-01-01T00:00:00Z",
      },
    ],
  });
}

function render(overrides = {}) {
  return renderAnnualAccountsXml({
    payload: payload(),
    companyOrgNumber: "310279617",
    companyName: "Holding & Test AS",
    contactEmail: "owner+talli@example.test",
    approvalDate: "2026-06-30",
    confirmingRepresentative: "Test & Person",
    ...overrides,
  });
}

test("renders deterministic live-schema RR0002 main and company-accounts XML", () => {
  const { mainFormXml, companyAccountsXml } = render();

  assert.match(mainFormXml, /<melding xmlns:xsi="http:\/\/www\.w3\.org\/2001\/XMLSchema-instance" xmlns:xsd="http:\/\/www\.w3\.org\/2001\/XMLSchema" xmlns="http:\/\/schema\.brreg\.no\/regnsys\/aarsregnskap_vanlig" dataFormatId="1266" dataFormatVersion="51820" tjenestehandling="aarsregnskap_vanlig" tjeneste="regnskap">/);
  assert.match(mainFormXml, /<organisasjonsnummer orid="18">310279617<\/organisasjonsnummer>/);
  assert.match(mainFormXml, /<navn orid="1">Holding &amp; Test AS<\/navn>/);
  assert.match(mainFormXml, /<e-post orid="19022">owner\+talli@example\.test<\/e-post>/);
  assert.match(mainFormXml, /<smaaForetak orid="8079">ja<\/smaaForetak>/);
  assert.match(mainFormXml, /<bekreftendeSelskapsrepresentant orid="19023">Test &amp; Person<\/bekreftendeSelskapsrepresentant>/);
  assert.match(mainFormXml, /<aarsregnskapIkkeRevideres orid="34669">ja<\/aarsregnskapIkkeRevideres>/);

  assert.match(companyAccountsXml, /<melding xmlns:xsi="http:\/\/www\.w3\.org\/2001\/XMLSchema-instance" xmlns:xsd="http:\/\/www\.w3\.org\/2001\/XMLSchema" xmlns="http:\/\/schema\.brreg\.no\/regnsys\/aarsregnskap_vanlig\/underskjema" dataFormatId="758" dataFormatVersion="51980" versjon="1\.1" tjenestehandling="aarsregnskap_vanlig_underskjema" tjeneste="regnskap">/);
  assert.match(companyAccountsXml, /<regnskapstype orid="25942">S<\/regnskapstype>/);
  assert.match(companyAccountsXml, /<valoer orid="28974">H<\/valoer>/);
  assert.match(companyAccountsXml, /<sumDriftskostnad>[\s\S]*<aarets orid="17126">1490<\/aarets>[\s\S]*<\/sumDriftskostnad>/);
  assert.match(companyAccountsXml, /<skattekostnad>[\s\S]*<aarets orid="11835">20000<\/aarets>[\s\S]*<\/skattekostnad>/);
  assert.match(companyAccountsXml, /<aarsresultat>[\s\S]*<aarets orid="172">78510<\/aarets>[\s\S]*<\/aarsresultat>/);
  assert.match(companyAccountsXml, /<sumEiendeler>[\s\S]*<aarets orid="219">128510<\/aarets>[\s\S]*<\/sumEiendeler>/);
  assert.match(companyAccountsXml, /<betalbarSkatt>[\s\S]*<aarets orid="2483">20000<\/aarets>[\s\S]*<\/betalbarSkatt>/);
  assert.match(companyAccountsXml, /<sumEgenkapitalGjeld>[\s\S]*<aarets orid="251">128510<\/aarets>[\s\S]*<\/sumEgenkapitalGjeld>/);
  assert.match(companyAccountsXml, /<antallAarsverk orid="37467">0<\/antallAarsverk>/);
  assert.ok(companyAccountsXml.indexOf("<resultatregnskapDriftsresultat>") < companyAccountsXml.indexOf("<resultatregnskapFinansinntekt>"));
  assert.ok(companyAccountsXml.indexOf("<resultatregnskapFinansinntekt>") < companyAccountsXml.indexOf("<resultatregnskapResultat>"));
  assert.ok(companyAccountsXml.indexOf("<resultatregnskapResultat>") < companyAccountsXml.indexOf("<balanseAnleggsmidlerOmloepsmidler>"));
});

test("rejects a payload with readiness blocks", () => {
  const blockedPayload = payload();
  blockedPayload.feedback.push({
    level: "block",
    code: "annual_accounts_audit_required",
    message: "Audit is outside launch scope.",
    source: "test",
  });

  assert.throws(
    () => render({ payload: blockedPayload }),
    /annual_accounts_audit_required/,
  );
});

test("rejects unbalanced or fractional whole-kroner payloads", () => {
  const unbalanced = payload();
  unbalanced.fields.find((field) => field.tag === "sumEiendeler/aarets").value += 1;
  assert.throws(() => render({ payload: unbalanced }), /balanse|eiendeler/i);

  const fractional = payload();
  fractional.fields.find((field) => field.tag === "sumFinansinntekter/aarets").value += 0.5;
  assert.throws(() => render({ payload: fractional }), /hele kroner/i);
});

test("rejects a missing field or mismatched official orid", () => {
  const missing = payload();
  missing.fields = missing.fields.filter((field) => field.tag !== "sumEgenkapital/aarets");
  assert.throws(() => render({ payload: missing }), /sumEgenkapital\/aarets/);

  const mismatched = payload();
  mismatched.fields.find((field) => field.tag === "valuta").orid = "wrong";
  assert.throws(() => render({ payload: mismatched }), /34984/);
});

test("rejects a calendar-invalid approval date", () => {
  assert.throws(
    () => render({ approvalDate: "2026-02-31" }),
    /Fastsettelsesdato/,
  );
});
