import assert from "node:assert/strict";
import test from "node:test";

import {
  CorporateDecisionFactsError,
  allocateDividendOreProportionally,
  buildAnnualCloseDecisionInput,
  buildOwnerDividendDecisionInput,
  corporateAnnualSourceHash,
} from "../app/lib/corporate-decision-facts.ts";
import { corporateDecisionHash } from "../app/lib/corporate-documents.ts";

const company = {
  id: "22222222-2222-4222-8222-222222222222",
  organizationNumber: "310279617",
  legalName: "LOGISK ØDE TIGER AS",
};

const shareholders = [
  { id: "shareholder-2", name: "Jørgen Østby", shareCount: 400, order: 2 },
  { id: "shareholder-1", name: "Åse Nordmann", shareCount: 600, order: 1 },
];

const annualBasis = {
  id: "33333333-3333-4333-8333-333333333333",
  incomeYear: 2024,
  isLatestApproved: true,
  annualDataHash: "a".repeat(64),
  annualAccountsPayloadHash: "b".repeat(64),
  resultAfterTaxOre: 12_500_000,
  equityOre: 50_000_000,
  availableDistributionOre: 30_000_000,
  cashOre: 40_000_000,
};

const reviewedFacts = {
  organizationNumber: company.organizationNumber,
  legalName: company.legalName,
  shareholders: [
    { shareholderId: "shareholder-1", name: "Åse Nordmann", shareCount: 600 },
    { shareholderId: "shareholder-2", name: "Jørgen Østby", shareCount: 400 },
  ],
  totalCompanyShares: 1000,
  availableDistributionOre: annualBasis.availableDistributionOre,
  annualDataHash: annualBasis.annualDataHash,
  annualAccountsPayloadHash: annualBasis.annualAccountsPayloadHash,
};

const meetingSubmission = {
  requestId: "11111111-1111-4111-8111-111111111111",
  incomeYear: 2025,
  boardMeeting: {
    meetingDate: "2025-06-10",
    meetingTime: "09:00:00",
    place: "  Os  ",
    treatmentMethod: "physical",
  },
  boardParticipants: [
    { participantId: "board-2", name: " Jørgen   Østby ", role: "member", order: 2 },
    { participantId: "board-1", name: "Åse Nordmann", role: "chair", order: 1 },
  ],
  generalMeeting: {
    meetingDate: "2025-06-20",
    meetingTime: "10:00:00",
    place: "Os",
    meetingForm: "physical",
    chairName: " Åse Nordmann ",
    coSignerName: "Jørgen Østby",
  },
  shareholderVotes: [
    { shareholderId: "shareholder-2", representedShareCount: 400, vote: "for" },
    { shareholderId: "shareholder-1", representedShareCount: 600, vote: "for" },
  ],
  oneShareClassConfirmed: true,
  fullBoardParticipationConfirmed: true,
  unanimousBoardConfirmed: true,
  supportedDividendBasisConfirmed: true,
  prudentEquityAndLiquidityConfirmed: true,
  reviewedFacts,
};

function ownerInput() {
  return {
    company: structuredClone(company),
    shareholders: structuredClone(shareholders),
    annualBasis: structuredClone(annualBasis),
    submission: {
      ...structuredClone(meetingSubmission),
      dividendAmountOre: 10_000_001,
      paymentDate: "2025-07-01",
    },
  };
}

test("largest-remainder allocation is deterministic in integer øre", () => {
  assert.deepEqual(
    allocateDividendOreProportionally(5, [
      { shareholderId: "b", shareCount: 2, order: 2 },
      { shareholderId: "a", shareCount: 1, order: 1 },
    ]),
    [
      { shareholderId: "a", amountOre: 2 },
      { shareholderId: "b", amountOre: 3 },
    ],
  );
  assert.equal(
    allocateDividendOreProportionally(10_000_001, [
      { shareholderId: "shareholder-1", shareCount: 600, order: 1 },
      { shareholderId: "shareholder-2", shareCount: 400, order: 2 },
    ]).reduce((sum, allocation) => sum + allocation.amountOre, 0),
    10_000_001,
  );
});

test("owner-dividend facts come only from persisted identity, shareholders, and approved annual totals", () => {
  const decision = buildOwnerDividendDecisionInput(ownerInput());

  assert.equal(decision.legal_name, company.legalName);
  assert.equal(decision.organization_number, company.organizationNumber);
  assert.equal(decision.total_company_shares, 1000);
  assert.deepEqual(decision.shareholders.map(({ shareholder_id, share_count }) => [shareholder_id, share_count]), [
    ["shareholder-1", 600],
    ["shareholder-2", 400],
  ]);
  assert.deepEqual(decision.board_participants.map(({ participant_id, name }) => [participant_id, name]), [
    ["board-1", "Åse Nordmann"],
    ["board-2", "Jørgen Østby"],
  ]);
  assert.equal(decision.financial_totals.available_distribution_ore, 30_000_000);
  assert.equal(decision.dividend.liquidity_after_payment_ore, 29_999_999);
  assert.deepEqual(decision.dividend.allocations, [
    { shareholder_id: "shareholder-1", amount_ore: 6_000_001 },
    { shareholder_id: "shareholder-2", amount_ore: 4_000_000 },
  ]);
  assert.equal(decision.source_hash, corporateAnnualSourceHash(annualBasis));
});

test("stale or tampered reviewed facts are rejected instead of silently replaced", () => {
  const mutations = [
    (input) => { input.submission.reviewedFacts.legalName = "OTHER AS"; },
    (input) => { input.submission.reviewedFacts.shareholders[0].shareCount = 601; },
    (input) => { input.submission.reviewedFacts.totalCompanyShares = 999; },
    (input) => { input.submission.reviewedFacts.availableDistributionOre += 1; },
    (input) => { input.submission.reviewedFacts.annualDataHash = "c".repeat(64); },
    (input) => { input.submission.reviewedFacts.annualAccountsPayloadHash = "d".repeat(64); },
  ];
  for (const mutate of mutations) {
    const input = ownerInput();
    mutate(input);
    assert.throws(
      () => buildOwnerDividendDecisionInput(input),
      (error) => error instanceof CorporateDecisionFactsError
        && error.code === "corporate_documents_reviewed_facts_changed",
    );
  }
});

test("annual-close input binds both annual-data and annual-account payload hashes", () => {
  const input = ownerInput();
  input.annualBasis.incomeYear = 2025;
  input.submission.requestId = "44444444-4444-4444-8444-444444444444";
  input.submission.boardMeeting.meetingDate = "2026-04-15";
  input.submission.generalMeeting.meetingDate = "2026-05-10";
  input.submission.annualResultAllocationOre = input.annualBasis.resultAfterTaxOre;
  delete input.submission.dividendAmountOre;
  delete input.submission.paymentDate;

  const decision = buildAnnualCloseDecisionInput(input);
  assert.equal(decision.decision_kind, "annual_close");
  assert.equal(decision.dividend, null);
  assert.equal(decision.source_hash, corporateAnnualSourceHash(input.annualBasis));

  const changed = structuredClone(input);
  changed.annualBasis.annualAccountsPayloadHash = "e".repeat(64);
  changed.submission.reviewedFacts.annualAccountsPayloadHash = changed.annualBasis.annualAccountsPayloadHash;
  const changedDecision = buildAnnualCloseDecisionInput(changed);
  assert.notEqual(changedDecision.source_hash, decision.source_hash);
  assert.notEqual(corporateDecisionHash(changedDecision), corporateDecisionHash(decision));
});
