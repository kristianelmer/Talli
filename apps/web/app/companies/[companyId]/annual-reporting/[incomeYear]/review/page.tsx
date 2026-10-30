import { AnnualWorkspaceRecovery } from "../../../../../components/annual-workspace/AnnualWorkspaceRecovery";
import { SubmissionReview } from "../../../../../components/annual-workspace/SubmissionReview";
import { loadAnnualWorkspace } from "../../../../../lib/annual-workspace-server";

export default async function AnnualReviewPage({
  params,
}: {
  params: Promise<{ companyId: string; incomeYear: string }>;
}) {
  const { companyId, incomeYear } = await params;
  const loaded = await loadAnnualWorkspace({ companyId, incomeYear: Number(incomeYear) });
  if (loaded.status === "unavailable") return <AnnualWorkspaceRecovery context={loaded.context} />;
  return (
    <SubmissionReview
      billingEntitlement={loaded.billingEntitlement}
      model={loaded.model}
      records={loaded.records}
    />
  );
}
