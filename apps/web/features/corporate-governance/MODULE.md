# Corporate-governance web feature

<!-- architecture-inventory
{"apiOperations":["corporateGovernanceApproveOwnerDividend","corporateGovernanceFinalizeOwnerDividend","corporateGovernanceProposeOwnerDividend","corporateGovernanceRecordOwnerDividendPayment","corporateGovernanceRecordShareholderLoan","corporateGovernanceRegisterOwnerDividendDocuments"],"dependencies":[],"publicEntryPoints":["@/features/corporate-governance","apps/web/features/corporate-governance","apps/web/features/corporate-governance/index.ts"],"routes":["/actions/[type]","/corporate-decisions/[decisionId]","/workspace"]}
-->

## Purpose and boundary

This feature is the generated-client transport and Norwegian error presentation
boundary for owner dividends and shareholder loans. The backend owns canonical facts, readiness,
authorization, idempotency, Ledger posting, and Banking claims. The web may
collect form facts, render the transitional document preview, and upload through
the Documents feature; it must not choose accounting policy or persist governance
state directly.
