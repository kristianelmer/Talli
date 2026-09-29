# Shareholder register filing

<!-- architecture-inventory
{"dependencies":[],"ownedTables":["shareholder_register_filing.authority_permissions","shareholder_register_filing.authority_test_runs","shareholder_register_filing.filing_approval_snapshots","shareholder_register_filing.filing_overrides","shareholder_register_filing.filing_previews","shareholder_register_filing.filing_review_comments","shareholder_register_filing.filing_submissions","shareholder_register_filing.opening_balance_setups","shareholder_register_filing.opening_shareholders","shareholder_register_filing.production_feedback_artifacts","shareholder_register_filing.production_filing_events","shareholder_register_filing.production_filing_submissions","shareholder_register_filing.year_source_heads","shareholder_register_filing.year_source_versions","shareholder_register_filing.register_observations","shareholder_register_filing.source_previews","shareholder_register_filing.source_review_bridges","shareholder_register_filing.source_approval_bindings","shareholder_register_filing.source_submission_bindings","shareholder_register_filing.submission_heads"],"ports":["OpeningSnapshotPersistence","ProductionOperationJournal","Rf1086FeedbackDiscovery","Rf1086MutationAuthority","Rf1086PreparationPersistence","Rf1086ProductionJournal","Rf1086ReadOnlyAuthority","Rf1086RegisterObservationPersistence","Rf1086SourceOperationJournal","Rf1086YearSourcePersistence"],"publicEntryPoints":["talli_backend.modules.shareholder_register_filing.public"]}
-->

## Owned behavior

The capability owns RF-1086 shareholder opening facts, payload rendering and
readiness, owner confirmations, review, simulation, production approval,
submission journaling, historical recovery and retained source evidence.
The public entry is `talli_backend.modules.shareholder_register_filing.public`.
Deterministic payloads preserve predecessor labels, JSON order, XML, numeric
formatting and original hashes. Canonical obligation identity is separate from
the preserved Norwegian preview label. Private parsing retains the characterized
historical validation behavior; public values are recursively immutable.

Opening share facts and the original bank input have separate owners. The
backend new-year workflow records RF shares and the Ledger-owned bank input
under the same preserved snapshot identity in one transaction with Ledger's
posting. RF does not choose accounts or own current or original bank balances.

Production still requires the verified owner, fresh MFA, exact approved payload,
Billing entitlement and pilot, accepted System User and stored release checks.
The two shipped Send/recovery HTTP contracts remain unchanged. Durable operation
intent precedes provider I/O; unknown outcomes are recovered without a duplicate
send. Documents owns receipt bytes and integrity. These infrastructure bindings
do not enable a production provider.

Source facts describe the complete Talli-recorded RF journal extent only when
positive migration inventory and a complete current read support it. Missing,
quarantined or stale proof is unavailable. Unknown attempts and correction links
remain explicit. Warning facts retain their source and owner acceptance; known
reconciliation outcomes retain their journal observation time separately from
transport incidents and mutation observations. Source facts make no commercial
refund decision.


`rf1086-source-v2` also commits the complete retained full-year archive: source
versions and head, independent observations and capture records, previews,
review bridges, approval lineage, durable claims, submission head, journal and
feedback-original bindings. The adapter reads these on the same repeatable
snapshot as legacy facts and independently counts all eight new storage
families. Coverage checks match both projections and exact family counts, and
validate retained source/archive integrity. Missing or inconsistent evidence
cannot certify complete history. Legacy v1 hashing remains byte-for-byte stable;
previous v1 evidence cannot verify a v2 snapshot. Read timestamps remain excluded
from the digest.

Complete historical coverage does not establish current full-year readiness.
When full-year sources exist, facts explicitly return
`rf1086_full_year_readiness_not_evaluated` rather than falling back to an opening
snapshot. Fresh admission and owned annual prerequisites remain separate work.

The archive projection reads previews, simulations and production evidence for the requested year
before decoding them, plus the original company-wide comments and permissions
and test evidence referenced by those simulations. Its approvals, production submissions,
complete journal and feedback metadata retain immutable manifests, payload hashes and
Documents-owned byte references. Company/year and parent relationships, artifact
counts and approval hashes are checked before publication. Missing or inconsistent
evidence is unavailable; archive reads do not require current paid entitlement.
It does not decode another year's payloads. The
workspace query retains its existing all-year and optional-year behavior.

## Storage and migration

The declared business relations are:

- `shareholder_register_filing.authority_permissions`
- `shareholder_register_filing.authority_test_runs`
- `shareholder_register_filing.filing_approval_snapshots`
- `shareholder_register_filing.filing_overrides`
- `shareholder_register_filing.filing_previews`
- `shareholder_register_filing.filing_review_comments`
- `shareholder_register_filing.filing_submissions`
- `shareholder_register_filing.opening_balance_setups`
- `shareholder_register_filing.opening_shareholders`
- `shareholder_register_filing.production_feedback_artifacts`
- `shareholder_register_filing.production_filing_events`
- `shareholder_register_filing.production_filing_submissions`

Migration state, inventory and quarantine are backend-system technical
bookkeeping, although colocated in the RF schema. Expand, one-writer cutover and
contract have separate lifecycle artifacts. The implementation evidence ledger
tracks their verification; declarations do not assert that a hosted migration,
production run, or the #151 final exit gate has completed.

## Public contracts

Commands:

- `RecordOpeningSnapshotCommand`
- `ShareholderRegisterFilingCommands`
- `GenerateRf1086PreviewCommand`
- `RecordRf1086OverrideCommand`
- `AddRf1086ReviewCommentCommand`
- `AcknowledgeRf1086ReviewCommentCommand`
- `ConfirmRf1086SimulationCommand`
- `ConfirmRf1086FilingPermissionCommand`
- `RecordRf1086TestEvidenceCommand`
- `ApproveRf1086ProductionCommand`
- `SendApprovedRf1086Command`
- `ReconcileRf1086FeedbackCommand`
- `OpeningSnapshotCommands`
- `Rf1086PreparationOperations`

