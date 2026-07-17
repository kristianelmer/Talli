import type { Metadata } from "next";

import { LegalPage } from "../components/LegalPage";
import { ownerCopy } from "../lib/copy";
import { currentCustomerAgreements } from "../lib/customer-agreements";

export const metadata: Metadata = {
  title: "Databehandleravtale – Talli",
  description: "Databehandleravtale for Talli bedriftskunder.",
};

export default function DatabehandleravtalePage() {
  const dpa = currentCustomerAgreements.dpa;
  return (
    <LegalPage doc={ownerCopy.legal.dpa} version={dpa.version} effectiveDate={dpa.effectiveDate} />
  );
}
