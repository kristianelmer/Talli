import assert from "node:assert/strict";
import { fixtureTableTransaction } from "./rf1086-fixture-access.mjs";
import { randomUUID } from "node:crypto";
import { createTalliApiClient, TalliApiError } from "../../packages/talli-api-client/src/index.ts";
import { presentRf1086Preview, presentRf1086Simulation, presentRf1086Override,
  presentRf1086ReviewComment, presentRf1086Permission, presentRf1086TestEvidence } from "../../apps/web/features/shareholder-register-filing/presentation.ts";
import { allocateLoopbackPort, startOwnedProcess, stopOwnedProcess, waitForOwnedReadiness } from "./owned-process-lifecycle.mjs";
import { isLoopbackSupabaseUrl } from "./supabase_fixture_safety.mjs";

export async function apiRequest(client, extras = {}) {
  const { data, error } = await client.auth.getSession();
  assert.ifError(error);
  assert.ok(data.session?.access_token);
  return { ...extras, headers: { Authorization: `Bearer ${data.session.access_token}` } };
}

export const deniedRf = (error) => error instanceof TalliApiError && [403, 404].includes(error.status);

export async function startWorkspaceRfApi(database, databaseConfig) {
  assert.ok(["127.0.0.1", "localhost", "::1"].includes(databaseConfig.host));
  assert.ok(isLoopbackSupabaseUrl(process.env.SUPABASE_URL));
  const borrowed = [];
  let server;
  const close = async () => {
    const errors = [];
    try { await stopOwnedProcess(server); } catch (error) { errors.push(error); }
    for (const role of borrowed) {
      try { await database.query(`alter role ${role} nologin password null`); } catch (error) { errors.push(error); }
    }
    if (errors.length) throw new AggregateError(errors, "workspace RF API teardown failed");
  };
  try {
    const connection = new URL("postgresql://127.0.0.1");
    connection.hostname = databaseConfig.host;
    connection.port = String(databaseConfig.port);
    connection.pathname = "/" + databaseConfig.database;
    connection.username = databaseConfig.user;
    connection.password = databaseConfig.password;
    const rootDatabase = connection.href;
    const roleUrls = {};
    for (const role of ["talli_company_access_backend", "talli_ledger_backend"]) {
      const previous = (await database.query("select rolcanlogin,rolinherit,rolbypassrls from pg_roles where rolname=$1", [role])).rows;
      assert.deepEqual(previous, [{ rolcanlogin: false, rolinherit: false, rolbypassrls: false }]);
      const password = randomUUID().replaceAll("-", "");
      await database.query(`alter role ${role} login password '${password}'`);
      borrowed.push(role);
      connection.username = role;
      connection.password = password;
      roleUrls[role] = connection.href;
    }
    const port = await allocateLoopbackPort();
    const nonce = randomUUID();
    const env = { NEXT_TELEMETRY_DISABLED: "1", TALLI_RF1086_PRODUCTION_ENABLED: "false", TALLI_AUTHORITY_OPS_ENABLED: "false",
      SUPABASE_URL: process.env.SUPABASE_URL, SUPABASE_ANON_KEY: process.env.SUPABASE_ANON_KEY,
      SUPABASE_SERVICE_ROLE_KEY: process.env.SUPABASE_SERVICE_ROLE_KEY,
      DATABASE_URL: rootDatabase, TALLI_LEDGER_DATABASE_URL: roleUrls.talli_ledger_backend,
      TALLI_COMPANY_ACCESS_DATABASE_URL: roleUrls.talli_company_access_backend,
      TALLI_BACKEND_PORT: String(port), TALLI_READINESS_NONCE: nonce };
    for (const key of ["PATH", "HOME", "TMPDIR", "LANG", "LC_ALL"]) if (process.env[key]) env[key] = process.env[key];
    server = startOwnedProcess({ command: process.env.TALLI_BACKEND_PYTHON_BIN || "apps/backend/.venv/bin/python",
      args: ["tests/fixtures/start_rf1086_workspace_backend.py"], cwd: process.cwd(), env,
      readinessProof: `TALLI_BACKEND_BOUND:${nonce}` });
    const baseUrl = `http://127.0.0.1:${port}`;
    await waitForOwnedReadiness({ process: server, url: baseUrl + "/health/ready" });
    const client = createTalliApiClient({ baseUrl });
    return {
      client, close,
      async call(actor, method, body, extra = {}) { return client[method](body, await apiRequest(actor, extra)); },
      async preview(actor, id) { return presentRf1086Preview(await client.rf1086Preview(id, await apiRequest(actor))); },
      async workspace(actor, companyId) {
        const value = await client.rf1086Workspace(companyId, undefined, await apiRequest(actor));
        assert.equal(value.companyId, companyId);
        return { previews: value.previews.map(presentRf1086Preview), submissions: value.simulations.map(presentRf1086Simulation),
          overrides: value.overrides.map(presentRf1086Override), comments: value.reviewComments.map(presentRf1086ReviewComment),
          permissions: value.permissions.map(presentRf1086Permission), evidence: value.testEvidence.map(presentRf1086TestEvidence) };
      },
      async openings(actor, companyId) {
        const page = await client.ledgerListOpeningSnapshots(await apiRequest(actor, { companyIds: [companyId] }));
        assert.equal(page.hasMore, false);
        return page.items.map(row => ({ id: row.setupId, company_id: row.companyId, income_year: row.incomeYear,
          bank_balance: Number(row.bankBalance.amount), share_capital: Number(row.shareCapital.amount),
          share_count: row.shareCount, nominal_value: Number(row.nominalValue.amount), locked_at: row.lockedAt,
          created_at: row.createdAt, created_by: row.createdBy, shareholders: row.shareholders.map(holder => ({
            id: holder.shareholderId, setup_id: holder.setupId, company_id: holder.companyId, name: holder.name,
            shareholder_kind: holder.shareholderKind, national_id: holder.nationalId, org_number: holder.orgNumber, share_count: holder.shareCount,
          })) }));
      },
    };
  } catch (error) {
    try { await close(); } catch (cleanup) { throw new AggregateError([error, cleanup], "workspace RF API setup failed"); }
    throw error;
  }
}

