import assert from "node:assert/strict";
import { copyFile, mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";

const launcherSource = new URL("../apps/web/scripts/run-next.mjs", import.meta.url);

test("web launcher uses the repository-root Next installation", async (t) => {
  const fixtureRoot = await mkdtemp(join(tmpdir(), "talli-next-launcher-"));
  t.after(() => rm(fixtureRoot, { force: true, recursive: true }));

  await mkdir(join(fixtureRoot, "apps/web/scripts"), { recursive: true });
  await mkdir(join(fixtureRoot, "node_modules/next/dist/bin"), { recursive: true });
  await copyFile(launcherSource, join(fixtureRoot, "apps/web/scripts/run-next.mjs"));
  await writeFile(join(fixtureRoot, "package.json"), "{}\n");
  await writeFile(
    join(fixtureRoot, "node_modules/next/dist/bin/next"),
    'console.log(`next ${process.argv.slice(2).join(" ")}`);\n',
  );

  const result = spawnSync(
    process.execPath,
    ["apps/web/scripts/run-next.mjs", "build"],
    { cwd: fixtureRoot, encoding: "utf8" },
  );

  assert.equal(result.status, 0, `${result.stdout}${result.stderr}`);
  assert.equal(result.stdout.trim(), "next build apps/web");
});
