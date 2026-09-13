# Independent Standards audit — #151 exit envelope

Read-only audit, 2026-09-10. Fixed entry `91b178c281bcc5fb887a6257d2f72e380199f3e6`; candidate checkpoint and HEAD `8f86488cb32e8d50ad8546654e20ea46d9c8885d`, plus current uncommitted work. Both references were resolved. No repository edits, database operations, browser runs, provider calls, or paid operations performed.

## Standards sources and scope

Applied AGENTS.md, CONTEXT.md, domain guidance, ADR0010/0011/0013, capability/system manifest contracts, and the code-review smell baseline. Read GitHub issue #132 directly through `gh issue view 132 --repo kristianelmer/Talli --json body,comments`, including its mandatory common envelope and stage 9. Source review covered stage-level manifests, catalog/ownership, deterministic dependency evidence, generated HTTP/client operation declarations, CLI/TypeScript retirement, contract/rollback cleanup, and evidence-status consistency. Prior exact-amendment findings were independently closed in `/tmp/talli-151-amendment-standards-review.md`; this audit does not reopen them.

## Actionable findings

1. **[P2] Contracted RF runtime retains temporary overlap implementations.** `supabase/migrations/20260909190548_shareholder_register_filing_capability.sql:906`, `:953`, `:965`, and `:992` retain public-schema writer routing in `insert_preparation_row_v1`, `acknowledge_review_comment_v1`, `confirm_filing_permission_v1`, and `record_simulation_v1`. The contract migration does not replace these definitions. Its AFTER projection-trigger removal also leaves the original `sync_legacy_projection_v1` definition installed through the required BEFORE write barrier; that definition still contains legacy-to-canonical mirroring/quarantine/delete code (`:692–729`). Contract rollback recreates projection triggers using those retained definitions (`supabase/rollback/20260909190955_shareholder_register_filing_contract.sql:487`) rather than restoring overlap functions. This conflicts with #132 common exact exit and stage 9's removal of temporary adapters, and #151 A5's active compatibility cleanup. Install canonical-only preparation functions and a barrier-only implementation at contract; make rollback restore overlap definitions before recreating their triggers. This is an installed-code cleanup finding, **not** evidence of two live authoritative writers or an authorization bypass in contracted phase. Keep the generic-row RF rejection barrier and frozen sibling behavior.

2. **[P2] Technical migration inventory omits the artifacts owning RF bookkeeping.** `architecture/backend-system.json:436–438` declares RF `migration_inventory`, `migration_quarantine`, and `migration_state` technical tables, but `technicalOwnership.migrations` (`:440` onward) contains none of the RF expand/cutover/contract files. Those tables are created by RF expand (`supabase/migrations/20260909190548_shareholder_register_filing_capability.sql:61–78`) and their state is changed by cutover/contract. ADR0011 assigns this bookkeeping to the backend-system manifest; ADR0013/#132 require manifests/documentation and migration ownership to agree. Add the RF lifecycle migration paths to the technical manifest and synchronize its documentation inventory. Capability ownership of the 12 RF business relations and Ledger ownership of the original bank input should remain unchanged.

## Reviewed consistency and limits

- RF's public capability owns 12 business relations; the catalog separately declares three technical migration tables and Ledger's `opening_bank_inputs`. Shared surviving generic filing relations remain legacy-business; historical opening-bank identity is not falsely aliased wholesale to RF.
- RF backend/web module manifests and system workflow register the generated preparation, review, simulation, approval, archive, and retained Send/recovery contracts. Retained `/legacy-rf1086/` endpoint names preserve shipped HTTP contracts; they do not identify a second legacy implementation.
- The deleted Python compatibility owners and web feature/rule/bridge files have no live application imports in the searched source. `holding_cli/main.py` consumes canonical RF public APIs; retained CLI subprocess integration tests exercise a supported user CLI, not the retired web-to-Python bridge.
- Oracle-based canonical regression tests do not execute a duplicate old implementation. Their historical `equivalence` naming alone was not treated as forbidden temporary runtime debt.
- The current requirements ledger truthfully leaves criteria, full fresh browser/database proof, two immutable complete gates and protected integration pending. Historical checkpoint receipts and superseded proposal statements are labeled historical; they are not current completion evidence. These outstanding gates are pending work, not source defects discovered by this review.
- Generated artifacts/dependency declarations were inspected as sources; no generation reproducibility, whole-tree architecture run, database topology, fresh browser flow, security/advisor runtime, or protected-main state is certified here. Root owns the live database aggregate and final gate verification.

