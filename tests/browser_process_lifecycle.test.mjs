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

test("browser owner cleanup removes tracked sources before company and user", async () => {
  const calls = [];
  const database = {
    async query(statement) {
      calls.push(statement.replace(/\s+/gu, " ").trim());
    },
    async end() {
      calls.push("database_end");
    },
  };
  const admin = cleanupAdmin(calls);

  const errors = await cleanupBrowserOwnerResources({
    admin,
    companyId: "company-created",
    database,
    databaseStarted: true,
    ownerId: "owner-created",
  });

  assert.deepEqual(errors, []);
  const deletedTables = calls
    .filter((call) => call.startsWith("delete from public."))
    .map((call) => call.match(/^delete from public\.([a-z_]+)/u)?.[1]);
  assert.deepEqual(deletedTables, [
    "company_year_acceptances",
    "company_year_admissions",
    "company_eligibility_assessments",
    "customer_agreement_acceptances",
    "corporate_document_events",
    "corporate_decision_finalizations",
    "corporate_document_artifacts",
    "corporate_document_sets",
    "corporate_decisions",
    "production_filing_events",
    "production_feedback_artifacts",
    "production_filing_submissions",
    "filing_approval_snapshots",
    "production_pilot_entitlements",
    "company_deletion_reviews",
    "bank_suggestion_acceptances",
    "investment_lot_allocations",
    "investment_lots",
    "investment_positions",
    "filing_review_comments",
    "filing_submissions",
    "holding_actions",
    "documents",
    "authority_test_runs",
    "authority_permissions",
    "filing_previews",
    "opening_shareholders",
    "opening_balance_setups",
    "billing_accounts",
    "audit_events",
    "company_archive_export_receipts",
    "company_archive_export_attempts",
    "company_archive_source_generations",
    "companies",
  ]);
  assert.ok(calls.includes(
    "delete from backend_system.ledger_command_receipts where company_id = $1",
  ));
  assert.ok(calls.includes(
    "delete from backend_system.ledger_workflow_receipts where company_id = $1",
  ));
  assert.ok(calls.includes("delete from ledger.entry_sources where company_id = $1"));
  assert.ok(calls.includes("delete from ledger.entry_contexts where company_id = $1"));
  assert.ok(calls.includes("delete from ledger.entries where company_id = $1"));
  assert.ok(calls.includes(
    "delete from ledger.opening_received_dividend_settlements where company_id = $1",
  ));
  assert.ok(calls.includes("delete from public.companies where id = $1"));
  assert.ok(calls.includes("set local role ledger_store_owner"));
  assert.ok(calls.includes("set local role ledger_workflow_store_owner"));
  for (const table of [
    "backend_system.ledger_command_receipts",
    "backend_system.ledger_workflow_receipts",
    "ledger.entries",
  ]) {
    const disable = calls.indexOf(
      `alter table ${table} no force row level security`,
    );
    const remove = calls.indexOf(
      `delete from ${table} where company_id = $1`,
    );
    const restore = calls.indexOf(
      `alter table ${table} force row level security`,
    );
    assert.ok(disable < remove && remove < restore);
  }
  assert.ok(
    calls.indexOf("delete from ledger.entry_sources where company_id = $1")
      < calls.indexOf("delete from ledger.entries where company_id = $1"),
  );
  const restoreTriggerMode = calls.indexOf("set local session_replication_role = origin");
  assert.ok(
    calls.indexOf("delete from public.company_eligibility_assessments where company_id = $1")
      < restoreTriggerMode,
  );
  assert.ok(
    calls.indexOf("delete from public.corporate_decisions where company_id = $1")
      < restoreTriggerMode,
  );
  assert.ok(
    calls.indexOf("delete from public.production_feedback_artifacts where company_id = $1")
      < restoreTriggerMode,
  );
  assert.ok(
    calls.indexOf("delete from public.company_archive_source_generations where company_id = $1")
      < calls.indexOf("delete from public.companies where id = $1"),
  );
  assert.ok(
    restoreTriggerMode
      < calls.indexOf("alter table public.companies disable trigger user"),
  );
  assert.ok(
    calls.indexOf("alter table public.companies disable trigger user")
      < calls.indexOf("delete from public.companies where id = $1"),
  );
  assert.ok(
    calls.indexOf("delete from public.companies where id = $1")
      < calls.indexOf("alter table public.companies enable trigger user"),
  );
  assert.ok(calls.indexOf("commit") < calls.indexOf("delete_company:company-created"));
  assert.deepEqual(calls.slice(-3), [
    "delete_company:company-created",
    "delete_user:owner-created",
    "database_end",
  ]);
});

