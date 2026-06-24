import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

import { createClient } from "@supabase/supabase-js";
import { chromium } from "playwright";

loadDotEnv();

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || process.env.SUPABASE_URL;
const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || process.env.SUPABASE_ANON_KEY;

test("browser owner annual loop uses persisted state and survives reload", async (t) => {
  if (!supabaseUrl || !serviceRoleKey || !anonKey) {
    t.skip("Supabase env missing");
    return;
  }

  const port = 3217;
  const baseUrl = `http://127.0.0.1:${port}`;
  const admin = createClient(supabaseUrl, serviceRoleKey, { auth: { persistSession: false } });
  const ownerEmail = `owner-${randomUUID()}@example.test`;
  const password = `Pw-${randomUUID()}-talli`;
  const orgNumber = String(Math.floor(100000000 + Math.random() * 899999999));
  const companyId = randomUUID();
  const setupId = randomUUID();
  const shareholderId = randomUUID();
  const previewId = randomUUID();

  const { data: createdUser, error: createUserError } = await admin.auth.admin.createUser({
    email: ownerEmail,
    password,
    email_confirm: true,
  });
  assert.ifError(createUserError);
  const ownerId = createdUser.user.id;

  await seedAnnualLoop(admin, { companyId, setupId, shareholderId, previewId, ownerId, orgNumber });

  const server = spawn("npm", ["run", "dev", "--", "--hostname", "127.0.0.1", "--port", String(port)], {
    cwd: process.cwd(),
    env: process.env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  t.after(() => server.kill("SIGTERM"));
  t.after(async () => {
    await admin.from("companies").delete().eq("id", companyId);
    await admin.auth.admin.deleteUser(ownerId);
  });

  await waitForServer(baseUrl);
  const browser = await chromium.launch({ headless: true });
  t.after(async () => browser.close());
  const page = await browser.newPage();

  await page.goto(baseUrl);
  const loginForm = page.locator("form").filter({ hasText: "Logg inn" }).first();
  await loginForm.getByLabel("E-post").fill(ownerEmail);
  await loginForm.getByLabel("Passord").fill(password);
  await loginForm.getByRole("button", { name: "Logg inn" }).click();
  await page.waitForLoadState("networkidle");
  await expectText(page, "Talli Browser Holding AS");
  await expectText(page, "Ikke vurdert");

  // The owner workflow tools now live under the /workspace route group (#90).
  await page.goto(`${baseUrl}/workspace`);
  await page.waitForLoadState("networkidle");

  await page.getByRole("button", { name: "Marker filingpakke betalt" }).click();
  await page.waitForLoadState("networkidle");
  await expectText(page, "Filing readiness må være klar før filingpakke kan betales.");

  await page.getByRole("button", { name: "Oppdater readiness" }).click();
  await page.waitForLoadState("networkidle");
  await page.reload();
  await page.waitForLoadState("networkidle");
  await expectText(page, "ready");

  await page.getByRole("button", { name: "Marker filingpakke betalt" }).click();
  await page.waitForLoadState("networkidle");
  await page.getByLabel("Jeg bekrefter rett til å sende inn for selskapet.").check();
  await page.getByLabel("Jeg har kontrollert endelig forhåndsvisning.").check();
  await page.getByRole("button", { name: "Arkiver simulert kvittering" }).click();
  await page.waitForLoadState("networkidle");

  await expectText(page, "sim-rf1086-");
  await expectText(page, "Eksporter arkiv");
});

async function seedAnnualLoop(admin, ids) {
  const { companyId, setupId, shareholderId, previewId, ownerId, orgNumber } = ids;
  await assertNoError(
    admin.from("companies").insert({
      id: companyId,
      org_number: orgNumber,
      name: "Talli Browser Holding AS",
      entity_type: "AS",
      address: "Storgata 1",
      postal_code: "0155",
      city: "OSLO",
      status_text: "aktiv",
      source: "browser_test",
      created_by: ownerId,
      identity_confirmed_at: new Date().toISOString(),
      identity_locked_at: new Date().toISOString(),
    }),
  );
  await assertNoError(
    admin.from("company_memberships").insert({
      company_id: companyId,
      user_id: ownerId,
      role: "owner",
      invited_by: ownerId,
      accepted_at: new Date().toISOString(),
    }),
  );
  await assertNoError(
    admin.from("opening_balance_setups").insert({
      id: setupId,
      company_id: companyId,
      income_year: 2025,
      bank_balance: 30000,
      share_capital: 30000,
      share_count: 100,
      nominal_value: 300,
      created_by: ownerId,
    }),
  );
  await assertNoError(
    admin.from("opening_shareholders").insert({
      id: shareholderId,
      setup_id: setupId,
      company_id: companyId,
      name: "Ola Nordmann",
      shareholder_kind: "norwegian_person",
      national_id: "01017012345",
      share_count: 100,
      created_by: ownerId,
    }),
  );
  await assertNoError(
    admin.from("ledger_entries").insert({
      company_id: companyId,
      setup_id: setupId,
      income_year: 2025,
      entry_type: "opening_balance",
      memo: "Åpningsbalanse",
      lines: [
        { account: "1920", debit: 30000, credit: 0 },
        { account: "2000", debit: 0, credit: 30000 },
      ],
      created_by: ownerId,
    }),
  );
  await assertNoError(
    admin.from("annual_data").insert({
      company_id: companyId,
      income_year: 2025,
      answers: {
        shares_owned_at_year_end: false,
        bought_or_sold_shares: false,
        received_dividends: false,
        declared_owner_dividends: false,
        shareholder_loans: false,
        paid_costs: false,
        bank_balance_confirmed: true,
        has_unpaid_items: false,
        general_meeting_approved: true,
        authority_to_submit_confirmed: true,
      },
      confirmations: ["bank_balance_confirmed", "general_meeting_approved", "authority_to_submit_confirmed", "no_activity_confirmed"],
      no_activity_confirmed: true,
      completed_by: ownerId,
      updated_by: ownerId,
    }),
  );
  await assertNoError(
    admin.from("billing_accounts").insert({
      company_id: companyId,
      pricing_plan: "founder",
      monthly_nok: 29,
      filing_package_nok: 299,
      founder_cohort_number: 1,
      subscription_active: true,
      filing_package_paid: false,
      supported_case: true,
      refund_eligible: false,
      no_charge_reason: null,
      updated_by: ownerId,
    }),
  );
  await assertNoError(
    admin.from("authority_permissions").insert([
      { company_id: companyId, obligation: "aksjonaerregisteroppgaven", submitter_user_id: ownerId, confirmed_by: ownerId, production_enabled: true },
      { company_id: companyId, obligation: "skattemelding", submitter_user_id: ownerId, confirmed_by: ownerId, production_enabled: true },
      { company_id: companyId, obligation: "aarsregnskap", submitter_user_id: ownerId, confirmed_by: ownerId, production_enabled: true },
    ]),
  );
  await assertNoError(
    admin.from("filing_previews").insert({
      id: previewId,
      company_id: companyId,
      setup_id: setupId,
      income_year: 2025,
      filing: "aksjonærregisteroppgaven",
      status: "ready",
      issues: [],
      preview: "RF-1086 forhåndsvisning for Talli Browser Holding AS",
      hovedskjema_xml: "<RF-1086><org>test</org></RF-1086>",
      underskjema_xml: { [shareholderId]: "<RF-1086U><shareholder>test</shareholder></RF-1086U>" },
      source: "browser_test",
      created_by: ownerId,
    }),
  );
}

async function waitForServer(baseUrl) {
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(baseUrl);
      if (response.ok) return;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
  }
  throw new Error(`Server did not start at ${baseUrl}`);
}

async function expectText(page, text) {
  await page.getByText(text, { exact: false }).first().waitFor({ timeout: 15000 });
}

async function assertNoError(query) {
  const { error } = await query;
  assert.ifError(error);
}

function loadDotEnv() {
  if (!existsSync(".env")) return;
  for (const line of readFileSync(".env", "utf8").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) continue;
    const [key, ...valueParts] = trimmed.split("=");
    if (!process.env[key]) {
      process.env[key] = valueParts.join("=").replace(/^["']|["']$/g, "");
    }
  }
}
