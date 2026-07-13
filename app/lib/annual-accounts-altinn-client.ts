const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const ORG_NUMBER_PATTERN = /^\d{9}$/u;
const PARTY_ID_PATTERN = /^\d{1,20}$/u;
const SAFE_PROVIDER_FIELD_PATTERN = /^[\p{L}\p{N}._:/\-[\]]+$/u;
const UNSAFE_XML_PATTERN = /<!\s*(?:DOCTYPE|ENTITY)\b/iu;
const FORBIDDEN_XML_TEXT_PATTERN = /[\u0000-\u0008\u000B\u000C\u000E-\u001F]/u;
const DEFAULT_TIMEOUT_MS = 20_000;
const DEFAULT_MAX_RESPONSE_BYTES = 10 * 1024 * 1024;
const MAX_XML_BYTES = 10 * 1024 * 1024;
const MAX_DATA_ELEMENTS = 64;
const MAX_VALIDATION_ISSUES = 2_000;

export const ANNUAL_ACCOUNTS_ALTINN_SCOPES = ["altinn:instances.read", "altinn:instances.write"] as const;
export const ANNUAL_ACCOUNTS_ALTINN_READ_SCOPES = ["altinn:instances.read"] as const;

export const ANNUAL_ACCOUNTS_ALTINN_ENDPOINTS = {
  exchange: "https://platform.tt02.altinn.no/authentication/api/v1/exchange/maskinporten",
  app: "https://brg.apps.tt02.altinn.no/brg/aarsregnskap-vanlig-202406",
} as const;

export type AnnualAccountsAltinnTransportRequest = {
  method: "GET" | "POST" | "PUT";
  url: string;
  headers: Readonly<Record<string, string>>;
  body?: string;
  timeoutMs: number;
  maxResponseBytes: number;
};

export type AnnualAccountsAltinnTransportResponse = {
  status: number;
  headers: Readonly<Record<string, string>>;
  body: Uint8Array;
};

export type AnnualAccountsAltinnTransport = (
  request: AnnualAccountsAltinnTransportRequest,
) => Promise<AnnualAccountsAltinnTransportResponse>;

export type AnnualAccountsInstanceRef = {
  ownerPartyId: string;
  instanceGuid: string;
};

export type AnnualAccountsDataElement = {
  id: string;
  instanceGuid: string;
  dataType: string;
  contentType: string;
  filename: string | null;
};

export type AnnualAccountsInstanceSnapshot = {
  instance: AnnualAccountsInstanceRef;
  organizationNumber: string;
  process: {
    endedAt: string | null;
    currentTask: { elementId: string; altinnTaskType: string } | null;
  };
  dataElements: AnnualAccountsDataElement[];
};

export type AnnualAccountsValidationIssue = {
  severity: "Error" | "Warning" | "Informational";
  code: string;
  scope?: string;
  targetId?: string;
  field?: string;
};

export type AnnualAccountsAltinnTestClient = {
  readonly environment: "test";
  inspectInstance(input: {
    instance: AnnualAccountsInstanceRef;
    organizationNumber: string;
  }): Promise<AnnualAccountsInstanceSnapshot>;
  createDraft(input: { organizationNumber: string }): Promise<{
    instance: AnnualAccountsInstanceRef;
    organizationNumber: string;
    currentTask: { elementId: string; altinnTaskType: string };
    dataElements: AnnualAccountsDataElement[];
  }>;
  replaceXmlDataElement(input: {
    instance: AnnualAccountsInstanceRef;
    dataElementId: string;
    xml: string;
  }): Promise<AnnualAccountsDataElement>;
  validateDraft(input: { instance: AnnualAccountsInstanceRef }): Promise<{
    valid: boolean;
    issues: AnnualAccountsValidationIssue[];
  }>;
  lockForPersonalSignature(input: { instance: AnnualAccountsInstanceRef }): Promise<{
    state: "awaiting-person-signature";
    currentTask: { elementId: string; altinnTaskType: string };
  }>;
};

export class AnnualAccountsAltinnError extends Error {
  readonly code: string;
  readonly retryable: boolean;
  readonly status?: number;

