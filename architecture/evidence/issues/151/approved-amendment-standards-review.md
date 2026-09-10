# Independent Standards review — exact RF compatibility amendment

Reviewed 2026-09-10 against pinned checkpoint `8f86488cb32e8d50ad8546654e20ea46d9c8885d`. Scope: uncommitted amendment enforcement in `scripts/check-architecture.mjs` and its architecture tests, assessed against the exact approved revision-2 proposal, inventory, original frozen-scope disposition, and ADR0013. No implementation edits or database/provider operations.

## Verdict

No remaining actionable finding in this reviewed correction. All three previously reported enforcement defects are closed:

1. Reattributed mixed operations now require their original or exact reviewed whole-operation digest in addition to preserved sibling persistence chains/counts. Arbitrary early returns, changed validation and cross-resource effect reordering cannot inherit the RF composition exemption.
2. Residual handoffs are rejected during `annual_accounts_filing` exit-review as well as after that capability exits.
3. Exact simulation/archive retirement digests remain required from RF onward while any frozen sibling scope in the operation remains. The prior gap immediately after RF exit is closed; completed-gate resource-deletion evidence no longer substitutes for preservation of current sibling behavior.

`checkArchitecture` supplies the immutable Git source registry and records errors if it cannot be loaded or validated. No production bypass through the optional `sourceRegistry` validation argument was found. The new production-source fixture includes that argument and authentic original scope proofs; its completed-stage source is a controlled fixture, not proof of an actual completed RF gate.

The original frozen `resourceOccurrences` calculation remains separate from strengthened persistence analysis. The immutable baseline file SHA256 is unchanged.

## Independently executed verification

`node --test --test-name-pattern='#151|immutable frozen inventory remains exact' tests/architecture_foundation.test.mjs`

Passed 3 tests, failed 0, exit 0 (983.84 ms): immutable frozen inventory; twelve exact handoffs/four read retirements with near-miss cases including final-filing expiry; and post-RF bounded retirement compositions with early-return negatives for simulation and archive. The latter has a passing unchanged-source control and requires the specific bounded-composition error for mutations.

## Source binding

| File | SHA256 |
| --- | --- |
| scripts/check-architecture.mjs | 322909cc18857711acfbb597548b2faafe77c831a8eefbfd223ad7f064e5bc68 |
| tests/architecture_foundation.test.mjs | 936a679c249218aa90e61a228d6bdcf89064fef573701310c0259896002058ef |
| architecture/compatibility-baseline.json | b8731da45dbf69baafba4e1101dc9a86dcc4ccf11057ebc1fac9b4b059c819ab |

This is independent focused source/test evidence. It does not certify mixed-action product behavior, SQL/RLS topology, browser parity, immutable customer-ready gates, protected integration, or overall #151/#192 completion.
