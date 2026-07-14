# Company Tax Return TT02 Submission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare a supported company tax return in TT02 for owner confirmation, retrieve the official feedback receipt after personal submission, and persist sanitized evidence without enabling production.

**Architecture:** Extend the existing test-only Skatteetaten/Altinn client with conservative process and feedback parsing. A resumable CLI writes sanitized evidence atomically before and after the human-controlled submission boundary. A separate company-bound runtime importer records completed evidence as pending until explicit final acceptance and human production approval exist.

**Tech Stack:** Next.js 16.2.9, TypeScript, Node test runner, Skatteetaten 2025 XML/XSD v1.62.47, Altinn 3 TT02, Maskinporten system user, Supabase/PostgreSQL

## Global Constraints

- Preserve `docs/remarks/holdingswift_produktkrav.md` unchanged.
- Work on `codex/holdingswift-production-readiness`; do not rewrite prior commits.
- Keep every company-tax production adapter disabled.
- Permit network writes only when environment is exactly `test` and explicit test-write approval is exactly `true`.
- The system-user client may make only the first process transition into confirmation; it must never perform the owner's final submission transition.
- Resume/polling performs only GET requests.
- Never persist private keys, tokens, raw source/current/receipt XML, calculated documents, or personal identifiers.
- Use TDD: add a focused failing test, observe the expected failure, implement the smallest behavior, then run focused and regression tests green.
- Run `git diff --check` and confirm the approved product-requirements source is unchanged before every commit.

---

### Task 1: Conservative process handoff and feedback-receipt client

**Files:**

- Modify: `app/lib/company-tax-return-authority-client.ts`
- Modify: `tests/company_tax_return_authority_client.test.mjs`

**Interfaces:**

- Consumes: existing test-only Altinn token, instance ID validation, `authorityRequest`, and official `data`/`confirmation`/`feedback` process contract.
- Produces: `getInstance`, `advanceToConfirmation`, `getOwnerConfirmationUrl`, `getFeedbackReceipt`, and `waitForCompanyTaxReturnFeedback`.

- [x] **Step 1: Add failing process-transition tests**

  Add fixtures shaped like real Altinn instances and assert:

  ```javascript
  const prepared = await client.advanceToConfirmation({ instanceId });
  assert.equal(prepared.processTask, "confirmation");
  assert.equal(prepared.transitioned, true);
  assert.deepEqual(requests.map(({ method }) => method), ["GET", "PUT", "GET"]);

  const retry = await client.advanceToConfirmation({ instanceId });
  assert.equal(retry.transitioned, false);
  assert.deepEqual(requests.map(({ method }) => method), ["GET"]);
  ```

  Test that `feedback`, ended, missing, and unknown tasks block without a PUT. Test the exact TT02 owner URL:

  ```text
  https://skatt-test.sits.no/web/skattemelding-visning/altinn?appId=skd/formueinntekt-skattemelding-v2&instansId=<instance-id>
  ```

- [x] **Step 2: Run the client test red**

  Run: `node --experimental-strip-types --test tests/company_tax_return_authority_client.test.mjs`

  Expected: failure because the new methods/exports do not exist.

- [x] **Step 3: Implement the minimal process API**

  Add exact public signatures:

  ```typescript
  getInstance(options: { instanceId: string }): Promise<CompanyTaxReturnInstanceSummary>
  advanceToConfirmation(options: { instanceId: string }): Promise<{
    instanceId: string;
    processTask: "confirmation";
    transitioned: boolean;
  }>
  getOwnerConfirmationUrl(options: { instanceId: string }): string
  ```

  `getInstance` validates the returned ID, parses `process.currentTask.altinnTaskType`, `process.ended`, `status.isArchived`, `status.archived`, and bounded data-element metadata. `advanceToConfirmation` calls `GET`, then `PUT .../process/next` only from `data`, then verifies with a final `GET`; when already in `confirmation`, it returns without writing.

- [x] **Step 4: Add failing receipt retrieval and polling tests**

  Assert one clean `tilbakemelding` element with XML content is downloaded from `/instances/{id}/data/{dataId}`. Assert missing/pending is retryable, duplicate elements block, rejected scan blocks, non-XML content blocks, and `waitForCompanyTaxReturnFeedback` uses only GETs and stops on success or bounded timeout.

- [x] **Step 5: Run the new receipt tests red**

  Run: `node --experimental-strip-types --test tests/company_tax_return_authority_client.test.mjs`

  Expected: failure because feedback methods are absent.

