# Customer-ready foundation implementation plan

> **For Codex:** Execute this plan with the `executing-plans` skill. Use the
> `superpowers-test-driven-development` red-green-refactor loop for every behavior
> change and `verification-before-completion` before claiming success.

**Goal:** Replace the forgeable customer-authored step-up mechanism with verified
Supabase AAL2 claims, make production filing depend on operator-only release
evidence and a final founder signoff, and make the public site truthfully describe
an invite-only free beta.

**Architecture:** User-presence proof comes only from a server-verified Supabase JWT:
the subject must match the authenticated user, `aal` must be `aal2`, and the newest
MFA authentication-method reference must be within the action's 15-minute window.
Human/environment readiness stays separate in operator-only `launch_signoffs` and
deny-by-default authority-adapter flags. The legacy `step_up_events` table remains
for historical compatibility but loses all customer grants and policies. Public
copy remains conservative until the same release gates are evidenced.

**Stack:** Next.js 16, React 19, TypeScript 6, Supabase Auth/Postgres/RLS, Node test
runner, Supabase CLI, Playwright.

**Non-negotiable release state:** Do not enable production authority adapters,
Vipps/live charging, paid-customer admission, or the
`founder_production_go_live` signoff in this plan.

---

## Task 1: Verify signed AAL2 claims at the application boundary

**Files:**

- Modify: `tests/security_step_up.test.mjs`
- Modify: `app/lib/security.ts`
- Verify callers: `app/actions.ts`

### Step 1: Write failing claim-boundary tests

Replace event-row fixtures in `tests/security_step_up.test.mjs` with signed-claim
shapes and a fake Supabase client exposing `auth.getClaims()`. Cover:

- fresh TOTP or WebAuthn `amr` + `aal2` + matching `sub` passes;
- `aal1`, missing `amr`, mismatched `sub`, invalid timestamp, future timestamp, and
  timestamp older than 15 minutes fail closed;
- a forged legacy `step_up_events` row is never read;
- allowed and blocked security audit records still persist;
- production filing has the same fresh-AAL2 requirement as other protected actions
  and no longer accepts caller-supplied security-review or credential booleans.

Use this target API in the tests:

```ts
const context = stepUpContextFromClaims("owner", {
  sub: "owner",
  aal: "aal2",
  amr: [{ method: "totp", timestamp: 1781603700 }],
});

const supabase = {
  auth: { async getClaims() { return { data: { claims }, error: null }; } },
  from(table) { /* audit_events only */ },
};
```

### Step 2: Prove the tests are red

Run:

```bash
npm run test:security
```

Expected: FAIL because `stepUpContextFromClaims` does not exist and the current
implementation still queries `step_up_events` and trusts caller booleans.

### Step 3: Implement the smallest trusted-claims boundary

In `app/lib/security.ts`:

- reduce `StepUpContext` to `actorId` and `mfaVerifiedAt`;
- reduce `StepUpRequirement` to user-presence fields; production readiness is not a
  user step-up property;
- replace `SupabaseStepUpClient` with a client type containing `auth.getClaims()`
  plus `from()` for audit writes;
- add a small claim parser that accepts the Supabase signed-claim shape but never a
  raw token from request input;
- require matching `sub` and exact `aal2`;
- select the newest finite `amr.timestamp` whose method represents MFA
  (`totp`, `webauthn`, or `mfa`), convert seconds to ISO, and let
  `assertStepUpAllowed` enforce the action-specific age/future rule;
- replace `loadLatestStepUpContext` with `loadTrustedStepUpContext`, using
  `supabase.auth.getClaims()` and converting provider/shape failures to stable
  `SensitiveActionStepUpError` codes;
- keep audit messages free of JWT/claim contents.

The trusted context must have this shape:

```ts
export type StepUpContext = {
  actorId: string;
  mfaVerifiedAt: string | null;
};
```

### Step 4: Prove the focused tests are green

Run:

```bash
npm run test:security
npm run typecheck
```

Expected: PASS.

### Step 5: Commit the trusted application boundary

```bash
git add tests/security_step_up.test.mjs app/lib/security.ts app/actions.ts
git commit -m "fix: trust verified aal2 claims for step-up"
```

---

## Task 2: Revoke the forgeable database path and protect corporate RPCs

**Files:**

