/** Actual local Auth/Storage/SQL proof; no historical Corporate closure is seeded. */
import assert from "node:assert/strict";
import { createHmac, createHash, randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { createClient } from "@supabase/supabase-js";
import { startTaxBrowserFixture } from "./support/tax-browser-fixture.mjs";
import { completeAccountsCorporateAnnualClose } from "./support/accounts-browser-governance.mjs";

const reader = "public.company_access_read_corporate_owner_v1(uuid,text)";
const assertion = "corporate_governance.assert_annual_close_owner_v2(uuid,integer,text,boolean)";
const readerFile = "20261027080000_company_access_corporate_owner_read.sql";
const policyFile = "20261027080100_corporate_annual_close_2025.sql";
const sqlFile = (folder, name) => readFile(new URL(`../supabase/${folder}/${name}`, import.meta.url), "utf8");

async function signedOwner(fixture) {
  const auth = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_ANON_KEY,
    { auth: { autoRefreshToken: false, persistSession: false } });
  const initial = await auth.auth.signInWithPassword({ email: fixture.owner.email, password: fixture.owner.password });
  assert.ifError(initial.error);
  const factor = await auth.auth.mfa.enroll({ factorType: "totp", friendlyName: "Corporate annual-close native test" });
  assert.ifError(factor.error);
  const challenge = await auth.auth.mfa.challenge({ factorId: factor.data.id });
  assert.ifError(challenge.error);
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const bits = [...factor.data.totp.secret.toUpperCase().replace(/=+$/u, "")].map(character => {
    const index = alphabet.indexOf(character); assert.notEqual(index, -1);
    return index.toString(2).padStart(5, "0");
  }).join("");
  const key = Buffer.from((bits.match(/.{8}/gu) ?? []).map(byte => Number.parseInt(byte, 2)));
  const counter = Buffer.alloc(8); counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30_000)));
  const digest = createHmac("sha1", key).update(counter).digest();
  const code = String((digest.readUInt32BE(digest.at(-1) & 15) & 0x7fffffff) % 1_000_000).padStart(6, "0");
  const elevated = await auth.auth.mfa.verify({ factorId: factor.data.id, challengeId: challenge.data.id, code });
  assert.ifError(elevated.error);
  const token = elevated.data.access_token;
  const claims = JSON.parse(Buffer.from(token.split(".")[1], "base64url"));
  assert.equal(claims.aal, "aal2"); assert.equal(claims.sub, fixture.owner.id);
  return { token, claims, aal1: initial.data.session.access_token };
}

