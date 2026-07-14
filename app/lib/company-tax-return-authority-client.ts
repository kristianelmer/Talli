export type CompanyTaxReturnAuthorityEnvironment = "test" | "production";

type FetchLike = (
  input: string | URL | globalThis.Request,
  init?: RequestInit,
) => Promise<Response>;

type AuthorityClientInput = {
  environment: CompanyTaxReturnAuthorityEnvironment;
  taxAccessToken: string;
  altinnAccessToken?: string;
  fetch?: FetchLike;
  timeoutMs?: number;
};

type ExchangeInput = {
  environment: CompanyTaxReturnAuthorityEnvironment;
  maskinportenAccessToken: string;
  fetch?: FetchLike;
  timeoutMs?: number;
};

type EnvironmentEndpoints = {
  taxApiBase: string;
  altinnPlatformBase: string;
  altinnAppBase: string;
};

type ParsedResponse = {
  response: Response;
  raw: string;
  json: Record<string, unknown>;
};

const ENDPOINTS: Record<CompanyTaxReturnAuthorityEnvironment, EnvironmentEndpoints> = {
  test: {
    taxApiBase: "https://api-test.sits.no",
    altinnPlatformBase: "https://platform.tt02.altinn.no",
    altinnAppBase: "https://skd.apps.tt02.altinn.no/skd/formueinntekt-skattemelding-v2",
  },
  production: {
    taxApiBase: "https://api.skatteetaten.no",
    altinnPlatformBase: "https://platform.altinn.no",
    altinnAppBase: "https://skd.apps.altinn.no/skd/formueinntekt-skattemelding-v2",
  },
};

const APP_ID = "skd/formueinntekt-skattemelding-v2";
const ENVELOPE_DATA_TYPE = "skattemeldingOgNaeringsspesifikasjon";
const INSTANCE_ID_PATTERN = /^\d+\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu;
const DATA_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu;
const JOB_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/u;

export class CompanyTaxReturnAuthorityError extends Error {
  readonly status: number | null;
  readonly code: string;
  readonly correlationId: string | null;
  readonly retryable: boolean;

  constructor(
    message: string,
    options: {
      status?: number | null;
      code?: string;
      correlationId?: string | null;
      retryable?: boolean;
      cause?: unknown;
    } = {},
  ) {
    super(message, options.cause === undefined ? undefined : { cause: options.cause });
    this.name = "CompanyTaxReturnAuthorityError";
    this.status = options.status ?? null;
    this.code = options.code ?? "COMPANY_TAX_AUTHORITY_ERROR";
    this.correlationId = options.correlationId ?? null;
    this.retryable = options.retryable ?? false;
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
    throw new Error("Company tax authority timeout must be between 1000 and 120000 milliseconds.");
  }
  return timeoutMs;
}

function validIncomeYear(value: number): number {
  if (!Number.isInteger(value) || value < 2000 || value > 2100) {
    throw new Error("Company tax income year must be an integer between 2000 and 2100.");
  }
  return value;
}

function validOrgNumber(value: string): string {
  if (!/^\d{9}$/u.test(value)) {
    throw new Error("Company tax organization number must contain 9 digits.");
  }
  return value;
}

function validInstanceId(value: string): string {
  if (!INSTANCE_ID_PATTERN.test(value)) {
    throw new Error("Company tax Altinn instance id must contain party id and instance UUID.");
  }
  return value;
}

function validDataId(value: string): string {
  if (!DATA_ID_PATTERN.test(value)) {
    throw new Error("Company tax Altinn data id must be a UUID.");
  }
  return value;
}

function validJobId(value: string): string {
  if (!JOB_ID_PATTERN.test(value)) {
    throw new Error("Company tax validation job id is invalid.");
  }
  return value;
}

function requiredXml(value: string, label: string): string {
  if (!value?.trim() || !value.trimStart().startsWith("<")) {
    throw new Error(`${label} XML is required.`);
  }
  return value;
}

function escapeXml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

