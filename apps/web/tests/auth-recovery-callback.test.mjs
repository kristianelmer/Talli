import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

const require = createRequire(import.meta.url);
const key = "synthetic-server-cookie-signing-key-for-callback-tests";
const userId = "10000000-0000-4000-8000-000000000001";
const otherId = "10000000-0000-4000-8000-000000000002";
const sessionId = "20000000-0000-4000-8000-000000000001";
const next = "/billing?incomeYear=2026#annual-billing";
function compile(file, dependencies = {}) {
  const exports = {};
  const source = readFileSync(new URL(`../app/${file}`, import.meta.url), "utf8");
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS,
  } }).outputText, { exports, require: name => dependencies[name] ?? require(name),
    URL, URLSearchParams, Buffer, Headers, Date, process: { env: { SUPABASE_SERVICE_ROLE_KEY: key } } });
  return exports;
}
const redirect = compile("lib/internal-redirect.ts");
const presentation = compile("lib/auth-recovery-presentation.ts", { "./internal-redirect": redirect });
const intent = compile("lib/auth-recovery-intent.ts", { "./auth-recovery-presentation": presentation });
function response(url) {
  const values = new Map();
  return { url, values, headers: new Headers(), cookies: {
    set: (name, value) => values.set(name, value), delete: name => values.set(name, ""),
  } };
}

function harness(options = {}) {
  const calls = [];
  const verifier = "synthetic-verifier/recovery";
  const signed = intent.mintRecoveryIntent({ kind: "request", email: "synthetic@example.invalid", verifierHash: intent.verifierDigest(verifier), next }, key);
  const initial = new Map([
    ["sb-local-auth-token", "original-account-cookie"],
    ["sb-local-code-verifier", options.verifier ?? verifier],
    [intent.RECOVERY_REQUEST_COOKIE, options.signed === undefined ? signed : options.signed],
  ]);
  let adapter;
  const verify = async kind => {
    calls.push(kind);
    adapter.setAll([{ name: "sb-local-auth-token", value: "replacement-account-cookie", options: {} }]);
    return { data: { user: { id: userId }, session: { access_token: "synthetic-access" }, redirectType: options.redirectType ?? "recovery" }, error: options.verifyError ?? null };
  };
  const auth = {
    async getUser(token) {
      calls.push(token ? "verified-user" : "prior-user");
      if (!token && options.throwPrior) throw new Error("private-provider-failure");
      return token
        ? { data: { user: { id: options.returnedId ?? userId, email: options.email ?? "synthetic@example.invalid" } }, error: null }
        : { data: { user: options.prior ?? null }, error: options.priorError ?? null };
    },
    exchangeCodeForSession: () => verify("exchange"), verifyOtp: () => verify("otp"),
    async getClaims() { calls.push("claims"); return { data: { claims: { sub: userId, session_id: sessionId } }, error: options.claimsError ?? null }; },
    async signOut(body) { calls.push(`sign-out:${body.scope}`); return { error: null }; },
  };
  const route = compile("auth/recovery/route.ts", {
    "@supabase/ssr": { createServerClient: (_url, _key, setup) => { adapter = setup.cookies; return { auth }; } },
    "next/headers": { cookies: async () => ({ getAll: () => [...initial].map(([name, value]) => ({ name, value })), get: name => ({ value: initial.get(name) }) }) },
    "next/server": { NextResponse: { redirect: response } },
    "../../lib/auth-recovery-context": { hasAuthRecoveryEnv: () => options.configured !== false },
    "../../lib/auth-recovery-intent": intent,
    "../../lib/auth-recovery-presentation": presentation,
  });
  return { calls, initial, run: params => route.GET({ nextUrl: new URL(`https://talli.example/auth/recovery?${params}`) }) };
}
const request = params => new URLSearchParams({ next, ...params });
test("verified token-hash recovery applies the new session and signs its exact actor/session", async () => {
  const h = harness();
  const result = await h.run(request({ token_hash: "synthetic-hash", type: "recovery" }));
  assert.equal(result.url.pathname, "/reset-password");
  assert.equal(result.url.searchParams.get("next"), next);
  assert.equal(result.values.get("sb-local-auth-token"), "replacement-account-cookie");
  const grant = intent.readRecoveryIntent(result.values.get(intent.RECOVERY_GRANT_COOKIE), key);
  assert.equal(grant.userId, userId); assert.equal(grant.sessionId, sessionId); assert.equal(grant.kind, "grant");
  assert.equal(result.headers.get("Cache-Control"), "private, no-store");
  assert.equal(result.headers.get("Referrer-Policy"), "no-referrer");
});
test("PKCE requires signed request and unchanged verifier, and retains its signed destination", async () => {
  const h = harness();
  const result = await h.run(request({ code: "synthetic-code", next: "https://outside.example" }));
  assert.equal(result.url.pathname, "/reset-password"); assert.equal(result.url.searchParams.get("next"), next);
  assert.ok(h.calls.includes("exchange"));
  for (const options of [{ signed: "forged" }, { signed: "" }, { verifier: "changed-verifier" }]) {
    const invalid = harness(options); const failure = await invalid.run(request({ code: "synthetic-code" }));
    assert.equal(failure.url.pathname, "/forgot-password"); assert.deepEqual(invalid.calls, []);
  }
});
for (const [name, options, params, reason] of [
  ["wrong account", { prior: { id: otherId } }, { token_hash: "synthetic", type: "recovery" }, "wrong-account"],
  ["wrong recipient", { email: "other@example.invalid" }, { code: "synthetic" }, "wrong-recipient"],
  ["expired or used", { verifyError: { code: "otp_expired" } }, { token_hash: "synthetic", type: "recovery" }, "invalid-link"],
  ["normal confirmation code", { redirectType: "signup" }, { code: "synthetic" }, "invalid-link"],
  ["unverifiable actor", { returnedId: otherId }, { token_hash: "synthetic", type: "recovery" }, "unavailable"],
  ["bad claims", { claimsError: {} }, { token_hash: "synthetic", type: "recovery" }, "unavailable"],
  ["provider unavailable", { priorError: { status: 503 } }, { code: "synthetic" }, "unavailable"],
]) test(`${name} recovery neither replaces the old account cookie nor grants a password form`, async () => {
  const h = harness(options); const result = await h.run(request(params));
  assert.equal(result.url.pathname, "/forgot-password"); assert.equal(result.url.searchParams.get("error"), reason);
  assert.equal(result.values.has("sb-local-auth-token"), false);
  assert.equal(result.values.get(intent.RECOVERY_GRANT_COOKIE), "");
  assert.equal(h.initial.get("sb-local-auth-token"), "original-account-cookie");
  assert.doesNotMatch(result.url.href, /synthetic-hash|synthetic-code|replacement-account-cookie/);
});
for (const params of [{}, { token_hash: "synthetic", type: "signup" }, { code: "synthetic", token_hash: "synthetic", type: "recovery" }, { code: "synthetic", error: "private-provider-message" }]) {
  test("ambiguous or non-recovery callback cannot invoke token verification", async () => {
    const h = harness(); const result = await h.run(request(params));
    assert.equal(result.url.searchParams.get("error"), "invalid-link"); assert.deepEqual(h.calls, []);
    assert.doesNotMatch(result.url.href, /private-provider-message/);
  });
}