## Source bindings

SHA256 values below bind the inspected working-tree envelope; this is not an immutable revision or full exit attestation.

| Path | SHA256 |
| --- | --- |
| `AGENTS.md` | `c4530bac3939f37053438b48a3dad2ea6e99d04481480ef61bee71d3dc81d4af` |
| `CONTEXT.md` | `e781ac1914abc8492435e6aa9bf2b96872f7f1941673892a3841c0b3e1c4d0c9` |
| `docs/agents/domain.md` | `0b66c33560f91373a7b268f3acf2c3d992e6a77cf5dc60acdc66efb4dc34a982` |
| `docs/adr/0010-use-a-two-application-modular-monorepo.md` | `977ebb0329fea302f695fb029b894d139360a4123b5220bb1a41f3e0a9b81c0a` |
| `docs/adr/0011-enforce-capability-owned-contracts-data-and-workflows.md` | `276f8e5d20a18ff1f20c8ec318000a13b009823c813b5f5c2a70f22cebbff874` |
| `docs/adr/0013-enforce-the-architecture-and-migrate-serially.md` | `8709d4311ba994c48521cd8d4a4ea5575235562a2bdb41c56c53d257d9282482` |
| `architecture/backend-system.json` | `c85bb4f9592dd996a1df212b1bd07416723a32f2130fa20b99021cc5f6f69632` |
| `architecture/BACKEND-SYSTEM.md` | `b4759fb3c8c29da94dcdf8f0eca97f26b7282d8401c76595d627bac6f102ebcd` |
| `architecture/database-catalog.json` | `336827088e88d2e2c0dc9ed18a237e8352bb68bb25866b06a5fa523d9c3a6822` |
| `architecture/company-archive-sources.json` | `daa47be25df45bba2bea3c6cb09ac123ea4f3cdb8e7be5f2a6327e331b620a52` |
| `architecture/compatibility.json` | `c906493085712ce426f3438cb023e132fbc81a1eb203613b61df5e6b84a52caa` |
| `architecture/compatibility-baseline.json` | `b8731da45dbf69baafba4e1101dc9a86dcc4ccf11057ebc1fac9b4b059c819ab` |
| `architecture/dependency-evidence.json` | `ef8ed8f51d568b73aa782d024be1911e341bec091126ebbaeea8ee8184696ec6` |
| `apps/backend/src/talli_backend/modules/shareholder_register_filing/module.json` | `d864ca6ed3e58b30dbf57e0125b96701c97a2f71a3817161d500eab77ec5c157` |
| `apps/backend/src/talli_backend/modules/shareholder_register_filing/MODULE.md` | `361137ee07491cf0a12cc6d06470fe7f664cfb64b92f7796966a773f49ccd882` |
| `apps/backend/src/talli_backend/modules/ledger/module.json` | `7d48c738574150810e08dda81d543636525537a8e4efe06db2acd814382bdc2a` |
| `apps/web/features/shareholder-register-filing/module.json` | `841bb94b614ad18ed074af443e3de9e53596d812aaa953754719c2713d0cab3f` |
| `apps/web/features/ledger/module.json` | `fa007a3d8f2f911564e369111df912a9331133f4507a07447de6db987c54201f` |
| `contracts/openapi/talli-v1.json` | `2cfca140bee4fcf3d88c33c8d6527e16a18f7ca3e851b20a1b115194949cdbd9` |
| `packages/talli-api-client/src/generated/client.ts` | `ee70c653d820b07771a61bfae5d3063fa9efbd94f8abe566a5f6253f7f4555d5` |
| `scripts/generate-api-client.mjs` | `22db2155e7e9c7ea6752708ac79747bc29a929389285897768aa92fabf9a5e7f` |
| `scripts/check-architecture.mjs` | `322909cc18857711acfbb597548b2faafe77c831a8eefbfd223ad7f064e5bc68` |
| `scripts/rehearse-authority-topology.mjs` | `134bb966f43facbec79de8e5fb742a12478aa3686f54716e3d6e3305a88847e5` |
| `scripts/test-supabase-local.sh` | `2f892e509998c1054224df4bd4ccb833933b7a165b908e21420f7ca94ae3ddb4` |
| `supabase/migrations/20260909190548_shareholder_register_filing_capability.sql` | `187f4210ab2df4b230ddfc631875eb6879216b8d8618b4d5b3ecd50764cac05b` |
| `supabase/migrations/20260909190905_shareholder_register_filing_cutover.sql` | `4259df64004a9ba4382db74be357f6a0e411449ede805f7d30d30590d27ed891` |
| `supabase/contract-migrations/20260909190955_shareholder_register_filing_contract.sql` | `413b755cf8f5dc589bfd2827787f4f0cd74db13118d6eca3735c06417c55f8ad` |
| `supabase/rollback/20260909190955_shareholder_register_filing_contract.sql` | `5f9d6a6782bf8aa90b3dfb9786e10e9b767263da5ed58612427d58495060929b` |
| `pyproject.toml` | `c4d43e59008aa2414a345d4fb52b50f5100e003ab7e1468b29f8ef268de6cb2e` |
| `holding_cli/main.py` | `9131c8ff8d0534ab1dd748576b2f81c4ecffa748ce9b71b7515c362a39fee545` |
| `package.json` | `6bed7d637de215aae4f8790ac128539d20bb51f36802fb18ae4415cd5a0ed782` |
| `architecture/evidence/issues/151/requirements.json` | `e87cbace26c8878c7f6d24ff1dd9207ffd06ecbc76b67cf676c2af995d883e3f` |
| `architecture/evidence/issues/151/web-test-retirement-map.md` | `19872a87a5f1ab151ffba3820ec909741c962301668b4af496778ebf63c30434` |
| `architecture/evidence/issues/151/cli-retirement-validation.md` | `56c8f2ec94e1ddd5835f4e2a05d5025332f10044480c7613339684b4d9be41af` |


