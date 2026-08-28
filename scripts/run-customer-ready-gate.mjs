import { createHash } from "node:crypto";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
const producerPath = "scripts/run-customer-ready-gate.mjs";
const sha256 = (value) => `sha256:${createHash("sha256").update(value).digest("hex")}`;
const git = (...args) => spawnSync("git", ["-C", root, ...args], { encoding: "utf8" });
const revision = git("rev-parse", "HEAD").stdout.trim();
const previousIndex = process.argv.indexOf("--previous");
const previousPassingRevision = previousIndex === -1 ? null : process.argv[previousIndex + 1];

if (!/^[a-f0-9]{40}$/u.test(revision)) throw new Error("The gate requires a committed Git revision.");
if (previousPassingRevision !== null && !/^[a-f0-9]{40}$/u.test(previousPassingRevision ?? "")) {
  throw new Error("--previous must name the prior passing revision.");
}
if (previousPassingRevision !== null
  && git("merge-base", "--is-ancestor", previousPassingRevision, revision).status !== 0) {
  throw new Error("The previous passing revision must be an ancestor of HEAD.");
}
if (git("status", "--porcelain").stdout.trim()) {
  throw new Error("The complete gate only runs against a clean working tree.");
}

const startedAt = new Date().toISOString();
const temporaryRoot = mkdtempSync(join(tmpdir(), "talli-customer-ready-gate-"));
const taxSchemaRoot = join(temporaryRoot, "skattemeldingen");
const transcript = [
  `customer-ready-release-gate revision=${revision}`,
  `startedAt=${startedAt}`,
];

function normalizeTranscriptOutput(value) {
  return value
    .replaceAll("\r", "")
    .split("\n")
    .map((line) => line.trimEnd())
    .join("\n")
    .trimEnd();
}

function execute(name, command, executable, args, environment = {}) {
  const started = Date.now();
  transcript.push("", `[${name}] command=${command}`);
  const result = spawnSync(executable, args, {
    cwd: root,
    encoding: "utf8",
    env: { ...process.env, ...environment },
    maxBuffer: 100 * 1024 * 1024,
  });
  if (result.stdout) transcript.push(normalizeTranscriptOutput(result.stdout));
  if (result.stderr) transcript.push(normalizeTranscriptOutput(result.stderr));
  const exitCode = result.status ?? 1;
  const durationMs = Date.now() - started;
  transcript.push(`[${name}] exit=${exitCode}`, `[${name}] durationMs=${durationMs}`);
  if (exitCode !== 0) {
    const evidenceDirectory = join(root, "architecture/evidence/customer-ready-gates");
    mkdirSync(evidenceDirectory, { recursive: true });
    writeFileSync(join(evidenceDirectory, `${revision}.log`), `${transcript.join("\n")}\n`);
    throw new Error(`${name} failed with exit code ${exitCode}`);
  }
  return { name, command, exitCode, durationMs };
}

try {
  execute(
    "schema-setup",
    "git clone --depth 1 --branch v1.62.47 https://github.com/Skatteetaten/skattemeldingen.git",
    "git",
    ["clone", "--depth", "1", "--branch", "v1.62.47", "https://github.com/Skatteetaten/skattemeldingen.git", taxSchemaRoot],
  );

  const checks = [
    execute(
      "credential-scan",
      "npm run test:credential-scan",
      "npm",
      ["run", "test:credential-scan"],
    ),
    execute("typecheck", "npm run typecheck", "npm", ["run", "typecheck"]),
    execute("architecture", "npm run check:architecture", "npm", ["run", "check:architecture"]),
    execute("boundary", "npm run test:boundary", "npm", ["run", "test:boundary"]),
    execute(
      "build-web",
      "TALLI_BACKEND_URL=http://127.0.0.1:8000 TALLI_MARKETING_MEASUREMENT_INTERNAL_KEY=<local-only> npm run build:web && npm run test:browser-public-acquisition:built",
      "bash",
      ["-lc", "npm run build:web && npm run test:browser-public-acquisition:built"],
      {
        TALLI_BACKEND_URL: "http://127.0.0.1:8000",
        TALLI_MARKETING_MEASUREMENT_INTERNAL_KEY: "customer-ready-local-measurement-key",
      },
    ),
    execute("build-backend", "npm run build:backend", "npm", ["run", "build:backend"]),
    execute("boundary-smoke", "npm run test:boundary-smoke", "npm", ["run", "test:boundary-smoke"]),
    execute(
      "launch-rehearsal",
      "TALLI_PYTHON_BIN=.venv/bin/python TALLI_SKATTE_XSD_DIR=<pinned-v1.62.47> npm run test:launch-rehearsal",
      "npm",
      ["run", "test:launch-rehearsal"],
      {
        TALLI_PYTHON_BIN: ".venv/bin/python",
        TALLI_SKATTE_XSD_DIR: join(taxSchemaRoot, "src/resources/xsd"),
      },
    ),
    execute(
      "production-dependency-audit",
      "npm audit --omit=dev --audit-level=high && npm audit --prefix apps/web --omit=dev --audit-level=high",
      "bash",
      ["-lc", "npm audit --omit=dev --audit-level=high && npm audit --prefix apps/web --omit=dev --audit-level=high"],
    ),
    execute(
      "database-isolation",
      "TALLI_PYTHON_BIN=.venv/bin/python npm run test:supabase:local",
      "npm",
      ["run", "test:supabase:local"],
      { TALLI_PYTHON_BIN: ".venv/bin/python" },
    ),
    execute(
      "whitespace",
      "bash scripts/check-clean-worktree.sh",
      "bash",
      ["scripts/check-clean-worktree.sh"],
    ),
  ];
  const executedAt = new Date().toISOString();
  transcript.push("", `executedAt=${executedAt}`, "verdict=pass");
  const transcriptText = `${transcript.join("\n")}\n`;
  const evidenceDirectory = join(root, "architecture/evidence/customer-ready-gates");
  const transcriptPath = `architecture/evidence/customer-ready-gates/${revision}.log`;
  const evidencePath = `architecture/evidence/customer-ready-gates/${revision}.json`;
  mkdirSync(evidenceDirectory, { recursive: true });
  writeFileSync(join(root, transcriptPath), transcriptText);
  const producer = git("show", `${revision}:${producerPath}`).stdout;
  if (!producer) throw new Error("The gate producer must be committed at the tested revision.");
  const evidence = {
    schemaVersion: "1.0",
    revision,
    previousPassingRevision,
    workflow: "customer-ready-release-gate",
    executor: "local-script",
    producer: producerPath,
    producerDigest: sha256(producer),
    transcriptPath,
    transcriptDigest: sha256(transcriptText),
    startedAt,
    executedAt,
    verdict: "pass",
    checks,
  };
  writeFileSync(join(root, evidencePath), `${JSON.stringify(evidence, null, 2)}\n`);
  process.stdout.write(`${evidencePath}\n`);
} finally {
  rmSync(temporaryRoot, { recursive: true, force: true });
}
