import { createHash } from "node:crypto";

import {
  requestMaskinportenToken,
  type MaskinportenAccessToken,
  type RequestMaskinportenTokenInput,
} from "./maskinporten.ts";
import { SYSTEM_USER_CALLBACK_URL } from "./system-user-requests.ts";

export const AUTHORITY_OPERATION = "register_rf1086_system" as const;
export const AUTHORITY_CONFIRMATION = "REGISTER TALLI RF1086 SYSTEM" as const;
export const SYSTEMBRUKER_CALLBACK_OPERATION = "set_rf1086_systembruker_callback" as const;
export const SYSTEMBRUKER_CALLBACK_CONFIRMATION = "SET TALLI SYSTEMBRUKER CALLBACK" as const;
export const SYSTEMBRUKER_CALLBACK_PATH = "/auth/systembruker/confirm" as const;
export const TALLI_SYSTEM_ID = "930835978_talli" as const;
export const RF1086_RIGHT = "ske-innrapportering-aksjonaerregisteroppgave" as const;

const SYSTEMREGISTER_SCOPE = "altinn:authentication/systemregister.write" as const;
const SYSTEMREGISTER_BASE_URL =
  "https://platform.altinn.no/authentication/api/v1/systemregister/vendor" as const;
const MAX_AUTHORITY_RESPONSE_BYTES = 64 * 1024;

export type AuthorityOperationEnvironment = {
  clientId: string;
  keyId: string;
  privateKeyPem: string;
};

type LocalizedText = { nb: string; nn: string; en: string };

export type Rf1086SystemDefinition = {
  id: typeof TALLI_SYSTEM_ID;
  vendor: { authority: "iso6523-actorid-upis"; ID: "0192:930835978" };
  name: LocalizedText;
  description: LocalizedText;
  rights: Array<{
    resource: Array<{ id: "urn:altinn:resource"; value: typeof RF1086_RIGHT }>;
  }>;
  accessPackages: [];
  clientId: [string];
  allowedredirecturls: [];
  isVisible: true;
};

export type Rf1086SystembrukerCallbackDefinition = Omit<
  Rf1086SystemDefinition,
  "allowedredirecturls"
> & {
  allowedRedirectUrls: Array<typeof SYSTEM_USER_CALLBACK_URL>;
  isDeleted: false;
};

export type AuthorityOperationResult = {
  status: "succeeded" | "conflict";
  code: "created_and_verified" | "already_verified" | "definition_conflict";
  systemId: typeof TALLI_SYSTEM_ID;
  clientId: string;
  right: typeof RF1086_RIGHT;
  authorityStatus: number;
};

export type SystembrukerCallbackResultCode =
  | "callback_already_verified"
  | "callback_updated_and_verified"
  | "definition_conflict";

export type SystembrukerCallbackOperationResult = {
  status: "succeeded" | "conflict";
  resultCode: SystembrukerCallbackResultCode;
  systemId: typeof TALLI_SYSTEM_ID;
  callbackPath: typeof SYSTEMBRUKER_CALLBACK_PATH;
  authorityStatus: number;
};

type FetchLike = (
  input: string | URL | globalThis.Request,
  init?: RequestInit,
) => Promise<Response>;

type TokenRequester = (
  input: RequestMaskinportenTokenInput,
) => Promise<MaskinportenAccessToken>;

export class AuthorityOperationError extends Error {
  readonly code: string;
  readonly authorityStatus: number | null;

