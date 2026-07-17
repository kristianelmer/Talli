# General Customer Agreement and DPA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every Talli business customer the same explicit, versioned Business Terms and DPA acceptance when creating a company workspace, while keeping beta differences in plan and capability state.

**Architecture:** Canonical Norwegian legal documents live in the application. Each version has an expected SHA-256 digest pinned in the registry; module initialization hashes the exact public copy and fails tests/builds on drift. A service-role-only, security-definer Supabase function creates the company, owner membership, immutable agreement acceptance, and audit event atomically after the authenticated Server Action validates submitted versions and digests before Brønnøysund lookup. A second service-role-only append function records exact current re-acceptance for existing companies after the owner layout detects missing current evidence. Both controls validate explicit assent before privileged work; browser clients cannot call either function. This service-access gate does not enable filing, billing, authority, or entitlements.

**Tech Stack:** Next.js 16 App Router and Server Actions, React 19, TypeScript 6, Node test runner, Supabase/Postgres migrations and RLS.

## Global Constraints

- The customer agreement is named **Talli Business Terms** (`Brukervilkår for bedriftskunder`) in the product.
- Account signup does not constitute company acceptance; acceptance occurs at Brønnøysund-verified company creation.
- Business Terms and DPA are separate, versioned documents accepted in one company-onboarding action.
- The authority/acceptance control is required, unchecked by default, and server validated.
- Beta is a plan and capability state; it does not use a separate contract or acceptance experience.
- The Privacy Notice is disclosed but is not a contract the customer must accept.
- No DocuSign, BankID, payment, production filing, or external legal approval is introduced.
- ELMER WELFIS, org.nr. 930 835 978 remains the current supplier until a separately approved entity migration.
- Acceptance never grants a production filing entitlement or bypasses an existing launch, authority, security, or restore gate.
- Existing companies receive no fabricated acceptance or silent backfill.
- User-facing copy is Norwegian-first; implementation, tests, and operator-only language may be English.
- Production code follows red-green-refactor: every behavioral change begins with a failing test.
- Version `2026-07-17` is retained only for the documented pre-release state in
  which no released customer acceptance exists.
- Pinned digests: Business Terms
  `f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543`;
  DPA `083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c`.
- The server rejects any submitted version or digest mismatch before
  Brønnøysund lookup or service-role work and sends only trusted registry
  metadata to the unchanged 19-key RPC payload.

---

### Task 1: Canonical, versioned Business Terms and DPA

**Files:**
- Create: `app/lib/customer-agreements.ts`
- Create: `app/databehandleravtale/page.tsx`
- Modify: `app/lib/copy.ts`
- Modify: `app/components/LegalPage.tsx`
- Modify: `app/vilkar/page.tsx`
- Create: `tests/customer_agreements.test.mjs`
- Modify: `package.json`

**Interfaces:**
- Consumes: `ownerCopy.legal.terms` and the new `ownerCopy.legal.dpa` as canonical public document content.
- Produces: pinned `currentCustomerAgreements`, `customerAgreementAuthorityStatementVersion`, `assertCanonicalAgreementContent`, and digest-aware `assertCurrentCustomerAgreementForm(input)` for Task 3.

- [ ] **Step 1: Write failing document and registry tests**

Create `tests/customer_agreements.test.mjs` with tests that assert the exact version/path/pinned-digest pairs, independently hash the exact public copy, mutate canonical content and require deterministic mismatch failure, and require missing, false, stale-version, or stale-digest form values to throw the stale-agreement message.

