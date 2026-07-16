import assert from "node:assert/strict";
import test from "node:test";

import {
  SYSTEM_USER_CONTROL_READ_SCOPE,
  SYSTEM_USER_CONTROL_WRITE_SCOPE,
  SYSTEM_USER_COOKIE,
  SYSTEM_USER_TAX_SCOPE,
  SystemUserFlowError,
  createProductionSystemUserFlowDependencies,
  isVerifiedSystemUserCallbackOperation,
  reconcileSystemUserRequest,
  retrySystemUserRequest,
  startSystemUserRequest,
} from "../app/lib/system-user-flow.ts";
import { SystemUserAuthorityError } from "../app/lib/system-user-authority-client.ts";

const companyId = "12345678-1234-4234-8234-123456789abc";
const requestId = "22345678-1234-4234-8234-123456789abc";
const ownerId = "32345678-1234-4234-8234-123456789abc";
const altinnRequestId = "42345678-1234-4234-8234-123456789abc";
const systemUserId = "52345678-1234-4234-8234-123456789abc";
const orgNumber = "310279617";
const externalRef = "A".repeat(43);
const confirmUrl = `https://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id=${altinnRequestId}`;

function requestRow(status = "creating", overrides = {}) {
  return {
    id: requestId,
    companyId,
    ownerId,
    orgNumber,
    obligation: "aksjonaerregisteroppgaven",
    externalRef,
    altinnRequestId: status === "creating" ? null : altinnRequestId,
    status,
    confirmUrl: status === "new" ? confirmUrl : null,
    preflightVerifiedAt: null,
    failureCode: null,
    ...overrides,
  };
}

function authorityResponse(status = "new") {
  return {
    id: altinnRequestId,
    externalRef,
    systemId: "930835978_talli",
    partyOrgNo: orgNumber,
    rights: [{ resource: [{ id: "urn:altinn:resource", value: "ske-innrapportering-aksjonaerregisteroppgave" }] }],
    status,
    redirectUrl: "https://talli.no/auth/systembruker/confirm",
    confirmUrl: status === "new" ? confirmUrl : null,
  };
}

function dependencies(overrides = {}) {
  const events = [];
  const deps = {
    generateExternalRef: () => externalRef,
    async verifyCallbackPrerequisite() {
      events.push({ kind: "callback_verified" });
    },
    async beginRequest(input) {
      events.push({ kind: "begin", input });
      return requestRow("creating");
    },
    async requestControlPlaneToken(input) {
      events.push({ kind: input.scope === SYSTEM_USER_CONTROL_WRITE_SCOPE ? "write_token" : "read_token", input });
      return { accessToken: input.scope === SYSTEM_USER_CONTROL_WRITE_SCOPE ? "write-secret" : "read-secret" };
    },
    async createRequest(input) {
      events.push({ kind: "create", input });
      return authorityResponse("new");
    },
    async getRequest(input) {
      events.push({ kind: "get_request", input });
      return authorityResponse("accepted");
    },
    async getRequestByExternalRef(input) {
      events.push({ kind: "lookup_by_external_ref", input });
      return authorityResponse("new");
    },
    async querySystemUser(input) {
      events.push({ kind: "query_system_user", input });
      return {
        id: systemUserId,
        systemId: "930835978_talli",
        reporteeOrgNo: orgNumber,
        externalRef,
        userType: "standard",
        isDeleted: false,
      };
    },
    async recordAuthorityState(input) {
      events.push({ kind: `record_${input.status}`, input });
      return requestRow(input.status, {
        altinnRequestId: input.altinnRequestId,
        confirmUrl: input.confirmUrl,
        failureCode: input.failureCode,
      });
    },
    async requestDelegatedTaxToken(input) {
      events.push({ kind: "delegated_tax_token", input });
      return { accessToken: "delegated-secret" };
    },
    discardToken(token) {
      events.push({ kind: "discard_token", tokenPresent: Boolean(token?.accessToken) });
    },
    async verifyPreflight(input) {
      events.push({ kind: "verify_preflight", input });
      return requestRow("accepted", {
        altinnRequestId,
        preflightVerifiedAt: "2026-07-16T12:00:00.000Z",
      });
    },
    ...overrides,
  };
  return { deps, events };
}

test("callback prerequisite accepts only an exact latest succeeded audit projection", () => {
  const exact = {
    operation: "set_rf1086_systembruker_callback",
    status: "succeeded",
    result_code: "callback_updated_and_verified",
    metadata: {
      systemId: "930835978_talli",
      callbackPath: "/auth/systembruker/confirm",
    },
  };
  assert.equal(isVerifiedSystemUserCallbackOperation(exact), true);
  assert.equal(isVerifiedSystemUserCallbackOperation({
    ...exact,
    result_code: "callback_already_verified",
  }), true);
  for (const invalid of [
    null,
    { ...exact, status: "failed" },
    { ...exact, result_code: "created_and_verified" },
    { ...exact, metadata: { ...exact.metadata, systemId: "other" } },
    { ...exact, metadata: { ...exact.metadata, callbackPath: "/attacker" } },
    { ...exact, metadata: { ...exact.metadata, extra: "field" } },
  ]) {
    assert.equal(isVerifiedSystemUserCallbackOperation(invalid), false);
  }
});

