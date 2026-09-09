import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { EventEmitter, once } from "node:events";
import test from "node:test";

import { createClient } from "@supabase/supabase-js";
import pg from "pg";

import {
  cleanupBrowserOwnerResources,
  cleanupFailure,
} from "./support/browser-owner-cleanup.mjs";
import {
  allocateLoopbackPort,
  startOwnedProcess,
  stopOwnedProcess,
  waitForOwnedReadiness,
} from "./support/owned-process-lifecycle.mjs";
import {
  isLoopbackPostgresUrl,
  isLoopbackSupabaseUrl,
} from "./support/supabase_fixture_safety.mjs";

import { fixtureTableTransaction } from "./support/rf1086-fixture-access.mjs";

const root = new URL("..", import.meta.url);

test("readiness rejects when its owned process exits before an unrelated listener responds", async () => {
  const child = startOwnedProcess({
    command: process.execPath,
    args: ["-e", "process.exit(1)"],
    cwd: root,
    readinessProof: "CHILD_BOUND",
  });
  await once(child, "exit");

  await assert.rejects(
    waitForOwnedReadiness({
      process: child,
      url: "http://127.0.0.1:1/ready",
      fetchImpl: async () => new Response(null, { status: 200 }),
      timeoutMs: 500,
      pollMs: 10,
    }),
    /owned_process_exited_before_readiness/u,
  );
  await stopOwnedProcess(child);
});

test("an unrelated ready listener cannot satisfy a live child without its bind proof", async () => {
  const child = startSleepingProcess();

  await assert.rejects(
    waitForOwnedReadiness({
      process: child,
      url: "http://127.0.0.1:1/ready",
      fetchImpl: async () => new Response(null, { status: 200 }),
      timeoutMs: 40,
      pollMs: 10,
    }),
    /owned_process_readiness_deadline_exceeded/u,
  );
  await stopOwnedProcess(child);
});

test("readiness failure tears down a live owned process", async () => {
  const child = startSleepingProcess();

  await assert.rejects(
    waitForOwnedReadiness({
      process: child,
      url: "http://127.0.0.1:1/ready",
      fetchImpl: async () => new Response(null, { status: 503 }),
      timeoutMs: 40,
      pollMs: 10,
    }),
    /owned_process_readiness_deadline_exceeded/u,
  );
  await stopOwnedProcess(child);
  assert.equal(hasExited(child), true);
});

test("a listener that never responds cannot outlive the readiness deadline", async () => {
  const port = await allocateLoopbackPort();
  const readinessProof = "HANGING_SERVER_BOUND";
  const child = startOwnedProcess({
    command: process.execPath,
    args: ["-e", hangingServerProgram(readinessProof)],
    cwd: root,
    env: { ...globalThis.process.env, TEST_PORT: String(port) },
    readinessProof,
  });
  const readiness = waitForOwnedReadiness({
    process: child,
    url: `http://127.0.0.1:${port}/health/ready`,
    timeoutMs: 100,
    pollMs: 10,
  });
  const outcome = await Promise.race([
    readiness.then(
      () => ({ result: "ready" }),
      (error) => ({ error, result: "rejected" }),
    ),
    delay(500).then(() => ({ result: "hung" })),
  ]);

  await stopOwnedProcess(child);
  await readiness.catch(() => {});
  assert.equal(outcome.result, "rejected");
  assert.match(outcome.error.message, /owned_process_readiness_deadline_exceeded/u);
  assert.equal(hasExited(child), true);
});

test("a ready owned process is terminated and cleanup is idempotent", async () => {
  const port = await allocateLoopbackPort();
  const readinessProof = "OWNED_SERVER_BOUND";
  const child = startOwnedProcess({
    command: process.execPath,
    args: ["-e", serverProgram(readinessProof)],
    cwd: root,
    env: { ...globalThis.process.env, TEST_PORT: String(port) },
    readinessProof,
  });

  await waitForOwnedReadiness({
    process: child,
    url: `http://127.0.0.1:${port}/health/ready`,
    timeoutMs: 2_000,
    pollMs: 10,
  });
  await stopOwnedProcess(child);
  const exitStatus = [child.exitCode, child.signalCode];
  await stopOwnedProcess(child);
  assert.deepEqual([child.exitCode, child.signalCode], exitStatus);
});

