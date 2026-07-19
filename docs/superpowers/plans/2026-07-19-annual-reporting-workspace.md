# Annual-Reporting Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the monolithic annual-reporting prototype with a production-ready, backend-integrated workspace for one company, one reporting year, three annual obligations, and owner/reviewer roles.

**Architecture:** Add a pure typed view-model layer over persisted readiness, deadline, document, review, authority, billing, and submission records. Load that data in a company/year route, render it through a shared product shell and obligation template, and keep existing server actions authoritative by returning them safely to the originating workspace route. Migrate annual content out of the root prototype only after the new route passes contract, accessibility, responsive, and critical-flow verification.

**Tech Stack:** Next.js 16 App Router, React 19 server components, TypeScript 6, Supabase SSR/RLS, Node's built-in test runner, Playwright, CSS Modules plus the tokens in `DESIGN.md`.

## Global Constraints

- Customer-facing copy is Norwegian-first and plain-spoken.
- Use the exact three launch obligations: `aksjonaerregisteroppgaven`, `aarsregnskap`, and `skattemelding`.
- Server state is canonical; never fabricate completion, readiness, submission, reviewer, or permission state.
- Preserve existing accounting, validation, authority, billing, MFA, RLS, and submission logic.
- The workspace is guided but non-linear: recommend one next action while keeping available obligations independently navigable.
- Unsupported cases block only the affected filing and preserve access to unaffected records.
- Owner and reviewer use the same information architecture; permissions change controls, not routes.
- Meet WCAG 2.2 AA, including keyboard operation, visible focus, non-color cues, screen-reader semantics, and reduced motion.
- Use `DESIGN.md`: Crisp Canvas `#f7f8fa`, Filing Green `#176b55` below roughly ten percent, Quiet Ink `#17202a`, Fine Rule `#dfe5e8`, 6–10px curves, and flat-by-default elevation.
- Prohibit cream/beige canvases, gradients, glassmorphism, hero metrics, uppercase eyebrows, identical card grids, border-plus-wide-shadow ghost cards, and radii above 16px.
- Use 150–250ms exponential ease-out transitions; no decorative page-load choreography.
- Do not add a component library, icon package, client state library, or new persistence table.

---

## File structure

### New files

- `app/lib/annual-workspace.ts` — pure route, status, progress, next-action, and view-model derivation.
- `app/lib/annual-workspace-server.ts` — authenticated company/year loader that scopes persisted records and reports bounded load failures.
- `app/lib/action-return.ts` — allow-listed post-action return-path parsing for annual routes.
- `app/components/annual-workspace/AnnualWorkspaceShell.tsx` — company/year header, labeled navigation, role indicator, responsive frame.
- `app/components/annual-workspace/AnnualOverview.tsx` — next action, three obligation rows, and contextual rail composition.
- `app/components/annual-workspace/ObligationRow.tsx` — semantic obligation summary row.
- `app/components/annual-workspace/ContextRail.tsx` — deadlines, documents, and reviewer activity.
- `app/components/annual-workspace/ObligationWorkspace.tsx` — shared readiness, evidence, review, and action template.
- `app/components/annual-workspace/SubmissionReview.tsx` — authority/billing/review gates and durable submission outcomes.
- `app/components/annual-workspace/annual-workspace.module.css` — scoped implementation of `DESIGN.md` and responsive states.
- `app/companies/[companyId]/annual-reporting/[incomeYear]/layout.tsx` — authenticated shared annual shell.
- `app/companies/[companyId]/annual-reporting/[incomeYear]/page.tsx` — annual overview.
- `app/companies/[companyId]/annual-reporting/[incomeYear]/[obligation]/page.tsx` — obligation detail route.
- `app/companies/[companyId]/annual-reporting/[incomeYear]/review/page.tsx` — final review and submission surface.
- `app/companies/[companyId]/annual-reporting/[incomeYear]/loading.tsx` — layout-preserving skeleton.
- `app/companies/[companyId]/annual-reporting/[incomeYear]/error.tsx` — recoverable client error boundary.
- `tests/annual_workspace_view_model.test.mjs` — pure model, status, progress, next-action, and unsupported-case tests.
- `tests/annual_workspace_scope.test.mjs` — company/year scoping and role presentation tests.
- `tests/action_return.test.mjs` — redirect allow-list and injection rejection tests.
- `tests/annual_workspace_render.test.mjs` — semantic source/render contracts for overview and detail surfaces.
- `tests/annual_workspace_routes.test.mjs` — route, Norwegian copy, and root-link migration contracts.
- `tests/browser_annual_workspace.mjs` — authenticated critical owner/reviewer browser flow and responsive checks.

### Modified files

- `app/lib/supabase/server.ts` — add current membership lookup for one company.
- `app/actions.ts` — safely revalidate and return annual-workspace actions to their origin.
- `app/page.tsx` — add the annual-workspace entry point and remove duplicated annual overview/readiness presentation after parity.
- `app/globals.css` — replace legacy warm prototype tokens with `DESIGN.md` primitives used outside the CSS Module.
- `package.json` — add focused annual-workspace test scripts.
- `tests/launch_copy.test.mjs` — follow required launch-boundary copy after annual content moves from root.

---

### Task 1: Build the pure annual-workspace view model

**Files:**
- Create: `app/lib/annual-workspace.ts`
- Create: `tests/annual_workspace_view_model.test.mjs`
- Modify: `package.json`

**Interfaces:**
- Consumes: `AuthorityObligation`, `FilingReadinessSnapshotRow`, `FilingDeadline`, `DocumentRow`, `FilingReviewCommentRow`, and `FilingSubmissionRow`.
- Produces: `annualOverviewHref()`, `annualObligationHref()`, `annualReviewHref()`, `AnnualWorkspaceViewModel`, `AnnualObligationViewModel`, and `buildAnnualWorkspaceViewModel()`.

- [ ] **Step 1: Write failing tests for ordering, next action, unsupported isolation, and submitted state**