test("production dependencies prove the latest callback audit and add RAR only to the delegated scope", async () => {
  const auditCalls = [];
  const tokenCalls = [];
  const auditRow = {
    operation: "set_rf1086_systembruker_callback",
    status: "succeeded",
    result_code: "callback_already_verified",
    metadata: {
      systemId: "930835978_talli",
      callbackPath: "/auth/systembruker/confirm",
    },
  };
  const serviceClient = {
    from(table) {
      const builder = {
        select(columns) { auditCalls.push(["select", table, columns]); return builder; },
        eq(column, value) { auditCalls.push(["eq", column, value]); return builder; },
        order(column, options) { auditCalls.push(["order", column, options]); return builder; },
        limit(value) { auditCalls.push(["limit", value]); return builder; },
        async maybeSingle() { return { data: auditRow, error: null }; },
      };
      return builder;
    },
    async rpc() { throw new Error("unused"); },
  };
  const credentials = {
    environment: "production",
    clientId: companyId,
    keyId: requestId,
    privateKeyPem: "injected-only",
  };
  const deps = createProductionSystemUserFlowDependencies({
    ownerClient: serviceClient,
    serviceClient,
    orgNumber,
    credentials,
    async requestToken(input) {
      tokenCalls.push(input);
      return { accessToken: "opaque", tokenType: "Bearer", expiresIn: 600, scope: input.scope, environment: "production" };
    },
    authorityClient: {},
  });

  await deps.verifyCallbackPrerequisite();
  await deps.requestControlPlaneToken({ scope: SYSTEM_USER_CONTROL_WRITE_SCOPE });
  await deps.requestControlPlaneToken({ scope: SYSTEM_USER_CONTROL_READ_SCOPE });
  await deps.requestDelegatedTaxToken({
    scope: SYSTEM_USER_TAX_SCOPE,
    systemUserOrgNumber: orgNumber,
    systemUserExternalRef: externalRef,
  });

  assert.deepEqual(auditCalls, [
    ["select", "authority_operations", "operation,status,result_code,metadata,created_at"],
    ["eq", "operation", "set_rf1086_systembruker_callback"],
    ["order", "created_at", { ascending: false }],
    ["limit", 1],
  ]);
  assert.equal("systemUserOrgNumber" in tokenCalls[0], false);
  assert.equal("systemUserExternalRef" in tokenCalls[0], false);
  assert.equal("systemUserOrgNumber" in tokenCalls[1], false);
  assert.equal("systemUserExternalRef" in tokenCalls[1], false);
  assert.deepEqual(tokenCalls.map((call) => call.scope), [
    SYSTEM_USER_CONTROL_WRITE_SCOPE,
    SYSTEM_USER_CONTROL_READ_SCOPE,
    SYSTEM_USER_TAX_SCOPE,
  ]);
  assert.equal(tokenCalls[2].systemUserOrgNumber, orgNumber);
  assert.equal(tokenCalls[2].systemUserExternalRef, externalRef);
});

test("start proves the fixed callback audit before durably recording creating and making one POST", async () => {
  const { deps, events } = dependencies();

  const result = await startSystemUserRequest(deps, {
    companyId,
    requestId,
    ownerId,
    orgNumber,
  });

  assert.deepEqual(events.map((event) => event.kind), [
    "callback_verified",
    "begin",
    "write_token",
    "create",
    "record_new",
  ]);
  assert.deepEqual(events.find((event) => event.kind === "write_token").input, {
    scope: SYSTEM_USER_CONTROL_WRITE_SCOPE,
  });
  assert.equal(events.filter((event) => event.kind === "create").length, 1);
  assert.equal(result.requestId, requestId);
  assert.equal(result.confirmUrl, confirmUrl);
  assert.deepEqual(result.cookie, { name: SYSTEM_USER_COOKIE.name, value: requestId, options: SYSTEM_USER_COOKIE.options });
  assert.doesNotMatch(JSON.stringify(result), /write-secret|delegated-secret|310279617|A{43}/u);
});

test("start accepts only the documented new response before exposing a confirmation URL", async () => {
  const { deps, events } = dependencies({
    async createRequest(input) {
      events.push({ kind: "create", input });
      return authorityResponse("accepted");
    },
  });

  const result = await startSystemUserRequest(deps, { companyId, requestId, ownerId, orgNumber });

  assert.equal(result.status, "verification_failed");
  assert.equal(result.confirmUrl, null);
  assert.equal(events.filter((event) => event.kind === "create").length, 1);
  assert.equal(events.some((event) => event.kind === "record_accepted"), false);
  assert.equal(events.at(-1).kind, "record_verification_failed");
});

test("start fails closed before persistence, token, or network when callback evidence is absent", async () => {
  const { deps, events } = dependencies({
    async verifyCallbackPrerequisite() {
      events.push({ kind: "callback_blocked" });
      throw new Error("raw database detail");
    },
  });

  await assert.rejects(
    () => startSystemUserRequest(deps, { companyId, requestId, ownerId, orgNumber }),
    (error) => error instanceof SystemUserFlowError
      && error.code === "callback_not_verified"
      && !error.message.includes("raw database detail"),
  );
  assert.deepEqual(events.map((event) => event.kind), ["callback_blocked"]);
});

