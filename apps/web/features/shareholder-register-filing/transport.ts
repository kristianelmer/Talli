import {
  createTalliApiClient, TalliApiError,
  type Rf1086GeneratePreviewWire, type Rf1086OverrideCommandWire,
  type Rf1086ReviewCommentCommandWire, type Rf1086ReviewAcknowledgementWire,
  type Rf1086SimulationCommandWire, type Rf1086PermissionCommandWire,
  type Rf1086TestEvidenceCommandWire, type Rf1086ProductionApprovalCommandWire,
  type Rf1086RecordedResultWire, type Rf1086WorkspaceWire, type Rf1086ArchiveSourceWire,
  type Rf1086ProductionArchiveSourceWire,
  type RfSourcePreviewWire, type RfSourcePreviewRequestWire, type RfYearSourceReceiptWire,
  type RfYearSourceCaptureWire, type RfRegisterObservationCaptureWire,
  type RfCurrentYearSourceWire, type RfRegisterObservationsWire,
  type RfSourceProductionReviewRequestWire, type RfSourceProductionReviewWire,
  type RfSourceProductionApprovalCommandWire,
} from "@talli/talli-api-client";
import { backendBaseUrl } from "#backend-configuration";

function client(accessToken: string) {
  return createTalliApiClient({ baseUrl: backendBaseUrl(), headers: { Authorization: `Bearer ${accessToken}` } });
}
function request() { return { signal: AbortSignal.timeout(30_000) }; }
// Preserve the existing bounded, sequential RF send and initial feedback polling.
function authorityRequest() { return { signal: AbortSignal.timeout(300_000) }; }

function recorded(value: Rf1086RecordedResultWire, companyId?: string) {
  if (companyId !== undefined && value.companyId !== companyId) throw new TalliApiError(502, undefined);
  return value;
}

function scopedWorkspace(value: Rf1086WorkspaceWire, companyId: string, incomeYear?: number) {
  if (value.companyId !== companyId || value.incomeYear !== (incomeYear ?? null)) {
    throw new TalliApiError(502, undefined);
  }
  for (const rows of [value.previews, value.simulations, value.overrides, value.reviewComments,
    value.permissions, value.testEvidence, value.approvals, value.productionSubmissions, value.feedbackArtifacts]) {
    if (rows.some((row) => row.companyId !== companyId)
        || new Set(rows.map((row) => row.id)).size !== rows.length) throw new TalliApiError(502, undefined);
  }
  if (incomeYear !== undefined && [value.previews, value.simulations, value.overrides,
    value.approvals, value.productionSubmissions].some((rows) => rows.some((row) => row.incomeYear !== incomeYear))) {
    throw new TalliApiError(502, undefined);
  }
  return value;
}

export async function loadRf1086Workspaces(accessToken: string, companyIds: readonly string[], incomeYear?: number) {
  const api = client(accessToken);
  const results: Rf1086WorkspaceWire[] = [];
  // No year means all retained years; never substitute a current-year-only result.
  for (const companyId of new Set(companyIds)) {
    results.push(scopedWorkspace(await api.rf1086Workspace(companyId, incomeYear, request()), companyId, incomeYear));
  }
  return results;
}