  constructor(code: string, message: string, options: { retryable?: boolean; status?: number } = {}) {
    super(message);
    this.name = "AnnualAccountsAltinnError";
    this.code = code;
    this.retryable = options.retryable ?? false;
    this.status = options.status;
  }
}

type ClientOptions = {
  maskinportenAccessToken: string;
  transport?: AnnualAccountsAltinnTransport;
  timeoutMs?: number;
  maxResponseBytes?: number;
};

function altinnError(code: string, message: string, retryable = false, status?: number) {
  return new AnnualAccountsAltinnError(code, message, {
    retryable,
    ...(status === undefined ? {} : { status }),
  });
}

function assertOptions(value: unknown): asserts value is ClientOptions {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw altinnError("annual_accounts_altinn_options_invalid", "Annual-accounts Altinn client options are invalid.");
  }
  if ("environment" in value || "baseUrl" in value || "exchangeUrl" in value || "appUrl" in value) {
    throw altinnError(
      "annual_accounts_altinn_endpoint_override_forbidden",
      "Annual-accounts Altinn test endpoints cannot be overridden.",
    );
  }
}

function assertBearerToken(value: unknown, code: string): string {
  if (typeof value !== "string" || value.length < 8 || value.length > 16_384 || /\s/u.test(value)) {
    throw altinnError(code, "Annual-accounts Altinn requires a bounded short-lived bearer token.");
  }
  return value;
}

function assertBoundedInteger(value: unknown, minimum: number, maximum: number, code: string): number {
  if (!Number.isInteger(value) || (value as number) < minimum || (value as number) > maximum) {
    throw altinnError(code, "Annual-accounts Altinn numeric option is outside the supported range.");
  }
  return value as number;
}

function assertOrganizationNumber(value: unknown): string {
  if (typeof value !== "string" || !ORG_NUMBER_PATTERN.test(value)) {
    throw altinnError("annual_accounts_altinn_org_number_invalid", "Annual-accounts organization number must have nine digits.");
  }
  return value;
}

function assertPartyId(value: unknown): string {
  if (typeof value !== "string" || !PARTY_ID_PATTERN.test(value)) {
    throw altinnError("annual_accounts_altinn_party_id_invalid", "Annual-accounts owner party ID is invalid.");
  }
  return value;
}

function assertUuid(value: unknown, code = "annual_accounts_altinn_uuid_invalid"): string {
  if (typeof value !== "string" || !UUID_PATTERN.test(value)) {
    throw altinnError(code, "Annual-accounts Altinn identifier must be a UUID.");
  }
  return value;
}

function assertInstanceRef(value: unknown): AnnualAccountsInstanceRef {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw altinnError("annual_accounts_altinn_instance_invalid", "Annual-accounts instance reference is invalid.");
  }
  const candidate = value as Partial<AnnualAccountsInstanceRef>;
  return {
    ownerPartyId: assertPartyId(candidate.ownerPartyId),
    instanceGuid: assertUuid(candidate.instanceGuid),
  };
}

function assertXml(value: unknown): string {
  if (typeof value !== "string" || !value.trimStart().startsWith("<")) {
    throw altinnError("annual_accounts_altinn_xml_invalid", "Annual-accounts data must be a non-empty XML document.");
  }
  if (UNSAFE_XML_PATTERN.test(value) || FORBIDDEN_XML_TEXT_PATTERN.test(value)) {
    throw altinnError("annual_accounts_altinn_xml_unsafe", "Annual-accounts XML contains unsupported declarations or characters.");
  }
  if (new TextEncoder().encode(value).byteLength > MAX_XML_BYTES) {
    throw altinnError("annual_accounts_altinn_xml_too_large", "Annual-accounts XML exceeds the supported size limit.");
  }
  return value;
}

function headerValue(headers: Readonly<Record<string, string>>, name: string) {
  return Object.entries(headers).find(([key]) => key.toLowerCase() === name.toLowerCase())?.[1];
}

function normalizedContentType(headers: Readonly<Record<string, string>>) {
  return headerValue(headers, "content-type")?.split(";", 1)[0]?.trim().toLowerCase();
}

function safeProviderField(value: unknown, maximum = 256): string | undefined {
  return typeof value === "string" && value.length > 0 && value.length <= maximum && SAFE_PROVIDER_FIELD_PATTERN.test(value)
    ? value
    : undefined;
}

