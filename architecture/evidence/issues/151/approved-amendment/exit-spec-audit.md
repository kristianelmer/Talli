# Independent #151 exit-envelope Spec gap audit

Read-only repository audit by the delegated Spec reviewer. Fixed point: `91b178c281bcc5fb887a6257d2f72e380199f3e6`; current work-in-progress atop `8f86488cb32e8d50ad8546654e20ea46d9c8885d`. No product edits, database/browser operations, provider calls or hosted mutations were performed. Root owns the currently running database aggregate; this audit does not rely on its eventual result.

## Authority and scope

Read the live #132 resolution with `gh api repos/kristianelmer/Talli/issues/comments/5083588592 --jq .body`. It requires the common entry/characterization/data-cutover/compatibility/release/rollback/exact-exit envelope, and Stage9 specifically requires both web RF CLI bridges, generic RF rows, duplicate TypeScript implementations, adapters and temporary equivalence suites removed. Reviewed #151 requirements, its approved source-contract requirements, the exact16 amendment and existing focused evidence. Previous independent corrections are recorded in `approved-amendment-spec-review.md` / `/tmp/talli-151-d060-spec-review.md`.

## Concrete remaining findings

### 1. P1 — final contract retains generic RF preparation rows

`supabase/contract-migrations/20260909190955_shareholder_register_filing_contract.sql` drops mirror triggers, old production views/routines and both opening projections, then marks `contracted` (line248), but never removes RF records from the six surviving public preparation families. This is not just absent evidence: `test_contracted_legacy_rf_projection_rejects_direct_deletion` in `test_shareholder_register_filing_lifecycle.py:508–515` explicitly expects a public RF preview to remain after CONTRACT. `test_frozen_projection_fixture_cleanup_restores_trigger_modes_on_success_and_rollback` also depends on these surviving mirrors.

This contradicts #151 acceptance5, #132 Stage9 exact exit and the approved amendment's condition that generic relations contain/reveal only uncut sibling families after RF contract. Canonical-first web routing and duplicate suppression solve overlap presentation; they do not retire physical rows, stale legacy reads or their active compatibility debt. Final-schema verification currently endorses the wrong end state for this condition.

### 2. P1 — valid sibling review comments are classified as quarantine and become unwritable

`classify_legacy_row_v1` in capability SQL:200 sets review-comment candidacy from `target='rf1086_preview'`; lines202–211 return `quarantine` if its parent preview is nonRF. Yet the frozen shared action intentionally writes that generic target for tax/accounts previews too (`actions.ts`, retained generic `addFilingReviewComment` branch). During canonical overlap and contract, `sync_legacy_projection_v1`'s write barrier rejects every non-sibling classification (704–708). Thus legitimate sibling comments are rejected by the real database despite the extracted web-action test passing with a mocked writer.

The amendment explicitly preserves the sibling writer, validation, error/effect behavior. Derive comment ownership from the authoritative parent relationship and preserve valid nonRF-parent generic-target comments; continue rejecting/quarantining contradictory company/provenance. Existing owner/reviewer lifecycle tests cover RF parents only. This is source-traced; no database reproduction is claimed.

## Additional unresolved acceptance case

`storage-ownership-inventory.md` explicitly identifies conflicting override `filing` versus `field_target` discriminators. The classifier currently ignores `field_target`, while frozen `annual-readiness.ts:299` treats any `rf1086.` target as RF-relevant. A tax-labelled/tax-parent blocking override with `field_target='rf1086.x'` stays outside the RF source snapshot, although the frozen annual decision treats it as an RF block. This requires an explicit preservation/quarantine/source-input test and documented disposition before the source-handoff criterion is proven. It does **not** authorize assigning all sibling overrides to RF or silently rewriting historical labels. This is a requirements-coverage gap, separated from the two definite implementation findings above.

## Exact cleanup extent

Six shared public preparation families need scoped physical retirement: `filing_previews`, `filing_submissions`, `filing_overrides`, `filing_review_comments`, `authority_permissions`, `authority_test_runs`.

Do not conflate these with:

