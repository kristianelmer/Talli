import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { TalliApiError } from "@talli/talli-api-client";
import { loadCompanyAccessContext } from "../features/company-access/transport/load-company-access-context.ts";
import { backendClientOptions } from "../lib/backend-configuration.ts";
import { BackendTransportError, createPreviewBackendFetch } from "../lib/protected-backend-fetch.ts";

const origin = "https://backend-preview.example";
const token = "synthetic.platform.signature";

function scopeEnvironment(t, values) {
  for (const [key, value] of Object.entries(values)) {
    const previous = process.env[key];
    t.after(() => previous === undefined ? delete process.env[key] : process.env[key] = previous);
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
}

function stableError(code) {
  return error => error instanceof BackendTransportError && error.code === code
    && error.message === code && error.cause === undefined;
}

test("one protected request retains user auth, command identity, body, cancellation and application response", async () => {
  const body = new Uint8Array([0, 1, 255]);
  const controller = new AbortController();
  const response = Response.json({ code: "AUTHENTICATION_REQUIRED" }, { status: 401 });
  let calls = 0;
  const send = createPreviewBackendFetch({ backendOrigin: origin, tokenProvider: async () => token,
    fetchImplementation: async (url, init) => {
      calls++;
      assert.equal(url, origin + "/api/v1/example?companyId=company");
      assert.equal(init.method, "POST");
      assert.equal(init.body, body);
      assert.equal(init.signal, controller.signal);
      assert.equal(init.headers.get("authorization"), "Bearer user-proof");
      assert.equal(init.headers.get("idempotency-key"), "command-proof");
      assert.equal(init.headers.get("x-vercel-trusted-oidc-idp-token"), token);
      assert.equal(init.redirect, "error");
      assert.equal(init.cache, "no-store");
      return response;
    } });
  const headers = { Authorization: "Bearer user-proof", "Idempotency-Key": "command-proof" };
  assert.equal(await send(origin + "/api/v1/example?companyId=company", {
    method: "POST", body, signal: controller.signal, headers, redirect: "follow", cache: "force-cache",
  }), response);
  assert.equal(calls, 1);
  assert.deepEqual(headers, { Authorization: "Bearer user-proof", "Idempotency-Key": "command-proof" });
});

for (const url of ["https://outsider.example/path", origin + ".outsider.example/path",
  "http://backend-preview.example/path", "https://backend-preview.example:444/path",
  "https://user:private@backend-preview.example/path", origin + "/path#fragment"]) {
  test("refuses an unbound request before resolving or sending credentials: " + new URL(url).origin, async () => {
    let calls = 0;
    const send = createPreviewBackendFetch({ backendOrigin: origin,
      tokenProvider: async () => { calls++; return token; },
      fetchImplementation: async () => { calls++; return new Response(); } });
    await assert.rejects(send(url), stableError("BACKEND_REQUEST_OUTSIDE_ORIGIN"));
    assert.equal(calls, 0);
  });
}

for (const header of ["X-Vercel-Trusted-Oidc-Idp-Token", "x-vercel-oidc-token", "x-vercel-protection-bypass"]) {
  test("rejects caller-supplied protection credentials: " + header, async () => {
    let calls = 0;
    const send = createPreviewBackendFetch({ backendOrigin: origin,
      tokenProvider: async () => { calls++; return token; },
      fetchImplementation: async () => { calls++; return new Response(); } });
    await assert.rejects(send(new Request(origin + "/path", { headers: { [header]: "caller-value" } })),
      stableError("BACKEND_CALLER_PROTECTION_HEADER_DENIED"));
    await assert.rejects(send(origin + "/path", { headers: { [header]: "caller-value" } }),
      stableError("BACKEND_CALLER_PROTECTION_HEADER_DENIED"));
    assert.equal(calls, 0);
  });
}

for (const value of ["", "invalid", "a.b.c.extra", "a.b.\r\nsecret", "a".repeat(32_769)]) {
  test("an invalid platform token never reaches fetch (length " + value.length + ")", async () => {
    let calls = 0;
    const send = createPreviewBackendFetch({ backendOrigin: origin, tokenProvider: async () => value,
      fetchImplementation: async () => { calls++; return new Response(); } });
    await assert.rejects(send(origin + "/path"), stableError("BACKEND_OIDC_TOKEN_UNAVAILABLE"));
    assert.equal(calls, 0);
  });
}

test("token-resolution and fetch failures expose no credential-bearing cause and never retry", async () => {
  const privateError = new Error("credential-bearing upstream diagnostic");
  let calls = 0;
  const noToken = createPreviewBackendFetch({ backendOrigin: origin,
    tokenProvider: async () => { throw privateError; },
    fetchImplementation: async () => { calls++; return new Response(); } });
  await assert.rejects(noToken(origin + "/path"), stableError("BACKEND_OIDC_TOKEN_UNAVAILABLE"));
  assert.equal(calls, 0);
  const noNetwork = createPreviewBackendFetch({ backendOrigin: origin, tokenProvider: async () => token,
    fetchImplementation: async () => { calls++; throw privateError; } });
  await assert.rejects(noNetwork(origin + "/path"), stableError("BACKEND_FETCH_UNAVAILABLE"));
  assert.equal(calls, 1);
});

test("Request bodies and existing headers are preserved without mutating the caller", async () => {
  const request = new Request(origin + "/path", { method: "POST", body: "exact-body",
    headers: { Authorization: "Bearer user-proof", "Idempotency-Key": "command-proof" } });
  const send = createPreviewBackendFetch({ backendOrigin: origin, tokenProvider: async () => token,
    fetchImplementation: async (input, init) => {
      assert.equal(input, request);
      assert.equal(input.bodyUsed, false);
      assert.equal(init.headers.get("authorization"), "Bearer user-proof");
      assert.equal(init.headers.get("idempotency-key"), "command-proof");
      assert.equal(init.headers.get("x-extra"), "option-value");
      return new Response();
    } });
  await send(request, { headers: { "X-Extra": "option-value" } });
  assert.equal(request.bodyUsed, false);
  assert.equal(request.headers.has("x-vercel-trusted-oidc-idp-token"), false);
});

test("the platform credential cannot be resolved in a browser context", async t => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", { configurable: true, value: {} });
  t.after(() => previous ? Object.defineProperty(globalThis, "window", previous) : delete globalThis.window);
  const send = createPreviewBackendFetch({ backendOrigin: origin,
    tokenProvider: async () => { assert.fail("browser attempted token resolution"); },
    fetchImplementation: async () => { assert.fail("browser attempted platform request"); } });
  await assert.rejects(send(origin + "/path"), stableError("BACKEND_SERVER_CONTEXT_REQUIRED"));
});

