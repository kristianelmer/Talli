import assert from "node:assert/strict";
import test from "node:test";
import { normalizeMfaFactorId, normalizeTotpCode, totpQrCodeDataUrl } from "../app/lib/mfa.ts";

test("normalizes human-entered TOTP codes and rejects malformed input", () => {
  assert.equal(normalizeTotpCode("123 456"), "123456");
  assert.equal(normalizeTotpCode("123-456"), "123456");
  assert.throws(() => normalizeTotpCode("12345"), /seks sifre/);
  assert.throws(() => normalizeTotpCode("12345a"), /seks sifre/);
});

test("accepts only UUID factor identifiers", () => {
  assert.equal(
    normalizeMfaFactorId("34e770dd-9ff9-416c-87fa-43b31d7ef225"),
    "34e770dd-9ff9-416c-87fa-43b31d7ef225",
  );
  assert.throws(() => normalizeMfaFactorId("factor-from-client"), /Ugyldig MFA-faktor/);
});

test("encodes Supabase SVG enrollment data without double-prefixing data URLs", () => {
  assert.equal(
    totpQrCodeDataUrl("<svg><path /></svg>"),
    "data:image/svg+xml;utf-8,%3Csvg%3E%3Cpath%20%2F%3E%3C%2Fsvg%3E",
  );
  const existing = "data:image/svg+xml;utf-8,%3Csvg%2F%3E";
  assert.equal(totpQrCodeDataUrl(existing), existing);
});
