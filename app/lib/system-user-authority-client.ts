import {
  SYSTEM_USER_CALLBACK_URL,
  SYSTEM_USER_RIGHT,
  SYSTEM_USER_SYSTEM_ID,
  type SystemUserRequestStatus,
} from "./system-user-requests.ts";

export type SystemUserAuthorityEnvironment = "tt02" | "production";

type AuthorityRequestStatus = Exclude<
  SystemUserRequestStatus,
  "creating" | "verification_failed"
>;

export type SystemUserAuthorityResponse = {
  id: string;
  externalRef: string;
  systemId: typeof SYSTEM_USER_SYSTEM_ID;
  partyOrgNo: string;
  rights: Array<{
    resource: Array<{
      id: "urn:altinn:resource";
      value: typeof SYSTEM_USER_RIGHT;
    }>;
  }>;
  status: AuthorityRequestStatus;
  redirectUrl: typeof SYSTEM_USER_CALLBACK_URL;
  confirmUrl: string | null;
};

export type QueriedSystemUser = {
  id: string;
  systemId: string;
  reporteeOrgNo: string;
  externalRef: string;
  userType: "standard";
  isDeleted: boolean;
};

export type SystemUserAuthorityClient = {
  createRequest(input: {
    bearerToken: string;
    partyOrgNo: string;
    externalRef: string;
  }): Promise<SystemUserAuthorityResponse>;
  getRequest(input: {
    bearerToken: string;
    requestId: string;
    partyOrgNo: string;
    externalRef: string;
  }): Promise<SystemUserAuthorityResponse>;
  getRequestByExternalRef(input: {
    bearerToken: string;
    partyOrgNo: string;
    externalRef: string;
  }): Promise<SystemUserAuthorityResponse>;
  querySystemUser(input: {
    bearerToken: string;
    partyOrgNo: string;
    externalRef: string;
  }): Promise<QueriedSystemUser>;
};

type FetchLike = (
  input: string | URL | globalThis.Request,
  init?: RequestInit,
) => Promise<Response>;

type CreateSystemUserAuthorityClientInput = {
  environment: SystemUserAuthorityEnvironment;
  fetchImpl?: FetchLike;
  timeoutMs?: number;
};

export type ValidateSystemUserAuthorityResponseInput = {
  environment: SystemUserAuthorityEnvironment;
  partyOrgNo: string;
  externalRef: string;
};

export type SystemUserAuthorityErrorCode =
  | "invalid_environment"
  | "invalid_timeout"
  | "invalid_bearer_token"
  | "invalid_organization_number"
  | "invalid_external_reference"
  | "invalid_request_id"
  | "network_error"
  | "response_too_large"
  | "response_contract_mismatch"
  | "invalid_confirmation_url"
  | "duplicate_system_user_request"
  | "authority_http_error";

export class SystemUserAuthorityError extends Error {
  readonly status: number | null;
  readonly code: SystemUserAuthorityErrorCode;
  readonly authorityCode: "AUTH-00007" | null;
  readonly retryable: boolean;

  constructor(
    code: SystemUserAuthorityErrorCode,
    options: {
      status?: number | null;
      authorityCode?: "AUTH-00007" | null;
      retryable?: boolean;
    } = {},
  ) {
    super(code);
    this.name = "SystemUserAuthorityError";
    this.status = options.status ?? null;
    this.code = code;
    this.authorityCode = options.authorityCode ?? null;
    this.retryable = options.retryable ?? false;
  }
}

const MAX_RESPONSE_BYTES = 65_536;
const DEFAULT_TIMEOUT_MS = 15_000;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu;
const EXTERNAL_REF_PATTERN = /^[A-Za-z0-9_-]{43}$/u;
const ORGANIZATION_NUMBER_PATTERN = /^\d{9}$/u;
const CONFIRMATION_PATH = "/accessmanagement/ui/systemuser/request";

const BASE_URLS: Record<SystemUserAuthorityEnvironment, string> = {
  tt02: "https://platform.tt02.altinn.no",
  production: "https://platform.altinn.no",
};

const CONFIRMATION_HOSTS: Record<SystemUserAuthorityEnvironment, ReadonlySet<string>> = {
  tt02: new Set(["am.ui.at22.altinn.cloud", "authn.ui.tt02.altinn.no"]),
  production: new Set(["am.ui.altinn.no"]),
};

