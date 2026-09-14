# #152 authority summary — Standards follow-up

**PASS — prior P2 summary-immutability finding closed.**

Immutable scope: `39b72c60ac941e92083dddfc503927a1653cb173...699f4dfa4cabb517529bc6bdc05aaf12eb5b3430`. Bounded Standards follow-up under the existing code-review/ADR/module rules and heuristic baseline; unrelated working-tree changes excluded.

`modules/company_tax_filing/public.py:644` now applies the existing iterative `_freeze_return_fact`, copying and freezing the entire public result. The original executable reproduction now raises `TypeError` on nested assignment. The new public regression additionally verifies immutable nested lists and that later IO-owned source changes cannot affect the returned summary. This satisfies ADR0011's immutable public-contract requirement.

`adapters/local_company_tax_rehearsal.py` explicitly converts immutable mappings/tuples to detached JSON dictionaries/lists for the thin CLI. The CLI applies that conversion only to the public result. No workflow guards, evidence checkpoints, provider sequencing or shared Annual behavior changes. The new CLI regression preserves structured completed-replay fields and checks JSON serialization without provider access.

Independent isolated **256/256 focused tests PASS** using the pinned Python source and Node24 where required. Separately ran actual predecessor and candidate CLI replay with 600-level nested metadata: both preserve depth, leaf and serialized JSON shape. Verified all ten source/evidence bindings in the follow-up manifest. The original private reproduction and both old/new nested-CLI controls are retained with transcripts and exact hashes.

No new actionable standards or heuristic finding. No shared source/config changes, database/provider/browser operations, full gate or stage-exit certification. This closes the P2 only at the fixed revision; the original 39b72c60 review remains historical.
