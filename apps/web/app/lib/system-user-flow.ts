import {
  SystemUserAuthorityError,
  createSystemUserAuthorityClient,
  type QueriedSystemUser,
  type SystemUserAuthorityErrorCode,
  type SystemUserAuthorityResponse,
} from "./system-user-authority-client.ts";
import {
  SYSTEM_USER_RIGHT,
  SYSTEM_USER_SYSTEM_ID,
  assertSystemUserTransition,
  generateSystemUserExternalRef,
  type SystemUserRequestStatus,
} from "./system-user-requests.ts";
import {
  MaskinportenTokenError,
  productionMaskinportenCredentials,
  requestMaskinportenToken,
  type ProductionMaskinportenCredentials,
} from "./maskinporten.ts";

export const SYSTEM_USER_CONTROL_WRITE_SCOPE =
  "altinn:authentication/systemuser.request.write" as const;
export const SYSTEM_USER_CONTROL_READ_SCOPE =
  "altinn:authentication/systemuser.request.read" as const;
export const SYSTEM_USER_TAX_SCOPE =
  "skatteetaten:innrapporteringaksjonaerregisteroppgave" as const;

export const SYSTEM_USER_COOKIE = {
  name: "talli_system_user_request",
  options: {
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    path: "/auth/systembruker/confirm",
    maxAge: 3600,
  },
} as const;

export type SystemUserFailureCode =
  | SystemUserAuthorityErrorCode
  | "maskinporten_grant_signing_failed"
  | "maskinporten_network_error"
  | "maskinporten_http_error"
  | "maskinporten_response_invalid"
  | "maskinporten_token_error";

export type SystemUserRequestRecord = {
  id: string;
  companyId: string;
  ownerId: string;
  orgNumber: string;
  obligation: "aksjonaerregisteroppgaven";
  externalRef: string;
  altinnRequestId: string | null;
  status: SystemUserRequestStatus;
  confirmUrl: string | null;
  preflightVerifiedAt: string | null;
  failureCode: string | null;
};

export type SystemUserFlowResult = {
  requestId: string;
  companyId: string;
  status: SystemUserRequestStatus;
  preflightVerifiedAt: string | null;
  confirmUrl: string | null;
  failureCode: string | null;
};

export type SystemUserStartResult = SystemUserFlowResult & {
  cookie: {
    name: typeof SYSTEM_USER_COOKIE.name;
    value: string;
    options: typeof SYSTEM_USER_COOKIE.options;
  };
};

type OpaqueToken = { accessToken: string };

export type SystemUserFlowDependencies = {
  generateExternalRef?: () => string;
  verifyCallbackPrerequisite(): Promise<void>;
  beginRequest(input: {
    requestId: string;
    companyId: string;
    ownerId: string;
    externalRef: string;
  }): Promise<SystemUserRequestRecord>;
  requestControlPlaneToken(input: {
    scope: typeof SYSTEM_USER_CONTROL_READ_SCOPE | typeof SYSTEM_USER_CONTROL_WRITE_SCOPE;
  }): Promise<OpaqueToken>;
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
  recordAuthorityState(input: {
    requestId: string;
    companyId: string;
    altinnRequestId: string | null;
    externalRef: string;
    status: SystemUserRequestStatus;
    confirmUrl: string | null;
    failureCode: SystemUserFailureCode | null;
    operatorEvidenceId: null;
  }): Promise<SystemUserRequestRecord>;
  requestDelegatedTaxToken(input: {
    scope: typeof SYSTEM_USER_TAX_SCOPE;
    systemUserOrgNumber: string;
    systemUserExternalRef: string;
  }): Promise<OpaqueToken>;
  discardToken(token: OpaqueToken): void;
  verifyPreflight(input: {
    requestId: string;
    expectedExternalRef: string;
  }): Promise<SystemUserRequestRecord>;
};

export type SystemUserFlowErrorCode =
  | "callback_not_verified"
  | "invalid_system_user_request"
  | "system_user_relationship_mismatch"
  | "system_user_request_start_failed"
  | "system_user_request_recovery_pending";

export class SystemUserFlowError extends Error {
  readonly code: SystemUserFlowErrorCode;

