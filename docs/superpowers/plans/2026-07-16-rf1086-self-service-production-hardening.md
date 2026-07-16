# RF-1086 Self-Service Production Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a company owner create and verify Talli's standard RF-1086 Systembruker without support, and turn a production submission into a durable, resumable, evidence-backed outcome without broadening any production gate.

**Architecture:** Add a strict Altinn Systembruker request client and a durable `system_user_requests` aggregate, then expose it through owner-only Server Actions and a fixed authenticated callback. Bind production entitlements and submission tokens to a preflight-verified request. Extend the RF-1086 journal with read-only reconciliation and private feedback artifacts, while keeping Systemregister mutation operator-only and callback-only.

**Tech Stack:** Next.js 16.2.9, React 19.2.7, TypeScript 6.0.3, Supabase/Postgres with RLS and security-definer RPCs, `@supabase/supabase-js` 2.108.x, `@supabase/ssr` 0.12.x, Node test runner, Playwright 1.61.0, and `saxes` 6.0.0 for bounded namespace-aware XML classification.

## Global Constraints

- Source of truth: `docs/superpowers/specs/2026-07-16-rf1086-self-service-production-hardening-design.md`.
- The system ID is exactly `930835978_talli`.
- The Altinn right is exactly `ske-innrapportering-aksjonaerregisteroppgave`.
- The callback is exactly `https://talli.no/auth/systembruker/confirm`.
- The supported filing boundary remains one Norwegian AS filing for itself on `rf1086_no_activity_v1`, one share class, Norwegian shareholders only, no purchase/sale/dividend/correction/replacement event, and explicit owner approval; Årsregnskap and Skattemelding production submission remain out of scope.
- Create a standard, vendor-controlled own-system Systembruker request; never call the agent request API.
- The request uses only the single RF-1086 right; never add an access package or another right.
- `externalRef` is opaque random data and must never contain an organization number, user ID, email address, name, or other PII.
- A request status of `accepted` is not sufficient for production use; a delegated Maskinporten preflight for the exact organization, system, right, scope, and `externalRef` must succeed and the token must then be discarded.
- The callback trusts only the authenticated session and the secure local request cookie; it ignores all Altinn query parameters for identity or request selection.
- Cookies are `HttpOnly`, `Secure`, `SameSite=Lax`, scoped to `/auth/systembruker/confirm`, and contain only the local request UUID.
- Altinn response bodies are capped at 64 KiB for JSON and 10 MiB for an individual artifact; confirmation URLs must be HTTPS on an environment-specific exact Altinn host.
- Persist no Maskinporten token, private key, raw authority request/response, raw XML, or PII in logs, audit events, error messages, or operator evidence.
- Systemregister update is operator-only, fresh signed AAL2, ops-gated, typed-confirmation protected, and may change only `allowedRedirectUrls` from empty to the exact callback; any other drift is a conflict and performs no write.
- Production filing remains off unless the existing controlled-beta switch, explicit entitlement, approval, authority permission, freshness checks, and all existing release gates pass.
- A production submission additionally requires one accepted and preflight-verified Systembruker request matching the owner, company, obligation, entitlement, and token `externalRef`.
- Never repeat a filing POST during reconciliation. Initial reconciliation performs at most five archive reads separated by two seconds; later reconciliation is read-only and user-triggered by page load, refresh, or an explicit action.
- `GLD_021`, `GLD_1017`, and an empty document collection mean `processing`, not failure and not acceptance.
- Durable outcome states are exactly `sent`, `processing`, `accepted`, `rejected`, `action_required`, and `unknown`.
- Append a reconciliation event only when the durable state or artifact set changes.
- Store feedback bytes only in the existing private `company-documents` bucket and store only company/submission/reference/content-type/byte-length/SHA-256/retrieval-time/classification metadata in Postgres.
- Unknown, malformed, mismatched, oversized, or unsupported feedback is `action_required`; document availability alone is never acceptance.
- Keep `TALLI_RF1086_PRODUCTION_ENABLED` and `TALLI_AUTHORITY_OPS_ENABLED` off in repository defaults and tests that do not explicitly mock the gate.
- Do not make live Altinn, Maskinporten, Skatteetaten, Supabase production, deployment, entitlement, Systemregister, or filing mutations while implementing or testing.
- No paid infrastructure or paid external action is authorized.
- Every behavior change follows an observed RED → GREEN → REFACTOR cycle and every task ends in a focused passing test run and an atomic commit.
- Before completion, run focused suites, local Supabase role-abuse tests, Supabase advisors, typecheck, build, the RF-1086 release gate, and the mocked browser flow.

## Authoritative References

- Altinn standard request API: `https://docs.altinn.studio/en/api/authentication/systemuserapi/systemuserrequest/external/`
- Altinn request model and `externalRef` contract: `https://docs.altinn.studio/en/api/authentication/systemuserapi/systemuserrequest/external/model/`
- Altinn Systembruker query contract: `https://docs.altinn.studio/en/authorization/guides/system-vendor/system-user/byquery/`
- Altinn delegated-token contract: `https://docs.altinn.studio/en/authorization/guides/system-vendor/system-user/usetoken/`
- Skatteetaten RF-1086 API and individual-document guidance: `https://skatteetaten.github.io/api-dokumentasjon/en/api/innrapportering-aksjonaerregisteroppgave`
- Supabase RLS: `https://supabase.com/docs/guides/database/postgres/row-level-security`
- Supabase database functions: `https://supabase.com/docs/guides/database/functions`
- Next.js cookies: `https://nextjs.org/docs/app/api-reference/functions/cookies`

---

### Task 1: Strict Systembruker Request Client and State Model

**Files:**
- Create: `app/lib/system-user-requests.ts`
- Create: `app/lib/system-user-authority-client.ts`
- Create: `tests/system_user_requests.test.mjs`
- Create: `tests/system_user_authority_client.test.mjs`
- Modify: `package.json`

**Interfaces:**
- Consumes: `requestMaskinportenToken` from `app/lib/maskinporten.ts`; production control-plane bearer tokens use scopes `altinn:authentication/systemuser.request.write` and `altinn:authentication/systemuser.request.read` without a Systembruker RAR.
- Produces: `SYSTEM_USER_SYSTEM_ID`, `SYSTEM_USER_RIGHT`, `SYSTEM_USER_CALLBACK_URL`, `SystemUserRequestStatus`, `assertSystemUserTransition`, `generateSystemUserExternalRef`, `createSystemUserAuthorityClient`, `validateSystemUserAuthorityResponse`, and sanitized `SystemUserAuthorityError`.