```js
import assert from "node:assert/strict";
import test from "node:test";

import {
  annualObligationHref,
  annualOverviewHref,
  buildAnnualWorkspaceViewModel,
} from "../app/lib/annual-workspace.ts";

const company = { id: "company-1", name: "Nordlys Holding AS", org_number: "314259521" };
const context = { companyId: company.id, incomeYear: 2025 };
const snapshot = (obligation, status, issues = []) => ({
  obligation,
  income_year: 2025,
  status,
  ready: status !== "blocked",
  hard_blocks: status === "blocked" ? issues : [],
  warnings: status === "warning" ? issues : [],
  accepted_warnings: [],
  evaluated_at: "2026-01-01T00:00:00Z",
});

test("builds the fixed launch order and a deep next action", () => {
  const model = buildAnnualWorkspaceViewModel({
    context,
    company,
    role: "owner",
    snapshots: [
      snapshot("skattemelding", "ready"),
      snapshot("aarsregnskap", "warning", [{ code: "notes_missing", message: "Noter mangler.", source: "annual_data" }]),
      snapshot("aksjonaerregisteroppgaven", "ready"),
    ],
    deadlines: [], documents: [], comments: [], submissions: [],
  });

  assert.deepEqual(model.obligations.map((item) => item.obligation), [
    "aksjonaerregisteroppgaven", "aarsregnskap", "skattemelding",
  ]);
  assert.equal(model.nextAction.href, `${annualObligationHref(context, "aarsregnskap")}#issue-notes_missing`);
  assert.equal(model.nextAction.label, "Fullfør noter");
});

test("isolates an unsupported block to one filing", () => {
  const model = buildAnnualWorkspaceViewModel({
    context,
    company,
    role: "owner",
    snapshots: [
      snapshot("aksjonaerregisteroppgaven", "ready"),
      snapshot("aarsregnskap", "ready"),
      snapshot("skattemelding", "blocked", [{ code: "tax_return_unclear_fritaksmetoden", message: "Saken må vurderes av regnskapsfører.", source: "holding_actions" }]),
    ],
    deadlines: [], documents: [], comments: [], submissions: [],
  });

  assert.equal(model.obligations.find((item) => item.obligation === "skattemelding").unsupported, true);
  assert.equal(model.obligations.find((item) => item.obligation === "aarsregnskap").href, annualObligationHref(context, "aarsregnskap"));
});

test("uses a persisted receipt as submitted truth", () => {
  const model = buildAnnualWorkspaceViewModel({
    context,
    company,
    role: "owner",
    snapshots: [snapshot("aksjonaerregisteroppgaven", "ready")],
    deadlines: [], documents: [], comments: [],
    submissions: [{ filing: "aksjonærregisteroppgaven", income_year: 2025, status: "submitted", receipt_id: "receipt-1", updated_at: "2026-01-20T00:00:00Z" }],
  });

  assert.equal(model.obligations[0].status, "submitted");
  assert.equal(model.obligations[0].receiptId, "receipt-1");
  assert.equal(annualOverviewHref(context), "/companies/company-1/annual-reporting/2025");
});
```

- [ ] **Step 2: Run the focused test and confirm the missing-module failure**

Run: `node --experimental-strip-types --test tests/annual_workspace_view_model.test.mjs`

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `app/lib/annual-workspace.ts`.

- [ ] **Step 3: Implement routes, fixed obligation metadata, status derivation, and next-action resolution**

```ts
import type { AuthorityObligation } from "./authority-permission";
import { authorityObligationLabel } from "./authority-permission";
import type { FilingDeadline } from "./deadlines";
import type {
  DocumentRow,
  FilingReadinessSnapshotRow,
  FilingReviewCommentRow,
  FilingSubmissionRow,
} from "./supabase/server";

export type AnnualWorkspaceContext = { companyId: string; incomeYear: number };
export type AnnualWorkspaceRole = "owner" | "reviewer" | "read_only";
export type AnnualWorkspaceStatus = "not_started" | "ready" | "warning" | "blocked" | "submitted";
export type AnnualWorkspaceAction = { label: string; href: string };

export type AnnualObligationViewModel = {
  obligation: AuthorityObligation;
  label: string;
  href: string;
  status: AnnualWorkspaceStatus;
  statusLabel: string;
  deadline: FilingDeadline | null;
  hardBlocks: FilingReadinessSnapshotRow["hard_blocks"];
  warnings: FilingReadinessSnapshotRow["warnings"];
  acceptedWarnings: FilingReadinessSnapshotRow["accepted_warnings"];
  unsupported: boolean;
  receiptId: string | null;
  nextAction: AnnualWorkspaceAction;
};

export type AnnualWorkspaceViewModel = {
  context: AnnualWorkspaceContext;
  company: { id: string; name: string; org_number: string };
  role: AnnualWorkspaceRole;
  obligations: AnnualObligationViewModel[];
  nextAction: AnnualWorkspaceAction;
  documents: DocumentRow[];
  comments: FilingReviewCommentRow[];
};

const obligationOrder: AuthorityObligation[] = ["aksjonaerregisteroppgaven", "aarsregnskap", "skattemelding"];
const unsupportedCodes = new Set([
  "unsupported_entity", "tax_return_unclear_fritaksmetoden",
  "tax_return_three_percent_treatment_missing", "tax_return_three_percent_treatment_unresolved",
  "tax_return_shareholder_loan_review_required",
]);

export function annualOverviewHref(context: AnnualWorkspaceContext) {
  return `/companies/${context.companyId}/annual-reporting/${context.incomeYear}`;
}

export function annualObligationHref(context: AnnualWorkspaceContext, obligation: AuthorityObligation) {
  return `${annualOverviewHref(context)}/${obligation}`;
}

export function annualReviewHref(context: AnnualWorkspaceContext) {
  return `${annualOverviewHref(context)}/review`;
}

