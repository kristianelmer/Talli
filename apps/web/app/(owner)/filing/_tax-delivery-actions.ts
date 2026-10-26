"use server";

import {revalidatePath} from "next/cache";
import {redirect} from "next/navigation";
import {getCurrentSessionAccessToken} from "../../lib/supabase/auth-session";
import {loadTaxDeliveryWorkspace,loadTaxDeliveryOwnerReview,prepareTaxDeliveryDraft,prepareTaxDeliveryCorrection,
  approveTaxDeliveryDraft,confirmTaxDeliverySubmission,advanceTaxDeliveryAction,companyTaxActionErrorMessage} from "../../../features/company-tax-filing";

const target="/filing/skattemelding";
class TaxDeliveryInputError extends Error {}
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u;

export async function taxDeliveryOwnerAction(form: FormData) {
  const token=await getCurrentSessionAccessToken();
  if (!token) redirect("/login?next=%2Ffiling%2Fskattemelding");
  try {
    const companyId=String(form.get("companyId") ?? "");const incomeYear=Number(form.get("incomeYear"));
    if (!uuid.test(companyId) || String(form.get("incomeYear"))!=="2025") throw new TaxDeliveryInputError("Ugyldig selskap eller inntektsår.");
    const workspace=await loadTaxDeliveryWorkspace(token,companyId,incomeYear);
    const action=String(form.get("deliveryAction") ?? "");const candidateId=String(form.get("candidateId") ?? "");
    if (action==="prepare") {
      if (!workspace.preparationAvailable || !uuid.test(candidateId)) throw new TaxDeliveryInputError("Et nytt utkast er ikke tilgjengelig nå.");
      await prepareTaxDeliveryDraft(token,{companyId,incomeYear,filingId:candidateId},"tax-prepare-"+candidateId);
    } else {
      const row=workspace.rows.find(row=>row.filingId===form.get("filingId"));
      const allowed=row?.actions.find(code=>code===action);
      if (!row || !allowed) throw new TaxDeliveryInputError("Steget er ikke tilgjengelig. Oppdater siden for gjeldende status.");
      const key="tax-delivery-"+row.filingId+"-"+allowed;
      if (allowed==="approve") {
        await approveTaxDeliveryDraft(token,{companyId,incomeYear,filingId:row.filingId,draftSha256:row.draftSha256,reviewSha256:row.reviewSha256},key);
      } else {
        if (!row.approvalSha256) throw new TaxDeliveryInputError("Utkastet mangler bekreftet kontroll.");
        if (allowed==="prepare_correction") {
          if (!uuid.test(candidateId)) throw new TaxDeliveryInputError("Korrigeringen mangler en gyldig referanse.");
          await prepareTaxDeliveryCorrection(token,{companyId,incomeYear,filingId:candidateId,parentFilingId:row.filingId,
            parentDraftSha256:row.draftSha256,parentApprovalSha256:row.approvalSha256},"tax-correction-"+candidateId);
        } else if (allowed==="submit") {
          if (form.get("documentsConfirmed")!=="on" || form.get("warningsAcknowledged")!=="on") throw new TaxDeliveryInputError("Bekreft dokumentene og merknadene før du fortsetter.");
          const review=await loadTaxDeliveryOwnerReview(token,companyId,incomeYear,row.filingId,row.approvalSha256);
          if (form.get("ownerReviewSha256")!==review.artifactSha256) throw new TaxDeliveryInputError("Kontrollen er endret. Les den på nytt.");
          await confirmTaxDeliverySubmission(token,{companyId,incomeYear,filingId:row.filingId,approvalSha256:row.approvalSha256,
            ownerReviewSha256:review.artifactSha256,documentsConfirmed:true,warningsAcknowledged:true},key);
        } else {
          await advanceTaxDeliveryAction(token,allowed,{companyId,incomeYear,filingId:row.filingId,approvalSha256:row.approvalSha256},key);
        }
      }
    }
  } catch (error) {
    const message=error instanceof TaxDeliveryInputError?error.message:companyTaxActionErrorMessage(error);
    redirect(target+"?error="+encodeURIComponent(message || "Steget kunne ikke bekreftes. Oppdater siden for gjeldende status."));
  }
  revalidatePath(target);
  redirect(target);
}
