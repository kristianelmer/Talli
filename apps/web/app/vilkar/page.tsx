import type { Metadata } from "next";

import { LegalPage } from "../components/LegalPage";
import { ownerCopy } from "../lib/copy";
import { currentCustomerAgreements } from "../lib/customer-agreements";

export const metadata: Metadata = {
  title: "Brukervilkår for bedriftskunder – Talli",
  description: "Talli Business Terms for bedriftskunder.",
  alternates: { canonical: "/vilkar" },
};

export default function VilkarPage() {
  const terms = currentCustomerAgreements.businessTerms;
  return (
    <LegalPage
      doc={ownerCopy.legal.terms}
      version={terms.version}
      effectiveDate={terms.effectiveDate}
    />
  );
}