export function buildAnnualWorkspaceViewModel(input: {
  context: AnnualWorkspaceContext;
  company: AnnualWorkspaceViewModel["company"];
  role: AnnualWorkspaceRole;
  snapshots: Pick<FilingReadinessSnapshotRow, "obligation" | "income_year" | "status" | "ready" | "hard_blocks" | "warnings" | "accepted_warnings" | "evaluated_at">[];
  deadlines: FilingDeadline[];
  documents: DocumentRow[];
  comments: FilingReviewCommentRow[];
  submissions: Pick<FilingSubmissionRow, "filing" | "income_year" | "status" | "receipt_id" | "updated_at">[];
}): AnnualWorkspaceViewModel {
  const obligations = obligationOrder.map((obligation) => buildObligation(input, obligation));
  const next = obligations.find((item) => item.status === "blocked")
    ?? obligations.find((item) => item.status === "warning")
    ?? obligations.find((item) => item.status !== "submitted")
    ?? null;
  return {
    context: input.context,
    company: input.company,
    role: input.role,
    obligations,
    nextAction: next?.nextAction ?? { label: "Se kvitteringer", href: annualReviewHref(input.context) },
    documents: input.documents,
    comments: input.comments,
  };
}
```

Add private helpers in the same file that map filing strings to obligations, derive status labels, resolve issue codes to Norwegian verb labels, and append `#issue-${issue.code}` for the first actionable block or warning. Use a literal exhaustive record for known issue labels; unknown codes fall back to `Løs åpent punkt`, never raw internal codes.

- [ ] **Step 4: Add the focused test script**

```json
"test:annual-workspace": "node --experimental-strip-types --test tests/annual_workspace_view_model.test.mjs tests/annual_workspace_scope.test.mjs tests/action_return.test.mjs tests/annual_workspace_render.test.mjs tests/annual_workspace_routes.test.mjs"
```

- [ ] **Step 5: Run the focused and existing readiness tests**

Run: `node --experimental-strip-types --test tests/annual_workspace_view_model.test.mjs tests/annual_readiness_gates.test.mjs tests/deadlines.test.mjs`

Expected: all tests PASS.

- [ ] **Step 6: Commit the view-model slice**

```bash
git add app/lib/annual-workspace.ts tests/annual_workspace_view_model.test.mjs package.json
git commit -m "feat: add annual workspace view model"
```

---

### Task 2: Add authenticated company/year loading and role scoping

**Files:**
- Modify: `app/lib/supabase/server.ts`
- Create: `app/lib/annual-workspace-server.ts`
- Create: `tests/annual_workspace_scope.test.mjs`

**Interfaces:**
- Consumes: existing Supabase list functions plus `getCurrentUser()` and `CompanyMembershipRow`.
- Produces: `getCompanyMembership(companyId, userId)`, `scopeAnnualWorkspaceRecords()`, and `loadAnnualWorkspace(context)`.

- [ ] **Step 1: Write failing company/year and role-scoping tests**

```js
import assert from "node:assert/strict";
import test from "node:test";
import { scopeAnnualWorkspaceRecords } from "../app/lib/annual-workspace-server.ts";

test("scopes every collection to the selected company and year", () => {
  const scoped = scopeAnnualWorkspaceRecords(
    { companyId: "company-1", incomeYear: 2025 },
    {
      documents: [{ id: "keep", company_id: "company-1", income_year: 2025 }, { id: "drop-company", company_id: "company-2", income_year: 2025 }, { id: "drop-year", company_id: "company-1", income_year: 2024 }],
      comments: [{ id: "comment", company_id: "company-1" }, { id: "other", company_id: "company-2" }],
      snapshots: [{ id: "snapshot", company_id: "company-1", income_year: 2025 }, { id: "old", company_id: "company-1", income_year: 2024 }],
      submissions: [{ id: "submission", company_id: "company-1", income_year: 2025 }],
    },
  );
  assert.deepEqual(scoped.documents.map((item) => item.id), ["keep"]);
  assert.deepEqual(scoped.comments.map((item) => item.id), ["comment"]);
  assert.deepEqual(scoped.snapshots.map((item) => item.id), ["snapshot"]);
});
```

- [ ] **Step 2: Run the test and confirm the missing-module failure**

Run: `node --experimental-strip-types --test tests/annual_workspace_scope.test.mjs`

Expected: FAIL with `ERR_MODULE_NOT_FOUND`.

- [ ] **Step 3: Add the membership query**

```ts
export async function getCompanyMembership(companyId: string, userId: string) {
  if (!hasSupabaseEnv()) return { membership: null as CompanyMembershipRow | null, error: null };
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase
    .from("company_memberships")
    .select("company_id, user_id, role, accepted_at")
    .eq("company_id", companyId)
    .eq("user_id", userId)
    .maybeSingle();
  return { membership: (data ?? null) as CompanyMembershipRow | null, error: error?.message ?? null };
}
```

- [ ] **Step 4: Implement the pure scoper and authenticated loader**

```ts
import { notFound, redirect } from "next/navigation";
import { buildDeadlineDashboard } from "./deadlines";
import { buildAnnualWorkspaceViewModel, type AnnualWorkspaceContext } from "./annual-workspace";
import {
  getCompanyMembership, getCurrentUser, listAnnualData, listAuthorityPermissions,
  listBankTransactions, listBillingAccounts, listCompanyWorkspaces, listDocumentsForCompanies,
  listFilingOverrides, listFilingPreviews, listFilingReadinessSnapshots, listFilingReviewComments,
  listFilingSubmissions, listHoldingActions, listLedgerEntries, listOpeningSetups, listPeriodLocks,
} from "./supabase/server";

export function scopeAnnualWorkspaceRecords(context, records) {
  const inYear = (row) => row.company_id === context.companyId && row.income_year === context.incomeYear;
  return {
    ...records,
    documents: records.documents.filter(inYear),
    comments: records.comments.filter((row) => row.company_id === context.companyId),
    snapshots: records.snapshots.filter(inYear),
    submissions: records.submissions.filter(inYear),
  };
}

export async function loadAnnualWorkspace(context: AnnualWorkspaceContext) {
  const user = await getCurrentUser();
  if (!user) redirect("/?error=Innlogging%20kreves");
  const { companies, error: companyError } = await listCompanyWorkspaces();
  const company = companies.find((item) => item.id === context.companyId);
  if (companyError) throw new Error("Kunne ikke laste selskapsarbeidsflaten.");
  if (!company) notFound();
  const { membership, error: membershipError } = await getCompanyMembership(company.id, user.id);
  if (membershipError || !membership) notFound();

  const ids = [company.id];
  const [documentsResult, snapshotsResult, commentsResult, submissionsResult] = await Promise.all([
    listDocumentsForCompanies(ids), listFilingReadinessSnapshots(ids),
    listFilingReviewComments(ids), listFilingSubmissions(ids),
  ]);
  const firstError = documentsResult.error || snapshotsResult.error || commentsResult.error || submissionsResult.error;
  if (firstError) throw new Error("Kunne ikke laste årsrapporteringen. Prøv igjen.");
  const scoped = scopeAnnualWorkspaceRecords(context, {
    documents: documentsResult.documents, snapshots: snapshotsResult.readinessSnapshots,
    comments: commentsResult.comments, submissions: submissionsResult.submissions,
  });
  return buildAnnualWorkspaceViewModel({
    context, company, role: membership.role,
    snapshots: scoped.snapshots,
    deadlines: buildDeadlineDashboard({ incomeYear: context.incomeYear, submissions: scoped.submissions }),
    documents: scoped.documents, comments: scoped.comments, submissions: scoped.submissions,
  });
}
```