const AUTHORITY_STATUSES: Readonly<Record<string, AuthorityRequestStatus>> = {
  New: "new",
  new: "new",
  Accepted: "accepted",
  accepted: "accepted",
  Rejected: "rejected",
  rejected: "rejected",
  Denied: "denied",
  denied: "denied",
  TimedOut: "timedout",
  timedout: "timedout",
};

const AUTHORITY_ERROR_CODES = {
  "AUTH-00007": "duplicate_system_user_request",
} as const satisfies Readonly<Record<string, SystemUserAuthorityErrorCode>>;

function fail(code: SystemUserAuthorityErrorCode): never {
  throw new SystemUserAuthorityError(code);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const sortedExpected = [...expected].sort();
  return actual.length === sortedExpected.length
    && actual.every((key, index) => key === sortedExpected[index]);
}

function requiredBearerToken(value: unknown): string {
  if (
    typeof value !== "string"
    || value.length < 1
    || value.length > 8_192
    || value !== value.trim()
    || /\s|[\u0000-\u001f\u007f]/u.test(value)
  ) {
    fail("invalid_bearer_token");
  }
  return value;
}

function requiredOrganizationNumber(value: unknown): string {
  if (typeof value !== "string" || !ORGANIZATION_NUMBER_PATTERN.test(value)) {
    fail("invalid_organization_number");
  }
  return value;
}

function requiredExternalRef(value: unknown): string {
  if (typeof value !== "string" || !EXTERNAL_REF_PATTERN.test(value)) {
    fail("invalid_external_reference");
  }
  return value;
}

function requiredRequestId(value: unknown): string {
  if (typeof value !== "string" || !UUID_PATTERN.test(value)) {
    fail("invalid_request_id");
  }
  return value;
}

function responseMismatch(): never {
  fail("response_contract_mismatch");
}

function normalizeAuthorityStatus(value: unknown): AuthorityRequestStatus {
  if (typeof value !== "string") responseMismatch();
  const normalized = AUTHORITY_STATUSES[value];
  if (!normalized) responseMismatch();
  return normalized;
}

function hasExactRight(value: unknown): boolean {
  if (!Array.isArray(value) || value.length !== 1) return false;
  const right = value[0];
  if (!isRecord(right) || !hasExactKeys(right, ["resource"])) return false;
  if (!Array.isArray(right.resource) || right.resource.length !== 1) return false;
  const resource = right.resource[0];
  return isRecord(resource)
    && hasExactKeys(resource, ["id", "value"])
    && resource.id === "urn:altinn:resource"
    && resource.value === SYSTEM_USER_RIGHT;
}

function validateConfirmationUrl(
  value: unknown,
  environment: SystemUserAuthorityEnvironment,
  requestId: string,
): string | null {
  if (value === null) return null;
  if (typeof value !== "string" || value.length > 2_048) fail("invalid_confirmation_url");

  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    fail("invalid_confirmation_url");
  }

  const ids = parsed.searchParams.getAll("id");
  if (
    parsed.protocol !== "https:"
    || parsed.username !== ""
    || parsed.password !== ""
    || parsed.port !== ""
    || !CONFIRMATION_HOSTS[environment].has(parsed.hostname)
    || parsed.pathname !== CONFIRMATION_PATH
    || parsed.hash !== ""
    || ids.length !== 1
    || ids[0] !== requestId
  ) {
    fail("invalid_confirmation_url");
  }

  return value;
}

