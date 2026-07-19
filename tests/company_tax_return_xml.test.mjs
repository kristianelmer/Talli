import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";

import { buildCompanyTaxReturnPayload } from "../app/lib/company-tax-return.ts";
import { renderCompanyTaxReturnXml } from "../app/lib/company-tax-return-xml.ts";

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

const ledgerEntries = [
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
      { account: "2000", debit: 0, credit: 30000 },
      { account: "2050", debit: 0, credit: 97020 },
    ],
    risk_flags: [],
    warning_accepted_by: null,
    warning_accepted_at: null,
    created_by: "owner",
    created_at: "2026-01-01T00:00:00Z",
  },
];

const holdingActions = [
  {
    id: "action-id",
    company_id: "company-id",
    income_year: 2025,
    action_type: "dividend_received",
    action_date: "2025-06-15",
    payload: {
      gross_amount: 100000,
      taxable_add_back: 3000,
      tax_treatment: "fritaksmetoden",
    },
    ledger_entry_id: "entry-id",
    bank_transaction_id: null,
    document_id: "document-id",
    risk_level: "info",
    blocker_code: null,
    created_by: "owner",
    created_at: "2026-01-01T00:00:00Z",
  },
];

function renderedDocuments() {
  const payload = buildCompanyTaxReturnPayload({
    companyOrgNumber: "314259521",
    incomeYear: 2025,
    annualData,
    ledgerEntries,
    holdingActions,
  });
  return renderCompanyTaxReturnXml(payload.fields);
}

test("renders deterministic 2025 XML with escaped values and schema order", () => {
  const { skattemeldingXml, naeringsspesifikasjonXml } = renderedDocuments();

  assert.match(skattemeldingXml, /<skattemelding xmlns="urn:no:skatteetaten:fastsetting:formueinntekt:skattemelding:upersonlig:ekstern:v5">/);
  assert.ok(skattemeldingXml.indexOf("<partsnummer>") < skattemeldingXml.indexOf("<inntektsaar>"));
  assert.ok(skattemeldingXml.indexOf("<erOmfattetAvFritaksmetoden>") < skattemeldingXml.indexOf("<utbytte>"));
  assert.match(naeringsspesifikasjonXml, /<naeringsspesifikasjon xmlns="urn:no:skatteetaten:fastsetting:formueinntekt:naeringsspesifikasjon:ekstern:v6">/);
  assert.ok(naeringsspesifikasjonXml.indexOf("<resultatregnskap>") < naeringsspesifikasjonXml.indexOf("<balanseregnskap>"));
  assert.ok(naeringsspesifikasjonXml.indexOf("<balanseregnskap>") < naeringsspesifikasjonXml.indexOf("<forskjellMellomRegnskapsmessigOgSkattemessigVerdi>"));
  assert.ok(naeringsspesifikasjonXml.indexOf("<forskjellMellomRegnskapsmessigOgSkattemessigVerdi>") < naeringsspesifikasjonXml.indexOf("<virksomhet>"));
  assert.match(naeringsspesifikasjonXml, /<resultatOgBalanseregnskapstype>8090<\/resultatOgBalanseregnskapstype>/);
  assert.match(naeringsspesifikasjonXml, /<permanentForskjellstype>tilbakefoeringAvInntektsfoertUtbytte<\/permanentForskjellstype>/);
});

test("rendered XML validates against the pinned official schemas when supplied", {
  skip: !process.env.TALLI_SKATTE_XSD_DIR,
}, () => {
  const directory = mkdtempSync(join(tmpdir(), "talli-tax-xml-"));
  const { skattemeldingXml, naeringsspesifikasjonXml } = renderedDocuments();
  const skattemeldingPath = join(directory, "skattemelding.xml");
  const naeringPath = join(directory, "naeringsspesifikasjon.xml");
  writeFileSync(skattemeldingPath, skattemeldingXml, "utf8");
  writeFileSync(naeringPath, naeringsspesifikasjonXml, "utf8");

  for (const [schema, document] of [
    ["skattemeldingUpersonlig_v5_ekstern.xsd", skattemeldingPath],
    ["naeringsspesifikasjon_v6_ekstern.xsd", naeringPath],
  ]) {
    const result = spawnSync("xmllint", [
      "--noout",
      "--schema",
      join(process.env.TALLI_SKATTE_XSD_DIR, schema),
      document,
    ], { encoding: "utf8" });
    assert.equal(result.status, 0, `${schema}: ${result.stderr || result.stdout}`);
  }
});
