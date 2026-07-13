import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  GENERIC_ACTION_ERROR,
  RF1086_RELEASE_SEALED_ACTION_ERROR,
  actionErrorMessage,
  encodeActionError,
  encodePublicActionError,
} from "../app/lib/action-errors.ts";

test("production redirects do not expose internal provider or database errors", () => {
  const internal = 'new row violates row-level security policy for table "company_memberships"';
  assert.equal(actionErrorMessage(internal, "internal", "production"), GENERIC_ACTION_ERROR);
});

test("the exact RF-1086 database seal becomes a fixed actionable production message", () => {
  const sealed = {
    code: "55000",
    message: "RF-1086 production release is temporarily sealed.",
    details: 'contains internal table "annual_data"',
  };

  assert.equal(
    decodeURIComponent(encodeActionError(sealed, "production")),
    RF1086_RELEASE_SEALED_ACTION_ERROR,
  );
});

test("near-miss database errors remain redacted in production", () => {
  assert.equal(
    decodeURIComponent(
      encodeActionError(
        { code: "55000", message: "A different object is temporarily sealed." },
        "production",
      ),
    ),
    GENERIC_ACTION_ERROR,
  );
  assert.equal(
    decodeURIComponent(
      encodeActionError(
        { code: "23505", message: "RF-1086 production release is temporarily sealed." },
        "production",
      ),
    ),
    GENERIC_ACTION_ERROR,
  );
  assert.equal(
    decodeURIComponent(
      encodeActionError("RF-1086 production release is temporarily sealed.", "production"),
    ),
    GENERIC_ACTION_ERROR,
  );
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
  assert.match(source, /encodeActionError\(uploadError\)/u);
  assert.match(source, /encodeActionError\(operatorError\)/u);
  assert.match(
    source,
    /document_metadata_persistence_failed[\s\S]*?encodeActionError\(metadataError\)/u,
  );
  assert.match(
    source,
    /owner_dividend_atomic_persistence_failed[\s\S]*?encodeActionError\(persistenceError\)/u,
  );
  assert.match(source, /encodePublicActionError\(error instanceof Error/u);
});
