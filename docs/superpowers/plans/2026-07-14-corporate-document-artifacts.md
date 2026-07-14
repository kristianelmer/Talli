# Corporate Document Artifacts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace owner-dividend placeholders with deterministic, private, immutable corporate PDF artifacts and add annual-close artifacts whose approved, signed, owner-attested decisions are the only path to accounting finalization.

**Architecture:** A pure Python domain module validates and deterministically renders four versioned PDF templates from canonical decision input. Next.js recomputes persisted facts, invokes the Python CLI, verifies hashes, stores objects privately, and calls narrow PostgreSQL security-definer functions. PostgreSQL owns immutable decisions, artifacts, events, accounting-policy resolution, idempotent finalization, and payable clearing. Draft generation never posts accounting; signed finalization does.

**Tech Stack:** Python 3.12, Pydantic 2, ReportLab 5.0.0, Noto Sans, Next.js 16, TypeScript, Node test runner, Supabase/PostgreSQL, private Supabase Storage

## Global Constraints

- Preserve `docs/remarks/holdingswift_produktkrav.md` unchanged.
- Work on `codex/holdingswift-production-readiness`; do not rewrite prior commits.
- Keep `TALLI_CORPORATE_DOCUMENTS_ENABLED=false` by default.
- Do not encode an unreviewed chart-of-accounts mapping. Owner-dividend finalization and payment resolve an enabled immutable `corporate_accounting_policies` row created only after named Norwegian accounting review.
- Never create a ledger entry, holding action, payable, or bank posting during draft generation.
- Never call a signed PDF cryptographically verified. The supported status is `signed_owner_attested`.
- Store all PDFs in the existing private `company-documents` bucket with `upsert: false`.
- Use canonical UTF-8 JSON and SHA-256 independently in Python and Node.
- Add or change behavior only after a focused failing test; run the focused test red, make the smallest implementation, then run it green.
- Run `git diff --check` before every task commit.

---

### Task 1: Canonical decision models and supported-scope validation

**Files:**

- Create: `holding_core/corporate_documents.py`
- Create: `tests/test_corporate_documents.py`
- Create: `tests/fixtures/corporate_documents/owner_dividend.json`
- Create: `tests/fixtures/corporate_documents/annual_close.json`
- Modify: `holding_core/__init__.py`

**Interfaces:**

- Consumes: the approved immutable-input and supported-launch-scope rules in `docs/superpowers/specs/2026-07-14-corporate-document-artifacts-design.md`.
- Produces: `CorporateDecisionInput`, `CorporateArtifactKind`, `CorporateDocumentValidationError`, `canonical_decision_json(CorporateDecisionInput) -> bytes`, `decision_sha256(CorporateDecisionInput) -> str`, `required_artifact_kinds(CorporateDecisionInput) -> tuple[CorporateArtifactKind, ...]`, and `validate_supported_scope(CorporateDecisionInput) -> None`.

- [x] **Step 1: Add failing canonicalization and validation tests**

  Define fixtures with stable UUIDs, `LOGISK ØDE TIGER AS`, two ordered board participants, two proportional shareholders, full representation, unanimous votes, exact annual totals in integer øre, and fixed meeting facts. Add tests for these public types and signatures:

  ```python
  class CorporateDocumentValidationError(ValueError):
      code: str

  CorporateDecisionInput
  CorporateArtifactKind
  canonical_decision_json(decision: CorporateDecisionInput) -> bytes
  decision_sha256(decision: CorporateDecisionInput) -> str
  required_artifact_kinds(decision: CorporateDecisionInput) -> tuple[CorporateArtifactKind, ...]
  validate_supported_scope(decision: CorporateDecisionInput) -> None
  ```

  Assert canonical bytes are identical after JSON key reordering; lists retain validated business order; money is integer øre; owner dividend requires latest approved annual basis, one share class, all board members, all shares, unanimity, proportional allocation, payment after decision, sufficient available equity, and non-negative post-payment liquidity. Assert each unsupported case emits the design's exact blocker code.

- [x] **Step 2: Run the Python test red**

  Run: `uv run python -m unittest tests.test_corporate_documents -v`

  Expected: import failure for `holding_core.corporate_documents`.

- [x] **Step 3: Implement the typed immutable models and validators**

  Use Pydantic models with `ConfigDict(extra="forbid", frozen=True)`, `date`/`time` fields, non-empty normalized strings, positive share counts, integer-øre money, and discriminated `decision_kind`. Assign `decision.model_dump(mode="json", exclude_none=False)` to `payload`, then serialize with `json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`. Exclude no decision fields and include no runtime timestamp.

- [x] **Step 4: Run focused and full Python tests green**

  Run: `uv run python -m unittest tests.test_corporate_documents -v`

  Expected: all corporate decision tests pass.

  Run: `uv run python -m unittest discover -s tests -p 'test_*.py'`

  Expected: the existing Python suite remains green.

- [x] **Step 5: Commit**

  Run: `git add holding_core/corporate_documents.py holding_core/__init__.py tests/test_corporate_documents.py tests/fixtures/corporate_documents && git commit -m "feat: model immutable corporate decisions"`

