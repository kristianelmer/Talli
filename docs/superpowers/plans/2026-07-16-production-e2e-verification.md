# Production E2E Verification Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan.

**Goal:** Produce fresh, independently reviewed evidence that the merged RF-1086 self-service release is as production-ready as can be proven without mutating production data or making a real statutory filing.

**Architecture:** Test the exact `origin/main` release commit in an isolated worktree. Exercise the repository release gate, local database and browser flows, production build, and a read-only Computer Use smoke test of `https://talli.no`. Record a graded conclusion that separates verified behavior from live-authority and customer-specific prerequisites.

**Tech Stack:** Next.js 15, TypeScript, Node test runner, Playwright, local Supabase CLI/PostgreSQL, Python runtime, GitHub Actions, Vercel, Computer Use.

---

## Global Constraints

- Target `origin/main` merge commit `2ac6ca69b10e00411fbb7bdd3578bf9be0e64297`; record any unexpected drift and stop rather than silently changing the target.
- Do not submit a filing, invoke a live authority mutation, change production environment variables, change entitlements, alter customer/company data, upload production data, make a payment, or incur a charge.
- Keep `TALLI_AUTHORITY_OPS_ENABLED` and `TALLI_RF1086_PRODUCTION_ENABLED` off in the parent environment. Authority behavior may be exercised only through tests' local mocks or fail-closed checks.
- The Computer Use slice is public/read-only. Do not log in unless the user separately authorizes it at action time; do not rely on an existing authenticated session to make changes.
- Treat production readiness as graded evidence, not a guarantee. A green run does not replace named-customer eligibility, delegation/credential checks, monitored first filing, or comparison against another provider's accepted output.
- If any command fails, preserve its evidence and use systematic debugging before changing code or tests.
- Record commands, UTC timestamps, exit codes, test counts when reported, target SHA, and unresolved limitations in `docs/launch/evidence/production-e2e-verification-2026-07-16.md`.

### Task 1: Freeze release target and audit the verification contract

**Files:**
- Create: `docs/launch/evidence/production-e2e-verification-2026-07-16.md`
- Inspect: `package.json`
- Inspect: `.github/workflows/release-gate.yml`
- Inspect: `docs/launch/production-launch-rehearsal.md`
- Inspect: `docs/filing/rf1086-live-release-gate.md`
- Inspect: `docs/filing/rf1086-production-pilot-runbook.md`

- [ ] **Step 1: Prove target and workspace isolation**

Run: `TARGET=2ac6ca69b10e00411fbb7bdd3578bf9be0e64297; test "$(git merge-base HEAD origin/main)" = "$TARGET" && git merge-base --is-ancestor "$TARGET" HEAD && git diff --quiet "$TARGET"..HEAD -- . ':(exclude)docs/superpowers/plans/2026-07-16-production-e2e-verification.md' && git status --short --branch`

Expected: the branch's merge base with `origin/main` is the immutable target release, the target is an ancestor of the documentation branch, no release code differs from the target, and status contains no unexpected changes before evidence is added. `HEAD` may be ahead of the target because it contains this verification plan and subsequent evidence commits.

- [ ] **Step 2: Inventory the official release checks and fail-closed production switches**

Run: `node -e "const p=require('./package.json'); for (const n of ['test:launch-rehearsal','test:supabase:local','test:supabase-advisors','test:browser-system-user','typecheck','build']) console.log(n, Boolean(p.scripts[n]))"`

Run: `node --test tests/ci_release_gate.test.mjs tests/filing_release_gate.test.mjs tests/rf1086_production_runbook.test.mjs`

Expected: every required script exists and all contract tests pass.

- [ ] **Step 3: Record provenance and explicit test boundary**

Create the evidence document with target SHA, branch/worktree, command results, safety boundary, and a pending checklist for Tasks 2–6.

- [ ] **Step 4: Commit the audit evidence**

Run: `git add docs/launch/evidence/production-e2e-verification-2026-07-16.md && git commit -m "docs: start production e2e verification evidence"`

### Task 2: Run the full repository release rehearsal and build

**Files:**
- Modify: `docs/launch/evidence/production-e2e-verification-2026-07-16.md`
- Verify: `package.json`
- Verify: `.github/workflows/release-gate.yml`

- [ ] **Step 1: Resolve pinned local runtimes without production credentials**

Verify the existing project Python virtualenv and pinned Skatteetaten XSD directory. Use `TALLI_PYTHON_BIN=/Users/kristianelmer/Documents/Work/Talli/.venv/bin/python` and the existing v1.62.47 XSD path when present. Do not fetch paid resources or expose secrets.

- [ ] **Step 2: Run the complete launch rehearsal**

Run: `env -u TALLI_AUTHORITY_OPS_ENABLED -u TALLI_RF1086_PRODUCTION_ENABLED TALLI_PYTHON_BIN=/Users/kristianelmer/Documents/Work/Talli/.venv/bin/python TALLI_SKATTE_XSD_DIR=/tmp/talli-skattemeldingen-v1.62.47/src/resources/xsd npm run test:launch-rehearsal`

Expected: every chained suite exits 0; no live authority endpoint is invoked.

- [ ] **Step 3: Run compiler and production build gates**

Run: `npm run typecheck`

Run: `env -u TALLI_AUTHORITY_OPS_ENABLED -u TALLI_RF1086_PRODUCTION_ENABLED npm run build`

Expected: both commands exit 0.

- [ ] **Step 4: Record and commit exact outcomes**

