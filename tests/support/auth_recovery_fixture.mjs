// Test-only boundary. Importing this module performs no I/O.
import { constants } from "node:fs";
import fs from "node:fs/promises";
import path from "node:path";
import { createHash, createHmac, createPrivateKey, createPublicKey, sign, verify, timingSafeEqual } from "node:crypto";
import { performance } from "node:perf_hooks";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u;
const SHA = /^[0-9a-f]{64}$/u;
const ID = /^[A-Za-z0-9_-]{1,128}$/u;
export const ORIGINS = Object.freeze({ api: "http://127.0.0.1:57747", mail: "http://127.0.0.1:57752", web: "http://localhost:50916" });
const fail = code => { throw new Error(code); };
const need = (ok, code) => { if (!ok) fail(code); };
const keys = (value, names) => value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).sort().join() === [...names].sort().join();
const digest = bytes => createHash("sha256").update(bytes).digest("hex");
const freeze = value => { if (value && typeof value === "object") { Object.values(value).forEach(freeze); Object.freeze(value); } return value; };

export function validateManifest(value) {
  need(keys(value, ["version", "runId", "targetAdmissionSha256", "sourceSha256", "buildSha256", "origins", "database", "context", "users"]), "fixture_manifest_shape");
  need(value.version === 1 && UUID.test(value.runId) && [value.targetAdmissionSha256, value.sourceSha256, value.buildSha256].every(x => typeof x === "string" && SHA.test(x)), "fixture_manifest_binding");
  need(keys(value.origins, ["api", "mail", "web"]) && Object.entries(ORIGINS).every(([key, origin]) => value.origins[key] === origin), "fixture_origins");
  need(value.context === "colima-talli-frontend-dd88-20261010", "fixture_context");
  need(keys(value.database, ["host", "port", "user", "database"]) && value.database.host === "127.0.0.1" && value.database.port === 57748 && value.database.user === "postgres" && value.database.database === "postgres", "fixture_database");
  need(Array.isArray(value.users) && value.users.length === 2, "fixture_users");
  value.users.forEach((user, index) => {
    need(keys(user, ["id", "email"]) && typeof user.id === "string" && UUID.test(user.id) && user.email === "auth-browser-" + value.runId + (index === 0 ? "-alice" : "-bob") + "@example.invalid", "fixture_users");
  });
  need(new Set([value.runId, ...value.users.map(user => user.id)]).size === 3, "fixture_users");
  return freeze(structuredClone(value));
}

async function privateFile(file, flags) {
  need(path.isAbsolute(file), "fixture_private_path");
  const parent = await fs.lstat(path.dirname(file));
  need(parent.isDirectory() && !parent.isSymbolicLink() && parent.uid === process.getuid() && (parent.mode & 0o777) === 0o700, "fixture_private_directory");
  const handle = await fs.open(file, flags | constants.O_NOFOLLOW);
  try {
    const stat = await handle.stat();
    need(stat.isFile() && stat.uid === process.getuid() && (stat.mode & 0o777) === 0o600 && stat.nlink === 1, "fixture_private_file");
    return handle;
  } catch (error) { await handle.close().catch(() => {}); throw error; }
}

export async function readFixtureManifest(file, sha256) {
  need(typeof sha256 === "string" && SHA.test(sha256), "fixture_manifest_pin");
  const handle = await privateFile(file, constants.O_RDONLY);
  let failed = false;
  try {
    const stat = await handle.stat();
    need(stat.size > 0 && stat.size <= 32768, "fixture_manifest_size");
    const buffer = Buffer.alloc(32769);
    const { bytesRead } = await handle.read(buffer, 0, buffer.length, 0);
    const bytes = buffer.subarray(0, bytesRead);
    need(bytesRead === stat.size && digest(bytes) === sha256, "fixture_manifest_pin");
    return validateManifest(parseJson(bytes));
  } catch (error) { failed = true; throw error; }
  finally { try { await handle.close(); } catch (error) { if (!failed) throw error; } }
}