Queries:

- `Rf1086ShareSnapshot`
- `Rf1086ShareholderSnapshot`
- `Rf1086ReadinessResult`
- `Rf1086RecordedResult`
- `Rf1086WorkspaceQuery`
- `Rf1086ArchiveQuery`
- `Rf1086SourceQuery`
- `JournaledRf1086ProductionResult`
- `Rf1086FeedbackResult`
- `Rf1086ReconciliationSnapshot`
- `Rf1086ReconciliationResult`
- `Rf1086SendResult`
- `Rf1086OwnerReconciliationResult`
- `Rf1086PreviewRecord`
- `Rf1086SimulationRecord`
- `Rf1086OverrideRecord`
- `Rf1086ReviewCommentRecord`
- `Rf1086FilingPermissionRecord`
- `Rf1086TestEvidenceRecord`
- `Rf1086ApprovalRecord`
- `Rf1086ProductionSubmissionRecord`
- `Rf1086FeedbackArtifactRecord`
- `Rf1086WorkspaceSnapshot`
- `Rf1086ArchiveSnapshot`
- `Rf1086ArchiveProductionEventRecord`
- `Rf1086ArchiveFeedbackArtifactRecord`
- `Rf1086SourceSnapshot`
- `Rf1086SourceFacts`
- `VerifyRf1086SourceEvidenceQuery`
- `ShareholderRegisterFilingQueries`
- `parse_rf1086_case`
- `generate_rf1086_documents`
- `assess_rf1086_readiness`
- `render_rf1086_preview`
- `render_no_activity_rf1086_preview`
- `create_rf1086_preparation_service`
- `ReadRf1086PreviewQuery`
- `create_rf1086_feedback_artifact_persistence_error`
- `create_opening_snapshot_service`
- `Rf1086CompanyFacts`
- `Rf1086OpeningFacts`
- `build_no_activity_rf1086_case`
- `Rf1086OpeningSource`
- `Rf1086OfflineSimulationResult`
- `Rf1086ValidationCaseResult`
- `Rf1086ValidationReport`
- `parse_rf1086_offline_simulation_input`
- `simulate_rf1086_offline_submission`
- `validate_rf1086_cases`
- `format_rf1086_readiness_report`
- `rf1086_code_decisions`
- `rf1086_code_decisions_for_case`
- `rf1086_production_code_blockers`
- `rf1086_production_scope_exclusions`

Errors:

- `ShareholderRegisterFilingErrorCode`
- `ShareholderRegisterFilingError`
- `Rf1086AuthorityError`
- `Rf1086UnknownProductionOutcomeError`
- `Rf1086BlockedProductionOperationError`
- `Rf1086FeedbackArtifactPersistenceError`
- `Rf1086ProductionError`

Values, identifiers and ports:

- `OpeningSnapshotId`
- `OpeningShareholder`
- `Rf1086ShareholderKind`
- `Rf1086Company`
- `Rf1086Shareholder`
- `Rf1086FormationAllocation`
- `Rf1086FormationEvent`
- `Rf1086ShareSaleEvent`
- `Rf1086DividendAllocation`
- `Rf1086DividendEvent`
- `Rf1086CashIssueEvent`
- `Rf1086NominalIncreaseAllocation`
- `Rf1086CashNominalIncreaseEvent`
- `Rf1086LossCoveringReductionEvent`
- `Rf1086Case`
- `Rf1086ReadinessIssue`
- `Rf1086DocumentSet`
- `Rf1086RenderedPreview`
- `PreviewId`
- `OverrideId`
- `ReviewCommentId`
- `ApprovalId`
- `SubmissionId`
- `TestEvidenceId`
- `Rf1086ActionAvailability`
- `Rf1086AuthorityCall`
- `Rf1086MainResponse`
- `Rf1086PostResponse`
- `Rf1086Confirmation`
- `Rf1086DocumentReference`
- `Rf1086DocumentPage`
- `Rf1086AuthorityDocument`
- `Rf1086ReadOnlyAuthority`
- `Rf1086FeedbackDiscovery`
- `Rf1086FeedbackTransmission`
- `Rf1086MutationAuthority`
- `ProductionOperation`
- `ProductionOperationFailure`
- `ProductionOperationJournal`
- `JournaledRf1086ProductionInput`
- `Rf1086ReconciliationArtifact`
- `Rf1086ProductionJournal`
- `Rf1086ReconciliationInput`
- `Rf1086Approval`
- `Rf1086Preview`
- `Rf1086Submission`
- `Rf1086Connection`
- `Rf1086OpeningBasis`
- `Rf1086PreparedPreview`
- `Rf1086SimulationBasis`
- `Rf1086PreparedSimulation`
- `Rf1086ApprovalBasis`
- `Rf1086PreparedApproval`
- `Rf1086MigrationInventory`
- `Rf1086JournalEvent`
- `Rf1086SourceEvidence`
- `Rf1086HistoryCoverage`
- `Rf1086ProductionAttemptFact`
- `Rf1086CorrectionLink`
- `Rf1086IncidentFact`
- `Rf1086WarningFact`
- `Rf1086OutcomeFact`
- `Rf1086PreparationPersistence`
- `rf1086_payload_utf8_bytes`
- `resume_production_operation`
- `rf1086_xml_schema`
- `OpeningSnapshotPersistence`
- `execute_journaled_rf1086_production`
- `rf1086_current_manifest_hash`
- `rf1086_production_document_order`
- `reconcile_journaled_rf1086_production`
- `Rf1086OpeningShareholderFact`
- `rf1086_adapter`
- `ProductionOperationState`
- `FailureClassification`
- `Rf1086FeedbackClassification`
- `Rf1086ReconciliationState`
- `Rf1086OfflineSimulationInput`
- `Rf1086OfflineSimulationCall`
- `Rf1086ValidationInput`
- `Rf1086CodeVerificationStatus`
- `Rf1086CodeDecision`

