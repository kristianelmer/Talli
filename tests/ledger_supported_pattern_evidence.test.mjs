import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const fixturePath = new URL("./fixtures/ledger-supported-patterns.json", import.meta.url);
const mapPath = new URL("../docs/accounting/supported-ledger-patterns.md", import.meta.url);

const fixture = JSON.parse(readFileSync(fixturePath, "utf8"));
const sourceMap = readFileSync(mapPath, "utf8");

const expectedPatterns = new Set([
  "opening-rebuild",
  "ordinary-administration-cost-paid",
  "norwegian-share-purchase-cost-method",
  "norwegian-share-sale-cost-method",
  "direct-owner-share-transfer",
  "cash-capital-increase",
  "capital-reduction-loss-coverage",
  "bank-interest-income",
  "company-tax-accrual",
  "ordinary-bank-loan",
  "owner-to-company-loan",
  "norwegian-intercompany-loan",
  "dividend-received",
  "owner-dividend",
  "group-contribution-subsidiary-to-parent",
  "group-contribution-parent-to-subsidiary",
  "group-contribution-sister-to-sister",
  "guided-correction",
  "period-close",
]);

const allowedProjections = new Set([
  "LEDGER",
  "BANK",
  "INVESTMENTS",
  "GOVERNANCE",
  "SHAREHOLDER_REGISTER",
  "TAX",
  "ANNUAL_ACCOUNTS",
  "SAF_T",
  "ARCHIVE",
]);

function cents(value) {
  assert.match(value, /^\d+\.\d{2}$/u);
  const [whole, fraction] = value.split(".");
  return BigInt(whole) * 100n + BigInt(fraction);
}

test("the normative map pins official sources and the owner-approved boundary", () => {
  assert.equal(fixture.schemaVersion, "1.0");
  assert.equal(fixture.sourceCut, "2026-08-27");
  assert.match(fixture.policyVersion, /^ledger-supported-patterns-\d{4}\.\d+$/u);
  assert.ok(sourceMap.includes(fixture.ownerResolution));
  assert.match(sourceMap, /All links below were accessed on 2026-08-27/u);
  for (const authority of [
    "lovdata.no/lov/2004-11-19-73",
    "lovdata.no/lov/1998-07-17-56",
    "lovdata.no/lov/1999-03-26-14",
    "lovdata.no/lov/1997-06-13-44",
    "regnskapsstiftelsen.no/wp-content/uploads/2026/01/NRS-8",
    "info.altinn.no",
    "www.brreg.no",
    "www.skatteetaten.no",
  ]) {
    assert.ok(sourceMap.includes(authority), `missing official source ${authority}`);
  }
  assert.match(sourceMap, /Tax logic must still select the law applicable to the company-year/u);
  assert.match(sourceMap, /Temporal tests must select the legal\/tax rule set by company-year/u);
});

test("every owner-approved deterministic pattern has one versioned golden case", () => {
  const actual = new Set(fixture.patterns.map((pattern) => pattern.id));
  assert.deepEqual(actual, expectedPatterns);
  assert.equal(actual.size, fixture.patterns.length);

  for (const pattern of fixture.patterns) {
    assert.match(pattern.id, /^[a-z][a-z0-9-]+$/u);
    assert.ok(sourceMap.includes(`### ${pattern.section}`), `${pattern.id} has no normative section`);
    assert.match(pattern.input.eventId, /^golden:/u);
    assert.ok(pattern.blocks.length > 0, `${pattern.id} has no fail-closed example`);
    assert.equal(new Set(pattern.blocks).size, pattern.blocks.length);
    assert.ok(pattern.projections.length > 0, `${pattern.id} has no downstream facts`);
    for (const projection of pattern.projections) {
      assert.ok(allowedProjections.has(projection), `${pattern.id} has unknown ${projection}`);
    }
  }
});