test("browser owner cleanup removes every tracked company before the shared owner", async () => {
  const calls = [];
  const database = {
    async query(statement) {
      calls.push(statement.replace(/\s+/gu, " ").trim());
    },
    async end() {
      calls.push("database_end");
    },
  };

  const errors = await cleanupBrowserOwnerResources({
    admin: cleanupAdmin(calls),
    companyId: "company-one",
    companyIds: ["company-one", "company-two"],
    database,
    databaseStarted: true,
    ownerId: "owner-created",
  });

  assert.deepEqual(errors, []);
  assert.deepEqual(
    calls.filter((call) => call.startsWith("delete_company:")),
    ["delete_company:company-one", "delete_company:company-two"],
  );
  assert.deepEqual(calls.slice(-2), ["delete_user:owner-created", "database_end"]);
});

test("browser owner cleanup preserves source failure and continues independent cleanup", async () => {
  const calls = [];
  const sourceFailure = new Error("source cleanup failed");
  const database = {
    async query(statement) {
      const normalized = statement.replace(/\s+/gu, " ").trim();
      calls.push(normalized);
      if (normalized.startsWith("delete from public.documents")) {
        throw sourceFailure;
      }
    },
    async end() {
      calls.push("database_end");
    },
  };

  const errors = await cleanupBrowserOwnerResources({
    admin: cleanupAdmin(calls),
    companyId: "company-created",
    database,
    databaseStarted: true,
    ownerId: "owner-created",
  });

  assert.deepEqual(errors, [sourceFailure]);
  assert.ok(calls.includes("rollback"));
  assert.deepEqual(calls.slice(-3), [
    "delete_company:company-created",
    "delete_user:owner-created",
    "database_end",
  ]);
});

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
    await database.query(
      `insert into public.filing_previews (
         id, company_id, income_year, filing, status, issues, preview,
         hovedskjema_xml, underskjema_xml, created_by
       ) values ($1, $2, 2025, 'RF-1086', 'ready', '[]', 'preview', '<xml/>', '{}', $3)`,
      [previewId, companyId, ownerId],
    );
    await database.query(
      `insert into public.production_pilot_entitlements (
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
      `insert into public.filing_approval_snapshots (
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
      `insert into public.production_filing_submissions (
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
      `insert into public.production_filing_events (
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

    const cleanupErrors = await cleanupBrowserOwnerResources(resources);
    cleanupAttempted = true;
    assert.deepEqual(cleanupErrors, []);

    const verifier = new pg.Client({ connectionString: databaseUrl });
    await verifier.connect();
    try {
      const { rows: [remaining] } = await verifier.query(
        `select
           (select count(*) from public.companies where id = $1)::integer as companies,
           (select count(*) from public.corporate_decisions where company_id = $1)::integer as decisions,
           (select count(*) from public.corporate_document_sets where company_id = $1)::integer as document_sets,
           (select count(*) from public.corporate_document_events where company_id = $1)::integer as document_events,
           (select count(*) from public.filing_approval_snapshots where company_id = $1)::integer as approvals,
           (select count(*) from public.production_filing_submissions where company_id = $1)::integer as submissions,
           (select count(*) from public.production_filing_events where submission_id = $3)::integer as submission_events,
           (select count(*) from auth.users where id = $2)::integer as users`,
        [companyId, ownerId, submissionId],
      );
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
