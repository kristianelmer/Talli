import { createPrivateKey, randomUUID, sign } from "node:crypto";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const ORG_NUMBER_PATTERN = /^\d{9}$/u;
const SCOPE_PATTERN = /^[a-z0-9][a-z0-9:/.\-_]{0,199}$/u;
const DEFAULT_TIMEOUT_MS = 15_000;
const MAX_TOKEN_RESPONSE_BYTES = 64 * 1024;

// Official issuer/audience and JWT-bearer token endpoint contract:
// https://docs.digdir.no/docs/Maskinporten/maskinporten_protocol_token.html
// System-user RAR authorization_details contract:
// https://docs.digdir.no/docs/Maskinporten/maskinporten_func_systembruker.html
export const MASKINPORTEN_ISSUERS = {
  test: "https://test.maskinporten.no/",
  production: "https://maskinporten.no/",
} as const;
export type MaskinportenEnvironment = keyof typeof MASKINPORTEN_ISSUERS;
export const MASKINPORTEN_TEST_ISSUER = MASKINPORTEN_ISSUERS.test;

export class MaskinportenSystemUserError extends Error {
  readonly code: string;
  readonly retryable: boolean;

  constructor(code: string, message: string, retryable = false) {
    super(message);
    this.name = "MaskinportenSystemUserError";
    this.code = code;
    this.retryable = retryable;
  }
}

function systemUserError(code: string, message: string, retryable = false) {
  return new MaskinportenSystemUserError(code, message, retryable);
}

function assertEnvironment(value: unknown): MaskinportenEnvironment {
  if (value !== "test" && value !== "production") {
    throw systemUserError("maskinporten_environment_invalid", "Maskinporten environment is invalid.");
  }
  return value;
}

function assertUuid(value: unknown, label: string) {
  if (typeof value !== "string" || !UUID_PATTERN.test(value)) {
    throw systemUserError("maskinporten_identifier_invalid", `${label} must be a UUID.`);
  }
  return value;
}

function assertOrgNumber(value: unknown) {
  if (typeof value !== "string" || !ORG_NUMBER_PATTERN.test(value)) {
    throw systemUserError("maskinporten_org_number_invalid", "Maskinporten customer organization number is invalid.");
  }
  return value;
}

function canonicalScopes(values: unknown) {
  if (!Array.isArray(values) || values.length < 1 || values.length > 20) {
    throw systemUserError("maskinporten_scope_invalid", "Maskinporten requires at least one bounded scope.");
  }
  const scopes = values.map((value) => {
    if (typeof value !== "string" || !SCOPE_PATTERN.test(value)) {
      throw systemUserError("maskinporten_scope_invalid", "Maskinporten scope is invalid.");
    }
    return value;
  });
  return [...new Set(scopes)].sort();
}

function encodeJson(value: unknown) {
  return Buffer.from(JSON.stringify(value), "utf8").toString("base64url");
}

export function createMaskinportenSystemUserGrant(input: {
  environment: MaskinportenEnvironment;
  clientId: string;
  keyId: string;
  customerOrgNumber: string;
  scopes: string[];
  privateKeyPem: string;
  nowSeconds?: number;
  jti?: string;
}) {
  const environment = assertEnvironment(input.environment);
  const clientId = assertUuid(input.clientId, "Maskinporten client ID");
  const keyId = assertUuid(input.keyId, "Maskinporten key ID");
  const customerOrgNumber = assertOrgNumber(input.customerOrgNumber);
  const scopes = canonicalScopes(input.scopes);
  const nowSeconds = input.nowSeconds ?? Math.floor(Date.now() / 1_000);
  if (!Number.isSafeInteger(nowSeconds) || nowSeconds < 1_500_000_000 || nowSeconds > 4_000_000_000) {
    throw systemUserError("maskinporten_time_invalid", "Maskinporten grant time is invalid.");
  }
  const jti = assertUuid(input.jti ?? randomUUID(), "Maskinporten JWT ID");
  if (typeof input.privateKeyPem !== "string" || input.privateKeyPem.length < 100 || input.privateKeyPem.length > 64 * 1024) {
    throw systemUserError("maskinporten_private_key_invalid", "Maskinporten private key is invalid.");
  }

  let privateKey;
  try {
    privateKey = createPrivateKey(input.privateKeyPem);
  } catch {
    throw systemUserError("maskinporten_private_key_invalid", "Maskinporten private key is invalid.");
  }
  if (privateKey.asymmetricKeyType !== "rsa" && privateKey.asymmetricKeyType !== "rsa-pss") {
    throw systemUserError("maskinporten_private_key_invalid", "Maskinporten private key must be RSA.");
  }

  const header = encodeJson({ alg: "RS256", kid: keyId, typ: "JWT" });
  const payload = encodeJson({
    aud: MASKINPORTEN_ISSUERS[environment],
    iss: clientId,
    scope: scopes.join(" "),
    authorization_details: [
      {
        type: "urn:altinn:systemuser",
        systemuser_org: {
          authority: "iso6523-actorid-upis",
          ID: `0192:${customerOrgNumber}`,
        },
      },
    ],
    iat: nowSeconds,
    exp: nowSeconds + 120,
    jti,
  });
  const signingInput = `${header}.${payload}`;
  const signature = sign("RSA-SHA256", Buffer.from(signingInput, "utf8"), privateKey).toString("base64url");
  return `${signingInput}.${signature}`;
}