function parseRemoteError(status: number, raw: string): CompanyTaxReturnAuthorityError {
  let parsed: unknown = {};
  try {
    parsed = raw ? JSON.parse(raw) : {};
  } catch {
    parsed = {};
  }
  const data = safeObject(parsed);
  const title = safeString(data.title || data.error || data.message, `Authority returned HTTP ${status}.`);
  const correlationId = safeString(data.traceId || data.trace_id || data.correlationId || data.korrelasjonsid) || null;
  return new CompanyTaxReturnAuthorityError(`Company tax authority request was rejected: ${title}`, {
    status,
    code: safeString(data.code || data.error, `COMPANY_TAX_HTTP_${status}`),
    correlationId,
    retryable: status === 401 || status === 408 || status === 425 || status === 429 || status >= 500,
  });
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
    throw new CompanyTaxReturnAuthorityError(
      "Company tax authority request failed before a response was received.",
      { code: "COMPANY_TAX_NETWORK_ERROR", retryable: true, cause },
    );
  }
  const raw = await response.text();
  if (!response.ok) throw parseRemoteError(response.status, raw);
  let json: Record<string, unknown> = {};
  try {
    json = safeObject(raw ? JSON.parse(raw) : {});
  } catch {
    json = {};
  }
  return { response, raw, json };
}

function documentReferenceFromCurrentXml(xml: string): string {
  const document = /<(?:(?:[A-Za-z_][\w.-]*):)?skattemeldingdokument\b[^>]*>([\s\S]*?)<\/(?:(?:[A-Za-z_][\w.-]*):)?skattemeldingdokument>/u.exec(xml)?.[1] ?? "";
  const reference = /<(?:(?:[A-Za-z_][\w.-]*):)?id\b[^>]*>([^<]+)<\/(?:(?:[A-Za-z_][\w.-]*):)?id>/u.exec(document)?.[1] ?? "";
  const normalized = reference.trim();
  if (!normalized || normalized.length > 4000) {
    throw new CompanyTaxReturnAuthorityError(
      "Current company tax return did not contain a usable document reference.",
      { code: "COMPANY_TAX_CURRENT_REFERENCE_MISSING" },
    );
  }
  return normalized;
}

type EnvelopeInput = {
  skattemeldingXml: string;
  naeringsspesifikasjonXml: string;
  companyOrgNumber: string;
  incomeYear: number;
  createdBy: string;
};

function renderEnvelope(input: EnvelopeInput & { currentDocumentReference?: string }): string {
  const skattemeldingXml = requiredXml(input.skattemeldingXml, "Company tax return");
  const naeringsspesifikasjonXml = requiredXml(input.naeringsspesifikasjonXml, "Company tax business specification");
  const currentDocumentReference = input.currentDocumentReference?.trim() ?? "";
  if (currentDocumentReference.length > 4000) {
    throw new Error("Current company tax document reference is too long.");
  }
  if (input.currentDocumentReference !== undefined && !currentDocumentReference) {
    throw new Error("Current company tax document reference is required.");
  }
  const createdBy = input.createdBy.trim();
  if (!createdBy || createdBy.length > 4000) {
    throw new Error("Company tax creator name is required.");
  }
  const companyOrgNumber = validOrgNumber(input.companyOrgNumber);
  const incomeYear = validIncomeYear(input.incomeYear);
  const taxBase64 = Buffer.from(skattemeldingXml, "utf8").toString("base64");
  const businessBase64 = Buffer.from(naeringsspesifikasjonXml, "utf8").toString("base64");

  const documentReferenceLines = currentDocumentReference
    ? [
      "  <dokumentreferanseTilGjeldendeDokument>",
      "    <dokumenttype>skattemeldingUpersonlig</dokumenttype>",
      `    <dokumentidentifikator>${escapeXml(currentDocumentReference)}</dokumentidentifikator>`,
      "  </dokumentreferanseTilGjeldendeDokument>",
    ]
    : [];

  return [
    "<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
    '<skattemeldingOgNaeringsspesifikasjonRequest xmlns="no:skatteetaten:fastsetting:formueinntekt:skattemeldingognaeringsspesifikasjon:request:v2">',
    "  <dokumenter>",
    "    <dokument>",
    "      <type>skattemeldingUpersonlig</type>",
    "      <encoding>utf-8</encoding>",
    `      <content>${taxBase64}</content>`,
    "    </dokument>",
    "    <dokument>",
    "      <type>naeringsspesifikasjon</type>",
    "      <encoding>utf-8</encoding>",
    `      <content>${businessBase64}</content>`,
    "    </dokument>",
    "  </dokumenter>",
    ...documentReferenceLines,
    `  <inntektsaar>${incomeYear}</inntektsaar>`,
    "  <innsendingsinformasjon>",
    "    <innsendingstype>komplett</innsendingstype>",
    `    <opprettetAv>${escapeXml(createdBy)}</opprettetAv>`,
    `    <tin>${companyOrgNumber}</tin>`,
    "    <innsendingsformaal>egenfastsetting</innsendingsformaal>",
    "  </innsendingsinformasjon>",
    "</skattemeldingOgNaeringsspesifikasjonRequest>",
    "",
  ].join("\n");
}