The mandatory database lane also runs `apps/backend/tests/test_shareholder_register_filing_lifecycle.py` for real phase, role and retained-row regressions.

## Related authority feedback

RF feedback discovery binds the stored dialog and original submission to the
company and RF service before returning any related transmission attachments.
The backend uses a separate `digdir:dialogporten` system-user token; neither token
nor dialog narrative/presentation URLs enters the public contract. All related
receipt documents are acquired within the shared scan deadline before any
persistence. A complete XML decision governs its accompanying PDF artifact;
missing XML, unknown content and conflicting decisions require action. Exact
Dialogporten IDs, provider creation time and expected company/year are retained
in artifact metadata while Documents owns the unchanged receipt bytes. A final
decision is appended only after every artifact has persisted.

A deterministic owned XML provenance manifest preserves every attachment identity
independently of content-hash deduplication; finalization also requires that
manifest to be durable. Its reference distinguishes it from provider receipts.


## Read-only action-required recovery

An owner may explicitly recheck an `action_required` submission against its
original confirmed transmission and dialog after repairing the reported problem.
The existing owner, approval, entitlement identity, connection and lease checks
still apply. This recheck never obtains a mutation binding or starts another
submission; expired submission eligibility does not erase recovery access.
Accepted and rejected decisions stay terminal. Receipt bytes and their recorded
classifications remain immutable: a recheck cannot turn historical ambiguous or
conflicting artifacts into acceptance. Such evidence requires separately designed
adjudication/correction support; this recovery path does not authorize it.

### Immutable full-year source foundation (#193)

The public source contracts are `RecordRf1086YearSource`, `Rf1086YearSourceId`,
`Rf1086PaidInSourceFacts`, `Rf1086YearDocumentEvidence`, `Rf1086YearEventEvidence`,
`Rf1086YearGovernanceReceipt`, `Rf1086VerifiedYearSourceContext`,
`Rf1086YearSourceFreshness`, `Rf1086YearSourceSnapshot`, and `Rf1086YearSourceError`.
The public operations are `prepare_rf1086_year_source`,
`assert_rf1086_year_source_fresh`, `assert_rf1086_year_source_integrity`,
`assert_rf1086_year_source_replay`, `rf1086_year_source_digest`, and
`rf1086_governance_economic_facts`.

`year_source.py` validates complete RF-owned source facts, explicit tax paid-in
amounts, verified document revisions, finalized corporate evidence, immutable
correction lineage, canonical decimal digests and the full freshness vector.
Previous-year documents may corroborate opening facts. There is no artificial
holder/event count limit. Register observations must be independent of the year
source that references the finalized governance receipt.

`Rf1086VerifiedYearSourceContext` is a trusted application-workflow input. It must
be assembled from authenticated owner public query contracts, never deserialized
from a browser request. The RF capability itself imports no other capability.
The command cannot supply verified context or finalized governance receipts.
Persistence must enforce accepted-owner authorization, company/year RLS, a
current-head compare-and-swap lock, and actor-scoped idempotency before using the
pure preparation/replay functions.

This is a deterministic contract foundation. Database capture, public Governance
and Documents projection bindings, transport, complete preview/approval/send
integration, source archive export, cross-owner freshness race closure and
service conformance remain pending. Existing production admission is not widened.


### Archive deployment overlap

`legacy_archive_source` preserves the original `/archive-source` query extent and
wire fields. Its adapter never reads or decodes production-only tables, and its
validation covers only that original extent. `archive_source` remains the complete
single-snapshot archive projection exposed by additive
`/archive-source/production` (`rf1086GetProductionArchiveSource`). The latter
includes original preview lineage and all four production evidence collections.
Clients must not treat the original response as evidence of absent production
history. This explicit overlap supports either deployment order under ADR-0012.

### Immutable full-year source persistence

`Rf1086YearSourcePersistence` records a verified workflow command and reads current
or historical sources. `serialize_rf1086_year_source` and
`parse_rf1086_year_source` use a closed versioned codec retaining exact decimal
facts and validate immutable source hashes. The restricted RF adapter locks the
company/year, checks current Company Access owner/year admission, resolves
actor-scoped identical idempotency and appends a new version with an exact current
predecessor. `shareholder_register_filing.year_source_versions` retains immutable
source/evidence snapshots; `shareholder_register_filing.year_source_heads` stores
only their current pointers. Both use FORCE RLS; only the append function writes.
The migration rollback revokes the new API without deleting retained evidence.
Source capture grants no correction filing or retry of an unknown provider action.

#### Year-source rollback runbook

Stop source capture before reversing `20260923091509_rf1086_immutable_year_source.sql`.
Its matching rollback revokes the new executor read/write API and leaves every
immutable source and current head intact; reapplying the migration restores access.
The old #151 full rollback drops the entire RF schema and must never run while
any year-source row exists. The coordinated authority topology runner fails with
`rf1086_retained_year_sources_block_full_schema_rollback` before predecessor
mutations. Use the bounded API rollback and preserve evidence; a deeper rollback
requires a separately reviewed, lossless source relocation. This guard assumes
source capture is stopped, as required before runtime/schema rollback.

### Independent registered-share observation foundation

The public `RecordRf1086RegisterObservation` / `prepare_rf1086_register_observation`
contract binds complete, owner-confirmed one-class before/after register states
for cash issues, nominal cash increases and loss-cover reductions to independently
verified original Documents references. Registered capital and nominal amounts
use exact Decimals; tax paid-in facts remain separate. Corrections append a new
UUID/version/hash with an exact predecessor. `assert_rf1086_register_observation_integrity`
checks retained content; `verify_rf1086_register_observation` matches an exact
Governance reference and full event economics through
`Rf1086RegisterObservationMatchQuery`.

This is deterministic source preparation only. Trusted capture must supply
`Rf1086VerifiedRegisterObservationContext` after live owner and original-byte
verification; browser input cannot assert it. There is no register-observation
store, current-head/withdrawal query, cross-capability lease or production route
in this foundation. Existing opening/source hashes and arbitrary Governance
references do not become verified observations. The remaining integration and
noncircular evidence dependency are recorded in
`architecture/evidence/issues/193/rf/register-observation-design.md`.

