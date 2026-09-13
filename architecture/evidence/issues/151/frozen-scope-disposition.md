# #151 exact frozen-scope disposition

Read-only proposal at `27ba9b6c954505808ef4c1ce75e94eae9bb5d84f`, 9 September 2026. No source/registry/baseline changes, tests, DB/provider operations or #151 claim. Root must assess this proposal before any approval question. This supersedes the broad conflict description in the earlier cutover plan: semantic RF ownership and routine reversible cutover choices are already authorized by #132/#151; a manifest edit alone creates no approval requirement.

Exact source inventory: `/tmp/talli-151-frozen-scope-inventory.json`, produced by read-only TypeScript AST traversal. It contains complete source call chains, line numbers and tuple metadata for 37 affected/adjacent scopes. Every current occurrence count equals its immutable-baseline count. Counts mean `.from`/`.rpc` occurrences in the named operation, not rows or executions.

## Identity conventions

Scopes have no independent `id` field. Their exact identity is `(recordId, path, rule, resource, operation)`; tables below specify every component using these path/rule constants:

- **A:** `apps/web/app/actions.ts`.
- **S:** `apps/web/app/lib/supabase/server.ts`.
- **Rule:** `direct-web-business-persistence` for every tuple below.
- Resource names are literal `table:…` values, not proposed names. `n/n` means frozen/current occurrence count. Source lines are at the candidate above.

## Clash 1: RF review/simulation effects recorded under future #149

All rows in this table have record **`compat-annual-compliance-persistence`**, capability `annual_compliance`, removal issue `#149`.

| Path | Resource | Operation | Count | Current effect / disposition |
| --- | --- | --- | --- | --- |
| A | `table:filing_review_comments` | `acknowledgeFilingReviewComment` | 2/2 | L1749 SELECT by comment ID, L1764 UPDATE acknowledgment; rejects hard-block acknowledgment. Keep the sibling implementation and its two calls; RF uses the owned RF contract. No whole future writer migration. |
| A | `table:filing_overrides` | `addFilingOverride` | 1/1 | L1488 INSERT copies selected preview company/year/filing plus validated target/values/risk/reason and owner confirmation. Preserve this one call for uncut sibling rows. |
| A | `table:filing_review_comments` | `addFilingReviewComment` | 1/1 | L1712 INSERT copies preview company, writes generic target `rf1086_preview`, advisory/hard_block and author. Preserve sibling behavior and one call. |
| A | `table:filing_overrides` | `confirmSimulatedRf1086Submission` | 1/1 | L1365 SELECT company/year/exact preview label/risk=block. RF-only simulation prerequisite; retire this web read when the RF command owns its own override facts. |
| A | `table:filing_readiness_snapshots` | `confirmSimulatedRf1086Submission` | 1/1 | L1339 SELECT exact company/year/ASCII RF obligation; requires stored `ready`. Preserve the existing annual-source fact/availability behavior through a declared immutable query input; do not move the annual writer or silently replace the check with browser facts. This web read must leave the RF coordinator. |
| A | `table:filing_review_comments` | `confirmSimulatedRf1086Submission` | 1/1 | L1352 SELECT preview/hard_block. RF-only prerequisite; retire this web read with RF review ownership. |
| A | `table:filing_readiness_snapshots` | `queueDeadlineReminders` | 1/1 | L1196 SELECT scoped annual readiness; preserve exactly. No notification/annual policy relocation. |
| A | `table:annual_data` | `refreshAnnualReadinessSnapshots` | 1/1 | L4707 SELECT company/year annual answers; preserve exactly. |
| A | `table:filing_overrides` | `refreshAnnualReadinessSnapshots` | 1/1 | L4702 SELECT all company/year override rows. Keep one sibling/annual-source read; RF facts may be combined through its public projection with equivalent ordering/error behavior. |
| A | `table:filing_readiness_snapshots` | `refreshAnnualReadinessSnapshots` | 1/1 | L4786 UPSERT all evaluated obligations; remains the one frozen annual aggregate writer. |
| A | `table:holding_actions` | `refreshAnnualReadinessSnapshots` | 1/1 | L4685 SELECT company/year legacy actions; preserve exactly. |
| S | `table:filing_overrides` | `listFilingOverrides` | 1/1 | L980 SELECT company IDs, descending creation time; preserve sibling call and row shape. Merge RF published results in outer transport composition; leave this legacy function untouched where possible. |
| S | `table:filing_readiness_snapshots` | `listFilingReadinessSnapshots` | 1/1 | L1066 SELECT annual projections, descending updated time; preserve exactly. |
| S | `table:filing_review_comments` | `listFilingReviewComments` | 1/1 | L1083 SELECT company IDs, descending creation time; preserve sibling call/shape, compose RF results outside it. |

