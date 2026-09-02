import assert from "node:assert/strict";
import test from "node:test";

import {
  buildAnnualCloseDecisionInput,
  corporateAnnualSourceHash,
} from "../apps/web/app/lib/corporate-decision-facts.ts";
import { corporateDecisionHash } from "../apps/web/app/lib/corporate-documents.ts";

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

function annualInput() {
  return {
    company: structuredClone(company),
    shareholders: structuredClone(shareholders),
    annualBasis: structuredClone(annualBasis),
    submission: {
      ...structuredClone(meetingSubmission),
      annualResultAllocationOre: annualBasis.resultAfterTaxOre,
    },
  };
}

test("annual-close input binds both annual-data and annual-account payload hashes", () => {
  const input = annualInput();
  input.annualBasis.incomeYear = 2025;
  input.submission.requestId = "44444444-4444-4444-8444-444444444444";
  input.submission.boardMeeting.meetingDate = "2026-04-15";
  input.submission.generalMeeting.meetingDate = "2026-05-10";
  input.submission.annualResultAllocationOre = input.annualBasis.resultAfterTaxOre;

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
