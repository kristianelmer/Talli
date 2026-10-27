"use server";

import {revalidatePath} from "next/cache";
import {redirect} from "next/navigation";
import {getCurrentSessionAccessToken} from "../../lib/supabase/auth-session";
import {loadAccountsDeliveryWorkspace,prepareAccountsDelivery,reviewAccountsDelivery,advanceAccountsDelivery,
  reconcileAccountsDelivery,annualAccountsActionErrorMessage} from "../../../features/annual-accounts-filing";

const target="/filing/aarsregnskap";
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u;
class AccountsInputError extends Error {}

export async function accountsDeliveryOwnerAction(form: FormData) {
  const token=await getCurrentSessionAccessToken();
  if (!token) redirect("/login?next=%2Ffiling%2Faarsregnskap");
  try {
    const companyId=String(form.get("companyId") ?? "");const incomeYear=Number(form.get("incomeYear"));
    if (!uuid.test(companyId) || String(form.get("incomeYear"))!=="2025") throw new AccountsInputError("Ugyldig selskap eller inntektsår.");
    const workspace=await loadAccountsDeliveryWorkspace(token,companyId,incomeYear);
    const action=String(form.get("deliveryAction") ?? "");
    if (action==="prepare") {
      const filingId=String(form.get("candidateId") ?? "");
      if (!workspace.preparationAvailable || !uuid.test(filingId)) throw new AccountsInputError("Et nytt utkast er ikke tilgjengelig nå.");
      await prepareAccountsDelivery(token,{companyId,incomeYear,filingId,contactEmail:String(form.get("contactEmail") ?? ""),
        confirmingRepresentative:String(form.get("confirmingRepresentative") ?? "")},"accounts-prepare-"+filingId);
    } else {
      const row=workspace.rows.find(row=>row.filingId===form.get("filingId"));const allowed=row?.actions.find(value=>value===action);
      if (!row || !allowed) throw new AccountsInputError("Steget er ikke tilgjengelig. Oppdater siden for gjeldende status.");
      const scope={companyId,incomeYear,filingId:row.filingId,draftSha256:row.draftSha256};
      if (allowed==="review_prepare" || allowed==="review_confirm" || allowed==="review_sign") {
        if (form.get("documentsChecked")!=="on" || form.get("actionConfirmed")!=="on") throw new AccountsInputError("Bekreft dokumentene og det valgte steget.");
        if (form.get("reviewSha256")!==row.reviewSha256) throw new AccountsInputError("Dokumentene er endret. Les dem på nytt.");
        await reviewAccountsDelivery(token,{...scope,stage:row.reviewStage,reviewedEvidenceSha256:row.reviewSha256,
          documentsChecked:true,actionConfirmed:true},"accounts-review-"+row.filingId+"-"+row.reviewStage);
      } else if (allowed==="reconcile") await reconcileAccountsDelivery(token,scope);
      else await advanceAccountsDelivery(token,{...scope,action:allowed});
    }
  } catch (error) {
    const message=error instanceof AccountsInputError?error.message:annualAccountsActionErrorMessage(error);
    redirect(target+"?error="+encodeURIComponent(message));
  }
  revalidatePath(target);redirect(target);
}
