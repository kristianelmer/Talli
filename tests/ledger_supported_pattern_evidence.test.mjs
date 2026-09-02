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

test("opening golden case is typed, classification-complete, and source-bound", () => {
  const opening = fixture.patterns.find((pattern) => pattern.id === "opening-rebuild");
  const lines = opening.journals[0].lines;
  const expectedAccounts = {
    ACCRUED_INTEREST_PAYABLE: "2965",
    ACCRUED_INTEREST_RECEIVABLE: "1700",
    ASSOCIATE_INVESTMENT: "1310",
    BANK: "1920",
    CORPORATE_SHAREHOLDER_LOAN_RECEIVABLE: "1370",
    CURRENT_FUND_INVESTMENT: "1815",
    CURRENT_LISTED_SHARE_INVESTMENT: "1810",
    CURRENT_TAX_PAYABLE: "2500",
    DEFERRED_TAX_ASSET: "1070",
    DEFERRED_TAX_LIABILITY: "2120",
    DIVIDEND_PAYABLE: "2800",
    DIVIDEND_RECEIVABLE: "1530",
    GROUP_COMPANY_LOAN_RECEIVABLE: "1325",
    GROUP_CONTRIBUTION_PAYABLE: "2960",
    GROUP_CONTRIBUTION_RECEIVABLE: "1560",
    INTERCOMPANY_LOAN_PAYABLE: "2260",
    LONG_TERM_BANK_LOAN_PAYABLE: "2220",
    OTHER_EQUITY: "2050",
    OTHER_LONG_TERM_INVESTMENT: "1350",
    OTHER_PAID_IN_EQUITY: "2035",
    OWNER_LOAN_PAYABLE: "2255",
    REGISTERED_SHARE_CAPITAL: "2000",
    RESTRICTED_BANK: "1921",
    RETAINED_EARNINGS: "2050",
    SHARE_PREMIUM: "2020",
    SHORT_TERM_BANK_LOAN_PAYABLE: "2380",
    SUBSCRIPTION_RECEIVABLE: "1500",
    SUBSIDIARY_INVESTMENT: "1300",
    SUBSIDIARY_LOAN_RECEIVABLE: "1320",
    SUPPLIER_PAYABLE: "2400",
    TAX_RECEIVABLE: "1570",
    UNCOVERED_LOSS: "2080",
    UNREGISTERED_CAPITAL_INCREASE: "2030",
    UNREGISTERED_CAPITAL_REDUCTION: "2033",
  };

  assert.equal(opening.input.mode, "PRIOR_CLOSE_RECONSTRUCTION");
  assert.equal(opening.input.openingBasis, "annual-accounts");
  assert.deepEqual(
    new Set(lines.map((line) => line.category)),
    new Set(Object.keys(expectedAccounts)),
  );
  assert.equal(lines.length, 36);
  for (const line of lines) {
    assert.equal(line.postingAccount, expectedAccounts[line.category]);
    assert.match(line.referenceId, /^[a-z][a-z0-9:-]+$/u);
    assert.ok("lifecyclePhase" in line);
  }

  assert.deepEqual(
    new Set(opening.input.components.map((component) => component.componentKind)),
    new Set([
      "CLASSIFIED_BALANCE",
      "BANK_LOAN",
      "INVESTMENT",
      "CAPITAL_INCREASE",
      "CAPITAL_REDUCTION",
      "DIVIDEND_RECEIVABLE",
      "DIVIDEND_PAYABLE",
    ]),
  );
  assert.deepEqual(
    new Set(lines.map((line) => line.lifecyclePhase).filter(Boolean)),
    new Set([
      "ASSOCIATE",
      "BINDING_SUBSCRIPTION",
      "CURRENT_FUND",
      "CURRENT_LISTED_SHARE",
      "DECIDED_NOT_REGISTERED",
      "DECLARED_UNPAID",
      "FINAL_DECISION_UNSETTLED",
      "LONG_TERM",
      "OTHER_LONG_TERM",
      "RESTRICTED_PAYMENT",
      "SHORT_TERM",
      "SUBSIDIARY",
    ]),
  );

  for (const source of Object.values(opening.input.sources)) {
    assert.match(source.recordId, /^[a-z][a-z0-9:-]+$/u);
    assert.ok(Number.isInteger(source.revision) && source.revision > 0);
    assert.match(source.factSha256, /^[0-9a-f]{64}$/u);
  }
  for (const component of opening.input.components) {
    assert.ok(opening.input.sources[component.primarySource]);
    assert.ok(component.corroboratingSources.length > 0);
    assert.equal(new Set([
      component.primarySource,
      ...component.corroboratingSources,
    ]).size, 1 + component.corroboratingSources.length);
    for (const sourceKey of component.corroboratingSources) {
      assert.ok(opening.input.sources[sourceKey]);
    }
  }
});