```js
import assert from "node:assert/strict";
import test from "node:test";

import {
  assertCurrentCustomerAgreementForm,
  currentCustomerAgreements,
  customerAgreementAuthorityStatementVersion,
} from "../app/lib/customer-agreements.ts";
import { ownerCopy } from "../app/lib/copy.ts";

test("publishes separate current Business Terms and DPA records", () => {
  assert.deepEqual(Object.keys(currentCustomerAgreements), ["businessTerms", "dpa"]);
  assert.equal(currentCustomerAgreements.businessTerms.version, "2026-07-17");
  assert.equal(currentCustomerAgreements.businessTerms.path, "/vilkar");
  assert.equal(currentCustomerAgreements.dpa.version, "2026-07-17");
  assert.equal(currentCustomerAgreements.dpa.path, "/databehandleravtale");
  assert.match(currentCustomerAgreements.businessTerms.contentSha256, /^[a-f0-9]{64}$/u);
  assert.match(currentCustomerAgreements.dpa.contentSha256, /^[a-f0-9]{64}$/u);
  assert.equal(customerAgreementAuthorityStatementVersion, "authority-v1");
});

test("uses one general supplier contract for beta and live plans", () => {
  const text = JSON.stringify([ownerCopy.legal.terms, ownerCopy.legal.dpa]);
  assert.match(text, /ELMER WELFIS/u);
  assert.match(text, /930 835 978/u);
  assert.match(text, /planen og funksjonene som vises i tjenesten/iu);
  assert.match(text, /databehandler/iu);
  assert.doesNotMatch(ownerCopy.legal.terms.intro, /ved å bruke/iu);
});

test("rejects absent and stale company agreement assent", () => {
  const current = {
    agreementAccepted: "accepted",
    businessTermsVersion: "2026-07-17",
    businessTermsSha256: "f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543",
    dpaVersion: "2026-07-17",
    dpaSha256: "083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c",
  };
  assert.doesNotThrow(() => assertCurrentCustomerAgreementForm(current));
  assert.throws(
    () => assertCurrentCustomerAgreementForm({ ...current, agreementAccepted: "" }),
    /Du må bekrefte fullmakt og godta avtalevilkårene/u,
  );
  assert.throws(
    () => assertCurrentCustomerAgreementForm({ ...current, dpaVersion: "2026-07-16" }),
    /Avtalevilkårene er oppdatert/u,
  );
});
```

Add `"test:customer-agreements": "node --experimental-strip-types --test tests/customer_agreements.test.mjs"` to `package.json`.

- [ ] **Step 2: Run the test and verify RED**

Run: `npm run test:customer-agreements`

Expected: FAIL because `app/lib/customer-agreements.ts` does not exist.

- [ ] **Step 3: Implement canonical document metadata and validation**

Create `app/lib/customer-agreements.ts` as a server-compatible TypeScript module using `createHash` from `node:crypto`. Pin the expected digest beside each version. Serialize each exact public document with `JSON.stringify` during module initialization, compute its digest, and throw `customer_agreement_content_digest_mismatch:<kind>` when it differs from the pinned value. `assertCurrentCustomerAgreementForm` must compare both submitted versions and both submitted digests with the registry.

```ts
import { createHash } from "node:crypto";

import { ownerCopy } from "./copy";

export const customerAgreementAuthorityStatementVersion = "authority-v1" as const;

const currentAgreementMetadata = {
  business_terms: {
    version: "2026-07-17",
    effectiveDate: "2026-07-17",
    contentSha256: "f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543",
  },
  dpa: {
    version: "2026-07-17",
    effectiveDate: "2026-07-17",
    contentSha256: "083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c",
  },
} as const;

function contractDocument(
  kind: "business_terms" | "dpa",
  path: "/vilkar" | "/databehandleravtale",
  content: typeof ownerCopy.legal.terms,
) {
  const metadata = currentAgreementMetadata[kind];
  const actualSha256 = createHash("sha256").update(JSON.stringify(content), "utf8").digest("hex");
  if (actualSha256 !== metadata.contentSha256) {
    throw new Error(`customer_agreement_content_digest_mismatch:${kind}`);
  }
  return {
    kind,
    version: metadata.version,
    effectiveDate: metadata.effectiveDate,
    path,
    contentSha256: actualSha256,
  } as const;
}

export const currentCustomerAgreements = {
  businessTerms: contractDocument("business_terms", "/vilkar", ownerCopy.legal.terms),
  dpa: contractDocument("dpa", "/databehandleravtale", ownerCopy.legal.dpa),
} as const;

export function assertCurrentCustomerAgreementForm(input: {
  agreementAccepted: string;
  businessTermsVersion: string;
  businessTermsSha256: string;
  dpaVersion: string;
  dpaSha256: string;
}) {
  if (input.agreementAccepted !== "accepted") {
    throw new Error("Du må bekrefte fullmakt og godta avtalevilkårene.");
  }
  if (
    input.businessTermsVersion !== currentCustomerAgreements.businessTerms.version ||
    input.businessTermsSha256 !== currentCustomerAgreements.businessTerms.contentSha256 ||
    input.dpaVersion !== currentCustomerAgreements.dpa.version ||
    input.dpaSha256 !== currentCustomerAgreements.dpa.contentSha256
  ) {
    throw new Error("Avtalevilkårene er oppdatert. Les dem og bekreft på nytt.");
  }
}
```