- Four wholly RF production families: approvals, submissions, events and feedback artifacts were moved physically with retained OIDs. Their public views already disappear in contract; canonical rows, permanent journal, leases and unknown outcomes must remain untouched.
- Two opening projection tables: already disposed/reconstructed through the reviewed RF-share/Ledger-bank split.
- `filing_readiness_snapshots`: remains the one Annual-owned frozen source. Its RF-obligation rows must stay; the exact amendment only retires one web read.

## Bounded contract cleanup and SQL hazards

1. Under the existing transaction, advisory lock and relation locks, snapshot all six source families before any deletion. Capture row identities, exact original JSON, owner classification and parent bindings; reconcile canonical RF rows and quarantine bytes before disposal. Snapshot sibling counts/deterministic hashes, canonical twelve-family/journal/inventory/quarantine hashes and archive-generation state. A missing/mismatched copy must abort the entire contract.
2. Compute retirement identities **before** removing parents. The classifier follows `public.filing_previews`, `public.authority_test_runs` and phase-dependent opening references. Reclassifying after parent deletion can silently change RF into quarantine or misidentify survivors.
3. Quarantine is evidence, not a sibling business record. Preserve every quarantined original row and relationship required for rollback before removing a public projection. Do not discard bad rows, silently repair them, or let them continue as trusted public RF evidence. Verify exact JSON-key/record identity and fail on canonical/quarantine collisions.
4. Temporarily suppress only the captured USER triggers for migration housekeeping (write barriers and archive tracking), restoring each original enabled/disabled/replica/always mode. Do not use `DISABLE TRIGGER ALL`, disable internal FK checks, or weaken FORCE RLS. Follow the existing bounded migration-role read policy/grant restoration pattern where necessary. This must be migration-local, with no extra runtime grant.
5. Delete explicit children first: review comments, overrides and submissions before previews/test evidence; then previews, authority test evidence and permissions. Preview FKs on the three child families are `ON DELETE CASCADE`, so deleting a parent first risks unnoticed child/sibling deletion. Test-evidence references are restrictive. Unknown/new inbound references should stop contract rather than be cascaded or dropped. Preserve siblings byte-for-byte.
6. Restore original trigger/security state, verify zero retired public RF/quarantine projection identities, sibling hashes unchanged, canonical/journal/inventory/quarantine bytes unchanged, and archive-generation state unchanged for pure projection disposal. Retain final public barriers against new RF writes. Mark phase contracted only after assertions succeed.
7. Rehearse both rollback routes and recutover with runtime-created canonical RF rows and unknown journal effects. Phase contract rollback already restores canonical six in an appropriate parent-first order (previews, permission/test evidence, submissions, overrides, comments). Full capability rollback currently restores submissions **before** authority test runs; once public mirrors are actually gone, RF test-authority submissions will violate their FK unless test evidence moves earlier.
8. Both rollback paths currently restore generic canonical copies but replay quarantine only for opening families. Extend generic quarantine replay in correct parent-before-child order, preserving exact original rows and failing closed on identity conflicts. Full rollback must preserve the canonical/new journal and original identities; do not blindly invoke effects. Phase rollback already checks canonical hashes; extend sibling/archive assertions as needed.

## Decisive additional tests

- Seed all six families with RF records, valid sibling records and relevant quarantined relationships; run expand/cutover/contract. Assert exact canonical/quarantine retention, zero public RF projections and zero authenticated RF visibility, unchanged sibling hashes, unchanged permanent production evidence, and no archive-generation change from projection housekeeping.
- Assert direct RF INSERT/UPDATE remains denied after contract while genuine sibling preview/comment/override/permission/test workflows still succeed. In particular create and acknowledge tax/accounts comments with the exact original `target='rf1086_preview'` in all three phases; include reviewer versus read_only and cross-company denial cases.
- Exercise generic FK edges: preview children, test-authority evidence references, and a contradictory/nonRF child referencing an RF parent. Fail closed before deleting a non-retired child or preserve its quarantined original through an explicit complete plan; never rely on cascades.
- Run contract rollback, phase rollback, recutover and full rollback with newly created RF test-authority submissions, exact original IDs/timestamps/XML/hashes, and prepared/unknown production journal entries. Verify canonical OIDs/effects, restored generic original/quarantine data, sibling hashes, ACLs/FORCE RLS/internal FKs/USER trigger modes, and archive-generation state.
- Force a late cleanup error and verify the transaction restores rows, DDL, phase, grants and trigger modes. Cover mismatched canonical copy, missing quarantine original and canonical/quarantine identity collision.
- Replace the lifecycle assertion that retained public RF preview count is1 after contract; it currently proves the opposite of required exit behavior.

