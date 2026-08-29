import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import test from "node:test";

import { chromium } from "playwright";

import {
  allocateLoopbackPort,
  ownedProcessDiagnostics,
  startOwnedProcess,
  stopOwnedProcess,
  waitForOwnedReadiness,
} from "./support/owned-process-lifecycle.mjs";

const nextCli = createRequire(
  new URL("../apps/web/package.json", import.meta.url),
).resolve("next/dist/bin/next");
const internalKey = "browser-only-marketing-measurement-key";

test("the production public journey is consent-silent, accessible, mobile-safe, and privacy bounded", { timeout: 180_000 }, async (t) => {
  assert.equal(
    existsSync(new URL("../apps/web/.next/BUILD_ID", import.meta.url)),
    true,
    "Run the production web build before the public acquisition browser gate",
  );
  const webPort = await allocateLoopbackPort();
  const backendPort = await allocateLoopbackPort();
  const baseUrl = `http://127.0.0.1:${webPort}`;
  const backendBaseUrl = `http://127.0.0.1:${backendPort}`;
  const backendRequests = [];
  const backendProblems = [];
  const backend = createMeasurementBackend({
    internalKey,
    problems: backendProblems,
    requests: backendRequests,
  });
  let next;
  let browser;

  t.after(async () => {
    await browser?.close();
    await stopOwnedProcess(next);
    await new Promise((resolve) => backend.close(() => resolve()));
  });

  await new Promise((resolve, reject) => {
    backend.once("error", reject);
    backend.listen(backendPort, "127.0.0.1", resolve);
  });
  next = startOwnedProcess({
    command: process.execPath,
    args: [
      nextCli,
      "start",
      "apps/web",
      "--hostname",
      "127.0.0.1",
      "--port",
      String(webPort),
    ],
    cwd: process.cwd(),
    env: {
      ...process.env,
      NODE_ENV: "production",
      TALLI_BACKEND_URL: backendBaseUrl,
      TALLI_MARKETING_MEASUREMENT_INTERNAL_KEY: internalKey,
      TALLI_PUBLIC_ORIGIN: baseUrl,
    },
    readinessProof: "Ready in",
  });
  try {
    await waitForOwnedReadiness({ process: next, url: baseUrl });
  } catch (error) {
    throw new Error(
      `${error instanceof Error ? error.message : String(error)}\n${ownedProcessDiagnostics(next)}`,
    );
  }

  browser = await chromium.launch({ headless: true });
  const guardedSignup = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await guardedSignup.goto(`${baseUrl}/signup?next=%2Fonboarding`);
  await guardedSignup.waitForURL(`${baseUrl}/sjekk-selskapet`);
  assert.equal(
    await guardedSignup.getByRole("heading", { name: "Sjekk selskapet gratis" }).isVisible(),
    true,
    "signup did not fail closed without a definitive eligibility continuation",
  );
  await guardedSignup.close();

  const desktop = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const browserProblems = [];
  const browserUrls = [];
  const firstPartyRequests = [];
  desktop.on("request", (request) => {
    browserUrls.push(request.url());
    if (request.url() === `${baseUrl}/api/marketing-events`) {
      firstPartyRequests.push(request.postData());
    }
  });
  desktop.on("console", (message) => {
    if (message.type() === "error") browserProblems.push(`console:${message.text()}`);
  });
  desktop.on("pageerror", (error) => browserProblems.push(`pageerror:${error.message}`));

  const navigationStarted = Date.now();
  const homeResponse = await desktop.goto(
    `${baseUrl}/?source=community&private=do-not-send`,
    { waitUntil: "load" },
  );
  const wallNavigationMs = Date.now() - navigationStarted;
  assert.equal(homeResponse?.status(), 200);
  await desktop.getByRole("heading", { name: "Hele selskapsåret i ett rolig løp" }).waitFor();
  await desktop.waitForTimeout(300);
  assert.equal(firstPartyRequests.length, 0, "measurement request occurred before consent");
  assert.equal(await desktop.evaluate(() => sessionStorage.length), 0, "optional storage existed before consent");
  assert.equal(await hasHorizontalOverflow(desktop), false, "desktop homepage overflows");

  const keyboardOrder = [];
  for (let index = 0; index < 80; index += 1) {
    await desktop.keyboard.press("Tab");
    const focused = await desktop.evaluate(() => {
      const element = document.activeElement;
      return element instanceof HTMLElement
        ? element.getAttribute("aria-label") || element.innerText || element.textContent || ""
        : "";
    });
    keyboardOrder.push(focused.trim());
    if (focused.includes("Tillat bruksmåling")) break;
  }
  assert.ok(keyboardOrder.some((label) => label.includes("Sjekk selskapet gratis")));
  assert.ok(keyboardOrder.at(-1)?.includes("Tillat bruksmåling"));
  assert.equal(await focusedControlHasVisibleOutline(desktop), true);

  await desktop.keyboard.press("Enter");
  await waitFor(() => backendRequests.some((request) => request.body.event === "home_view"));
  await desktop.getByRole("complementary", { name: "Hjelp oss forbedre selskapsjekken" })
    .locator("[aria-live='polite']")
    .getByText("Valget er lagret for denne fanen. Måling lagres bare når den viste personvernversjonen er godkjent og aktiv.")
    .waitFor();
  assert.equal(await desktop.evaluate(() => sessionStorage.length), 1);
  const homeEvent = backendRequests.find((request) => request.body.event === "home_view");
  assert.deepEqual(Object.keys(homeEvent.body).sort(), [
    "anonymousSessionHash",
    "campaignSource",
    "clientEventId",
    "consentVersion",
    "event",
    "firstLayerNoticeSha256",
    "firstLayerNoticeVersion",
    "privacyNoticeSha256",
    "privacyNoticeVersion",
    "reason",
    "releaseSha256",
    "surface",
  ]);
  assert.match(homeEvent.body.anonymousSessionHash, /^[a-f0-9]{64}$/u);
  assert.equal("anonymousSessionId" in homeEvent.body, false);
  assert.equal(homeEvent.body.consentVersion, "marketing-analytics-v1");
  assert.equal(homeEvent.body.firstLayerNoticeVersion, "candidate-2026-08-29");
  assert.match(homeEvent.body.firstLayerNoticeSha256, /^[a-f0-9]{64}$/u);
  assert.equal(homeEvent.body.privacyNoticeVersion, "unapproved");
  assert.equal(homeEvent.body.privacyNoticeSha256, "unapproved");
  assert.equal(homeEvent.body.releaseSha256, "unapproved");
  assert.equal(homeEvent.body.campaignSource, "community");
  assert.equal(homeEvent.headers.referer, undefined, "measurement leaked the landing URL");

  await desktop.getByRole("link", { name: "Sjekk selskapet gratis" }).first().click();
  await desktop.waitForURL(/\/sjekk-selskapet$/u);
  await waitFor(() => backendRequests.some((request) => request.body.event === "eligibility_start"));
  const eligibilityEvent = backendRequests.find((request) => request.body.event === "eligibility_start");
  assert.equal(eligibilityEvent.body.campaignSource, "community");
  assert.match(desktop.url(), /\/sjekk-selskapet$/u);
  await desktop.getByLabel("Organisasjonsnummer").fill("314159265");
  await desktop.getByRole("button", { name: "Sjekk selskapet gratis" }).click();
  await desktop.getByText("Offentlige opplysninger ser riktige ut").waitFor();
  await waitFor(() => backendRequests.some((request) => request.body?.event === "provisional_supported"));
  await desktop.getByLabel("Ja").check();
  await desktop.getByRole("button", { name: "Se endelig svar" }).click();
  await desktop.getByRole("heading", { name: "Rolig Holding AS kan bruke Talli" }).waitFor();
  await waitFor(() => backendRequests.some((request) => request.body?.event === "definitive_eligible"));
  const measuredEligibilityBodies = backendRequests
    .filter((request) => request.path === "/api/v1/marketing-measurement/events")
    .map((request) => JSON.stringify(request.body));
  assert.ok(measuredEligibilityBodies.every((body) => !body.includes("314159265")));
  assert.ok(measuredEligibilityBodies.every((body) => !body.includes("Rolig Holding AS")));
  await desktop.getByRole("link", { name: "Opprett konto og godta" }).click();
  await desktop.waitForURL(/\/signup\?next=%2Fonboarding$/u);
  try {
    await waitFor(() => backendRequests.some((request) => request.body?.event === "signup_start"));
  } catch (error) {
    throw new Error(`signup_start was not measured: ${JSON.stringify({
      browserProblems,
      events: backendRequests.map((request) => request.body?.event).filter(Boolean),
      sessionStorage: await desktop.evaluate(() => Object.fromEntries(
        Array.from({ length: sessionStorage.length }, (_, index) => {
          const key = sessionStorage.key(index) ?? "";
          return [key, sessionStorage.getItem(key)];
        }),
      )),
    })}`, { cause: error });
  }
  await desktop.goto(baseUrl);
  await desktop.getByRole("button", { name: "Trekk samtykke og slett økten" }).click();
  await waitFor(() => backendRequests.some((request) => request.path.endsWith("/withdrawals")));
  await desktop.getByRole("complementary", { name: "Hjelp oss forbedre selskapsjekken" })
    .locator("[aria-live='polite']")
    .getByText("Samtykket er trukket, og økten med tilfeldig ID er slettet.")
    .waitFor();
  assert.equal(await desktop.evaluate(() => sessionStorage.length), 0);

  const navigation = await desktop.evaluate(() => {
    const entry = performance.getEntriesByType("navigation")[0];
    const resources = performance.getEntriesByType("resource");
    return {
      domContentLoaded: entry?.domContentLoadedEventEnd ?? Number.POSITIVE_INFINITY,
      duration: entry?.duration ?? Number.POSITIVE_INFINITY,
      encodedBytes: resources.reduce((total, item) => total + (item.encodedBodySize || 0), 0),
      resourceCount: resources.length,
    };
  });
  assert.ok(wallNavigationMs < 5_000, `production navigation took ${wallNavigationMs}ms`);
  assert.ok(navigation.domContentLoaded < 3_000, `DOMContentLoaded took ${navigation.domContentLoaded}ms`);
  assert.ok(navigation.duration < 4_000, `load took ${navigation.duration}ms`);
  assert.ok(navigation.encodedBytes < 1_500_000, `page transferred ${navigation.encodedBytes} encoded bytes`);
  assert.ok(navigation.resourceCount < 50, `page loaded ${navigation.resourceCount} resources`);
  assert.deepEqual(
    [...new Set(browserUrls.map((value) => new URL(value).origin))],
    [baseUrl],
    "browser made unexpected cross-origin requests",
  );

  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const mobileFirstPartyRequests = [];
  const mobileProblems = [];
  mobile.on("request", (request) => {
    if (request.url() === `${baseUrl}/api/marketing-events`) {
      mobileFirstPartyRequests.push(request.postData());
    }
  });
  mobile.on("console", (message) => {
    if (message.type() === "error") mobileProblems.push(`console:${message.text()}`);
  });
  mobile.on("pageerror", (error) => mobileProblems.push(`pageerror:${error.message}`));
  await mobile.goto(baseUrl, { waitUntil: "load" });
  await mobile.getByRole("button", { name: "Nei takk" }).click();
  await mobile.waitForTimeout(200);
  assert.equal(mobileFirstPartyRequests.length, 0, "decline sent a measurement request");
  assert.equal(await mobile.evaluate(() => sessionStorage.length), 0);
  assert.equal(await hasHorizontalOverflow(mobile), false, "390px homepage overflows");
  assert.equal(await minimumConsentContrast(mobile) >= 4.5, true, "consent text contrast is below 4.5:1");

  await mobile.setViewportSize({ width: 640, height: 450 });
  assert.equal(await hasHorizontalOverflow(mobile), false, "homepage overflows at 200% desktop zoom");
  await mobile.setViewportSize({ width: 320, height: 640 });
  assert.equal(await hasHorizontalOverflow(mobile), false, "homepage fails 320px reflow");
  assert.equal(
    await mobile.getByRole("link", { name: "Sjekk selskapet gratis" }).first().isVisible(),
    true,
  );

  for (const [path, heading] of [
    ["/pris", "NOK 1,490 inkl. mva."],
    ["/hjelp", "Finn neste trygge steg"],
    ["/personvern", "Personvernerklæring"],
    ["/sikkerhet", "Stopp først når bevis mangler"],
    ["/status", "Gratis rekruttering · produksjon stengt"],
  ]) {
    const response = await mobile.goto(`${baseUrl}${path}`);
    assert.equal(response?.status(), 200, `${path} did not render`);
    assert.equal(await hasHorizontalOverflow(mobile), false, `${path} overflows at mobile width`);
    assert.match(await mobile.locator("h1").first().innerText(), new RegExp(heading, "iu"));
  }

  assert.deepEqual(backendProblems, []);
  assert.deepEqual(browserProblems, []);
  assert.deepEqual(mobileProblems, []);
});

