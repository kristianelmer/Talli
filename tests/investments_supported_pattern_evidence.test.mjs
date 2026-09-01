import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const root = new URL("../", import.meta.url);
const evidence = JSON.parse(readFileSync(new URL(
  "fixtures/investments-supported-patterns.json",
  import.meta.url,
), "utf8"));
const documentation = readFileSync(
  new URL("docs/accounting/supported-investment-patterns.md", root),
  "utf8",
);

const money = (value) => Math.round(Number(value) * 100);

test("#190 evidence pins the approved source cut and complete supported set", () => {
  assert.equal(evidence.schemaVersion, "2.0");
  assert.equal(evidence.issue, "#190");
  assert.match(evidence.sourceCheckedAt, /^2026-08-31T/u);
  assert.deepEqual(
    evidence.acceptedPatterns.map((pattern) => pattern.id),
    [
      "private-share-purchase",
      "listed-share-purchase",
      "fund-unit-purchase",
      "private-share-sale-gain",
      "listed-share-sale-loss",
      "fund-redemption-gain",
      "ordinary-share-dividend",
      "group-share-dividend",
      "fund-distribution-over-80",
      "fund-distribution-under-20",
      "fund-distribution-proportional",
    ],
  );
  assert.ok(evidence.sources.every((source) => source.url.startsWith("https://")));
  assert.ok(evidence.acceptedPatterns.every((pattern) => (
    /^[0-9a-f]{64}$/u.test(pattern.expected.calculationId)
  )));
  for (const source of evidence.sources) assert.match(documentation, new RegExp(source.url.replaceAll("/", "\\/"), "u"));
});

test("year-end golden keeps book impairment and tax values separate", () => {
  const [measurement] = evidence.yearEndMeasurementCases;
  assert.equal(measurement.id, "listed-share-year-end-impairment");
  assert.equal(measurement.input.asOf, "2026-12-31");
  assert.equal(
    money(measurement.expected.impairmentAmountNok),
    money(measurement.input.preMeasurementBookValueNok)
      - money(measurement.expected.closingBookValueNok),
  );
  assert.equal(measurement.input.taxBasisNok, "100.00");
  assert.equal(measurement.input.taxValueNok, "97.00");
  assert.match(measurement.expected.calculationId, /^[0-9a-f]{64}$/u);
  const debit = measurement.expected.ledgerLines.reduce(
    (sum, line) => sum + money(line.debitNok),
    0,
  );
  const credit = measurement.expected.ledgerLines.reduce(
    (sum, line) => sum + money(line.creditNok),
    0,
  );
  assert.equal(debit, credit);
});

test("simple ownership changes preserve the classified position", () => {
  const [change] = evidence.ownershipContinuityCases;
  assert.equal(
    Number(change.closingUnits),
    Number(change.openingUnits) - Number(change.soldUnits),
  );
  assert.equal(change.accountingClassification, "other_long_term");
  assert.equal(change.positionIdentityPreserved, true);
});

test("purchase and sale golden cases reconcile cent-exact carrying amounts", () => {
  for (const pattern of evidence.acceptedPatterns.filter((item) => item.operation === "purchase")) {
    assert.equal(
      money(pattern.expected.capitalizedCostNok),
      money(pattern.input.considerationNok) + money(pattern.input.transactionCostsNok),
      pattern.id,
    );
    assert.equal(pattern.expected.recognitionLedgerLines[0].account, pattern.expected.investmentAccount);
    assert.equal(money(pattern.expected.recognitionLedgerLines[0].debitNok), money(pattern.expected.capitalizedCostNok));
  }

  for (const pattern of evidence.acceptedPatterns.filter((item) => item.operation === "sale")) {
    const net = money(pattern.input.grossProceedsNok) - money(pattern.input.transactionCostsNok);
    assert.equal(money(pattern.expected.netProceedsNok), net, pattern.id);
    assert.equal(
      money(pattern.expected.gainOrLossNok),
      net - money(pattern.input.fifoCostBasisNok),
      pattern.id,
    );
    for (const lines of [
      pattern.expected.recognitionLedgerLines,
      pattern.expected.settlementLedgerLines,
    ]) {
      const debit = lines.reduce((sum, line) => sum + money(line.debitNok), 0);
      const credit = lines.reduce((sum, line) => sum + money(line.creditNok), 0);
      assert.equal(debit, credit, pattern.id);
    }
  }
});

test("every golden separates accrual recognition from bank settlement", () => {
  const recognitionBalances = {
    purchase: "2990",
    sale: "1570",
    share_dividend: "1530",
    fund_distribution: "1530",
  };
  for (const pattern of evidence.acceptedPatterns) {
    assert.notEqual(pattern.input.eventId, pattern.input.settlementId, pattern.id);
    assert.ok(
      pattern.expected.recognitionLedgerLines.some(
        (line) => line.account === recognitionBalances[pattern.operation],
      ),
      pattern.id,
    );
    assert.ok(
      pattern.expected.settlementLedgerLines.some((line) => line.account === "1920"),
      pattern.id,
    );
    assert.ok(
      pattern.expected.recognitionLedgerLines.every((line) => line.account !== "1920"),
      pattern.id,
    );
  }
});

