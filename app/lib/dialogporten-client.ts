const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const ORG_NUMBER_PATTERN = /^\d{9}$/u;
const DEFAULT_TIMEOUT_MS = 15_000;
const DEFAULT_MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
const MAX_TRANSMISSIONS = 10_000;
const MAX_ATTACHMENTS = 10_000;
const MAX_URLS = 20;

export const DIALOGPORTEN_BASE_URLS = {
  test: "https://platform.tt02.altinn.no/dialogporten/api/v1/enduser",
  production: "https://platform.altinn.no/dialogporten/api/v1/enduser",
} as const;

export const DIALOGPORTEN_MASKINPORTEN_SCOPE = "digdir:dialogporten";

export type DialogportenEnvironment = keyof typeof DIALOGPORTEN_BASE_URLS;
export type DialogportenTransmissionType =
  | "Information"
  | "Acceptance"
  | "Rejection"
  | "Request"
  | "Alert"
  | "Decision"
  | "Submission"
  | "Correction";
export type DialogportenStatus = "InProgress" | "Draft" | "RequiresAttention" | "Completed" | "NotApplicable" | "Awaiting";

export type DialogportenAttachmentUrl = {
  id: string;
  url: string;
  mediaType: string | null;
  consumerType: "Gui" | "Api";
};

export type DialogportenAttachment = {
  id: string;
  name: string | null;
  expiresAt: string | null;
  urls: DialogportenAttachmentUrl[];
};

export type DialogportenTransmission = {
  id: string;
  createdAt: string;
  isAuthorized: boolean;
  type: DialogportenTransmissionType;
  attachments: DialogportenAttachment[];
};

export type DialogportenDialog = {
  id: string;
  revision: string;
  org: string;
  serviceResource: string;
  party: string;
  status: DialogportenStatus;
  createdAt: string;
  updatedAt: string;
  transmissions: DialogportenTransmission[];
};

export type DialogportenTransportRequest = {
  method: "GET";
  url: string;
  headers: Readonly<Record<string, string>>;
  timeoutMs: number;
  maxResponseBytes: number;
};

export type DialogportenTransportResponse = {
  status: number;
  headers: Readonly<Record<string, string>>;
  body: Uint8Array;
};

export type DialogportenTransport = (request: DialogportenTransportRequest) => Promise<DialogportenTransportResponse>;

export type DialogportenClient = {
  readonly environment: DialogportenEnvironment;
  getDialog(input: {
    dialogId: string;
    expectedPartyOrgNumber: string;
    expectedServiceResource: string;
  }): Promise<DialogportenDialog>;
};

export class DialogportenClientError extends Error {
  readonly code: string;
  readonly retryable: boolean;
  readonly status?: number;

  constructor(code: string, message: string, options: { retryable: boolean; status?: number }) {
    super(message);
    this.name = "DialogportenClientError";
    this.code = code;
    this.retryable = options.retryable;
    this.status = options.status;
  }
}

function clientError(code: string, message: string, retryable = false, status?: number) {
  return new DialogportenClientError(code, message, { retryable, ...(status === undefined ? {} : { status }) });
}

function assertUuid(value: unknown, label: string) {
  if (typeof value !== "string" || !UUID_PATTERN.test(value)) {
    throw clientError("dialogporten_input_invalid", `${label} must be a UUID.`);
  }
  return value;
}

function assertBoundedString(value: unknown, maximum: number): string {
  if (typeof value !== "string" || value.length < 1 || value.length > maximum) throw new Error("invalid");
  return value;
}

function assertOptionalBoundedString(value: unknown, maximum: number): string | null {
  if (value === null || value === undefined) return null;
  return assertBoundedString(value, maximum);
}

function assertTimestamp(value: unknown) {
  const timestamp = assertBoundedString(value, 64);
  if (!Number.isFinite(Date.parse(timestamp))) throw new Error("invalid");
  return timestamp;
}

function assertRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("invalid");
  return value as Record<string, unknown>;
}

