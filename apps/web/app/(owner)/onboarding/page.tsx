import { redirect } from "next/navigation";

import { Banner, WizardShell } from "../../components/ui";
import { ownerCopy } from "../../lib/copy";
import { readEligibilityContinuation } from "../../lib/eligibility-continuation";
import {
  selectOnboardingPhase,
  shouldRedirectReturningOwner,
} from "../../lib/onboarding-presentation";
import { loadWorkspaceData } from "../../lib/workspace-data";
import { BankImportForm } from "./BankImportForm";
import { CompanyYearAdmissionForm } from "./CompanyYearAdmissionForm";
import { OpeningBalanceForm } from "./OpeningBalanceForm";

type OnboardingProps = {
  searchParams?: Promise<{
    error?: string;
    bankImportOperationId?: string;
    newYearOperationId?: string;
    step?: string;
  }>;
};

export default async function OnboardingPage({ searchParams }: OnboardingProps) {
  const params = await searchParams;
  const data = await loadWorkspaceData();
  const { companies, primaryCompanyId, primaryIncomeYear, setups, transactions } =
    data;

  const primaryCompany =
    companies.find((company) => company.id === primaryCompanyId) ?? companies[0];
  const hasSetup = primaryCompany
    ? setups.some((setup) => setup.company_id === primaryCompany.id)
    : false;
  const eligibilityContinuation = await readEligibilityContinuation();
  const continuationAlreadyAdmitted = eligibilityContinuation
    ? companies.some((company) => (
        company.org_number === eligibilityContinuation.orgNumber
        && company.admittedAccountingYear === eligibilityContinuation.accountingYear
      ))
    : false;
  const pendingAdmission = continuationAlreadyAdmitted
    ? null
    : eligibilityContinuation;
  if (!primaryCompany && !pendingAdmission) {
    redirect("/sjekk-selskapet");
  }
  const presentation = {
    hasCompany: Boolean(primaryCompany) && pendingAdmission === null,
    hasSetup: pendingAdmission === null && hasSetup,
    hasError: Boolean(params?.error),
    step: params?.step,
  };

  // A returning, fully-onboarded owner goes straight to the dashboard.
  if (shouldRedirectReturningOwner(presentation)) {
    redirect("/dashboard");
  }

  const ob = ownerCopy.onboarding;
  const steps = [ob.steps.company, ob.steps.balances, ob.steps.bank];
  const year = primaryIncomeYear ?? new Date().getFullYear() - 1;

  const phase = selectOnboardingPhase(presentation);
  const current = phase === "lookup" ? 0 : phase === "balances" ? 1 : 2;
  const head =
    phase === "lookup" ? ob.lookup : phase === "balances" ? ob.balances : ob.bank;

  return (
    <WizardShell
      title={head.title}
      intro={head.intro}
      steps={steps}
      current={current}
    >
      {params?.error ? <Banner variant="danger">{params.error}</Banner> : null}

      {phase === "lookup" && pendingAdmission ? (
        <CompanyYearAdmissionForm continuation={pendingAdmission} />
      ) : null}
      {phase === "balances" && primaryCompany ? (
        <OpeningBalanceForm
          companyId={primaryCompany.id}
          incomeYear={year}
          operationId={params?.newYearOperationId}
        />
      ) : null}
      {phase === "bank" && primaryCompany ? (
        <BankImportForm
          companyId={primaryCompany.id}
          incomeYear={year}
          importedCount={transactions.length}
          retryOperationId={params?.bankImportOperationId}
        />
      ) : null}
    </WizardShell>
  );
}
