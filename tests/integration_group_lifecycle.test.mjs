import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import {
  chmodSync, copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync,
  readdirSync, realpathSync, rmSync, writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import test from "node:test";

// Only the lifecycle boundaries are synthetic. The shell, plan, receipt state
// machine and loopback validator are copied unchanged from the current WIP.
// Everything (including diagnostics and Git metadata) lives under one temp root.
const fixtureSupport = String.raw`
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { appendFileSync, existsSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
export const fault = process.env.LIFECYCLE_FAULT;
export const database = 'postgresql://postgres:fixture@127.0.0.1:54322/postgres';
export const url = 'http://127.0.0.1:54321';
export function event(name, workdir = process.env.TALLI_SUPABASE_WORKDIR) {
  const pending = join(process.env.TALLI_CI_OUTPUT_DIR, 'pending.json');
  if (process.env.LIFECYCLE_MODE === 'group') assert.ok(existsSync(pending), 'receipt must precede acquisition');
  const state = existsSync(pending) ? JSON.parse(readFileSync(pending, 'utf8'))
    : { setup: {}, cleanup: {}, finished: false };
  appendFileSync(process.env.LIFECYCLE_TRACE, JSON.stringify({ name, workdir,
    setup: state.setup, cleanup: state.cleanup, finished: state.finished,
    published: existsSync(join(process.env.TALLI_CI_OUTPUT_DIR, 'publish/result.json')) }) + '\n');
  return state;
}
export function driftGenerated() {
  for (const name of ['next-env.d.ts', 'tsconfig.json', 'AGENTS.md', 'CLAUDE.md'])
    writeFileSync(join('apps/web', name), 'generated ' + name + '\n');
}
export function localContext() {
  assert.equal(process.env.DATABASE_URL, database);
  assert.equal(process.env.SUPABASE_URL, url);
  assert.equal(process.env.SUPABASE_ANON_KEY, 'fixture-anon');
  assert.equal(process.env.SUPABASE_SERVICE_ROLE_KEY, 'fixture-service');
  assert.equal(process.env.NEXT_PUBLIC_SUPABASE_URL, url);
  assert.equal(process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY, 'fixture-anon');
  assert.ok(process.env.TALLI_SUPABASE_WORKDIR);
  assert.ok(!Object.keys(process.env).some(name => name.startsWith('TALLI_CI_LOCAL_')));
}
export async function hold(name) {
  event('held:' + name);
  // Bounded even if the test process is interrupted before releasing the shim.
  const deadline = Date.now() + 10000;
  while (!existsSync(process.env.LIFECYCLE_RELEASE)) {
    assert.ok(Date.now() < deadline, 'fixture hold timed out');
    await delay(10);
  }
}
export function changeSource() {
  writeFileSync('source.txt', 'changed source\n');
  if (fault === 'committed-source-change') {
    const result = spawnSync('git', ['add', 'source.txt'], { encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    const commit = spawnSync('git', ['commit', '--quiet', '-m', 'fixture source change'], { encoding: 'utf8' });
    assert.equal(commit.status, 0, commit.stderr);
  }
}
export function failRestore() { renameSync('apps/web', 'apps/web-displaced'); }
`;

const npmShim = String.raw`
import assert from 'node:assert/strict';
import { existsSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { database, url, event, fault, hold, localContext, failRestore } from '../repo/scripts/lifecycle-fixture.mjs';
const args = process.argv.slice(2);
assert.equal(process.env.SUPABASE_TELEMETRY_DISABLED, '1');
assert.equal(process.env.DO_NOT_TRACK, '1');
if (args[0] === 'exec') {
  assert.deepEqual(args.slice(0, 3), ['exec', '--', 'supabase']);
  assert.ok(['start', 'status', 'stop'].includes(args[3]), 'unexpected stack command');
  assert.equal(args[4], '--workdir');
  const workdir = args[5];
  assert.ok(existsSync(join(workdir, 'prepared')), 'only the owned prepared workdir may be used');
  const state = event(args[3], workdir);
  if (args[3] === 'start') {
    assert.equal(state.setup.status, undefined);
    writeFileSync(join(workdir, 'partially-started'), 'owned stack\n');
    if (fault === 'hold-start') await hold('start');
    if (fault === 'start-failure') process.exit(23);
  } else if (args[3] === 'status') {
    assert.deepEqual(args.slice(6), ['--output', 'env']);
    if (fault === 'status-failure') process.exit(29);
    process.stdout.write([
      'DB_URL=' + database, 'API_URL=' + url,
      'ANON_KEY=fixture-anon', 'SERVICE_ROLE_KEY=fixture-service',
      'PUBLISHABLE_KEY=fixture-anon', 'SECRET_KEY=fixture-service', '',
    ].join('\n'));
  } else {
    assert.deepEqual(args.slice(6), ['--no-backup']);
    if (process.env.LIFECYCLE_MODE === 'group')
      assert.ok(Number.isInteger(state.cleanup.startedMs), 'cleanup must be marked before stopping');
    if (fault.includes('stop-failure')) process.exit(31);
  }
} else {
  assert.deepEqual(args.slice(0, 1), ['run']);
  assert.equal(args.length, 2);
  assert.ok(['test:supabase-advisors', 'test:authority-connections-database'].includes(args[1]),
    'unexpected npm command: never execute a real suite');
  const state = event(args[1]);
  assert.equal(state.setup.status, 'success');
  if (args[1] === 'test:authority-connections-database') {
    localContext();
    if (fault === 'hold-phase') await hold('phase');
    if (fault === 'restore-failure') failRestore();
    if (fault.startsWith('phase-failure')) process.exit(37);
  }
}
`;

// These shims exercise actual filesystem commands, injecting one failure at a
// selected acquisition boundary. A failed backup can contain partial private
// bytes; it must be deleted, never restored over the original.
const filesystemShim = String.raw`
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const command = path.basename(process.argv[1]), args = process.argv.slice(2);
const counter = path.join(process.env.LIFECYCLE_CONTROL, command + '-count');
const count = fs.existsSync(counter) ? Number(fs.readFileSync(counter, 'utf8')) + 1 : 1;
fs.writeFileSync(counter, String(count));
const pending = path.join(process.env.TALLI_CI_OUTPUT_DIR, 'pending.json');
const locked = fs.existsSync('.git/talli-integration.lock');
fs.appendFileSync(path.join(process.env.LIFECYCLE_CONTROL, 'filesystem.jsonl'), JSON.stringify({
  command, args, count, initialized: fs.existsSync(pending), locked,
}) + '\n');
const fault = process.env.LIFECYCLE_FAULT;
if (fault === command + '-failure-' + count) {
  if (command === 'cp') fs.writeFileSync(args.at(-1), 'PARTIAL_PRIVATE_BACKUP');
  process.exit(command === 'mktemp' ? 43 : 45);
}
if (command === 'rmdir') {
  assert.ok(locked, 'unlock must still own the checkout');
  if (process.env.LIFECYCLE_MODE === 'group') {
    assert.ok(fs.existsSync(path.join(process.env.TALLI_CI_OUTPUT_DIR, 'publish/result.json')),
      'lock must cover receipt finalization');
  }
  if (fault === 'unlock-failure') process.exit(47);
}
const binaries = JSON.parse(process.env.LIFECYCLE_FILESYSTEM_BINARIES);
const result = spawnSync(binaries[command], args, { stdio: 'inherit' });
process.exit(result.status ?? 1);
`;

const nodeShim = String.raw`
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const args = process.argv.slice(2);
if (args[0] === 'scripts/run-integration-group.mjs' && args[1] === '--finalize') {
  assert.ok(fs.existsSync('.git/talli-integration.lock'), 'finalization must hold the checkout lock');
  fs.appendFileSync(path.join(process.env.LIFECYCLE_CONTROL, 'finalizations.jsonl'),
    JSON.stringify(args.slice(2)) + '\n');
}
const result = spawnSync(process.execPath, args, { stdio: 'inherit' });
process.exit(result.status ?? 1);
`;

function fixture(t, fault = "success", selection = ["--group", "authority"], { existingClaude = false } = {}) {
  // macOS exposes TMPDIR through /var, whose symlink ancestor is correctly
  // rejected by the real receipt output guard. Give it a canonical path.
  const root = realpathSync(mkdtempSync(join(tmpdir(), "talli-integration-lifecycle-")));
  const repo = join(root, "repo");
  const bin = join(root, "bin");
  const temporary = join(root, "temporary");
  const output = join(root, "diagnostics");
  const trace = join(root, "events.jsonl");
  const release = join(root, "release");
  const summary = join(root, "summary.md");
  const control = join(root, "control");
  const children = [];
  t.after(async () => {
    writeFileSync(release, "release\n");
    for (const { child } of children) {
      if (child.exitCode === null && child.signalCode === null) {
        try { process.kill(-child.pid, "SIGKILL"); } catch (error) { if (error.code !== "ESRCH") throw error; }
      }
    }
    await Promise.all(children.map(({ done }) => done));
    rmSync(root, { recursive: true, force: true });
  });
  for (const path of [bin, temporary, control, join(repo, "scripts"), join(repo, "tests/support"), join(repo, "apps/web")])
    mkdirSync(path, { recursive: true });
  for (const path of ["scripts/test-supabase-local.sh", "scripts/run-integration-group.mjs",
    "scripts/integration-plan.mjs", "tests/support/supabase_fixture_safety.mjs"])
    copyFileSync(new URL("../" + path, import.meta.url), join(repo, path));
  writeFileSync(join(repo, "scripts/lifecycle-fixture.mjs"), fixtureSupport);
  writeFileSync(join(repo, "scripts/prepare-isolated-supabase-workdir.mjs"), String.raw`
import { writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { driftGenerated, event, fault } from './lifecycle-fixture.mjs';
const workdir = process.argv[2];
event('prepare', workdir); // Reading pending.json proves --init preceded acquisition.
driftGenerated();
if (fault === 'prepare-failure') process.exit(19);
writeFileSync(join(workdir, 'prepared'), 'fixture\n');
`);
  writeFileSync(join(repo, "scripts/prepare-rf1086-browser-tail.mjs"), String.raw`
import assert from 'node:assert/strict';
import { changeSource, event, fault, localContext } from './lifecycle-fixture.mjs';
assert.deepEqual(process.argv.slice(2), ['--authority-contract']);
localContext();
assert.equal(event('authority-prerequisites').setup.status, 'success');
if (fault === 'prerequisite-failure') process.exit(41);
if (fault.endsWith('source-change')) changeSource();
`);
  const originals = new Map([
    ["apps/web/next-env.d.ts", Buffer.from("original declaration\r\n")],
    ["apps/web/tsconfig.json", Buffer.from('{"original":true}\n')],
    ["apps/web/AGENTS.md", Buffer.from("Original guide: beholdt\r\n")],
  ]);
  if (existingClaude) originals.set("apps/web/CLAUDE.md", Buffer.from("Original Claude guide\r\n"));
  for (const [path, bytes] of originals) writeFileSync(join(repo, path), bytes);
  writeFileSync(join(repo, "source.txt"), "original source\n");
  writeFileSync(join(bin, "node"), `#!${process.execPath}\n${nodeShim}`);
  chmodSync(join(bin, "node"), 0o755);
  writeFileSync(join(bin, "npm"), `#!${process.execPath}\n${npmShim}`);
  chmodSync(join(bin, "npm"), 0o755);
  const filesystemBinaries = {};
  for (const command of ["mktemp", "cp", "rmdir"]) {
    const located = spawnSync("sh", ["-c", 'command -v "$1"', "fixture", command], { encoding: "utf8" });
    assert.equal(located.status, 0, located.stderr);
    filesystemBinaries[command] = located.stdout.trim();
    writeFileSync(join(bin, command), `#!${process.execPath}\n${filesystemShim}`);
    chmodSync(join(bin, command), 0o755);
  }
  // Defense against accidentally expanding the fixture to a real service call.
  for (const command of ["docker", "supabase", "npx"]) {
    writeFileSync(join(bin, command), "#!/bin/sh\necho 'unexpected external command' >&2\nexit 98\n");
    chmodSync(join(bin, command), 0o755);
  }
  const env = Object.fromEntries(Object.entries(process.env).filter(([name]) =>
    !/^(?:GIT_|GITHUB_|TALLI_|SUPABASE_|NEXT_PUBLIC_SUPABASE_|DATABASE_URL$|NODE_OPTIONS$|BASH_ENV$|ENV$)/u.test(name)));
  Object.assign(env, {
    PATH: `${bin}:${dirname(process.execPath)}:/usr/bin:/bin`, TMPDIR: temporary,
    GIT_CONFIG_NOSYSTEM: "1", GIT_CONFIG_GLOBAL: "/dev/null",
    GIT_AUTHOR_NAME: "Lifecycle fixture", GIT_AUTHOR_EMAIL: "fixture@example.invalid",
    GIT_COMMITTER_NAME: "Lifecycle fixture", GIT_COMMITTER_EMAIL: "fixture@example.invalid",
    CI: "true", GITHUB_RUN_ID: "1234", GITHUB_RUN_ATTEMPT: "2",
    TALLI_CI_OUTPUT_DIR: output, GITHUB_STEP_SUMMARY: summary,
    LIFECYCLE_TRACE: trace, LIFECYCLE_FAULT: fault, LIFECYCLE_RELEASE: release,
    LIFECYCLE_CONTROL: control, LIFECYCLE_FILESYSTEM_BINARIES: JSON.stringify(filesystemBinaries),
    LIFECYCLE_MODE: selection[0] === "--group" ? "group" : "canonical",
  });
  function git(...args) {
    const result = spawnSync("git", args, { cwd: repo, env, encoding: "utf8", timeout: 5000 });
    assert.ifError(result.error);
    assert.equal(result.status, 0, result.stderr);
    return result.stdout.trim();
  }
  git("-c", "init.defaultBranch=fixture", "init", "--quiet");
  git("config", "core.hooksPath", "/dev/null");
  git("add", ".");
  git("commit", "--quiet", "-m", "miniature owned checkout");
  const head = git("rev-parse", "HEAD");
  const tree = git("rev-parse", "HEAD^{tree}");
  env.TALLI_CI_CANDIDATE = head;
  const args = ["scripts/test-supabase-local.sh", ...selection];
  const events = () => existsSync(trace) ? readFileSync(trace, "utf8").trim().split("\n").map(JSON.parse) : [];
  const receipt = () => JSON.parse(readFileSync(join(output, "publish/result.json"), "utf8"));
  const run = (overrides = {}, contenderSelection = selection) => {
    const result = spawnSync("bash", [args[0], ...contenderSelection], {
      cwd: repo, env: { ...env, ...overrides }, encoding: "utf8", timeout: 15000,
    });
    assert.ifError(result.error);
    assert.equal(result.signal, null, result.stdout + result.stderr);
    return result;
  };
  function start() {
    const child = spawn("bash", args, { cwd: repo, env, detached: true, stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "", stderr = "";
    child.stdout.on("data", chunk => { stdout += chunk; });
    child.stderr.on("data", chunk => { stderr += chunk; });
    const done = new Promise((resolve, reject) => {
      child.once("error", reject);
      child.once("close", (status, signal) => resolve({ status, signal, stdout, stderr }));
    });
    children.push({ child, done });
    return { child, done };
  }
  return { root, repo, temporary, output, release, trace, summary, control, env, args,
    originals, head, tree, git, run, start, events, receipt };
}

const names = workspace => workspace.events().map(event => event.name);
const phaseIds = receipt => receipt.phases.map(phase => phase.id);
const allPhases = ["security-initial", "authority-prerequisites", "authority-database", "security-final"];

function assertRestored(workspace) {
  for (const [path, bytes] of workspace.originals) assert.deepEqual(readFileSync(join(workspace.repo, path)), bytes, path);
  if (!workspace.originals.has("apps/web/CLAUDE.md"))
    assert.equal(existsSync(join(workspace.repo, "apps/web/CLAUDE.md")), false);
  assert.equal(existsSync(join(workspace.repo, ".git/talli-integration.lock")), false);
}

function assertReceipt(workspace, { status, command, setup = "success", cleanup = "success", phases = [] }) {
  const receipt = workspace.receipt();
  assert.equal(receipt.status, status);
  assert.equal(receipt.commandExitCode, command);
  assert.equal(receipt.setup.status, setup);
  assert.equal(receipt.cleanup.status, cleanup);
  assert.equal(receipt.cleanupSucceeded, cleanup === "success");
  assert.equal(receipt.head, workspace.head);
  assert.equal(receipt.checkout, workspace.head);
  assert.equal(receipt.tree, workspace.tree);
  assert.equal(receipt.runId, "1234");
  assert.equal(receipt.attempt, 2);
  assert.deepEqual(receipt.expectedPhases, allPhases);
  assert.deepEqual(phaseIds(receipt), phases);
  for (const duration of [receipt.durationMs, receipt.setup.durationMs, receipt.cleanup.durationMs,
    ...receipt.phases.map(phase => phase.durationMs)]) assert.ok(Number.isInteger(duration) && duration >= 0);
  assert.ok(workspace.events().every(event => event.published === false), "receipt must wait for owned cleanup");
  assert.equal(readFileSync(workspace.summary, "utf8"), readFileSync(join(workspace.output, "publish/timings.md"), "utf8"));
  assert.match(readFileSync(workspace.summary, "utf8"), new RegExp(`Result: ${status};`));
  const stops = workspace.events().filter(event => event.name === "stop");
  assert.ok(stops.length <= 1, "stop only the owned stack, exactly once");
  for (const stop of stops) {
    assert.ok(Number.isInteger(stop.cleanup.startedMs));
    assert.equal(stop.workdir, workspace.events().find(event => event.name === "prepare").workdir);
  }
  return receipt;
}

async function waitFor(workspace, eventName) {
  const deadline = Date.now() + 5000;
  while (!names(workspace).includes(eventName)) {
    assert.ok(Date.now() < deadline, `missing ${eventName}: ${names(workspace)}`);
    await delay(10);
  }
}

test("owned group completes real receipt lifecycle and restores generated files", t => {
  const workspace = fixture(t);
  const result = workspace.run();
  assert.equal(result.status, 0, result.stdout + result.stderr);
  assert.deepEqual(names(workspace), ["prepare", "start", "status", "test:supabase-advisors",
    "authority-prerequisites", "test:authority-connections-database", "test:supabase-advisors", "stop"]);
  const receipt = assertReceipt(workspace, { status: "success", command: 0, phases: allPhases });
  assert.equal(receipt.finished, true);
  assert.equal(receipt.sourceClean, true);
  assert.ok(receipt.phases.every(phase => phase.exitCode === 0));
  assertRestored(workspace);
  assert.deepEqual(readdirSync(workspace.temporary), []);
  assert.equal(workspace.git("status", "--porcelain"), "");
});

test("partial start failure still stops the owned stack and publishes a failure receipt", t => {
  const workspace = fixture(t, "start-failure");
  assert.equal(workspace.run().status, 23);
  assert.deepEqual(names(workspace), ["prepare", "start", "stop"]);
  assertReceipt(workspace, { status: "failure", command: 23, setup: "failure" });
  assertRestored(workspace);
  assert.deepEqual(readdirSync(workspace.temporary), []);
});

test("default receipt directory is initialized before acquisition without reserving a stack workdir", t => {
  const workspace = fixture(t, "mktemp-failure-1");
  const result = workspace.run({ TALLI_CI_OUTPUT_DIR: "" });
  assert.equal(result.status, 43, result.stdout + result.stderr);
  const retained = readdirSync(workspace.temporary);
  assert.equal(retained.length, 1, "only the deliberate diagnostics directory remains");
  assert.match(retained[0], /^talli-integration-.*-diagnostics$/u);
  const receipt = JSON.parse(readFileSync(join(workspace.temporary, retained[0], "publish/result.json"), "utf8"));
  assert.equal(receipt.status, "failure");
  assert.equal(receipt.setup.status, "failure");
  assert.equal(receipt.commandExitCode, 43);
  assert.equal(receipt.cleanupSucceeded, true);
  assertRestored(workspace);
});

for (const fault of ["prepare-failure", "status-failure"]) {
  test(`${fault} publishes a setup failure receipt without running phases`, t => {
    const workspace = fixture(t, fault);
    const result = workspace.run();
    assert.notEqual(result.status, 0);
    if (fault === "prepare-failure") assert.equal(result.status, 19);
    assert.deepEqual(names(workspace), fault === "prepare-failure" ? ["prepare"] : ["prepare", "start", "status", "stop"]);
    assertReceipt(workspace, { status: "failure", command: result.status, setup: "failure" });
    assertRestored(workspace);
    assert.deepEqual(readdirSync(workspace.temporary), []);
  });
}

for (const [command, count] of [
  ["mktemp", 1], ["mktemp", 2], ["mktemp", 3], ["mktemp", 4], ["mktemp", 5],
  ["cp", 1], ["cp", 2], ["cp", 3], ["cp", 4],
]) {
  test(`early ${command} failure ${count} removes partial acquisitions without overwriting originals`, t => {
    const workspace = fixture(t, `${command}-failure-${count}`, undefined, { existingClaude: true });
    const result = workspace.run();
    const code = command === "mktemp" ? 43 : 45;
    assert.equal(result.status, code, result.stdout + result.stderr);
    assertReceipt(workspace, { status: "failure", command: code, setup: "failure" });
    assert.deepEqual(names(workspace), [], "no stack preparation or phases after failed acquisition");
    assertRestored(workspace);
    assert.deepEqual(readdirSync(workspace.temporary), [], "no private workdir or partial snapshot may leak");
    assert.equal(workspace.git("status", "--porcelain"), "");
    const operations = readFileSync(join(workspace.control, "filesystem.jsonl"), "utf8").trim().split("\n").map(JSON.parse);
    assert.ok(operations.every(operation => operation.initialized && operation.locked),
      "receipt and cleanup ownership must precede every acquisition");
  });
}

test("unlock failure rewrites an otherwise successful receipt as failed cleanup", t => {
  const workspace = fixture(t, "unlock-failure");
  const result = workspace.run();
  assert.notEqual(result.status, 0, result.stdout + result.stderr);
  const receipt = workspace.receipt();
  assert.equal(receipt.status, "failure");
  assert.equal(receipt.cleanupSucceeded, false);
  assert.equal(receipt.cleanup.status, "failure");
  assert.equal(receipt.commandExitCode, 0);
  assert.equal(receipt.finished, true);
  assert.deepEqual(phaseIds(receipt), allPhases);
  assert.equal(existsSync(join(workspace.repo, ".git/talli-integration.lock")), true);
  assert.deepEqual(readFileSync(join(workspace.control, "finalizations.jsonl"), "utf8").trim().split("\n").map(JSON.parse),
    [["0", "0"], ["0", "1"]]);
  assert.match(readFileSync(join(workspace.output, "publish/timings.md"), "utf8"), /Result: failure; owned cleanup: FAILED/u);
});

for (const [fault, code, phases] of [
  ["prerequisite-failure", 41, allPhases.slice(0, 2)],
  ["phase-failure", 37, allPhases.slice(0, 3)],
  ["phase-failure-stop-failure", 37, allPhases.slice(0, 3)],
]) {
  test(`${fault} stops later phases, cleans up and preserves the command failure`, t => {
    const workspace = fixture(t, fault);
    assert.equal(workspace.run().status, code);
    const cleanup = fault.includes("stop-failure") ? "failure" : "success";
    const receipt = assertReceipt(workspace, { status: "failure", command: code, cleanup, phases });
    assert.equal(receipt.finished, false);
    assert.equal(receipt.phases.at(-1).exitCode, code);
    assert.equal(names(workspace).filter(name => name === "test:supabase-advisors").length, 1, "final advisor phase must not run");
    assert.equal(names(workspace).at(-1), "stop");
    assertRestored(workspace);
    assert.equal(existsSync(workspace.events().find(event => event.name === "start").workdir), cleanup === "failure");
  });
}

for (const fault of ["stop-failure", "restore-failure"]) {
  test(`${fault} retains the owned workdir and rejects otherwise successful phases`, t => {
    const workspace = fixture(t, fault);
    const result = workspace.run();
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /Owned cleanup incomplete; workdir preserved/u);
    const receipt = assertReceipt(workspace, { status: "failure", command: 0, cleanup: "failure", phases: allPhases });
    assert.equal(receipt.finished, true);
    const workdir = workspace.events().find(event => event.name === "start").workdir;
    assert.equal(readFileSync(join(workdir, "partially-started"), "utf8"), "owned stack\n");
    assert.equal(names(workspace).at(-1), "stop", "restoration failure must not skip stack cleanup");
    assert.equal(existsSync(join(workspace.repo, ".git/talli-integration.lock")), false);
    if (fault === "stop-failure") assertRestored(workspace);
    else {
      const snapshots = readdirSync(workspace.temporary).filter(name => !name.startsWith("talli-supabase-local."))
        .map(name => readFileSync(join(workspace.temporary, name), "utf8")).sort();
      assert.deepEqual(snapshots, [...workspace.originals.values()].map(bytes => bytes.toString("utf8")).sort(),
        "failed restoration preserves original recovery bytes");
    }
  });
}

for (const [signal, code] of [["SIGTERM", 143], ["SIGINT", 130]]) {
  test(`${signal} during an owned test phase runs cleanup and finalizes cancellation`, { timeout: 15000 }, async t => {
    const workspace = fixture(t, "hold-phase");
    const { child, done } = workspace.start();
    await waitFor(workspace, "held:phase");
    // Signal the whole owned process group, as CI cancellation does. This also
    // terminates the synchronous runner's child rather than orphaning it.
    process.kill(-child.pid, signal);
    const result = await done;
    assert.equal(result.signal, null, result.stderr);
    assert.equal(result.status, code, result.stdout + result.stderr);
    const receipt = workspace.receipt();
    assertReceipt(workspace, { status: "failure", command: code, phases: phaseIds(receipt) });
    assert.equal(receipt.finished, false);
    assert.ok(!phaseIds(receipt).includes("security-final"));
    assert.equal(names(workspace).at(-1), "stop");
    assertRestored(workspace);
    assert.deepEqual(readdirSync(workspace.temporary), []);
  });
}

test("hard cancellation cannot leave a success receipt when cleanup cannot run", { timeout: 15000 }, async t => {
  const workspace = fixture(t, "hold-phase");
  const { child, done } = workspace.start();
  await waitFor(workspace, "held:phase");
  process.kill(-child.pid, "SIGKILL");
  const result = await done;
  assert.equal(result.signal, "SIGKILL");
  assert.notEqual(result.status, 0);
  assert.equal(existsSync(join(workspace.output, "publish/result.json")), false,
    "an interrupted run with no final receipt is not release evidence");
  const pending = JSON.parse(readFileSync(join(workspace.output, "pending.json"), "utf8"));
  assert.equal(pending.finished, false);
  assert.ok(!phaseIds(pending).includes("security-final"));
  assert.ok(!names(workspace).includes("stop"), "SIGKILL cannot promise graceful cleanup");
  assert.equal(existsSync(workspace.events().find(event => event.name === "start").workdir), true);
});

test("same-checkout lock refuses a concurrent group before touching generated files or snapshots", { timeout: 15000 }, async t => {
  const workspace = fixture(t, "hold-start");
  const { done } = workspace.start();
  await waitFor(workspace, "held:start");
  const generated = new Map(["next-env.d.ts", "tsconfig.json", "AGENTS.md", "CLAUDE.md"]
    .map(name => [name, readFileSync(join(workspace.repo, "apps/web", name))]));
  const before = readdirSync(workspace.temporary).sort();
  const pending = readFileSync(join(workspace.output, "pending.json"));
  const trace = readFileSync(workspace.trace);
  const contenderOutput = join(workspace.root, "contender-diagnostics");
  for (const selection of [["--group", "authority"], [], ["--rf10-diagnostic"], ["--rf10-fast-diagnostic"]]) {
    const result = workspace.run({ TALLI_CI_OUTPUT_DIR: contenderOutput }, selection);
    assert.equal(result.status, 2, result.stderr);
    assert.match(result.stderr, /already owns this checkout/u);
  }
  assert.equal(existsSync(contenderOutput), false);
  assert.equal(existsSync(join(workspace.repo, ".git/talli-integration.lock")), true);
  assert.deepEqual(readFileSync(workspace.trace), trace, "contender must not acquire or stop the owner's stack");
  assert.deepEqual(readFileSync(join(workspace.output, "pending.json")), pending);
  assert.deepEqual(readdirSync(workspace.temporary).sort(), before);
  for (const [name, bytes] of generated) assert.deepEqual(readFileSync(join(workspace.repo, "apps/web", name)), bytes);
  writeFileSync(workspace.release, "release\n");
  const owner = await done;
  assert.equal(owner.status, 0, owner.stdout + owner.stderr);
  assertReceipt(workspace, { status: "success", command: 0, phases: allPhases });
  assertRestored(workspace);
  assert.deepEqual(readdirSync(workspace.temporary), []);
});

for (const selection of [[], ["--rf10-diagnostic"], ["--rf10-fast-diagnostic"]]) {
  test(`${selection[0] ?? "canonical"} holds the checkout lock against a group`, { timeout: 15000 }, async t => {
    const workspace = fixture(t, "hold-start", selection);
    const { child, done } = workspace.start();
    await waitFor(workspace, "held:start");
    const before = readFileSync(workspace.trace);
    const result = workspace.run({}, ["--group", "authority"]);
    assert.equal(result.status, 2, result.stderr);
    assert.match(result.stderr, /already owns this checkout/u);
    assert.deepEqual(readFileSync(workspace.trace), before);
    process.kill(-child.pid, "SIGTERM");
    const owner = await done;
    assert.equal(owner.status, 143, owner.stdout + owner.stderr);
    assert.equal(names(workspace).at(-1), "stop");
    assertRestored(workspace);
    assert.deepEqual(readdirSync(workspace.temporary), []);
    assert.equal(existsSync(workspace.output), false, "canonical and RF diagnostics do not become group receipts");
  });
}

for (const fault of ["initially-dirty", "dirty-source-change", "committed-source-change"]) {
  test(`${fault} cannot publish release success even when every phase passes`, t => {
    const workspace = fixture(t, fault);
    if (fault === "initially-dirty") writeFileSync(join(workspace.repo, "source.txt"), "pre-existing user change\n");
    const result = workspace.run();
    const receipt = workspace.receipt();
    assertRestored(workspace);
    assert.equal(receipt.finished, true);
    assert.deepEqual(phaseIds(receipt), allPhases);
    assert.equal(receipt.cleanupSucceeded, true);
    assert.ok(receipt.phases.every(phase => phase.exitCode === 0));
    assert.notEqual(receipt.status, "success", "a changed source binding must never become release evidence");
    assert.notEqual(result.status, 0, "CI must reject the source change after cleanup");
    if (fault === "committed-source-change") {
      assert.notEqual(workspace.git("rev-parse", "HEAD"), workspace.head);
      assert.equal(workspace.git("status", "--porcelain"), "", "a clean new commit still changes the source binding");
    } else {
      assert.equal(receipt.sourceClean, false);
      assert.match(readFileSync(join(workspace.repo, "source.txt"), "utf8"), /change/u);
    }
  });
}
