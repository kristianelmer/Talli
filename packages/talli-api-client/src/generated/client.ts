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
  completed: boolean;
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
  status: "export_required" | "retention_hold" | "deletion_approved" | "deleted";
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
    hasOnlyProperties(value, ["aal","address","city","createdAt","createdBy","entityType","id","identityConfirmedAt","identityLockedAt","name","orgNumber","postalCode","resourceScope","role","source","statusText"]) &&
    typeof value.id === "string" &&
    typeof value.orgNumber === "string" &&
    typeof value.name === "string" &&
    typeof value.entityType === "string" &&
    typeof value.address === "string" &&
    typeof value.postalCode === "string" &&
    typeof value.city === "string" &&
    typeof value.statusText === "string" &&
    typeof value.source === "string" &&
    typeof value.createdBy === "string" &&
    (value.identityConfirmedAt === null || typeof value.identityConfirmedAt === "string") &&
    (value.identityLockedAt === null || typeof value.identityLockedAt === "string") &&
    typeof value.createdAt === "string" &&
    value.role === "owner" &&
    value.resourceScope === "owner_sensitive" &&
    value.aal === "aal2"
  );
}

function isCompanyContextResponse(value: unknown): value is CompanyContextResponse {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companies","selectedCompany"]) &&
    isCompanyContext(value.selectedCompany) &&
    Array.isArray(value.companies) && value.companies.every((item) => isCompanyContext(item))
  );
}

function isCompanyInvitation(value: unknown): value is CompanyInvitation {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","createdAt","expiresAt","id","invitedEmail","role","status","updatedAt"]) &&
    typeof value.id === "string" &&
    typeof value.companyId === "string" &&
    typeof value.invitedEmail === "string" &&
    (value.role === "reviewer" || value.role === "read_only") &&
    (value.status === "pending" || value.status === "accepted" || value.status === "revoked" || value.status === "expired") &&
    typeof value.expiresAt === "string" &&
    typeof value.createdAt === "string" &&
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
    isCompanyInvitation(value.invitation) &&
    (value.deliveryToken === null || typeof value.deliveryToken === "string") &&
    (value.deliverySubject === null || typeof value.deliverySubject === "string") &&
    (value.deliveryBody === null || typeof value.deliveryBody === "string")
  );
}

function isCompanyMembership(value: unknown): value is CompanyMembership {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["acceptedAt","companyId","role","state","userId"]) &&
    typeof value.companyId === "string" &&
    typeof value.userId === "string" &&
    (value.role === "reviewer" || value.role === "read_only") &&
    (value.state === "active" || value.state === "removed") &&
    typeof value.acceptedAt === "string"
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

function isInvitationLookup(value: unknown): value is InvitationLookup {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyName","expiresAt","role"]) &&
    typeof value.companyName === "string" &&
    (value.role === "reviewer" || value.role === "read_only") &&
    typeof value.expiresAt === "string"
  );
}

function isInvitationSideEffectContinuation(value: unknown): value is InvitationSideEffectContinuation {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["commandName","companyId","deliveryBody","deliverySubject","deliveryToken","invitation","membership","operationId"]) &&
    typeof value.operationId === "string" &&
    (value.commandName === "create_invitation" || value.commandName === "accept_invitation" || value.commandName === "revoke_invitation" || value.commandName === "resend_invitation") &&
    typeof value.companyId === "string" &&
    (value.invitation === null || isCompanyInvitation(value.invitation)) &&
    (value.membership === null || isCompanyMembership(value.membership)) &&
    (value.deliveryToken === null || typeof value.deliveryToken === "string") &&
    (value.deliverySubject === null || typeof value.deliverySubject === "string") &&
    (value.deliveryBody === null || typeof value.deliveryBody === "string")
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
    typeof value.operationId === "string" &&
    value.completed === true
  );
}

function isCompanyCancellationEvidence(value: unknown): value is CompanyCancellationEvidence {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["archiveDownloadPath","archiveExportedAt","archiveIncomeYear","corporateEvidenceComplete","corporateObjectKeys","legalReviewRequired","missingCorporateObjectKeys","missingDocumentIds","retentionClasses"])
  );
}

function isCompanyCancellation(value: unknown): value is CompanyCancellation {
  return (
    isRecord(value) &&
    hasOnlyProperties(value, ["companyId","deletedAt","deletedBy","evidence","id","reason","requestedAt","requestedBy","reviewedAt","reviewedBy","status","updatedAt"]) &&
    typeof value.id === "string" &&
    typeof value.companyId === "string" &&
    (value.status === "export_required" || value.status === "retention_hold" || value.status === "deletion_approved" || value.status === "deleted") &&
    typeof value.reason === "string" &&
    isCompanyCancellationEvidence(value.evidence) &&
    typeof value.requestedBy === "string" &&
    typeof value.requestedAt === "string" &&
    (value.reviewedBy === null || typeof value.reviewedBy === "string") &&
    (value.reviewedAt === null || typeof value.reviewedAt === "string") &&
    (value.deletedBy === null || typeof value.deletedBy === "string") &&
    (value.deletedAt === null || typeof value.deletedAt === "string") &&
    typeof value.updatedAt === "string"
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
    typeof value.id === "string" &&
    typeof value.cancellationId === "string" &&
    typeof value.companyId === "string" &&
    (value.decision === "approved" || value.decision === "rejected") &&
    typeof value.evidenceReference === "string" &&
    typeof value.reviewedBy === "string" &&
    typeof value.reviewedAt === "string" &&
    typeof value.operationId === "string" &&
    typeof value.cancellationRevision === "string"
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
    typeof value.type === "string" &&
    typeof value.title === "string" &&
    typeof value.status === "number" &&
    typeof value.detail === "string" &&
    typeof value.instance === "string" &&
    typeof value.code === "string" &&
    typeof value.requestId === "string"
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
    const candidate: unknown = await response.json();
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