export function validateSystemUserAuthorityResponse(
  value: unknown,
  expected: ValidateSystemUserAuthorityResponseInput,
): SystemUserAuthorityResponse {
  const partyOrgNo = requiredOrganizationNumber(expected.partyOrgNo);
  const externalRef = requiredExternalRef(expected.externalRef);
  if (!BASE_URLS[expected.environment]) fail("invalid_environment");
  if (!isRecord(value) || !hasExactKeys(value, [
    "id",
    "externalRef",
    "systemId",
    "partyOrgNo",
    "rights",
    "status",
    "redirectUrl",
    "confirmUrl",
  ])) {
    responseMismatch();
  }

  if (typeof value.id !== "string" || !UUID_PATTERN.test(value.id)) responseMismatch();
  if (value.externalRef !== externalRef || !EXTERNAL_REF_PATTERN.test(value.externalRef)) {
    responseMismatch();
  }
  if (value.systemId !== SYSTEM_USER_SYSTEM_ID) responseMismatch();
  if (
    value.partyOrgNo !== partyOrgNo
    || typeof value.partyOrgNo !== "string"
    || !ORGANIZATION_NUMBER_PATTERN.test(value.partyOrgNo)
  ) {
    responseMismatch();
  }
  if (!hasExactRight(value.rights)) responseMismatch();
  const status = normalizeAuthorityStatus(value.status);
  if (value.redirectUrl !== SYSTEM_USER_CALLBACK_URL) responseMismatch();
  const confirmUrl = validateConfirmationUrl(value.confirmUrl, expected.environment, value.id);
  if (status === "new" && confirmUrl === null) responseMismatch();

  return {
    id: value.id,
    externalRef,
    systemId: SYSTEM_USER_SYSTEM_ID,
    partyOrgNo,
    rights: [{
      resource: [{ id: "urn:altinn:resource", value: SYSTEM_USER_RIGHT }],
    }],
    status,
    redirectUrl: SYSTEM_USER_CALLBACK_URL,
    confirmUrl,
  };
}

function validateQueriedSystemUser(
  value: unknown,
  expected: { partyOrgNo: string; externalRef: string },
): QueriedSystemUser {
  if (!isRecord(value) || !hasExactKeys(value, [
    "id",
    "systemId",
    "reporteeOrgNo",
    "externalRef",
    "userType",
    "isDeleted",
  ])) {
    responseMismatch();
  }
  if (typeof value.id !== "string" || !UUID_PATTERN.test(value.id)) responseMismatch();
  if (value.systemId !== SYSTEM_USER_SYSTEM_ID) responseMismatch();
  if (value.reporteeOrgNo !== expected.partyOrgNo) responseMismatch();
  if (value.externalRef !== expected.externalRef) responseMismatch();
  if (value.userType !== "standard") responseMismatch();
  if (typeof value.isDeleted !== "boolean") responseMismatch();

  return {
    id: value.id,
    systemId: SYSTEM_USER_SYSTEM_ID,
    reporteeOrgNo: expected.partyOrgNo,
    externalRef: expected.externalRef,
    userType: "standard",
    isDeleted: value.isDeleted,
  };
}

async function cancelQuietly(reader: ReadableStreamDefaultReader<Uint8Array>): Promise<void> {
  try {
    await reader.cancel();
  } catch {
    // The bounded response has already been rejected; cancellation is best effort.
  }
}

async function readBoundedResponse(response: Response): Promise<string> {
  if (!response.body) return "";
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let byteLength = 0;

  while (true) {
    let result: ReadableStreamReadResult<Uint8Array>;
    try {
      result = await reader.read();
    } catch {
      await cancelQuietly(reader);
      fail("network_error");
    }
    if (result.done) break;
    byteLength += result.value.byteLength;
    if (byteLength > MAX_RESPONSE_BYTES) {
      await cancelQuietly(reader);
      fail("response_too_large");
    }
    chunks.push(result.value);
  }

  const bytes = new Uint8Array(byteLength);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    responseMismatch();
  }
}

function safeAuthorityCode(value: unknown): keyof typeof AUTHORITY_ERROR_CODES | null {
  if (!isRecord(value)) return null;
  const candidates = [value.code, value.errorCode, value.error];
  for (const candidate of candidates) {
    if (typeof candidate === "string" && Object.hasOwn(AUTHORITY_ERROR_CODES, candidate)) {
      return candidate as keyof typeof AUTHORITY_ERROR_CODES;
    }
  }
  return null;
}

function authorityHttpError(status: number, parsed: unknown): SystemUserAuthorityError {
  const authorityCode = safeAuthorityCode(parsed);
  const retryable = status === 408 || status === 425 || status === 429 || status >= 500;
  if (authorityCode) {
    return new SystemUserAuthorityError(AUTHORITY_ERROR_CODES[authorityCode], {
      status,
      authorityCode,
      retryable,
    });
  }
  return new SystemUserAuthorityError("authority_http_error", { status, retryable });
}