## Common-envelope assessment

| Requirement | Current source/evidence assessment |
| --- | --- |
| Entry/predecessor/baseline/inventory | Committed entry gate and inventories exist; earlier independent review verified the fixed point. This audit does not revalidate every entry transcript byte. |
| Fixed-input/statutory behavior | Canonical golden suites retain original outputs; exact historical TT02 receipt exists. Independently ran the narrow108-test suite below successfully. No new authority run. |
| Owned data/one authoritative writer | Canonical production table OIDs/journal and guarded preparation phases are present; final generic-row retirement is missing (finding1). |
| Expand/count-hash/backfill | Fixed-family copy/reconciliation/quarantine exists. Additional cleanup reconciliation is required; runtime proof belongs to root. |
| API/web/deployment-order cutover | Generated owner operations and reviewed canonical-first overlap routing exist. Full current deployment-order/browser evidence is pending root. |
| Restricted roles/RLS/actor/tenant/concurrency | Dedicated roles, FORCE RLS and owned commands exist; previously recorded focused tests are not a fresh complete proof. Sibling classification defect remains (finding2). |
| Permanent journal/unknown rollback | Same physical journal and replay guards remain; reviewed prior focused evidence. Cleanup must not touch these four production families. |
| Rollback/recutover | Shipped phase/full artifacts exist; actual generic retirement adds restoration/quarantine/order requirements above. Current aggregate is root-owned and not certified here. |
| Old code/compatibility/parity cleanup | Eight specified retired implementation paths are absent; no active RF compatibility record remains; baseline bytes match entry. Generic RF data still prevents exit. See golden-suite disposition below. |
| Sibling/audit/notification/archive/support equivalence | Web effect-placement corrections were independently closed. SQL sibling-comment case disproves complete equivalence; archive housekeeping must be tested during actual retirement. |
| Fresh owner + historical browser | Harnesses and existing historical evidence exist. No browser executed in this audit; fresh/current whole journey remains root verification. |
| Builds/security/dependency/advisors | Prior source-bound focused receipts exist. Current final immutable candidate evidence remains necessary. |
| Independent reviews | Prior Standards/Spec correction artifacts exist; this audit adds open findings and does not certify reviewer-authored code. |
| Module/system/catalog/graph agreement | Deterministic dependency evidence updated in WIP; no active RF compatibility record. Final actual-storage truth must reflect completed retirement. |
| Two linked immutable full gates | Requirements ledger currently contains `completeGates: []`; not achieved. This is pending verification, not a code defect. |
| Protected integration/exact-main evidence | Requirements ledger says `PENDING_NOT_STARTED`; not achieved. Preserve serialized source order and production freeze. |

## Temporary-equivalence versus permanent regression disposition

The three files named `test_rf1086_*_equivalence.py` now execute only the canonical implementation/retained CLI against captured immutable vectors. They do not import or execute a second old production implementation. The source capture scripts referenced by the oracle manifest are not retained runtime code. `web-test-retirement-map.md` explains replaced old tests. Therefore their names alone do not prove active compatibility debt. Before exact exit, explicitly identify these as permanent statutory/behavior golden regressions (and rename if useful), preserve their historical provenance, and remove any genuinely temporary dual-implementation harness still found. Do not delete statutory golden coverage merely to satisfy a filename search. Retained `/legacy-rf1086/` HTTP paths directly call the canonical workflow to preserve shipped contracts; no second compatibility workflow remains behind them.

## Independently executed narrow checks

```sh
PYTHONDONTWRITEBYTECODE=1 apps/backend/.venv/bin/python -m pytest -c apps/backend/pyproject.toml apps/backend/tests/test_rf1086_rule_equivalence.py apps/backend/tests/test_rf1086_offline_equivalence.py apps/backend/tests/test_rf1086_cli_equivalence.py apps/backend/tests/test_rf1086_source_facts.py -q
```

