import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const actions = readFileSync(new URL("../app/actions.ts", import.meta.url), "utf8");
const authorityAction = actions.slice(
  actions.indexOf("export async function runProductionAuthorityOperation"),
  actions.indexOf("const RF1086_PRODUCTION_ADAPTER_VERSION"),
);
const operatorPage = readFileSync(
  new URL("../app/(operator)/operator/page.tsx", import.meta.url),
  "utf8",
);
const server = readFileSync(new URL("../app/lib/supabase/server.ts", import.meta.url), "utf8");

test("authority operation is admin-only, AAL2-gated, exact, and service-audited", () => {
  assert.match(actions, /export async function runProductionAuthorityOperation/u);
  assert.match(actions, /eq\("role", "admin"\)/u);
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
  assert.match(server, /eq\("role", "admin"\)/u);
  assert.match(server, /from\("authority_operations"\)/u);
  assert.match(server, /order\("created_at", \{ ascending: false \}\)\.limit\(10\)/u);
  assert.doesNotMatch(server, /private_key|access_token|assertion/iu);
});
