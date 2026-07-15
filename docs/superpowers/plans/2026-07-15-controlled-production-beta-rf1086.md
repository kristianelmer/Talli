# Controlled Production Beta — RF-1086 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a deny-by-default, operator-entitled RF-1086 production-pilot path that binds fresh owner approval to an immutable payload, journals every authority mutation, prevents duplicate sends, and reports only authority-proven outcomes.

**Architecture:** Keep simulation/test submissions untouched and introduce a separate production-only aggregate. PostgreSQL owns entitlement, immutable approval, append-only journal, tenant isolation, and AAL2 enforcement; TypeScript owns deterministic hashes, release-gate evaluation, credential/environment validation, and the journaled Skatteetaten orchestration. Production is reachable only when the exact company/user/year/obligation entitlement, authority permission, TT02 evidence, human signoffs, supported profile, fresh AAL2, adapter flag, and production credentials all pass.

**Tech Stack:** Next.js 16 server actions, React 19, TypeScript 6, Supabase/PostgreSQL RLS and security-definer RPCs, Node test runner, existing Maskinporten and Skatteetaten RF-1086 clients.

## Global Constraints

- Start with `aksjonaerregisteroppgaven` and the exact `rf1086_no_activity_v1` case profile only.
- `skattemelding` and `aarsregnskap` remain production-unimplemented and disabled.
- Customers cannot create, widen, activate, extend, or revoke their own pilot entitlements.
- Free-beta billing bypass applies only to an active exact entitlement with `billing_exempt = true`; paid production still requires the existing billing gate and billing signoff.
- Owner approval and authority send are separate AAL2-protected actions.
- A changed payload, adapter version, company, year, obligation, or case profile invalidates approval.
- Every authority mutation has a persisted stable UUID idempotency key before the network call.
- A timeout or unknown outcome is quarantined; it is never blindly retried.
- HTTP success, a dialog ID, a forsendelse ID, or archived submitted documents never mean final acceptance.
- Production is disabled unless `TALLI_RF1086_PRODUCTION_ENABLED=true`; no test endpoint, test key path, or TT02 credential may be selected by production code.
- Secrets remain only in server-side environment/managed secret storage and are never stored in rows, browser output, logs, or evidence archives.
- No real production request is made by automated tests or by completing this plan.

## File map

- `app/lib/production-pilot.ts`: exact entitlement validation and supported-profile rules.
- `app/lib/production-approval.ts`: deterministic approval manifest and SHA-256 hashing.
- `app/lib/production-submission.ts`: normalized status machine and journal contracts.
- `app/lib/rf1086-production.ts`: resumable RF-1086 operation sequence over injected journal and authority client.
- `app/lib/filing-release-gate.ts`: includes exact entitlement and narrowly scoped free-beta billing behavior.
- `app/lib/authority-adapters.ts`: reads the RF production kill switch; other adapters stay disabled.
- `app/lib/supabase/server.ts`: typed reads for pilot entitlement, approval, submission, and events.
- `app/actions.ts`: operator entitlement, owner approval, and owner send actions.
- `app/(operator)/operator/page.tsx`: exact entitlement activation/suspension control.
- `app/(owner)/filing/[obligation]/page.tsx`: real-filing review, approval, send, and honest status presentation.
- `supabase/migrations/20260715180000_controlled_production_beta.sql`: production aggregate, RLS, grants, AAL2 RPCs, and append-only enforcement.
- `supabase/rollback/controlled_production_beta.sql`: manual rollback outside the auto-applied migration stream; it disables functions before dropping additive objects.
- `tests/production_pilot.test.mjs`: entitlement and free-beta release-gate behavior.
- `tests/production_approval.test.mjs`: manifest hashing and invalidation.
- `tests/production_submission.test.mjs`: legal status transitions and retry policy.
- `tests/rf1086_production.test.mjs`: operation order, idempotency, resume, and unknown-outcome quarantine.
- `tests/controlled_production_beta_schema.test.mjs`: static SQL privilege, RLS, AAL2, and append-only assertions.
- `tests/supabase_workspace.test.mjs`: local database owner/operator/outsider enforcement.
- `.env.example`: production-only variable names with empty values.
- `app/lib/backup-restore.ts`: adds production aggregate tables to launch-critical backup order.
- `docs/filing/rf1086-live-release-gate.md`: first-production-run and kill-switch runbook.