test("forced process cleanup has a final timeout and tolerates an undefined handle", async () => {
  await stopOwnedProcess(undefined);
  const child = new EventEmitter();
  child.exitCode = null;
  child.signalCode = null;
  child.signals = [];
  child.kill = (signal) => {
    child.signals.push(signal);
    return true;
  };

  await assert.rejects(
    stopOwnedProcess(child, { terminateTimeoutMs: 5, killTimeoutMs: 5 }),
    /owned_process_kill_deadline_exceeded/u,
  );
  assert.deepEqual(child.signals, ["SIGTERM", "SIGKILL"]);
});

test("partial setup cleanup closes the database and removes only known resources", async () => {
  const calls = [];
  const database = {
    async query() {
      calls.push("database_query");
    },
    async end() {
      calls.push("database_end");
    },
  };
  const admin = {
    auth: {
      admin: {
        async deleteUser(id) {
          calls.push(`delete_user:${id}`);
          return { error: null };
        },
      },
    },
    from() {
      throw new Error("unknown company must not be deleted");
    },
  };

  const errors = await cleanupBrowserOwnerResources({
    admin,
    database,
    databaseStarted: true,
    ownerId: "owner-created",
  });

  assert.deepEqual(errors, []);
  assert.deepEqual(calls, ["delete_user:owner-created", "database_end"]);
  const primary = new Error("setup failed");
  assert.equal(cleanupFailure(primary, [new Error("cleanup failed")]), null);
  assert.ok(
    cleanupFailure(undefined, [new Error("cleanup failed")]) instanceof
      AggregateError,
  );
});

for (const phase of ["predecessor", "overlap", "contracted"]) {
  test(`browser owner cleanup preserves every prior family in ${phase} before company and user`, async () => {
    const calls = [];
    const database = cleanupDatabaseProbe(calls, { phase });
    const companyId = "11111111-1111-4111-8111-111111111111";
    const errors = await cleanupBrowserOwnerResources({
      admin: cleanupAdmin(calls), companyId, database, databaseStarted: true, ownerId: "owner-created",
    });
    assert.deepEqual(errors, []);
    const rf = phase === "predecessor" ? "public" : "shareholder_register_filing";
    const authority = phase === "predecessor" ? "public" : "authority_connections";
    // Original explicit deletion-family coverage, with only moved resources
    // mapped to their physical owner. Additional canonical mirrors are separate.
    const required = [
      ...["company_year_acceptances", "company_year_admissions", "company_eligibility_assessments",
        "customer_agreement_acceptances", "corporate_document_events", "corporate_decision_finalizations",
        "corporate_document_artifacts", "corporate_document_sets", "corporate_decisions", "company_deletion_reviews",
        "bank_suggestion_acceptances", "bank_transactions", "investment_lot_allocations", "investment_lots",
        "investment_positions", "filing_review_comments", "filing_submissions", "holding_actions", "documents",
        "authority_test_runs", "authority_permissions", "filing_previews", "audit_events", "company_archive_export_receipts",
        "company_archive_export_attempts", "company_archive_source_generations", "companies"].map(name => `public.${name}`),
      ...["production_filing_events", "production_feedback_artifacts", "production_filing_submissions",
        "filing_approval_snapshots"].map(name => `${rf}.${name}`),
      `${authority}.system_user_requests`, "billing.production_pilot_entitlements", "billing.billing_accounts",
      ...["opening_shareholders", "opening_balance_setups"].map(name => `${phase === "contracted" ? rf : "public"}.${name}`),
      ...["transaction_sources", "coverage_intervals", "suggestion_acceptances", "transactions", "source_files",
        "sync_attempts", "accounts", "connections"].map(name => `banking.${name}`),
      ...["opening_received_dividend_settlements", "opening_position_component_sources", "opening_position_components",
        "opening_position_rebuilds", "entry_corrections", "entry_sources", "entry_contexts", "entries"].map(name => `ledger.${name}`),
      ...["lifecycle_correction_sources", "lifecycle_corrections", "measurement_sources", "year_end_measurements",
        "received_fund_distribution_recognitions", "received_dividend_recognitions", "share_purchase_recognitions",
        "cash_settlements", "event_sources", "economic_events", "position_boundary_confirmations", "position_classifications",
        "source_fact_registry", "company_year_policies", "corrections", "share_sale_allocations", "received_fund_distributions",
        "received_dividends", "share_sales", "share_purchases", "acquisition_lots", "positions"].map(name => `investments.${name}`),
      "backend_system.banking_command_receipts", "backend_system.ledger_command_receipts", "backend_system.ledger_workflow_receipts",
    ];
    assert.equal(required.length, 77);
    for (const relation of required) assert.ok(calls.some(call => call.startsWith(`delete from ${relation} `)), relation);
    const deletion = relation => calls.findIndex(call => call.startsWith(`delete from ${relation} `));
    assert.ok(deletion("public.corporate_decision_finalizations") < deletion("ledger.entries"));
    assert.ok(deletion("public.holding_actions") < deletion("ledger.entries"));
    assert.ok(deletion("banking.suggestion_acceptances") < deletion("ledger.entries"));
    assert.ok(deletion("ledger.entry_sources") < deletion("ledger.entries"));
    assert.ok(deletion("ledger.entry_corrections") < deletion("ledger.entries"));
    assert.ok(deletion(`${rf}.production_filing_submissions`) < deletion(`${rf}.filing_approval_snapshots`));
    assert.ok(deletion(`${rf}.filing_approval_snapshots`) < deletion("billing.production_pilot_entitlements"));
    assert.ok(deletion("public.company_archive_source_generations") < deletion("public.companies"));
    assert.doesNotMatch(calls.join("\n"), /session_replication_role|no force row level security|disable trigger (?:all|user)/iu);
    database.assertRestored();
    assert.ok(calls.indexOf("commit") < calls.indexOf(`delete_company:${companyId}`));
    assert.deepEqual(calls.slice(-3), [`delete_company:${companyId}`, "delete_user:owner-created", "database_end"]);
  });
}

