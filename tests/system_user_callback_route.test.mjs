import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { SYSTEM_USER_COOKIE } from "../apps/web/app/lib/system-user-presentation.ts";
import { systemUserCallbackProof } from "../apps/web/app/lib/authority-callback-transport.ts";
import { createSystemUserCallbackHandler, systemUserSiteOrigin } from "../apps/web/app/auth/systembruker/confirm/route.ts";

const requestId = "22345678-1234-4234-8234-123456789abc";
const companyId = "12345678-1234-4234-8234-123456789abc";
const token = "synthetic-owner-session";
const key = "local-test-callback-key-with-32-bytes-minimum";

test("production route import defers canonical origin validation until a callback request", () => {
  const routeUrl = new URL("../apps/web/app/auth/systembruker/confirm/route.ts", import.meta.url).href;
  const result = spawnSync(
    process.execPath,
    [
      "--experimental-strip-types",
      "--input-type=module",
      "--eval",
      `await import(${JSON.stringify(routeUrl)})`,
    ],
    {
      encoding: "utf8",
      env: {
        ...process.env,
        NODE_ENV: "production",
        SITE_URL: "",
        NEXT_PUBLIC_SITE_URL: "",
      },
    },
  );

  assert.equal(result.status, 0, result.stderr);
});


function callbackFixture(options = {}) {
  const deletions = [], reconciliations = [], proofs = [];
  const handler = createSystemUserCallbackHandler({
    siteOrigin: "https://talli.no",
    async getAccessToken() { return options.noSession ? null : token; },
    async getCookieStore() {
      return {
        get() { return options.cookieMissing ? undefined : { value: options.cookieValue ?? requestId }; },
        delete(value) { deletions.push(value); },
      };
    },
    createProof(id, accessToken) {
      proofs.push({ id, accessToken });
      return systemUserCallbackProof(id, accessToken,
        { TALLI_AUTHORITY_CALLBACK_INTERNAL_KEY: options.noKey ? "" : key }, 1788960000000);
    },
    async reconcileRequest(accessToken, id, proof) {
      reconciliations.push({ accessToken, id, proof });
      if (options.backendReject) throw new Error("private owner/provider diagnostic");
      return options.result ?? {
        requestId, companyId, status: "accepted", preflightVerifiedAt: "2026-07-16T12:00:00.000Z",
        confirmationUrl: null, failureCode: null,
      };
    },
  });
  return { handler, deletions, reconciliations, proofs };
}

test("callback redirects use only the fixed Talli origin, with localhost limited to non-production", () => {
  assert.equal(systemUserSiteOrigin({ NODE_ENV: "production", SITE_URL: "https://talli.no" }), "https://talli.no");
  assert.equal(systemUserSiteOrigin({ NODE_ENV: "development" }), "http://localhost:3000");
  assert.equal(
    systemUserSiteOrigin({ NODE_ENV: "test", SITE_URL: "http://localhost:3100" }),
    "http://localhost:3100",
  );
  for (const invalid of [
    { NODE_ENV: "production", SITE_URL: "http://localhost:3000" },
    { NODE_ENV: "production", SITE_URL: "https://evil.invalid" },
    { NODE_ENV: "production", SITE_URL: "https://talli.no/path" },
    { NODE_ENV: "development", SITE_URL: "https://preview.invalid" },
  ]) {
    assert.throws(() => systemUserSiteOrigin(invalid), /site_origin_invalid/u);
  }
});


test("callback ignores all query parameters and forwards only its local cookie with bound server proof", async () => {
  const fixture = callbackFixture();
  const response = await fixture.handler(new Request("https://evil.invalid/auth/systembruker/confirm?request=attacker&company=other&next=https://evil.invalid"));
  assert.equal(response.status, 307);
  assert.equal(response.headers.get("location"), `https://talli.no/connections?company=${companyId}&systembruker=connected`);
  assert.deepEqual(fixture.proofs, [{ id: requestId, accessToken: token }]);
  assert.equal(fixture.reconciliations.length, 1);
  assert.equal(fixture.reconciliations[0].id, requestId);
  assert.equal(fixture.reconciliations[0].accessToken, token);
  assert.match(fixture.reconciliations[0].proof, /^v1:1788960000:[a-f0-9]{64}$/u);
  assert.deepEqual(fixture.deletions, [{ name: SYSTEM_USER_COOKIE.name, path: SYSTEM_USER_COOKIE.options.path }]);
  assert.doesNotMatch(response.headers.get("location"), /evil|attacker|other|session|key/u);
});

