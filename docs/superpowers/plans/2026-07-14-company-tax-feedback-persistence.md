# Company Tax TT02 Feedback Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist completed company-tax TT02 evidence as an idempotent, company/year-bound filing state with structured pending feedback, receipt/archive metadata, and owner-visible archive output while production remains disabled.

**Architecture:** Extend the strict evidence mapper with a pure persistence projection, then pass that projection to one step-up-protected PostgreSQL RPC that atomically upserts the authority test run and its linked `filing_submissions` record. The filing record uses an explicit `test_authority` mode, stores only sanitized hashes/references, and stops at `feedback_ready` because the receipt does not contain a machine-verified accepted/rejected outcome. Owner UI and archive export read the same persisted record; no production flag, permission, launch signoff, raw XML, token, or key is written.

**Tech Stack:** Next.js 16.2.9, TypeScript, Node test runner, Supabase/PostgreSQL 17, Altinn TT02 evidence schema v2

## Global Constraints

- Preserve `docs/remarks/holdingswift_produktkrav.md` unchanged.
- Work in `/Users/kristianelmer/Documents/Work/Talli/.worktrees/company-tax-feedback-persistence` on `codex/company-tax-feedback-persistence`.
- Treat `docs/superpowers/specs/2026-07-14-company-tax-return-tt02-submission-design.md` as the approved contract.
- Do not implement the separate attachment-boundary design until its explicit approval gate is satisfied.
- Keep `productionCompanyTaxReturnAdapterEnabled()` false and keep the production client constructor fail-closed.
- Import only evidence with `environment:"test"`, `productionEnabled:false`, exact company/year/scope/resource, complete schema validation, `validertOK`, human-confirmation handoff, one official feedback data element, and matching archive references.
- Do not infer accepted/rejected from receipt presence. Persist `status:"feedback_ready"` and warning code `COMPANY_TAX_AUTHORITY_OUTCOME_PENDING`.
- Never persist raw source/current/submission/receipt XML, access tokens, private keys, current-document references, internal party numbers, or personal identifiers.
- Use TDD: write the focused failing assertion, observe the expected failure, implement the smallest behavior, and rerun focused plus regression tests.
- Run `git diff --check` and `git diff --exit-code -- docs/remarks/holdingswift_produktkrav.md` before every commit.

---

### Task 1: Pure company-tax filing persistence projection

**Files:**

- Create: `app/lib/company-tax-return-submission.ts`
- Modify: `app/lib/authority-test-evidence.ts`
- Modify: `app/lib/supabase/server.ts`
- Create: `tests/company_tax_return_submission.test.mjs`
- Modify: `tests/authority_test_evidence.test.mjs`
- Modify: `package.json`

**Interfaces:**

- Consumes: the same already-validated TT02 evidence object used by `buildCompanyTaxReturnAuthorityTestRunFromEvidence`.
- Produces: one deterministic `CompanyTaxReturnEvidencePersistence` projection containing the authority test run and a sanitized `filing_submissions` payload.

- [ ] **Step 1: Add failing projection tests**

  Assert that a valid evidence fixture produces:

  ```javascript
  assert.equal(projected.submission.mode, "test_authority");
  assert.equal(projected.submission.adapter_mode, "test_authority");
  assert.equal(projected.submission.status, "feedback_ready");
  assert.equal(projected.submission.receipt_id, evidence.receipt.dataId);
  assert.deepEqual(projected.submission.feedback_document_ids, [evidence.receipt.dataId]);
  assert.deepEqual(projected.submission.feedback_items, [{
    severity: "warning",
    code: "COMPANY_TAX_AUTHORITY_OUTCOME_PENDING",
    message: "Offisiell tilbakemelding er mottatt, men myndighetsutfallet venter på klassifisering.",
    documentId: evidence.receipt.dataId,
  }]);
  assert.equal(projected.submission.submitted_payload, null);
  assert.match(projected.submission.payload_hash, /^[0-9a-f]{64}$/u);
  assert.match(projected.submission.idempotency_key, /^company-tax:company-1:2025:/u);
  ```

  Assert retrying with the same company/year/evidence produces the same payload hash and idempotency key. Recursively inspect the projection JSON and assert it contains none of the raw XML, current document reference, party number, token, key, or personal identifier sentinel values.