---

### Task 1: Exact pilot entitlement and free-beta release gate

**Files:**
- Create: `app/lib/production-pilot.ts`
- Modify: `app/lib/filing-release-gate.ts`
- Test: `tests/production_pilot.test.mjs`

**Interfaces:**
- Produces: `ProductionPilotEntitlement`, `ProductionPilotContext`, `evaluateProductionPilotEntitlement(context, entitlement, now)`, and `isBillingExemptProductionPilot(entitlement)`.
- Consumes: `AuthorityObligation` and the existing billing/authority/evidence/signoff/step-up gates.

- [ ] **Step 1: Write failing entitlement and release-gate tests**

```js
test("requires an exact active company/user/year/obligation/profile entitlement", () => {
  const result = evaluateProductionPilotEntitlement(context, {
    ...entitlement,
    user_id: "another-owner",
  }, new Date("2026-07-15T12:00:00Z"));
  assert.deepEqual(result, { allowed: false, reason: "pilot_entitlement_user_mismatch" });
});

test("bypasses billing only for an exact billing-exempt pilot", () => {
  const gate = buildFilingReleaseGates({
    ...readyGateInput,
    billingAccount: null,
    pilotContext: context,
    pilotEntitlements: [entitlement],
  }).find((item) => item.obligation === "aksjonaerregisteroppgaven");
  assert.equal(gate.status, "production_ready");
  assert.ok(!gate.disabledReasons.includes("billing_account_missing"));
  assert.ok(!gate.disabledReasons.some((reason) => reason.startsWith("billing_refund_signoff_")));
});
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `node --experimental-strip-types --test tests/production_pilot.test.mjs`

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `app/lib/production-pilot.ts`.

- [ ] **Step 3: Implement the minimal exact-match domain**

```ts
export type ProductionPilotEntitlement = {
  id: string;
  company_id: string;
  user_id: string;
  income_year: number;
  obligation: AuthorityObligation;
  case_profile: "rf1086_no_activity_v1";
  status: "pending" | "active" | "suspended" | "completed" | "revoked";
  billing_exempt: boolean;
  starts_at: string;
  expires_at: string;
};