The immutable value contracts are `Rf1086RegisterObservationId`,
`Rf1086RegisterHolding`, `Rf1086RegisteredShareState`,
`Rf1086RegisterDocumentEvidence`, and `Rf1086RegisterObservationSnapshot`.
`Rf1086RegisterObservationError` carries closed diagnostics without identifiers
or source document contents.

`rf1086_register_observation_request_digest` validates and normalizes request
content for stable idempotency comparisons independent of input holder/document
ordering. It does not issue a new observation identity.

`rf1086_event_register_states` projects exact before/after registered capital and active holders for a selected capital event using the same complete chronological reconciliation as readiness. It includes preceding formation and ownership transfers, validates the entire year and rejects non-capital selections or malformed identities. It does not attest external register truth or tax paid-in balances.

### Independent register observation persistence

`Rf1086RegisterObservationPersistence` appends independent observations to
`shareholder_register_filing.register_observations`. Multiple initial observations
may exist for one company/year. Each correction names the exact previous immutable
ID/hash and reason. A unique predecessor and the company/year transaction lock
prevent forks. Exact current reads return no result for a superseded ID; historical
reads preserve it. `serialize_rf1086_register_observation` and
`parse_rf1086_register_observation` use a closed, versioned codec and verify the
original facts before returning them. Identical normalized idempotency replays
return the original snapshot, including after a correction; authorization is
checked again under the database transaction lock.

The accepted, confirmed and locked AS owner can discover all retained company/year
observations through `GET /api/v1/shareholder-register-filings/register-observations`.
`list_register_observations` uses one snapshot transaction, fresh owner admission,
existing executor SELECT/RLS, and no pagination limit. Every stored codec, row binding
and complete predecessor chain is checked before any history is returned. The response
pairs each receipt with its exact editable public draft and `isCurrent` (no retained
successor). Three confirmations reset to false; the draft predecessor names that
selected observation's ID/hash and its correction reason is cleared. Historical
drafts remain readable, while capture independently requires the current predecessor.
This read neither verifies original bytes nor certifies current evidence or approval.

The RF adapter calls Documents-owned retention for each original in stable ID
order within the same transaction. Complete current metadata, original document
year, hash and byte length are checked while locking each document. A mismatch
rolls back both retention and RF capture. Full-year capture checks retained
register observations are still current under the same company/year lock.

Migration `20260923102314_rf1086_register_observation_store.sql` and its bounded
rollback preserve every immutable observation. Stop capture before API rollback.
Full RF schema rollback fails with
`rf1086_retained_register_observations_block_full_schema_rollback` when any original
observation remains. A deeper reversal requires a separately reviewed lossless
relocation, never deleting evidence to make the guard pass.

### Source-backed full-year previews

The internal source workflow re-verifies accepted ownership, retained original
bytes, all relevant Governance receipts, and independent register observations
before `GenerateRf1086SourcePreview`. Canonical full-year rendering includes
supported events and an explicit review of tax paid-in capital and premium.
`Rf1086SourcePreviewPreparation` persists the source id, source and case hashes,
rendering profile, readiness, review text and exact XML in `source_previews`.

Capture rechecks accepted ownership and the current source after acquiring the
same company/year lock used by source corrections. Identical source/rendered
content replays the same preview; corrected evidence creates a distinct preview
even when XML is unchanged. Historical previews remain readable using their
original stored rendering. The closed codec checks storage integrity without
regenerating historical files. The migration and rollback preserve every preview;
full RF rollback refuses to erase retained previews.

This internal binding performs no provider operation. Customer routes, source
review/approval/send integration and cross-owner action-time consistency remain
pending. Existing legacy previews and production activation are unchanged.

`Rf1086PreparedSourcePreview` binds the verified source to canonical rendering.
`assert_rf1086_source_preview_matches` verifies new previews against that source.
`serialize_rf1086_source_preview` and `parse_rf1086_source_preview` retain exact
historical bytes and reject altered or unsupported storage. RF owns
`shareholder_register_filing.source_previews`.

<!-- architecture-inventory
{"ownedTables":["shareholder_register_filing.source_previews"],"ports":["Rf1086SourcePreviewPreparation"]}
-->

## Full-year approval identity

`build_rf1086_source_approval_manifest` creates the separate
`production-source-approval-v1` identity for an exact retained source and preview.
It commits source/case/freshness hashes, owner and entitlement identities, review
projection and warning acknowledgments, XML bytes and optional predecessor
submission/manifest/reason. It preserves the historical no-activity manifest.

Full-year shareholder IDs are ordered by UTF-8 bytes and mapped to stable SHA-256
journal keys so arbitrary supported IDs fit existing journal operation names.
The returned immutable document map feeds the existing submit-once journal.
Changing an input or adding unknown manifest keys invalidates the approval.

This pure builder does not grant approval or submission authority. Transactional
owner/AAL2/entitlement/review checks, cross-owner freshness, correction admission,
persistence and production profile integration remain separate required work.

## Source writer company guard

`20260924062746_rf1086_source_company_guard.sql` makes source capture,
register-observation capture and source-preview append acquire the existing
company-wide archive advisory guard before the RF year lock and document/head
row locks. Access is checked again after the company guard is acquired. The
application capture transactions use READ COMMITTED. RF-owned row triggers also
cover every permitted mutation of the four source tables, including a first
insert into an empty year. The narrow guard grant adds no cross-owner table
access. Rollback suspends these commands while retaining guards and originals.

The original source guard covers RF source writers. The successor company
guards below extend writer coverage; complete action-time source-backed
production admission remains required. These guard-only triggers do not add
source evidence to company archive exports or advance archive generations.

## Source intake basis

