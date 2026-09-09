import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";


const actions = readFileSync(new URL("../apps/web/app/actions.ts", import.meta.url), "utf8");
const ownerPage = readFileSync(new URL("../apps/web/app/(owner)/filing/[obligation]/page.tsx", import.meta.url), "utf8");
const operatorPage = readFileSync(new URL("../apps/web/app/(operator)/operator/page.tsx", import.meta.url), "utf8");
const supabaseServer = readFileSync(new URL("../apps/web/app/lib/supabase/server.ts", import.meta.url), "utf8");
const systemUserFlow = readFileSync(new URL("../apps/web/app/lib/system-user-presentation.ts", import.meta.url), "utf8");
const ownerCopy = readFileSync(new URL("../apps/web/app/lib/copy.ts", import.meta.url), "utf8");

test("operator entitlement action is exact and database-authorized", () => {
  assert.match(actions, /export async function upsertProductionPilotEntitlement/u);
  assert.match(actions, /requiredFormUuid\(formData, "companyId"\)/u);
  assert.match(actions, /requiredFormUuid\(formData, "ownerUserId"\)/u);
  assert.match(actions, /getCurrentSessionAccessToken\(\)/u);
  assert.match(actions, /manageProductionPilotEntitlement\(accessToken, \{/u);
  assert.match(actions, /requiredFormUuid\(formData, "systemUserRequestId"\)/u);
  assert.match(actions, /systemUserRequestId,/u);
  assert.match(actions, /\}, operationId\);/u);
  assert.doesNotMatch(actions, /manage_production_pilot_entitlement/u);
  assert.doesNotMatch(actions, /p_system_user_external_reference/u);
  assert.match(operatorPage, /Eksakt RF-1086-produksjonspilot/u);
  assert.match(operatorPage, /name="systemUserRequestId"/u);
  assert.doesNotMatch(operatorPage, /name="systemUserExternalReference"/u);
  assert.doesNotMatch(operatorPage, /skattemelding.*produksjonspilot|årsregnskap.*produksjonspilot/iu);
});

test("owner approval binds persisted preview data and requires a real-filing acknowledgement", () => {
  assert.match(actions, /export async function approveProductionFiling/u);
  assert.match(actions, /realFilingConfirmed/u);
  assert.match(actions, /requireSensitiveActionStepUp\(supabase, user\.id, preview\.company_id, "production_filing"\)/u);
  assert.match(actions, /buildProductionApprovalManifest/u);
  assert.match(actions, /productionApprovalHash/u);
  assert.match(actions, /approve_production_filing/u);
  assert.match(ownerPage, /f\.production\.warning/u);
  assert.match(ownerPage, /f\.production\.approveCta/u);
  assert.match(ownerCopy, /juridiske konsekvenser/u);
  assert.match(ownerCopy, /Godkjenn innholdet/u);
});

test("send action carries only approval identity through the authenticated backend transport", () => {
  const sendAction = actions.slice(actions.indexOf("export async function sendApprovedRf1086ProductionFiling"),
    actions.indexOf("export async function reconcileRf1086ProductionAction"));
  assert.match(sendAction, /requiredFormUuid\(formData, "approvalId"\)/u);
  assert.match(sendAction, /getCurrentSessionAccessToken/u);
  assert.match(sendAction, /sendApprovedRf1086ThroughApi\(accessToken, approvalId\)/u);
  assert.doesNotMatch(sendAction, /privateKey|requestMaskinportenToken|\.from\(|\.rpc\(/u);
});

test("owner connection actions accept only local UUID selection and enforce fresh AAL2 before flow orchestration", () => {
  const ownerConnectionActions = actions.slice(
    actions.indexOf("export async function startSystemUserRequestAction"),
    actions.indexOf("const RF1086_PRODUCTION_ADAPTER_VERSION"),
  );
  assert.match(ownerConnectionActions, /export async function startSystemUserRequestAction/u);
  assert.match(ownerConnectionActions, /export async function refreshSystemUserRequestAction/u);
  assert.match(ownerConnectionActions, /requiredFormUuid\(formData, "companyId"\)/u);
  assert.match(ownerConnectionActions, /requiredFormUuid\(formData, "requestId"\)/u);
  assert.match(ownerConnectionActions, /randomUUID\(\)/u);
  assert.match(ownerConnectionActions, /requireSensitiveActionStepUp\([\s\S]{0,160}"system_user_connection"\)/u);
  assert.match(ownerConnectionActions, /startOwnerSystemUserRequest/u);
  assert.match(systemUserFlow, /talli_system_user_request/u);
  assert.match(systemUserFlow, /httpOnly:\s*true/u);
  assert.match(systemUserFlow, /secure:\s*true/u);
  assert.match(systemUserFlow, /sameSite:\s*"lax"/u);
  assert.match(systemUserFlow, /path:\s*"\/auth\/systembruker\/confirm"/u);
  assert.match(systemUserFlow, /maxAge:\s*3600/u);
  assert.doesNotMatch(ownerConnectionActions, /formString\(formData, "(?:orgNumber|ownerId|externalRef|altinnRequestId)"\)/u);
});

test("production UI never equates receipt transport with final acceptance", () => {
  assert.match(ownerPage, /buildRf1086OwnerProductionPresentation/u);
  assert.match(ownerPage, /productionPresentation\.status\.label/u);
  assert.match(ownerCopy, /Mottatt/u);
  assert.match(ownerCopy, /Til behandling/u);
  assert.match(ownerCopy, /mottakskvittering betyr ikke at innholdet er endelig godkjent/u);
  assert.doesNotMatch(ownerPage, /\{productionSubmission\?\.feedback_state\}|\{artifact\.classification\}/u);
});

test("a disabled production adapter tolerates an unapplied additive schema during rollout", () => {
  assert.match(supabaseServer, /function productionPilotSchemaUnavailable/u);
  assert.match(supabaseServer, /TALLI_RF1086_PRODUCTION_ENABLED !== "true"/u);
  assert.match(supabaseServer, /PGRST205|42P01/u);
});
