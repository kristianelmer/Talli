import { createHash } from "node:crypto";

import type {
  ApprovedAnnualCorporateBasis,
  PersistedCorporateCompany,
  PersistedCorporateShareholder,
  ReviewedCorporateFacts,
} from "./corporate-decision-facts.ts";

type AnnualDataForDividendBasis = {
  id: string;
  company_id: string;
  income_year: number;
  answers: { general_meeting_approved?: boolean };
  confirmations: string[];
  no_activity_confirmed: boolean;
  annual_full_time_equivalents?: number | null;
  completed_at: string;
  updated_at: string;
};

type AnnualAccountsPayloadForDividendBasis = {
  fields: Array<{ tag: string; value: string | number }>;
  feedback: Array<{ level: "block" | "warning"; code: string; message: string }>;
};

export class OwnerDividendDraftBasisError extends Error {
  readonly code: string;

  constructor(message: string, code: string) {
    super(message);
    this.name = "OwnerDividendDraftBasisError";
    this.code = code;
  }
}

function stableJson(value: unknown): unknown {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new OwnerDividendDraftBasisError(
      "Årsgrunnlaget inneholder et ugyldig tall.",
      "corporate_documents_invalid_annual_basis",
    );
    return value;
  }
  if (Array.isArray(value)) return value.map(stableJson);
  if (value && typeof value === "object") {
    const sorted: Record<string, unknown> = {};
    for (const key of Object.keys(value as Record<string, unknown>).sort()) {
      const child = (value as Record<string, unknown>)[key];
      if (child === undefined) continue;
      sorted[key] = stableJson(child);
    }
    return sorted;
  }
  throw new OwnerDividendDraftBasisError(
    "Årsgrunnlaget inneholder en ugyldig verdi.",
    "corporate_documents_invalid_annual_basis",
  );
}

export function persistedFactHash(value: unknown) {
  return createHash("sha256").update(JSON.stringify(stableJson(value)), "utf8").digest("hex");
}

function fieldNumber(payload: AnnualAccountsPayloadForDividendBasis, tag: string) {
  const field = payload.fields.find((candidate) => candidate.tag === tag);
  const value = Number(field?.value);
  if (!field || !Number.isFinite(value)) {
    throw new OwnerDividendDraftBasisError(
      `Årsregnskapsgrunnlaget mangler ${tag}.`,
      "corporate_documents_invalid_annual_basis",
    );
  }
  return value;
}

function toOre(value: number) {
  const ore = Math.round(value * 100);
  if (!Number.isSafeInteger(ore)) {
    throw new OwnerDividendDraftBasisError(
      "Årsregnskapsbeløpet er utenfor støttet område.",
      "corporate_documents_invalid_annual_basis",
    );
  }
  return ore;
}

export function buildOwnerDividendAnnualBasis(input: {
  annualData: AnnualDataForDividendBasis;
  annualAccountsPayload: AnnualAccountsPayloadForDividendBasis;
}): ApprovedAnnualCorporateBasis {
  if (input.annualData.answers.general_meeting_approved !== true) {
    throw new OwnerDividendDraftBasisError(
      "Siste årsregnskap er ikke registrert som godkjent av generalforsamlingen.",
      "corporate_documents_latest_annual_accounts_required",
    );
  }
  const hardBlock = input.annualAccountsPayload.feedback.find(({ level }) => level === "block");
  if (hardBlock) {
    throw new OwnerDividendDraftBasisError(
      hardBlock.message,
      hardBlock.code,
    );
  }
  const equityOre = toOre(fieldNumber(input.annualAccountsPayload, "sumEgenkapital/aarets"));
  const retainedEquityOre = toOre(fieldNumber(input.annualAccountsPayload, "annenEgenkapital/aarets"));
  const cashOre = toOre(fieldNumber(input.annualAccountsPayload, "sumBankinnskuddKontanter/aarets"));
  if (equityOre < 0 || cashOre < 0) {
    throw new OwnerDividendDraftBasisError(
      "Negativ egenkapital eller likviditet er utenfor støttet utbytteløype.",
      "corporate_documents_unsupported_dividend_basis",
    );
  }
  const annualDataSnapshot = {
    id: input.annualData.id,
    company_id: input.annualData.company_id,
    income_year: input.annualData.income_year,
    answers: input.annualData.answers,
    confirmations: input.annualData.confirmations,
    no_activity_confirmed: input.annualData.no_activity_confirmed,
    annual_full_time_equivalents: input.annualData.annual_full_time_equivalents ?? 0,
    completed_at: input.annualData.completed_at,
    updated_at: input.annualData.updated_at,
  };
  return {
    id: input.annualData.id,
    incomeYear: input.annualData.income_year,
    isLatestApproved: true,
    annualDataHash: persistedFactHash(annualDataSnapshot),
    annualAccountsPayloadHash: persistedFactHash(input.annualAccountsPayload),
    resultAfterTaxOre: toOre(fieldNumber(input.annualAccountsPayload, "aarsresultat/aarets")),
    equityOre,
    availableDistributionOre: Math.max(0, retainedEquityOre),
    cashOre,
  };
}

export function buildOwnerDividendReviewedFacts(input: {
  company: PersistedCorporateCompany;
  shareholders: PersistedCorporateShareholder[];
  annualBasis: ApprovedAnnualCorporateBasis;
}): ReviewedCorporateFacts {
  const shareholders = [...input.shareholders]
    .sort((left, right) => left.order - right.order || left.id.localeCompare(right.id, "en"))
    .map((shareholder) => ({
      shareholderId: shareholder.id,
      name: shareholder.name,
      shareCount: shareholder.shareCount,
    }));
  return {
    organizationNumber: input.company.organizationNumber,
    legalName: input.company.legalName,
    shareholders,
    totalCompanyShares: shareholders.reduce((sum, shareholder) => sum + shareholder.shareCount, 0),
    availableDistributionOre: input.annualBasis.availableDistributionOre,
    annualDataHash: input.annualBasis.annualDataHash,
    annualAccountsPayloadHash: input.annualBasis.annualAccountsPayloadHash,
  };
}
