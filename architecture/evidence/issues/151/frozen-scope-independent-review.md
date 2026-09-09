# Independent review — #151 frozen-scope disposition

Reviewed 2026-09-09 against protected-main `91b178c281bcc5fb887a6257d2f72e380199f3e6` (same implementation tree as the proposal's `27ba9b6c954505808ef4c1ce75e94eae9bb5d84f`). Inputs: `/tmp/talli-151-frozen-scope-disposition.md`, `/tmp/talli-151-frozen-scope-inventory.json`, live #132 resolution comment 5083588592, #151 acceptance, ADR0013, current catalog/checker and the actual action/reader/annual-workspace source. This is a proposal review only: no #151 claim, source change, test suite, database, provider or tracker mutation.

## Verdict

**Bounded pass: no blocking correction found.** The proposal is concrete enough for the root's approval-necessity decision. RF semantic ownership, review/override migration and normal cutover choices are already authorized. Do not ask the owner to approve those again or pause independent RF characterization/design behind the bookkeeping decision after normal stage entry is satisfied.

The uncovered remainder is correctly limited to **12 exact residual-tuple reattributions and three exact RF-coordinator read deletions** under today's literal ADR/checker model. ADR0013:50–93 forbids adding scopes to a future facade and restricts future deletion to whole-resource active ownership. `check-architecture.mjs:1461–1499` cannot attribute an extant mixed `public` table to a new RF table through an alias; `2090–2168` demands current deletion/ownership proof; `2248–2279` rejects new record scopes, count changes and unauthorized operation-body changes. Merely updating a manifest cannot satisfy those rules. Conversely, the #132 resolution expressly permits RF rows to leave generic tables and an unmigrated dependency to remain behind its declared target contract. This does not require reopening filing policy or migrating Annual Compliance.

## Independent inventory result

A separate TypeScript AST traversal of current functions, exact tuple lookup in `compatibility-baseline.json`, and source/line matching found **zero discrepancies**:

- 37 unique tuples, 39 `.from`/`.rpc` occurrences.
- 14 annual tuples; 14 RF tuples, comprising the 12 mixed entries plus two current simulation entries.
- Eight audit tuples, one INSERT each; one notification tuple, two calls (SELECT and conditional INSERT).
- The proposed future deletions are precisely override, review-comment and stored-readiness reads in `confirmSimulatedRf1086Submission`, one occurrence each.

The retained sibling behavior is real: generic preview storage is free-text (`0001_authenticated_workspace.sql:322–338`), `ObligationWorkspace.tsx` selects previews and wires review/permission forms for all three obligations, permissions/test evidence accept all three identifiers, and the tax import persists a `skattemelding for AS` submission. Wholesale deletion would therefore remove accepted sibling reads/effects. Source occurrence counts alone are not row-ownership proof; the proposal correctly requires the latter before cutover.

## Constraints that make this bounded pass valid

1. Keep future-only `acknowledgeFilingReviewComment`, list-review/list-override functions unchanged where no tuple deletion otherwise authorizes body changes. Add the RF command/UI branch outside them. For mixed functions, the finite exception may allow only RF delegation/result composition and necessary verified authorization plumbing; it is not permission to rewrite sibling rules.
2. Preserve exact annual query semantics: company + year + ASCII RF obligation, stored-ready prerequisite, absent/not-ready denial, original query-error behavior. A frozen immutable DTO does **not** turn the owner-writable legacy readiness snapshot into trustworthy final-#192 readiness. The annual aggregate writer/rules stay frozen; no browser-supplied `ready` assertion substitutes for the source query. The minimal declared dependency contract is already allowed by #132.
3. RF review-row classification must follow verified persisted parent identity. `target="rf1086_preview"` is also written by the shared comment function for a supplied non-RF preview, so that string alone cannot classify ownership. Likewise preserve inconsistent/unrecognized legacy rows for explicit reconciliation, not silent reassignment. This is an implementation consequence of the proposal's row-ownership proof, not a request for a broader exception.
4. Preserve annual inputs, error precedence and result ordering when combining RF projections with retained sibling reads. Preserve audit eight and notification two call placements/outcomes, including unchanged dedupe/planning; retain original errors rather than opportunistically changing ignored audit-result semantics.
5. The last-relevant-sibling expiry is essential and the draft states it correctly. `#149` is only the residual wrapper attribution, never authority to retain an exited sibling's generic rows/writes. Encode removal per exact tuple when its last real sibling leaves at #152/#153; no later than the last filing cutover for these obligation stores. For example, current shipped non-RF `filing_submissions` production is the tax evidence import; do not invent an annual-accounts generic writer to prolong its reader exception. Determine any preserved historical family from actual migration inventory. The finite mapping must authorize/prove those eventual removals and reject retention after that condition.

No additional architecture decision is identified. Keep the immutable baseline unchanged, test near-miss scope/count changes, and prove single-writer cutover, sibling parity and rollback/recutover before acceptance. This review does not certify implementation, schema completeness, actual-main CI, a complete gate or #151 readiness/closure.
