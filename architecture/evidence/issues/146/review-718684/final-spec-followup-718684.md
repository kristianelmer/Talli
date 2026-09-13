# #146 rehearsal-fix Spec review

**PASS_BOUNDED_REHEARSAL_FIXES — no actionable regression found.** Reviewed `1d440ae4471c4c377d951650595b0828cc13d9b2...7186841f3286c53fdb5c838963703de0efac17cc` (one commit, 26 files). Source hashes are in sibling `final-spec-followup-718684-bindings.json`.

The Documents-owned locking function is byte-identical after relocation from Tax expansion to cutover. Its same-company/year and verified-owner checks, read/locking policies and `WITH CHECK(false)` remain intact. Cutover restores the previous schema-CREATE privilege; all changes share the enclosing migration transaction. Expansion now leaves the predecessor Documents schema free of this function. Expansion-only Tax rollback conditionally revokes the binding only if it exists, and the new regression explicitly exercises that absence. The committed lifecycle log reports22 passes; I inspected the source/log without database execution.

Archive changes update only the obsolete fixture expectation: the exact owned Tax read is removed from the frozen query-chain list and supplied through the authenticated Tax source mock. Remaining chains, RF history, effect order and authentication guards remain asserted. The added tests preserve all thirteen original fields including nested payload and timestamp, and reject unavailable Tax source before export completion. **All20 tests passed independently**, zero skips, Node25.6.1, from an outside-repository pinned archive.

The browser extension retains the prior lost-response→preview-outage→same-ID recovery assertions and additionally posts payment through the wizard and refund through the workspace. The committed log reports one passing full-stack case; this is inspected evidence, not an independent browser run.

Verified all **157 predecessor source hashes** against entry20999 and all12 adopted artifact hashes. Deployment proofs retain their explicit1d440 source/migration binding, synthetic old-app authentication and local-only limits. The Node25 attribution correction and separate Node24 rerun remain distinct. The failed1d440 gate is clearly recorded as FAIL with no exit credit.

Original requirements and compatibility registry bytes are unchanged. Fresh full-stack aggregate, immutable gate pair and protected integration remain pending. No database, browser, provider, repository, Git-state or generated-file mutation occurred. This review grants no full #146 or #152 acceptance.
