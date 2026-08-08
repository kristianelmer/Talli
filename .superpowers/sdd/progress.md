# Modular architecture migration progress

## Program baseline

- Integration branch: `codex/issue-134-production-boundary`
- Approved architecture: issues #132 and #133, recorded by ADR-0010 through
  ADR-0013 in the same commit as this progress record.
- Superseded decisions: ADR-0007 and ADR-0008.
- Integration with the then-current `origin/main`: merge commit `504be423`.
- Migration rule: execute one ticket at a time from the accepted integration
  head, with a fresh-context implementer and fresh-context architecture and
  standards reviewers before advancing.

## Accepted production-boundary proof (#134)

- Exact review base: `ea7bb75db7f593f63268682c3b75c883fe64cbbe`
- Accepted implementation head before integration: `5964823c`
- Original implementation: `045daddd`
- Review fixes: `4d70e7a5`, `c13fa25a`, `ac0a2de5`, `a0ad24d2`,
  `d3711b3d`, and `5964823c`
- Final architecture review: no findings.
- Final standards review: no findings.
- Evidence recorded on GitHub issue #134.

Accepted verification:

- `npm run test:boundary`
- `npm run typecheck`
- `npm run build:backend`
- `npm run build:web`
- `npm run test:boundary-smoke`
- `npm run test:customer-agreement-actions` after merging `origin/main`
- `git diff --check`

The proof now covers RFC 9457 errors, explicit fail-closed backend
configuration, process-only liveness, local-configuration readiness, declared
correlation headers, generated-client provenance, v1 compatibility checks for
responses, arrays, nullability, inputs, authentication, headers, and package
versioning, plus pinned mixed-version consumers in both deployment orders.

## Serialized migration queue

The repaired dependency chain is:

`#135 -> #136 -> #160 -> #161 -> #138 -> #139 -> #140 -> #141 -> #142 -> #143 -> #147 -> #144 -> #145 -> #148 -> #137 -> #150 -> #151 -> #146 -> #152 -> #153 -> #149 -> #155 -> #156 -> #157 -> #154`

Newly added missing capability migrations:

- #160 — company invitations and membership administration
- #161 — company cancellation and deletion lifecycle
- #155 — append-only audit evidence
- #156 — notification outbox and delivery
- #157 — company archive composition

## Accepted authenticated company context (#136)

- Exact review base: `3c05ddfa7532eea40a02fdf5325a1d6d96d4a388`
- Accepted implementation head: `681e4523094f34cd42dcbf77a4c07bcb18bb62b8`
- Implementation commits: `b583b7df`, `eb8b2a66`, `124d37d1`, `9c872c5d`,
  `951dc0a8`, `4549a367`, `e1ac5222`, and `681e4523`
- Final fresh-context acceptance review: PASS, no findings.
- Scope confirmation: authenticated company context only; onboarding,
  membership administration, and cancellation/deletion remain serialized in
  #160, #161, and #138.

Accepted verification:

- `npm run test:architecture` — 34 passed.
- `npm run check:architecture`
- `npm run typecheck`
- `npm run test:boundary` — backend 19, web 16, contract 12 passed.
- `npm run test:supabase` — 7 mandatory/static tests passed; 4 pre-existing
  optional local-environment tests skipped.
- Fresh PostgreSQL company-access RLS rehearsal — passed.
- `npm run build:backend`
- `npm run build:web`
- `npm run test:boundary-smoke`
- `npm run test:launch-rehearsal`
- `git diff --check`

The slice now validates Supabase sessions before RLS reads, injects a declared
credential-safe Supabase adapter, enforces owner/AAL2/tenant-concealed policy,
returns literal-checked context through the generated client, removes direct web
selected-context persistence, and records every remaining legacy operation as
one exact path/rule/resource/operation compatibility scope.

## Implemented company invitations and membership administration (#160)

- Exact implementation base: `2ae2708d206ede406b24f39c04b1dd84f29fe163`
- Implementation head before this progress-only record: `41b5352d`
- Implementation commits: `c20c81c1`, `306f1fef`, `ef673514`, and `41b5352d`
- Acceptance state: implementation complete; fresh-context architecture and
  standards review remain before this slice is accepted and the queue advances.
- Scope confirmation: invitation and membership administration only;
  cancellation/deletion remains serialized in #161 and no later capability was
  moved early.

Implementation verification:

- `npm run test:boundary` — backend 25, web 18, contract 13 passed.
- `npm run test:supabase` — 7 mandatory/static tests passed; 4 pre-existing
  optional local-environment tests skipped.
- Fresh PostgreSQL invitation/membership runtime rehearsal — passed.
- Invitation migration schema tests — 3 passed.
- `npm run test:review` — 5 passed.
- `npm run test:supabase-grants` — 3 passed.
- Architecture tests — 34 passed in four resource-bounded shards (11 + 10 + 6
  + 7); `npm run check:architecture` passed.
- `npm run typecheck`
- `npm run build:backend`
- `npm run build:web`
- `npm run test:boundary-smoke`
- `npm run test:launch-rehearsal`
- `git diff --check`

The slice adds authenticated invitation lookup, create, revoke, resend, and
accept flows plus reviewer/read-only membership administration through stable
generated contracts. Supabase sessions are independently validated, owner
administration requires AAL2, invitation acceptance is atomic, tenant discovery
is concealed, token hashes are denied at the database and API boundaries, and
the migrated web operations no longer persist invitation, membership, or
company records directly.

## Accepted module-definition foundation (#135)

- Exact review base: `0319776cab4bda22445370bc1c45127d74f0764d`
- Accepted implementation head: `0ec08f1fa03b5874dd3c9197b08a4f8cb918455b`
- Implementation commits: `a64b64b3`, `a057ac3f`, `01938ecf`, `379dcbb6`,
  `daa213de`, `8affd0b8`, `ea33b89c`, `5d0a8886`, `d5a6b433`, `0cf762ec`,
  `792f2817`, and `0ec08f1f`
- Final fresh-context acceptance review: PASS, no actionable findings.
- Scope confirmation: enabling foundation only; no business capability, rule,
  table, provider operation, or authoritative write moved.

Accepted verification:

- `npm run test:architecture` — 26 passed.
- `npm run check:architecture`
- `npm run typecheck`
- `npm run test:boundary` — backend 6, web 9, contract 11 passed.
- `npm run build:backend`
- `npm run build:web`
- `npm run test:boundary-smoke`
- `npm run test:launch-rehearsal`
- `git diff --check`

The foundation now has schema-valid technical and web module manifests,
machine-checked documentation inventories, deterministic dependency evidence,
source-derived technical table ownership, binding-aware TypeScript and Python
boundary enforcement, a minimal shared-kernel policy, bounded compatibility
exceptions, and annotated-tag-derived customer-ready release state.

## Next handoff

- Next ticket: #161, company cancellation and deletion lifecycle.
- Start only after #160 receives fresh-context architecture and standards
  acceptance review and is merged.
- Preserve the #135 architecture gate, #136 session/RLS boundary, #160
  invitation/membership contracts, and exact operation-scoped compatibility
  contract.
- Re-run the accepted checks relevant to #161 and record its exact base,
  implementation commits, independent review dispositions, and verification
  evidence here before advancing to #138.
- Unresolved #160 implementation findings: none; independent review is pending.

## Issue #160 review-fix round 1

- Review input: `/tmp/talli-issue-160-architecture-review-1.md` and
  `/tmp/talli-issue-160-standards-review-1.md`.
- Exact reviewed head: `373f85ccac5fb6f7c2a36e2ea25cd72fada729a8`.
- Corrected implementation head before this progress-only record:
  `114b82f72c8efe40044357e17be612d03af5ec17`.
- Review-fix commits: `6dbe9405`, `da9c8c94`, and `114b82f7`.
- Acceptance state: every Critical, Important, and Minor round-1 finding is
  implemented; a new fresh-context architecture and standards review remains
  required before #160 is accepted.

Resolved review findings:

- Pgcrypto hashing resolves the installed extension schema under an empty
  function search path, with real fresh-PostgreSQL create and resend coverage.
- Invitation and membership commands execute as the restricted
  `company_access_executor` NOLOGIN/NOBYPASSRLS non-owner and are therefore
  filtered by genuine RLS. Only technical command receipts use FORCE RLS.
  Invitees cannot enumerate invitation rows directly.
- Lookup and acceptance atomically bind both the current verified Auth subject
  and normalized email and reject disagreement with stale JWT claims.
- Consequential commands carry durable operation IDs, persisted replay receipts,
  optimistic revision preconditions, one bounded identical-operation retry, and
  deterministic notification/audit IDs without moving #155 or #156 ownership.
- The migration is split into expand and contract files; the PostgreSQL runtime
  test proves the old direct writer, the overlap, and the final RPC-only writer.
