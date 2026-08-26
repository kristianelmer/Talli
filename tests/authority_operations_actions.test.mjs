import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const actions = readFileSync(new URL("../apps/web/app/actions.ts", import.meta.url), "utf8");
const authorityAction = actions.slice(
  actions.indexOf("export async function runProductionAuthorityOperation"),
  actions.indexOf("export async function runProductionSystembrukerCallbackOperation"),
);
const callbackAction = actions.slice(
  actions.indexOf("export async function runProductionSystembrukerCallbackOperation"),
  actions.indexOf("function systemUserConnectionTarget"),
);
const operatorPage = readFileSync(
  new URL("../apps/web/app/(operator)/operator/page.tsx", import.meta.url),
  "utf8",
);
const copy = readFileSync(new URL("../apps/web/app/lib/copy.ts", import.meta.url), "utf8");
const server = readFileSync(new URL("../apps/web/app/lib/supabase/server.ts", import.meta.url), "utf8");
const authorityQuery = server.slice(
  server.indexOf("export async function listAuthorityOperations"),
  server.indexOf("export async function searchOperatorSupportDashboard"),
);

test("authority operation is admin-only, AAL2-gated, exact, and service-audited", () => {
  assert.match(actions, /export async function runProductionAuthorityOperation/u);
  assert.match(authorityAction, /loadAuthorizedSupportOperator\(\)/u);
  assert.match(authorityAction, /operator\.role !== "admin"/u);
  assert.doesNotMatch(authorityAction, /from\("support_operators"\)/u);
  assert.match(actions, /assertStepUpAllowed\("authority_operations"/u);
  assert.match(actions, /assertAuthorityOperationIntent/u);
  assert.match(actions, /authorityOperationEnvironmentFailureCode/u);
  assert.match(actions, /createSupabaseServiceRoleClient/u);
  assert.match(actions, /from\("authority_operations"\)\.insert/u);
  assert.match(actions, /executeRf1086SystemRegistration/u);
  assert.doesNotMatch(authorityAction, /accessToken|privateKeyPem/iu);
});

test("operator UI exposes only the immutable RF-1086 operation and redacted results", () => {
  assert.match(operatorPage, /930835978_talli/u);
  assert.match(operatorPage, /ske-innrapportering-aksjonaerregisteroppgave/u);
  assert.match(operatorPage, /REGISTER TALLI RF1086 SYSTEM/u);
  assert.match(operatorPage, /Maskinporten-klient-ID-en er ugyldig/u);
  assert.match(operatorPage, /Maskinporten-nøkkel-ID-en er ugyldig/u);
  assert.match(operatorPage, /Maskinporten-privatnøkkelen er ugyldig/u);
  assert.match(operatorPage, /runProductionAuthorityOperation/u);
  assert.match(server, /listAuthorityOperations/u);
  assert.doesNotMatch(operatorPage, /private key|access token/iu);
});

test("the server query is limited to recent redacted rows for active admins", () => {
  assert.match(authorityQuery, /backendOperatorSession\(supabase\)/u);
  assert.match(authorityQuery, /operator\.role !== "admin"/u);
  assert.doesNotMatch(authorityQuery, /from\("support_operators"\)/u);
  assert.match(authorityQuery, /from\("authority_operations"\)/u);
  assert.match(authorityQuery, /order\("created_at", \{ ascending: false \}\)\.limit\(10\)/u);
  assert.doesNotMatch(authorityQuery, /private_key|access_token|assertion/iu);
});

test("callback update has a separate admin, fresh-AAL2, ops-gated audited action", () => {
  assert.match(actions, /export async function runProductionSystembrukerCallbackOperation/u);
  assert.match(callbackAction, /loadAuthorizedSupportOperator\(\)/u);
  assert.match(callbackAction, /operator\.role !== "admin"/u);
  assert.doesNotMatch(callbackAction, /from\("support_operators"\)/u);
  assert.match(callbackAction, /assertStepUpAllowed\("authority_operations"/u);
  assert.match(callbackAction, /assertSystembrukerCallbackOperationIntent/u);
  assert.match(callbackAction, /productionAuthorityOperationEnvironment/u);
  assert.match(callbackAction, /SYSTEMBRUKER_CALLBACK_OPERATION/u);
  assert.match(callbackAction, /executeRf1086SystembrukerCallbackUpdate/u);
  assert.match(callbackAction, /from\("authority_operations"\)\.insert/u);
  assert.match(callbackAction, /callbackPath: SYSTEMBRUKER_CALLBACK_PATH/u);
  assert.match(actions, /case "authority_verification_error"/u);
  assert.match(operatorPage, /authority_verification_error/u);
  assert.doesNotMatch(callbackAction, /clientId:|right:|accessToken|privateKeyPem|response\.body/iu);
});

test("operator callback UI is native, exact, and honest about its narrow effect", () => {
  assert.match(operatorPage, /runProductionSystembrukerCallbackOperation/u);
  assert.match(operatorPage, /operatorAuthorityCopy\.systembrukerCallback/u);
  assert.match(
    operatorPage,
    /name="operation"[\s\S]*value="set_rf1086_systembruker_callback"/u,
  );
  assert.match(operatorPage, /<label[\s\S]*name="confirmation"[\s\S]*<\/label>/u);
  assert.match(copy, /SET TALLI SYSTEMBRUKER CALLBACK/u);
  assert.match(copy, /https:\/\/talli\.no\/auth\/systembruker\/confirm/u);
  assert.match(copy, /bare den faste callback-adressen/iu);
  assert.match(copy, /oppretter ikke en Systembruker/iu);
  assert.match(copy, /åpner ikke for produksjonsinnsending/iu);
});