- [ ] **Step 1: Write failing state-model tests**

```js
test("external references are opaque and transitions are monotonic", () => {
  const reference = generateSystemUserExternalRef();
  assert.match(reference, /^[A-Za-z0-9_-]{43}$/);
  assert.doesNotMatch(reference, /930835978|@|\s/);
  assert.equal(assertSystemUserTransition("creating", "new"), "new");
  assert.equal(assertSystemUserTransition("new", "accepted"), "accepted");
  assert.throws(() => assertSystemUserTransition("accepted", "new"), /invalid_system_user_transition/);
});

test("terminal Altinn failures cannot be reopened", () => {
  for (const status of ["rejected", "denied", "timedout"]) {
    assert.throws(() => assertSystemUserTransition(status, "new"), /invalid_system_user_transition/);
  }
});
```

- [ ] **Step 2: Run the state-model tests and observe RED**

Run: `node --experimental-strip-types --test tests/system_user_requests.test.mjs`

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `app/lib/system-user-requests.ts`.

- [ ] **Step 3: Implement the minimal state model**

```ts
import { randomBytes } from "node:crypto";

export const SYSTEM_USER_SYSTEM_ID = "930835978_talli" as const;
export const SYSTEM_USER_RIGHT = "ske-innrapportering-aksjonaerregisteroppgave" as const;
export const SYSTEM_USER_CALLBACK_URL = "https://talli.no/auth/systembruker/confirm" as const;

export type SystemUserRequestStatus =
  | "creating"
  | "new"
  | "accepted"
  | "rejected"
  | "denied"
  | "timedout"
  | "verification_failed";

const allowedTransitions: Record<SystemUserRequestStatus, ReadonlySet<SystemUserRequestStatus>> = {
  creating: new Set(["creating", "new", "accepted", "rejected", "denied", "timedout", "verification_failed"]),
  new: new Set(["new", "accepted", "rejected", "denied", "timedout", "verification_failed"]),
  accepted: new Set(["accepted", "verification_failed"]),
  rejected: new Set(["rejected"]),
  denied: new Set(["denied"]),
  timedout: new Set(["timedout"]),
  verification_failed: new Set(["verification_failed", "accepted"]),
};

export function generateSystemUserExternalRef() {
  return randomBytes(32).toString("base64url");
}

export function assertSystemUserTransition(from: SystemUserRequestStatus, to: SystemUserRequestStatus) {
  if (!allowedTransitions[from].has(to)) throw new Error("invalid_system_user_transition");
  return to;
}
```

- [ ] **Step 4: Write failing strict-client tests**

```js
test("create sends one standard request with the exact fixed contract", async () => {
  const seen = [];
  const client = createSystemUserAuthorityClient({
    environment: "production",
    fetchImpl: async (url, init) => {
      seen.push({ url, init });
      return jsonResponse(201, validAuthorityResponse);
    },
  });
  const result = await client.createRequest({ bearerToken: "memory-only", partyOrgNo: "123456789", externalRef });
  assert.equal(seen.length, 1);
  assert.equal(seen[0].url, "https://platform.altinn.no/authentication/api/v1/systemuser/request/vendor");
  assert.deepEqual(JSON.parse(seen[0].init.body), {
    externalRef,
    systemId: "930835978_talli",
    partyOrgNo: "123456789",
    rights: [{ resource: [{ id: "urn:altinn:resource", value: "ske-innrapportering-aksjonaerregisteroppgave" }] }],
    redirectUrl: "https://talli.no/auth/systembruker/confirm",
  });
  assert.equal(result.status, "new");
});

test("the client rejects agent fields, mismatches, wrong hosts, and oversized bodies", async () => {
  await assert.rejects(() => clientFor({ ...validAuthorityResponse, accessPackages: [{ urn: "forbidden" }] }), /response_contract_mismatch/);
  await assert.rejects(() => clientFor({ ...validAuthorityResponse, partyOrgNo: "987654321" }), /response_contract_mismatch/);
  await assert.rejects(() => clientFor({ ...validAuthorityResponse, confirmUrl: "https://evil.example/approve" }), /invalid_confirmation_url/);
  await assert.rejects(() => oversizedClient.createRequest(input), /response_too_large/);
});
```

- [ ] **Step 5: Run the client tests and observe RED**

Run: `node --experimental-strip-types --test tests/system_user_authority_client.test.mjs`

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `app/lib/system-user-authority-client.ts`.

- [ ] **Step 6: Implement create, lookup, and strict validation**

```ts
export type SystemUserAuthorityResponse = {
  id: string;
  externalRef: string;
  systemId: typeof SYSTEM_USER_SYSTEM_ID;
  partyOrgNo: string;
  rights: Array<{ resource: Array<{ id: "urn:altinn:resource"; value: typeof SYSTEM_USER_RIGHT }> }>;
  status: Exclude<SystemUserRequestStatus, "creating" | "verification_failed">;
  redirectUrl: typeof SYSTEM_USER_CALLBACK_URL;
  confirmUrl: string | null;
};

export type SystemUserAuthorityClient = {
  createRequest(input: { bearerToken: string; partyOrgNo: string; externalRef: string }): Promise<SystemUserAuthorityResponse>;
  getRequest(input: { bearerToken: string; requestId: string; partyOrgNo: string; externalRef: string }): Promise<SystemUserAuthorityResponse>;
  getRequestByExternalRef(input: { bearerToken: string; partyOrgNo: string; externalRef: string }): Promise<SystemUserAuthorityResponse>;
  querySystemUser(input: { bearerToken: string; partyOrgNo: string; externalRef: string }): Promise<{ id: string; systemId: string; reporteeOrgNo: string; externalRef: string; userType: "standard"; isDeleted: boolean }>;
};
```

Use `response.body.getReader()` to stop reading after 65,536 bytes, reject unknown status values and extra agent-only authority shapes, validate UUIDs and nine-digit organization numbers, compare every echoed fixed field, allow `confirmUrl` only on `am.ui.altinn.no` in production and `am.ui.at22.altinn.cloud` or `authn.ui.tt02.altinn.no` in TT02, and map only documented `AUTH-*` codes to safe internal error codes. Never include response bodies, bearer tokens, organization numbers, or URLs with query strings in thrown messages.

