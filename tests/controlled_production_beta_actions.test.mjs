import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const actions = readFileSync(new URL("../app/actions.ts", import.meta.url), "utf8");
const ownerPage = readFileSync(new URL("../app/(owner)/filing/[obligation]/page.tsx", import.meta.url), "utf8");
const operatorPage = readFileSync(new URL("../app/(operator)/operator/page.tsx", import.meta.url), "utf8");

test("operator entitlement action is exact and database-authorized", () => {
  assert.match(actions, /export async function upsertProductionPilotEntitlement/u);
  assert.match(actions, /requiredFormUuid\(formData, "companyId"\)/u);
  assert.match(actions, /requiredFormUuid\(formData, "ownerUserId"\)/u);
  assert.match(actions, /manage_production_pilot_entitlement/u);
  assert.match(actions, /p_system_user_external_reference/u);
  assert.match(operatorPage, /Eksakt RF-1086-produksjonspilot/u);
  assert.doesNotMatch(operatorPage, /skattemelding.*produksjonspilot|årsregnskap.*produksjonspilot/iu);
});

test("owner approval binds persisted preview data and requires a real-filing acknowledgement", () => {
  assert.match(actions, /export async function approveProductionFiling/u);
  assert.match(actions, /realFilingConfirmed/u);
  assert.match(actions, /requireSensitiveActionStepUp\(supabase, user\.id, preview\.company_id, "production_filing"\)/u);
  assert.match(actions, /buildProductionApprovalManifest/u);
  assert.match(actions, /productionApprovalHash/u);
  assert.match(actions, /approve_production_filing/u);
  assert.match(ownerPage, /juridiske konsekvenser/u);
  assert.match(ownerPage, /Godkjenn eksakt innhold/u);
});

test("send action rechecks approval, uses production-only credentials, and journals authority calls", () => {
  assert.match(actions, /export async function sendApprovedRf1086ProductionFiling/u);
  assert.match(actions, /approvalMatchesCurrentPayload/u);
  assert.match(actions, /rf1086ProductionEnvironment\(\)/u);
  assert.match(actions, /requestMaskinportenToken/u);
  assert.match(actions, /begin_production_filing/u);
  assert.match(actions, /createSupabaseServiceRoleClient/u);
  assert.match(actions, /executeJournaledRf1086Production/u);
  assert.match(actions, /environment: "production"/u);
  assert.doesNotMatch(actions, /executeJournaledRf1086Production[\s\S]{0,1200}environment: "test"/u);
});

test("production UI never equates receipt transport with final acceptance", () => {
  assert.match(ownerPage, /Mottatt/u);
  assert.match(ownerPage, /Til behandling/u);
  assert.match(ownerPage, /HTTP-svar eller kvitteringsreferanse betyr ikke/u);
  assert.match(ownerPage, /productionSubmission\?\.status === "accepted" \? "Godkjent"/u);
});