- Immutable request contracts now belong to the capability public entry point;
  generated invitation decoders reject every unknown field.
- Login continuation, membership selector labeling, manifest attribution, and
  success `X-Request-ID` OpenAPI declarations are covered by regression tests.
- Delivery-secret persistence is documented truthfully: private command receipts
  and the legacy notification outbox can contain raw tokens; authenticated roles
  cannot read receipts, accepted owners retain the existing outbox policy, and
  #160 adds no automatic purge beyond token invalidation/expiry.

Review-fix verification:

- `npm run test:boundary` — backend 26, web 19, contract 20 passed.
- `npm run test:supabase` — 16 passed, 4 optional environment-dependent tests
  skipped; the mandatory fresh PostgreSQL 16 test exercised real create, resend,
  replay, RLS, concealment, identity binding, and expand/contract overlap.
- `npm run test:architecture` — all 34 cases passed in one run.
- `npm run check:architecture`, `npm run test:supabase-grants`,
  `npm run typecheck`, OpenAPI generation check, and generated-client check passed.
- `npm run build:backend`, `npm run build:web`, and
  `npm run test:boundary-smoke` passed.
- `npm run test:launch-rehearsal` passed; its two pre-existing optional official
  schema checks remained skipped because no external schema directory was set.
- `git diff --check 2ae2708d206ede406b24f39c04b1dd84f29fe163..114b82f7`
  passed, and the implementation tree was clean before this progress update.

## Issue #160 review-fix round 2

- Review input: `/tmp/talli-issue-160-architecture-review-2.md` and
  `/tmp/talli-issue-160-standards-review-2.md`.
- Exact reviewed head: `80d40453`.
- Corrected implementation head before this progress-only record:
  `55178b7dc5dfff0fc6b8eb654e11b876c90411c8`.
- Review-fix commits: `b344f455`, `274b199b`, and `55178b7d`.
- Acceptance state: every Critical, Important, and Minor round-2 finding is
  implemented; a new fresh-context architecture and standards review remains
  required before #160 is accepted.

Resolved review findings:

- Pgcrypto access is isolated behind a fixed-empty-search-path, security-definer
  token-hash helper. The command executor has no `extensions` schema usage, and
  authenticated callers cannot execute either narrow privileged helper.
- Token lookup and acceptance derive the current subject and normalized email
  from `auth.users`, then require caller arguments and JWT claims to agree. A
  direct authenticated RPC with stale email claims is rejected.
- The destructive contract release artifact now lives under
  `supabase/contract-migrations/`, outside the automatic migration runner. The
  expand release remains compatible; a later immutable Release C must move and
  apply the artifact only after the cutoff evidence is approved.
- Command receipts are classified as backend-system technical state in the
  catalog, backend-system inventory, generated dependency evidence, and
  capability documentation.
- Auth/database helpers use the `_v1` convention. FORCE RLS evidence now states
  exactly that only the technical receipt table is forced; invitation and
  membership commands instead use genuine RLS through a non-owner,
  NOBYPASSRLS executor.
- The legacy authenticated self-membership update policy and UPDATE grant are
  removed during expand, preventing reviewer self-promotion to owner or
  re-opening membership acceptance.
- Public company-access UUIDs and optimistic revisions are validated before the
  PostgREST boundary. Malformed UUIDs and naive/non-RFC3339 revisions return a
  stable RFC 9457 HTTP 422 without making an upstream call.

Round-2 TDD and verification evidence:

- The initial review regression suite failed 6/6; the two malformed-command API
  regressions failed with 201/404 instead of 422; and the target-shaped database
  runtime failed with `permission denied for schema extensions` before the fixes.
- `npm run test:boundary` passed: backend 28, web 19, contract 26.
- `npm run test:supabase` passed 16 with 4 pre-existing optional
  environment-dependent skips. The mandatory target-shaped PostgreSQL runtime
  performed real create/resend/replay, rejected stale direct-RPC identity,
  denied reviewer promotion, verified helper grants, and exercised manual
  expand/contract staging.
- `npm run test:supabase-grants` passed 3/3; `npm run test:architecture` passed
  34/34; `npm run check:architecture`, generated OpenAPI/client checks,
  `npm run typecheck`, backend/web builds, and `npm run test:boundary-smoke`
  passed.
- `npm run test:launch-rehearsal` passed, including launch copy, signoff, legal,
  CI-gate, and the remaining rehearsal suites.
