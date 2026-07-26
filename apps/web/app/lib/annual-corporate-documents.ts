import type {
  ApprovedAnnualCorporateBasis,
  PersistedCorporateCompany,
  PersistedCorporateShareholder,
  ReviewedCorporateFacts,
} from "./corporate-decision-facts.ts";
import {
  buildOwnerDividendAnnualBasis,
  buildOwnerDividendReviewedFacts,
} from "./owner-dividend.ts";

type AnnualDataForCorporateClose = Parameters<typeof buildOwnerDividendAnnualBasis>[0]["annualData"];
type AnnualAccountsPayloadForCorporateClose = Parameters<
  typeof buildOwnerDividendAnnualBasis
>[0]["annualAccountsPayload"];

export function buildAnnualCloseBasis(input: {
  annualData: AnnualDataForCorporateClose;
  annualAccountsPayload: AnnualAccountsPayloadForCorporateClose;
}): ApprovedAnnualCorporateBasis {
  return buildOwnerDividendAnnualBasis(input);
}

export function buildAnnualCloseReviewedFacts(input: {
  company: PersistedCorporateCompany;
  shareholders: PersistedCorporateShareholder[];
  annualBasis: ApprovedAnnualCorporateBasis;
}): ReviewedCorporateFacts {
  return buildOwnerDividendReviewedFacts(input);
}
