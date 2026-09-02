import { createHash } from "node:crypto";

import type { CorporateDecisionInput } from "./corporate-documents.ts";

export class CorporateDecisionFactsError extends Error {
  readonly code: string;

  constructor(message: string, code: string) {
    super(message);
    this.name = "CorporateDecisionFactsError";
    this.code = code;
  }
}

const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const TIME_PATTERN = /^([01]\d|2[0-3]):[0-5]\d:[0-5]\d$/;

export type PersistedCorporateCompany = {
  id: string;
  organizationNumber: string;
  legalName: string;
};

export type PersistedCorporateShareholder = {
  id: string;
  name: string;
  shareCount: number;
  order: number;
};

export type ApprovedAnnualCorporateBasis = {
  id: string;
  incomeYear: number;
  isLatestApproved: boolean;
  annualDataHash: string;
  annualAccountsPayloadHash: string;
  resultAfterTaxOre: number;
  equityOre: number;
  availableDistributionOre: number;
  cashOre: number;
};

export type ReviewedCorporateFacts = {
  organizationNumber: string;
  legalName: string;
  shareholders: Array<{
    shareholderId: string;
    name: string;
    shareCount: number;
  }>;
  totalCompanyShares: number;
  availableDistributionOre: number;
  annualDataHash: string;
  annualAccountsPayloadHash: string;
};

export type CorporateMeetingSubmission = {
  requestId: string;
  incomeYear: number;
  boardMeeting: {
    meetingDate: string;
    meetingTime: string;
    place: string;
    treatmentMethod: "physical" | "video" | "written";
  };
  boardParticipants: Array<{
    participantId: string;
    name: string;
    role: "chair" | "member";
    order: number;
  }>;
  generalMeeting: {
    meetingDate: string;
    meetingTime: string;
    place: string;
    meetingForm: "physical" | "video";
    chairName: string;
    coSignerName: string;
  };
  shareholderVotes: Array<{
    shareholderId: string;
    representedShareCount: number;
    vote: "for" | "against" | "abstain";
  }>;
  oneShareClassConfirmed: boolean;
  fullBoardParticipationConfirmed: boolean;
  unanimousBoardConfirmed: boolean;
  supportedDividendBasisConfirmed: boolean;
  prudentEquityAndLiquidityConfirmed: boolean;
  reviewedFacts: ReviewedCorporateFacts;
};

export type AnnualCloseDecisionSubmission = CorporateMeetingSubmission & {
  annualResultAllocationOre: number;
};

export type CorporateDecisionFactsInput<TSubmission extends CorporateMeetingSubmission> = {
  company: PersistedCorporateCompany;
  shareholders: PersistedCorporateShareholder[];
  annualBasis: ApprovedAnnualCorporateBasis;
  submission: TSubmission;
};

function normalizedText(value: string) {
  return value.normalize("NFC").trim().replace(/\s+/g, " ");
}

function assertSafeInteger(value: number, field: string, minimum = 0) {
  if (!Number.isSafeInteger(value) || value < minimum) {
    throw new CorporateDecisionFactsError(
      `${field} må være et gyldig heltall i øre eller antall.`,
      "corporate_documents_invalid_persisted_facts",
    );
  }
}

function sortedShareholders(shareholders: PersistedCorporateShareholder[]) {
  const sorted = shareholders.map((shareholder) => ({
    ...shareholder,
    id: normalizedText(shareholder.id),
    name: normalizedText(shareholder.name),
  })).sort((left, right) => left.order - right.order || left.id.localeCompare(right.id, "en"));
  if (sorted.length === 0 || new Set(sorted.map(({ id }) => id)).size !== sorted.length) {
    throw new CorporateDecisionFactsError(
      "Aksjonærgrunnlaget mangler eller inneholder duplikater.",
      "corporate_documents_invalid_persisted_facts",
    );
  }
  for (const shareholder of sorted) {
    assertSafeInteger(shareholder.shareCount, "Aksjeantall", 1);
    assertSafeInteger(shareholder.order, "Aksjonærrekkefølge", 0);
    if (!shareholder.id || !shareholder.name) {
      throw new CorporateDecisionFactsError(
        "Aksjonærgrunnlaget mangler stabil ID eller navn.",
        "corporate_documents_invalid_persisted_facts",
      );
    }
  }
  return sorted;
}

export function corporateAnnualSourceHash(
  basis: Pick<ApprovedAnnualCorporateBasis, "id" | "annualDataHash" | "annualAccountsPayloadHash">,
) {
  if (!SHA256_PATTERN.test(basis.annualDataHash)
    || !SHA256_PATTERN.test(basis.annualAccountsPayloadHash)) {
    throw new CorporateDecisionFactsError(
      "Årsgrunnlaget mangler gyldige SHA-256-verdier.",
      "corporate_documents_invalid_persisted_facts",
    );
  }
  const canonicalSource = JSON.stringify({
    annual_accounts_payload_hash: basis.annualAccountsPayloadHash,
    annual_close_source_id: basis.id,
    annual_data_hash: basis.annualDataHash,
  });
  return createHash("sha256").update(canonicalSource, "utf8").digest("hex");
}

