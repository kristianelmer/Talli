// Generated from contracts/openapi/talli-v1.json. Do not edit by hand.
// Contract version: 1.0.0

export interface SystemBoundaryStatus {
  apiVersion: string;
  service: string;
  status: "AVAILABLE";
}

export interface CompanyContext {
  aal: "aal2";
  address: string;
  city: string;
  createdAt: string;
  createdBy: string;
  currentAgreementAccepted: boolean;
  entityType: string;
  id: string;
  identityConfirmedAt: string | null;
  identityLockedAt: string | null;
  name: string;
  orgNumber: string;
  postalCode: string;
  resourceScope: "owner_sensitive";
  role: "owner";
  source: string;
  statusText: string;
}

export interface CompanyContextResponse {
  companies: CompanyContext[];
  selectedCompany: CompanyContext;
}

export interface CompanyInvitation {
  companyId: string;
  createdAt: string;
  expiresAt: string;
  id: string;
  invitedEmail: string;
  role: "reviewer" | "read_only";
  status: "pending" | "accepted" | "revoked" | "expired";
  updatedAt: string;
}

export interface CompanyInvitationListResponse {
  invitations: CompanyInvitation[];
}

export interface CompanyInvitationResponse {
  deliveryBody: string | null;
  deliverySubject: string | null;
  deliveryToken: string | null;
  invitation: CompanyInvitation;
}

export interface CompanyMembership {
  acceptedAt: string;
  companyId: string;
  role: "reviewer" | "read_only";
  state: "active" | "removed";
  userId: string;
}

export interface CompanyMembershipListResponse {
  memberships: CompanyMembership[];
}

export interface CompanyMembershipResponse {
  membership: CompanyMembership;
}

export interface CompanyOnboardingRequest {
  agreementAccepted: true;
  businessTermsSha256: "f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543";
  businessTermsVersion: "2026-07-17";
  dpaSha256: "083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c";
  dpaVersion: "2026-07-17";
  orgNumber: string;
}

export interface CompanyOnboardingResponse {
  companyId: string;
  currentAgreementAccepted: true;
  replayed: boolean;
}

export interface CompanyAgreementAcceptanceRequest {
  agreementAccepted: true;
  businessTermsSha256: "f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543";
  businessTermsVersion: "2026-07-17";
  companyId: string;
  dpaSha256: "083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c";
  dpaVersion: "2026-07-17";
}

export interface CompanyAgreementAcceptanceResponse {
  companyId: string;
  currentAgreementAccepted: true;
  replayed: boolean;
}

export interface CompanyAccessRecord {
  address: string;
  city: string;
  createdAt: string;
  createdBy: string;
  entityType: string;
  id: string;
  identityConfirmedAt: string | null;
  identityLockedAt: string | null;
  name: string;
  orgNumber: string;
  postalCode: string;
  role: "owner" | "reviewer" | "read_only";
  source: string;
  statusText: string;
}

export interface CompanyAccessRecordResponse {
  company: CompanyAccessRecord;
}

export interface OperatorContextResponse {
  active: true;
  role: "support" | "admin";
}

export interface OperatorCompanyRecord {
  address: string;
  city: string;
  createdAt: string;
  createdBy: string;
  entityType: string;
  id: string;
  identityConfirmedAt: string | null;
  identityLockedAt: string | null;
  name: string;
  orgNumber: string;
  postalCode: string;
  source: string;
  statusText: string;
}

export interface OperatorCompanySearchResponse {
  companies: OperatorCompanyRecord[];
}

export interface AcceptCompanyInvitationRequest {
  operationId: string;
  token: string;
}

export interface CreateCompanyInvitationRequest {
  companyId: string;
  invitedEmail: string;
  operationId: string;
  role: "reviewer" | "read_only";
}

export interface InvitationLookup {
  companyName: string;
  expiresAt: string;
  role: "reviewer" | "read_only";
}

export interface InvitationTokenRequest {
  token: string;
}

