# Shareholder register filing

<!-- architecture-inventory
{"dependencies":[],"ownedTables":["shareholder_register_filing.authority_permissions","shareholder_register_filing.authority_test_runs","shareholder_register_filing.filing_approval_snapshots","shareholder_register_filing.filing_overrides","shareholder_register_filing.filing_previews","shareholder_register_filing.filing_review_comments","shareholder_register_filing.filing_submissions","shareholder_register_filing.opening_balance_setups","shareholder_register_filing.opening_shareholders","shareholder_register_filing.production_feedback_artifacts","shareholder_register_filing.production_filing_events","shareholder_register_filing.production_filing_submissions"],"ports":["OpeningSnapshotPersistence","ProductionOperationJournal","Rf1086MutationAuthority","Rf1086PreparationPersistence","Rf1086ProductionJournal","Rf1086ReadOnlyAuthority"],"publicEntryPoints":["talli_backend.modules.shareholder_register_filing.public"]}
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
remain explicit; source facts make no commercial refund decision.

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