function parseAttachmentUrl(value: unknown): DialogportenAttachmentUrl {
  const item = assertRecord(value);
  const id = assertUuid(item.id, "Dialogporten attachment URL ID");
  const url = assertBoundedString(item.url, 4_096);
  if (url !== "urn:dialogporten:unauthorized") {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:" || parsed.username || parsed.password || parsed.hash) throw new Error("invalid");
  }
  const mediaType = assertOptionalBoundedString(item.mediaType, 200);
  if (item.consumerType !== "Gui" && item.consumerType !== "Api") throw new Error("invalid");
  return { id, url, mediaType, consumerType: item.consumerType };
}

function parseAttachment(value: unknown): DialogportenAttachment {
  const item = assertRecord(value);
  const urls = item.urls === null || item.urls === undefined ? [] : item.urls;
  if (!Array.isArray(urls) || urls.length > MAX_URLS) throw new Error("invalid");
  const expiresAt = item.expiresAt === null || item.expiresAt === undefined ? null : assertTimestamp(item.expiresAt);
  return {
    id: assertUuid(item.id, "Dialogporten attachment ID"),
    name: assertOptionalBoundedString(item.name, 200),
    expiresAt,
    urls: urls.map(parseAttachmentUrl),
  };
}

function parseTransmission(value: unknown): DialogportenTransmission {
  const item = assertRecord(value);
  const types: readonly DialogportenTransmissionType[] = [
    "Information",
    "Acceptance",
    "Rejection",
    "Request",
    "Alert",
    "Decision",
    "Submission",
    "Correction",
  ];
  const attachments = item.attachments === null || item.attachments === undefined ? [] : item.attachments;
  if (!Array.isArray(attachments) || attachments.length > MAX_ATTACHMENTS) throw new Error("invalid");
  if (typeof item.isAuthorized !== "boolean" || !types.includes(item.type as DialogportenTransmissionType)) {
    throw new Error("invalid");
  }
  return {
    id: assertUuid(item.id, "Dialogporten transmission ID"),
    createdAt: assertTimestamp(item.createdAt),
    isAuthorized: item.isAuthorized,
    type: item.type as DialogportenTransmissionType,
    attachments: attachments.map(parseAttachment),
  };
}

function parseDialog(
  value: unknown,
  input: { dialogId: string; expectedPartyOrgNumber: string; expectedServiceResource: string },
): DialogportenDialog {
  try {
    const item = assertRecord(value);
    const statuses: readonly DialogportenStatus[] = ["InProgress", "Draft", "RequiresAttention", "Completed", "NotApplicable", "Awaiting"];
    const expectedParty = `urn:altinn:organization:identifier-no:${input.expectedPartyOrgNumber}`;
    const transmissions = item.transmissions === null || item.transmissions === undefined ? [] : item.transmissions;
    if (
      item.id !== input.dialogId ||
      item.party !== expectedParty ||
      item.serviceResource !== input.expectedServiceResource ||
      !statuses.includes(item.status as DialogportenStatus) ||
      !Array.isArray(transmissions) ||
      transmissions.length > MAX_TRANSMISSIONS
    ) {
      throw new Error("invalid");
    }
    return {
      id: assertUuid(item.id, "Dialogporten dialog ID"),
      revision: assertUuid(item.revision, "Dialogporten revision ID"),
      org: assertBoundedString(item.org, 100),
      serviceResource: assertBoundedString(item.serviceResource, 500),
      party: assertBoundedString(item.party, 500),
      status: item.status as DialogportenStatus,
      createdAt: assertTimestamp(item.createdAt),
      updatedAt: assertTimestamp(item.updatedAt),
      transmissions: transmissions.map(parseTransmission),
    };
  } catch {
    throw clientError("dialogporten_response_invalid", "Dialogporten returned an invalid dialog response.");
  }
}

