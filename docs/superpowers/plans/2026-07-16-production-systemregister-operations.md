# Production Systemregister Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a founder-only, audited production operation that verifies Talli's Maskinporten Systembruker scope and idempotently registers the fixed RF-1086 Systemregister definition without exposing production credentials.

**Architecture:** A pure authority-operations module owns the fixed payload, environment validation, redacted errors, and idempotent Altinn GET/POST flow. An admin-only server action applies signed AAL2 and exact-confirmation gates, records a service-role-only global audit row, and exposes the operation through the existing operator page. A disabled-by-default production flag permits the single controlled run inside Vercel, after which the flag is disabled again.

**Tech Stack:** Next.js App Router/server actions, TypeScript, Node test runner, Supabase/PostgreSQL RLS, Maskinporten private-key JWT, Altinn Systemregister API, Vercel Sensitive Environment Variables.

## Global Constraints

- `TALLI_AUTHORITY_OPS_ENABLED` must be the exact string `true`; every other value fails closed.
- Never accept an endpoint, scope, system ID, right, redirect URL, client ID, or payload field from browser input.
- Never log, persist, render, or return a private key, JWT assertion, access token, or raw upstream response body.
- Use only `https://maskinporten.no/token` and `https://platform.altinn.no/authentication/api/v1/systemregister/vendor`.
- System ID is exactly `930835978_talli`; right is exactly `ske-innrapportering-aksjonaerregisteroppgave`.
- Existing definitions are verified, never automatically overwritten with PUT.
- The production filing gate `TALLI_RF1086_PRODUCTION_ENABLED` remains `false`.
- No paid integration or plan is introduced. Stop if Vercel or another provider presents a charge, upgrade, or overage.

## File Structure

- Create `app/lib/authority-operations.ts`: fixed operation contract, environment validation, canonical payload/hash, safe errors, and injected GET/POST execution.
- Modify `app/lib/security.ts`: add `authority_operations` to the existing signed-AAL2 sensitive-action policy.
- Modify `app/actions.ts`: add the admin-only audited server action.
- Modify `app/lib/supabase/server.ts`: define and read redacted authority-operation rows for the operator page.
- Modify `app/(operator)/operator/page.tsx`: render the immutable target, confirmation field, execution state, and recent results.
- Create `supabase/migrations/20260716110000_authority_operations.sql`: global service-written audit table and admin-read RLS.
- Create `supabase/rollback/authority_operations.sql`: revoke then remove the additive audit table.
- Create `tests/authority_operations.test.mjs`: pure operation and HTTP-boundary tests.
- Create `tests/authority_operations_schema.test.mjs`: migration/rollback contract tests.
- Create `tests/authority_operations_actions.test.mjs`: source-contract tests for the server action and operator UI.
- Modify `tests/security_step_up.test.mjs`: prove the new operation requires fresh signed AAL2.
- Modify `package.json`: add the targeted `test:authority-operations` command and include it in the launch rehearsal.
- Modify `docs/filing/authority-onboarding-runbook.md`: record the production scopes, registration result, evidence, and missing `instances.write` picker item.
- Create `docs/launch/evidence/production-systemregister-2026-07-16.md`: capture the redacted deployment and live-operation evidence.

---

### Task 1: Add the authority-operation security policy

**Files:**
- Modify: `app/lib/security.ts`
- Modify: `tests/security_step_up.test.mjs`

**Interfaces:**
- Consumes: existing `assertStepUpAllowed(action, context, now)` and signed-claim parsing.
- Produces: `SensitiveAction` value `authority_operations` with a 15-minute MFA window.

- [ ] **Step 1: Write the failing security test**

Add this assertion to `tests/security_step_up.test.mjs`:

