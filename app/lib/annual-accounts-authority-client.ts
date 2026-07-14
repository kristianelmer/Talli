export type AnnualAccountsAuthorityEnvironment = "test" | "production";

type FetchLike = (
  input: string | URL | globalThis.Request,
  init?: RequestInit,
) => Promise<Response>;

type AuthorityClientInput = {
  environment: AnnualAccountsAuthorityEnvironment;
  altinnAccessToken: string;
  fetch?: FetchLike;
  timeoutMs?: number;
};

type ExchangeInput = {
  environment: AnnualAccountsAuthorityEnvironment;
  maskinportenAccessToken: string;
  fetch?: FetchLike;
  timeoutMs?: number;
};

type EnvironmentEndpoints = {
  altinnPlatformBase: string;
  altinnAppBase: string;
};

type ParsedResponse = {
  raw: string;
  data: unknown;
};

export type AnnualAccountsValidationIssue = {
  severity: string;
  code: string;
  field: string;
  message: string;
};

export type AnnualAccountsValidationSummary = {
  hasErrors: boolean;
  issues: AnnualAccountsValidationIssue[];
};

const ENDPOINTS: Record<AnnualAccountsAuthorityEnvironment, EnvironmentEndpoints> = {
  test: {
    altinnPlatformBase: "https://platform.tt02.altinn.no",
    altinnAppBase: "https://brg.apps.tt02.altinn.no/brg/aarsregnskap-vanlig-202406",
  },
  production: {
    altinnPlatformBase: "https://platform.altinn.no",
    altinnAppBase: "https://brg.apps.altinn.no/brg/aarsregnskap-vanlig-202406",
  },
};

const MAIN_DATA_TYPE = "Hovedskjema";
const COMPANY_ACCOUNTS_DATA_TYPE = "Underskjema";
const INSTANCE_ID_PATTERN = /^\d+\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu;
const DATA_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu;

export class AnnualAccountsAuthorityError extends Error {
  readonly status: number | null;
  readonly code: string;
  readonly correlationId: string | null;
  readonly retryable: boolean;
  readonly validationCodes: string[];

  constructor(
    message: string,
    options: {
      status?: number | null;
      code?: string;
      correlationId?: string | null;
      retryable?: boolean;
      validationCodes?: string[];
      cause?: unknown;
    } = {},
  ) {
    super(message, options.cause === undefined ? undefined : { cause: options.cause });
    this.name = "AnnualAccountsAuthorityError";
    this.status = options.status ?? null;
    this.code = options.code ?? "ANNUAL_ACCOUNTS_AUTHORITY_ERROR";
    this.correlationId = options.correlationId ?? null;
    this.retryable = options.retryable ?? false;
    this.validationCodes = options.validationCodes ?? [];
  }
}

function safeString(value: unknown, fallback = ""): string {
  if (typeof value !== "string") return fallback;
  return value
    .replace(/[\u0000-\u001f\u007f]/gu, " ")
    .replace(/\s+/gu, " ")
    .trim()
    .slice(0, 500);
}

function safeObject(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function opaqueToken(value: string | undefined, label: string): string {
  if (!value || value !== value.trim() || /\s/u.test(value)) {
    throw new Error(`${label} is required and must be opaque.`);
  }
  return value;
}

function validTimeout(value: number | undefined): number {
  const timeoutMs = value ?? 20_000;
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1_000 || timeoutMs > 120_000) {
    throw new Error("Annual accounts authority timeout must be between 1000 and 120000 milliseconds.");
  }
  return timeoutMs;
}

function validOrgNumber(value: string): string {
  if (!/^\d{9}$/u.test(value)) {
    throw new Error("Annual accounts organization number must contain 9 digits.");
  }
  return value;
}

function validInstanceId(value: string): string {
  if (!INSTANCE_ID_PATTERN.test(value)) {
    throw new Error("Annual accounts Altinn instance id must contain party id and instance UUID.");
  }
  return value;
}

function validDataId(value: string): string {
  if (!DATA_ID_PATTERN.test(value)) {
    throw new Error("Annual accounts Altinn data id must be a UUID.");
  }
  return value;
}

function requiredXml(value: string, label: string): string {
  if (!value?.trim() || !value.trimStart().startsWith("<")) {
    throw new Error(`${label} XML is required.`);
  }
  return value;
}

