import { AnnualWorkspaceRecovery } from "../../../../components/annual-workspace/AnnualWorkspaceRecovery";
import type { ReactNode } from "react";

import { AnnualWorkspaceShell } from "../../../../components/annual-workspace/AnnualWorkspaceShell";
import { loadAnnualWorkspace } from "../../../../lib/annual-workspace-server";

export default async function AnnualReportingLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ companyId: string; incomeYear: string }>;
}) {
  const { companyId, incomeYear } = await params;
  const loaded = await loadAnnualWorkspace({ companyId, incomeYear: Number(incomeYear) });
  if (loaded.status === "unavailable") return <AnnualWorkspaceRecovery context={loaded.context} />;
  return <AnnualWorkspaceShell model={loaded.model}>{children}</AnnualWorkspaceShell>;
}
