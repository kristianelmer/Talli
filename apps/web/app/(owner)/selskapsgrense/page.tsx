import { randomUUID } from "node:crypto";
import Link from "next/link";
import { redirect } from "next/navigation";

import {
  eligibilityActionErrorMessage,
  precheckCompanyEligibility,
} from "../../../features/company-access/index.ts";
import { Banner } from "../../components/ui";
import { listCompanyAccessContexts } from "../../lib/company-access-context";
import { refreshCompanyYearEligibilityGate } from "../../actions";
import { EligibilityInterview } from "../../sjekk-selskapet/EligibilityChecker";
import styles from "../../sjekk-selskapet/eligibility.module.css";
import { recheckMaterialCompanyYearAnswers } from "./actions";

type CompanyYearBoundaryProps = {
  searchParams?: Promise<{ companyId?: string; error?: string; result?: string }>;
};

export default async function CompanyYearBoundaryPage({
  searchParams,
}: CompanyYearBoundaryProps) {
  const params = await searchParams;
  const { companies, error: contextError } = await listCompanyAccessContexts();
  const admittedCompanies = companies.filter((company) => (
    company.companyYearAdmissionId !== null
    && company.admittedAccountingYear !== null
  ));
  if (admittedCompanies.length === 0 && !contextError) redirect("/sjekk-selskapet");
  const selectedCompany = admittedCompanies.find(
    (company) => company.id === params?.companyId,
  ) ?? admittedCompanies[0];

  if (contextError || !selectedCompany || selectedCompany.admittedAccountingYear === null) {
    return (
      <section className="band" role="alert">
        <h1>Talli kunne ikke åpne selskapsgrensen</h1>
        <p>Ingen opplysninger eller status ble endret. Prøv igjen senere.</p>
      </section>
    );
  }

  let precheck;
  let providerError: string | null = null;
  try {
    precheck = await precheckCompanyEligibility({
      orgNumber: selectedCompany.org_number,
      accountingYear: selectedCompany.admittedAccountingYear,
    }, randomUUID());
  } catch (error) {
    providerError = eligibilityActionErrorMessage(error);
  }

  return (
    <section className={styles.shell} aria-labelledby="company-year-boundary-title">
      <p className={styles.eyebrow}>Selskapsgrense · {selectedCompany.admittedAccountingYear}</p>
      <h1 id="company-year-boundary-title">Har opplysningene for {selectedCompany.name} endret seg?</h1>
      <p>
        Svar på nytt når aktivitet, eiere, investeringer, lån eller andre vesentlige
        forhold er endret. Talli lagrer svaret som den gjeldende grensen for selskapsåret.
      </p>
      {admittedCompanies.length > 1 ? (
        <nav aria-label="Velg selskap">
          {admittedCompanies.map((company) => (
            <Link key={company.id} href={`/selskapsgrense?companyId=${company.id}`}>
              {company.name}
            </Link>
          ))}
        </nav>
      ) : null}
      {params?.error ? (
        <Banner variant="danger" title="Talli kunne ikke kontrollere selskapsgrensen">
          {params.error} Ingen opplysninger eller status ble endret.
        </Banner>
      ) : null}
      {params?.result === "supported" ? (
        <Banner variant="success" title="Selskapsgrensen er kontrollert">
          Opplysningene er fortsatt innenfor grensen.
        </Banner>
      ) : ["clarify", "blocked", "stopped"].includes(params?.result ?? "") ? (
        <Banner variant="danger" title="Selskapsgrensen må avklares">
          Den gjeldende grensen er lagret. Se den konkrete forklaringen og neste handling øverst på siden.
        </Banner>
      ) : null}
      {providerError ? (
        <Banner variant="danger" title="Talli kunne ikke hente offentlige opplysninger">
          {providerError} Ingen opplysninger eller status ble endret.
        </Banner>
      ) : precheck?.questions.length ? (
        <EligibilityInterview
          precheck={precheck}
          definitiveAction={recheckMaterialCompanyYearAnswers}
          submitLabel="Oppdater selskapsgrensen"
          companyId={selectedCompany.id}
        />
      ) : precheck ? (
        <div>
          <Banner variant="danger" title="Offentlige opplysninger må kontrolleres">
            {precheck.reasonExplanations.join(" ") || precheck.nextStep}
          </Banner>
          <form action={refreshCompanyYearEligibilityGate}>
            <input type="hidden" name="companyId" value={selectedCompany.id} />
            <input type="hidden" name="trigger" value="public_fact_changed" />
            <button className="btn btn--primary" type="submit">Kontroller offentlige opplysninger</button>
          </form>
        </div>
      ) : null}
    </section>
  );
}
