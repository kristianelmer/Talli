import assert from "node:assert/strict";
import test, { after } from "node:test";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { createHash, createHmac, generateKeyPairSync, sign, verify, createPublicKey } from "node:crypto";
import { performance } from "node:perf_hooks";
import { ORIGINS, validateManifest, readFixtureManifest, admitFixture, appendOwnership, makeBoundedFetch, jsonResponse, listMail, mailOwnership, createOwnedUsers, makeExpiryPair, checkedExpiryPair, cleanupOwned, runWithCleanup, boundedClose } from "./support/auth_recovery_fixture.mjs";

// Every HTTP response below is generated; an accidental real fetch is a failure.
const originalFetch = globalThis.fetch;
globalThis.fetch = () => { throw Error("unexpected_real_fetch"); };
after(() => { globalThis.fetch = originalFetch; });
const runId = "a0000000-0000-4000-8000-000000000000";
const ids = ["a0000000-0000-4000-8000-000000000001", "a0000000-0000-4000-8000-000000000002"];
const manifest = () => ({ version: 1, runId, targetAdmissionSha256: "1".repeat(64), sourceSha256: "2".repeat(64), buildSha256: "3".repeat(64), origins: { ...ORIGINS }, database: { host: "127.0.0.1", port: 57748, user: "postgres", database: "postgres" }, context: "colima-talli-frontend-dd88-20261010", users: ids.map((id, index) => ({ id, email: "auth-browser-" + runId + (index ? "-bob" : "-alice") + "@example.invalid" })) });
const settings = () => ({ SUPABASE_URL: ORIGINS.api, TALLI_AUTH_TEST_MAIL_URL: ORIGINS.mail, TALLI_AUTH_TEST_WEB_PORT: "50916", DOCKER_CONTEXT: manifest().context, SUPABASE_ANON_KEY: "synthetic-anon", SUPABASE_SERVICE_ROLE_KEY: "synthetic-service", DATABASE_URL: "postgresql://postgres:synthetic%40password@127.0.0.1:57748/postgres", TALLI_AUTH_TEST_JWT_SECRET: "synthetic-signing-secret" });
const response = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
const digest = bytes => createHash("sha256").update(bytes).digest("hex");
const end = () => performance.now() + 10000;
const bounded = fetchImpl => makeBoundedFetch({ origin: ORIGINS.api, deadline: end(), fetchImpl });

test("discrete PostgreSQL configuration keeps private password but no URL/parser overrides", () => {
  const value = admitFixture(manifest(), settings());
  assert.deepEqual(value.database, { host: "127.0.0.1", port: 57748, user: "postgres", database: "postgres", password: "synthetic@password", ssl: false, connectionTimeoutMillis: 5000, query_timeout: 5000, statement_timeout: 5000, application_name: "talli-owned-auth-recovery" });
  assert.equal(Object.hasOwn(value.database, "connectionString"), false);
  assert.ok(Object.isFrozen(value.manifest.users[0]));
});
for (const suffix of ["?host=remote.invalid", "?port=443", "?options=-c", "?sslcert=/tmp/key", "?", "#", "#fragment"]) test("PG query/fragment rejected: " + suffix, () => {
  assert.throws(() => admitFixture(manifest(), { ...settings(), DATABASE_URL: settings().DATABASE_URL + suffix }), /fixture_database/u);
});
for (const [key, value] of [
  ["SUPABASE_URL", "http://localhost:57747"], ["SUPABASE_URL", ORIGINS.api + "/"], ["SUPABASE_URL", "http://user@127.0.0.1:57747"], ["SUPABASE_URL", "http://127.1:57747"], ["SUPABASE_URL", ORIGINS.api + "?x=1"], ["SUPABASE_URL", ORIGINS.api + "#x"], ["SUPABASE_URL", "https://127.0.0.1:57747"], ["TALLI_AUTH_TEST_MAIL_URL", ORIGINS.api], ["TALLI_AUTH_TEST_WEB_PORT", "0"], ["TALLI_AUTH_TEST_WEB_PORT", "050916"], ["DOCKER_CONTEXT", "colima-talli"], ["SUPABASE_SERVICE_ROLE_KEY", ""], ["SUPABASE_ANON_KEY", "a\nb"], ["DATABASE_URL", "postgresql://postgres:secret@127.0.0.1:5432/postgres"], ["DATABASE_URL", "postgresql://other:secret@127.0.0.1:57748/postgres"]
]) test("exact admission rejects " + key + ":" + value.replace(/secret/gu, "synthetic"), () => assert.throws(() => admitFixture(manifest(), { ...settings(), [key]: value })));
test("missing signing material refuses before any client or user", () => { const env = settings(); delete env.TALLI_AUTH_TEST_JWT_SECRET; assert.throws(() => admitFixture(manifest(), env), /fixture_signing_material/u); });
for (const [label, change] of [
  ["extra key", m => { m.extra = true; }], ["duplicate id", m => { m.users[1].id = m.users[0].id; }], ["foreign email", m => { m.users[0].email = "other@example.invalid"; }], ["noncanonical UUID", m => { m.runId = m.runId.toUpperCase(); }], ["changed origin", m => { m.origins.api += "/"; }], ["missing target pin", m => { delete m.targetAdmissionSha256; }]
]) test("closed caller manifest refuses " + label, () => { const value = manifest(); change(value); assert.throws(() => validateManifest(value)); });