function ensureObject(value: unknown, code = "annual_accounts_altinn_response_invalid"): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw altinnError(code, "Annual-accounts Altinn returned an invalid response.");
  }
  return value as Record<string, unknown>;
}

function decodeJson(response: AnnualAccountsAltinnTransportResponse): unknown {
  if (normalizedContentType(response.headers) !== "application/json") {
    throw altinnError(
      "annual_accounts_altinn_response_content_type_invalid",
      "Annual-accounts Altinn did not return JSON.",
    );
  }
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(response.body));
  } catch {
    throw altinnError("annual_accounts_altinn_response_invalid", "Annual-accounts Altinn returned invalid JSON.");
  }
}

function ensureResponse(value: unknown, maximum: number): AnnualAccountsAltinnTransportResponse {
  if (!value || typeof value !== "object") {
    throw altinnError("annual_accounts_altinn_transport_invalid", "Annual-accounts transport returned no response.", true);
  }
  const candidate = value as Partial<AnnualAccountsAltinnTransportResponse>;
  if (!Number.isInteger(candidate.status) || !candidate.headers || !(candidate.body instanceof Uint8Array)) {
    throw altinnError("annual_accounts_altinn_transport_invalid", "Annual-accounts transport returned an invalid response.", true);
  }
  if (candidate.body.byteLength > maximum) {
    throw altinnError(
      "annual_accounts_altinn_response_too_large",
      "Annual-accounts Altinn response exceeded the configured limit.",
      true,
    );
  }
  return candidate as AnnualAccountsAltinnTransportResponse;
}

function httpFailure(response: AnnualAccountsAltinnTransportResponse) {
  const retryable =
    response.status === 401 ||
    response.status === 408 ||
    response.status === 425 ||
    response.status === 429 ||
    response.status >= 500;
  const code = `annual_accounts_altinn_http_${response.status}`;
  return altinnError(code, `Annual-accounts Altinn request failed (${code}).`, retryable, response.status);
}

function parseCurrentTask(value: unknown): { elementId: string; altinnTaskType: string } {
  const task = ensureObject(value);
  const elementId = safeProviderField(task.elementId, 128);
  const altinnTaskType = safeProviderField(task.altinnTaskType, 128);
  if (!elementId || !altinnTaskType) {
    throw altinnError("annual_accounts_altinn_response_invalid", "Annual-accounts Altinn returned an invalid process task.");
  }
  return { elementId, altinnTaskType };
}

function parseDataElement(value: unknown, expectedInstanceGuid?: string): AnnualAccountsDataElement {
  const element = ensureObject(value);
  const id = assertUuid(element.id, "annual_accounts_altinn_data_id_invalid");
  const instanceGuid = assertUuid(element.instanceGuid);
  const dataType = safeProviderField(element.dataType, 128);
  const contentType = safeProviderField(element.contentType, 128);
  const filename = element.filename === null || element.filename === undefined
    ? null
    : safeProviderField(element.filename, 512);
  if (!dataType || !contentType || filename === undefined || (expectedInstanceGuid && instanceGuid !== expectedInstanceGuid)) {
    throw altinnError("annual_accounts_altinn_response_invalid", "Annual-accounts Altinn returned an invalid data element.");
  }
  return { id, instanceGuid, dataType, contentType, filename };
}

function parseEndedAt(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (
    typeof value !== "string" ||
    value.length > 40 ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$/u.test(value) ||
    !Number.isFinite(Date.parse(value))
  ) {
    throw altinnError("annual_accounts_altinn_response_invalid", "Annual-accounts Altinn returned an invalid process end time.");
  }
  return value;
}

