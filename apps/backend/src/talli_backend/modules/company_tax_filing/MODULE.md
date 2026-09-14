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

The #152 expansion in `supabase/contract-migrations/20260914200000_company_tax_return_expand.sql` creates inert filing targets. It copies Tax rows from six shared families under a source lock, pins exact rows/schema/RPC evidence, quarantines ambiguous obligation or relationship provenance, and compares counts and ordered JSONB hashes. The legacy writer remains authoritative; target tables have FORCE RLS and no business policy/grant. Existing company, actor and opening-snapshot foreign-key behavior is preserved, while intra-Tax references bind to the new schema. Temporary migration privileges are restored. The explicitly ordered cutover, contract and rollback artifacts are rehearsed locally; complete stage-exit verification remains pending.

<!-- architecture-inventory
{"ownedTables": ["company_tax_filing.filing_previews", "company_tax_filing.filing_submissions", "company_tax_filing.filing_overrides", "company_tax_filing.filing_review_comments", "company_tax_filing.authority_permissions", "company_tax_filing.authority_test_runs"]}
-->

`CompanyTaxWorkspaceQuery`, `CompanyTaxFilingRows`, and `CompanyTaxWorkspacePersistence` publish complete immutable company-scoped filing rows. The public result checks company, year, obligation, duplicate identities and related preview/test evidence. The read-only SQL contracts in `supabase/contract-migrations/20260914201000_company_tax_return_read_contracts.sql` deny access to inert expansion or rolled-back copies; enabling them still requires the separate canonical cutover. Company-wide test evidence is not a claim of yearly production completeness.

<!-- architecture-inventory
{"ports":["CompanyTaxWorkspacePersistence"]}
-->

The TT02 import accepts immutable raw evidence and obtains company identity from the existing Company Access public contract. `CompanyTaxReturnPersistence` writes the deterministic projection and returns original receipt IDs with a creation flag. The application owns the surrounding transaction and Audit ordering. The import SQL retains all legacy strict payload, attribution, timestamp, hash, content and replay checks, using owned Tax tables and owner decisions from Company Access. Expansion and rollback reject import execution.

<!-- architecture-inventory
{"ports": ["CompanyTaxReturnPersistence"]}
-->

`ImportCompanyTaxReturnEvidence` carries the immutable command. `CompanyTaxCompanyIdentity` carries the authorized identity fact and `ImportedCompanyTaxEvidence` carries `TaxAuthorityEvidenceId`, `TaxFilingSubmissionId` and the creation flag.

The preparation controls preserve the existing normalization, owner confirmation, reviewer acknowledgement and manual evidence behavior. `RecordCompanyTaxOverride`, `AddCompanyTaxReviewComment`, `ConfirmCompanyTaxPermission`, `RecordCompanyTaxTestEvidence`, `CompanyTaxRecordQuery`, `CompanyTaxRecordedResult`, `normalize_company_tax_override`, `normalize_company_tax_review`, `normalize_company_tax_test_evidence`, `TaxFilingRecordId`, `CompanyTaxPreparationPersistence` expose the declared Tax contracts. Company Access retains accepted-role and fresh-MFA policy. A permission flag records the existing owner declaration; it does not activate a provider or submit a filing. Existing web Audit continuations remain outside these formerly single-row operations.

<!-- architecture-inventory
{"ports": ["CompanyTaxPreparationPersistence"]}
-->

`CompanyTaxReadinessIssue` and `assess_company_tax_readiness` preserve Tax's ordered annual readiness issues: selected company/year holding blocks and missing settlement, followed by the existing payload feedback. Annual retains common readiness gates and Billing retains entitlement/refund decisions. `AnnualTaxEstimateSource` carries only the ordered accounting and holding facts actually used by the existing estimate; it introduces no fictitious company or year.

The authenticated `companyTaxPreviewReadiness` and `companyTaxPreviewAnnualEstimate` endpoints authenticate the caller and evaluate supplied immutable facts without business-data reads or persistence. Their company/year labels scope the requested preview; they do not attest stored source completeness, membership in another company, production history, filing permission, or an authority outcome. They preserve the existing cross-company/all-year annual estimate aggregation. JSON facts are bounded to 8 MiB, malformed facts fail validation, and nonfinite estimates are rejected instead of returning an unusable monetary result. Web calculation retirement and source-backed production handoff remain separate work.

The HTTP assessment boundary validates consumed nested containers and requires a string ledger account. Direct pure/CLI callers additionally preserve ECMAScript Boolean conversion, including truthy empty arrays/objects; these values cannot silently clear a loan block because Python would consider them false. The 45 predecessor Boolean-boundary captures exercise both payload feedback and Tax readiness.


The four filing expansion/read/write artifacts live in `supabase/contract-migrations/` because their predecessor must already be contracted. `scripts/rehearse-tax-topology.mjs filing-expand` applies them in dependency order; `filing-contract` then applies `20260914012503_company_tax_return_cutover.sql` and `20260914012930_company_tax_return_contract.sql`. They are not automatic startup migrations.

