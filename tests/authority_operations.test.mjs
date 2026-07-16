import assert from "node:assert/strict";
import test from "node:test";

import {
  AuthorityOperationError,
  SYSTEMBRUKER_CALLBACK_CONFIRMATION,
  SYSTEMBRUKER_CALLBACK_OPERATION,
  authorityOperationEnvironmentFailureCode,
  assertAuthorityOperationIntent,
  assertSystembrukerCallbackOperationIntent,
  authorityOperationRequestHash,
  buildRf1086SystemDefinition,
  buildRf1086SystembrukerCallbackDefinition,
  executeRf1086SystemRegistration,
  executeRf1086SystembrukerCallbackUpdate,
  productionAuthorityOperationEnvironment,
} from "../app/lib/authority-operations.ts";

const productionEnvironment = {
  TALLI_AUTHORITY_OPS_ENABLED: "true",
  TALLI_PROD_MASKINPORTEN_CLIENT_ID: "4a42d9fe-9759-4d4e-a07a-84ebc80a5a1b",
  TALLI_PROD_MASKINPORTEN_KEY_ID: "93fea8a9-4435-4fdc-84fc-775803714c53",
  TALLI_PROD_MASKINPORTEN_PRIVATE_KEY_PEM:
    "-----BEGIN PRIVATE KEY-----\nZmFrZS1wcm9kdWN0aW9uLWtleQ==\n-----END PRIVATE KEY-----",
};

function environment() {
  const result = productionAuthorityOperationEnvironment(productionEnvironment);
  assert.ok(result);
  return result;
}

function token(accessToken = "opaque-secret-token") {
  return {
    accessToken,
    tokenType: "Bearer",
    expiresIn: 119,
    scope: "altinn:authentication/systemregister.write",
    environment: "production",
  };
}

