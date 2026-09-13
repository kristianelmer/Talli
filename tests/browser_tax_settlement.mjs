import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { mkdir } from "node:fs/promises";
import test from "node:test";
import { chromium } from "playwright";
import { startTaxBrowserFixture } from "./support/tax-browser-fixture.mjs";
import { fixtureTableTransaction } from "./support/rf1086-fixture-access.mjs";
import { installBrowserEgressGuard } from "./fixtures/system-user-authority-mock.mjs";

// Mandatory full-stack lane. Only identity/admission prerequisites are seeded;
// the normal owner form, verified JWT, restricted SQL and Audit create effects.
test("owner captures every settlement kind through wizard and workspace and retries without duplicate effects", { timeout: 240_000 }, async (t) => {
  const fixture = await startTaxBrowserFixture();
  let browser;
  t.after(async () => { try { await browser?.close(); } finally { await fixture.close(); } });
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const blockedRequests = [];
  await installBrowserEgressGuard(context, { approvalEnabled: false, blockedRequests, mockBaseUrl: fixture.siteOrigin });
  const page = await context.newPage();
  page.setDefaultTimeout(20_000);
  await page.goto(fixture.siteOrigin + "/login");
  await page.getByRole("textbox", { name: "E-post", exact: true }).fill(fixture.owner.email);
  await page.locator('input[name="password"]').fill(fixture.owner.password);
  await page.getByRole("button", { name: "Logg inn", exact: true }).click();
  await page.waitForURL(url => url.pathname !== "/login");
  await establishOwnerAal2(page, fixture.siteOrigin);
  await page.goto(fixture.siteOrigin + "/actions/tax-settlement");
  const amount = page.getByRole("textbox", { name: "Beløp (kr)" });
  const date = page.getByRole("textbox", { name: /Oppgjørsdato/ });
  const confirm = page.getByRole("button", { name: "Bekreft og bokfør", exact: true });
  const kind = page.getByRole("combobox", { name: "Type", exact: true });
  await confirm.waitFor();
  assert.equal(await confirm.isDisabled(), true);
  const operationId = await page.locator('input[name="operationId"]').inputValue();
  const year = await page.locator('input[name="incomeYear"]').inputValue();
  const fill = async value => { await date.fill(`${year}-09-01`); await amount.fill(value); };
  for (const value of ["-1", "abc", "Infinity", "1,5"]) {
    await fill(value);
    await page.getByText("Skattebeløp må være større enn 0.", { exact: true }).waitFor();
    assert.equal(await confirm.isDisabled(), true);
  }
  await amount.fill("17.605");
  await page.getByRole("cell", { name: "8300 Skattekostnad", exact: true }).waitFor();
  assert.match(await page.locator("table tbody").innerText(), /17,61/u);
  assert.equal(await confirm.isEnabled(), true);
  for (const [value, first, second] of [["payment", "2500 Betalbar skatt", "1920 Bankinnskudd"], ["refund", "1920 Bankinnskudd", "1570 Skatt til gode"]]) {
    await kind.selectOption(value);
    await page.getByRole("cell", { name: first, exact: true }).waitFor();
    const cells = await page.locator("table tbody tr td:first-child").allTextContents();
    assert.equal(cells[0], first);
    assert.ok(cells[1].startsWith(second.split(" ")[0]));
  }
  await kind.selectOption("payable");
  fixture.controls.delayPreviewAmount = 101;
  await amount.fill("101");
  await poll(() => fixture.controls.previews.some(input => input.amount === 101));
  await amount.fill("202");
  assert.equal(await confirm.isDisabled(), true);
  await page.waitForFunction(() => document.querySelector("table tbody")?.textContent?.includes("202,00"));
  assert.doesNotMatch(await page.locator("table tbody").innerText(), /101,00/u);
  if (process.env.TALLI_TAX_BROWSER_ARTIFACTS === "1") {
    await mkdir("output/playwright", { recursive: true });
    await page.screenshot({ path: "output/playwright/tax-settlement-preview.png", fullPage: true });
  }
  fixture.controls.dropNextCapture = true;
  await confirm.click();
  await page.waitForURL(url => url.searchParams.get("taxSettlementOperationId") === operationId);
  assert.equal(await page.locator('input[name="operationId"]').inputValue(), operationId);
  assert.equal(fixture.controls.captures.length, 1);
  assert.equal(fixture.controls.captures[0].status, 201);
  assert.equal(fixture.controls.captures[0].response.replayed, false);
  await fill("202");
  await page.getByRole("cell", { name: "8300 Skattekostnad", exact: true }).waitFor();
  // The first replay attempt fails at its new server preview hop. It must
  // retain the already committed action's identity through another redirect.
  fixture.controls.failNextPreview = true;
  await confirm.click();
  await page.waitForURL(url => url.searchParams.get("taxSettlementOperationId") === operationId
    && url.searchParams.get("error") === "Forhåndsvisningen kunne ikke hentes. Prøv igjen.");
  assert.equal(await page.locator('input[name="operationId"]').inputValue(), operationId);
  assert.equal(fixture.controls.captures.length, 1);
  await fill("202");
  await page.getByRole("cell", { name: "8300 Skattekostnad", exact: true }).waitFor();
  await confirm.click();
  await page.waitForURL(url => url.pathname === "/actions" && !url.searchParams.has("error"));
  assert.equal(fixture.controls.captures.length, 2);
  assert.deepEqual(fixture.controls.captures.map(call => [call.body.actionId, call.status, call.response.replayed]), [[operationId,201,false],[operationId,201,true]]);
  await fixtureTableTransaction(fixture.db, ["company_tax_filing.settlements", "ledger.entries", "backend_system.ledger_workflow_receipts", "public.audit_events"], async () => {
    const { rows } = await fixture.db.query(`select
      (select count(*)::int from company_tax_filing.settlements where company_id=$1) settlements,
      (select count(*)::int from ledger.entries where company_id=$1) entries,
      (select count(*)::int from backend_system.ledger_workflow_receipts where company_id=$1) receipts,
      (select count(*)::int from public.audit_events where company_id=$1 and action='tax_settlement_recorded') audits`, [fixture.companyId]);
    assert.deepEqual(rows, [{ settlements:1, entries:1, receipts:1, audits:1 }]);
  });
  // Complete the other supported captures through both shipped owner forms.
  await page.goto(fixture.siteOrigin + "/actions/tax-settlement");
  await kind.selectOption("payment");
  await fill("12.34");
  await page.getByRole("cell", { name: "1920 Bankinnskudd", exact: true }).waitFor();
  await confirm.click();
  await page.waitForURL(url => url.pathname === "/actions" && !url.searchParams.has("error"));
  await page.goto(fixture.siteOrigin + "/workspace");
  const workspaceForm = page.locator("form").filter({ has: page.getByRole("button", { name: "Poster skatteoppgjør", exact: true }) });
  await workspaceForm.locator('input[name="incomeYear"]').fill(year);
  await workspaceForm.locator('input[name="settlementDate"]').fill(`${year}-09-02`);
  await workspaceForm.locator('select[name="settlementType"]').selectOption("refund");
  await workspaceForm.locator('input[name="amount"]').fill("33.10");
  const workspaceOperation = await workspaceForm.locator('input[name="operationId"]').inputValue();
  await workspaceForm.getByRole("button", { name: "Poster skatteoppgjør", exact: true }).click();
  await page.waitForFunction(previous => {
    const form = [...document.forms].find(item => item.querySelector('select[name="settlementType"]'));
    const value = form?.querySelector('input[name="operationId"]')?.value;
    return Boolean(value && value !== previous);
  }, workspaceOperation);
  assert.equal(new URL(page.url()).pathname, "/workspace");
  assert.equal(new URL(page.url()).searchParams.has("error"), false);
  assert.deepEqual(fixture.controls.captures.map(call => [call.body.settlementKind, call.status, call.response.replayed]),
    [["payable",201,false],["payable",201,true],["payment",201,false],["refund",201,false]]);
  assert.deepEqual(blockedRequests, []);
});