```js
test("production authority operations require fresh signed AAL2", () => {
  assert.throws(
    () => assertStepUpAllowed("authority_operations", { actorId: "operator", mfaVerifiedAt: null }, now),
    /fersk MFA\/step-up/,
  );
  assert.doesNotThrow(() =>
    assertStepUpAllowed(
      "authority_operations",
      { actorId: "operator", mfaVerifiedAt: "2026-06-16T09:59:00.000Z" },
      now,
    ),
  );
});
```

- [ ] **Step 2: Run the test and verify RED**

Run: `npm run test:security`

Expected: FAIL with `unknown_sensitive_action` for `authority_operations`.

- [ ] **Step 3: Add the minimal policy**

Extend `SensitiveAction` and `sensitiveActionRequirements` in `app/lib/security.ts`:

```ts
export type SensitiveAction =
  | "authority_operations"
  // existing values remain unchanged
;

{
  action: "authority_operations",
  requiresMfa: true,
  maxMfaAgeMinutes: 15,
  label: "Produksjonsoperasjon mot myndighet",
},
```

- [ ] **Step 4: Run the test and verify GREEN**

Run: `npm run test:security`

Expected: all security step-up tests PASS.

- [ ] **Step 5: Commit the policy**

```bash
git add app/lib/security.ts tests/security_step_up.test.mjs
git commit -m "feat: require AAL2 for authority operations"
```

---

### Task 2: Build the fixed, redacted Systemregister operation

**Files:**
- Create: `app/lib/authority-operations.ts`
- Create: `tests/authority_operations.test.mjs`

**Interfaces:**
- Consumes: `requestMaskinportenToken(input)` from `app/lib/maskinporten.ts`.
- Produces:
  - `productionAuthorityOperationEnvironment(environment?): AuthorityOperationEnvironment | null`
  - `buildRf1086SystemDefinition(clientId): Rf1086SystemDefinition`
  - `authorityOperationRequestHash(definition): string`
  - `assertAuthorityOperationIntent(input): void`
  - `executeRf1086SystemRegistration(environment, dependencies?): Promise<AuthorityOperationResult>`

- [ ] **Step 1: Write failing environment, payload, intent, and redaction tests**

Create `tests/authority_operations.test.mjs` with tests that assert:

```js
import assert from "node:assert/strict";
import test from "node:test";
import {
  AuthorityOperationError,
  assertAuthorityOperationIntent,
  authorityOperationRequestHash,
  buildRf1086SystemDefinition,
  executeRf1086SystemRegistration,
  productionAuthorityOperationEnvironment,
} from "../app/lib/authority-operations.ts";

const productionEnvironment = {
  TALLI_AUTHORITY_OPS_ENABLED: "true",
  TALLI_PROD_MASKINPORTEN_CLIENT_ID: "4a42d9fe-9759-4d4e-a07a-84ebc80a5a1b",
  TALLI_PROD_MASKINPORTEN_KEY_ID: "93fea8a9-4435-4fdc-84fc-775803714c53",
  TALLI_PROD_MASKINPORTEN_PRIVATE_KEY_PEM:
    "-----BEGIN PRIVATE KEY-----\nZmFrZS1wcm9kdWN0aW9uLWtleQ==\n-----END PRIVATE KEY-----",
};

test("authority operation environment fails closed and rejects test credentials", () => {
  assert.equal(productionAuthorityOperationEnvironment({}), null);
  assert.throws(
    () => productionAuthorityOperationEnvironment({
      ...productionEnvironment,
      TALLI_PROD_MASKINPORTEN_CLIENT_ID: "tt02-client",
    }),
    /must not reference test/i,
  );
});

test("builds the one fixed RF-1086 own-system definition", () => {
  const definition = buildRf1086SystemDefinition(productionEnvironment.TALLI_PROD_MASKINPORTEN_CLIENT_ID);
  assert.equal(definition.id, "930835978_talli");
  assert.equal(definition.vendor.ID, "0192:930835978");
  assert.deepEqual(definition.rights, [{
    resource: [{ id: "urn:altinn:resource", value: "ske-innrapportering-aksjonaerregisteroppgave" }],
  }]);
  assert.deepEqual(definition.clientId, [productionEnvironment.TALLI_PROD_MASKINPORTEN_CLIENT_ID]);
  assert.deepEqual(definition.allowedredirecturls, []);
  assert.equal(definition.isVisible, true);
  assert.match(authorityOperationRequestHash(definition), /^[a-f0-9]{64}$/u);
});

test("requires the exact immutable operation and confirmation phrase", () => {
  assert.doesNotThrow(() => assertAuthorityOperationIntent({
    operation: "register_rf1086_system",
    confirmation: "REGISTER TALLI RF1086 SYSTEM",
  }));
  assert.throws(() => assertAuthorityOperationIntent({
    operation: "register_other_system",
    confirmation: "REGISTER TALLI RF1086 SYSTEM",
  }), /authority_operation_invalid/u);
});
```