- Create: `tests/trusted_aal2_schema.test.mjs`
- Modify: `tests/supabase_workspace.test.mjs`
- Modify: `tests/fixtures/corporate_documents/database_rehearsal.sql`
- Modify: `package.json`
- Create with Supabase CLI, then modify:
  `supabase/migrations/<timestamp>_trusted_aal2_boundary.sql`

### Step 1: Verify the supported migration command

Run:

```bash
npx supabase --version
npx supabase migration new --help
```

Expected: Supabase CLI 2.109.1 and help for creating a migration.

### Step 2: Write failing static schema tests

Add `tests/trusted_aal2_schema.test.mjs`. It must locate the migration by suffix
`_trusted_aal2_boundary.sql` and assert that it:

- revokes authenticated/anonymous access to `public.step_up_events`;
- drops both legacy customer policies;
- replaces `public.assert_fresh_corporate_step_up(uuid)`;
- checks `auth.uid()`, `auth.jwt()->>'aal' = 'aal2'`, and signed `amr` freshness;
- does not read `public.step_up_events` inside the replacement function;
- adds `founder_production_go_live` to the database launch-signoff key constraint.

Add `test:trusted-aal2-schema` to `package.json` and include it immediately after
`test:security` in `test:launch-rehearsal`.

### Step 3: Invert the live database expectation

In `tests/supabase_workspace.test.mjs`, change the owner step-up insert/read
expectations so both owner and outsider customer sessions are denied. Preserve the
rest of the tenant-isolation assertions.

In `tests/fixtures/corporate_documents/database_rehearsal.sql`, remove the
`step_up_events` insert. Before corporate RPC calls, set transaction-local claims:

```sql
select set_config(
  'request.jwt.claims',
  jsonb_build_object(
    'sub', :'owner_id',
    'aal', 'aal2',
    'amr', jsonb_build_array(
      jsonb_build_object('method', 'totp', 'timestamp', extract(epoch from now())::bigint)
    )
  )::text,
  true
);
```

### Step 4: Prove the schema tests are red

Run:

```bash
npm run test:trusted-aal2-schema
```

Expected: FAIL because the migration does not exist.

### Step 5: Create and implement the migration

Run exactly once:

```bash
npx supabase migration new trusted_aal2_boundary
```

Edit the generated file with `apply_patch`. The migration must:

1. revoke every customer grant on `step_up_events` from `anon` and
   `authenticated`;
2. drop `users can read their own step up events` and
   `users can create their own step up events`;
3. replace `assert_fresh_corporate_step_up` as `security definer` with an explicit
   `search_path`, require company ownership, signed `aal2`, and an MFA AMR timestamp
   from the last 15 minutes and not the future;
4. preserve execute revocations for `public`, `anon`, and `authenticated`, because
   only the wrapping security-definer RPCs call it;
5. replace the `launch_signoffs` key check constraint with the existing keys plus
   `founder_production_go_live` without inserting or approving that signoff.

### Step 6: Prove schema and local behavior are green

Run:

```bash
npm run test:trusted-aal2-schema
npm run test:supabase
npm run test:corporate-documents
npm run test:supabase:local
```

Expected: static/unit tests PASS. Local Supabase tests PASS when Docker is
available; if Docker is unavailable, record the exact environment limitation and
do not treat it as database evidence.

### Step 7: Commit the database boundary

```bash
git add package.json tests/trusted_aal2_schema.test.mjs tests/supabase_workspace.test.mjs tests/fixtures/corporate_documents/database_rehearsal.sql supabase/migrations/*_trusted_aal2_boundary.sql
git commit -m "fix: remove customer-forgeable step-up state"
```

---

## Task 3: Require global operator signoffs and final founder confirmation

**Files:**

- Modify: `tests/launch_signoff.test.mjs`
- Modify: `tests/filing_release_gate.test.mjs`
- Modify: `app/lib/launch-signoff.ts`
- Modify: `app/lib/filing-release-gate.ts`
- Inspect/update if required: `app/(operator)/operator/launch-readiness/page.tsx`

### Step 1: Write failing release-gate tests

Extend launch-signoff tests to require and label
`founder_production_go_live`. Extend filing-release tests so an otherwise ready
obligation remains disabled when any common signoff is absent:

```ts
const commonProductionSignoffKeys = [
  "launch_legal_name_public_copy",
  "legal_policy_pack",
  "security_restore",
  "billing_refund",
  "support_rollback",
  "founder_production_go_live",
];
```

Also prove a stale `security_restore` signoff blocks each filing gate and that
fresh AAL2 is necessary but cannot substitute for operator signoffs or adapter
capability.