- [x] **Step 6: Implement receipt retrieval and polling**

  Add exact signatures:

  ```typescript
  getFeedbackReceipt(options: { instanceId: string }): Promise<{
    instanceId: string;
    dataId: string;
    dataType: "tilbakemelding";
    contentType: "application/xml" | "text/xml";
    sizeBytes: number;
    reference: string;
    receiptXml: string;
    archived: boolean;
    archivedAt: string | null;
    archiveReference: string;
  }>

  waitForCompanyTaxReturnFeedback(
    client: CompanyTaxReturnAuthorityClient,
    input: { instanceId: string },
    dependencies?: { sleep?: (milliseconds: number) => Promise<void>; attempts?: number },
  ): Promise<CompanyTaxReturnFeedbackReceipt>
  ```

  Keep receipt XML in memory only. Sanitize all remote errors and validate UUIDs, content type, scan state, byte length, returned instance ID, and archive reference.

- [x] **Step 7: Run focused and authority regression tests green**

  Run: `npm run test:company-tax-return-authority`

  Run: `npm run test:authority-adapters`

  Run: `npm run typecheck`

  Expected: all commands exit 0.

- [x] **Step 8: Commit**

  Run:

  ```bash
  git add app/lib/company-tax-return-authority-client.ts tests/company_tax_return_authority_client.test.mjs
  git diff --cached --check
  git commit -m "feat: add company tax owner submission handoff"
  ```

---

### Task 2: Resumable test-only rehearsal and sanitized evidence

**Files:**

- Modify: `scripts/company-tax-return-authority-test.mjs`
- Create: `tests/company_tax_return_authority_script.test.mjs`
- Modify: `package.json`

**Interfaces:**

- Consumes: Task 1 client, existing 2025 payload/XML renderer, pinned XSD directory, Maskinporten token helper, and Altinn exchange helper.
- Produces: prepare/resume modes and schema-version-2 sanitized evidence.

- [ ] **Step 1: Add failing script safety and idempotency tests**

  Spawn the script with an empty environment and assert explicit write approval is required. Inspect the script source and assert it requires all three scopes, supports `prepare` and `resume`, calls `advanceToConfirmation` only in prepare, calls `waitForCompanyTaxReturnFeedback` only in resume, never invokes a final process transition, writes atomically, and compares company/year/payload hashes before reusing evidence.

- [ ] **Step 2: Run the script test red**

  Run: `node --test tests/company_tax_return_authority_script.test.mjs`

  Expected: failure because resumable phases are absent.

- [ ] **Step 3: Implement prepare mode**

  Require:

  ```text
  TALLI_COMPANY_TAX_APPROVED_TEST_WRITE=true
  TALLI_COMPANY_TAX_REHEARSAL_MODE=prepare
  TALLI_MASKINPORTEN_ENVIRONMENT=test
  TALLI_MASKINPORTEN_SCOPE="skatteetaten:formueinntekt/skattemelding altinn:instances.read altinn:instances.write"
  ```

  Fetch the current draft, render the reference-bound envelope, validate all three XSDs, mint/exchange tokens, create/upload the instance, wait for `Clean`, run async validation, require `validertOK`, and advance once to confirmation. Write evidence after every irreversible remote step so retries reuse the same instance.

- [ ] **Step 4: Implement read-only resume mode**

  Require compatible existing evidence with status `awaiting_person_confirmation`. Mint fresh tokens, call only `waitForCompanyTaxReturnFeedback`, hash the returned XML, then update evidence to `submitted_and_receipted`. Store stable metadata and hashes only:

  ```json
  {
    "status": "submitted_and_receipted",
    "productionEnabled": false,
    "receipt": {
      "dataType": "tilbakemelding",
      "contentSha256": "<64 lowercase hex>",
      "byteLength": 1,
      "reference": "<TT02 data URL>"
    }
  }
  ```

- [ ] **Step 5: Add scripts and run tests green**

  Add `test:company-tax-return-authority-script` to `package.json` and include it in `test:launch-rehearsal`.

  Run: `npm run test:company-tax-return-authority-script`

  Run: `npm run test:company-tax-return-authority`

  Run: `npm run typecheck`

  Expected: all commands exit 0.

- [ ] **Step 6: Commit**

  Run:

  ```bash
  git add scripts/company-tax-return-authority-test.mjs tests/company_tax_return_authority_script.test.mjs package.json
  git diff --cached --check
  git commit -m "feat: rehearse company tax TT02 submission"
  ```

---

### Task 3: Real TT02 preparation, owner handoff, receipt, and evidence docs

**Files:**

- Modify: `docs/filing/evidence/company-tax-tt02-2026-07-14.json`
- Modify: `docs/filing/evidence/company-tax-tt02-2026-07-14.md`
- Modify: `docs/filing/company-tax-return-authority-map.md`
- Modify: `docs/filing/company-tax-return-schema-evidence-register.md`
- Modify: `docs/filing/authority-onboarding-runbook.md`
- Modify: `docs/prd/holdingswift-product-requirements-implementation-plan.md`
- Modify: `docs/filing/production-submission-state.md`