- [ ] **Step 2: Write failing HTTP-flow tests**

Add injected fake-token and fake-fetch tests for these outcomes:

```js
test("creates a missing system then verifies it without leaking the token", async () => {
  const requests = [];
  const definition = buildRf1086SystemDefinition(productionEnvironment.TALLI_PROD_MASKINPORTEN_CLIENT_ID);
  const responses = [
    new Response(null, { status: 404 }),
    new Response(JSON.stringify(definition), { status: 200, headers: { "content-type": "application/json" } }),
    new Response(JSON.stringify(definition), { status: 200, headers: { "content-type": "application/json" } }),
  ];
  const result = await executeRf1086SystemRegistration(
    productionAuthorityOperationEnvironment(productionEnvironment),
    {
      requestToken: async (input) => {
        assert.equal(input.scope, "altinn:authentication/systemregister.write");
        assert.equal(input.systemUserOrgNumber, undefined);
        return { accessToken: "opaque-secret-token", tokenType: "Bearer", expiresIn: 119, scope: input.scope, environment: "production" };
      },
      fetch: async (url, init) => {
        requests.push([String(url), init.method]);
        return responses.shift();
      },
    },
  );
  assert.equal(result.code, "created_and_verified");
  assert.deepEqual(requests.map(([, method]) => method), ["GET", "POST", "GET"]);
  assert.doesNotMatch(JSON.stringify(result), /opaque-secret-token/u);
});

test("does not overwrite a conflicting existing definition", async () => {
  const result = await executeRf1086SystemRegistration(
    productionAuthorityOperationEnvironment(productionEnvironment),
    {
      requestToken: async () => ({ accessToken: "token", tokenType: "Bearer", expiresIn: 119, scope: "scope", environment: "production" }),
      fetch: async () => new Response(JSON.stringify({
        ...buildRf1086SystemDefinition(productionEnvironment.TALLI_PROD_MASKINPORTEN_CLIENT_ID),
        isVisible: false,
      }), { status: 200, headers: { "content-type": "application/json" } }),
    },
  );
  assert.equal(result.code, "definition_conflict");
  assert.equal(result.status, "conflict");
});
```

Also assert a matching GET returns `already_verified`, malformed JSON becomes
`authority_response_invalid`, redirects use `redirect: "error"`, timeouts are present,
and thrown errors contain neither the key nor token nor upstream body.

- [ ] **Step 3: Run the focused tests and verify RED**

Run: `node --experimental-strip-types --test tests/authority_operations.test.mjs`

Expected: FAIL because `app/lib/authority-operations.ts` does not exist.

- [ ] **Step 4: Implement the minimal operation module**

Create `app/lib/authority-operations.ts` with fixed constants and this public shape:

```ts
export const AUTHORITY_OPERATION = "register_rf1086_system" as const;
export const AUTHORITY_CONFIRMATION = "REGISTER TALLI RF1086 SYSTEM" as const;
export const TALLI_SYSTEM_ID = "930835978_talli" as const;
export const RF1086_RIGHT = "ske-innrapportering-aksjonaerregisteroppgave" as const;

export type AuthorityOperationResult = {
  status: "succeeded" | "failed" | "conflict";
  code: "created_and_verified" | "already_verified" | "definition_conflict";
  systemId: typeof TALLI_SYSTEM_ID;
  clientId: string;
  right: typeof RF1086_RIGHT;
  authorityStatus: number;
};

export class AuthorityOperationError extends Error {
  constructor(
    readonly code: string,
    readonly authorityStatus: number | null = null,
  ) {
    super(code);
    this.name = "AuthorityOperationError";
  }
}
```

Use a canonical sorted JSON projection for equality and hashing. Limit JSON response
reads to one object, reject non-JSON or non-object bodies, use `AbortSignal.timeout(15_000)`,
and pass `redirect: "error"`. Only the fixed GET and POST URLs may be constructed.

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run: `node --experimental-strip-types --test tests/authority_operations.test.mjs`

Expected: all authority-operation unit tests PASS.

- [ ] **Step 6: Commit the operation core**

```bash
git add app/lib/authority-operations.ts tests/authority_operations.test.mjs
git commit -m "feat: add fixed production Systemregister operation"
```

---

### Task 3: Add the service-written authority audit table

**Files:**
- Create: `supabase/migrations/20260716110000_authority_operations.sql`
- Create: `supabase/rollback/authority_operations.sql`
- Create: `tests/authority_operations_schema.test.mjs`

**Interfaces:**
- Consumes: existing `support_operators(user_id, role, active)` grants.
- Produces: `public.authority_operations` readable only by active admin operators and mutable only by `service_role`.

- [ ] **Step 1: Write the failing schema test**

Create `tests/authority_operations_schema.test.mjs`:

```js
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const sql = readFileSync(new URL("../supabase/migrations/20260716110000_authority_operations.sql", import.meta.url), "utf8");
const rollback = readFileSync(new URL("../supabase/rollback/authority_operations.sql", import.meta.url), "utf8");

test("authority operations are constrained, RLS protected, and service-written", () => {
  assert.match(sql, /create table if not exists public\.authority_operations/iu);
  assert.match(sql, /register_rf1086_system/u);
  assert.match(sql, /started.*succeeded.*failed.*conflict/su);
  assert.match(sql, /alter table public\.authority_operations enable row level security/iu);
  assert.match(sql, /revoke all on table public\.authority_operations from public, anon, authenticated/iu);
  assert.match(sql, /grant select on table public\.authority_operations to authenticated/iu);
  assert.match(sql, /grant insert, update on table public\.authority_operations to service_role/iu);
  assert.doesNotMatch(sql, /grant (?:insert|update)[^;]*authority_operations[^;]*authenticated/iu);
  assert.match(sql, /support_operators[\s\S]*role = 'admin'[\s\S]*active/iu);
});

test("rollback revokes access before dropping the table", () => {
  assert.ok(rollback.indexOf("revoke all on table public.authority_operations") < rollback.indexOf("drop table if exists public.authority_operations"));
});
```

- [ ] **Step 2: Run the schema test and verify RED**

Run: `node --test tests/authority_operations_schema.test.mjs`

Expected: FAIL because the migration does not exist.

- [ ] **Step 3: Add the migration and rollback**

The migration must create fields and checks equivalent to:

```sql
create table if not exists public.authority_operations (
  id uuid primary key default gen_random_uuid(),
  operation text not null check (operation in ('register_rf1086_system')),
  actor_id uuid not null references auth.users(id) on delete restrict,
  status text not null check (status in ('started', 'succeeded', 'failed', 'conflict')),
  request_hash text not null check (request_hash ~ '^[a-f0-9]{64}$'),
  result_code text not null default 'started',
  authority_http_status integer check (authority_http_status between 100 and 599),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  completed_at timestamptz
);

alter table public.authority_operations enable row level security;
revoke all on table public.authority_operations from public, anon, authenticated;
grant select on table public.authority_operations to authenticated;
grant insert, update on table public.authority_operations to service_role;
```