test("opening golden case declares cross-output projection parity", () => {
  const opening = fixture.patterns.find((pattern) => pattern.id === "opening-rebuild");
  const facts = opening.projectionFacts;

  assert.deepEqual(new Set(Object.keys(facts)), new Set(opening.projections));
  assert.equal(facts.LEDGER.compiledLineCount, opening.journals[0].lines.length);
  assert.equal(
    facts.LEDGER.distinctCategoryCount,
    new Set(opening.journals[0].lines.map((line) => line.category)).size,
  );
  assert.deepEqual(facts.BANK.postingAccounts, ["1920", "1921"]);
  assert.deepEqual(facts.INVESTMENTS.classifications, [
    "SUBSIDIARY",
    "ASSOCIATE",
    "OTHER_LONG_TERM",
    "CURRENT_LISTED_SHARE",
    "CURRENT_FUND",
  ]);
  assert.deepEqual(new Set(facts.TAX.categories), new Set([
    "TAX_RECEIVABLE",
    "CURRENT_TAX_PAYABLE",
    "DEFERRED_TAX_ASSET",
    "DEFERRED_TAX_LIABILITY",
  ]));
  assert.equal(facts.SAF_T.restrictedBankPostingAccount, "1921");
  assert.equal(facts.SAF_T.restrictedBankStandardAccount, "1920");
  assert.equal(facts.SAF_T.allLinesHavePostingAccount, true);
  assert.deepEqual(
    new Set(facts.ARCHIVE.sourceKeys),
    new Set(Object.keys(opening.input.sources)),
  );
  assert.equal(facts.ARCHIVE.immutableHashesRequired, true);
  for (const blocker of [
    "OPENING_BASIS_MISSING",
    "OPENING_EVIDENCE_SOURCE_MISMATCH",
    "OPENING_SOURCE_OVERLAP",
    "DUPLICATE_COMPONENT_IDENTITY",
    "UNSUPPORTED_OPENING_CLASSIFICATION",
    "UNBALANCED_OPENING",
    "OPENING_LOAN_REFERENCE_COLLISION",
    "OPENING_LIFECYCLE_ANCHOR_INCOMPLETE",
  ]) {
    assert.ok(opening.blocks.includes(blocker));
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

test("cash capital increase phases retain one stable lifecycle reference", () => {
  const capitalIncrease = fixture.patterns.find(
    (pattern) => pattern.id === "cash-capital-increase",
  );

  assert.equal(
    capitalIncrease.input.capitalIncreaseReferenceId,
    "capital-increase:1",
  );
  assert.deepEqual(capitalIncrease.input.allocations, [
    {
      subscriberId: "shareholder:owner-a",
      shares: "100",
      acquisitionDate: "2026-05-10",
      dividendRightsDate: "2026-05-20",
    },
  ]);
  assert.deepEqual(capitalIncrease.input.sourceReferences, {
    decision: "corporate-governance:capital-increase:1",
    signedSubscription: "documents:capital-subscription:1",
    restrictedAccountReceipt: "banking:restricted-contribution:1",
    contributionConfirmation: "documents:contribution-confirmation:1",
    registrySubmission: "corporate-governance:registry-submission:1",
    registryRegistration: "corporate-governance:registry-registration:1",
    updatedArticles: "documents:articles:registered:1",
    shareholderRegister: "shareholder-register-filing:capital-increase:1",
  });
  const shareCount = BigInt(capitalIncrease.input.newShares);
  assert.equal(
    cents(capitalIncrease.input.nominalPerShareNok) * shareCount,
    cents(capitalIncrease.input.nominalIncreaseNok),
  );
  assert.equal(
    cents(capitalIncrease.input.premiumPerShareNok) * shareCount,
    cents(capitalIncrease.input.sharePremiumNok),
  );
  assert.equal(
    cents(capitalIncrease.input.issuePricePerShareNok),
    cents(capitalIncrease.input.nominalPerShareNok)
      + cents(capitalIncrease.input.premiumPerShareNok),
  );
  assert.equal(
    cents(capitalIncrease.input.inputValuePerShareNok),
    cents(capitalIncrease.input.issuePricePerShareNok),
  );
  assert.equal(
    cents(capitalIncrease.input.paidInCapitalPerShareNok),
    cents(capitalIncrease.input.nominalPerShareNok)
      + cents(capitalIncrease.input.premiumPerShareNok),
  );
  assert.equal(
    cents(capitalIncrease.input.issuePricePerShareNok) * shareCount,
    cents(capitalIncrease.input.cashContributionNok),
  );
  assert.deepEqual(
    capitalIncrease.journals.map((journal) => journal.phase),
    ["BINDING_SUBSCRIPTION", "RESTRICTED_PAYMENT", "REGISTERED"],
  );
  for (const projection of [
    "LEDGER",
    "BANK",
    "GOVERNANCE",
    "SHAREHOLDER_REGISTER",
    "TAX",
    "ANNUAL_ACCOUNTS",
    "SAF_T",
    "ARCHIVE",
  ]) {
    assert.ok(
      capitalIncrease.projections.includes(projection),
      `cash-capital-increase is missing ${projection}`,
    );
  }
  assert.deepEqual(capitalIncrease.blocks, [
    "CONTRIBUTION_CONFIRMATION_MISSING",
    "NON_CASH_CONTRIBUTION",
    "REGISTRATION_MISMATCH",
    "OPENING_CAPITAL_INCREASE_ANCHOR_MISSING",
  ]);
});

test("loss-coverage capital reduction preserves stable lifecycle and per-share evidence", () => {
  const capitalReduction = fixture.patterns.find(
    (pattern) => pattern.id === "capital-reduction-loss-coverage",
  );

  assert.equal(
    capitalReduction.input.capitalReductionReferenceId,
    "capital-reduction:1",
  );
  assert.deepEqual(capitalReduction.lifecycleShapes, {
    decisionThenRegistration: ["DECIDED_NOT_REGISTERED", "REGISTERED"],
    firstRecognizedAfterRegistration: ["FIRST_RECOGNIZED_AFTER_REGISTRATION"],
  });
  assert.deepEqual(
    capitalReduction.journals.map((journal) => journal.phase),
    ["DECIDED_NOT_REGISTERED", "REGISTERED"],
  );
  assert.deepEqual(capitalReduction.firstRegisteredJournal, {
    phase: "FIRST_RECOGNIZED_AFTER_REGISTRATION",
    company: "talli-company",
    lines: [
      {
        account: "REGISTERED_SHARE_CAPITAL",
        debitNok: "20000.00",
        creditNok: "0.00",
      },
      {
        account: "UNCOVERED_LOSS",
        debitNok: "0.00",
        creditNok: "20000.00",
      },
    ],
  });
  const directRegistrationDebit = capitalReduction.firstRegisteredJournal.lines
    .reduce((sum, line) => sum + cents(line.debitNok), 0n);
  const directRegistrationCredit = capitalReduction.firstRegisteredJournal.lines
    .reduce((sum, line) => sum + cents(line.creditNok), 0n);
  assert.equal(directRegistrationDebit, directRegistrationCredit);
  assert.ok(directRegistrationDebit > 0n);
  assert.deepEqual(capitalReduction.input.sourceReferences, {
    boardProposal: "corporate-governance:capital-reduction-proposal:1",
    generalMeetingDecision: "corporate-governance:capital-reduction-decision:1",
    balanceEvidence: "documents:capital-reduction-balance:1",
    registrySubmission: "corporate-governance:capital-reduction-submission:1",
    registryRegistration: "corporate-governance:capital-reduction-registration:1",
    updatedArticles: "documents:articles:capital-reduction-registered:1",
    shareholderRegister: "shareholder-register-filing:capital-reduction:1",
  });

  const shareCount = BigInt(capitalReduction.input.shareCount);
  assert.equal(
    (cents(capitalReduction.input.oldNominalPerShareNok)
      - cents(capitalReduction.input.newNominalPerShareNok)) * shareCount,
    cents(capitalReduction.input.nominalReductionNok),
  );
  assert.equal(
    cents(capitalReduction.input.oldNominalPerShareNok) * shareCount,
    cents(capitalReduction.input.oldRegisteredShareCapitalNok),
  );
  assert.equal(
    cents(capitalReduction.input.newNominalPerShareNok) * shareCount,
    cents(capitalReduction.input.newRegisteredShareCapitalNok),
  );
  assert.equal(
    cents(capitalReduction.input.paidInCapitalPerShareBeforeNok),
    cents(capitalReduction.input.paidInCapitalPerShareAfterNok),
    "loss coverage must preserve historical paid-in capital per surviving share",
  );
  assert.equal(capitalReduction.input.ownersAndShareCountUnchanged, true);
  assert.equal(capitalReduction.input.cashToOwnersNok, "0.00");
  assert.deepEqual(capitalReduction.blocks, [
    "PAID_IN_CAPITAL_REPAYMENT",
    "LOSS_EVIDENCE_INSUFFICIENT",
    "MINIMUM_CAPITAL_BREACH",
    "OPENING_CAPITAL_REDUCTION_ANCHOR_MISSING",
  ]);
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