test("persisted private manifest pin, permissions and ownership journal", async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "auth-fixture-generated-"));
  try {
    await fs.chmod(dir, 0o700);
    const file = path.join(dir, "manifest.json"), bytes = JSON.stringify(manifest());
    await fs.writeFile(file, bytes, { mode: 0o600 });
    await fs.writeFile(path.join(dir, "ownership.ndjson"), "", { mode: 0o600 });
    assert.deepEqual(await readFixtureManifest(file, digest(bytes)), manifest());
    await appendOwnership(file, digest(bytes), { kind: "browser", pid: 12345 });
    assert.deepEqual(JSON.parse(await fs.readFile(path.join(dir, "ownership.ndjson"), "utf8")), { manifestSha256: digest(bytes), kind: "browser", pid: 12345 });
    await assert.rejects(readFixtureManifest(file, "0".repeat(64)), /fixture_manifest_pin/u);
    await assert.rejects(appendOwnership(file, digest(bytes), { kind: "foreign", pid: 12345 }));
    await fs.chmod(file, 0o644); await assert.rejects(readFixtureManifest(file, digest(bytes)), /fixture_private_file/u); await fs.chmod(file, 0o600);
    const link = path.join(dir, "alias.json"); await fs.symlink(file, link); await assert.rejects(readFixtureManifest(link, digest(bytes)));
    await fs.unlink(path.join(dir, "ownership.ndjson")); await assert.rejects(appendOwnership(file, digest(bytes), { kind: "next", pid: 12345 }));
  } finally { await fs.rm(dir, { recursive: true, force: true }); }
});