export async function loadRf1086ArchiveSource(
  accessToken: string, companyId: string, incomeYear: number, requestId?: string,
): Promise<Rf1086ArchiveSourceWire | Rf1086ProductionArchiveSourceWire> {
  const api = client(accessToken);
  let value: Rf1086ArchiveSourceWire | Rf1086ProductionArchiveSourceWire;
  let usedLegacyFallback = false;
  try {
    value = await api.rf1086GetProductionArchiveSource(companyId, incomeYear, { ...request(), requestId });
  } catch (error) {
    // Only an absent expanded endpoint permits the original archive contract.
    // Its lack of production evidence is preserved, never interpreted as zero.
    if (!(error instanceof TalliApiError) || error.status !== 404) throw error;
    value = await api.rf1086GetArchiveSource(companyId, incomeYear, { ...request(), requestId });
    usedLegacyFallback = true;
  }
  if (value.companyId !== companyId || value.incomeYear !== incomeYear) throw new TalliApiError(502, undefined);
  for (const rows of [value.previews, value.simulations, value.reviewComments, value.permissions, value.testEvidence]) {
    if (rows.some((row) => row.companyId !== companyId)
        || new Set(rows.map((row) => row.id)).size !== rows.length) throw new TalliApiError(502, undefined);
  }
  if ([value.previews, value.simulations]
    .some((rows) => rows.some((row) => row.incomeYear !== incomeYear))) {
    throw new TalliApiError(502, undefined);
  }
  if (usedLegacyFallback) return value;
  if (!("productionSubmissions" in value)) throw new TalliApiError(502, undefined);
  for (const rows of [value.approvals, value.productionSubmissions, value.productionEvents, value.feedbackArtifacts]) {
    if (rows.some(row => row.companyId !== companyId)
        || new Set(rows.map(row => row.id)).size !== rows.length) throw new TalliApiError(502, undefined);
  }
  if ([value.approvals, value.productionSubmissions, value.productionEvents]
    .some(rows => rows.some(row => row.incomeYear !== incomeYear))) throw new TalliApiError(502, undefined);
  const approvalIds = new Set(value.approvals.map(row => row.id));
  const submissionIds = new Set(value.productionSubmissions.map(row => row.id));
  if (value.productionSubmissions.some(row => !approvalIds.has(row.approvalId)
      || (row.supersedesSubmissionId !== null && !submissionIds.has(row.supersedesSubmissionId)))
    || [...value.productionEvents, ...value.feedbackArtifacts].some(row => !submissionIds.has(row.submissionId))) {
    throw new TalliApiError(502, undefined);
  }
  return value;
}

export async function loadRf1086Preview(accessToken: string, previewId: string) {
  const result = await client(accessToken).rf1086Preview(previewId, request());
  if (result.id !== previewId) throw new TalliApiError(502, undefined);
  return result;
}

function isMissingRfRecord(error: unknown) {
  return error instanceof TalliApiError && error.status === 404
    && error.problem?.code === "SHAREHOLDER_REGISTER_FILING_NOT_FOUND";
}

export async function findRf1086Preview(accessToken: string, previewId: string) {
  try { return await loadRf1086Preview(accessToken, previewId); }
  catch (error) { if (isMissingRfRecord(error)) return null; throw error; }
}

export async function acknowledgeOwnedRf1086Comment(accessToken: string, commentId: string) {
  try { return await acknowledgeRf1086ReviewCommentThroughApi(accessToken, { commentId }); }
  catch (error) { if (isMissingRfRecord(error)) return null; throw error; }
}

export async function generateRf1086PreviewThroughApi(accessToken: string, body: Rf1086GeneratePreviewWire) {
  return recorded(await client(accessToken).rf1086GeneratePreview(body, request()), body.companyId);
}
export async function recordRf1086OverrideThroughApi(accessToken: string, body: Rf1086OverrideCommandWire) {
  return recorded(await client(accessToken).rf1086RecordOverride(body, request()));
}
export async function addRf1086ReviewCommentThroughApi(accessToken: string, body: Rf1086ReviewCommentCommandWire) {
  return recorded(await client(accessToken).rf1086AddReviewComment(body, request()));
}
export async function acknowledgeRf1086ReviewCommentThroughApi(accessToken: string, body: Rf1086ReviewAcknowledgementWire) {
  return recorded(await client(accessToken).rf1086AcknowledgeReviewComment(body, request()));
}
export async function confirmRf1086SimulationThroughApi(accessToken: string, body: Rf1086SimulationCommandWire) {
  return recorded(await client(accessToken).rf1086ConfirmSimulation(body, request()));
}
export async function confirmRf1086PermissionThroughApi(accessToken: string, body: Rf1086PermissionCommandWire) {
  return recorded(await client(accessToken).rf1086ConfirmFilingPermission(body, request()), body.companyId);
}
export async function recordRf1086TestEvidenceThroughApi(accessToken: string, body: Rf1086TestEvidenceCommandWire) {
  return recorded(await client(accessToken).rf1086RecordTestEvidence(body, request()), body.companyId);
}
export async function approveRf1086ProductionThroughApi(accessToken: string, body: Rf1086ProductionApprovalCommandWire) {
  return recorded(await client(accessToken).rf1086ApproveProduction(body, request()));
}
export async function sendApprovedRf1086ThroughApi(accessToken: string, approvalId: string) {
  return client(accessToken).legacyRf1086SendApprovedFiling({ approvalId }, authorityRequest());
}
export async function reconcileRf1086ThroughApi(accessToken: string, submissionId: string) {
  return client(accessToken).legacyRf1086ReconcileFeedback({ submissionId }, authorityRequest());
}


