"use server";

import { randomUUID } from "node:crypto";

import type {
  EligibilityAnswer,
  EligibilityDecisionResponse,
} from "../../features/company-access";
import {
  assessCompanyEligibility,
  eligibilityActionErrorMessage,
  precheckCompanyEligibility,
} from "../../features/company-access";
import {
  clearEligibilityContinuation,
  eligibilityContinuationFromResult,
  setEligibilityContinuation,
} from "../lib/eligibility-continuation";

export type EligibilityActionState = {
  result?: EligibilityDecisionResponse;
  error?: string;
};

function formString(formData: FormData, key: string) {
  const value = formData.get(key);
  return typeof value === "string" ? value.trim() : "";
}

function accountingYear(formData: FormData): 2025 | 2026 | null {
  const year = Number(formString(formData, "accountingYear") || "2026");
  return year === 2025 || year === 2026 ? year : null;
}

export async function precheckEligibilityAction(
  _state: EligibilityActionState,
  formData: FormData,
): Promise<EligibilityActionState> {
  await clearEligibilityContinuation();
  const orgNumber = formString(formData, "orgNumber");
  const year = accountingYear(formData);
  if (year === null) return { error: "Velg selskapsåret 2025 eller 2026." };
  if (!/^\d{9}$/u.test(orgNumber)) {
    return { error: "Organisasjonsnummeret må ha ni sifre." };
  }
  try {
    return {
      result: await precheckCompanyEligibility(
        { orgNumber, accountingYear: year },
        randomUUID(),
      ),
    };
  } catch (error) {
    return { error: eligibilityActionErrorMessage(error) };
  }
}

export async function definitiveEligibilityAction(
  _state: EligibilityActionState,
  formData: FormData,
): Promise<EligibilityActionState> {
  await clearEligibilityContinuation();
  const year = accountingYear(formData);
  if (year === null) return { error: "Velg selskapsåret 2025 eller 2026." };
  const questionCodes = formData.getAll("questionCode").filter(
    (value): value is string => typeof value === "string" && /^[a-z0-9_]{1,100}$/u.test(value),
  );
  if (questionCodes.length === 0 || questionCodes.length !== new Set(questionCodes).size) {
    return { error: "Spørsmålene er endret. Start sjekken på nytt." };
  }
  const rawAnswers = Object.fromEntries(
    questionCodes.map((code) => [code, formString(formData, `answer:${code}`)]),
  );
  if (Object.values(rawAnswers).some((answer) => !["yes", "no", "unknown"].includes(answer))) {
    return { error: "Svar på spørsmålet før du fortsetter." };
  }
  const answers = rawAnswers as Record<string, EligibilityAnswer>;
  try {
    const result = await assessCompanyEligibility({
      orgNumber: formString(formData, "orgNumber"),
      accountingYear: year,
      expectedPublicFactsSha256: formString(formData, "publicFactsSha256"),
      capabilityManifestVersion: formString(formData, "capabilityManifestVersion"),
      capabilityManifestSha256: formString(formData, "capabilityManifestSha256"),
      answers,
    }, randomUUID());
    const continuation = eligibilityContinuationFromResult(result);
    if (continuation) await setEligibilityContinuation(continuation);
    return { result };
  } catch (error) {
    return { error: eligibilityActionErrorMessage(error) };
  }
}