test("create sends exact pre-owned UUID/email and rejects uncertain result without retry", async () => {
  const admitted = admitFixture(manifest(), settings()); const calls = [];
  const admin = { auth: { admin: { createUser: async attributes => { calls.push(attributes); return calls.length === 1 ? { data: { user: attributes }, error: null } : { data: { user: null }, error: { code: "network" } }; } } } };
  await assert.rejects(createOwnedUsers(admitted, admin, "synthetic-password"), /fixture_create_unconfirmed/u);
  assert.deepEqual(calls.map(({ id, email }) => ({ id, email })), manifest().users);
});
test("unexpected server UUID cannot widen cleanup ownership", async () => {
  await assert.rejects(createOwnedUsers(admitFixture(manifest(), settings()), { auth: { admin: { createUser: async attributes => ({ data: { user: { ...attributes, id: "foreign" } } }) } } }, "synthetic"), /fixture_create_unconfirmed/u);
});
for (const url of ["https://remote.invalid/auth/v1/user", ORIGINS.mail + "/auth/v1/user", ORIGINS.api + "/rest/v1/users", "http://name@127.0.0.1:57747/auth/v1/user", ORIGINS.api + "/auth/v1/user#x"]) test("bounded fetch refuses target before dispatch " + url, async () => {
  let calls = 0; const fetch = bounded(async () => { calls++; return response({}); });
  await assert.rejects(fetch(url)); assert.equal(calls, 0);
});
test("bounded fetch preserves SDK JSON/status and request authority", async () => {
  const fetch = bounded(async (url, init) => { assert.equal(init.redirect, "error"); assert.equal(init.headers.Authorization, "private-synthetic"); return response({ error_code: "bad_jwt" }, 401); });
  const result = await fetch(ORIGINS.api + "/auth/v1/user", { headers: { Authorization: "private-synthetic" } });
  assert.equal(result.status, 401); assert.deepEqual(await jsonResponse(result), { error_code: "bad_jwt" });
});
test("bounded fetch rejects redirects, oversized chunked bodies and expired budget", async () => {
  await assert.rejects(bounded(async () => new Response(null, { status: 302, headers: { location: ORIGINS.api + "/auth/v1/user" } }))(ORIGINS.api + "/auth/v1/user"), /fixture_fetch_redirect/u);
  await assert.rejects(bounded(async () => new Response(new Uint8Array(262145)))(ORIGINS.api + "/auth/v1/user"), /fixture_fetch_limit/u);
  const exact = await bounded(async () => new Response(new Uint8Array(262144)))(ORIGINS.api + "/auth/v1/user"); assert.equal((await exact.arrayBuffer()).byteLength, 262144);
  let calls = 0; await assert.rejects(makeBoundedFetch({ origin: ORIGINS.api, deadline: performance.now() - 1, fetchImpl: async () => { calls++; } })(ORIGINS.api + "/auth/v1/user"), /fixture_fetch_deadline/u); assert.equal(calls, 0);
});
test("body deadline is active after headers, including an uncooperative cancel", async () => {
  const fetch = makeBoundedFetch({ origin: ORIGINS.api, deadline: end(), requestMs: 15, fetchImpl: async () => new Response(new ReadableStream({ pull() { return new Promise(() => {}); }, cancel() { return new Promise(() => {}); } })) });
  await assert.rejects(fetch(ORIGINS.api + "/auth/v1/user"), /fixture_fetch_deadline/u);
});
test("cancellation identity survives body and reader cleanup failure", async () => {
  const sentinel = new Error("generated primary"); const abort = new AbortController(); let reached;
  const ready = new Promise(resolve => { reached = resolve; });
  const fetch = makeBoundedFetch({ origin: ORIGINS.api, deadline: end(), signal: abort.signal, fetchImpl: async () => ({ status: 200, headers: {}, url: "", redirected: false, body: { getReader: () => ({ read() { reached(); return new Promise(() => {}); }, cancel() { throw Error("secondary"); }, releaseLock() { throw Error("secondary lock"); } }) } }) });
  const pending = fetch(ORIGINS.api + "/auth/v1/user"); await ready; abort.abort(sentinel);
  await assert.rejects(pending, error => error === sentinel);
});
test("strict JSON refuses malformed UTF8 and excessive depth", async () => {
  await assert.rejects(jsonResponse(new Response(Uint8Array.from([0xff]))), /fixture_json/u);
  await assert.rejects(jsonResponse(response(JSON.parse("[".repeat(18) + "0" + "]".repeat(18)))), /fixture_json_depth/u);
});

test("mail pagination is bounded and finds a later exact owned recipient", async () => {
  const first = Array.from({ length: 100 }, (_, i) => ({ ID: "m" + i, To: [{ Address: "foreign@example.invalid" }] }));
  const owned = { ID: "owned", To: [{ Address: manifest().users[0].email }] }; const calls = [];
  const result = await listMail(async url => { calls.push(url); return response({ total: 101, messages: calls.length === 1 ? first : [owned] }); });
  assert.equal(result.length, 101); assert.equal(mailOwnership(result[100], manifest().users), "owned"); assert.match(calls[1], /start=100&limit=100$/u);
  assert.equal(mailOwnership({ ...owned, Cc: [{ Address: "foreign@example.invalid" }] }, manifest().users), "mixed");
});
for (const [label, data] of [["duplicate", { total: 2, messages: [{ ID: "same" }, { ID: "same" }] }], ["partial", { total: 1, messages: [] }], ["limit", { total: 1001, messages: [] }]]) test("mail inventory refuses " + label, async () => await assert.rejects(listMail(async () => response(data))));

