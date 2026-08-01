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
