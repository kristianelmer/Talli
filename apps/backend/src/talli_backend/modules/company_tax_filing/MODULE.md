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

`CompanyTaxEvidenceInput`, `CompanyTaxEvidenceProjection`, and `project_company_tax_evidence` preserve the strict, sanitized TT02 projection. Imported receipt evidence remains pending authority classification. The pure projection does not authorize persistence, certify a provider operation, or substitute for action-time authentication and MFA. The web import routes through FastAPI and the generated client to the owned SQL workflow. Tax production transport remains disabled.

`CompanyTaxValidationSummary` and `summarize_company_tax_validation` preserve bounded validation text, duplicate removal and Norwegian ICU ordering. The pinned Ada URL parser preserves the predecessor WHATWG canonical-URL check. Both dependencies are local deterministic mechanisms; neither performs authority I/O.

`prepare_company_tax_return` returns `PreparedCompanyTaxReturn` only when the characterized payload has no blocking feedback. The existing tax CLI consumes these public contracts in process; its four statutory TypeScript subprocess branches are retired. The annual-accounts subprocess remains until #153.

The #152 expansion in `supabase/contract-migrations/20260914200000_company_tax_return_expand.sql` creates inert filing targets. It copies Tax rows from six shared families under a source lock, pins exact rows/schema/RPC evidence, quarantines ambiguous obligation or relationship provenance, and compares counts and ordered JSONB hashes. During expansion the legacy writer remains authoritative and the inert targets have FORCE RLS and no business policy/grant. Cutover enables only the owned contracts, fences legacy Tax writes and preserves sibling Accounts rows. Existing company, actor and opening-snapshot foreign-key behavior is preserved, while intra-Tax references bind to the new schema. Temporary migration privileges are restored. The explicitly ordered cutover, contract and rollback artifacts are rehearsed locally; complete stage-exit verification remains pending.

<!-- architecture-inventory
{"ownedTables": ["company_tax_filing.filing_previews", "company_tax_filing.filing_submissions", "company_tax_filing.filing_overrides", "company_tax_filing.filing_review_comments", "company_tax_filing.authority_permissions", "company_tax_filing.authority_test_runs"]}
-->

`CompanyTaxWorkspaceQuery`, `CompanyTaxFilingRows`, and `CompanyTaxWorkspacePersistence` publish complete immutable company-scoped filing rows. The public result checks company, year, obligation, duplicate identities and related preview/test evidence. The read-only SQL contracts in `supabase/contract-migrations/20260914201000_company_tax_return_read_contracts.sql` deny access to inert expansion or rolled-back copies; they become available only after the separate canonical cutover. Company-wide test evidence is not a claim of yearly production completeness.

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

The authenticated `companyTaxPreviewReadiness` and `companyTaxPreviewAnnualEstimate` endpoints authenticate the caller and evaluate supplied immutable facts without business-data reads or persistence. Their company/year labels scope the requested preview; they do not attest stored source completeness, membership in another company, production history, filing permission, or an authority outcome. They preserve the existing cross-company/all-year annual estimate aggregation. JSON facts are bounded to 8 MiB, malformed facts fail validation, and nonfinite estimates are rejected instead of returning an unusable monetary result. The web consumes these previews through the generated client; the separate source contract below publishes current recorded history and the disabled-production gate.

The HTTP assessment boundary validates consumed nested containers and requires a string ledger account. Direct pure/CLI callers additionally preserve ECMAScript Boolean conversion, including truthy empty arrays/objects; these values cannot silently clear a loan block because Python would consider them false. The 45 predecessor Boolean-boundary captures exercise both payload feedback and Tax readiness.


The four filing expansion/read/write artifacts and the source-snapshot contract live in `supabase/contract-migrations/` because their predecessor must already be contracted. `scripts/rehearse-tax-topology.mjs filing-expand` applies all five in dependency order; `filing-contract` then applies `20260914012503_company_tax_return_cutover.sql` and `20260914012930_company_tax_return_contract.sql`. They are not automatic startup migrations.

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

`TaxDeliverySource`, `TaxDeliveryEnvelope`, `tax_delivery_digest`,
`prepare_tax_delivery` and `verify_tax_review` bind a complete, company/year-scoped
Annual/Ledger/Investments read to immutable statutory documents, the current
authority document reference and the schema pin. Preparation requires an explicit
no-additional-attachments answer and typed Tax-consumed annual facts; a caller-fact
assessment preview cannot establish that persisted source. Common Annual
readiness remains an independently published prerequisite for the application,
not a decision made by document preparation. Changed source, independently read
current schema or current authority document reference invalidate review.

`TaxMutationKind`, `TaxMutationIntent`, `TaxMutationRecord`,
`TaxMutationDisposition` and `plan_tax_mutation` define submit-once operation
policy. Persistence must atomically commit a unique new intent before execution.
An existing uncertain operation requires read-only reconciliation; expiry or a
changed request never permits another POST. Completed results have a closed,
operation-specific shape. These policy contracts do not yet constitute a
persisted delivery workflow, enable a provider or replace the disabled-production
source gate above.

The internal `CompanyTaxApplication` delivery-source read now composes the
existing exact-year Annual interview contract, every Ledger entry page, and
Investments' complete reporting snapshot in one verified repeatable transaction
with no business writes. Existing migration-fence row locks remain supported.
Owning adapters borrow only existing executor memberships, enforce
the verified subject/claims and isolation binding, and restore the Tax role on
success, SQL error or cancellation. The source keeps all upstream digests while
projecting selected-year facts into the characterized Tax calculator. Missing
interviews, malformed pages and unresolved source lineage fail closed. This
preparation seam has no public HTTP route, stored approval or authority effect.

