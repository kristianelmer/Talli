import assert from "node:assert/strict";
import test from "node:test";

import {
  authorityObligationLabel,
  productionAuthorityGate,
  validateAuthorityObligation,
} from "../apps/web/app/lib/authority-permission.ts";

test("validates supported authority obligations", () => {
  assert.equal(validateAuthorityObligation("aksjonaerregisteroppgaven"), "aksjonaerregisteroppgaven");
  assert.equal(authorityObligationLabel("aarsregnskap"), "Årsregnskap");
  assert.throws(() => validateAuthorityObligation("mva"), /Ugyldig/);
});

test("blocks production submission when authority confirmation is missing", () => {
  const gate = productionAuthorityGate([], "aksjonaerregisteroppgaven");

  assert.equal(gate.status, "missing_authority_confirmation");
  assert.equal(gate.allowed, false);
});

test("blocks production submission when production gate is disabled", () => {
  const gate = productionAuthorityGate(
    [
      {
        obligation: "skattemelding",
        confirmed_at: "2026-01-01T00:00:00Z",
        production_enabled: false,
      },
    ],
    "skattemelding",
  );

  assert.equal(gate.status, "production_disabled");
  assert.equal(gate.allowed, false);
});

test("allows production submission only after confirmation and production enablement", () => {
  const gate = productionAuthorityGate(
    [
      {
        obligation: "aarsregnskap",
        confirmed_at: "2026-01-01T00:00:00Z",
        production_enabled: true,
      },
    ],
    "aarsregnskap",
  );

  assert.equal(gate.status, "ready_for_production_submission");
  assert.equal(gate.allowed, true);
});