test("ambiguous create recovers by the same externalRef without a second POST", async () => {
  let creates = 0;
  const { deps, events } = dependencies({
    async createRequest(input) {
      creates += 1;
      events.push({ kind: "create", input });
      throw new SystemUserAuthorityError("network_error", { retryable: true });
    },
  });

  const result = await startSystemUserRequest(deps, { companyId, requestId, ownerId, orgNumber });

  assert.equal(creates, 1);
  assert.deepEqual(events.map((event) => event.kind), [
    "callback_verified",
    "begin",
    "write_token",
    "create",
    "read_token",
    "lookup_by_external_ref",
    "record_new",
  ]);
  assert.equal(events.find((event) => event.kind === "lookup_by_external_ref").input.externalRef, externalRef);
  assert.equal(result.status, "new");
});

test("retry of creating looks up first and creates the same reference only when independently absent", async () => {
  let lookups = 0;
  let creates = 0;
  const { deps, events } = dependencies({
    async getRequestByExternalRef(input) {
      lookups += 1;
      events.push({ kind: "lookup_by_external_ref", input });
      throw new SystemUserAuthorityError("authority_http_error", { status: 404 });
    },
    async createRequest(input) {
      creates += 1;
      events.push({ kind: "create", input });
      return authorityResponse("new");
    },
  });

  const result = await retrySystemUserRequest(deps, requestRow("creating"));

  assert.equal(lookups, 1);
  assert.equal(creates, 1);
  assert.deepEqual(events.map((event) => event.kind), [
    "read_token",
    "lookup_by_external_ref",
    "callback_verified",
    "write_token",
    "create",
    "record_new",
  ]);
  assert.equal(events.find((event) => event.kind === "create").input.externalRef, externalRef);
  assert.equal(result.status, "new");
});

test("accepted reconciliation uses read scope for status, write scope for byquery, then exact delegated preflight", async () => {
  const { deps, events } = dependencies();

  const result = await reconcileSystemUserRequest(deps, requestRow("new", { confirmUrl }));

  assert.deepEqual(events.map((event) => event.kind), [
    "read_token",
    "get_request",
    "write_token",
    "query_system_user",
    "record_accepted",
    "delegated_tax_token",
    "discard_token",
    "verify_preflight",
  ]);
  assert.deepEqual(events.find((event) => event.kind === "read_token").input, {
    scope: SYSTEM_USER_CONTROL_READ_SCOPE,
  });
  assert.deepEqual(events.find((event) => event.kind === "write_token").input, {
    scope: SYSTEM_USER_CONTROL_WRITE_SCOPE,
  });
  assert.deepEqual(events.find((event) => event.kind === "delegated_tax_token").input, {
    scope: SYSTEM_USER_TAX_SCOPE,
    systemUserOrgNumber: orgNumber,
    systemUserExternalRef: externalRef,
  });
  assert.equal(result.status, "accepted");
  assert.equal(result.preflightVerifiedAt, "2026-07-16T12:00:00.000Z");
  assert.doesNotMatch(JSON.stringify(result), /read-secret|write-secret|delegated-secret/u);
});

test("mismatched or deleted resulting Systembruker blocks preflight and records only a safe failure", async () => {
  const { deps, events } = dependencies({
    async querySystemUser(input) {
      events.push({ kind: "query_system_user", input });
      return {
        id: systemUserId,
        systemId: "930835978_talli",
        reporteeOrgNo: "999999999",
        externalRef,
        userType: "standard",
        isDeleted: true,
      };
    },
  });

  const result = await reconcileSystemUserRequest(deps, requestRow("new", { confirmUrl }));

  assert.equal(result.status, "verification_failed");
  assert.equal(result.failureCode, "response_contract_mismatch");
  assert.deepEqual(events.map((event) => event.kind), [
    "read_token",
    "get_request",
    "write_token",
    "query_system_user",
    "record_verification_failed",
  ]);
  const persisted = events.at(-1).input;
  assert.deepEqual(persisted.failureCode, "response_contract_mismatch");
  assert.doesNotMatch(JSON.stringify(persisted), /999999999|raw|secret/u);
});

test("delegated preflight failures discard any token and persist an allowlisted Maskinporten code", async () => {
  const { deps, events } = dependencies({
    async requestDelegatedTaxToken(input) {
      events.push({ kind: "delegated_tax_token", input });
      const error = new Error("remote response with organization and key");
      error.code = "invalid_scope_from_provider";
      error.status = 400;
      throw error;
    },
  });

  const result = await reconcileSystemUserRequest(deps, requestRow("new", { confirmUrl }));

  assert.equal(result.status, "verification_failed");
  assert.equal(result.failureCode, "maskinporten_http_error");
  assert.equal(events.some((event) => event.kind === "verify_preflight"), false);
  assert.doesNotMatch(JSON.stringify(events.at(-1)), /invalid_scope_from_provider|organization and key/u);
});