The authenticated `rf1086ReadSourceIntakeBasis` read returns the currently
confirmed AS identity and Governance's complete reporting-year enumeration for
customer source intake. The server projects typed economics using the same
parsers as source capture. It retains pending, rejected, superseded, corrected,
reversed and cross-year records; each capital lifecycle retains its original
phases. Decision/finalization identities, original document references, register
observation references and Ledger amendment lineage remain explicit. Dividend
finalizations identify their exact signed originals on the server.

`enumerationComplete` describes the Governance read only. Empty `blockers` does
not establish source completeness, verified document bytes, an eligible
finalization, filing readiness or approval. Original references are observations;
source capture independently verifies all originals and current register facts.
Capital document references have no source year in the Governance contract, so
that field remains null until Documents supplies its verified metadata. The read
performs no RF writes and does not create or advance source evidence.

## Consequential company guards and Governance assertion

`20260924080249_documents_rf_consequential_company_guards.sql` guards RF preview,
review, permission, simulation, approval and begin commands before their local
row locks, preserving each existing function owner and ACL. Command adapters
explicitly use READ COMMITTED and guard before locking/rechecking their basis.
Existing consistent read-only projections retain REPEATABLE READ.

Governance can call `assert_current_register_observation_v1` with the exact
observation identity, company/year, revision, hash and verified actor on its
final guarded transaction connection. The assertion rereads current owner
access and rejects an observation that has a successor. It gives Governance no
RF table privileges. This closes the observation freshness gap only for callers
that hold the shared company guard until their consequential write commits.

Row backstops additionally serialize canonical/legacy overrides and readiness
mutations. The legacy direct readiness writer still needs an owned command that
guards before row locks and recomputes its evidence after the guard; a trigger
alone does not prove a previously computed payload fresh. Complete full-year
approval/send composition, source archive inclusion, and production readiness
remain separate work. The safe rollback suspends guarded commands, preserving
evidence and backstops. Database execution is required to verify migration,
role, replay and concurrency behavior.

## Guarded source admission scope

The internal `ShareholderRegisterSourceAdmission.admit` context manager performs
private original verification before opening a short READ COMMITTED transaction.
Company Access then checks live owner/MFA/year eligibility and acquires the
company guard before the RF year guard. Current source and preview, retained
original assertions, complete Governance reporting-year evidence and referenced
current register observations are read on that same connection. The shared
capture/admission policy rebuilds the source freshness context. A change during
preflight prevents the consumer from reaching its decision write.

The yielded scope expires on context exit. Consumers must persist their decision
before exiting it; an admitted value retained afterward grants no authority.
`PostgresCorporateReportingEvidence` delegates to the narrow Governance public
projection, which requires the caller's already held exact company guard and
combines complete lifecycle, capital history and Ledger amendment projections.
It grants RF no cross-owner table access. Object and provider I/O stay outside.

This internal scope is not yet wired to an approval/send route. Full-year profile,
review/permission, entitlement, immutable bridge, approval persistence, submission
head/correction admission and journal integration remain required. Unit tests
exercise policy and scope lifetime; actual database permission/concurrency tests
must run in CI before runtime behavior is considered verified.


The full-year review bridge retains the exact source-preview ID, source/hash
binding, text, issues and XML under the existing filing-review identity without
an opening setup. Arbitrary shareholder IDs map to the versioned manifest's
stable hashed journal keys. It is immutable, tenant-scoped, and replayable only
while its original source remains current. Historical review reads remain
available after a source correction. The application materializes it within
source admission, after retained-byte and complete Governance checks.

The bridge itself enables review only. Legacy approval rejects the full-year
marker. The dedicated full-year approval command enters fresh source admission,
requires exact active pilot/Authority identity and current review/permission,
and appends the canonical manifest with immutable source and raw review bindings.
The review and append share the company/year guard. Exact replay rechecks current
admission; changed review requires renewed confirmation. Historical archives
rebuild full-year manifests from retained lineage without consulting current
source heads. Full-year provider dispatch remains blocked pending its guarded application
composition and journal integration. Claims and correction validation are described below. The legacy stored
readiness prerequisite remains until its owned full-year replacement is ready.
Rollback suspends new approvals while preserving evidence and send barriers.

`Rf1086SourceApprovalReview` exposes the exact point-in-time review commitment,
warning codes and blockers. `Rf1086ArchiveSourceReviewBridge` and
`Rf1086ArchiveSourceApprovalLineage` retain the bridge, source, preview and exact
approved manifest/review text needed to verify a historical full-year approval.

Correction approval reverifies the exact previous terminal filing, manifest,
reconciliation event and artifact set. Documents checks each private original
before admission; the final RF transaction locks the predecessor and compares
that complete snapshot and retained receipts before writing approval. Journal
writers acquire the company guard before their submission row locks.

Versioned source-readiness evidence binds the selected source and canonical
preview after guarded freshness checks. It explicitly leaves annual
prerequisites, current review/overrides, Authority, Billing and technical release
unevaluated. It does not replace the legacy stored release gate yet.

The held source-admission transaction can read Banking-owned
`BankYearReconciliationEvidence` through `bank_year_evidence`. This keeps the
exact canonical transaction digest and observation on the same company guard,
without private Banking table access or a separate connection. It is a producer
input for annual readiness; counts/digests do not prove bank-statement coverage
and are not yet a replacement for the stored annual gate.

`annual_interview` reads the frozen annual-data history API on that same held
connection, then selects only the requested company/year. Earlier interviews
cannot satisfy current prerequisites. Duplicate identities/years, malformed
scope, timestamps or prerequisite booleans fail closed; an empty successful
enumeration remains distinct from unavailable evidence. The view is deeply
immutable. This consumer does not change the history reader's at-or-before-year
semantics, browser permissions or interview writers. The read still grants no
filing authorization; annual policy composition remains pending.

The correction contract is `Rf1086CorrectionPredecessorSnapshot`, verified by
`assert_rf1086_correction_predecessor`. Source assessment exports
`Rf1086SourceReadinessEvidence`, `Rf1086SourceReadinessProof`,
`build_rf1086_source_readiness` and `assert_rf1086_source_readiness_matches`.

