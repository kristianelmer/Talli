import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const workflowPath = new URL("../.github/workflows/release-gate.yml", import.meta.url);

test("release gate covers pull requests and main with least privilege", () => {
  const workflow = readFileSync(workflowPath, "utf8");

  assert.match(workflow, /^name: Customer-ready release gate$/m);
  assert.match(workflow, /pull_request:/);
  assert.match(workflow, /push:\n\s+branches:\s+\[main\]/);
  assert.match(workflow, /permissions:\n\s+contents: read/);
  assert.match(workflow, /concurrency:/);
  assert.doesNotMatch(workflow, /pull_request_target:/);
  assert.doesNotMatch(workflow, /permissions:\s+write-all/);
});

test("release gate runs every customer-readiness check before promotion", () => {
  const workflow = readFileSync(workflowPath, "utf8");

  for (const required of [
    "npm ci",
    "python -m pip install uv==0.10.2",
    "uv sync --locked",
    "npm run typecheck",
    "npm run test:launch-rehearsal",
    "npm run test:supabase:local",
    "npm run build",
    "npm audit --omit=dev --audit-level=high",
    "git diff --check",
    "TALLI_SKATTE_XSD_DIR",
    "Skatteetaten/skattemeldingen",
    "v1.62.47",
    "Release gate",
  ]) {
    assert.ok(workflow.includes(required), `missing required release check: ${required}`);
  }

  assert.match(workflow, /uses: actions\/checkout@[0-9a-f]{40}/);
  assert.match(workflow, /uses: actions\/setup-node@[0-9a-f]{40}/);
  assert.match(workflow, /uses: actions\/setup-python@[0-9a-f]{40}/);
  assert.match(workflow, /TALLI_PYTHON_BIN:\s+\.venv\/bin\/python/);
  assert.match(workflow, /timeout-minutes:/);
});
