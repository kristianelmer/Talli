import { createHash } from "node:crypto";

export type Rf1086AuthorityEnvironment = "test" | "production";
export type Rf1086AuthorityCallStatus = "accepted";

export type Rf1086AuthorityCallEvidence = {
  method: "GET" | "POST";
  endpoint: string;
  bodyHash: string;
  idempotencyKey: string | null;
  status: Rf1086AuthorityCallStatus;
};

export type Rf1086IdempotencyKeys = {
  hovedskjema: string;
  underskjema: Record<string, string>;
  bekreft: string;
};

export type Rf1086AuthoritySubmissionInput = {
  incomeYear: number;
  hovedskjemaXml: string;
  underskjemaXml: Record<string, string>;
  idempotencyKeys: Rf1086IdempotencyKeys;
};

export type Rf1086AuthoritySubmissionResult = {
  hovedskjemaId: string;
  oppgavegiversLeveranseReferanse: string;
  dialogId: string;
  forsendelseId: string;
  documents: {
    lookupReferenceType: "forsendelseId" | "dialogId";
    totalItems: number;
    totalPages: number;
    currentPage: number;
    documents: Rf1086ArchiveDocument[];
  };
  calls: Rf1086AuthorityCallEvidence[];
};

export type Rf1086ArchiveDocumentReference = {
  reference: string;
};

export type Rf1086ArchiveDocument = string | Rf1086ArchiveDocumentReference;

export type Rf1086AuthorityDocument = {
  reference: string;
  contentType: string;
  bytes: Uint8Array;
};

type FetchLike = (
  input: string | URL | globalThis.Request,
  init?: RequestInit,
) => Promise<Response>;

type AuthorityClientInput = {
  environment: Rf1086AuthorityEnvironment;
  accessToken: string;
  fetch?: FetchLike;
  timeoutMs?: number;
};

type RequestResult = {
  data: Record<string, unknown>;
  call: Rf1086AuthorityCallEvidence;
};

const BASE_URLS: Record<Rf1086AuthorityEnvironment, string> = {
  test: "https://api-test.sits.no/api/aksjonaerregister/v1",
  production: "https://api.skatteetaten.no/api/aksjonaerregister/v1",
};

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu;
const MAX_JSON_RESPONSE_BYTES = 64 * 1024;
const MAX_DOCUMENT_BYTES = 10 * 1024 * 1024;
const DOCUMENT_CONTENT_TYPES = new Set([
  "application/xml",
  "text/xml",
  "application/pdf",
  "text/plain",
  "application/octet-stream",
]);

export class Rf1086AuthorityError extends Error {
  readonly status: number | null;
  readonly code: string;
  readonly correlationId: string | null;
  readonly specificationCodes: string[];
  readonly retryable: boolean;

  constructor(
    message: string,
    options: {
      status?: number | null;
      code?: string;
      correlationId?: string | null;
      specificationCodes?: string[];
      retryable?: boolean;
      cause?: unknown;
    } = {},
  ) {
    super(message, options.cause === undefined ? undefined : { cause: options.cause });
    this.name = "Rf1086AuthorityError";
    this.status = options.status ?? null;
    this.code = options.code ?? "RF1086_AUTHORITY_ERROR";
    this.correlationId = options.correlationId ?? null;
    this.specificationCodes = options.specificationCodes ?? [];
    this.retryable = options.retryable ?? false;
  }
}

function requiredOpaqueToken(value: string): string {
  if (!value || value !== value.trim() || /\s/u.test(value)) {
    throw new Error("RF-1086 authority access token is required and must be opaque.");
  }
  return value;
}

function incomeYear(value: number): number {
  if (!Number.isInteger(value) || value < 2000 || value > 2100) {
    throw new Error("RF-1086 income year must be an integer between 2000 and 2100.");
  }
  return value;
}

function requiredXml(value: string): string {
  if (!value?.trim() || !value.trimStart().startsWith("<")) {
    throw new Error("RF-1086 XML document is required.");
  }
  return value;
}

function requiredUuid(value: string, label: string): string {
  if (!UUID_PATTERN.test(value)) {
    throw new Error(`${label} must be a UUID.`);
  }
  return value;
}