export function createMaskinportenTestSystemUserGrant(
  input: Omit<Parameters<typeof createMaskinportenSystemUserGrant>[0], "environment">,
) {
  return createMaskinportenSystemUserGrant({ ...input, environment: "test" });
}

async function readBoundedJson(response: Response) {
  const contentType = response.headers.get("content-type")?.split(";", 1)[0]?.trim().toLowerCase();
  if (contentType !== "application/json") {
    throw systemUserError("maskinporten_response_invalid", "Maskinporten returned an invalid response.");
  }
  const declaredLength = Number(response.headers.get("content-length"));
  if (Number.isFinite(declaredLength) && declaredLength > MAX_TOKEN_RESPONSE_BYTES) {
    throw systemUserError("maskinporten_response_invalid", "Maskinporten returned an invalid response.");
  }
  const body = new Uint8Array(await response.arrayBuffer());
  if (body.byteLength > MAX_TOKEN_RESPONSE_BYTES) {
    throw systemUserError("maskinporten_response_invalid", "Maskinporten returned an invalid response.");
  }
  try {
    const value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(body));
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("invalid");
    return value as Record<string, unknown>;
  } catch {
    throw systemUserError("maskinporten_response_invalid", "Maskinporten returned an invalid response.");
  }
}

export async function requestMaskinportenSystemUserToken(input: {
  environment: MaskinportenEnvironment;
  assertion: string;
  requestedScopes: string[];
  fetchImplementation?: typeof fetch;
  timeoutMs?: number;
}) {
  const environment = assertEnvironment(input.environment);
  if (typeof input.assertion !== "string" || input.assertion.length < 16 || input.assertion.length > 128 * 1024) {
    throw systemUserError("maskinporten_assertion_invalid", "Maskinporten assertion is invalid.");
  }
  const requestedScopes = canonicalScopes(input.requestedScopes);
  const timeoutMs = input.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1_000 || timeoutMs > 60_000) {
    throw systemUserError("maskinporten_timeout_invalid", "Maskinporten timeout is invalid.");
  }
  const body = new URLSearchParams({
    assertion: input.assertion,
    grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
  }).toString();
  const abortController = new AbortController();
  const timeout = setTimeout(() => abortController.abort(), timeoutMs);
  let response: Response;
  try {
    response = await (input.fetchImplementation ?? fetch)(`${MASKINPORTEN_ISSUERS[environment]}token`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
      redirect: "error",
      signal: abortController.signal,
    });
  } catch {
    throw systemUserError("maskinporten_transport_failed", "Maskinporten token request failed.", true);
  } finally {
    clearTimeout(timeout);
  }
  const value = await readBoundedJson(response);
  if (!response.ok) {
    throw systemUserError("maskinporten_token_rejected", `Maskinporten token request failed (${response.status}).`, response.status >= 500);
  }

  const accessToken = value.access_token;
  const tokenType = value.token_type;
  const expiresIn = value.expires_in;
  const scopes = typeof value.scope === "string" ? value.scope.split(/\s+/u).filter(Boolean).sort() : [];
  if (
    typeof accessToken !== "string" ||
    accessToken.length < 8 ||
    accessToken.length > 32 * 1024 ||
    /\s/u.test(accessToken) ||
    tokenType !== "Bearer" ||
    !Number.isSafeInteger(expiresIn) ||
    (expiresIn as number) < 1 ||
    (expiresIn as number) > 600 ||
    requestedScopes.some((scope) => !scopes.includes(scope))
  ) {
    throw systemUserError("maskinporten_response_invalid", "Maskinporten returned an invalid response.");
  }
  return { accessToken, expiresIn: expiresIn as number, scopes };
}

export function requestMaskinportenTestSystemUserToken(
  input: Omit<Parameters<typeof requestMaskinportenSystemUserToken>[0], "environment">,
) {
  return requestMaskinportenSystemUserToken({ ...input, environment: "test" });
}

export async function issueMaskinportenSystemUserToken(
  input: Parameters<typeof createMaskinportenSystemUserGrant>[0] & {
    fetchImplementation?: typeof fetch;
    timeoutMs?: number;
  },
) {
  const assertion = createMaskinportenSystemUserGrant(input);
  return requestMaskinportenSystemUserToken({
    environment: input.environment,
    assertion,
    requestedScopes: input.scopes,
    ...(input.fetchImplementation ? { fetchImplementation: input.fetchImplementation } : {}),
    ...(input.timeoutMs ? { timeoutMs: input.timeoutMs } : {}),
  });
}

export async function issueMaskinportenTestSystemUserToken(
  input: Parameters<typeof createMaskinportenTestSystemUserGrant>[0] & {
    fetchImplementation?: typeof fetch;
    timeoutMs?: number;
  },
) {
  return issueMaskinportenSystemUserToken({ ...input, environment: "test" });
}
