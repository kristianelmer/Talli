import assert from "node:assert/strict";
import { createHmac, randomUUID } from "node:crypto";
import { createRequire } from "node:module";
import test from "node:test";

import { createClient } from "@supabase/supabase-js";
import { chromium } from "playwright";
import pg from "pg";
import { allocateLoopbackPort, startOwnedProcess, stopOwnedProcess, waitForOwnedReadiness } from "./support/owned-process-lifecycle.mjs";
import { isLoopbackPostgresUrl, isLoopbackSupabaseUrl } from "./support/supabase_fixture_safety.mjs";
import { captureFrontendStep } from "./support/frontend-capture.mjs";
import { activate, fillField, tabTo } from "./support/frontend-keyboard-audit.mjs";

test("local password and MFA recovery retain identity, uncertainty and return scope", { timeout: 300_000 }, async (t) => {
  const api = process.env.SUPABASE_URL;
  const anon = process.env.SUPABASE_ANON_KEY;
  const service = process.env.SUPABASE_SERVICE_ROLE_KEY;
  const db = process.env.DATABASE_URL;
  const mail = process.env.TALLI_AUTH_TEST_MAIL_URL;
  if (!api || !anon || !service || !db || !mail) { t.skip("explicit owned Auth/mail fixture env required"); return; }
  assert.ok(isLoopbackSupabaseUrl(api) && isLoopbackPostgresUrl(db) && isLoopbackSupabaseUrl(mail), "Auth fixtures cannot leave loopback");
  assert.ok(process.env.DOCKER_CONTEXT?.startsWith("colima-talli-frontend-"), "explicit frontend-owned context required");
  const port = Number(process.env.TALLI_AUTH_TEST_WEB_PORT) || await allocateLoopbackPort();
  const base = `http://localhost:${port}`;
  const next = "/sjekk-selskapet?via=password-recovery#company";
  const prefix = `auth-browser-${randomUUID()}`;
  const emails = [`${prefix}-alice@example.invalid`, `${prefix}-bob@example.invalid`];
  const oldPassword = "Synthetic-Old-Password-123!";
  const newPassword = "Synthetic-New-Password-456!";
  const admin = createClient(api, service, { auth: { persistSession: false, autoRefreshToken: false } });
  const client = () => createClient(api, anon, { auth: { persistSession: false, autoRefreshToken: false } });
  const database = new pg.Client({ connectionString: db });
  const ids = [];
  const seenMail = new Set();
  let server, browser;
  const allowed = new Set([String(port), new URL(api).port, new URL(mail).port]);
  const remote = [];
  t.after(async () => {
    const errors = [];
    try { await browser?.close(); } catch { errors.push(new Error("owned browser cleanup failed")); }
    try { await stopOwnedProcess(server); } catch { errors.push(new Error("owned Next cleanup failed")); }
    for (const id of ids) {
      const result = await admin.auth.admin.deleteUser(id);
      if (result.error) errors.push(new Error(`fixture user cleanup:${result.error.code}`));
    }
    try {
      const messages = (await (await fetch(`${mail}/api/v1/messages`)).json()).messages;
      const owned = messages.filter(message => message.To.some(({ Address }) => emails.includes(Address.toLowerCase()))).map(({ ID }) => ID);
      if (owned.length) {
        const response = await fetch(`${mail}/api/v1/messages`, { method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ IDs: owned }) });
        if (!response.ok) errors.push(new Error("owned mail cleanup failed"));
      }
    } catch { errors.push(new Error("owned mail cleanup unavailable")); }
    try { await database.end(); } catch { errors.push(new Error("fixture database disconnect failed")); }
    if (errors.length) throw new AggregateError(errors, "Auth fixture cleanup incomplete");
  });
  await database.connect();
  for (const email of emails) {
    const result = await admin.auth.admin.createUser({ email, password: oldPassword, email_confirm: true });
    assert.equal(result.error, null, `fixture create:${result.error?.code}`); ids.push(result.data.user.id);
  }
  const nextCli = createRequire(new URL("../apps/web/package.json", import.meta.url)).resolve("next/dist/bin/next");
  server = startOwnedProcess({ command: process.execPath, args: [nextCli, process.env.TALLI_AUTH_TEST_BUILT === "1" ? "start" : "dev", "apps/web", "--hostname", "127.0.0.1", "--port", String(port)],
    cwd: process.cwd(), env: { PATH: process.env.PATH, NODE_ENV: process.env.TALLI_AUTH_TEST_BUILT === "1" ? "production" : "test", NEXT_TELEMETRY_DISABLED: "1",
      SUPABASE_URL: api, SUPABASE_ANON_KEY: anon, SUPABASE_SERVICE_ROLE_KEY: service,
      NEXT_PUBLIC_SUPABASE_URL: api, NEXT_PUBLIC_SUPABASE_ANON_KEY: anon,
      SITE_URL: base, TALLI_BACKEND_URL: "http://127.0.0.1:1" }, readinessProof: "Ready in" });
  await waitForOwnedReadiness({ process: server, url: `${base}/login?reauth=1` });
  browser = await chromium.launch({ headless: true });
  async function page() {
    const value = await browser.newPage({ viewport: { width: 320, height: 844 } });
    await value.context().route("**/*", route => {
      const url = new URL(route.request().url());
      if (["http:", "https:"].includes(url.protocol) && !(["localhost", "127.0.0.1", "[::1]"].includes(url.hostname) && allowed.has(url.port))) {
        remote.push(`${url.origin}${url.pathname}`); return route.abort();
      }
      return route.continue();
    });
    return value;
  }
  async function hashLink(email) {
    const result = await admin.auth.admin.generateLink({ type: "recovery", email });
    assert.equal(result.error, null, `fixture link:${result.error?.code}`);
    return `${base}/auth/recovery?${new URLSearchParams({ token_hash: result.data.properties.hashed_token, type: "recovery", next })}`;
  }
  async function resetRequest(value, email) {
    await value.goto(`${base}/forgot-password?${new URLSearchParams({ next })}`);
    await value.getByRole("heading", { name: "Tilbakestill passord" }).waitFor();
    await fillField(value, value.getByLabel("E-post"), email);
    assert.equal(await value.getByLabel("E-post").inputValue(), email, "recipient request input changed before submit");
    await activate(value, value.getByRole("button", { name: "Send lenke", exact: true }));
    await value.locator("h2, .errorText").filter({ hasText: /Se etter e-post|Vent litt før du ber om en ny lenke/u }).waitFor();
    if (await value.locator(".errorText").filter({ hasText: "Vent litt før du ber om en ny lenke" }).count()) {
      assert.equal(await value.getByLabel("E-post").inputValue(), email, "throttle retry must retain the recipient");
      await captureFrontendStep(value, "request-rate-limit");
      // The owned fixture's unchanged email max_frequency is 1s. A preceding
      // provider-generated link can start this timer; retry once after that bound.
      await new Promise(resolve => setTimeout(resolve, 1_100));
      await activate(value, value.getByRole("button", { name: "Send lenke", exact: true }));
    }
    try { await value.getByRole("heading", { name: "Se etter e-post" }).waitFor({ timeout: 10_000 }); }
    catch {
      await captureFrontendStep(value, "request-retry-failure");
      assert.fail(JSON.stringify({ error: await value.locator(".errorText").allTextContents(),
        emailMatched: await value.getByLabel("E-post").inputValue() === email,
        requestIntent: (await value.context().cookies()).some(cookie => cookie.name === "talli_password_recovery_request") }));
    }
  }
  async function deliveredLink(email) {
    const deadline = Date.now() + 10_000;
    while (Date.now() < deadline) {
      const list = (await (await fetch(`${mail}/api/v1/messages`)).json()).messages;
      const summary = list.find(message => !seenMail.has(message.ID) && message.To.some(({ Address }) => Address.toLowerCase() === email));
      if (summary) {
        seenMail.add(summary.ID);
        const message = await (await fetch(`${mail}/api/v1/message/${summary.ID}`)).json();
        const links = (message.HTML.match(/href="([^"]+)"/gu) || []).map(value => new URL(value.slice(6, -1).replaceAll("&amp;", "&")));
        const url = links.find(url => url.origin === api && url.pathname === "/auth/v1/verify" && url.searchParams.get("type") === "recovery");
        assert.ok(url, "owned mail has no recovery verification link");
        assert.equal(new URL(url.searchParams.get("redirect_to")).origin, base, "Auth link escaped the owned web origin");
        return url.href;
      }
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert.fail("owned recovery mail delivery timed out");
  }
  async function credentials(email, password, expected) {
    const verifier = client(); const result = await verifier.auth.signInWithPassword({ email, password });
    assert.equal(result.error === null, expected, "provider credential verdict differs");
    if (!result.error) await verifier.auth.signOut({ scope: "local" });
  }
  async function retainBeforeHydration(value, url, fields) {
    let release;
    const gate = new Promise(resolve => { release = resolve; });
    let held = 0;
    const holdScripts = async route => {
      if (route.request().resourceType() === "script") { held += 1; await gate; }
      await route.continue();
    };
    await value.route(`${base}/_next/**`, holdScripts);
    try {
      await value.goto(url, { waitUntil: "commit" });
      for (const [label, text] of fields) await value.getByLabel(label).fill(text);
    } finally { release(); }
    await value.waitForLoadState("networkidle");
    assert.ok(held > 0, "regression must hold JavaScript while entering fields");
    for (const [label, text] of fields) {
      const field = value.getByLabel(label);
      await field.press("Tab");
      assert.equal(await field.inputValue(), text, "pre-hydration typing lost on blur");
    }
    await value.unroute(`${base}/_next/**`, holdScripts);
  }
  await t.test("recovery request retains typing before JavaScript loads", async () => {
    const value = await page();
    await retainBeforeHydration(value, `${base}/forgot-password`, [["E-post", emails[0]]]);
    await value.close();
  });
  let usedLink;
  await t.test("real local email and PKCE recovery change only the verified owner password", async () => {
    const value = await page();
    await value.goto(`${base}/login?${new URLSearchParams({ reauth: "1", next })}`);
    await activate(value, value.getByRole("link", { name: "Glemt passord?" }));
    await value.getByRole("heading", { name: "Tilbakestill passord" }).waitFor();
    assert.equal(new URL(value.url()).searchParams.get("next"), next);
    await captureFrontendStep(value, "01-request");
    await fillField(value, value.getByLabel("E-post"), emails[0]);
    assert.equal(await value.getByLabel("E-post").inputValue(), emails[0], "request email changed before submit");
    let requestPosts = 0;
    value.on("request", request => { if (request.method() === "POST" && new URL(request.url()).pathname === "/forgot-password") requestPosts += 1; });
    await activate(value, value.getByRole("button", { name: "Send lenke", exact: true }));
    const receipt = value.getByRole("heading", { name: "Se etter e-post" });
    try { await receipt.waitFor({ timeout: 10_000 }); } catch {
      await captureFrontendStep(value, "01a-request-failure");
      const cookies = await value.context().cookies();
      assert.fail(JSON.stringify({ requestPosts, emailMatched: await value.getByLabel("E-post").inputValue() === emails[0],
        error: await value.locator(".errorText").allTextContents(),
        hasVerifier: cookies.some(cookie => cookie.name.endsWith("-code-verifier")),
        hasRequestIntent: cookies.some(cookie => cookie.name === "talli_password_recovery_request") }));
    }
    assert.equal(await receipt.evaluate(element => element === document.activeElement), true);
    await captureFrontendStep(value, "02-request-sent");
    usedLink = await deliveredLink(emails[0]);
    const resetPage = await page();
    await retainBeforeHydration(resetPage, await hashLink(emails[1]), [
      [/^Nytt passord/u, "Synthetic-Early-Password-123!"], ["Gjenta nytt passord", "Synthetic-Early-Password-123!"],
    ]);
    await resetPage.close();
    await value.goto(usedLink);
    await value.getByRole("heading", { name: "Velg nytt passord" }).waitFor();
    assert.equal(new URL(value.url()).searchParams.get("next"), next);
    await captureFrontendStep(value, "03-reset-ready");
    await fillField(value, value.getByLabel(/^Nytt passord/u), newPassword);
    await fillField(value, value.getByLabel("Gjenta nytt passord"), "Synthetic-Different-Password!");
    await activate(value, value.getByRole("button", { name: "Endre passord" }));
    await value.locator('[role="alert"]').filter({ hasText: "Passordene er ikke like" }).waitFor();
    await captureFrontendStep(value, "04-password-mismatch");
    await credentials(emails[0], oldPassword, true);
    await fillField(value, value.getByLabel(/^Nytt passord/u), newPassword);
    await fillField(value, value.getByLabel("Gjenta nytt passord"), newPassword);
    await activate(value, value.getByRole("button", { name: "Endre passord" }));
    await value.waitForURL(url => url.pathname === "/login" && url.searchParams.get("passwordChanged") === "1");
    assert.equal(new URL(value.url()).searchParams.get("next"), next);
    assert.equal((await value.context().cookies()).some(cookie => cookie.name === "talli_password_recovery_grant"), false);
    await captureFrontendStep(value, "05-sign-in-after-reset");
    await credentials(emails[0], oldPassword, false); await credentials(emails[0], newPassword, true);
    await fillField(value, value.getByLabel("E-post"), emails[0]); await fillField(value, value.getByLabel("Passord", { exact: false }), newPassword);
    await activate(value, value.getByRole("button", { name: "Logg inn", exact: true }));
    await value.waitForURL(url => `${url.pathname}${url.search}${url.hash}` === next);
    await value.close();
  });
  assert.ok(usedLink, "primary mail recovery did not reach a delivered link; dependent cases stop here");
  await t.test("used, expired and missing links cannot create a reset grant", async () => {
    const value = await page();
    await value.goto(usedLink); await value.waitForURL(url => url.pathname === "/forgot-password" && url.searchParams.has("error"));
    await captureFrontendStep(value, "06-used-link");
    const expired = await hashLink(emails[1]);
    await database.query("update auth.users set recovery_sent_at = now() - interval '2 hours' where id = $1", [ids[1]]);
    await value.goto(expired); await value.waitForURL(url => url.pathname === "/forgot-password" && url.searchParams.get("error") === "invalid-link");
    await captureFrontendStep(value, "07-expired-link");
    await value.goto(`${base}/reset-password?${new URLSearchParams({ next })}`);
    assert.equal(await value.getByLabel(/^Nytt passord/u).count(), 0);
    await captureFrontendStep(value, "08-missing-link");
    assert.equal((await value.context().cookies()).some(cookie => cookie.name === "talli_password_recovery_grant"), false);
    await value.close();
  });
  await t.test("another signed-in account is preserved when a different owner's link is opened", async () => {
    const value = await page();
    await value.goto(`${base}/login?${new URLSearchParams({ reauth: "1", next })}`);
    await fillField(value, value.getByLabel("E-post"), emails[1]); await fillField(value, value.getByLabel("Passord"), oldPassword);
    await activate(value, value.getByRole("button", { name: "Logg inn", exact: true }));
    await value.waitForURL(url => `${url.pathname}${url.search}${url.hash}` === next);
    await value.goto(await hashLink(emails[0]));
    await value.waitForURL(url => url.pathname === "/forgot-password" && url.searchParams.get("error") === "wrong-account");
    assert.equal((await verifiedBrowserUser(value, client())).id, ids[1]);
    await captureFrontendStep(value, "09-wrong-account");
    await activate(value, value.getByRole("button", { name: "Logg ut og tilbakestill passord" }));
    await value.getByRole("button", { name: "Send lenke", exact: true }).waitFor();
    await value.close();
  });
  await t.test("a link for a different requested recipient is rejected without switching account", async () => {
    const value = await page(); await resetRequest(value, emails[0]);
    await value.goto(await hashLink(emails[1]));
    await value.waitForURL(url => url.pathname === "/forgot-password" && url.searchParams.get("error") === "wrong-recipient");
    assert.equal((await value.context().cookies()).some(cookie => /-auth-token(?:\.\d+)?$/u.test(cookie.name)), false);
    await captureFrontendStep(value, "10-wrong-recipient"); await value.close();
  });
  await t.test("an expired access token and invalid refresh token block the loaded recovery form", async () => {
    const value = await page(); await value.goto(await hashLink(emails[0]));
    await value.getByRole("heading", { name: "Velg nytt passord" }).waitFor();
    const session = await browserSession(value);
    const [header, encoded] = session.access_token.split(".");
    const payload = JSON.parse(Buffer.from(encoded, "base64url")); payload.exp = Math.floor(Date.now() / 1_000) - 60;
    const body = Buffer.from(JSON.stringify(payload)).toString("base64url");
    const token = `${header}.${body}.${createHmac("sha256", process.env.TALLI_AUTH_TEST_JWT_SECRET).update(`${header}.${body}`).digest("base64url")}`;
    assert.ok((await client().auth.getUser(token)).error, "owned Auth did not reject expired input");
    await replaceBrowserSession(value, { ...session, access_token: token, refresh_token: "synthetic-invalid-refresh", expires_at: payload.exp });
    await fillField(value, value.getByLabel(/^Nytt passord/u), "Synthetic-Blocked-Change-789!");
    await fillField(value, value.getByLabel("Gjenta nytt passord"), "Synthetic-Blocked-Change-789!");
    await activate(value, value.getByRole("button", { name: "Endre passord" }));
    await value.locator('[role="alert"]').filter({ hasText: "Innloggingen for tilbakestillingen" }).waitFor();
    await captureFrontendStep(value, "11-expired-session");
    await credentials(emails[0], newPassword, true); await credentials(emails[0], "Synthetic-Blocked-Change-789!", false);
    await value.close();
  });
  await t.test("registered backup MFA and read retry preserve the existing AAL2 gate", async () => {
    const seed = client(); assert.equal((await seed.auth.signInWithPassword({ email: emails[0], password: newPassword })).error, null);
    const factors = [];
    for (const name of ["Daglig app", "Reserve"]) {
      const enrolled = await seed.auth.mfa.enroll({ factorType: "totp", friendlyName: name });
      assert.equal(enrolled.error, null, `fixture enrollment:${enrolled.error?.code}`);
      const factor = enrolled.data; factors.push(factor);
      assert.equal((await seed.auth.mfa.challengeAndVerify({ factorId: factor.id, code: currentTotp(factor.totp.secret) })).error, null);
    }
    await seed.auth.signOut({ scope: "local" });
    const value = await page(); await resetRequest(value, emails[0]);
    await value.goto(await deliveredLink(emails[0]));
    await value.getByRole("link", { name: "Bekreft med autentiseringsappen", exact: true }).waitFor();
    assert.equal(await value.getByLabel(/^Nytt passord/u).count(), 0);
    await captureFrontendStep(value, "12-mfa-required");
    const trustedSession = await browserSession(value);
    await replaceBrowserSession(value, { ...trustedSession, user: { ...trustedSession.user, factors: [] } });
    await value.reload();
    await value.getByRole("link", { name: "Bekreft med autentiseringsappen", exact: true }).waitFor();
    assert.equal(await value.getByLabel(/^Nytt passord/u).count(), 0, "unsigned cookie factor metadata cannot remove MFA");
    await value.route("**/auth/v1/user", route => route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ message: "synthetic local read failure", code: "unexpected_failure" }) }));
    await activate(value, value.getByRole("link", { name: "Bekreft med autentiseringsappen", exact: true }));
    await value.getByRole("button", { name: "Prøv kontrollen igjen" }).waitFor();
    assert.equal(await value.getByRole("button", { name: "Sett opp autentiseringsapp" }).count(), 0);
    await captureFrontendStep(value, "13-mfa-status-error-synthetic");
    await value.unroute("**/auth/v1/user");
    await activate(value, value.getByRole("button", { name: "Prøv kontrollen igjen" }));
    await value.getByLabel("Autentiseringsapp", { exact: true }).waitFor();
    await tabTo(value, value.getByLabel("Autentiseringsapp", { exact: true })); await value.keyboard.press("r");
    assert.equal(await value.getByLabel("Autentiseringsapp", { exact: true }).inputValue(), factors[1].id);
    await captureFrontendStep(value, "14-mfa-backup-choice");
    await activate(value, value.locator("summary").filter({ hasText: "Kan ikke bruke autentiseringsappen?" }));
    await value.getByText("Tilgangen kan ikke gjenopprettes automatisk her.", { exact: false }).waitFor();
    await captureFrontendStep(value, "14b-mfa-lost-app-help");
    const correct = currentTotp(factors[1].totp.secret);
    const wrong = String((Number(correct) + 1) % 1_000_000).padStart(6, "0");
    await fillField(value, value.getByLabel("Sekssifret kode"), wrong);
    await activate(value, value.getByRole("button", { name: "Bekreft og fortsett" }));
    await value.locator('[role="alert"]').filter({ hasText: "Koden kunne ikke bekreftes" }).waitFor();
    assert.equal(await value.getByLabel("Sekssifret kode").inputValue(), "");
    await captureFrontendStep(value, "15-mfa-invalid-code");
    await fillField(value, value.getByLabel("Sekssifret kode"), currentTotp(factors[1].totp.secret));
    await activate(value, value.getByRole("button", { name: "Bekreft og fortsett" }));
    await value.getByRole("heading", { name: "Velg nytt passord" }).waitFor();
    await captureFrontendStep(value, "16-mfa-verified-reset-ready");
    await value.close();
  });
  assert.deepEqual(remote, [], "browser egress escaped the owned fixture");
  assert.equal((await database.query("select count(*)::int as count from public.companies where created_by = any($1::uuid[])", [ids])).rows[0].count, 0);
});