async function readBoundedBody(response: Response, maximum: number) {
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
      throw clientError("dialogporten_response_too_large", "Dialogporten response exceeded the configured limit.", true);
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

export function createFetchDialogportenTransport(fetchImplementation: typeof fetch = fetch): DialogportenTransport {
  return async (request) => {
    const abortController = new AbortController();
    const timeout = setTimeout(() => abortController.abort(), request.timeoutMs);
    try {
      const response = await fetchImplementation(request.url, {
        method: request.method,
        headers: request.headers,
        redirect: "error",
        signal: abortController.signal,
      });
      return {
        status: response.status,
        headers: Object.fromEntries(response.headers.entries()),
        body: await readBoundedBody(response, request.maxResponseBytes),
      };
    } catch (error) {
      if (error instanceof DialogportenClientError) throw error;
      throw clientError("dialogporten_transport_failed", "Dialogporten request failed before a response was received.", true);
    } finally {
      clearTimeout(timeout);
    }
  };
}

export function createDialogportenClient(options: {
  environment: DialogportenEnvironment;
  accessToken: string;
  transport?: DialogportenTransport;
  timeoutMs?: number;
  maxResponseBytes?: number;
}): DialogportenClient {
  if (options.environment !== "test" && options.environment !== "production") {
    throw clientError("dialogporten_environment_invalid", "Dialogporten environment is invalid.");
  }
  if (
    typeof options.accessToken !== "string" ||
    options.accessToken.length < 8 ||
    options.accessToken.length > 16_384 ||
    /\s/u.test(options.accessToken)
  ) {
    throw clientError("dialogporten_access_token_invalid", "Dialogporten requires a short-lived bearer token.");
  }
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const maxResponseBytes = options.maxResponseBytes ?? DEFAULT_MAX_RESPONSE_BYTES;
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1_000 || timeoutMs > 60_000) {
    throw clientError("dialogporten_timeout_invalid", "Dialogporten timeout is invalid.");
  }
  if (!Number.isSafeInteger(maxResponseBytes) || maxResponseBytes < 64 || maxResponseBytes > 10 * 1024 * 1024) {
    throw clientError("dialogporten_response_limit_invalid", "Dialogporten response limit is invalid.");
  }
  const transport = options.transport ?? createFetchDialogportenTransport();
  const baseUrl = DIALOGPORTEN_BASE_URLS[options.environment];

  return {
    environment: options.environment,
    async getDialog(input: { dialogId: string; expectedPartyOrgNumber: string; expectedServiceResource: string }) {
      const dialogId = assertUuid(input.dialogId, "Dialogporten dialog ID");
      if (!ORG_NUMBER_PATTERN.test(input.expectedPartyOrgNumber)) {
        throw clientError("dialogporten_input_invalid", "Dialogporten expected organization number is invalid.");
      }
      if (
        typeof input.expectedServiceResource !== "string" ||
        !/^urn:altinn:resource:[a-z0-9][a-z0-9._-]{0,199}$/u.test(input.expectedServiceResource)
      ) {
        throw clientError("dialogporten_input_invalid", "Dialogporten expected service resource is invalid.");
      }
      let response: DialogportenTransportResponse;
      try {
        response = await transport({
          method: "GET",
          url: `${baseUrl}/dialogs/${dialogId}`,
          headers: {
            Authorization: `Bearer ${options.accessToken}`,
            Accept: "application/json",
            "Accept-Language": "nb",
          },
          timeoutMs,
          maxResponseBytes,
        });
      } catch (error) {
        if (error instanceof DialogportenClientError) throw error;
        throw clientError("dialogporten_transport_failed", "Dialogporten request failed before a response was received.", true);
      }
      if (
        !response ||
        !Number.isSafeInteger(response.status) ||
        !response.headers ||
        !(response.body instanceof Uint8Array)
      ) {
        throw clientError("dialogporten_transport_invalid", "Dialogporten transport returned an invalid response.", true);
      }
      if (response.body.byteLength > maxResponseBytes) {
        throw clientError("dialogporten_response_too_large", "Dialogporten response exceeded the configured limit.", true);
      }
      if (response.status !== 200) {
        const retryable = [401, 408, 425, 429, 503].includes(response.status) || response.status >= 500;
        throw clientError(
          `dialogporten_http_${response.status}`,
          `Dialogporten request failed (${response.status}).`,
          retryable,
          response.status,
        );
      }
      const contentType = Object.entries(response.headers).find(([key]) => key.toLowerCase() === "content-type")?.[1]
        ?.split(";", 1)[0]
        ?.trim()
        .toLowerCase();
      if (contentType !== "application/json") {
        throw clientError("dialogporten_response_invalid", "Dialogporten returned an invalid dialog response.");
      }
      let value: unknown;
      try {
        value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(response.body));
      } catch {
        throw clientError("dialogporten_response_invalid", "Dialogporten returned an invalid dialog response.");
      }
      return parseDialog(value, input);
    },
  };
}