Expand the loader's single `Promise.all` to fetch the remaining existing annual inputs needed by obligation pages: setups, annual data, previews, overrides, transactions, actions, entries, locks, billing, and authority permissions. Return them as a `records` property beside `model`; surface one bounded Norwegian error string instead of provider details.

- [ ] **Step 5: Run scoping, Supabase, and type checks**

Run: `node --experimental-strip-types --test tests/annual_workspace_scope.test.mjs tests/supabase_workspace.test.mjs && npm run typecheck`

Expected: all tests PASS and TypeScript exits 0.

- [ ] **Step 6: Commit the loader slice**

```bash
git add app/lib/supabase/server.ts app/lib/annual-workspace-server.ts tests/annual_workspace_scope.test.mjs
git commit -m "feat: load role-aware annual workspace data"
```

---

### Task 3: Return existing server actions safely to the workspace

**Files:**
- Create: `app/lib/action-return.ts`
- Create: `tests/action_return.test.mjs`
- Modify: `app/actions.ts`

**Interfaces:**
- Consumes: `FormData` field `returnTo`.
- Produces: `safeActionReturnPath(value, fallback)` and a consistent `revalidatePath(returnTo); redirect(returnTo)` tail for annual actions.

- [ ] **Step 1: Write failing allow-list and redirect-injection tests**

```js
import assert from "node:assert/strict";
import test from "node:test";
import { safeActionReturnPath } from "../app/lib/action-return.ts";

test("accepts only local annual workspace routes", () => {
  const valid = "/companies/3d955bb1-23f5-4a12-b4cb-f749844fe150/annual-reporting/2025/aarsregnskap#issue-notes_missing";
  assert.equal(safeActionReturnPath(valid, "/"), valid);
  for (const invalid of ["https://evil.example", "//evil.example", "/admin", "/companies/x/annual-reporting/not-a-year", "javascript:alert(1)"]) {
    assert.equal(safeActionReturnPath(invalid, "/"), "/");
  }
});
```

- [ ] **Step 2: Run the test and confirm the missing-module failure**

Run: `node --experimental-strip-types --test tests/action_return.test.mjs`

Expected: FAIL with `ERR_MODULE_NOT_FOUND`.

- [ ] **Step 3: Implement the return-path allow-list**

```ts
const annualReturnPattern = /^\/companies\/[0-9a-f-]{36}\/annual-reporting\/\d{4}(?:\/(?:aksjonaerregisteroppgaven|aarsregnskap|skattemelding|review))?(?:#[a-z0-9_-]+)?$/i;

export function safeActionReturnPath(value: FormDataEntryValue | string | null | undefined, fallback = "/") {
  return typeof value === "string" && annualReturnPattern.test(value) ? value : fallback;
}
```

- [ ] **Step 4: Thread `returnTo` through annual-facing actions**

For each of `uploadDocument`, `generateRf1086Preview`, `confirmSimulatedRf1086Submission`, `addFilingOverride`, `inviteWorkspaceReviewer`, `addFilingReviewComment`, `acknowledgeFilingReviewComment`, `saveYearEndInterview`, `refreshAnnualReadinessSnapshots`, `requestFilingPackagePayment`, and `confirmAuthorityPermission`, capture the path once after reading `FormData`:

```ts
const returnTo = safeActionReturnPath(formData.get("returnTo"));
```

Replace only that action's successful tail:

```ts
revalidatePath(returnTo);
redirect(returnTo);
```

For public or internal errors in those actions, redirect to the same route with a bounded query parameter:

```ts
redirect(`${returnTo}?error=${encodePublicActionError(message)}`);
```

Keep authentication and missing-environment redirects at `/`; never reflect an unvalidated path.

- [ ] **Step 5: Run action-return, disclosure, security, and type checks**

Run: `node --experimental-strip-types --test tests/action_return.test.mjs tests/action_errors.test.mjs tests/security_step_up.test.mjs && npm run typecheck`

Expected: all tests PASS and TypeScript exits 0.

- [ ] **Step 6: Commit the action-routing slice**

```bash
git add app/lib/action-return.ts tests/action_return.test.mjs app/actions.ts
git commit -m "feat: return annual actions to their workspace"
```

---

### Task 4: Build the annual product shell and design-system CSS

**Files:**
- Create: `app/components/annual-workspace/AnnualWorkspaceShell.tsx`
- Create: `app/components/annual-workspace/annual-workspace.module.css`
- Create: `app/companies/[companyId]/annual-reporting/[incomeYear]/layout.tsx`
- Create: `app/companies/[companyId]/annual-reporting/[incomeYear]/loading.tsx`
- Create: `app/companies/[companyId]/annual-reporting/[incomeYear]/error.tsx`
- Create: `tests/annual_workspace_render.test.mjs`

**Interfaces:**
- Consumes: `AnnualWorkspaceViewModel` company, context, role, and child route content.
- Produces: labeled desktop/mobile navigation, company/year header, semantic main landmark, skeleton, and recoverable error boundary.