function sourceScope(value: { companyId: string; incomeYear: number }, companyId: string, incomeYear: number) {
  if (value.companyId !== companyId || value.incomeYear !== incomeYear) throw new TalliApiError(502, undefined);
}

function sourceReceipt(value: RfYearSourceReceiptWire, companyId: string, incomeYear: number) {
  sourceScope(value, companyId, incomeYear);
  if (value.version < 1 || !/^[a-f0-9]{64}$/.test(value.sourceSha256)
      || !/^[a-f0-9]{64}$/.test(value.caseSha256)) throw new TalliApiError(502, undefined);
  return value;
}

function sourceMutationRequest(idempotencyKey: string) {
  // The form/action owns attempt identity. This transport never generates or
  // replaces a key on retry, and never converts body amounts or civil times.
  if (typeof idempotencyKey !== "string" || !/^[A-Za-z0-9._:-]{16,255}$/.test(idempotencyKey)) {
    throw new TalliApiError(422, undefined);
  }
  return { ...request(), idempotencyKey };
}

export async function loadRf1086SourceIntakeBasis(accessToken: string, companyId: string, incomeYear: number) {
  const value = await client(accessToken).rf1086ReadSourceIntakeBasis({ ...request(), companyId, incomeYear });
  sourceScope(value, companyId, incomeYear);
  // Cross-year Governance originals are intentionally retained in this envelope.
  // Backend enumeration and blockers own completeness and eligibility policy.
  return value;
}

export async function loadRf1086CurrentYearSource(
  accessToken: string, companyId: string, incomeYear: number,
): Promise<RfCurrentYearSourceWire> {
  const value = await client(accessToken).rf1086ReadCurrentYearSource({ ...request(), companyId, incomeYear });
  if (value.currentSource === null) return value;
  const { receipt, draft } = value.currentSource;
  sourceReceipt(receipt, companyId, incomeYear);
  sourceScope(draft, companyId, incomeYear);
  if (draft.case.company.incomeYear !== incomeYear
      || draft.supersedesSourceId !== receipt.sourceId || draft.supersedesSourceSha256 !== receipt.sourceSha256
      || draft.identitiesReviewed || draft.completeYearConfirmed || draft.paidInReviewed || draft.noActivityConfirmed
      || draft.correctionReason !== null
      || draft.documents.some(document => document.companyId !== companyId)
      || new Set(draft.documents.map(document => document.documentId)).size !== draft.documents.length) {
    throw new TalliApiError(502, undefined);
  }
  return value;
}

export async function loadRf1086RegisterObservations(
  accessToken: string, companyId: string, incomeYear: number,
): Promise<RfRegisterObservationsWire> {
  const value = await client(accessToken).rf1086ListRegisterObservations({ ...request(), companyId, incomeYear });
  sourceScope(value, companyId, incomeYear);
  const ids = new Set<string>();
  for (const { receipt, draft, isCurrent } of value.observations) {
    sourceScope(receipt, companyId, incomeYear);
    sourceScope(draft, companyId, incomeYear);
    if (ids.has(receipt.observationId) || receipt.version < 1 || !/^[a-f0-9]{64}$/.test(receipt.factSha256)
        || typeof isCurrent !== "boolean" || draft.supersedesObservationId !== receipt.observationId
        || draft.supersedesObservationSha256 !== receipt.factSha256 || draft.correctionReason !== null
        || draft.completeRegisterConfirmed || draft.registrationConfirmed || draft.singleShareClassConfirmed
        || draft.documents.some(document => document.companyId !== companyId)
        || new Set(draft.documents.map(document => JSON.stringify([document.documentId, document.role]))).size
          !== draft.documents.length) throw new TalliApiError(502, undefined);
    ids.add(receipt.observationId);
  }
  // Independent lineages can each be current. Only the backend has the original
  // predecessor graph; preserve its currentness flags, including historical rows.
  return value;
}