Update `ownerCopy.legal.terms` to `Brukervilkår for bedriftskunder`, replace passive-use assent with explicit company acceptance, retain supported-scope, customer-review, direct-filing, support, liability, termination, and Norwegian-law boundaries, incorporate the DPA by reference, and state that price and availability follow the plan and capabilities displayed in the service. Add `ownerCopy.legal.dpa` with Article 28 sections for roles, instructions, processing details, confidentiality, security, subprocessors, transfers, assistance, breach notice, audit, and return/deletion. Do not state unverified provider regions, certifications, or transfer bases as current facts.

Extend `LegalPage` with optional `version` and `effectiveDate` props and render `Versjon {version} · Gjelder fra {effectiveDate}`. Pass the current registry metadata from `/vilkar` and create `/databehandleravtale` using the same component and DPA metadata.

- [ ] **Step 4: Run focused tests and typecheck for GREEN**

Run: `npm run test:customer-agreements && npm run typecheck`

Expected: both commands exit 0 with all tests passing and no TypeScript diagnostics.

- [ ] **Step 5: Commit the document slice**

```bash
git add app/lib/customer-agreements.ts app/lib/copy.ts app/components/LegalPage.tsx app/vilkar/page.tsx app/databehandleravtale/page.tsx tests/customer_agreements.test.mjs package.json
git commit -m "feat: publish versioned business terms and dpa"
```

### Task 2: Immutable acceptance schema and atomic company creation

**Files:**
- Create: `supabase/migrations/20260717110000_customer_agreement_acceptances.sql`
- Create: `supabase/rollback/customer_agreement_acceptances.sql`
- Create: `tests/customer_agreement_schema.test.mjs`
- Create: `tests/customer_agreement_database_runtime.test.mjs`
- Modify: `package.json`

**Interfaces:**
- Consumes: company identity and current agreement evidence supplied by Task 3.
- Produces: service-role-only RPC `public.create_company_workspace_with_acceptance(uuid, text, text, text, text, text, text, text, text, text, date, text, text, text, date, text, text, text, text)` returning `uuid`.

- [ ] **Step 1: Write the failing schema contract test**

Create `tests/customer_agreement_schema.test.mjs` that reads the migration and asserts:

```js
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const sql = readFileSync(
  new URL("../supabase/migrations/20260717110000_customer_agreement_acceptances.sql", import.meta.url),
  "utf8",
);

test("stores immutable company-scoped agreement evidence", () => {
  assert.match(sql, /create table public\.customer_agreement_acceptances/iu);
  assert.match(sql, /business_terms_sha256[^\n]+\^\[a-f0-9\]\{64\}\$/iu);
  assert.match(sql, /dpa_sha256[^\n]+\^\[a-f0-9\]\{64\}\$/iu);
  assert.match(sql, /acceptance_method[^\n]+in_app_clickwrap/iu);
  assert.match(sql, /prevent_customer_agreement_acceptance_mutation/iu);
  assert.match(sql, /before update or delete/iu);
  assert.match(sql, /enable row level security/iu);
  assert.match(sql, /company members can read customer agreement acceptances/iu);
  assert.doesNotMatch(sql, /grant\s+(insert|update|delete)[^;]+customer_agreement_acceptances[^;]+authenticated/iu);
});

test("creates company, owner, acceptance, and audit evidence atomically", () => {
  const fn = sql.match(/create or replace function public\.create_company_workspace_with_acceptance[\s\S]+?\n\$\$;/iu)?.[0] ?? "";
  assert.match(fn, /auth\.role\(\).*service_role/iu);
  assert.match(fn, /p_actor_id is null/iu);
  assert.match(fn, /p_entity_type is distinct from 'AS'/iu);
  assert.match(fn, /insert into public\.companies/iu);
  assert.match(fn, /insert into public\.company_memberships/iu);
  assert.match(fn, /insert into public\.customer_agreement_acceptances/iu);
  assert.match(fn, /insert into public\.audit_events/iu);
  assert.doesNotMatch(fn, /production_pilot_entitlements/iu);
  assert.match(sql, /revoke all on function public\.create_company_workspace_with_acceptance[\s\S]+from public, anon/iu);
  assert.doesNotMatch(sql, /grant execute on function public\.create_company_workspace_with_acceptance[\s\S]+to authenticated/iu);
  assert.match(sql, /grant execute on function public\.create_company_workspace_with_acceptance[\s\S]+to service_role/iu);
});
```

Add `"test:customer-agreement-schema": "node --test tests/customer_agreement_schema.test.mjs"` to `package.json`.
Add the runtime test to the existing `test:supabase` command so the normal local
database gate always proves that authenticated and anonymous clients cannot call
the RPC, service role cannot update/delete/truncate/directly insert evidence,
null acceptance values fail, successful service-role creation writes all four
records atomically, and a failed call writes none.

- [ ] **Step 2: Run the schema test and verify RED**

Run: `npm run test:customer-agreement-schema`

Expected: FAIL because the migration does not exist.

- [ ] **Step 3: Implement the append-only table, RLS, RPC, grants, and rollback**

Create the migration with the exact evidence columns from the design. Use `check (business_terms_sha256 ~ '^[a-f0-9]{64}$')` and the equivalent DPA check. Add a `before update or delete` trigger using a dedicated function that always raises `customer_agreement_acceptance_is_immutable`. Use `on delete restrict` for acceptance evidence. Enable RLS; grant authenticated users only `select`; permit reads only where an accepted company membership exists. Revoke every table privilege from service role and grant it only `select`, so it cannot update, delete, truncate, or directly insert evidence.

Implement the named 19-argument RPC. It must:

```sql
declare
  v_actor_id uuid := p_actor_id;
  v_company_id uuid;
  v_now timestamptz := now();
begin
  if auth.role() is distinct from 'service_role' then raise exception 'service_role_required'; end if;
  if v_actor_id is null then raise exception 'authenticated_actor_required'; end if;
  if p_org_number !~ '^[0-9]{9}$' then raise exception 'invalid_org_number'; end if;
  if p_entity_type is distinct from 'AS' then raise exception 'unsupported_entity_type'; end if;
  if p_acceptance_method is distinct from 'in_app_clickwrap' then raise exception 'invalid_acceptance_method'; end if;
  if p_authority_statement_version is distinct from 'authority-v1' then raise exception 'invalid_authority_statement'; end if;
  if p_business_terms_sha256 !~ '^[a-f0-9]{64}$' or p_dpa_sha256 !~ '^[a-f0-9]{64}$' then
    raise exception 'invalid_contract_digest';
  end if;

  insert into public.companies (..., created_by, identity_confirmed_at, identity_locked_at)
  values (..., v_actor_id, v_now, v_now)
  returning id into v_company_id;
  insert into public.company_memberships (company_id, user_id, role, accepted_at)
  values (v_company_id, v_actor_id, 'owner', v_now);
  insert into public.customer_agreement_acceptances (...)
  values (..., v_actor_id, ..., 'in_app_clickwrap', v_now);
  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (v_company_id, v_actor_id, 'company', 'workspace_created', 'Selskapsarbeidsflate opprettet med dokumentert avtaleaksept.');
  return v_company_id;
end;
```

