import type {
  CompanyTaxPreviewWire, CompanyTaxSubmissionWire, CompanyTaxOverrideWire,
  CompanyTaxReviewCommentWire, CompanyTaxPermissionWire, CompanyTaxTestEvidenceWire,
} from "@talli/talli-api-client";

function text(value: Record<string, unknown>, key: string): string {
  const field = value[key];
  if (typeof field !== "string") throw new Error("Tax filing source is incomplete.");
  return field;
}
function nullableText(value: Record<string, unknown>, key: string): string | null {
  return value[key] === null ? null : text(value, key);
}
function integer(value: Record<string, unknown>, key: string): number {
  const field = value[key];
  if (typeof field !== "number" || !Number.isSafeInteger(field)) throw new Error("Tax filing source is incomplete.");
  return field;
}
function strings(value: Record<string, unknown>, key: string): string[] {
  const field = value[key];
  if (!Array.isArray(field) || field.some(item => typeof item !== "string")) throw new Error("Tax filing source is incomplete.");
  return field;
}
function receipt(value: Record<string, unknown> | null) {
  if (value === null) return null;
  const authority = value.authority;
  const status = value.status;
  const dataType = value.dataType;
  const contentType = value.contentType;
  if (authority !== "skatteetaten" || status !== "feedback_ready" || dataType !== "tilbakemelding"
      || (contentType !== "application/xml" && contentType !== "text/xml")) throw new Error("Tax filing receipt is incomplete.");
  return { ...value, authority, status, dataType, contentType,
    receiptId: text(value, "receiptId"), receivedAt: text(value, "receivedAt"),
    feedbackDocumentIds: strings(value, "feedbackDocumentIds"), byteLength: integer(value, "byteLength"),
    contentSha256: text(value, "contentSha256"), reference: text(value, "reference"),
    archiveReference: text(value, "archiveReference"), processEndedAt: text(value, "processEndedAt"),
    archivedAt: text(value, "archivedAt"),
  } as const;
}
function payloadReference(value: Record<string, unknown> | null) {
  if (value === null) return null;
  return { ...value, companyOrgNumber: text(value, "companyOrgNumber"), incomeYear: integer(value, "incomeYear"),
    envelopeDataId: text(value, "envelopeDataId"), archiveReference: text(value, "archiveReference"),
    payloadHash: text(value, "payloadHash"), skattemeldingHash: text(value, "skattemeldingHash"),
    naeringsspesifikasjonHash: text(value, "naeringsspesifikasjonHash"), validationEnvelopeHash: text(value, "validationEnvelopeHash"),
    submissionEnvelopeHash: text(value, "submissionEnvelopeHash"), currentDocumentReferenceHash: text(value, "currentDocumentReferenceHash"),
    storedAt: text(value, "storedAt"),
  };
}

export function presentCompanyTaxPreview(value: CompanyTaxPreviewWire) {
  return { id: value.id, company_id: value.companyId, setup_id: value.setupId, income_year: value.incomeYear,
    filing: value.filing, status: value.status, preview: value.preview, hovedskjema_xml: value.hovedskjemaXml,
    underskjema_xml: value.underskjemaXml, source: value.source, created_by: value.createdBy, created_at: value.createdAt,
    issues: value.issues.map(issue => ({ ...issue, level: text(issue, "level"), code: text(issue, "code"), message: text(issue, "message") })),
  };
}
export function presentCompanyTaxSubmission(value: CompanyTaxSubmissionWire) {
  if (value.submittedPayload !== null) throw new Error("Tax filing source contains an unsupported raw payload.");
  return { id: value.id, preview_id: value.previewId, authority_test_run_id: value.authorityTestRunId,
    company_id: value.companyId, setup_id: value.setupId, income_year: value.incomeYear, filing: value.filing,
    mode: value.mode, adapter_mode: value.adapterMode, payload_hash: value.payloadHash, idempotency_key: value.idempotencyKey,
    status: value.status, authority_confirmed_by: value.authorityConfirmedBy, authority_confirmed_at: value.authorityConfirmedAt,
    preview_confirmed_by: value.previewConfirmedBy, preview_confirmed_at: value.previewConfirmedAt,
    calls: value.calls.map(call => ({ ...call, endpoint: text(call, "endpoint"), body_hash: text(call, "body_hash"),
      idempotency_key: nullableText(call, "idempotency_key"), status: text(call, "status"), created_at: text(call, "created_at") })),
    receipt_id: value.receiptId, feedback_document_ids: value.feedbackDocumentIds,
    feedback_items: value.feedbackItems.map(item => {
      const severity = item.severity;
      if (severity !== "accepted" && severity !== "error" && severity !== "warning") throw new Error("Tax filing feedback is incomplete.");
      return { ...item, severity, code: text(item, "code"), message: text(item, "message"), documentId: nullableText(item, "documentId") } as const;
    }),
    receipt_metadata: receipt(value.receiptMetadata), submitted_payload_ref: payloadReference(value.submittedPayloadRef),
    submitted_payload: null, failure_code: value.failureCode, failure_message: value.failureMessage,
    created_by: value.createdBy, submitted_by: value.submittedBy, created_at: value.createdAt, updated_at: value.updatedAt,
  };
}
export function presentCompanyTaxOverride(value: CompanyTaxOverrideWire) {
  return { id: value.id, preview_id: value.previewId, company_id: value.companyId, income_year: value.incomeYear,
    filing: value.filing, field_target: value.fieldTarget, old_value: value.oldValue, new_value: value.newValue,
    reason: value.reason, risk_level: value.riskLevel, owner_confirmed_by: value.ownerConfirmedBy,
    owner_confirmed_at: value.ownerConfirmedAt, created_by: value.createdBy, created_at: value.createdAt };
}
export function presentCompanyTaxComment(value: CompanyTaxReviewCommentWire) {
  return { id: value.id, preview_id: value.previewId, company_id: value.companyId, target: value.target,
    severity: value.severity, body: value.body, created_by: value.createdBy, acknowledged_by: value.acknowledgedBy,
    acknowledged_at: value.acknowledgedAt, created_at: value.createdAt };
}
export function presentCompanyTaxPermission(value: CompanyTaxPermissionWire) {
  return { id: value.id, company_id: value.companyId, obligation: value.obligation, submitter_user_id: value.submitterUserId,
    confirmed_by: value.confirmedBy, confirmed_at: value.confirmedAt, production_enabled: value.productionEnabled, updated_at: value.updatedAt };
}
export function presentCompanyTaxTestEvidence(value: CompanyTaxTestEvidenceWire) {
  return { id: value.id, company_id: value.companyId, obligation: value.obligation, environment: value.environment,
    status: value.status, test_reference: value.testReference, feedback_summary: value.feedbackSummary,
    receipt_reference: value.receiptReference, archive_reference: value.archiveReference, evidence_url: value.evidenceUrl,
    payload_hash: value.payloadHash, recorded_by: value.recordedBy, recorded_at: value.recordedAt };
}
