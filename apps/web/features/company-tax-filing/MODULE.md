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

`loadTaxDeliveryDraftArchiveSource` and `TaxDeliveryDraftArchiveProjection` compose
`companyTaxGetSourceFacts` and `companyTaxGetDeliveryDraftArchive`. A complete V1
source positively proves the old seven-table extent and permits frontend-first
rollout without inventing a missing archive response. V2 requires the exact
originals, unchanged source digest, per-record UTF-8 SHA-256, and matching
company/year/filing identity. Unknown versions, missing originals and changed
bytes remain unavailable. Company export retains the source facts and exact
canonical draft strings inside its existing generation boundary. Drafts remain
prepared-only; these reads decide no filing readiness or authority outcome.

<!-- architecture-inventory
{"apiOperations":["companyTaxGetSourceFacts","companyTaxGetDeliveryDraftArchive"]}
-->

`companyTaxGetDeliveryJournalArchive` supplies Source V3 facts, immutable draft
and event originals, and finite-rehearsal journal summaries from one guarded
repeatable read. `loadTaxDeliveryDraftArchiveSource` requests it when the older
exact-extent proof detects the event store, checks original digests/scope and
review/request links, and includes it in company export. A successor read failure
never falls back to an older incomplete source. Positively complete seven/eight
table sources retain their prior read behavior. `TaxDeliveryDraftArchiveProjection`
carries the optional journal bundle; export publishes `companyTaxDeliveryJournal`
without interpreting it as a live provider outcome.

<!-- architecture-inventory
{"apiOperations":["companyTaxGetDeliveryJournalArchive"]}
-->


`loadTaxDeliveryOwnerReview` reads the complete prepared review through generated
authenticated transport. It verifies scope, initial approval and artifact
commitments, fixed schema pins, detail counts, unique fields and decoded
calculated-original hashes, plus the exact enclosing validation-response hash.
Missing or malformed data fails the read; there is
no empty-review fallback. The artifact retains backend-owned projections and
all calculated originals. The browser decides no XML validity, readiness,
confirmation or submission outcome.

<!-- architecture-inventory
{"apiOperations":["companyTaxGetDeliveryOwnerReview"]}
-->
