import assert from "node:assert/strict";
import { createHmac, randomUUID } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { createServer } from "node:http";
import test from "node:test";

import { createClient } from "@supabase/supabase-js";
import { chromium } from "playwright";
import pg from "pg";

import {
  cleanupBrowserOwnerResources,
  cleanupFailure,
} from "./support/browser-owner-cleanup.mjs";
import {
  allocateLoopbackPort,
  startOwnedProcess,
  waitForOwnedReadiness,
} from "./support/owned-process-lifecycle.mjs";
import {
  isLoopbackPostgresUrl,
  isLoopbackSupabaseUrl,
} from "./support/supabase_fixture_safety.mjs";

loadDotEnv();

const supabaseUrl =
  process.env.NEXT_PUBLIC_SUPABASE_URL || process.env.SUPABASE_URL;
const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
const anonKey =
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || process.env.SUPABASE_ANON_KEY;
const databaseUrl = process.env.DATABASE_URL;

test("a verified AAL1 owner completes accessible, fail-closed company onboarding through FastAPI", { timeout: 240_000 }, async (t) => {
  if (!supabaseUrl || !serviceRoleKey || !anonKey || !databaseUrl) {
    t.skip("Supabase env missing");
    return;
  }
  if (!isLoopbackSupabaseUrl(supabaseUrl) || !isLoopbackPostgresUrl(databaseUrl)) {
    t.skip("Browser onboarding fixtures require local Supabase");
    return;
  }

  const webPort = await allocateLoopbackPort();
  const backendPort = await allocateLoopbackPort();
  const brregPort = await allocateLoopbackPort();
  // Next server-action redirects canonicalize the development host to
  // `localhost`; keep one hostname so confirmation-session cookies never cross
  // the localhost/127.0.0.1 boundary.
  const baseUrl = `http://localhost:${webPort}`;
  const backendBaseUrl = `http://127.0.0.1:${backendPort}`;
  const brregBaseUrl = `http://127.0.0.1:${brregPort}`;
  const orgNumbers = {
    unsupported: "987654321",
    missing: "987654323",
    malformed: "987654324",
    supported: "987654322",
    secondSupported: "987654325",
  };
  const brregRequests = [];
  const brregControl = { failedOrgNumber: null };
  const browserRequests = [];
  const admin = createClient(supabaseUrl, serviceRoleKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  const database = new pg.Client({ connectionString: databaseUrl });
  const resources = {
    admin,
    backend: undefined,
    browser: undefined,
    cleanupBackendDatabaseRole: undefined,
    companyId: undefined,
    companyIds: [],
    database,
    databaseStarted: false,
    ownerId: undefined,
    primaryFailure: undefined,
    server: undefined,
  };
  const brreg = createBrregServer({ control: brregControl, orgNumbers, requests: brregRequests });
  t.after(async () => {
    await new Promise((resolve) => brreg.close(() => resolve()));
    if (resources.ownerId && resources.databaseStarted) {
      try {
        const created = await database.query(
          "select id from public.companies where created_by = $1 order by created_at desc",
          [resources.ownerId],
        );
        resources.companyIds = [...new Set([
          ...(resources.companyIds ?? []),
          ...created.rows.map(({ id }) => id),
        ])];
      } catch {
        // The shared cleanup helper reports any substantive teardown failure.
      }
    }
    const cleanupErrors = await cleanupBrowserOwnerResources(resources);
    const failure = cleanupFailure(resources.primaryFailure, cleanupErrors);
    if (failure) throw failure;
  });

  try {
    await new Promise((resolve, reject) => {
      brreg.once("error", reject);
      brreg.listen(brregPort, "127.0.0.1", resolve);
    });
    await database.connect();
    resources.databaseStarted = true;
    const backendDatabasePassword = randomUUID().replaceAll("-", "");
    const roleBoundary = await database.query(
      `select rolcanlogin, rolinherit, rolbypassrls,
        pg_catalog.pg_has_role('talli_company_access_backend', 'company_access_executor', 'set') as can_set_executor,
        pg_catalog.pg_has_role('talli_company_access_backend', 'company_access_recovery_executor', 'set') as can_set_recovery
       from pg_catalog.pg_roles where rolname = 'talli_company_access_backend'`,
    );
    assert.deepEqual(roleBoundary.rows, [{
      rolcanlogin: false,
      rolinherit: false,
      rolbypassrls: false,
      can_set_executor: true,
      can_set_recovery: true,
    }]);
    await database.query(
      `alter role talli_company_access_backend login password '${backendDatabasePassword}'`,
    );
    resources.cleanupBackendDatabaseRole = async () => {
      await database.query(
        "alter role talli_company_access_backend nologin password null",
      );
      resources.cleanupBackendDatabaseRole = undefined;
    };
    const backendDatabaseUrl = databaseUrlForBackendRole(
      databaseUrl,
      backendDatabasePassword,
    );
    const ownerEmail = `onboarding-${randomUUID()}@example.test`;
    const password = `Pw-${randomUUID()}-talli`;
    const { data: confirmation, error: confirmationError } =
      await admin.auth.admin.generateLink({
        type: "signup",
        email: ownerEmail,
        password,
      });
    assert.ifError(confirmationError);
    assert.ok(confirmation.properties.hashed_token, "fixture confirmation token is absent");
    assert.ok(!confirmation.user.email_confirmed_at, "fixture user started confirmed");
    const confirmationToken = confirmation.properties.hashed_token;
    resources.ownerId = confirmation.user.id;
    assert.equal(await actorState(database, resources.ownerId), "0:0:0:0:0:0:0");

    resources.backend = startBackendServer({
      anonKey,
      brregBaseUrl,
      databaseUrl: backendDatabaseUrl,
      port: backendPort,
      supabaseUrl,
    });
    await waitForOwnedReadiness({
      process: resources.backend,
      url: `${backendBaseUrl}/health/ready`,
    });
    resources.server = startNextServer({ backendBaseUrl, port: webPort });
    await waitForOwnedReadiness({ process: resources.server, url: baseUrl });

    resources.browser = await chromium.launch({ headless: true });
    const page = await resources.browser.newPage({ viewport: { width: 390, height: 844 } });
    const browserProblems = [];
    page.on("request", (request) => browserRequests.push(request.url()));
    page.on("console", (message) => {
      if (["error", "warning"].includes(message.type())) {
        browserProblems.push(`console:${message.type()}:${message.text()}`);
      }
    });
    page.on("pageerror", (error) => browserProblems.push(`pageerror:${error.message}`));

    await page.goto(`${baseUrl}/sjekk-selskapet`);
    await assertAccessibleEligibilityLookup(page);
    assert.equal(await hasHorizontalOverflow(page), false, "390px eligibility lookup overflows");

    // Public legal-form rejection is a business result, while registry 404 and
    // malformed provider data are distinct operational failures. None may write.
    await beginEligibility(page, orgNumbers.unsupported);
    const publicBlockHeading = page.getByRole("heading", { name: "Talli passer ikke for dette året" });
    await publicBlockHeading.waitFor();
    assert.equal(await publicBlockHeading.evaluate((element) => element === document.activeElement), true);
    assert.match(await page.locator("main").innerText(), /Foreløpig svar/u);
    assert.match(await page.locator("main").innerText(), /Bruk regnskapsfører/u);
    assert.equal(await actorState(database, resources.ownerId), "0:0:0:0:0:0:0");

    await page.getByRole("link", { name: "Start på nytt" }).click();
    await beginEligibility(page, orgNumbers.missing);
    await assertEligibilityFailureAndZeroState({ database, ownerId: resources.ownerId, page });
    assert.match(await errorAlert(page).innerText(), /Enhetsregisteret/u);

    await page.goto(`${baseUrl}/sjekk-selskapet`);
    await beginEligibility(page, orgNumbers.malformed, { keyboardSubmit: true });
    await assertEligibilityFailureAndZeroState({ database, ownerId: resources.ownerId, page });
    assert.match(await errorAlert(page).innerText(), /betyr ikke at selskapet er utenfor Talli/u);

    // Unknown private facts produce clarification with an exact next step and
    // no continuation or persistence.
    await page.goto(`${baseUrl}/sjekk-selskapet`);
    await beginEligibility(page, orgNumbers.supported, { keyboardSubmit: true });
    await answerEligibilityInterview(page, { unknownCode: "is_small_enterprise" });
    const clarifyHeading = page.getByRole("heading", { name: "Dette må avklares først" });
    await clarifyHeading.waitFor();
    assert.equal(await clarifyHeading.evaluate((element) => element === document.activeElement), true);
    assert.match(await page.locator("main").innerText(), /Avklar det ukjente med en regnskapsfører/u);
    assert.equal(await actorState(database, resources.ownerId), "0:0:0:0:0:0:0");
    assert.equal(
      (await page.context().cookies()).some(({ name }) => name === "talli_company_year_eligibility"),
      false,
      "clarification unexpectedly created an admission continuation",
    );

    // A known unsupported private fact is a definitive block, not a provisional
    // registry result and not a provider failure.
    await page.getByRole("link", { name: "Start på nytt" }).click();
    await beginEligibility(page, orgNumbers.supported);
    await answerEligibilityInterview(page, { blockedCode: "has_auditor_or_audit_requirement" });
    const definitiveBlockHeading = page.getByRole("heading", { name: "Talli passer ikke for dette året" });
    await definitiveBlockHeading.waitFor();
    assert.equal(await definitiveBlockHeading.evaluate((element) => element === document.activeElement), true);
    assert.doesNotMatch(await page.locator("main").innerText(), /Foreløpig svar · Utenfor grensen/u);
    assert.match(await page.locator("main").innerText(), /Bruk regnskapsfører/u);
    assert.equal(await actorState(database, resources.ownerId), "0:0:0:0:0:0:0");

    // The supported golden path answers the complete manifest, keeps the
    // continuation HTTP-only, and preserves it through login to admission.
    await page.getByRole("link", { name: "Start på nytt" }).click();
    await beginEligibility(page, orgNumbers.supported);
    await answerEligibilityInterview(page);
    const supportedHeading = page.getByRole("heading", { name: /kan bruke Talli/u });
    await supportedHeading.waitFor();
    assert.equal(await supportedHeading.evaluate((element) => element === document.activeElement), true);
    assert.match(await page.locator("main").innerText(), /komplett fra 1\. januar/u);
    assert.equal(await hasHorizontalOverflow(page), false, "390px supported result overflows");
    await page.setViewportSize({ width: 1280, height: 800 });
    assert.equal(await hasHorizontalOverflow(page), false, "desktop supported result overflows");
    await page.setViewportSize({ width: 390, height: 844 });
    const eligibilityCookie = (await page.context().cookies()).find(
      ({ name }) => name === "talli_company_year_eligibility",
    );
    assert.equal(eligibilityCookie?.httpOnly, true);
    assert.equal(eligibilityCookie?.sameSite, "Lax");

    await page.getByRole("link", { name: "Opprett konto og godta" }).click();
    await page.waitForURL((url) => url.pathname === "/signup" && url.searchParams.get("next") === "/onboarding");
    assert.equal(await page.locator('input[name="next"]').first().inputValue(), "/onboarding");
    assert.equal(await hasHorizontalOverflow(page), false, "390px signup form overflows");
    await page.getByRole("link", { name: "Logg inn" }).click();
    await page.waitForURL((url) => url.pathname === "/login" && url.searchParams.get("next") === "/onboarding");
    const loginForm = page.locator("form").filter({ hasText: "Logg inn" }).first();
    await loginForm.getByLabel("E-post").fill(ownerEmail);
    await loginForm.getByLabel("Passord").fill(password);
    await loginForm.getByRole("button", { name: "Logg inn" }).click();
    await page.waitForURL(
      (url) => url.pathname === "/verify-email" && url.searchParams.get("next") === "/onboarding",
      { timeout: 20_000 },
    );
    assert.equal(await page.locator('input[name="next"]').first().inputValue(), "/onboarding");
    assert.equal(
      await page.getByRole("link", { name: /tilbake til innlogging/iu }).getAttribute("href"),
      "/login?next=%2Fonboarding",
    );
    await page.goto(
      `${baseUrl}/auth/confirm?token_hash=${encodeURIComponent(confirmationToken)}&type=signup&next=%2Fonboarding`,
    );
    await page.waitForURL((url) => url.pathname === "/onboarding", { timeout: 20_000 });
    assert.equal(new URL(page.url()).pathname, "/onboarding");
    const confirmedSession = await browserSupabaseSession(page);
    assert.equal(jwtPayload(confirmedSession.access_token).aal, "aal1");
    const emptyContextResponse = await fetch(
      `${backendBaseUrl}/api/v1/company-access/context`,
      { headers: { Authorization: `Bearer ${confirmedSession.access_token}` } },
    );
    const emptyContext = await emptyContextResponse.json();
    assert.deepEqual(
      { status: emptyContextResponse.status, code: emptyContext.code },
      { status: 404, code: "COMPANY_CONTEXT_NOT_FOUND" },
      `verified no-company context failed closed incorrectly: ${JSON.stringify(emptyContext)}`,
    );

    const authority = page.getByLabel("Jeg bekrefter at jeg har fullmakt", { exact: false });
    await assertAccessibleAdmission({ authority, page });
    await authority.focus();
    await page.keyboard.press("Space");
    assert.equal(await authority.isChecked(), true, "Space did not accept the company-year promise");
    await page.getByRole("button", { name: "Godta og opprett selskapsåret" }).click();
    await page.waitForURL((url) => url.pathname === "/mfa", { timeout: 20_000 });
    await page.getByRole("heading", {
      name: "Beskytt kontoen før du fortsetter",
    }).waitFor({ state: "visible" });
    assert.equal(await actorState(database, resources.ownerId), "1:1:1:1:1:1:1");
    const startMfa = page.getByRole("button", {
      name: "Sett opp autentiseringsapp",
    });
    await startMfa.click();
    const secret = (await page.locator("code").innerText()).trim();
    assert.match(secret, /^[A-Z2-7]+=*$/u);
    const mfaCode = page.getByLabel("Sekssifret kode");
    assert.equal(await mfaCode.getAttribute("inputmode"), "numeric");
    await mfaCode.fill(currentTotp(secret));
    await page.getByRole("button", { name: "Bekreft og fortsett" }).click();
    await page.waitForURL((url) => url.pathname === "/onboarding", {
      timeout: 20_000,
    });
    const browserSession = await browserSupabaseSession(page);
    assert.equal(jwtPayload(browserSession.access_token).sub, resources.ownerId);
    assert.equal(jwtPayload(browserSession.access_token).aal, "aal2");
    const restrictedMemberships = await membershipsAsBackendActor({
      accessToken: browserSession.access_token,
      databaseUrl: backendDatabaseUrl,
    });
    assert.deepEqual(restrictedMemberships, [{
      accepted: true,
      userId: resources.ownerId,
    }]);
    const selectedContextResponse = await fetch(
      `${backendBaseUrl}/api/v1/company-access/context`,
      { headers: { Authorization: `Bearer ${browserSession.access_token}` } },
    );
    const selectedContext = await selectedContextResponse.json();
    assert.equal(
      selectedContextResponse.status,
      200,
      `AAL2 selected context failed: ${JSON.stringify({
        status: selectedContextResponse.status,
        code: selectedContext.code,
      })}`,
    );
    assert.deepEqual(
      selectedContext.companies?.map((company) => company.id),
      [selectedContext.selectedCompany.id],
    );
    assert.equal(selectedContext.selectedCompany.admittedAccountingYear, 2026);
    assert.equal(selectedContext.selectedCompany.currentEligibilityDecision, "supported");
    assert.equal(selectedContext.selectedCompany.consequentialOperationsAllowed, true);
    try {
      await page.getByRole("heading", { name: "Åpningsbalanse" }).waitFor({
        state: "visible",
        timeout: 10_000,
      });
    } catch {
      const state = await actorState(database, resources.ownerId);
      const body = (await page.locator("body").innerText()).replace(/\s+/gu, " ").trim();
      throw new Error(`supported_company_did_not_advance:state=${state}:body=${body.slice(0, 800)}`);
    }
    assert.equal(await page.getByLabel("Regnskapsår").inputValue(), "2026");

    const created = await database.query(
      "select id, name, entity_type from public.companies where org_number = $1",
      [orgNumbers.supported],
    );
    assert.deepEqual(created.rows.map(({ name, entity_type: entityType }) => ({ name, entityType })), [
      { name: "Talli Browser Holding AS", entityType: "AS" },
    ]);
    resources.companyId = created.rows[0].id;
    resources.companyIds.push(resources.companyId);
    assert.equal(await companyAtomicState(database, resources.companyId, resources.ownerId), "1:1:1:1:1:1:1");

    // A supported owner can report a material change through company_access.
    // The persisted block remains company-scoped, keeps the read surface open,
    // and distinguishes a later provider failure from customer ineligibility.
    await page.getByRole("button", { name: "Meny" }).click();
    await page.getByRole("link", { name: "Selskapsgrense" }).click();
    await page.getByRole("heading", { name: /Har opplysningene for Talli Browser Holding AS endret seg/u }).waitFor();
    await answerEligibilityInterview(page, {
      blockedCode: "has_auditor_or_audit_requirement",
      submitLabel: "Oppdater selskapsgrensen",
    });
    await page.waitForURL((url) => (
      url.pathname === "/selskapsgrense" && url.searchParams.get("result") === "blocked"
    ));
    assert.match(await page.locator("main").innerText(), /Selskapsgrensen må avklares/u);
    assert.equal(
      await companyEligibilityState(database, resources.companyId, resources.ownerId),
      "2:blocked:f:t",
    );
    assert.equal(await hasHorizontalOverflow(page), false, "390px material block overflows");

    brregControl.failedOrgNumber = orgNumbers.supported;
    await page.getByRole("button", { name: "Kontroller grensen på nytt" }).click();
    await page.waitForURL((url) => (
      url.pathname === "/selskapsgrense" && url.searchParams.has("error")
    ));
    const recheckFailure = page.getByRole("alert").filter({
      hasText: "Talli kunne ikke kontrollere selskapsgrensen",
    });
    await recheckFailure.waitFor();
    assert.match(await recheckFailure.innerText(), /Ingen opplysninger eller status ble endret/u);
    assert.equal(
      await companyEligibilityState(database, resources.companyId, resources.ownerId),
      "2:blocked:f:t",
      "provider failure unexpectedly changed the eligibility gate",
    );
    brregControl.failedOrgNumber = null;

    // The same owner can then check and admit a second company. The existing
    // blocked company notice must not replace or redirect the pending form.
    await page.getByRole("button", { name: "Meny" }).click();
    await page.getByRole("button", { name: "Logg ut" }).click();
    await page.waitForURL((url) => url.pathname === "/login");
    await page.goto(`${baseUrl}/sjekk-selskapet`);
    await beginEligibility(page, orgNumbers.secondSupported);
    await answerEligibilityInterview(page);
    await page.getByRole("heading", { name: "Talli Browser Invest AS kan bruke Talli" }).waitFor();
    await page.getByRole("link", { name: "Logg inn" }).click();
    await page.waitForURL((url) => url.pathname === "/login" && url.searchParams.get("next") === "/onboarding");
    const returningLogin = page.locator("form").filter({ hasText: "Logg inn" }).first();
    await returningLogin.getByLabel("E-post").fill(ownerEmail);
    await returningLogin.getByLabel("Passord").fill(password);
    await returningLogin.getByRole("button", { name: "Logg inn" }).click();
    await page.waitForURL((url) => url.pathname === "/onboarding", { timeout: 20_000 });
    await page.getByRole("heading", { name: "Bekreft innloggingen før du fortsetter" }).waitFor();
    await page.getByRole("link", { name: "Sett opp eller bekreft autentiseringsapp" }).click();
    await page.waitForURL((url) => url.pathname === "/mfa");
    await page.getByLabel("Sekssifret kode").fill(currentTotp(secret));
    await page.getByRole("button", { name: "Bekreft og fortsett" }).click();
    await page.waitForURL((url) => url.pathname === "/onboarding", { timeout: 20_000 });
    await page.getByText("Talli Browser Invest AS · 987654325", { exact: true }).waitFor();
    const secondAuthority = page.getByLabel("Jeg bekrefter at jeg har fullmakt", { exact: false });
    await secondAuthority.check();
    const reachedMfa = page.waitForURL((url) => url.pathname === "/mfa", { timeout: 20_000 });
    await page.getByRole("button", { name: "Godta og opprett selskapsåret" }).click();
    await reachedMfa;
    await page.waitForURL((url) => url.pathname === "/onboarding", { timeout: 20_000 });
    assert.equal(
      (await page.context().cookies()).some(({ name }) => name === "talli_company_year_eligibility"),
      false,
      "second admission did not clear its continuation",
    );
    const secondCreated = await database.query(
      "select id from public.companies where org_number = $1",
      [orgNumbers.secondSupported],
    );
    const secondCompanyId = secondCreated.rows[0]?.id;
    assert.ok(secondCompanyId, "second admitted company is absent");
    resources.companyIds.push(secondCompanyId);
    assert.equal(await companyAtomicState(database, resources.companyId, resources.ownerId), "1:1:1:1:1:1:1");
    assert.equal(await companyAtomicState(database, secondCompanyId, resources.ownerId), "1:1:1:1:1:1:1");
    assert.equal(await actorState(database, resources.ownerId), "2:2:2:3:2:2:3");

    const secondSession = await browserSupabaseSession(page);
    assert.equal(jwtPayload(secondSession.access_token).aal, "aal2");
    const bothContextResponse = await fetch(
      `${backendBaseUrl}/api/v1/company-access/context`,
      { headers: { Authorization: `Bearer ${secondSession.access_token}` } },
    );
    const bothContext = await bothContextResponse.json();
    assert.equal(bothContextResponse.status, 200, JSON.stringify(bothContext));
    assert.deepEqual(
      bothContext.companies.map((company) => ({
        allowed: company.consequentialOperationsAllowed,
        decision: company.currentEligibilityDecision,
        orgNumber: company.orgNumber,
        year: company.admittedAccountingYear,
      })).sort((left, right) => left.orgNumber.localeCompare(right.orgNumber)),
      [
        { allowed: false, decision: "blocked", orgNumber: orgNumbers.supported, year: 2026 },
        { allowed: true, decision: "supported", orgNumber: orgNumbers.secondSupported, year: 2026 },
      ],
    );
    assert.deepEqual(
      (await membershipsAsBackendActor({
        accessToken: secondSession.access_token,
        databaseUrl: backendDatabaseUrl,
      })).sort((left, right) => left.userId.localeCompare(right.userId)),
      [
        { accepted: true, userId: resources.ownerId },
        { accepted: true, userId: resources.ownerId },
      ],
    );

    const brregRequestCounts = Object.fromEntries(Object.values(orgNumbers).map((orgNumber) => [
      orgNumber,
      brregRequests.filter((path) => path.endsWith(`/${orgNumber}`)).length,
    ]));
    assert.deepEqual(brregRequestCounts, {
      [orgNumbers.unsupported]: 1,
      [orgNumbers.missing]: 1,
      [orgNumbers.malformed]: 1,
      [orgNumbers.supported]: 12,
      [orgNumbers.secondSupported]: 3,
    });
    for (const url of browserRequests) {
      assert.ok(isLoopbackUrl(url), `browser contacted a non-loopback service: ${url}`);
    }
    assert.deepEqual(browserProblems, []);
  } catch (error) {
    resources.primaryFailure = error;
    throw error;
  }
});

async function assertAccessibleEligibilityLookup(page) {
  await page.getByRole("heading", { name: "Sjekk selskapet gratis" }).waitFor();
  const orgNumber = page.getByLabel("Organisasjonsnummer");
  const submit = page.getByRole("button", { name: "Sjekk selskapet gratis" });
  await orgNumber.waitFor({ state: "visible" });
  await submit.waitFor({ state: "visible" });
  assert.equal(await orgNumber.getAttribute("required"), "");
  assert.equal(await orgNumber.getAttribute("inputmode"), "numeric");
  const describedBy = await orgNumber.getAttribute("aria-describedby");
  assert.ok(describedBy, "organization number has no accessible description");
  assert.match(await page.locator(`#${describedBy}`).innerText(), /offentlige opplysninger/u);
  await orgNumber.focus();
  assert.equal(await orgNumber.evaluate((element) => element === document.activeElement), true);
}

async function beginEligibility(page, orgNumberValue, { keyboardSubmit = false } = {}) {
  const orgNumber = page.getByLabel("Organisasjonsnummer");
  await orgNumber.fill(orgNumberValue);
  if (keyboardSubmit) {
    await orgNumber.press("Enter");
  } else {
    await page.getByRole("button", { name: "Sjekk selskapet gratis" }).click();
  }
}

async function answerEligibilityInterview(page, {
  blockedCode,
  submitLabel = "Se endelig svar",
  unknownCode,
} = {}) {
  const noIsSupported = new Set([
    "has_auditor_or_audit_requirement",
    "requires_consolidated_accounts",
    "conducts_regulated_finance",
  ]);
  for (let index = 0; index < 31; index += 1) {
    const ordinal = index + 1;
    await page.getByText(`Spørsmål ${ordinal} av 31`, { exact: true }).waitFor();
    const fieldset = page.locator("fieldset");
    if (index > 0) {
      const legend = fieldset.locator("legend");
      assert.equal(
        await legend.evaluate((element) => element === document.activeElement),
        true,
        `question ${ordinal} did not receive focus`,
      );
    }
    const firstRadio = fieldset.locator('input[type="radio"]').first();
    const inputName = await firstRadio.getAttribute("name");
    assert.match(inputName ?? "", /^visible:[a-z0-9_]+$/u);
    const code = inputName.slice("visible:".length);
    const label = code === unknownCode
      ? "Vet ikke"
      : code === blockedCode
        ? "Ja"
        : noIsSupported.has(code)
          ? "Nei"
          : "Ja";
    const radio = fieldset.getByLabel(label, { exact: true });
    if (index === 0) {
      await radio.focus();
      await page.keyboard.press("Space");
      assert.equal(await radio.isChecked(), true, "keyboard did not select an eligibility answer");
    } else {
      await radio.check();
    }
    if (index === 30) {
      await page.getByRole("button", { name: submitLabel }).click();
    } else {
      await page.getByRole("button", { name: "Neste" }).click();
    }
  }
}

async function assertAccessibleAdmission({ authority, page }) {
  try {
    await authority.waitFor({ state: "visible", timeout: 10_000 });
  } catch {
    const body = (await page.locator("body").innerText()).replace(/\s+/gu, " ").trim();
    throw new Error(`company_year_admission_form_unavailable:${body.slice(0, 800)}`);
  }
  assert.equal(await authority.isChecked(), false, "authority checkbox started checked");
  assert.equal(await authority.getAttribute("required"), "");
  const describedBy = await authority.getAttribute("aria-describedby");
  assert.ok(describedBy, "authority checkbox has no accessible description");
  assert.match(await page.locator(`#${describedBy}`).innerText(), /fullmakt.+brukervilkårene.+databehandleravtalen.+personvernerklæringen/isu);
  assert.match(
    await page.locator("main").innerText(),
    /Komplett gjenoppbygging.+Bokføring.+selskapsdokumenter.+aksjonærregisteroppgaven.+skattemeldingen.+årsregnskapet.+Banktilkobling.+SAF-T.+Komplett selskapsårsarkiv.+eneste regnskaps-/isu,
  );
  assert.equal(await hasHorizontalOverflow(page), false, "390px admission form overflows");
}

async function assertEligibilityFailureAndZeroState({ database, ownerId, page }) {
  const alert = errorAlert(page);
  await alert.waitFor({ state: "visible", timeout: 20_000 });
  assert.ok((await alert.innerText()).trim().length > 0, "failure alert has no accessible text");
  assert.equal(await actorState(database, ownerId), "0:0:0:0:0:0:0");
}

async function hasHorizontalOverflow(page) {
  return page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
}

function errorAlert(page) {
  return page.getByRole("alert").filter({ hasText: /\S/u }).last();
}

async function actorState(database, ownerId) {
  const result = await database.query(
    `select concat_ws(':',
      (select count(*) from public.companies where created_by = $1),
      (select count(*) from public.company_memberships where user_id = $1),
      (select count(*) from public.customer_agreement_acceptances where accepted_by = $1),
      (select count(*) from public.company_eligibility_assessments where assessed_by = $1),
      (select count(*) from public.company_year_admissions where admitted_by = $1),
      (select count(*) from public.company_year_acceptances where accepted_by = $1),
      (select count(*) from public.company_access_command_receipts where actor_id = $1)) as state`,
    [ownerId],
  );
  return result.rows[0].state;
}

async function companyAtomicState(database, companyId, ownerId) {
  const result = await database.query(
    `select concat_ws(':',
      (select count(*) from public.companies where id = $1 and created_by = $2),
      (select count(*) from public.company_memberships where company_id = $1 and user_id = $2 and role = 'owner' and accepted_at is not null),
      (select count(*) from public.customer_agreement_acceptances where company_id = $1 and accepted_by = $2),
      (select count(*) from public.company_eligibility_assessments where company_id = $1 and assessed_by = $2 and trigger = 'initial_admission' and decision = 'supported'),
      (select count(*) from public.company_year_admissions where company_id = $1 and admitted_by = $2 and reconstruct_from = date '2026-01-01'),
      (select count(*) from public.company_year_acceptances where company_id = $1 and accepted_by = $2),
      (select count(*) from public.company_access_command_receipts where company_id = $1 and actor_id = $2 and command_name = 'admit_company_year')) as state`,
    [companyId, ownerId],
  );
  return result.rows[0].state;
}

async function companyEligibilityState(database, companyId, ownerId) {
  const result = await database.query(
    `select concat_ws(':',
      count(*),
      (array_agg(decision order by assessed_at desc, id desc))[1],
      (array_agg(consequential_operations_allowed order by assessed_at desc, id desc))[1],
      (array_agg(archive_export_available order by assessed_at desc, id desc))[1]) as state
     from public.company_eligibility_assessments
     where company_id = $1 and assessed_by = $2`,
    [companyId, ownerId],
  );
  return result.rows[0].state;
}

function jwtPayload(token) {
  return JSON.parse(Buffer.from(token.split(".")[1], "base64url").toString("utf8"));
}

async function browserSupabaseSession(page) {
  const storageKey = `sb-${new URL(supabaseUrl).hostname.split(".")[0]}-auth-token`;
  const cookies = await page.context().cookies();
  const exact = cookies.find((cookie) => cookie.name === storageKey);
  const encoded = exact?.value ?? cookies
    .filter((cookie) => cookie.name.startsWith(`${storageKey}.`))
    .sort((left, right) =>
      Number(left.name.slice(storageKey.length + 1))
      - Number(right.name.slice(storageKey.length + 1)))
    .map((cookie) => cookie.value)
    .join("");
  assert.ok(encoded, "browser Supabase session cookie is absent after MFA");
  const serialized = encoded.startsWith("base64-")
    ? Buffer.from(encoded.slice("base64-".length), "base64url").toString("utf8")
    : encoded;
  const session = JSON.parse(serialized);
  assert.ok(session.access_token, "browser Supabase session cookie has no access token");
  return session;
}

async function membershipsAsBackendActor({ accessToken, databaseUrl: restrictedDatabaseUrl }) {
  const claims = jwtPayload(accessToken);
  const database = new pg.Client({ connectionString: restrictedDatabaseUrl });
  await database.connect();
  try {
    await database.query("begin");
    await database.query("set local role company_access_executor");
    await database.query(
      "select pg_catalog.set_config('talli.verified_actor_id', $1, true)",
      [claims.sub],
    );
    await database.query(
      "select pg_catalog.set_config('talli.verified_actor_claims', $1, true)",
      [JSON.stringify({
        aal: claims.aal,
        amr: claims.amr,
        email: claims.email,
        role: "authenticated",
        sub: claims.sub,
      })],
    );
    const result = await database.query(
      `select user_id as "userId", accepted_at is not null as accepted
       from public.company_memberships
       where user_id = public.company_access_auth_uid_v1()`,
    );
    await database.query("rollback");
    return result.rows;
  } finally {
    await database.end();
  }
}

function currentTotp(secret, now = Date.now()) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const character of secret.toUpperCase().replaceAll("=", "")) {
    const value = alphabet.indexOf(character);
    assert.notEqual(value, -1, "MFA secret is not canonical base32");
    bits += value.toString(2).padStart(5, "0");
  }
  const key = Buffer.from(
    Array.from({ length: Math.floor(bits.length / 8) }, (_, index) =>
      Number.parseInt(bits.slice(index * 8, index * 8 + 8), 2),
    ),
  );
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(now / 30_000)));
  const digest = createHmac("sha1", key).update(counter).digest();
  const offset = digest.at(-1) & 0x0f;
  const code = (digest.readUInt32BE(offset) & 0x7fffffff) % 1_000_000;
  return String(code).padStart(6, "0");
}

