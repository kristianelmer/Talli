import { createHash } from "node:crypto";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const DEFAULT_TIMEOUT_MS = 15_000;
const DEFAULT_MAX_RESPONSE_BYTES = 10 * 1024 * 1024;
const MAX_XML_BYTES = 10 * 1024 * 1024;

export const RF1086_AUTHORITY_BASE_URLS = {
  test: "https://api-test.sits.no/api/aksjonaerregister/v1",
  production: "https://api.skatteetaten.no/api/aksjonaerregister/v1",
} as const;

export type Rf1086AuthorityEnvironment = keyof typeof RF1086_AUTHORITY_BASE_URLS;
export type Rf1086AuthorityDocumentContentType = "application/json" | "application/xml" | "application/pdf" | "text/csv";

export type Rf1086AuthorityTransportRequest = {
  method: "GET" | "POST";
  url: string;
  headers: Readonly<Record<string, string>>;
  body?: string;
  timeoutMs: number;
  maxResponseBytes: number;
};

export type Rf1086AuthorityTransportResponse = {
  status: number;
  headers: Readonly<Record<string, string>>;
  body: Uint8Array;
};

export type Rf1086AuthorityTransport = (
  request: Rf1086AuthorityTransportRequest,
) => Promise<Rf1086AuthorityTransportResponse>;

export type Rf1086Leveransebekreftelse = {
  oppgavegiversLeveranseReferanse: string;
  dialogId: string;
  forsendelseId: string;
};

export type Rf1086DocumentPage = {
  totalItems: number;
  totalPages: number;
  currentPage: number;
  dokumenter: string[];
};

export class Rf1086AuthorityError extends Error {
  readonly code: string;
  readonly options: {
    retryable: boolean;
    status?: number;
    correlationId?: string;
  };

  constructor(
    code: string,
    message: string,
    options: {
      retryable: boolean;
      status?: number;
      correlationId?: string;
    },
  ) {
    super(message);
    this.name = "Rf1086AuthorityError";
    this.code = code;
    this.options = options;
  }

  get retryable() {
    return this.options.retryable;
  }

  get status() {
    return this.options.status;
  }

  get correlationId() {
    return this.options.correlationId;
  }
}

export type Rf1086AuthorityClient = {
  readonly environment: Rf1086AuthorityEnvironment;
  submitHovedskjema(input: {
    incomeYear: number;
    xml: string;
    idempotencyKey: string;
  }): Promise<{ hovedskjemaId: string }>;
  submitUnderskjema(input: {
    incomeYear: number;
    hovedskjemaId: string;
    xml: string;
    idempotencyKey: string;
  }): Promise<void>;
  confirmSubmission(input: {
    incomeYear: number;
    hovedskjemaId: string;
    underskjemaCount: number;
  }): Promise<Rf1086Leveransebekreftelse>;
  listDocuments(input: {
    incomeYear: number;
    forsendelseId: string;
    page?: number;
    size?: number;
  }): Promise<Rf1086DocumentPage>;
  getDocument(input: {
    incomeYear: number;
    forsendelseId: string;
    dokumentId: string;
    accept: Rf1086AuthorityDocumentContentType;
  }): Promise<{ contentType: Rf1086AuthorityDocumentContentType; body: Uint8Array }>;
};

type ClientOptions = {
  environment: Rf1086AuthorityEnvironment;
  accessToken: string;
  transport?: Rf1086AuthorityTransport;
  timeoutMs?: number;
  maxResponseBytes?: number;
};

function authorityError(code: string, message: string, retryable = false) {
  return new Rf1086AuthorityError(code, message, { retryable });
}

function assertEnvironment(value: unknown): asserts value is Rf1086AuthorityEnvironment {
  if (value !== "test" && value !== "production") {
    throw authorityError("rf1086_environment_invalid", "RF-1086 authority environment must be test or production.");
  }
}

function assertAccessToken(value: unknown): asserts value is string {
  if (typeof value !== "string" || value.length < 8 || value.length > 16_384 || /\s/u.test(value)) {
    throw authorityError("rf1086_access_token_invalid", "RF-1086 requires a short-lived system-user bearer token.");
  }
}