- [ ] **Step 2: Run the focused test red**

  Run: `node --experimental-strip-types --test tests/company_tax_return_submission.test.mjs`

  Expected: failure because `company-tax-return-submission.ts` and its projection export do not exist.

- [ ] **Step 3: Implement the minimal pure projection**

  Add these exact public shapes:

  ```typescript
  export type CompanyTaxReturnEvidencePersistence = {
    authorityRun: AuthorityTestRun;
    submission: {
      company_id: string;
      income_year: number;
      filing: "skattemelding for AS";
      mode: "test_authority";
      adapter_mode: "test_authority";
      payload_hash: string;
      idempotency_key: string;
      status: "feedback_ready";
      calls: FilingSubmissionCall[];
      receipt_id: string;
      feedback_document_ids: string[];
      feedback_items: FilingSubmissionFeedbackItem[];
      receipt_metadata: CompanyTaxReturnReceiptMetadata;
      submitted_payload_ref: CompanyTaxReturnPayloadReference;
      submitted_payload: null;
      failure_code: null;
      failure_message: null;
      created_by: string;
      submitted_by: null;
      updated_at: string;
    };
  };

  export function buildCompanyTaxReturnEvidencePersistence(
    input: CompanyTaxReturnAuthorityTestRunImportInput,
  ): CompanyTaxReturnEvidencePersistence;
  ```

  Refactor strict evidence parsing into one internal validated snapshot used by both the existing authority-run mapper and the new projection, so company/year/scope/resource/receipt/archive checks cannot diverge. Build the operation journal only from timestamps and hashes explicitly present in the evidence. Store references and SHA-256 values, not reconstructed raw documents. Generalize `FilingSubmissionRow` JSON field types enough to represent RF-1086 and company-tax records without weakening their runtime validation.

- [ ] **Step 4: Run focused and evidence regressions green**

  Add `test:company-tax-return-submission` to `package.json`.

  Run: `npm run test:company-tax-return-submission`

  Run: `npm run test:authority-evidence`

  Run: `npm run typecheck`

  Expected: all commands exit 0.

- [ ] **Step 5: Commit**

  Run:

  ```bash
  git add app/lib/company-tax-return-submission.ts app/lib/authority-test-evidence.ts app/lib/supabase/server.ts tests/company_tax_return_submission.test.mjs tests/authority_test_evidence.test.mjs package.json docs/superpowers/plans/2026-07-14-company-tax-feedback-persistence.md
  git diff --cached --check
  git diff --exit-code -- docs/remarks/holdingswift_produktkrav.md
  git commit -m "feat: project company tax TT02 filing feedback"
  ```

---

### Task 2: Atomic, owner-step-up-protected evidence import

**Files:**

- Create: `supabase/migrations/0005_company_tax_feedback_persistence.sql`
- Modify: `app/actions.ts`
- Modify: `tests/company_tax_return_authority_evidence_import.test.mjs`
- Modify: `tests/supabase_workspace.test.mjs`
- Modify: `tests/backup_restore.test.mjs`

**Interfaces:**

- Consumes: `buildCompanyTaxReturnEvidencePersistence(...)` and an authenticated owner with a fresh step-up event.
- Produces: one atomic, retry-safe authority-test-run/filing-submission pair linked by `authority_test_run_id`.

- [ ] **Step 1: Add failing migration and action tests**

  Assert the migration:

  - adds nullable `authority_test_run_id` with a foreign key and unique index to `filing_submissions`;
  - permits `mode IN ('simulation', 'test_authority')` and `adapter_mode IN ('simulation', 'test_authority', 'production')` while retaining the owner RLS policy's direct-write requirement `mode = 'simulation'`;
  - permits `preview_id IS NULL` only when `mode = 'test_authority'` and requires a preview for simulation;
  - creates `public.import_company_tax_tt02_evidence(jsonb)` as `security definer` with `search_path = public, pg_temp`;
  - checks `auth.uid()`, accepted owner membership, a step-up event from the last 15 minutes, company/year identity, obligation `skattemelding`, test environment, pending authority status, test-authority mode, feedback-ready status, matching hashes/references, and null raw payload;
  - grants execute only to `authenticated` after revoking public/anon access.

  Assert `recordCompanyTaxReturnTt02Evidence` calls the pure projection and exactly one RPC instead of a direct `authority_test_runs` insert.

