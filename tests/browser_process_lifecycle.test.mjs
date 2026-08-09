import assert from "node:assert/strict";
import { EventEmitter, once } from "node:events";
import test from "node:test";

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
    "customer_agreement_acceptances",
    "production_feedback_artifacts",
    "filing_approval_snapshots",
    "company_deletion_reviews",
    "corporate_document_events",
    "corporate_decision_finalizations",
    "corporate_document_artifacts",
    "corporate_document_sets",
    "corporate_decisions",
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
    "ledger_entries",
    "opening_shareholders",
    "opening_balance_setups",
    "billing_accounts",
    "audit_events",
    "company_archive_export_receipts",
    "company_archive_export_attempts",
    "company_archive_source_generations",
  ]);
  assert.ok(calls.indexOf("commit") < calls.indexOf("delete_company:company-created"));
  assert.deepEqual(calls.slice(-3), [
    "delete_company:company-created",
    "delete_user:owner-created",
    "database_end",
  ]);
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