function safeString(value: unknown, fallback = ""): string {
  if (typeof value !== "string") return fallback;
  return value.replace(/[\u0000-\u001f\u007f]/gu, " ").replace(/\s+/gu, " ").trim().slice(0, 500);
}

function safeObject(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function bodyHash(body: string | undefined): string {
  return createHash("sha256").update(body ?? "", "utf8").digest("hex");
}

function retryableFailure(status: number, code: string): boolean {
  return status === 401 || status === 408 || status === 425 || status === 429 || status >= 500 || code === "GLD_004";
}

function parseAuthorityError(status: number, parsed: unknown): Rf1086AuthorityError {
  const data = safeObject(parsed);
  const code = safeString(data.kode, `RF1086_HTTP_${status}`);
  const summary = safeString(data.melding, `Skatteetaten returned HTTP ${status}.`);
  const specificationObjects = Array.isArray(data.spesifisering)
    ? data.spesifisering
      .slice(0, 5)
      .map((value) => safeObject(value))
    : [];
  const specifications = specificationObjects
      .map((value) => [safeString(value.kode), safeString(value.melding), safeString(value.sti)].filter(Boolean).join(" — "))
      .filter(Boolean);
  const detail = specifications.length ? ` Details: ${specifications.join("; ")}` : "";
  return new Rf1086AuthorityError(`RF-1086 authority request was rejected: ${summary}${detail}`, {
    status,
    code,
    correlationId: safeString(data.korrelasjonsid) || null,
    specificationCodes: specificationObjects.map((value) => safeString(value.kode)).filter(Boolean),
    retryable: retryableFailure(status, code),
  });
}

async function boundedResponseBytes(
  response: Response,
  options: {
    maximumBytes: number;
    code: string;
    message: string;
  },
) {
  const statedLength = Number(response.headers.get("content-length"));
  if (Number.isFinite(statedLength) && statedLength > options.maximumBytes) {
    throw new Rf1086AuthorityError(options.message, {
      status: response.status,
      code: options.code,
      retryable: false,
    });
  }
  if (!response.body) return new Uint8Array();

  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let byteLength = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      byteLength += value.byteLength;
      if (byteLength > options.maximumBytes) {
        await reader.cancel();
        throw new Rf1086AuthorityError(options.message, {
          status: response.status,
          code: options.code,
          retryable: false,
        });
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(byteLength);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes;
}

function responseContentType(response: Response) {
  return response.headers.get("content-type")?.split(";", 1)[0]?.trim().toLowerCase() ?? "";
}

function isJsonContentType(contentType: string) {
  return contentType === "application/json"
    || (contentType.startsWith("application/") && contentType.endsWith("+json"));
}

async function parseAuthorityJson(response: Response): Promise<unknown> {
  const contentType = responseContentType(response);
  if (contentType && !isJsonContentType(contentType)) {
    throw new Rf1086AuthorityError("RF-1086 authority response has a disallowed JSON content type.", {
      status: response.status,
      code: "RF1086_JSON_CONTENT_TYPE",
      retryable: false,
    });
  }
  const bytes = await boundedResponseBytes(response, {
    maximumBytes: MAX_JSON_RESPONSE_BYTES,
    code: "RF1086_JSON_TOO_LARGE",
    message: "RF-1086 authority JSON response exceeds the permitted response size.",
  });
  if (bytes.byteLength === 0) return {};
  if (!contentType) {
    throw new Rf1086AuthorityError("RF-1086 authority response has a disallowed JSON content type.", {
      status: response.status,
      code: "RF1086_JSON_CONTENT_TYPE",
      retryable: false,
    });
  }
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    if (!response.ok) return {};
    throw new Rf1086AuthorityError("RF-1086 authority response contained invalid JSON.", {
      status: response.status,
      code: "RF1086_JSON_INVALID",
      retryable: false,
    });
  }
}

function strictDocumentReference(value: unknown): Rf1086ArchiveDocumentReference | null {
  const object = safeObject(value);
  const keys = Object.keys(object);
  if (keys.length !== 1 || !["dokumentId", "documentId"].includes(keys[0])) return null;
  const reference = object[keys[0]];
  return typeof reference === "string" && UUID_PATTERN.test(reference)
    ? { reference }
    : null;
}

export type Rf1086AuthorityClient = ReturnType<typeof createRf1086AuthorityClient>;

export function createRf1086AuthorityClient(input: AuthorityClientInput) {
  const baseUrl = BASE_URLS[input.environment];
  if (!baseUrl) throw new Error("RF-1086 authority environment must be test or production.");
  const accessToken = requiredOpaqueToken(input.accessToken);
  const fetchImplementation = input.fetch ?? fetch;
  const timeoutMs = input.timeoutMs ?? 20_000;
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1_000 || timeoutMs > 120_000) {
    throw new Error("RF-1086 authority timeout must be between 1000 and 120000 milliseconds.");
  }

  async function request(options: {
    method: "GET" | "POST";
    endpoint: string;
    body?: string;
    idempotencyKey?: string;
    xml?: boolean;
  }): Promise<RequestResult> {
    const headers: Record<string, string> = {
      accept: "application/json",
      authorization: `Bearer ${accessToken}`,
    };
    if (options.xml) headers["content-type"] = "application/xml";
    if (options.idempotencyKey) {
      headers.idempotencyKey = requiredUuid(options.idempotencyKey, "RF-1086 idempotency key");
    }
    let response: Response;
    try {
      response = await fetchImplementation(options.endpoint, {
        method: options.method,
        headers,
        body: options.body,
        redirect: "error",
        signal: AbortSignal.timeout(timeoutMs),
      });
    } catch (cause) {
      throw new Rf1086AuthorityError("RF-1086 authority request failed before a response was received.", {
        code: "RF1086_NETWORK_ERROR",
        retryable: true,
        cause,
      });
    }

    const parsed = await parseAuthorityJson(response);
    if (!response.ok) throw parseAuthorityError(response.status, parsed);

    return {
      data: safeObject(parsed),
      call: {
        method: options.method,
        endpoint: options.endpoint,
        bodyHash: bodyHash(options.body),
        idempotencyKey: options.idempotencyKey ?? null,
        status: "accepted",
      },
    };
  }

  return {
    environment: input.environment,

    async postHovedskjema(options: { incomeYear: number; xml: string; idempotencyKey: string }) {
      const year = incomeYear(options.incomeYear);
      const result = await request({
        method: "POST",
        endpoint: `${baseUrl}/${year}/1086H`,
        body: requiredXml(options.xml),
        idempotencyKey: options.idempotencyKey,
        xml: true,
      });
      const hovedskjemaId = safeString(result.data.hovedskjemaId || result.data.hovedskjemaid);
      return {
        hovedskjemaId: requiredUuid(hovedskjemaId, "RF-1086 hovedskjema id"),
        call: result.call,
      };
    },

    async postUnderskjema(options: {
      incomeYear: number;
      hovedskjemaId: string;
      xml: string;
      idempotencyKey: string;
    }) {
      const year = incomeYear(options.incomeYear);
      const hovedskjemaId = requiredUuid(options.hovedskjemaId, "RF-1086 hovedskjema id");
      const result = await request({
        method: "POST",
        endpoint: `${baseUrl}/${year}/${hovedskjemaId}/1086U`,
        body: requiredXml(options.xml),
        idempotencyKey: options.idempotencyKey,
        xml: true,
      });
      return { call: result.call };
    },

    async confirm(options: {
      incomeYear: number;
      hovedskjemaId: string;
      underskjemaCount: number;
      idempotencyKey: string;
    }) {
      const year = incomeYear(options.incomeYear);
      const hovedskjemaId = requiredUuid(options.hovedskjemaId, "RF-1086 hovedskjema id");
      if (!Number.isInteger(options.underskjemaCount) || options.underskjemaCount < 1) {
        throw new Error("RF-1086 confirmation requires at least one underskjema.");
      }
      const result = await request({
        method: "POST",
        endpoint: `${baseUrl}/${year}/${hovedskjemaId}/bekreft?antall_underskjema=${options.underskjemaCount}`,
        idempotencyKey: options.idempotencyKey,
      });
      return {
        oppgavegiversLeveranseReferanse: safeString(result.data.oppgavegiversLeveranseReferanse),
        dialogId: requiredUuid(safeString(result.data.dialogId), "RF-1086 dialog id"),
        forsendelseId: requiredUuid(safeString(result.data.forsendelseId), "RF-1086 forsendelse id"),
        call: result.call,
      };
    },

    async listDocuments(options: {
      incomeYear: number;
      referenceId: string;
      page?: number;
      size?: number;
    }) {
      const year = incomeYear(options.incomeYear);
      const referenceId = requiredUuid(options.referenceId, "RF-1086 archive lookup reference");
      const page = options.page ?? 0;
      const size = options.size ?? 50;
      if (!Number.isInteger(page) || page < 0) throw new Error("RF-1086 document page must be zero or greater.");
      if (!Number.isInteger(size) || size < 1 || size > 50) throw new Error("RF-1086 document page size must be 1-50.");
      const result = await request({
        method: "GET",
        endpoint: `${baseUrl}/${year}/forsendelser/${referenceId}/dokumenter?page=${page}&size=${size}`,
      });
      const rawDocuments = result.data.dokumenter;
      const documents: Rf1086ArchiveDocument[] = [];
      let documentShapeValid = Array.isArray(rawDocuments);
      if (Array.isArray(rawDocuments)) {
        for (const value of rawDocuments) {
          if (typeof value === "string" && value.trim()) {
            documents.push(value);
            continue;
          }
          const reference = strictDocumentReference(value);
          if (reference) {
            documents.push(reference);
            continue;
          }
          documentShapeValid = false;
        }
      }
      const totalItems = Number(result.data.totalItems ?? documents.length);
      const totalPages = Number(result.data.totalPages ?? (documents.length ? 1 : 0));
      const currentPage = Number(result.data.currentPage ?? page);
      documentShapeValid = documentShapeValid
        && Number.isInteger(totalItems) && totalItems >= documents.length
        && Number.isInteger(totalPages) && totalPages >= 0
        && Number.isInteger(currentPage) && currentPage >= 0;
      return {
        totalItems,
        totalPages,
        currentPage,
        documents,
        documentShapeValid,
        call: result.call,
      };
    },

    async getDocument(options: {
      incomeYear: number;
      forsendelseId: string;
      documentId: string;
    }): Promise<Rf1086AuthorityDocument> {
      const year = incomeYear(options.incomeYear);
      const forsendelseId = requiredUuid(options.forsendelseId, "RF-1086 forsendelse id");
      const documentId = requiredUuid(options.documentId, "RF-1086 document id");
      let response: Response;
      try {
        response = await fetchImplementation(
          `${baseUrl}/${encodeURIComponent(String(year))}/forsendelser/${encodeURIComponent(forsendelseId)}/dokumenter/${encodeURIComponent(documentId)}`,
          {
            method: "GET",
            headers: {
              accept: [...DOCUMENT_CONTENT_TYPES].join(", "),
              authorization: `Bearer ${accessToken}`,
            },
            redirect: "error",
            signal: AbortSignal.timeout(timeoutMs),
          },
        );
      } catch (cause) {
        throw new Rf1086AuthorityError("RF-1086 authority request failed before a response was received.", {
          code: "RF1086_NETWORK_ERROR",
          retryable: true,
          cause,
        });
      }

      if (!response.ok) {
        const parsed = await parseAuthorityJson(response);
        throw parseAuthorityError(response.status, parsed);
      }
      const bytes = await boundedResponseBytes(response, {
        maximumBytes: MAX_DOCUMENT_BYTES,
        code: "RF1086_DOCUMENT_TOO_LARGE",
        message: "RF-1086 authority document exceeds the permitted response size.",
      });
      const contentType = responseContentType(response);
      if (!DOCUMENT_CONTENT_TYPES.has(contentType)) {
        throw new Rf1086AuthorityError("RF-1086 authority document has a disallowed content type.", {
          status: response.status,
          code: "RF1086_DOCUMENT_CONTENT_TYPE",
          retryable: false,
        });
      }
      if (bytes.byteLength < 1) {
        throw new Rf1086AuthorityError("RF-1086 authority document was empty.", {
          status: response.status,
          code: "RF1086_DOCUMENT_EMPTY",
          retryable: false,
        });
      }
      return { reference: documentId, contentType, bytes };
    },
  };
}

