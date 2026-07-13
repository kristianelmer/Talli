import assert from "node:assert/strict";
import { readdir, stat } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

const root = process.cwd();
const standaloneRoot = path.join(root, ".next", "standalone");

async function filesBelow(directory, relativeTo = directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = await Promise.all(entries.map(async (entry) => {
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) return filesBelow(absolute, relativeTo);
    return [path.relative(relativeTo, absolute)];
  }));
  return files.flat();
}

test("standalone artifact includes the web and RF-1086 runtimes without local secrets", async () => {
  assert.equal((await stat(path.join(standaloneRoot, "server.js"))).isFile(), true);
  assert.equal((await stat(path.join(standaloneRoot, "holding_cli", "main.py"))).isFile(), true);
  assert.equal((await stat(path.join(standaloneRoot, "holding_core", "rf1086.py"))).isFile(), true);
  assert.equal(
    (await stat(path.join(standaloneRoot, "docs", "filing", "aksjonaerregisteroppgaveHovedskjema.xsd"))).isFile(),
    true,
  );

  const files = await filesBelow(standaloneRoot);
  const forbidden = files.filter((file) => (
    /(^|\/)\.env(?:\.|$)/u.test(file)
    || file === "next.config.ts"
    || file.startsWith("tests/")
    || file.endsWith(".pyc")
    || file.includes("/__pycache__/")
    || (file.startsWith("docs/") && file.endsWith(".md"))
  ));

  assert.deepEqual(forbidden, []);
});