- [ ] **Step 7: Run focused tests and typecheck**

Run: `node --experimental-strip-types --test tests/system_user_requests.test.mjs tests/system_user_authority_client.test.mjs && npm run typecheck`

Expected: all tests PASS and TypeScript exits 0.

- [ ] **Step 8: Commit the client slice**

```bash
git add app/lib/system-user-requests.ts app/lib/system-user-authority-client.ts tests/system_user_requests.test.mjs tests/system_user_authority_client.test.mjs package.json
git commit -m "feat: add strict Systembruker request client"
```

### Task 2: Durable Request Persistence, RLS, and Entitlement Binding

**Files:**
- Create with `npx supabase migration new rf1086_system_user_requests`: the exact migration path printed by the command, ending `_rf1086_system_user_requests.sql`
- Create: `supabase/rollback/rf1086_system_user_requests.sql`
- Create: `tests/system_user_requests_schema.test.mjs`
- Create: `tests/system_user_requests_database_runtime.test.mjs`
- Modify: `app/lib/supabase/server.ts`
- Modify: `tests/controlled_production_beta_schema.test.mjs`
- Modify: `tests/supabase_explicit_grants.test.mjs`

**Interfaces:**
- Consumes: `SystemUserRequestStatus` and fixed constants from Task 1; `public.assert_fresh_production_owner(uuid)` and controlled-beta tables from `20260715180000_controlled_production_beta.sql`.
- Produces: `system_user_requests`, `begin_system_user_request(uuid,uuid,text)`, `record_system_user_authority_state(uuid,uuid,uuid,text,text,text,uuid)`, `verify_system_user_preflight(uuid,text)`, an entitlement foreign key `system_user_request_id`, and `SystemUserRequestRow`/`listSystemUserRequests` in the server data layer.

- [ ] **Step 1: Create the migration through the Supabase CLI**

Run: `npx supabase migration new rf1086_system_user_requests`

Expected: one new empty migration whose basename ends in `_rf1086_system_user_requests.sql`.

- [ ] **Step 2: Write failing schema and role-abuse tests**

```js
test("request persistence is owner-readable and mutation is RPC-only", () => {
  assert.match(sql, /create table public\.system_user_requests/i);
  assert.match(sql, /enable row level security/i);
  assert.match(sql, /initiating_owner_user_id uuid not null/i);
  assert.match(sql, /preflight_verified_at timestamptz/i);
  assert.match(sql, /revoke all on public\.system_user_requests from anon, authenticated/i);
  assert.match(sql, /grant select on public\.system_user_requests to authenticated/i);
  assert.match(sql, /grant execute on function public\.begin_system_user_request\(uuid, uuid, text\) to authenticated/i);
  assert.match(sql, /grant execute on function public\.record_system_user_authority_state[^;]+to service_role/is);
});

test("an owner cannot read another company or forge an accepted request", async () => {
  assert.deepEqual(await ownerB.from("system_user_requests").select("id").eq("id", ownerARequestId), { data: [], error: null });
  const forged = await ownerA.from("system_user_requests").update({ status: "accepted" }).eq("id", ownerARequestId);
  assert.ok(forged.error);
});
```

- [ ] **Step 3: Run tests and observe RED**

Run: `node --test tests/system_user_requests_schema.test.mjs && npm run test:supabase:local -- tests/system_user_requests_database_runtime.test.mjs`

Expected: schema assertions fail because the table/functions do not exist; the local runtime test fails before setup or reports the missing relation.

- [ ] **Step 4: Implement the table, policies, and RPC transition boundary**

```sql
create table public.system_user_requests (
  id uuid primary key,
  company_id uuid not null references public.companies(id) on delete cascade,
  initiating_owner_user_id uuid not null references auth.users(id) on delete restrict,
  obligation text not null default 'aksjonaerregisteroppgaven' check (obligation = 'aksjonaerregisteroppgaven'),
  external_ref text not null unique check (external_ref ~ '^[A-Za-z0-9_-]{43}$'),
  altinn_request_id uuid unique,
  status text not null check (status in ('creating','new','accepted','rejected','denied','timedout','verification_failed')),
  confirm_url text,
  preflight_verified_at timestamptz,
  failure_code text check (failure_code is null or failure_code ~ '^[a-z0-9_]{1,64}$'),
  operator_evidence_id uuid references public.authority_operations(id) on delete set null,
  requested_at timestamptz,
  last_status_checked_at timestamptz,
  accepted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  resolved_at timestamptz,
  check (preflight_verified_at is null or status = 'accepted')
);

create unique index system_user_requests_one_live_company_obligation
  on public.system_user_requests(company_id, obligation)
  where status in ('creating','new','accepted','verification_failed');

alter table public.system_user_requests enable row level security;
create policy system_user_requests_owner_read on public.system_user_requests for select to authenticated
using (
  initiating_owner_user_id = (select auth.uid())
  and exists (
    select 1 from public.company_memberships m
    where m.company_id = system_user_requests.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
      and m.accepted_at is not null
  )
);

create policy system_user_requests_operator_read on public.system_user_requests for select to authenticated
using (
  exists (
    select 1 from public.support_operators o
    where o.user_id = (select auth.uid()) and o.active
  )
);
```

`begin_system_user_request` must call `assert_fresh_production_owner`, require a caller-supplied random UUID and 43-character external reference, and insert `creating`. `record_system_user_authority_state` is `SECURITY DEFINER SET search_path = ''`, callable only by `service_role`, validates the exact owner/company/externalRef relationship and the transition matrix from Task 1, accepts only an allowlisted failure code plus an existing safe `authority_operations` evidence UUID, and updates `requested_at`, `last_status_checked_at`, `accepted_at`, `resolved_at`, and `updated_at` according to the transition. `verify_system_user_preflight` is service-only and may set the timestamp only on `accepted` after matching the expected external reference.

- [ ] **Step 5: Bind controlled-beta entitlements and `begin_production_filing`**

```sql
alter table public.production_pilot_entitlements
  add column system_user_request_id uuid references public.system_user_requests(id) on delete restrict;

alter table public.production_pilot_entitlements
  add constraint production_pilot_entitlements_verified_request_required
  check (not active or system_user_request_id is not null);
```

