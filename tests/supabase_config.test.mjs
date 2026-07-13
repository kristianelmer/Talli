import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("local Supabase rehearsal uses a stable isolated project and production-shaped auth defaults", async () => {
  const config = await readFile("supabase/config.toml", "utf8");

  assert.match(config, /^project_id = "talli-local"$/mu);
  assert.match(config, /^major_version = 17$/mu);
  assert.match(config, /\[db\.migrations\][\s\S]*?^enabled = true$/mu);
  assert.match(config, /\[db\.seed\][\s\S]*?^enabled = false$/mu);
  assert.match(config, /^minimum_password_length = 12$/mu);
  assert.match(config, /\[auth\.email\][\s\S]*?^enable_confirmations = true$/mu);
  assert.match(config, /\[auth\.email\][\s\S]*?^secure_password_change = true$/mu);
  assert.match(config, /\[auth\.mfa\.totp\][\s\S]*?^enroll_enabled = true$/mu);
  assert.match(config, /\[auth\.mfa\.totp\][\s\S]*?^verify_enabled = true$/mu);
  assert.doesNotMatch(config, /(?:service_role|anon_key|database_url)\s*=\s*"[^e]/iu);
});
