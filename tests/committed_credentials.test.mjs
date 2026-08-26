import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  mkdirSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const scanner = join(root, "scripts/check-committed-credentials.mjs");
const runScanner = (repository) => spawnSync(
  process.execPath,
  [scanner, repository],
  { encoding: "utf8" },
);

test("the credential scanner scans its own clean repository without matching itself", () => {
  const result = runScanner(root);
  assert.equal(result.status, 0, result.stdout || result.stderr);
});

test("the credential scanner rejects a tracked source credential", () => {
  const repository = mkdtempSync(join(tmpdir(), "talli-credential-scan-"));
  const source = join(repository, "src/config.js");
  mkdirSync(dirname(source), { recursive: true });

  try {
    assert.equal(spawnSync("git", ["init", "-q", repository]).status, 0);
    writeFileSync(source, "export const configured = false;\n");
    assert.equal(spawnSync("git", ["-C", repository, "add", "."]).status, 0);
    assert.equal(runScanner(repository).status, 0);

    writeFileSync(source, "export const credential = '-----BEGIN PRIVATE KEY-----';\n");
    assert.equal(spawnSync("git", ["-C", repository, "add", "."]).status, 0);
    const result = runScanner(repository);
    assert.equal(result.status, 1);
    assert.match(result.stdout, /src\/config\.js/u);
  } finally {
    rmSync(repository, { recursive: true, force: true });
  }
});