- No hosted provider, deployment, GitHub mutation, push, or chargeable action
  was performed.

## Issue #160 review-fix round 3

- Review input: `/tmp/talli-issue-160-architecture-review-3.md` and
  `/tmp/talli-issue-160-standards-review-3.md`.
- Exact reviewed head: `94e3f3dec5c2689e6585a513cce4f09e1f4026d7`.
- Corrected implementation head before this progress-only record:
  `20ee4c9d475d4b8f8f55ad6ca7026f70a50cfe21`.
- Review-fix commits: `c79eb3b7` and `20ee4c9d`.
- Acceptance state: the one Important architecture finding and one Minor
  standards finding are implemented; fresh-context acceptance review remains
  required before #160 is merged.

Resolved review findings:

- Create, resend, revoke, and membership-administration RPCs now require the
  caller to remain a currently accepted owner at AAL2 before reading or
  returning any historical receipt. Authorization loss is concealed as
  `company_access_not_found`, including token-bearing create/resend receipts.
- Receipt replay now rejects expired receipts before fingerprint comparison or
  result/token recovery. An authorized caller can still reconcile the exact
  unexpired operation after authority is restored, preserving idempotency.
- Invitation revision fields must arrive as JSON strings matching RFC3339's
  date/time shape before Pydantic converts them to aware datetimes. Numeric
  epochs and space-separated timestamps return RFC 9457 HTTP 422 without any
  Auth or PostgREST gateway call.

Round-3 TDD and verification evidence:

- RED: the target-shaped PostgreSQL regression disclosed `retained-token` to a
  demoted historical actor; the two strict timestamp requests reached the
  gateway and returned 404 instead of 422.
- Focused GREEN: backend company-access tests passed 24/24; the real PostgreSQL
  runtime passed 1/1; migration/schema and prior-review tests passed 15/15.
- `npm run test:boundary` passed: backend 30, web 19, contract 26.
- `npm run test:supabase` passed 16 with 4 unchanged optional environment
  skips. Its mandatory PostgreSQL case denied all four receipt families at
  AAL1, denied create/resend after owner demotion, preserved exact reconciliation
  after authority restoration, and concealed an expired token-bearing receipt.
- `npm run typecheck`, `npm run check:architecture`,
  `npm run test:supabase-grants` (3/3), OpenAPI/client reproducibility checks,
  and `npm run build:backend` passed.
- No hosted provider, deployment, GitHub mutation, push, external action, or
  chargeable operation was performed.

## Issue #160 review-fix round 5

- Review input: `/tmp/talli-issue-160-architecture-review-5.md`.
- Exact reviewed head: `176e9ed8f9fd65f8d6e197398aed0ed088e765aa`.
- Corrected implementation head before this progress-only record:
  `89ec3685c661fd97e9f81124b42336949d0b04c2`.
- Review-fix commit: `89ec3685`.
- Acceptance state: the one Important cross-tenant oracle finding is
  implemented; fresh-context architecture acceptance remains required.

Resolved review finding:

- The privileged hidden-receipt check now requires operation ID, company,
  command name, and request fingerprint, and derives the original actor from
  `auth.uid()` internally. Authenticated callers cannot execute it directly or
  spoof an actor parameter.
- All four owner RPCs pass a constant command name plus their existing stable
  business fingerprint. A foreign tenant/actor/command/fingerprint receipt is
  therefore indistinguishable from an unknown operation before ordinary input
  validation, while this caller's exact hidden demoted/expired replay remains
  concealed rather than re-executed.
- Acceptance replay remains outside the helper, and the round-four receipt-read
  authorization linearization point is unchanged.

Round-5 TDD and verification evidence:

- RED: a real company-A AAL2 owner probed a company-B receipt and an unknown ID
  with identical invalid create payloads. The old helper returned
  `company_access_not_found` versus `company_access_invalid_request`; the static
  contract also rejected the globally scoped signature.
- GREEN: both probes return the exact same `company_access_invalid_request`, and
  PostgreSQL verifies no invitation or receipt mutation. Focused runtime/schema/
  review tests passed 24/24, including the prior concurrent-demotion case.
- `npm run test:boundary` passed: backend 30, web 19, contract 27.
- `npm run test:supabase` passed 16 with 4 unchanged optional environment skips;
  `npm run test:supabase-grants` passed 3/3.