- [ ] **Step 1: Write failing source contracts for landmarks, labels, and forbidden patterns**

```js
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("annual shell uses labeled navigation and design-system guardrails", async () => {
  const source = await readFile("app/components/annual-workspace/AnnualWorkspaceShell.tsx", "utf8");
  const css = await readFile("app/components/annual-workspace/annual-workspace.module.css", "utf8");
  assert.match(source, /aria-label="Hovednavigasjon"/);
  assert.match(source, /Årsrapportering/);
  assert.match(source, /Handlinger/);
  assert.match(css, /#f7f8fa/i);
  assert.match(css, /:focus-visible/);
  assert.doesNotMatch(css, /linear-gradient|backdrop-filter|border-radius:\s*(?:2[0-9]|[3-9][0-9])px/i);
});
```

- [ ] **Step 2: Run the test and confirm the missing-file failure**

Run: `node --experimental-strip-types --test tests/annual_workspace_render.test.mjs`

Expected: FAIL with `ENOENT` for `AnnualWorkspaceShell.tsx`.

- [ ] **Step 3: Implement the shared shell**

```tsx
import Link from "next/link";
import type { ReactNode } from "react";
import { annualOverviewHref, type AnnualWorkspaceViewModel } from "../../lib/annual-workspace";
import styles from "./annual-workspace.module.css";

export function AnnualWorkspaceShell({ model, children }: { model: AnnualWorkspaceViewModel; children: ReactNode }) {
  const base = annualOverviewHref(model.context);
  return (
    <div className={styles.appShell}>
      <aside className={styles.sidebar}>
        <Link className={styles.brand} href="/">Talli</Link>
        <nav aria-label="Hovednavigasjon" className={styles.primaryNav}>
          <Link aria-current="page" href={base}>Årsrapportering</Link>
          <Link href="/?area=handlinger">Handlinger</Link>
          <Link href="/?area=transaksjoner">Transaksjoner</Link>
          <Link href="/?area=dokumenter">Dokumenter</Link>
          <Link href="/?area=selskap">Selskap</Link>
          <Link href="/?area=innstillinger">Innstillinger</Link>
        </nav>
      </aside>
      <div className={styles.workspace}>
        <header className={styles.workspaceHeader}>
          <div><strong>{model.company.name}</strong><span>{model.company.org_number}</span></div>
          <div><span>Inntektsår</span><strong>{model.context.incomeYear}</strong></div>
          <span className={styles.roleLabel}>{model.role === "owner" ? "Eier" : "Reviewer"}</span>
        </header>
        <main id="hovedinnhold" className={styles.main}>{children}</main>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Implement the route layout, skeleton, and error boundary**

The layout parses numeric year, loads the model once, and wraps child routes. `loading.tsx` renders the final header/row geometry with `aria-busy="true"`. `error.tsx` is a client component with `role="alert"`, the copy `Kunne ikke laste årsrapporteringen. Arbeidet ditt er ikke endret.`, and a `Prøv igjen` button calling `reset()`.

- [ ] **Step 5: Implement CSS Module primitives and responsive shell behavior**

Use the exact token declarations below at the module root and consume them throughout the file:

```css
.appShell {
  --canvas: #f7f8fa; --surface: #fff; --selection: #e8f3ef;
  --ink: #17202a; --muted: #617067; --line: #dfe5e8;
  --primary: #176b55; --primary-strong: #084838; --warning: #985713; --danger: #a73a34;
  min-height: 100vh; display: grid; grid-template-columns: 224px minmax(0, 1fr);
  background: var(--canvas); color: var(--ink);
}
.main { width: min(100%, 1280px); margin: 0 auto; padding: 32px; }
.primaryNav a { min-height: 44px; display: flex; align-items: center; padding: 10px 12px; border-radius: 8px; }
.primaryNav a[aria-current="page"] { background: var(--selection); color: var(--primary-strong); }
.appShell :focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; box-shadow: 0 0 0 3px rgb(23 107 85 / 22%); }
@media (max-width: 860px) { .appShell { grid-template-columns: 1fr; } .sidebar { position: static; } }
@media (prefers-reduced-motion: reduce) { .appShell *, .appShell *::before, .appShell *::after { scroll-behavior: auto !important; transition-duration: 0.01ms !important; } }
```

- [ ] **Step 6: Run render contracts and typecheck**

Run: `node --experimental-strip-types --test tests/annual_workspace_render.test.mjs && npm run typecheck`

Expected: all tests PASS and TypeScript exits 0.

- [ ] **Step 7: Commit the shell slice**

```bash
git add app/components/annual-workspace app/companies tests/annual_workspace_render.test.mjs
git commit -m "feat: add annual workspace shell"
```

---

### Task 5: Implement the obligation-led annual overview

**Files:**
- Create: `app/components/annual-workspace/AnnualOverview.tsx`
- Create: `app/components/annual-workspace/ObligationRow.tsx`
- Create: `app/components/annual-workspace/ContextRail.tsx`
- Create: `app/companies/[companyId]/annual-reporting/[incomeYear]/page.tsx`
- Modify: `app/components/annual-workspace/annual-workspace.module.css`
- Modify: `tests/annual_workspace_render.test.mjs`

**Interfaces:**
- Consumes: `AnnualWorkspaceViewModel` from the route layout/loader.
- Produces: one `Neste steg`, exactly three semantic obligation rows, deadline/document/reviewer context, and no numeric progress unless backed by explicit persisted checks.

- [ ] **Step 1: Add failing overview contracts**

```js
test("overview leads with one next action and semantic obligation rows", async () => {
  const overview = await readFile("app/components/annual-workspace/AnnualOverview.tsx", "utf8");
  const row = await readFile("app/components/annual-workspace/ObligationRow.tsx", "utf8");
  assert.match(overview, /Neste steg/);
  assert.match(overview, /model\.obligations\.map/);
  assert.match(row, /data-status=/);
  assert.match(row, /aria-label=.*status/i);
  assert.doesNotMatch(overview, /metric|KPI|hero/i);
});
```

- [ ] **Step 2: Run the test and confirm the missing-file failure**

Run: `node --experimental-strip-types --test tests/annual_workspace_render.test.mjs`

Expected: FAIL with `ENOENT` for `AnnualOverview.tsx`.

- [ ] **Step 3: Implement the overview composition**

```tsx
import Link from "next/link";
import type { AnnualWorkspaceViewModel } from "../../lib/annual-workspace";
import { ContextRail } from "./ContextRail";
import { ObligationRow } from "./ObligationRow";
import styles from "./annual-workspace.module.css";

