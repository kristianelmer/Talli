import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

const require = createRequire(import.meta.url);
const key = "synthetic-server-cookie-signing-key-for-frontend-tests";
const userId = "10000000-0000-4000-8000-000000000001";
const otherId = "10000000-0000-4000-8000-000000000002";
const sessionId = "20000000-0000-4000-8000-000000000001";
const next = `/billing?companyId=${userId}&beforePurchaseId=${otherId}#annual-billing`;
const source = name => readFileSync(new URL(`../app/${name}`, import.meta.url), "utf8");
function compile(name, dependencies, env = {}) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(source(name), { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText, { exports, require: name => dependencies?.[name] ?? require(name),
    Buffer, URL, URLSearchParams, Date, process: { env: { SUPABASE_SERVICE_ROLE_KEY: key, NODE_ENV: "production", SITE_URL: "https://talli.example", ...env } } });
  return exports;
}
const redirectModule = compile("lib/internal-redirect.ts");
const presentation = compile("lib/auth-recovery-presentation.ts", { "./internal-redirect": redirectModule });
const intent = compile("lib/auth-recovery-intent.ts", { "./auth-recovery-presentation": presentation });
const grant = (extra = {}, now = Date.now()) => intent.mintRecoveryIntent({ kind: "grant", userId, sessionId, next, ...extra }, key, now);

test("signed recovery scope rejects tampering, wrong keys, expiry and extra segments", () => {
  const signed = grant({}, 10_000);
  assert.equal(intent.readRecoveryIntent(signed, key, 10_001).userId, userId);
  const [payload, signature] = signed.split(".");
  const value = JSON.parse(Buffer.from(payload, "base64url"));
  value.userId = otherId;
  assert.equal(intent.readRecoveryIntent(`${Buffer.from(JSON.stringify(value)).toString("base64url")}.${signature}`, key, 10_001), null);
  assert.equal(intent.readRecoveryIntent(signed, "another-synthetic-key", 10_001), null);
  assert.equal(intent.readRecoveryIntent(signed, key, 610_000), null);
  assert.equal(intent.readRecoveryIntent(signed, key, 9_999), null);
  assert.equal(intent.readRecoveryIntent(`${signed}.extra`, key, 10_001), null);
  for (const invalid of ["", "not-a-cookie", "a.b", "a".repeat(8_193)]) assert.equal(intent.readRecoveryIntent(invalid, key), null);
  assert.equal(intent.recoveryCookieOptions.httpOnly, true);
  assert.equal(intent.recoveryCookieOptions.secure, true);
  assert.equal(intent.recoveryCookieOptions.sameSite, "lax");
});

test("recovery return retains annual scope and rejects external or recursive auth entries", () => {
  assert.equal(presentation.recoveryReturn(next), next);
  for (const value of ["https://outside.example", "//outside.example", "/\\outside.example", "/login?next=/reset-password", "/auth/confirm", "/reset-password", "/signup", "/forgot-password", "/dashboard\nLocation:evil", "a".repeat(2_049)]) {
    assert.equal(presentation.recoveryReturn(value), "/dashboard");
  }
  assert.equal(presentation.recoveryError("raw-private-provider-error"), null);
});

function contextHarness(options = {}) {
  const calls = [];
  const cookie = options.cookie ?? grant();
  const auth = {
    async getUser() { calls.push("user"); return { data: { user: options.user === undefined ? { id: userId, email: "synthetic@example.invalid", factors: options.assurance?.nextLevel === "aal2" ? [{ status: "verified" }] : [] } : options.user }, error: options.userError ?? null }; },
    async getClaims() { calls.push("claims"); return { data: { claims: options.claims ?? { sub: userId, session_id: sessionId, aal: options.assurance?.currentLevel ?? "aal1" } }, error: options.claimsError ?? null }; },
  };
  const module = compile("lib/auth-recovery-context.ts", {
    "next/headers": { cookies: async () => ({ get: () => ({ value: cookie }) }) },
    "./supabase/server": { hasSupabaseEnv: () => options.configured !== false, createSupabaseServerClient: async () => ({ auth }) },
    "./auth-recovery-intent": intent,
  });
  return { calls, run: module.passwordRecoveryContext };
}

