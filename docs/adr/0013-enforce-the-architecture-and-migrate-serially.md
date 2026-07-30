---
status: accepted
date: 2026-07-26
---

# Enforce the Architecture and Migrate Serially

Talli will adopt the repository and module format prototyped at commit
`1c38dc6d`, then migrate capabilities one at a time in the exact order approved
by issue #132. Machine-readable manifests are the architectural source of truth,
but enforcement reconciles them with language-aware imports, public exports,
database catalogs and migrations, generated contracts, scoped documentation,
tests, compatibility records, and deterministic dependency artifacts. The
customer-ready CI aggregator remains the highest acceptance seam and must include
both application builds, architecture checks, contract/deploy-order checks,
security/RLS evidence, migration equivalence while active, critical browser
journeys, and the existing launch rehearsal without duplicate test ownership.

The prototype's JSON Schema and `MODULE.template.md` are normative starting
points. Its filled ledger documents are illustrative examples; where their
headings omit or rename template sections, foundation must align them before they
can serve as conformance fixtures. A companion backend system manifest and a
schema-validated compatibility registry cover workflows, technical state, adapter
bindings, and exceptions that a capability/web manifest cannot own.

Foundation may place a not-yet-migrated capability's single canonical legacy
implementation behind its already-declared target contract. Such a legacy façade
must be registered, may not create a second writer or accept new functionality,
and expires at that capability's numbered migration stage. It is distinct from
active-stage compatibility debt. Debt created by the active capability must be
removed before the next stage; the narrow human exception in issue #132 may defer
it for at most the earlier of fourteen days or one stable customer-ready release.

Every capability stage uses characterization, one authoritative writer,
expand–migrate–contract, deterministic reconciliation, rollback/recutover rehearsal,
cleanup of old code/data/adapters/equivalence tests, Graphify/manifest agreement,
and two consecutive complete gates on immutable revisions. Activated production
paths also require the approved seven-day observation window. Implementation
issues may be created only after issue #133 and the Wayfinder map are closed.

## Canonical decision inputs

- Repository prototype and manifest format: issue #130 and commit `1c38dc6d`.
- Enforcement and acceptance suite: issue #131.
- Serialized roadmap and exit criteria: issue #132.
- Final approval and frozen pointer index: issue #133.

## Consequences

- Structural movement is not a capability migration and cannot hide business or
  data cutover.
- Circular dependencies, unowned data, failed authorization/RLS, statutory-output
  differences, secret leakage, and ambiguous external effects are never
  suppressible.
- Semantic Graphify extraction is optional and non-blocking; deterministic
  manifest-derived dependency evidence is required and incurs no model/provider
  charge.
- Future changes to the frozen baseline require an issue that identifies affected
  ADRs/manifests, compatibility and migration impact, acceptance evidence, and
  explicit approval before implementation.
