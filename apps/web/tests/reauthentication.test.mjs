import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import ts from "typescript";

const require = createRequire(import.meta.url);
const source = path => readFileSync(new URL(`../app/${path}`, import.meta.url), "utf8");
function compile(text, dependencies = {}, globals = {}) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(text, { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText, { exports, require: name => name in dependencies ? dependencies[name] : require(name),
    URL, URLSearchParams, Error, ...globals });
  return exports;
}
const { sanitizeInternalRedirect } = compile(source("lib/internal-redirect.ts"));
const next = "/billing?companyId=10000000-0000-4000-8000-000000000002&beforePurchaseId=10000000-0000-4000-8000-000000000003&refundPurchaseId=10000000-0000-4000-8000-000000000004&refundRequestId=10000000-0000-4000-8000-000000000201&beforeRefundRequestId=10000000-0000-4000-8000-000000000202";
const redirect = href => { throw new Error(`redirect:${href}`); };
function fields(element) {
  if (!element || typeof element !== "object") return [];
  if (Array.isArray(element)) return element.flatMap(fields);
  return [...(element.type === "input" ? [[element.props.name, element.props.value]] : []), ...fields(element.props?.children)];
}
function entry({ user = { email_confirmed_at: "2026-09-06" }, configured = true, continuation = null } = {}) {
  const calls = [];
  const server = { hasSupabaseEnv: () => configured,
    getCurrentUser: async () => { calls.push("read-user"); return user; },
    needsEmailVerification: value => !value.email_confirmed_at,
    createSupabaseServerClient: () => { throw new Error("GET must not mutate session"); } };
  const common = {
    "next/navigation": { redirect }, "next/link": () => null,
    "../../components/ui": { Banner: () => null, FormField: () => null, SubmitButton: () => null },
    "../../actions": { signIn: async () => {}, signUp: async () => {} },
    "../../lib/supabase/server": server,
    "../../lib/copy": { ownerCopy: { brand: "Talli", auth: {} } },
    "../../lib/internal-redirect": { sanitizeInternalRedirect },
    "../../lib/eligibility-continuation": { readEligibilityContinuation: async () => { calls.push("read-eligibility"); return continuation; } },
    "../GoogleSignInButton": { GoogleSignInButton: () => null },
  };
  const layout = compile(source("(auth)/layout.tsx"), {
    "next/navigation": { redirect }, "../lib/supabase/server": server,
  }).default;
  const page = route => compile(source(`(auth)/${route}/page.tsx`), common).default;
  return { calls, page, run: async (params, route = "login") => layout({
    children: await page(route)({ searchParams: Promise.resolve(params) }),
  }) };
}

test("explicit reauthentication displays the login form despite a backend-rejected but valid Supabase session", async () => {
  const harness = entry();
  const rendered = await harness.run({ reauth: "1", next });
  const values = Object.fromEntries(fields(rendered));
  assert.equal(values.reauth, "1");
  assert.equal(values.next, next);
  assert.deepEqual(harness.calls, ["read-user"]);
});

test("ordinary signed-in login and signup redirects and unconfirmed-user gate remain intact", async () => {
  for (const route of ["login", "signup"]) {
    for (const reauth of [undefined, "0", "true", ["1", "1"]]) {
      const harness = entry();
      await assert.rejects(harness.run({ next, reauth }, route), /redirect:\/dashboard/);
      assert.deepEqual(harness.calls, ["read-user"]);
    }
    await assert.rejects(entry({ user: {} }).run({ next, reauth: "1" }, route), /redirect:\/verify-email/);
  }
  await assert.rejects(entry().run({ next, reauth: "1" }, "signup"), /redirect:\/dashboard/);
  await assert.rejects(entry({ user: null }).run({ next }, "signup"), /redirect:\/sjekk-selskapet/);
  const page = await entry({ user: null }).run({ reauth: "1", next: "https://outside.example" });
  assert.equal(Object.fromEntries(fields(page)).next, "/dashboard");
});

