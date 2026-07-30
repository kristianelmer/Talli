"use client";

import Link from "next/link";

import { currentCustomerAgreements } from "../lib/customer-agreements";
import { ownerCopy } from "../lib/copy";

export function CustomerAgreementAcceptanceFields() {
  return (
    <>
      <input
        name="businessTermsVersion"
        type="hidden"
        value={currentCustomerAgreements.businessTerms.version}
      />
      <input
        name="businessTermsSha256"
        type="hidden"
        value={currentCustomerAgreements.businessTerms.contentSha256}
      />
      <input
        name="dpaVersion"
        type="hidden"
        value={currentCustomerAgreements.dpa.version}
      />
      <input
        name="dpaSha256"
        type="hidden"
        value={currentCustomerAgreements.dpa.contentSha256}
      />
      <div className="checkboxLabel">
        <input
          id="agreementAccepted"
          name="agreementAccepted"
          type="checkbox"
          value="accepted"
          aria-describedby="agreementAcceptedDescription"
          required
        />
        <p id="agreementAcceptedDescription">
          <label htmlFor="agreementAccepted">
            {ownerCopy.workspace.agreementAcceptance.authority}{" "}
          </label>
          <Link href="/vilkar">{ownerCopy.workspace.agreementAcceptance.businessTerms}</Link>{" "}
          {ownerCopy.workspace.agreementAcceptance.conjunction}{" "}
          <Link href="/databehandleravtale">{ownerCopy.workspace.agreementAcceptance.dpa}</Link>
        </p>
      </div>
    </>
  );
}
