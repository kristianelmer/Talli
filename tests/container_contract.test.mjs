import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("container build is reproducible and excludes local development state", async () => {
  const [dockerfile, dockerignore] = await Promise.all([
    readFile("Dockerfile", "utf8"),
    readFile(".dockerignore", "utf8"),
  ]);

  assert.match(dockerfile, /node:24-trixie-slim@sha256:[a-f0-9]{64}/u);
  assert.match(dockerfile, /ghcr\.io\/astral-sh\/uv:0\.10\.2@sha256:[a-f0-9]{64}/u);
  assert.match(dockerfile, /npm ci/u);
  assert.match(dockerfile, /uv sync --locked --no-dev --no-install-project/u);
  assert.match(dockerfile, /USER node/u);
  assert.match(dockerfile, /PYTHONDONTWRITEBYTECODE=1/u);
  assert.doesNotMatch(dockerfile, /TALLI_ENABLE_RF1086_PRODUCTION_ADAPTER/u);

  const exclusions = new Set(dockerignore.split(/\r?\n/u));
  for (const excluded of [
    ".env",
    ".env.*",
    "**/*.key",
    "**/*.pem",
    "**/*.p12",
    "**/*.pfx",
    "**/*.jwk",
    "tests",
    "supabase",
    ".git",
    ".next",
    "node_modules",
  ]) {
    assert.ok(exclusions.has(excluded), `${excluded} must be excluded from the build context`);
  }
});

test("container smoke test exercises hardened runtime and readiness", async () => {
  const smoke = await readFile("scripts/container-smoke.mjs", "utf8");

  assert.match(smoke, /--read-only/u);
  assert.match(smoke, /--cap-drop/u);
  assert.match(smoke, /no-new-privileges:true/u);
  assert.match(smoke, /\/api\/health/u);
  assert.match(smoke, /\/api\/ready/u);
  assert.match(smoke, /id -u/u);
  assert.match(smoke, /holding_cli\.main/u);
  assert.match(smoke, /holding_core\.corporate_documents/u);
  assert.match(smoke, /reportlab/u);
  assert.match(smoke, /test ! -e \/app\/\.env/u);
});