- `npm run test:architecture` passed 34/34; `npm run check:architecture`,
  `npm run typecheck`, and `npm run build:backend` passed.
- No hosted provider, deployment, GitHub mutation, push, external action, or
  chargeable operation was performed.

## Issue #160 review-fix round 6

- Review input: `/tmp/talli-issue-160-architecture-review-6.md` and
  `/tmp/talli-issue-160-standards-review-6.md`.
- Exact reviewed head: `f85fffed06a1faae10c56c352c865ac4d38dc87b`.
- Corrected implementation head before this progress-only record:
  `d407bb3c8ce31bb7236824903e679ec05f8ee83a`.
- Review-fix commit: `d407bb3c`.
- Acceptance state: the shared Important storage/locking namespace finding is
  implemented; fresh-context acceptance review remains required.

Resolved review finding:

- Command receipts now use `(actor_id, operation_id)` as their composite primary
  key. Different actors may safely reuse the same operation UUID, while the same
  actor deliberately retains one idempotency/conflict namespace across companies.
- Every owner and acceptance receipt read selects by both internally derived
  actor and operation ID. The existing company, command, and fingerprint checks
  continue to define exact replay semantics.
- All five command advisory locks hash the internally derived actor together
  with the operation ID. The tested company-A/company-B actors have distinct
  lock keys for the same operation UUID; the per-email create serialization lock
  remains independently scoped to company and recipient.

Round-6 TDD and verification evidence:

- RED: a valid company-A create using company B's operation ID rolled back on
  the global receipt primary key, while the identical unknown-ID request
  succeeded. Static contracts also rejected the global key, actor-unscoped
  receipt reads, and operation-only advisory locks.
- GREEN: both valid requests reach identical successful create semantics inside
  isolated rollback transactions. No company-A invitation/receipt remains and
  company B's receipt is unchanged. Focused runtime/schema/review tests passed
  24/24, including acceptance replay, exact replay, demotion concealment,
  restored reconciliation, and prior invalid-payload concealment.
- `npm run test:boundary` passed: backend 30, web 19, contract 27.
- `npm run test:supabase` passed 16 with 4 unchanged optional environment skips;
  `npm run test:supabase-grants` passed 3/3.
- `npm run test:architecture` passed 34/34; `npm run check:architecture`,
  `npm run typecheck`, and `npm run build:backend` passed.
- No hosted provider, deployment, GitHub mutation, push, external action, or
  chargeable operation was performed.

## Issue #160 review-fix round 4

- Review input: `/tmp/talli-issue-160-architecture-review-4.md`; the matching
  standards review passed without findings.
- Exact reviewed head: `a660c3eee3c8742f407bcc0b63dbc7a733169142`.
- Corrected implementation head before this progress-only record:
  `6ddb2d29778bbbcd7382e0b41e9fec7970313bc8`.
- Review-fix commit: `6ddb2d29`.
- Acceptance state: the one Important concurrency finding is implemented;
  fresh-context architecture acceptance review remains required before merge.

Resolved review finding:

- Receipt SELECT RLS preserves actor-only acceptance replay while requiring the
  original actor, AAL2, current accepted ownership, and unexpired lifetime for
  all four owner-command receipt families in the SELECT statement's snapshot.
- A narrow security-definer existence helper is executable only by the
  restricted command executor. It exposes no receipt fields and prevents a
  hidden demoted/expired operation ID from being re-executed.
- The authorized receipt read is now the replay linearization point. A demotion
  committed after preliminary authorization but before receipt selection is
  concealed as `company_access_not_found`; create/resend tokens cannot cross
  that boundary. Restoring owner authority preserves exact unexpired replay.

Round-4 TDD and verification evidence:

- RED: a disposable-database helper hook computed and cached owner authorization,
  blocked on an advisory lock, allowed a second connection to commit demotion,
  then resumed the receipt SELECT. The old policy returned `resend-token`.
- GREEN: the coordinated two-connection runtime denied the same race without a
  token and reconciled the original resend after owner restoration. Focused
  database/schema/review tests passed 17/17.
- `npm run test:boundary` passed: backend 30, web 19, contract 27.
- `npm run test:supabase` passed 16 with 4 unchanged optional environment skips;
  `npm run test:supabase-grants` passed 3/3.
- `npm run test:architecture` passed 34/34; `npm run check:architecture`,
  `npm run typecheck`, and `npm run build:backend` passed.
- No hosted provider, deployment, GitHub mutation, push, external action, or
  chargeable operation was performed.

