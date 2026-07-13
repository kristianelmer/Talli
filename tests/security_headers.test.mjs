import assert from "node:assert/strict";
import test from "node:test";

import nextConfig, { applicationSecurityHeaders } from "../next.config.ts";

test("all application routes receive restrictive browser security headers", async () => {
  const configured = await nextConfig.headers();
  assert.equal(configured.length, 1);
  assert.equal(configured[0].source, "/(.*)");

  const headers = Object.fromEntries(applicationSecurityHeaders.map(({ key, value }) => [key, value]));
  assert.equal(headers["X-Content-Type-Options"], "nosniff");
  assert.equal(headers["X-Frame-Options"], "DENY");
  assert.match(headers["Permissions-Policy"], /camera=\(\)/u);
  assert.match(headers["Content-Security-Policy"], /default-src 'self'/u);
  assert.match(headers["Content-Security-Policy"], /frame-ancestors 'none'/u);
  assert.match(headers["Content-Security-Policy"], /object-src 'none'/u);
  assert.match(headers["Content-Security-Policy"], /connect-src 'self' https:\/\/\*\.supabase\.co wss:\/\/\*\.supabase\.co/u);
  assert.doesNotMatch(headers["Content-Security-Policy"], /unsafe-eval/u);
});
