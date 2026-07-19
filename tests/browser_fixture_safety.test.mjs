import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { isLoopbackSupabaseUrl } from "./support/supabase_fixture_safety.mjs";

test("Supabase browser fixtures only accept loopback URLs", () => {
  for (const value of [
    "http://127.0.0.1:54321",
    "http://localhost:54321",
    "http://[::1]:54321",
  ]) {
    assert.equal(isLoopbackSupabaseUrl(value), true, value);
  }

  for (const value of [
    "https://project.supabase.co",
    "https://localhost.example.com",
    "https://127.0.0.1.example.com",
    "not-a-url",
  ]) {
    assert.equal(isLoopbackSupabaseUrl(value), false, value);
  }
});

test("owner browser harness stops before remote fixture creation", () => {
  const harnessPath = fileURLToPath(
    new URL("./browser_owner_annual_loop.mjs", import.meta.url),
  );
  const result = spawnSync(process.execPath, [harnessPath], {
    encoding: "utf8",
    env: {
      ...process.env,
      NEXT_PUBLIC_SUPABASE_ANON_KEY: "remote-test-key",
      NEXT_PUBLIC_SUPABASE_URL: "https://remote.invalid",
      SUPABASE_ANON_KEY: "remote-test-key",
      SUPABASE_SERVICE_ROLE_KEY: "remote-test-service-key",
      SUPABASE_URL: "https://remote.invalid",
    },
  });

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /Browser fixtures require local Supabase/u);
});
