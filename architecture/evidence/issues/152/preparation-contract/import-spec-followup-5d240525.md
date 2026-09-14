# #152 TT02 import Spec follow-up: 5d240525

**PASS for the bounded correction. SPEC-152-IMPORT-1 and SPEC-152-IMPORT-2 are closed; no new actionable finding.** Reviewed fixed `b400103d2d7204c9a2154fd953a03ccb00041ad4...5d240525284e6aa92e2875940a638adb110421a6`, excluding uncommitted preparation drafts.

The unchanged original 3,864-byte evidence fixture, containing an ignored 600-level array, again produces the exact frozen projection through pinned predecessor Node 24.20.0. The same original HTTP regression now passes against the fixed FastAPI source. Iterative conversion preserves ordered nested mappings and arrays as immutable facts without exhausting Python's call stack for this input. Independent controls confirm shared references are copied without false cycle detection, caller mutations cannot alter either snapshot, nested mapping writes fail, and ancestor cycles are rejected.

The unchanged original persistence probe exercises all three SQL failure mappings through the actual API with a mocked persistence boundary. Each now produces `COMPANY_TAX_EVIDENCE_PERSISTENCE_REJECTED`; the exact committed presenter returns the original “TT02-evidensen kunne ikke lagres.” message. Projection-invalid and MFA controls retain their distinct original messages. This closes the exported-contract parity issue; UI activation remains pending.

The original HTTP regression plus the committed import, pure-characterization and workspace suites independently report **190 passed in 2.70s**. One initial invocation named a nonexistent private test file and ran no tests; the corrected invocation uses the exact committed characterization filename. The presenter extraction emits only Node's module-type inference warning and passes all assertions.

All adopted evidence artifact hashes match. Requirements, SQL import, named transaction workflow, Audit contract, API source, generated client and OpenAPI remain byte-identical to the reviewed milestone. Thus no SQL policy, atomicity, replay, authorization or provider behavior is changed by this fix.

Verification used committed sources extracted privately; no shared repository, database, browser or configuration mutation occurred. This is bounded acceptance of the two corrections, not exhaustive arbitrary-JSON-depth equivalence or independent SQL execution. The prior 19 SQL cases remain recorded rollback-only synthetic evidence. Owner UI, coordinated cutover, migration reversal, real authorization/browser verification, complete gates and protected integration remain pending; no full-stage or #155 credit.
