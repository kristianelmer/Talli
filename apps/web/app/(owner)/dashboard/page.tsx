import { redirect } from "next/navigation";

import { annualOverviewHref } from "../../lib/annual-workspace";
import { loadWorkspaceData } from "../../lib/workspace-data";

type DashboardProps = {
  searchParams?: Promise<{ agreement?: string }>;
};

export default async function DashboardPage({ searchParams }: DashboardProps) {
  const params = await searchParams;
  if (params?.agreement === "required") {
    return (
      <section className="dataPanel widePanel" role="status">
        <h1>Avtalen må godkjennes av en eier</h1>
        <p>
          Årsrapporteringen er stengt til en selskapseier har godtatt gjeldende avtaler.
          Be en eier logge inn og fullføre avtaleaksepten.
        </p>
      </section>
    );
  }

  const { companies, primaryCompanyId, primaryIncomeYear } = await loadWorkspaceData();
  const primaryCompany =
    companies.find((company) => company.id === primaryCompanyId) ?? companies[0];

  if (!primaryCompany) {
    redirect("/onboarding");
  }

  redirect(annualOverviewHref({
    companyId: primaryCompany.id,
    incomeYear: primaryIncomeYear,
  }));
}
