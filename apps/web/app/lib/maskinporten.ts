import { randomUUID, sign, type KeyLike } from "node:crypto";

export const MASKINPORTEN_JWT_BEARER_GRANT_TYPE =
  "urn:ietf:params:oauth:grant-type:jwt-bearer";

export type MaskinportenEnvironment = "test" | "production";

export type ProductionMaskinportenCredentials = {
  environment: "production";
  clientId: string;
  keyId: string;
  privateKeyPem: string;
};

export type MaskinportenGrantHeader = {
  alg: "RS256";
  kid: string;
  typ: "JWT";
};

export type MaskinportenGrantClaims = {
  aud: string;
  iss: string;
  iat: number;
  exp: number;
  jti: string;
  scope: string;
  sub?: string;
  authorization_details?: Array<{
    type: "urn:altinn:systemuser";
    systemuser_org: {
      authority: "iso6523-actorid-upis";
      ID: string;
    };
    externalRef?: string;
  }>;
};

export type MaskinportenGrant = {
  header: MaskinportenGrantHeader;
  claims: MaskinportenGrantClaims;
  tokenEndpoint: string;
  environment: MaskinportenEnvironment;
};

export type BuildMaskinportenGrantInput = {
  environment: MaskinportenEnvironment;
  clientId: string;
  keyId: string;
  scope: string;
  systemUserOrgNumber?: string;
  systemUserExternalRef?: string;
  now?: Date;
  jti?: string;
};

export type RequestMaskinportenTokenInput = BuildMaskinportenGrantInput & {
  privateKeyPem: string;
};

export type MaskinportenAccessToken = {
  accessToken: string;
  tokenType: string;
  expiresIn: number;
  scope: string;
  environment: MaskinportenEnvironment;
};

export type MaskinportenTokenSummary = {
  environment: MaskinportenEnvironment;
  scope: string;
  tokenType: string;
  expiresIn: number;
  accessTokenPresent: boolean;
};

type FetchLike = (
  input: string | URL | globalThis.Request,
  init?: RequestInit,
) => Promise<Response>;

export class MaskinportenTokenError extends Error {
  readonly status: number | null;
  readonly code: string;

  constructor(message: string, options: { status?: number | null; code?: string; cause?: unknown } = {}) {
    super(message, options.cause === undefined ? undefined : { cause: options.cause });
    this.name = "MaskinportenTokenError";
    this.status = options.status ?? null;
    this.code = options.code ?? "maskinporten_token_error";
  }
}

const ENDPOINTS: Record<MaskinportenEnvironment, { issuer: string; tokenEndpoint: string }> = {
  test: {
    issuer: "https://test.maskinporten.no/",
    tokenEndpoint: "https://test.maskinporten.no/token",
  },
  production: {
    issuer: "https://maskinporten.no/",
    tokenEndpoint: "https://maskinporten.no/token",
  },
};

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;

export function productionMaskinportenCredentials(
  environment: Record<string, string | undefined> = process.env,
): ProductionMaskinportenCredentials {
  const clientId = environment.TALLI_PROD_MASKINPORTEN_CLIENT_ID ?? "";
  const keyId = environment.TALLI_PROD_MASKINPORTEN_KEY_ID ?? "";
  const privateKeyPem = environment.TALLI_PROD_MASKINPORTEN_PRIVATE_KEY_PEM ?? "";
  if (
    !UUID_PATTERN.test(clientId)
    || !UUID_PATTERN.test(keyId)
    || /(?:test|tt02)/iu.test(clientId)
    || /(?:test|tt02)/iu.test(keyId)
  ) {
    throw new Error("Production Maskinporten credential identifiers are required.");
  }
  if (
    /(?:test|tt02)/iu.test(privateKeyPem)
    || !/^-----BEGIN (?:RSA )?PRIVATE KEY-----[\s\S]+-----END (?:RSA )?PRIVATE KEY-----\s*$/u
      .test(privateKeyPem)
  ) {
    throw new Error("Production Maskinporten private key must be an inline PEM credential.");
  }
  return { environment: "production", clientId, keyId, privateKeyPem };
}

function requiredIdentifier(value: string, label: string): string {
  const trimmed = value?.trim() ?? "";
  if (!trimmed || trimmed !== value || /[\s\u0000-\u001f]/u.test(trimmed)) {
    throw new Error(`${label} is required and cannot contain whitespace.`);
  }
  return trimmed;
}

function normalizedScope(value: string): string {
  const trimmed = value?.trim() ?? "";
  if (!trimmed || trimmed !== value || /[\r\n\t\u0000]/u.test(trimmed)) {
    throw new Error("Maskinporten scope is invalid.");
  }
  const parts = trimmed.split(" ");
  if (parts.some((part) => !part)) {
    throw new Error("Maskinporten scope is invalid.");
  }
  return trimmed;
}

function endpointFor(environment: MaskinportenEnvironment) {
  const endpoint = ENDPOINTS[environment];
  if (!endpoint) {
    throw new Error("Maskinporten environment must be test or production.");
  }
  return endpoint;
}

function base64UrlJson(value: unknown): string {
  return Buffer.from(JSON.stringify(value), "utf8").toString("base64url");
}