function databaseUrlForBackendRole(value, password) {
  const url = new URL(value);
  assert.ok(isLoopbackPostgresUrl(value), "backend database fixture escaped loopback");
  url.username = "talli_company_access_backend";
  url.password = password;
  return url.toString();
}

function isLoopbackUrl(value) {
  const hostname = new URL(value).hostname;
  return hostname === "127.0.0.1" || hostname === "localhost" || hostname === "[::1]";
}

function createBrregServer({ control, orgNumbers, requests }) {
  return createServer((request, response) => {
    requests.push(request.url ?? "");
    const orgNumber = request.url?.split("/").at(-1);
    if (orgNumber === control.failedOrgNumber) {
      response.writeHead(503, { "Content-Type": "application/json" });
      response.end(JSON.stringify({ message: "fixture provider unavailable" }));
      return;
    }
    if (orgNumber === orgNumbers.missing) {
      response.writeHead(404, { "Content-Type": "application/json" });
      response.end(JSON.stringify({ message: "not found" }));
      return;
    }
    if (orgNumber === orgNumbers.malformed) {
      response.writeHead(200, { "Content-Type": "application/json" });
      response.end(JSON.stringify({ organisasjonsnummer: orgNumber, navn: "" }));
      return;
    }
    if (![orgNumbers.supported, orgNumbers.secondSupported, orgNumbers.unsupported].includes(orgNumber)) {
      response.writeHead(404, { "Content-Type": "application/json" }).end();
      return;
    }
    response.writeHead(200, { "Content-Type": "application/json" });
    response.end(JSON.stringify({
      organisasjonsnummer: orgNumber,
      navn: orgNumber === orgNumbers.supported
        ? "Talli Browser Holding AS"
        : orgNumber === orgNumbers.secondSupported
          ? "Talli Browser Invest AS"
        : "Talli Browser Enkeltpersonforetak",
      organisasjonsform: {
        kode: [orgNumbers.supported, orgNumbers.secondSupported].includes(orgNumber)
          ? "AS"
          : "ENK",
      },
      konkurs: false,
      underAvvikling: false,
      underTvangsavviklingEllerTvangsopplosning: false,
      forretningsadresse: {
        adresse: ["Storgata 1"],
        postnummer: "0155",
        poststed: "OSLO",
      },
    }));
  });
}