function parseInstanceSnapshot(value: unknown): AnnualAccountsInstanceSnapshot {
  const response = ensureObject(value);
  const owner = ensureObject(response.instanceOwner);
  const ownerPartyId = assertPartyId(owner.partyId);
  const organizationNumber = assertOrganizationNumber(owner.organisationNumber);
  const id = typeof response.id === "string" ? response.id : "";
  const [idParty, instanceGuidCandidate, extra] = id.split("/");
  const instanceGuid = assertUuid(instanceGuidCandidate);
  if (extra !== undefined || idParty !== ownerPartyId) {
    throw altinnError("annual_accounts_altinn_response_invalid", "Annual-accounts Altinn returned an inconsistent instance ID.");
  }
  const process = ensureObject(response.process);
  const endedAt = parseEndedAt(process.ended);
  const currentTask = process.currentTask === null || process.currentTask === undefined
    ? null
    : parseCurrentTask(process.currentTask);
  if ((endedAt === null) === (currentTask === null)) {
    throw altinnError("annual_accounts_altinn_response_invalid", "Annual-accounts Altinn returned an inconsistent process state.");
  }
  if (!Array.isArray(response.data) || response.data.length > MAX_DATA_ELEMENTS) {
    throw altinnError("annual_accounts_altinn_response_invalid", "Annual-accounts Altinn returned invalid data elements.");
  }
  return {
    instance: { ownerPartyId, instanceGuid },
    organizationNumber,
    process: { endedAt, currentTask },
    dataElements: response.data.map((element) => parseDataElement(element, instanceGuid)),
  };
}

function parseDraft(value: unknown) {
  const snapshot = parseInstanceSnapshot(value);
  if (snapshot.process.endedAt !== null || snapshot.process.currentTask === null) {
    throw altinnError("annual_accounts_altinn_response_invalid", "Annual-accounts Altinn returned an ended draft.");
  }
  return {
    instance: snapshot.instance,
    organizationNumber: snapshot.organizationNumber,
    currentTask: snapshot.process.currentTask,
    dataElements: snapshot.dataElements,
  };
}

function parseValidationIssue(value: unknown): AnnualAccountsValidationIssue {
  const issue = ensureObject(value);
  if (issue.severity !== "Error" && issue.severity !== "Warning" && issue.severity !== "Informational") {
    throw altinnError("annual_accounts_altinn_response_invalid", "Annual-accounts Altinn returned an invalid validation severity.");
  }
  const code = safeProviderField(issue.code, 256);
  const scope = issue.scope === null || issue.scope === undefined ? undefined : safeProviderField(issue.scope, 256);
  const targetId = issue.targetId === null || issue.targetId === undefined ? undefined : assertUuid(issue.targetId);
  const field = issue.field === null || issue.field === undefined ? undefined : safeProviderField(issue.field, 512);
  if (!code || (issue.scope !== null && issue.scope !== undefined && !scope) || (issue.field !== null && issue.field !== undefined && !field)) {
    throw altinnError("annual_accounts_altinn_response_invalid", "Annual-accounts Altinn returned an invalid validation issue.");
  }
  return {
    severity: issue.severity,
    code,
    ...(scope ? { scope } : {}),
    ...(targetId ? { targetId } : {}),
    ...(field ? { field } : {}),
  };
}

async function readBoundedBody(response: Response, maximum: number): Promise<Uint8Array> {
  if (!response.body) return new Uint8Array();
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let length = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    length += value.byteLength;
    if (length > maximum) {
      await reader.cancel();
      throw altinnError(
        "annual_accounts_altinn_response_too_large",
        "Annual-accounts Altinn response exceeded the configured limit.",
        true,
      );
    }
    chunks.push(value);
  }
  const body = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body;
}

export function createFetchAnnualAccountsAltinnTransport(
  fetchImplementation: typeof fetch = fetch,
): AnnualAccountsAltinnTransport {
  return async (request) => {
    const abortController = new AbortController();
    const timeout = setTimeout(() => abortController.abort(), request.timeoutMs);
    try {
      const response = await fetchImplementation(request.url, {
        method: request.method,
        headers: request.headers,
        body: request.body,
        redirect: "error",
        signal: abortController.signal,
      });
      return {
        status: response.status,
        headers: Object.fromEntries(response.headers.entries()),
        body: await readBoundedBody(response, request.maxResponseBytes),
      };
    } catch (error) {
      if (error instanceof AnnualAccountsAltinnError) throw error;
      const timedOut = error instanceof DOMException && error.name === "AbortError";
      throw altinnError(
        timedOut ? "annual_accounts_altinn_transport_timeout" : "annual_accounts_altinn_transport_failed",
        timedOut
          ? "Annual-accounts Altinn request timed out."
          : "Annual-accounts Altinn request failed before a response was received.",
        true,
      );
    } finally {
      clearTimeout(timeout);
    }
  };
}

