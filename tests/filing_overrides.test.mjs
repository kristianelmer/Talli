import assert from "node:assert/strict";
import test from "node:test";

import { assertNoBlockingFilingOverrides, validateFilingOverride } from "../apps/web/app/lib/filing-overrides.ts";

test("validates advisory filing override fields", () => {
  const override = validateFilingOverride({
    fieldTarget: "rf1086.transaction_code",
    oldValue: "U",
    newValue: "K",
    reason: "Authority field not modelled yet",
    riskLevel: "advisory",
  });

  assert.deepEqual(override, {
    fieldTarget: "rf1086.transaction_code",
    oldValue: "U",
    newValue: "K",
    reason: "Authority field not modelled yet",
    riskLevel: "advisory",
  });
});

test("requires reason, target, value, and known risk level", () => {
  assert.throws(
    () =>
      validateFilingOverride({
        fieldTarget: "",
        oldValue: "",
        newValue: "K",
        reason: "Authority field not modelled yet",
        riskLevel: "advisory",
      }),
    /Feltmål/,
  );
  assert.throws(
    () =>
      validateFilingOverride({
        fieldTarget: "rf1086.transaction_code",
        oldValue: "",
        newValue: "",
        reason: "Authority field not modelled yet",
        riskLevel: "advisory",
      }),
    /Gammel eller ny verdi/,
  );
  assert.throws(
    () =>
      validateFilingOverride({
        fieldTarget: "rf1086.transaction_code",
        oldValue: "U",
        newValue: "K",
        reason: "",
        riskLevel: "advisory",
      }),
    /Begrunnelse/,
  );
  assert.throws(
    () =>
      validateFilingOverride({
        fieldTarget: "rf1086.transaction_code",
        oldValue: "U",
        newValue: "K",
        reason: "Authority field not modelled yet",
        riskLevel: "unknown",
      }),
    /Ugyldig risikonivå/,
  );
});

test("block overrides stop simulated submission gate", () => {
  assert.doesNotThrow(() =>
    assertNoBlockingFilingOverrides([
      { risk_level: "advisory", field_target: "rf1086.note" },
      { risk_level: "warning", field_target: "rf1086.memo" },
    ]),
  );
  assert.throws(
    () => assertNoBlockingFilingOverrides([{ risk_level: "block", field_target: "rf1086.transaction_code" }]),
    /Blokkerende filing-overstyring/,
  );
});
