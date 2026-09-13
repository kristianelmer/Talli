# Company Tax

Company Tax owns settlement capture facts and normalization. Ledger owns account selection and posting; Banking owns matching; Documents owns evidence storage. The application workflow composes those public contracts.

The first migration slice is #146. Annual tax estimates and filing remain in #152. Preview normalization preserves the characterized date-shape and binary64 rounding behavior; it does not certify a valid capture date, positive rounded Money, authorization, or available bank link.

<!-- architecture-inventory
{"dependencies":[],"ownedTables":[],"ports":[],"publicEntryPoints":["talli_backend.modules.company_tax_filing.public"]}
-->

Public entry point: `talli_backend.modules.company_tax_filing.public`. The query `normalize_tax_settlement` accepts `TaxSettlementInput` and returns `NormalizedTaxSettlement` or `TaxSettlementValidationError`. `TaxSettlementKind` and `TaxSettlementDocumentStatus` describe the supported capture vocabulary.

The settlement workflow uses `RecordTaxSettlementCommand`, `validate_new_tax_settlement`, `CompanyTaxError`, `TaxSettlementId`, `BankTransactionReference`, `DocumentReference`, `AccountingEntryReference`, `TaxSettlementPersistence`, `tax_settlement_persistence_adapter`. The port binds to `talli_backend.adapters.postgres_company_tax_filing.PostgresCompanyTaxTransaction`.

`company_tax_filing.settlements` retains the thirteen predecessor fields and opaque Ledger, Banking and Documents identifiers. Expansion snapshots and backfills with its writer disabled; the separate cutover artifact locks and reconciles the old source before enabling capture. The migration implementation remains in progress under #146; no exit is asserted.

<!-- architecture-inventory
{"ports":["TaxSettlementPersistence"],"ownedTables":["company_tax_filing.settlements"]}
-->
