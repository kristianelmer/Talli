# RF withdrawal: archive-owner dependency proposal

**Status: proposed engineering design, not a human-approved architecture exception.**
Independent source review at `5660a7212eef88b3082985be0ac912435b2b6ffa`, 2026-10-09.
This document changes no business code, grants, migration pointer or acceptance
criteria. It refines the [withdrawal plan](observation-withdrawal-plan-20261009.json).

## Decision needed and smallest sequence

RF can stage its immutable withdrawal model, persistence, admission backstops,
public lifecycle query and additive v5 archive contract before #157. It cannot
offer a supported withdrawal command while an old producer can mint a current
archive receipt that omits withdrawals, or an old list can present withdrawn
evidence as current. An unavailable command is staging, not completed technical
acceptance of withdrawal.

The proposed dependency detour is serial:

1. **RF:** finish and verify its owned contracts and fail-closed guards; leave
   withdrawal execution unavailable to all deployed runtime callers.
2. **Governance:** take a bounded owner turn for the final SQL backstop and the
   repair dependency below; return to RF. No foreign-table access or RF rewrite
   of Governance facts.
3. **Company Archive:** after an explicit, narrowly scoped ADR0013 decision,
   bring forward only the canonical completion/verification handoff from #157.
   Establish one archive receipt writer, consume RF public coverage, and replace
   the exact begin/complete transport seams. Do not migrate unrelated archive
   sources or add a parallel exporter. Company Access then takes a bounded turn
   to consume the archive owner's receipt-validity contract.
4. **RF:** prove owner integration, old-list fencing and rollback; only then
   enable the withdrawal command within the applicable runtime authority.
   Resume the existing technical sequence; the rest of #157 remains outstanding.

Staging means withholding withdrawal `EXECUTE` from `PUBLIC`, browser/service
roles, runtime executors and login roles, with no direct-DML or wrapper route.
The store-owner role must remain unavailable through runtime login/`SET ROLE`.
A UI flag or application environment switch is not this database boundary.

[ADR0013](../../../../../docs/adr/0013-enforce-the-architecture-and-migrate-serially.md)
freezes future facade behavior and stage order. Its resource-owner exception
permits exact resource retirement, not new future-owned completeness policy.
The September 10 archive exception removed only `table:opening_balance_setups`
while preserving output, begin/complete records and adjacent reads. Neither that
exception nor the October 9 technical-first amendment authorizes this detour.
The latter expressly preserves unresolved technical dependencies and the facade
freeze. The required sequence/ownership decision is technical architecture work,
not external pilot proof; this proposal neither supplies nor requests approval.

## Existing seams and proposed owner changes

| Exact seam | Current behavior and bounded change |
| --- | --- |
| [`compat-company-archive-persistence`](../../../../../architecture/compatibility.json), removal #157 | Canonical owner is `web:legacy-runtime:company_archive`; no canonical backend Archive module exists. The detour must declare the receiving Archive public package, data/adapter ownership, workflow edges, generated transport and exact retired facade scopes. A SQL role name is not an ownership decision. |
| [`company_archive_begin_export(uuid,integer)`](../../../../../supabase/migrations/20260808120000_company_access_cancellation_lifecycle.sql) | Accepted-owner/fresh-MFA check; attempt binds actor, company/year, generation and expiry. Preserve these guarantees through the new owner boundary. |
| `company_archive_complete_export(uuid,text)` in the same migration | Checks attempt, expiry and unchanged generation; trusts the supplied archive hash. Add a separate owner completion contract with verified artifact coverage. Keep this legacy RPC callable only where its output remains valid; reject affected scopes under the company lock before receipt insertion. |
| [`download/route.ts`](../../../../../apps/web/app/archive/[companyId]/[incomeYear]/download/route.ts): `loadArchiveRf1086`, RF/Documents check, `JSON.stringify`, SHA-256 and service-role completion | Transport the assembled exact bytes to the owner for verification/completion; return those same bytes only after success. Move the new completeness decision into Archive, not the route, `app/lib/archive.ts` or the operational control plane. Existing unrelated source composition remains characterized and frozen until its owner stage. |
| `company_access_request_cancellation`, `company_access_resume_cancellation`, `company_access_finalize_deletion` in the lifecycle migration | Each selects a receipt solely by current generation. For fresh commands, require an Archive-owned current eligible receipt, including required coverage; preserve missing-document and authorization checks. Do not duplicate RF policy in Company Access. |
| `company_access_review_deletion` and `company_access_reconcile_cancellation_operation` | Review records independent approval for a cancellation revision; it does not currently select an archive receipt. Preserve that role and exact command reconciliation. Finalization must still recheck current eligibility; review is no substitute. |