const encoded = value => Buffer.from(JSON.stringify(value)).toString("base64url");
function generatedJwt(algorithm) {
  const claims = { sub: ids[0], role: "authenticated", session_id: "s", exp: 2000, iat: 900, aud: "authenticated" };
  const header = { alg: algorithm, typ: "JWT", kid: "generated-key" };
  const body = encoded(header) + "." + encoded(claims);
  if (algorithm === "HS256") { const secret = "generated-private-secret"; return { session: { access_token: body + "." + createHmac("sha256", secret).update(body).digest("base64url") }, signingMaterial: { secret } }; }
  const { privateKey } = generateKeyPairSync("ec", { namedCurve: "P-256" }); const jwk = { ...privateKey.export({ format: "jwk" }), kid: header.kid, alg: "ES256", use: "sig" };
  return { session: { access_token: body + "." + sign("sha256", Buffer.from(body), { key: privateKey, dsaEncoding: "ieee-p1363" }).toString("base64url") }, signingMaterial: { jwk } };
}
for (const algorithm of ["HS256", "ES256"]) {
  test(algorithm + " positive control and expired token differ only in exp with authentic signatures", async () => {
    const generated = generatedJwt(algorithm); const seen = [];
    const pair = await checkedExpiryPair({ ...generated, expectedUser: ids[0], nowSeconds: 1000, getUser: async token => {
      seen.push(token); const [header, payload, sig] = token.split("."); const signed = Buffer.from(header + "." + payload);
      if (algorithm === "HS256") assert.equal(createHmac("sha256", generated.signingMaterial.secret).update(signed).digest("base64url"), sig);
      else assert.ok(verify("sha256", signed, { key: createPublicKey({ key: generated.signingMaterial.jwk, format: "jwk" }), dsaEncoding: "ieee-p1363" }, Buffer.from(sig, "base64url")));
      return JSON.parse(Buffer.from(payload, "base64url")).exp > 1000 ? { data: { user: { id: ids[0] } }, error: null } : { data: { user: null }, error: { status: 403, code: "bad_jwt" } };
    } });
    assert.equal(seen.length, 3); assert.equal(pair.algorithm, algorithm);
    const positive = JSON.parse(Buffer.from(pair.positive.split(".")[1], "base64url")), expired = JSON.parse(Buffer.from(pair.expired.split(".")[1], "base64url"));
    assert.equal(positive.exp, 1300); assert.equal(expired.exp, 940); delete positive.exp; delete expired.exp; assert.deepEqual(positive, expired);
  });
  test(algorithm + " wrong signing material cannot pass the control", () => {
    const generated = generatedJwt(algorithm);
    const wrong = algorithm === "HS256" ? { secret: "wrong" } : generatedJwt("ES256").signingMaterial;
    assert.throws(() => makeExpiryPair({ session: generated.session, signingMaterial: wrong, expectedUser: ids[0], nowSeconds: 1000 }), /fixture_signing_control/u);
  });
}
test("ES256 kid mismatch, wrong curve and unsupported alg refuse", () => {
  const value = generatedJwt("ES256"); value.signingMaterial.jwk.kid = "other";
  assert.throws(() => makeExpiryPair({ ...value, expectedUser: ids[0], nowSeconds: 1000 }), /fixture_signing_kid/u);
  value.signingMaterial.jwk.crv = "P-384"; assert.throws(() => makeExpiryPair({ ...value, expectedUser: ids[0], nowSeconds: 1000 }));
  const h = generatedJwt("HS256"); h.session.access_token = encoded({ alg: "none" }) + "." + h.session.access_token.split(".").slice(1).join(".");
  assert.throws(() => makeExpiryPair({ ...h, expectedUser: ids[0], nowSeconds: 1000 }), /fixture_jwt_header/u);
});
test("failed positive control prevents the expired probe; unexpected/cancel error stays identical", async () => {
  const value = generatedJwt("HS256"); let calls = 0;
  await assert.rejects(checkedExpiryPair({ ...value, expectedUser: ids[0], nowSeconds: 1000, getUser: async () => { calls++; return calls === 1 ? { data: { user: { id: ids[0] } } } : { error: { status: 401 } }; } }), /fixture_expiry_positive_control/u); assert.equal(calls, 2);
  const sentinel = new Error("cancel"); await assert.rejects(checkedExpiryPair({ ...value, expectedUser: ids[0], nowSeconds: 1000, getUser: async () => { throw sentinel; } }), e => e === sentinel);
});
test("transport failure is not an expired-token rejection", async () => {
  let calls = 0; await assert.rejects(checkedExpiryPair({ ...generatedJwt("HS256"), expectedUser: ids[0], nowSeconds: 1000, getUser: async () => ++calls < 3 ? { data: { user: { id: ids[0] } } } : { error: { status: 0 } } }), /fixture_expiry_negative_control/u);
});