export interface CompanyInvitationCommandRequest {
  companyId: string;
  expectedUpdatedAt: string;
  operationId: string;
}

export interface AdministerCompanyMembershipRequest {
  companyId: string;
  expectedRole: "reviewer" | "read_only";
  operationId: string;
  role?: "reviewer" | "read_only" | null;
  state?: "active" | "removed" | null;
}

export interface InvitationSideEffectContinuation {
  commandName: "create_invitation" | "accept_invitation" | "revoke_invitation" | "resend_invitation";
  companyId: string;
  deliveryBody: string | null;
  deliverySubject: string | null;
  deliveryToken: string | null;
  invitation: CompanyInvitation | null;
  membership: CompanyMembership | null;
  operationId: string;
}

export interface InvitationSideEffectContinuationList {
  continuations: InvitationSideEffectContinuation[];
}

export interface InvitationSideEffectCompletion {
  completed: true;
  operationId: string;
}

export interface CompanyCancellationEvidence {
  archiveDownloadPath?: string | null;
  archiveExportedAt?: string | null;
  archiveIncomeYear?: number | null;
  corporateEvidenceComplete?: boolean | null;
  corporateObjectKeys?: string[];
  legalReviewRequired?: boolean;
  missingCorporateObjectKeys?: string[];
  missingDocumentIds?: string[];
  retentionClasses?: string[];
}

export interface CompanyCancellation {
  companyId: string;
  deletedAt: string | null;
  deletedBy: string | null;
  evidence: CompanyCancellationEvidence;
  id: string;
  reason: string;
  requestedAt: string;
  requestedBy: string;
  reviewedAt: string | null;
  reviewedBy: string | null;
  status: "export_required" | "retention_hold" | "deletion_approved" | "deleted" | "superseded";
  updatedAt: string;
}

export interface CompanyCancellationListResponse {
  cancellations: CompanyCancellation[];
}

export interface CompanyCancellationResponse {
  cancellation: CompanyCancellation;
}

export interface CompanyDeletionReview {
  cancellationId: string;
  cancellationRevision: string;
  companyId: string;
  decision: "approved" | "rejected";
  evidenceReference: string;
  id: string;
  operationId: string;
  reviewedAt: string;
  reviewedBy: string;
}

export interface CompanyDeletionReviewResponse {
  cancellation: CompanyCancellation;
  review: CompanyDeletionReview;
}

export interface RequestCompanyCancellationRequest {
  companyId: string;
  incomeYear: number;
  operationId: string;
  reason: string;
}

export interface ResumeCompanyCancellationRequest {
  companyId: string;
  expectedUpdatedAt: string;
  incomeYear: number;
  operationId: string;
}

export interface ReviewCompanyDeletionRequest {
  companyId: string;
  decision: "approved" | "rejected";
  evidenceReference: string;
  expectedUpdatedAt: string;
  operationId: string;
}

export interface FinalizeCompanyDeletionRequest {
  companyId: string;
  expectedUpdatedAt: string;
  operationId: string;
}

export interface ProblemDetails {
  code: string;
  detail: string;
  instance: string;
  requestId: string;
  status: number;
  title: string;
  type: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function hasOnlyProperties(
  value: Record<string, unknown>,
  allowedProperties: readonly string[],
): boolean {
  return Object.keys(value).every((property) => allowedProperties.includes(property));
}

function isUuid(value: unknown): value is string {
  return typeof value === "string"
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu.test(value);
}

function isDateTime(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|([+-])(\d{2}):(\d{2}))$/u.exec(value);
  if (!match) return false;
  const [, yearText, monthText, dayText, hourText, minuteText, secondText, , offsetHourText, offsetMinuteText] = match;
  const [year, month, day, hour, minute, second] = [yearText, monthText, dayText, hourText, minuteText, secondText].map(Number);
  if (hour > 23 || minute > 59 || second > 59) return false;
  if (offsetHourText !== undefined && (Number(offsetHourText) > 23 || Number(offsetMinuteText) > 59)) return false;
  const calendar = new Date(0);
  calendar.setUTCHours(0, 0, 0, 0);
  calendar.setUTCFullYear(year, month - 1, day);
  calendar.setUTCHours(hour, minute, second, 0);
  return calendar.getUTCFullYear() === year
    && calendar.getUTCMonth() === month - 1
    && calendar.getUTCDate() === day
    && !Number.isNaN(Date.parse(value));
}

