import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const workflowPath = new URL("../.github/workflows/release-gate.yml", import.meta.url);
const vercelConfigPath = new URL("../vercel.json", import.meta.url);

test("release gate covers pull requests and main with least privilege", () => {
  const workflow = readFileSync(workflowPath, "utf8");

  assert.match(workflow, /^name: Customer-ready release gate$/m);
  assert.match(workflow, /pull_request:/);
  assert.match(workflow, /push:\n\s+branches:\s+\[main\]/);
  assert.match(workflow, /permissions:\n\s+contents: read/);
  assert.match(workflow, /concurrency:/);
  assert.doesNotMatch(workflow, /pull_request_target:/);
  assert.doesNotMatch(workflow, /permissions:\s+write-all/);
  assert.doesNotMatch(
    workflow,
    /(BEGIN (RSA |EC )?PRIVATE KEY|go-keyring-base64:|eyJhbGciOi[A-Za-z0-9_-]+\.)/,
    "the scanner must not trigger on its own workflow source",
  );
});

test("release gate runs every customer-readiness check before promotion", () => {
  const workflow = readFileSync(workflowPath, "utf8");

  for (const required of [
    "npm ci",
    "python -m pip install uv==0.10.2",
    "uv sync --locked",
    "uv sync --project apps/backend --locked",
    "npx playwright install --with-deps chromium",
    "npm run typecheck",
    "npm run check:architecture",
    "npm run test:boundary",
    "npm run test:boundary-smoke",
    "npm run test:launch-rehearsal",
    "npm run test:supabase:local",
    "npm run build:web",
    "npm run build:backend",
    "npm audit --omit=dev --audit-level=high",
    "git diff --check",
    "TALLI_SKATTE_XSD_DIR",
    "Skatteetaten/skattemeldingen",
    "v1.62.47",
    "Release gate",
  ]) {
    assert.ok(workflow.includes(required), `missing required release check: ${required}`);
  }
  assert.doesNotMatch(
    workflow,
    /npm ci --prefix apps\/web/,
    "the root workspace install must remain the sole application install",
  );

  assert.match(workflow, /uses: actions\/checkout@[0-9a-f]{40}/);
  assert.match(workflow, /fetch-depth:\s+0/, "release verification needs complete tags and history");
  assert.match(workflow, /uses: actions\/setup-node@[0-9a-f]{40}/);
  assert.match(workflow, /uses: actions\/setup-python@[0-9a-f]{40}/);
  assert.match(workflow, /TALLI_PYTHON_BIN:\s+\.venv\/bin\/python/);
  assert.match(workflow, /timeout-minutes:/);
  assert.ok(
    workflow.indexOf("npm run build:backend") <
      workflow.indexOf("npm run test:boundary-smoke"),
    "backend artifact must be built before the production smoke",
  );
  assert.ok(
    workflow.indexOf("npm run build:web") <
      workflow.indexOf("npm run test:boundary-smoke"),
    "web artifact must be built before the production smoke",
  );
});

test("database isolation uses the locked Python renderer environment", () => {
  const workflow = readFileSync(workflowPath, "utf8");
  const databaseJob = workflow.match(/\n  database:[\s\S]*?\n  release-gate:/)?.[0] ?? "";

  assert.match(databaseJob, /uses: actions\/setup-python@[0-9a-f]{40}/);
  assert.ok(databaseJob.includes("python -m pip install uv==0.10.2"));
  assert.ok(databaseJob.includes("uv sync --locked"));
  assert.match(databaseJob, /TALLI_PYTHON_BIN:\s+\.venv\/bin\/python/);
  assert.ok(databaseJob.includes("npx playwright install --with-deps chromium"));
});

test("browser owner rehearsal owns and terminates the Next.js process directly", () => {
  const harness = readFileSync(
    new URL("browser_owner_annual_loop.mjs", import.meta.url),
    "utf8",
  );

  assert.doesNotMatch(harness, /spawn\("npm"/);
  assert.match(harness, /node_modules\/next\/dist\/bin\/next/);
  assert.match(harness, /await stopServer\(server\)/);
  assert.match(harness, /server\.kill\("SIGKILL"\)/);
});

test("Vercel deploys the Next output produced by the root build", () => {
  const config = JSON.parse(readFileSync(vercelConfigPath, "utf8"));

  assert.deepEqual(config, { outputDirectory: "apps/web/.next" });
});