RF override/review policy and data ownership itself needs no fresh approval: #132 explicitly includes review and overrides in stage9, and the accepted control-plane disposition selects RF rows from generic tables. Keeping unchanged generic functions for non-RF rows is not a second RF writer once contracted SQL rejects RF rows and the RF UI uses the generated RF command. Do not retain dead calls just to satisfy counts.

The future-read disposition inventory is **three tuples**, all in `confirmSimulatedRf1086Submission`; this is not automatically a request for three new exceptions. It is an RF coordinator, not a sibling coordinator. Its associated current-RF tuples are A/`table:filing_previews`/same operation (1/1, L1331 SELECT original preview) and A/`table:filing_submissions`/same operation (1/1, L1402 simulation UPSERT by preview). Those two current tuples retire normally under #151. The two RF-owned future reads do not authorize moving all shared override/comment data. The annual readiness read does not acquire annual aggregation ownership.

## Clash 2: current #151 scopes include non-RF sibling calls

All rows below have record **`compat-rf1086-persistence`**, capability `shareholder_register_filing`, removal issue `#151`. Each has count **1/1**. These are the **12 mixed tuples**, including the two preview reads used by generic review/override writers.

| Path | Resource | Operation | Source effect |
| --- | --- | --- | --- |
| A | `table:filing_previews` | `addFilingOverride` | L1462 SELECT id/company/year/filing by arbitrary preview ID. No RF filter. |
| A | `table:filing_previews` | `addFilingReviewComment` | L1703 SELECT id/company by arbitrary preview ID. No RF filter. |
| A | `table:authority_permissions` | `confirmAuthorityPermission` | L4905 UPSERT any of three validated obligations; step-up first, same owner attestation and production flag. |
| A | `table:authority_test_runs` | `recordAuthorityTestEvidence` | L4978 INSERT any of three validated obligations, test/manual_evidence environment and validated imported references/hash. No provider operation. |
| A | `table:filing_submissions` | `queueDeadlineReminders` | L1195 SELECT company/year submissions for all obligations before existing reminder policy. |
| A | `table:authority_permissions` | `refreshAnnualReadinessSnapshots` | L4714 SELECT all company obligations. |
| A | `table:filing_previews` | `refreshAnnualReadinessSnapshots` | L4715 SELECT all company/year previews. |
| A | `table:filing_submissions` | `refreshAnnualReadinessSnapshots` | L4716 SELECT all company/year submissions. |
| S | `table:authority_permissions` | `listAuthorityPermissions` | L1100 SELECT company IDs, descending updated time, all obligations. |
| S | `table:authority_test_runs` | `listAuthorityTestRuns` | L1117 SELECT company IDs, descending recorded time, all obligations. |
| S | `table:filing_previews` | `listFilingPreviews` | L872 SELECT company IDs, descending created time, free-text filing family. |
| S | `table:filing_submissions` | `listFilingSubmissions` | L889 SELECT company IDs, descending updated time, simulation/test imported sibling evidence. |