export function evaluateProductionPilotEntitlement(
  context: ProductionPilotContext,
  entitlement: ProductionPilotEntitlement | null,
  now = new Date(),
): ProductionPilotGate {
  if (!entitlement) return { allowed: false, reason: "pilot_entitlement_missing" };
  if (entitlement.company_id !== context.companyId) return { allowed: false, reason: "pilot_entitlement_company_mismatch" };
  if (entitlement.user_id !== context.userId) return { allowed: false, reason: "pilot_entitlement_user_mismatch" };
  if (entitlement.income_year !== context.incomeYear) return { allowed: false, reason: "pilot_entitlement_year_mismatch" };
  if (entitlement.obligation !== context.obligation) return { allowed: false, reason: "pilot_entitlement_obligation_mismatch" };
  if (entitlement.case_profile !== context.caseProfile) return { allowed: false, reason: "pilot_entitlement_profile_mismatch" };
  if (entitlement.status !== "active") return { allowed: false, reason: `pilot_entitlement_${entitlement.status}` };
  if (now < new Date(entitlement.starts_at) || now >= new Date(entitlement.expires_at)) return { allowed: false, reason: "pilot_entitlement_inactive_interval" };
  return { allowed: true, reason: "pilot_entitlement_active" };
}
```

Update `buildFilingReleaseGates` to accept `pilotContext` and `pilotEntitlements`, require the exact entitlement, and skip only `billing_account_missing` plus `billing_refund` for an allowed entitlement whose `billing_exempt` is true.

- [ ] **Step 4: Run focused and regression tests**

Run: `node --experimental-strip-types --test tests/production_pilot.test.mjs tests/filing_release_gate.test.mjs`

Expected: all tests PASS; legacy inputs without an entitlement remain `production_disabled`.

- [ ] **Step 5: Commit the slice**

```bash
git add app/lib/production-pilot.ts app/lib/filing-release-gate.ts tests/production_pilot.test.mjs tests/filing_release_gate.test.mjs
git commit -m "feat: gate production filing by exact pilot entitlement"
```

### Task 2: Immutable approval and legal production state machine

**Files:**
- Create: `app/lib/production-approval.ts`
- Create: `app/lib/production-submission.ts`
- Test: `tests/production_approval.test.mjs`
- Test: `tests/production_submission.test.mjs`

**Interfaces:**
- Produces: `buildProductionApprovalManifest`, `productionApprovalHash`, `approvalMatchesCurrentPayload`, `ProductionSubmissionStatus`, `transitionProductionSubmission`, and `classifyRf1086TransportOutcome`.
- Consumes: `rf1086PayloadHash` and RF preview document hashes.

- [ ] **Step 1: Write failing deterministic-hash and illegal-transition tests**

```js
test("approval hash changes when any legally relevant value changes", () => {
  const manifest = buildProductionApprovalManifest(input);
  assert.equal(productionApprovalHash(manifest), productionApprovalHash({ ...manifest }));
  assert.notEqual(productionApprovalHash(manifest), productionApprovalHash({ ...manifest, incomeYear: 2024 }));
});

test("transport acknowledgement cannot become accepted", () => {
  assert.throws(
    () => transitionProductionSubmission("received", "accepted", { finalAuthorityDecision: false }),
    /final authority decision/i,
  );
  assert.equal(classifyRf1086TransportOutcome({ forsendelseId: "id", documents: ["submitted"] }), "processing");
});
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `node --experimental-strip-types --test tests/production_approval.test.mjs tests/production_submission.test.mjs`

Expected: FAIL because both modules are missing.

- [ ] **Step 3: Implement canonical manifest hashing and transition allowlist**

The manifest contains `companyId`, `userId`, `organizationNumber`, `incomeYear`, `obligation`, `caseProfile`, `adapterVersion`, `previewId`, `payloadHash`, sorted document hashes, sorted blockers, and sorted warnings. Serialize a fixed object shape with sorted arrays and hash it with SHA-256. Define statuses `approved`, `sending`, `received`, `processing`, `accepted`, `rejected`, `action_required`, and `unknown`. Allow only `approved→sending`, `sending→received|unknown|rejected`, `received→processing|rejected|action_required`, and `processing→accepted|rejected|action_required`; require `finalAuthorityDecision: true` for `accepted`.

- [ ] **Step 4: Run focused tests**

Run: `node --experimental-strip-types --test tests/production_approval.test.mjs tests/production_submission.test.mjs`

Expected: all tests PASS.

- [ ] **Step 5: Commit the slice**

```bash
git add app/lib/production-approval.ts app/lib/production-submission.ts tests/production_approval.test.mjs tests/production_submission.test.mjs
git commit -m "feat: bind production approval to immutable filing state"
```

### Task 3: Production aggregate, RLS, and AAL2 database boundary

**Files:**
- Create: `supabase/migrations/20260715180000_controlled_production_beta.sql`
- Create: `supabase/rollback/controlled_production_beta.sql`
- Create: `tests/controlled_production_beta_schema.test.mjs`
- Modify: `tests/supabase_workspace.test.mjs`

**Interfaces:**
- Produces tables `production_pilot_entitlements`, `filing_approval_snapshots`, `production_filing_submissions`, `production_filing_events`; RPCs `approve_production_filing`, `begin_production_filing`, and `append_production_filing_event`.
- Consumes signed `auth.jwt()` AAL2/AMR, `memberships`, `operator_profiles`, `authority_permissions`, `authority_test_runs`, and `launch_signoffs`.