test("missing or invalid cookie, missing session, and missing transport key fail before backend effects", async () => {
  for (const options of [{ cookieMissing: true }, { cookieValue: "not-a-uuid" }, { noSession: true }, { noKey: true }]) {
    const fixture = callbackFixture(options);
    const response = await fixture.handler(new Request("https://talli.no/auth/systembruker/confirm?error=reflected"));
    assert.equal(response.headers.get("location"), "https://talli.no/connections?systembruker=manual");
    assert.equal(fixture.reconciliations.length, 0);
    assert.deepEqual(fixture.deletions, [{ name: SYSTEM_USER_COOKIE.name, path: SYSTEM_USER_COOKIE.options.path }]);
  }
});

test("backend owner, stale-request or provider rejection exposes no private diagnostic", async () => {
  const fixture = callbackFixture({ backendReject: true });
  const response = await fixture.handler(new Request("https://talli.no/auth/systembruker/confirm?error=raw-secret"));
  assert.equal(response.headers.get("location"), "https://talli.no/connections?systembruker=manual");
  assert.doesNotMatch(response.headers.get("location"), /raw|secret|provider|session|private/u);
  assert.deepEqual(fixture.deletions, [{ name: SYSTEM_USER_COOKIE.name, path: SYSTEM_USER_COOKIE.options.path }]);
});

test("callback rejects a backend result for another request", async () => {
  const fixture = callbackFixture({ result: { requestId: "92345678-1234-4234-8234-123456789abc", companyId, status: "accepted", preflightVerifiedAt: "2026-07-16T12:00:00Z" } });
  const response = await fixture.handler(new Request("https://talli.no/auth/systembruker/confirm"));
  assert.equal(response.headers.get("location"), "https://talli.no/connections?systembruker=manual");
});

test("callback maps only existing local presentation states", async () => {
  for (const [status, preflightVerifiedAt, expected] of [
    ["creating", null, "pending"], ["new", null, "pending"], ["accepted", null, "verifying"],
    ["accepted", "2026-07-16T12:00:00Z", "connected"], ["rejected", null, "rejected"],
    ["denied", null, "denied"], ["timedout", null, "timedout"], ["verification_failed", null, "manual"],
  ]) {
    const fixture = callbackFixture({ result: { requestId, companyId, status, preflightVerifiedAt, confirmationUrl: null, failureCode: null } });
    const response = await fixture.handler(new Request("https://talli.no/auth/systembruker/confirm"));
    const location = new URL(response.headers.get("location"));
    assert.equal(location.searchParams.get("systembruker"), expected);
    assert.equal(location.searchParams.get("company"), companyId);
  }
});

test("web callback proof interoperates with the backend verifier and binds request plus bearer", () => {
  const proof = systemUserCallbackProof(requestId, token, { TALLI_AUTHORITY_CALLBACK_INTERNAL_KEY: key }, 1788960000000);
  const result = spawnSync("apps/backend/.venv/bin/python", ["-c", `
import json,sys
from talli_backend.adapters.authority_callback_transport import AuthorityCallbackTransport
v=json.load(sys.stdin)
a=AuthorityCallbackTransport(v['key'],clock=lambda:1788960000)
assert a.verify(request_id=v['request'],bearer=v['token'],proof=v['proof'])
assert not a.verify(request_id=v['request'],bearer='different-session',proof=v['proof'])
`], { input: JSON.stringify({ key, request: requestId, token, proof }), encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
  assert.notEqual(proof, systemUserCallbackProof(requestId, "another-session", { TALLI_AUTHORITY_CALLBACK_INTERNAL_KEY: key }, 1788960000000));
});