function parseRemoteError(status: number, raw: string): AnnualAccountsAuthorityError {
  let parsed: unknown = {};
  try {
    parsed = raw ? JSON.parse(raw) : {};
  } catch {
    parsed = {};
  }
  const data = safeObject(parsed);
  const title = safeString(data.title || data.error || data.message, `Authority returned HTTP ${status}.`);
  const correlationId = safeString(
    data.traceId || data.trace_id || data.correlationId || data.korrelasjonsid,
  ) || null;
  return new AnnualAccountsAuthorityError(
    `Annual accounts authority request was rejected: ${title}`,
    {
      status,
      code: safeString(data.code || data.error, `ANNUAL_ACCOUNTS_HTTP_${status}`),
      correlationId,
      retryable: status === 401 || status === 408 || status === 425 || status === 429 || status >= 500,
    },
  );
}

async function authorityRequest(options: {
  fetch: FetchLike;
  url: string;
  method: "GET" | "POST" | "PUT";
  token: string;
  timeoutMs: number;
  headers?: Record<string, string>;
  body?: string;
}): Promise<ParsedResponse> {
  let response: Response;
  try {
    response = await options.fetch(options.url, {
      method: options.method,
      headers: {
        authorization: `Bearer ${options.token}`,
        ...options.headers,
      },
      body: options.body,
      signal: AbortSignal.timeout(options.timeoutMs),
    });
  } catch (cause) {
    throw new AnnualAccountsAuthorityError(
      "Annual accounts authority request failed before a response was received.",
      { code: "ANNUAL_ACCOUNTS_NETWORK_ERROR", retryable: true, cause },
    );
  }

  const raw = await response.text();
  if (!response.ok) throw parseRemoteError(response.status, raw);
  let data: unknown = {};
  try {
    data = raw ? JSON.parse(raw) : {};
  } catch {
    data = {};
  }
  return { raw, data };
}

function dataElements(value: unknown): Record<string, unknown>[] {
  const data = safeObject(value);
  return Array.isArray(data.data) ? data.data.map(safeObject) : [];
}

function dataElementId(value: unknown, dataType: string): string | null {
  const matches = dataElements(value)
    .filter((element) => safeString(element.dataType) === dataType)
    .map((element) => safeString(element.id))
    .filter(Boolean);
  return matches.length === 1 ? validDataId(matches[0]) : null;
}

function dataElement(value: unknown, dataType: string): Record<string, unknown> | null {
  const matches = dataElements(value)
    .filter((element) => safeString(element.dataType) === dataType);
  return matches.length === 1 ? matches[0] : null;
}

function isoDateTime(value: unknown): string | null {
  const candidate = safeString(value);
  return candidate && !Number.isNaN(Date.parse(candidate)) ? candidate : null;
}

function processTask(value: unknown): string {
  const data = safeObject(value);
  const process = safeObject(data.process);
  const currentTask = safeObject(process.currentTask);
  return safeString(currentTask.altinnTaskType || currentTask.elementId, "unknown");
}

function validationIssues(value: unknown): AnnualAccountsValidationIssue[] {
  const container = safeObject(value);
  const rawIssues = Array.isArray(value)
    ? value
    : Array.isArray(container.validationIssues)
      ? container.validationIssues
      : [];
  return rawIssues.map(safeObject).map((issue) => ({
    severity: safeString(issue.severity, "Unknown"),
    code: safeString(issue.code, "ANNUAL_ACCOUNTS_VALIDATION_ISSUE"),
    field: safeString(issue.field),
    message: safeString(issue.message),
  }));
}

function isErrorSeverity(value: string): boolean {
  return value.toLocaleLowerCase("en") === "error";
}

export async function exchangeMaskinportenForAnnualAccountsAltinnToken(
  input: ExchangeInput,
): Promise<string> {
  const endpoints = ENDPOINTS[input.environment];
  if (!endpoints) throw new Error("Annual accounts authority environment must be test or production.");
  const token = opaqueToken(input.maskinportenAccessToken, "Maskinporten access token");
  const result = await authorityRequest({
    fetch: input.fetch ?? fetch,
    url: `${endpoints.altinnPlatformBase}/authentication/api/v1/exchange/maskinporten`,
    method: "GET",
    token,
    timeoutMs: validTimeout(input.timeoutMs),
    headers: { accept: "text/plain" },
  });
  return opaqueToken(result.raw, "Altinn access token");
}

export type AnnualAccountsAuthorityClient = ReturnType<typeof createAnnualAccountsAuthorityClient>;