function assertBoundedInteger(value: unknown, minimum: number, maximum: number, code: string, label: string): number {
  if (!Number.isInteger(value) || (value as number) < minimum || (value as number) > maximum) {
    throw authorityError(code, `${label} is outside the supported range.`);
  }
  return value as number;
}

function assertIncomeYear(value: unknown): number {
  return assertBoundedInteger(value, 1000, 9999, "rf1086_income_year_invalid", "RF-1086 income year");
}

function assertUuid(value: unknown, label: string): string {
  if (typeof value !== "string" || !UUID_PATTERN.test(value)) {
    throw authorityError("rf1086_uuid_invalid", `${label} must be a UUID.`);
  }
  return value;
}

function assertXml(value: unknown): string {
  if (typeof value !== "string" || !value.trimStart().startsWith("<")) {
    throw authorityError("rf1086_xml_invalid", "RF-1086 XML must be a non-empty XML document.");
  }
  if (new TextEncoder().encode(value).byteLength > MAX_XML_BYTES) {
    throw authorityError("rf1086_xml_too_large", "RF-1086 XML exceeds the configured size limit.");
  }
  return value;
}

function headerValue(headers: Readonly<Record<string, string>>, name: string) {
  const match = Object.entries(headers).find(([key]) => key.toLowerCase() === name.toLowerCase());
  return match?.[1];
}

function normalizedContentType(headers: Readonly<Record<string, string>>) {
  return headerValue(headers, "content-type")?.split(";", 1)[0]?.trim().toLowerCase();
}

function assertResponseShape(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw authorityError("rf1086_response_invalid", "RF-1086 authority returned an invalid response.");
  }
  return value as Record<string, unknown>;
}

function decodeJson(response: Rf1086AuthorityTransportResponse): Record<string, unknown> {
  if (normalizedContentType(response.headers) !== "application/json") {
    throw authorityError("rf1086_response_content_type_invalid", "RF-1086 authority did not return JSON.");
  }
  try {
    const text = new TextDecoder("utf-8", { fatal: true }).decode(response.body);
    return assertResponseShape(JSON.parse(text));
  } catch (error) {
    if (error instanceof Rf1086AuthorityError) throw error;
    throw authorityError("rf1086_response_invalid", "RF-1086 authority returned invalid JSON.");
  }
}

function safeProviderField(value: unknown, pattern: RegExp, maximum: number) {
  return typeof value === "string" && value.length <= maximum && pattern.test(value) ? value : undefined;
}

function httpFailure(response: Rf1086AuthorityTransportResponse) {
  let provider: Record<string, unknown> = {};
  if (response.body.byteLength && normalizedContentType(response.headers) === "application/json") {
    try {
      provider = assertResponseShape(JSON.parse(new TextDecoder().decode(response.body)));
    } catch {
      provider = {};
    }
  }
  const code = safeProviderField(provider.kode, /^[A-Z0-9_-]+$/u, 64) ?? `rf1086_http_${response.status}`;
  const correlationId = safeProviderField(provider.korrelasjonsid, /^[\p{L}\p{N}._:-]+$/u, 200);
  const retryable = response.status === 401 || response.status === 408 || response.status === 425 || response.status === 429 || response.status >= 500;
  return new Rf1086AuthorityError(code, `RF-1086 authority request failed (${code}).`, {
    retryable,
    status: response.status,
    ...(correlationId ? { correlationId } : {}),
  });
}

function ensureResponse(response: unknown, maximum: number): Rf1086AuthorityTransportResponse {
  if (!response || typeof response !== "object") {
    throw authorityError("rf1086_transport_invalid", "RF-1086 transport returned no response.", true);
  }
  const candidate = response as Partial<Rf1086AuthorityTransportResponse>;
  if (!Number.isInteger(candidate.status) || !candidate.headers || !(candidate.body instanceof Uint8Array)) {
    throw authorityError("rf1086_transport_invalid", "RF-1086 transport returned an invalid response.", true);
  }
  if (candidate.body.byteLength > maximum) {
    throw authorityError("rf1086_response_too_large", "RF-1086 authority response exceeded the configured limit.", true);
  }
  return candidate as Rf1086AuthorityTransportResponse;
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
      throw authorityError("rf1086_response_too_large", "RF-1086 authority response exceeded the configured limit.", true);
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

export function createFetchRf1086AuthorityTransport(fetchImplementation: typeof fetch = fetch): Rf1086AuthorityTransport {
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
      if (error instanceof Rf1086AuthorityError) throw error;
      const timedOut = error instanceof DOMException && error.name === "AbortError";
      throw authorityError(
        timedOut ? "rf1086_transport_timeout" : "rf1086_transport_failed",
        timedOut ? "RF-1086 authority request timed out." : "RF-1086 authority request failed before a response was received.",
        true,
      );
    } finally {
      clearTimeout(timeout);
    }
  };
}

