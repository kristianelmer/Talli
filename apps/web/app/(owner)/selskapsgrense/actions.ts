"use server";

import { randomUUID } from "node:crypto";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import type { EligibilityAnswer } from "../../../features/company-access/index.ts";
import {
  eligibilityActionErrorMessage,
  recheckCompanyYearEligibilityThroughApi,
} from "../../../features/company-access/index.ts";
import { listCompanyAccessContexts } from "../../lib/company-access-context";
import { getCurrentSessionAccessToken } from "../../lib/supabase/auth-session";

function formString(formData: FormData, key: string) {
  const value = formData.get(key);
  return typeof value === "string" ? value.trim() : "";
}

function recheckTarget(companyId: string, parameter: "error" | "result", value: string) {
  const search = new URLSearchParams({ companyId, [parameter]: value });
  return `/selskapsgrense?${search.toString()}`;
}

export async function recheckMaterialCompanyYearAnswers(formData: FormData) {
  const companyId = formString(formData, "companyId");
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu.test(companyId)) {
    redirect(recheckTarget("", "error", "Selskapet kunne ikke kontrolleres."));
  }
  const questionCodes = formData.getAll("questionCode").filter(
    (value): value is string => (
      typeof value === "string" && /^[a-z0-9_]{1,100}$/u.test(value)
    ),
  );
  if (
    questionCodes.length === 0
    || questionCodes.length > 64
    || questionCodes.length !== new Set(questionCodes).size
  ) {
    redirect(recheckTarget(companyId, "error", "Spørsmålene er endret. Last siden på nytt."));
  }
  const rawAnswers = Object.fromEntries(
    questionCodes.map((code) => [code, formString(formData, `answer:${code}`)]),
  );
  if (Object.values(rawAnswers).some((answer) => !["yes", "no", "unknown"].includes(answer))) {
    redirect(recheckTarget(companyId, "error", "Svar på alle spørsmålene før du fortsetter."));
  }
  const accessToken = await getCurrentSessionAccessToken();
  if (!accessToken) redirect("/login?next=%2Fselskapsgrense");
  const { companies, error } = await listCompanyAccessContexts({ companyId });
  const company = companies.find((candidate) => candidate.id === companyId);
  if (
    error
    || !company
    || company.companyYearAdmissionId === null
    || company.admittedAccountingYear === null
  ) {
    redirect(recheckTarget(companyId, "error", "Selskapsåret kunne ikke kontrolleres nå."));
  }

  let decision: "supported" | "clarify" | "blocked";
  try {
    const state = await recheckCompanyYearEligibilityThroughApi(
      accessToken,
      company.companyYearAdmissionId,
      {
        operationId: randomUUID(),
        trigger: "material_answer_changed",
        answers: rawAnswers as Record<string, EligibilityAnswer>,
      },
      randomUUID(),
    );
    decision = state.decision;
  } catch (caught) {
    redirect(recheckTarget(companyId, "error", eligibilityActionErrorMessage(caught)));
  }
  revalidatePath("/");
  redirect(recheckTarget(companyId, "result", decision));
}
