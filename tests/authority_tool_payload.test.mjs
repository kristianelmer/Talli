import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { authorityToolPayload } from "../scripts/authority-tool-payload.mjs";
import { buildAnnualAccountsPayload } from "../apps/web/app/lib/annual-accounts.ts";
import { renderAnnualAccountsXml } from "../apps/web/app/lib/annual-accounts-xml.ts";
import { renderCompanyTaxReturnEnvelope, summarizeCompanyTaxReturnValidation } from "../apps/web/app/lib/company-tax-return-authority-payload.ts";

const digest = (value) => createHash("sha256").update(value).digest("hex");
const fixture = (name) => JSON.parse(readFileSync(new URL(`./fixtures/authority/${name}.json`, import.meta.url)));

test("fixed tax generator preserves predecessor statutory and envelope bytes", () => {
  const c = fixture("company-tax-no-activity-2025");
  const input = { companyOrgNumber: c.company.orgNumber, companyPartyNumber: "1234567", incomeYear: c.company.incomeYear,
    annualData: c.annualData, ledgerEntries: c.ledgerEntries, holdingActions: c.holdingActions };
  const documents = authorityToolPayload({ operation: "company_tax", input });
  // Characterized against the frozen predecessor before deleting its credential transport.
  assert.equal(digest(documents.skattemeldingXml), "42f1424f872f108daecb5d0429e473f1bebaebc3a407990f04dcff6fd1fd7a44");
  assert.equal(digest(documents.naeringsspesifikasjonXml), "ab43d1a3120d6cb50c09f1a88ef211a49b4b3e31233342179a76871badf52599");
  const envelopeInput = { ...documents, companyOrgNumber: c.company.orgNumber, incomeYear: c.company.incomeYear, createdBy: "Talli" };
  assert.equal(digest(authorityToolPayload({ operation: "company_tax_validation_envelope", input: envelopeInput }).envelopeXml),
    "67191b4b3574401afeacbf9ce02b20ce7600d88255f2acd63cb65a4a5f8be113");
  assert.equal(digest(authorityToolPayload({ operation: "company_tax_envelope", input: { ...envelopeInput, currentDocumentReference: "SKI:755:1" } }).envelopeXml),
    "8beaf7dd98950f70b7c2a6f0b39fd5726d04291a2a6905091ca83c1e594743de");
});

test("annual subprocess uses the unchanged frozen generator and passes feedback", () => {
  const c = fixture("annual-accounts-simple-holding-2025");
  const input = { incomeYear: c.company.incomeYear, annualData: c.annualData, ledgerEntries: c.ledgerEntries,
    companyOrgNumber: c.company.orgNumber, companyName: c.company.name, contactEmail: "synthetic@example.test",
    approvalDate: "2026-06-30", confirmingRepresentative: "Synthetic Person" };
  const payload = buildAnnualAccountsPayload(input);
  assert.deepEqual(authorityToolPayload({ operation: "annual_accounts", input }),
    { ...renderAnnualAccountsXml({ ...input, payload }), feedback: payload.feedback });
});

test("extracted tax helper retains XML escaping, base64 and bounded validation summary", () => {
  const envelope = renderCompanyTaxReturnEnvelope({ skattemeldingXml: "<tax>æ &amp; ø</tax>",
    naeringsspesifikasjonXml: "<business/>", currentDocumentReference: "SKI:755:1<&>",
    companyOrgNumber: "310279617", incomeYear: 2025, createdBy: "Talli" });
  assert.ok(envelope.includes(Buffer.from("<tax>æ &amp; ø</tax>").toString("base64")));
  assert.ok(envelope.includes("SKI:755:1&lt;&amp;&gt;"));
  assert.deepEqual(summarizeCompanyTaxReturnValidation("<r><resultatAvValidering>validertMedFeil</resultatAvValidering><avvikstype>B</avvikstype><avvikstype>A</avvikstype><avvikstype>B</avvikstype><veiledningstype>C</veiledningstype><aarsakTilValidertMedFeil>UgyldigPartsnummer</aarsakTilValidertMedFeil><calculatedDocument>private</calculatedDocument></r>"),
    { result: "validertMedFeil", deviationCodes: ["A", "B"], guidanceCodes: ["C"], failureReasons: ["UgyldigPartsnummer"] });
});

test("payload subprocess rejects arbitrary module/path dispatch without reflecting input", () => {
  for (const operation of ["../../evil.js", "exec", "https://evil.invalid/"]) {
    assert.throws(() => authorityToolPayload({ operation, input: {} }), /payload_operation_invalid/);
  }
  const result = spawnSync(process.execPath, ["--experimental-strip-types", "scripts/authority-tool-payload.mjs"], {
    input: JSON.stringify({ operation: "exec", input: { privateKey: "private-input-marker" } }), encoding: "utf8",
    env: { PATH: process.env.PATH ?? "" },
  });
  assert.equal(result.status, 1);
  assert.equal(result.stdout, "");
  assert.equal(result.stderr, "authority_tool_payload_failed\n");
});