---

### Task 2: Deterministic, versioned PDF renderer and CLI boundary

**Files:**

- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `holding_core/corporate_documents.py`
- Modify: `holding_cli/main.py`
- Modify: `tests/test_corporate_documents.py`
- Create: `holding_core/assets/fonts/NotoSans-Regular.ttf`
- Create: `holding_core/assets/fonts/NotoSans-Bold.ttf`
- Create: `holding_core/assets/fonts/OFL.txt`

**Interfaces:**

- Consumes: Task 1's `CorporateDecisionInput`, canonical bytes/hash, artifact kinds, and validation error.
- Produces: `RenderedCorporateArtifact`, `render_corporate_documents(CorporateDecisionInput) -> tuple[RenderedCorporateArtifact, ...]`, template version `corporate-no-v1-reportlab-5.0.0-noto-ffebf8c1`, and the CLI JSON contract consumed by Task 5.

- [x] **Step 1: Add failing render and CLI tests**

  Test these signatures and output contract:

  ```python
  class RenderedCorporateArtifact(BaseModel):
      artifact_kind: CorporateArtifactKind
      filename: str
      template_version: str
      decision_hash: str
      content_sha256: str
      byte_length: int
      pdf_bytes: bytes

  render_corporate_documents(decision: CorporateDecisionInput) -> tuple[RenderedCorporateArtifact, ...]
  ```

  Assert the same fixture renders byte-identical output twice, each byte stream begins `%PDF-`, independently recomputed hashes and lengths match, metadata contains only stable values, both owner-dividend and both annual-close kinds render, and extracted page content contains Norwegian names, organization number, meeting facts, exact amounts, decision wording, signature lines, decision hash, and template version. Test `talli render-corporate-documents --stdin-json` returns JSON with base64 bytes and typed blocked output on invalid input.

- [x] **Step 2: Run the renderer test red**

  Run: `uv run python -m unittest tests.test_corporate_documents -v`

  Expected: missing renderer symbols and CLI command.

- [x] **Step 3: Pin ReportLab and the exact font assets**

  Set `reportlab==5.0.0` in `pyproject.toml`, then run `uv lock` and `uv sync`.

  Download the three immutable upstream assets from Noto commit `ffebf8c1ee449e544955a7e813c54f9b73848eac`:

  - `https://raw.githubusercontent.com/notofonts/noto-fonts/ffebf8c1ee449e544955a7e813c54f9b73848eac/hinted/ttf/NotoSans/NotoSans-Regular.ttf`
  - `https://raw.githubusercontent.com/notofonts/noto-fonts/ffebf8c1ee449e544955a7e813c54f9b73848eac/hinted/ttf/NotoSans/NotoSans-Bold.ttf`
  - `https://raw.githubusercontent.com/notofonts/noto-fonts/ffebf8c1ee449e544955a7e813c54f9b73848eac/LICENSE`

  Verify SHA-256 before use:

  - regular: `b85c38ecea8a7cfb39c24e395a4007474fa5a4fc864f6ee33309eb4948d232d5`
  - bold: `c976e4b1b99edc88775377fcc21692ca4bfa46b6d6ca6522bfda505b28ff9d6a`

- [x] **Step 4: Implement stable rendering**

  Register the bundled fonts, use ReportLab invariant mode and fixed metadata, suppress runtime dates and random identifiers, use stable page geometry and ordering, and set template version `corporate-no-v1-reportlab-5.0.0-noto-ffebf8c1`. In tests, write rendered bytes to a temporary file and invoke the verified Poppler `pdftotext` binary for content assertions; the application itself must not invoke or depend on Poppler.

- [x] **Step 5: Implement the CLI JSON contract**

  Add `render-corporate-documents --stdin-json`. Success output is `{status:"rendered", decisionHash, artifacts:[{artifactKind, filename, templateVersion, decisionHash, contentSha256, byteLength, pdfBase64}]}`. Validation failures are `{status:"blocked", issues:[{code,message}]}` and exit 1; unexpected rendering failures use `corporate_documents_render_failed`, omit document bytes, and exit 1.

- [x] **Step 6: Run renderer, CLI, and full Python tests green**

  Run: `uv run python -m unittest tests.test_corporate_documents -v`

  Run: `printf '%s' "$(cat tests/fixtures/corporate_documents/owner_dividend.json)" | uv run talli render-corporate-documents --stdin-json > /tmp/talli-corporate-render.json && jq -e '.status == "rendered" and (.artifacts | length == 2)' /tmp/talli-corporate-render.json`

  Run: `uv run python -m unittest discover -s tests -p 'test_*.py'`

  Expected: all commands exit 0.

- [x] **Step 7: Commit**

  Run: `git add pyproject.toml uv.lock holding_core/corporate_documents.py holding_core/assets holding_cli/main.py tests/test_corporate_documents.py && git commit -m "feat: render deterministic corporate PDFs"`

---

