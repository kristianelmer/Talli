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