function cleanupModel({ failFirst = false, conflict = false, mixed = false, late = false } = {}) {
  const admitted = admitFixture(manifest(), settings());
  const users = new Map(admitted.manifest.users.map(user => [user.id, { ...user }]));
  if (conflict) users.get(ids[0]).email = "foreign@example.invalid";
  const messages = new Map([["own", { ID: "own", To: [{ Address: admitted.manifest.users[0].email }], ...(mixed ? { Cc: [{ Address: "foreign@example.invalid" }] } : {}) }], ["foreign", { ID: "foreign", To: [{ Address: "foreign@example.invalid" }] }]]);
  const calls = []; let lists = 0;
  const fetchImpl = async (input, init) => {
    const url = new URL(input); calls.push([init.method || "GET", url.pathname]);
    if (url.pathname === "/auth/v1/admin/users") return response({ users: [...users.values()] });
    if (url.pathname.startsWith("/auth/v1/admin/users/")) {
      const id = url.pathname.split("/").at(-1);
      if (init.method === "DELETE") { if (failFirst && id === ids[0]) throw Error("synthetic deletion failure"); users.delete(id); return response({}); }
      return users.has(id) ? response(users.get(id)) : response({ error_code: "user_not_found" }, 404);
    }
    if (url.pathname === "/api/v1/messages") {
      if (init.method === "DELETE") { JSON.parse(init.body).IDs.forEach(id => messages.delete(id)); return response({}); }
      lists++; if (late && lists === 3) messages.set("late", { ID: "late", To: [{ Address: admitted.manifest.users[1].email }] });
      return response({ total: messages.size, messages: [...messages.values()] });
    }
    throw Error("unexpected generated endpoint");
  };
  return { admitted, users, messages, calls, fetchImpl };
}
test("independent cleanup reconciles both persisted users including a lost create response", async () => {
  const model = cleanupModel(); const result = await cleanupOwned({ ...model, deadline: end(), pause: async () => {} });
  assert.deepEqual(result, { complete: true, errors: [], usersAbsent: true, mailAbsent: true }); assert.equal(model.users.size, 0); assert.deepEqual([...model.messages.keys()], ["foreign"]);
});
test("failed first user cleanup never prevents second user or mail; failure remains incomplete", async () => {
  const model = cleanupModel({ failFirst: true }); const result = await cleanupOwned({ ...model, deadline: end(), pause: async () => {} });
  assert.equal(result.complete, false); assert.ok(result.errors.includes("user_cleanup")); assert.ok(model.users.has(ids[0])); assert.equal(model.users.has(ids[1]), false); assert.equal(model.messages.has("own"), false);
});
test("foreign identity and mixed-recipient mail are never deleted", async () => {
  const model = cleanupModel({ conflict: true, mixed: true }); const result = await cleanupOwned({ ...model, deadline: end(), pause: async () => {} });
  assert.equal(result.complete, false); assert.ok(model.users.has(ids[0])); assert.ok(model.messages.has("own")); assert.equal(model.calls.some(([method, url]) => method === "DELETE" && url.endsWith(ids[0])), false);
});
test("late mail and exhausted cleanup budget cannot claim absence", async () => {
  const model = cleanupModel({ late: true }); assert.equal((await cleanupOwned({ ...model, deadline: end(), pause: async () => {} })).complete, false);
  const expired = cleanupModel(); assert.equal((await cleanupOwned({ ...expired, deadline: performance.now() - 1, pause: async () => {} })).complete, false); assert.equal(expired.calls.length, 0);
});
test("body primary survives cleanup error, while cleanup failure rejects success", async () => {
  const primary = new Error("body failure"); let cleaned = false;
  await assert.rejects(runWithCleanup(async () => { throw primary; }, async () => { cleaned = true; throw Error("cleanup"); }), e => e === primary); assert.ok(cleaned);
  await assert.rejects(runWithCleanup(async () => {}, async () => ({ complete: false })), /fixture_cleanup_incomplete/u);
  await assert.rejects(boundedClose(() => new Promise(() => {}), 5), /fixture_close_deadline/u);
});