- [ ] **Step 1: Write failing static schema abuse tests**

```js
test("production tables deny direct customer mutation", () => {
  assert.match(sql, /revoke all on public\.production_pilot_entitlements from anon, authenticated/i);
  assert.match(sql, /grant select on public\.production_pilot_entitlements to authenticated/i);
  assert.doesNotMatch(sql, /grant\s+(?:insert|update|delete)[^;]*production_pilot_entitlements[^;]*authenticated/i);
});

test("approval and send RPCs enforce owner AAL2 and exact active entitlement", () => {
  assert.match(sql, /auth\.jwt\(\)[\s\S]*aal[\s\S]*aal2/i);
  assert.match(sql, /production_pilot_entitlements[\s\S]*status = 'active'[\s\S]*user_id = auth\.uid\(\)/i);
});
```

- [ ] **Step 2: Run static test and confirm RED**

Run: `node --test tests/controlled_production_beta_schema.test.mjs`

Expected: FAIL because the migration is missing.

- [ ] **Step 3: Add the additive schema and security-definer boundaries**

Create constrained enum-like checks, foreign keys, unique exact-entitlement index, immutable approval rows, one production submission per approval, append-only event rows, and member-select/operator-select policies. Revoke all table mutation privileges from authenticated users. Grant only select and narrowly scoped RPC execute. Each RPC sets `search_path = public, pg_temp`, rejects missing/stale signed AAL2 AMR, verifies current owner membership and exact active entitlement, and validates input against persisted preview/approval hashes. `append_production_filing_event` is callable only through an internal database role boundary, not by browsers.

- [ ] **Step 4: Add local Supabase role tests**

Test that an admin operator can create and activate one exact entitlement; the named owner can read it and invoke approval/begin with fresh AAL2; adviser, outsider, another owner, and the customer directly inserting/updating any production table are denied; direct event update/delete is denied; suspended/expired/mismatched entitlements fail.

- [ ] **Step 5: Run schema and local database tests**

Run: `node --test tests/controlled_production_beta_schema.test.mjs`

Run: `npm run test:supabase:local`

Expected: both commands PASS.

- [ ] **Step 6: Commit the slice**

```bash
git add supabase/migrations/20260715180000_controlled_production_beta.sql supabase/rollback/controlled_production_beta.sql tests/controlled_production_beta_schema.test.mjs tests/supabase_workspace.test.mjs
git commit -m "feat: add protected production filing aggregate"
```

### Task 4: Resumable RF-1086 production orchestrator

**Files:**
- Create: `app/lib/rf1086-production.ts`
- Create: `tests/rf1086_production.test.mjs`
- Modify: `app/lib/rf1086-authority-client.ts`

**Interfaces:**
- Consumes: `Rf1086AuthorityClient` individual methods and the durable journal interface.
- Produces: `executeJournaledRf1086Production(input, dependencies)` returning `received`, `processing`, `rejected`, or `unknown` with sanitized references.

- [ ] **Step 1: Write failing orchestration tests**

```js
test("persists stable prepared keys before each authority mutation and resumes", async () => {
  const result = await executeJournaledRf1086Production(input, { journal, authorityClient });
  assert.deepEqual(journal.operations.map((op) => [op.name, op.state]), [
    ["post_hovedskjema", "succeeded"],
    ["post_underskjema:owner", "succeeded"],
    ["confirm", "succeeded"],
    ["list_documents", "succeeded"],
  ]);
  assert.ok(journal.operations.slice(0, 3).every((op) => UUID_PATTERN.test(op.idempotencyKey)));
  assert.equal(result.status, "processing");
});

test("quarantines a mutation timeout instead of retrying", async () => {
  await assert.rejects(executeJournaledRf1086Production(input, { journal, authorityClient: timeoutClient }), /unknown outcome/i);
  assert.equal(journal.operations.at(-1).state, "unknown");
  assert.equal(timeoutClient.postCount, 1);
});
```

