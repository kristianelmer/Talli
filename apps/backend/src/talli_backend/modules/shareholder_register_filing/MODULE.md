# Shareholder register filing

<!-- architecture-inventory
{"dependencies":[],"ownedTables":["shareholder_register_filing.authority_permissions","shareholder_register_filing.authority_test_runs","shareholder_register_filing.filing_approval_snapshots","shareholder_register_filing.filing_overrides","shareholder_register_filing.filing_previews","shareholder_register_filing.filing_review_comments","shareholder_register_filing.filing_submissions","shareholder_register_filing.opening_balance_setups","shareholder_register_filing.opening_shareholders","shareholder_register_filing.production_feedback_artifacts","shareholder_register_filing.production_filing_events","shareholder_register_filing.production_filing_submissions","shareholder_register_filing.year_source_heads","shareholder_register_filing.year_source_versions","shareholder_register_filing.register_observations"],"ports":["OpeningSnapshotPersistence","ProductionOperationJournal","Rf1086FeedbackDiscovery","Rf1086MutationAuthority","Rf1086PreparationPersistence","Rf1086ProductionJournal","Rf1086ReadOnlyAuthority","Rf1086YearSourcePersistence","Rf1086RegisterObservationPersistence"],"publicEntryPoints":["talli_backend.modules.shareholder_register_filing.public"]}
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