test("browser owner cleanup removes every tracked company before the shared owner", async () => {
  const calls = [];
  const database = cleanupDatabaseProbe(calls);

  const errors = await cleanupBrowserOwnerResources({
    admin: cleanupAdmin(calls),
    companyId: "11111111-1111-4111-8111-111111111111",
    companyIds: ["11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"],
    database,
    databaseStarted: true,
    ownerId: "owner-created",
  });

  assert.deepEqual(errors, []);
  assert.deepEqual(
    calls.filter((call) => call.startsWith("delete_company:")),
    ["delete_company:11111111-1111-4111-8111-111111111111", "delete_company:22222222-2222-4222-8222-222222222222"],
  );
  assert.deepEqual(calls.slice(-2), ["delete_user:owner-created", "database_end"]);
});

test("browser owner cleanup preserves source failure and continues independent cleanup", async () => {
  const calls = [];
  const sourceFailure = new Error("source cleanup failed");
  const database = cleanupDatabaseProbe(calls, { failStatement: "delete from public.documents", failure: sourceFailure });

  const errors = await cleanupBrowserOwnerResources({
    admin: cleanupAdmin(calls),
    companyId: "33333333-3333-4333-8333-333333333333",
    database,
    databaseStarted: true,
    ownerId: "owner-created",
  });

  assert.deepEqual(errors, [sourceFailure]);
  assert.ok(calls.includes("rollback"));
  assert.deepEqual(calls.slice(-3), [
    "delete_company:33333333-3333-4333-8333-333333333333",
    "delete_user:owner-created",
    "database_end",
  ]);
});

test("browser owner cleanup preserves both operation and rollback failures", async () => {
  const calls = [];
  const failure = new Error("fixture delete failed");
  const rollbackFailure = new Error("fixture rollback failed");
  const database = cleanupDatabaseProbe(calls, { failStatement: "delete from public.documents", failure, rollbackFailure });
  const errors = await cleanupBrowserOwnerResources({ admin: cleanupAdmin(calls), database, databaseStarted: true,
    companyId: "44444444-4444-4444-8444-444444444444", ownerId: "owner-created" });
  assert.equal(errors.length, 1);
  assert.ok(errors[0] instanceof AggregateError);
  assert.deepEqual(errors[0].errors, [failure, rollbackFailure]);
  assert.deepEqual(calls.slice(-2), ["delete_user:owner-created", "database_end"]);
});

for (const defect of ["missing-family", "wrong-owner", "invalid-trigger-mode"]) {
  test(`browser owner cleanup fails closed for ${defect}`, async () => {
    const calls = [];
    const database = cleanupDatabaseProbe(calls, { defect });
    const errors = await cleanupBrowserOwnerResources({ admin: cleanupAdmin(calls), database, databaseStarted: true,
      companyId: "55555555-5555-4555-8555-555555555555" });
    assert.equal(errors.length, 1);
    assert.ok(!calls.some(call => call.startsWith("delete from ")));
    assert.ok(!calls.includes("commit"));
    database.assertRestored();
  });
}

