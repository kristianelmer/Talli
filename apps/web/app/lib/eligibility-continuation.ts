import { cookies } from "next/headers";

import type {
  EligibilityAnswer,
  EligibilityDecisionResponse,
} from "../../features/company-access";

export const ELIGIBILITY_CONTINUATION_COOKIE = "talli_company_year_eligibility";

export type EligibilityContinuation = {
  orgNumber: string;
  companyName: string;
  accountingYear: number;
  publicFactsSha256: string;
  capabilityManifestVersion: string;
  capabilityManifestSha256: string;
  answers: Record<string, EligibilityAnswer>;
  answersSha256: string;
  reconstructFrom: string;
  onlyAccountingAndFilingProduct: true;
  customerClaims: string[];
};

function isSha256(value: unknown): value is string {
  return typeof value === "string" && /^[a-f0-9]{64}$/u.test(value);
}

function isAnswerMap(value: unknown): value is Record<string, EligibilityAnswer> {
  return typeof value === "object"
    && value !== null
    && Object.keys(value).length > 0
    && Object.values(value).every((answer) => ["yes", "no", "unknown"].includes(String(answer)));
}

function parseEligibilityContinuation(value: string): EligibilityContinuation | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null) return null;
  const candidate = parsed as Record<string, unknown>;
  if (
    Object.keys(candidate).sort().join(",")
      !== "accountingYear,answers,answersSha256,capabilityManifestSha256,capabilityManifestVersion,companyName,customerClaims,onlyAccountingAndFilingProduct,orgNumber,publicFactsSha256,reconstructFrom"
    || typeof candidate.orgNumber !== "string"
    || !/^\d{9}$/u.test(candidate.orgNumber)
    || typeof candidate.companyName !== "string"
    || !candidate.companyName
    || candidate.accountingYear !== 2026
    || !isSha256(candidate.publicFactsSha256)
    || candidate.capabilityManifestVersion !== "2026.1"
    || !isSha256(candidate.capabilityManifestSha256)
    || !isAnswerMap(candidate.answers)
    || !isSha256(candidate.answersSha256)
    || candidate.reconstructFrom !== "2026-01-01"
    || candidate.onlyAccountingAndFilingProduct !== true
    || !Array.isArray(candidate.customerClaims)
    || candidate.customerClaims.length !== 12
    || !candidate.customerClaims.every(
      (claim) => typeof claim === "string" && claim.length > 0 && claim.length <= 160,
    )
  ) {
    return null;
  }
  return candidate as EligibilityContinuation;
}

export function eligibilityContinuationFromResult(
  result: EligibilityDecisionResponse,
): EligibilityContinuation | null {
  if (
    result.provisional
    || result.decision !== "supported"
    || result.answersSha256 === null
    || result.companyYearPromise === null
  ) {
    return null;
  }
  return {
    orgNumber: result.publicFacts.orgNumber,
    companyName: result.publicFacts.name,
    accountingYear: result.accountingYear,
    publicFactsSha256: result.publicFactsSha256,
    capabilityManifestVersion: result.capabilityManifestVersion,
    capabilityManifestSha256: result.capabilityManifestSha256,
    answers: result.answers,
    answersSha256: result.answersSha256,
    reconstructFrom: result.companyYearPromise.reconstructionRequiredFrom,
    onlyAccountingAndFilingProduct:
      result.companyYearPromise.onlyAccountingAndFilingProduct,
    customerClaims: result.companyYearPromise.customerClaims,
  };
}

export async function setEligibilityContinuation(
  continuation: EligibilityContinuation,
) {
  const cookieStore = await cookies();
  cookieStore.set(ELIGIBILITY_CONTINUATION_COOKIE, JSON.stringify(continuation), {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 30 * 60,
    priority: "high",
  });
}

export async function readEligibilityContinuation() {
  const cookieStore = await cookies();
  const value = cookieStore.get(ELIGIBILITY_CONTINUATION_COOKIE)?.value;
  return value ? parseEligibilityContinuation(value) : null;
}

export async function clearEligibilityContinuation() {
  const cookieStore = await cookies();
  cookieStore.delete(ELIGIBILITY_CONTINUATION_COOKIE);
}
