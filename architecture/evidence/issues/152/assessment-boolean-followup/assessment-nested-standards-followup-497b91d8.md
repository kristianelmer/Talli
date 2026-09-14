# Standards follow-up — nested assessment facts

**Changes requested: one residual P2 input-boundary defect.** Reviewed `e2dfdf5475af3d051ad782650314839a47105451...497b91d8643b7639ff1157b66761fc8c2590b850`, four files. Separate pure/CLI truthiness and uncommitted web-consumer work are excluded.

The follow-up correctly rejects non-array ledger lines, non-object line elements, non-Boolean Annual answers/no-activity flags, and non-array readiness risk flags. All **339 focused backend tests passed independently** against extracted source. OpenAPI bytes remain unchanged and the committed test-artifact hash matches.

**P2 — Validate the consumed account discriminator** (`apps/backend/src/talli_backend/main.py:1057`). The new nested validation accepts every dictionary line, including malformed lines without an account. Actual pinned FastAPI receives `ledgerEntries: [{entry_type: "admin_cost", lines: [{debit: 100, credit: 0}]}]` and returns 200 with `adminCosts: 0`, `taxBasis: 0`. Adding `account: "7770"` returns the expected 100/-100; `account: null` is also accepted. Thus the same silent-zero failure remains for a malformed object shape. Require a string account at this HTTP boundary and add absent/null controls, leaving the separately characterized pure/CLI behavior untouched.

This is a concrete validation defect under ADR0012’s governed API boundary and the module’s documented malformed-fact rejection, not a heuristic smell judgment. No additional ownership/authority regression was identified: this delta adds transport validation only and opens no business transaction.

The reproduction uses real FastAPI with the existing fake session factory. No shared source/runtime/database/browser/provider mutation, cutover, full-stage or release-gate verification occurred. Exact source, evidence, probe and transcript hashes accompany this report.
