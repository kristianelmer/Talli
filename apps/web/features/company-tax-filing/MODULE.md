# Company Tax presentation

Generated authenticated settlement previews and capture preserve the released v1 operation and use one operation ID for request and idempotency identity. Company Tax owns normalization; Ledger owns account mapping.

<!-- architecture-inventory
{"apiOperations":["companyTaxPreviewSettlement","ledgerPostTaxSettlement"],"dependencies":[],"publicEntryPoints":["@/features/company-tax-filing","apps/web/features/company-tax-filing","apps/web/features/company-tax-filing/index.ts"],"routes":["/workspace","/actions/[type]"]}
-->

Archive and readiness read the same exact year-scoped Tax source fields. Failed or malformed reads remain errors; they cannot silently supply an empty successful source.

<!-- architecture-inventory
{"apiOperations":["companyTaxGetSettlementArchiveSource"]}
-->

`loadCompanyTaxFilingWorkspace` exposes the generated read contract for six owned Tax row families. Workspace, Annual readiness and Archive consume this owned source. A failed source remains unavailable; the UI never substitutes empty history.

<!-- architecture-inventory
{"apiOperations":["companyTaxGetFilingWorkspace"]}
-->

The generated TT02 import transport submits the original bounded evidence JSON with company/year scope. Its error presenter preserves the existing MFA prompt and sanitized failure messages.

<!-- architecture-inventory
{"apiOperations":["companyTaxImportTt02Evidence"]}
-->

Generated preparation transports provide Tax preview lookup, overrides, review comments, acknowledgements, permissions and manual test evidence. A missing owned record permits the frozen sibling flow to continue; an unavailable or unauthorized source never becomes absence.

<!-- architecture-inventory
{"apiOperations": ["companyTaxGetPreview", "companyTaxRecordOverride", "companyTaxAddReviewComment", "companyTaxAcknowledgeReviewComment", "companyTaxConfirmPermission", "companyTaxRecordTestEvidence"]}
-->

The readiness and annual-estimate transports send caller facts to the canonical Python previews; they contain no TypeScript Tax calculation. Their responses are display previews, not attestations of stored prerequisites or production readiness. The separate backend source contract carries positively covered recorded history and the disabled-production gate.

<!-- architecture-inventory
{"apiOperations":["companyTaxPreviewReadiness","companyTaxPreviewAnnualEstimate"]}
-->
