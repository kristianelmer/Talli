import assert from "node:assert/strict";
import test from "node:test";

import { sanitizeInternalRedirect } from "../app/lib/internal-redirect.ts";

test("invitation login continuation accepts only same-origin absolute paths", () => {
  assert.equal(
    sanitizeInternalRedirect("/invite/accept?token=one%20two"),
    "/invite/accept?token=one%20two",
  );
  assert.equal(sanitizeInternalRedirect("//attacker.example/invite"), "/dashboard");
  assert.equal(sanitizeInternalRedirect("https://attacker.example/invite"), "/dashboard");
  assert.equal(sanitizeInternalRedirect("/\\attacker.example/invite"), "/dashboard");
  assert.equal(sanitizeInternalRedirect("/invite\n/accept"), "/dashboard");
});