export function AnnualOverview({ model }: { model: AnnualWorkspaceViewModel }) {
  return (
    <div className={styles.overviewLayout}>
      <section aria-labelledby="annual-title">
        <header className={styles.pageHeader}>
          <div><h1 id="annual-title">Årsrapportering</h1><p>{model.company.name} · {model.context.incomeYear}</p></div>
        </header>
        <section aria-labelledby="next-action-title" className={styles.nextAction}>
          <div><h2 id="next-action-title">Neste steg</h2><p>Vi anbefaler handlingen som løser det viktigste åpne punktet.</p></div>
          <Link className={styles.primaryButton} href={model.nextAction.href}>{model.nextAction.label}</Link>
        </section>
        <div className={styles.obligationList}>
          {model.obligations.map((obligation) => <ObligationRow key={obligation.obligation} obligation={obligation} />)}
        </div>
        <p className={styles.flowHint}>Du kan åpne pliktene i valgfri rekkefølge når avhengighetene er oppfylt.</p>
      </section>
      <ContextRail model={model} />
    </div>
  );
}
```

- [ ] **Step 4: Implement semantic obligation rows and context rail**

`ObligationRow` renders a heading link, owner-level description from an exhaustive obligation record, status text plus icon, deadline, concise open-point count, and one action. `ContextRail` renders the nearest three deadlines, five most recent linked documents, and five latest review comments with progressive `Se alle` links. Neither component nests cards.

- [ ] **Step 5: Bind the overview route to the loaded model**

```tsx
import { AnnualOverview } from "../../../../components/annual-workspace/AnnualOverview";
import { loadAnnualWorkspace } from "../../../../lib/annual-workspace-server";

export default async function AnnualReportingPage({ params }) {
  const { companyId, incomeYear } = await params;
  const loaded = await loadAnnualWorkspace({ companyId, incomeYear: Number(incomeYear) });
  return <AnnualOverview model={loaded.model} />;
}
```

- [ ] **Step 6: Run focused tests and typecheck**

Run: `npm run test:annual-workspace && npm run typecheck`

Expected: all annual-workspace tests PASS and TypeScript exits 0.

- [ ] **Step 7: Commit the overview slice**

```bash
git add app/components/annual-workspace app/companies tests/annual_workspace_render.test.mjs
git commit -m "feat: add obligation-led annual overview"
```

---

### Task 6: Implement shared obligation pages and reviewer context

**Files:**
- Create: `app/components/annual-workspace/ObligationWorkspace.tsx`
- Create: `app/companies/[companyId]/annual-reporting/[incomeYear]/[obligation]/page.tsx`
- Modify: `app/components/annual-workspace/annual-workspace.module.css`
- Modify: `tests/annual_workspace_render.test.mjs`

**Interfaces:**
- Consumes: `loaded.model`, persisted records, existing form actions, and a validated `AuthorityObligation` route segment.
- Produces: one shared obligation template with readiness, evidence, comments, role-aware controls, and safe `returnTo` fields.

- [ ] **Step 1: Add failing contracts for route validation, issue anchors, and role-aware controls**

```js
test("obligation workspace anchors issues and carries safe returns", async () => {
  const source = await readFile("app/components/annual-workspace/ObligationWorkspace.tsx", "utf8");
  const route = await readFile("app/companies/[companyId]/annual-reporting/[incomeYear]/[obligation]/page.tsx", "utf8");
  assert.match(source, /id={`issue-\$\{issue\.code\}`}/);
  assert.match(source, /name="returnTo"/);
  assert.match(source, /model\.role === "owner"/);
  assert.match(route, /validateAuthorityObligation/);
});
```

- [ ] **Step 2: Run the test and confirm the missing-file failure**

Run: `node --experimental-strip-types --test tests/annual_workspace_render.test.mjs`

Expected: FAIL with `ENOENT` for `ObligationWorkspace.tsx`.

- [ ] **Step 3: Implement the shared obligation template**

```tsx
export function ObligationWorkspace({ model, obligation, records }) {
  const view = model.obligations.find((item) => item.obligation === obligation);
  if (!view) return null;
  const issues = [...view.hardBlocks, ...view.warnings, ...view.acceptedWarnings];
  return (
    <div className={styles.obligationLayout}>
      <section>
        <header className={styles.pageHeader}><h1>{view.label}</h1><p>{obligationDescription[obligation]}</p></header>
        {view.unsupported ? <UnsupportedFilingNotice message={view.hardBlocks[0]?.message} /> : null}
        <section aria-labelledby="readiness-title">
          <h2 id="readiness-title">Dette må være klart</h2>
          <div className={styles.readinessList}>
            {issues.map((issue) => (
              <article id={`issue-${issue.code}`} key={`${issue.source}-${issue.code}`} className={styles.readinessRow}>
                <StatusIcon level={issue.level} accepted={issue.accepted} />
                <div><h3>{issueTitle(issue.code)}</h3><p>{issue.message}</p></div>
                <ResolutionLink issue={issue} context={model.context} />
              </article>
            ))}
          </div>
        </section>
        <EvidenceSection obligation={obligation} records={records} />
      </section>
      <ReviewerSection model={model} obligation={obligation} records={records} />
    </div>
  );
}
```

Use exhaustive records for `obligationDescription`, `issueTitle`, and issue-source resolution routes. Unknown issues display the persisted public message and link to the overview; never expose raw provider diagnostics.

- [ ] **Step 4: Add role-aware forms backed by existing actions**

Owner forms render only when `model.role === "owner"`. Reviewer comment forms render for `reviewer` and owner where existing server authorization permits. Every form includes:

```tsx
<input type="hidden" name="returnTo" value={view.href} />
<input type="hidden" name="companyId" value={model.context.companyId} />
<input type="hidden" name="incomeYear" value={model.context.incomeYear} />
```

Reuse `generateRf1086Preview`, `addFilingReviewComment`, `acknowledgeFilingReviewComment`, `uploadDocument`, `saveYearEndInterview`, `refreshAnnualReadinessSnapshots`, and `confirmAuthorityPermission`. Do not add UI-only state mutations.

- [ ] **Step 5: Implement the dynamic obligation route**

```tsx
import { notFound } from "next/navigation";
import { validateAuthorityObligation } from "../../../../../lib/authority-permission";
import { loadAnnualWorkspace } from "../../../../../lib/annual-workspace-server";
import { ObligationWorkspace } from "../../../../../components/annual-workspace/ObligationWorkspace";