export function createRf1086AuthorityClient(options: ClientOptions): Rf1086AuthorityClient {
  assertEnvironment(options.environment);
  assertAccessToken(options.accessToken);
  const timeoutMs = assertBoundedInteger(
    options.timeoutMs ?? DEFAULT_TIMEOUT_MS,
    1_000,
    60_000,
    "rf1086_timeout_invalid",
    "RF-1086 timeout",
  );
  const maxResponseBytes = assertBoundedInteger(
    options.maxResponseBytes ?? DEFAULT_MAX_RESPONSE_BYTES,
    64,
    50 * 1024 * 1024,
    "rf1086_response_limit_invalid",
    "RF-1086 response limit",
  );
  const transport = options.transport ?? createFetchRf1086AuthorityTransport();
  const baseUrl = RF1086_AUTHORITY_BASE_URLS[options.environment];
  const authorization = `Bearer ${options.accessToken}`;
  const idempotencyFingerprints = new Map<string, string>();

  function assertIdempotencyUse(key: string, url: string, body: string) {
    const fingerprint = createHash("sha256").update(url).update("\0").update(body).digest("hex");
    const existing = idempotencyFingerprints.get(key);
    if (existing && existing !== fingerprint) {
      throw authorityError(
        "rf1086_idempotency_key_reused",
        "RF-1086 idempotency key cannot be reused for a different request.",
      );
    }
    idempotencyFingerprints.set(key, fingerprint);
  }

  async function request(input: Omit<Rf1086AuthorityTransportRequest, "timeoutMs" | "maxResponseBytes">) {
    let transported: unknown;
    try {
      transported = await transport({ ...input, timeoutMs, maxResponseBytes });
    } catch (error) {
      if (error instanceof Rf1086AuthorityError) throw error;
      throw authorityError("rf1086_transport_failed", "RF-1086 authority request failed before a response was received.", true);
    }
    const response = ensureResponse(transported, maxResponseBytes);
    if (response.status !== 200) throw httpFailure(response);
    return response;
  }

  const jsonHeaders = (accept: string = "application/json") => ({ Authorization: authorization, Accept: accept });
  const xmlHeaders = (idempotencyKey: string) => ({
    ...jsonHeaders(),
    "Content-Type": "application/xml",
    idempotencyKey,
  });

  return {
    environment: options.environment,
    async submitHovedskjema(input) {
      const incomeYear = assertIncomeYear(input.incomeYear);
      const xml = assertXml(input.xml);
      const key = assertUuid(input.idempotencyKey, "RF-1086 idempotency key");
      const url = `${baseUrl}/${incomeYear}/1086H`;
      assertIdempotencyUse(key, url, xml);
      const response = await request({
        method: "POST",
        url,
        headers: xmlHeaders(key),
        body: xml,
      });
      const body = decodeJson(response);
      try {
        return { hovedskjemaId: assertUuid(body.hovedskjemaId, "RF-1086 hovedskjema ID") };
      } catch {
        throw authorityError("rf1086_response_invalid", "RF-1086 authority returned an invalid hovedskjema response.");
      }
    },

    async submitUnderskjema(input) {
      const incomeYear = assertIncomeYear(input.incomeYear);
      const hovedskjemaId = assertUuid(input.hovedskjemaId, "RF-1086 hovedskjema ID");
      const xml = assertXml(input.xml);
      const key = assertUuid(input.idempotencyKey, "RF-1086 idempotency key");
      const url = `${baseUrl}/${incomeYear}/${hovedskjemaId}/1086U`;
      assertIdempotencyUse(key, url, xml);
      await request({
        method: "POST",
        url,
        headers: xmlHeaders(key),
        body: xml,
      });
    },

    async confirmSubmission(input) {
      const incomeYear = assertIncomeYear(input.incomeYear);
      const hovedskjemaId = assertUuid(input.hovedskjemaId, "RF-1086 hovedskjema ID");
      const underskjemaCount = assertBoundedInteger(
        input.underskjemaCount,
        1,
        100_000,
        "rf1086_underskjema_count_invalid",
        "RF-1086 underskjema count",
      );
      const response = await request({
        method: "POST",
        url: `${baseUrl}/${incomeYear}/${hovedskjemaId}/bekreft?antall_underskjema=${underskjemaCount}`,
        headers: jsonHeaders(),
      });
      const body = decodeJson(response);
      const reference = typeof body.oppgavegiversLeveranseReferanse === "string" ? body.oppgavegiversLeveranseReferanse : "";
      if (!reference || reference.length > 100) {
        throw authorityError("rf1086_response_invalid", "RF-1086 authority returned an invalid confirmation response.");
      }
      try {
        return {
          oppgavegiversLeveranseReferanse: reference,
          dialogId: assertUuid(body.dialogId, "RF-1086 dialog ID"),
          forsendelseId: assertUuid(body.forsendelseId, "RF-1086 forsendelse ID"),
        };
      } catch {
        throw authorityError("rf1086_response_invalid", "RF-1086 authority returned an invalid confirmation response.");
      }
    },

    async listDocuments(input) {
      const incomeYear = assertIncomeYear(input.incomeYear);
      const forsendelseId = assertUuid(input.forsendelseId, "RF-1086 forsendelse ID");
      const page = assertBoundedInteger(input.page ?? 0, 0, 1_000_000, "rf1086_page_invalid", "RF-1086 page");
      const size = assertBoundedInteger(input.size ?? 10, 1, 50, "rf1086_page_size_invalid", "RF-1086 page size");
      const response = await request({
        method: "GET",
        url: `${baseUrl}/${incomeYear}/forsendelser/${forsendelseId}/dokumenter?page=${page}&size=${size}`,
        headers: jsonHeaders(),
      });
      const body = decodeJson(response);
      const isNonnegativeSafeInteger = (value: unknown) => Number.isSafeInteger(value) && (value as number) >= 0;
      if (
        !isNonnegativeSafeInteger(body.totalItems) ||
        !isNonnegativeSafeInteger(body.totalPages) ||
        !isNonnegativeSafeInteger(body.currentPage) ||
        ((body.totalPages as number) > 0 && (body.currentPage as number) >= (body.totalPages as number)) ||
        !Array.isArray(body.dokumenter) ||
        body.dokumenter.length > 50 ||
        !body.dokumenter.every((document) => typeof document === "string")
      ) {
        throw authorityError("rf1086_response_invalid", "RF-1086 authority returned an invalid document page.");
      }
      return {
        totalItems: body.totalItems as number,
        totalPages: body.totalPages as number,
        currentPage: body.currentPage as number,
        dokumenter: body.dokumenter as string[],
      };
    },

    async getDocument(input) {
      const incomeYear = assertIncomeYear(input.incomeYear);
      const forsendelseId = assertUuid(input.forsendelseId, "RF-1086 forsendelse ID");
      const dokumentId = assertUuid(input.dokumentId, "RF-1086 document ID");
      const allowedTypes: readonly Rf1086AuthorityDocumentContentType[] = [
        "application/json",
        "application/xml",
        "application/pdf",
        "text/csv",
      ];
      if (!allowedTypes.includes(input.accept)) {
        throw authorityError("rf1086_document_type_invalid", "RF-1086 document content type is not supported.");
      }
      const response = await request({
        method: "GET",
        url: `${baseUrl}/${incomeYear}/forsendelser/${forsendelseId}/dokumenter/${dokumentId}`,
        headers: jsonHeaders(input.accept),
      });
      const contentType = normalizedContentType(response.headers);
      if (contentType !== input.accept) {
        throw authorityError("rf1086_response_content_type_invalid", "RF-1086 authority returned an unexpected document type.");
      }
      return { contentType: input.accept, body: response.body };
    },
  };
}
