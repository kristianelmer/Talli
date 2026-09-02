/**
 * Presentation shapes for reviewed corporate facts.
 *
 * Canonicalization, validation, source identity, decision hashing, signer
 * requirements, and readiness are owned by the Python corporate-governance
 * module and exposed through its generated API contract.
 */

export type PersistedCorporateCompany = {
  id: string;
  organizationNumber: string;
  legalName: string;
};

export type PersistedCorporateShareholder = {
  id: string;
  name: string;
  shareCount: number;
  order: number;
};

export type ApprovedAnnualCorporateBasis = {
  id: string;
  incomeYear: number;
  isLatestApproved: boolean;
  annualDataHash: string;
  annualAccountsPayloadHash: string;
  resultAfterTaxOre: number;
  equityOre: number;
  availableDistributionOre: number;
  cashOre: number;
};

export type ReviewedCorporateFacts = {
  organizationNumber: string;
  legalName: string;
  shareholders: Array<{
    shareholderId: string;
    name: string;
    shareCount: number;
  }>;
  totalCompanyShares: number;
  availableDistributionOre: number;
  annualDataHash: string;
  annualAccountsPayloadHash: string;
};
