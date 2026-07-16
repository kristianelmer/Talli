import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import * as rf1086Production from "../app/lib/rf1086-production.ts";

const actions = readFileSync(new URL("../app/actions.ts", import.meta.url), "utf8");
const ownerPage = readFileSync(new URL("../app/(owner)/filing/[obligation]/page.tsx", import.meta.url), "utf8");
const operatorPage = readFileSync(new URL("../app/(operator)/operator/page.tsx", import.meta.url), "utf8");
const supabaseServer = readFileSync(new URL("../app/lib/supabase/server.ts", import.meta.url), "utf8");
const systemUserFlow = readFileSync(new URL("../app/lib/system-user-flow.ts", import.meta.url), "utf8");

test("operator entitlement action is exact and database-authorized", () => {
  assert.match(actions, /export async function upsertProductionPilotEntitlement/u);
  assert.match(actions, /requiredFormUuid\(formData, "companyId"\)/u);
  assert.match(actions, /requiredFormUuid\(formData, "ownerUserId"\)/u);
  assert.match(actions, /manage_production_pilot_entitlement/u);
  assert.match(actions, /requiredFormUuid\(formData, "systemUserRequestId"\)/u);
  assert.match(actions, /p_system_user_request_id:\s*systemUserRequestId/u);
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
  assert.match(ownerPage, /juridiske konsekvenser/u);
  assert.match(ownerPage, /Godkjenn eksakt innhold/u);
});

test("send action rechecks approval, uses production-only credentials, and journals authority calls", () => {
  const sendAction = actions.slice(
    actions.indexOf("export async function sendApprovedRf1086ProductionFiling"),
    actions.indexOf("export async function postManualJournal"),
  );
  assert.match(actions, /export async function sendApprovedRf1086ProductionFiling/u);
  assert.match(actions, /approvalMatchesCurrentPayload/u);
  assert.match(actions, /rf1086ProductionEnvironment\(\)/u);
  assert.match(actions, /requestMaskinportenToken/u);
  assert.match(actions, /begin_production_filing/u);
  assert.match(actions, /entitlement\.system_user_request_id/u);
  assert.match(actions, /from\("system_user_requests"\)/u);
  assert.match(actions, /systemUserRequest\.company_id !== approval\.company_id/u);
  assert.match(actions, /systemUserRequest\.initiating_owner_user_id !== user\.id/u);
  assert.match(actions, /systemUserRequest\.obligation !== approval\.obligation/u);
  assert.match(actions, /systemUserRequest\.status !== "accepted"/u);
  assert.match(actions, /!systemUserRequest\.preflight_verified_at/u);
  assert.match(actions, /systemUserRequest\.external_ref !== entitlement\.system_user_external_reference/u);
  assert.match(actions, /systemUserExternalRef:\s*systemUserRequest\.external_ref/u);
  assert.match(actions, /createSupabaseServiceRoleClient/u);
  assert.ok(
    sendAction.indexOf("createSupabaseServiceRoleClient()") < sendAction.indexOf("requestMaskinportenToken({"),
    "service-role journal configuration must fail before a sending row is created",
  );
  assert.ok(
    sendAction.indexOf("requestMaskinportenToken({") < sendAction.indexOf('rpc("begin_production_filing"'),
    "delegated-token acquisition must fail before a sending row can be created",
  );
  assert.ok(
    sendAction.indexOf('rpc("begin_production_filing"') < sendAction.indexOf("executeJournaledRf1086Production({"),
    "all external submission mutations must remain after the durable release gate",
  );
  assert.match(actions, /order\("created_at", \{ ascending: false \}\)[\s\S]{0,100}limit\(1\)/u);
  assert.match(actions, /retryableFailure = latest\.operation_state === "failed"[\s\S]{0,80}latest\.failure_class === "retryable"/u);
  assert.match(actions, /latest\.attempt >= 20/u);
  assert.match(actions, /latest\.attempt \+ 1/u);
  assert.match(actions, /executeJournaledRf1086Production/u);
  assert.match(actions, /environment: "production"/u);
  assert.doesNotMatch(actions, /executeJournaledRf1086Production[\s\S]{0,1200}environment: "test"/u);
});