The cutover locks and positively enumerates all six shared families, recopies the latest Tax rows, reconciles exact counts/hashes and retains Accounts rows. It restores source trigger modes without advancing Archive generations. Static constraints retire old Tax writes; the existing comment FK binds comments to surviving public previews. The old TT02 RPC is first disabled and then dropped. Runtime source access holds a shared migration-state lock; rollback takes the conflicting lock. Stale repeatable-read transactions fail closed. Documents keeps receipt/feedback retention through a Tax-owned boolean contract.

The full rollback restores the latest owned records and exact predecessor RPC permissions, including records created after cutover. It fences retained owned rows, makes the backend source unavailable and preserves Archive generations. Contract-only rollback leaves the owned writer active. The same cutover artifact supports re-cutover after full rollback. Local SQL and transaction-race evidence does not replace the required HTTP, browser and full release gates.


The predecessor web Tax calculation, XML/envelope, evidence-projection and estimate files are removed. Tax-only helpers are also removed from the shared web authority-evidence file. The remaining Annual Accounts and shared definitions are unchanged. Existing JavaScript cross-output fixtures use a fixed test-only driver of these public Python contracts; no production TypeScript Tax implementation remains.


`CompanyTaxAuthority` is the outbound test-authority port, registered through `company_tax_authority_adapter` to `talli_backend.adapters.company_tax_authority.CompanyTaxTransport`. Its fixed TT02 adapter preserves the existing endpoint, response-validation and redaction mechanics. `CompanyTaxReturnAuthorityError` preserves the sanitized failure shape. `wait_for_company_tax_validation`, `wait_for_company_tax_feedback` and `wait_for_company_tax_clean_envelope` own the existing retry, terminal-status and timeout decisions. The sleep mechanism is supplied by the caller. There is no human-confirmation operation on the port, and production transport remains disabled.

The shared `authority_tools._filing.FixedTransport` and parsing helpers remain the single canonical technical implementation also used by Annual Accounts until #153. The Tax capability does not import those CLI mechanics. The old Tax transport file is removed; the CLI uses the declared adapter and public polling contracts. The local rehearsal state machine now resides in this capability.

<!-- architecture-inventory
{"ports": ["CompanyTaxAuthority"]}
-->


`CompanyTaxRehearsalConfiguration`, `CompanyTaxRehearsalIO` and `rehearse_company_tax_return` expose the existing local prepare/resume workflow. The frozen configuration contains only nonsecret declarations. The capability owns approved test scope, no-activity admission, prior evidence identity, durable intent before credential checks, repair eligibility, instance/upload/validation transitions, human handoff, read-only receipt resume and completed replay. The local adapter owns paths, JSON decoding, atomic private evidence writes, clocks, revision lookup, schema execution and credential acquisition. Existing pure payload generation crosses the public Tax contracts in process. The final summary is immutable; internal checkpoint evidence remains private mutable workflow state. No genuine filing or provider operation is performed during local verification.

<!-- architecture-inventory
{"ports": ["CompanyTaxRehearsalIO"]}
-->


`CompanyTaxSourceQuery`, `CompanyTaxSourceSnapshot`, `CompanyTaxSourceEvidence`, `CompanyTaxHistoryCoverage`, `CompanyTaxSubmissionFact`, `CompanyTaxIncidentFact`, `CompanyTaxOutcomeFact`, `CompanyTaxCorrectionLink`, `CompanyTaxSourceFacts`, `CompanyTaxSourcePersistence`, `project_company_tax_source` and `verify_company_tax_source` publish immutable evidence of the recorded Tax source. The adapter reads all six owned families and positive migration evidence in one authorized owner repeatable snapshot. The SQL contract checks scope, retained submission identities, six-family reconciliation, source hashes, exact legacy writer fences, original mode constraints and the declared seven-table Tax extent. Missing proof cannot mean no submissions. A production-labelled or unknown-mode legacy row remains an unknown potential attempt and makes coverage incomplete because no Tax production journal exists in this stage.

Source readiness is currently blocked by the existing disabled Tax production implementation. A stored permission flag or TT02 receipt cannot enable it. This decisive gate does not certify any other readiness prerequisite or turn the caller-fact assessment into an authoritative source. Before production is enabled, the source version and readiness contract must include current durable Annual, Ledger and Investments facts. Test and simulation outcomes remain labelled with their original source/adapter modes, record identities, observation times and actor references. Local observation time is not authority event time; incident attribution stays unknown. Corrections require explicit recorded links. Billing alone applies commercial policy.

The deferred `20260914022608_company_tax_return_source_contract.sql` follows the four filing expansion contracts in the explicit runner. Its function remains unavailable before cutover and after full rollback. Source evidence verification rereads a fresh snapshot and rejects scope/version/digest drift, future evidence times or incomplete coverage. The evidence scope is Talli-recorded Company Tax, not all external authority filings.

<!-- architecture-inventory
{"ports": ["CompanyTaxSourcePersistence"]}
-->