function isSystemBoundaryStatus(value: unknown): value is SystemBoundaryStatus {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["apiVersion","service","status"]) &&
    typeof value.apiVersion === "string" &&
    typeof value.service === "string" &&
    value.status === "AVAILABLE"
  );
}

function isCompanyContext(value: unknown): value is CompanyContext {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["aal","address","city","createdAt","createdBy","currentAgreementAccepted","entityType","id","identityConfirmedAt","identityLockedAt","name","orgNumber","postalCode","resourceScope","role","source","statusText"]) &&
    value.aal === "aal2" &&
    typeof value.address === "string" &&
    typeof value.city === "string" &&
    typeof value.createdAt === "string" &&
    typeof value.createdBy === "string" &&
    typeof value.currentAgreementAccepted === "boolean" &&
    typeof value.entityType === "string" &&
    typeof value.id === "string" &&
    (typeof value.identityConfirmedAt === "string" || value.identityConfirmedAt === null) &&
    (typeof value.identityLockedAt === "string" || value.identityLockedAt === null) &&
    typeof value.name === "string" &&
    typeof value.orgNumber === "string" &&
    typeof value.postalCode === "string" &&
    value.resourceScope === "owner_sensitive" &&
    value.role === "owner" &&
    typeof value.source === "string" &&
    typeof value.statusText === "string"
  );
}

function isCompanyContextResponse(value: unknown): value is CompanyContextResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companies","selectedCompany"]) &&
    Array.isArray(value.companies) && value.companies.every((item) => isCompanyContext(item)) &&
    isCompanyContext(value.selectedCompany)
  );
}

function isCompanyInvitation(value: unknown): value is CompanyInvitation {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","createdAt","expiresAt","id","invitedEmail","role","status","updatedAt"]) &&
    typeof value.companyId === "string" &&
    typeof value.createdAt === "string" &&
    typeof value.expiresAt === "string" &&
    typeof value.id === "string" &&
    typeof value.invitedEmail === "string" &&
    (value.role === "reviewer" || value.role === "read_only") &&
    (value.status === "pending" || value.status === "accepted" || value.status === "revoked" || value.status === "expired") &&
    typeof value.updatedAt === "string"
  );
}

function isCompanyInvitationListResponse(value: unknown): value is CompanyInvitationListResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["invitations"]) &&
    Array.isArray(value.invitations) && value.invitations.every((item) => isCompanyInvitation(item))
  );
}

function isCompanyInvitationResponse(value: unknown): value is CompanyInvitationResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["deliveryBody","deliverySubject","deliveryToken","invitation"]) &&
    (typeof value.deliveryBody === "string" || value.deliveryBody === null) &&
    (typeof value.deliverySubject === "string" || value.deliverySubject === null) &&
    (typeof value.deliveryToken === "string" || value.deliveryToken === null) &&
    isCompanyInvitation(value.invitation)
  );
}

function isCompanyMembership(value: unknown): value is CompanyMembership {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["acceptedAt","companyId","role","state","userId"]) &&
    typeof value.acceptedAt === "string" &&
    typeof value.companyId === "string" &&
    (value.role === "reviewer" || value.role === "read_only") &&
    (value.state === "active" || value.state === "removed") &&
    typeof value.userId === "string"
  );
}

function isCompanyMembershipListResponse(value: unknown): value is CompanyMembershipListResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["memberships"]) &&
    Array.isArray(value.memberships) && value.memberships.every((item) => isCompanyMembership(item))
  );
}