Add one SELECT policy requiring the current user to have `role = 'admin'` and
`active = true`. Add no authenticated INSERT, UPDATE, or DELETE policy.

- [ ] **Step 4: Run the schema test and verify GREEN**

Run: `node --test tests/authority_operations_schema.test.mjs`

Expected: both schema tests PASS.

- [ ] **Step 5: Commit the audit schema**

```bash
git add supabase/migrations/20260716110000_authority_operations.sql supabase/rollback/authority_operations.sql tests/authority_operations_schema.test.mjs
git commit -m "feat: audit production authority operations"
```

---

### Task 4: Add the admin server action and operator UI

**Files:**
- Modify: `app/actions.ts`
- Modify: `app/lib/supabase/server.ts`
- Modify: `app/(operator)/operator/page.tsx`
- Create: `tests/authority_operations_actions.test.mjs`

**Interfaces:**
- Consumes: Task 1 AAL2 policy, Task 2 operation module, Task 3 audit table, existing `createSupabaseServerClient()` and `createSupabaseServiceRoleClient()`.
- Produces: `runProductionAuthorityOperation(formData)` and `listAuthorityOperations(actorId)`.

- [ ] **Step 1: Write the failing action/UI source-contract tests**

Create `tests/authority_operations_actions.test.mjs` with assertions:

```js
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const actions = readFileSync(new URL("../app/actions.ts", import.meta.url), "utf8");
const operatorPage = readFileSync(new URL("../app/(operator)/operator/page.tsx", import.meta.url), "utf8");
const server = readFileSync(new URL("../app/lib/supabase/server.ts", import.meta.url), "utf8");

test("authority operation is admin-only, AAL2-gated, exact, and service-audited", () => {
  assert.match(actions, /export async function runProductionAuthorityOperation/u);
  assert.match(actions, /eq\("role", "admin"\)/u);
  assert.match(actions, /assertStepUpAllowed\("authority_operations"/u);
  assert.match(actions, /assertAuthorityOperationIntent/u);
  assert.match(actions, /createSupabaseServiceRoleClient/u);
  assert.match(actions, /from\("authority_operations"\)\.insert/u);
  assert.match(actions, /executeRf1086SystemRegistration/u);
  assert.doesNotMatch(actions, /accessToken.*redirect|privateKeyPem.*redirect/isu);
});

test("operator UI exposes only the immutable RF-1086 operation and redacted results", () => {
  assert.match(operatorPage, /930835978_talli/u);
  assert.match(operatorPage, /ske-innrapportering-aksjonaerregisteroppgave/u);
  assert.match(operatorPage, /REGISTER TALLI RF1086 SYSTEM/u);
  assert.match(operatorPage, /runProductionAuthorityOperation/u);
  assert.match(server, /listAuthorityOperations/u);
  assert.doesNotMatch(operatorPage, /private key|access token/iu);
});
```

- [ ] **Step 2: Run the source-contract test and verify RED**

Run: `node --test tests/authority_operations_actions.test.mjs`

Expected: FAIL because the action and UI do not exist.

- [ ] **Step 3: Implement `listAuthorityOperations`**

Add `AuthorityOperationRow` and a query in `app/lib/supabase/server.ts`:

```ts
export type AuthorityOperationRow = {
  id: string;
  operation: "register_rf1086_system";
  actor_id: string;
  status: "started" | "succeeded" | "failed" | "conflict";
  request_hash: string;
  result_code: string;
  authority_http_status: number | null;
  metadata: { systemId?: string; clientId?: string; right?: string };
  created_at: string;
  completed_at: string | null;
};

export async function listAuthorityOperations(actorId: string) {
  const supabase = await createSupabaseServerClient();
  const { data: operator } = await supabase.from("support_operators")
    .select("role, active").eq("user_id", actorId).eq("role", "admin").eq("active", true).maybeSingle();
  if (!operator) return { operations: [], isAdminOperator: false, error: null };
  const { data, error } = await supabase.from("authority_operations").select("*")
    .order("created_at", { ascending: false }).limit(10);
  return { operations: (data ?? []) as AuthorityOperationRow[], isAdminOperator: true, error: error?.message ?? null };
}
```

- [ ] **Step 4: Implement the server action**

The action in `app/actions.ts` must follow this order:

```ts
export async function runProductionAuthorityOperation(formData: FormData) {
  if (!hasSupabaseEnv()) redirect("/operator?authority=authority_ops_unavailable");
  const supabase = await createSupabaseServerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/login");
  const { data: operator } = await supabase.from("support_operators")
    .select("role, active").eq("user_id", user.id).eq("role", "admin").eq("active", true).maybeSingle();
  if (!operator) redirect("/operator?authority=admin_operator_required");
  const stepUp = await loadTrustedStepUpContext(supabase, user.id);
  assertStepUpAllowed("authority_operations", stepUp);
  assertAuthorityOperationIntent({
    operation: formString(formData, "operation"),
    confirmation: formString(formData, "confirmation"),
  });
  const environment = productionAuthorityOperationEnvironment();
  if (!environment) redirect("/operator?authority=authority_ops_disabled");
  const definition = buildRf1086SystemDefinition(environment.clientId);
  const service = createSupabaseServiceRoleClient();
  const { data: started } = await service.from("authority_operations").insert({
    operation: AUTHORITY_OPERATION,
    actor_id: user.id,
    status: "started",
    request_hash: authorityOperationRequestHash(definition),
    result_code: "started",
    metadata: { systemId: definition.id, clientId: environment.clientId, right: RF1086_RIGHT },
  }).select("id").single();
  // Execute, update only safe result fields, and redirect with an allowlisted result code.
}
```

Catch `SensitiveActionStepUpError` and `AuthorityOperationError`; map them to fixed
safe result codes. Never include `error.message` from an unknown exception in a URL or
database row. Update the started row to `failed` when the external operation throws.

- [ ] **Step 5: Add the operator UI**

Extend the operator page params with `authority?: string`, load
`listAuthorityOperations(user.id)`, and render an admin-only form:

```tsx
<form className="dataPanel formPanel widePanel" action={runProductionAuthorityOperation}>
  <h3>Produksjon · Systemregister</h3>
  <p>System: <code>930835978_talli</code></p>
  <p>Rettighet: <code>ske-innrapportering-aksjonaerregisteroppgave</code></p>
  <input type="hidden" name="operation" value="register_rf1086_system" />
  <label>
    Skriv REGISTER TALLI RF1086 SYSTEM
    <input name="confirmation" autoComplete="off" required />
  </label>
  <button className="secondaryButton" type="submit">Registrer eller verifiser system</button>
</form>
```

Render only the status, result code, HTTP status, system ID, client ID, right, and
timestamps from recent rows. Do not render arbitrary metadata keys.

- [ ] **Step 6: Run the action/UI tests and verify GREEN**

Run: `node --test tests/authority_operations_actions.test.mjs`

Expected: all action/UI source-contract tests PASS.

- [ ] **Step 7: Run all targeted tests**

Run:

```bash
node --experimental-strip-types --test \
  tests/authority_operations.test.mjs \
  tests/authority_operations_schema.test.mjs \
  tests/authority_operations_actions.test.mjs \
  tests/security_step_up.test.mjs
```

Expected: all authority-operation and security tests PASS.

- [ ] **Step 8: Commit the operator surface**