`assert_rf1086_submission_predecessor` checks the complete company/year production
history before full-year approval. An initial approval requires empty history;
a correction requires the exact terminal leaf of one complete linear chain.
Duplicate identities, forks, competing roots, missing parents, cycles and
unresolved outcomes fail. The adapter enumerates all submitters and profiles
under the admission scope's company/year guards; it never chooses by timestamp.
Original feedback and canonical manifest verification remain separate required
checks. This approval check does not create the durable submission head or
submit-once claim, which remain required before full-year sending opens.

### Durable full-year submission claim

Migration `20260928060732_rf1086_source_submission_claim.sql` retains immutable
`source_submission_bindings` and one `submission_heads` row per company, year,
obligation and production environment. The guarded database command binds the
exact approved manifest and predecessor, checks every retained filing as one
complete chain, then inserts the claim and journal row and advances the head in
one transaction. Forks, disconnected history, stale predecessors and unresolved
outcomes fail closed. The company/year guards precede head/parent rows and the
Authority/Billing revalidation performed by the approval validator.

An exact historical lookup remains available after approval invalidation or
pilot expiry. Replay returns the existing claim without authorizing another
provider POST. Legacy begin rejects source approvals, and a managed head blocks
new unmanaged legacy insertions. Existing legacy approval replay remains valid.
The immutable binding authorizes only matching full-year journal rows; ordinary
journal status changes preserve their original payload and predecessor.

Rollback revokes the new claim command but retains heads, claims and historical
visibility. Replay the claim successor after the review/approval predecessors.
The existing production submission generation trigger records claim insertion
in the same transaction. Full-year application dispatch, owned annual readiness,
original-byte revalidation at send remain required
before enabling the full-year send path; this database foundation does not expose
an HTTP send command or activate production.

`Rf1086RetainedSourceApproval` carries the approval record and exact canonical
manifest text. `inspect_rf1086_retained_source_approval` verifies its identity
before source admission. `Rf1086SourceSubmissionClaim` retains the immutable
approval, payload, actor and predecessor identity;
`assert_rf1086_source_submission_claim` validates that identity on every read.
`Rf1086SourceSubmissionClaimResult` distinguishes a new claim from historical
recovery. Recovery never grants a second provider dispatch.

The application claim workflow derives scope, preview and entitlement from the
retained approval. It verifies original bytes before admission, then rechecks
approval, complete history, correction receipts, source, Governance and review
on the guarded connection before rebuilding the exact manifest and claiming.
Retries first recover retained claims without demanding current source or pilot
freshness. A concurrent commit can also be recovered after failed admission.
This workflow has no provider binding and is not exposed as an HTTP send route.

Full-year correction predecessors now retain `source_approval_lineage` and
`source_claim` in `Rf1086CorrectionPredecessorSnapshot`. The validator rebuilds
the original source preview and canonical approval from retained review evidence,
checks the immutable claim's scope, actor, payload, manifest and parent, then
requires matching terminal feedback artifacts and reconciliation. Legacy
predecessors cannot carry source-only lineage. The adapter loads both forms on
the caller's snapshot or guarded connection; it never substitutes current source
or review inputs for captured history. The application still verifies feedback
originals before the guard and compares the complete snapshot and original
receipts inside it. Bound feedback artifacts read their exact historical Documents
original before locking, including captured metadata and byte verification. Final
admission compares the complete predecessor snapshot and asserts that same receipt
under the company guard. Current document changes cannot substitute a newer
original. Unbound legacy feedback retains its existing current-evidence check;
this does not backfill missing historical bindings. This predecessor support does
not open provider dispatch.

The production archive now includes `source_submission_claims` and the scoped
`Rf1086SubmissionHead` from the same database snapshot as original approvals and
journal rows. Full-year records require exactly matching immutable claims and a
complete linear history ending at that head. Their journal mutation names, XML
hashes and persistent idempotency keys must match the approved source document
order; terminal submissions require successful document posts and confirmation
as well as retained reconciliation/artifact evidence. Unknown outcomes remain
unknown in the export. The API exposes claim/head DTOs without granting send
authority, and legacy-only archives preserve their existing shape plus empty
claim/head fields. This is RF archive source coverage; company-wide retention
generation and consolidated backup/restore validation still require separate proof.

`serialize_rf1086_archive` and `parse_rf1086_archive` provide the closed
`rf1086-production-archive-v3` record carried as `canonicalArchive` when feedback
original bindings are present. Existing v1 and v2 records remain byte-for-byte
round-trippable; v1 records
explicitly lack the complete source-history capture. This preserves complete captured sources, freshness and
Governance receipts, previews, review bridges, approvals, claims, heads, journals
and feedback metadata. The parser checks the expected company/year and reuses RF
source, approval and history validation. It preserves original numeric types and
XML, rejects unknown record types, duplicate fields, nonfinite values, oversized
records and invalid commitments, and never deserializes executable classes.

`Rf1086ArchiveError` reports a closed integrity diagnostic. Records are bounded
to 64 MiB; the command-line input file is bounded to 256 MiB.
The nested snapshot text has an accidental-damage checksum; it is not an external
signature. Parsing grants no identity, live freshness, database restore or send
authority. The local `apps/backend/scripts/verify_rf1086_archive.py` verifier reads
this authoritative record from either an API export or a company download. It
performs no database/provider calls and does not prove retained object bytes.
V2 captures every source version, the source head, every independent register
observation and correction, source previews (including blocked/unbridged work),
and review bridges on the same repeatable database snapshot as filing history.
Capture records retain the original storage text, idempotency key and request
hash. Validation rejects missing/forked chains, inconsistent heads, orphaned
previews/bridges, changed capture records and incompatible approved lineage.
Historical unapproved renderer output is preserved rather than regenerated.
This is an export, not a database backup or completed restoration.


