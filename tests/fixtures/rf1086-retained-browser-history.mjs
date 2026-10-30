import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";

const verifier = fileURLToPath(new URL("../support/rf1086_retained_browser_history.py", import.meta.url));

// A fixture observer only: the real V6 download and shipped strict parser own
// validation. Never fall back to the closed V4 source/approval allowlists.
export async function loadRetainedBrowserHistory(api, companyId, incomeYear, options, python, environment) {
  const deadline = new AbortController();
  const timer = setTimeout(() => deadline.abort(new Error("rf1086_retained_history_deadline")), 30_000);
  const signal = options?.signal ? AbortSignal.any([deadline.signal, options.signal]) : deadline.signal;
  let child, done, closed;
  try {
    const response = await api.rf1086DownloadProductionArchiveV6(companyId, incomeYear, { ...options, signal });
    const env = Object.fromEntries(["PATH", "LANG", "LC_ALL", "TZ", "PYTHONPATH"]
      .filter(key => environment[key] !== undefined).map(key => [key, environment[key]]));
    child = spawn(python, [verifier, companyId, String(incomeYear)], {
      env: { ...env, PYTHONDONTWRITEBYTECODE: "1" }, stdio: ["pipe", "pipe", "pipe"], signal, killSignal: "SIGKILL",
    });
    // Abort's error event can precede close. Keep reaping separate from the
    // rejecting operation promise so cleanup cannot return on that early error.
    closed = new Promise(resolve => child.once("close", resolve));
    let bytes = 0;
    const chunks = [];
    child.stdout.on("data", chunk => {
      bytes += chunk.length;
      if (bytes > 16 * 1024 * 1024) deadline.abort(new Error("rf1086_retained_history_observer_limit"));
      else chunks.push(chunk);
    });
    child.stderr.resume(); // Never persist an original or credential through diagnostics.
    done = new Promise((resolve, reject) => {
      child.once("error", reject);
      child.once("close", code => code === 0 ? resolve() : reject(new Error("rf1086_retained_history_invalid")));
    });
    await Promise.all([done, pipeline(Readable.fromWeb(response.body), child.stdin, { signal })]);
    const result = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    assert.equal(result.schema, "rf1086-retained-browser-history-v1");
    assert.equal(result.companyId, companyId);
    assert.equal(result.incomeYear, incomeYear);
    return result;
  } finally {
    clearTimeout(timer);
    if (child && child.exitCode === null && child.signalCode === null) {
      deadline.abort();
      child.kill("SIGKILL");
    }
    await closed;
  }
}