for (const [name, options, kind, calls] of [
  ["missing", { cookie: "" }, "invalid-link", []],
  ["forged", { cookie: "forged" }, "invalid-link", []],
  ["expired", { cookie: grant({}, Date.now() - 601_000) }, "invalid-link", []],
  ["unavailable", { configured: false }, "unavailable", []],
  ["no session", { user: null }, "expired-session", ["user"]],
  ["Auth read outage", { userError: { status: 503 } }, "unavailable", ["user"]],
  ["wrong actor", { user: { id: otherId } }, "wrong-account", ["user"]],
  ["changed session", { claims: { sub: userId, session_id: otherId } }, "expired-session", ["user", "claims"]],
  ["bad claims", { claimsError: {} }, "expired-session", ["user", "claims"]],
  ["claims outage", { claimsError: { status: 503 } }, "unavailable", ["user", "claims"]],
  ["MFA required", { assurance: { currentLevel: "aal1", nextLevel: "aal2" } }, "mfa", ["user", "claims"]],
  ["unknown MFA", { claims: { sub: userId, session_id: sessionId, aal: "unknown" } }, "unavailable", ["user", "claims"]],
  ["cookie cannot hide a registered factor", { user: { id: userId, factors: [{ id: "registered", status: "verified" }] } }, "mfa", ["user", "claims"]],
]) {
  test(`${name} recovery never reaches a password write`, async () => {
    const harness = contextHarness(options);
    assert.equal((await harness.run()).kind, kind);
    assert.deepEqual(harness.calls, calls);
  });
}
test("verified AAL2 and exact session preserve the signed return", async () => {
  const result = await contextHarness({ assurance: { currentLevel: "aal2", nextLevel: "aal2" } }).run();
  assert.equal(result.kind, "ready"); assert.equal(result.next, next);
});

function actionHarness(options = {}) {
  const calls = [];
  const cookieMap = new Map();
  const cookieStore = {
    getAll: () => [...cookieMap].map(([name, value]) => ({ name, value })),
    set: (name, value) => cookieMap.set(name, value), delete: name => { calls.push(`delete:${name}`); cookieMap.delete(name); },
  };
  const auth = {
    async resetPasswordForEmail(email, request) {
      calls.push({ reset: email, callback: request.redirectTo });
      if (options.throwRequest) throw new Error("private-response");
      cookieMap.set("sb-local-code-verifier", "synthetic-verifier/recovery");
      return { error: options.requestError ?? null };
    },
    async updateUser(body) {
      calls.push({ update: body.password });
      if (options.throwUpdate) throw new Error("private-response");
      return { data: { user: options.responseUser ?? { id: userId } }, error: options.updateError ?? null };
    },
    async signOut(body) { calls.push({ signOut: body.scope }); return { error: null }; },
  };
  const module = compile("(auth)/recovery-actions.ts", {
    "next/headers": { cookies: async () => cookieStore },
    "next/navigation": { redirect: value => { throw new Error(`redirect:${value}`); } },
    "../lib/supabase/server": { createSupabaseServerClient: async () => ({ auth }) },
    "../lib/site-url": { getSiteUrl: async () => options.site ?? "https://talli.example" },
    "../lib/auth-recovery-context": { hasAuthRecoveryEnv: () => options.configured !== false,
      passwordRecoveryContext: async () => options.context ?? { kind: "ready", user: { id: userId }, next, supabase: { auth } } },
    "../lib/auth-recovery-intent": intent,
    "../lib/auth-recovery-presentation": presentation,
  });
  return { ...module, calls, cookieMap };
}
function fields(extra = {}) {
  const data = new FormData();
  for (const [name, value] of Object.entries({ email: "SYNTHETIC@example.invalid", password: "synthetic-password-only", confirmation: "synthetic-password-only", userId, next, ...extra })) data.set(name, value);
  return data;
}
test("request issues one PKCE recovery callback and signs the exact verifier, email and return", async () => {
  const harness = actionHarness();
  assert.equal((await harness.requestPasswordRecovery({ status: "idle" }, fields())).status, "sent");
  const request = harness.calls.find(value => value.reset);
  const callback = new URL(request.callback);
  assert.equal(callback.pathname, "/auth/recovery"); assert.equal(callback.searchParams.get("next"), next);
  const signed = intent.readRecoveryIntent(harness.cookieMap.get(intent.RECOVERY_REQUEST_COOKIE), key);
  assert.equal(signed.email, "synthetic@example.invalid");
  assert.equal(signed.verifierHash, intent.verifierDigest("synthetic-verifier/recovery"));
  assert.equal(signed.next, next);
});
for (const [name, options, status, reason] of [
  ["unknown address", { requestError: { code: "user_not_found" } }, "sent"],
  ["rate limit", { requestError: { status: 429, message: "private-response" } }, "error", "rate-limit"],
  ["transport", { throwRequest: true }, "error", "unavailable"],
  ["unsafe site", { site: "http://outside.example" }, "error", "unavailable"],
]) test(`${name} request has bounded, non-enumerating feedback`, async () => {
  const result = await actionHarness(options).requestPasswordRecovery({ status: "idle" }, fields());
  assert.equal(result.status, status); if (reason) assert.equal(result.reason, reason);
  assert.doesNotMatch(JSON.stringify(result), /private-response|user_not_found/);
});