The production archive composition additionally exports `sourceOriginals` via
Documents' public historical-recovery and portable-record contracts. Exact
versions are deduplicated by document/company/source year and metadata/content
commitments, not document ID alone. Current metadata and current-year document
lists cannot replace the captured version. Original lookup requires an accepted
owner with AAL2 and the same verified actor as the RF session. Missing or changed
originals fail the complete archive response before it can be downloaded.
The inline bundle permits at most 128 MiB of combined source and feedback
original bytes; larger bundles fail closed and need a future streaming transport.
Unrelated company-document byte bundles and actual restore remain separate work. The offline verifier's `--require-source-originals` flag
requires every captured source version and validates each with Documents policy;
it reports source-byte verification separately from database/object restoration.

Source originals now cover every v2 source and observation, including unapproved
work, while v1 retains its approved-lineage requirements. The offline verifier's
`--require-source-history` rejects older partial records; history counts and
source-byte verification are reported separately. No restore/write authority is
created by decoding either version.

`Rf1086ArchiveSourceHistory` groups the complete source and observation snapshots,
`Rf1086ArchiveYearSourceHead`, all retained `Rf1086ArchiveSourcePreview` records,
and review bridges. `Rf1086ArchiveCaptureRecord` binds each source/observation to
its original stored text, request hash and actor-scoped idempotency key.


For newly uploaded authority feedback, the adapter requires Documents-owned
verification and immutable-original retention before recording RF artifact
metadata. It checks the receipt against the exact uploaded document metadata and
content commitments. Ambiguous retention failures preserve the uploaded record
without acknowledging RF metadata. The owned
`record_retained_feedback_artifact_v1` writer reasserts the exact Documents
receipt under the company guard, then atomically stores the artifact and its
original ID, metadata digest, source year and retention timestamp. Bound rows
reject mutation. Existing canonical artifacts keep their attribution and legacy
null bindings; legacy backfill remains separate work.

Bound feedback records export their original ID, metadata digest, source year and
retention time in the v3 canonical record and transport projection. The
`feedbackOriginals` bundle contains the Documents-owned original bytes and metadata.
Export, download and offline verification require an exact receipt match, submission
link, uploader attribution and content commitments. Current bucket metadata cannot
replace or invalidate this retained version. Web checks compare bindings with the
canonical record and preserve submillisecond timestamp precision.

`--require-feedback-originals` requires retained bytes for every feedback artifact;
older unbound artifacts fail that strict check. Without the flag, legacy records
remain readable and the verifier reports partial feedback coverage. Verification
of supplied bytes grants no independent authenticity, provider or restoration
authority. Both v1 and v2 records keep their original codec and bytes.


`prepare_rf1086_source_reconciliation` reconstructs read-only feedback input for
confirmed full-year submissions from the validated canonical archive. It checks
the authenticated submitter, retained approval and claim, complete original
journal, exact confirmation/dialog identity and the immutable source preview.
The returned input retains the approved `source_*` document keys and original XML;
current source facts cannot substitute for the claimed payload.

The authenticated recovery workflow supports both production profiles. Full-year
recovery reads this retained snapshot after obtaining its feedback lease and
before acquiring a read-only authority token. It retains accepted-owner and exact
historical entitlement/connection checks but permits revoked or expired pilots
and invalidated approvals to recover their already-confirmed submission. Archive
failure or changed evidence releases the lease without a provider call. An
unconfirmed unknown mutation still cannot be replayed or treated as confirmed.
The legacy send entry explicitly rejects full-year approvals; owned readiness and
full-year dispatch remain separate work.


The RF admission scope also reads Ledger-owned opening-bank inputs and complete
period-lock history on its held connection, through the unchanged Ledger public
queries. The application selects the exact reporting year only after all pages
complete; cursor cycles, inconsistent extents, duplicate identities and foreign
company facts are unavailable. Missing current-year inputs stay empty instead of
reusing another year. The immutable result preserves Ledger Money values (its existing two-decimal normalization),
original identities and attribution. It is not a company-year close assessment, statement coverage or
RF readiness decision. Only two existing read EXECUTE grants are added. Rollback
disables those calls while retaining harmless namespace visibility; historical
rehearsal restores the grants after Ledger/RF function recreation.

`annual_document_inputs` enumerates active Documents metadata through the unchanged
Documents owner query on the held admission connection, then selects the exact
company/year. It preserves statuses and original metadata; staged, quarantined
and accepted-missing records are not silently discarded. Inconsistent scope,
duplicate identities, removed records or malformed metadata fail closed. No
object download occurs while holding the company guard. This projection proves
neither original-byte integrity nor filing readiness. The only new database
authority is EXECUTE on `documents.list_documents_v1(uuid[],text)`; rollback
revokes it and historical rehearsal restores it after owner function recreation.

`annual_opening_inputs` reads RF's existing opening and shareholder owner queries
inside source admission. It retains exact company/year, snapshot identity and a
versioned digest of every opening/holder field, including lock time and original
attribution. Missing openings remain distinct from malformed or quarantined
records. Duplicate parents/holders, mismatched scope, missing lock timestamps,
non-finite capital or inconsistent share totals fail closed. This digest is
separate from the legacy opening-rendering source digest. The projection does
not render a no-activity case or equate an onboarding snapshot with the statutory
start-of-year capital of a newly formed company. No SQL grant or writer changes.

### Annual prerequisite proof

`Rf1086AnnualReadinessInputs` carries scoped, complete owner projections and all
five family evidence digests; `Rf1086AnnualDocumentStatus` retains document
identity, linkage and status for RF policy. `build_rf1086_annual_readiness` binds
these inputs to the exact source/preview in `Rf1086AnnualReadinessProof`.
`assert_rf1086_annual_readiness_matches` rebuilds the entire proof, including
issues, required/accepted warnings and explicit unevaluated release families.
The application reads each owner sequentially on the held admission connection.
Banking observation time is excluded from proof identity; changes to canonical
facts or other owner metadata change the proof even when counts remain equal.