function isCompanyMembershipResponse(value: unknown): value is CompanyMembershipResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["membership"]) &&
    isCompanyMembership(value.membership)
  );
}

function isCompanyOnboardingResponse(value: unknown): value is CompanyOnboardingResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","currentAgreementAccepted","replayed"]) &&
    isUuid(value.companyId) &&
    value.currentAgreementAccepted === true &&
    typeof value.replayed === "boolean"
  );
}

function isCompanyAgreementAcceptanceResponse(value: unknown): value is CompanyAgreementAcceptanceResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","currentAgreementAccepted","replayed"]) &&
    isUuid(value.companyId) &&
    value.currentAgreementAccepted === true &&
    typeof value.replayed === "boolean"
  );
}

function isCompanyAccessRecord(value: unknown): value is CompanyAccessRecord {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["address","city","createdAt","createdBy","entityType","id","identityConfirmedAt","identityLockedAt","name","orgNumber","postalCode","role","source","statusText"]) &&
    typeof value.address === "string" &&
    typeof value.city === "string" &&
    typeof value.createdAt === "string" &&
    typeof value.createdBy === "string" &&
    typeof value.entityType === "string" &&
    typeof value.id === "string" &&
    (typeof value.identityConfirmedAt === "string" || value.identityConfirmedAt === null) &&
    (typeof value.identityLockedAt === "string" || value.identityLockedAt === null) &&
    typeof value.name === "string" &&
    typeof value.orgNumber === "string" &&
    typeof value.postalCode === "string" &&
    (value.role === "owner" || value.role === "reviewer" || value.role === "read_only") &&
    typeof value.source === "string" &&
    typeof value.statusText === "string"
  );
}

function isCompanyAccessRecordResponse(value: unknown): value is CompanyAccessRecordResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["company"]) &&
    isCompanyAccessRecord(value.company)
  );
}

function isOperatorContextResponse(value: unknown): value is OperatorContextResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["active","role"]) &&
    value.active === true &&
    (value.role === "support" || value.role === "admin")
  );
}

function isOperatorCompanyRecord(value: unknown): value is OperatorCompanyRecord {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["address","city","createdAt","createdBy","entityType","id","identityConfirmedAt","identityLockedAt","name","orgNumber","postalCode","source","statusText"]) &&
    typeof value.address === "string" &&
    typeof value.city === "string" &&
    typeof value.createdAt === "string" &&
    typeof value.createdBy === "string" &&
    typeof value.entityType === "string" &&
    typeof value.id === "string" &&
    (typeof value.identityConfirmedAt === "string" || value.identityConfirmedAt === null) &&
    (typeof value.identityLockedAt === "string" || value.identityLockedAt === null) &&
    typeof value.name === "string" &&
    typeof value.orgNumber === "string" &&
    typeof value.postalCode === "string" &&
    typeof value.source === "string" &&
    typeof value.statusText === "string"
  );
}

function isOperatorCompanySearchResponse(value: unknown): value is OperatorCompanySearchResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companies"]) &&
    Array.isArray(value.companies) && value.companies.every((item) => isOperatorCompanyRecord(item))
  );
}

function isInvitationLookup(value: unknown): value is InvitationLookup {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyName","expiresAt","role"]) &&
    typeof value.companyName === "string" &&
    typeof value.expiresAt === "string" &&
    (value.role === "reviewer" || value.role === "read_only")
  );
}

function isInvitationSideEffectContinuation(value: unknown): value is InvitationSideEffectContinuation {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["commandName","companyId","deliveryBody","deliverySubject","deliveryToken","invitation","membership","operationId"]) &&
    (value.commandName === "create_invitation" || value.commandName === "accept_invitation" || value.commandName === "revoke_invitation" || value.commandName === "resend_invitation") &&
    typeof value.companyId === "string" &&
    (typeof value.deliveryBody === "string" || value.deliveryBody === null) &&
    (typeof value.deliverySubject === "string" || value.deliverySubject === null) &&
    (typeof value.deliveryToken === "string" || value.deliveryToken === null) &&
    (isCompanyInvitation(value.invitation) || value.invitation === null) &&
    (isCompanyMembership(value.membership) || value.membership === null) &&
    typeof value.operationId === "string"
  );
}

