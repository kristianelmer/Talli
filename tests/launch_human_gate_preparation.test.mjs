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
const consentProofMigration = readFileSync(
  new URL(
    "../supabase/migrations/20260829080345_marketing_measurement_consent_proof.sql",
    import.meta.url,
  ),
  "utf8",
);
const observationMigration = readFileSync(
  new URL(
    "../supabase/migrations/20260829074916_validation_observation_authority.sql",
    import.meta.url,
  ),
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
    /Private forced-RLS release and append-only action tables/u,
    /No release is approved or provisioned/u,
    /Backups, provider logs and recipients/u,
  ]) {
    assert.match(measurementDecision, required);
  }
  assert.match(measurementDecision, /pseudonymous\/personal pending/u);
  assert.match(measurementDecision, /must remain explicitly pending/iu);
  assert.match(measurementDecision, /not “anonym måling”/u);
  assert.match(measurementDecision, /require five distinct session hashes/u);
  assert.doesNotMatch(measurementDecision, /hosted facts (?:are|were) approved/iu);
});

test("consent proof remains exact-release-bound and inactive without human approval", () => {
  for (const required of [
    /create table backend_system\.marketing_measurement_releases/u,
    /create table backend_system\.marketing_consent_actions/u,
    /force row level security/u,
    /p_first_layer_notice_sha256/u,
    /p_privacy_notice_sha256/u,
    /p_release_sha256/u,
    /v_now \+ interval '30 minutes'/u,
    /status = 'approved'/u,
  ]) {
    assert.match(consentProofMigration, required);
  }

  assert.match(
    consentProofMigration,
    /No release is approved or activated by this migration/u,
  );
  assert.match(measurementDecision, /2026-08-30 notice cannot activate collection/u);
  assert.match(measurementDecision, /exact copy, retention and legal\/privacy activation remain pending/u);
});

test("validation plan links preparation without opening intake", () => {
  assert.match(validationPlan, /representative-validation-pre-intake-pack\.md/u);
  assert.match(validationPlan, /does not open this entry gate, claim #197 or authorize/u);
});

test("founder-approved pilot observation direction stays separate and fails closed for launch", () => {
  for (const required of [
    /Temporary Invited-Pilot Evaluation Mode/u,
    /only `off` and `invited-pilot` states/u,
    /server-side named pilot entitlement/u,
    /V-01` through `V-12/u,
    /must be disabled for full public launch/u,
    /there is no test-product branch/u,
    /sole permitted\s+difference is the additional bounded observation-log write/u,
    /at least 90% of core tasks/u,
  ]) {
    assert.match(measurementDecision, required);
  }

  for (const required of [
    /Temporary Higher-Resolution Observation Mode/u,
    /must not be\s+enabled by a URL, browser setting or client-supplied request field/u,
    /marketing\s+source attribution/u,
    /exact normal production product/u,
    /sole permitted difference/u,
    /proven `off` before full public launch/u,
  ]) {
    assert.match(validationPlan, required);
  }

  assert.match(preIntakePack, /Design approved; implementation\/activation blocked/u);
  assert.match(preIntakePack, /no public request can re-enable it/u);

  for (const required of [
    /mode text not null default 'off'/u,
    /create table backend_system\.validation_runs/u,
    /create table backend_system\.validation_pilot_entitlements/u,
    /validation_observation_entitlement_inactive/u,
    /validation_observation_launch_status_v1/u,
    /mode = 'off' and active_entitlements = 0/u,
  ]) {
    assert.match(observationMigration, required);
  }
  assert.match(
    observationMigration,
    /provisions no run, entitlement, reviewer, participant or event/u,
  );
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