async function poll(condition) {
  const deadline = Date.now() + 20_000;
  while (!condition()) { assert.ok(Date.now() < deadline, "fixture condition timed out"); await new Promise(resolve => setTimeout(resolve, 25)); }
}

async function establishOwnerAal2(page, origin) {
  await page.goto(`${origin}/mfa?next=%2Fconnections`);
  await page.getByRole("heading", { name: "Beskytt kontoen før du fortsetter" }).waitFor();
  await page.getByRole("button", { name: "Sett opp autentiseringsapp", exact: true }).click();
  const secret = (await page.locator("code").innerText()).trim();
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const bits = [...secret.toUpperCase().replace(/=+$/u, "")].map((character) => {
    const index = alphabet.indexOf(character);
    assert.notEqual(index, -1);
    return index.toString(2).padStart(5, "0");
  }).join("");
  const key = Buffer.from((bits.match(/.{8}/gu) ?? []).map((byte) => Number.parseInt(byte, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
  const digest = createHmac("sha1", key).update(counter).digest();
  const code = String((digest.readUInt32BE(digest.at(-1) & 0x0f) & 0x7fffffff) % 1000000).padStart(6, "0");
  await page.getByLabel("Sekssifret kode").fill(code);
  await page.getByRole("button", { name: "Bekreft og fortsett", exact: true }).click();
  await page.waitForURL((url) => url.pathname !== "/mfa");
}