function isInvitationSideEffectContinuationList(value: unknown): value is InvitationSideEffectContinuationList {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["continuations"]) &&
    Array.isArray(value.continuations) && value.continuations.every((item) => isInvitationSideEffectContinuation(item))
  );
}

function isInvitationSideEffectCompletion(value: unknown): value is InvitationSideEffectCompletion {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["completed","operationId"]) &&
    value.completed === true &&
    typeof value.operationId === "string"
  );
}

function isCompanyCancellationEvidence(value: unknown): value is CompanyCancellationEvidence {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["archiveDownloadPath","archiveExportedAt","archiveIncomeYear","corporateEvidenceComplete","corporateObjectKeys","legalReviewRequired","missingCorporateObjectKeys","missingDocumentIds","retentionClasses"]) &&
    (value.archiveDownloadPath === undefined || (typeof value.archiveDownloadPath === "string" || value.archiveDownloadPath === null)) &&
    (value.archiveExportedAt === undefined || (isDateTime(value.archiveExportedAt) || value.archiveExportedAt === null)) &&
    (value.archiveIncomeYear === undefined || ((typeof value.archiveIncomeYear === "number" && Number.isInteger(value.archiveIncomeYear) && value.archiveIncomeYear >= 2000 && value.archiveIncomeYear <= 2100) || value.archiveIncomeYear === null)) &&
    (value.corporateEvidenceComplete === undefined || (typeof value.corporateEvidenceComplete === "boolean" || value.corporateEvidenceComplete === null)) &&
    (value.corporateObjectKeys === undefined || Array.isArray(value.corporateObjectKeys) && value.corporateObjectKeys.every((item) => typeof item === "string")) &&
    (value.legalReviewRequired === undefined || typeof value.legalReviewRequired === "boolean") &&
    (value.missingCorporateObjectKeys === undefined || Array.isArray(value.missingCorporateObjectKeys) && value.missingCorporateObjectKeys.every((item) => typeof item === "string")) &&
    (value.missingDocumentIds === undefined || Array.isArray(value.missingDocumentIds) && value.missingDocumentIds.every((item) => isUuid(item))) &&
    (value.retentionClasses === undefined || Array.isArray(value.retentionClasses) && value.retentionClasses.every((item) => typeof item === "string"))
  );
}

function isCompanyCancellation(value: unknown): value is CompanyCancellation {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","deletedAt","deletedBy","evidence","id","reason","requestedAt","requestedBy","reviewedAt","reviewedBy","status","updatedAt"]) &&
    isUuid(value.companyId) &&
    (isDateTime(value.deletedAt) || value.deletedAt === null) &&
    (isUuid(value.deletedBy) || value.deletedBy === null) &&
    isCompanyCancellationEvidence(value.evidence) &&
    isUuid(value.id) &&
    (typeof value.reason === "string" && value.reason.length >= 1 && value.reason.length <= 1000) &&
    isDateTime(value.requestedAt) &&
    isUuid(value.requestedBy) &&
    (isDateTime(value.reviewedAt) || value.reviewedAt === null) &&
    (isUuid(value.reviewedBy) || value.reviewedBy === null) &&
    (value.status === "export_required" || value.status === "retention_hold" || value.status === "deletion_approved" || value.status === "deleted" || value.status === "superseded") &&
    isDateTime(value.updatedAt)
  );
}

function isCompanyCancellationListResponse(value: unknown): value is CompanyCancellationListResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["cancellations"]) &&
    Array.isArray(value.cancellations) && value.cancellations.every((item) => isCompanyCancellation(item))
  );
}

