"use server";

import { revalidatePath } from "next/cache";
import { loadBillingEntitlement } from "../../../../../features/billing";
import { approveRf1086SourceProduction, prepareRf1086SourceProductionReview, loadRf1086Workspaces,
  rf1086ActionErrorMessage, type RfSourceProductionApprovalCommandWire,
  type RfSourceProductionReviewWire, type Rf1086RecordedResultWire } from "../../../../../features/shareholder-register-filing";
import { getCurrentSessionAccessToken } from "../../../../lib/supabase/auth-session";

export type PriorFiling = { submissionId: string; manifestSha256: string; createdAt: string; status: string };
type Result<T> = { ok: true; value: T } | { ok: false; message: string };
const uuid = (value: unknown): value is string => typeof value === "string"
  && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);

export async function reviewSourceProductionAction(input: { companyId: string; incomeYear: number;
  previewId: string; sourceId: string; sourceSha256: string }): Promise<Result<{ review: RfSourceProductionReviewWire; priorFilings: PriorFiling[] }>> {
  if (!input || !uuid(input.companyId) || !uuid(input.previewId) || !uuid(input.sourceId)
      || !Number.isInteger(input.incomeYear) || input.incomeYear < 2000 || input.incomeYear > 2100
      || !/^[a-f0-9]{64}$/.test(input.sourceSha256)) return { ok: false, message: "Kontroller lagret årsgrunnlag og forhåndsvisning." };
  try {
    const token = await getCurrentSessionAccessToken();
    if (!token) return { ok: false, message: "Logg inn på nytt for å fortsette." };
    const entitlement = await loadBillingEntitlement(token, { companyId: input.companyId, incomeYear: input.incomeYear,
      obligation: "aksjonaerregisteroppgaven", caseProfile: "rf1086_full_year_v1" });
    if (entitlement.companyId !== input.companyId || entitlement.incomeYear !== input.incomeYear
        || entitlement.obligation !== "aksjonaerregisteroppgaven" || !entitlement.allowed || !entitlement.pilotEntitlementId) {
      return { ok: false, message: "Godkjenning krever en aktiv pilotavtale for dette selskapet og inntektsåret." };
    }
    const [review, [workspace]] = await Promise.all([
      prepareRf1086SourceProductionReview(token, { companyId: input.companyId, incomeYear: input.incomeYear,
        previewId: input.previewId, entitlementId: entitlement.pilotEntitlementId }, input.sourceId, input.sourceSha256),
      loadRf1086Workspaces(token, [input.companyId], input.incomeYear),
    ]);
    const priorFilings = workspace.productionSubmissions.map(submission => {
      const approval = workspace.approvals.find(row => row.id === submission.approvalId);
      if (!approval) throw new Error("Missing retained approval");
      return { submissionId: submission.id, manifestSha256: approval.manifestHash,
        createdAt: submission.createdAt, status: submission.feedbackState };
    });
    return { ok: true, value: { review, priorFilings } };
  } catch (error) { return { ok: false, message: rf1086ActionErrorMessage(error) }; }
}

export async function approveSourceProductionAction(command: RfSourceProductionApprovalCommandWire): Promise<Result<Rf1086RecordedResultWire>> {
  try {
    const token = await getCurrentSessionAccessToken();
    if (!token) return { ok: false, message: "Logg inn på nytt for å fortsette." };
    const value = await approveRf1086SourceProduction(token, command);
    revalidatePath("/filing/aksjonaerregisteroppgaven");
    return { ok: true, value };
  } catch (error) { return { ok: false, message: rf1086ActionErrorMessage(error) }; }
}