### Task 3: Immutable PostgreSQL lifecycle schema and policies

**Files:**

- Create: `supabase/migrations/0004_corporate_document_artifacts.sql`
- Create: `tests/corporate_document_schema.test.mjs`
- Modify: `docs/supabase/talli_mvp_schema.sql`

**Interfaces:**

- Consumes: canonical decision hashes, artifact kinds, variants, state events, and accounting-policy gate defined by Tasks 1–2 and the design.
- Produces: six immutable tables, company/year indexes, composite foreign keys, read-only membership RLS, immutable triggers, and SQL types/constraints consumed by Task 4 RPCs and Task 11 archive queries.

- [x] **Step 1: Add a failing structural schema test**

  Assert the migration creates `corporate_accounting_policies`, `corporate_decisions`, `corporate_document_sets`, `corporate_document_artifacts`, `corporate_document_events`, and `corporate_decision_finalizations`; uses SHA-256 hex checks, constrained kinds/variants/events, cross-company composite foreign keys, unique request/idempotency/storage/finalization constraints, RLS, immutable triggers, `security definer` functions with `set search_path = public, pg_temp`, and authenticated read-only policies scoped through accepted membership. Assert direct authenticated insert/update/delete is revoked for all six tables.

- [x] **Step 2: Run the schema test red**

  Run: `node --test tests/corporate_document_schema.test.mjs`

  Expected: missing migration file.

- [x] **Step 3: Add tables, constraints, RLS, and immutable triggers**

  Use UUID primary keys supplied as request IDs for decisions/sets/artifacts. Use `numeric(18,2)` only for ledger amounts already represented as decimal currency and store document decision money as integer øre inside canonical JSON. Add `prevent_corporate_record_mutation()` before-update/delete triggers. Give `service_role` full access, accepted company members select access, and authenticated users no direct writes. Keep the accounting-policy table inaccessible to authenticated users.

- [x] **Step 4: Add migration to the consolidated schema and run structural tests**

  Add the repository-standard `\i ../../supabase/migrations/0004_corporate_document_artifacts.sql` include to `docs/supabase/talli_mvp_schema.sql` after migrations 0001–0003 so the consolidated schema continues to apply the migration source of truth in lexical order.

  Run: `node --test tests/corporate_document_schema.test.mjs tests/investment_lots_schema.test.mjs tests/bank_suggestion_schema.test.mjs`

  Expected: all schema tests pass.

- [x] **Step 5: Commit**

  Run: `git add supabase/migrations/0004_corporate_document_artifacts.sql docs/supabase/talli_mvp_schema.sql tests/corporate_document_schema.test.mjs && git commit -m "feat: add immutable corporate decision schema"`

---

### Task 4: Atomic draft, transition, finalization, and payment RPCs

**Files:**

- Modify: `supabase/migrations/0004_corporate_document_artifacts.sql`
- Modify: `docs/supabase/talli_mvp_schema.sql`
- Create: `tests/corporate_document_database_runtime.test.mjs`
- Create: `tests/fixtures/corporate_documents/database_rehearsal.sql`

**Interfaces:**

- Consumes: Task 3 tables/constraints plus existing `companies`, `company_memberships`, `step_up_events`, `documents`, `ledger_entries`, `holding_actions`, and `bank_transactions`.
- Produces: `create_corporate_document_draft(jsonb) -> jsonb`, `record_corporate_document_event(jsonb) -> jsonb`, `attest_corporate_signed_artifact(jsonb) -> jsonb`, `finalize_corporate_decision(jsonb) -> jsonb`, and `record_owner_dividend_payment(jsonb) -> jsonb`.

- [x] **Step 1: Add failing PostgreSQL runtime cases**

  Reuse the repository's temporary PostgreSQL rehearsal pattern. Cover:

  - `create_corporate_document_draft(jsonb)` creates decision, set, document/artifact rows, and `generated` events atomically without ledger/action rows;
  - exact request retry returns existing IDs only when hashes match;
  - mismatched retry and cross-company references fail;
  - `record_corporate_document_event(jsonb)` permits only legal state transitions and exact current hashes;
  - `attest_corporate_signed_artifact(jsonb)` requires a signed PDF document row, signer metadata, a fresh owner step-up, and an approved current decision;
  - `finalize_corporate_decision(jsonb)` blocks without all signed variants, enabled policy, current hashes, or accepted owner membership;
  - owner-dividend finalization creates exactly one balanced declaration ledger entry and holding action without account `1920` on the declaration credit;
  - annual-close finalization creates no unrelated ledger entry;
  - `record_owner_dividend_payment(jsonb)` clears the payable once, references the declaration, matches one bank transaction, and rejects overpayment/retry conflict;
  - direct mutation and rejected/superseded finalization fail.

- [x] **Step 2: Run database runtime test red**

  Run: `node --test tests/corporate_document_database_runtime.test.mjs`

  Expected: RPC assertions fail because functions are absent.