Replace operator-supplied `system_user_external_reference` in `manage_production_pilot_entitlement` with `p_system_user_request_id uuid`. The RPC must load the request, require exact company/owner/obligation, `status = 'accepted'`, non-null `preflight_verified_at`, and copy `external_ref` into the existing entitlement column. `begin_production_filing` must repeat those checks and require the entitlement request's initiating owner to equal `auth.uid()`.

- [ ] **Step 6: Add rollback, server row types, and read helper**

```ts
export type SystemUserRequestRow = {
  id: string;
  company_id: string;
  initiating_owner_user_id: string;
  obligation: "aksjonaerregisteroppgaven";
  external_ref: string;
  altinn_request_id: string | null;
  status: SystemUserRequestStatus;
  confirm_url: string | null;
  preflight_verified_at: string | null;
  failure_code: string | null;
  operator_evidence_id: string | null;
  requested_at: string | null;
  last_status_checked_at: string | null;
  accepted_at: string | null;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
};

export async function listSystemUserRequests(supabase: SupabaseClient, companyIds: string[]): Promise<SystemUserRequestRow[]> {
  if (companyIds.length === 0) return [];
  const { data, error } = await supabase.from("system_user_requests").select("id,company_id,initiating_owner_user_id,obligation,external_ref,altinn_request_id,status,confirm_url,preflight_verified_at,failure_code,operator_evidence_id,requested_at,last_status_checked_at,accepted_at,created_at,updated_at,resolved_at").in("company_id", companyIds).order("created_at", { ascending: false });
  if (error) throw error;
  return (data ?? []) as SystemUserRequestRow[];
}
```

The rollback must revoke new function grants before dropping/replacing functions, restore the old entitlement RPC signature and `begin_production_filing`, drop the entitlement constraint/column, then drop policies/table.

- [ ] **Step 7: Run focused schema, local RLS, grant, and type tests**

Run: `node --test tests/system_user_requests_schema.test.mjs tests/controlled_production_beta_schema.test.mjs tests/supabase_explicit_grants.test.mjs && npm run test:supabase:local -- tests/system_user_requests_database_runtime.test.mjs && npm run typecheck`

Expected: all static and local runtime tests PASS; cross-company reads are empty; direct owner mutations and stale/AAL1 RPC calls fail; service-role valid transitions pass.

- [ ] **Step 8: Commit persistence**

```bash
git add supabase/migrations supabase/rollback/rf1086_system_user_requests.sql app/lib/supabase/server.ts tests/system_user_requests_schema.test.mjs tests/system_user_requests_database_runtime.test.mjs tests/controlled_production_beta_schema.test.mjs tests/supabase_explicit_grants.test.mjs
git commit -m "feat: persist verified Systembruker requests"
```

### Task 3: Callback-Only Systemregister Hardening

**Files:**
- Create with `npx supabase migration new rf1086_systemregister_callback_operation`: the exact migration path printed by the command, ending `_rf1086_systemregister_callback_operation.sql`
- Create: `supabase/rollback/rf1086_systemregister_callback_operation.sql`
- Modify: `app/lib/authority-operations.ts`
- Modify: `app/actions.ts`
- Modify: `app/(operator)/operator/page.tsx`
- Modify: `app/lib/copy.ts`
- Modify: `tests/authority_operations.test.mjs`
- Modify: `tests/authority_operations_schema.test.mjs`
- Modify: `tests/authority_operations_actions.test.mjs`

**Interfaces:**
- Consumes: existing `executeRf1086SystemRegistration`, operator/admin checks, signed fresh AAL2, `TALLI_AUTHORITY_OPS_ENABLED`, and `authority_operations` audit table.
- Produces: operation `set_rf1086_systembruker_callback`, typed phrase `SET TALLI SYSTEMBRUKER CALLBACK`, and `executeRf1086SystembrukerCallbackUpdate`.

- [ ] **Step 1: Write failing callback-operation tests**

```js
test("callback update performs a full PUT only from the exact empty-callback definition", async () => {
  const calls = [];
  const result = await executeRf1086SystembrukerCallbackUpdate(configWithFetch(sequence([
    jsonResponse(200, exactDefinition([])),
    jsonResponse(200, exactDefinition(["https://talli.no/auth/systembruker/confirm"])),
    jsonResponse(200, exactDefinition(["https://talli.no/auth/systembruker/confirm"])),
  ], calls)));
  assert.equal(result.resultCode, "callback_updated_and_verified");
  assert.deepEqual(calls.map((call) => call.method), ["GET", "PUT", "GET"]);
  assert.deepEqual(JSON.parse(calls[1].body).allowedRedirectUrls, ["https://talli.no/auth/systembruker/confirm"]);
});

test("any non-callback drift blocks without a write", async () => {
  const calls = [];
  const result = await executeRf1086SystembrukerCallbackUpdate(configWithFetch(sequence([
    jsonResponse(200, { ...exactDefinition([]), clientId: ["unexpected-client"] }),
  ], calls)));
  assert.equal(result.resultCode, "definition_conflict");
  assert.deepEqual(calls.map((call) => call.method), ["GET"]);
});
```

- [ ] **Step 2: Run tests and observe RED**

Run: `npm run test:authority-operations`

Expected: FAIL because the callback operation and result codes are missing.

- [ ] **Step 3: Implement strict projection and GET → conditional PUT → GET**

```ts
export const SYSTEMBRUKER_CALLBACK_OPERATION = "set_rf1086_systembruker_callback" as const;
export const SYSTEMBRUKER_CALLBACK_CONFIRMATION = "SET TALLI SYSTEMBRUKER CALLBACK" as const;

export type SystembrukerCallbackResultCode =
  | "callback_already_verified"
  | "callback_updated_and_verified"
  | "definition_conflict";
```

Build both expected projections from the existing fixed registration definition. If the GET equals the callback projection, return `callback_already_verified`. If it equals the empty-callback projection, PUT the complete callback projection and verify with a second GET. If the system is absent or any right/client/vendor/description/system ID/deletion field differs, return `definition_conflict` and never POST or PUT. Cap every response and sanitize errors using the existing operation boundary.

- [ ] **Step 4: Add the audited operator action, migration, and UI**

The action must require operator admin, `TALLI_AUTHORITY_OPS_ENABLED=true`, signed AAL2 no older than 15 minutes, the exact operation and exact phrase, and record only `systemId`, callback path (without query), result code, actor, timestamps, and a sanitized error code. The UI must say that it only adds the fixed callback, show the current ops-gate state, use a native labeled input, and never imply that Systembruker creation or production filing is enabled.

