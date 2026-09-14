# #152 Archive ACL — Standards follow-up

**PASS — the sole pinned 9c879ff7 finding is closed.**

Immutable scope: `9c879ff78b5ec5aa3bb639e5de4a39ab38ef9cfc...6353c78cdc32700b92c1431732d9e782fba5612a`. Bounded Standards follow-up under the existing code-review/ADR/module ownership and heuristic baseline.

`supabase/contract-migrations/20260914012503_company_tax_return_cutover.sql` removes the direct Archive function EXECUTE grant and its faulty effective-permission snapshot/cleanup entirely. Trigger creation uses the already borrowed inheritable owner membership; the existing exact membership restoration remains. This removes the extra durable ACL change without granting replacement privileges or altering reconciliation, phase locks, retained siblings or rollback semantics.

`apps/backend/tests/test_company_tax_return_lifecycle.py:30` now snapshots the actual Archive trigger-function ACL. The new no-direct-grant scenario removes the ambient direct permission and checks exact ACL preservation along with the existing environment checks. The retained red producer substitutes exact predecessor SQL; its transcript fails specifically at `archiveTriggerAcl unchanged`. The fixed-source transcript reports seven passing lifecycle scenarios. The new eleven-check committed-clone race receipt binds the corrected cutover hash and unchanged rollback hash. These are inspected committed runtime results, not database tests rerun by this reviewer.

Independently verified all nine manifest source/artifact hashes and both race SQL bindings. The exact previously external seed producer is now retained and the race runner asserts its SHA before extracting the seed. No new actionable standards finding. Prior isolated Node24 architecture matrices passed 2/2 at 9c879ff7; no checker change occurs here and they were not rerun for this correction.

No shared edits, database/browser/provider operations, full gate, cutover activation, or stage-exit certification. The historical 9c879ff7 review remains unchanged; this follow-up closes its P2 at the fixed revision only.
