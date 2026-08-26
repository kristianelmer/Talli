import assert from "node:assert/strict";
import {
  chmodSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";

const workflowPath = new URL(
  "../.github/workflows/release-gate.yml",
  import.meta.url,
);
const vercelConfigPath = new URL("../vercel.json", import.meta.url);
const localGatePath = new URL(
  "../scripts/run-customer-ready-gate.mjs",
  import.meta.url,
);
const databaseHarnessPath = new URL(
  "../scripts/test-supabase-local.sh",
  import.meta.url,
);
const cleanWorktreePath = fileURLToPath(
  new URL("../scripts/check-clean-worktree.sh", import.meta.url),
);

function run(command, args, options = {}) {
  return spawnSync(command, args, {
    encoding: "utf8",
    ...options,
  });
}

function initializeTemporaryRepository() {
  const directory = mkdtempSync(join(tmpdir(), "talli-clean-worktree-test-"));
  writeFileSync(join(directory, "tracked.txt"), "original\n");
  for (const args of [
    ["init", "--quiet"],
    ["config", "user.name", "Talli Test"],
    ["config", "user.email", "test@invalid.example"],
    ["add", "tracked.txt"],
    ["commit", "--quiet", "-m", "fixture"],
  ]) {
    const result = run("git", args, { cwd: directory });
    assert.equal(result.status, 0, result.stderr);
  }
  return directory;
}

function createHarnessWorkspace(mode) {
  const directory = mkdtempSync(join(tmpdir(), "talli-database-harness-test-"));
  const nextEnvPath = join(directory, "apps/web/next-env.d.ts");
  const binDirectory = join(directory, "bin");
  const snapshotDirectory = join(directory, "snapshots");
  mkdirSync(dirname(nextEnvPath), { recursive: true });
  mkdirSync(binDirectory);
  mkdirSync(snapshotDirectory);
  writeFileSync(nextEnvPath, "original declaration\n");
  const npmPath = join(binDirectory, "npm");
  writeFileSync(
    npmPath,
    `#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == "exec -- supabase status --output env" ]]; then
  printf '%s\\n' 'API_URL=http://127.0.0.1:54321' 'ANON_KEY=local-anon' 'SERVICE_ROLE_KEY=local-service' 'DB_URL=postgresql://127.0.0.1/local'
  exit 0
fi
if [[ "$*" == "run test:browser-owner" ]]; then
  printf 'generated declaration\\n' > apps/web/next-env.d.ts
  if [[ "${mode}" == "command-failure" ]]; then
    exit 7
  fi
  if [[ "${mode}" == "restore-failure" ]]; then
    mv apps/web apps/web-displaced
  fi
fi
`,
  );
  chmodSync(npmPath, 0o755);
  return { directory, nextEnvPath, snapshotDirectory, binDirectory };
}

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
    assert.ok(
      workflow.includes(required),
      `missing required release check: ${required}`,
    );
  }
  assert.doesNotMatch(
    workflow,
    /npm ci --prefix apps\/web/,
    "the root workspace install must remain the sole application install",
  );

  assert.match(workflow, /uses: actions\/checkout@[0-9a-f]{40}/);
  assert.match(
    workflow,
    /fetch-depth:\s+0/,
    "release verification needs complete tags and history",
  );
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
  const databaseJob =
    workflow.match(/\n  database:[\s\S]*?\n  release-gate:/)?.[0] ?? "";

  assert.match(databaseJob, /uses: actions\/setup-python@[0-9a-f]{40}/);
  assert.ok(databaseJob.includes("python -m pip install uv==0.10.2"));
  assert.ok(databaseJob.includes("uv sync --locked"));
  assert.ok(databaseJob.includes("uv sync --project apps/backend --locked"));
  assert.match(databaseJob, /TALLI_PYTHON_BIN:\s+\.venv\/bin\/python/);
  assert.ok(
    databaseJob.includes("npx playwright install --with-deps chromium"),
  );
});

test("local immutable gate rejects tracked, staged, and untracked drift", () => {
  const localGate = readFileSync(localGatePath, "utf8");
  assert.match(localGate, /scripts\/check-clean-worktree\.sh/u);

  for (const scenario of ["clean", "tracked", "staged", "untracked"]) {
    const directory = initializeTemporaryRepository();
    try {
      if (scenario === "tracked" || scenario === "staged") {
        writeFileSync(join(directory, "tracked.txt"), "changed\n");
      }
      if (scenario === "staged") {
        const staged = run("git", ["add", "tracked.txt"], { cwd: directory });
        assert.equal(staged.status, 0, staged.stderr);
      }
      if (scenario === "untracked") {
        writeFileSync(join(directory, "untracked.txt"), "unexpected\n");
      }

      const result = run("bash", [cleanWorktreePath], { cwd: directory });
      assert.equal(
        result.status === 0,
        scenario === "clean",
        `${scenario}: ${result.stdout}${result.stderr}`,
      );
    } finally {
      rmSync(directory, { recursive: true, force: true });
    }
  }
});

test("database harness restores generated drift and preserves failure semantics", () => {
  for (const mode of ["success", "command-failure", "restore-failure"]) {
    const workspace = createHarnessWorkspace(mode);
    try {
      const result = run("bash", [fileURLToPath(databaseHarnessPath)], {
        cwd: workspace.directory,
        env: {
          ...process.env,
          PATH: `${workspace.binDirectory}:${process.env.PATH}`,
          TMPDIR: workspace.snapshotDirectory,
        },
      });

      if (mode === "success") {
        assert.equal(result.status, 0, result.stderr);
        assert.equal(readFileSync(workspace.nextEnvPath, "utf8"), "original declaration\n");
        assert.deepEqual(readdirSync(workspace.snapshotDirectory), []);
      } else if (mode === "command-failure") {
        assert.equal(result.status, 7, result.stderr);
        assert.equal(readFileSync(workspace.nextEnvPath, "utf8"), "original declaration\n");
        assert.deepEqual(readdirSync(workspace.snapshotDirectory), []);
      } else {
        assert.notEqual(result.status, 0);
        assert.equal(readdirSync(workspace.snapshotDirectory).length, 1);
      }
    } finally {
      rmSync(workspace.directory, { recursive: true, force: true });
    }
  }
});

test("browser owner rehearsal includes executable owned-process lifecycle coverage", () => {
  const harness = readFileSync(
    new URL("browser_owner_annual_loop.mjs", import.meta.url),
    "utf8",
  );
  const packageJson = JSON.parse(
    readFileSync(new URL("../package.json", import.meta.url), "utf8"),
  );

  assert.ok(
    packageJson.scripts["test:browser-owner"].includes(
      "browser_process_lifecycle.test.mjs",
    ),
  );
  assert.match(harness, /startBackendServer/);
  assert.match(harness, /allocateLoopbackPort/);
  assert.match(harness, /TALLI_BACKEND_URL:\s*backendBaseUrl/);
  assert.match(harness, /await establishOwnerAal2\(page, baseUrl\)/);
  assert.match(harness, /cleanupBrowserOwnerResources\(resources\)/);
  assert.match(harness, /TALLI_BACKEND_BOUND:/);
  assert.match(harness, /readinessProof:\s*"Ready in"/);
  assert.ok(
    harness.indexOf("t.after(async ()") <
      harness.indexOf("resources.databaseStarted = true"),
    "fixture cleanup must be registered before database connection and fixture setup",
  );
});

test("Vercel deploys the Next output produced by the root build", () => {
  const config = JSON.parse(readFileSync(vercelConfigPath, "utf8"));

  assert.deepEqual(config, { outputDirectory: "apps/web/.next" });
});