- [ ] **Step 5: Run focused tests and typecheck**

Run: `npm run test:authority-operations && npm run test:security && npm run typecheck`

Expected: all tests PASS and TypeScript exits 0.

- [ ] **Step 6: Commit callback hardening**

```bash
git add app/lib/authority-operations.ts app/actions.ts 'app/(operator)/operator/page.tsx' app/lib/copy.ts supabase/migrations supabase/rollback/rf1086_systemregister_callback_operation.sql tests/authority_operations.test.mjs tests/authority_operations_schema.test.mjs tests/authority_operations_actions.test.mjs
git commit -m "feat: add callback-only Systemregister operation"
```

### Task 4: Owner Start, Callback, Status, and Preflight Orchestration

**Files:**
- Create: `app/lib/system-user-flow.ts`
- Create: `app/auth/systembruker/confirm/route.ts`
- Create: `tests/system_user_flow.test.mjs`
- Create: `tests/system_user_callback_route.test.mjs`
- Modify: `app/actions.ts`
- Modify: `app/lib/maskinporten.ts`
- Modify: `app/lib/security.ts`
- Modify: `tests/maskinporten.test.mjs`
- Modify: `tests/security_step_up.test.mjs`
- Modify: `tests/controlled_production_beta_actions.test.mjs`

**Interfaces:**
- Consumes: Task 1 client/state model, Task 2 RPCs, existing production Maskinporten credential loader, service-role client, and Next.js async `cookies()`.
- Produces: `startSystemUserRequestAction`, `refreshSystemUserRequestAction`, `reconcileSystemUserRequest`, and authenticated fixed callback behavior.

- [ ] **Step 1: Write failing orchestration tests**

```js
test("start durably records creating before the only create call and returns a safe redirect", async () => {
  const events = [];
  const result = await startSystemUserRequest(dependencies(events), { companyId, requestId, ownerId, orgNumber });
  assert.deepEqual(events.map((event) => event.kind), ["begin", "write_token", "create", "record_new"]);
  assert.equal(result.cookie.value, requestId);
  assert.deepEqual(result.cookie.options, { httpOnly: true, secure: true, sameSite: "lax", path: "/auth/systembruker/confirm", maxAge: 3600 });
  assert.match(result.confirmUrl, /^https:\/\/am\.ui\.altinn\.no\//);
});

test("accepted is persisted only after query and delegated preflight match", async () => {
  const result = await reconcileSystemUserRequest(dependencies(), requestRow("new"));
  assert.deepEqual(result.calls, ["read_token", "get_request", "query_system_user", "delegated_tax_token", "discard_token", "verify_preflight"]);
  assert.equal(result.status, "accepted");
  assert.ok(result.preflightVerifiedAt);
});

test("a duplicate or ambiguous create is recovered by externalRef without a second POST", async () => {
  const result = await retrySystemUserRequest(dependenciesWithCreateError("AUTH-00007"), requestRow("creating"));
  assert.deepEqual(result.calls, ["read_token", "lookup_by_external_ref"]);
});
```

- [ ] **Step 2: Run tests and observe RED**

Run: `node --experimental-strip-types --test tests/system_user_flow.test.mjs tests/system_user_callback_route.test.mjs`

Expected: FAIL because the flow module and callback route do not exist.

- [ ] **Step 3: Implement dependency-injected orchestration**

```ts
export type SystemUserFlowResult = {
  requestId: string;
  companyId: string;
  status: SystemUserRequestStatus;
  preflightVerifiedAt: string | null;
  confirmUrl: string | null;
};

export async function reconcileSystemUserRequest(
  dependencies: SystemUserFlowDependencies,
  request: SystemUserRequestRecord,
): Promise<SystemUserFlowResult>;
```

The start path requires authenticated owner membership and fresh AAL2 both in the action and RPC, uses a caller-generated UUID plus `generateSystemUserExternalRef()`, records `creating` before requesting a write-scope token, creates exactly once, validates the echoed relationship, records `new`, sets the cookie, then redirects. On documented duplicate/pending or an ambiguous transport result, recover only through the same `externalRef`; do not generate another reference or POST again.

The reconcile path obtains a read-scope control-plane token, loads the exact request by Altinn request ID or external reference, validates every relationship, and maps status monotonically. For `accepted`, query the resulting standard Systembruker and then request a tax-scope delegated token with `systemUserOrgNumber = company.org_number` and `systemUserExternalRef = request.external_ref`; discard it immediately and set `preflight_verified_at`. A failed preflight records `verification_failed` plus an allowlisted failure code.

- [ ] **Step 4: Implement thin Server Actions and the fixed callback**

```ts
export async function startSystemUserRequestAction(formData: FormData) {
  const companyId = requiredUuid(formData, "companyId");
  const requestId = randomUUID();
  const result = await startOwnedSystemUserRequest({ companyId, requestId });
  const cookieStore = await cookies();
  cookieStore.set("talli_system_user_request", result.requestId, {
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    path: "/auth/systembruker/confirm",
    maxAge: 3600,
  });
  redirect(result.confirmUrl);
}
```

The callback calls `supabase.auth.getUser()`, reads only `talli_system_user_request`, loads that request through owner RLS, reconciles it, deletes the cookie with the same path, and redirects to `/connections?company=<uuid>&systembruker=<allowlisted-state>`. Missing user/cookie/request and every error redirect to `/connections?systembruker=manual` without reflecting query parameters or error details.

- [ ] **Step 5: Gate entitlement management and production send**

Change operator entitlement input from arbitrary external reference to a local request UUID. Before `begin_production_filing`, load the request through the entitlement relationship and require exact company, owner, obligation, `accepted`, non-null preflight timestamp, and exact external reference. Build the delegated production token only from that stored reference. Preserve every existing production gate and do not change any default switch.

- [ ] **Step 6: Run focused action, security, Maskinporten, and type tests**

Run: `node --experimental-strip-types --test tests/system_user_flow.test.mjs tests/system_user_callback_route.test.mjs tests/maskinporten.test.mjs tests/security_step_up.test.mjs tests/controlled_production_beta_actions.test.mjs && npm run typecheck`

Expected: all tests PASS; tests prove no request query parameter is trusted, no token is persisted/logged, and mismatched/stale/unverified requests block filing.

- [ ] **Step 7: Commit owner orchestration**

