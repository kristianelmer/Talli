import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const check = process.argv.includes("--check");
const contractPath = resolve("contracts/openapi/talli-v1.json");
const outputPath = resolve("packages/talli-api-client/src/generated/client.ts");
const contract = JSON.parse(readFileSync(contractPath, "utf8"));
const path = "/api/v1/system-boundary/tracer";
const operation = contract.paths?.[path]?.get;
const companyAccessPath = "/api/v1/company-access/context";
const companyAccessOperation = contract.paths?.[companyAccessPath]?.get;
const companyAccessOperations = {
  listInvitations: ["/api/v1/company-access/invitations", "get", "companyAccessListInvitations"],
  createInvitation: ["/api/v1/company-access/invitations", "post", "companyAccessCreateInvitation"],
  lookupInvitation: ["/api/v1/company-access/invitations/lookup", "post", "companyAccessLookupInvitation"],
  acceptInvitation: ["/api/v1/company-access/invitations/accept", "post", "companyAccessAcceptInvitation"],
  revokeInvitation: ["/api/v1/company-access/invitations/{invitation_id}/revoke", "post", "companyAccessRevokeInvitation"],
  resendInvitation: ["/api/v1/company-access/invitations/{invitation_id}/resend", "post", "companyAccessResendInvitation"],
  listPendingInvitationSideEffects: ["/api/v1/company-access/invitation-side-effects/pending", "get", "companyAccessListPendingInvitationSideEffects"],
  completeInvitationSideEffect: ["/api/v1/company-access/invitation-side-effects/{operation_id}/complete", "post", "companyAccessCompleteInvitationSideEffect"],
  listMemberships: ["/api/v1/company-access/memberships", "get", "companyAccessListMemberships"],
  administerMembership: ["/api/v1/company-access/memberships/{user_id}", "patch", "companyAccessAdministerMembership"],
  listCancellations: ["/api/v1/company-access/cancellations", "get", "companyAccessListCancellations"],
  requestCancellation: ["/api/v1/company-access/cancellations", "post", "companyAccessRequestCancellation"],
  resumeCancellation: ["/api/v1/company-access/cancellations/{cancellation_id}/resume", "post", "companyAccessResumeCancellation"],
  reviewDeletion: ["/api/v1/company-access/cancellations/{cancellation_id}/reviews", "post", "companyAccessReviewDeletion"],
  finalizeDeletion: ["/api/v1/company-access/cancellations/{cancellation_id}/finalize", "post", "companyAccessFinalizeDeletion"],
};

if (operation?.operationId !== "systemBoundaryGetTracerStatus") {
  throw new Error(`Expected systemBoundaryGetTracerStatus at ${path}`);
}
if (companyAccessOperation?.operationId !== "companyAccessGetSelectedContext") {
  throw new Error(`Expected companyAccessGetSelectedContext at ${companyAccessPath}`);
}
for (const [name, [operationPath, method, operationId]] of Object.entries(companyAccessOperations)) {
  if (contract.paths?.[operationPath]?.[method]?.operationId !== operationId) {
    throw new Error(`Expected ${operationId} for ${name} at ${operationPath}`);
  }
}

const correlationParameter = operation.parameters?.find(
  (parameter) => parameter.in === "header" && parameter.required === false,
);
if (!correlationParameter || correlationParameter.schema?.type !== "string") {
  throw new Error(`Expected an optional string correlation header at ${path}`);
}
for (const status of ["200", "500", "503"]) {
  const responseHeader =
    operation.responses?.[status]?.headers?.[correlationParameter.name];
  if (responseHeader?.schema?.type !== "string") {
    throw new Error(
      `Expected response ${status} to declare correlation header ${correlationParameter.name}`,
    );
  }
}

function resolveSchema(schema) {
  if (!schema?.$ref) {
    return schema;
  }
  const name = schema.$ref.split("/").at(-1);
  return contract.components?.schemas?.[name];
}

function schemaType(schema) {
  if (schema?.$ref) return schema.$ref.split("/").at(-1);
  if (schema?.anyOf) {
    const values = schema.anyOf.map(schemaType);
    return values.join(" | ");
  }
  if (schema?.type === "null") return "null";
  if (schema?.type === "array") return `${schemaType(schema.items)}[]`;
  if (schema?.type === "string" && schema.const !== undefined) {
    return JSON.stringify(schema.const);
  }
  if (schema?.type === "string" && schema.enum?.length) {
    return schema.enum.map((value) => JSON.stringify(value)).join(" | ");
  }
  if (schema?.type === "string") return "string";
  if (schema?.type === "integer" || schema?.type === "number") return "number";
  if (schema?.type === "boolean") return "boolean";
  if (schema?.type === "object") return "Record<string, unknown>";
  throw new Error(`Unsupported generated-client schema type: ${schema?.type}`);
}

