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
    version: "2026-08-30",
    effectiveDate: "2026-08-30",
    contentSha256: "afc6fc3610f05056f3de8cc849a33accbf3bdff7d469aef8be57c5ccbe074c04",
  },
  dpa: {
    version: "2026-08-30",
    effectiveDate: "2026-08-30",
    contentSha256: "1f5c45a882db79fb248bdff92bd1a245e97b9a7a2f174b943b761f67bda4b94a",
  },
} as const;

export function assertCanonicalAgreementContent(
  kind: "business_terms" | "dpa" | "privacy_notice",
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

function contractDocument<
  const Kind extends "business_terms" | "dpa",
  const Version extends string,
  const ContentSha256 extends string,
>(
  kind: Kind,
  path: "/vilkar" | "/databehandleravtale",
  content: ContractContent,
  metadata: {
    version: Version;
    effectiveDate: string;
    contentSha256: ContentSha256;
  },
) {
  assertCanonicalAgreementContent(kind, content, metadata.contentSha256);
  return {
    kind,
    version: metadata.version,
    effectiveDate: metadata.effectiveDate,
    path,
    contentSha256: metadata.contentSha256,
  } as const;
}

export const currentCustomerAgreements = {
  businessTerms: contractDocument(
    "business_terms",
    "/vilkar",
    ownerCopy.legal.terms,
    currentAgreementMetadata.business_terms,
  ),
  dpa: contractDocument(
    "dpa",
    "/databehandleravtale",
    ownerCopy.legal.dpa,
    currentAgreementMetadata.dpa,
  ),
} as const;

export const currentPrivacyNotice = {
  kind: "privacy_notice",
  version: "2026-08-30",
  effectiveDate: "2026-08-30",
  path: "/personvern",
  contentSha256: "041a65be9f020c037bd65b7097e04afdbeb2c944ef45d7bef3dd380e92f907de",
} as const;

assertCanonicalAgreementContent(
  currentPrivacyNotice.kind,
  ownerCopy.legal.privacy,
  currentPrivacyNotice.contentSha256,
);
