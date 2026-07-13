import assert from "node:assert/strict";
import test from "node:test";

import {
  MAX_SIGNUP_PASSWORD_LENGTH,
  MIN_SIGNUP_PASSWORD_LENGTH,
  validateSignupPassword,
} from "../app/lib/auth-input.ts";

test("signup password policy accepts passphrases without composition rules", () => {
  const password = "fire rolige ord sammen";
  assert.equal(validateSignupPassword(password), password);
});

test("signup password policy rejects short and unbounded inputs", () => {
  assert.throws(() => validateSignupPassword("x".repeat(MIN_SIGNUP_PASSWORD_LENGTH - 1)), /minst 12 tegn/);
  assert.throws(() => validateSignupPassword("x".repeat(MAX_SIGNUP_PASSWORD_LENGTH + 1)), /maksimalt 128 tegn/);
});

test("password validation preserves leading and trailing characters", () => {
  const password = "  leading and trailing  ";
  assert.equal(validateSignupPassword(password), password);
});