export function createAnnualAccountsAltinnTestClient(options: ClientOptions): AnnualAccountsAltinnTestClient {
  assertOptions(options);
  const maskinportenAccessToken = assertBearerToken(
    options.maskinportenAccessToken,
    "annual_accounts_altinn_maskinporten_token_invalid",
  );
  const timeoutMs = assertBoundedInteger(
    options.timeoutMs ?? DEFAULT_TIMEOUT_MS,
    1_000,
    60_000,
    "annual_accounts_altinn_timeout_invalid",
  );
  const maxResponseBytes = assertBoundedInteger(
    options.maxResponseBytes ?? DEFAULT_MAX_RESPONSE_BYTES,
    64,
    50 * 1024 * 1024,
    "annual_accounts_altinn_response_limit_invalid",
  );
  const transport = options.transport ?? createFetchAnnualAccountsAltinnTransport();
  let exchangePromise: Promise<string> | undefined;
  const instanceRevisions = new Map<string, number>();
  const validatedRevisions = new Map<string, number>();

  async function request(
    input: Omit<AnnualAccountsAltinnTransportRequest, "timeoutMs" | "maxResponseBytes">,
    expectedStatuses: readonly number[],
  ) {
    let transported: unknown;
    try {
      transported = await transport({ ...input, timeoutMs, maxResponseBytes });
    } catch (error) {
      if (error instanceof AnnualAccountsAltinnError) throw error;
      throw altinnError(
        "annual_accounts_altinn_transport_failed",
        "Annual-accounts Altinn request failed before a response was received.",
        true,
      );
    }
    const response = ensureResponse(transported, maxResponseBytes);
    if (!expectedStatuses.includes(response.status)) throw httpFailure(response);
    return response;
  }

  async function exchangeAccessToken() {
    const response = await request(
      {
        method: "GET",
        url: ANNUAL_ACCOUNTS_ALTINN_ENDPOINTS.exchange,
        headers: {
          Authorization: `Bearer ${maskinportenAccessToken}`,
          Accept: "text/plain",
        },
      },
      [200],
    );
    if (normalizedContentType(response.headers) !== "text/plain") {
      throw altinnError(
        "annual_accounts_altinn_exchange_content_type_invalid",
        "Annual-accounts Altinn token exchange did not return plain text.",
      );
    }
    let token: string;
    try {
      token = new TextDecoder("utf-8", { fatal: true }).decode(response.body).trim();
    } catch {
      throw altinnError("annual_accounts_altinn_exchange_invalid", "Annual-accounts Altinn token exchange returned invalid text.");
    }
    return assertBearerToken(token, "annual_accounts_altinn_exchange_invalid");
  }

  async function altinnAccessToken() {
    if (!exchangePromise) {
      exchangePromise = exchangeAccessToken().catch((error) => {
        exchangePromise = undefined;
        throw error;
      });
    }
    return exchangePromise;
  }

  async function appRequest(
    input: Omit<AnnualAccountsAltinnTransportRequest, "timeoutMs" | "maxResponseBytes" | "headers"> & {
      headers?: Readonly<Record<string, string>>;
    },
    expectedStatuses: readonly number[],
  ) {
    const token = await altinnAccessToken();
    return request(
      {
        ...input,
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: "application/json",
          ...input.headers,
        },
      },
      expectedStatuses,
    );
  }

  function instanceBase(instanceValue: unknown) {
    const instance = assertInstanceRef(instanceValue);
    return {
      instance,
      key: `${instance.ownerPartyId}/${instance.instanceGuid}`,
      url: `${ANNUAL_ACCOUNTS_ALTINN_ENDPOINTS.app}/instances/${instance.ownerPartyId}/${instance.instanceGuid}`,
    };
  }

  return {
    environment: "test",
    async inspectInstance(input) {
      const { instance, url } = instanceBase(input?.instance);
      const organizationNumber = assertOrganizationNumber(input?.organizationNumber);
      const response = await appRequest({ method: "GET", url }, [200]);
      const snapshot = parseInstanceSnapshot(decodeJson(response));
      if (
        snapshot.instance.ownerPartyId !== instance.ownerPartyId ||
        snapshot.instance.instanceGuid !== instance.instanceGuid ||
        snapshot.organizationNumber !== organizationNumber
      ) {
        throw altinnError("annual_accounts_altinn_response_invalid", "Annual-accounts Altinn returned the wrong instance owner.");
      }
      return snapshot;
    },
    async createDraft(input) {
      const organizationNumber = assertOrganizationNumber(input?.organizationNumber);
      const response = await appRequest(
        {
          method: "POST",
          url: `${ANNUAL_ACCOUNTS_ALTINN_ENDPOINTS.app}/instances/create`,
          headers: { "Content-Type": "application/json; charset=utf-8" },
          body: JSON.stringify({ instanceOwner: { organisationNumber: organizationNumber } }),
        },
        [201],
      );
      const draft = parseDraft(decodeJson(response));
      if (draft.organizationNumber !== organizationNumber) {
        throw altinnError("annual_accounts_altinn_response_invalid", "Annual-accounts Altinn returned the wrong instance owner.");
      }
      const key = `${draft.instance.ownerPartyId}/${draft.instance.instanceGuid}`;
      instanceRevisions.set(key, 0);
      validatedRevisions.delete(key);
      return draft;
    },
    async replaceXmlDataElement(input) {
      const { instance, key, url } = instanceBase(input?.instance);
      const dataElementId = assertUuid(input?.dataElementId, "annual_accounts_altinn_data_id_invalid");
      const xml = assertXml(input?.xml);
      const response = await appRequest(
        {
          method: "PUT",
          url: `${url}/data/${dataElementId}`,
          headers: { "Content-Type": "application/xml; charset=utf-8" },
          body: xml,
        },
        [200, 201],
      );
      const element = parseDataElement(decodeJson(response), instance.instanceGuid);
      if (element.id !== dataElementId) {
        throw altinnError("annual_accounts_altinn_response_invalid", "Annual-accounts Altinn returned the wrong data element.");
      }
      instanceRevisions.set(key, (instanceRevisions.get(key) ?? 0) + 1);
      validatedRevisions.delete(key);
      return element;
    },
    async validateDraft(input) {
      const { key, url } = instanceBase(input?.instance);
      const response = await appRequest({ method: "GET", url: `${url}/validate` }, [200]);
      const value = decodeJson(response);
      if (!Array.isArray(value) || value.length > MAX_VALIDATION_ISSUES) {
        throw altinnError("annual_accounts_altinn_response_invalid", "Annual-accounts Altinn returned invalid validation feedback.");
      }
      const issues = value.map(parseValidationIssue);
      const valid = issues.every((issue) => issue.severity !== "Error");
      if (valid) {
        validatedRevisions.set(key, instanceRevisions.get(key) ?? 0);
      } else {
        validatedRevisions.delete(key);
      }
      return { valid, issues };
    },
    async lockForPersonalSignature(input) {
      const { key, url } = instanceBase(input?.instance);
      const currentRevision = instanceRevisions.get(key) ?? 0;
      if (validatedRevisions.get(key) !== currentRevision) {
        throw altinnError(
          "annual_accounts_altinn_validation_required",
          "Annual-accounts draft must pass validation after its latest data change before it can be locked.",
        );
      }
      const response = await appRequest(
        {
          method: "PUT",
          url: `${url}/process/next`,
          headers: { "Content-Type": "application/json; charset=utf-8" },
          body: JSON.stringify({ action: "confirm" }),
        },
        [200],
      );
      const process = ensureObject(decodeJson(response));
      const currentTask = parseCurrentTask(process.currentTask);
      if (
        (process.ended !== null && process.ended !== undefined) ||
        currentTask.altinnTaskType.toLowerCase() !== "signing"
      ) {
        throw altinnError(
          "annual_accounts_altinn_signature_boundary_invalid",
          "Annual-accounts process unexpectedly ended before personal signing.",
        );
      }
      validatedRevisions.delete(key);
      return { state: "awaiting-person-signature" as const, currentTask };
    },
  };
}