- [ ] **Step 2: Run focused test and confirm RED**

Run: `node --experimental-strip-types --test tests/rf1086_production.test.mjs`

Expected: FAIL because `rf1086-production.ts` is missing.

- [ ] **Step 3: Implement the journal contract and sequential executor**

```ts
export interface ProductionOperationJournal {
  prepare(input: { submissionId: string; name: string; bodyHash: string; idempotencyKey: string | null }): Promise<ProductionOperation>;
  succeed(operationId: string, authorityReference: string | null): Promise<void>;
  fail(operationId: string, failure: { classification: "retryable" | "blocked" | "unknown"; code: string; correlationId: string | null }): Promise<void>;
}
```

For each write: call `prepare`, reuse the returned persisted key, call one authority method, then call `succeed`. Skip already succeeded operations on resume. If a network/timeout error occurs after dispatch, write `unknown` and stop. Archive lookup is read-only and may use bounded retry. Return `processing` when the authority only exposes submitted documents.

- [ ] **Step 4: Run RF production and existing client tests**

Run: `node --experimental-strip-types --test tests/rf1086_production.test.mjs tests/rf1086_authority_client.test.mjs`

Expected: all tests PASS and no result contains the access token or raw XML.

- [ ] **Step 5: Commit the slice**

```bash
git add app/lib/rf1086-production.ts app/lib/rf1086-authority-client.ts tests/rf1086_production.test.mjs tests/rf1086_authority_client.test.mjs
git commit -m "feat: journal RF-1086 production authority operations"
```

### Task 5: Server-side kill switch and production credential boundary

**Files:**
- Modify: `app/lib/authority-adapters.ts`
- Modify: `app/lib/rf1086-submission.ts`
- Modify: `app/lib/maskinporten.ts`
- Modify: `.env.example`
- Create: `tests/rf1086_production_environment.test.mjs`

**Interfaces:**
- Produces: `rf1086ProductionEnvironment()` and truthful RF adapter capability.
- Consumes only `TALLI_RF1086_PRODUCTION_ENABLED`, `TALLI_PROD_MASKINPORTEN_CLIENT_ID`, `TALLI_PROD_MASKINPORTEN_KEY_ID`, `TALLI_PROD_MASKINPORTEN_PRIVATE_KEY_PEM`, and exact RF scope.

- [ ] **Step 1: Write failing environment-boundary tests**

```js
test("production stays disabled by default and rejects TT02 material", () => {
  assert.equal(rf1086ProductionEnvironment({}), null);
  assert.throws(() => rf1086ProductionEnvironment({
    TALLI_RF1086_PRODUCTION_ENABLED: "true",
    TALLI_PROD_MASKINPORTEN_CLIENT_ID: "client",
    TALLI_PROD_MASKINPORTEN_KEY_ID: "key",
    TALLI_PROD_MASKINPORTEN_PRIVATE_KEY_PEM: "/Users/me/talli-test.key",
  }), /PEM|test credential/i);
});
```

- [ ] **Step 2: Run focused test and confirm RED**

Run: `node --experimental-strip-types --test tests/rf1086_production_environment.test.mjs`

Expected: FAIL because the environment reader is missing.

- [ ] **Step 3: Implement strict production-only configuration**

Require the flag to be the exact string `true`, require an inline PEM beginning `-----BEGIN PRIVATE KEY-----` or `-----BEGIN RSA PRIVATE KEY-----`, reject filesystem paths and values containing `test`, require non-empty client/key IDs, hard-code the production Maskinporten issuer/token endpoint through the existing production environment selector, and leave tax/annual capabilities false.

- [ ] **Step 4: Run environment, Maskinporten, and adapter tests**

Run: `node --experimental-strip-types --test tests/rf1086_production_environment.test.mjs tests/maskinporten.test.mjs tests/authority_adapters.test.mjs`

Expected: all tests PASS; current process environment without the flag reports RF production disabled.

- [ ] **Step 5: Commit the slice**