- [x] **Step 3: Implement the five security-definer RPCs**

  Implement exact functions:

  ```sql
  create_corporate_document_draft(jsonb) returns jsonb
  record_corporate_document_event(jsonb) returns jsonb
  attest_corporate_signed_artifact(jsonb) returns jsonb
  finalize_corporate_decision(jsonb) returns jsonb
  record_owner_dividend_payment(jsonb) returns jsonb
  ```

  Lock the decision and source rows `for update`; check `auth.uid()`, accepted owner membership, latest step-up age at most 15 minutes for approval/attestation/finalization, period state, source hash, artifact count/kinds, and policy registry internally. Derive ledger lines from policy accounts, not caller JSON. Set deterministic application-level idempotency keys in payloads/events. Revoke public execute and grant only the intended authenticated functions.

- [x] **Step 4: Run a fresh-migration PostgreSQL rehearsal green**

  Run: `node --test tests/corporate_document_database_runtime.test.mjs`

  Expected: all lifecycle, RLS, idempotency, and accounting cases pass against a fresh database.

  Run: `git diff --check`

- [x] **Step 5: Commit**

  Run: `git add supabase/migrations/0004_corporate_document_artifacts.sql docs/supabase/talli_mvp_schema.sql tests/corporate_document_database_runtime.test.mjs tests/fixtures/corporate_documents/database_rehearsal.sql && git commit -m "feat: add atomic corporate decision lifecycle"`

---

### Task 5: Node rendering bridge, independent hash checks, and private storage orchestration

**Files:**

- Create: `app/lib/corporate-documents.ts`
- Create: `app/lib/corporate-document-storage.ts`
- Create: `tests/corporate_documents.test.mjs`
- Modify: `package.json`
- Modify: `.env.example`

**Interfaces:**

- Consumes: Task 2's CLI success/blocked JSON and `resolveTalliPythonBinary()`.
- Produces: TypeScript `CorporateDecisionInput`, `RenderedCorporateArtifact`, `CorporateRenderResult`, `CorporateArtifactUploadInput`, `CorporateUploadResult`, `canonicalDecisionJson`, `corporateDecisionHash`, `parseCorporateRenderResult`, `renderCorporateDocuments`, `corporateArtifactStorageKey`, and `uploadCorporateArtifacts` for Tasks 6–9.

- [x] **Step 1: Add failing bridge and storage tests**

  Define and test:

  ```typescript
  CorporateDecisionInput
  RenderedCorporateArtifact
  canonicalDecisionJson(input: CorporateDecisionInput): string
  corporateDecisionHash(input: CorporateDecisionInput): string
  parseCorporateRenderResult(stdout: string, expected: CorporateDecisionInput): CorporateRenderResult
  renderCorporateDocuments(input: CorporateDecisionInput): Promise<CorporateRenderResult>
  corporateArtifactStorageKey(input: { companyId: string; incomeYear: number; setId: string; artifactKind: string; contentSha256: string }): string
  uploadCorporateArtifacts(input: CorporateArtifactUploadInput): Promise<CorporateUploadResult>
  ```

  Assert independent Node/Python canonical hash parity, base64/length/content-hash checks, exact required artifact kinds, bounded CLI stdout/stderr, malformed JSON failure, path validation, `upsert:false`, existing-object download/hash retry, and cleanup of only newly uploaded objects after later failure.

- [x] **Step 2: Run Node test red**

  Run: `node --experimental-strip-types --test tests/corporate_documents.test.mjs`

  Expected: module-not-found failures.

- [x] **Step 3: Implement the bridge and storage seam**

  Use `resolveTalliPythonBinary()`, `spawn` with stdin JSON and a 15-second timeout, a 10 MiB stdout cap, no shell, and a restricted inherited environment. Parse with explicit type guards. Recompute every hash with `node:crypto`. Accept a narrow injected Storage client in tests; production uses the authenticated server client and the private `company-documents` bucket.

- [x] **Step 4: Add scripts and feature defaults**

  Add `test:corporate-documents` to `package.json` and include it in `test:launch-rehearsal`. Add `TALLI_CORPORATE_DOCUMENTS_ENABLED=false` to `.env.example`.

- [x] **Step 5: Run bridge and regression tests green**

  Run: `npm run test:corporate-documents`

  Run: `npm run test:python-runtime`

  Run: `npm run typecheck`

  Expected: all commands pass.

- [x] **Step 6: Commit**

  Run: `git add app/lib/corporate-documents.ts app/lib/corporate-document-storage.ts tests/corporate_documents.test.mjs package.json .env.example && git commit -m "feat: add corporate PDF server bridge"`

---

### Task 6: Persisted fact builders and readiness state machine

**Files:**

- Create: `app/lib/corporate-decision-facts.ts`
- Create: `app/lib/corporate-document-readiness.ts`
- Create: `tests/corporate_decision_facts.test.mjs`
- Create: `tests/corporate_document_readiness.test.mjs`
- Modify: `app/lib/annual-readiness.ts`

**Interfaces:**