test("ordinary and proved group dividends keep the statutory inclusion distinct", () => {
  const dividend = evidence.acceptedPatterns.find((item) => item.id === "ordinary-share-dividend");
  const groupDividend = evidence.acceptedPatterns.find((item) => item.id === "group-share-dividend");
  assert.ok(dividend && groupDividend);
  assert.equal(
    money(dividend.expected.taxableAddBackNok),
    Math.round(money(dividend.input.grossAmountNok) * 0.03),
  );
  assert.equal(dividend.expected.taxTreatment, "fritaksmetoden");
  assert.equal(groupDividend.input.groupExceptionEvidence.ownershipBasisPoints, 9001);
  assert.equal(groupDividend.input.groupExceptionEvidence.votingBasisPoints, 9001);
  assert.equal(money(groupDividend.expected.taxableAddBackNok), 0);
  assert.equal(groupDividend.expected.groupExceptionApplied, true);
});

test("fund distributions use the documented statutory equity split", () => {
  const cases = new Map(
    evidence.acceptedPatterns
      .filter((item) => item.operation === "fund_distribution")
      .map((item) => [item.id, item]),
  );
  const expected = {
    "fund-distribution-over-80": [10_000, 0],
    "fund-distribution-under-20": [0, 10_000],
    "fund-distribution-proportional": [5_000, 5_000],
  };
  for (const [id, [dividendBp, interestBp]] of Object.entries(expected)) {
    const pattern = cases.get(id);
    assert.ok(pattern, id);
    const gross = money(pattern.input.grossAmountNok);
    assert.equal(money(pattern.expected.dividendPortionNok), Math.round(gross * dividendBp / 10_000), id);
    assert.equal(money(pattern.expected.interestPortionNok), Math.round(gross * interestBp / 10_000), id);
    assert.equal(
      money(pattern.expected.taxableAddBackNok),
      Math.round(money(pattern.expected.dividendPortionNok) * 0.03),
      id,
    );
    assert.equal(
      money(pattern.expected.totalTaxableIncomeNok),
      money(pattern.expected.interestPortionNok) + money(pattern.expected.taxableAddBackNok),
      id,
    );
  }
});

test("fund redemption averages acquisition-year and sale-year equity evidence", () => {
  const sale = evidence.acceptedPatterns.find((item) => item.id === "fund-redemption-gain");
  assert.ok(sale);
  const averageBp = Math.round(
    (sale.input.acquisitionYearEquityBasisPoints + sale.input.saleYearEquityBasisPoints) / 2,
  );
  assert.equal(sale.expected.averageEquityBasisPoints, averageBp);
  assert.equal(
    money(sale.expected.exemptGainNok),
    Math.round(money(sale.expected.taxGainOrLossNok) * averageBp / 10_000),
  );
  assert.equal(
    money(sale.expected.taxableGainNok),
    money(sale.expected.taxGainOrLossNok) - money(sale.expected.exemptGainNok),
  );
});

test("every accepted case declares exact cross-output disposition", () => {
  const outputs = ["investments", "ledger", "rf1086", "companyTax", "annualAccounts", "saft", "archive"];
  for (const pattern of evidence.acceptedPatterns) {
    assert.deepEqual(Object.keys(pattern.reconciliation).sort(), outputs.sort(), pattern.id);
    assert.equal(pattern.reconciliation.investments.economicEventId, pattern.input.eventId);
    assert.equal(pattern.reconciliation.investments.settlementId, pattern.input.settlementId);
    assert.equal(pattern.reconciliation.ledger.recognitionSourceRecordId, pattern.input.eventId);
    assert.equal(pattern.reconciliation.ledger.settlementSourceRecordId, pattern.input.settlementId);
    assert.equal(pattern.reconciliation.rf1086.effect, "none");
    assert.equal(pattern.reconciliation.archive.evidenceRequired, true);
    assert.equal(pattern.reconciliation.companyTax.calculationId, pattern.expected.calculationId);
    assert.equal(pattern.reconciliation.annualAccounts.economicEventId, pattern.input.eventId);
    assert.deepEqual(
      pattern.reconciliation.saft.sourceRecordIds,
      [pattern.input.eventId, pattern.input.settlementId],
    );
  }
});

test("the hard-block matrix names every approved unsupported family", () => {
  assert.deepEqual(
    new Set(evidence.blockedPatterns.map((pattern) => pattern.code)),
    new Set([
      "FOREIGN_OR_FX_UNSUPPORTED",
      "CRYPTO_UNSUPPORTED",
      "DERIVATIVE_UNSUPPORTED",
      "ACTIVE_TRADING_UNSUPPORTED",
      "COMPLEX_CORPORATE_ACTION_UNSUPPORTED",
      "FUND_EQUITY_DATA_INCOMPLETE",
      "TAX_CLASSIFICATION_UNCLEAR",
      "OWNERSHIP_OR_RIGHTS_UNCLEAR",
      "EVIDENCE_INCOMPLETE",
    ]),
  );
  assert.ok(evidence.blockedPatterns.every((pattern) => pattern.mutationCount === 0));
});
