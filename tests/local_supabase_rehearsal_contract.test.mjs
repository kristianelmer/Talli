import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("local Supabase rehearsal is disposable, loopback-bound, and keeps status credentials in memory", async () => {
  const script = await readFile("scripts/local-supabase-rehearsal.mjs", "utf8");
  const workspaceTest = await readFile("tests/supabase_workspace.test.mjs", "utf8");
  const packageJson = JSON.parse(await readFile("package.json", "utf8"));

  assert.equal(packageJson.devDependencies.supabase, "2.109.1");
  assert.match(script, /supabase[\s\S]*?stop[\s\S]*?--no-backup/u);
  assert.match(script, /com\.docker\.network\.bridge\.host_binding_ipv4=127\.0\.0\.1/u);
  assert.match(script, /supabase[\s\S]*?start[\s\S]*?--network-id/u);
  assert.match(script, /COMPOSE_PARALLEL_LIMIT: "1"/u);
  assert.match(script, /supabase[\s\S]*?status[\s\S]*?--output[\s\S]*?env/u);
  assert.match(script, /SUPABASE_URL: local\.API_URL/u);
  assert.match(script, /SUPABASE_SERVICE_ROLE_KEY: local\.SERVICE_ROLE_KEY/u);
  assert.match(script, /PUBLISHABLE_KEY\|DB_URL/u);
  assert.match(script, /sb_\(\?:secret\|publishable\)/u);
  assert.doesNotMatch(script, /writeFile|appendFile|console\.log\([^)]*(?:ANON_KEY|SERVICE_ROLE_KEY|status\.stdout)/u);
  assert.doesNotMatch(workspaceTest, /(?:from "pg"|DIRECT_DATABASE_URL|DATABASE_URL|applyMigration)/u);
  assert.match(workspaceTest, /auth\.mfa\.enroll/u);
  assert.match(workspaceTest, /auth\.mfa\.challenge/u);
  assert.match(workspaceTest, /auth\.mfa\.verify/u);
  assert.match(workspaceTest, /rpc\("record_mfa_step_up"\)/u);
  assert.equal(packageJson.dependencies.pg, undefined);
});
