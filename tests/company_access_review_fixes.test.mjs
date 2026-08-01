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

test("legacy outbox writes reconcile by the durable command operation id", async () => {
  const actions = await source("apps/web/app/actions.ts");

  assert.match(actions, /id: operationId/u);
  assert.match(actions, /\.eq\("id", operationId\)/u);
  assert.match(actions, /invitationId/u);
  assert.match(actions, /payload\?\.body !== created\.deliveryBody/u);
  assert.match(actions, /payload\?\.acceptUrl !== deliveryPayload\.acceptUrl/u);
});

test("membership role selector has a target-specific accessible name", async () => {
  const workspace = await source("apps/web/app/(owner)/workspace/page.tsx");
  assert.match(workspace, /aria-label=\{`Medlemsrolle for \$\{membership\.userId\}`\}/u);
});

test("capability manifest attributes the invitation migration", async () => {
  const manifest = JSON.parse(await source("apps/backend/src/talli_backend/modules/company_access/module.json"));
  assert.equal(
    manifest.owns.migrations,
    "supabase/migrations/20260801090000_company_access_invitations.sql",
  );
});
