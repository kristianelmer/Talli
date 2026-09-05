import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const root = new URL("../", import.meta.url);
const evidence = JSON.parse(readFileSync(new URL(
  "fixtures/corporate-governance-supported-events.json",
  import.meta.url,
), "utf8"));
const ledgerPolicy = readFileSync(
  new URL("docs/accounting/supported-ledger-patterns.md", root),
  "utf8",
);
const ledgerService = readFileSync(
  new URL("apps/backend/src/talli_backend/modules/ledger/service.py", root),
  "utf8",
);
const governancePublic = readFileSync(
  new URL("apps/backend/src/talli_backend/modules/corporate_governance/public.py", root),
  "utf8",
);
const governanceApi = readFileSync(
  new URL("apps/backend/src/talli_backend/main.py", root),
  "utf8",
);

const ore = (value) => Math.round(Number(value) * 100);

test("#191 freezes the complete supported capital, financing, and group matrix", () => {
  assert.equal(evidence.schemaVersion, "1.0");
  assert.equal(evidence.issue, "#191");
  assert.equal(evidence.policyVersion, "corporate-governance-supported-events-2026.1");
  assert.deepEqual(evidence.outputOwners, [
    "ledger", "rf1086", "companyTax", "annualAccounts", "saft", "archive",
  ]);
  assert.deepEqual(
    evidence.patterns.map((pattern) => pattern.id),
    [
      "cash-capital-binding-subscription",
      "cash-capital-restricted-payment",
      "cash-capital-registered",
      "loss-coverage-reduction-decided",
      "loss-coverage-reduction-registered",
      "loss-coverage-reduction-first-recognized-after-registration",
      "owner-to-company-loan-funding",
      "parent-to-subsidiary-loan-lender",
      "intercompany-loan-borrower",
      "ordinary-bank-loan-disbursement",
      "ordinary-bank-loan-payment",
      "group-contribution-subsidiary-to-parent-recipient",
      "group-contribution-parent-to-subsidiary-giver",
      "group-contribution-sister-recipient",
    ],
  );
});

test("every supported occurrence is cent-exact, balanced, signed, and source-addressable", () => {
  for (const pattern of evidence.patterns) {
    assert.match(pattern.eventId, /^[0-9a-f-]{36}$/u, pattern.id);
    assert.ok(pattern.signedArtifacts.length > 0, pattern.id);
    const debit = pattern.ledgerLines.reduce((sum, line) => sum + ore(line[1]), 0);
    const credit = pattern.ledgerLines.reduce((sum, line) => sum + ore(line[2]), 0);
    assert.equal(debit, credit, pattern.id);
    assert.ok(debit > 0, pattern.id);
    assert.ok(pattern.companyTax.effect, pattern.id);
    assert.ok(pattern.annualAccounts.effect, pattern.id);
  }
  assert.equal(evidence.projectionContract.ledgerSourceRecordId, "eventId");
  assert.match(evidence.projectionContract.saftSourceRecordId, /eventId/u);
  assert.equal(evidence.projectionContract.archiveSourceRecordId, "eventId");
  assert.equal(evidence.projectionContract.archiveFinalization, "finalizationSha256");
});

test("RF-1086 receives only registered issuer-capital facts", () => {
  const issuerEffects = evidence.patterns.filter((pattern) => (
    pattern.rf1086.effect.startsWith("issuer_")
  ));
  assert.deepEqual(
    issuerEffects.map((pattern) => pattern.id),
    [
      "cash-capital-registered",
      "loss-coverage-reduction-registered",
      "loss-coverage-reduction-first-recognized-after-registration",
    ],
  );
  for (const pattern of issuerEffects) {
    assert.equal(pattern.rf1086.sourceFact, "shareholder_register");
  }
  for (const pattern of evidence.patterns.filter((item) => !issuerEffects.includes(item))) {
    assert.match(pattern.rf1086.effect, /^none/u, pattern.id);
  }
});

test("group-contribution tax handoffs retain gross, tax, and after-tax amounts separately", () => {
  const groups = evidence.patterns.filter((pattern) => pattern.eventKind === "group_contribution");
  assert.equal(groups.length, 3);
  for (const pattern of groups) {
    const tax = pattern.companyTax;
    assert.equal(tax.effect, "tax_calculation_projection");
    assert.equal(tax.sourceFact, "company_tax_filing");
    assert.equal(
      ore(tax.grossTaxAmountNok),
      ore(tax.relatedTaxNok) + ore(tax.afterTaxAccountingAmountNok),
      pattern.id,
    );
  }
});

test("the pinned account set and immutable finalization contract stay executable", () => {
  const accounts = new Set(evidence.patterns.flatMap((pattern) => (
    pattern.ledgerLines.map((line) => line[0])
  )));
  for (const account of accounts) {
    assert.match(ledgerService, new RegExp(`"${account}"`, "u"), account);
  }
  for (const account of ["1921", "2000", "2020", "2030", "2033", "2080", "1320", "2260", "2035"]) {
    assert.match(ledgerPolicy, new RegExp(`\\b${account}\\b`, "u"), account);
  }
  assert.match(governancePublic, /def signed_artifact_hashes\(/u);
  assert.match(governancePublic, /def finalization_sha256\(/u);
  assert.match(governanceApi, /lifecycle_state: Literal\["finalized"\]/u);
  assert.match(governanceApi, /finalization_sha256=value\.finalization_sha256/u);
});