function isCompanyCancellationResponse(value: unknown): value is CompanyCancellationResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["cancellation"]) &&
    isCompanyCancellation(value.cancellation)
  );
}

function isCompanyDeletionReview(value: unknown): value is CompanyDeletionReview {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["cancellationId","cancellationRevision","companyId","decision","evidenceReference","id","operationId","reviewedAt","reviewedBy"]) &&
    isUuid(value.cancellationId) &&
    isDateTime(value.cancellationRevision) &&
    isUuid(value.companyId) &&
    (value.decision === "approved" || value.decision === "rejected") &&
    (typeof value.evidenceReference === "string" && value.evidenceReference.length >= 1 && value.evidenceReference.length <= 500) &&
    isUuid(value.id) &&
    isUuid(value.operationId) &&
    isDateTime(value.reviewedAt) &&
    isUuid(value.reviewedBy)
  );
}

function isCompanyDeletionReviewResponse(value: unknown): value is CompanyDeletionReviewResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["cancellation","review"]) &&
    isCompanyCancellation(value.cancellation) &&
    isCompanyDeletionReview(value.review)
  );
}

function isProblemDetails(value: unknown): value is ProblemDetails {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["code","detail","instance","requestId","status","title","type"]) &&
    typeof value.code === "string" &&
    typeof value.detail === "string" &&
    typeof value.instance === "string" &&
    typeof value.requestId === "string" &&
    typeof value.status === "number" && Number.isInteger(value.status) &&
    typeof value.title === "string" &&
    typeof value.type === "string"
  );
}

export class TalliApiError extends Error {
  readonly status: number;
  readonly problem: ProblemDetails | undefined;

  constructor(
    status: number,
    problem: ProblemDetails | undefined,
  ) {
    super(problem?.code ?? `HTTP_${status}`);
    this.name = "TalliApiError";
    this.status = status;
    this.problem = problem;
  }
}

export interface TalliApiClientOptions {
  baseUrl: string;
  fetch?: typeof globalThis.fetch;
  headers?: HeadersInit;
}

export interface TalliRequestOptions {
  signal?: AbortSignal;
  headers?: HeadersInit;
  requestId?: string;
}

export interface CompanyAccessContextRequest extends TalliRequestOptions {
  companyId?: string;
}