- [ ] **Step 2: Run focused tests red**

  Run: `node --test tests/company_tax_return_authority_evidence_import.test.mjs tests/backup_restore.test.mjs`

  Expected: failure because migration 0005 and the RPC action path do not exist.

- [ ] **Step 3: Implement migration 0005 and the atomic RPC**

  The function accepts this exact top-level JSON object:

  ```json
  {
    "authorityRun": {
      "company_id": "<uuid>",
      "obligation": "skattemelding",
      "environment": "test",
      "status": "pending",
      "test_reference": "tt02:<party>/<instance-uuid>"
    },
    "submission": {
      "company_id": "<same uuid>",
      "income_year": 2025,
      "filing": "skattemelding for AS",
      "mode": "test_authority",
      "adapter_mode": "test_authority",
      "status": "feedback_ready",
      "submitted_payload": null
    }
  }
  ```

  Add a unique index on `(company_id, obligation, environment, test_reference)` for authority runs. Inside one function transaction, reuse or insert the exact authority run, then reuse or insert the filing submission by `authority_test_run_id`. On retry, compare payload hash, idempotency key, receipt ID, feedback IDs/items, receipt metadata, payload reference, and calls; raise `company_tax_evidence_conflict` on any mismatch rather than overwriting history. Return the two row IDs and `created:boolean`. Insert the audit event in the same function only on first creation.

  Keep raw table inserts blocked by RLS for `test_authority`; the RPC is the sole write path for this mode.

- [ ] **Step 4: Switch the server action to the RPC**

  Replace the direct insert with:

  ```typescript
  const persistence = buildCompanyTaxReturnEvidencePersistence({
    companyId,
    expectedCompanyOrgNumber: company.org_number,
    expectedIncomeYear: Number(formString(formData, "incomeYear")),
    evidence,
    evidenceUrl: formString(formData, "evidenceUrl"),
    recordedBy: user.id,
  });
  const { error } = await supabase.rpc("import_company_tax_tt02_evidence", {
    p_payload: persistence,
  });
  ```

  Do not separately mutate `authority_permissions`, `launch_signoffs`, adapter configuration, or audit events.

- [ ] **Step 5: Add deployed-database behavior coverage**

  Extend the Supabase workspace test to apply migration 0005 and prove:

  - an owner without fresh step-up is rejected;
  - a stepped-up owner creates exactly one linked authority run and submission;
  - retry returns the same IDs and does not add an audit row;
  - a conflicting payload/receipt is rejected;
  - reviewer/outsider cannot call the RPC;
  - company members can read the persisted record through normal RLS;
  - `authority_permissions.production_enabled` and launch signoffs remain unchanged.

- [ ] **Step 6: Run focused and database tests green**

  Run: `node --test tests/company_tax_return_authority_evidence_import.test.mjs tests/backup_restore.test.mjs`

  Run: `npm run test:supabase`

  Run: `npm run typecheck`

  Expected: all commands exit 0; database test may skip only under its existing documented no-local-Postgres condition.

- [ ] **Step 7: Commit**

  Run:

  ```bash
  git add supabase/migrations/0005_company_tax_feedback_persistence.sql app/actions.ts tests/company_tax_return_authority_evidence_import.test.mjs tests/supabase_workspace.test.mjs tests/backup_restore.test.mjs docs/superpowers/plans/2026-07-14-company-tax-feedback-persistence.md
  git diff --cached --check
  git diff --exit-code -- docs/remarks/holdingswift_produktkrav.md
  git commit -m "feat: persist company tax TT02 feedback atomically"
  ```

---

### Task 3: Owner-visible feedback, archive output, and release evidence

**Files:**

- Modify: `app/(owner)/filing/[obligation]/page.tsx`
- Modify: `app/lib/archive.ts`
- Create: `tests/owner_filing_flow.test.mjs`
- Modify: `tests/company_tax_return_payload.test.mjs`
- Modify: `docs/filing/company-tax-return-authority-map.md`
- Modify: `docs/filing/production-submission-state.md`
- Modify: `docs/filing/authority-onboarding-runbook.md`
- Modify: `docs/prd/holdingswift-product-requirements-implementation-plan.md`
- Modify: `docs/superpowers/plans/2026-07-14-company-tax-feedback-persistence.md`