[ADR0011](../../../../../docs/adr/0011-enforce-capability-owned-contracts-data-and-workflows.md)
requires immutable public contracts and named multi-owner workflows;
[ADR0012](../../../../../docs/adr/0012-govern-the-fastapi-web-and-operational-boundary.md)
keeps business policy behind FastAPI/generated clients. A new check hidden in the
frozen web facade or a generic readiness/release gate would violate those bounds.

## RF coverage contract and completion enforcement

Proposed RF public query: `load_archive_coverage_v1(company_id, income_year)`.
Names are illustrative; the contract must return an immutable, owner-read
snapshot commitment containing scope, format/domain version, canonical v5 digest,
complete family counts, withdrawal count and lifecycle digest, and commitments to
required originals/history. RF owns scope selection and lifecycle validation.
`captured-empty` requires an actual complete read; missing/legacy coverage is
`unknown`, never zero. A pure codec validates supplied history but cannot attest
that storage enumeration was complete.

Archive owns attempt/generation and complete-company eligibility. Its verifier
must inspect the **actual final archive bytes**, invoke the RF public v5 verifier,
and match canonical RF content, readable projection and original commitments to
the authoritative RF snapshot. Caller-supplied counts, version, booleans or two
unrelated hashes are insufficient. Use a narrowly owned verification record
binding attempt, actor/scope, source generation, final-byte hash and RF commitment;
no new durable object store is required by this proposal. Only the Archive
verification path can create that record.

Final completion consumes that record in a short transaction, takes the existing
company archive lock, and rechecks current generation and RF commitment before
writing one receipt. Require READ COMMITTED and read generation after acquiring
the lock; a snapshot fixed before a competing write is not a current check.
Use a consistent lock order across begin, source writes,
verification completion and cancellation. Verification/network work stays outside
the transaction. Exact completion retries must recover the same receipt; a
changed artifact/commitment under the same command cannot succeed.

The existing [retained-generation triggers](../../../../../supabase/migrations/20260930160335_rf1086_retained_archive_generations.sql)
can invalidate pre-withdrawal receipts when withdrawal becomes a tracked RF
source. They do **not** prevent this false-complete case: withdraw → old exporter
begins at the new generation → omits withdrawal → legacy completion accepts its
hash. Fix it at the old completion RPC itself: under the same lock, query a narrow
RF public coverage fact and reject a scope whose required lifecycle history the
old contract cannot represent. Attempts begun before and after withdrawal must
both be covered. Preserve legacy receipts as history; fresh cancellation must not
treat them as currently eligible. Never silently relabel them v5.

Further source review on 2026-10-10 found that existing legacy completion does
not require READ COMMITTED. A REPEATABLE READ transaction whose snapshot predates
withdrawal can acquire the company lock later and still compare the old generation.
Its resulting receipt is stale to later fresh reads, but generation tracking alone
does not force completion itself to fail. The bounded Archive-owner change must
close this isolation gap as well as verify coverage; test both withdrawal-first
and completion-first lock orders with a previously fixed snapshot. This is a
source-derived gap, not an executed race result or approval of the pending detour.

No Archive grant may expose RF private tables. RF's coverage query/assertion is
read-only and limited to the declared Archive executor. The new receipt writer
must not accept browser or service-role assertions as verification. Preserve or
tighten current denial of direct receipt-table DML; no runtime role may bypass the
owner command through table grants, callable wrappers or `SET ROLE` membership.
The legacy service-role RPC grant is safe only with its mandatory coverage fence.

## Separate old-list fence and rollback