function renderInterface(name, schema) {
  const required = new Set(schema.required ?? []);
  const properties = Object.entries(schema.properties ?? {})
    .map(([property, propertySchema]) => {
      const optional = required.has(property) ? "" : "?";
      return `  ${property}${optional}: ${schemaType(propertySchema)};`;
    })
    .join("\n");
  return `export interface ${name} {\n${properties}\n}`;
}

function renderGuard(name, schema) {
  const allowedProperties = Object.keys(schema.properties ?? {});
  const required = new Set(schema.required ?? []);
  const propertyCheck = (propertySchema, value) => {
    if (propertySchema?.$ref) return `is${schemaType(propertySchema)}(${value})`;
    if (propertySchema?.anyOf) {
      return `(${propertySchema.anyOf.map((candidate) => propertyCheck(candidate, value)).join(" || ")})`;
    }
    if (propertySchema?.type === "null") return `${value} === null`;
    if (propertySchema?.type === "array") {
      return `Array.isArray(${value}) && ${value}.every((item) => ${propertyCheck(propertySchema.items, "item")})`;
    }
    if (propertySchema?.const !== undefined) return `${value} === ${JSON.stringify(propertySchema.const)}`;
    if (propertySchema?.enum?.length) {
      return `(${propertySchema.enum.map((candidate) => `${value} === ${JSON.stringify(candidate)}`).join(" || ")})`;
    }
    if (propertySchema?.type === "object") return `isRecord(${value})`;
    if (propertySchema?.type === "string" && propertySchema.format === "uuid") return `isUuid(${value})`;
    if (propertySchema?.type === "string" && propertySchema.format === "date-time") return `isDateTime(${value})`;
    if (propertySchema?.type === "integer") return `typeof ${value} === "number" && Number.isInteger(${value})`;
    if (propertySchema?.type === "number") return `typeof ${value} === "number" && Number.isFinite(${value})`;
    return `typeof ${value} === "${schemaType(propertySchema)}"`;
  };
  const checks = [
    `    hasOnlyProperties(value, ${JSON.stringify(allowedProperties)})`,
    ...Object.entries(schema.properties ?? {}).map(([property, propertySchema]) => {
      const check = propertyCheck(propertySchema, `value.${property}`);
      return required.has(property)
        ? `    ${check}`
        : `    (value.${property} === undefined || ${check})`;
    }),
  ];
  return `function is${name}(value: unknown): value is ${name} {
  return (
    isRecord(value) &&
${checks.join(" &&\n")}
  );
}`;
}

const successSchema = resolveSchema(
  operation.responses["200"].content["application/json"].schema,
);
const companyContextSchema = contract.components.schemas.CompanyContext;
const companyContextResponseSchema = resolveSchema(
  companyAccessOperation.responses["200"].content["application/json"].schema,
);
const additionalSchemas = Object.fromEntries([
  "CompanyInvitation",
  "CompanyInvitationListResponse",
  "CompanyInvitationResponse",
  "CompanyMembership",
  "CompanyMembershipListResponse",
  "CompanyMembershipResponse",
  "AcceptCompanyInvitationRequest",
  "CreateCompanyInvitationRequest",
  "InvitationLookup",
  "InvitationTokenRequest",
  "CompanyInvitationCommandRequest",
  "AdministerCompanyMembershipRequest",
  "InvitationSideEffectContinuation",
  "InvitationSideEffectContinuationList",
  "InvitationSideEffectCompletion",
  "CompanyCancellationEvidence",
  "CompanyCancellation",
  "CompanyCancellationListResponse",
  "CompanyCancellationResponse",
  "CompanyDeletionReview",
  "CompanyDeletionReviewResponse",
  "RequestCompanyCancellationRequest",
  "ResumeCompanyCancellationRequest",
  "ReviewCompanyDeletionRequest",
  "FinalizeCompanyDeletionRequest",
].map((name) => [name, contract.components.schemas[name]]));
const problemSchema = resolveSchema(
  operation.responses["503"].content["application/problem+json"].schema,
);

