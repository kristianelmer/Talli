---
status: accepted
date: 2026-07-26
---

# Enforce the Architecture and Migrate Serially

Talli will adopt the repository and module format prototyped at commit
`1c38dc6d`, then migrate capabilities one at a time in the exact order approved
by issue #132. Machine-readable manifests are the architectural source of truth,
but enforcement reconciles them with language-aware imports, public exports,
database catalogs and migrations, generated contracts, scoped documentation,
tests, compatibility records, and deterministic dependency artifacts. The
customer-ready CI aggregator remains the highest acceptance seam and must include
both application builds, architecture checks, contract/deploy-order checks,
security/RLS evidence, migration equivalence while active, critical browser
journeys, and the existing launch rehearsal without duplicate test ownership.

The prototype's JSON Schema and `MODULE.template.md` are normative starting
points. Its filled ledger documents are illustrative examples; where their
headings omit or rename template sections, foundation must align them before they
can serve as conformance fixtures. A companion backend system manifest and a
schema-validated compatibility registry cover workflows, technical state, adapter
bindings, and exceptions that a capability/web manifest cannot own.

Foundation may place a not-yet-migrated capability's single canonical legacy
implementation behind its already-declared target contract. Such a legacy façade
must be registered, may not create a second writer or accept new functionality,
and expires at that capability's numbered migration stage. It is distinct from
active-stage compatibility debt. Debt created by the active capability must be
removed before the next stage; the narrow human exception in issue #132 may defer
it for at most the earlier of fourteen days or one stable customer-ready release.
Stable customer-ready releases are annotated Git tag objects whose tag identity
begins `customer-ready-`. Lightweight tags do not qualify. The tracked release
state must exactly match the latest such tag reachable from the gated revision,
including its peeled commit and tagger timestamp. Equal tagger timestamps are
ambiguous and fail the gate rather than being ordered by tag name. Until the
first qualifying tag exists, the explicit release state is `null`.

Every capability stage uses characterization, one authoritative writer,
expand–migrate–contract, deterministic reconciliation, rollback/recutover rehearsal,
cleanup of old code/data/adapters/equivalence tests, Graphify/manifest agreement,
and two consecutive complete gates on immutable revisions. Activated production
paths also require the approved seven-day observation window. Implementation
issues may be created only after issue #133 and the Wayfinder map are closed.

## 2026-08-26 clarification: frozen facades are not compatibility debt

Issues #185 and #186 clarify the compatibility language above without changing
the serialized migration decision. The records present at revision
`d331ee2717d1eeacef0d81db42b9d4fb5848b408` are frozen legacy-facade records,
not calendar-expiring exceptions. `architecture/compatibility-baseline.json`
records their exact IDs, scopes, removal issues, and single canonical legacy
runtime. The active registry may remove the current capability's frozen scopes.
It may not add a facade or scope, retain a facade after its stage, create a
second writer, or use a facade to add business behavior. A future capability's
facade otherwise remains frozen, subject only to the resource-owner cutover
amendment below.

Only debt created while migrating the current capability is active-stage debt.
It remains a narrow, explicitly approved exception: it expires at the earlier of
fourteen days or the next stable customer-ready release and may survive no
farther than the immediately succeeding capability. Authorization/RLS,
statutory-output reconciliation, secret leakage, ambiguous external effects,
and the other non-suppressible categories above can never become either record
kind.

The migration state names one current capability and its exact removal ticket or
tickets. An exit attempt fails while any current legacy facade or blocking
predecessor debt remains. Once a capability advances, the registry must preserve
two distinct immutable revisions on which the complete customer-ready gate
passed. Future stages stay static until they become current, except for the
exact resource-owner deletions authorized below.
The one-time #186 foundation recovery records its two passes separately before
the first capability stage can rely on the restored baseline.

## 2026-08-26 amendment: active-resource authorization cutover

Issue #138 exposed that a current capability cannot revoke browser access to a
resource it owns while frozen future operations retain direct authorization or
context reads of that resource. Kristian approved this narrow amendment after
the affected scopes and post-contract RLS failure were recorded on #138.

The active capability may remove an exact frozen scope from a future facade only
when the database catalog assigns that scope's resource to the active capability.
Current source must prove the exact call is gone. Every retained future-owned
persistence resource and occurrence count in the affected operation remains
frozen, and no new persistence resource may appear. An entire future record may
disappear only when every one of its scopes satisfies the same ownership and
deletion proofs.

