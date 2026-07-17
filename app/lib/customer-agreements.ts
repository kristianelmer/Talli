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

const currentAgreementMetadata = {
  business_terms: {
    version: "2026-07-17",
    effectiveDate: "2026-07-17",
    contentSha256: "f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543",
  },
  dpa: {
    version: "2026-07-17",
    effectiveDate: "2026-07-17",
    contentSha256: "083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c",
  },
} as const;

export function assertCanonicalAgreementContent(
  kind: "business_terms" | "dpa",
  content: ContractContent,
  expectedSha256: string,
) {
  const actualSha256 = createHash("sha256")
    .update(JSON.stringify(content), "utf8")
    .digest("hex");
  if (actualSha256 !== expectedSha256) {
    throw new Error(`customer_agreement_content_digest_mismatch:${kind}`);
  }
  return actualSha256;
}

function contractDocument(
  kind: "business_terms" | "dpa",
  path: "/vilkar" | "/databehandleravtale",
  content: ContractContent,
) {
  const metadata = currentAgreementMetadata[kind];
  const contentSha256 = assertCanonicalAgreementContent(kind, content, metadata.contentSha256);
  return {
    kind,
    version: metadata.version,
    effectiveDate: metadata.effectiveDate,
    path,
    contentSha256,
  } as const;
}

export const currentCustomerAgreements = {
  businessTerms: contractDocument("business_terms", "/vilkar", ownerCopy.legal.terms),
  dpa: contractDocument("dpa", "/databehandleravtale", ownerCopy.legal.dpa),
} as const;

export function assertCurrentCustomerAgreementForm(input: {
  agreementAccepted: string;
  businessTermsVersion: string;
  businessTermsSha256: string;
  dpaVersion: string;
  dpaSha256: string;
}) {
  if (input.agreementAccepted !== "accepted") {
    throw new Error("Du må bekrefte fullmakt og godta avtalevilkårene.");
  }
  if (
    input.businessTermsVersion !== currentCustomerAgreements.businessTerms.version ||
    input.businessTermsSha256 !== currentCustomerAgreements.businessTerms.contentSha256 ||
    input.dpaVersion !== currentCustomerAgreements.dpa.version ||
    input.dpaSha256 !== currentCustomerAgreements.dpa.contentSha256
  ) {
    throw new Error("Avtalevilkårene er oppdatert. Les dem og bekreft på nytt.");
  }
}