// Endpoint sequence follows Brønnøysundregistrene's official RR0002 Postman flow:
// https://brreg.github.io/docs/apidokumentasjon/regnskapsregisteret/maskinell-innrapportering/eksempler-paa-registrering/
export function createAnnualAccountsAuthorityClient(input: AuthorityClientInput) {
  const endpoints = ENDPOINTS[input.environment];
  if (!endpoints) throw new Error("Annual accounts authority environment must be test or production.");
  if (input.environment === "production") {
    throw new Error("Annual accounts production authority transport is disabled.");
  }
  const altinnAccessToken = opaqueToken(input.altinnAccessToken, "Annual accounts Altinn access token");
  const fetchImplementation = input.fetch ?? fetch;
  const timeoutMs = validTimeout(input.timeoutMs);

  function instanceUrl(instanceId: string): string {
    return `${endpoints.altinnAppBase}/instances/${validInstanceId(instanceId)}`;
  }

  async function uploadXml(options: {
    instanceId: string;
    dataId: string;
    xml: string;
    label: string;
  }) {
    const id = validInstanceId(options.instanceId);
    const dataId = validDataId(options.dataId);
    const body = requiredXml(options.xml, options.label);
    await authorityRequest({
      fetch: fetchImplementation,
      url: `${endpoints.altinnAppBase}/instances/${id}/data/${dataId}`,
      method: "PUT",
      token: altinnAccessToken,
      timeoutMs,
      headers: { accept: "application/json", "content-type": "application/xml" },
      body,
    });
    return { dataId, uploaded: true as const };
  }

  return {
    environment: input.environment,

    async createInstance(options: { companyOrgNumber: string }) {
      const companyOrgNumber = validOrgNumber(options.companyOrgNumber);
      const result = await authorityRequest({
        fetch: fetchImplementation,
        url: `${endpoints.altinnAppBase}/instances/create`,
        method: "POST",
        token: altinnAccessToken,
        timeoutMs,
        headers: { accept: "application/json", "content-type": "application/json" },
        body: JSON.stringify({ instanceOwner: { organisationNumber: companyOrgNumber } }),
      });
      const response = safeObject(result.data);
      const id = validInstanceId(safeString(response.id));
      const mainForm = dataElementId(result.data, MAIN_DATA_TYPE);
      const companyAccounts = dataElementId(result.data, COMPANY_ACCOUNTS_DATA_TYPE);
      if (!mainForm || !companyAccounts) {
        throw new AnnualAccountsAuthorityError(
          "Altinn did not create exactly one main form and one company-accounts data element.",
          { code: "ANNUAL_ACCOUNTS_DATA_ELEMENTS_MISSING" },
        );
      }
      return {
        id,
        dataIds: { mainForm, companyAccounts },
        processTask: processTask(result.data),
      };
    },

    async uploadMainForm(options: { instanceId: string; dataId: string; xml: string }) {
      return uploadXml({ ...options, label: "Annual accounts main form" });
    },

    async uploadCompanyAccounts(options: { instanceId: string; dataId: string; xml: string }) {
      return uploadXml({ ...options, label: "Annual accounts company accounts" });
    },

    async validateInstance(options: { instanceId: string }): Promise<AnnualAccountsValidationSummary> {
      const result = await authorityRequest({
        fetch: fetchImplementation,
        url: `${instanceUrl(options.instanceId)}/validate`,
        method: "GET",
        token: altinnAccessToken,
        timeoutMs,
        headers: { accept: "application/json" },
      });
      const issues = validationIssues(result.data);
      return { hasErrors: issues.some((issue) => isErrorSeverity(issue.severity)), issues };
    },

    async lockForSigning(options: { instanceId: string }) {
      const result = await authorityRequest({
        fetch: fetchImplementation,
        url: `${instanceUrl(options.instanceId)}/process/next`,
        method: "PUT",
        token: altinnAccessToken,
        timeoutMs,
        headers: { accept: "application/json", "content-type": "application/json" },
        body: JSON.stringify({ action: "confirm" }),
      });
      const currentTask = safeObject(safeObject(result.data).currentTask);
      return {
        processTask: safeString(currentTask.altinnTaskType || currentTask.elementId, "unknown"),
        locked: true as const,
      };
    },

    async getSigningHandoff(options: { instanceId: string }) {
      const id = validInstanceId(options.instanceId);
      const result = await authorityRequest({
        fetch: fetchImplementation,
        url: instanceUrl(id),
        method: "GET",
        token: altinnAccessToken,
        timeoutMs,
        headers: { accept: "application/json" },
      });
      const returnedId = validInstanceId(safeString(safeObject(result.data).id));
      if (returnedId !== id) {
        throw new AnnualAccountsAuthorityError(
          "Altinn returned a different annual accounts instance id.",
          { code: "ANNUAL_ACCOUNTS_INSTANCE_MISMATCH" },
        );
      }
      return {
        instanceId: id,
        processTask: processTask(result.data),
        signingUrl: `${endpoints.altinnAppBase}/#/instance/${id}`,
        signed: false as const,
        submitted: false as const,
      };
    },

    // Altinn's official instance model exposes process.ended/endEvent and
    // status.archived. The official end-user-system guide identifies the
    // ref-data-as-pdf data element as the receipt for this filing flow.
    // https://docs.altinn.studio/en/api/models/instance/
    // https://docs.altinn.studio/nb/altinn-studio/v8/guides/integration/sbs/apis/#4-hente-kvittering
    async getSubmissionEvidence(options: { instanceId: string }) {
      const id = validInstanceId(options.instanceId);
      const result = await authorityRequest({
        fetch: fetchImplementation,
        url: instanceUrl(id),
        method: "GET",
        token: altinnAccessToken,
        timeoutMs,
        headers: { accept: "application/json" },
      });
      const instance = safeObject(result.data);
      const returnedId = validInstanceId(safeString(instance.id));
      if (returnedId !== id) {
        throw new AnnualAccountsAuthorityError(
          "Altinn returned a different annual accounts instance id.",
          { code: "ANNUAL_ACCOUNTS_INSTANCE_MISMATCH" },
        );
      }

      const process = safeObject(instance.process);
      const status = safeObject(instance.status);
      const processEndedAt = isoDateTime(process.ended);
      const endEvent = safeString(process.endEvent) || null;
      const processCompleted = process.currentTask === null
        && processEndedAt !== null
        && endEvent !== null;
      const archivedAt = isoDateTime(status.archived);
      const archived = status.isArchived === true && archivedAt !== null;

      const signatureElement = dataElement(result.data, "signature");
      const signed = signatureElement !== null
        && safeString(signatureElement.contentType) === "application/json";
      const signatureDataId = signed
        ? validDataId(safeString(signatureElement.id))
        : null;
      const receiptElement = dataElement(result.data, "ref-data-as-pdf");
      let receipt = null;
      if (receiptElement && safeString(receiptElement.contentType) === "application/pdf") {
        const dataId = validDataId(safeString(receiptElement.id));
        const sizeBytes = Number(receiptElement.size);
        if (Number.isInteger(sizeBytes) && sizeBytes > 0) {
          receipt = {
            dataId,
            dataType: "ref-data-as-pdf" as const,
            filename: safeString(receiptElement.filename, "annual-accounts-receipt.pdf"),
            contentType: "application/pdf" as const,
            sizeBytes,
            reference: `${endpoints.altinnPlatformBase}/storage/api/v1/instances/${id}/data/${dataId}`,
            downloadUrl: `${instanceUrl(id)}/data/${dataId}`,
          };
        }
      }

      return {
        instanceId: id,
        processCompleted,
        processEndedAt,
        endEvent,
        signed,
        signatureDataId,
        submitted: processCompleted && signed && archived && receipt !== null,
        archived,
        archivedAt,
        archiveReference: archived
          ? `${endpoints.altinnPlatformBase}/storage/api/v1/instances/${id}`
          : null,
        receipt,
      };
    },
  };
}

