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
Stable customer-ready releases are annotated Git tag objects whose tag identity
begins `customer-ready-`. Lightweight tags do not qualify. The tracked release
state must exactly match the latest such tag reachable from the gated revision,
including its peeled commit and tagger timestamp. Equal tagger timestamps are
ambiguous and fail the gate rather than being ordered by tag name. Until the
first qualifying tag exists, the explicit release state is `null`.

Every capability stage uses characterization, one authoritative writer,
expand–migrate–contract, deterministic reconciliation, rollback/recutover rehearsal,
cleanup of old code/data/adapters/equivalence tests, Graphify/manifest agreement,
and two consecutive complete gates on immutable revisions. Activated production
paths also require the approved seven-day observation window. Implementation
issues may be created only after issue #133 and the Wayfinder map are closed.

## 2026-08-26 clarification: frozen facades are not compatibility debt

Issues #185 and #186 clarify the compatibility language above without changing
the serialized migration decision. The records present at revision
`d331ee2717d1eeacef0d81db42b9d4fb5848b408` are frozen legacy-facade records,
not calendar-expiring exceptions. `architecture/compatibility-baseline.json`
records their exact IDs, scopes, removal issues, and single canonical legacy
runtime. The active registry may remove the current capability's frozen scopes.
It may not add a facade or scope, retain a facade after its stage, create a
second writer, or use a facade to add business behavior. A future capability's
facade otherwise remains frozen, subject only to the resource-owner cutover
amendment below.

Only debt created while migrating the current capability is active-stage debt.
It remains a narrow, explicitly approved exception: it expires at the earlier of
fourteen days or the next stable customer-ready release and may survive no
farther than the immediately succeeding capability. Authorization/RLS,
statutory-output reconciliation, secret leakage, ambiguous external effects,
and the other non-suppressible categories above can never become either record
kind.

The migration state names one current capability and its exact removal ticket or
tickets. An exit attempt fails while any current legacy facade or blocking
predecessor debt remains. Once a capability advances, the registry must preserve
two distinct immutable revisions on which the complete customer-ready gate
passed. Future stages stay static until they become current, except for the
exact resource-owner deletions authorized below.
The one-time #186 foundation recovery records its two passes separately before
the first capability stage can rely on the restored baseline.

## 2026-08-26 amendment: active-resource authorization cutover

Issue #138 exposed that a current capability cannot revoke browser access to a
resource it owns while frozen future operations retain direct authorization or
context reads of that resource. Kristian approved this narrow amendment after
the affected scopes and post-contract RLS failure were recorded on #138.

The active capability may remove an exact frozen scope from a future facade only
when the database catalog assigns that scope's resource to the active capability.
Current source must prove the exact call is gone. Every retained future-owned
persistence resource and occurrence count in the affected operation remains
frozen, and no new persistence resource may appear. An entire future record may
disappear only when every one of its scopes satisfies the same ownership and
deletion proofs.

This exception authorizes only behavior-equivalent authorization-helper or RLS
seam changes required to revoke access to the active capability's resources. It
does not authorize a future capability's writer, provider effect, business rule,
public contract, statutory output, or other business behavior to change.
Characterization, generated-contract, database/RLS, browser, rollback/recutover,
and two immutable customer-ready gates must prove the cutover. Any affected
resource without exact catalog ownership fails closed and remains frozen.

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
