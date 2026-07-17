import { createHash } from "node:crypto";

import { ownerCopy } from "./copy.ts";

export const customerAgreementAuthorityStatementVersion = "authority-v1" as const;

type ContractContent = {
  title: string;
  intro: string;
  sections: readonly {
    heading: string;
    body: readonly string[];
    bullets: readonly string[];
  }[];
};

function contractDocument(
  kind: "business_terms" | "dpa",
  path: "/vilkar" | "/databehandleravtale",
  content: ContractContent,
) {
  const canonical = JSON.stringify(content);
  return {
    kind,
    version: "2026-07-17",
    effectiveDate: "2026-07-17",
    path,
    contentSha256: createHash("sha256").update(canonical, "utf8").digest("hex"),
  } as const;
}

export const currentCustomerAgreements = {
  businessTerms: contractDocument("business_terms", "/vilkar", ownerCopy.legal.terms),
  dpa: contractDocument("dpa", "/databehandleravtale", ownerCopy.legal.dpa),
} as const;

export function assertCurrentCustomerAgreementForm(input: {
  agreementAccepted: string;
  businessTermsVersion: string;
  dpaVersion: string;
}) {
  if (input.agreementAccepted !== "accepted") {
    throw new Error("Du må bekrefte fullmakt og godta avtalevilkårene.");
  }
  if (
    input.businessTermsVersion !== currentCustomerAgreements.businessTerms.version ||
    input.dpaVersion !== currentCustomerAgreements.dpa.version
  ) {
    throw new Error("Avtalevilkårene er oppdatert. Les dem og bekreft på nytt.");
  }
}
