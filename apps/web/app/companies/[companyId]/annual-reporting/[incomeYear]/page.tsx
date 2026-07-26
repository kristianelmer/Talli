import { AnnualOverview } from "../../../../components/annual-workspace/AnnualOverview";
import { loadAnnualWorkspace } from "../../../../lib/annual-workspace-server";

export default async function AnnualReportingPage({
  params,
}: {
  params: Promise<{ companyId: string; incomeYear: string }>;
}) {
  const { companyId, incomeYear } = await params;
  const loaded = await loadAnnualWorkspace({ companyId, incomeYear: Number(incomeYear) });
  return <AnnualOverview model={loaded.model} />;
}