Ledger's published amendment references identify administrative-cost reversals
for the distinct entry-based annual estimate. Statutory expenses and share losses
use net account balances, so full reversal/replacement chains do not double-count.
Unsettled investment-income and sale receivables (`1530`/`1570`) map to the pinned
2025 business code `1570` (other current receivables); settled balances cancel.
Current-asset occurrences reserve distinct paths for securities, bank and
receivables instead of colliding when the only investment is a current asset.

`TaxDeliverySchemaValidator`, `TaxSchemaValidation` and
`tax_delivery_schema_adapter` bind local validation to the exact immutable
documents and schema/code-list pin. The infrastructure adapter
`talli_backend.adapters.company_tax_schemas.PinnedTax2025Schemas` verifies the
packaged manifest and every resource against the fixed upstream commit, then
validates all three XML documents offline. It rejects DTDs/external resources,
unlisted business codes, substituted envelope bytes and inconsistent
company/year/party/current-reference bindings. The shipped Apache-licensed
resources retain their upstream license and provenance; runtime makes no fetch.

The release-only `scripts/check_company_tax_schema_drift.py` resolves the fixed
official branch once and checks all nine 2025 resources at that immutable commit.
The launch rehearsal requires this gate: drift blocks, incomplete reads remain
unavailable, and matching resources remain current when only other years change.
Comments and processing instructions cannot hide code-list text; validation
proofs continue to hash the exact original document bytes.

The single calculator has a versioned authority-code projection. Historical
characterization keeps its original Ledger-number labels. New delivery uses
`company-tax-delivery-2025-v1`: Ledger cost accounts `6420`,
`6700`/`6705`/`6720`, and `7770`/`7790`/`7795` map respectively to the official
2025 business codes `6400`, `6700`, and `7700`, aggregating each category while
retaining the contributing Ledger account references. Amount calculations and
bookkeeping accounts are shared; this adds no second writer. The old labels do
not constitute code-list validation or authorization for new delivery.

<!-- architecture-inventory
{"ports":["TaxDeliverySchemaValidator"]}
-->

<!-- architecture-inventory
{"ports": ["CompanyTaxSourcePersistence"]}
-->

`TaxDeliveryDraft`, `StoredTaxDeliveryDraft`, `TaxDeliveryDraftFact`,
`decode_tax_delivery_draft` and `TaxDeliveryDraftPersistence` retain exact
versioned draft bytes, source/review/schema proofs, company/year, actor,
command identity and server time. Duplicate keys, noncanonical JSON, lossy XML,
changed scope/proofs and unknown versions are rejected on read. Exact concurrent
replay returns the same original; a changed binding conflicts. Drafts grant no
Annual readiness, Billing entitlement, approval, dispatch or authority outcome.

The deferred `20261026062315_company_tax_delivery_journal.sql` adds the owned
append-only `delivery_drafts` store after the Tax predecessor is contracted.
Its full owned relation is `company_tax_filing.delivery_drafts`.
Restricted runtime roles receive only exact RPC access. Forced RLS permits the
accepted owner to read/insert; no update/delete policy exists. Writes require
READ COMMITTED and recheck owner/phase after the published company lock.
Rollback closes a volatile write fence checked after the company lock and revokes
the write RPC, including containment of calls already waiting. Originals and
source reads remain available. Reopening requires restoring the private fence
helper to true and the original exact EXECUTE grant.

Source V2 positively enumerates all eight declared Tax tables and every retained
draft, including per-draft digests/count, without altering V1's seven-table
extent. V1 correctly becomes incomplete. The adapter selects installed V2; if
it is missing, V1 cannot conceal an added store. Unknown extra stores, incomplete
enumeration and mismatched draft bindings prevent complete coverage. Read bounds
(1,000 drafts/64 MiB per scope) fail unavailable, never truncate. V2 observation
time is read after enumeration,
so a valid draft committed between transaction begin and its first repeatable
snapshot cannot be rejected as future evidence. Historical production-labelled rows remain unknown; prepared drafts stay out of submission
and outcome history. No hosted migration, provider call or public draft-write
route is enabled by these internal contracts.

<!-- architecture-inventory
{"ports":["TaxDeliveryDraftPersistence"],"ownedTables":["company_tax_filing.delivery_drafts"]}
-->

`TaxDeliveryDraftArchive` and `archive_tax_delivery_drafts` preserve every exact
canonical draft and its retained actor, scope, source/review/schema bindings and
server time. The original reader refuses invalid enumeration. Unknown effects
on a retained legacy submission do not erase otherwise positively covered draft
originals. The API `/api/v1/company-tax/archive-source/delivery-drafts-v1` returns
these originals only through the canonical fresh-MFA policy. A short READ
COMMITTED company guard encloses the separate repeatable source read and
rechecks current owner/MFA after it; no provider I/O occurs while it is held.

The draft table installs the existing Company Access archive-generation trigger.
Its exact enabled function/arguments are included in positive V2 coverage.
Temporary trigger EXECUTE authority and role memberships are restored after DDL.
New writes invalidate in-progress company exports; exact replay does not.
Containment preserves originals and generation tracking.