- Consumes: Task 5 TypeScript decision types plus persisted company/shareholder/annual/lifecycle rows.
- Produces: `buildOwnerDividendDecisionInput`, `buildAnnualCloseDecisionInput`, `allocateDividendOreProportionally`, `deriveCorporateDecisionState`, and `evaluateCorporateDocumentReadiness`, with typed blocker/state unions consumed by Tasks 7–9.

- [x] **Step 1: Add failing fact-builder and readiness tests**

  Test owner-dividend inputs are computed from company identity, all persisted shareholders, latest approved annual totals, and submitted meeting fields; allocations are proportional by share count with deterministic øre remainder assignment. Reject client-supplied company names, shareholder counts, total shares, available equity, and annual hashes when they differ from persisted data. Test annual-close decisions bind both annual-data and annual-account-payload hashes.

  Define readiness states `draft`, `rendered`, `facts_approved`, `signed_owner_attested`, `finalized`, `superseded`, `rejected`, derived only from immutable rows/events. Assert annual submission readiness blocks unless the current annual decision hash matches and is finalized.

- [x] **Step 2: Run focused tests red**

  Run: `node --experimental-strip-types --test tests/corporate_decision_facts.test.mjs tests/corporate_document_readiness.test.mjs`

  Expected: missing modules.

- [x] **Step 3: Implement pure fact builders and readiness evaluator**

  Keep Supabase access outside pure functions. Normalize Norwegian form input, stable-sort participants by supplied order plus stable ID, allocate money using integer øre, and compare exact hashes. Return typed blocker codes rather than booleans.

- [x] **Step 4: Run focused and annual readiness regressions green**

  Run: `node --experimental-strip-types --test tests/corporate_decision_facts.test.mjs tests/corporate_document_readiness.test.mjs tests/annual_readiness_gates.test.mjs`

  Expected: all tests pass.

- [x] **Step 5: Commit**

  Run: `git add app/lib/corporate-decision-facts.ts app/lib/corporate-document-readiness.ts app/lib/annual-readiness.ts tests/corporate_decision_facts.test.mjs tests/corporate_document_readiness.test.mjs && git commit -m "feat: derive corporate decision facts and readiness"`

---

### Task 7: Replace legacy owner-dividend posting with a review-first draft action

**Files:**

- Modify: `app/lib/owner-dividend.ts`
- Modify: `tests/owner_dividend.test.mjs`
- Modify: `app/actions.ts`
- Modify: `app/(owner)/actions/_components/OwnerDividendWizard.tsx`
- Modify: `app/(owner)/actions/new/page.tsx`
- Modify: `app/(owner)/workspace/page.tsx`

**Interfaces:**

- Consumes: Task 5 render/storage orchestration, Task 6 owner-dividend fact builder/readiness, and Task 4 `create_corporate_document_draft` RPC.
- Produces: server action `createOwnerDividendDecisionDraft(FormData) -> Promise<void>` and a decision-review redirect to `/corporate-decisions/{decisionId}`; removes the legacy `recordOwnerDividend` write path.

- [x] **Step 1: Rewrite owner-dividend tests to fail on legacy behavior**

  Assert no exported helper produces `2050/1920` declaration lines or `.txt` placeholder documents. Assert the wizard accepts all shareholders, board/meeting participants, one-share-class/full-participation/full-representation/unanimity confirmations, and exposes only proportional allocations. Assert the server action is named `createOwnerDividendDecisionDraft` and `recordOwnerDividend` is absent.

- [x] **Step 2: Run owner-dividend test red**

  Run: `npm run test:owner-dividend`

  Expected: assertions identify the legacy bank posting and placeholders.

- [x] **Step 3: Implement the draft-only server action**

  `createOwnerDividendDecisionDraft(formData)` authenticates the owner, checks the feature flag, loads the accepted membership/company/all shareholders/annual sources/period state, builds facts server-side, renders and uploads both PDFs, calls `create_corporate_document_draft`, cleans up only new objects after RPC failure, audits IDs/hashes without bodies, and redirects to the decision review. It does not insert `ledger_entries`, `holding_actions`, or placeholder `documents` directly.

- [x] **Step 4: Implement the review-first Norwegian UI**

  Present basis, computed allocations, meeting facts, participants, confirmations, and explicit unsupported-case blockers. Use `utkast` and `godkjent for signering`; never imply the draft is signed or booked. Keep the old workspace form unavailable when the feature is enabled and show a fail-closed explanation when disabled.

- [x] **Step 5: Run owner workflow tests and typecheck green**

  Run: `npm run test:owner-dividend`

  Run: `npm run test:corporate-documents`

  Run: `npm run typecheck`

  Expected: all commands pass and repository search finds no `.txt` corporate placeholders or early bank posting.

- [x] **Step 6: Commit**

  Run: `git add app/lib/owner-dividend.ts tests/owner_dividend.test.mjs app/actions.ts 'app/(owner)/actions/_components/OwnerDividendWizard.tsx' 'app/(owner)/actions/new/page.tsx' 'app/(owner)/workspace/page.tsx' && git commit -m "feat: create owner dividend decision drafts"`

---

### Task 8: Annual board and general-meeting artifact flow