  constructor(code: string, authorityStatus: number | null = null) {
    super(code);
    this.name = "AuthorityOperationError";
    this.code = code;
    this.authorityStatus = authorityStatus;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function requiredProductionUuid(value: string | undefined, label: string): string {
  const candidate = value ?? "";
  if (/(?:test|tt02)/iu.test(candidate)) {
    throw new AuthorityOperationError(`${label} must not reference test`);
  }
  if (!/^[a-f0-9]{8}-[a-f0-9]{4}-[1-5][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/iu.test(candidate)) {
    throw new AuthorityOperationError(`${label}_invalid`);
  }
  return candidate;
}

export function productionAuthorityOperationEnvironment(
  environment: Record<string, string | undefined> = process.env,
): AuthorityOperationEnvironment | null {
  if (environment.TALLI_AUTHORITY_OPS_ENABLED !== "true") {
    return null;
  }

  const clientId = requiredProductionUuid(
    environment.TALLI_PROD_MASKINPORTEN_CLIENT_ID,
    "authority_client_id",
  );
  const keyId = requiredProductionUuid(
    environment.TALLI_PROD_MASKINPORTEN_KEY_ID,
    "authority_key_id",
  );
  const privateKeyPem = environment.TALLI_PROD_MASKINPORTEN_PRIVATE_KEY_PEM ?? "";
  if (/(?:test|tt02)/iu.test(privateKeyPem)) {
    throw new AuthorityOperationError("authority_private_key must not reference test");
  }
  if (
    !/^-----BEGIN (?:RSA )?PRIVATE KEY-----[\s\S]+-----END (?:RSA )?PRIVATE KEY-----\s*$/u
      .test(privateKeyPem)
  ) {
    throw new AuthorityOperationError("authority_private_key_invalid");
  }

  return { clientId, keyId, privateKeyPem };
}

export function authorityOperationEnvironmentFailureCode(error: unknown):
  | "authority_client_id_invalid"
  | "authority_key_id_invalid"
  | "authority_private_key_invalid"
  | "authority_environment_invalid" {
  if (!(error instanceof AuthorityOperationError)) {
    return "authority_environment_invalid";
  }
  if (error.code.startsWith("authority_client_id")) {
    return "authority_client_id_invalid";
  }
  if (error.code.startsWith("authority_key_id")) {
    return "authority_key_id_invalid";
  }
  if (error.code.startsWith("authority_private_key")) {
    return "authority_private_key_invalid";
  }
  return "authority_environment_invalid";
}

export function buildRf1086SystemDefinition(clientId: string): Rf1086SystemDefinition {
  const productionClientId = requiredProductionUuid(clientId, "authority_client_id");
  return {
    id: TALLI_SYSTEM_ID,
    vendor: { authority: "iso6523-actorid-upis", ID: "0192:930835978" },
    name: { nb: "Talli", nn: "Talli", en: "Talli" },
    description: {
      nb: "Talli leverer aksjonærregisteroppgaven (RF-1086) for enkle holdingselskap (AS) på vegne av selskapet selv.",
      nn: "Talli leverer aksjonærregisteroppgåva (RF-1086) for enkle holdingselskap (AS) på vegne av selskapet sjølv.",
      en: "Talli files the shareholder register statement (RF-1086) for simple holding companies (AS) on behalf of the company itself.",
    },
    rights: [
      {
        resource: [{ id: "urn:altinn:resource", value: RF1086_RIGHT }],
      },
    ],
    accessPackages: [],
    clientId: [productionClientId],
    allowedredirecturls: [],
    isVisible: true,
  };
}

function buildSystembrukerCallbackDefinition(
  clientId: string,
  allowedRedirectUrls: Array<typeof SYSTEM_USER_CALLBACK_URL>,
): Rf1086SystembrukerCallbackDefinition {
  const { allowedredirecturls: _allowedRedirectUrls, ...fixedDefinition } =
    buildRf1086SystemDefinition(clientId);
  return {
    ...fixedDefinition,
    allowedRedirectUrls,
    isDeleted: false,
  };
}

export function buildRf1086SystembrukerCallbackDefinition(
  clientId: string,
): Rf1086SystembrukerCallbackDefinition {
  return buildSystembrukerCallbackDefinition(clientId, [SYSTEM_USER_CALLBACK_URL]);
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(",")}]`;
  }
  if (isRecord(value)) {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

export function authorityOperationRequestHash(
  definition: Rf1086SystemDefinition | Rf1086SystembrukerCallbackDefinition,
): string {
  return createHash("sha256").update(canonicalJson(definition), "utf8").digest("hex");
}

export function assertAuthorityOperationIntent(input: {
  operation: unknown;
  confirmation: unknown;
}): void {
  if (
    input.operation !== AUTHORITY_OPERATION ||
    input.confirmation !== AUTHORITY_CONFIRMATION
  ) {
    throw new AuthorityOperationError("authority_operation_invalid");
  }
}

export function assertSystembrukerCallbackOperationIntent(input: {
  operation: unknown;
  confirmation: unknown;
}): void {
  if (
    input.operation !== SYSTEMBRUKER_CALLBACK_OPERATION ||
    input.confirmation !== SYSTEMBRUKER_CALLBACK_CONFIRMATION
  ) {
    throw new AuthorityOperationError("authority_operation_invalid");
  }
}

function definitionProjection(value: unknown): Rf1086SystemDefinition | null {
  if (!isRecord(value)) return null;
  const vendor = isRecord(value.vendor) ? value.vendor : {};
  const projected = {
    id: value.id,
    vendor: {
      authority: vendor.authority ?? "iso6523-actorid-upis",
      ID: vendor.ID,
    },
    name: value.name,
    description: value.description,
    rights: value.rights,
    accessPackages: value.accessPackages,
    clientId: value.clientId,
    allowedredirecturls: value.allowedredirecturls ?? value.allowedRedirectUrls,
    isVisible: value.isVisible,
  };
  return projected as Rf1086SystemDefinition;
}

function definitionsMatch(actual: unknown, expected: Rf1086SystemDefinition): boolean {
  const projected = definitionProjection(actual);
  return projected !== null && canonicalJson(projected) === canonicalJson(expected);
}

function callbackDefinitionProjection(
  value: unknown,
): Rf1086SystembrukerCallbackDefinition | null {
  if (!isRecord(value)) return null;
  const vendor = isRecord(value.vendor) ? value.vendor : {};
  const camelCaseCallbacks = value.allowedRedirectUrls;
  const legacyCallbacks = value.allowedredirecturls;
  if (
    camelCaseCallbacks !== undefined &&
    legacyCallbacks !== undefined &&
    canonicalJson(camelCaseCallbacks) !== canonicalJson(legacyCallbacks)
  ) {
    return null;
  }
  return {
    id: value.id,
    vendor: {
      authority: vendor.authority === undefined
        ? "iso6523-actorid-upis"
        : vendor.authority,
      ID: vendor.ID,
    },
    name: value.name,
    description: value.description,
    rights: value.rights,
    accessPackages: value.accessPackages,
    clientId: value.clientId,
    allowedRedirectUrls: camelCaseCallbacks ?? legacyCallbacks,
    isVisible: value.isVisible,
    isDeleted: value.isDeleted,
  } as Rf1086SystembrukerCallbackDefinition;
}

function callbackDefinitionsMatch(
  actual: unknown,
  expected: Rf1086SystembrukerCallbackDefinition,
): boolean {
  const projected = callbackDefinitionProjection(actual);
  return projected !== null && canonicalJson(projected) === canonicalJson(expected);
}

async function parseAuthorityJson(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  const contentLength = Number(response.headers.get("content-length") ?? "0");
  if (
    !contentType.toLowerCase().includes("application/json") ||
    (Number.isFinite(contentLength) && contentLength > MAX_AUTHORITY_RESPONSE_BYTES)
  ) {
    throw new AuthorityOperationError("authority_response_invalid", response.status);
  }

  let text: string;
  try {
    text = await response.text();
  } catch {
    throw new AuthorityOperationError("authority_response_invalid", response.status);
  }
  if (Buffer.byteLength(text, "utf8") > MAX_AUTHORITY_RESPONSE_BYTES) {
    throw new AuthorityOperationError("authority_response_invalid", response.status);
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new AuthorityOperationError("authority_response_invalid", response.status);
  }
  return parsed;
}

async function parseAuthorityObject(response: Response): Promise<Record<string, unknown>> {
  const parsed = await parseAuthorityJson(response);
  if (!isRecord(parsed)) {
    throw new AuthorityOperationError("authority_response_invalid", response.status);
  }
  return parsed;
}

async function parseAuthorityCreateResponse(response: Response): Promise<void> {
  const parsed = await parseAuthorityJson(response);
  if (
    typeof parsed !== "string" ||
    !/^[a-f0-9]{8}-[a-f0-9]{4}-[1-5][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/iu.test(parsed)
  ) {
    throw new AuthorityOperationError("authority_response_invalid", response.status);
  }
}

async function consumeCappedAuthorityResponse(response: Response): Promise<void> {
  const contentLength = Number(response.headers.get("content-length") ?? "0");
  if (Number.isFinite(contentLength) && contentLength > MAX_AUTHORITY_RESPONSE_BYTES) {
    throw new AuthorityOperationError("authority_response_invalid", response.status);
  }
  let text: string;
  try {
    text = await response.text();
  } catch {
    throw new AuthorityOperationError("authority_response_invalid", response.status);
  }
  if (Buffer.byteLength(text, "utf8") > MAX_AUTHORITY_RESPONSE_BYTES) {
    throw new AuthorityOperationError("authority_response_invalid", response.status);
  }
}

async function authorityFetch(
  fetcher: FetchLike,
  url: string,
  init: RequestInit,
): Promise<Response> {
  try {
    return await fetcher(url, {
      ...init,
      redirect: "error",
      signal: AbortSignal.timeout(15_000),
    });
  } catch {
    throw new AuthorityOperationError("authority_network_error");
  }
}

function result(
  environment: AuthorityOperationEnvironment,
  status: AuthorityOperationResult["status"],
  code: AuthorityOperationResult["code"],
  authorityStatus: number,
): AuthorityOperationResult {
  return {
    status,
    code,
    systemId: TALLI_SYSTEM_ID,
    clientId: environment.clientId,
    right: RF1086_RIGHT,
    authorityStatus,
  };
}

export async function executeRf1086SystemRegistration(
  environment: AuthorityOperationEnvironment,
  dependencies: { requestToken?: TokenRequester; fetch?: FetchLike } = {},
): Promise<AuthorityOperationResult> {
  const definition = buildRf1086SystemDefinition(environment.clientId);
  let accessToken: MaskinportenAccessToken;
  try {
    accessToken = await (dependencies.requestToken ?? requestMaskinportenToken)({
      environment: "production",
      clientId: environment.clientId,
      keyId: environment.keyId,
      privateKeyPem: environment.privateKeyPem,
      scope: SYSTEMREGISTER_SCOPE,
    });
  } catch {
    throw new AuthorityOperationError("authority_token_error");
  }

  const fetcher = dependencies.fetch ?? fetch;
  const headers = {
    authorization: `Bearer ${accessToken.accessToken}`,
    accept: "application/json",
  };
  const systemUrl = `${SYSTEMREGISTER_BASE_URL}/${TALLI_SYSTEM_ID}`;
  const currentResponse = await authorityFetch(fetcher, systemUrl, {
    method: "GET",
    headers,
  });

  if (currentResponse.status === 200) {
    const current = await parseAuthorityObject(currentResponse);
    return definitionsMatch(current, definition)
      ? result(environment, "succeeded", "already_verified", currentResponse.status)
      : result(environment, "conflict", "definition_conflict", currentResponse.status);
  }
  if (currentResponse.status !== 404) {
    throw new AuthorityOperationError("authority_http_error", currentResponse.status);
  }

  const createResponse = await authorityFetch(fetcher, SYSTEMREGISTER_BASE_URL, {
    method: "POST",
    headers: { ...headers, "content-type": "application/json" },
    body: JSON.stringify(definition),
  });
  if (createResponse.status !== 200 && createResponse.status !== 201) {
    throw new AuthorityOperationError("authority_http_error", createResponse.status);
  }
  await parseAuthorityCreateResponse(createResponse);

  const verifyResponse = await authorityFetch(fetcher, systemUrl, {
    method: "GET",
    headers,
  });
  if (verifyResponse.status !== 200) {
    throw new AuthorityOperationError("authority_http_error", verifyResponse.status);
  }
  const verified = await parseAuthorityObject(verifyResponse);
  return definitionsMatch(verified, definition)
    ? result(environment, "succeeded", "created_and_verified", verifyResponse.status)
    : result(environment, "conflict", "definition_conflict", verifyResponse.status);
}

function callbackResult(
  status: SystembrukerCallbackOperationResult["status"],
  resultCode: SystembrukerCallbackResultCode,
  authorityStatus: number,
): SystembrukerCallbackOperationResult {
  return {
    status,
    resultCode,
    systemId: TALLI_SYSTEM_ID,
    callbackPath: SYSTEMBRUKER_CALLBACK_PATH,
    authorityStatus,
  };
}

export async function executeRf1086SystembrukerCallbackUpdate(
  environment: AuthorityOperationEnvironment,
  dependencies: { requestToken?: TokenRequester; fetch?: FetchLike } = {},
): Promise<SystembrukerCallbackOperationResult> {
  const emptyDefinition = buildSystembrukerCallbackDefinition(environment.clientId, []);
  const callbackDefinition = buildRf1086SystembrukerCallbackDefinition(environment.clientId);
  let accessToken: MaskinportenAccessToken;
  try {
    accessToken = await (dependencies.requestToken ?? requestMaskinportenToken)({
      environment: "production",
      clientId: environment.clientId,
      keyId: environment.keyId,
      privateKeyPem: environment.privateKeyPem,
      scope: SYSTEMREGISTER_SCOPE,
    });
  } catch {
    throw new AuthorityOperationError("authority_token_error");
  }

  const fetcher = dependencies.fetch ?? fetch;
  const headers = {
    authorization: `Bearer ${accessToken.accessToken}`,
    accept: "application/json",
  };
  const systemUrl = `${SYSTEMREGISTER_BASE_URL}/${TALLI_SYSTEM_ID}`;
  const currentResponse = await authorityFetch(fetcher, systemUrl, {
    method: "GET",
    headers,
  });
  if (currentResponse.status === 404) {
    return callbackResult("conflict", "definition_conflict", currentResponse.status);
  }
  if (currentResponse.status !== 200) {
    throw new AuthorityOperationError("authority_http_error", currentResponse.status);
  }

  const current = await parseAuthorityObject(currentResponse);
  if (callbackDefinitionsMatch(current, callbackDefinition)) {
    return callbackResult("succeeded", "callback_already_verified", currentResponse.status);
  }
  if (!callbackDefinitionsMatch(current, emptyDefinition)) {
    return callbackResult("conflict", "definition_conflict", currentResponse.status);
  }

  const updateResponse = await authorityFetch(fetcher, systemUrl, {
    method: "PUT",
    headers: { ...headers, "content-type": "application/json" },
    body: JSON.stringify(callbackDefinition),
  });
  if (updateResponse.status !== 200 && updateResponse.status !== 204) {
    throw new AuthorityOperationError("authority_http_error", updateResponse.status);
  }
  await consumeCappedAuthorityResponse(updateResponse);

  const verifyResponse = await authorityFetch(fetcher, systemUrl, {
    method: "GET",
    headers,
  });
  if (verifyResponse.status !== 200) {
    throw new AuthorityOperationError("authority_http_error", verifyResponse.status);
  }
  const verified = await parseAuthorityObject(verifyResponse);
  return callbackDefinitionsMatch(verified, callbackDefinition)
    ? callbackResult("succeeded", "callback_updated_and_verified", verifyResponse.status)
    : callbackResult("conflict", "definition_conflict", verifyResponse.status);
}
