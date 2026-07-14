import assert from "node:assert/strict";
import { generateKeyPairSync, verify } from "node:crypto";
import test from "node:test";

import {
  MASKINPORTEN_JWT_BEARER_GRANT_TYPE,
  MaskinportenTokenError,
  buildMaskinportenGrant,
  requestMaskinportenToken,
  signMaskinportenGrant,
  summarizeMaskinportenToken,
} from "../app/lib/maskinporten.ts";

const clientId = "7166e743-978e-4a60-8a2d-0a5c00fe6ad0";
const keyId = "2d275f93-10a2-4839-993e-b14da2b84ad8";
const scope = "skatteetaten:innrapporteringaksjonaerregisteroppgave";
const systemUserOrgNumber = "310279617";

function keyPair() {
  return generateKeyPairSync("rsa", { modulusLength: 2048 });
}

test("builds a short-lived TT02 system-user grant against the issuer audience", () => {
  const grant = buildMaskinportenGrant({
    environment: "test",
    clientId,
    keyId,
    scope,
    systemUserOrgNumber,
    now: new Date("2026-07-14T10:00:00.000Z"),
    jti: "3e51ac33-9675-4328-9604-01c34c9f0170",
  });

  assert.deepEqual(grant.header, { alg: "RS256", kid: keyId, typ: "JWT" });
  assert.equal(grant.claims.iss, clientId);
  assert.equal(grant.claims.sub, clientId);
  assert.equal(grant.claims.aud, "https://test.maskinporten.no/");
  assert.equal(grant.claims.scope, scope);
  assert.equal(grant.claims.exp - grant.claims.iat, 119);
  assert.deepEqual(grant.claims.authorization_details, [
    {
      type: "urn:altinn:systemuser",
      systemuser_org: {
        authority: "iso6523-actorid-upis",
        ID: "0192:310279617",
      },
    },
  ]);
});

test("signs a verifiable compact RS256 JWT without exposing the private key", () => {
  const { privateKey, publicKey } = keyPair();
  const grant = buildMaskinportenGrant({
    environment: "test",
    clientId,
    keyId,
    scope,
    systemUserOrgNumber,
    now: new Date("2026-07-14T10:00:00.000Z"),
    jti: "3e51ac33-9675-4328-9604-01c34c9f0170",
  });

  const assertion = signMaskinportenGrant(grant, privateKey.export({ type: "pkcs8", format: "pem" }));
  const [header, claims, signature] = assertion.split(".");

  assert.equal(assertion.split(".").length, 3);
  assert.equal(
    verify(
      "RSA-SHA256",
      Buffer.from(`${header}.${claims}`),
      publicKey,
      Buffer.from(signature, "base64url"),
    ),
    true,
  );
  assert.doesNotMatch(assertion, /PRIVATE KEY/);
});

test("posts the JWT bearer grant and returns an opaque access token in memory", async () => {
  const { privateKey } = keyPair();
  let captured;
  const token = await requestMaskinportenToken(
    {
      environment: "test",
      clientId,
      keyId,
      scope,
      systemUserOrgNumber,
      privateKeyPem: privateKey.export({ type: "pkcs8", format: "pem" }).toString(),
      now: new Date("2026-07-14T10:00:00.000Z"),
      jti: "3e51ac33-9675-4328-9604-01c34c9f0170",
    },
    {
      fetch: async (url, init) => {
        captured = { url, init };
        return new Response(
          JSON.stringify({ access_token: "opaque-secret-token", token_type: "Bearer", expires_in: 599, scope }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      },
    },
  );

  assert.equal(captured.url, "https://test.maskinporten.no/token");
  assert.equal(captured.init.method, "POST");
  assert.equal(captured.init.headers["content-type"], "application/x-www-form-urlencoded");
  const form = new URLSearchParams(captured.init.body);
  assert.equal(form.get("grant_type"), MASKINPORTEN_JWT_BEARER_GRANT_TYPE);
  assert.equal(form.get("assertion")?.split(".").length, 3);
  assert.equal(token.accessToken, "opaque-secret-token");
  assert.deepEqual(summarizeMaskinportenToken(token), {
    environment: "test",
    scope,
    tokenType: "Bearer",
    expiresIn: 599,
    accessTokenPresent: true,
  });
  assert.doesNotMatch(JSON.stringify(summarizeMaskinportenToken(token)), /opaque-secret-token/);
});

test("sanitizes authority errors and rejects malformed token responses", async () => {
  const { privateKey } = keyPair();
  const config = {
    environment: "test",
    clientId,
    keyId,
    scope,
    systemUserOrgNumber,
    privateKeyPem: privateKey.export({ type: "pkcs8", format: "pem" }).toString(),
  };

  await assert.rejects(
    requestMaskinportenToken(config, {
      fetch: async () => new Response(
        JSON.stringify({ error: "invalid_scope", error_description: "MP-250 scope denied", access_token: "must-not-leak" }),
        { status: 400, headers: { "content-type": "application/json" } },
      ),
    }),
    (error) => {
      assert.ok(error instanceof MaskinportenTokenError);
      assert.equal(error.status, 400);
      assert.equal(error.code, "invalid_scope");
      assert.match(error.message, /MP-250 scope denied/);
      assert.doesNotMatch(error.message, /must-not-leak/);
      return true;
    },
  );

  await assert.rejects(
    requestMaskinportenToken(config, {
      fetch: async () => new Response(JSON.stringify({ token_type: "Bearer", expires_in: 599 }), { status: 200 }),
    }),
    /missing access_token/i,
  );
});

test("fails closed on invalid environment, identifiers, scope, and key material", async () => {
  assert.throws(
    () => buildMaskinportenGrant({ environment: "staging", clientId, keyId, scope, systemUserOrgNumber }),
    /environment/i,
  );
  assert.throws(
    () => buildMaskinportenGrant({ environment: "test", clientId: "", keyId, scope, systemUserOrgNumber }),
    /client id/i,
  );
  assert.throws(
    () => buildMaskinportenGrant({ environment: "test", clientId, keyId, scope: "bad scope\nsecond", systemUserOrgNumber }),
    /scope/i,
  );
  assert.throws(
    () => buildMaskinportenGrant({ environment: "test", clientId, keyId, scope, systemUserOrgNumber: "123" }),
    /organization number/i,
  );
  await assert.rejects(
    requestMaskinportenToken({
      environment: "test",
      clientId,
      keyId,
      scope,
      systemUserOrgNumber,
      privateKeyPem: "not-a-private-key",
    }),
    /sign Maskinporten grant/i,
  );
});
