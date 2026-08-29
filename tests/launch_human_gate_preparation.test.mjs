import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const measurementDecision = readFileSync(
  new URL("../docs/legal/marketing-measurement-decision-draft.md", import.meta.url),
  "utf8",
);
const validationPlan = readFileSync(
  new URL("../docs/launch/representative-validation-2-plus-8-plan.md", import.meta.url),
  "utf8",
);
const preIntakePack = readFileSync(
  new URL("../docs/launch/representative-validation-pre-intake-pack.md", import.meta.url),
  "utf8",
);

test("measurement decision inventories application-controlled data without hosted overclaims", () => {
  for (const required of [
    /talli\.marketing-consent\.v1/u,
    /talli\.marketing-withdrawal\.v1/u,
    /clientEventId/u,
    /2,048 bytes/u,
    /SHA-256/u,
    /marketing_funnel_events/u,
    /90 days/u,
    /marketing_funnel_withdrawals/u,
    /30 minutes/u,
    /There is no separate durable consent-action record/u,
    /Backups, provider logs and recipients/u,
  ]) {
    assert.match(measurementDecision, required);
  }
  assert.match(measurementDecision, /pseudonymous\/personal pending/u);
  assert.match(measurementDecision, /must remain explicitly pending/iu);
  assert.match(measurementDecision, /not “anonym måling”/u);
  assert.doesNotMatch(measurementDecision, /hosted facts (?:are|were) approved/iu);
});

test("validation plan links preparation without opening intake", () => {
  assert.match(validationPlan, /representative-validation-pre-intake-pack\.md/u);
  assert.match(validationPlan, /does not open this entry gate, claim #197 or authorize/u);
});

test("pre-intake pack stays blank, protected-store-first and fail closed", () => {
  for (const required of [
    /#197 is unclaimed/u,
    /Do not put a person's name/u,
    /human-controlled\s+protected store/u,
    /Git\/issues\/chat are forbidden stores/u,
    /V-01.*V-12/us,
    /talli-defect/u,
    /source-defect/u,
    /presentation-only/u,
    /unresolved-judgment/u,
    /at least 90%/u,
    /median support below 30 minutes/u,
    /Automatic Stop Rules/u,
  ]) {
    assert.match(preIntakePack, required);
  }
  assert.match(preIntakePack, /Blocked — issue open \/ ready-for-human/u);
  assert.match(preIntakePack, /Blocked by #189 external A9/u);
  assert.match(preIntakePack, /No recruitment, outreach, named-company intake/u);
  assert.doesNotMatch(preIntakePack, /Kristian Bollæren Ellefsen Elmer/u);
  assert.doesNotMatch(preIntakePack, /930835978|930 835 978/u);
});