## Follow-up review — provisional cleanup correction

Read-only follow-up on 2026-09-10. **Runtime compatibility-code finding is closed at source level.** Parsed and compared the seven replacement functions (four preparation functions, classifier, projection/barrier, and `backend_system.admit_rf_opening_scope_v1`). After normalizing only `CREATE OR REPLACE` to `CREATE`, all seven rollback definitions match their expanded originals exactly. Contracted preparation functions differ only by selecting the canonical schema/removing the unreachable public writer branch; existing validation, owner/MFA/readiness checks, columns, conflict updates and returns remain. The classifier selects canonical opening identity without a phase switch. Admission removes only the legacy actor-null allowance. The contracted trigger is a BEFORE-only sibling barrier with no mirroring, quarantine insertion or canonical-row mutation body. It retains rejection of RF-classified new/old rows.

These are `CREATE OR REPLACE` of the existing function signatures, retaining identity, ownership and existing ACLs. The patch does not add function EXECUTE grants. Rollback explicitly restores overlap implementations before installing projection triggers. Static expansion/cutover/contract definition reconciliation found 54 surviving parsed functions and no remaining `legacy_overlap`, `canonical_overlap`, or public opening-table branch in their bodies. This is source proof, not live catalog or role-execution proof.

**Technical migration inventory finding is partially closed:** JSON now includes the three RF lifecycle migration paths. At this observation, `architecture/BACKEND-SYSTEM.md`'s `architecture-inventory.technicalMigrations` still omits those same three paths and must be synchronized before the finding fully closes.