  constructor(code: SystemUserFlowErrorCode) {
    super(code);
    this.name = "SystemUserFlowError";
    this.code = code;
  }
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const EXTERNAL_REF_PATTERN = /^[A-Za-z0-9_-]{43}$/u;
const ORG_NUMBER_PATTERN = /^\d{9}$/u;
const REQUEST_STATUSES = new Set<SystemUserRequestStatus>([
  "creating",
  "new",
  "accepted",
  "rejected",
  "denied",
  "timedout",
  "verification_failed",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function isVerifiedSystemUserCallbackOperation(value: unknown): boolean {
  if (!isRecord(value) || !isRecord(value.metadata)) return false;
  const metadataKeys = Object.keys(value.metadata).sort();
  return value.operation === "set_rf1086_systembruker_callback"
    && value.status === "succeeded"
    && (value.result_code === "callback_already_verified"
      || value.result_code === "callback_updated_and_verified")
    && metadataKeys.length === 2
    && metadataKeys[0] === "callbackPath"
    && metadataKeys[1] === "systemId"
    && value.metadata.systemId === SYSTEM_USER_SYSTEM_ID
    && value.metadata.callbackPath === SYSTEM_USER_COOKIE.options.path;
}

function assertStartInput(input: {
  companyId: string;
  requestId: string;
  ownerId: string;
  orgNumber: string;
}): void {
  if (
    !UUID_PATTERN.test(input.companyId)
    || !UUID_PATTERN.test(input.requestId)
    || !UUID_PATTERN.test(input.ownerId)
    || !ORG_NUMBER_PATTERN.test(input.orgNumber)
  ) {
    throw new SystemUserFlowError("invalid_system_user_request");
  }
}

function assertRequestRelationship(
  request: SystemUserRequestRecord,
  expected: Pick<SystemUserRequestRecord, "id" | "companyId" | "ownerId" | "orgNumber" | "externalRef">,
): void {
  if (
    request.id !== expected.id
    || request.companyId !== expected.companyId
    || request.ownerId !== expected.ownerId
    || request.orgNumber !== expected.orgNumber
    || request.externalRef !== expected.externalRef
    || request.obligation !== "aksjonaerregisteroppgaven"
    || !UUID_PATTERN.test(request.id)
    || !UUID_PATTERN.test(request.companyId)
    || !UUID_PATTERN.test(request.ownerId)
    || !ORG_NUMBER_PATTERN.test(request.orgNumber)
    || !EXTERNAL_REF_PATTERN.test(request.externalRef)
  ) {
    throw new SystemUserFlowError("system_user_relationship_mismatch");
  }
}

function assertAuthorityRelationship(
  response: SystemUserAuthorityResponse,
  request: SystemUserRequestRecord,
): void {
  const right = response.rights[0]?.resource[0];
  if (
    response.externalRef !== request.externalRef
    || response.partyOrgNo !== request.orgNumber
    || response.systemId !== SYSTEM_USER_SYSTEM_ID
    || response.redirectUrl !== "https://talli.no/auth/systembruker/confirm"
    || response.rights.length !== 1
    || response.rights[0]?.resource.length !== 1
    || right?.id !== "urn:altinn:resource"
    || right.value !== SYSTEM_USER_RIGHT
    || (request.altinnRequestId !== null && response.id !== request.altinnRequestId)
  ) {
    throw new SystemUserAuthorityError("response_contract_mismatch");
  }
}

function assertQueriedSystemUser(
  systemUser: QueriedSystemUser,
  request: SystemUserRequestRecord,
): void {
  if (
    systemUser.systemId !== SYSTEM_USER_SYSTEM_ID
    || systemUser.reporteeOrgNo !== request.orgNumber
    || systemUser.externalRef !== request.externalRef
    || systemUser.userType !== "standard"
    || systemUser.isDeleted
  ) {
    throw new SystemUserAuthorityError("response_contract_mismatch");
  }
}

function flowResult(request: SystemUserRequestRecord): SystemUserFlowResult {
  return {
    requestId: request.id,
    companyId: request.companyId,
    status: request.status,
    preflightVerifiedAt: request.preflightVerifiedAt,
    confirmUrl: request.confirmUrl,
    failureCode: request.failureCode,
  };
}

function startResult(request: SystemUserRequestRecord): SystemUserStartResult {
  return {
    ...flowResult(request),
    cookie: {
      name: SYSTEM_USER_COOKIE.name,
      value: request.id,
      options: SYSTEM_USER_COOKIE.options,
    },
  };
}

function authorityFailureCode(error: unknown): SystemUserFailureCode {
  if (error instanceof SystemUserAuthorityError) return error.code;
  if (error instanceof MaskinportenTokenError) {
    switch (error.code) {
      case "maskinporten_grant_signing_failed":
      case "maskinporten_network_error":
      case "maskinporten_response_invalid":
        return error.code;
      default:
        return error.status === null ? "maskinporten_token_error" : "maskinporten_http_error";
    }
  }
  return "response_contract_mismatch";
}

function preflightFailureCode(error: unknown): SystemUserFailureCode {
  if (error instanceof SystemUserAuthorityError) return error.code;
  if (error instanceof MaskinportenTokenError) return authorityFailureCode(error);
  if (
    error !== null
    && typeof error === "object"
    && "status" in error
    && typeof error.status === "number"
  ) {
    return "maskinporten_http_error";
  }
  return "maskinporten_token_error";
}

function isAmbiguousCreate(error: unknown): boolean {
  return error instanceof SystemUserAuthorityError
    && (error.code === "duplicate_system_user_request" || error.code === "network_error" || error.retryable);
}

function isIndependentAbsence(error: unknown): boolean {
  return error instanceof SystemUserAuthorityError
    && error.code === "authority_http_error"
    && error.status === 404;
}

async function persistAuthorityResponse(
  dependencies: SystemUserFlowDependencies,
  request: SystemUserRequestRecord,
  response: SystemUserAuthorityResponse,
): Promise<SystemUserRequestRecord> {
  assertAuthorityRelationship(response, request);
  assertSystemUserTransition(request.status, response.status);
  const recorded = await dependencies.recordAuthorityState({
    requestId: request.id,
    companyId: request.companyId,
    altinnRequestId: response.id,
    externalRef: request.externalRef,
    status: response.status,
    confirmUrl: response.confirmUrl,
    failureCode: null,
    operatorEvidenceId: null,
  });
  assertRequestRelationship(recorded, request);
  if (recorded.status !== response.status || recorded.altinnRequestId !== response.id) {
    throw new SystemUserFlowError("system_user_relationship_mismatch");
  }
  return recorded;
}

async function persistFailure(
  dependencies: SystemUserFlowDependencies,
  request: SystemUserRequestRecord,
  failureCode: SystemUserFailureCode,
): Promise<SystemUserRequestRecord> {
  assertSystemUserTransition(request.status, "verification_failed");
  const recorded = await dependencies.recordAuthorityState({
    requestId: request.id,
    companyId: request.companyId,
    altinnRequestId: request.altinnRequestId,
    externalRef: request.externalRef,
    status: "verification_failed",
    confirmUrl: request.confirmUrl,
    failureCode,
    operatorEvidenceId: null,
  });
  assertRequestRelationship(recorded, request);
  if (recorded.status !== "verification_failed" || recorded.failureCode !== failureCode) {
    throw new SystemUserFlowError("system_user_relationship_mismatch");
  }
  return recorded;
}

function recoveryPending(): never {
  throw new SystemUserFlowError("system_user_request_recovery_pending");
}

async function persistFailureOrRecovery(
  dependencies: SystemUserFlowDependencies,
  request: SystemUserRequestRecord,
  failureCode: SystemUserFailureCode,
): Promise<SystemUserRequestRecord> {
  try {
    return await persistFailure(dependencies, request, failureCode);
  } catch {
    return recoveryPending();
  }
}

async function persistCreatedResponse(
  dependencies: SystemUserFlowDependencies,
  request: SystemUserRequestRecord,
  response: SystemUserAuthorityResponse,
): Promise<SystemUserRequestRecord> {
  try {
    if (response.status !== "new") {
      throw new SystemUserAuthorityError("response_contract_mismatch");
    }
    assertAuthorityRelationship(response, request);
    assertSystemUserTransition(request.status, response.status);
  } catch (error) {
    return persistFailureOrRecovery(dependencies, request, authorityFailureCode(error));
  }

  try {
    return await persistAuthorityResponse(dependencies, request, response);
  } catch {
    return recoveryPending();
  }
}

async function persistRecoveredResponse(
  dependencies: SystemUserFlowDependencies,
  request: SystemUserRequestRecord,
  response: SystemUserAuthorityResponse,
): Promise<SystemUserRequestRecord> {
  try {
    assertAuthorityRelationship(response, request);
    assertSystemUserTransition(request.status, response.status);
  } catch (error) {
    return persistFailureOrRecovery(dependencies, request, authorityFailureCode(error));
  }

  try {
    return await persistAuthorityResponse(dependencies, request, response);
  } catch {
    return recoveryPending();
  }
}

async function recoverCreatingRequest(
  dependencies: SystemUserFlowDependencies,
  request: SystemUserRequestRecord,
  allowCreateIfAbsent: boolean,
): Promise<SystemUserRequestRecord> {
  let readToken: OpaqueToken;
  try {
    readToken = await dependencies.requestControlPlaneToken({
      scope: SYSTEM_USER_CONTROL_READ_SCOPE,
    });
  } catch {
    return recoveryPending();
  }
  let recovered: SystemUserAuthorityResponse | null = null;
  try {
    recovered = await dependencies.getRequestByExternalRef({
      bearerToken: readToken.accessToken,
      partyOrgNo: request.orgNumber,
      externalRef: request.externalRef,
    });
  } catch (error) {
    if (
      error instanceof SystemUserAuthorityError
      && error.code === "response_contract_mismatch"
    ) {
      return persistFailureOrRecovery(dependencies, request, error.code);
    }
    if (!isIndependentAbsence(error) || !allowCreateIfAbsent) {
      return recoveryPending();
    }
  }
  if (recovered) {
    return persistRecoveredResponse(dependencies, request, recovered);
  }

  try {
    await dependencies.verifyCallbackPrerequisite();
  } catch {
    throw new SystemUserFlowError("callback_not_verified");
  }
  let writeToken: OpaqueToken;
  try {
    writeToken = await dependencies.requestControlPlaneToken({
      scope: SYSTEM_USER_CONTROL_WRITE_SCOPE,
    });
  } catch {
    return recoveryPending();
  }

  let created: SystemUserAuthorityResponse;
  try {
    created = await dependencies.createRequest({
      bearerToken: writeToken.accessToken,
      partyOrgNo: request.orgNumber,
      externalRef: request.externalRef,
    });
  } catch (error) {
    if (isAmbiguousCreate(error)) {
      return recoveryPending();
    }
    return persistFailureOrRecovery(dependencies, request, authorityFailureCode(error));
  }
  return persistCreatedResponse(dependencies, request, created);
}

export async function startSystemUserRequest(
  dependencies: SystemUserFlowDependencies,
  input: { companyId: string; requestId: string; ownerId: string; orgNumber: string },
): Promise<SystemUserStartResult> {
  assertStartInput(input);
  try {
    await dependencies.verifyCallbackPrerequisite();
  } catch {
    throw new SystemUserFlowError("callback_not_verified");
  }

  const externalRef = (dependencies.generateExternalRef ?? generateSystemUserExternalRef)();
  if (!EXTERNAL_REF_PATTERN.test(externalRef)) {
    throw new SystemUserFlowError("invalid_system_user_request");
  }

  let request: SystemUserRequestRecord;
  try {
    request = await dependencies.beginRequest({
      requestId: input.requestId,
      companyId: input.companyId,
      ownerId: input.ownerId,
      externalRef,
    });
  } catch {
    throw new SystemUserFlowError("system_user_request_start_failed");
  }
  assertRequestRelationship(request, { ...input, id: input.requestId, externalRef });
  if (request.status !== "creating" || request.altinnRequestId !== null) {
    throw new SystemUserFlowError("system_user_relationship_mismatch");
  }

  let token: OpaqueToken;
  try {
    token = await dependencies.requestControlPlaneToken({
      scope: SYSTEM_USER_CONTROL_WRITE_SCOPE,
    });
  } catch {
    return recoveryPending();
  }

  let response: SystemUserAuthorityResponse;
  try {
    response = await dependencies.createRequest({
      bearerToken: token.accessToken,
      partyOrgNo: request.orgNumber,
      externalRef: request.externalRef,
    });
  } catch (error) {
    if (isAmbiguousCreate(error)) {
      try {
        return startResult(await recoverCreatingRequest(dependencies, request, false));
      } catch (recoveryError) {
        if (recoveryError instanceof SystemUserFlowError) throw recoveryError;
        return recoveryPending();
      }
    }
    return startResult(await persistFailureOrRecovery(
      dependencies,
      request,
      authorityFailureCode(error),
    ));
  }
  return startResult(await persistCreatedResponse(dependencies, request, response));
}

export async function retrySystemUserRequest(
  dependencies: SystemUserFlowDependencies,
  request: SystemUserRequestRecord,
): Promise<SystemUserFlowResult> {
  assertRequestRelationship(request, request);
  if (request.status !== "creating") {
    return reconcileSystemUserRequest(dependencies, request);
  }
  return flowResult(await recoverCreatingRequest(dependencies, request, true));
}

export async function reconcileSystemUserRequest(
  dependencies: SystemUserFlowDependencies,
  request: SystemUserRequestRecord,
): Promise<SystemUserFlowResult> {
  assertRequestRelationship(request, request);
  const readToken = await dependencies.requestControlPlaneToken({
    scope: SYSTEM_USER_CONTROL_READ_SCOPE,
  });
  const response = request.altinnRequestId === null
    ? await dependencies.getRequestByExternalRef({
        bearerToken: readToken.accessToken,
        partyOrgNo: request.orgNumber,
        externalRef: request.externalRef,
      })
    : await dependencies.getRequest({
        bearerToken: readToken.accessToken,
        requestId: request.altinnRequestId,
        partyOrgNo: request.orgNumber,
        externalRef: request.externalRef,
      });
  assertAuthorityRelationship(response, request);

  if (response.status !== "accepted") {
    return flowResult(await persistAuthorityResponse(dependencies, request, response));
  }

  let current = request;
  try {
    const queryToken = await dependencies.requestControlPlaneToken({
      scope: SYSTEM_USER_CONTROL_WRITE_SCOPE,
    });
    const systemUser = await dependencies.querySystemUser({
      bearerToken: queryToken.accessToken,
      partyOrgNo: request.orgNumber,
      externalRef: request.externalRef,
    });
    assertQueriedSystemUser(systemUser, request);
    current = await persistAuthorityResponse(dependencies, request, response);
    if (current.preflightVerifiedAt !== null) return flowResult(current);

    let delegatedToken: OpaqueToken | null = null;
    try {
      delegatedToken = await dependencies.requestDelegatedTaxToken({
        scope: SYSTEM_USER_TAX_SCOPE,
        systemUserOrgNumber: request.orgNumber,
        systemUserExternalRef: request.externalRef,
      });
    } finally {
      if (delegatedToken) dependencies.discardToken(delegatedToken);
    }
    const verified = await dependencies.verifyPreflight({
      requestId: request.id,
      expectedExternalRef: request.externalRef,
    });
    assertRequestRelationship(verified, request);
    if (verified.status !== "accepted" || verified.preflightVerifiedAt === null) {
      throw new SystemUserAuthorityError("response_contract_mismatch");
    }
    return flowResult(verified);
  } catch (error) {
    const failureCode = current.status === "accepted"
      ? preflightFailureCode(error)
      : error instanceof SystemUserAuthorityError
        ? error.code
        : preflightFailureCode(error);
    return flowResult(await persistFailure(dependencies, current, failureCode));
  }
}

export type SystemUserCallbackState =
  | "pending"
  | "verifying"
  | "connected"
  | "rejected"
  | "denied"
  | "timedout"
  | "manual";

export function callbackStateForResult(result: SystemUserFlowResult): SystemUserCallbackState {
  switch (result.status) {
    case "creating":
    case "new":
      return "pending";
    case "accepted":
      return result.preflightVerifiedAt === null ? "verifying" : "connected";
    case "rejected":
      return "rejected";
    case "denied":
      return "denied";
    case "timedout":
      return "timedout";
    case "verification_failed":
      return "manual";
  }
}

type SupabaseFlowClient = {
  rpc(name: string, parameters: Record<string, unknown>): Promise<{
    data: unknown;
    error: unknown;
  }>;
  from(table: string): any;
};

type RequestToken = typeof requestMaskinportenToken;

export function systemUserRequestRecordFromRow(
  value: unknown,
  orgNumber: string,
): SystemUserRequestRecord {
  if (
    !isRecord(value)
    || typeof value.id !== "string"
    || typeof value.company_id !== "string"
    || typeof value.initiating_owner_user_id !== "string"
    || value.obligation !== "aksjonaerregisteroppgaven"
    || typeof value.external_ref !== "string"
    || (value.altinn_request_id !== null && typeof value.altinn_request_id !== "string")
    || typeof value.status !== "string"
    || !REQUEST_STATUSES.has(value.status as SystemUserRequestStatus)
    || (value.confirm_url !== null && typeof value.confirm_url !== "string")
    || (value.preflight_verified_at !== null && typeof value.preflight_verified_at !== "string")
    || (value.failure_code !== null && typeof value.failure_code !== "string")
  ) {
    throw new SystemUserFlowError("invalid_system_user_request");
  }
  const request: SystemUserRequestRecord = {
    id: value.id,
    companyId: value.company_id,
    ownerId: value.initiating_owner_user_id,
    orgNumber,
    obligation: "aksjonaerregisteroppgaven",
    externalRef: value.external_ref,
    altinnRequestId: value.altinn_request_id as string | null,
    status: value.status as SystemUserRequestStatus,
    confirmUrl: value.confirm_url as string | null,
    preflightVerifiedAt: value.preflight_verified_at as string | null,
    failureCode: value.failure_code as string | null,
  };
  assertRequestRelationship(request, request);
  return request;
}

export function createProductionSystemUserFlowDependencies(input: {
  ownerClient: SupabaseFlowClient;
  serviceClient: SupabaseFlowClient;
  orgNumber: string;
  credentials?: ProductionMaskinportenCredentials;
  requestToken?: RequestToken;
  authorityClient?: ReturnType<typeof createSystemUserAuthorityClient>;
}): SystemUserFlowDependencies {
  if (!ORG_NUMBER_PATTERN.test(input.orgNumber)) {
    throw new SystemUserFlowError("invalid_system_user_request");
  }
  const credentials = input.credentials ?? productionMaskinportenCredentials();
  const tokenRequest = input.requestToken ?? requestMaskinportenToken;
  const authorityClient = input.authorityClient ?? createSystemUserAuthorityClient({
    environment: "production",
  });

  async function rpc(
    client: SupabaseFlowClient,
    name: string,
    parameters: Record<string, unknown>,
  ): Promise<SystemUserRequestRecord> {
    const { data, error } = await client.rpc(name, parameters);
    if (error || !data) throw new SystemUserAuthorityError("response_contract_mismatch");
    return systemUserRequestRecordFromRow(data, input.orgNumber);
  }

  return {
    async verifyCallbackPrerequisite() {
      const { data, error } = await input.serviceClient
        .from("authority_operations")
        .select("operation,status,result_code,metadata,created_at")
        .eq("operation", "set_rf1086_systembruker_callback")
        .order("created_at", { ascending: false })
        .limit(1)
        .maybeSingle();
      if (error || !isVerifiedSystemUserCallbackOperation(data)) {
        throw new SystemUserFlowError("callback_not_verified");
      }
    },

    async beginRequest(beginInput) {
      return rpc(input.ownerClient, "begin_system_user_request", {
        p_id: beginInput.requestId,
        p_company_id: beginInput.companyId,
        p_external_ref: beginInput.externalRef,
      });
    },

    async requestControlPlaneToken(tokenInput) {
      return tokenRequest({
        ...credentials,
        scope: tokenInput.scope,
      });
    },

    createRequest: (requestInput) => authorityClient.createRequest(requestInput),
    getRequest: (requestInput) => authorityClient.getRequest(requestInput),
    getRequestByExternalRef: (requestInput) => authorityClient.getRequestByExternalRef(requestInput),
    querySystemUser: (requestInput) => authorityClient.querySystemUser(requestInput),

    async recordAuthorityState(stateInput) {
      return rpc(input.serviceClient, "record_system_user_authority_state", {
        p_request_id: stateInput.requestId,
        p_company_id: stateInput.companyId,
        p_altinn_request_id: stateInput.altinnRequestId,
        p_external_ref: stateInput.externalRef,
        p_status: stateInput.status,
        p_confirm_url: stateInput.confirmUrl,
        p_failure_code: stateInput.failureCode,
        p_operator_evidence_id: null,
      });
    },

    async requestDelegatedTaxToken(tokenInput) {
      return tokenRequest({
        ...credentials,
        scope: tokenInput.scope,
        systemUserOrgNumber: tokenInput.systemUserOrgNumber,
        systemUserExternalRef: tokenInput.systemUserExternalRef,
      });
    },

    discardToken(token) {
      token.accessToken = "";
    },

    async verifyPreflight(preflightInput) {
      return rpc(input.serviceClient, "verify_system_user_preflight", {
        p_request_id: preflightInput.requestId,
        p_expected_external_ref: preflightInput.expectedExternalRef,
      });
    },
  };
}