Use one PL/pgSQL function transaction; do not catch exceptions inside it. Revoke function execution from `public`, `anon`, and `authenticated`, and grant it only to `service_role`. Revoke all table privileges from all API roles, then grant authenticated tenant-scoped `select` and service-role `select` only. The rollback must revoke RPC access before dropping the function, policy, trigger, trigger function, and table, and must remain safe when the table is already absent.

- [ ] **Step 4: Run schema/grant tests for GREEN**

Run: `npm run test:customer-agreement-schema && npm run test:supabase-grants`

Expected: both commands exit 0.

Then run `npm run test:supabase:local` and require the committed runtime test to
pass alongside the existing local database and owner-browser suites.

- [ ] **Step 5: Commit the schema slice**

```bash
git add supabase/migrations/20260717110000_customer_agreement_acceptances.sql supabase/rollback/customer_agreement_acceptances.sql tests/customer_agreement_schema.test.mjs tests/customer_agreement_database_runtime.test.mjs package.json docs/superpowers/specs/2026-07-17-general-customer-agreement-dpa-design.md docs/superpowers/plans/2026-07-17-general-customer-agreement-dpa.md
git commit -m "feat: persist immutable customer agreement acceptance"
```

### Task 3: Bind explicit acceptance to company onboarding

**Files:**
- Modify: `app/actions.ts`
- Modify: `app/(owner)/workspace/page.tsx`
- Modify: `app/lib/copy.ts`
- Create: `tests/customer_agreement_actions.test.mjs`
- Modify: `package.json`

**Interfaces:**
- Consumes: Task 1 registry/validator and Task 2 RPC.
- Produces: one self-service company-creation experience that creates nothing without current explicit agreement acceptance.

- [ ] **Step 1: Write failing action and UI contract tests**

Create `tests/customer_agreement_actions.test.mjs` to read the action and workspace sources and assert:

```js
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const actions = readFileSync(new URL("../app/actions.ts", import.meta.url), "utf8");
const workspace = readFileSync(new URL("../app/(owner)/workspace/page.tsx", import.meta.url), "utf8");

test("company creation requires current explicit company assent", () => {
  assert.match(actions, /assertCurrentCustomerAgreementForm/iu);
  assert.match(actions, /formString\(formData, "agreementAccepted"\)/iu);
  assert.match(actions, /formString\(formData, "businessTermsVersion"\)/iu);
  assert.match(actions, /formString\(formData, "businessTermsSha256"\)/iu);
  assert.match(actions, /formString\(formData, "dpaVersion"\)/iu);
  assert.match(actions, /formString\(formData, "dpaSha256"\)/iu);
  assert.match(actions, /\.rpc\("create_company_workspace_with_acceptance"/iu);
  assert.doesNotMatch(actions.match(/export async function createWorkspace[\s\S]+?\n}\n/iu)?.[0] ?? "", /\.from\("companies"\)\.insert/iu);
});

test("workspace creation shows an unchecked authority and agreement control", () => {
  assert.match(workspace, /name="agreementAccepted"/iu);
  assert.match(workspace, /type="checkbox"/iu);
  assert.match(workspace, /value="accepted"/iu);
  assert.match(workspace, /required/iu);
  assert.doesNotMatch(workspace, /defaultChecked|checked=\{true\}/iu);
  assert.match(workspace, /href="\/vilkar"/iu);
  assert.match(workspace, /href="\/databehandleravtale"/iu);
  assert.match(workspace, /businessTermsVersion/iu);
  assert.match(workspace, /businessTermsSha256/iu);
  assert.match(workspace, /dpaVersion/iu);
  assert.match(workspace, /dpaSha256/iu);
});
```

Add `"test:customer-agreement-actions": "node --test tests/customer_agreement_actions.test.mjs"` to `package.json`.

