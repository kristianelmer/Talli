# Corporate-governance web feature

<!-- architecture-inventory
{"apiOperations":["corporateGovernanceApproveAnnualClose","corporateGovernanceApproveOwnerDividend","corporateGovernanceAttestAnnualCloseSignedArtifact","corporateGovernanceAttestOwnerDividendSignedArtifact","corporateGovernanceFinalizeAnnualClose","corporateGovernanceFinalizeOwnerDividend","corporateGovernanceListDecisionLifecycle","corporateGovernanceProposeAnnualClose","corporateGovernanceProposeOwnerDividend","corporateGovernanceReadDecisionLifecycle","corporateGovernanceReadDecisionReadiness","corporateGovernanceRecordAnnualCloseEvent","corporateGovernanceRecordOwnerDividendEvent","corporateGovernanceRecordOwnerDividendPayment","corporateGovernanceRecordShareholderLoan","corporateGovernanceRegisterAnnualCloseDocuments","corporateGovernanceRegisterOwnerDividendDocuments"],"dependencies":[],"publicEntryPoints":["@/features/corporate-governance","apps/web/features/corporate-governance","apps/web/features/corporate-governance/index.ts"],"routes":["/actions/[type]","/corporate-decisions/[decisionId]","/workspace"]}
-->

## Purpose and boundary

This feature is the generated-client transport and Norwegian error-presentation
boundary for annual close, owner dividends, shareholder loans, and corporate
artifact lifecycle reads. The backend owns canonical facts, readiness,
authorization, idempotency, deterministic rendering, Ledger posting, and Banking
claims. The web may collect form facts, present lifecycle state and hard-block
guidance, and upload through the Documents feature; it must not choose accounting
policy, regenerate governance decisions, or persist governance state directly.