The topology helper adds the already-published launch-signoff contract rollback before authority rollback. Its corresponding model test now models contract policy consumption and rollback restoration across workspace → rollback → final recutover. The helper is loopback-only and this change does not modify the signoff policy definitions or broaden provider behavior. No runtime result for this correction is certified here.

Generic-row deletion/hash/provenance logic and rollback row restoration were intentionally left to the separately assigned SQL-safety reviewer; this follow-up does not certify that concurrent change.

Follow-up source bindings:

| Path | SHA256 |
| --- | --- |
| `supabase/migrations/20260909190548_shareholder_register_filing_capability.sql` | `fa29bbe4b4c7a498554e18bf3f71ede4146d616e414e48b9290815d52fc99e15` |
| `supabase/migrations/20260909190905_shareholder_register_filing_cutover.sql` | `4259df64004a9ba4382db74be357f6a0e411449ede805f7d30d30590d27ed891` |
| `supabase/contract-migrations/20260909190955_shareholder_register_filing_contract.sql` | `b70e56d4dbf03bd83fcb6b932f9d0e80543929ef42ce0f711eb3f6c1b585a342` |
| `supabase/rollback/20260909190955_shareholder_register_filing_contract.sql` | `fa34b43318cbfeb138d27f1791d04f46ac23bc1c686d079a7bd58315680b0a42` |
| `architecture/backend-system.json` | `a93be96bee1109c7e3a903cb68df657cdd899b8bc34a018eb3da3322ad85274d` |
| `architecture/BACKEND-SYSTEM.md` | `64b031fae774221db8b3cc00d1790a560c72297451e670981cee62988dd1dbbc` |
| `scripts/rehearse-authority-topology.mjs` | `16ed9fed26d1b2dfea4e7673ae14319c18ccce8d6809fdade6639c287c9126a3` |
| `tests/ci_release_gate.test.mjs` | `29ef0efca7ad1e32fa11c58f91aa043528778c1587749b85e397191b9e7dcf67` |


## Closure — documentation inventory synchronized

Read-only verification, 2026-09-10: parsed `architecture/BACKEND-SYSTEM.md`'s embedded JSON inventory and compared `technicalMigrations` with `architecture/backend-system.json`'s `technicalOwnership.migrations`. The sorted lists match exactly, with no missing or extra entries, including all three RF lifecycle artifacts. **The technical migration inventory finding is now closed.**

Both exit-envelope Standards findings are therefore closed within the reviewed source scope. The earlier canonical-definition conclusion remains bound to unchanged expand/contract/contract-rollback hashes below: all seven restored overlap definitions matched expand, canonical replacements removed the dormant branches, and existing function identities/ACLs were retained. This closure does not re-review subsequent full-rollback UUID/archive corrections assigned to the Spec reviewer. Root reports the architecture check passed in `/tmp/talli-151-exit-architecture2.log`; this follow-up independently establishes inventory equality, not a new runtime or complete-gate result.

Current source bindings:

| Path | SHA256 |
| --- | --- |
| `architecture/backend-system.json` | `a93be96bee1109c7e3a903cb68df657cdd899b8bc34a018eb3da3322ad85274d` |
| `architecture/BACKEND-SYSTEM.md` | `64b031fae774221db8b3cc00d1790a560c72297451e670981cee62988dd1dbbc` |
| `architecture/dependency-evidence.json` | `ef8ed8f51d568b73aa782d024be1911e341bec091126ebbaeea8ee8184696ec6` |
| `supabase/migrations/20260909190548_shareholder_register_filing_capability.sql` | `fa29bbe4b4c7a498554e18bf3f71ede4146d616e414e48b9290815d52fc99e15` |
| `supabase/contract-migrations/20260909190955_shareholder_register_filing_contract.sql` | `b70e56d4dbf03bd83fcb6b932f9d0e80543929ef42ce0f711eb3f6c1b585a342` |
| `supabase/rollback/20260909190955_shareholder_register_filing_contract.sql` | `fa34b43318cbfeb138d27f1791d04f46ac23bc1c686d079a7bd58315680b0a42` |
