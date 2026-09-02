import Link from "next/link";

import type { EligibilityContinuation } from "../../lib/eligibility-continuation";
import { currentCustomerAgreements, currentPrivacyNotice } from "../../lib/customer-agreements";
import { Banner, SubmitButton } from "../../components/ui";
import { admitCompanyYear } from "./actions";

export function CompanyYearAdmissionForm({
  continuation,
}: {
  continuation: EligibilityContinuation;
}) {
  return (
    <form action={admitCompanyYear} className="wizardForm">
      <input type="hidden" name="businessTermsVersion" value={currentCustomerAgreements.businessTerms.version} />
      <input type="hidden" name="businessTermsSha256" value={currentCustomerAgreements.businessTerms.contentSha256} />
      <input type="hidden" name="dpaVersion" value={currentCustomerAgreements.dpa.version} />
      <input type="hidden" name="dpaSha256" value={currentCustomerAgreements.dpa.contentSha256} />
      <input type="hidden" name="privacyNoticeVersion" value={currentPrivacyNotice.version} />
      <input type="hidden" name="privacyNoticeSha256" value={currentPrivacyNotice.contentSha256} />
      <input type="hidden" name="capabilityManifestVersion" value={continuation.capabilityManifestVersion} />
      <input type="hidden" name="capabilityManifestSha256" value={continuation.capabilityManifestSha256} />
      <Banner variant="success" title="Selskapet passer for Talli">
        {continuation.companyName} · {continuation.orgNumber}
      </Banner>
      <p>
        Du tar inn hele selskapsåret {continuation.accountingYear}. Alt bygges opp fra
        1. januar. Tidligere år er ikke med.
      </p>
      <ul aria-label="Dette er med i selskapsåret">
        {continuation.customerClaims.map((claim) => <li key={claim}>{claim}</li>)}
      </ul>
      {continuation.onlyAccountingAndFilingProduct ? (
        <p>Talli skal være det eneste regnskaps- og innsendingsproduktet for dette året.</p>
      ) : null}
      <p>
        Hvis nye opplysninger senere faller utenfor grensen, lagrer Talli at
        selskapsgrensen må avklares, forklarer neste steg og beholder leseadgangen.
        Ferdige arkiver kan fortsatt eksporteres fra arbeidsflaten.
      </p>
      <div className="checkboxLabel">
        <input
          id="companyYearPromiseAccepted"
          name="companyYearPromiseAccepted"
          type="checkbox"
          value="accepted"
          required
          aria-describedby="companyYearPromiseDescription"
        />
        <p id="companyYearPromiseDescription">
          <label htmlFor="companyYearPromiseAccepted">
            Jeg bekrefter at jeg har fullmakt til å inngå avtalen for selskapet og
            godtar den viste, komplette selskapsårsgrensen for {continuation.accountingYear},{" "}
          </label>
          <Link href="/vilkar">brukervilkårene</Link>,{" "}
          <Link href="/databehandleravtale">databehandleravtalen</Link> og{" "}
          <Link href="/personvern">personvernerklæringen</Link>.
        </p>
      </div>
      <SubmitButton block pendingLabel="Oppretter selskapsåret…">
        Godta og opprett selskapsåret
      </SubmitButton>
    </form>
  );
}