This is actual source behavior, not a hypothetical future API: the shared `ObligationWorkspace` wires `confirmAuthorityPermission` and `addFilingReviewComment` for its supplied obligation; the workspace generic forms accept all three obligations. Existing tax import persists `filing_submissions` with `filing='skattemelding for AS'`. Dropping these calls/functions wholesale would drop sibling access. Assigning the whole generic relation to RF would contradict the accepted semantic split.

RF can add its owned branch/API and combine public RF read results while preserving each existing sibling call exactly once. The legacy relation must contain/reveal only uncut sibling families after RF contract; legacy INSERT/UPSERT/UPDATE paths must reject RF-classified rows. Scope/permission rechecks remain server-owned, never decided from a browser-provided discriminator. Do not relocate the sibling writer or change its validation/audit behavior.

That preserves behavior but does **not** by itself satisfy today's literal registry rule: a current #151 record cannot remain at exit, and a removed tuple must have zero source occurrences. This is a bookkeeping conflict between accepted semantic row ownership and frozen table-level tuple accounting, not authority to migrate all three filings.

## Adjacent effects that must remain fixed

For record **`compat-audit-persistence`**, capability `audit`, removal `#155`, path A/rule above/resource **`table:audit_events`**, these eight operations each have **1/1** INSERT after their existing effect:

`acknowledgeFilingReviewComment` L1772; `addFilingOverride` L1506; `addFilingReviewComment` L1724; `confirmAuthorityPermission` L4921; `confirmSimulatedRf1086Submission` L1437; `queueDeadlineReminders` L1238; `recordAuthorityTestEvidence` L4983; `refreshAnnualReadinessSnapshots` L4806.

For record **`compat-notification-persistence`**, capability `notifications`, removal `#156`, path A/rule above/resource **`table:notification_outbox`**, `queueDeadlineReminders` has **2/2**: L1197 SELECT existing notices and L1214 conditional batch INSERT. Preserve both, all dedupe/planning behavior and existing audit placement. The proposal does not move these effects into/out of a transaction, add a writer, or authorize provider delivery.

## What is routine versus the finite ADR remainder

Routine and already authorized: RF semantic data split; backend RF review/override/simulation policy; owned public projections; generated RF transport; preserving sibling generic call occurrences; keeping annual aggregation, audit and notifications unchanged; updating manifests/catalog to truthfully describe those owners. Existing ADR0013 active-resource authorization/RLS seams may retire exact calls whose entire resource is demonstrably active/exited-owned. No approval follows merely from adding a source-owned contract or correcting metadata to represent already-approved ownership.

Today the catalog cannot truthfully assign `table:filing_previews`/`filing_overrides`/`filing_review_comments` wholesale to RF while their non-RF rows remain: `check-architecture.mjs:1461–1499` maps a resource to one whole catalog entry and rejects a compatibility alias colliding with an extant public table. Its deletion check at L2090–2168 requires zero resource occurrences and active/exited ownership for future tuples. Retained tuples require the original count; altered operation text needs a deletion-authorized operation (L2248–2279).

The **12 mixed-tuple handoffs** are the concrete uncovered remainder: their existing literal calls must survive for siblings, yet their current record must exit at #151, and adding them to a future record is expressly forbidden by ADR0013:50–93. This needs a finite attribution amendment; ordinary manifest editing alone cannot authorize it.

The three intrinsic reads have different semantic owners but the same literal enforcement obstacle:

- `table:filing_overrides` and `table:filing_review_comments` in the RF-only coordinator consume RF-owned facts explicitly assigned by #132. Their semantic migration is already approved; no re-approval of RF review/override behavior is requested. But the existing catalog resources still name the entire surviving public tables, including sibling/annual rows. They cannot truthfully be RF-owned, and aliases from the new RF-owned tables collide with those public entries. Consequently the existing future-tuple deletion check rejects both 1→0 removals despite the approved RF row semantics. A generic row-aware authorization exception would be broader than this fixed pair; the minimal proposal explicitly accounts for these two known deletions.
- `table:filing_readiness_snapshots` consumes a stored annual aggregation fact. Its replacement is an unchanged immutable query/public input from that single frozen annual source, as #132 permits for dependencies; it moves no writer or readiness rule. Its resource remains #149-owned, so the same future-tuple deletion check also rejects the literal 1→0 web removal. Do not declare it RF-owned to evade the check or silently replace its stored-ready prerequisite with newly computed or browser-supplied facts.