// Historical source fixture only: no preview, approval, simulation or provider
// result is seeded. Application assertions below use the real canonical API.
export async function seedHistoricalRfOpening(database, companyId, actorId, input) {
  const setupId = randomUUID();
  await rfFixtureTransaction(database, async () => {
    await database.query(`insert into shareholder_register_filing.opening_balance_setups
      (id,company_id,income_year,share_capital,share_count,nominal_value,created_by)
      values($1,$2,2025,$3,$4,$5,$6)`, [setupId, companyId, input.shareCapital, input.shareCount, input.nominalValue, actorId]);
    await database.query(`insert into ledger.opening_bank_inputs(snapshot_id,company_id,income_year,bank_balance_nok,recorded_by,recorded_at)
      values($1,$2,2025,$3,$4,now())`, [setupId, companyId, input.bankBalance, actorId]);
    const projectionPresent = (await database.query("select to_regclass('public.opening_balance_setups') is not null present")).rows[0].present;
    if (projectionPresent) await database.query(`insert into public.opening_balance_setups
      (id,company_id,income_year,bank_balance,share_capital,share_count,nominal_value,created_by)
      values($1,$2,2025,$3,$4,$5,$6,$7)`, [setupId,companyId,input.bankBalance,input.shareCapital,input.shareCount,input.nominalValue,actorId]);
    for (const holder of input.shareholders) {
      const holderId = randomUUID();
      await database.query(`insert into shareholder_register_filing.opening_shareholders
      (id,setup_id,company_id,name,shareholder_kind,national_id,org_number,share_count,created_by)
      values($1,$2,$3,$4,$5,$6,$7,$8,$9)`, [holderId,setupId,companyId,holder.name,holder.shareholderKind,
        holder.nationalId ?? null,holder.orgNumber ?? null,holder.shareCount,actorId]);
      if (projectionPresent) await database.query(`insert into public.opening_shareholders
        (id,setup_id,company_id,name,shareholder_kind,national_id,org_number,share_count,created_by)
        values($1,$2,$3,$4,$5,$6,$7,$8,$9)`, [holderId,setupId,companyId,holder.name,holder.shareholderKind,
          holder.nationalId ?? null,holder.orgNumber ?? null,holder.shareCount,actorId]);
    }
    if (projectionPresent) {
      assert.equal((await database.query(`select to_jsonb(p)=to_jsonb(r)||jsonb_build_object('bank_balance',b.bank_balance_nok) exact
        from public.opening_balance_setups p join shareholder_register_filing.opening_balance_setups r using(id)
        join ledger.opening_bank_inputs b on b.snapshot_id=r.id where p.id=$1`, [setupId])).rows[0].exact, true);
      assert.equal((await database.query(`select count(*)::int count from public.opening_shareholders p
        full join shareholder_register_filing.opening_shareholders r using(id) where coalesce(p.setup_id,r.setup_id)=$1
        and to_jsonb(p) is distinct from to_jsonb(r)`, [setupId])).rows[0].count, 0);
    }
  }, { openingProjection: true });
  return setupId;
}

export const RF_FIXTURE_TABLES = ["production_feedback_artifacts", "production_filing_submissions", "filing_approval_snapshots",
  "filing_review_comments", "filing_overrides", "filing_submissions", "authority_test_runs", "authority_permissions", "filing_previews",
  "opening_shareholders", "opening_balance_setups", "migration_inventory", "migration_quarantine"];
export async function rfFixtureTransaction(database, operation, { feedbackSupport = false, openingProjection = false } = {}) {
  const projections = openingProjection && (await database.query("select to_regclass('public.opening_balance_setups') is not null present")).rows[0].present
    ? ["public.opening_balance_setups", "public.opening_shareholders"] : [];
  return fixtureTableTransaction(database, [...RF_FIXTURE_TABLES.map(name => `shareholder_register_filing.${name}`),
    "shareholder_register_filing.production_filing_events", "ledger.opening_bank_inputs", ...projections,
    ...["filing_review_comments", "filing_overrides", "filing_submissions", "filing_previews", "authority_permissions", "authority_test_runs"].map(name => `public.${name}`),
    ...(feedbackSupport ? ["billing.production_pilot_entitlements", "public.documents", "documents.evidence_references"] : [])], operation);
}
