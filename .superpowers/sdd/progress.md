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

`#135 -> #136 -> #138 -> #139 -> #140 -> #141 -> #142 -> #143 -> #147 -> #144 -> #145 -> #148 -> #137 -> #150 -> #151 -> #146 -> #152 -> #153 -> #149 -> #155 -> #156 -> #157 -> #154`

Newly added missing capability migrations:

- #155 — append-only audit evidence
- #156 — notification outbox and delivery
- #157 — company archive composition

## Next handoff

- Next ticket: #135, enabling foundation only.
- Start from the architecture-baseline commit containing this progress record.
- Do not migrate business capability behavior in #135.
- Re-run the accepted checks relevant to the slice and record its exact base,
  implementation commits, independent review dispositions, and verification
  evidence here before advancing to #136.
- Unresolved #134 findings: none.