```bash
git add app/actions.ts app/lib/supabase/server.ts 'app/(operator)/operator/page.tsx' tests/authority_operations_actions.test.mjs
git commit -m "feat: add audited authority operations UI"
```

---

### Task 5: Integrate verification and operational documentation

**Files:**
- Modify: `package.json`
- Modify: `docs/filing/authority-onboarding-runbook.md`
- Create: `docs/launch/evidence/production-systemregister-2026-07-16.md`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: repeatable verification command and redacted operational evidence.

- [ ] **Step 1: Add the targeted package command**

Add:

```json
"test:authority-operations": "node --experimental-strip-types --test tests/authority_operations.test.mjs tests/authority_operations_schema.test.mjs tests/authority_operations_actions.test.mjs"
```

Append `npm run test:authority-operations` to `test:launch-rehearsal` next to the
existing Maskinporten/authority tests.

- [ ] **Step 2: Run the complete local verification**

Run:

```bash
npm run test:authority-operations
npm run test:security
npm run test:maskinporten
npm run typecheck
npm run build
npm audit --audit-level=high
git diff --check
```

Expected: tests, typecheck, and build PASS; audit has no critical/high reachable
runtime finding; diff check is clean.

- [ ] **Step 3: Commit the local integration**

```bash
git add package.json package-lock.json
git commit -m "test: gate production authority operations"
```

- [ ] **Step 4: Apply the additive database migration**

Run: `npx supabase db push --linked`

Expected: `20260716110000_authority_operations.sql` is applied to the linked production
project. This consumes no paid provider feature; stop if a charge or plan upgrade is
presented.

- [ ] **Step 5: Configure the temporary disabled-by-default runtime gate**

Add `TALLI_AUTHORITY_OPS_ENABLED=true` to Vercel Production only. Do not modify
`TALLI_RF1086_PRODUCTION_ENABLED=false`. Verify the environment variable listing by
name only; never print values.

- [ ] **Step 6: Deploy the reviewed commit**

Run: `npx vercel --prod --yes`

Expected: deployment reaches `Ready` and `https://talli.no/operator` loads. The project
is currently on Vercel Free; this consumes included build/runtime quota and must stop
if Vercel requests payment or an upgrade.

- [ ] **Step 7: Execute the live operation once**

In the signed-in production operator page, complete fresh Supabase MFA if required,
enter exactly `REGISTER TALLI RF1086 SYSTEM`, and submit once. This is an external
authority mutation and requires action-time user confirmation under browser-control
policy even though the implementation was pre-approved.

Expected: safe result `created_and_verified` or `already_verified`; an audit row shows
`succeeded`; no token or key appears in UI, logs, or database.

- [ ] **Step 8: Disable the operations surface and redeploy**

Set `TALLI_AUTHORITY_OPS_ENABLED=false` in Vercel Production and deploy the same commit
again. Verify the operator UI reports disabled and a repeated operation fails closed.
Leave `TALLI_RF1086_PRODUCTION_ENABLED=false` unchanged.

- [ ] **Step 9: Record redacted evidence and the remaining picker gap**

Update the runbook and create the evidence document with:

- production client ID and public key ID/fingerprint only;
- attached scope names;
- missing `altinn:instances.write` picker result;
- Systemregister system ID, right, safe result code, HTTP statuses, request hash, and
  audit operation ID;
- deployment IDs before/after disabling the gate;
- confirmation that no filing endpoint was called and no paid action occurred.

- [ ] **Step 10: Commit the operational evidence**

```bash
git add docs/filing/authority-onboarding-runbook.md docs/launch/evidence/production-systemregister-2026-07-16.md
git commit -m "docs: record production Systemregister verification"
```

- [ ] **Step 11: Finish the branch**

Run the `verification-before-completion` skill, then the `finishing-a-development-branch`
skill. Merge to `main` and push only after every verification and the disabled gate are
confirmed. Report both commits and the final token/build/test evidence without exposing
credentials.