export async function executeRf1086AuthoritySubmission(
  client: Rf1086AuthorityClient,
  input: Rf1086AuthoritySubmissionInput,
  dependencies: {
    sleep?: (milliseconds: number) => Promise<void>;
    archiveAttempts?: number;
  } = {},
): Promise<Rf1086AuthoritySubmissionResult> {
  const entries = Object.entries(input.underskjemaXml).sort(([left], [right]) => left.localeCompare(right));
  if (!entries.length) throw new Error("RF-1086 submission requires at least one underskjema.");
  if (Object.keys(input.idempotencyKeys.underskjema).length !== entries.length) {
    throw new Error("RF-1086 idempotency keys must match every underskjema exactly.");
  }

  const main = await client.postHovedskjema({
    incomeYear: input.incomeYear,
    xml: input.hovedskjemaXml,
    idempotencyKey: input.idempotencyKeys.hovedskjema,
  });
  const calls: Rf1086AuthorityCallEvidence[] = [main.call];

  for (const [shareholderId, xml] of entries) {
    const idempotencyKey = input.idempotencyKeys.underskjema[shareholderId];
    if (!idempotencyKey) throw new Error(`RF-1086 idempotency key is missing for underskjema ${shareholderId}.`);
    const subdocument = await client.postUnderskjema({
      incomeYear: input.incomeYear,
      hovedskjemaId: main.hovedskjemaId,
      xml,
      idempotencyKey,
    });
    calls.push(subdocument.call);
  }

  const confirmation = await client.confirm({
    incomeYear: input.incomeYear,
    hovedskjemaId: main.hovedskjemaId,
    underskjemaCount: entries.length,
    idempotencyKey: input.idempotencyKeys.bekreft,
  });
  calls.push(confirmation.call);

  const sleep = dependencies.sleep ?? (async (milliseconds: number) => {
    await new Promise((resolveDelay) => setTimeout(resolveDelay, milliseconds));
  });
  const archiveAttempts = dependencies.archiveAttempts ?? 5;
  if (!Number.isInteger(archiveAttempts) || archiveAttempts < 1 || archiveAttempts > 20) {
    throw new Error("RF-1086 archive attempts must be between 1 and 20.");
  }
  const lookupReferenceType = "forsendelseId" as const;
  let documentPage;
  for (let attempt = 1; attempt <= archiveAttempts; attempt += 1) {
    try {
      documentPage = await client.listDocuments({
        incomeYear: input.incomeYear,
        referenceId: confirmation.forsendelseId,
        page: 0,
        size: 50,
      });
      if (documentPage.totalItems > 0 && documentPage.documents.length > 0) break;
    } catch (error) {
      const observedEventualConsistency = error instanceof Rf1086AuthorityError
        && error.status === 404
        && error.code === "GLD_021"
        && error.specificationCodes.includes("GLD_1017");
      if (!observedEventualConsistency || attempt === archiveAttempts) throw error;
    }
    if (attempt < archiveAttempts) await sleep(2_000);
  }
  if (!documentPage || documentPage.totalItems < 1 || documentPage.documents.length < 1) {
    throw new Rf1086AuthorityError("RF-1086 archive returned no documents after confirmation.", {
      code: "RF1086_ARCHIVE_PENDING",
      retryable: true,
    });
  }
  calls.push(documentPage.call);

  return {
    hovedskjemaId: main.hovedskjemaId,
    oppgavegiversLeveranseReferanse: confirmation.oppgavegiversLeveranseReferanse,
    dialogId: confirmation.dialogId,
    forsendelseId: confirmation.forsendelseId,
    documents: {
      lookupReferenceType,
      totalItems: documentPage.totalItems,
      totalPages: documentPage.totalPages,
      currentPage: documentPage.currentPage,
      documents: documentPage.documents,
    },
    calls,
  };
}