export async function loadRf1086SourceDocument(accessToken: string, companyId: string, documentId: string) {
  const value = await client(accessToken).rf1086ReadSourceDocument(documentId, companyId, request());
  if (value.companyId !== companyId || value.documentId !== documentId) throw new TalliApiError(502, undefined);
  // Prior-year originals can substantiate the selected year; retain their year.
  return value;
}

export async function captureRf1086YearSourceThroughApi(
  accessToken: string, body: RfYearSourceCaptureWire, idempotencyKey: string,
) {
  const options = sourceMutationRequest(idempotencyKey);
  if (body.case.company.incomeYear !== body.incomeYear
      || body.documents.some(document => document.companyId !== body.companyId)) throw new TalliApiError(422, undefined);
  const value = sourceReceipt(await client(accessToken).rf1086CaptureYearSource(body, options), body.companyId, body.incomeYear);
  if (value.sourceId === body.supersedesSourceId) throw new TalliApiError(502, undefined);
  return value;
}

export async function captureRf1086RegisterObservationThroughApi(
  accessToken: string, body: RfRegisterObservationCaptureWire, idempotencyKey: string,
) {
  const options = sourceMutationRequest(idempotencyKey);
  if (body.documents.some(document => document.companyId !== body.companyId)) throw new TalliApiError(422, undefined);
  const value = await client(accessToken).rf1086CaptureRegisterObservation(body, options);
  sourceScope(value, body.companyId, body.incomeYear);
  if (value.version < 1 || !/^[a-f0-9]{64}$/.test(value.factSha256)
      || value.observationId === body.supersedesObservationId) throw new TalliApiError(502, undefined);
  return value;
}

function sourcePreview(value: RfSourcePreviewWire, companyId: string, incomeYear: number, sourceId: string) {
  sourceScope(value, companyId, incomeYear);
  if (value.sourceId !== sourceId || !/^[a-f0-9]{64}$/.test(value.sourceSha256)
      || !/^[a-f0-9]{64}$/.test(value.caseSha256)) throw new TalliApiError(502, undefined);
  return value;
}

export async function generateRf1086SourcePreviewThroughApi(accessToken: string, body: RfSourcePreviewRequestWire) {
  // This backend operation deliberately appends a preview; it does not offer
  // mutation-key replay. Keep it a separate owner action, without automatic retry.
  return sourcePreview(await client(accessToken).rf1086GenerateSourcePreview(body, request()),
    body.companyId, body.incomeYear, body.sourceId);
}

export async function loadRf1086SourcePreview(
  accessToken: string, companyId: string, incomeYear: number, sourceId: string, previewId: string,
) {
  const value = sourcePreview(await client(accessToken).rf1086ReadSourcePreview(previewId,
    { ...request(), companyId, incomeYear }), companyId, incomeYear, sourceId);
  if (value.previewId !== previewId) throw new TalliApiError(502, undefined);
  return value;
}

