import assert from "node:assert/strict";
import { once } from "node:events";
import test from "node:test";

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

test("a ready owned process is terminated and cleanup is idempotent", async () => {
  const port = await allocateLoopbackPort();
  const child = startOwnedProcess({
    command: process.execPath,
    args: ["-e", serverProgram()],
    cwd: root,
    env: { ...globalThis.process.env, TEST_PORT: String(port) },
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

function startSleepingProcess() {
  return startOwnedProcess({
    command: process.execPath,
    args: ["-e", "setInterval(() => {}, 1_000)"],
    cwd: root,
  });
}

function hasExited(child) {
  return child.exitCode !== null || child.signalCode !== null;
}

function serverProgram() {
  return [
    'const http = require("node:http");',
    'http.createServer((_request, response) => response.end("ready"))',
    '.listen(Number(process.env.TEST_PORT), "127.0.0.1");',
  ].join("");
}
