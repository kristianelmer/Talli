import type {
  Rf1086PreviewWire,
  Rf1086SimulationWire,
  Rf1086OverrideWire,
  Rf1086ReviewCommentWire,
  Rf1086PermissionWire,
  Rf1086TestEvidenceWire,
  Rf1086ApprovalWire,
  Rf1086ProductionSubmissionWire,
  Rf1086FeedbackArtifactWire,
} from "@talli/talli-api-client";

export function presentRf1086Preview(value: Rf1086PreviewWire) {
  return {
    company_id: value.companyId,
    created_at: value.createdAt,
    filing: value.filing,
    hovedskjema_xml: value.hovedskjemaXml,
    id: value.id,
    income_year: value.incomeYear,
    issues: value.issues,
    preview: value.preview,
    setup_id: value.setupId,
    source: value.source,
    status: value.status,
    underskjema_xml: value.underskjemaXml,
  };
}

export function presentRf1086Simulation(value: Rf1086SimulationWire) {
  return {
    adapter_mode: value.adapterMode,
    authority_confirmed_at: value.authorityConfirmedAt,
    authority_test_run_id: value.authorityTestRunId,
    calls: value.calls.map((call) => ({
      endpoint: call.endpoint, body_hash: call.bodyHash, idempotency_key: call.idempotencyKey,
      status: call.status, created_at: call.createdAt,
    })),
    company_id: value.companyId,
    created_at: value.createdAt,
    feedback_document_ids: value.feedbackDocumentIds,
    feedback_items: value.feedbackItems,
    filing: value.filing,
    id: value.id,
    idempotency_key: value.idempotencyKey,
    income_year: value.incomeYear,
    mode: value.mode,
    payload_hash: value.payloadHash,
    preview_confirmed_at: value.previewConfirmedAt,
    preview_id: value.previewId,
    receipt_id: value.receiptId,
    receipt_metadata: value.receiptMetadata,
    status: value.status,
    submitted_by: value.submittedBy,
    submitted_payload: value.submittedPayload,
    submitted_payload_ref: value.submittedPayloadRef,
    updated_at: value.updatedAt,
  };
}

export function presentRf1086Override(value: Rf1086OverrideWire) {
  return {
    company_id: value.companyId,
    created_at: value.createdAt,
    created_by: value.createdBy,
    field_target: value.fieldTarget,
    filing: value.filing,
    id: value.id,
    income_year: value.incomeYear,
    new_value: value.newValue,
    old_value: value.oldValue,
    owner_confirmed_at: value.ownerConfirmedAt,
    owner_confirmed_by: value.ownerConfirmedBy,
    preview_id: value.previewId,
    reason: value.reason,
    risk_level: value.riskLevel,
  };
}

export function presentRf1086ReviewComment(value: Rf1086ReviewCommentWire) {
  return {
    acknowledged_at: value.acknowledgedAt,
    acknowledged_by: value.acknowledgedBy,
    body: value.body,
    company_id: value.companyId,
    created_at: value.createdAt,
    created_by: value.createdBy,
    id: value.id,
    preview_id: value.previewId,
    severity: value.severity,
    target: value.target,
  };
}

export function presentRf1086Permission(value: Rf1086PermissionWire) {
  return {
    company_id: value.companyId,
    confirmed_at: value.confirmedAt,
    confirmed_by: value.confirmedBy,
    id: value.id,
    obligation: value.obligation,
    production_enabled: value.productionEnabled,
    submitter_user_id: value.submitterUserId,
    updated_at: value.updatedAt,
  };
}

export function presentRf1086TestEvidence(value: Rf1086TestEvidenceWire) {
  return {
    archive_reference: value.archiveReference,
    company_id: value.companyId,
    environment: value.environment,
    evidence_url: value.evidenceUrl,
    feedback_summary: value.feedbackSummary,
    id: value.id,
    obligation: value.obligation,
    payload_hash: value.payloadHash,
    receipt_reference: value.receiptReference,
    recorded_at: value.recordedAt,
    recorded_by: value.recordedBy,
    status: value.status,
    test_reference: value.testReference,
  };
}

export function presentRf1086Approval(value: Rf1086ApprovalWire) {
  return {
    adapter_version: value.adapterVersion,
    approved_at: value.approvedAt,
    approved_by: value.approvedBy,
    case_profile: value.caseProfile,
    company_id: value.companyId,
    entitlement_id: value.entitlementId,
    id: value.id,
    income_year: value.incomeYear,
    invalidated_at: value.invalidatedAt,
    invalidation_reason: value.invalidationReason,
    manifest: value.manifest,
    manifest_hash: value.manifestHash,
    obligation: value.obligation,
    payload_hash: value.payloadHash,
    preview_id: value.previewId,
    user_id: value.userId,
  };
}

export function presentRf1086ProductionSubmission(value: Rf1086ProductionSubmissionWire) {
  return {
    adapter_version: value.adapterVersion,
    approval_id: value.approvalId,
    authority_references: value.authorityReferences,
    case_profile: value.caseProfile,
    company_id: value.companyId,
    created_at: value.createdAt,
    entitlement_id: value.entitlementId,
    environment: value.environment,
    failure_class: value.failureClass,
    feedback_artifact_count: value.feedbackArtifactCount,
    feedback_correlation_id: value.feedbackCorrelationId,
    feedback_last_changed_at: value.feedbackLastChangedAt,
    feedback_last_checked_at: value.feedbackLastCheckedAt,
    feedback_safe_error_code: value.feedbackSafeErrorCode,
    feedback_state: value.feedbackState,
    id: value.id,
    income_year: value.incomeYear,
    obligation: value.obligation,
    payload_hash: value.payloadHash,
    status: value.status,
    submitted_by: value.submittedBy,
    supersedes_submission_id: value.supersedesSubmissionId,
    updated_at: value.updatedAt,
    user_id: value.userId,
  };
}

export function presentRf1086FeedbackArtifact(value: Rf1086FeedbackArtifactWire) {
  return {
    byte_length: value.byteLength,
    classification: value.classification,
    company_id: value.companyId,
    content_type: value.contentType,
    document_id: value.documentId,
    id: value.id,
    retrieved_at: value.retrievedAt,
    sha256: value.sha256,
    submission_id: value.submissionId,
  };
}