Append commands, timestamps, exit codes, test totals where available, warnings, and limitations to the evidence document.

Run: `git add docs/launch/evidence/production-e2e-verification-2026-07-16.md && git commit -m "docs: record release rehearsal and build evidence"`

### Task 3: Exercise local Supabase migrations, grants, RLS, and advisors

**Files:**
- Modify: `docs/launch/evidence/production-e2e-verification-2026-07-16.md`
- Verify: `scripts/test-supabase-local.sh`
- Verify: `scripts/assert-supabase-advisors.mjs`

- [ ] **Step 1: Verify local-only database prerequisites**

Run: `supabase --version && docker info --format '{{.ServerVersion}}'`

Expected: local tooling is available without connecting to a hosted customer project.

- [ ] **Step 2: Run the isolated migration and authenticated database suite**

Run: `npm run test:supabase:local`

Expected: migrations, grants, role-abuse/RLS checks, database runtimes, advisors, and the owner browser loop pass; teardown leaves no conflicting local service.

- [ ] **Step 3: Re-run explicit static grant and advisor gates**

Run: `npm run test:supabase-grants && npm run test:supabase-advisors`

Expected: zero blocking findings; record performance warnings separately rather than hiding them.

- [ ] **Step 4: Record and commit exact outcomes**

Run: `git add docs/launch/evidence/production-e2e-verification-2026-07-16.md && git commit -m "docs: record local database verification evidence"`

### Task 4: Run the mocked RF-1086 browser flow end to end

**Files:**
- Modify: `docs/launch/evidence/production-e2e-verification-2026-07-16.md`
- Verify: `tests/browser_system_user_flow.mjs`
- Verify: `tests/browser_system_user_flow_contract.test.mjs`

- [ ] **Step 1: Prove the parent process is fail-closed**

Run: `test "${TALLI_AUTHORITY_OPS_ENABLED-}" != true && test "${TALLI_RF1086_PRODUCTION_ENABLED-}" != true`

Expected: exit 0.

- [ ] **Step 2: Execute the local-mock browser journey**

Run: `env -u TALLI_AUTHORITY_OPS_ENABLED -u TALLI_RF1086_PRODUCTION_ENABLED npm run test:browser-system-user`

Expected: contract and flow tests pass at 320x900 and 1440x900, keyboard order is verified, browser console has no warnings/errors, cross-company access is denied, the receipt/archive path works, and filing egress is local-mock-only.

- [ ] **Step 3: Check for leaked processes and unexpected tracked changes**

Run: `git status --short && (lsof -nP -iTCP:3100 -sTCP:LISTEN || true) && (lsof -nP -iTCP:54321 -sTCP:LISTEN || true)`

Expected: only the evidence document is modified and no test-owned listener remains.

- [ ] **Step 4: Record and commit exact outcomes**

Run: `git add docs/launch/evidence/production-e2e-verification-2026-07-16.md && git commit -m "docs: record rf1086 browser e2e evidence"`

### Task 5: Smoke-test the deployed public surface with Computer Use

**Files:**
- Modify: `docs/launch/evidence/production-e2e-verification-2026-07-16.md`

- [ ] **Step 1: Open `https://talli.no` in Chrome using Computer Use**

Use the Computer Use skill and obtain a fresh accessibility tree and screenshot. Do not bypass browser security warnings.

- [ ] **Step 2: Perform read-only navigation checks**

Verify the landing page renders, primary public navigation works, the login route can be reached without submitting credentials, and no obvious error page or broken loading state appears. Re-read app state after every UI action; do not click mutation, checkout, upload, filing, or account-creation actions.

- [ ] **Step 3: Record observations and evidence boundaries**

Append the visited routes, visible state, timestamp, and any UI limitation. Do not include sensitive browser/session data or screenshots containing it.

- [ ] **Step 4: Commit the deployed-surface evidence**

Run: `git add docs/launch/evidence/production-e2e-verification-2026-07-16.md && git commit -m "docs: record deployed surface smoke evidence"`

### Task 6: Reconcile evidence and issue the production-readiness verdict

**Files:**
- Modify: `docs/launch/evidence/production-e2e-verification-2026-07-16.md`

- [ ] **Step 1: Re-run the decisive gates on the final evidence commit**

Run: `node --test tests/ci_release_gate.test.mjs tests/filing_release_gate.test.mjs tests/rf1086_production_runbook.test.mjs && npm run typecheck && env -u TALLI_AUTHORITY_OPS_ENABLED -u TALLI_RF1086_PRODUCTION_ENABLED npm run build`

Expected: all commands exit 0.

- [ ] **Step 2: Reconcile local evidence with deployed commit evidence**

Confirm the GitHub post-merge Customer-ready release gate is green for the target release and the Vercel production deployment for that release is Ready. Use read-only inspection only.

- [ ] **Step 3: Grade the outcome**

State one of: `GO for a hand-held eligible-company beta`, `CONDITIONAL GO`, or `NO-GO`. List every untested external dependency and the exact safe next step. A GO must still say that the first real filing needs named-company eligibility, production credentials/delegation, the controlled entitlement and approval flow, monitoring, comparison with an incumbent output, and explicit operator authorization.

- [ ] **Step 4: Commit final evidence and request whole-branch review**

Run: `git add docs/launch/evidence/production-e2e-verification-2026-07-16.md && git commit -m "docs: conclude production e2e verification"`

Dispatch a final read-only reviewer against the full plan and branch range. Resolve every Critical or Important finding, then repeat the decisive verification before presenting branch-integration options.
