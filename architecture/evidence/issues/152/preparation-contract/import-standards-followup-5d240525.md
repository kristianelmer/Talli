# Standards follow-up — TT02 import correction

**PASS: prior P2 depth finding closed; no new actionable Standards finding.** Reviewed `b400103d2d7204c9a2154fd953a03ccb00041ad4...5d240525284e6aa92e2875940a638adb110421a6`, one commit, ten changed files. Uncommitted preparation contracts are excluded.

The iterative immutable conversion preserves the original accepted evidence instead of imposing a new depth restriction. The unchanged original HTTP probe now returns 200 at 20, 300, 600 and 1,100 levels. Existing fake-session assertions verify the exact predecessor projection and creation-only Audit ordering. The committed regression also verifies 600 nested tuples. Independent controls confirm detached snapshots, shared sibling references, and rejection of ancestor cycles.

The adapter now distinguishes the three SQL persistence rejections from projection validation using `COMPANY_TAX_EVIDENCE_PERSISTENCE_REJECTED`. Norwegian presentation retains the generic persistence failure message, while malformed evidence and MFA retain their separate messages. The error remains a stable owned code; no SQL diagnostics or evidence bytes are exposed. No authority, persistence, migration or transaction-order change accompanies this correction.

Independent isolated runs passed **32 import/workspace tests plus 157 pure characterization tests (189 total)** and **19 transport tests using pinned Node24.20.0**. All four committed evidence artifact hashes match. The source review remains bounded to ADR0011–0013/module contracts and the retained heuristic smell baseline; no heuristic warrants a finding here.

No database, provider, browser, owner-UI, cutover, release-gate or full-stage acceptance is certified. Exact revisions, source hashes, probe/transcript hashes and prior review bindings are recorded in the accompanying JSON.
