import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const component = readFileSync(
  new URL("../app/(operator)/operator/operator-mfa.tsx", import.meta.url),
  "utf8",
);
const page = readFileSync(new URL("../app/(operator)/operator/page.tsx", import.meta.url), "utf8");

test("operator MFA uses the signed-in browser session and official TOTP APIs", () => {
  assert.match(component, /"use client"/u);
  assert.match(component, /createBrowserClient/u);
  assert.match(component, /getAuthenticatorAssuranceLevel/u);
  assert.match(component, /listFactors/u);
  assert.match(component, /mfa\.enroll\(\{[\s\S]*factorType: "totp"/u);
  assert.match(component, /mfa\.challengeAndVerify/u);
  assert.doesNotMatch(component, /SERVICE_ROLE|service_role|dangerouslySetInnerHTML/u);
});

test("an existing AAL2 session can be re-verified after the freshness window expires", () => {
  assert.match(component, /mode === "verified"[\s\S]*Bekreft AAL2 på nytt/u);
  assert.ok(
    component.indexOf("const totpFactor") < component.indexOf('currentLevel === "aal2"'),
    "the enrolled factor must be loaded before rendering the verified state",
  );
});

test("the MFA surface is rendered only inside the existing admin operator boundary", () => {
  assert.match(page, /launchSignoffState\.isAdminOperator[\s\S]*<OperatorMfa/u);
  assert.match(page, /process\.env\.SUPABASE_URL/u);
  assert.match(page, /process\.env\.SUPABASE_ANON_KEY/u);
});