export function createTalliApiClient(options: TalliApiClientOptions) {
  const fetchImplementation = options.fetch ?? globalThis.fetch;
  const baseUrl = options.baseUrl.replace(/\/$/, "");

  async function executeJson<T>(
    url: string,
    method: string,
    request: TalliRequestOptions,
    body: unknown,
    guard: (value: unknown) => value is T,
  ): Promise<T> {
    const response = await fetchImplementation(url, {
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
      headers: {
        Accept: "application/json, application/problem+json",
        ...(body === undefined ? {} : { ["Content-Type"]: "application/json" }),
        ...options.headers,
        ...request.headers,
        ...(request.requestId === undefined
          ? {}
          : { ["X-Request-ID"]: request.requestId }),
      },
      method,
      signal: request.signal,
    });
    if (!response.ok) {
      const contentType = response.headers.get("content-type") ?? "";
      const candidate = contentType.includes("application/problem+json")
        ? await response.json().catch(() => undefined)
        : undefined;
      throw new TalliApiError(
        response.status,
        isProblemDetails(candidate) ? candidate : undefined,
      );
    }
    const candidate: unknown = await response.json().catch(() => {
      throw new TalliApiError(502, undefined);
    });
    if (!guard(candidate)) throw new TalliApiError(502, undefined);
    return candidate;
  }

  return {
    async systemBoundaryGetTracerStatus(
      request: TalliRequestOptions = {},
    ): Promise<SystemBoundaryStatus> {
      const response = await fetchImplementation(`${baseUrl}/api/v1/system-boundary/tracer`, {
        cache: "no-store",
        headers: {
          Accept: "application/json, application/problem+json",
          ...options.headers,
          ...request.headers,
          ...(request.requestId === undefined
            ? {}
            : { ["X-Request-ID"]: request.requestId }),
        },
        method: "GET",
        signal: request.signal,
      });

      if (!response.ok) {
        const contentType = response.headers.get("content-type") ?? "";
        const candidate = contentType.includes("application/problem+json")
          ? await response.json().catch(() => undefined)
          : undefined;
        const problem = isProblemDetails(candidate) ? candidate : undefined;
        throw new TalliApiError(response.status, problem);
      }

      const candidate: unknown = await response.json();
      if (!isSystemBoundaryStatus(candidate)) {
        throw new TalliApiError(502, undefined);
      }
      return candidate;
    },

    async companyAccessGetSelectedContext(
      request: CompanyAccessContextRequest = {},
    ): Promise<CompanyContextResponse> {
      const query = new URLSearchParams();
      if (request.companyId !== undefined) query.set("company_id", request.companyId);
      const suffix = query.size ? `?${query}` : "";
      const response = await fetchImplementation(`${baseUrl}/api/v1/company-access/context${suffix}`, {
        cache: "no-store",
        headers: {
          Accept: "application/json, application/problem+json",
          ...options.headers,
          ...request.headers,
          ...(request.requestId === undefined
            ? {}
            : { ["X-Request-ID"]: request.requestId }),
        },
        method: "GET",
        signal: request.signal,
      });

      if (!response.ok) {
        const contentType = response.headers.get("content-type") ?? "";
        const candidate = contentType.includes("application/problem+json")
          ? await response.json().catch(() => undefined)
          : undefined;
        const problem = isProblemDetails(candidate) ? candidate : undefined;
        throw new TalliApiError(response.status, problem);
      }

      const candidate: unknown = await response.json();
      if (!isCompanyContextResponse(candidate)) {
        throw new TalliApiError(502, undefined);
      }
      return candidate;
    },

    async companyAccessOnboardCompany(
      body: CompanyOnboardingRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyOnboardingResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/onboarding`,
        "POST",
        request,
        body,
        isCompanyOnboardingResponse,
      );
    },

    async companyAccessReacceptAgreement(
      body: CompanyAgreementAcceptanceRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyAgreementAcceptanceResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/agreements/reaccept`,
        "POST",
        request,
        body,
        isCompanyAgreementAcceptanceResponse,
      );
    },

    async companyAccessGetCompanyRecord(
      companyId: string,
      request: TalliRequestOptions = {},
    ): Promise<CompanyAccessRecordResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/companies/${encodeURIComponent(companyId)}`,
        "GET",
        request,
        undefined,
        isCompanyAccessRecordResponse,
      );
    },

    async companyAccessGetOperatorContext(
      request: TalliRequestOptions = {},
    ): Promise<OperatorContextResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/operator-context`,
        "GET",
        request,
        undefined,
        isOperatorContextResponse,
      );
    },

    async companyAccessSearchOperatorCompanies(
      query: string,
      request: TalliRequestOptions = {},
    ): Promise<OperatorCompanySearchResponse> {
      const search = new URLSearchParams({ query });
      return executeJson(
        `${baseUrl}/api/v1/company-access/operator-companies?${search}`,
        "GET",
        request,
        undefined,
        isOperatorCompanySearchResponse,
      );
    },

    async companyAccessListInvitations(
      companyId: string,
      request: TalliRequestOptions = {},
    ): Promise<CompanyInvitationListResponse> {
      const query = new URLSearchParams({ company_id: companyId });
      return executeJson(
        `${baseUrl}/api/v1/company-access/invitations?${query}`,
        "GET",
        request,
        undefined,
        isCompanyInvitationListResponse,
      );
    },

    async companyAccessCreateInvitation(
      body: CreateCompanyInvitationRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyInvitationResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/invitations`,
        "POST",
        request,
        body,
        isCompanyInvitationResponse,
      );
    },

    async companyAccessLookupInvitation(
      body: InvitationTokenRequest,
      request: TalliRequestOptions = {},
    ): Promise<InvitationLookup> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/invitations/lookup`,
        "POST",
        request,
        body,
        isInvitationLookup,
      );
    },

    async companyAccessAcceptInvitation(
      body: AcceptCompanyInvitationRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyMembershipResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/invitations/accept`,
        "POST",
        request,
        body,
        isCompanyMembershipResponse,
      );
    },

    async companyAccessRevokeInvitation(
      invitationId: string,
      body: CompanyInvitationCommandRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyInvitationResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/invitations/${encodeURIComponent(invitationId)}/revoke`,
        "POST",
        request,
        body,
        isCompanyInvitationResponse,
      );
    },

    async companyAccessResendInvitation(
      invitationId: string,
      body: CompanyInvitationCommandRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyInvitationResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/invitations/${encodeURIComponent(invitationId)}/resend`,
        "POST",
        request,
        body,
        isCompanyInvitationResponse,
      );
    },

    async companyAccessListPendingInvitationSideEffects(
      request: TalliRequestOptions = {},
    ): Promise<InvitationSideEffectContinuationList> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/invitation-side-effects/pending`,
        "GET",
        request,
        undefined,
        isInvitationSideEffectContinuationList,
      );
    },

    async companyAccessCompleteInvitationSideEffect(
      operationId: string,
      request: TalliRequestOptions = {},
    ): Promise<InvitationSideEffectCompletion> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/invitation-side-effects/${encodeURIComponent(operationId)}/complete`,
        "POST",
        request,
        undefined,
        isInvitationSideEffectCompletion,
      );
    },

    async companyAccessListMemberships(
      companyId: string,
      request: TalliRequestOptions = {},
    ): Promise<CompanyMembershipListResponse> {
      const query = new URLSearchParams({ company_id: companyId });
      return executeJson(
        `${baseUrl}/api/v1/company-access/memberships?${query}`,
        "GET",
        request,
        undefined,
        isCompanyMembershipListResponse,
      );
    },

    async companyAccessAdministerMembership(
      userId: string,
      body: AdministerCompanyMembershipRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyMembershipResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/memberships/${encodeURIComponent(userId)}`,
        "PATCH",
        request,
        body,
        isCompanyMembershipResponse,
      );
    },

    async companyAccessListCancellations(
      companyId: string,
      request: TalliRequestOptions = {},
    ): Promise<CompanyCancellationListResponse> {
      const query = new URLSearchParams({ company_id: companyId });
      return executeJson(
        `${baseUrl}/api/v1/company-access/cancellations?${query}`,
        "GET",
        request,
        undefined,
        isCompanyCancellationListResponse,
      );
    },

    async companyAccessRequestCancellation(
      body: RequestCompanyCancellationRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyCancellationResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/cancellations`,
        "POST",
        request,
        body,
        isCompanyCancellationResponse,
      );
    },

    async companyAccessReviewDeletion(
      cancellationId: string,
      body: ReviewCompanyDeletionRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyDeletionReviewResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/cancellations/${encodeURIComponent(cancellationId)}/reviews`,
        "POST",
        request,
        body,
        isCompanyDeletionReviewResponse,
      );
    },

    async companyAccessResumeCancellation(
      cancellationId: string,
      body: ResumeCompanyCancellationRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyCancellationResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/cancellations/${encodeURIComponent(cancellationId)}/resume`,
        "POST",
        request,
        body,
        isCompanyCancellationResponse,
      );
    },

    async companyAccessFinalizeDeletion(
      cancellationId: string,
      body: FinalizeCompanyDeletionRequest,
      request: TalliRequestOptions = {},
    ): Promise<CompanyCancellationResponse> {
      return executeJson(
        `${baseUrl}/api/v1/company-access/cancellations/${encodeURIComponent(cancellationId)}/finalize`,
        "POST",
        request,
        body,
        isCompanyCancellationResponse,
      );
    },
  };
}
