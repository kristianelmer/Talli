# Company Tax

Company Tax owns settlement capture facts and normalization. Ledger owns account selection and posting; Banking owns matching; Documents owns evidence storage. The application workflow composes those public contracts.

The settlement slice #146 is merged. The full filing slice #152 is in progress. Preview normalization preserves the characterized date-shape and binary64 rounding behavior; it does not certify a valid capture date, positive rounded Money, authorization, or available bank link.

<!-- architecture-inventory
{"dependencies":[],"ownedTables":[],"ports":[],"publicEntryPoints":["talli_backend.modules.company_tax_filing.public"]}
-->

Public entry point: `talli_backend.modules.company_tax_filing.public`. The query `normalize_tax_settlement` accepts `TaxSettlementInput` and returns `NormalizedTaxSettlement` or `TaxSettlementValidationError`. `TaxSettlementKind` and `TaxSettlementDocumentStatus` describe the supported capture vocabulary.

The settlement workflow uses `RecordTaxSettlementCommand`, `validate_new_tax_settlement`, `CompanyTaxError`, `TaxSettlementId`, `BankTransactionReference`, `DocumentReference`, `AccountingEntryReference`, `TaxSettlementPersistence`, `tax_settlement_persistence_adapter`. The port binds to `talli_backend.adapters.postgres_company_tax_filing.PostgresCompanyTaxTransaction`.

`company_tax_filing.settlements` retains the thirteen predecessor fields and opaque Ledger, Banking and Documents identifiers. Expansion snapshots and backfills with its writer disabled; the separate cutover artifact locks and reconciles the old source before enabling capture. Settlement integration is complete under #146; full Company Tax stage exit remains subject to #152.

<!-- architecture-inventory
{"ports":["TaxSettlementPersistence"],"ownedTables":["company_tax_filing.settlements"]}
-->

The Archive query preserves all thirteen fields and opaque references in one authorized company/year. Private Documents callbacks disclose only reference existence and follow the active physical source during rollback.

<!-- architecture-inventory
{"ports":["TaxSettlementArchivePersistence"]}
-->

`TaxSettlementArchiveQuery` binds the verified actor, company and year for the preserved source read.

The deterministic filing contracts are `CompanyTaxReturnSource`, `CompanyTaxReturnCandidate`, `AnnualTaxEstimate`, `CompanyTaxReturnDocuments`, `CompanyTaxEnvelopeInput`, `build_company_tax_return`, `estimate_annual_tax`, `render_company_tax_return`, and `render_company_tax_envelope`. Source and candidate mappings are recursively copied and frozen. The named workflow supplies annual and accounting facts through public contracts; calculations perform no I/O. Annual estimate aggregation deliberately differs from filing-payload aggregation, preserving the captured predecessor behavior.

`CompanyTaxEvidenceInput`, `CompanyTaxEvidenceProjection`, and `project_company_tax_evidence` preserve the strict, sanitized TT02 projection. Imported receipt evidence remains pending authority classification. The pure projection does not authorize persistence, certify a provider operation, or substitute for action-time authentication and MFA. Existing production routes still use the predecessor until the subsequent #152 cutover.

`CompanyTaxValidationSummary` and `summarize_company_tax_validation` preserve bounded validation text, duplicate removal and Norwegian ICU ordering. The pinned Ada URL parser preserves the predecessor WHATWG canonical-URL check. Both dependencies are local deterministic mechanisms; neither performs authority I/O.

`prepare_company_tax_return` returns `PreparedCompanyTaxReturn` only when the characterized payload has no blocking feedback. The existing tax CLI consumes these public contracts in process; its four statutory TypeScript subprocess branches are retired. The annual-accounts subprocess remains until #153.

The #152 expansion in `supabase/migrations/20260914200000_company_tax_return_expand.sql` creates inert filing targets. It copies Tax rows from six shared families under a source lock, pins exact rows/schema/RPC evidence, quarantines ambiguous obligation or relationship provenance, and compares counts and ordered JSONB hashes. The legacy writer remains authoritative; target tables have FORCE RLS and no business policy/grant. Existing company, actor and opening-snapshot foreign-key behavior is preserved, while intra-Tax references bind to the new schema. Temporary migration privileges are restored. Separate cutover, contract and rollback work is still pending.

<!-- architecture-inventory
{"ownedTables": ["company_tax_filing.filing_previews", "company_tax_filing.filing_submissions", "company_tax_filing.filing_overrides", "company_tax_filing.filing_review_comments", "company_tax_filing.authority_permissions", "company_tax_filing.authority_test_runs"]}
-->

`CompanyTaxWorkspaceQuery`, `CompanyTaxFilingRows`, and `CompanyTaxWorkspacePersistence` publish complete immutable company-scoped filing rows. The public result checks company, year, obligation, duplicate identities and related preview/test evidence. The read-only SQL contracts in `supabase/migrations/20260914201000_company_tax_return_read_contracts.sql` deny access to inert expansion or rolled-back copies; enabling them still requires the separate canonical cutover. Company-wide test evidence is not a claim of yearly production completeness.

<!-- architecture-inventory
{"ports":["CompanyTaxWorkspacePersistence"]}
-->

The TT02 import accepts immutable raw evidence and obtains company identity from the existing Company Access public contract. `CompanyTaxReturnPersistence` writes the deterministic projection and returns original receipt IDs with a creation flag. The application owns the surrounding transaction and Audit ordering. The import SQL retains all legacy strict payload, attribution, timestamp, hash, content and replay checks, using owned Tax tables and owner decisions from Company Access. Expansion and rollback reject import execution.

<!-- architecture-inventory
{"ports": ["CompanyTaxReturnPersistence"]}
-->

`ImportCompanyTaxReturnEvidence` carries the immutable command. `CompanyTaxCompanyIdentity` carries the authorized identity fact and `ImportedCompanyTaxEvidence` carries `TaxAuthorityEvidenceId`, `TaxFilingSubmissionId` and the creation flag.
