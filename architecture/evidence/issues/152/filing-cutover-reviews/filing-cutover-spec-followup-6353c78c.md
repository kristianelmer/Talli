Spec follow-up: Archive ACL and race-seed binding 6353c78c

PASS for the bounded correction. SPEC-152-CUTOVER-1 is closed at `6353c78cdc32700b92c1431732d9e782fba5612a`; no additional actionable Spec finding was found.

The cutover removes the direct Archive-trigger-function EXECUTE grant and its incorrect effective-privilege cleanup. Trigger creation retains the temporary inherited owner access already established by the migration, whose original membership options are restored afterward. This eliminates the new persistent ACL entry and satisfies the stated exact privilege-preservation requirement. No transfer, classifier, FK, phase, rollback or retention logic changed.

The new lifecycle regression captures the exact Archive function ACL and includes a scenario with neither original direct EXECUTE nor borrowed archive-owner membership. I inspected the recorded predecessor failure at `archiveTriggerAcl unchanged`, the corrected seven-scenario pass, and the repeated eleven race checks. All seven evidence artifact hashes, both source hashes, and current cutover/rollback hashes in the race receipt verify. These are reviewed synthetic local SQL results; I did not rerun the database tests.

The race-seed dependency is now committed as `probe-filing-cutover.py.txt`. Its full SHA-256 matches both the manifest and the race producer’s mandatory assertion before seed extraction, closing the earlier reproduction-binding limitation. The original lifecycle manifest remains unchanged and retains its historical result.

The prior pinned non-DB catalog test remains applicable because this correction does not change catalog discovery or rehearsal ordering. HTTP/browser/provider verification, dead-code retirement, complete source handoff, immutable gates and full stage exit remain outside this bounded receipt. No hosted, provider, full-stage or successor acceptance is granted.