async function browserSession(page) {
  const cookies = (await page.context().cookies()).filter(({ name }) => /-auth-token(?:\.\d+)?$/u.test(name));
  assert.ok(cookies.length, "fixture auth session absent");
  cookies.sort((a, b) => a.name.localeCompare(b.name));
  const raw = cookies.map(({ value }) => value).join("");
  return JSON.parse(raw.startsWith("base64-") ? Buffer.from(raw.slice(7), "base64url").toString() : raw);
}
async function verifiedBrowserUser(page, auth) {
  const result = await auth.auth.getUser((await browserSession(page)).access_token);
  assert.equal(result.error, null); return result.data.user;
}
async function replaceBrowserSession(page, session) {
  const existing = (await page.context().cookies()).find(({ name }) => /-auth-token(?:\.\d+)?$/u.test(name));
  assert.ok(existing); const name = existing.name.replace(/\.\d+$/u, "");
  await page.context().clearCookies({ name: /-auth-token(?:\.\d+)?$/u });
  await page.context().addCookies([{ name, value: `base64-${Buffer.from(JSON.stringify(session)).toString("base64url")}`, url: page.url(), sameSite: "Lax" }]);
}
function currentTotp(secret) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const bits = [...secret.replace(/=+$/u, "")].map(char => alphabet.indexOf(char).toString(2).padStart(5, "0")).join("");
  const bytes = Buffer.from((bits.match(/.{8}/gu) || []).map(byte => parseInt(byte, 2)));
  const counter = Buffer.alloc(8); counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30_000)));
  const digest = createHmac("sha1", bytes).update(counter).digest(); const offset = digest[digest.length - 1] & 15;
  return String((digest.readUInt32BE(offset) & 0x7fff_ffff) % 1_000_000).padStart(6, "0");
}