**Files:**

- Modify: `app/actions.ts`
- Modify: `app/(owner)/filing/[obligation]/page.tsx`
- Modify: `app/(owner)/year-end/page.tsx`
- Create: `app/(owner)/year-end/CorporateAnnualDecisionForm.tsx`
- Create: `tests/annual_corporate_documents.test.mjs`
- Modify: `package.json`

**Interfaces:**

- Consumes: Task 5 render/storage orchestration, Task 6 annual-close fact builder/readiness, current annual-data and annual-account payload hashes, and Task 4 draft RPC.
- Produces: server action `createAnnualCorporateDecisionDraft(FormData) -> Promise<void>`, annual corporate-decision form, and annual readiness integration consumed by Task 9 finalization.

- [x] **Step 1: Add failing annual artifact tests**

  Assert `createAnnualCorporateDecisionDraft(formData)` accepts only an annual-data/annual-payload-ready year, recomputes both source hashes, creates exactly `annual_board_minutes` and `annual_general_meeting_minutes`, never creates an unrelated ledger entry, and becomes stale when annual facts change. Assert the filing page blocks production readiness until the matching decision is signed/attested/finalized.

- [x] **Step 2: Run annual corporate test red**

  Run: `node --experimental-strip-types --test tests/annual_corporate_documents.test.mjs`

  Expected: missing annual decision action/UI.

- [x] **Step 3: Implement annual decision draft action and form**

  Reuse the common rendering/storage/RPC orchestration. Bind the canonical decision to current annual-data and annual-account payload hashes. Render adoption/minutes facts but state that annual accounts themselves require separate statutory signatures.

- [x] **Step 4: Integrate readiness and scripts**

  Add `test:annual-corporate-documents` and include it in launch rehearsal. Show current/superseded status, hashes, template version, and actionable missing steps in year-end and filing views.

- [x] **Step 5: Run annual tests and typecheck green**

  Run: `npm run test:annual-corporate-documents`

  Run: `npm run test:annual-readiness`

  Run: `npm run test:annual-accounts`

  Run: `npm run typecheck`

  Expected: all commands pass.

- [x] **Step 6: Commit**

  Run: `git add app/actions.ts 'app/(owner)/filing/[obligation]/page.tsx' 'app/(owner)/year-end/page.tsx' 'app/(owner)/year-end/CorporateAnnualDecisionForm.tsx' tests/annual_corporate_documents.test.mjs package.json && git commit -m "feat: add annual corporate decision artifacts"`

---

### Task 9: Owner approval, signed-copy attestation, and immutable finalization

**Files:**

- Modify: `app/lib/security.ts`
- Modify: `tests/security_step_up.test.mjs`
- Modify: `app/actions.ts`
- Create: `app/(owner)/corporate-decisions/[decisionId]/page.tsx`
- Create: `app/(owner)/corporate-decisions/[decisionId]/SignedArtifactUpload.tsx`
- Create: `app/documents/[documentId]/preview/route.ts`
- Create: `tests/corporate_decision_workflow.test.mjs`

**Interfaces:**

- Consumes: Tasks 4–8 decision rows, RPCs, rendered/private objects, derived state, and existing step-up helpers.
- Produces: sensitive actions `approve_corporate_facts`, `attest_signed_corporate_document`, `finalize_corporate_decision`; server actions `approveCorporateDecisionFacts`, `recordCorporateSigningRequested`, `attestSignedCorporateArtifact`, `rejectCorporateDecision`, `finalizeCorporateDecision`; and owner-only review/preview/upload UI.

- [x] **Step 1: Add failing security and workflow tests**

  Add sensitive actions `approve_corporate_facts`, `attest_signed_corporate_document`, and `finalize_corporate_decision`, all requiring accepted owner and MFA no older than 15 minutes. Test exact-hash approval; PDF MIME, `%PDF-` magic, non-empty body, and 10 MiB limit; explicit required signer names; separate immutable signed storage key; stale/rejected/superseded failure; enabled accounting policy requirement for dividend; idempotent finalization; annual finalization without ledger; and private owner-only inline preview.

- [x] **Step 2: Run tests red**

  Run: `node --experimental-strip-types --test tests/security_step_up.test.mjs tests/corporate_decision_workflow.test.mjs`

  Expected: missing sensitive actions and workflow routes/actions.

- [x] **Step 3: Implement lifecycle actions**

  Add `approveCorporateDecisionFacts`, `recordCorporateSigningRequested`, `attestSignedCorporateArtifact`, `rejectCorporateDecision`, and `finalizeCorporateDecision`. Each authenticates, loads the immutable decision/set/artifacts, calls `requireStepUpForAction` where required, verifies current hashes, then invokes one RPC. Signed upload uses a new object with `upsert:false`; failure cleanup cannot delete the unsigned or prior signed object.

- [x] **Step 4: Implement the decision review page**

  Display persisted facts, template/input/content hashes, owner-only PDF previews, state history, exact signer checklist, signed uploads, and finalization result. Copy must say `signert kopi bekreftet av eier`, not `verifisert signatur`.