function assertReviewedFacts(
  company: PersistedCorporateCompany,
  shareholders: ReturnType<typeof sortedShareholders>,
  basis: ApprovedAnnualCorporateBasis,
  reviewed: ReviewedCorporateFacts,
) {
  const totalCompanyShares = shareholders.reduce((sum, shareholder) => sum + shareholder.shareCount, 0);
  const expectedShareholders = shareholders.map((shareholder) => ({
    shareholderId: shareholder.id,
    name: shareholder.name,
    shareCount: shareholder.shareCount,
  })).sort((left, right) => left.shareholderId.localeCompare(right.shareholderId, "en"));
  const reviewedShareholders = reviewed.shareholders.map((shareholder) => ({
    shareholderId: normalizedText(shareholder.shareholderId),
    name: normalizedText(shareholder.name),
    shareCount: shareholder.shareCount,
  })).sort((left, right) => left.shareholderId.localeCompare(right.shareholderId, "en"));
  const changed = reviewed.organizationNumber !== company.organizationNumber
    || normalizedText(reviewed.legalName) !== normalizedText(company.legalName)
    || JSON.stringify(reviewedShareholders) !== JSON.stringify(expectedShareholders)
    || reviewed.totalCompanyShares !== totalCompanyShares
    || reviewed.availableDistributionOre !== basis.availableDistributionOre
    || reviewed.annualDataHash !== basis.annualDataHash
    || reviewed.annualAccountsPayloadHash !== basis.annualAccountsPayloadHash;
  if (changed) {
    throw new CorporateDecisionFactsError(
      "Fakta er endret siden de ble vist. Last siden på nytt og gjennomgå beslutningen igjen.",
      "corporate_documents_reviewed_facts_changed",
    );
  }
}

function validateAnnualBasis(basis: ApprovedAnnualCorporateBasis) {
  if (!basis.isLatestApproved) {
    throw new CorporateDecisionFactsError(
      "Siste godkjente årsregnskap må brukes som beslutningsgrunnlag.",
      "corporate_documents_latest_annual_accounts_required",
    );
  }
  assertSafeInteger(basis.incomeYear, "Regnskapsår", 2000);
  assertSafeInteger(basis.resultAfterTaxOre, "Årsresultat", Number.MIN_SAFE_INTEGER);
  assertSafeInteger(basis.equityOre, "Egenkapital");
  assertSafeInteger(basis.availableDistributionOre, "Fri egenkapital");
  assertSafeInteger(basis.cashOre, "Likviditet");
  corporateAnnualSourceHash(basis);
}

function normalizedMeetingFacts(
  submission: CorporateMeetingSubmission,
  shareholders: ReturnType<typeof sortedShareholders>,
) {
  if (!DATE_PATTERN.test(submission.boardMeeting.meetingDate)
    || !DATE_PATTERN.test(submission.generalMeeting.meetingDate)
    || !TIME_PATTERN.test(submission.boardMeeting.meetingTime)
    || !TIME_PATTERN.test(submission.generalMeeting.meetingTime)) {
    throw new CorporateDecisionFactsError(
      "Møtedato eller møtetid er ugyldig.",
      "corporate_documents_invalid_meeting_facts",
    );
  }
  const participants = submission.boardParticipants.map((participant) => ({
    participant_id: normalizedText(participant.participantId),
    name: normalizedText(participant.name),
    role: participant.role,
    order: participant.order,
  })).sort((left, right) => left.order - right.order
    || left.participant_id.localeCompare(right.participant_id, "en"));
  if (participants.length === 0
    || participants.some((participant) => !participant.participant_id || !participant.name)
    || new Set(participants.map(({ participant_id }) => participant_id)).size !== participants.length) {
    throw new CorporateDecisionFactsError(
      "Styredeltakerne mangler eller inneholder duplikater.",
      "corporate_documents_invalid_meeting_facts",
    );
  }
  for (const participant of participants) assertSafeInteger(participant.order, "Deltakerrekkefølge", 0);

  const votes = new Map(submission.shareholderVotes.map((vote) => [normalizedText(vote.shareholderId), vote]));
  if (votes.size !== shareholders.length || submission.shareholderVotes.length !== shareholders.length) {
    throw new CorporateDecisionFactsError(
      "Alle registrerte aksjonærer må være med i stemmegrunnlaget.",
      "corporate_documents_shareholder_facts_mismatch",
    );
  }
  const decisionShareholders = shareholders.map((shareholder) => {
    const vote = votes.get(shareholder.id);
    if (!vote) {
      throw new CorporateDecisionFactsError(
        "Alle registrerte aksjonærer må være med i stemmegrunnlaget.",
        "corporate_documents_shareholder_facts_mismatch",
      );
    }
    assertSafeInteger(vote.representedShareCount, "Representert aksjeantall");
    return {
      shareholder_id: shareholder.id,
      name: shareholder.name,
      share_count: shareholder.shareCount,
      represented_share_count: vote.representedShareCount,
      vote: vote.vote,
    };
  });
  return {
    boardMeeting: {
      meeting_date: submission.boardMeeting.meetingDate,
      meeting_time: submission.boardMeeting.meetingTime,
      place: normalizedText(submission.boardMeeting.place),
      treatment_method: submission.boardMeeting.treatmentMethod,
    },
    boardParticipants: participants.map(({ order: _order, ...participant }) => participant),
    generalMeeting: {
      meeting_date: submission.generalMeeting.meetingDate,
      meeting_time: submission.generalMeeting.meetingTime,
      place: normalizedText(submission.generalMeeting.place),
      meeting_form: submission.generalMeeting.meetingForm,
      chair_name: normalizedText(submission.generalMeeting.chairName),
      co_signer_name: normalizedText(submission.generalMeeting.coSignerName),
    },
    decisionShareholders,
  };
}