const sourceMessages: Record<string, string> = {
  rf1086_source_changed: "Årsgrunnlaget er endret. Last inn det lagrede grunnlaget på nytt før du fortsetter.",
  rf1086_source_predecessor_mismatch: "En nyere versjon er allerede lagret. Last inn årsgrunnlaget på nytt og vurder endringene.",
  rf1086_source_predecessor_required: "Det finnes allerede et årsgrunnlag. Last det inn og lagre endringen som en ny versjon.",
  rf1086_source_idempotency_conflict: "Dette lagringsforsøket er allerede brukt med andre opplysninger. Kontroller lagret status før du starter et nytt forsøk.",
  rf1086_source_correction_reason_required: "Beskriv hvorfor årsgrunnlaget skal korrigeres.",
  rf1086_source_owner_required: "En bekreftet eier av selskapet må åpne årsgrunnlaget.",
  rf1086_source_not_found: "Fant ikke årsgrunnlaget for dette selskapet og året.",
  rf1086_source_preview_not_found: "Fant ikke forhåndsvisningen for dette selskapet og året.",
  rf1086_source_document_not_found: "Fant ikke dokumentet i dette selskapet.",
  rf1086_source_documents_unverified: "Dokumentene kunne ikke bekreftes. Last inn originalene på nytt og kontroller vedleggene.",
  rf1086_source_register_original_changed: "Et originaldokument i aksjeeierboken er endret. Kontroller og bekreft dokumentasjonen på nytt.",
  rf1086_source_governance_unresolved: "Selskapet har selskapsbeslutninger eller korrigeringer som må avklares før årsgrunnlaget kan lagres.",
  rf1086_source_governance_events_omitted: "Alle rapporteringspliktige selskapsbeslutninger må være med i årsgrunnlaget.",
  rf1086_source_independent_register_unavailable: "Bekreft aksjeeierboken og registreringsdokumentasjonen for kapitalendringen først.",
  rf1086_source_governance_nominal_increase_unavailable: "Denne økningen av pålydende kan ikke bekreftes gjennom den tilgjengelige selskapsdokumentasjonen ennå.",
  rf1086_source_completeness_required: "Kontroller og bekreft at hele året, aksjonæridentitetene og innbetalt kapital er gjennomgått.",
  rf1086_source_no_activity_confirmation_mismatch: "Bekreftelsen om et år uten hendelser stemmer ikke med opplysningene. Kontroller hendelsene.",
  rf1086_source_paid_in_mismatch: "Innbetalt kapital og overkurs stemmer ikke med årsgrunnlaget. Kontroller beløpene og dokumentasjonen.",
};
const sourceValidationCodes = new Set([
  "rf1086_source_invalid_request", "rf1086_source_structure_invalid", "rf1086_source_contract_invalid",
  "rf1086_source_amount_invalid", "rf1086_source_identity_invalid", "rf1086_source_holder_identity_invalid",
  "rf1086_source_holder_identity_duplicate", "rf1086_source_case_not_ready", "rf1086_source_event_evidence_incomplete",
  "rf1086_source_event_evidence_mismatch", "rf1086_source_basis_evidence_missing", "rf1086_source_paid_in_required",
  "rf1086_source_signed_evidence_missing", "rf1086_source_company_year_mismatch", "rf1086_register_value_invalid",
]);

const sourcePrewriteValidationCodes = new Set([
  "rf1086_source_structure_invalid", "rf1086_source_contract_invalid", "rf1086_source_amount_invalid",
  "rf1086_source_identity_invalid", "rf1086_source_holder_identity_invalid", "rf1086_source_holder_identity_duplicate",
  "rf1086_source_case_not_ready", "rf1086_source_event_evidence_incomplete", "rf1086_source_event_evidence_mismatch",
  "rf1086_source_basis_evidence_missing", "rf1086_source_paid_in_required", "rf1086_source_paid_in_mismatch",
  "rf1086_source_signed_evidence_missing", "rf1086_source_documents_unverified", "rf1086_source_company_year_mismatch",
  "rf1086_source_completeness_required", "rf1086_source_no_activity_confirmation_mismatch",
  "rf1086_source_correction_reason_required", "rf1086_register_value_invalid",
]);

// Classifies this response only. A later refusal does not resolve an earlier
// unknown result for the same attempt; the caller must retain that uncertainty.
export function rf1086SourceCaptureRejected(error: unknown): boolean {
  if (!(error instanceof TalliApiError) || error.problem?.status !== error.status) return false;
  const code = error.problem.code;
  if (error.status === 409) return sourcePrewriteValidationCodes.has(code);
  if (error.status !== 400 && error.status !== 422) return false;
  return sourceValidationCodes.has(code) || code === "SHAREHOLDER_REGISTER_FILING_INVALID_INPUT"
    || code === "invalid_request";
}

