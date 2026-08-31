import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("..", import.meta.url);

async function source(path) {
  return readFile(new URL(path, root), "utf8");
}

test("capability owns immutable business request contracts", async () => {
  const capability = await source("apps/backend/src/talli_backend/modules/company_access/public.py");
  const main = await source("apps/backend/src/talli_backend/main.py");

  for (const contract of [
    "CreateCompanyInvitationRequest",
    "InvitationTokenRequest",
    "CompanyInvitationCommandRequest",
    "AdministerCompanyMembershipRequest",
  ]) {
    assert.match(capability, new RegExp(`class ${contract}\\(`));
    assert.doesNotMatch(main, new RegExp(`class ${contract}\\(`));
  }
  assert.match(capability, /ConfigDict\([\s\S]*frozen=True[\s\S]*extra="forbid"/u);
});

test("every invitation decoder rejects unknown and token-shaped response fields", async () => {
  const generator = await source("scripts/generate-api-client.mjs");
  const webTest = await source("apps/web/tests/company-access-administration.test.mjs");

  assert.match(generator, /Object\.keys\(value\)/u);
  assert.match(generator, /allowedProperties/u);
  for (const leaked of ["tokenHash", "token_hash", "deliveryTokenHash", "acceptanceToken"]) {
    assert.match(webTest, new RegExp(leaked));
  }
});

test("all company-access success responses declare X-Request-ID", async () => {
  const contract = JSON.parse(await source("contracts/openapi/talli-v1.json"));
  for (const [path, item] of Object.entries(contract.paths)) {
    if (!path.startsWith("/api/v1/company-access/")) continue;
    for (const operation of Object.values(item)) {
      for (const [status, response] of Object.entries(operation.responses)) {
        if (!status.startsWith("2")) continue;
        assert.equal(response.headers?.["X-Request-ID"]?.schema?.type, "string", `${path} ${status}`);
      }
    }
  }
});

test("login preserves a sanitized invitation continuation for password and OAuth", async () => {
  const login = await source("apps/web/app/(auth)/login/page.tsx");
  const actions = await source("apps/web/app/actions.ts");
  const google = await source("apps/web/app/(auth)/GoogleSignInButton.tsx");

  assert.match(login, /name="next"/u);
  assert.match(login, /GoogleSignInButton next=/u);
  assert.match(actions, /sanitizeInternalRedirect/u);
  assert.match(actions, /redirect\(next\)/u);
  assert.match(actions, /auth\/confirm\?next=/u);
  assert.match(google, /name="next"/u);
});

test("invitation side effects reconcile in the trusted actor and command namespace", async () => {
  const actions = await source("apps/web/app/actions.ts");
  const sideEffects = await source("apps/web/app/lib/invitation-side-effects.ts");

  assert.doesNotMatch(actions, /id: operationId/u);
  assert.doesNotMatch(actions, /persistInvitationOutbox/u);
  assert.match(actions, /persistInvitationAudit/u);
  assert.match(sideEffects, /deriveInvitationSideEffectId/u);
  assert.match(sideEffects, /actorId/u);
  assert.match(sideEffects, /operationId/u);
  assert.match(sideEffects, /purpose/u);
  assert.doesNotMatch(sideEffects, /notification_outbox|insertOutbox/u);
  assert.match(sideEffects, /existing\.message/u);
});

test("shipped server actions expose receipt-owned recovery without browser command inputs", async () => {
  const actions = await source("apps/web/app/actions.ts");
  const workspace = await source("apps/web/app/(owner)/workspace/page.tsx");
  const accept = await source("apps/web/app/invite/accept/page.tsx");

  assert.match(actions, /recoverWorkspaceInvitationSideEffects\(\)/u);
  assert.match(actions, /listPendingInvitationSideEffects/u);
  assert.match(actions, /completeInvitationSideEffect/u);
  assert.match(actions, /\.recover\(user\.id\)/u);
  assert.doesNotMatch(actions, /recoverWorkspaceInvitationSideEffects\(formData/u);
  assert.match(workspace, /action=\{recoverWorkspaceInvitationSideEffects\}/u);
  assert.match(accept, /action=\{recoverWorkspaceInvitationSideEffects\}/u);
  assert.match(accept, /params\?\.recovery \? "\/invite\/accept\?recovery=1" : `\/invite\/accept\?token=\$\{token\}`/u);
  assert.doesNotMatch(accept, /recovery=1[^"`\n]*token=/u);
});

test("membership role selector has a target-specific accessible name", async () => {
  const workspace = await source("apps/web/app/(owner)/workspace/page.tsx");
  assert.match(workspace, /aria-label=\{`Medlemsrolle for \$\{membership\.userId\}`\}/u);
});

test("capability manifest attributes the latest company-access ownership migration", async () => {
  const manifest = JSON.parse(await source("apps/backend/src/talli_backend/modules/company_access/module.json"));
  assert.equal(
    manifest.owns.migrations,
    "supabase/migrations/20260830091341_case_bound_support_access.sql",
  );
});