function jsonResponse(value, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function exactCallbackDefinition(callbacks = []) {
  const definition = buildRf1086SystemDefinition(
    productionEnvironment.TALLI_PROD_MASKINPORTEN_CLIENT_ID,
  );
  const { allowedredirecturls: _allowedRedirectUrls, ...fixedDefinition } = definition;
  return {
    ...fixedDefinition,
    vendor: { ID: definition.vendor.ID },
    allowedRedirectUrls: callbacks,
    isDeleted: false,
  };
}

function callbackDependencies(responses, requests) {
  return {
    requestToken: async () => token(),
    fetch: async (url, init) => {
      requests.push({ url: String(url), ...init });
      const response = responses.shift();
      assert.ok(response, "unexpected authority request");
      return response;
    },
  };
}

test("authority operation environment fails closed and rejects test credentials", () => {
  assert.equal(productionAuthorityOperationEnvironment({}), null);
  assert.equal(
    productionAuthorityOperationEnvironment({
      ...productionEnvironment,
      TALLI_AUTHORITY_OPS_ENABLED: "TRUE",
    }),
    null,
  );
  assert.throws(
    () =>
      productionAuthorityOperationEnvironment({
        ...productionEnvironment,
        TALLI_PROD_MASKINPORTEN_CLIENT_ID: "tt02-client",
      }),
    /must not reference test/i,
  );
});

test("authority environment accepts the proven RSA PEM shape used by production filing", () => {
  const rsaPem =
    "-----BEGIN RSA PRIVATE KEY-----\nZmFrZS1wcm9kdWN0aW9uLXJzYS1rZXk=\n-----END RSA PRIVATE KEY-----\n";
  const result = productionAuthorityOperationEnvironment({
    ...productionEnvironment,
    TALLI_PROD_MASKINPORTEN_PRIVATE_KEY_PEM: rsaPem,
  });

  assert.ok(result);
  assert.equal(result.privateKeyPem, rsaPem);
});

test("environment diagnostics expose only the invalid field", () => {
  assert.equal(
    authorityOperationEnvironmentFailureCode(
      new AuthorityOperationError("authority_client_id_invalid"),
    ),
    "authority_client_id_invalid",
  );
  assert.equal(
    authorityOperationEnvironmentFailureCode(
      new AuthorityOperationError("authority_key_id must not reference test"),
    ),
    "authority_key_id_invalid",
  );
  assert.equal(
    authorityOperationEnvironmentFailureCode(
      new AuthorityOperationError("authority_private_key_invalid"),
    ),
    "authority_private_key_invalid",
  );
  assert.equal(
    authorityOperationEnvironmentFailureCode(new Error("secret detail")),
    "authority_environment_invalid",
  );
});

test("builds the one fixed RF-1086 own-system definition", () => {
  const definition = buildRf1086SystemDefinition(
    productionEnvironment.TALLI_PROD_MASKINPORTEN_CLIENT_ID,
  );
  assert.equal(definition.id, "930835978_talli");
  assert.deepEqual(definition.vendor, {
    authority: "iso6523-actorid-upis",
    ID: "0192:930835978",
  });
  assert.deepEqual(definition.rights, [
    {
      resource: [
        { id: "urn:altinn:resource", value: "ske-innrapportering-aksjonaerregisteroppgave" },
      ],
    },
  ]);
  assert.deepEqual(definition.accessPackages, []);
  assert.deepEqual(definition.clientId, [productionEnvironment.TALLI_PROD_MASKINPORTEN_CLIENT_ID]);
  assert.deepEqual(definition.allowedredirecturls, []);
  assert.equal(definition.isVisible, true);
  assert.match(authorityOperationRequestHash(definition), /^[a-f0-9]{64}$/u);
});

test("requires the exact immutable operation and confirmation phrase", () => {
  assert.doesNotThrow(() =>
    assertAuthorityOperationIntent({
      operation: "register_rf1086_system",
      confirmation: "REGISTER TALLI RF1086 SYSTEM",
    }),
  );
  for (const input of [
    { operation: "register_other_system", confirmation: "REGISTER TALLI RF1086 SYSTEM" },
    { operation: "register_rf1086_system", confirmation: "register talli rf1086 system" },
    { operation: "register_rf1086_system", confirmation: " REGISTER TALLI RF1086 SYSTEM" },
  ]) {
    assert.throws(() => assertAuthorityOperationIntent(input), /authority_operation_invalid/u);
  }
});

test("requires the separate exact callback operation and confirmation phrase", () => {
  assert.equal(SYSTEMBRUKER_CALLBACK_OPERATION, "set_rf1086_systembruker_callback");
  assert.equal(SYSTEMBRUKER_CALLBACK_CONFIRMATION, "SET TALLI SYSTEMBRUKER CALLBACK");
  assert.doesNotThrow(() =>
    assertSystembrukerCallbackOperationIntent({
      operation: "set_rf1086_systembruker_callback",
      confirmation: "SET TALLI SYSTEMBRUKER CALLBACK",
    }),
  );
  for (const input of [
    { operation: "register_rf1086_system", confirmation: "SET TALLI SYSTEMBRUKER CALLBACK" },
    { operation: "set_rf1086_systembruker_callback", confirmation: "set talli systembruker callback" },
    { operation: "set_rf1086_systembruker_callback", confirmation: " SET TALLI SYSTEMBRUKER CALLBACK" },
  ]) {
    assert.throws(
      () => assertSystembrukerCallbackOperationIntent(input),
      /authority_operation_invalid/u,
    );
  }
});

test("callback update performs a full PUT only from the exact empty-callback definition", async () => {
  const requests = [];
  const callbackDefinition = buildRf1086SystembrukerCallbackDefinition(
    productionEnvironment.TALLI_PROD_MASKINPORTEN_CLIENT_ID,
  );
  const result = await executeRf1086SystembrukerCallbackUpdate(
    environment(),
    callbackDependencies([
      jsonResponse(exactCallbackDefinition([])),
      jsonResponse(exactCallbackDefinition(["https://talli.no/auth/systembruker/confirm"])),
      jsonResponse(exactCallbackDefinition(["https://talli.no/auth/systembruker/confirm"])),
    ], requests),
  );

  assert.equal(result.resultCode, "callback_updated_and_verified");
  assert.equal(result.status, "succeeded");
  assert.deepEqual(requests.map((request) => request.method), ["GET", "PUT", "GET"]);
  assert.equal(requests[0].url, requests[1].url);
  assert.equal(requests[1].url, requests[2].url);
  assert.deepEqual(JSON.parse(requests[1].body), callbackDefinition);
  assert.deepEqual(
    JSON.parse(requests[1].body).allowedRedirectUrls,
    ["https://talli.no/auth/systembruker/confirm"],
  );
  assert.equal(JSON.parse(requests[1].body).isDeleted, false);
});

test("an exact callback definition is already verified with GET only", async () => {
  const requests = [];
  const result = await executeRf1086SystembrukerCallbackUpdate(
    environment(),
    callbackDependencies([
      jsonResponse(exactCallbackDefinition(["https://talli.no/auth/systembruker/confirm"])),
    ], requests),
  );

  assert.equal(result.resultCode, "callback_already_verified");
  assert.equal(result.status, "succeeded");
  assert.deepEqual(requests.map((request) => request.method), ["GET"]);
});

test("a missing system is a definition conflict and never creates or updates", async () => {
  const requests = [];
  const result = await executeRf1086SystembrukerCallbackUpdate(
    environment(),
    callbackDependencies([new Response(null, { status: 404 })], requests),
  );

  assert.equal(result.resultCode, "definition_conflict");
  assert.equal(result.status, "conflict");
  assert.deepEqual(requests.map((request) => request.method), ["GET"]);
});

test("any non-callback definition drift blocks without a write", async () => {
  const exact = exactCallbackDefinition([]);
  const conflicts = [
    { ...exact, id: "930835978_other" },
    { ...exact, vendor: { ID: "0192:999999999" } },
    { ...exact, vendor: { authority: null, ID: exact.vendor.ID } },
    { ...exact, name: { ...exact.name, nb: "Other" } },
    { ...exact, description: { ...exact.description, en: "Other" } },
    { ...exact, rights: [] },
    { ...exact, accessPackages: ["other"] },
    { ...exact, clientId: ["unexpected-client"] },
    { ...exact, isVisible: false },
    { ...exact, isDeleted: true },
    { ...exact, allowedRedirectUrls: ["https://talli.no/other"] },
  ];

  for (const conflict of conflicts) {
    const requests = [];
    const result = await executeRf1086SystembrukerCallbackUpdate(
      environment(),
      callbackDependencies([jsonResponse(conflict)], requests),
    );
    assert.equal(result.resultCode, "definition_conflict");
    assert.deepEqual(requests.map((request) => request.method), ["GET"]);
  }
});

test("callback verification drift is reported as conflict after the one allowed PUT", async () => {
  const requests = [];
  const result = await executeRf1086SystembrukerCallbackUpdate(
    environment(),
    callbackDependencies([
      jsonResponse(exactCallbackDefinition([])),
      jsonResponse(exactCallbackDefinition(["https://talli.no/auth/systembruker/confirm"])),
      jsonResponse({
        ...exactCallbackDefinition(["https://talli.no/auth/systembruker/confirm"]),
        isVisible: false,
      }),
    ], requests),
  );

  assert.equal(result.resultCode, "definition_conflict");
  assert.deepEqual(requests.map((request) => request.method), ["GET", "PUT", "GET"]);
});

test("creates a missing system then verifies it without leaking the token", async () => {
  const requests = [];
  const definition = buildRf1086SystemDefinition(
    productionEnvironment.TALLI_PROD_MASKINPORTEN_CLIENT_ID,
  );
  const responses = [
    new Response(null, { status: 404 }),
    jsonResponse("772e52bc-63c3-45c0-80b7-f3bb1581469f"),
    jsonResponse({ ...definition, isDeleted: false }),
  ];

  const result = await executeRf1086SystemRegistration(environment(), {
    requestToken: async (input) => {
      assert.equal(input.environment, "production");
      assert.equal(input.scope, "altinn:authentication/systemregister.write");
      assert.equal(input.systemUserOrgNumber, undefined);
      return token();
    },
    fetch: async (url, init) => {
      requests.push([String(url), init]);
      return responses.shift();
    },
  });

  assert.equal(result.code, "created_and_verified");
  assert.equal(result.status, "succeeded");
  assert.deepEqual(
    requests.map(([, init]) => init.method),
    ["GET", "POST", "GET"],
  );
  assert.equal(
    requests[0][0],
    "https://platform.altinn.no/authentication/api/v1/systemregister/vendor/930835978_talli",
  );
  assert.equal(
    requests[1][0],
    "https://platform.altinn.no/authentication/api/v1/systemregister/vendor",
  );
  for (const [, init] of requests) {
    assert.equal(init.redirect, "error");
    assert.ok(init.signal instanceof AbortSignal);
    assert.equal(init.headers.authorization, "Bearer opaque-secret-token");
  }
  assert.doesNotMatch(JSON.stringify(result), /opaque-secret-token/u);
});

test("returns already_verified for an exactly matching existing definition", async () => {
  const definition = buildRf1086SystemDefinition(
    productionEnvironment.TALLI_PROD_MASKINPORTEN_CLIENT_ID,
  );
  const { allowedredirecturls, ...documentedFields } = definition;
  let calls = 0;
  const result = await executeRf1086SystemRegistration(environment(), {
    requestToken: async () => token(),
    fetch: async () => {
      calls += 1;
      return jsonResponse({
        ...documentedFields,
        vendor: { ID: definition.vendor.ID },
        allowedRedirectUrls: allowedredirecturls,
        isDeleted: false,
      });
    },
  });

  assert.equal(calls, 1);
  assert.equal(result.code, "already_verified");
  assert.equal(result.status, "succeeded");
});

test("does not overwrite a conflicting existing definition", async () => {
  const requests = [];
  const result = await executeRf1086SystemRegistration(environment(), {
    requestToken: async () => token("token"),
    fetch: async (_url, init) => {
      requests.push(init.method);
      return jsonResponse({
        ...buildRf1086SystemDefinition(productionEnvironment.TALLI_PROD_MASKINPORTEN_CLIENT_ID),
        isVisible: false,
      });
    },
  });

  assert.deepEqual(requests, ["GET"]);
  assert.equal(result.code, "definition_conflict");
  assert.equal(result.status, "conflict");
});

test("rejects malformed authority responses with only safe errors", async () => {
  const privateKey = productionEnvironment.TALLI_PROD_MASKINPORTEN_PRIVATE_KEY_PEM;
  const rawBody = "upstream-secret-body";

  await assert.rejects(
    () =>
      executeRf1086SystemRegistration(environment(), {
        requestToken: async () => token("opaque-secret-token"),
        fetch: async () =>
          new Response(rawBody, {
            status: 200,
            headers: { "content-type": "application/json" },
          }),
      }),
    (error) => {
      assert.ok(error instanceof AuthorityOperationError);
      assert.equal(error.code, "authority_response_invalid");
      const serialized = `${error.name}:${error.message}:${error.stack}`;
      assert.doesNotMatch(serialized, /opaque-secret-token/u);
      assert.doesNotMatch(serialized, new RegExp(rawBody, "u"));
      assert.doesNotMatch(serialized, new RegExp(privateKey.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&"), "u"));
      return true;
    },
  );
});

test("sanitizes network and upstream HTTP failures", async () => {
  await assert.rejects(
    () =>
      executeRf1086SystemRegistration(environment(), {
        requestToken: async () => token("opaque-secret-token"),
        fetch: async () => {
          throw new Error("network contained opaque-secret-token");
        },
      }),
    (error) =>
      error.code === "authority_network_error" &&
      !error.message.includes("opaque-secret-token") &&
      error.authorityStatus === null,
  );

  await assert.rejects(
    () =>
      executeRf1086SystemRegistration(environment(), {
        requestToken: async () => token(),
        fetch: async () => jsonResponse({ detail: "raw-provider-secret" }, 503),
      }),
    (error) =>
      error.code === "authority_http_error" &&
      error.authorityStatus === 503 &&
      !error.message.includes("raw-provider-secret"),
  );
});