for (const params of [{ code: "synthetic" }, { token_hash: "synthetic", type: "recovery" }]) {
  for (const priorError of [{ status: 0 }, { status: 429 }, { status: 400 }, { name: "AuthSessionMissingError", status: 400 }]) {
    test(`uncertain prior account ${JSON.stringify(priorError)} stops ${Object.keys(params)[0]} before exchange`, async () => {
      const h = harness({ priorError });
      const result = await h.run(request(params));
      assert.equal(result.url.searchParams.get("error"), "unavailable");
      assert.deepEqual(h.calls, ["prior-user"]);
      assert.equal(result.values.has("sb-local-auth-token"), false);
      assert.equal(result.values.get(intent.RECOVERY_GRANT_COOKIE), "");
    });
  }
  test(`explicit SDK missing-session permits ${Object.keys(params)[0]} recovery`, async () => {
    const { AuthSessionMissingError } = require("@supabase/supabase-js");
    const h = harness({ priorError: new AuthSessionMissingError() });
    assert.equal((await h.run(request(params))).url.pathname, "/reset-password");
  });
  test(`throwing prior lookup stops ${Object.keys(params)[0]} recovery`, async () => {
    const h = harness({ throwPrior: true });
    const result = await h.run(request(params));
    assert.equal(result.url.searchParams.get("error"), "unavailable");
    assert.deepEqual(h.calls, ["prior-user"]);
    assert.equal(result.values.has("sb-local-auth-token"), false);
  });
}

for (const name of ["code", "token_hash", "type", "next"]) {
  test(`duplicate ${name} cannot invoke the recovery provider`, async () => {
    const h = harness();
    const params = request({ token_hash: "synthetic", type: "recovery" });
    params.append(name, "first"); params.append(name, "second");
    assert.equal((await h.run(params)).url.searchParams.get("error"), "invalid-link");
    assert.deepEqual(h.calls, []);
  });
}