- [x] **Step 5: Run workflow, security, document, and type tests green**

  Run: `node --experimental-strip-types --test tests/security_step_up.test.mjs tests/corporate_decision_workflow.test.mjs tests/documents.test.mjs`

  Run: `npm run typecheck`

  Expected: all commands pass.

- [x] **Step 6: Commit**

  Run: `git add app/lib/security.ts tests/security_step_up.test.mjs app/actions.ts 'app/(owner)/corporate-decisions/[decisionId]/page.tsx' 'app/(owner)/corporate-decisions/[decisionId]/SignedArtifactUpload.tsx' 'app/documents/[documentId]/preview/route.ts' tests/corporate_decision_workflow.test.mjs && git commit -m "feat: finalize owner-attested corporate decisions"`

---

### Task 10: Dividend payable payment matching

**Files:**

- Modify: `app/lib/owner-dividend.ts`
- Create: `app/lib/owner-dividend-payment.ts`
- Modify: `tests/owner_dividend.test.mjs`
- Create: `tests/owner_dividend_payment.test.mjs`
- Modify: `app/actions.ts`
- Modify: `app/(owner)/workspace/page.tsx`

**Interfaces:**

- Consumes: Task 4 `record_owner_dividend_payment` RPC, Task 9 finalized declaration rows, eligible persisted bank transactions, and the immutable accounting-policy version resolved in PostgreSQL.
- Produces: `validateOwnerDividendPaymentInput`, `deriveOpenDividendPayable`, and server action `recordOwnerDividendPayment(FormData) -> Promise<void>`.

- [x] **Step 1: Add failing declaration/payment separation tests**

  Assert declaration lines are not computed client-side and never credit bank. Test payment input references one finalized declaration, one unmatched outgoing bank transaction, and the open payable. Reject wrong company/year/currency/sign, amount above open payable, already matched transactions, and duplicate idempotency conflicts. Assert payment ledger lines are returned only from the policy-bound RPC and contain payable debit/bank credit.

- [x] **Step 2: Run payment tests red**

  Run: `node --experimental-strip-types --test tests/owner_dividend.test.mjs tests/owner_dividend_payment.test.mjs`

  Expected: missing payment module/action.

- [x] **Step 3: Implement payment matching and UI**

  Add `recordOwnerDividendPayment(formData)` with feature flag, authentication, fresh step-up, persisted reference checks, and `record_owner_dividend_payment` RPC. Present only eligible outgoing bank transactions and the remaining payable. Support partial payments while total paid cannot exceed declared amount; the final payment marks the payable settled by derived state, not mutation.

- [x] **Step 4: Run payment, bank, and owner tests green**

  Run: `node --experimental-strip-types --test tests/owner_dividend.test.mjs tests/owner_dividend_payment.test.mjs tests/bank_workflow.test.mjs tests/bank_suggestion_integration.test.mjs`

  Run: `npm run typecheck`

  Expected: all commands pass.

- [x] **Step 5: Commit**

  Run: `git add app/lib/owner-dividend.ts app/lib/owner-dividend-payment.ts tests/owner_dividend.test.mjs tests/owner_dividend_payment.test.mjs app/actions.ts 'app/(owner)/workspace/page.tsx' && git commit -m "feat: match dividend payments to declared payable"`

---

### Task 11: Archive, backup/restore, cancellation, and operational evidence

**Files:**

- Modify: `app/lib/supabase/server.ts`
- Modify: `app/lib/workspace-data.ts`
- Modify: `app/lib/archive.ts`
- Modify: `app/lib/backup-restore.ts`
- Modify: `app/archive/[companyId]/[incomeYear]/download/route.ts`
- Modify: `app/lib/cancellation.ts`
- Modify: `tests/archive_export.test.mjs`
- Modify: `tests/backup_restore.test.mjs`
- Modify: `tests/cancellation.test.mjs`
- Create: `docs/launch/corporate-document-release-gate.md`
- Create: `docs/security/corporate-document-backup-restore-runbook.md`

**Interfaces:**

- Consumes: all Task 3 lifecycle row types, Task 5 storage references/hashes, Task 9 signed variants/finalizations, and current archive/restore/cancellation structures.
- Produces: corporate lifecycle fields in persisted workspace/archive/manifest/restore models, object-reference integrity checks, cancellation evidence requirements, and external release-gate/runbook documents.

- [x] **Step 1: Add failing archive and restore assertions**

  Assert company/year archives include decisions, sets, artifacts, events, finalizations, policy version references, document metadata, and both unsigned/signed object references. Assert manifests count all new tables/objects; restore fixtures preserve IDs/hashes/relationships; integrity fails on missing corporate rows or objects; cancellation blocks until corporate objects are included in export evidence.

- [x] **Step 2: Run archive/restore tests red**

  Run: `node --experimental-strip-types --test tests/archive_export.test.mjs tests/backup_restore.test.mjs tests/cancellation.test.mjs`

  Expected: missing corporate lifecycle data assertions fail.