const source = `// Generated from contracts/openapi/talli-v1.json. Do not edit by hand.
// Contract version: ${contract.info.version}

${renderInterface("SystemBoundaryStatus", successSchema)}

${renderInterface("CompanyContext", companyContextSchema)}

${renderInterface("CompanyContextResponse", companyContextResponseSchema)}

${Object.entries(additionalSchemas).map(([name, schema]) => renderInterface(name, schema)).join("\n\n")}

${renderInterface("ProblemDetails", problemSchema)}

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
  const match = /^(\\d{4})-(\\d{2})-(\\d{2})T(\\d{2}):(\\d{2}):(\\d{2})(?:\\.\\d+)?(?:Z|([+-])(\\d{2}):(\\d{2}))$/u.exec(value);
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

${renderGuard("SystemBoundaryStatus", successSchema)}

${renderGuard("CompanyContext", companyContextSchema)}

${renderGuard("CompanyContextResponse", companyContextResponseSchema)}

${[
  "CompanyInvitation",
  "CompanyInvitationListResponse",
  "CompanyInvitationResponse",
  "CompanyMembership",
  "CompanyMembershipListResponse",
  "CompanyMembershipResponse",
  "InvitationLookup",
  "InvitationSideEffectContinuation",
  "InvitationSideEffectContinuationList",
  "InvitationSideEffectCompletion",
  "CompanyCancellationEvidence",
  "CompanyCancellation",
  "CompanyCancellationListResponse",
  "CompanyCancellationResponse",
  "CompanyDeletionReview",
  "CompanyDeletionReviewResponse",
].map((name) => renderGuard(name, additionalSchemas[name])).join("\n\n")}

${renderGuard("ProblemDetails", problemSchema)}

export class TalliApiError extends Error {
  readonly status: number;
  readonly problem: ProblemDetails | undefined;

  constructor(
    status: number,
    problem: ProblemDetails | undefined,
  ) {
    super(problem?.code ?? \`HTTP_\${status}\`);
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
  const baseUrl = options.baseUrl.replace(/\\/$/, "");

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
          : { [${JSON.stringify(correlationParameter.name)}]: request.requestId }),
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
    async ${operation.operationId}(
      request: TalliRequestOptions = {},
    ): Promise<SystemBoundaryStatus> {
      const response = await fetchImplementation(\`\${baseUrl}${path}\`, {
        cache: "no-store",
        headers: {
          Accept: "application/json, application/problem+json",
          ...options.headers,
          ...request.headers,
          ...(request.requestId === undefined
            ? {}
            : { [${JSON.stringify(correlationParameter.name)}]: request.requestId }),
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

    async ${companyAccessOperation.operationId}(
      request: CompanyAccessContextRequest = {},
    ): Promise<CompanyContextResponse> {
      const query = new URLSearchParams();
      if (request.companyId !== undefined) query.set("company_id", request.companyId);
      const suffix = query.size ? \`?\${query}\` : "";
      const response = await fetchImplementation(\`\${baseUrl}${companyAccessPath}\${suffix}\`, {
        cache: "no-store",
        headers: {
          Accept: "application/json, application/problem+json",
          ...options.headers,
          ...request.headers,
          ...(request.requestId === undefined
            ? {}
            : { [${JSON.stringify(correlationParameter.name)}]: request.requestId }),
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
        \`\${baseUrl}/api/v1/company-access/invitations?\${query}\`,
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
        \`\${baseUrl}/api/v1/company-access/invitations\`,
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
        \`\${baseUrl}/api/v1/company-access/invitations/lookup\`,
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
        \`\${baseUrl}/api/v1/company-access/invitations/accept\`,
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
        \`\${baseUrl}/api/v1/company-access/invitations/\${encodeURIComponent(invitationId)}/revoke\`,
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
        \`\${baseUrl}/api/v1/company-access/invitations/\${encodeURIComponent(invitationId)}/resend\`,
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
        \`\${baseUrl}/api/v1/company-access/invitation-side-effects/pending\`,
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
        \`\${baseUrl}/api/v1/company-access/invitation-side-effects/\${encodeURIComponent(operationId)}/complete\`,
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
        \`\${baseUrl}/api/v1/company-access/memberships?\${query}\`,
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
        \`\${baseUrl}/api/v1/company-access/memberships/\${encodeURIComponent(userId)}\`,
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
        \`\${baseUrl}/api/v1/company-access/cancellations?\${query}\`,
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
        \`\${baseUrl}/api/v1/company-access/cancellations\`,
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
        \`\${baseUrl}/api/v1/company-access/cancellations/\${encodeURIComponent(cancellationId)}/reviews\`,
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
        \`\${baseUrl}/api/v1/company-access/cancellations/\${encodeURIComponent(cancellationId)}/resume\`,
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
        \`\${baseUrl}/api/v1/company-access/cancellations/\${encodeURIComponent(cancellationId)}/finalize\`,
        "POST",
        request,
        body,
        isCompanyCancellationResponse,
      );
    },
  };
}
`;

if (check) {
  let committed = "";
  try {
    committed = readFileSync(outputPath, "utf8");
  } catch {
    // A missing artifact is contract drift.
  }
  if (committed !== source) {
    console.error("Generated TypeScript client drift detected.");
    process.exitCode = 1;
  }
} else {
  mkdirSync(resolve("packages/talli-api-client/src/generated"), { recursive: true });
  writeFileSync(outputPath, source);
}