Observed **108 passed in4.63s**, zero failures/skips. This covers pure source/golden/offline outputs and retained CLI subprocesses, not database, browser, full release or provider behavior. Earlier independent40 action/transport tests and helper recheck are recorded in the prior review artifact.

Read-only inventory check: eight retired implementations are absent (`rf1086.ts`, `rf1086-submission.ts`, `production-approval.ts`, `production-submission.ts`, legacy backend coordinator/adapter and both opening/shareholder facades). Compatibility registry has zero records attributed to RF. `compatibility-baseline.json` exactly matches entry bytes, SHA256 `b8731da45dbf69baafba4e1101dc9a86dcc4ccf11057ebc1fac9b4b059c819ab`.

## Source binding

These hashes bind the inspected WIP at artifact creation. They are not immutable final-gate receipts; later edits require recheck of affected findings.

| Path | SHA256 |
| --- | --- |
| `supabase/migrations/20260909190548_shareholder_register_filing_capability.sql` | `187f4210ab2df4b230ddfc631875eb6879216b8d8618b4d5b3ecd50764cac05b` |
| `supabase/migrations/20260909190905_shareholder_register_filing_cutover.sql` | `4259df64004a9ba4382db74be357f6a0e411449ede805f7d30d30590d27ed891` |
| `supabase/contract-migrations/20260909190955_shareholder_register_filing_contract.sql` | `413b755cf8f5dc589bfd2827787f4f0cd74db13118d6eca3735c06417c55f8ad` |
| `supabase/rollback/20260909190955_shareholder_register_filing_contract.sql` | `5f9d6a6782bf8aa90b3dfb9786e10e9b767263da5ed58612427d58495060929b` |
| `supabase/rollback/20260909190548_shareholder_register_filing_capability.sql` | `b14ed6bd2224be710adc31e089dea6468cd992f0960ef1494924b504ff056e71` |
| `apps/backend/tests/test_shareholder_register_filing_lifecycle.py` | `d31729e272e67320b0ad28e0f9d43e22ed2784f5fa7b655748553cb5593360b6` |
| `apps/backend/src/talli_backend/modules/shareholder_register_filing/source_facts.py` | `97df7a594b80e5c266926f88d98c65db18817575061d8590bf4d142f89ebd85b` |
| `apps/backend/src/talli_backend/modules/shareholder_register_filing/public.py` | `a9c0c54763ec7311d03b2370b961a6509ed6927ff157a28a252cbf0daee6a674` |
| `apps/backend/src/talli_backend/adapters/postgres_shareholder_register_filing.py` | `bc061d7ba670dbb5ffca303464c4a71c3be5673adbb82de9d424ddbe58349f99` |
| `apps/web/app/actions.ts` | `b407f01296b42bb7cc9f5c5e2e2633dcf97110618a818a84ced38270daa8e4f9` |
| `apps/web/app/lib/annual-readiness.ts` | `23bb49c6c57e69c68418747ca35cb164ea2122892f39de5f9c4ef6e7acccce37` |
| `architecture/compatibility.json` | `c906493085712ce426f3438cb023e132fbc81a1eb203613b61df5e6b84a52caa` |
| `architecture/compatibility-baseline.json` | `b8731da45dbf69baafba4e1101dc9a86dcc4ccf11057ebc1fac9b4b059c819ab` |
| `architecture/evidence/issues/151/requirements.json` | `e87cbace26c8878c7f6d24ff1dd9207ffd06ecbc76b67cf676c2af995d883e3f` |
| `apps/backend/tests/test_rf1086_rule_equivalence.py` | `cbf752d725100c56489ccf1d757068943c430fded3ac97e45a553e20cd870bd8` |
| `apps/backend/tests/test_rf1086_offline_equivalence.py` | `7e7fb1947cb0d855c1785847abe817cc97d808f5c0641fb4a8d804e4188f2a41` |
| `apps/backend/tests/test_rf1086_cli_equivalence.py` | `aff51a4f08bc04dceeb516494ee847bc1b338c64e0f86762b719ef7399a7cd6c` |
| `apps/backend/tests/test_rf1086_source_facts.py` | `4d0c31a460b56bfe48954a19a2d97670cfcab5da1ec0705440fbc29288e475d3` |

No stage, #192, full gate, database aggregate, protected integration or production activation completion is claimed. All live database work remains root-owned.
