import assert from "node:assert/strict";
import { generateKeyPairSync, verify } from "node:crypto";
import test from "node:test";

import {
  MASKINPORTEN_TEST_ISSUER,
  createMaskinportenTestSystemUserGrant,
  requestMaskinportenTestSystemUserToken,
} from "../app/lib/maskinporten-system-user.ts";

const clientId = "7166e743-978e-4a60-8a2d-0a5c00fe6ad0";
const keyId = "2d275f93-10a2-4839-993e-b14da2b84ad8";
const customerOrgNumber = "310279617";
const scope = "skatteetaten:innrapporteringaksjonaerregisteroppgave";
const { privateKey, publicKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
const privateKeyPem = privateKey.export({ type: "pkcs8", format: "pem" }).toString();

function decodeSegment(value) {
  return JSON.parse(Buffer.from(value, "base64url").toString("utf8"));
}

test("creates a signed, short-lived TT02 system-user grant", () => {
  const assertion = createMaskinportenTestSystemUserGrant({
    clientId,
    keyId,
    customerOrgNumber,
    scopes: [scope, scope],
    privateKeyPem,
    nowSeconds: 1_720_000_000,
    jti: "12345678-1234-4234-9234-123456789abc",
  });
  const [encodedHeader, encodedPayload, signature] = assertion.split(".");

  assert.deepEqual(decodeSegment(encodedHeader), { alg: "RS256", kid: keyId, typ: "JWT" });
  assert.deepEqual(decodeSegment(encodedPayload), {
    aud: MASKINPORTEN_TEST_ISSUER,
    iss: clientId,
    scope,
    authorization_details: [
      {
        type: "urn:altinn:systemuser",
        systemuser_org: {
          authority: "iso6523-actorid-upis",
          ID: `0192:${customerOrgNumber}`,
        },
      },
    ],
    iat: 1_720_000_000,
    exp: 1_720_000_120,
    jti: "12345678-1234-4234-9234-123456789abc",
  });
  assert.equal(
    verify("RSA-SHA256", Buffer.from(`${encodedHeader}.${encodedPayload}`), publicKey, Buffer.from(signature, "base64url")),
    true,
  );
});

test("requests a token without exposing it in the returned metadata", async () => {
  let request;
  const result = await requestMaskinportenTestSystemUserToken({
    assertion: "header.payload.signature",
    requestedScopes: [scope],
    fetchImplementation: async (url, init) => {
      request = { url, init };
      return new Response(
        JSON.stringify({ access_token: "short-lived-system-user-token", token_type: "Bearer", expires_in: 120, scope }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    },
  });

  assert.equal(request.url, `${MASKINPORTEN_TEST_ISSUER}token`);
  assert.equal(request.init.method, "POST");
  assert.equal(request.init.redirect, "error");
  assert.equal(request.init.headers["Content-Type"], "application/x-www-form-urlencoded");
  assert.equal(new URLSearchParams(request.init.body).get("assertion"), "header.payload.signature");
  assert.deepEqual(result, { accessToken: "short-lived-system-user-token", expiresIn: 120, scopes: [scope] });
  assert.doesNotMatch(JSON.stringify(request), /short-lived-system-user-token/u);
});

test("rejects invalid grant inputs and unsafe token responses", async () => {
  assert.throws(
    () =>
      createMaskinportenTestSystemUserGrant({
        clientId,
        keyId,
        customerOrgNumber: "930835978",
        scopes: ["invalid scope"],
        privateKeyPem,
      }),
    /scope/u,
  );
  await assert.rejects(
    requestMaskinportenTestSystemUserToken({
      assertion: "header.payload.signature",
      requestedScopes: [scope],
      fetchImplementation: async () =>
        new Response(JSON.stringify({ access_token: "secret", token_type: "Bearer", expires_in: 120, scope: "other:scope" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    }),
    /invalid response/u,
  );
});