export function rf1086SourceErrorMessage(error: unknown) {
  const code = error instanceof TalliApiError ? error.problem?.code : undefined;
  if (code && Object.hasOwn(sourceMessages, code)) return sourceMessages[code];
  if ((code && sourceValidationCodes.has(code)) || (error instanceof TalliApiError && error.status === 422)) {
    return "Kontroller feltene, dokumenthenvisningene og bekreftelsene før du prøver igjen.";
  }
  if (error instanceof TalliApiError && error.status === 401) return "Logg inn på nytt for å fortsette med årsgrunnlaget.";
  if (error instanceof TalliApiError && error.status === 403) return "Du har ikke tilgang til å bekrefte dette årsgrunnlaget.";
  return "Årsgrunnlaget kunne ikke bekreftes. Kontroller lagret status før du prøver igjen.";
}

const registerPrewriteValidationCodes = new Set([
  "rf1086_register_amount_invalid", "rf1086_register_count_invalid", "rf1086_register_capital_count_mismatch",
  "rf1086_register_capital_below_supported_minimum", "rf1086_register_holders_missing", "rf1086_register_holder_invalid",
  "rf1086_register_holder_identity_invalid", "rf1086_register_holder_count_invalid", "rf1086_register_holder_duplicate",
  "rf1086_register_holder_total_mismatch", "rf1086_register_owner_confirmation_required", "rf1086_register_effective_time_invalid",
  "rf1086_register_holder_identity_changed", "rf1086_register_issue_transition_invalid", "rf1086_register_issue_holder_transition_invalid",
  "rf1086_register_nominal_holder_transition_invalid", "rf1086_register_nominal_transition_invalid", "rf1086_register_event_unsupported",
  "rf1086_register_documents_missing", "rf1086_register_document_binding_invalid", "rf1086_register_document_role_invalid",
  "rf1086_register_document_duplicate", "rf1086_register_document_version_conflict", "rf1086_register_document_coverage_incomplete",
  "rf1086_register_correction_reason_required", "rf1086_register_correction_scope_invalid",
  "rf1086_register_document_postdates_capture", "rf1086_register_capture_predates_event",
  "rf1086_source_register_original_required", "rf1086_source_documents_unverified",
]);
const registerMessages: Record<string, string> = {
  rf1086_register_predecessor_mismatch: "Aksjeeierboken er allerede korrigert. Last inn lagrede opplysninger på nytt før du fortsetter.",
  rf1086_register_idempotency_conflict: "Dette lagringsforsøket er allerede brukt med andre opplysninger. Kontroller lagret status før du starter et nytt forsøk.",
  rf1086_register_correction_reason_required: "Beskriv hvorfor opplysningene fra aksjeeierboken skal korrigeres.",
  rf1086_register_correction_scope_invalid: "En korrigering må beholde selskap, år, hendelsestype og tidspunkt fra den lagrede registreringen.",
  rf1086_register_owner_confirmation_required: "Kontroller og bekreft hele aksjeeierboken, registreringen og at selskapet har én aksjeklasse.",
  rf1086_register_effective_time_invalid: "Oppgi dato og lokalt klokkeslett i det valgte inntektsåret, med hele sekunder.",
  rf1086_register_document_coverage_incomplete: "Legg ved aksjeeierboken før og etter endringen, og dokumentasjon på registreringen.",
  rf1086_register_capital_count_mismatch: "Aksjekapitalen må stemme med antall aksjer og pålydende. Kontroller begge tidspunktene.",
  rf1086_register_holder_total_mismatch: "Aksjene fordelt på aksjonærene må stemme med samlet antall aksjer.",
  rf1086_source_register_original_required: "Velg vedlagte originaldokumenter fra selskapets dokumenter.",
  rf1086_source_documents_unverified: "Dokumentopplysningene kunne ikke bekreftes. Hent originalene på nytt og kontroller vedleggene.",
};