export default async function ObligationPage({ params }) {
  const { companyId, incomeYear, obligation: raw } = await params;
  let obligation;
  try { obligation = validateAuthorityObligation(raw); } catch { notFound(); }
  const loaded = await loadAnnualWorkspace({ companyId, incomeYear: Number(incomeYear) });
  return <ObligationWorkspace model={loaded.model} obligation={obligation} records={loaded.records} />;
}
```

- [ ] **Step 6: Run annual, review, document, authority, and type checks**

Run: `npm run test:annual-workspace && npm run test:review && npm run test:documents && npm run test:authority && npm run typecheck`

Expected: all tests PASS and TypeScript exits 0.

- [ ] **Step 7: Commit the obligation slice**

```bash
git add app/components/annual-workspace app/companies tests/annual_workspace_render.test.mjs
git commit -m "feat: add annual obligation workspaces"
```

---

### Task 7: Implement final review, submission, and durable outcomes

**Files:**
- Create: `app/components/annual-workspace/SubmissionReview.tsx`
- Create: `app/companies/[companyId]/annual-reporting/[incomeYear]/review/page.tsx`
- Modify: `app/components/annual-workspace/annual-workspace.module.css`
- Modify: `tests/annual_workspace_render.test.mjs`

**Interfaces:**
- Consumes: obligation view models, persisted review comments, authority permissions, billing state, MFA-backed existing actions, and filing submissions.
- Produces: explicit gate summary, owner confirmation, pending/idempotent state, receipt archive, and retry/escalation presentation.

- [ ] **Step 1: Add failing contracts for gates, duplicate prevention, receipts, and non-color statuses**

```js
test("submission review renders gates and durable outcomes", async () => {
  const source = await readFile("app/components/annual-workspace/SubmissionReview.tsx", "utf8");
  assert.match(source, /Innsendingsrett/);
  assert.match(source, /Betaling/);
  assert.match(source, /Review/);
  assert.match(source, /receipt_id/);
  assert.match(source, /aria-live="polite"/);
  assert.match(source, /disabled=.*pending/);
});
```

- [ ] **Step 2: Run the test and confirm the missing-file failure**

Run: `node --experimental-strip-types --test tests/annual_workspace_render.test.mjs`

Expected: FAIL with `ENOENT` for `SubmissionReview.tsx`.

- [ ] **Step 3: Implement the gate and outcome model in the component**

Render one row each for readiness, unresolved hard review comments, authority permission, billing, and step-up requirement. Each row has explicit text, icon, consequence, and resolution link. Derive `pending` only from persisted submission statuses; derive `submitted` only from a persisted `receipt_id`.

```tsx
const pending = submissions.some((item) => item.status === "pending" && !item.receipt_id);
const completed = submissions.find((item) => item.receipt_id);
return (
  <section aria-labelledby="review-title">
    <h1 id="review-title">Gjennomgang og innsending</h1>
    <GateList gates={gates} />
    <div aria-live="polite">
      {completed ? <ReceiptSummary submission={completed} /> : null}
      {pending ? <PendingSubmission submission={submissions.find((item) => item.status === "pending")} /> : null}
    </div>
    {model.role === "owner" && selectedPreview && allGatesOpen ? (
      <form action={confirmSimulatedRf1086Submission}>
        <input type="hidden" name="returnTo" value={annualReviewHref(model.context)} />
        <input type="hidden" name="previewId" value={selectedPreview.id} />
        <ConfirmationFields company={model.company} year={model.context.incomeYear} />
        <button disabled={pending} className={styles.primaryButton}>Send inn</button>
      </form>
    ) : null}
  </section>
);
```

Where production adapters are sealed or only simulation is implemented, label the actual mode exactly and retain `preProductionDirectFilingCopy`. Never display a production-success claim for a simulation receipt.

- [ ] **Step 4: Bind the review route and recoverable errors**

The review route loads the same company/year records and passes only scoped previews, submissions, comments, authority permissions, and billing state. It renders retry links for retryable failures and an accountant/support escalation for terminal or unsupported failures.

- [ ] **Step 5: Run submission, billing, security, release-gate, and type checks**

Run: `npm run test:annual-workspace && npm run test:rf1086:submission && npm run test:billing && npm run test:mfa && npm run test:filing-release-gate && npm run typecheck`

Expected: all tests PASS and TypeScript exits 0.

- [ ] **Step 6: Commit the review/submission slice**

```bash
git add app/components/annual-workspace app/companies tests/annual_workspace_render.test.mjs
git commit -m "feat: add annual review and submission surface"
```

---

### Task 8: Migrate the root entry point and complete responsive/accessibility/browser verification

**Files:**
- Modify: `app/page.tsx`
- Modify: `app/globals.css`
- Modify: `tests/launch_copy.test.mjs`
- Create: `tests/annual_workspace_routes.test.mjs`
- Create: `tests/browser_annual_workspace.mjs`
- Modify: `package.json`

**Interfaces:**
- Consumes: the complete new workspace routes.
- Produces: a root entry point into the selected company's latest year, removal of duplicate annual presentation from the prototype, production design tokens, and end-to-end evidence.

- [ ] **Step 1: Write failing root-route and copy contracts**

```js
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("root links authenticated owners into the annual workspace", async () => {
  const source = await readFile("app/page.tsx", "utf8");
  assert.match(source, /annualOverviewHref/);
  assert.match(source, /Åpne årsrapportering/);
});