**Interfaces:**

- Consumes: `FilingSubmissionRow` with `filing:"skattemelding for AS"`, `mode:"test_authority"`, and `status:"feedback_ready"`.
- Produces: truthful owner feedback and a year archive entry without presenting test evidence as production acceptance.

- [ ] **Step 1: Add failing owner-flow and archive tests**

  For the company-tax route, assert a persisted test-authority record renders:

  - label `TT02-tilbakemelding mottatt`;
  - warning text `Myndighetsutfallet venter på klassifisering`;
  - receipt data ID and archive reference;
  - an explicit `Test – ikke produksjonsinnsending` badge;
  - no success/accepted copy and no production submit control.

  Assert the archive exposes a `companyTaxSubmissions` array with mode, status, payload hash, idempotency key, receipt ID, feedback items, receipt metadata, submitted-payload reference, and sanitized call journal. Assert `submittedPayload` remains null and `simulatedReceipts` continues to contain simulation records only.

- [ ] **Step 2: Run focused tests red**

  Run: `node --test tests/owner_filing_flow.test.mjs tests/company_tax_return_payload.test.mjs`

  Expected: failure because the non-RF-1086 route still renders only the generic preparing placeholder and the archive lacks `companyTaxSubmissions`.

- [ ] **Step 3: Render the persisted pending outcome truthfully**

  In the non-RF-1086 branch, select the current-year filing submission by `obligationFilingString(obligation)`. For `skattemelding`, render a feedback section only when the record is `mode === "test_authority"` and `status === "feedback_ready"`; otherwise keep the current preparing placeholder. Use warning styling and never derive acceptance from receipt presence.

- [ ] **Step 4: Extend the archive**

  Add `companyTaxSubmissions` alongside `rf1086Submissions`. Map only stored sanitized fields. Keep the existing `simulatedReceipts` filter exactly simulation-only so test-authority evidence cannot be mislabeled as a simulated or production receipt.

- [ ] **Step 5: Update release documentation**

  Record that local/deployed-capable persistence, idempotency, RLS, structured pending feedback, and archive visibility are implemented. Leave these gates explicitly open:

  - actual import execution against the deployed Supabase project;
  - explicit classification of the receipt outcome;
  - attachment-boundary approval/implementation;
  - production credentials, security/restore review, and dated named approval;
  - production adapter implementation and enablement.

- [ ] **Step 6: Run full verification green**

  Run:

  ```bash
  npm run test:company-tax-return-submission
  npm run test:authority-evidence
  npm run test:supabase
  TALLI_PYTHON_BIN=/Users/kristianelmer/Documents/Work/Talli/.venv/bin/python TALLI_SKATTE_XSD_DIR=/tmp/talli-skattemeldingen-v1.62.47/src/resources/xsd npm run test:launch-rehearsal
  npm run build
  npm audit --omit=dev
  git diff --check
  git diff --exit-code -- docs/remarks/holdingswift_produktkrav.md
  ```

  Expected: all commands exit 0, with zero known production dependency vulnerabilities.

- [ ] **Step 7: Commit**

  Run:

  ```bash
  git add 'app/(owner)/filing/[obligation]/page.tsx' app/lib/archive.ts tests/owner_filing_flow.test.mjs tests/company_tax_return_payload.test.mjs docs/filing/company-tax-return-authority-map.md docs/filing/production-submission-state.md docs/filing/authority-onboarding-runbook.md docs/prd/holdingswift-product-requirements-implementation-plan.md docs/superpowers/plans/2026-07-14-company-tax-feedback-persistence.md
  git diff --cached --check
  git diff --exit-code -- docs/remarks/holdingswift_produktkrav.md
  git commit -m "feat: expose company tax TT02 feedback state"
  ```

---

## Final review

- [ ] Run a fresh whole-branch specification review against the approved TT02 design and this plan.
- [ ] Run a fresh whole-branch code-quality review.
- [ ] Resolve every Critical or Important finding and rerun the affected verification.
- [ ] Confirm production capability remains disabled in tests and source.
- [ ] Confirm the product-requirements source file is byte-for-byte unchanged.
