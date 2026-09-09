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
  server.indexOf("export async function readOperatorSupportDashboard"),
);

test("authority actions carry exact intent to the authenticated backend without web audit or credentials", () => {
  const flow = actions.slice(actions.indexOf("async function runExistingAuthorityOperation"), actions.indexOf("function systemUserConnectionTarget"));
  assert.match(flow, /loadAuthorizedSupportOperator\(\)/u);
  assert.match(flow, /operator\.role !== "admin"/u);
  assert.match(flow, /assertStepUpAllowed\("authority_operations"/u);
  assert.match(flow, /runAuthorityOperation\(accessToken/u);
  assert.match(flow, /operationId: randomUUID\(\)/u);
  assert.doesNotMatch(flow, /\.from\(|\.rpc\(|createSupabaseServiceRoleClient|privateKey|requestMaskinporten|executeRf1086/u);
  assert.match(authorityAction, /runExistingAuthorityOperation\(formData, "register_rf1086_system"\)/u);
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

test("operator audit history uses generated transport and retains current-admin UI visibility", () => {
  assert.match(authorityQuery, /backendOperatorSession\(supabase\)/u);
  assert.match(authorityQuery, /operator\.role !== "admin"/u);
  assert.match(authorityQuery, /loadAuthorityOperations\(token\)/u);
  assert.doesNotMatch(authorityQuery, /\.from\(|\.rpc\(|private_key|assertion/iu);
});

test("callback operation carries only its fixed action identity through the shared transport", () => {
  assert.match(callbackAction, /runExistingAuthorityOperation\(formData, "set_rf1086_systembruker_callback"\)/u);
  assert.match(operatorPage, /authority_verification_error/u);
  assert.doesNotMatch(callbackAction, /clientId:|right:|privateKeyPem|response\.body|\.from\(/iu);
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
