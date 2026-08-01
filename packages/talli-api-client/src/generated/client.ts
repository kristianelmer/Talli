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

function isSystemBoundaryStatus(value: unknown): value is SystemBoundaryStatus {
  return (
    isRecord(value) &&
    typeof value.apiVersion === "string" &&
    typeof value.service === "string" &&
    value.status === "AVAILABLE"
  );
}

function isCompanyContext(value: unknown): value is CompanyContext {
  return (
    isRecord(value) &&
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
    isCompanyContext(value.selectedCompany) &&
    Array.isArray(value.companies) && value.companies.every((item) => isCompanyContext(item))
  );
}

function isProblemDetails(value: unknown): value is ProblemDetails {
  return (
    isRecord(value) &&
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
  };
}