- [x] **Step 3: Extend data loading, archive, manifest, restore, and cancellation**

  Query each table by company/year with explicit columns. Include object content hashes and sizes in the manifest. Never embed raw signed PDFs in JSON archives; include authenticated storage references and verify them during the backup rehearsal.

- [x] **Step 4: Write operator runbooks and immutable release gate**

  Name every external gate: legal review of four templates, accounting review of policy accounts, PDF golden/visual approval, deployed RLS/storage test evidence, backup/restore rehearsal, and public-copy review. State current status and required evidence fields without marking an unavailable review complete.

- [x] **Step 5: Run archive/restore/cancellation tests green**

  Run: `node --experimental-strip-types --test tests/archive_export.test.mjs tests/backup_restore.test.mjs tests/cancellation.test.mjs`

  Expected: all commands pass.

- [x] **Step 6: Commit**

  Run: `git add app/lib/supabase/server.ts app/lib/workspace-data.ts app/lib/archive.ts app/lib/backup-restore.ts 'app/archive/[companyId]/[incomeYear]/download/route.ts' app/lib/cancellation.ts tests/archive_export.test.mjs tests/backup_restore.test.mjs tests/cancellation.test.mjs docs/launch/corporate-document-release-gate.md docs/security/corporate-document-backup-restore-runbook.md && git commit -m "feat: archive corporate decision evidence"`

---

### Task 12: Production verification and handoff

**Files:**

- Modify: `docs/launch/production-launch-rehearsal.md`
- Modify: `docs/launch/clearance-checklist.md`
- Modify: `docs/launch/corporate-document-release-gate.md`
- Modify: `docs/prd/talli-holding-first-filing-assistant.md`
- Modify: `docs/superpowers/plans/2026-07-14-corporate-document-artifacts.md`
- Create: `docs/launch/evidence/corporate-document-local-rehearsal.md`

**Interfaces:**

- Consumes: every implementation/test command and artifact from Tasks 1–11.
- Produces: reproducible local launch evidence, updated clearance status, exact pending external gates, and a clean reviewable branch with the feature disabled by default.

- [x] **Step 1: Run static safety scans**

  Run: `rg -n "Styreforslag utbytte\.txt|Generalforsamlingsprotokoll utbytte\.txt|missing_placeholder|Dividend paid from bank|account: \"1920\"" app tests`

  Expected: no legacy corporate placeholder or declaration-as-payment matches.

  Run: `rg -n "service_role|SUPABASE_SERVICE_ROLE_KEY|PRIVATE KEY|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY" app holding_core tests docs --glob '!docs/superpowers/**'`

  Expected: no embedded secret material; documentation references are reviewed individually.

- [x] **Step 2: Run all automated verification**

  Run: `uv run python -m unittest discover -s tests -p 'test_*.py'`

  Run: `npm run test:launch-rehearsal`

  Run: `npm run test:web`

  Run: `npm run test:supabase`

  Run: `npm run typecheck`

  Run: `npm run build`

  Run: `npm audit --audit-level=high`

  Expected: local commands pass. If authenticated Supabase credentials are absent, record that exact external gate as not run; do not claim it passed.

- [x] **Step 3: Verify PDFs structurally and visually**

  Render both fixtures twice; compare SHA-256; run `pdfinfo` and `pdftotext` on all four files; confirm page counts, valid structure, Norwegian text extraction, no dynamic timestamps, and no clipped text. Render pages to PNG with `pdftoppm`, inspect all pages, and record hashes/template version/screenshots in the local rehearsal evidence.

- [x] **Step 4: Rehearse fresh PostgreSQL and private storage behavior**

  Run migrations 0001–0004 into a fresh local PostgreSQL instance, execute the database runtime suite, and exercise draft/retry/approval/attestation/finalization/payment/cross-company denial. If deployed Supabase credentials exist, repeat RLS and storage tests against the configured test project; otherwise leave the release gate explicitly pending.

- [x] **Step 5: Update launch evidence without overstating readiness**

  Record exact commands, versions, commit SHA, output summaries, PDF hashes, font hashes, migration results, and pending named reviews. Keep `TALLI_CORPORATE_DOCUMENTS_ENABLED=false` until every external release-gate row is evidenced.

- [x] **Step 6: Run final diff and status checks**

  Run: `git diff --check`

  Run: `git status --short`

  Run: `git log --oneline --decorate -15`

  Expected: no unintended or uncommitted files; commits are task-scoped and reviewable.

- [x] **Step 7: Commit verification evidence**

  Run: `git add docs/launch/production-launch-rehearsal.md docs/launch/clearance-checklist.md docs/launch/corporate-document-release-gate.md docs/launch/evidence/corporate-document-local-rehearsal.md docs/prd/talli-holding-first-filing-assistant.md docs/superpowers/plans/2026-07-14-corporate-document-artifacts.md && git commit -m "docs: record corporate document launch rehearsal"`

  Expected: the commit contains only reviewed evidence/documentation changes; external gates remain visibly pending until supplied.