## Issue #160 review-fix round 7

- Review input: `/tmp/talli-issue-160-architecture-review-7.md` and
  `/tmp/talli-issue-160-standards-review-7.md`.
- Exact reviewed head: `2fc24d031b9a42725cdb17faa126808a8f091208`.
- Corrected implementation head before this progress-only record: `a61c3ca7`.
- Review-fix commit: `a61c3ca7`.
- Acceptance state: the shared Important downstream side-effect namespace
  finding is implemented; fresh-context acceptance review remains required.

Resolved review finding:

- Invitation delivery and audit identities are deterministic UUIDv8 values over
  the authenticated actor, durable operation ID, and command/purpose. Different
  actors may safely reuse one operation UUID, while exact same-actor retries
  retain one stable continuation identity.
- The original operation UUID remains in delivery payloads and audit correlation
  text. Exact-row reconciliation handles duplicate/retry outcomes; missing,
  hidden, mismatched, and transient failures fail closed instead of silently
  dropping audit evidence.
- The #155 audit and #156 notification compatibility registrations now point to
  the shared helper operation without changing their owner, expiry, or removal
  conditions.

Round-7 TDD and verification evidence:

- RED: workflow and static contracts failed before actor-scoped side-effect
  derivation/persistence existed.
- GREEN at the helper boundary: four workflow tests cover actor/purpose
  determinism, two actors sharing one UUID across create/resend, exact replay,
  no oracle, and audit failure/retry. These tests did not prove that a fresh UI
  render could recover the original operation; Round 8 supersedes that claim.
- The real PostgreSQL rehearsal created/resend for two owners with the same
  operation IDs, persisted four distinct delivery and four distinct audit rows,
  and verified per-actor RLS visibility.
- `npm run test:boundary` passed: backend 30, web 23, contract 27.
- `npm run test:supabase` passed 16 with 4 unchanged optional environment skips;
  the focused invitation runtime/schema set passed 10/10.
- `npm run test:architecture` passed 34/34; `npm run test:supabase-grants`
  passed 3/3; `npm run check:architecture`, `npm run typecheck`,
  `npm run build:web`, and `npm run build:backend` passed.
- No hosted provider, deployment, GitHub mutation, push, external action, or
  chargeable operation was performed.

## Issue #160 review-fix round 8

- Review input: `/tmp/talli-issue-160-architecture-review-8.md` and
  `/tmp/talli-issue-160-standards-review-8.md`.
- Clean starting head: `6ba651945822701ebcb73793f48f8fea324af8c6`.
- Review-fix implementation commit: `aa635f98`.
- Acceptance state: the unreachable-retry Important finding and stale module
  documentation finding are implemented; fresh-context acceptance review remains required.

Resolved review findings:

- Invitation command receipts now own a durable pending side-effect
  continuation. The shipped recovery forms accept no browser operation ID or
  token; the backend derives the actor from Auth, lists only that actor's pending
  receipts, and resumes the original operation without invoking the business
  command again.
- Completion is idempotent and fail-closed. PostgreSQL verifies the exact
  actor+operation+purpose UUIDv8 outbox/audit evidence before marking the receipt
  complete and clearing its delivery token. Expired continuations retain audit
  recovery, clear their token when examined, and do not enqueue obsolete mail.
- Company-access module documentation now describes the actor-scoped IDs,
  receipt-owned recovery, proof-completion boundary, and clock-free expiry
  limitation instead of the obsolete raw-operation retry design.

Round-8 TDD and verification evidence:

- RED: the action-level recovery suite initially failed because the workflow
  module did not exist. GREEN: seven injected-failure cases cover create,
  accept, revoke, and resend at every outbox/audit boundary and prove one command
  mutation, one original operation ID, and completion through the shipped recovery path.
- The real PostgreSQL rehearsal rejects completion without exact evidence,
  completes idempotently after evidence exists, clears tokens, hides a foreign
  receipt completion as not found, and preserves same-operation isolation for two actors.
- `npm run test:boundary` passed: backend 31, web 30, contract 28.
- `npm run test:supabase` passed 17 with 4 unchanged optional environment skips;
  `npm run test:supabase-grants` passed 3/3.
- `npm run test:architecture` passed 34/34; `npm run check:architecture`,
  `npm run typecheck`, `npm run build:web`, and `npm run build:backend` passed.
- No hosted provider, deployment, GitHub mutation, push, external action, or
  chargeable operation was performed.