export function renderCompanyTaxReturnEnvelope(
  input: EnvelopeInput & { currentDocumentReference: string },
): string {
  return renderEnvelope(input);
}

export function renderCompanyTaxReturnValidationEnvelope(input: EnvelopeInput): string {
  return renderEnvelope(input);
}

export type CompanyTaxReturnValidationSummary = {
  result: "validertOK" | "validertMedFeil" | "unknown";
  deviationCodes: string[];
  guidanceCodes: string[];
  failureReasons: string[];
};

function xmlTextValues(xml: string, elementName: string): string[] {
  const qualifiedName = `(?:[A-Za-z_][\\w.-]*:)?${elementName}`;
  const pattern = new RegExp(`<${qualifiedName}\\b[^>]*>([^<]*)<\\/${qualifiedName}>`, "gu");
  return [...xml.matchAll(pattern)]
    .map((match) => safeString(match[1]))
    .filter(Boolean);
}

function uniqueSorted(values: string[]): string[] {
  return [...new Set(values)].sort((left, right) => left.localeCompare(right, "nb"));
}

export function summarizeCompanyTaxReturnValidation(
  resultXml: string,
): CompanyTaxReturnValidationSummary {
  const xml = requiredXml(resultXml, "Company tax validation result");
  const rawResult = xmlTextValues(xml, "resultatAvValidering")[0];
  const result = rawResult === "validertOK" || rawResult === "validertMedFeil"
    ? rawResult
    : "unknown";

  return {
    result,
    deviationCodes: uniqueSorted(xmlTextValues(xml, "avvikstype")),
    guidanceCodes: uniqueSorted(xmlTextValues(xml, "veiledningstype")),
    failureReasons: uniqueSorted(xmlTextValues(xml, "aarsakTilValidertMedFeil")),
  };
}

export async function exchangeMaskinportenForAltinnToken(input: ExchangeInput): Promise<string> {
  const endpoints = ENDPOINTS[input.environment];
  if (!endpoints) throw new Error("Company tax authority environment must be test or production.");
  const maskinportenAccessToken = opaqueToken(input.maskinportenAccessToken, "Maskinporten access token");
  const result = await authorityRequest({
    fetch: input.fetch ?? fetch,
    url: `${endpoints.altinnPlatformBase}/authentication/api/v1/exchange/maskinporten`,
    method: "GET",
    token: maskinportenAccessToken,
    timeoutMs: validTimeout(input.timeoutMs),
    headers: { accept: "text/plain" },
  });
  return opaqueToken(result.raw, "Altinn access token");
}

export type CompanyTaxReturnAuthorityClient = ReturnType<typeof createCompanyTaxReturnAuthorityClient>;