function createMeasurementBackend({ internalKey: expectedKey, problems, requests }) {
  return createServer((request, response) => {
    const chunks = [];
    request.on("data", (chunk) => chunks.push(chunk));
    request.on("end", () => {
      try {
        const body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString("utf8")) : null;
        requests.push({ path: request.url, body, headers: request.headers });
        response.setHeader("content-type", "application/json");
        if (request.url === "/api/v1/marketing-measurement/events") {
          assert.equal(request.headers["x-talli-marketing-measurement-key"], expectedKey);
          response.statusCode = 202;
          response.end(JSON.stringify({ accepted: true, duplicate: false }));
          return;
        }
        if (request.url === "/api/v1/marketing-measurement/withdrawals") {
          assert.equal(request.headers["x-talli-marketing-measurement-key"], expectedKey);
          response.statusCode = 200;
          response.end(JSON.stringify({ deletedEventCount: 1 }));
          return;
        }
        if (request.url === "/api/v1/company-access/eligibility/precheck") {
          response.statusCode = 200;
          response.end(JSON.stringify(eligibilityResult({ provisional: true })));
          return;
        }
        if (request.url === "/api/v1/company-access/eligibility/definitive") {
          response.statusCode = 200;
          response.end(JSON.stringify(eligibilityResult({ provisional: false })));
          return;
        }
        response.statusCode = 404;
        response.end(JSON.stringify({ code: "not_found" }));
      } catch (error) {
        problems.push(error instanceof Error ? error.message : String(error));
        response.statusCode = 400;
        response.end(JSON.stringify({ code: "invalid_fixture_request" }));
      }
    });
  });
}