for (const name of ["PGHOST", "PGPORT", "PGOPTIONS", "PGSSLCERT", "NODE_OPTIONS", "NODE_USE_ENV_PROXY", "HTTPS_PROXY"]) test("ambient effective-endpoint override refused: " + name, () => {
  assert.throws(() => admitFixture(manifest(), { ...settings(), [name]: "generated-override" }), /fixture_environment_override/u);
});
test("ES256-only admission does not require or fall back to an HS256 secret", () => {
  const env = settings(); delete env.TALLI_AUTH_TEST_JWT_SECRET;
  env.TALLI_AUTH_TEST_JWT_PRIVATE_JWK = JSON.stringify(generatedJwt("ES256").signingMaterial.jwk);
  assert.equal(admitFixture(manifest(), env).signingMaterial.secret, undefined);
  env.TALLI_AUTH_TEST_JWT_PRIVATE_JWK = "{}"; assert.throws(() => admitFixture(manifest(), env));
});
test("real installed SDK forwards the caller UUID through the bounded fetch boundary", async () => {
  const { createClient } = await import("@supabase/supabase-js");
  const admitted = admitFixture(manifest(), settings()); const sent = [];
  const fetch = bounded(async (url, init) => { assert.equal(String(url), ORIGINS.api + "/auth/v1/admin/users"); assert.equal(init.method, "POST"); const user = JSON.parse(init.body); sent.push(user); return response({ ...user, aud: "authenticated", role: "authenticated" }); });
  const admin = createClient(ORIGINS.api, "generated-private-service", { auth: { persistSession: false, autoRefreshToken: false }, global: { fetch } });
  await createOwnedUsers(admitted, admin, "generated-private-password");
  assert.deepEqual(sent.map(({ id, email }) => ({ id, email })), manifest().users);
});
test("a create that persists then throws is reconciled using only the preexisting manifest", async () => {
  const model = cleanupModel(); model.users.clear(); model.messages.clear(); const sentinel = new Error("lost generated response");
  const admin = { auth: { admin: { createUser: async user => { model.users.set(user.id, { id: user.id, email: user.email }); throw sentinel; } } } };
  await assert.rejects(createOwnedUsers(model.admitted, admin, "synthetic"), error => error === sentinel);
  assert.deepEqual([...model.users.keys()], [ids[0]]);
  const result = await cleanupOwned({ ...model, deadline: end(), pause: async () => {} });
  assert.equal(result.complete, true); assert.equal(model.users.size, 0);
});
test("cleanup cannot treat a generic gateway404 as known user absence", async () => {
  const model = cleanupModel(); model.users.clear(); model.messages.clear(); const inherited = model.fetchImpl;
  model.fetchImpl = (url, init) => new URL(url).pathname.includes("/users/") ? Promise.resolve(response({ message: "unknown" }, 404)) : inherited(url, init);
  const result = await cleanupOwned({ ...model, deadline: end(), pause: async () => {} });
  assert.equal(result.complete, false); assert.equal(result.errors.filter(x => x === "user_cleanup").length, 2);
});
test("an individual mail delete failure does not prevent later owned mail cleanup", async () => {
  const model = cleanupModel(); model.messages.set("second", { ID: "second", To: [{ Address: manifest().users[1].email }] }); const inherited = model.fetchImpl;
  model.fetchImpl = (url, init) => init.method === "DELETE" && new URL(url).pathname === "/api/v1/messages" && JSON.parse(init.body).IDs[0] === "own" ? Promise.reject(Error("generated mail delete failure")) : inherited(url, init);
  const result = await cleanupOwned({ ...model, deadline: end(), pause: async () => {} });
  assert.equal(result.complete, false); assert.equal(model.messages.has("second"), false); assert.equal(model.messages.has("own"), true);
});
test("truncated final user inventory cannot assert absence", async () => {
  const model = cleanupModel(); model.users.clear(); model.messages.clear(); const inherited = model.fetchImpl;
  model.fetchImpl = (url, init) => new URL(url).pathname === "/auth/v1/admin/users" ? Promise.resolve(response({ users: Array.from({ length: 100 }, (_, i) => ({ id: "foreign-" + i, email: "foreign@example.invalid" })) })) : inherited(url, init);
  const result = await cleanupOwned({ ...model, deadline: end(), pause: async () => {} });
  assert.equal(result.complete, false); assert.equal(result.usersAbsent, false);
});
test("response redirects cancel their body without forwarding to any second target", async () => {
  let cancelled = 0, calls = 0;
  const fetch = bounded(async () => { calls++; return new Response(new ReadableStream({ cancel() { cancelled++; } }), { status: 302 }); });
  await assert.rejects(fetch(ORIGINS.api + "/auth/v1/user"), /fixture_fetch_redirect/u);
  assert.equal(calls, 1); assert.equal(cancelled, 1);
});

