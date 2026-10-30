import { spawnSync } from "node:child_process";
import { readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const directory = fileURLToPath(new URL("../tests/", import.meta.url));
const scripts = readdirSync(directory, { withFileTypes: true })
  .filter(entry => entry.isFile() && /^browser_.*\.mjs$/u.test(entry.name))
  .map(entry => entry.name)
  .sort();
if (scripts.length === 0) throw new Error("No browser rehearsal entrypoints found.");

for (const name of scripts) {
  const result = spawnSync(process.execPath, ["--check", join(directory, name)], {
    stdio: "inherit", timeout: 10_000,
  });
  if (result.error || result.status !== 0) process.exit(result.status || 1);
}
console.log(JSON.stringify({ status: "pass", browserEntrypointsChecked: scripts.length }));
