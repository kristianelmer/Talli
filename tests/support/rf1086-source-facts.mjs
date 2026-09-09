import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../../", import.meta.url));

// Test-only composition: production web requests use the generated HTTP client.
export function renderRf1086SourceFacts(company, opening, shareholders) {
  const python = process.env.TALLI_PYTHON_BIN || `${root}apps/backend/.venv/bin/python`;
  const result = spawnSync(python, ["tests/fixtures/render_rf1086_source_facts.py"], {
    cwd: root,
    input: JSON.stringify({ company, opening, shareholders }),
    encoding: "utf8",
    timeout: 30_000,
    maxBuffer: 4 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`Canonical RF renderer failed: ${result.stderr}`);
  return JSON.parse(result.stdout);
}
