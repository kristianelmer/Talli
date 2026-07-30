import { redirect } from "next/navigation";
import Link from "next/link";

import { reacceptCompanyAgreement, signOut } from "../actions";
import { currentCustomerAgreements } from "../lib/customer-agreements";
import { companiesRequiringCurrentCustomerAgreement } from "../lib/customer-agreement-reacceptance";
import {
  getOperatorContext,
  listCustomerAgreementAcceptances,
  needsEmailVerification,
} from "../lib/supabase/server";
import { listCompanyAccessContexts } from "../lib/company-access-context";
import { ownerCopy } from "../lib/copy";
import { AppNav } from "./AppNav";

export default async function OwnerLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const { user, isOperator } = await getOperatorContext();
  if (!user) {
    redirect("/login");
  }
  if (needsEmailVerification(user)) {
    redirect("/verify-email");
  }
  const { companies, error: companiesError } = await listCompanyAccessContexts();
  const { acceptances, error: acceptancesError } = companiesError
    ? { acceptances: [], error: null }
    : await listCustomerAgreementAcceptances(companies.map(({ id }) => id));
  const agreementDataError = companiesError ?? acceptancesError;
  const pendingCompanies = companiesRequiringCurrentCustomerAgreement(companies, acceptances);
  const pendingCompany = pendingCompanies[0];
  return (
    <div className="appShell">
      <header className="appTopbar">
        <div className="appBrand">
          <span className="appBrandMark" aria-hidden="true" />
          <span>{ownerCopy.brand}</span>
        </div>
        <AppNav isOperator={isOperator}>
          <span className="appUserEmail">{user.email}</span>
          <form action={signOut}>
            <button className="btn btn--ghost" type="submit">
              {ownerCopy.nav.signOut}
            </button>
          </form>
        </AppNav>
      </header>
      <main className="appMain">
        {agreementDataError ? (
          <section className="band" role="alert">
            <h1>Kunne ikke kontrollere gjeldende avtaleaksept</h1>
            <p>Arbeidsflaten er midlertidig stengt. Prøv igjen senere.</p>
          </section>
        ) : pendingCompany ? (
          <section className="band" aria-labelledby="agreementReacceptanceTitle">
            <div className="sectionHeader">
              <p className="eyebrow">Oppdaterte avtaler</p>
              <h1 id="agreementReacceptanceTitle">Godta gjeldende avtaler for {pendingCompany.name}</h1>
              <p>Du må bekrefte gjeldende avtaleversjoner før du kan fortsette i arbeidsflaten.</p>
            </div>
            <form className="dataPanel formPanel widePanel" action={reacceptCompanyAgreement}>
              <input name="returnTo" type="hidden" value="/dashboard" />
              <input name="companyId" type="hidden" value={pendingCompany.id} />
              <input name="businessTermsVersion" type="hidden" value={currentCustomerAgreements.businessTerms.version} />
              <input name="businessTermsSha256" type="hidden" value={currentCustomerAgreements.businessTerms.contentSha256} />
              <input name="dpaVersion" type="hidden" value={currentCustomerAgreements.dpa.version} />
              <input name="dpaSha256" type="hidden" value={currentCustomerAgreements.dpa.contentSha256} />
              <div className="checkboxLabel">
                <input
                  id="reacceptAgreementAccepted"
                  name="agreementAccepted"
                  type="checkbox"
                  value="accepted"
                  aria-describedby="reacceptAgreementDescription"
                  required
                />
                <p id="reacceptAgreementDescription">
                  <label htmlFor="reacceptAgreementAccepted">
                    {ownerCopy.workspace.agreementAcceptance.authority}{" "}
                  </label>
                  <Link href="/vilkar">{ownerCopy.workspace.agreementAcceptance.businessTerms}</Link>{" "}
                  {ownerCopy.workspace.agreementAcceptance.conjunction}{" "}
                  <Link href="/databehandleravtale">{ownerCopy.workspace.agreementAcceptance.dpa}</Link>
                </p>
              </div>
              <button className="primaryButton" type="submit">Godta og fortsett</button>
            </form>
            {pendingCompanies.length > 1 ? (
              <p>Deretter gjenstår: {pendingCompanies.slice(1).map(({ name }) => name).join(", ")}.</p>
            ) : null}
          </section>
        ) : children}
      </main>
    </div>
  );
}
