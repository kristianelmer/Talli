# Exact #151 compatibility registry amendment

Status: reviewed proposal, awaiting Kristian's decision. No #151 implementation or claim has started. #150 is merged in PR #210; its exact-main Release verification is still running.

The RF migration must remove RF data and policy from the generic web path. Twelve existing registry entries also cover tax/accounts and shared annual-workspace calls. Removing those calls now would break later stages; retaining them under the RF stage would violate the frozen registry's exit rule.

Approve only the following finite adjustment to ADR0013 and its enforcement:

1. Reattribute the **12 existing mixed entries**, each with exactly one existing persistence call, from `compat-rf1086-persistence/#151` to the existing `compat-annual-compliance-persistence/#149` record after RF's rows and writes have been removed. Preserve their original identities, sibling behavior, validation, authorization, results, errors and side-effect order. This tracks existing shared transport; tax/accounts retain their business ownership. Each residual call expires when its last real sibling source migrates, no later than the last filing cutover, rather than waiting automatically for #149.
2. Retire exactly **three reads** in the RF-only `confirmSimulatedRf1086Submission` coordinator: `filing_overrides`, `filing_review_comments` and `filing_readiness_snapshots`, one call each. RF review/override facts move under their already-approved owner. The stored annual-readiness prerequisite remains an unchanged, server-read source input through a declared frozen query; its writer and rules remain with #149.

The [exact tuple and effect inventory](/tmp/talli-151-frozen-scope-disposition.md) is the binding scope, together with its [machine-readable source inventory](/tmp/talli-151-frozen-scope-inventory.json). All other future scopes remain frozen. The immutable baseline remains byte-identical. This adds no generic permission to relocate future writers or expand compatibility scopes.

The adjustment preserves all eight adjacent audit calls, both notification calls and their placement. It allows only the listed RF delegation/read-result composition and necessary authorization plumbing. Generic stores must reject or conceal RF rows after contract. RF and sibling counts/hashes, tenant isolation, exact sibling behavior, rollback/recutover, independent review and the two complete gates remain mandatory. Historical payloads, manifests and receipt hashes are preserved.

The [independent proposal review](/tmp/talli-151-frozen-scope-independent-review.md) verified all 37 affected/adjacent tuples and 39 calls without discrepancies. It found this finite registry adjustment necessary under the current literal rules. RF semantic ownership and normal implementation choices are already authorized and are not being submitted for approval again.

Why this needs a separate decision: [ADR0013](</Users/kristianelmer/.codex/worktrees/192-cancellation-01a07a7f/Holding accounting/docs/adr/0013-enforce-the-architecture-and-migrate-serially.md:54>) says the registry “may not add a facade or scope, retain a facade after its stage” and permits future deletions only when the catalog assigns the whole resource to the active owner. These shared public tables still contain sibling/annual data, so that exception cannot truthfully cover the 15 listed dispositions. The two earlier approvals cover #150's credential relocations only.

This decision concerns migration bookkeeping and preserved code behavior. It authorizes no provider tests, real filings, spending, production activation or promotion. #151 still requires its own entry baseline after #150's integration is verified.