export function createCompanyTaxReturnAuthorityClient(input: AuthorityClientInput) {
  const endpoints = ENDPOINTS[input.environment];
  if (!endpoints) throw new Error("Company tax authority environment must be test or production.");
  if (input.environment === "production") {
    throw new Error("Company tax return production authority transport is disabled.");
  }
  const taxAccessToken = opaqueToken(input.taxAccessToken, "Company tax Maskinporten access token");
  const altinnAccessToken = input.altinnAccessToken === undefined
    ? null
    : opaqueToken(input.altinnAccessToken, "Company tax Altinn access token");
  const fetchImplementation = input.fetch ?? fetch;
  const timeoutMs = validTimeout(input.timeoutMs);

  function requireAltinnToken(): string {
    if (!altinnAccessToken) {
      throw new CompanyTaxReturnAuthorityError(
        "Altinn access token is required for company tax instance operations.",
        { code: "COMPANY_TAX_ALTINN_TOKEN_REQUIRED" },
      );
    }
    return altinnAccessToken;
  }

  function taxUrl(path: string): string {
    return `${endpoints.taxApiBase}/api/skattemelding/v2/${path}`;
  }

  return {
    environment: input.environment,

    async fetchCurrent(options: { incomeYear: number; companyOrgNumber: string }) {
      const year = validIncomeYear(options.incomeYear);
      const orgNumber = validOrgNumber(options.companyOrgNumber);
      const result = await authorityRequest({
        fetch: fetchImplementation,
        url: taxUrl(`${year}/${orgNumber}`),
        method: "GET",
        token: taxAccessToken,
        timeoutMs,
        headers: { accept: "application/xml" },
      });
      const rawXml = requiredXml(result.raw, "Current company tax return response");
      return { rawXml, documentReference: documentReferenceFromCurrentXml(rawXml) };
    },

    async validateTest(options: {
      incomeYear: number;
      companyOrgNumber: string;
      envelopeXml: string;
    }) {
      const year = validIncomeYear(options.incomeYear);
      const orgNumber = validOrgNumber(options.companyOrgNumber);
      const body = requiredXml(options.envelopeXml, "Company tax validation envelope");
      const result = await authorityRequest({
        fetch: fetchImplementation,
        url: taxUrl(`validertest/${year}/${orgNumber}`),
        method: "POST",
        token: taxAccessToken,
        timeoutMs,
        headers: { accept: "application/xml", "content-type": "application/xml" },
        body,
      });
      return { resultXml: requiredXml(result.raw, "Company tax validation result") };
    },

    async createInstance(options: { incomeYear: number; companyOrgNumber: string }) {
      const year = validIncomeYear(options.incomeYear);
      const orgNumber = validOrgNumber(options.companyOrgNumber);
      const body = JSON.stringify({
        instanceOwner: { organisationNumber: orgNumber },
        appId: APP_ID,
        dataValues: { inntektsaar: year },
      });
      const result = await authorityRequest({
        fetch: fetchImplementation,
        url: `${endpoints.altinnAppBase}/instances/`,
        method: "POST",
        token: requireAltinnToken(),
        timeoutMs,
        headers: { accept: "application/json", "content-type": "application/json" },
        body,
      });
      return { id: validInstanceId(safeString(result.json.id)) };
    },

    async uploadEnvelope(options: { instanceId: string; envelopeXml: string }) {
      const id = validInstanceId(options.instanceId);
      const body = requiredXml(options.envelopeXml, "Company tax envelope");
      const result = await authorityRequest({
        fetch: fetchImplementation,
        url: `${endpoints.altinnAppBase}/instances/${id}/data?dataType=${ENVELOPE_DATA_TYPE}`,
        method: "POST",
        token: requireAltinnToken(),
        timeoutMs,
        headers: {
          accept: "application/json",
          "content-type": "text/xml",
          "content-disposition": "attachment; filename=skattemeldingOgNaeringsspesifikasjon.xml",
        },
        body,
      });
      return {
        dataId: validDataId(safeString(result.json.id)),
        fileScanResult: safeString(result.json.fileScanResult, "Unknown"),
      };
    },

    async getEnvelopeScan(options: { instanceId: string }) {
      const id = validInstanceId(options.instanceId);
      const result = await authorityRequest({
        fetch: fetchImplementation,
        url: `${endpoints.altinnAppBase}/instances/${id}`,
        method: "GET",
        token: requireAltinnToken(),
        timeoutMs,
        headers: { accept: "application/json" },
      });
      const elements = Array.isArray(result.json.data) ? result.json.data.map(safeObject) : [];
      const envelope = elements.find((element) => safeString(element.dataType) === ENVELOPE_DATA_TYPE);
      if (!envelope) {
        throw new CompanyTaxReturnAuthorityError(
          "Altinn instance does not contain the company tax envelope.",
          { code: "COMPANY_TAX_ENVELOPE_MISSING", retryable: true },
        );
      }
      const fileScanResult = safeString(envelope.fileScanResult, "Unknown");
      if (!["Pending", "Clean"].includes(fileScanResult)) {
        throw new CompanyTaxReturnAuthorityError(
          "Altinn rejected the uploaded company tax envelope during file scanning.",
          { code: "COMPANY_TAX_ENVELOPE_SCAN_REJECTED" },
        );
      }
      return { dataId: safeString(envelope.id), fileScanResult };
    },

    async startValidation(options: {
      incomeYear: number;
      companyOrgNumber: string;
      instanceId: string;
    }) {
      const year = validIncomeYear(options.incomeYear);
      const orgNumber = validOrgNumber(options.companyOrgNumber);
      const id = validInstanceId(options.instanceId);
      const body = JSON.stringify({ appId: APP_ID, instansId: id });
      const result = await authorityRequest({
        fetch: fetchImplementation,
        url: taxUrl(`jobb/altinn/${year}/${orgNumber}/start`),
        method: "POST",
        token: taxAccessToken,
        timeoutMs,
        headers: { accept: "application/json", "content-type": "application/json" },
        body,
      });
      return {
        jobId: validJobId(safeString(result.json.jobbId)),
        status: safeString(result.json.jobbStatus),
      };
    },

    async getValidationStatus(options: {
      incomeYear: number;
      companyOrgNumber: string;
      jobId: string;
    }) {
      const year = validIncomeYear(options.incomeYear);
      const orgNumber = validOrgNumber(options.companyOrgNumber);
      const jobId = validJobId(options.jobId);
      const result = await authorityRequest({
        fetch: fetchImplementation,
        url: taxUrl(`jobb/altinn/${year}/${orgNumber}/${jobId}/status`),
        method: "GET",
        token: taxAccessToken,
        timeoutMs,
        headers: { accept: "application/json" },
      });
      return {
        status: safeString(result.json.jobbStatus),
        previousStatus: safeString(result.json.forrigeStatus) || null,
      };
    },

    async getValidationResult(options: {
      incomeYear: number;
      companyOrgNumber: string;
      jobId: string;
    }) {
      const year = validIncomeYear(options.incomeYear);
      const orgNumber = validOrgNumber(options.companyOrgNumber);
      const jobId = validJobId(options.jobId);
      const result = await authorityRequest({
        fetch: fetchImplementation,
        url: taxUrl(`jobb/altinn/${year}/${orgNumber}/${jobId}/resultat`),
        method: "GET",
        token: taxAccessToken,
        timeoutMs,
        headers: { accept: "application/xml" },
      });
      if (result.response.status === 204 || !result.raw.trim()) {
        throw new CompanyTaxReturnAuthorityError(
          "Company tax validation result is not ready.",
          { code: "COMPANY_TAX_VALIDATION_PENDING", retryable: true },
        );
      }
      return { resultXml: requiredXml(result.raw, "Company tax validation result") };
    },
  };
}