function buildCommonDecisionInput<TSubmission extends CorporateMeetingSubmission>(
  input: CorporateDecisionFactsInput<TSubmission>,
) {
  const company = {
    ...input.company,
    organizationNumber: normalizedText(input.company.organizationNumber),
    legalName: normalizedText(input.company.legalName),
  };
  const shareholders = sortedShareholders(input.shareholders);
  validateAnnualBasis(input.annualBasis);
  assertReviewedFacts(company, shareholders, input.annualBasis, input.submission.reviewedFacts);
  const meeting = normalizedMeetingFacts(input.submission, shareholders);
  const totalCompanyShares = shareholders.reduce((sum, shareholder) => sum + shareholder.shareCount, 0);
  const fullShareRepresentation = meeting.decisionShareholders.every(
    (shareholder) => shareholder.represented_share_count === shareholder.share_count,
  );
  const unanimousShareholders = meeting.decisionShareholders.every(({ vote }) => vote === "for");

  return {
    request_id: input.submission.requestId,
    company_id: company.id,
    organization_number: company.organizationNumber,
    legal_name: company.legalName,
    income_year: input.submission.incomeYear,
    decision_kind: "annual_close" as const,
    annual_close_source_id: input.annualBasis.id,
    source_hash: corporateAnnualSourceHash(input.annualBasis),
    template_family: "norwegian_simple_as" as const,
    template_version: "corporate-no-v1-reportlab-5.0.0-noto-ffebf8c1" as const,
    annual_basis_year: input.annualBasis.incomeYear,
    financial_totals: {
      result_after_tax_ore: input.annualBasis.resultAfterTaxOre,
      equity_ore: input.annualBasis.equityOre,
      available_distribution_ore: input.annualBasis.availableDistributionOre,
      cash_ore: input.annualBasis.cashOre,
    },
    board_meeting: meeting.boardMeeting,
    board_participants: meeting.boardParticipants,
    general_meeting: meeting.generalMeeting,
    shareholders: meeting.decisionShareholders,
    total_company_shares: totalCompanyShares,
    one_share_class_confirmed: input.submission.oneShareClassConfirmed,
    confirmations: {
      latest_approved_annual_accounts: input.annualBasis.isLatestApproved,
      supported_dividend_basis: input.submission.supportedDividendBasisConfirmed,
      full_board_participation: input.submission.fullBoardParticipationConfirmed,
      full_share_representation: fullShareRepresentation,
      unanimous_board: input.submission.unanimousBoardConfirmed,
      unanimous_shareholders: unanimousShareholders,
      proportional_allocation: true,
      prudent_equity_and_liquidity: input.submission.prudentEquityAndLiquidityConfirmed,
    },
    sortedShareholders: shareholders,
  };
}

export function buildAnnualCloseDecisionInput(
  input: CorporateDecisionFactsInput<AnnualCloseDecisionSubmission>,
): CorporateDecisionInput {
  const common = buildCommonDecisionInput(input);
  assertSafeInteger(
    input.submission.annualResultAllocationOre,
    "Resultatdisponering",
    Number.MIN_SAFE_INTEGER,
  );
  if (input.annualBasis.incomeYear !== input.submission.incomeYear
    || input.submission.annualResultAllocationOre !== input.annualBasis.resultAfterTaxOre) {
    throw new CorporateDecisionFactsError(
      "Resultatdisponeringen stemmer ikke med årsregnskapsgrunnlaget.",
      "corporate_documents_annual_result_mismatch",
    );
  }
  const { sortedShareholders: _sortedShareholders, ...decision } = common;
  return {
    ...decision,
    dividend: null,
    annual_result_allocation_ore: input.submission.annualResultAllocationOre,
  };
}
