import { AnnualWorkspaceRecovery } from "../../../../../components/annual-workspace/AnnualWorkspaceRecovery";
import { notFound } from "next/navigation";

import { ObligationWorkspace } from "../../../../../components/annual-workspace/ObligationWorkspace";
import { validateAuthorityObligation } from "../../../../../lib/authority-permission";
import { loadAnnualWorkspace } from "../../../../../lib/annual-workspace-server";

export default async function ObligationPage({
  params,
}: {
  params: Promise<{ companyId: string; incomeYear: string; obligation: string }>;
}) {
  const { companyId, incomeYear, obligation: rawObligation } = await params;
  let obligation;
  try {
    obligation = validateAuthorityObligation(rawObligation);
  } catch {
    notFound();
  }
  const loaded = await loadAnnualWorkspace({ companyId, incomeYear: Number(incomeYear) });
  if (loaded.status === "unavailable") return <AnnualWorkspaceRecovery context={loaded.context} />;
  return <ObligationWorkspace model={loaded.model} obligation={obligation} records={loaded.records} />;
}
