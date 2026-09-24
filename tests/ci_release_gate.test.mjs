import assert from "node:assert/strict";
import {
  chmodSync,
  existsSync,
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

function createHarnessWorkspace(mode, guideState) {
  const directory = mkdtempSync(join(tmpdir(), "talli-database-harness-test-"));
  const nextEnvPath = join(directory, "apps/web/next-env.d.ts");
  const tsconfigPath = join(directory, "apps/web/tsconfig.json");
  const guidePaths = ["AGENTS.md", "CLAUDE.md"].map((name) => join(directory, "apps/web", name));
  const originalGuides = guidePaths.map((_, index) => (
    guideState === "existing" || (guideState === "mixed" && index === 0)
      ? Buffer.from(`Original guide ${index}: beholdt\r\n`, "utf8")
      : null
  ));
  const binDirectory = join(directory, "bin");
  const snapshotDirectory = join(directory, "snapshots");
  mkdirSync(dirname(nextEnvPath), { recursive: true });
  mkdirSync(join(directory, "scripts"));
  mkdirSync(binDirectory);
  mkdirSync(snapshotDirectory);
  writeFileSync(nextEnvPath, "original declaration\n");
  writeFileSync(tsconfigPath, "original config\n");
  guidePaths.forEach((path, index) => {
    if (originalGuides[index]) writeFileSync(path, originalGuides[index]);
  });
  writeFileSync(
    join(directory, "scripts/prepare-isolated-supabase-workdir.mjs"),
    "// Test fixture: the npm shim owns the isolated Supabase lifecycle.\n",
  );
  writeFileSync(join(directory, "scripts/rehearse-authority-topology.mjs"),
    "console.log('AUTHORITY_TOPOLOGY:' + process.argv[2]);\n"
    + `if (process.argv[2] === 'recutover' && ${JSON.stringify(mode)} === 'authority-recutover-failure') process.exit(11);\n`);
  const npmPath = join(binDirectory, "npm");
  writeFileSync(
    npmPath,
    `#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *"supabase status --workdir"* && "$*" == *"--output env"* ]]; then
  printf '%s\\n' 'API_URL=http://127.0.0.1:54321' 'PUBLISHABLE_KEY=local-anon' 'SECRET_KEY=local-service' 'DB_URL=postgresql://127.0.0.1/local'
  exit 0
fi
printf 'HARNESS_NPM:%s\\n' "$*"
if [[ "$*" == "run test:billing-database-lifecycle" && "${mode}" == "billing-failure" ]]; then
  exit 13
fi
if [[ "$*" == "run test:browser-owner" ]]; then
  printf 'generated declaration\\n' > apps/web/next-env.d.ts
  printf 'generated config\\n' > apps/web/tsconfig.json
  printf 'generated agent guide\\n' > apps/web/AGENTS.md
  printf 'generated Claude guide\\n' > apps/web/CLAUDE.md
  if [[ "${mode}" == "restore-failure" || "${mode}" == "command-and-restore-failure" ]]; then
    mv apps/web apps/web-displaced
  fi
  if [[ "${mode}" == "command-failure" || "${mode}" == "command-and-restore-failure" ]]; then
    exit 7
  fi
fi
`,
  );
  chmodSync(npmPath, 0o755);
  return {
    directory,
    nextEnvPath,
    tsconfigPath,
    guidePaths,
    originalGuides,
    snapshotDirectory,
    binDirectory,
  };
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

test("manual release gates can retain linked immutable evidence", () => {
  const workflow = readFileSync(workflowPath, "utf8");

  assert.match(workflow, /record_evidence:/u);
  assert.match(workflow, /previous_passing_revision:/u);
  assert.match(workflow, /npm run gate:customer-ready/u);
  assert.match(workflow, /--previous "\$PREVIOUS_PASSING_REVISION"/u);
  assert.match(workflow, /uses: actions\/upload-artifact@[0-9a-f]{40}/u);
  assert.match(
    workflow,
    /architecture\/evidence\/customer-ready-gates\/\$\{\{ github\.sha \}\}\.json/u,
  );
  assert.match(
    workflow,
    /architecture\/evidence\/customer-ready-gates\/\$\{\{ github\.sha \}\}\.log/u,
  );
  assert.match(workflow, /needs: \[application, database, evidence\]/u);
  assert.match(workflow, /test "\$EVIDENCE_RESULT" = "success"/u);
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

test("database isolation runs the complete ledger contract lifecycle", () => {
  const databaseHarness = readFileSync(databaseHarnessPath, "utf8");
  const packageJson = JSON.parse(
    readFileSync(new URL("../package.json", import.meta.url), "utf8"),
  );

  assert.match(databaseHarness, /npm run test:ledger-database-lifecycle/u);
  assert.equal(
    packageJson.scripts["test:ledger-database-lifecycle"],
    "node --test --test-concurrency=1 tests/ledger_capability_schema.test.mjs tests/ledger_capability_boundary_regressions.test.mjs tests/ledger_full_year_database_runtime.test.mjs tests/ledger_supported_patterns_database_runtime.test.mjs tests/ledger_opening_position_rebuild_schema.test.mjs tests/ledger_corrections_database_runtime.test.mjs tests/ledger_supported_event_reversals_schema.test.mjs tests/ledger_company_year_close_database_runtime.test.mjs tests/ledger_database_runtime.test.mjs",
  );
  assert.match(databaseHarness, /prepare-isolated-supabase-workdir\.mjs/u);
  assert.match(databaseHarness, /supabase start --workdir "\$isolated_workdir"/u);
  assert.match(databaseHarness, /PUBLISHABLE_KEY:-\$ANON_KEY/u);
  assert.match(databaseHarness, /SECRET_KEY:-\$SERVICE_ROLE_KEY/u);
  assert.doesNotMatch(databaseHarness, /supabase migration up --local/u);
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

test("local immutable gate normalizes terminal output before recording it", () => {
  const localGate = readFileSync(localGatePath, "utf8");

  assert.match(localGate, /function normalizeTranscriptOutput\(value\)/u);
  assert.match(localGate, /\.replaceAll\("\\r", ""\)/u);
  assert.match(localGate, /\.map\(\(line\) => line\.trimEnd\(\)\)/u);
  assert.match(
    localGate,
    /transcript\.push\(normalizeTranscriptOutput\(result\.stdout\)\)/u,
  );
  assert.match(
    localGate,
    /transcript\.push\(normalizeTranscriptOutput\(result\.stderr\)\)/u,
  );
});

test("database harness restores generated drift and preserves failure semantics", () => {
  for (const [mode, guideState] of [
    "success", "command-failure", "restore-failure", "command-and-restore-failure",
  ].flatMap((mode) => ["absent", "existing", "mixed"].map((guideState) => [mode, guideState]))) {
    const workspace = createHarnessWorkspace(mode, guideState);
    try {
      const result = run("bash", [fileURLToPath(databaseHarnessPath)], {
        cwd: workspace.directory,
        env: {
          ...process.env,
          PATH: `${workspace.binDirectory}:${process.env.PATH}`,
          TMPDIR: workspace.snapshotDirectory,
        },
      });

      if (mode === "success" || mode === "command-failure") {
        assert.equal(result.status, mode === "success" ? 0 : 7, result.stderr);
        assert.equal(readFileSync(workspace.nextEnvPath, "utf8"), "original declaration\n");
        assert.equal(readFileSync(workspace.tsconfigPath, "utf8"), "original config\n");
        workspace.guidePaths.forEach((path, index) => {
          if (workspace.originalGuides[index]) {
            assert.deepEqual(readFileSync(path), workspace.originalGuides[index], `${mode}/${guideState}`);
          } else {
            assert.equal(existsSync(path), false, `${mode}/${guideState}: remove only newly generated guides`);
          }
        });
        assert.deepEqual(readdirSync(workspace.snapshotDirectory), []);
      } else {
        assert.equal(result.status, mode === "command-and-restore-failure" ? 7 : 1, result.stderr);
        const snapshots = readdirSync(workspace.snapshotDirectory)
          .map((name) => readFileSync(join(workspace.snapshotDirectory, name), "utf8"))
          .sort();
        assert.deepEqual(snapshots, [
          "original declaration\n", "original config\n",
          ...workspace.originalGuides.filter(Boolean).map((bytes) => bytes.toString("utf8")),
        ].sort(), "failed restoration must retain the original bytes for recovery");
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
  assert.match(harness, /documents\.stage_upload_v1/u);
  assert.match(harness, /documents\.finalize_upload_v1/u);
  assert.doesNotMatch(harness, /admin\.from\("documents"\)\.insert/u);
  assert.ok(
    harness.indexOf("t.after(async ()") <
      harness.indexOf("resources.databaseStarted = true"),
    "fixture cleanup must be registered before database connection and fixture setup",
  );
});

test("Vercel deploys the Next output near the owner-designated database", () => {
  const config = JSON.parse(readFileSync(vercelConfigPath, "utf8"));

  assert.equal(config.outputDirectory, "apps/web/.next");
  assert.deepEqual(config.regions, ["dub1"]);
});

test("backend boundary partitions every test across the ordinary, Billing, Authority, Company Tax and Accounts mandatory lanes", () => {
  const packageJson = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
  const lifecycle = packageJson.scripts["test:billing-database-lifecycle"];
  const authorityLifecycle = packageJson.scripts["test:authority-connections-database"];
  const files = lifecycle.match(/apps\/backend\/tests\/test_\w+\.py/gu);
  const authorityFiles = authorityLifecycle.match(/apps\/backend\/tests\/test_\w+\.py/gu);
  assert.match(authorityLifecycle, /&& uv run --project apps\/backend python scripts\/test-corporate-reporting-owned-clone\.py$/u);
  const cloneRunner = readFileSync(new URL("../scripts/test-corporate-reporting-owned-clone.py", import.meta.url), "utf8");
  const cloneFiles = cloneRunner.match(/apps\/backend\/tests\/test_\w+\.py/gu);
  assert.deepEqual(cloneFiles, ["apps/backend/tests/test_corporate_reporting_year_database_runtime.py"]);
  authorityFiles.push(...cloneFiles);
  assert.ok(files?.length, "the mandatory database lane must name its test files");
  assert.ok(authorityFiles?.length, "the mandatory Authority lane must name its test files");
  const env = { ...process.env };
  delete env.DATABASE_URL;
  const collect = (command) => {
    const result = run("sh", ["-c", `${command} --collect-only -q`], {
      cwd: fileURLToPath(new URL("../", import.meta.url)),
      env,
      maxBuffer: 8 * 1024 * 1024,
      timeout: 30_000,
    });
    assert.equal(result.status, 0, result.stdout + result.stderr);
    return new Set(result.stdout.split("\n").filter((line) => /^tests\/.*::/u.test(line)));
  };
  const pytest = "uv run --project apps/backend pytest -c apps/backend/pyproject.toml";
  const database = collect(`${pytest} ${files.join(" ")}`);
  assert.ok(database.size >= 158, "existing annual and predecessor DB cases must remain collected");
  const marked = collect(`${pytest} apps/backend/tests -m billing_database`);
  assert.deepEqual(marked, database, "marked exclusions must exactly match the mandatory lifecycle selection");
  const authority = collect(`${pytest} ${authorityFiles.join(" ")}`);
  const authorityMarked = collect(`${pytest} apps/backend/tests -m authority_database`);
  assert.deepEqual(authorityMarked, authority, "every excluded Authority/RF/signoff case must be in its mandatory lane");
  assert.ok(authority.size >= 36, "owner, operator and technical signoff cases must remain collected");
  const taxFiles = packageJson.scripts["test:company-tax-database"].match(/apps\/backend\/tests\/test_\w+\.py/gu);
  assert.deepEqual(taxFiles, [
    "apps/backend/tests/test_company_tax_filing_database.py",
    "apps/backend/tests/test_company_tax_filing_runtime.py",
    "apps/backend/tests/test_company_tax_return_lifecycle.py",
  ], "Tax must retain settlement expansion/runtime and filing lifecycle coverage");
  const tax = collect(`${pytest} ${taxFiles.join(" ")}`);
  assert.deepEqual(collect(`${pytest} apps/backend/tests -m company_tax_database`), tax);
  assert.ok(tax.size >= 21);
  const accountsFiles = packageJson.scripts["test:annual-accounts-database"].match(/apps\/backend\/tests\/test_\w+\.py/gu);
  assert.deepEqual(accountsFiles, ["apps/backend/tests/test_annual_accounts_filing_lifecycle.py"]);
  const accounts = collect(`${pytest} ${accountsFiles.join(" ")}`);
  assert.deepEqual(collect(`${pytest} apps/backend/tests -m accounts_database`), accounts);
  assert.ok(accounts.size >= 23);
  const boundary = collect(packageJson.scripts["test:boundary-backend"]);
  const all = collect(`${pytest} apps/backend/tests`);
  assert.deepEqual(new Set([...boundary, ...database, ...authority, ...tax, ...accounts]), all, "no backend test may disappear between lanes");
  assert.deepEqual([...accounts].filter((id) => boundary.has(id) || database.has(id) || authority.has(id) || tax.has(id)), [], "Accounts must run only in its mandatory lane");
  assert.deepEqual([...boundary].filter((id) => database.has(id)), [], "database fixtures must not run in the ordinary boundary lane");
  assert.deepEqual([...boundary].filter((id) => authority.has(id)), [], "Authority fixtures must not run in the ordinary boundary lane");
  assert.deepEqual([...authority].filter((id) => database.has(id)), [], "database lifecycle lanes must not overlap");
  assert.deepEqual([...tax].filter((id) => boundary.has(id) || database.has(id) || authority.has(id)), [], "Tax must run only in its mandatory lane");
  assert.match(readFileSync(databaseHarnessPath, "utf8"), /DATABASE_URL="\$DB_URL" npm run test:billing-database-lifecycle/u);
  assert.match(readFileSync(databaseHarnessPath, "utf8"), /DATABASE_URL="\$DB_URL" npm run test:authority-connections-database/u);
  assert.match(lifecycle, /&& node --test --test-concurrency=1 tests\/billing_database_runtime\.test\.mjs/u);
});

test("mandatory Billing and Authority lifecycles refuse missing DB configuration before any test runner", () => {
  const packageJson = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
  const directory = mkdtempSync(join(tmpdir(), "talli-billing-lane-test-"));
  try {
    for (const executable of ["uv", "node"]) {
      const path = join(directory, executable);
      writeFileSync(path, "#!/bin/sh\necho TEST_RUNNER_STARTED\n");
      chmodSync(path, 0o755);
    }
    const env = { ...process.env, PATH: `${directory}:${process.env.PATH}` };
    delete env.DATABASE_URL;
    for (const lane of ["test:billing-database-lifecycle", "test:authority-connections-database", "test:company-tax-database", "test:annual-accounts-database"]) {
      const result = run("sh", ["-c", packageJson.scripts[lane]], { env });
      assert.notEqual(result.status, 0, `missing DATABASE_URL must fail ${lane}`);
      assert.match(result.stderr, /DATABASE_URL.*disposable/u);
      assert.doesNotMatch(result.stdout, /TEST_RUNNER_STARTED/u);
    }
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});


test("mandatory local lane preserves every predecessor before Billing and final Authority verification", () => {
  for (const mode of ["success", "billing-failure", "authority-recutover-failure"]) {
    const workspace = createHarnessWorkspace(mode, "absent");
    try {
      const result = run("bash", [fileURLToPath(databaseHarnessPath)], { cwd: workspace.directory,
        env: { ...process.env, PATH: `${workspace.binDirectory}:${process.env.PATH}`, TMPDIR: workspace.snapshotDirectory } });
      assert.equal(result.status, mode === "success" ? 0 : mode === "billing-failure" ? 13 : 11, result.stderr);
      const milestones = [
        "AUTHORITY_TOPOLOGY:rollback",
        "HARNESS_NPM:run test:ledger-database-lifecycle", "HARNESS_NPM:run test:banking-database-lifecycle",
        "HARNESS_NPM:run test:investments-database-lifecycle", "HARNESS_NPM:run test:documents-database-lifecycle",
        "HARNESS_NPM:run test:marketing-measurement-database", "HARNESS_NPM:run test:validation-observation",
        "HARNESS_NPM:run test:supabase-predecessor", "AUTHORITY_TOPOLOGY:workspace",
        "HARNESS_NPM:run test:supabase-rf-workspace", "HARNESS_NPM:run test:browser-owner",
        "AUTHORITY_TOPOLOGY:rollback",
        "HARNESS_NPM:run test:ledger-hosted-migration-authority", "HARNESS_NPM:run test:corporate-governance-database-lifecycle",
        "HARNESS_NPM:run test:billing-database-lifecycle",
        ...(mode !== "billing-failure" ? ["AUTHORITY_TOPOLOGY:recutover"] : []),
        ...(mode === "success" ? ["HARNESS_NPM:run test:authority-connections-database", "HARNESS_NPM:run test:company-tax-database", "HARNESS_NPM:run test:browser-owner-annual", "HARNESS_NPM:run test:supabase-rf-feedback", "HARNESS_NPM:run test:browser-authority-connections", "HARNESS_NPM:run test:browser-shareholder-register-filing"] : []),
      ];
      let previous = -1;
      for (const milestone of milestones) {
        const position = result.stdout.indexOf(milestone + "\n", previous + 1);
        assert.ok(position > previous, `${mode}: missing or reordered ${milestone}\n${result.stdout}`);
        previous = position;
      }
      if (mode !== "success") assert.doesNotMatch(result.stdout, /HARNESS_NPM:run test:(?:authority-connections-database|browser-authority-connections)/u);
      assert.deepEqual(readdirSync(workspace.snapshotDirectory), []);
    } finally { rmSync(workspace.directory, { recursive: true, force: true }); }
  }
});


// Exact #150/#151 fixture dependency and source-file partition regressions.
{
const {rehearseAuthorityTopology}=await import("../scripts/rehearse-authority-topology.mjs");
const AU='20260909120610_authority_connections_capability.sql';
const OP='20260909123709_authority_operations_capability.sql';
const RF='20260909125113_legacy_rf1086_authority_relocation.sql';
const AUC='20260909124659_authority_connections_contract.sql';
const SIGN='20260909125250_backend_system_launch_signoffs_contract.sql';
const RFX='20260909190548_shareholder_register_filing_capability.sql';
const RFC='20260909190905_shareholder_register_filing_cutover.sql';
const RFF='20260909190955_shareholder_register_filing_contract.sql';
const RFR='20260917110951_rf1086_action_required_read_recovery.sql';
const RFA='20260917114424_rf1086_production_archive_evidence.sql';
const RFY='20260923091509_rf1086_immutable_year_source.sql';
const RFO='20260923102314_rf1086_register_observation_store.sql';
const RFP='20260923105912_rf1086_source_backed_preview.sql';
const RFG='20260924062746_rf1086_source_company_guard.sql';
const DLG='20260923125730_documents_ledger_evidence_guard.sql';
const predecessor={rf_owned:false,authority_kind:'r',ledger_kind:'v',ledger_setup:true,opening_kind:'r'};
const forward=[`migrations/${AU}`,`migrations/${OP}`,`migrations/${RF}`,`contract-migrations/${AUC}`,`contract-migrations/${SIGN}`,`migrations/${RFX}`,`migrations/${RFC}`,`migrations/${DLG}`,`migrations/${RFR}`,`migrations/${RFA}`,`migrations/${RFY}`,`migrations/${RFO}`,`migrations/${RFP}`,`migrations/${RFG}`];
const consequentialGuards=['20260924080208_company_access_rf_admission_guard.sql','20260924080249_documents_rf_consequential_company_guards.sql','20260924080355_governance_ledger_company_write_guards.sql','20260924083154_governance_guarded_reporting_year_read.sql','20260924084752_billing_rf_full_year_pilot_profile.sql','20260924085227_rf1086_source_review_bridge.sql'].map(file=>`migrations/${file}`);
const workspaceForward=[...forward.filter(path=>path!==`contract-migrations/${AUC}`),...consequentialGuards];
function fake(initial,{fail,noEffect=false}={}) {
 const state={signoff_open:true,...initial},executed=[];
 return {state,executed,database:{async query(sql) {
  if(sql.startsWith('select\n')) return {rows:[{...state}]};
  if(sql.startsWith('select exists(select 1 from shareholder_register_filing.register_observations)')) return {rows:[{retained_observations:state.retained_observations??false}]};
  if(sql.startsWith('select exists(select 1 from shareholder_register_filing.year_source_versions)')) return {rows:[{retained_sources:state.retained_sources??false}]};
  executed.push(sql); if(sql===fail) throw new Error('synthetic_dependency_failure');
  if(!noEffect){
   if(sql===`contract-migrations/${SIGN}`){if(!state.signoff_open)throw new Error('launch_signoff_policy_missing');state.signoff_open=false;}
   if(sql===`rollback/${SIGN}`)state.signoff_open=true;
   if(sql===`rollback/${RFX}`){state.rf_owned=false;state.opening_kind='r';}
   if(sql===`rollback/${AUC}`)state.authority_kind='v';
   if(sql===`rollback/${AU}`)state.authority_kind='r';
   if(sql===`migrations/${AU}`)state.authority_kind='v';
   if(sql===`contract-migrations/${AUC}`)state.authority_kind=null;
   if(sql===`migrations/${RFX}`)state.rf_owned=true;
   if(sql===`contract-migrations/${RFF}`)state.opening_kind=null;
  }
  return {rows:[]};
 }}};
}
const run=(direction,fixture)=>rehearseAuthorityTopology({direction,database:fixture.database,loadSql:async path=>path});
for(const authority_kind of ['v',null]) for(const rf_owned of [false,true]) {
 test(`rollback RF=${rf_owned} AU=${authority_kind} restores dependency order`,async()=>{
  const fixture=fake({...predecessor,authority_kind,rf_owned});await run('rollback',fixture);
  assert.deepEqual(fixture.executed,[...(rf_owned?[`rollback/${RFA}`,`rollback/${RFX}`]:[]),`rollback/${SIGN}`,...(authority_kind===null?[`rollback/${AUC}`]:[]),`rollback/${RF}`,`rollback/${OP}`,`rollback/${AU}`]);
 });
}
test('empty source-preview API rolls back before source APIs and full RF schema',async()=>{
 const f=fake({...predecessor,rf_owned:true,rf_source_company_guard:true,rf_source_previews:true,rf_register_observations:true,rf_year_sources:true,authority_kind:null});
 await run('rollback',f);
 assert.deepEqual(f.executed.slice(0,6),[`rollback/${RFG}`,`rollback/${RFP}`,`rollback/${RFO}`,`rollback/${RFY}`,`rollback/${RFA}`,`rollback/${RFX}`]);
});
test('retained independent register observations block full-schema rollback before any mutation',async()=>{
 const f=fake({...predecessor,rf_owned:true,rf_register_observations:true,retained_observations:true,authority_kind:null});
 await assert.rejects(run('rollback',f),/rf1086_retained_register_observations_block_full_schema_rollback/);
 assert.deepEqual(f.executed,[]);
});
test('retained immutable RF year sources block full-schema rollback before any mutation',async()=>{
 const f=fake({...predecessor,rf_owned:true,rf_year_sources:true,retained_sources:true,authority_kind:null});
 await assert.rejects(run('rollback',f),/rf1086_retained_year_sources_block_full_schema_rollback/);
 assert.deepEqual(f.executed,[]);
});
test('workspace rollback followed by final recutover restores signoff policy topology',async()=>{
 const f=fake(predecessor);await run('workspace',f);await run('rollback',f);
 f.state.ledger_kind=null;f.state.ledger_setup=false;
 await run('recutover',f);assert.equal(f.state.signoff_open,false);
});
test('RF rollback failure prevents all predecessor mutations',async()=>{
 const f=fake({...predecessor,rf_owned:true,authority_kind:null},{fail:`rollback/${RFX}`});
 await assert.rejects(run('rollback',f),/synthetic_dependency_failure/);assert.deepEqual(f.executed,[`rollback/${RFA}`,`rollback/${RFX}`]);
});
test('workspace retains AU and Ledger overlap for Billing and sibling consumers',async()=>{
 const f=fake(predecessor);await run('workspace',f);assert.deepEqual(f.executed,workspaceForward);
 assert.ok(!f.executed.some(p=>p.includes('ledger_capability_contract')||p===`contract-migrations/${AUC}`||p===`contract-migrations/${RFF}`));
});
for(const wrong of [{ledger_kind:null,ledger_setup:false},{ledger_kind:'r'},{ledger_setup:false},{opening_kind:null}])test(`workspace refuses wrong Ledger topology ${JSON.stringify(wrong)}`,async()=>{
 const f=fake({...predecessor,...wrong});await assert.rejects(run('workspace',f),/workspace_requires_ledger_ordinary_overlap/);assert.deepEqual(f.executed,[]);
});
test('final RF contract follows explicit final Ledger guard and owner recutover',async()=>{
 const f=fake({...predecessor,ledger_kind:null,ledger_setup:false});await run('recutover',f);assert.deepEqual(f.executed,[...forward,`contract-migrations/${RFF}`,...consequentialGuards]);
});
for(const wrong of [{ledger_kind:'v',ledger_setup:true},{ledger_kind:null,ledger_setup:true},{ledger_kind:'v',ledger_setup:false}])test(`final refuses incomplete Ledger contract ${JSON.stringify(wrong)}`,async()=>{
 const f=fake({...predecessor,...wrong});await assert.rejects(run('recutover',f),/final_rf_requires_ledger_contract/);assert.deepEqual(f.executed,[]);
});
for(const fail of [`migrations/${RF}`,`migrations/${RFX}`,`migrations/${RFC}`,`migrations/${DLG}`,`migrations/${RFR}`,`contract-migrations/${RFF}`,...consequentialGuards])test(`dependency failure stops final sequence at ${fail}`,async()=>{
 const f=fake({...predecessor,ledger_kind:null,ledger_setup:false},{fail});await assert.rejects(run('recutover',f),/synthetic_dependency_failure/);
 const files=[...forward,`contract-migrations/${RFF}`,...consequentialGuards];assert.deepEqual(f.executed,files.slice(0,files.indexOf(fail)+1));
});
test('success is refused if SQL does not establish target state',async()=>{
 const f=fake(predecessor,{noEffect:true});await assert.rejects(run('workspace',f),/authority_rehearsal_target_not_reached/);
});
test('unexpected earlier owner topology fails before mutation',async()=>{
 const f=fake({...predecessor,authority_kind:'v'});await assert.rejects(run('workspace',f),/authority_predecessor_topology_required/);assert.deepEqual(f.executed,[]);
});
test('unknown direction fails before even probing the database',async()=>{
 await assert.rejects(rehearseAuthorityTopology({direction:'all',database:{query(){assert.fail('query must not run');}}}),/invalid_authority_rehearsal_direction/);
});
test('package partition retains every original file once',()=>{
 const previous=["tests/supabase_workspace.test.mjs", "tests/rf1086_feedback_schema.test.mjs", "tests/company_access_invitations_schema.test.mjs", "tests/company_access_cancellation_schema.test.mjs", "tests/company_year_admission_schema.test.mjs", "tests/current_legal_evidence_schema.test.mjs", "tests/current_legal_evidence_migration_lifecycle.test.mjs", "tests/support_access_schema.test.mjs", "tests/company_access_database_runtime.test.mjs", "tests/company_access_onboarding_database_runtime.test.mjs", "tests/support_access_database_runtime.test.mjs", "tests/support_access_migration_lifecycle.test.mjs", "tests/documents_database_runtime.test.mjs", "tests/documents_migration_lifecycle.test.mjs"];
 const allScripts=JSON.parse(readFileSync(new URL('../package.json',import.meta.url),'utf8')).scripts;
 const scripts=Object.fromEntries(['test:supabase-predecessor','test:supabase-rf-workspace','test:supabase-rf-feedback'].map(name=>[name,allScripts[name]]));
 assert.equal(allScripts['test:supabase'],'npm run test:supabase:local');
 assert.doesNotMatch(readFileSync(databaseHarnessPath,'utf8'),/npm run test:supabase\s*$/mu);
 const actual=Object.values(scripts).flatMap(x=>x.split(' ').filter(y=>y.startsWith('tests/')));
 assert.equal(actual.length,new Set(actual).size);assert.deepEqual([...actual].sort(),[...previous].sort());
});
test("complete local runner requires the fresh RF browser after historical recovery", () => {
  const scripts = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8")).scripts;
  assert.equal(scripts["test:browser-shareholder-register-filing"],
    "node --test --test-concurrency=1 tests/shareholder_register_browser_fixture_safety.test.mjs tests/browser_shareholder_register_filing.mjs");
  const harness = readFileSync(databaseHarnessPath, "utf8");
  const fresh = "npm run test:browser-shareholder-register-filing";
  assert.equal(harness.split(fresh).length, 2);
  assert.ok(harness.indexOf(fresh) > harness.indexOf("npm run test:browser-authority-connections"));
});

}

// Execute the actual shell with local shims; no database or provider process starts.
{
const shell=fileURLToPath(new URL('../scripts/test-supabase-local.sh',import.meta.url));
const phases=['topology:rollback:1','npm:test:ledger-database-lifecycle','npm:test:banking-database-lifecycle',
 'npm:test:investments-database-lifecycle','npm:test:documents-database-lifecycle','npm:test:marketing-measurement-database',
 'npm:test:validation-observation','npm:test:supabase-predecessor','topology:workspace','npm:test:supabase-rf-workspace',
 'npm:test:browser-owner','topology:rollback:2','npm:test:ledger-hosted-migration-authority',
 'npm:test:corporate-governance-database-lifecycle','npm:test:billing-database-lifecycle','topology:recutover',
 'npm:test:authority-connections-database','npm:test:company-tax-database','npm:test:annual-accounts-database','npm:test:browser-owner-annual','npm:test:supabase-rf-feedback','npm:test:browser-authority-connections','npm:test:browser-shareholder-register-filing','npm:test:browser-company-tax','npm:test:browser-annual-accounts'];
const nodeShim=`#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == "scripts/prepare-isolated-supabase-workdir.mjs" ]]; then exit 0; fi
[[ "$1" == "scripts/rehearse-authority-topology.mjs" ]]
phase="topology:$2"
if [[ "$2" == "rollback" ]]; then
 count=0; [[ ! -f rollback-count ]] || count=$(cat rollback-count)
 count=$((count+1)); printf '%s' "$count" > rollback-count; phase="$phase:$count"
fi
printf 'PHASE:%s\\n' "$phase"
if [[ "$phase" == "$FAIL_PHASE" ]]; then exit 23; fi
`;
const npmShim=`#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *"supabase status --workdir"* && "$*" == *"--output env"* ]]; then
 printf '%s\\n' 'API_URL=http://127.0.0.1:54321' 'PUBLISHABLE_KEY=synthetic' 'SECRET_KEY=synthetic' 'DB_URL=postgresql://127.0.0.1/local'
 exit 0
fi
if [[ "$1" == "exec" ]]; then exit 0; fi
[[ "$1" == "run" ]]
if [[ "$2" == "test:supabase-advisors" ]]; then exit 0; fi
phase="npm:$2"; printf 'PHASE:%s\\n' "$phase"
if [[ "$2" == "test:browser-owner" ]]; then
 printf 'generated\\n' > apps/web/next-env.d.ts
 printf 'generated\\n' > apps/web/tsconfig.json
 printf 'generated\\n' > apps/web/AGENTS.md
 printf 'generated\\n' > apps/web/CLAUDE.md
fi
if [[ "$phase" == "$FAIL_PHASE" ]]; then exit 23; fi
`;
for(const fail of ['', 'topology:workspace','npm:test:supabase-rf-workspace','npm:test:browser-owner','topology:rollback:2',
 'npm:test:ledger-hosted-migration-authority','npm:test:billing-database-lifecycle','topology:recutover','npm:test:supabase-rf-feedback',
 'npm:test:company-tax-database','npm:test:annual-accounts-database','npm:test:browser-owner-annual','npm:test:browser-shareholder-register-filing','npm:test:browser-company-tax','npm:test:browser-annual-accounts']) {
 test(`real shell stops at ${fail||'success'} and restores owned generated files`,()=>{
  const dir=mkdtempSync(join(tmpdir(),'talli-151-shell-proof-'));
  try {
   mkdirSync(join(dir,'apps/web'),{recursive:true});mkdirSync(join(dir,'bin'));mkdirSync(join(dir,'snapshots'));
   writeFileSync(join(dir,'apps/web/next-env.d.ts'),'original declaration\r\n');
   writeFileSync(join(dir,'apps/web/tsconfig.json'),'original config\r\n');
   for(const [name,body] of [['node',nodeShim],['npm',npmShim]]) {const path=join(dir,'bin',name);writeFileSync(path,body);chmodSync(path,0o755);}
   const result=spawnSync('bash',[shell],{cwd:dir,encoding:'utf8',env:{...process.env,FAIL_PHASE:fail,PATH:join(dir,'bin')+':'+process.env.PATH,TMPDIR:join(dir,'snapshots')}});
   assert.equal(result.status,fail?23:0,result.stderr);
   const seen=result.stdout.split('\n').filter(x=>x.startsWith('PHASE:')).map(x=>x.slice(6));
   assert.deepEqual(seen,fail?phases.slice(0,phases.indexOf(fail)+1):phases);
   assert.equal(readFileSync(join(dir,'apps/web/next-env.d.ts'),'utf8'),'original declaration\r\n');
   assert.equal(readFileSync(join(dir,'apps/web/tsconfig.json'),'utf8'),'original config\r\n');
   assert.deepEqual(readdirSync(join(dir,'apps/web')).sort(),['next-env.d.ts','tsconfig.json']);
   assert.deepEqual(readdirSync(join(dir,'snapshots')),[]);
  } finally {rmSync(dir,{recursive:true,force:true});}
 });
}

}