function startBackendServer({ port, supabaseUrl: localSupabaseUrl, anonKey: localAnonKey, brregBaseUrl, databaseUrl: localDatabaseUrl }) {
  const backendPython =
    process.env.TALLI_BACKEND_PYTHON_BIN || "apps/backend/.venv/bin/python";
  if (!existsSync(backendPython)) throw new Error("backend_python_missing");
  const readinessNonce = randomUUID();
  return startOwnedProcess({
    command: backendPython,
    args: ["tests/fixtures/start_talli_backend.py"],
    cwd: process.cwd(),
    env: {
      PATH: process.env.PATH,
      BRREG_BASE_URL: brregBaseUrl,
      BRREG_TIMEOUT_SECONDS: "2",
      SUPABASE_URL: localSupabaseUrl,
      SUPABASE_ANON_KEY: localAnonKey,
      TALLI_COMPANY_ACCESS_DATABASE_URL: localDatabaseUrl,
      TALLI_BACKEND_PORT: String(port),
      TALLI_READINESS_NONCE: readinessNonce,
    },
    readinessProof: `TALLI_BACKEND_BOUND:${readinessNonce}`,
  });
}

function startNextServer({ port, backendBaseUrl }) {
  return startOwnedProcess({
    command: process.execPath,
    args: [
      "node_modules/next/dist/bin/next",
      "dev",
      "apps/web",
      "--hostname",
      "127.0.0.1",
      "--port",
      String(port),
    ],
    cwd: process.cwd(),
    env: {
      PATH: process.env.PATH,
      NODE_ENV: "test",
      NEXT_PUBLIC_SUPABASE_URL: supabaseUrl,
      NEXT_PUBLIC_SUPABASE_ANON_KEY: anonKey,
      SUPABASE_URL: supabaseUrl,
      SUPABASE_ANON_KEY: anonKey,
      TALLI_BACKEND_URL: backendBaseUrl,
    },
    readinessProof: "Ready in",
  });
}

function loadDotEnv() {
  if (!existsSync(".env")) return;
  for (const line of readFileSync(".env", "utf8").split(/\r?\n/u)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) continue;
    const [key, ...valueParts] = trimmed.split("=");
    if (!process.env[key]) {
      process.env[key] = valueParts.join("=").replace(/^["']|["']$/gu, "");
    }
  }
}