**Interfaces:**

- Consumes: Task 2 CLI, synthetic company access, user-controlled high-assurance TestID, and official TT02 receipt.
- Produces: machine-checkable complete TT02 evidence with no secrets.

- [ ] **Step 1: Probe the current synthetic company read-only**

  Mint a test system-user token and call only `fetchCurrent` for the approved company/year. If the draft is absent, query only approved synthetic candidates and choose a company that satisfies the same supported holding-AS/no-attachment fixture boundary. Do not create an instance until a current document reference exists.

- [ ] **Step 2: Run prepare mode and verify owner handoff**

  Run the CLI with the pinned v1.62.47 XSD directory and synthetic case. Verify evidence says `awaiting_person_confirmation`, includes the exact instance ID/viewer URL, has `validertOK`, and contains no raw XML, token, key, or personal identifier.

- [ ] **Step 3: Complete the human boundary**

  Open the exact TT02 viewer URL. A person authenticated with TestID at high assurance reviews and performs the final confirmation/submission. No automation clicks the final submit control without a contemporaneous user confirmation.

- [ ] **Step 4: Run resume mode and verify receipt/archive**

  Run resume mode until `tilbakemelding` is available. Independently download it in memory, recompute SHA-256/byte length, and verify those values equal sanitized evidence. Confirm production remains disabled.

- [ ] **Step 5: Add/update evidence tests first, then docs**

  Extend `tests/company_tax_return_tt02_evidence.test.mjs` to require submitted/receipted test-only evidence, matching receipt/archive references, hashes, and no secrets. Run it red before updating evidence; then update the machine evidence and narrative/authority maps and run it green.

- [ ] **Step 6: Run verification and commit**

  Run:

  ```bash
  npm run test:authority-evidence
  npm run test:company-tax-return-authority
  npm run test:company-tax-return-authority-script
  git diff --check
  git diff --exit-code -- docs/remarks/holdingswift_produktkrav.md
  ```

  Commit:

  ```bash
  git add docs/filing tests/company_tax_return_tt02_evidence.test.mjs docs/prd/holdingswift-product-requirements-implementation-plan.md
  git commit -m "docs: record company tax TT02 submission evidence"
  ```

---

### Task 4: Fail-closed runtime import and final verification

**Files:**

- Modify: `app/lib/authority-test-evidence.ts`
- Modify: `app/actions.ts`
- Modify: `app/(owner)/workspace/page.tsx`
- Modify: `tests/authority_test_evidence.test.mjs`
- Create: `tests/company_tax_return_authority_evidence_import.test.mjs`
- Modify: `package.json`
- Modify: `docs/filing/company-tax-return-authority-map.md`
- Modify: `docs/filing/authority-onboarding-runbook.md`
- Modify: `docs/filing/production-submission-state.md`
- Modify: `docs/prd/holdingswift-product-requirements-implementation-plan.md`
- Modify: `docs/superpowers/plans/2026-07-14-company-tax-return-tt02-submission.md`

**Interfaces:**

- Consumes: Task 3 sanitized evidence.
- Produces: company-bound, owner-step-up-protected JSON import into `authority_test_runs`, always `pending` unless the receipt has an explicit accepted outcome that the mapper validates.

- [ ] **Step 1: Add failing mapper/action/UI tests**

  Test exact company/year/scope/app/data type, `validertOK`, confirmation handoff, official receipt hash/reference, archive reference, test-only environment, and `productionEnabled:false`. Assert the action writes only `authority_test_runs` plus audit metadata and never changes `authority_permissions`, launch signoffs, production flags, or adapter capability.

- [ ] **Step 2: Run tests red**

  Run: `npm run test:authority-evidence`

  Expected: failure because the company-tax mapper/import action is absent.

- [ ] **Step 3: Implement the minimal importer**

  Reuse the annual-evidence upload boundary: authenticated owner, sensitive-action step-up, 512 KiB JSON limit, company lookup, strict evidence validation, deterministic combined payload hash, `pending` status, one insert, and sanitized audit event.

- [ ] **Step 4: Run full verification green**

  Run:

  ```bash
  TALLI_SKATTE_XSD_DIR=/tmp/talli-skattemeldingen-v1.62.47/src/resources/xsd npm run test:launch-rehearsal
  npm run build
  npm audit --omit=dev
  git diff --check
  git diff --exit-code -- docs/remarks/holdingswift_produktkrav.md
  ```

  Expected: all commands exit 0; production remains disabled in adapter and release-gate tests.

- [ ] **Step 5: Commit**

  Run:

  ```bash
  git add app tests package.json docs
  git diff --cached --check
  git commit -m "feat: import company tax TT02 evidence safely"
  ```