This exception authorizes only behavior-equivalent authorization-helper or RLS
seam changes required to revoke access to the active capability's resources. It
does not authorize a future capability's writer, provider effect, business rule,
public contract, statutory output, or other business behavior to change.
Characterization, generated-contract, database/RLS, browser, rollback/recutover,
and two immutable customer-ready gates must prove the cutover. Any affected
resource without exact catalog ownership fails closed and remains frozen.

## 2026-08-27 amendment: ledger-stage atomic coordinator relocation

Issue #139 established that the last ledger writers cannot preserve both one
authoritative posting result and the frozen future-capability effects when the
browser commits those effects in separate requests. Kristian therefore approved
the narrow amendment and audit option A in
[#139 comment 5434908084](https://github.com/kristianelmer/Talli/issues/139#issuecomment-5434908084).

This authorization applies only while `ledger` and #139 are the active migration
stage. It covers exactly the four legacy web operations `recordAdminCost`,
`recordDividendReceived`, `recordShareholderLoan`, and `recordTaxSettlement`, plus
the five future posting routines `accept_bank_transaction_suggestion`,
`record_share_purchase_fifo`, `record_share_sale_fifo`,
`finalize_corporate_decision`, and `record_owner_dividend_payment`. Their
coordination may move from the browser or predecessor SQL entry point into named
backend-system workflows so the ledger write and the frozen future-owned business
writes share one request-bound Postgres transaction. The ledger posting must go
through the ledger public contract. Compatibility implementations may retain only
the already-characterized future behavior; they do not migrate the future
capability or create a second implementation.

For the seven registered web operations involved in this relocation
(`recordAdminCost`, `recordDividendReceived`, `recordShareholderLoan`,
`recordTaxSettlement`, `acceptBankTransactionSuggestion`, `recordSharePurchase`,
and `recordShareSale`), every frozen scope belonging to one operation must be
deleted together with current-source proof. The checker authorizes only the exact
record, resource, path, rule, and operation tuples frozen for this decision. It
does not authorize a generic future-facade shrink, a new resource, or a partial
relocation. The immutable compatibility baseline does not change.

Option A preserves the already-characterized idempotent after-commit audit
continuations: a committed business result is not repeated, audit identity is
deterministic, an exact immutable audit row is reconciled on retry, and audit
failure cannot be reported as success. This does not reclassify an audit write
that already occurs inside one of the five frozen future SQL routines as an
after-commit continuation. Its existing placement and outcomes remain frozen.
Moving any audit persistence into or out of a transaction is not authorized by
this amendment.

No policy, schema, provider, public contract, capability scope,
statutory result, error, idempotency, retry, or risk-response expansion is
permitted. Characterization, generated-contract, database/RLS, browser,
rollback/recutover, deterministic dependency, and two immutable complete-gate
passes must prove the relocation before #139 exits.

## 2026-08-28 amendment: split ledger acceptance from live cross-capability reconciliation

Issue #188 exposed a dependency cycle in the mass-market route. The ledger stage
must define and enforce January-to-as-of source completeness and downstream-output
binding, but the canonical source producers and several receiving calculators do
not exist until their later serialized capability stages. Requiring their live
results before #188 closes would either start later capabilities concurrently,
read their private legacy tables, or accept fixture labels as if they were real
reconciliation. All three outcomes contradict this ADR and weaken the launch
proof.

Kristian therefore approved the explicit split recorded in
[#188 comment 5448715773](https://github.com/kristianelmer/Talli/issues/188#issuecomment-5448715773).
#188 owns the canonical ledger receiver and close contracts: typed January-to-as-of
coverage and gap topology, immutable economic/source fact bindings, immutable
downstream-output declarations, deterministic postings and corrections, pinned
official mappings, golden journals, and unsupported-case failure. It must reject
historical, incomplete, stale, unbound, duplicated, or digest-mismatched evidence.
It does not claim that future source owners already produce their attestations or
that future calculators already agree with them.

Issue #199 is a mandatory post-#195 integration gate. Once all canonical source
owners, filings, SAF-T, audit, and archive exist, #199 must exercise their public
contracts over one complete company-year graph and prove stable-ID/hash agreement
with zero unexplained material differences. It may add integration tests and
evidence, but it may not create a cross-capability writer, read a private capability
table, revive a compatibility facade, or duplicate accounting policy. A defect is
routed through exactly one owning capability at a time and the whole graph is
rerun. Fixture declarations alone cannot satisfy #199.

The serialized tail is therefore `#195 → #199 → #154`. The archive/SAF-T and
final zero-difference tranche of #197 also waits for #199. This is an ordering
change, not an assurance waiver: #154 cannot contract the legacy system and #198
cannot clear launch until #199 and the representative #197 evidence have passed.
Cost, credential, named-data, production, filing, provider, and public-action
guardrails are unchanged.

## 2026-08-30 amendment: case-bound support security exception

Kristian approved the exact security-only exception in
[#200 comment 5467952439](https://github.com/kristianelmer/Talli/issues/200#issuecomment-5467952439).
It does not advance or reopen a capability migration: the serialized pointer
remains investments/#141. It authorizes `backend:company_access` to own a
generated UUID support case, immutable command receipts, and durable explicit
opening evidence, and to replace standing operator data access with one
operator/company/reason/scope/time/fresh-MFA/opening boundary.

The authorization seam covers exactly `public.companies`, `audit_events`,
`company_cancellations`, `filing_submissions`, `filing_readiness_snapshots`,
`billing_accounts`, `billing_payment_events`, `authority_permissions`,
`authority_test_runs`, `system_user_requests`, `production_pilot_entitlements`,
`filing_approval_snapshots`, `production_filing_submissions`,
`production_filing_events`, `production_feedback_artifacts`, `documents`,
`storage.objects`, and `company_deletion_reviews`. Those resources keep their
existing capability ownership and business writers. Support grant, revoke,
explicit POST open, read-only GET, and deletion review run only through the
backend executor and generated client; authenticated browser policies and RPC
execution are removed.

The compatibility checker may delete only the six remaining frozen
`searchOperatorSupportDashboard` scopes, atomically and without changing the
immutable baseline: billing accounts/events, filing readiness, authority
permissions, filing submissions, and audit events. The exception cannot add a
writer, move product or accounting policy, change filing/billing/provider
effects, alter public customer contracts, or broaden another operation. Fresh
and upgrade migration, negative RLS, POST idempotency/audit, read-only GET,
deletion-review parity, generated contract/browser, rollback/recutover, and two
immutable complete-gate passes are required before hosted application.

## 2026-09-09 amendment: exact legacy acquisition retirement

On 9 September 2026, Kristian's recorded decision was **"approved"** in response
to both the
[`legacy-retirement-amendment-proposal.md`](../../architecture/evidence/issues/192/legacy-retirement-amendment-proposal.md)
and option B of the
[`source-order-amendment-proposal.md`](../../architecture/evidence/issues/192/source-order-amendment-proposal.md).
This subsection records only the exact four-retirement approval.

Issue #192 may retire the obsolete acquisition Server Actions
`saveBillingAccount`, `activateBillingSubscription`, and
`requestFilingPackagePayment`, together with their current clients and forms.
The amendment applies at billing or a later serialized stage and authorizes
deletion of exactly these frozen tuples, all at `apps/web/app/actions.ts` under
`direct-web-business-persistence`:

| Frozen record | Resource | Operation | Unchanged removal issue |
| --- | --- | --- | --- |
| compat-audit-persistence | table:audit_events | saveBillingAccount | #155 |
| compat-audit-persistence | table:audit_events | activateBillingSubscription | #155 |
| compat-audit-persistence | table:audit_events | requestFilingPackagePayment | #155 |
| compat-annual-compliance-persistence | table:filing_readiness_snapshots | requestFilingPackagePayment | #149 |

The four deletions must be atomic and all three entire actions must disappear.
Unreachable writers after unconditional failure, relocated or renamed writers,
replacement acquisition entry points, different paths or tuples, dynamic writers,
partial deletion and additions are forbidden. Current-source proof and the global
web persistence/provider boundary continue to apply. The immutable compatibility
baseline, its digest, every other frozen future scope and occurrence count, and
resource ownership remain unchanged. Only the active inventory decreases by four.

This amendment authorizes no annual-readiness implementation, migration of audit
or annual compliance, change to their remaining operations, second writer,
provider effect, business rule, financial or statutory result, or expansion of
authorization, privacy, contract or release authority. Retirement alone preserves
the serialized migration order. The separately approved source-order option B
permits a gated interim billing checkpoint before #150 under its own conditions;
this retirement amendment does not supply that gate or claim the next stage.
The exact owner decision alone does not constitute stage-exit evidence.

Historical payment/cancellation/refund recovery, deterministic reconciliation,
rollback/recutover, generated contracts, negative RLS, critical browser journeys,
independent immutable reviews, two complete 11/11 gates and the required
protected-main Release/Preview proof remain required by #192. Actual Vipps MT,
trustworthy source-owned readiness and the remaining annual
runtime/refund/worker/callback acceptance remain required. Apply retirement
rollback before predecessor billing rollbacks and reapply retirement last;
preserve account, event and receipt evidence and coordinate runtime rollback so
old acquisition code cannot regain a writer surface accidentally. Production
filing, promotion and paid activation receive no authority from this amendment.

## 2026-09-09 amendment: billing checkpoint before source-backed completion

Kristian replied **"approved"** to the exact four-retirement and source-order
option B proposals. The [recorded decision](https://github.com/kristianelmer/Talli/issues/192#issuecomment-5599100453)
approves the following exception to the normal post-migration completion rule:

`#137 → #192 interim checkpoint → #150 → #151 → #146 → #152 → #153 → #193 [RF → tax → accounts] → #149 → Company Access year prerequisite (#208) → #192 final acceptance → #194 → existing tail`

Issue #192 remains open. Its interim checkpoint must complete currently
implementable billing work, keep acquisition/renewal unavailable when trusted
sources are absent, and preserve historical recovery, cancellation, refund and
read/export rights. Before #150 may be claimed, require independent review,
two linked immutable complete 11/11 gates, protected Release/Preview merge and
exact-main Release/Preview evidence. Approval alone supplies none of these
receipts. The registry's existing `authority_connections/#150` position follows
#137's capability exit; it does not authorize starting #150 before this checkpoint.
Do not rewrite capability migration order or manufacture a #192 capability exit.

Only one capability owner may edit business state. After the interim checkpoint,
#192 implementation pauses while #150 through #149 execute in their existing
relative order; #192 may receive read-only analysis during that interval.
#193 remains internally serialized RF-1086, company tax, then annual accounts.

Filing owners publish immutable company/year/obligation readiness, complete
submission history, terminal/unknown outcomes, corrections and coverage through
public contracts. Absence of a source is unavailable, never evidence that no
production filing occurred. Annual Compliance #149 aggregates the three contracts
with versioned identity and a current-evidence verifier; readiness before charging
must be independent of paid entitlement. Each incident producer attests only its
own facts and attribution, event time and company/year. Billing alone applies
#177's commercial classification and refund amounts. A missing incident owner
must be identified and scheduled explicitly; no omniscient incident service or
legacy readiness row becomes authority.

After #149, a bounded change to canonical Company Access selects immutable
accounting-year admission manifests and rechecks renewal eligibility. Preserve
accepted 2026 references and fail closed for unvalidated years. A mechanism test
or copied 2026 promise cannot establish 2027 support. Boundary changes still
require the relevant decision to be reopened.

Then #192 binds the real sources and proves ordinary paid entitlement, durable
automatic renewal/refund processing without fabricated owner claims, and every
original A1–A8 criterion over the real runtime. Final customer/operator,
provider, security/privacy/accounting, representative, independent review,
two complete immutable gates and protected-main evidence remain mandatory.
Full #192 is required before #194 and #197's billing tranche. #189, #193's genuine
filing proofs, #197/#199 and #198 remain mandatory. This amendment changes neither
the frozen compatibility baseline nor source ownership and grants no spending,
production filing, provider activation, named-data, outreach or launch authority.
`release/production` remains independent and frozen.

The [approved proposal](../../architecture/evidence/issues/192/source-order-amendment-proposal.md)
retains the exact reviewed scope and producer obligations. The control-plane
ledger and #192 requirements record the pending checkpoint separately from final
completion; missing receipts remain pending.

## Canonical decision inputs

- Billing retirement and source-order option B: issue #192 comment
  `5599100453`, owner decision dated 9 September 2026.
- Repository prototype and manifest format: issue #130 and commit `1c38dc6d`.
- Enforcement and acceptance suite: issue #131.
- Serialized roadmap and exit criteria: issue #132.
- Final approval and frozen pointer index: issue #133.
- Ledger atomic-coordinator relocation and option A: issue #139 comment
  `5434908084`.
- Ledger/live-reconciliation acceptance split: issue #188 comment `5448715773`
  and issue #199.
- Case-bound support security exception: issue #200 comment `5467952439`.

## Consequences

- Structural movement is not a capability migration and cannot hide business or
  data cutover.
- Circular dependencies, unowned data, failed authorization/RLS, statutory-output
  differences, secret leakage, and ambiguous external effects are never
  suppressible.
- Semantic Graphify extraction is optional and non-blocking; deterministic
  manifest-derived dependency evidence is required and incurs no model/provider
  charge.
- Future changes to the frozen baseline require an issue that identifies affected
  ADRs/manifests, compatibility and migration impact, acceptance evidence, and
  explicit approval before implementation.

## 2026-09-09 amendment: exact RF authority credential relocation

During the Authority Connections stage, #150 requires all authority credentials
and policy to leave TypeScript, while the two frozen RF-1086 submit/recovery
coordinators still require delegated Maskinporten credentials. The existing
authorization-helper/RLS exception does not cover their provider execution.
Kristian approved the exact relocation in
[#150 comment 5601323119](https://github.com/kristianelmer/Talli/issues/150#issuecomment-5601323119),
against the complete
[scope proposal](https://github.com/kristianelmer/Talli/issues/150#issuecomment-5601305923).

Only while `authority_connections/#150` is current, the existing
`sendApprovedRf1086ProductionFiling` and `reconcileRf1086ProductionAction`
coordinators and their enumerated journal/feedback helpers may move into one
registered frozen RF compatibility implementation behind named backend-system
workflows. Authority Connections supplies its owned connection and credential
ports; it acquires no RF statutory, approval, journal or feedback policy.
`architecture/evidence/issues/150/rf-credential-relocation-2026-09-09.md` binds the
eight exact future #151 facade tuples, two current #150 reads, transitive source
functions, six SQL routines, five HTTP methods and existing cross-owner effects.
The immutable compatibility baseline is unchanged. The two old web effects are
removed together at cutover; no second writer or generic provider proxy remains.
No other future tuple, occurrence count, resource, provider effect or rule changes.

The generated web contracts accept only the original approval/submission identity
and intent. Verified backend context supplies the company, owner, durable payload,
provider endpoint and operation identity. Send preserves fresh filing MFA, exact
current entitlement and approval/payload/release gates, with delegation before
`begin_production_filing`; token failure starts no filing. Recovery preserves its
original historical authority after entitlement expiry, terminal early returns,
lease-before-delegation order and `finally` cleanup. It cannot add new-filing
eligibility requirements, invoke the three filing POST methods or blindly retry an
unknown mutation. Credentials, grants and bearer tokens never return to the web.

The existing RF journal, statutory bytes, intent keys, response/error mappings,
feedback classification, per-document GETs, five initial/one retry polling
iterations, Documents stage/finalize/conditional compensation, contracted billing
reader/lock seam and existing audit placement are preserved. The original RF
compatibility implementation remains its single frozen owner until #151 absorbs
and removes it. No RF migration or production-completion exit is implied.

Characterization must compare these exact effects and operation ordering, including
cross-company denial, stale authorization, token failure, ambiguous provider
responses, lease loss, duplicates and recovery after entitlement expiry. RLS,
count/hash reconciliation, rollback/recutover, generated contracts, browser
journeys, independent reviews and two immutable complete gates remain required.
This amendment changes no source-stage order and grants no provider activation,
real filing, spending, named-company processing, production promotion or launch
authority.

## 2026-09-10 amendment: sixteen exact RF compatibility dispositions

Kristian replied **"approved"** in the requested handoff destination to the exact
sixteen-entry revision-2 decision. The [decision record](../../architecture/evidence/issues/151/compatibility-amendment-v2-decision.json)
binds the unchanged [proposal](../../architecture/evidence/issues/151/compatibility-amendment-v2-proposal.md)
and [inventory](../../architecture/evidence/issues/151/compatibility-amendment-v2-inventory.json),
including the original twelve handoffs and three simulation reads.

Only those twelve baseline tuples may move from `compat-rf1086-persistence/#151`
to existing `compat-annual-compliance-persistence/#149`, after RF rows and writers
leave the generic stores. Each retains its path, rule, resource, operation and
single occurrence, sibling authorization, validation, results, errors and effect
order. Tax/accounts retain business ownership. Each residual call expires when
its last real sibling source migrates, no later than the last filing cutover.

Only the three listed `confirmSimulatedRf1086Submission` reads may retire
atomically with that coordinator's two current RF persistence tuples. RF owns
review/override facts; the unchanged stored-ready prerequisite remains a declared
frozen annual-source query, with its scope, unavailable/error behavior and owner.
The sixteenth disposition retires only archive GET's historical
`table:opening_balance_setups` tuple under `compat-company-archive-persistence/#157`.
Its generated year-scoped Ledger query composes RF shares/identity and Ledger bank
amounts, preserving archive output, authorization, begin/complete records, audit
and eight remaining generic reads. Do not assign the historical mixed resource
to one owner or introduce a general split-resource exception.

Require zero direct/dynamic occurrences for each retired resource. Preserve the
eight adjacent action audit calls and both notification calls and their placement.
Reject unlisted, moved, dynamic or additional persistence and changed sibling
counts. Keep the immutable compatibility baseline byte-identical. Count/hash,
row ownership, tenant/RLS, sibling journeys, rollback/recutover, independent review,
both complete immutable gates and protected integration remain mandatory.
This approval changes no serialized stage order or production freeze and grants
no provider tests, real filings, spending or production activation/promotion.
