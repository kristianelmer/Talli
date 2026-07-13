import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  GENERIC_ACTION_ERROR,
  actionErrorMessage,
  encodePublicActionError,
} from "../app/lib/action-errors.ts";

test("production redirects do not expose internal provider or database errors", () => {
  const internal = 'new row violates row-level security policy for table "company_memberships"';
  assert.equal(actionErrorMessage(internal, "internal", "production"), GENERIC_ACTION_ERROR);
});

test("trusted domain validation remains actionable and URL encoded", () => {
  const message = "Aksjene må avstemmes før innsending.";
  assert.equal(actionErrorMessage(message, "public", "production"), message);
  assert.equal(decodeURIComponent(encodePublicActionError(message)), message);
});

test("development retains bounded diagnostics without creating oversized redirects", () => {
  const longMessage = `provider: ${"x".repeat(700)}`;
  assert.equal(actionErrorMessage(longMessage, "internal", "development").length, 500);
});

test("server actions route dynamic errors through the disclosure boundary", async () => {
  const source = await readFile("app/actions.ts", "utf8");
  assert.doesNotMatch(source, /encodeURIComponent\(/u);
  assert.match(source, /encodeActionError\(uploadError\.message\)/u);
  assert.match(source, /encodeActionError\(operatorError\.message\)/u);
  assert.match(source, /encodePublicActionError\(error instanceof Error/u);
});