for (const [name, extra, context, reason] of [
  ["short password", { password: "short", confirmation: "short" }, undefined, "password-short"],
  ["mismatch", { confirmation: "different-password" }, undefined, "password-mismatch"],
  ["foreign form actor", { userId: otherId }, undefined, "wrong-account"],
  ["missing grant", {}, { kind: "invalid-link" }, "invalid-link"],
  ["MFA gate", {}, { kind: "mfa" }, "mfa"],
]) test(`${name} blocks before updateUser`, async () => {
  const harness = actionHarness({ context });
  assert.equal((await harness.updateRecoveredPassword({ status: "idle" }, fields(extra))).reason, reason);
  assert.equal(harness.calls.some(value => value.update), false);
});
for (const options of [{ throwUpdate: true }, { updateError: new (require("@supabase/supabase-js").AuthRetryableFetchError)("synthetic lost response", 0) }, { updateError: {} }, { updateError: { status: 503 } }, { responseUser: { id: otherId } }]) {
  test("unconfirmed password change clears update intent without claiming failure or retrying", async () => {
    const harness = actionHarness(options);
    await assert.rejects(harness.updateRecoveredPassword({ status: "idle" }, fields()), error => {
      const target = new URL(error.message.slice(9), "https://talli.example");
      assert.equal(target.pathname, "/reset-password");
      assert.equal(target.searchParams.get("error"), "password-unknown");
      assert.equal(target.searchParams.get("next"), next);
      return true;
    });
    assert.equal(harness.calls.filter(value => value.update).length, 1);
    assert.ok(harness.calls.includes(`delete:${intent.RECOVERY_GRANT_COOKIE}`));
    assert.equal(harness.calls.some(value => value.signOut), false);
  });
}
test("confirmed update clears intent, signs out locally and retains the annual return", async () => {
  const harness = actionHarness();
  await assert.rejects(harness.updateRecoveredPassword({ status: "idle" }, fields()), error => {
    const url = new URL(error.message.slice(9), "https://talli.example");
    assert.equal(url.pathname, "/login"); assert.equal(url.searchParams.get("reauth"), "1");
    assert.equal(url.searchParams.get("next"), next); return true;
  });
  assert.equal(harness.calls.filter(value => value.update).length, 1);
  assert.ok(harness.calls.some(value => value.signOut === "local"));
});