// System users may fill and lock RR0002, but an ID-porten person must sign.
// https://brreg.github.io/docs/apidokumentasjon/regnskapsregisteret/maskinell-innrapportering/hvordan-sende-inn/
export async function prepareAnnualAccountsForSigning(
  client: AnnualAccountsAuthorityClient,
  input: {
    companyOrgNumber: string;
    mainFormXml: string;
    companyAccountsXml: string;
  },
) {
  const instance = await client.createInstance({ companyOrgNumber: input.companyOrgNumber });
  await client.uploadMainForm({
    instanceId: instance.id,
    dataId: instance.dataIds.mainForm,
    xml: input.mainFormXml,
  });
  await client.uploadCompanyAccounts({
    instanceId: instance.id,
    dataId: instance.dataIds.companyAccounts,
    xml: input.companyAccountsXml,
  });
  const validation = await client.validateInstance({ instanceId: instance.id });
  if (validation.hasErrors) {
    throw new AnnualAccountsAuthorityError(
      "Annual accounts authority validation must pass before the instance can be locked.",
      {
        code: "ANNUAL_ACCOUNTS_VALIDATION_FAILED",
        validationCodes: [...new Set(
          validation.issues.filter((issue) => isErrorSeverity(issue.severity)).map((issue) => issue.code),
        )].sort(),
      },
    );
  }
  await client.lockForSigning({ instanceId: instance.id });
  const handoff = await client.getSigningHandoff({ instanceId: instance.id });
  return {
    ...handoff,
    dataIds: instance.dataIds,
    validation,
  };
}