test("every golden economic journal is balanced in exact NOK cents", () => {
  for (const pattern of fixture.patterns) {
    for (const journal of pattern.journals) {
      assert.ok(journal.lines.length >= 2, `${pattern.id}/${journal.phase} is not double-entry`);
      const debit = journal.lines.reduce((sum, line) => sum + cents(line.debitNok), 0n);
      const credit = journal.lines.reduce((sum, line) => sum + cents(line.creditNok), 0n);
      assert.equal(debit, credit, `${pattern.id}/${journal.phase} is unbalanced`);
      assert.ok(debit > 0n, `${pattern.id}/${journal.phase} has no economic amount`);
      for (const line of journal.lines) {
        assert.match(line.account, /^[A-Z][A-Z0-9_]+$/u);
        assert.ok(cents(line.debitNok) === 0n || cents(line.creditNok) === 0n);
      }
    }
  }
});

test("non-ledger ownership changes and locks cannot fabricate economic journals", () => {
  for (const id of ["direct-owner-share-transfer", "period-close"]) {
    const pattern = fixture.patterns.find((candidate) => candidate.id === id);
    assert.deepEqual(pattern.journals, []);
  }
  const transfer = fixture.patterns.find(
    (candidate) => candidate.id === "direct-owner-share-transfer",
  );
  assert.ok(transfer.projections.includes("SHAREHOLDER_REGISTER"));
  assert.ok(!transfer.projections.includes("LEDGER"));
});

test("high-risk equity and group cases preserve the researched semantic distinctions", () => {
  const capitalIncrease = fixture.patterns.find(
    (pattern) => pattern.id === "cash-capital-increase",
  );
  assert.deepEqual(
    capitalIncrease.journals.map((journal) => journal.phase),
    ["BINDING_SUBSCRIPTION", "RESTRICTED_PAYMENT", "REGISTERED"],
  );
  const capitalReduction = fixture.patterns.find(
    (pattern) => pattern.id === "capital-reduction-loss-coverage",
  );
  assert.equal(capitalReduction.input.cashToOwnersNok, "0.00");
  assert.ok(capitalReduction.blocks.includes("PAID_IN_CAPITAL_REPAYMENT"));

  const groupPatterns = fixture.patterns.filter((pattern) =>
    pattern.id.startsWith("group-contribution-"),
  );
  assert.deepEqual(
    new Set(groupPatterns.map((pattern) => pattern.input.relationship)),
    new Set(["SUBSIDIARY_TO_PARENT", "PARENT_TO_SUBSIDIARY", "SISTER_TO_SISTER"]),
  );
  assert.equal(
    new Set(groupPatterns.map((pattern) => JSON.stringify(pattern.journals))).size,
    3,
    "relationship-specific group-contribution routes must not collapse",
  );
});

test("ordinary bank-loan phases retain stable agreement and loan linkage", () => {
  const bankLoan = fixture.patterns.find(
    (pattern) => pattern.id === "ordinary-bank-loan",
  );

  assert.equal(bankLoan.input.agreementId, "bank-loan-agreement:1");
  assert.equal(bankLoan.input.loanReferenceId, "bank-loan:1");
  assert.deepEqual(
    bankLoan.journals.map((journal) => journal.phase),
    ["DISBURSEMENT", "PAYMENT"],
  );
  for (const projection of [
    "BANK",
    "TAX",
    "ANNUAL_ACCOUNTS",
    "SAF_T",
    "ARCHIVE",
  ]) {
    assert.ok(
      bankLoan.projections.includes(projection),
      `ordinary-bank-loan is missing ${projection}`,
    );
  }
  assert.ok(
    bankLoan.blocks.includes("OPENING_LOAN_ANCHOR_MISSING"),
    "a prior-year loan without an evidenced opening anchor must fail closed",
  );
});

test("golden outputs declare every downstream family needed by later reconciliation", () => {
  const used = new Set(fixture.patterns.flatMap((pattern) => pattern.projections));
  for (const required of [
    "LEDGER",
    "BANK",
    "INVESTMENTS",
    "GOVERNANCE",
    "SHAREHOLDER_REGISTER",
    "TAX",
    "ANNUAL_ACCOUNTS",
    "SAF_T",
    "ARCHIVE",
  ]) {
    assert.ok(used.has(required), `missing downstream family ${required}`);
  }
  for (const pattern of fixture.patterns.filter((candidate) => candidate.journals.length > 0)) {
    assert.ok(pattern.projections.includes("LEDGER"));
    assert.ok(pattern.projections.includes("ARCHIVE"));
  }
});