function eligibilityResult({ provisional }) {
  return {
    accountingYear: 2026,
    answers: provisional ? {} : { is_small_enterprise: "yes" },
    answersSha256: provisional ? null : "c".repeat(64),
    capabilityManifestSha256: "a".repeat(64),
    capabilityManifestVersion: "2026.1",
    companyYearPromise: provisional ? null : {
      accountingYear: 2026,
      customerClaims: ["komplett gjenoppbygging fra 1. januar"],
      endsOn: "2026-12-31",
      onlyAccountingAndFilingProduct: true,
      reconstructionRequiredFrom: "2026-01-01",
      startsOn: "2026-01-01",
    },
    decision: "supported",
    nextStep: provisional
      ? "Svar på ett spørsmål for et endelig svar."
      : "Opprett konto og godta selskapsåret når du er klar.",
    nextStepCode: provisional ? "ANSWER_QUESTIONS" : "CREATE_ACCOUNT_AND_ACCEPT",
    provisional,
    publicFacts: {
      entityType: "AS",
      name: "Rolig Holding AS",
      orgNumber: "314159265",
      source: "brreg",
      statusText: "aktiv",
    },
    publicFactsSha256: "b".repeat(64),
    questionCodes: ["is_small_enterprise"],
    questions: [{
      answerOptions: ["yes", "no", "unknown"],
      code: "is_small_enterprise",
      prompt: "Er selskapet et lite foretak?",
    }],
    reasonCodes: [],
    reasonExplanations: [],
  };
}

async function waitFor(predicate, timeoutMs = 5_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  assert.fail("browser measurement state did not arrive before the deadline");
}

async function hasHorizontalOverflow(page) {
  return page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
}

async function focusedControlHasVisibleOutline(page) {
  return page.evaluate(() => {
    const element = document.activeElement;
    if (!(element instanceof HTMLElement)) return false;
    const style = getComputedStyle(element);
    return style.outlineStyle !== "none" && Number.parseFloat(style.outlineWidth) >= 2;
  });
}

async function minimumConsentContrast(page) {
  return page.getByRole("complementary").evaluate((panel) => {
    const rgb = (value) => (value.match(/[\d.]+/gu) ?? []).slice(0, 3).map(Number);
    const luminance = (value) => {
      const channels = rgb(value).map((channel) => {
        const normalized = channel / 255;
        return normalized <= 0.04045
          ? normalized / 12.92
          : ((normalized + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
    };
    const foreground = luminance(getComputedStyle(panel.querySelector("p")).color);
    const background = luminance(getComputedStyle(panel).backgroundColor);
    return (Math.max(foreground, background) + 0.05) / (Math.min(foreground, background) + 0.05);
  });
}