export async function waitForCompanyTaxReturnValidation(
  client: CompanyTaxReturnAuthorityClient,
  input: { incomeYear: number; companyOrgNumber: string; jobId: string },
  dependencies: { sleep?: (milliseconds: number) => Promise<void>; attempts?: number } = {},
) {
  const attempts = dependencies.attempts ?? 20;
  if (!Number.isInteger(attempts) || attempts < 1 || attempts > 120) {
    throw new Error("Company tax validation attempts must be between 1 and 120.");
  }
  const sleep = dependencies.sleep ?? (async (milliseconds: number) => {
    await new Promise((resolveDelay) => setTimeout(resolveDelay, milliseconds));
  });
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const status = await client.getValidationStatus(input);
    if (status.status === "FERDIG") {
      return client.getValidationResult(input);
    }
    if (["AVBRUTT", "FEILET"].includes(status.status)) {
      throw new CompanyTaxReturnAuthorityError(
        `Company tax validation ended with status ${status.status}.`,
        { code: `COMPANY_TAX_VALIDATION_${status.status}`, retryable: status.status === "FEILET" },
      );
    }
    if (!["NY", "OPPRETTET", "KJOERER", "VENTER"].includes(status.status)) {
      throw new CompanyTaxReturnAuthorityError(
        "Company tax validation returned an unknown status.",
        { code: "COMPANY_TAX_VALIDATION_STATUS_UNKNOWN" },
      );
    }
    if (attempt < attempts) await sleep(2_000);
  }
  throw new CompanyTaxReturnAuthorityError(
    "Company tax validation did not finish within the polling window.",
    { code: "COMPANY_TAX_VALIDATION_TIMEOUT", retryable: true },
  );
}