export function createSystemUserAuthorityClient(
  input: CreateSystemUserAuthorityClientInput,
): SystemUserAuthorityClient {
  const baseUrl = (BASE_URLS as Readonly<Record<string, string | undefined>>)[input.environment];
  if (!baseUrl) fail("invalid_environment");
  const timeoutMs = input.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1_000 || timeoutMs > 120_000) {
    fail("invalid_timeout");
  }
  const fetchImpl = input.fetchImpl ?? fetch;
  const requestBase = `${baseUrl}/authentication/api/v1/systemuser/request/vendor`;

  async function request(options: {
    method: "GET" | "POST";
    url: string;
    bearerToken: string;
    body?: string;
  }): Promise<unknown> {
    const headers: Record<string, string> = {
      accept: "application/json",
      authorization: `Bearer ${options.bearerToken}`,
    };
    if (options.body !== undefined) headers["content-type"] = "application/json";

    let response: Response;
    try {
      response = await fetchImpl(options.url, {
        method: options.method,
        headers,
        body: options.body,
        cache: "no-store",
        redirect: "error",
        signal: AbortSignal.timeout(timeoutMs),
      });
    } catch {
      fail("network_error");
    }

    const raw = await readBoundedResponse(response);
    let parsed: unknown = {};
    if (raw) {
      try {
        parsed = JSON.parse(raw) as unknown;
      } catch {
        if (response.ok) responseMismatch();
      }
    }
    if (!response.ok) throw authorityHttpError(response.status, parsed);
    if (!raw) responseMismatch();
    return parsed;
  }

  return {
    async createRequest(requestInput) {
      const bearerToken = requiredBearerToken(requestInput.bearerToken);
      const partyOrgNo = requiredOrganizationNumber(requestInput.partyOrgNo);
      const externalRef = requiredExternalRef(requestInput.externalRef);
      const parsed = await request({
        method: "POST",
        url: requestBase,
        bearerToken,
        body: JSON.stringify({
          externalRef,
          systemId: SYSTEM_USER_SYSTEM_ID,
          partyOrgNo,
          rights: [{
            resource: [{ id: "urn:altinn:resource", value: SYSTEM_USER_RIGHT }],
          }],
          redirectUrl: SYSTEM_USER_CALLBACK_URL,
        }),
      });
      return validateSystemUserAuthorityResponse(parsed, {
        environment: input.environment,
        partyOrgNo,
        externalRef,
      });
    },

    async getRequest(requestInput) {
      const bearerToken = requiredBearerToken(requestInput.bearerToken);
      const requestId = requiredRequestId(requestInput.requestId);
      const partyOrgNo = requiredOrganizationNumber(requestInput.partyOrgNo);
      const externalRef = requiredExternalRef(requestInput.externalRef);
      const parsed = await request({
        method: "GET",
        url: `${requestBase}/${requestId}`,
        bearerToken,
      });
      return validateSystemUserAuthorityResponse(parsed, {
        environment: input.environment,
        partyOrgNo,
        externalRef,
      });
    },

    async getRequestByExternalRef(requestInput) {
      const bearerToken = requiredBearerToken(requestInput.bearerToken);
      const partyOrgNo = requiredOrganizationNumber(requestInput.partyOrgNo);
      const externalRef = requiredExternalRef(requestInput.externalRef);
      const parsed = await request({
        method: "GET",
        url: `${requestBase}/byexternalref/${SYSTEM_USER_SYSTEM_ID}/${partyOrgNo}/${externalRef}`,
        bearerToken,
      });
      return validateSystemUserAuthorityResponse(parsed, {
        environment: input.environment,
        partyOrgNo,
        externalRef,
      });
    },

    async querySystemUser(requestInput) {
      const bearerToken = requiredBearerToken(requestInput.bearerToken);
      const partyOrgNo = requiredOrganizationNumber(requestInput.partyOrgNo);
      const externalRef = requiredExternalRef(requestInput.externalRef);
      const query = new URLSearchParams({
        "system-id": SYSTEM_USER_SYSTEM_ID,
        orgno: partyOrgNo,
      });
      const parsed = await request({
        method: "GET",
        url: `${baseUrl}/authentication/api/v1/systemuser/vendor/byquery?${query.toString()}`,
        bearerToken,
      });
      return validateQueriedSystemUser(parsed, { partyOrgNo, externalRef });
    },
  };
}