```bash
git add app/lib/system-user-flow.ts app/auth/systembruker/confirm/route.ts app/actions.ts app/lib/maskinporten.ts app/lib/security.ts tests/system_user_flow.test.mjs tests/system_user_callback_route.test.mjs tests/maskinporten.test.mjs tests/security_step_up.test.mjs tests/controlled_production_beta_actions.test.mjs
git commit -m "feat: orchestrate owner Systembruker approval"
```

### Task 5: Owner Connection Surface and Honest Status UI

**Files:**
- Create: `app/(owner)/connections/page.tsx`
- Create: `app/(owner)/connections/SystemUserRequestControls.tsx`
- Create: `tests/system_user_connections_page.test.mjs`
- Modify: `app/(owner)/AppNav.tsx`
- Modify: `app/(owner)/filing/[obligation]/page.tsx`
- Modify: `app/lib/copy.ts`
- Modify: `tests/launch_copy.test.mjs`
- Modify: `tests/web_workspace.test.mjs`

**Interfaces:**
- Consumes: owner actions from Task 4 and `listSystemUserRequests` from Task 2.
- Produces: `/connections`, a navigation item, retry/manual-refresh controls, and filing links/status copy.

- [ ] **Step 1: Write failing presentation and source-contract tests**

```js
test("every durable request state has distinct Norwegian copy", () => {
  assert.deepEqual(Object.keys(copy.owner.connections.states).sort(), ["accepted", "creating", "denied", "new", "rejected", "timedout", "verification_failed"]);
  assert.match(copy.owner.connections.states.accepted.body, /verifisert/i);
  assert.match(copy.owner.connections.states.verification_failed.body, /kunne ikke verifiseres/i);
});

test("connections page uses semantic actions and never renders the external reference", () => {
  assert.match(source, /<h1[^>]*>Altinn-tilkobling<\/h1>/);
  assert.match(source, /startSystemUserRequestAction/);
  assert.match(source, /refreshSystemUserRequestAction/);
  assert.doesNotMatch(source, /external_ref|confirm_url/);
});
```

- [ ] **Step 2: Run tests and observe RED**

Run: `node --experimental-strip-types --test tests/system_user_connections_page.test.mjs tests/launch_copy.test.mjs tests/web_workspace.test.mjs`

Expected: FAIL because `/connections` and its copy do not exist.

- [ ] **Step 3: Implement the server-rendered connection page**

Render one `h1`, company selector links, one current-request region per selected company, and these exact user meanings: `creating` = “Vi gjør forespørselen klar”; `new` = “Venter på godkjenning i Altinn”; `accepted` without preflight = “Verifiserer tilkoblingen”; `accepted` with preflight = “Tilkoblingen er godkjent og verifisert”; `rejected` = “Forespørselen ble avslått”; `denied` = “Altinn nektet forespørselen”; `timedout` = “Forespørselen utløp”; `verification_failed` = “Godkjent, men kunne ikke verifiseres for innsending”. Do not show the Altinn request ID, external reference, organization number, raw failure code, or confirmation URL.

Use native forms and buttons with visible labels. Show “Opprett tilkobling” only when no live request exists, “Fortsett i Altinn” only for a validated stored Altinn URL, “Sjekk status” for non-terminal requests, “Prøv verifisering på nytt” for verification failure, and “Opprett ny forespørsel” only after terminal rejection/denial/timeout. Include an `aria-live="polite"` result region and an explicit manual-status explanation for stale/missing callbacks.

- [ ] **Step 4: Integrate navigation and filing presentation**

Add `Tilkoblinger` to the existing owner nav without changing operator visibility. On the RF-1086 filing page, replace ambiguous authority copy with a link to `/connections?company=<uuid>` and show “Systembruker mangler”, “Venter på Altinn”, “Klar for kontrollert innsending”, or “Tilkoblingen krever handling” based on durable state. Never label `new` or unverified `accepted` as ready.

- [ ] **Step 5: Run UI tests and typecheck**

Run: `node --experimental-strip-types --test tests/system_user_connections_page.test.mjs tests/launch_copy.test.mjs tests/web_workspace.test.mjs && npm run typecheck`

Expected: all tests PASS and TypeScript exits 0.

- [ ] **Step 6: Commit the owner UI**

```bash
git add 'app/(owner)/connections/page.tsx' 'app/(owner)/connections/SystemUserRequestControls.tsx' 'app/(owner)/AppNav.tsx' 'app/(owner)/filing/[obligation]/page.tsx' app/lib/copy.ts tests/system_user_connections_page.test.mjs tests/launch_copy.test.mjs tests/web_workspace.test.mjs
git commit -m "feat: add owner Altinn connection flow"
```

### Task 6: Durable RF-1086 Reconciliation and Private Feedback Artifacts

**Files:**
- Create with `npx supabase migration new rf1086_feedback_reconciliation`: the exact migration path printed by the command, ending `_rf1086_feedback_reconciliation.sql`
- Create: `supabase/rollback/rf1086_feedback_reconciliation.sql`
- Create: `app/lib/rf1086-feedback.ts`
- Create: `tests/rf1086_feedback.test.mjs`
- Create: `tests/rf1086_feedback_schema.test.mjs`
- Modify: `package.json`
- Modify: `package-lock.json`
- Modify: `app/lib/rf1086-authority-client.ts`
- Modify: `app/lib/rf1086-production.ts`
- Modify: `app/lib/documents.ts`
- Modify: `app/lib/supabase/server.ts`
- Modify: `app/actions.ts`
- Modify: `app/(owner)/filing/[obligation]/page.tsx`
- Modify: `app/(owner)/filing/_submission-presentation.ts`
- Modify: `tests/rf1086_authority_client.test.mjs`
- Modify: `tests/rf1086_production.test.mjs`
- Modify: `tests/production_submission.test.mjs`

**Interfaces:**
- Consumes: existing idempotent submission journal, `company-documents` bucket, signed document downloads, stored `forsendelse_id`, exact request/entitlement relationship, and Skatteetaten individual document endpoint.
- Produces: `getDocument`, `classifyRf1086Feedback`, `reconcileJournaledRf1086Production`, `production_feedback_artifacts`, and `reconcileRf1086ProductionAction`.

- [ ] **Step 1: Install the strict XML parser and write failing classifier tests**

Run: `npm install --save-exact saxes@6.0.0`