for (const algorithm of ["HS256", "ES256"]) test("Auth v2.192.0 expiry rejection uses real SDK 403 bad_jwt: " + algorithm, async () => {
  const { createClient } = await import("@supabase/supabase-js");
  const generated = generatedJwt(algorithm); const seen = [];
  const fetch = bounded(async (url, init) => {
    assert.equal(String(url), ORIGINS.api + "/auth/v1/user");
    const token = new Headers(init.headers).get("Authorization").slice(7); seen.push(token);
    const claims = JSON.parse(Buffer.from(token.split(".")[1], "base64url"));
    return claims.exp > 1000 ? response({ id: ids[0], role: "authenticated" }) : response({ code: 403, error_code: "bad_jwt", msg: "generated expired token" }, 403);
  });
  const auth = createClient(ORIGINS.api, "synthetic-anon", { auth: { persistSession: false, autoRefreshToken: false }, global: { fetch } }).auth;
  const pair = await checkedExpiryPair({ ...generated, expectedUser: ids[0], nowSeconds: 1000, getUser: token => auth.getUser(token) });
  assert.deepEqual(seen, [generated.session.access_token, pair.positive, pair.expired]);
  assert.equal(pair.expiredAt, 940);
});

for (const error of [{ status: 401, code: "bad_jwt" }, { status: 403, code: "session_not_found" }, { status: 403 }, { status: 500, code: "bad_jwt" }]) test("Auth v2.192.0 rejects unrelated expiry denial: " + JSON.stringify(error), async () => {
  let calls = 0;
  await assert.rejects(checkedExpiryPair({ ...generatedJwt("HS256"), expectedUser: ids[0], nowSeconds: 1000, getUser: async () => ++calls < 3 ? { data: { user: { id: ids[0] } } } : { data: { user: null }, error } }), /fixture_expiry_negative_control/u);
});
test("Auth v2.192.0 expiry failure cannot coexist with a returned identity", async () => {
  let calls = 0;
  await assert.rejects(checkedExpiryPair({ ...generatedJwt("ES256"), expectedUser: ids[0], nowSeconds: 1000, getUser: async () => ++calls < 3 ? { data: { user: { id: ids[0] } } } : { data: { user: { id: ids[0] } }, error: { status: 403, code: "bad_jwt" } } }), /fixture_expiry_negative_control/u);
});

