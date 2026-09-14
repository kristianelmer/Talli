# #152 preparation Spec follow-up: 8af134bf

**PASS for the bounded correction. SPEC-152-PREP-1 is closed; no new actionable finding.** Reviewed fixed `6e67ba3e0759641db845449756306df444a3a9b1...8af134bf673ea0969f31856b84bde2246d615835`, excluding uncommitted owner-action and compatibility work.

The named acknowledgement workflow now compares the returned record identity with the requested identity while its transaction remains open. A mismatch raises `COMPANY_TAX_DEPENDENCY_UNAVAILABLE` before return, causing rollback; the existing API identity guard remains intact. This places the rejection within the application transaction required by ADR0011 and preserves successful acknowledgement behavior.

The original independent regression runs unchanged against privately extracted committed sources and passes: actual FastAPI returns HTTP 503, while the persistence double records **begin → acknowledgement-write → rollback**, with no commit. Together with the 25 committed preparation cases, independent execution reports **26 passed in 2.41s**. These include valid controls, hard-review rejection, session binding, and MFA/unavailable distinctions.

All adopted artifact hashes match. The SQL, adapter, API, generated client, transport, OpenAPI, web actions and requirements remain byte-identical to the earlier reviewed milestone. Only the application check and its regression are executable changes; other changes preserve review/test evidence.

This verifies malformed-result transaction ordering through an injected persistence result, not a real-database corruption event. No shared repository, database, browser or configuration mutation was performed. The original 60 recorded SQL checks retain their 45-prior/15-new, synthetic-claims, rollback-only scope. No provider, owner UI activation, durable cutover/rollback, concurrency, real JWT/MFA, or full-stage acceptance credit is granted.