test("browser owner cleanup removes immutable corporate and production filing graphs", async (t) => {
  const databaseUrl = process.env.DATABASE_URL;
  const supabaseUrl = process.env.SUPABASE_URL;
  const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (
    !databaseUrl ||
    !supabaseUrl ||
    !serviceRoleKey ||
    !isLoopbackPostgresUrl(databaseUrl) ||
    !isLoopbackSupabaseUrl(supabaseUrl)
  ) {
    t.skip("local Supabase runtime is required");
    return;
  }

  const admin = createClient(supabaseUrl, serviceRoleKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  const database = new pg.Client({ connectionString: databaseUrl });
  await database.connect();
  const companyId = randomUUID();
  const previewId = randomUUID();
  const entitlementId = randomUUID();
  const approvalId = randomUUID();
  const submissionId = randomUUID();
  const decisionId = randomUUID();
  const setId = randomUUID();
  const resources = {
    admin,
    companyId: undefined,
    database,
    databaseStarted: true,
    ownerId: undefined,
  };
  let cleanupAttempted = false;

  try {
    const { data: createdUser, error: createUserError } = await admin.auth.admin.createUser({
      email: `browser-cleanup-${randomUUID()}@example.test`,
      password: `Talli-${randomUUID()}!`,
      email_confirm: true,
    });
    assert.ifError(createUserError);
    const ownerId = createdUser.user.id;
    resources.ownerId = ownerId;
    await database.query(
      `insert into public.companies (id, org_number, name, entity_type, created_by)
       values ($1, $2, 'Browser cleanup graph', 'AS', $3)`,
      [companyId, String(100_000_000 + Math.floor(Math.random() * 899_999_999)), ownerId],
    );
    resources.companyId = companyId;
    const rfSchema = (await database.query("select to_regclass('shareholder_register_filing.production_filing_submissions') is not null present")).rows[0].present
      ? "shareholder_register_filing" : "public";
    const graphRelations = [
      ...["filing_previews", "filing_approval_snapshots", "production_filing_submissions", "production_filing_events"].map(name => `${rfSchema}.${name}`),
      "billing.production_pilot_entitlements", "public.corporate_decisions", "public.corporate_document_sets", "public.corporate_document_events",
    ];
    await fixtureTableTransaction(database, graphRelations, async () => {
      await database.query(
        `insert into ${rfSchema}.filing_previews (
           id, company_id, income_year, filing, status, issues, preview,
           hovedskjema_xml, underskjema_xml, created_by
         ) values ($1, $2, 2025, $4, 'ready', '[]', 'preview', '<xml/>', '{}', $3)`,
        [previewId, companyId, ownerId, rfSchema === "public" ? "RF-1086" : "aksjonærregisteroppgaven"],
      );
      await database.query(
        `insert into billing.production_pilot_entitlements (
           id, company_id, user_id, income_year, obligation, case_profile, status,
           billing_exempt, system_user_external_reference, starts_at, expires_at,
           evidence_reference, approved_by
         ) values (
           $1, $2, $3, 2025, 'aksjonaerregisteroppgaven', 'rf1086_no_activity_v1', 'revoked',
           true, 'browser-cleanup', now() - interval '2 hours', now() - interval '1 hour',
           'browser cleanup graph', $3
         )`,
        [entitlementId, companyId, ownerId],
      );
      await database.query(
        `insert into ${rfSchema}.filing_approval_snapshots (
           id, entitlement_id, preview_id, company_id, user_id, income_year,
           obligation, case_profile, adapter_version, payload_hash, manifest_hash,
           manifest, approved_by, invalidated_at, invalidation_reason
        ) values (
           $1, $2, $3, $4, $5, 2025, 'aksjonaerregisteroppgaven', 'rf1086_no_activity_v1',
           'test-v1', $6, $7, '{}', $5, now(), 'cleanup test'
         )`,
        [
          approvalId,
          entitlementId,
          previewId,
          companyId,
          ownerId,
          "a".repeat(64),
          "b".repeat(64),
        ],
      );
      await database.query(
        `insert into ${rfSchema}.production_filing_submissions (
           id, approval_id, entitlement_id, company_id, user_id, income_year,
           obligation, case_profile, payload_hash, adapter_version, environment,
           status, submitted_by
         ) values (
           $1, $2, $3, $4, $5, 2025, 'aksjonaerregisteroppgaven', 'rf1086_no_activity_v1',
           $6, 'test-v1', 'production', 'received', $5
        )`,
        [submissionId, approvalId, entitlementId, companyId, ownerId, "a".repeat(64)],
      );
      await database.query(
        `insert into ${rfSchema}.production_filing_events (
           submission_id, operation_name, operation_state, attempt, body_hash,
           idempotency_key, resulting_status
         ) values ($1, 'confirm', 'succeeded', 1, $2, $3, 'received')`,
        [submissionId, "e".repeat(64), randomUUID()],
      );
      const sourceHash = "c".repeat(64);
      const decisionHash = "d".repeat(64);
      await database.query(
        `insert into public.corporate_decisions (
           id, company_id, income_year, decision_kind, source_hash,
           canonical_input, decision_hash, created_by
         ) values ($1, $2, 2025, 'owner_dividend', $3, $4, $5, $6)`,
        [
          decisionId,
          companyId,
          sourceHash,
          {
            company_id: companyId,
            income_year: 2025,
            decision_kind: "owner_dividend",
            source_hash: sourceHash,
          },
          decisionHash,
          ownerId,
        ],
      );
      await database.query(
        `insert into public.corporate_document_sets (
           id, company_id, income_year, decision_id, template_family,
           template_version, decision_hash, created_by
         ) values ($1, $2, 2025, $3, 'norwegian_simple_as', 'cleanup-v1', $4, $5)`,
        [setId, companyId, decisionId, decisionHash, ownerId],
      );
      await database.query(
        `insert into public.corporate_document_events (
           company_id, income_year, decision_id, set_id, event_kind, actor_id,
           decision_hash, metadata, idempotency_key
         ) values ($1, 2025, $2, $3, 'generated', $4, $5, '{}', $6)`,
        [companyId, decisionId, setId, ownerId, decisionHash, randomUUID()],
      );

    });

    const cleanupErrors = await cleanupBrowserOwnerResources(resources);
    cleanupAttempted = true;
    assert.deepEqual(cleanupErrors, []);

    const verifier = new pg.Client({ connectionString: databaseUrl });
    await verifier.connect();
    try {
      const { rows: [remaining] } = await fixtureTableTransaction(verifier, graphRelations, () => verifier.query(
        `select
           (select count(*) from public.companies where id = $1)::integer as companies,
           (select count(*) from public.corporate_decisions where company_id = $1)::integer as decisions,
           (select count(*) from public.corporate_document_sets where company_id = $1)::integer as document_sets,
           (select count(*) from public.corporate_document_events where company_id = $1)::integer as document_events,
           (select count(*) from ${rfSchema}.filing_approval_snapshots where company_id = $1)::integer as approvals,
           (select count(*) from ${rfSchema}.production_filing_submissions where company_id = $1)::integer as submissions,
           (select count(*) from ${rfSchema}.production_filing_events where submission_id = $3)::integer as submission_events,
           (select count(*) from auth.users where id = $2)::integer as users`,
        [companyId, ownerId, submissionId],
      ));
      assert.deepEqual(remaining, {
        companies: 0,
        decisions: 0,
        document_sets: 0,
        document_events: 0,
        approvals: 0,
        submissions: 0,
        submission_events: 0,
        users: 0,
      });
    } finally {
      await verifier.end();
    }
  } finally {
    if (!cleanupAttempted) {
      await cleanupBrowserOwnerResources(resources);
    }
  }
});

function cleanupAdmin(calls) {
  return {
    auth: {
      admin: {
        async deleteUser(id) {
          calls.push(`delete_user:${id}`);
          return { error: null };
        },
      },
    },
    from(table) {
      assert.equal(table, "companies");
      return {
        delete() {
          return {
            async eq(column, id) {
              assert.equal(column, "id");
              calls.push(`delete_company:${id}`);
              return { error: null };
            },
          };
        },
      };
    },
  };
}

function startSleepingProcess() {
  return startOwnedProcess({
    command: process.execPath,
    args: ["-e", "setInterval(() => {}, 1_000)"],
    cwd: root,
    readinessProof: "NEVER_EMITTED",
  });
}

function hasExited(child) {
  return child.exitCode !== null || child.signalCode !== null;
}

function serverProgram(readinessProof) {
  return [
    'const http = require("node:http");',
    'http.createServer((_request, response) => response.end("ready"))',
    `.listen(Number(process.env.TEST_PORT), "127.0.0.1", () => console.log(${JSON.stringify(readinessProof)}));`,
  ].join("");
}

function hangingServerProgram(readinessProof) {
  return [
    'const http = require("node:http");',
    "http.createServer(() => {})",
    `.listen(Number(process.env.TEST_PORT), "127.0.0.1", () => console.log(${JSON.stringify(readinessProof)}));`,
  ].join("");
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

// Catalog model for the real finite transaction engine: it deliberately starts
// without owner SET, private schema USAGE, or direct-table write grants. It also
// retains all four USER trigger modes so success/failure must restore each one.
function cleanupDatabaseProbe(calls, { phase = "overlap", failStatement, failure,
  rollbackFailure, defect } = {}) {
  const roles = new Map();
  const tables = new Map();
  const schemas = new Map();
  let role = "postgres";
  const ownerBySchema = { public: "postgres", backend_system: "ledger_store_owner",
    ledger: "ledger_store_owner", banking: "banking_store_owner", investments: "investments_store_owner",
    billing: "billing_store_owner", documents: "documents_store_owner",
    authority_connections: "authority_connections_store_owner", shareholder_register_filing: "shareholder_register_filing_store_owner" };
  const specialOwners = { "public.documents": "documents_store_owner",
    "backend_system.banking_command_receipts": "banking_store_owner",
    "backend_system.ledger_command_receipts": "ledger_store_owner",
    "backend_system.ledger_workflow_receipts": "ledger_workflow_store_owner",
    "shareholder_register_filing.migration_inventory": "postgres",
    "shareholder_register_filing.migration_quarantine": "postgres" };
  const initialRole = () => ({ admin_option: true, inherit_option: false, set_option: false });
  const initialTriggers = () => [{ name: 'normal"trigger', mode: "O" }, { name: "disabled", mode: "D" },
    { name: "replica", mode: "R" }, { name: "always", mode: "A" }];
  const table = relation => {
    if (!tables.has(relation)) tables.set(relation, { acl: "original-table-acl", forced: true, triggers: initialTriggers() });
    return tables.get(relation);
  };
  const physicalKind = relation => {
    if (defect === "missing-family" && relation === "shareholder_register_filing.filing_previews") return undefined;
    if (["public.billing_accounts", "public.production_pilot_entitlements"].includes(relation)) return "v";
    if (phase === "predecessor") {
      if (relation.startsWith("shareholder_register_filing.") || relation.startsWith("authority_connections.") || relation === "ledger.opening_bank_inputs") return undefined;
    } else if (["public.system_user_requests", ...["production_feedback_artifacts", "production_filing_events",
      "production_filing_submissions", "filing_approval_snapshots"].map(name => `public.${name}`)].includes(relation)) {
      return phase === "contracted" ? undefined : "v";
    }
    if (phase === "contracted" && ["public.opening_balance_setups", "public.opening_shareholders"].includes(relation)) return undefined;
    return "r";
  };
  const decode = identifier => identifier.replaceAll('"', "");
  return {
    connectionParameters: { host: "127.0.0.1" },
    async end() { calls.push("database_end"); },
    assertRestored() {
      assert.equal(role, "postgres");
      for (const value of roles.values()) assert.deepEqual(value, initialRole());
      for (const value of schemas.values()) assert.equal(value, false);
      for (const value of tables.values()) {
        assert.equal(value.acl, "original-table-acl");
        assert.equal(value.forced, true);
        assert.deepEqual(value.triggers, initialTriggers());
      }
    },
    async query(statement, values = []) {
      statement = statement.replace(/\s+/gu, " ").trim();
      calls.push(statement);
      if (failStatement && statement.startsWith(failStatement)) throw failure;
      if (statement.includes("select relkind")) {
        const relkind = physicalKind(values[0]);
        return { rows: relkind ? [{ relkind }] : [] };
      }
      if (statement.includes("select current_user principal")) return { rows: [{ principal: role, bypass: true }] };
      if (statement.includes("pg_has_role(current_user,$1,'SET')")) {
        if (!roles.has(values[0])) roles.set(values[0], initialRole());
        return { rows: [{ present: roles.get(values[0]).set_option }] };
      }
      if (statement.includes("from pg_auth_members")) return { rows: [structuredClone(roles.get(values[0]))] };
      if (statement.includes("nspacl::text acl,has_schema_privilege")) {
        if (!schemas.has(values[0])) schemas.set(values[0], false);
        return { rows: [{ acl: "original-schema-acl", permitted: schemas.get(values[0]) }] };
      }
      if (statement.includes("nspacl::text acl")) return { rows: [{ acl: schemas.get(values[0]) ? "borrowed-schema-acl" : "original-schema-acl" }] };
      if (statement.includes("c.relacl::text acl")) {
        assert.equal(physicalKind(values[0]), "r", "views cannot enter the DDL janitor");
        const stored = table(values[0]);
        const owner = defect === "wrong-owner" ? "unexpected_owner" : specialOwners[values[0]] ?? ownerBySchema[values[0].split(".")[0]];
        return { rows: [{ acl: stored.acl, forced: stored.forced, owner, missing: ["UPDATE", "DELETE"] }] };
      }
      if (statement.includes("from pg_trigger")) {
        assert.ok(statement.includes("not tgisinternal"));
        const triggers = structuredClone(table(values[0]).triggers);
        if (defect === "invalid-trigger-mode") triggers[0].mode = "X";
        return { rows: triggers };
      }
      if (statement.includes("select relacl::text acl,relforcerowsecurity")) {
        const stored = table(values[0]);
        return { rows: [{ acl: stored.acl, forced: stored.forced }] };
      }
      if (statement.includes("has_table_privilege('billing_store_owner'")) return { rows: [{ acl: table("billing.billing_command_receipts").acl, permitted: false }] };
      if (statement.includes("select relacl::text acl")) return { rows: [{ acl: table("billing.billing_command_receipts").acl }] };
      let match;
      if ((match = /^set local role (.+)$/u.exec(statement))) role = decode(match[1]);
      else if (statement === "reset role") role = "postgres";
      else if ((match = /^grant "([^"]+)" to "postgres" with set true granted by "postgres"$/u.exec(statement))) roles.get(match[1]).set_option = true;
      else if ((match = /^grant "([^"]+)" to "postgres" with admin (true|false), inherit (true|false), set (true|false) granted by "postgres"$/u.exec(statement))) {
        roles.set(match[1], { admin_option: match[2] === "true", inherit_option: match[3] === "true", set_option: match[4] === "true" });
      } else if ((match = /^(grant|revoke) usage on schema "([^"]+)" (?:to|from) "postgres"$/u.exec(statement))) {
        assert.equal(role, ownerBySchema[match[2]], "schema grant uses its exact owner");
        schemas.set(match[2], match[1] === "grant");
      } else if ((match = /^(grant|revoke) UPDATE,DELETE on (\S+) (?:to|from) "postgres"$/u.exec(statement))) table(decode(match[2])).acl = match[1] === "grant" ? "borrowed-table-acl" : "original-table-acl";
      else if ((match = /^alter table (\S+) (enable replica|enable always|enable|disable) trigger "((?:[^"]|"")+)"$/u.exec(statement))) {
        table(decode(match[1])).triggers.find(trigger => trigger.name === match[3].replaceAll('""', '"')).mode = { enable: "O", disable: "D", "enable replica": "R", "enable always": "A" }[match[2]];
      } else if (statement === "grant delete on billing.billing_command_receipts to billing_store_owner") table("billing.billing_command_receipts").acl = "borrowed-table-acl";
      else if (statement === "revoke delete on billing.billing_command_receipts from billing_store_owner") table("billing.billing_command_receipts").acl = "original-table-acl";
      else if (statement === "rollback") {
        for (const owner of roles.keys()) roles.set(owner, initialRole());
        for (const name of schemas.keys()) schemas.set(name, false);
        tables.clear(); role = "postgres";
        if (rollbackFailure) throw rollbackFailure;
      } else if (statement.startsWith("delete from ")) {
        assert.equal(role, "postgres");
        assert.equal(values.length, 1);
        assert.ok(/^[0-9a-f-]{36}$/iu.test(Array.isArray(values[0]) ? values[0][0] : values[0]));
        assert.match(statement, /where (?:company_id|id|submission_id|document_id)/u);
      }
      return { rows: [] };
    },
  };
}