test("MFA successful JSON enrollment permits a bounded SVG larger than the ordinary cap", async () => {
  const data = { id: ids[0], type: "totp", totp: { qr_code: "<svg>" + "x".repeat(300000) + "</svg>", secret: "SYNTHETIC", uri: "otpauth://totp/generated" } };
  const fetch = bounded(async () => response(data));
  assert.deepEqual(await jsonResponse(await fetch(ORIGINS.api + "/auth/v1/factors", { method: "POST" })), data);
});

for (const [name,route,method,status,type] of [
  ["factor GET", "/auth/v1/factors", "GET", 200, "application/json"],
  ["other Auth route", "/auth/v1/token", "POST", 200, "application/json"],
  ["failed enrollment", "/auth/v1/factors", "POST", 500, "application/json"],
  ["nonJSON enrollment", "/auth/v1/factors", "POST", 200, "text/plain"],
  ["enrollment query", "/auth/v1/factors?extra=1", "POST", 200, "application/json"]
]) test("MFA larger bound never applies to " + name, async () => {
  const fetch = bounded(async () => new Response("x".repeat(262145), { status, headers: { "Content-Type": type } }));
  await assert.rejects(fetch(ORIGINS.api + route, { method }), /fixture_fetch_limit/u);
});
test("MFA enrollment cap is exactly finite and overflow cancels its stream", async () => {
  let cancelled = 0;
  const fetch = bounded(async () => new Response(new ReadableStream({ start(controller) { controller.enqueue(new Uint8Array(1048577)); }, cancel() { cancelled++; } }), { headers: { "Content-Type": "application/json; charset=utf-8" } }));
  await assert.rejects(fetch(ORIGINS.api + "/auth/v1/factors", { method: "POST" }), /fixture_fetch_limit/u); assert.equal(cancelled, 1);
});
test("MFA large response still preserves cancellation identity", async () => {
  const stop = new AbortController(), sentinel = new Error("generated abort");
  const fetch = makeBoundedFetch({ origin: ORIGINS.api, deadline: end(), signal: stop.signal, fetchImpl: async () => new Response(new ReadableStream({ pull() { stop.abort(sentinel); } }), { headers: { "Content-Type": "application/json" } }) });
  await assert.rejects(fetch(ORIGINS.api + "/auth/v1/factors", { method: "POST" }), error => error === sentinel);
});

test("Mailpit null optional recipient lists permit exact owned cleanup only", async () => {
  const model = cleanupModel(), deletes = [], inherited = model.fetchImpl;
  for (const message of model.messages.values()) { message.Cc = null; message.Bcc = null; }
  model.fetchImpl = (url, init) => {
    if (init.method === "DELETE" && new URL(url).pathname === "/api/v1/messages") deletes.push(JSON.parse(init.body));
    return inherited(url, init);
  };
  const result = await cleanupOwned({ ...model, deadline: end(), pause: async () => {} });
  assert.deepEqual(result, { complete: true, errors: [], usersAbsent: true, mailAbsent: true });
  assert.deepEqual(deletes, [{ IDs: ["own"] }]); assert.deepEqual([...model.messages.keys()], ["foreign"]);
});

for (const field of ["Cc", "Bcc"]) for (const value of [{}, "", false, 0, [null], [{ Address: null }]]) test("Mailpit malformed optional recipients still refuse: " + field + JSON.stringify(value), () => {
  assert.throws(() => mailOwnership({ To: [{ Address: manifest().users[0].email }], [field]: value }, manifest().users), /fixture_mail_recipients/u);
});
test("Mailpit null To never becomes owned or absent", () => {
  assert.throws(() => mailOwnership({ To: null, Cc: null, Bcc: null }, manifest().users), /fixture_mail_recipients/u);
});
test("Mailpit null optional list never permits deleting mixed recipients", async () => {
  const model = cleanupModel({ mixed: true }); model.messages.get("own").Bcc = null;
  const result = await cleanupOwned({ ...model, deadline: end(), pause: async () => {} });
  assert.equal(result.complete, false); assert.equal(result.mailAbsent, false);
  assert.ok(result.errors.includes("mail_mixed_ownership")); assert.ok(model.messages.has("own"));
  assert.equal(model.calls.some(([method, url]) => method === "DELETE" && url === "/api/v1/messages"), false);
});