### Step 2: Prove the tests are red

Run:

```bash
npm run test:launch-signoff
npm run test:filing-release-gate
```

Expected: FAIL because the founder key and common filing signoffs are not enforced.

### Step 3: Implement the global release gate

In `app/lib/launch-signoff.ts`:

- add `founder_production_go_live` and label it “Final founder production go-live”;
- export a reusable approved/fresh signoff evaluator or gate result so release code
  does not duplicate validation;
- keep `security_restore` freshness at 30 days by default.

In `app/lib/filing-release-gate.ts`:

- require fresh AAL2 through the reduced `StepUpContext`;
- require every common signoff plus the obligation-specific authority signoff;
- expose stable reasons such as
  `founder_production_go_live_signoff_missing` and
  `security_restore_signoff_stale`;
- keep adapter `productionImplemented` and `productionEnabled` checks independent.

Do not create the founder signoff or change any environment flag.

### Step 4: Prove the focused tests are green

Run:

```bash
npm run test:launch-signoff
npm run test:filing-release-gate
npm run typecheck
```

Expected: PASS.

### Step 5: Commit the release gates

```bash
git add tests/launch_signoff.test.mjs tests/filing_release_gate.test.mjs app/lib/launch-signoff.ts app/lib/filing-release-gate.ts app/(operator)/operator/launch-readiness/page.tsx
git commit -m "feat: require final production release signoffs"
```

---

## Task 4: Make public and legal copy truthful for invite-only beta

**Files:**

- Modify: `tests/launch_copy.test.mjs`
- Modify: `app/lib/launch-copy.ts`
- Modify: `app/lib/copy.ts`
- Modify if CTA rendering requires it: `app/page.tsx`

### Step 1: Write failing public-copy tests

Update `tests/launch_copy.test.mjs` to inspect `ownerCopy.home` and the public route
source. Require:

- the exact posture “Invitasjonsbasert gratis beta”;
- a clear statement that production submission and live payment are unavailable;
- `ELMER WELFIS` and organisation number `930 835 978` on legal pages;
- support address `post@talli.no`;
- the existing non-affiliation statement.

Reject public copy containing claims equivalent to:

- “uten regnskapsfører”;
- “menneskelig kontroll” or professional quality assurance;
- “du betaler først ved innsending”;
- claims that the filing “leveres” or has been sent live;
- legal placeholders such as `[Talli AS`, `XXX XXX XXX`, or `[Oslo tingrett]`.

### Step 2: Prove the tests are red

Run:

```bash
npm run test:launch-copy
npm run test:legal-policy
```

Expected: launch-copy FAIL on current homepage and placeholders.

### Step 3: Rewrite only the claims needed for a truthful beta

In `app/lib/copy.ts`:

- describe Talli as an invite-only free beta for supported holding-company cases;
- change the signup CTA to express beta interest while retaining invited-user
  login;
- describe technical checks, exact preview, user review, and unsupported-case
  blockers without implying accountant/human review;
- state that production submission and live payment are not open;
- identify `ELMER WELFIS, org.nr. 930 835 978` as beta operator/controller;
- use `post@talli.no` consistently for beta support/privacy contact;
- replace the venue placeholder with neutral Norwegian-law wording referring to
  ordinary courts and applicable mandatory venue rules;
- preserve conservative in-app simulated-filing copy.

In `app/lib/launch-copy.ts`, extend the prohibited-pattern validator to cover the
new overclaims. In `app/page.tsx`, change wiring only if required to render the
approved beta CTA/posture.

### Step 4: Prove public-copy tests are green

Run:

```bash
npm run test:launch-copy
npm run test:legal-policy
npm run typecheck
```

Expected: PASS.

### Step 5: Commit the beta posture

```bash
git add tests/launch_copy.test.mjs app/lib/launch-copy.ts app/lib/copy.ts app/page.tsx
git commit -m "fix: publish truthful invite-only beta copy"
```

---

## Task 5: Reconcile customer-readiness evidence and operational docs

**Files:**

- Modify: `docs/launch/customer-ready-decision-map.md`
- Modify: `docs/launch/talli-clearance-evidence-register.md`
- Modify: `docs/launch/release-evidence-checklist.md`
- Modify if referenced: `docs/launch/production-rollout-runbook.md`

### Step 1: Add a failing documentation assertion