export function admitFixture(manifest, env) {
  const value = validateManifest(manifest);
  need(!Object.keys(env).some(name => name.startsWith("PG") || ["NODE_OPTIONS", "NODE_USE_ENV_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"].includes(name)), "fixture_environment_override");
  need(env.SUPABASE_URL === value.origins.api && env.TALLI_AUTH_TEST_MAIL_URL === value.origins.mail && env.TALLI_AUTH_TEST_WEB_PORT === "50916" && env.DOCKER_CONTEXT === value.context, "fixture_endpoint");
  for (const name of ["SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY"]) need(typeof env[name] === "string" && env[name].length > 0 && env[name].length <= 16384 && !/[\r\n]/u.test(env[name]), "fixture_credential");
  need(typeof env.DATABASE_URL === "string" && !/[?#\s]/u.test(env.DATABASE_URL), "fixture_database");
  let uri;
  try { uri = new URL(env.DATABASE_URL); } catch { fail("fixture_database"); }
  need(["postgres:", "postgresql:"].includes(uri.protocol) && uri.hostname === "127.0.0.1" && uri.port === "57748" && uri.pathname === "/postgres" && uri.username === "postgres" && uri.password, "fixture_database");
  let password;
  try { password = decodeURIComponent(uri.password); } catch { fail("fixture_database"); }
  need(password.length > 0 && password.length <= 8192 && !/[\x00\r\n]/u.test(password), "fixture_database");
  const secret = env.TALLI_AUTH_TEST_JWT_SECRET;
  const jwkText = env.TALLI_AUTH_TEST_JWT_PRIVATE_JWK;
  need((typeof secret === "string" && secret.length > 0) || (typeof jwkText === "string" && jwkText.length > 0), "fixture_signing_material");
  need(secret === undefined || (typeof secret === "string" && secret.length > 0 && secret.length <= 8192), "fixture_signing_material");
  let jwk;
  if (jwkText !== undefined) {
    need(typeof jwkText === "string" && jwkText.length > 0 && Buffer.byteLength(jwkText) <= 8192, "fixture_signing_material");
    jwk = parseJson(Buffer.from(jwkText));
    esKey(jwk);
  }
  return { manifest: value, anon: env.SUPABASE_ANON_KEY, service: env.SUPABASE_SERVICE_ROLE_KEY,
    signingMaterial: { secret, jwk }, database: { ...value.database, password, ssl: false, connectionTimeoutMillis: 5000, query_timeout: 5000, statement_timeout: 5000, application_name: "talli-owned-auth-recovery" } };
}

export async function appendOwnership(manifestPath, manifestSha256, record) {
  need(keys(record, ["kind", "pid"]) && ["harness", "next_launch", "next", "browser_launch", "browser"].includes(record.kind) && Number.isSafeInteger(record.pid) && record.pid > 1, "fixture_process_record");
  await readFixtureManifest(manifestPath, manifestSha256);
  const handle = await privateFile(path.join(path.dirname(manifestPath), "ownership.ndjson"), constants.O_WRONLY | constants.O_APPEND);
  let failed = false;
  try {
    need((await handle.stat()).size < 32768, "fixture_journal_limit");
    await handle.writeFile(JSON.stringify({ manifestSha256, ...record }) + "\n");
    await handle.sync();
  } catch (error) { failed = true; throw error; }
  finally { try { await handle.close(); } catch (error) { if (!failed) throw error; } }
}

export function parseJson(bytes) {
  let value;
  try { value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); } catch { fail("fixture_json"); }
  const visit = (entry, depth) => {
    need(depth <= 16, "fixture_json_depth");
    if (entry && typeof entry === "object") Object.values(entry).forEach(child => visit(child, depth + 1));
  };
  visit(value, 0);
  return value;
}

export function makeBoundedFetch({ origin, deadline, signal, fetchImpl = globalThis.fetch, requestMs = 5000 }) {
  need([ORIGINS.api, ORIGINS.mail].includes(origin) && Number.isFinite(deadline) && requestMs > 0 && requestMs <= 5000, "fixture_fetch_config");
  return async (input, init = {}) => {
    const url = new URL(input instanceof Request ? input.url : input);
    const method = (init.method || (input instanceof Request ? input.method : "GET")).toUpperCase();
    need(url.origin === origin && !url.username && !url.password && !url.hash && (origin === ORIGINS.api ? url.pathname.startsWith("/auth/v1/") : /^\/api\/v1\/(?:messages|message\/[A-Za-z0-9_-]{1,128})$/u.test(url.pathname)) && ["GET", "POST", "PUT", "DELETE"].includes(method), "fixture_fetch_target");
    const remaining = Math.min(requestMs, deadline - performance.now());
    need(remaining > 0, "fixture_fetch_deadline");
    const controller = new AbortController();
    const signals = [controller.signal, signal, init.signal, input instanceof Request ? input.signal : undefined].filter(Boolean);
    const combined = AbortSignal.any(signals);
    const timeout = setTimeout(() => controller.abort(new Error("fixture_fetch_deadline")), remaining);
    let onAbort;
    const aborted = new Promise((_, reject) => { onAbort = () => reject(combined.reason); combined.addEventListener("abort", onAbort, { once: true }); if (combined.aborted) onAbort(); });
    const race = promise => Promise.race([promise, aborted]);
    let reader, primary, result, failed = false;
    const retain = error => { if (!failed) { primary = error; failed = true; } };
    try {
      combined.throwIfAborted();
      const response = await race(fetchImpl(input, { ...init, redirect: "error", signal: combined }));
      reader = response.body?.getReader();
      need(!response.redirected && (response.url === "" || new URL(response.url).origin === origin) && !(response.status >= 300 && response.status < 400), "fixture_fetch_redirect");
      // TOTP enrollment carries a generated SVG; only this successful JSON route gets 1 MiB.
      const enrollment = origin === ORIGINS.api && method === "POST" && url.pathname === "/auth/v1/factors" && url.search === "" && response.status === 200 && /^application\/json(?:\s*;|$)/iu.test(response.headers.get("content-type") || "");
      const responseLimit = enrollment ? 1048576 : 262144;
      let size = 0; const chunks = [];
      if (reader) while (true) {
        const item = await race(reader.read());
        if (item.done) break;
        size += item.value.byteLength; need(size <= responseLimit, "fixture_fetch_limit"); chunks.push(Buffer.from(item.value));
      }
      const headers = new Headers(response.headers); headers.delete("content-encoding"); headers.delete("content-length");
      result = new Response([204, 205, 304].includes(response.status) ? null : Buffer.concat(chunks), { status: response.status, statusText: response.statusText, headers });
    } catch (error) { retain(error); }
    finally {
      if (reader) {
        try { await race(reader.cancel()); } catch (error) { retain(error); }
        try { reader.releaseLock(); } catch (error) { retain(error); }
      }
      clearTimeout(timeout); combined.removeEventListener("abort", onAbort);
    }
    if (failed) throw primary;
    return result;
  };
}

export async function jsonResponse(response) { return parseJson(new Uint8Array(await response.arrayBuffer())); }

export async function listMail(fetchMail) {
  const messages = [], ids = new Set(); let total;
  for (let page = 0; page < 10; page++) {
    const response = await fetchMail(ORIGINS.mail + "/api/v1/messages?start=" + messages.length + "&limit=100");
    need(response.status === 200, "fixture_mail_list");
    const data = await jsonResponse(response);
    need(Number.isSafeInteger(data.total) && data.total >= 0 && data.total <= 1000 && Array.isArray(data.messages) && data.messages.length <= 100 && (total === undefined || total === data.total), "fixture_mail_inventory");
    total = data.total;
    for (const message of data.messages) { need(message && ID.test(message.ID) && !ids.has(message.ID), "fixture_mail_inventory"); ids.add(message.ID); messages.push(message); }
    need(messages.length <= total, "fixture_mail_inventory");
    if (messages.length === total) return messages;
    need(data.messages.length > 0, "fixture_mail_inventory");
  }
  fail("fixture_mail_inventory_limit");
}

export function mailOwnership(message, users) {
  const emails = new Set(users.map(user => user.email));
  need(Array.isArray(message.To), "fixture_mail_recipients");
  const addresses = [...message.To];
  for (const key of ["Cc", "Bcc"]) { // Mailpit v1.30.2 summaries encode absent Cc/Bcc slices as null.
    if (message[key] !== undefined && message[key] !== null) { need(Array.isArray(message[key]), "fixture_mail_recipients"); addresses.push(...message[key]); } }
  need(addresses.every(item => item && typeof item.Address === "string"), "fixture_mail_recipients");
  const owned = addresses.filter(item => emails.has(item.Address.toLowerCase())).length;
  return owned === 0 ? "foreign" : owned === addresses.length ? "owned" : "mixed";
}

export async function createOwnedUsers(admitted, admin, password) {
  for (const user of admitted.manifest.users) {
    const result = await admin.auth.admin.createUser({ ...user, password, email_confirm: true });
    need(!result.error && result.data?.user?.id === user.id && result.data.user.email === user.email, "fixture_create_unconfirmed");
  }
}

function jwtPart(value) {
  need(typeof value === "string" && value.length > 0 && /^[A-Za-z0-9_-]+$/u.test(value), "fixture_jwt");
  const bytes = Buffer.from(value, "base64url"); need(bytes.toString("base64url") === value, "fixture_jwt"); return bytes;
}
function esKey(jwk) {
  need(jwk && jwk.kty === "EC" && jwk.crv === "P-256" && ["x", "y", "d"].every(key => typeof jwk[key] === "string" && jwtPart(jwk[key]).length === 32) && (jwk.alg === undefined || jwk.alg === "ES256") && (jwk.use === undefined || jwk.use === "sig") && (jwk.key_ops === undefined || (Array.isArray(jwk.key_ops) && jwk.key_ops.includes("sign") && jwk.key_ops.every(x => ["sign", "verify"].includes(x)))), "fixture_signing_material");
  try { return createPrivateKey({ key: jwk, format: "jwk" }); } catch { fail("fixture_signing_material"); }
}
export function makeExpiryPair({ session, expectedUser, signingMaterial, nowSeconds = Math.floor(Date.now() / 1000) }) {
  need(typeof session?.access_token === "string" && session.access_token.length <= 16384 && Number.isSafeInteger(nowSeconds), "fixture_jwt");
  const parts = session.access_token.split("."); need(parts.length === 3, "fixture_jwt");
  const header = parseJson(jwtPart(parts[0])), claims = parseJson(jwtPart(parts[1])), signature = jwtPart(parts[2]);
  need(header && ["HS256", "ES256"].includes(header.alg) && !["crit", "jku", "jwk", "x5u", "x5c"].some(key => Object.hasOwn(header, key)) && (header.typ === undefined || header.typ === "JWT") && (header.kid === undefined || typeof header.kid === "string"), "fixture_jwt_header");
  need(claims?.sub === expectedUser && claims.role === "authenticated" && Number.isSafeInteger(claims.exp) && claims.exp > nowSeconds && (claims.nbf === undefined || (Number.isSafeInteger(claims.nbf) && claims.nbf <= nowSeconds)), "fixture_jwt_claims");
  let signer, verified;
  const original = Buffer.from(parts[0] + "." + parts[1]);
  if (header.alg === "HS256") {
    need(typeof signingMaterial.secret === "string" && signingMaterial.secret.length > 0, "fixture_signing_material");
    signer = data => createHmac("sha256", signingMaterial.secret).update(data).digest();
    const expected = signer(original); verified = signature.length === expected.length && timingSafeEqual(signature, expected);
  } else {
    const key = esKey(signingMaterial.jwk);
    need(header.kid === undefined || header.kid === signingMaterial.jwk.kid, "fixture_signing_kid");
    signer = data => sign("sha256", data, { key, dsaEncoding: "ieee-p1363" });
    verified = signature.length === 64 && verify("sha256", original, { key: createPublicKey(key), dsaEncoding: "ieee-p1363" }, signature);
  }
  need(verified, "fixture_signing_control");
  const encode = exp => { const body = parts[0] + "." + Buffer.from(JSON.stringify({ ...claims, exp })).toString("base64url"); return body + "." + signer(Buffer.from(body)).toString("base64url"); };
  return { positive: encode(nowSeconds + 300), expired: encode(nowSeconds - 60), expiredAt: nowSeconds - 60, algorithm: header.alg };
}
export async function checkedExpiryPair({ session, expectedUser, signingMaterial, getUser, nowSeconds }) {
  const pair = makeExpiryPair({ session, expectedUser, signingMaterial, nowSeconds });
  for (const token of [session.access_token, pair.positive]) {
    const result = await getUser(token);
    need(!result.error && result.data?.user?.id === expectedUser, "fixture_expiry_positive_control");
  }
  const negative = await getUser(pair.expired);
  // Pinned Auth v2.192.0 maps expired JWT validation to 403 bad_jwt, with no parser leeway.
  need(negative.error?.status === 403 && negative.error.code === "bad_jwt" && !negative.data?.user, "fixture_expiry_negative_control");
  return pair;
}

export async function cleanupOwned({ admitted, deadline, signal, fetchImpl = globalThis.fetch, pause = ms => new Promise(resolve => setTimeout(resolve, ms)) }) {
  const manifest = validateManifest(admitted.manifest);
  need(typeof admitted.service === "string" && admitted.service.length > 0 && admitted.service.length <= 16384 && !/[\r\n]/u.test(admitted.service), "fixture_credential");
  const auth = makeBoundedFetch({ origin: ORIGINS.api, deadline, signal, fetchImpl });
  const mail = makeBoundedFetch({ origin: ORIGINS.mail, deadline, signal, fetchImpl });
  const headers = { apikey: admitted.service, Authorization: "Bearer " + admitted.service };
  const errors = []; let usersAbsent = false, mailAbsent = false;
  const attempt = async (stage, fn) => { try { await fn(); } catch { errors.push(stage); } };
  const readUsers = async () => {
    const users = [], seen = new Set();
    for (let page = 1; page <= 10; page++) {
      const response = await auth(ORIGINS.api + "/auth/v1/admin/users?page=" + page + "&per_page=100", { headers });
      need(response.status === 200, "fixture_user_inventory");
      const data = await jsonResponse(response); need(Array.isArray(data.users) && data.users.length <= 100, "fixture_user_inventory");
      for (const user of data.users) { need(user && typeof user.id === "string" && typeof user.email === "string" && !seen.has(user.id), "fixture_user_inventory"); seen.add(user.id); users.push(user); }
      if (data.users.length < 100) return users;
    }
    fail("fixture_user_inventory_limit");
  };
  for (const user of manifest.users) await attempt("user_cleanup", async () => {
    const url = ORIGINS.api + "/auth/v1/admin/users/" + user.id;
    const response = await auth(url, { headers });
    const data = await jsonResponse(response);
    if (response.status === 404) { need(data.error_code === "user_not_found" || data.code === "user_not_found", "fixture_user_missing_unconfirmed"); return; }
    need(response.status === 200 && data.id === user.id && data.email === user.email, "fixture_user_ownership");
    const deleted = await auth(url, { method: "DELETE", headers });
    need(deleted.status === 200 || deleted.status === 204, "fixture_user_delete");
  });
  await attempt("mail_cleanup", async () => {
    const messages = await listMail(mail);
    for (const message of messages) {
      const ownership = mailOwnership(message, manifest.users);
      if (ownership === "mixed") { errors.push("mail_mixed_ownership"); continue; }
      if (ownership !== "owned") continue;
      await attempt("mail_delete", async () => {
        const response = await mail(ORIGINS.mail + "/api/v1/messages", { method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ IDs: [message.ID] }) });
        need(response.status === 200 || response.status === 204, "fixture_mail_delete");
      });
    }
  });
  for (let pass = 0; pass < 2; pass++) {
    if (pass) await attempt("cleanup_settle", async () => { need(deadline - performance.now() >= 250, "fixture_cleanup_deadline"); await pause(250); });
    await attempt("user_absence", async () => {
      usersAbsent = false;
      const users = await readUsers();
      need(!users.some(user => manifest.users.some(owned => user.id === owned.id || user.email.toLowerCase() === owned.email)), "fixture_user_still_present"); usersAbsent = true;
    });
    await attempt("mail_absence", async () => {
      mailAbsent = false;
      need((await listMail(mail)).every(message => mailOwnership(message, manifest.users) === "foreign"), "fixture_mail_still_present"); mailAbsent = true;
    });
  }
  return { complete: errors.length === 0 && usersAbsent && mailAbsent, errors, usersAbsent, mailAbsent };
}

export async function runWithCleanup(body, cleanup) {
  let primary, failed = false, result, cleanupResult;
  try { result = await body(); } catch (error) { primary = error; failed = true; }
  try { cleanupResult = await cleanup(); } catch (error) { if (!failed) { primary = error; failed = true; } }
  if (failed) throw primary;
  need(cleanupResult?.complete === true, "fixture_cleanup_incomplete");
  return result;
}

export async function boundedClose(action, milliseconds = 5000) {
  let timer;
  try { return await Promise.race([Promise.resolve().then(action), new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("fixture_close_deadline")), milliseconds); })]); }
  finally { clearTimeout(timer); }
}
