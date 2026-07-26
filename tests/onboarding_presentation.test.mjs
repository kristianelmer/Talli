import assert from "node:assert/strict";
import test from "node:test";

import {
  selectOnboardingPhase,
  shouldRedirectReturningOwner,
} from "../apps/web/app/lib/onboarding-presentation.ts";

test("a returning owner with a company lookup error stays on the lookup phase", () => {
  const input = {
    hasCompany: true,
    hasSetup: true,
    hasError: true,
  };

  assert.equal(shouldRedirectReturningOwner(input), false);
  assert.equal(selectOnboardingPhase(input), "lookup");
});

test("ordinary returning owners still enter their existing workspace", () => {
  const input = {
    hasCompany: true,
    hasSetup: true,
    hasError: false,
  };

  assert.equal(shouldRedirectReturningOwner(input), true);
  assert.equal(selectOnboardingPhase(input), "bank");
});

test("bank-step errors remain on the bank phase", () => {
  const input = {
    hasCompany: true,
    hasSetup: true,
    hasError: true,
    step: "bank",
  };

  assert.equal(shouldRedirectReturningOwner(input), false);
  assert.equal(selectOnboardingPhase(input), "bank");
});