The old [observation list](../../../../../apps/backend/src/talli_backend/main.py)
sets `isCurrent` from successor absence; it cannot express withdrawal. A new
backend error does not protect an old binary still serving that route. Before
the first withdrawal, verify routing/drain of every reachable old list producer,
in-flight request and rollback target. New lifecycle contracts must drive the
selector, and every consequential command must independently reject stale input.
Do not hide withdrawn rows with RLS: that destroys historical recovery and can
reactivate ancestors.

Before activation, both deployment orders remain usable with zero withdrawals.
After the first withdrawal, retain rows, generation tracking, SQL admission and
archive-completion fences on rollback. A binary unable to represent lifecycle
must remain unroutable for affected reads; it may not regain command grants.
Disabling new withdrawal commands stops additional writes but does not make old
reads/archives truthful. v1–v4 artifacts remain readable with their historical
coverage limits; v5 must not be negotiated onto old routes. An RF stream's complete
trailer proves transfer completion, not complete company-archive eligibility.
The additive RF work belongs in the owned
[archive codec](../../../../../apps/backend/src/talli_backend/modules/shareholder_register_filing/archive_storage.py),
[history contract](../../../../../apps/backend/src/talli_backend/modules/shareholder_register_filing/archive_history.py)
and [stream workflow](../../../../../apps/backend/src/talli_backend/application/shareholder_register_archive.py),
with corresponding [restore verification](../../../../../apps/web/app/lib/rf1086-restore-integrity.ts).
Their validity checks must not acquire company-archive eligibility policy.

## Governance dependency is separate

Governance is already canonical, so its bounded serial repair needs no future
Archive-facade exception. The [Python workflow](../../../../../apps/backend/src/talli_backend/application/corporate_governance_workflow.py)
calls RF evidence assertion, but the permitted SQL
[`complete_supported_event_v1`](../../../../../supabase/migrations/20260904220000_corporate_governance_supported_events.sql)
can be called without that Python step. Its later
[company guard wrapper](../../../../../supabase/migrations/20260924080355_governance_ledger_company_write_guards.sql)
does not add RF currentness. For existing register-required kinds/phases, final
SQL must call RF's public exact-current assertion after exact replay detection
and before fresh completion. RF extends that assertion to exclude withdrawals;
preserve committed-event replay and recovery.

An already-recorded event retains an exact observation reference. RF's
[`_build_capital_receipts`](../../../../../apps/backend/src/talli_backend/application/shareholder_register_source_workflow.py)
rejects corrected Governance events and observations confirmed after the event.
A new independent RF capture plus source correction therefore does not repair
that binding. The Governance owner must demonstrate a public repair path preserving
economics, attribution, timing and Ledger linkage, or implement its bounded
repair first. Until then this scenario remains blocked technical work; RF must
not rewrite the event, move its timestamp or claim repair through recapture.

## Required proof and exit limit

- Real restricted-role SQL tests: no withdrawal/DML/wrapper bypass while staged;
  direct Governance fresh completion rejects withdrawn evidence; exact replay and
  already-admitted outcome reconciliation survive.
- Real transaction races in both orders: withdrawal versus old/new export,
  completion and cancellation/finalization. Test old exports started **after**
  withdrawal, pre-withdrawal REPEATABLE READ/serializable snapshots,
  stale/fabricated coverage, omitted rows/originals, mismatched final
  bytes, captured-empty coverage, expiry, cross-tenant calls and lost-response retry.
- Immutable v1–v4 reader/route compatibility; v5 canonical/readable/original
  agreement; full family count/hash reconciliation; truthful list/browser history
  with no ancestor reactivation; executable rollback/recutover and routing proof.
- Exact manifest/compatibility inventory and independent owner review; both
  immutable complete gates and protected integration. The sequencing amendment
  retains full A1–A7, A3 service/production evidence and later 12-lane/14-approval
  clearance requirements; it does not convert missing technical dependencies into
  external proof.

Until the bounded owner decision and these dependencies are implemented and
verified, RF may merge inactive foundations but cannot claim supported withdrawal
or its complete technical handoff. No provider, company, production activation or
launch authority follows from this proposal.