- [ ] **Step 2: Run the action test and verify RED**

Run: `npm run test:customer-agreement-actions`

Expected: FAIL because the form and action do not yet implement acceptance.

- [ ] **Step 3: Implement form and server action integration**

Import `currentCustomerAgreements`, `customerAgreementAuthorityStatementVersion`, and `assertCurrentCustomerAgreementForm` into `app/actions.ts`. At the beginning of `createWorkspace`, after user authentication and before Brønnøysund lookup, read the acceptance value plus both submitted versions and both submitted digests and validate them. Preserve the existing Brønnøysund lookup and supported-AS checks. Replace direct company, membership, and audit inserts with the Task 2 RPC through `createSupabaseServiceRoleClient()`, passing `p_actor_id: user.id`, the normalized Brønnøysund identity, plus:

```ts
p_business_terms_version: currentCustomerAgreements.businessTerms.version,
p_business_terms_effective_date: currentCustomerAgreements.businessTerms.effectiveDate,
p_business_terms_path: currentCustomerAgreements.businessTerms.path,
p_business_terms_sha256: currentCustomerAgreements.businessTerms.contentSha256,
p_dpa_version: currentCustomerAgreements.dpa.version,
p_dpa_effective_date: currentCustomerAgreements.dpa.effectiveDate,
p_dpa_path: currentCustomerAgreements.dpa.path,
p_dpa_sha256: currentCustomerAgreements.dpa.contentSha256,
p_authority_statement_version: customerAgreementAuthorityStatementVersion,
p_acceptance_method: "in_app_clickwrap",
```

If validation or RPC fails, use the existing `failTo` boundary and create nothing.

In the workspace company-creation form, add hidden current version and digest inputs for both documents and one required unchecked checkbox. The exact visible copy is:

> Jeg bekrefter at jeg har fullmakt til å inngå avtale på vegne av selskapet, og godtar Talli Brukervilkår for bedriftskunder og Databehandleravtalen.

Use `Link` for both legal documents. Add the sentence to `ownerCopy.workspace` and render it without duplicating the Norwegian sentence inline.

- [ ] **Step 4: Run focused tests and typecheck for GREEN**

Run: `npm run test:customer-agreements && npm run test:customer-agreement-schema && npm run test:customer-agreement-actions && npm run test:web && npm run typecheck`

Expected: all commands exit 0.

- [ ] **Step 5: Commit the onboarding slice**

```bash
git add app/actions.ts app/'(owner)'/workspace/page.tsx app/lib/copy.ts tests/customer_agreement_actions.test.mjs package.json
git commit -m "feat: require agreement acceptance for company setup"
```

### Task 4: Align the legal pack and verify the release boundary

**Files:**
- Modify: `docs/legal/terms-of-service-draft.md`
- Modify: `docs/legal/dpa-draft.md`
- Modify: `docs/legal/README.md`
- Modify: `tests/legal_policy_pack.test.mjs`
- Modify: `docs/launch/evidence/production-e2e-verification-2026-07-16.md`

**Interfaces:**
- Consumes: the implemented public Business Terms, DPA, acceptance record, and unchanged hosted-environment gate.
- Produces: documentation that describes electronic acceptance accurately without claiming legal, security, or production-filing approval.

- [ ] **Step 1: Write failing legal-policy assertions**

Extend `tests/legal_policy_pack.test.mjs` with one test requiring:

```js
test("legal pack uses one beta-to-live business agreement and explicit electronic acceptance", () => {
  assert.match(docs.terms, /Business Terms/i);
  assert.match(docs.terms, /ELMER WELFIS/);
  assert.match(docs.terms, /930 835 978/);
  assert.match(docs.terms, /plan and capabilities shown in the service/i);
  assert.match(docs.terms, /Data Processing Agreement/i);
  assert.doesNotMatch(docs.terms, /continued use.*constitutes acceptance/i);
  assert.match(docs.dpa, /Article 28/i);
  assert.match(docs.dpa, /documented instructions/i);
  assert.match(docs.dpa, /categories of data subjects/i);
  assert.match(docs.dpa, /technical and organizational measures/i);
});
```

