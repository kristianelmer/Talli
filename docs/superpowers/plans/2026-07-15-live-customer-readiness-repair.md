# Live customer-readiness repair plan

**Goal:** Remove the customer-visible dead ends proven in the 2026-07-15 live
rehearsal, while keeping filing, charging, and legally gated features fail-closed.

**Baseline:** `main` at `cfc3f3b`; live project `oytdpbtzoibocshwunss`; public
application `https://talli.no`.

## Scope and launch boundary

This plan may deploy internal product and database corrections. It does not
approve production filing, live charging, corporate-document release, paid
customer admission, or `founder_production_go_live`. Those capabilities remain
blocked until their existing external evidence gates are complete.

## Task 1 — Make deployed schema parity observable and restore it

**Dependencies:** authenticated Supabase operator access; existing ordered
migrations in `supabase/migrations/`.

**Acceptance criteria:**

- a deterministic contract check reports every live table/RPC required by the
  product without printing credentials;
- the check is red against the audited baseline because the FIFO RPCs and later
  migration artifacts are absent;
- all existing migrations apply cleanly to a fresh local Supabase database;
- only missing migrations are applied to the hosted project, in repository order;
- the hosted contract then passes and the migration history matches the repository;
- security/performance advisors have no unrecorded blocking finding.

**Verification:** `npm run test:deployed-contract` and, with the hosted deployment credentials,
`npm run verify:deployed-contract`,
`npm run test:investment-lots-schema`, `npm run test:supabase:local`, hosted
PostgREST/OpenAPI contract probe, migration-history query, Supabase advisors.

## Task 2 — Prove atomic holding workflows in the deployed application

**Dependencies:** Task 1.

**Acceptance criteria:**

- a supported share purchase creates one holding action, one ledger entry, one
  position, and one FIFO lot atomically;
- a failed request creates none of those records;
- the live UI no longer returns the generic atomic-write failure caused by a
  missing RPC;
- the customer sees a stable, actionable message for any remaining classified
  database rejection.

**Verification:** focused Node tests, local database runtime test, deployed
contract test, authenticated browser rehearsal against a synthetic Test-Norge
case, and post-write relational query.

## Task 3 — Reconcile year-end answers with persisted accounting facts

**Dependencies:** Task 2 only for the live holding-action scenario; the ledger
cost scenario is independent.

**Acceptance criteria:**

- persisted positive activity facts are merged into the interview's initial
  answers and cannot be silently presented as no activity;
- a posted administrative cost makes `paid_costs` true even before an interview
  has been saved;
- holding positions/actions similarly seed their corresponding activity answers;
- saved positive answers remain positive; user confirmations that are not
  derivable from records remain user-controlled;
- the summary never says `Ingen aktivitet registrert i året` when a supported
  persisted activity fact exists.

**Verification:** red/green pure unit tests, year-end presentation test,
typecheck, and authenticated browser rehearsal using the live posted expense.

## Task 4 — Remove remaining customer-facing lifecycle dead ends

**Dependencies:** Tasks 1–3; retention policy and cancellation ADRs.

**Acceptance criteria:**

- connection status distinguishes a real query failure from a healthy empty
  optional feature table;
- no seeded/demo value is presented as a fact for a newly created workspace;
- an unlinked accidental upload can be removed through a retention-safe,
  audited flow; evidence linked to accounting/submission records cannot be
  destroyed and receives a clear explanation;
- under-development filing routes and inactive billing remain truthfully
  unavailable rather than looking broken.

**Verification:** lifecycle unit/database tests, tenant-isolation checks,
browser deletion/blocked-deletion rehearsal, and copy assertions.

## Task 5 — Customer-ready verification and handoff

**Dependencies:** Tasks 1–4.

**Acceptance criteria:**

- the full local launch rehearsal, typecheck, production build, dependency audit,
  whitespace check, and code review pass on one immutable commit;
- the deployed login, onboarding, document, bank, holding, year-end, preview,
  billing-disabled, and logout journeys are rehearsed on desktop and mobile;
- the canonical CR-001…CR-018 map records completed internal evidence and names
  every remaining external owner/gate;
- verified changes are committed and pushed; `main` is updated only with the
  tested commit.

**Verification:** `npm run test:launch-rehearsal`, `npm run typecheck`,
`npm run build`, `npm audit --omit=dev`, `git diff --check`, code-review checklist,
and a timestamped browser evidence entry.