```js
test("known Innsendingstilbakemelding is accepted only for the stored transmission", () => {
  assert.deepEqual(classifyRf1086Feedback(bytes(acceptedXml), context), {
    classification: "accepted",
    schema: "innsendingstilbakemelding-v2",
    transmissionId: context.forsendelseId,
  });
});

test("rejection, unknown namespace, duplicate status, entity, and mismatch require action", () => {
  assert.equal(classifyRf1086Feedback(bytes(rejectedXml), context).classification, "rejected");
  for (const xml of [unknownNamespaceXml, duplicateStatusXml, doctypeXml, wrongTransmissionXml]) {
    assert.equal(classifyRf1086Feedback(bytes(xml), context).classification, "action_required");
  }
});
```

- [ ] **Step 2: Run classifier tests and observe RED**

Run: `node --experimental-strip-types --test tests/rf1086_feedback.test.mjs`

Expected: FAIL because `app/lib/rf1086-feedback.ts` does not exist.

- [ ] **Step 3: Implement bounded namespace-aware classification**

```ts
export type Rf1086FeedbackClassification = "accepted" | "rejected" | "action_required";
export type Rf1086FeedbackResult = {
  classification: Rf1086FeedbackClassification;
  schema: "innsendingstilbakemelding-v2" | "leveransetilbakemelding-v2" | "unknown";
  transmissionId: string | null;
};

export function classifyRf1086Feedback(
  bytes: Uint8Array,
  context: { forsendelseId: string; incomeYear: number },
): Rf1086FeedbackResult;
```

Reject input over 10 MiB before decoding. Use `SaxesParser` with namespaces enabled and no external resolver. Accept only root namespace `urn:ske:fastsetting:innsamling:grunnlagsdata:tilbakemelding:innsendingstilbakemelding:v2` or `urn:ske:fastsetting:innsamling:grunnlagsdata:tilbakemelding:leveransetilbakemelding:v2`; collect exactly one `leveransestatus` (`godkjent` or `avvist`), exactly one matching `forsendelseid` when present, and a matching income year when present. Parser errors, DTD/entity declarations, unknown fields that create ambiguity, missing/duplicate status, or relationship mismatch return `action_required`, never `accepted`.

- [ ] **Step 4: Write failing authority/reconciliation tests**

```js
test("initial reconciliation polls five times without another POST", async () => {
  const result = await reconcileJournaledRf1086Production(journal, authoritySequence([pending021, empty, pending1017, empty, acceptedFeedback]), input, { sleep: noDelay });
  assert.equal(result.state, "accepted");
  assert.equal(result.archiveReads, 5);
  assert.equal(result.postCalls, 0);
});

test("later reconciliation appends only state or artifact changes", async () => {
  await reconcileJournaledRf1086Production(journal, authority, input, { sleep: noDelay });
  await reconcileJournaledRf1086Production(journal, authority, input, { sleep: noDelay });
  assert.equal(journal.events.filter((event) => event.kind === "reconciliation").length, 1);
});
```

- [ ] **Step 5: Run authority/reconciliation tests and observe RED**

Run: `node --experimental-strip-types --test tests/rf1086_authority_client.test.mjs tests/rf1086_production.test.mjs tests/production_submission.test.mjs`

Expected: FAIL because individual document retrieval, durable reconciliation, and change-only events are missing.

- [ ] **Step 6: Add individual-document reads and read-only reconciliation**

```ts
export type Rf1086AuthorityDocument = {
  reference: string;
  contentType: string;
  bytes: Uint8Array;
};

export async function reconcileJournaledRf1086Production(
  journal: Rf1086ProductionJournal,
  authority: Rf1086AuthorityClient,
  input: Rf1086ReconciliationInput,
  options?: { initialPoll?: boolean; sleep?: (milliseconds: number) => Promise<void> },
): Promise<Rf1086ReconciliationResult>;
```

`getDocument` uses `GET /{inntektsaar}/forsendelser/{forsendelseId}/dokumenter/{documentId}`, percent-encodes path segments, streams at most 10 MiB, accepts only allowlisted XML/PDF/plain/octet content types, and returns bytes without logging. Extend list normalization to preserve current inline XML strings and strict object document references when present. Hash submitted hovedskjema/underskjema and never classify them as feedback.

Initial mode reads at most five times with two-second gaps and returns `processing` after the fifth pending response; it does not throw. Later mode reads once. `GLD_021`, `GLD_1017`, and empty lists are `processing`. Unknown archive shapes, conflicting statuses, or feedback that cannot be classified are `action_required`. Transport uncertainty with no authoritative outcome is `unknown`. The function never invokes any POST method.

- [ ] **Step 7: Persist artifacts privately and append change-only events**

```sql
create table public.production_feedback_artifacts (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  submission_id uuid not null references public.production_filing_submissions(id) on delete cascade,
  document_id uuid not null references public.documents(id) on delete restrict,
  authority_reference text not null,
  content_type text not null,
  byte_length bigint not null check (byte_length between 1 and 10485760),
  sha256 text not null check (sha256 ~ '^[a-f0-9]{64}$'),
  retrieved_at timestamptz not null default now(),
  classification text not null check (classification in ('accepted','rejected','action_required')),
  unique (submission_id, sha256)
);
```

Enable RLS with owner/operator SELECT using existing membership/operator helpers; deny direct authenticated mutation; grant service-only execute on one `record_production_feedback_artifact` RPC that validates company/submission/document relationships and deduplicates by SHA-256. Upload bytes first to a deterministic `authority-feedback/<company>/<submission>/<sha256>` key in `company-documents`, insert the existing `documents` row with a non-PII filename, then call the metadata RPC. If DB recording fails, remove the just-uploaded object. Never return a public URL; reuse the existing short-lived signed download route.

Store the latest durable state on `production_filing_submissions`, add an append-RPC reconciliation event only when `(state, sorted artifact hashes)` differs from the last event, and expose only safe state/count/timestamps to owners. The rollback revokes functions first and removes only this feature's columns/table/policies.

- [ ] **Step 8: Wire action and filing page resume behavior**

`reconcileRf1086ProductionAction` requires the authenticated owner, exact submission/company relationship, and matching verified Systembruker request, then performs one read-only reconciliation and revalidates the filing path. On initial send, call initial polling after the confirmation POST. On later page load, render the stored state immediately and include a small client control that submits at most one reconciliation action at a time, waits for it to settle, and reschedules a read while the state remains `sent`, `processing`, or `unknown`; stop automatically at terminal `accepted`, `rejected`, or `action_required`, on page close, or on an error that requires manual retry. Always include a visible “Sjekk status på nytt” button.