Therefore the concrete minimum under the current whole-resource catalog and zero-occurrence rules is **12 exact attribution handoffs plus three exact read deletions**. The 15-item proposal changes frozen-scope bookkeeping, not the already-approved RF ownership or sibling business behavior. The two RF-owned reads cannot use the existing exception without falsely widening resource ownership or introducing a broader new row-aware exception; the annual read has an additional requirement to preserve its genuine future-owner query seam. This necessity follows from the precise current representation and ADR0013's no-unlisted-future-shrink rule, not merely from a manifest needing edits.

## Exact proposed exception, not applied or approved here

1. **Twelve exact residual handoffs:** permit only the 12 listed baseline tuple identities to be represented in existing `compat-annual-compliance-persistence/#149` as shared legacy annual-workspace transport after their RF row family is gone. This is registry attribution of pre-existing sibling calls, not assignment of tax/accounts business state to Annual Compliance. Preserve original path/rule/resource/operation and count1. Leave generic sibling implementation in place; allow only RF delegation/result composition and necessary source-authorization plumbing. No unlisted resource or occurrence may be added. Keep sibling validators, side-effect order, actor checks, return shape and failure behavior equivalent.
2. **Three exact read deletions:** permit deletion only of the three `compat-annual-compliance-persistence` tuples with path A/rule `direct-web-business-persistence`/operation `confirmSimulatedRf1086Submission` and resources `table:filing_overrides`, `table:filing_review_comments`, `table:filing_readiness_snapshots`, each frozen/current count1. Remove them atomically with the RF coordinator's two current tuples. Require zero remaining direct/dynamic web occurrences in the retired coordinator. Replacement review/override facts come from RF's owned public contract; stored readiness comes through the same frozen annual source's declared immutable query/public input. Preserve exact scope, stored-ready prerequisite, unavailable/error behavior and annual source ownership. No annual writer/rule migration or sibling override/review policy change is included.
3. **Timing/removal:** the handoff applies only at #151 RF cutover after count/hash/row-ownership proof; it is not permission to leave RF rows or writes in generic stores. Each sibling row family still leaves at #152/#153. Remove its remaining generic persistence calls as soon as the last relevant source owner cuts over; do not retain such calls until #149 merely because the wrapper serves the annual workspace. #149 still owns only its annual aggregation and final wrapper cleanup. No source stage advances out of order.
4. **Enforcement:** keep `architecture/compatibility-baseline.json` byte-identical. Record a finite original-record→allowed-record map for the 12 handoffs and the three exact deletions; no general rename/relocation or row-owner exception. Reject partial deletion of the RF coordinator, altered sibling counts, new/dynamic/moved persistence, any legacy RF writer/row visibility, or broadened owner assignment. Retained audit8 and notification2 occurrences above, all other future scopes and all known sibling observations stay fixed. Test the exact positives and near misses after implementation is authorized; no tests were run for this proposal.
5. **Evidence/rollback:** published scope inventory and source hashes; RF/sibling count/hash equivalence; tenant/RLS and no-RF-legacy-write checks; identical sibling review/permission/evidence/annual/reminder journeys; API/deployment order; exact rollback/recutover; independent review and both immutable full gates. Rollback restores the original single writer and original registry disposition only with matching data topology, preserving newly journalled/unknown RF effects for reconciliation. No backfill rewrites historical hashes, no blind effect replay, no new provider action or charge.

Root can narrow this further if a concrete implementation preserves an existing call or proves an entire resource RF-owned. It should not widen it to arbitrary future paths or use approval as a substitute for source/row proof. No user question is warranted for the routine RF work above; only this literal finite enforcement remainder is proposed for independent assessment.