```bash
git add app/lib/authority-adapters.ts app/lib/rf1086-submission.ts app/lib/maskinporten.ts .env.example tests/rf1086_production_environment.test.mjs tests/authority_adapters.test.mjs
git commit -m "feat: enforce RF-1086 production credential boundary"
```

### Task 6: Operator entitlement and owner approval/send flows

**Files:**
- Modify: `app/lib/supabase/server.ts`
- Modify: `app/lib/workspace-data.ts`
- Modify: `app/actions.ts`
- Modify: `app/(operator)/operator/page.tsx`
- Modify: `app/(owner)/filing/[obligation]/page.tsx`
- Create: `tests/controlled_production_beta_actions.test.mjs`
- Modify: `tests/owner_filing_flow.test.mjs`

**Interfaces:**
- Produces server actions `upsertProductionPilotEntitlement`, `approveProductionFiling`, and `sendApprovedRf1086ProductionFiling`.
- Consumes the protected RPCs, exact entitlement gate, approval hash, release gate, production environment reader, Maskinporten token provider, and journaled RF executor.

- [ ] **Step 1: Write failing action/UI contract tests**

Assert that operator action accepts only UUID company/user IDs, income year 2000–2100, RF obligation, exact case profile, bounded ISO activation/expiry, and explicit evidence; owner approval requires the exact real-filing checkbox and calls the approval RPC; send re-reads persisted approval/preview/entitlement/signoffs and never trusts hidden payload or status fields; production UI says `Godkjent av deg` before send and `Mottatt`/`Til behandling` after transport, never `Godkjent` without a final decision.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `node --experimental-strip-types --test tests/controlled_production_beta_actions.test.mjs tests/owner_filing_flow.test.mjs`

Expected: FAIL because the actions and presentation contracts are missing.

- [ ] **Step 3: Add typed reads and operator control**

Add row types and list/get functions for entitlements, approvals, submissions, and events. The operator form exposes exact company, named owner, year, fixed obligation/profile, dates, billing exemption, status, and evidence reference. The action calls a database RPC that independently verifies `operator_profiles.role = 'admin'` and records `approved_by = auth.uid()`.

- [ ] **Step 4: Add owner review and approval**

Render organization, year, supported profile, blockers/warnings, visible values, downloadable exact documents, hashes, and the real-filing warning. `approveProductionFiling` requires fresh step-up, recomputes the manifest from persisted rows, and invokes `approve_production_filing`; no XML or client-selected hash is accepted from the form.

- [ ] **Step 5: Add fail-closed send action**

`sendApprovedRf1086ProductionFiling` revalidates fresh step-up, membership, exact active entitlement, current payload hash, approval hash, authority permission, accepted test evidence, signoffs, adapter flag, and credentials. It begins/resumes the protected submission, obtains a production Maskinporten token in memory, executes the journaled RF sequence, persists sanitized events/references, revalidates the page, and returns a safe Norwegian status message. Unknown outcomes direct the user to support and never perform a second write.

- [ ] **Step 6: Run focused tests, typecheck, and build**

Run: `node --experimental-strip-types --test tests/controlled_production_beta_actions.test.mjs tests/owner_filing_flow.test.mjs`

Run: `npm run typecheck`

Run: `npm run build`

Expected: all commands PASS.

- [ ] **Step 7: Commit the slice**

```bash
git add app/lib/supabase/server.ts app/lib/workspace-data.ts app/actions.ts 'app/(operator)/operator/page.tsx' 'app/(owner)/filing/[obligation]/page.tsx' tests/controlled_production_beta_actions.test.mjs tests/owner_filing_flow.test.mjs
git commit -m "feat: add controlled RF-1086 owner production flow"
```

### Task 7: Backup, monitoring, correction boundary, and release evidence