test("annual routes retain launch-boundary language", async () => {
  const review = await readFile("app/components/annual-workspace/SubmissionReview.tsx", "utf8");
  assert.match(review, /preProductionDirectFilingCopy/);
  assert.match(review, /requiredNonAffiliationCopy/);
});
```

- [ ] **Step 2: Run route contracts and confirm the root-link failure**

Run: `node --experimental-strip-types --test tests/annual_workspace_routes.test.mjs tests/launch_copy.test.mjs`

Expected: FAIL because `app/page.tsx` does not yet use `annualOverviewHref`.

- [ ] **Step 3: Add the authenticated annual-workspace entry point**

After company/year selection on the root page, render:

```tsx
<a className="primaryButton" href={annualOverviewHref({ companyId: primaryCompanyId, incomeYear: primaryIncomeYear })}>
  Åpne årsrapportering
</a>
```

Remove the duplicated annual readiness, year-end, deadline, review, authority, and simulated-submission presentation from `app/page.tsx` only after the new routes render the same persisted records and actions. Keep everyday holding actions accessible from their existing root anchors until their own separate-route migration is designed.

- [ ] **Step 4: Align global tokens with `DESIGN.md`**

```css
:root {
  color-scheme: light;
  --background: #f7f8fa; --foreground: #17202a; --muted: #617067;
  --line: #dfe5e8; --soft: #f7f8fa; --panel: #ffffff;
  --accent: #176b55; --accent-strong: #084838;
  --amber: #985713; --red: #a73a34; --ink: #17202a;
}
```

Remove the brand-mark and meter gradients, repeated eyebrow styling, marketing-scale `h1` rules, and the static panel's wide shadow. Preserve the legacy everyday-action layout until its future migration, but make it consume the same neutral canvas and control states.

- [ ] **Step 5: Add the authenticated Playwright flow**

```js
import { chromium } from "playwright";
import assert from "node:assert/strict";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
await page.goto(process.env.TALLI_BASE_URL ?? "http://127.0.0.1:3000");
await page.getByLabel("E-post").first().fill(process.env.TALLI_TEST_EMAIL ?? "owner@example.no");
await page.getByLabel("Passord").first().fill(process.env.TALLI_TEST_PASSWORD ?? "test-password-123");
await page.getByRole("button", { name: "Logg inn" }).click();
await page.getByRole("link", { name: "Åpne årsrapportering" }).click();
await page.getByRole("heading", { name: "Årsrapportering" }).waitFor();
assert.equal(await page.locator("[data-obligation]").count(), 3);
await page.getByRole("link", { name: /Fortsett|Løs|Åpne/ }).first().focus();
assert.equal(await page.evaluate(() => document.activeElement?.matches(":focus-visible")), true);
await page.setViewportSize({ width: 390, height: 844 });
assert.equal(await page.locator("body").evaluate((body) => body.scrollWidth <= window.innerWidth), true);
await browser.close();
```

Use the existing local Supabase rehearsal credentials/environment in CI; do not commit real credentials. Extend the flow with reviewer login when the fixture provides one, then assert the same route renders read-only owner actions and an available comment form.

- [ ] **Step 6: Add browser and focused scripts**

```json
"test:browser-annual-workspace": "node tests/browser_annual_workspace.mjs",
"test:annual-workspace": "node --experimental-strip-types --test tests/annual_workspace_view_model.test.mjs tests/annual_workspace_scope.test.mjs tests/action_return.test.mjs tests/annual_workspace_render.test.mjs tests/annual_workspace_routes.test.mjs"
```

- [ ] **Step 7: Run the focused workspace verification**

Run: `npm run test:annual-workspace && npm run test:review && npm run test:documents && npm run test:authority && npm run test:billing && npm run test:mfa && npm run test:filing-release-gate && npm run test:launch-copy && npm run typecheck`

Expected: all tests PASS and TypeScript exits 0.

- [ ] **Step 8: Run production build and browser verification**

Run: `npm run build && npm run test:browser-annual-workspace`

Expected: Next.js build exits 0; the authenticated owner flow finds exactly three obligations, keyboard focus is visible, and 390px viewport has no horizontal body overflow.

- [ ] **Step 9: Run the complete release suite**

Run: `npm run test:release`

Expected: Python tests, launch rehearsal, security tests, typecheck, build, and packaging all PASS with zero failures.

- [ ] **Step 10: Inspect the final surface at three widths**

Open the annual overview, each obligation page, and review page at 1440×1000, 860×900, and 390×844. Confirm: one dominant action, readable Norwegian wrapping, no clipped popovers, no color-only states, no nested/repeated card grid, no cream/gradient/ghost-shadow regressions, and preserved access to unaffected filings when one obligation is unsupported.

- [ ] **Step 11: Commit the migration and verification slice**

```bash
git add app/page.tsx app/globals.css app/components/annual-workspace app/companies tests package.json
git commit -m "feat: launch annual reporting workspace"
```

---

## Final acceptance checklist

- [ ] The overview contains exactly three launch obligations in the approved order.
- [ ] `Neste steg` links to the exact persisted unresolved requirement.
- [ ] Owners can open available obligations non-linearly.
- [ ] Unsupported cases block only their affected filing and explain accountant escalation.
- [ ] Reviewers use the same routes with server-authorized role-aware controls.
- [ ] All actions return safely to the originating workspace route.
- [ ] Readiness, warnings, submissions, receipts, permissions, billing, and comments come from persisted backend records.
- [ ] Submission pending state prevents duplicate submission.
- [ ] Simulation and production language remain factually distinct.
- [ ] Desktop, tablet, and mobile layouts are usable without horizontal body overflow.
- [ ] Keyboard, focus, status announcements, contrast, non-color cues, and reduced motion meet WCAG 2.2 AA.
- [ ] Root no longer duplicates annual readiness, review, deadline, authority, and submission presentation.
- [ ] Everyday holding actions remain accessible as separate destinations/anchors.
- [ ] `npm run test:release` passes with zero failures.