const actions = source("actions.ts");
function action(name, following, { error = null, configured = true, url = "https://accounts.example/authorize" } = {}) {
  const calls = [];
  const code = actions.slice(actions.indexOf(`export async function ${name}(`), actions.indexOf(`export async function ${following}(`));
  const run = compile(code, {}, {
    sanitizeInternalRedirect, formString: (data, key) => data.get(key) ?? "", redirect,
    hasSupabaseEnv: () => configured, getSiteUrl: async () => "https://talli.example",
    createSupabaseServerClient: async () => ({ auth: {
      signInWithPassword: async data => { calls.push({ password: true, email: data.email }); return { error }; },
      signInWithOAuth: async data => { calls.push(data); return { data: { url }, error }; },
    } }), revalidatePath: path => calls.push({ revalidate: path }),
  })[name];
  return { run, calls };
}
function form(extra = {}) {
  const data = new FormData();
  for (const [key, value] of Object.entries({ next, reauth: "1", email: "synthetic@example.invalid", password: "synthetic-only", ...extra })) data.set(key, value);
  return data;
}
async function destination(promise) {
  let result;
  await assert.rejects(promise, error => {
    assert.match(error.message, /^redirect:/); result = new URL(error.message.slice(9), "https://talli.example"); return true;
  });
  return result;
}
for (const [name, following] of [["signIn", "signUp"], ["signInWithGoogle", "signOut"]]) {
  test(`${name} preserves explicit reauthentication and next through failures`, async () => {
    for (const options of [{ configured: false }, { error: { message: "Synthetic failure" } },
      ...(name === "signIn" ? [{ error: { code: "email_not_confirmed", message: "Email not confirmed" } }] : [{ url: null }])]) {
      const target = await destination(action(name, following, options).run(form()));
      assert.equal(target.pathname, "/login");
      assert.equal(target.searchParams.get("reauth"), "1");
      assert.equal(target.searchParams.get("next"), next);
    }
  });
}
test("successful password login consumes recovery intent; ordinary unconfirmed credentials keep verification recovery", async () => {
  const success = await destination(action("signIn", "signUp").run(form()));
  assert.equal(success.pathname + success.search, next);
  const ordinary = await destination(action("signIn", "signUp", { error: { code: "email_not_confirmed", message: "Email not confirmed" } }).run(form({ reauth: "0" })));
  assert.equal(ordinary.pathname, "/verify-email");
});
test("Google startup carries recovery through its callback URL", async () => {
  const harness = action("signInWithGoogle", "signOut");
  await destination(harness.run(form()));
  const callback = new URL(harness.calls[0].options.redirectTo);
  assert.equal(callback.pathname, "/auth/confirm");
  assert.equal(callback.searchParams.get("reauth"), "1");
  assert.equal(callback.searchParams.get("next"), next);
});

test("the Google form carries the same explicit recovery intent as password sign-in", () => {
  const { GoogleSignInButton } = compile(source("(auth)/GoogleSignInButton.tsx"), {
    "../actions": { signInWithGoogle: async () => {} },
    "../components/ui": { SubmitButton: () => null },
    "../lib/supabase/server": { hasSupabaseEnv: () => true },
    "../lib/copy": { ownerCopy: { auth: {} } },
  });
  assert.deepEqual(Object.fromEntries(fields(GoogleSignInButton({ next, reauthenticate: true }))), { next, reauth: "1" });
  assert.deepEqual(Object.fromEntries(fields(GoogleSignInButton({ next }))), { next });
});

function callback({ error = null, configured = true, throws = false } = {}) {
  const calls = [];
  const auth = { exchangeCodeForSession: async () => { calls.push("exchange"); if (throws) throw new Error("private token"); return { error }; },
    verifyOtp: async () => { calls.push("otp"); return { error }; } };
  const run = compile(source("auth/confirm/route.ts"), {
    "next/server": { NextResponse: { redirect: url => url } },
    "../../lib/supabase/server": { hasSupabaseEnv: () => configured, createSupabaseServerClient: async () => ({ auth }) },
    "../../lib/internal-redirect": { sanitizeInternalRedirect },
  }).GET;
  return { calls, run: async (params = {}) => run({ nextUrl: new URL(`https://talli.example/auth/confirm?${new URLSearchParams({ next, reauth: "1", ...params })}`) }) };
}
test("denied, missing, failed and unavailable OAuth callbacks return to an actionable recovery login", async () => {
  for (const [options, params] of [[{}, { error: "access_denied" }], [{}, {}], [{ error: {} }, { code: "synthetic" }],
    [{ throws: true }, { code: "synthetic" }], [{ configured: false }, { code: "synthetic" }]]) {
    const target = await callback(options).run(params);
    assert.equal(target.pathname, "/login");
    assert.equal(target.searchParams.get("reauth"), "1");
    assert.equal(target.searchParams.get("next"), next);
    assert.doesNotMatch(target.href, /private token/);
    await entry().run(Object.fromEntries(target.searchParams));
  }
});
test("successful callback returns to the scoped page while ordinary email confirmation failure is unchanged", async () => {
  const target = await callback().run({ code: "synthetic" });
  assert.equal(target.pathname + target.search, next);
  assert.equal((await callback({ error: {} }).run({ code: "synthetic", reauth: "0" })).pathname, "/verify-email");
});