**Files:**
- Modify: `app/lib/backup-restore.ts`
- Modify: `tests/backup_restore.test.mjs`
- Modify: `docs/filing/rf1086-live-release-gate.md`
- Modify: `docs/filing/authority-onboarding-runbook.md`
- Modify: `docs/launch/customer-ready-decision-map.md`
- Create: `docs/filing/rf1086-production-pilot-runbook.md`
- Create: `tests/rf1086_production_runbook.test.mjs`

**Interfaces:**
- Produces a first-run operator checklist, kill-switch procedure, unknown-outcome reconciliation, evidence export, support route, and linked correction record procedure.
- Consumes the production aggregate table order and exact status vocabulary.

- [ ] **Step 1: Write failing backup/runbook contract tests**

Assert that the critical-table manifest orders entitlement → approval → submission → events, restore validation fails when any production aggregate is absent, and the runbook contains exact pre-flight, credential fingerprint, deployed SHA, named customer, supported profile, statutory fallback/support contact, kill-switch command, duplicate-risk quarantine, receipt/final-feedback distinction, evidence archive, and correction-link steps.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `node --experimental-strip-types --test tests/backup_restore.test.mjs tests/rf1086_production_runbook.test.mjs`

Expected: FAIL because the aggregate and runbook requirements are absent.

- [ ] **Step 3: Implement backup ordering and operational documentation**

Add all four production tables to the backup manifest and restore gate. Document that `TALLI_RF1086_PRODUCTION_ENABLED=false` is the immediate kill switch; disabling transport preserves approvals/journals. Define stuck-state thresholds, safe correlation-ID logging, authority/delegation failure escalation, evidence export, final-feedback verification, and the rule that a correction creates a new approval/submission linked by `supersedes_submission_id`.

- [ ] **Step 4: Run focused tests**

Run: `node --experimental-strip-types --test tests/backup_restore.test.mjs tests/rf1086_production_runbook.test.mjs`

Expected: all tests PASS.

- [ ] **Step 5: Commit the slice**

```bash
git add app/lib/backup-restore.ts tests/backup_restore.test.mjs docs/filing/rf1086-live-release-gate.md docs/filing/authority-onboarding-runbook.md docs/launch/customer-ready-decision-map.md docs/filing/rf1086-production-pilot-runbook.md tests/rf1086_production_runbook.test.mjs
git commit -m "docs: operationalize controlled RF-1086 production pilot"
```

### Task 8: Full security and release verification

**Files:**
- Modify only files required to fix failures caused by Tasks 1–7.

**Interfaces:**
- Produces a verified, still-disabled production-pilot build.

- [ ] **Step 1: Run the full launch rehearsal**

Run: `npm run test:launch-rehearsal`

Expected: PASS.

- [ ] **Step 2: Run database and deployed-contract verification**

Run: `npm run test:supabase:local`

Run: `npm run test:deployed-contract`

Expected: PASS.

- [ ] **Step 3: Run compiler and production build**

Run: `npm run typecheck`

Run: `npm run build`

Expected: PASS.

- [ ] **Step 4: Run dependency and secret checks**

Run: `npm audit --audit-level=high`

Run: `git grep -n -I -E 'BEGIN (RSA )?PRIVATE KEY|eyJ[a-zA-Z0-9_-]{20,}|talli-test\.key' -- ':!docs/superpowers/plans/*' ':!tests/*'`

Expected: audit exits 0 with no high/critical reachable vulnerabilities; secret scan has no output.

- [ ] **Step 5: Confirm deny-by-default behavior**

Run: `env -u TALLI_RF1086_PRODUCTION_ENABLED node --experimental-strip-types --test tests/rf1086_production_environment.test.mjs tests/authority_adapters.test.mjs`

Expected: PASS and RF production capability is disabled.

- [ ] **Step 6: Inspect final diff and commit verification fixes if any**

Run: `git diff --check && git status --short && git log --oneline --decorate -12`

Expected: no whitespace errors; only intentional changes; clean working tree after any fix commit.

- [ ] **Step 7: Apply the finishing-development-branch skill**

Review changes against the approved design, do not enable the production environment flag, do not enter real credentials, and integrate only after all verification evidence is green.
