Spec review: filing lifecycle 9c879ff7

One acknowledged P2 preservation defect remains at the pinned checkpoint; no additional product defect was found in `git diff f9838c60...9c879ff7`.

SPEC-152-CUTOVER-1 (also identified by Standards): `supabase/contract-migrations/20260914012503_company_tax_return_cutover.sql:195–197,223–226` samples effective archive-function EXECUTE after temporarily inheriting the archive owner, then unconditionally grants direct EXECUTE. The inherited privilege makes `had_execute` true, so cleanup skips revoking the new direct grant. Removing borrowed membership consequently does not restore the original ACL. This contradicts the slice’s exact privilege preservation requirement and MODULE.md’s “Temporary migration privileges are restored.” Parent has reproduced the failure and is preparing a separate correction; I verified the source mechanism, without executing SQL.

The remaining static paths preserve six-family content and IDs with count/hash constraints, reject ambiguous classification, delete children before parents, keep internal FKs active, and positively reconcile Accounts rows. The shared phase lock serializes runtime access with migration; static fences reject old writes. Full rollback captures latest owned rows, rejects identity collisions, restores parent-first and fences inactive copies; re-cutover accepts those retained versions. Documents retention uses the owned predicate, and physical transfers suppress only user triggers while checking unchanged Archive generations.

All four relocations are byte-identical. Four new SQL hashes, six evidence artifacts and the eleven recorded race-check bindings verify. The pinned non-DB catalog test passes, including rejection of an uncatalogued deferred table. Database results are inspected historical synthetic evidence (six scenarios and eleven race checks), not independently rerun.

Evidence detail: the race script reads private `probe-filing-cutover.py` for its seed, which is not included in this manifest; parent was asked to bind that dependency in the correction. This limits independent reproduction of the archived harness, not the observed SQL hash binding.

Original requirements remain unchanged. HTTP/browser/provider workflows, dead-code retirement, full source handoff, complete gates and stage exit are explicitly pending and are not reported as defects or granted acceptance.