function safeText(value: unknown, fallback: string): string {
  if (typeof value !== "string") return fallback;
  const sanitized = value.replace(/[\u0000-\u001f\u007f]/gu, " ").replace(/\s+/gu, " ").trim();
  return sanitized.slice(0, 500) || fallback;
}

function safeJsonObject(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

export function buildMaskinportenGrant(input: BuildMaskinportenGrantInput): MaskinportenGrant {
  const endpoint = endpointFor(input.environment);
  const clientId = requiredIdentifier(input.clientId, "Maskinporten client id");
  const keyId = requiredIdentifier(input.keyId, "Maskinporten key id");
  const scope = normalizedScope(input.scope);
  const issuedAt = Math.floor((input.now ?? new Date()).getTime() / 1000);
  if (!Number.isFinite(issuedAt)) {
    throw new Error("Maskinporten grant time is invalid.");
  }

  const claims: MaskinportenGrantClaims = {
    aud: endpoint.issuer,
    iss: clientId,
    iat: issuedAt,
    exp: issuedAt + 119,
    jti: requiredIdentifier(input.jti ?? randomUUID(), "Maskinporten JWT id"),
    scope,
  };

  if (input.systemUserOrgNumber !== undefined) {
    const organizationNumber = input.systemUserOrgNumber.trim();
    if (!/^\d{9}$/u.test(organizationNumber)) {
      throw new Error("Maskinporten system-user organization number must contain 9 digits.");
    }
    const authorizationDetail: NonNullable<MaskinportenGrantClaims["authorization_details"]>[number] = {
      type: "urn:altinn:systemuser",
      systemuser_org: {
        authority: "iso6523-actorid-upis",
        ID: `0192:${organizationNumber}`,
      },
    };
    if (input.systemUserExternalRef !== undefined) {
      authorizationDetail.externalRef = requiredIdentifier(
        input.systemUserExternalRef,
        "Altinn system-user external reference",
      );
    }
    claims.sub = clientId;
    claims.authorization_details = [authorizationDetail];
  }

  return {
    header: { alg: "RS256", kid: keyId, typ: "JWT" },
    claims,
    tokenEndpoint: endpoint.tokenEndpoint,
    environment: input.environment,
  };
}

export function signMaskinportenGrant(grant: MaskinportenGrant, privateKey: KeyLike): string {
  const signingInput = `${base64UrlJson(grant.header)}.${base64UrlJson(grant.claims)}`;
  const signature = sign("RSA-SHA256", Buffer.from(signingInput, "ascii"), privateKey);
  return `${signingInput}.${signature.toString("base64url")}`;
}

export async function requestMaskinportenToken(
  input: RequestMaskinportenTokenInput,
  dependencies: { fetch?: FetchLike } = {},
): Promise<MaskinportenAccessToken> {
  const grant = buildMaskinportenGrant(input);
  let assertion: string;
  try {
    assertion = signMaskinportenGrant(grant, input.privateKeyPem);
  } catch (cause) {
    throw new MaskinportenTokenError("Unable to sign Maskinporten grant.", {
      code: "maskinporten_grant_signing_failed",
      cause,
    });
  }

  const body = new URLSearchParams({
    grant_type: MASKINPORTEN_JWT_BEARER_GRANT_TYPE,
    assertion,
  });
  let response: Response;
  try {
    response = await (dependencies.fetch ?? fetch)(grant.tokenEndpoint, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: body.toString(),
      signal: AbortSignal.timeout(15_000),
    });
  } catch (cause) {
    throw new MaskinportenTokenError("Maskinporten token request failed before a response was received.", {
      code: "maskinporten_network_error",
      cause,
    });
  }

  let parsed: unknown = {};
  try {
    parsed = await response.json();
  } catch {
    parsed = {};
  }
  const data = safeJsonObject(parsed);

  if (!response.ok) {
    const code = safeText(data.error, "maskinporten_http_error");
    const description = safeText(data.error_description, `Maskinporten returned HTTP ${response.status}.`);
    throw new MaskinportenTokenError(`Maskinporten token request was rejected: ${description}`, {
      status: response.status,
      code,
    });
  }

  const accessToken = typeof data.access_token === "string" ? data.access_token : "";
  if (!accessToken) {
    throw new MaskinportenTokenError("Maskinporten token response is missing access_token.", {
      status: response.status,
      code: "maskinporten_response_invalid",
    });
  }
  const expiresIn = Number(data.expires_in);
  if (!Number.isFinite(expiresIn) || expiresIn <= 0) {
    throw new MaskinportenTokenError("Maskinporten token response has an invalid expires_in value.", {
      status: response.status,
      code: "maskinporten_response_invalid",
    });
  }
  if (data.scope !== undefined && data.scope !== grant.claims.scope) {
    throw new MaskinportenTokenError("Maskinporten token response scope does not match the request.", {
      status: response.status,
      code: "maskinporten_response_invalid",
    });
  }

  return {
    accessToken,
    tokenType: safeText(data.token_type, "Bearer"),
    expiresIn,
    scope: grant.claims.scope,
    environment: grant.environment,
  };
}

export function summarizeMaskinportenToken(token: MaskinportenAccessToken): MaskinportenTokenSummary {
  return {
    environment: token.environment,
    scope: token.scope,
    tokenType: token.tokenType,
    expiresIn: token.expiresIn,
    accessTokenPresent: Boolean(token.accessToken),
  };
}