test("production release does not begin or submit when delegated-token acquisition fails", async () => {
  const events = [];
  await assert.rejects(
    () => rf1086Production.executeRf1086ProductionRelease({
      async acquireDelegatedToken() {
        events.push("token");
        throw new Error("token unavailable");
      },
      async beginProductionFiling() {
        events.push("begin");
        return { id: "submission" };
      },
      async executeExternalSubmission() {
        events.push("post");
      },
      discardToken() {
        events.push("discard");
      },
    }),
    /token unavailable/u,
  );
  assert.deepEqual(events, ["token"]);
});

test("production release makes no POST when transactional begin rejects after token acquisition", async () => {
  const events = [];
  const token = { accessToken: "opaque" };
  await assert.rejects(
    () => rf1086Production.executeRf1086ProductionRelease({
      async acquireDelegatedToken() {
        events.push("token");
        return token;
      },
      async beginProductionFiling() {
        events.push("begin");
        throw new Error("request invalidated");
      },
      async executeExternalSubmission() {
        events.push("post");
      },
      discardToken(value) {
        events.push("discard");
        value.accessToken = "";
      },
    }),
    /request invalidated/u,
  );
  assert.deepEqual(events, ["token", "begin", "discard"]);
  assert.equal(token.accessToken, "");
});

test("production release orders token, durable begin, then journaled external submission", async () => {
  const events = [];
  const result = await rf1086Production.executeRf1086ProductionRelease({
    async acquireDelegatedToken() {
      events.push("token");
      return { accessToken: "opaque" };
    },
    async beginProductionFiling() {
      events.push("begin");
      return { id: "submission" };
    },
    async executeExternalSubmission({ submission }) {
      events.push("post");
      assert.equal(submission.id, "submission");
    },
    discardToken(token) {
      events.push("discard");
      token.accessToken = "";
    },
  });
  assert.deepEqual(events, ["token", "begin", "post", "discard"]);
  assert.equal(result.id, "submission");
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
  assert.match(systemUserFlow, /begin_system_user_request/u);
  assert.match(systemUserFlow, /talli_system_user_request/u);
  assert.match(systemUserFlow, /httpOnly:\s*true/u);
  assert.match(systemUserFlow, /secure:\s*true/u);
  assert.match(systemUserFlow, /sameSite:\s*"lax"/u);
  assert.match(systemUserFlow, /path:\s*"\/auth\/systembruker\/confirm"/u);
  assert.match(systemUserFlow, /maxAge:\s*3600/u);
  assert.doesNotMatch(ownerConnectionActions, /formString\(formData, "(?:orgNumber|ownerId|externalRef|altinnRequestId)"\)/u);
});

test("production UI never equates receipt transport with final acceptance", () => {
  assert.match(ownerPage, /Mottatt/u);
  assert.match(ownerPage, /Til behandling/u);
  assert.match(ownerPage, /HTTP-svar eller kvitteringsreferanse betyr ikke/u);
  assert.match(ownerPage, /productionFeedbackState === "accepted" \? "Godkjent"/u);
  assert.match(ownerPage, /productionSubmission\?\.status === "sending" \? "Sender"/u);
  assert.match(ownerPage, /productionFeedbackState === "action_required" \? "Krever handling"/u);
});

test("a disabled production adapter tolerates an unapplied additive schema during rollout", () => {
  assert.match(supabaseServer, /function productionPilotSchemaUnavailable/u);
  assert.match(supabaseServer, /TALLI_RF1086_PRODUCTION_ENABLED !== "true"/u);
  assert.match(supabaseServer, /PGRST205|42P01/u);
});
