# Corporate-governance web feature

<!-- architecture-inventory
{"apiOperations":["corporateGovernanceApproveAnnualClose","corporateGovernanceApproveOwnerDividend","corporateGovernanceAttestAnnualCloseSignedArtifact","corporateGovernanceAttestOwnerDividendSignedArtifact","corporateGovernanceDeriveDecisionFacts","corporateGovernanceFinalizeAnnualClose","corporateGovernanceFinalizeOwnerDividend","corporateGovernanceListDecisionLifecycle","corporateGovernanceListSupportedEvents","corporateGovernanceProposeAnnualClose","corporateGovernanceProposeOwnerDividend","corporateGovernanceReadDecisionLifecycle","corporateGovernanceReadDecisionReadiness","corporateGovernanceRecordAnnualCloseEvent","corporateGovernanceRecordOwnerDividendEvent","corporateGovernanceRecordOwnerDividendPayment","corporateGovernanceRecordShareholderLoan","corporateGovernanceRecordSupportedEvent","corporateGovernanceRegisterAnnualCloseDocuments","corporateGovernanceRegisterOwnerDividendDocuments"],"dependencies":[],"publicEntryPoints":["@/features/corporate-governance","apps/web/features/corporate-governance","apps/web/features/corporate-governance/index.ts"],"routes":["/actions/[type]","/corporate-decisions/[decisionId]","/workspace"]}
-->

## Purpose and boundary

This feature is the generated-client transport and Norwegian error-presentation
boundary for annual close, owner dividends, shareholder loans, supported domestic
capital, financing and group events, and corporate artifact lifecycle reads.
`corporateGovernanceDeriveDecisionFacts` obtains the
backend-owned proposal facts before the web submits owner-reviewed intent. The
backend owns canonical facts, readiness,
authorization, idempotency, deterministic rendering, Ledger posting, and Banking
claims. The web may collect form facts, present lifecycle state and hard-block
guidance, and upload through the Documents feature; it must not choose accounting
policy, regenerate governance decisions, or persist governance state directly.