function syntheticToken(id) {
  const encode = value => Buffer.from(JSON.stringify(value)).toString("base64url");
  return [encode({ alg: "RS256" }), encode({ exp: Math.floor(Date.now() / 1000) + 3_600, jti: id }), "local-proof"].join(".");
}

test("the real Company Access transport resolves current OIDC per request and preserves application 401", async t => {
  scopeEnvironment(t, { VERCEL_ENV: "preview", TALLI_BACKEND_URL: origin, VERCEL_OIDC_TOKEN: syntheticToken("first") });
  const previous = globalThis.fetch;
  t.after(() => globalThis.fetch = previous);
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: new URL(url), init });
    return Response.json({ code: "AUTHENTICATION_REQUIRED" }, { status: 401 });
  };
  const expectedTokens = [];
  for (const id of ["first", "second"]) {
    process.env.VERCEL_OIDC_TOKEN = syntheticToken(id);
    expectedTokens.push(process.env.VERCEL_OIDC_TOKEN);
    await assert.rejects(loadCompanyAccessContext("user-proof", "request-" + id),
      error => error instanceof TalliApiError && error.status === 401);
  }
  assert.equal(calls.length, 2);
  assert.notEqual(expectedTokens[0], expectedTokens[1]);
  for (const [index, { url, init }] of calls.entries()) {
    assert.equal(url.origin, origin);
    assert.equal(init.headers.get("authorization"), "Bearer user-proof");
    assert.equal(init.headers.get("x-vercel-trusted-oidc-idp-token"), expectedTokens[index]);
    assert.equal(init.redirect, "error");
    assert.equal(init.cache, "no-store");
  }
});

test("Preview configuration rejects another origin and insecure loopback without requesting a token", t => {
  scopeEnvironment(t, { VERCEL_ENV: "preview", TALLI_BACKEND_URL: origin });
  assert.throws(() => backendClientOptions({ baseUrl: "https://other.example" }),
    stableError("BACKEND_REQUEST_OUTSIDE_ORIGIN"));
  process.env.TALLI_BACKEND_URL = "http://127.0.0.1:8000";
  assert.throws(() => backendClientOptions(), stableError("BACKEND_ORIGIN_INVALID"));
});

for (const environment of [undefined, "development", "production"]) {
  test("ordinary fetch configuration is preserved outside Preview: " + environment, t => {
    scopeEnvironment(t, { VERCEL_ENV: environment });
    const options = { baseUrl: "http://127.0.0.1:8000", fetch: async () => new Response() };
    assert.equal(backendClientOptions(options), options);
  });
}

test("every feature SDK constructor uses the shared platform options without a later fetch/origin override", () => {
  const root = new URL("../features/", import.meta.url);
  let constructors = 0;
  function visitDirectory(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) visitDirectory(path);
      else if (entry.name.endsWith(".ts")) {
        const source = ts.createSourceFile(path, readFileSync(path, "utf8"), ts.ScriptTarget.Latest, true);
        function visit(node) {
          if (ts.isCallExpression(node) && node.expression.getText(source) === "createTalliApiClient") {
            constructors++;
            const options = node.arguments[0];
            assert.ok(ts.isObjectLiteralExpression(options), path);
            assert.equal(options.properties.filter(ts.isSpreadAssignment).length, 1, path);
            for (const property of options.properties) {
              if (ts.isSpreadAssignment(property)) {
                assert.ok(ts.isCallExpression(property.expression), path);
                assert.equal(property.expression.expression.getText(source), "backendClientOptions", path);
              } else assert.equal(property.name.getText(source), "headers", path);
            }
          }
          ts.forEachChild(node, visit);
        }
        visit(source);
      }
    }
  }
  visitDirectory(fileURLToPath(root));
  assert.ok(constructors > 0);
});