- [ ] **Step 2: Run the policy test and verify RED**

Run: `npm run test:legal-policy`

Expected: FAIL because the drafts still describe a pre-incorporation natural-person operator and passive continued-use acceptance.

- [ ] **Step 3: Rewrite the drafts and release condition**

Rewrite the terms draft as the general B2B Business Terms for ELMER WELFIS, preserving the product/support/refund/liability review boundaries and expressing beta/paid differences through the plan and capabilities shown in the service. Rewrite the DPA into a concrete Article 28 structure matching the public DPA; mark subprocessor locations and transfer bases as requiring production re-confirmation rather than asserting unverified facts. Update the legal README to describe explicit company-level electronic acceptance, immutable versions/digests, and the remaining founder/legal/security approvals.

In the production E2E evidence, replace literal manual-signature wording with:

> Business Terms and DPA validly accepted by an authorized representative for the named company, with immutable evidence of the customer, document versions and digests, acceptance method, and timestamp.

Retain the separate requirement for approved current hosted tenant-isolation, private-storage, and restore evidence, and retain the production-filing NO-GO.

- [ ] **Step 4: Run policy and complete project verification**

Run these fresh commands in order:

```bash
npm run test:customer-agreements
npm run test:customer-agreement-schema
npm run test:customer-agreement-actions
npm run test:legal-policy
npm run test:supabase-grants
npm run test:web
npm run typecheck
npm run build
npm run test:supabase:local
```

Expected: every command exits 0. If local Supabase cannot run because Docker or the CLI is unavailable, report that exact blocker and do not claim database runtime verification.

- [ ] **Step 5: Commit the legal and evidence slice**

```bash
git add docs/legal/terms-of-service-draft.md docs/legal/dpa-draft.md docs/legal/README.md tests/legal_policy_pack.test.mjs docs/launch/evidence/production-e2e-verification-2026-07-16.md
git commit -m "docs: align legal pack with reusable electronic acceptance"
```

### Task 5: Whole-branch review and completion evidence

**Files:**
- Modify only files required to resolve Critical or Important review findings.
- Record progress in ignored `.superpowers/sdd/progress.md`.

**Interfaces:**
- Consumes: reviewed commits from Tasks 1–4.
- Produces: a broad review verdict and fresh completion evidence.

- [ ] **Step 1: Generate the final review package**

Run the subagent-driven-development `review-package` script using merge base `2ac6ca69b10e00411fbb7bdd3578bf9be0e64297` and current `HEAD`. Record the emitted package path.

- [ ] **Step 2: Dispatch the broad final reviewer**

Use the requesting-code-review final reviewer template. Require review of security, contract-evidence integrity, atomicity, RLS/grants, stale-form rejection, beta/live equivalence, test quality, and any accidental production-filing or billing activation. The reviewer returns explicit specification and quality verdicts with Critical/Important/Minor findings.

- [ ] **Step 3: Resolve blocking review findings**

If Critical or Important findings exist, dispatch one fix subagent with the complete list, require focused tests and a commit, regenerate the review package, and re-run the broad review. Record Minor findings in the progress ledger for final triage.

- [ ] **Step 4: Run fresh final verification after the last code change**

Run:

```bash
npm run test:customer-agreements && npm run test:customer-agreement-schema && npm run test:customer-agreement-actions && npm run test:legal-policy && npm run test:supabase-grants && npm run test:web && npm run typecheck && npm run build
```

Then run `npm run test:supabase:local`. Read complete output and report exact pass/fail counts and any environment limitations.

- [ ] **Step 5: Inspect final scope and secrets**

Run `git status --short`, `git diff --check 2ac6ca69b10e00411fbb7bdd3578bf9be0e64297..HEAD`, and inspect the final diff for secrets, unrelated edits, generated files, production switch changes, payment activation, or filing entitlement changes. Resolve any discovered scope defect before completion.