Extend the most relevant existing static launch test (prefer
`tests/launch_signoff.test.mjs`) to assert that the evidence register names
`founder_production_go_live` and explicitly records it as not approved. Assert that
the customer-ready map links the implementation design and this plan.

### Step 2: Prove it is red

Run:

```bash
npm run test:launch-signoff
```

Expected: FAIL until the evidence documents are updated.

### Step 3: Update evidence without overstating completion

Document:

- the signed-AAL2 implementation and migration evidence;
- that hosted migration application, hosted real-MFA rehearsal, professional
  review/risk acceptance, five-company beta evidence, live Vipps charge/refund,
  and production authority adapters remain open;
- that `founder_production_go_live` is intentionally missing and requires a new
  explicit founder confirmation;
- that public beta copy is safe to deploy with live filing/payment flags off.

Do not mark external or hosted checks complete based only on local tests.

### Step 4: Prove docs/tests are green

Run:

```bash
npm run test:launch-signoff
git diff --check
```

Expected: PASS.

### Step 5: Commit evidence reconciliation

```bash
git add docs/launch/customer-ready-decision-map.md docs/launch/talli-clearance-evidence-register.md docs/launch/release-evidence-checklist.md docs/launch/production-rollout-runbook.md tests/launch_signoff.test.mjs
git commit -m "docs: record guarded beta release state"
```

---

## Task 6: Full verification and browser proof

**Files:**

- Create only if the repository convention requires it:
  `docs/launch/evidence/customer-ready-foundation-2026-07-15.md`

### Step 1: Run the complete automated verification

Use the known XSD/Python runtime from the baseline rehearsal:

```bash
TALLI_PYTHON_BIN=/Users/kristianelmer/Documents/Work/Talli/.venv/bin/python \
TALLI_SKATTE_XSD_DIR=/tmp/talli-skattemeldingen-v1.62.47/src/resources/xsd \
npm run test:launch-rehearsal
npm run typecheck
npm run build
npm audit --omit=dev
git diff --check
```

Expected: every command exits 0. Existing Node module-type warnings may be noted;
new warnings or failures must be resolved.

### Step 2: Run local Supabase verification

```bash
npm run test:supabase:local
```

Expected: PASS when Docker is available. Record a limitation if Docker is absent;
never substitute a static test for hosted/local RLS proof.

### Step 3: Inspect the public beta page in a real browser

Start the production build locally and use Playwright/browser tooling to verify:

- desktop and mobile homepage visibly say invite-only free beta;
- CTA and login destinations work;
- no human-review, direct-live-filing, or live-payment claim is visible;
- legal pages visibly show ELMER WELFIS, organisation number, and `post@talli.no`;
- browser console has no application errors.

Store screenshots only if the repository evidence convention already uses local
visual artifacts; otherwise report the tested URLs and result in the evidence note.

### Step 4: Review the full branch diff

Run:

```bash
git diff --stat a20447b..HEAD
git diff --check a20447b..HEAD
git status --short
```

Review for leaked secrets, accidental live flags, SQL privilege regressions, stale
copy, and changes outside the approved scope.

### Step 5: Commit verification evidence if a note was created

```bash
git add docs/launch/evidence/customer-ready-foundation-2026-07-15.md
git commit -m "docs: record customer-ready foundation verification"
```

Skip this commit only when no evidence file was created.

---

## Task 7: Finish, merge, and push with all live capabilities disabled

### Step 1: Use the finishing workflow

Read and follow `finishing-a-development-branch`. Because the founder has already
authorized merge/push to `main`, select the local merge path after verification.

### Step 2: Merge without enabling production

From `/Users/kristianelmer/Documents/Work/Talli`:

```bash
git status --short --branch
git fetch origin
git merge --ff-only codex/customer-ready-foundation
git push origin main
```

If `main` has advanced, stop the fast-forward merge, inspect the new commits, and
rebase/resolve only with the merge-conflict workflow. Never force-push.

### Step 3: Verify remote state and release lock

```bash
git rev-parse HEAD
git rev-parse origin/main
git grep -n "founder_production_go_live" -- docs app supabase tests
```

Expected: local `main` equals `origin/main`; the founder signoff is supported but
not approved; production adapter and payment flags remain disabled.

### Step 4: Report outcome and remaining external gates

Report the merged commit, verification commands, any environment-limited database
check, and the exact remaining external evidence. Do not ask for or infer the final
production confirmation in the same handoff; it remains a separate future decision
after hosted migration, real MFA, authority, professional, beta, and payment
evidence exists.
