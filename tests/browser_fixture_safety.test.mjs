import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";

import {
  isLoopbackPostgresUrl,
  isLoopbackSupabaseUrl,
} from "./support/supabase_fixture_safety.mjs";

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

test("browser database fixtures only accept loopback PostgreSQL URLs", () => {
  for (const value of [
    "postgres://postgres:postgres@127.0.0.1:54322/postgres",
    "postgresql://postgres:postgres@localhost:54322/postgres",
    "postgresql://postgres:postgres@[::1]:54322/postgres",
  ]) {
    assert.equal(isLoopbackPostgresUrl(value), true, value);
  }

  for (const value of [
    "postgresql://postgres:secret@database.example.com/postgres",
    "postgresql://postgres:secret@localhost.example.com/postgres",
    "https://localhost:54322/postgres",
    "not-a-url",
  ]) {
    assert.equal(isLoopbackPostgresUrl(value), false, value);
  }
});

test("owner browser harness stops before remote fixture creation", () => {
  const harnessPath = fileURLToPath(
    new URL("./browser_owner_annual_loop.mjs", import.meta.url),
  );
  const env = {
    ...process.env,
    DATABASE_URL: "postgresql://postgres:postgres@127.0.0.1:54322/postgres",
    NEXT_PUBLIC_SUPABASE_ANON_KEY: "remote-test-key",
    NEXT_PUBLIC_SUPABASE_URL: "https://remote.invalid",
    SUPABASE_ANON_KEY: "remote-test-key",
    SUPABASE_SERVICE_ROLE_KEY: "remote-test-service-key",
    SUPABASE_URL: "https://remote.invalid",
  };
  delete env.NODE_TEST_CONTEXT;
  const result = spawnSync(process.execPath, [harnessPath], {
    encoding: "utf8",
    env,
  });

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /Browser fixtures require local Supabase/u);
});

test("owner browser harness rejects a remote database mixed with local Supabase", () => {
  const harnessPath = fileURLToPath(
    new URL("./browser_owner_annual_loop.mjs", import.meta.url),
  );
  const env = {
    ...process.env,
    DATABASE_URL:
      "postgresql://postgres:secret@database.example.invalid/postgres",
    NEXT_PUBLIC_SUPABASE_ANON_KEY: "local-test-key",
    NEXT_PUBLIC_SUPABASE_URL: "http://127.0.0.1:54321",
    SUPABASE_ANON_KEY: "local-test-key",
    SUPABASE_SERVICE_ROLE_KEY: "local-test-service-key",
    SUPABASE_URL: "http://127.0.0.1:54321",
  };
  delete env.NODE_TEST_CONTEXT;
  const result = spawnSync(process.execPath, [harnessPath], {
    encoding: "utf8",
    env,
  });

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /Browser fixtures require local database/u);
});