Annual hard conditions include locked opening, matching Ledger opening-bank
identity, unmatched unaccepted transactions, unsupported unpaid items and annual
authority confirmation. Period/interview/bank-confirmation warnings remain
unaccepted until a later explicit acknowledgement. Missing interview preserves
RF's existing warning behavior. Missing interview answer keys retain their
existing false defaults; present non-boolean answers are unavailable. Accepted
missing-document status is retained as an accepted warning. Canonical ASCII RF
linkage, Norwegian linkage and RF-1086 labels all select the obligation. Unknown
or removed document statuses fail closed at the input boundary.

This is a read-only point-in-time prerequisite assessment. Review/overrides,
current Authority permission, Billing, technical signoffs and warning acceptance
remain independent release checks. Consequential consumers must rebuild under
their own held guard; the proof alone grants no permission to approve or send.

`serialize_rf1086_annual_readiness` and `parse_rf1086_annual_readiness` retain a
closed, canonical proof encoding and replay RF policy against the exact retained
source/preview. Noncanonical bytes, duplicate/unknown fields, foreign scope and
changed derived policy fail closed. A manifest basis with `annual_readiness`
produces `production-source-approval-v2`, binding both the policy digest and exact
proof bytes. Blocked annual proofs cannot produce approval manifests; every
required warning must be acknowledged. The XML/document order and production
adapter version stay unchanged. A basis without annual evidence retains exact
V1 manifest bytes for historical recovery.

V2 archives rebuild the retained annual proof without current owner queries. A
matching `rf1086-source-review-v2` records the same annual binding,
`otherOverridesReady` and the independent technical gate; V1 archives retain
their original stored-release review contract. Claim identity inspection accepts
both manifest versions, but does not grant freshness or dispatch authority.
Live full-year review, approval and first claim use V2. The thin workflow reads
all annual owners again inside held source admission and passes only its
server-computed proof to persistence. No request accepts annual proof bytes or a
caller ready flag. SQL commits the exact proof with current authorization and
review, validates its source/preview scope and requires first-claim proof bytes
to equal the retained approval. A changed annual digest requires a new approval,
even if the XML and warning set are unchanged. The adapter revalidates the proof
codec against the held source/preview before passing it to SQL.

The old browser-written stored-ready prerequisite no longer decides new full-year
approval or claim. Its non-RF blocking-override predicate is preserved through
`backend_system.rf1086_other_overrides_ready_v1`, with the existing receiver owner
and current member check. RF overrides/comments, Authority/Billing, post-wait MFA
and technical signoffs remain independent gates. Annual policy stays in RF Python;
SQL enforces persistence, identity and authorization, not a second policy engine.

V1 full-year effect RPC grants are revoked. Unclaimed V1 approvals need fresh V2
approval; exact committed claims and historical archives remain recoverable.
Rollback suspends new V2 effects, leaves V1 effects closed and preserves history.
Mandatory successor replay restores V2 after historical migrations. Provider
send remains unexposed pending profile-specific dispatch and recovery.


### Retained dispatch position and uncertain attempts

`assess_rf1086_source_dispatch` returns `Rf1086SourceDispatchAssessment` and reconstructs the exact immutable payload, source
keys, document order, durable claim and journal position from the validated
archive. It produces no provider authority. Unstarted V2 operations require
current admission; a retryable failure requires a new durable retry admission
using its original key. A prepared operation without a committed outcome is
uncertain, just like an explicit unknown result. Neither may be automatically
repeated. Attempt 20 and explicitly blocked failures cannot retry. Unstarted V1
claims require current approval rather than obtaining authority from recovery.

The assessment rejects gaps, conflicting outcomes, duplicate intents, retries
after success/unknown/block, backward attempt timestamps, and downstream
mutations without predecessor success. Original successful outcomes without a
prepared row remain readable for historical imports. Confirmed feedback recovery
now applies these checks before acquiring a read-only provider binding. The
archive codec remains unchanged; these stricter checks govern recovery use.

The next dispatch step must commit its initial/retry intent under current source,
annual and authorization admission before network I/O. This assessment is a
read-only position, not that admission; full-year provider dispatch remains closed.


### Durable source operation intent

`Rf1086SourceOperationPreparation` reports the persisted journal event and whether
this transaction created it. The backend-only `prepare_source_operation_v1`
serializes company/year and submission scope, checks original claim/manifest,
operation order, payload hashes and current owner/MFA, Authority, Billing,
permission, overrides and technical release gates. Before the main POST it also
requires current annual evidence and the exact approved review. Continuation
retains the originally approved bytes even if today's annual facts change.

Initial and retry intents commit before network I/O. A retry retains the original
key and increments the persisted attempt exactly once. A competing request sees
the existing intent and receives no new dispatch grant. Prepared, unknown,
blocked and exhausted attempts never grant an automatic retry. The generic
legacy mutation commands reject full-year operations, including trimmed names.

`finish_source_operation_v1` records only an exact prepared mutation's outcome.
Exact replay is idempotent; contradictory outcomes and stale intent IDs fail.
Recording a completed request does not require the earlier MFA or entitlement
to remain fresh. Rollback suspends preparation while preserving this outcome
recording and historical recovery. No new tables or archive codecs are added.
Application dispatch integration and provider interaction remain unexposed.


`Rf1086SourceOperationJournal` binds each admitted intent and exact outcome.
`execute_rf1086_source_dispatch` consumes its `newly_prepared` result explicitly;
an old retryable failure never becomes a send grant. The application
source-dispatch component of `shareholder-register-filing` verifies retained archive/claim
identity, acquires and discards the provider binding outside database admission,
commits current annual evidence for the main document, and preserves approved
bytes during subsequent current-authority admissions. It performs no provider
mutation while a database guard is held. A generic transport or persistence
exception leaves an unknown outcome. No full-year HTTP route is composed yet.

Migration `20260929192057_rf1086_dispatch_binding_identity.sql` binds the exact
credential request/external identity to each intent under Authority/Billing locks.
It closes the older prepare RPC; rollback also keeps that bypass closed while
preserving in-flight completion. Tests cover simulated dispatch/crash behavior,
exact replay, and database binding changes without actual provider credentials.