- [ ] **Step 9: Run focused tests, local role-abuse tests, and typecheck**

Run: `node --experimental-strip-types --test tests/rf1086_feedback.test.mjs tests/rf1086_feedback_schema.test.mjs tests/rf1086_authority_client.test.mjs tests/rf1086_production.test.mjs tests/production_submission.test.mjs && npm run test:supabase:local -- tests/rf1086_feedback_schema.test.mjs && npm run typecheck`

Expected: all tests PASS; repeated reconciliation is read-only and event-idempotent; feedback bytes are private; malformed/unknown feedback cannot yield acceptance.

- [ ] **Step 10: Commit reconciliation**

```bash
git add package.json package-lock.json app/lib/rf1086-feedback.ts app/lib/rf1086-authority-client.ts app/lib/rf1086-production.ts app/lib/documents.ts app/lib/supabase/server.ts app/actions.ts 'app/(owner)/filing/[obligation]/page.tsx' 'app/(owner)/filing/_submission-presentation.ts' supabase/migrations supabase/rollback/rf1086_feedback_reconciliation.sql tests/rf1086_feedback.test.mjs tests/rf1086_feedback_schema.test.mjs tests/rf1086_authority_client.test.mjs tests/rf1086_production.test.mjs tests/production_submission.test.mjs
git commit -m "feat: reconcile RF-1086 production feedback"
```

### Task 7: Mocked Browser Flow, Runbooks, and Release Gate

**Files:**
- Create: `tests/browser_system_user_flow.mjs`
- Create: `tests/fixtures/system-user-authority-mock.mjs`
- Modify: `package.json`
- Modify: `docs/filing/rf1086-production-pilot-runbook.md`
- Modify: `docs/filing/rf1086-live-release-gate.md`
- Modify: `docs/launch/evidence/production-systemregister-2026-07-16.md`
- Modify: `tests/rf1086_production_runbook.test.mjs`
- Modify: `tests/filing_release_gate.test.mjs`

**Interfaces:**
- Consumes: all previous tasks and existing browser/Supabase test harness.
- Produces: `npm run test:browser-system-user`, release-gate assertions, operator activation/recovery guidance, and final proof that all production switches remain off.

- [ ] **Step 1: Write failing browser and runbook contract tests**

```js
test("release docs require callback verification before self-service activation", () => {
  assert.match(runbook, /callback_already_verified|callback_updated_and_verified/);
  assert.match(runbook, /TALLI_AUTHORITY_OPS_ENABLED=false/);
  assert.match(runbook, /TALLI_RF1086_PRODUCTION_ENABLED=false/);
  assert.match(runbook, /rollback/i);
});
```

The Playwright scenario must create an isolated test owner/company, use a local mock adapter for all Altinn/Maskinporten/Skatteetaten calls, log in through `/login`, open `/connections`, start a request, observe the external approval redirect at the mock, return through `/auth/systembruker/confirm`, observe `accepted` plus verified copy, reload and retain it, open RF-1086 filing, reconcile `processing` to `accepted`, reload, and download the private feedback artifact. It must also prove a tampered callback query parameter does not select another request and that another owner receives neither the request nor artifact.

- [ ] **Step 2: Run tests and observe RED**

Run: `node --test tests/rf1086_production_runbook.test.mjs tests/filing_release_gate.test.mjs && npm run test:browser-system-user`

Expected: runbook assertions fail and npm reports the missing `test:browser-system-user` script.

- [ ] **Step 3: Implement the local authority mock and Playwright flow**

The mock binds only to `127.0.0.1`, stores opaque synthetic IDs in memory, returns fixed contract-valid JSON/XML, and exits with the test. The Next test server receives only test adapter base URLs and local Supabase credentials. Do not proxy, record, or replay production traffic. Use Playwright roles/labels, wait on explicit UI states rather than arbitrary sleeps, capture console warnings/errors, test keyboard focus order, and verify 320 px and 1440 px viewports.

- [ ] **Step 4: Update runbooks and release gates**

Document this activation order: deploy schema/code with both switches off; perform and audit the callback-only Systemregister operation; verify exact GET projection; exercise mocked/local flow; approve explicit pilot entitlement referencing a verified request; separately authorize any production filing. Document recovery for stale callback, duplicate/pending request, failed preflight, processing archive, unknown feedback, failed artifact persistence, and rollback. Explicitly state that this implementation did not make a live request, change Systemregister, enable a switch, grant an entitlement, or submit a filing.

- [ ] **Step 5: Run the full relevant release verification**

Run: `npm run test:authority-operations && npm run test:maskinporten && npm run test:rf1086:authority-client && npm run test:rf1086:production-pilot && npm run test:filing-release-gate && npm run test:security && npm run test:supabase-grants && npm run test:supabase:local && npm run test:supabase-advisors && npm run test:browser-system-user && npm run typecheck && npm run build`

Expected: every command exits 0; browser console has no error/warning; local RLS abuse tests pass; advisors report no accepted new errors; production switches remain off.

- [ ] **Step 6: Commit browser and release evidence**

```bash
git add tests/browser_system_user_flow.mjs tests/fixtures/system-user-authority-mock.mjs package.json docs/filing/rf1086-production-pilot-runbook.md docs/filing/rf1086-live-release-gate.md docs/launch/evidence/production-systemregister-2026-07-16.md tests/rf1086_production_runbook.test.mjs tests/filing_release_gate.test.mjs
git commit -m "test: prove RF-1086 self-service release flow"
```

## Final Cross-Cutting Review

- [ ] Generate one merge-base-to-HEAD review package and dispatch a fresh broad reviewer using the `requesting-code-review` template.
- [ ] Fix every Critical and Important finding through observed RED → GREEN cycles, re-run the affected focused suites, and re-review until none remain.
- [ ] Search the complete diff for secrets, tokens, private keys, organization numbers, emails, raw XML, unrestricted URLs, missing response caps, `service_role` in client code, and production switches accidentally enabled.
- [ ] Confirm the progress ledger at `.superpowers/sdd/progress.md` lists every task commit and review disposition.
- [ ] Run the full Task 7 release-verification command again from a clean worktree and record exact results in the final handoff.
