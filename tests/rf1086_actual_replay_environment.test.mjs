import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import { actualReplayEnvironment } from "./support/rf1086-actual-replay-environment.mjs";

const environment = {
  TALLI_RF_REPLAY_DIR: "/fixture/replay", RUNNER_TEMP: "/fixture",
  PRIVATE_CANARY: "must-not-forward",
};

test("replay environment is opt-in and forwards only its three fields", () => {
  assert.deepEqual(actualReplayEnvironment(1, 2, {}), {});
  assert.deepEqual(actualReplayEnvironment(1000, 2000, environment), {
    TALLI_RF_REPLAY_DIR: "/fixture/replay", RUNNER_TEMP: "/fixture", TALLI_RF_REPLAY_EXPORT_MS: "150000",
  });
});

test("replay allowance reserves owning-test cleanup at the actual child launch", () => {
  assert.equal(actualReplayEnvironment(1000, 171000.9, environment).TALLI_RF_REPLAY_EXPORT_MS, "129999");
  assert.equal(actualReplayEnvironment(1000, 400000, environment).TALLI_RF_REPLAY_EXPORT_MS, "0");
  for (const [started, now] of [[undefined, 1], [NaN, 1], [1, Infinity], [-1, 1], [2, 1]]) {
    assert.equal(actualReplayEnvironment(started, now, environment).TALLI_RF_REPLAY_EXPORT_MS, "0");
  }
});

test("the first company-retention child receives replay settings at its launch", () => {
  const source = readFileSync(new URL("./fixtures/rf1086-company-test-retention-browser-journey.mjs", import.meta.url), "utf8");
  const start = source.indexOf("JSON.parse(execFileSync(");
  const end = source.indexOf("}));", start) + 3;
  assert.ok(start >= 0 && end > start);
  let captured;
  let clockReads = 0;
  // Exercise the actual child-call expression without browser/database side effects.
  vm.runInNewContext(source.slice(start, end), {
    python: "fixture-python", company: { id: "synthetic" }, streamPath: "fixture-stream", expectation: "fixture-expectation",
    process: { cwd: () => "." }, environment: { GITHUB_RUN_ID: "123" },
    sourceDatabaseUrl: "fixture-source", readerDatabaseUrl: "fixture-reader", supabaseUrl: "fixture-url",
    anonKey: "fixture-anon", ownerToken: "fixture-owner", outsiderToken: "fixture-outsider", replayTestStarted: 1000,
    actualReplayEnvironment: started => { clockReads += 1; return actualReplayEnvironment(started, 171000, environment); },
    execFileSync: (binary, args, options) => { captured = { binary, args, options }; return "{}"; },
  });
  assert.equal(clockReads, 1);
  assert.equal(captured.args[0], "scripts/rehearse-rf1086-company-test-retention-restore.py");
  assert.equal(captured.options.env.TALLI_RF_REPLAY_DIR, environment.TALLI_RF_REPLAY_DIR);
  assert.equal(captured.options.env.RUNNER_TEMP, environment.RUNNER_TEMP);
  assert.equal(captured.options.env.TALLI_RF_REPLAY_EXPORT_MS, "130000");
  assert.equal(captured.options.env.GITHUB_RUN_ID, "123");
  assert.equal(captured.options.env.PRIVATE_CANARY, undefined);
  assert.equal(captured.options.timeout, 180_000);
  assert.equal(captured.options.killSignal, "SIGTERM");
  const browser = readFileSync(new URL("./browser_shareholder_register_filing.mjs", import.meta.url), "utf8");
  const caller = browser.slice(browser.indexOf("await exerciseCompanyTestRetention("), browser.indexOf("const sourceYear ="));
  assert.match(caller, /python, replayTestStarted, environment:/);
  assert.match(browser, /\.\.\.actualReplayEnvironment\(replayTestStarted\)/);
});