// Like source capture, this classifies only this response, never an earlier
// uncertain attempt. Conflicts, storage failures and unknown codes stay uncertain.
export function rf1086RegisterCaptureRejected(error: unknown): boolean {
  if (!(error instanceof TalliApiError) || error.problem?.status !== error.status) return false;
  if (error.status === 409) return registerPrewriteValidationCodes.has(error.problem.code);
  return (error.status === 400 || error.status === 422)
    && ["rf1086_source_invalid_request", "SHAREHOLDER_REGISTER_FILING_INVALID_INPUT", "invalid_request"].includes(error.problem.code);
}

export function rf1086RegisterErrorMessage(error: unknown) {
  const code = error instanceof TalliApiError ? error.problem?.code : undefined;
  if (code && Object.hasOwn(registerMessages, code)) return registerMessages[code];
  if ((code && registerPrewriteValidationCodes.has(code)) || (error instanceof TalliApiError && error.status === 422)) {
    return "Kontroller aksjonærene, aksjene, beløpene og dokumenthenvisningene før du prøver igjen.";
  }
  if (error instanceof TalliApiError && error.status === 401) return "Logg inn på nytt for å fortsette med aksjeeierboken.";
  if (error instanceof TalliApiError && error.status === 403) return "Du har ikke tilgang til å bekrefte aksjeeierboken for dette selskapet.";
  return "Opplysningene fra aksjeeierboken kunne ikke bekreftes. Kontroller lagret status før du prøver igjen.";
}

const codes = new Set(["invalid_request", "authentication_required", "configuration_unavailable", "approval_expired",
  "basis_unavailable", "connection_unavailable", "payload_changed", "send_unavailable", "status_unavailable", "status_busy", "step_up_required"]);
export function rf1086ApiErrorCode(error: unknown) {
  if (error instanceof TalliApiError && error.problem?.code === "SHAREHOLDER_REGISTER_FILING_INVALID_INPUT") return "invalid_request";
  if (error instanceof TalliApiError && error.problem?.code && codes.has(error.problem.code)) return error.problem.code;
  return "status_unavailable";
}
export function rf1086ActionErrorMessage(error: unknown) {
  const code = error instanceof TalliApiError ? error.problem?.code : undefined;
  if (code === "authentication_required") return "Innlogging kreves.";
  if (code === "step_up_required") return "Ekstra identitetsbekreftelse med tofaktorautentisering kreves.";
  if (code === "SHAREHOLDER_REGISTER_FILING_NOT_FOUND") return "Fant ikke RF-1086-grunnlaget.";
  if (code === "SHAREHOLDER_REGISTER_FILING_FORBIDDEN") return "Du har ikke tilgang til RF-1086-handlingen.";
  if (code === "SHAREHOLDER_REGISTER_FILING_INVALID_INPUT" || code === "invalid_request") return "Kontroller feltene og bekreftelsene før du prøver igjen.";
  return "RF-1086-handlingen kunne ikke bekreftes. Se lagret status før du prøver igjen.";
}


export async function prepareRf1086SourceProductionReview(accessToken: string,
  body: RfSourceProductionReviewRequestWire, sourceId: string, sourceSha256: string): Promise<RfSourceProductionReviewWire> {
  const value = await client(accessToken).rf1086PrepareSourceProductionReview(body, request());
  if (value.companyId !== body.companyId || value.incomeYear !== body.incomeYear
      || value.previewId !== body.previewId || value.entitlementId !== body.entitlementId
      || value.sourceId !== sourceId || value.sourceSha256 !== sourceSha256
      || value.canApprove !== (value.blockers.length === 0)
      || new Set(value.warningCodes).size !== value.warningCodes.length
      || new Set(value.blockers).size !== value.blockers.length) throw new TalliApiError(502, undefined);
  return value;
}

export async function approveRf1086SourceProduction(accessToken: string, body: RfSourceProductionApprovalCommandWire) {
  const value = await client(accessToken).rf1086ApproveSourceProduction(body, request());
  if (value.companyId !== body.companyId || value.incomeYear !== body.incomeYear) throw new TalliApiError(502, undefined);
  return value;
}