test("signed cookies reject malformed purpose, extra fields and invalid actor/session even with a valid signature", () => {
  const { createHmac } = require("node:crypto");
  const decoded = JSON.parse(Buffer.from(grant({}, 10_000).split(".")[0], "base64url"));
  const sign = value => {
    const payload = Buffer.from(JSON.stringify(value)).toString("base64url");
    const signingKey = createHmac("sha256", key).update("talli/auth/password-recovery/v1").digest();
    return `${payload}.${createHmac("sha256", signingKey).update(payload).digest("hex")}`;
  };
  for (const change of [{ kind: "request" }, { kind: "other" }, { extra: true }, { sessionId: "invalid" },
    { userId: "invalid" }, { version: 2 }, { expiresAt: 610_002 }, { next: "//outside.example" }]) {
    assert.equal(intent.readRecoveryIntent(sign({ ...decoded, ...change }), key, 10_001), null);
  }
  assert.equal(intent.readRecoveryIntent(grant({}, 10_000), key, 609_999).sessionId, sessionId);
  assert.equal(intent.recoveryCookieOptions.maxAge, 600);
  assert.equal(intent.recoveryCookieOptions.path, "/");
  const requestIntent = intent.mintRecoveryIntent({ kind: "request", email: "synthetic@example.invalid", verifierHash: intent.verifierDigest("verifier"), next }, key);
  return contextHarness({ cookie: requestIntent }).run().then(result => assert.equal(result.kind, "invalid-link"));
});
test("recovery availability requires a configured canonical origin and server signing key", () => {
  for (const [env, expected] of [
    [{ SITE_URL: undefined }, false], [{ SITE_URL: "not-a-url" }, false],
    [{ SITE_URL: "https://user:password@talli.example" }, false], [{ SITE_URL: "http://talli.example" }, false],
    [{ SITE_URL: "http://localhost:3000" }, true], [{ SUPABASE_SERVICE_ROLE_KEY: "short" }, false],
    [{ SITE_URL: undefined, NEXT_PUBLIC_SITE_URL: "https://talli.example" }, true],
  ]) {
    const module = compile("lib/auth-recovery-context.ts", {
      "next/headers": {}, "./supabase/server": { hasSupabaseEnv: () => true },
      "./auth-recovery-intent": { ...intent, recoverySigningSecret: () => (env.SUPABASE_SERVICE_ROLE_KEY ?? key).length >= 32 ? key : null },
    }, env);
    assert.equal(module.hasAuthRecoveryEnv(), expected);
  }
});
test("unconfigured or unsafe-origin requests never reach email delivery", async () => {
  for (const options of [{ configured: false }, { site: "http://outside.example" }, { site: "https://user:pass@talli.example" }]) {
    const h = actionHarness(options);
    assert.equal((await h.requestPasswordRecovery({ status: "idle" }, fields())).reason, "unavailable");
    assert.equal(h.calls.some(call => call.reset), false);
  }
});

test("unknown password outcome survives server rerender with no write form or Auth read", async () => {
  const page = compile("(auth)/reset-password/page.tsx", {
    "next/link": { __esModule: true, default: "a" },
    "../../components/ui": { Banner: "banner", SubmitButton: "button" },
    "../../lib/auth-recovery-context": { passwordRecoveryContext: () => { throw new Error("unknown outcome must not read Auth"); } },
    "../../lib/auth-recovery-presentation": presentation,
    "../recovery-actions": { leaveAccountForRecovery: () => { throw new Error("must not write"); } },
    "./ResetPasswordForm": { ResetPasswordForm: "reset-password-form" },
  }).default;
  const collect = element => !element || typeof element !== "object" ? [] : Array.isArray(element)
    ? element.flatMap(collect) : [element, ...collect(element.props?.children)];
  for (const [requested, expected] of [[next, next], ["https://outside.example", "/dashboard"]]) {
    const nodes = collect(await page({ searchParams: Promise.resolve({ error: "password-unknown", next: requested }) }));
    assert.equal(nodes.some(node => ["form", "reset-password-form"].includes(node.type)), false);
    assert.ok(nodes.some(node => node.props.children === presentation.authRecoveryMessage["password-unknown"]));
    const signIn = new URL(nodes.find(node => node.props.children === "Prøv å logge inn").props.href, "https://talli.example");
    assert.equal(signIn.pathname, "/login"); assert.equal(signIn.searchParams.get("reauth"), "1");
    assert.equal(signIn.searchParams.get("next"), expected);
    const newLink = new URL(nodes.find(node => node.props.children === "Be om en ny lenke").props.href, "https://talli.example");
    assert.equal(newLink.pathname, "/forgot-password"); assert.equal(newLink.searchParams.get("next"), expected);
  }
});

for (const [error, reason] of [[{ status: 400, code: "weak_password" }, "password-rejected"],
  [{ status: 403, code: "insufficient_aal" }, "mfa"]]) {
  test(`definite ${error.code} rejection keeps its actionable recovery state`, async () => {
    const h = actionHarness({ updateError: error });
    assert.equal((await h.updateRecoveredPassword({ status: "idle" }, fields())).reason, reason);
    assert.equal(h.calls.filter(call => call.update).length, 1);
    assert.equal(h.calls.some(call => call.signOut), false);
    assert.equal(h.calls.includes(`delete:${intent.RECOVERY_GRANT_COOKIE}`), false);
  });
}