test("supported2025 Corporate lifecycle uses actual owner evidence with narrow authority and retentive rollback", { timeout: 300_000 }, async t => {
  const fixture = await startTaxBrowserFixture({ incomeYear: 2025, accountsDelivery: true });
  t.after(() => fixture.close());
  const { token, claims, aal1 } = await signedOwner(fixture);
  const request = (path, options = {}, bearer = token) => {
    assert.match(path, /^\/api\/v1\/(?:corporate-governance|documents|annual-accounts)\//u);
    return fetch(fixture.backendOrigin + path, { ...options, headers: { ...options.headers, authorization: `Bearer ${bearer}` } });
  };
  const events = async () => (await fixture.db.query("select count(*)::int count from corporate_governance.annual_close_events where company_id=$1", [fixture.companyId])).rows[0].count;
  let approvalDenialsChecked = false;
  const effects = [];
  fixture.governanceRequest = async (path, options = {}) => {
    if (path.endsWith("/approvals") && !approvalDenialsChecked) {
      const before = await events();
      assert.equal((await request(path, options, aal1)).status, 403, "actual AAL1 owner cannot approve");
      const foreign = { ...JSON.parse(options.body), companyId: randomUUID() };
      assert.equal((await request(path, { ...options, body: JSON.stringify(foreign) })).status, 403);
      assert.equal(await events(), before, "denied approvals append no event");
      approvalDenialsChecked = true;
    }
    const response = await request(path, options);
    if (options.method === "POST") effects.push({ path, status: response.status });
    return response;
  };

  const completed = await completeAccountsCorporateAnnualClose(fixture);
  assert.equal(approvalDenialsChecked, true);
  assert.equal(completed.readiness.finalized, true);
  assert.equal(completed.readiness.currentSourceMatches, true);
  assert.equal(effects.filter(item => item.path.endsWith("/approvals") && item.status === 201).length, 1);
  assert.equal(effects.filter(item => item.path.endsWith("/signed-artifacts") && item.status === 201).length, 2);
  assert.equal(effects.filter(item => item.path.endsWith("/finalizations") && item.status === 201).length, 1);

  await t.test("finalized Corporate source supports an actual Accounts draft and owner review", async () => {
    const filingId = randomUUID();
    const post = (path, body) => request(path, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": randomUUID() }, body: JSON.stringify(body) });
    const scope = { companyId: fixture.companyId, incomeYear: 2025, filingId };
    const draftResponse = await post("/api/v1/annual-accounts/delivery-drafts", { ...scope, contactEmail: "owner@example.test", confirmingRepresentative: "Synthetic Chair" });
    assert.equal(draftResponse.status, 200);
    const draft = await draftResponse.json();
    const reviewResponse = await post("/api/v1/annual-accounts/delivery-reviews", { ...scope, draftSha256: draft.draftSha256,
      stage: "prepare", reviewedEvidenceSha256: draft.draftSha256, documentsChecked: true, actionConfirmed: true });
    assert.equal(reviewResponse.status, 200, fixture.diagnostics());
  });

  async function authority({ year = 2025, subject = fixture.owner.id, context = claims, mutate, allowed = false, isolation = "read committed", legacy = false } = {}) {
    assert.ok(["read committed", "repeatable read"].includes(isolation));
    await fixture.db.query(`begin isolation level ${isolation}`);
    try {
      await fixture.db.query("select set_config('talli.verified_actor_id',$1,true),set_config('talli.verified_actor_claims',$2,true)", [context.sub, JSON.stringify(context)]);
      if (mutate) await mutate();
      await fixture.db.query("set local role corporate_governance_store_owner");
      const name = legacy ? "assert_owner_v1" : "assert_annual_close_owner_v2";
      const call = () => fixture.db.query(`select corporate_governance.${name}($1::uuid,$2::integer,$3,true) actor`, [fixture.companyId, year, subject]);
      if (allowed) assert.equal((await call()).rows[0].actor, fixture.owner.id);
      else await assert.rejects(call(), error => error.code === "P0001" &&
        ["corporate_governance_forbidden", "company_access_corporate_read_committed_required"].includes(error.message));
    } finally { await fixture.db.query("rollback"); }
  }

  await t.test("current authority is required without creating general2025 year admission", async () => {
    await authority({ allowed: true });
    await authority({ year: 2024 });
    await authority({ year: 2026 }); // This fixture has no admitted2026 company-year either.
    await authority({ subject: randomUUID() });
    await authority({ context: { ...claims, aal: "aal1" } });
    await authority({ context: { ...claims, amr: [{ method: "totp", timestamp: Math.floor(Date.now() / 1000) - 901 }] } });
    await authority({ isolation: "repeatable read" });
    await authority({ mutate: () => fixture.db.query("update public.company_memberships set role='read_only' where company_id=$1 and user_id=$2", [fixture.companyId, fixture.owner.id]) });
    await authority({ mutate: () => fixture.db.query("update public.companies set identity_locked_at=null where id=$1", [fixture.companyId]) });
    assert.equal((await fixture.db.query("select public.company_access_has_current_agreement_v1($1) accepted", [randomUUID()])).rows[0].accepted, false,
      "an unknown company has no current agreement; immutable acceptances are never mutated");
    await authority({ mutate: () => fixture.db.query("insert into public.company_cancellations(company_id,status,requested_by) values($1,'retention_hold',$2)", [fixture.companyId, fixture.owner.id]) });
    await fixture.db.query("begin");
    try {
      await fixture.db.query("select set_config('talli.verified_actor_id',$1,true),set_config('talli.verified_actor_claims',$2,true)", [fixture.owner.id, JSON.stringify(claims)]);
      await fixture.db.query("set local role corporate_governance_store_owner");
      assert.equal((await fixture.db.query("select public.company_access_company_year_allows_consequential_v1($1,2025) admitted", [fixture.companyId])).rows[0].admitted, false);
      await assert.rejects(fixture.db.query("select corporate_governance.assert_owner_v1($1,2025,$2,true)", [fixture.companyId, fixture.owner.id]), error => error.code === "P0001");
    } finally { await fixture.db.query("rollback"); }
  });

  await t.test("private helpers add no public or workflow-callable authority and no immutable UPDATE policy", async () => {
    for (const role of ["anon", "authenticated", "service_role", "corporate_governance_workflow_executor"]) {
      for (const signature of [reader, assertion]) assert.equal((await fixture.db.query("select has_function_privilege($1,$2,'EXECUTE') allowed", [role, signature])).rows[0].allowed, false);
    }
    const rows = (await fixture.db.query("select cmd from pg_policies where schemaname='corporate_governance' and tablename='annual_close_artifacts'")).rows;
    assert.equal(rows.some(row => ["UPDATE", "ALL"].includes(row.cmd)), false);
    assert.equal((await fixture.db.query("select relrowsecurity and relforcerowsecurity guarded from pg_class where oid='corporate_governance.annual_close_artifacts'::regclass")).rows[0].guarded, true);
  });

  async function inventory() {
    const records = [];
    for (const table of ["annual_close_decisions", "annual_close_artifacts", "annual_close_events", "annual_close_finalizations"]) {
      const rows = (await fixture.db.query(`select to_jsonb(r)::text original from corporate_governance.${table} r where company_id=$1 order by id`, [fixture.companyId])).rows;
      records.push([table, createHash("sha256").update(JSON.stringify(rows)).digest("hex")]);
    }
    return {
      records,
      memberships: (await fixture.db.query("select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3")).rows,
      generalGuards: (await fixture.db.query("select oid::regprocedure::text signature,prosrc,proacl::text,proconfig from pg_proc where oid=any($1::regprocedure[]) order by oid::regprocedure::text", [["public.company_access_company_year_allows_consequential_v1(uuid,integer)", "corporate_governance.assert_owner_v1(uuid,integer,text,boolean)"]])).rows,
      policies: (await fixture.db.query("select tablename,policyname,cmd,roles::text,qual,with_check from pg_policies where schemaname='corporate_governance' order by tablename,policyname")).rows,
    };
  }

  await t.test("two actual migration rollbacks and recutovers preserve evidence and unrelated authority", async () => {
    const before = await inventory();
    for (let cycle = 0; cycle < 2; cycle++) {
      await fixture.db.query(await sqlFile("rollback", policyFile));
      assert.equal((await fixture.db.query("select to_regprocedure($1) routine", [assertion])).rows[0].routine, null);
      await authority({ legacy: true });
      await fixture.db.query(await sqlFile("rollback", readerFile));
      await fixture.db.query(await sqlFile("migrations", readerFile));
      await fixture.db.query(await sqlFile("contract-migrations", policyFile));
      await fixture.db.query(await sqlFile("contract-migrations", policyFile));
      assert.deepEqual(await inventory(), before);
      await authority({ allowed: true });
    }
    const response = await request(`/api/v1/corporate-governance/readiness?${new URLSearchParams({ companyId: fixture.companyId, incomeYear: "2025", decisionKind: "annual_close" })}`);
    assert.equal(response.status, 200);
    assert.equal((await response.json()).finalizationId, completed.finalizationId);
  });
});
