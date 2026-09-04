# Mass-market execution control plane

Status: active execution control  
Repository basis: 2026-08-31, task `01a0564b-8c6e-7691-8c08-2b3e7e7df038`, pre-amendment revision `e362006a`
Artifact identity: the immutable Git commit containing this path, published and linked from #188  
Authoritative queue: GitHub issue [#165](https://github.com/kristianelmer/Talli/issues/165) and its live child tickets  
Mandatory preflight source: [#188 comment 5434701877](https://github.com/kristianelmer/Talli/issues/188#issuecomment-5434701877)

This document is an execution index, not a replacement for GitHub acceptance
criteria or volatile official/provider sources. A ticket's live issue, the
machine-readable architecture registries, and pinned evidence remain
authoritative. Update this ledger at every ticket boundary.

## Destination and non-negotiable boundary

The destination is unrestricted general availability for the approved practical
majority of privately owner-managed Norwegian holding AS companies. An eligible
company can join at any date, reconstruct the complete current calendar year from
1 January, use Talli as its only accounting and filing product for that supported
company-year, connect one bank read-only with a hardened file fallback, complete
RF-1086, the company tax return, and annual accounts directly in production, and
export SAF-T Financial 1.40 plus the complete retained archive.

The offer is one NOK 1,490 including-VAT annual company-year including the bank
connection and all three filings. The journey is the selected calm checklist:
one primary action, short plain Norwegian, progressive detail, responsive at
390px and desktop, and WCAG 2.2 AA. Public precheck, price, refund, consent,
checkout, help/legal/SEO, and privacy-safe first-party measurement must be
truthful and capability-gated.

Truthful free recruitment/ad readiness remains a day 21–30 target and
unrestricted launch remains a day 60 target. These are orchestration targets,
not authority to advertise, deploy, contact anyone, spend, or waive a red gate.

Talli remains deterministic owner-controlled software. Unsupported operating,
foreign, complex, regulated, consolidation, or material-judgment cases fail
closed. A Talli person or operational agent must not perform customer-specific
accounting. No charge, paid provider, outreach, named-company processing,
production filing, public deployment/claim, ad purchase, or launch occurs merely
because a code ticket is complete.

## Route topology and serialization

Completed prefix:

`#186 → #138 → #187 → #139 → #188 → #140`

Current ADR-0013 serialized implementation path:

`#141 → #142 → #143 → #190 → #147 → #144 → #145 → #148 → #191 → #137 → #192 → #150 → #151 → #146 → #152 → #153 → #193 → #149 → #194 → #155 → #156 → #157 → #195 → #199 → #154`

Only one ADR-0013 business capability migration may be active. A post-migration
mass-market slice immediately following a capability must finish before the next
capability begins. #193 is internally serialized RF-1086 → company tax → annual
accounts; it may not mutate two filing capabilities concurrently.

Permitted overlap:

- #189 is an independent external bank-provider clearance lane after #140. Its
  provider-neutral local criteria A1–A8 are complete; its A9 written coverage,
  licence, commercial, legal/privacy/security, reliability and human `bank_aisp`
  evidence remains red. It may stay open while #141–#154 advance against only the
  provider-neutral read-only banking public contract and hardened file fallback.
  It must close before provider choice or activation, live bank use, #197's bank
  tranche, any live-bank readiness claim, production banking, or #198 clearance.
- #196 is a non-business-persistence public acquisition lane. It may change only
  truthful free-recruitment/precheck, presentation, help/legal/SEO, consent shell,
  and privacy-safe aggregate measurement. Checkout, live claims, deployment,
  tracking-provider activation, ads, outreach, and launch stay gated.
- #197 is an evidence lane, not a product writer, and may not be claimed or edited
  until #196 closes. After that, work may overlap only after each
  exact legal, terms/DPA, hosted isolation/storage/MFA/logging/restore, named-data,
  provider, outreach, charge, and production-entry gate is green. Local synthetic
  preparation before #196 closes is generic control-plane work, not #197 execution
  or evidence. Its archive/SAF-T and final zero-difference tranche may begin only
  after #199 closes.
- #198 is blocked by both #154 and #197. It is the only ticket that may record
  unrestricted launch clearance; action-time authority still applies.

No parallel lane may edit `architecture/compatibility.json`, business
persistence, capability migrations, generated contracts, or shared integration
files while the serialized owner is changing them. One integration owner merges
and gates all bounded contributions.

Live blocker audit at this snapshot: #140 is closed with two immutable complete
gates, the architecture registry identifies `investments/#141` as the sole active
capability stage, and #141 is the sole next implementation claim. #189 remains
open as the independent external gate described above; its label or open state
does not reopen banking or authorize provider-specific assumptions. Every later
`Blocked by` edge remains serialized, and `ready-for-agent` labels do not override
those edges.

### Continuous-main integration rule

A capability ticket is not complete merely because its implementation is green
or its GitHub issue is closed. The sole integration owner must publish one
cohesive branch, open a pull request to `main`, pass the protected Release gate
and the Vercel Preview check on that immutable revision, and merge the pull
request. The next serialized ticket may be claimed only after that merge is on
`main` and the post-merge Release gate is green. A closed-but-unmerged ticket
remains the active stage; agents must neither rotate to nor begin its successor.

`release/production` is an independent production pointer. Capability PRs never
advance it, and a green Preview deployment is not production authorization.
The #189 provider gate and #198 final release/launch gate remain mandatory.

## Ownership zones

Every business zone `L` through `AR` includes its module manifests and scoped
docs, generated OpenAPI/client surface, capability tests,
architecture/database-catalog changes, additive migration, separate contract
migration, and phase-aware rollback when those are needed. Presentation,
validation and release zones `P`, `V` and `R` do not inherit business contracts,
data or migrations. Shared files (`apps/backend/src/talli_backend/main.py`,
`apps/backend/src/talli_backend/openapi.py`, `apps/web/app/actions.ts`,
`apps/web/app/lib/supabase/server.ts`, `architecture/*`, generated clients, and
root gate scripts) have one integration owner and are never assigned concurrently.

| Zone | Capability/data owner | Exclusive files and legacy contraction surface |
|---|---|---|
| `L` | `backend:ledger`; `ledger.entries`, `ledger.period_locks` and opening-ledger projections. Receipt/migration/cursor infrastructure remains `backend-system` technical ownership | `apps/backend/src/talli_backend/modules/ledger/**`, `application/ledger_*`, `adapters/supabase_ledger.py`, `apps/web/features/ledger/**`, ledger/onboarding forms and ledger migrations/tests |
| `B` | `backend:banking`; `bank_transactions`, `bank_suggestion_acceptances`, provider-neutral read models | new `modules/banking/**`, banking workflows/adapters, `features/banking/**`, transaction/import pages, `lib/bank*.ts`; remove `compat-banking-persistence` at #140 |
| `I` | `backend:investments`; positions, lots, allocations and investment semantic rows | new `modules/investments/**`, investment workflow/adapters/features, `lib/share-*`, `lib/dividend-received.ts`; remove investment compatibility records at #141/#142/#143 |
| `D` | `backend:documents`; document metadata, `company-documents` bucket lifecycle and document export projection | new `modules/documents/**`, storage adapter, document pages/routes and `lib/documents.ts`; remove `compat-documents-persistence` at #147 |
| `G` | `backend:corporate_governance`; decisions, finalizations, policies, document sets/events/artifacts and governance semantic rows | new `modules/corporate_governance/**`, governance workflows/features, corporate-decision/year-end routes and `lib/corporate-*`, dividend/loan presentation; remove governance compatibility at #148 |
| `BL` | `backend:billing`; billing accounts/events and entitlement state | new `modules/billing/**`, billing provider port/adapters/features/page and `lib/billing.ts`; remove `compat-billing-persistence` at #137 |
| `AU` | `backend:authority_connections`; System User requests, authority operations and connection/preflight evidence | new `modules/authority_connections/**`, provider adapters/features/connections/operator controls and authority libraries; remove `compat-authority-connections-persistence` at #150 |
| `RF` | `backend:shareholder_register_filing`; opening shareholder facts and RF-1086 obligation journal/artifacts | new `modules/shareholder_register_filing/**`, RF-1086 workflows/adapters/features and `lib/rf1086*`; remove `compat-rf1086-persistence` at #151 |
| `TX` | `backend:company_tax_filing`; tax settlement facts and company-tax obligation journal/artifacts | new `modules/company_tax_filing/**`, tax workflows/adapters/features, `lib/tax-settlement.ts` and `lib/company-tax-return*`; remove tax compatibility at #152 |
| `AA` | `backend:annual_accounts_filing`; annual-accounts obligation journal/artifacts | new `modules/annual_accounts_filing/**`, annual-accounts workflows/adapters/features and `lib/annual-accounts*`; remove annual-accounts compatibility at #153 |
| `AC` | `backend:annual_compliance`; `annual_data`, annual readiness/review/interview state and read-only obligation aggregation | new `modules/annual_compliance/**`, annual workspace feature/components/routes and annual readiness/data libraries; remove `compat-annual-compliance-persistence` at #149 |
| `AD` | `backend:audit`; append-only `audit_events` | new `modules/audit/**`, audit adapter/query feature and producer workflow bindings; remove `compat-audit-persistence` at #155 |
| `N` | `backend:notifications` owns notification intent, templates and delivery policy; backend-system owns generic worker/idempotency/delivery infrastructure declared in its manifest | new `modules/notifications/**`, public intent contract, provider ports/adapters/templates and system-declared workers; dispose `public.notification_outbox` and `compat-notification-persistence` at #156 without misclassifying technical state |
| `AR` | `backend:company_archive`; export projections/checkpoints only, never another capability's source tables | new `modules/company_archive/**`, archive workflow/feature/download route, SAF-T/archive generator and source projections; remove `compat-company-archive-persistence` at #157 |
| `CI` | cross-capability integration evidence; no business writer or data owner | #199 integration tests and immutable evidence over public contracts only; fixes return to exactly one owning capability at a time, with the whole graph rerun |
| `P` | public acquisition presentation; no business data owner | #196 exact reservation: `apps/web/features/public-acquisition/**`; `apps/web/app/page.tsx`; `apps/web/app/page.module.css`; public information routes `apps/web/app/{passer-talli,pris,hjelp,sikkerhet,status}/**`; SEO/social files `apps/web/app/{layout.tsx,robots.ts,sitemap.ts,opengraph-image.*}` and `apps/web/public/og.png`; public legal route metadata in `apps/web/app/{vilkar,personvern,databehandleravtale}/page.tsx`; technical measurement route `apps/web/app/api/marketing-events/route.ts`; aggregate operator presentation `apps/web/app/(operator)/operator/marketing/page.tsx`; #196 tests; and the declared backend-system measurement seam in `supabase/migrations/20260828103000_marketing_funnel_measurement.sql`, `architecture/{backend-system.json,BACKEND-SYSTEM.md,database-catalog.json}`, and its schema/runtime tests. Company-access alone owns consent/precheck persistence, billing alone owns checkout, and backend-system owns measurement storage. Generated contracts and compatibility files remain forbidden to `P`. Any other shared file requires a new exact #196 reservation before edit |
| `V` | immutable validation references; no business writer | `docs/validation/**` may contain only redacted/pseudonymous evidence indexes created after #196 closes. Participant identity/contact/consent/withdrawal/export/deletion/incident data belongs to a named human-controlled validation operator in an approved protected store selected before intake; it never enters Git |
| `R` | backend-system operational release control, not a business capability | `architecture/release-state.json`, launch evidence/signoff schemas and records, runtime feature/kill switches, release/restore/incident/capacity runbooks; #198 owns final clearance only |

### Current-to-target data disposition

The zone owner is the approved target owner, not a claim that migration already
happened. Until its ticket exits, every catalog entry marked `legacy-business`
remains in the single frozen legacy runtime. Expand names the target schema/table;
contract removes the legacy row family only after reconciliation and rollback
proof. Shared legacy tables are split by semantic discriminator, never assigned
wholesale to the first capability that touches them.

| Current resource | Target owner/row family | Disposition ticket |
|---|---|---|
| `bank_transactions`, `bank_suggestion_acceptances` | banking transaction/suggestion models | #140 |
| `investment_positions`, `investment_lots`, `investment_lot_allocations`; investment rows in `holding_actions` | investments positions/lots/allocations/events | #141/#142/#143 |
| `documents` and `company-documents` objects | documents metadata/object lifecycle and export projection | #147 |
| `corporate_*`; dividend/loan/capital/financing/group rows in `holding_actions` | corporate-governance decisions, policies, artifacts and events | #144/#145/#148, completed patterns #191 |
| `billing_accounts`, `billing_payment_events`, `production_pilot_entitlements` | billing account, payment-event and entitlement models | #137; offer lifecycle #192 |
| `system_user_requests`, `authority_operations`; connection/preflight rows in `authority_test_runs` | authority-connections request, operation and evidence models | #150 |
| `opening_shareholders`; RF-1086 rows selected from generic `filing_*`, `production_*`, `authority_permissions` and `authority_test_runs` | shareholder-register facts and obligation-specific journal/artifacts | #151, production completion #193 RF sub-slice |
| tax-settlement rows in `holding_actions`; company-tax rows selected from generic filing/production tables | company-tax settlement facts and obligation-specific journal/artifacts | #146/#152, production completion #193 tax sub-slice |
| annual-accounts rows selected from generic filing/production/authority-test tables | annual-accounts obligation-specific journal/artifacts | #153, production completion #193 accounts sub-slice |
| `annual_data`; annual readiness/review/override rows selected from generic filing tables; annual coordinator rows in `holding_actions` | annual-compliance interview/readiness/review/aggregation models | #149 |
| `audit_events` | audit business evidence; generic transaction/idempotency infrastructure stays backend-system owned | #155 |
| `notification_outbox` | notification intent/policy in notifications; generic durable delivery infrastructure in backend-system | #156 |
| company-archive attempt/receipt/source-generation rows and broad archive reads | company-archive projections/checkpoints and public source contracts | #157; complete SAF-T/archive #195 |

Generic filing tables may therefore survive multiple filing stages only as one
frozen canonical legacy store for uncut obligations. Each stage migrates and
contracts only its discriminator-owned row family with count/hash proof.

### Cross-capability workflow seams

| Seam | Coordinator and public contracts | Transaction/external boundary and failure |
|---|---|---|
| administrative cost → ledger | backend-system ledger administrative-cost workflow; ledger public contract plus the exact frozen administrative-cost compatibility effect | administrative-cost source effect + ledger post in one request-bound DB transaction. It does not consume a banking public contract; failure leaves neither effect |
| bank-suggestion acceptance → ledger | backend-system banking-plus-ledger workflow; banking and ledger public contracts | banking acceptance + ledger post in one request-bound DB transaction; provider sync is an idempotent state machine outside it. No accepted suggestion without one posting |
| purchase/sale/received dividend → ledger | backend-system investment-posting workflow; investments and ledger public contracts | lots/positions/allocations + ledger in one DB transaction; imported broker/bank evidence precedes it. Invalid/oversell/duplicate leaves neither side |
| dividends/loans/capital/group events → ledger/documents | backend-system governance workflow; governance, ledger and documents public contracts | semantic decision/finalization + posting in one short DB transaction; object transfer is staged outside and referenced by immutable `DocumentId`. Failure blocks finalization/payment |
| tax settlement → banking/ledger | backend-system tax-settlement workflow; tax, banking and ledger public contracts | settlement, cash recognition and posting commit together; failure creates no settlement/posting |
| filing approval/submission → authority/documents/archive | backend-system obligation workflow; one filing capability plus authority-connections and published document/archive contracts | approval/journal state commits locally; external submission/feedback uses permanent submit-once idempotent state machine outside the transaction. Unknown outcome reconciles before retry |
| consequential mutation → audit | producing backend-system workflow plus audit public contract after #155 | audit append is in the same business transaction after #155. Until then, the exact #139 Option-A continuations and frozen transaction-local placements remain characterized; no generic relocation is implied |
| committed event → notification | producing workflow/event plus notifications public contract after #156 | intent enqueue is atomic with the declared event/workflow; provider delivery is post-commit, at-least-once and deduplicated. Delivery failure never rolls back business success |

Audit and notification placement changes occur only at #155/#156. External bank,
billing and authority I/O never runs inside a business database transaction.

### Rollback identity rule

Rollback restores the immediately preceding single canonical path, not an older
browser/RPC writer. For banking admin-cost/acceptance, investments
purchase/sale/dividend, governance dividend/loan/decision, and tax settlement,
the predecessor is the exact #139 backend-system compatibility coordinator behind
the ledger public contract. Its contract artifact, deploy order, source/receipt/
hash reconciliation and corrected recutover condition must be named in the stage
evidence. Other stages restore only their frozen baseline façade. #155 must first
inventory its mixed predecessor topology—Option-A after-commit continuations and
already transaction-local future placements—and rehearse that exact topology;
“restore a prior audit writer” never means reviving an arbitrary direct writer.

## Acceptance-to-test and evidence vocabulary

Every ticket maps each acceptance criterion to at least one stable evidence ID in
its closing comment and committed requirement ledger. The common envelope is:

- `U`: deterministic unit/golden/official-source characterization, coded errors,
  fixed clocks/IDs, cross-output facts, unsupported-case risk responses.
- `C`: public contract, OpenAPI/generated-client reproducibility, deploy-order
  compatibility, no deep imports or duplicate contract implementation.
- `A`: focused architecture/import/public-export/data-ownership/compatibility
  proof, including exact removal of obsolete façade scopes and no new exception.
- `D`: fresh database, ownership, RLS/tenant concealment, ACLs, atomicity,
  idempotency, concurrency, reconciliation hashes, expand/contract/rollback/
  corrected recutover and from-zero migration.
- `W`: affected real browser journey, reload/retry/unknown outcome, 390px and
  desktop; keyboard/screen-reader/reflow/contrast/error checks where UI changes.
- `S`: credential/dependency/security/privacy/log-redaction/abuse checks and
  provider fake/conformance evidence; no network or fee in standard tests.
- `X`: cross-capability/output reconciliation and archive projection evidence.
- `O`: operational health, alerts, incident/kill switch/rollback, restore,
  capacity, correlation and protected read/export behavior.
- `G`: typecheck, architecture/import/data ownership, both production builds,
  boundary smoke, launch rehearsal, deterministic dependency artifact freshness,
  and manifest/scoped-document agreement. Semantic Graphify extraction is
  optional/non-blocking; the deterministic manifest-derived graph is mandatory.
- `G2`: two consecutive complete customer-ready gates on distinct immutable
  revisions, linked by `previousPassingRevision`. Required for every #132
  capability exit, every #193 filing sub-slice, and final #154/#198 evidence where
  specified.
- `H`: current human/external evidence. It records reviewer/role, exact version,
  digest/link, date, expiry/recheck, decision and conditions; it never masquerades
  as an automated pass.

An actually activated production path also needs the #132/ADR-0013 seven
consecutive-day observation window without a capability-attributable serious
incident before its stage/product exit. Local, simulated, disabled and
undeployed paths record the observation as deferred to the activation/clearance
ticket; they do not claim it passed.

Rollback is fail-closed by default: stop the new writer/effect, preserve the prior
single writer or read/export path, quarantine/reconcile ambiguous state, never
blindly retry a payment/filing/provider effect, and rehearse corrected recutover.
No stage closes with active-capability compatibility debt, obsolete rules/RPCs,
unowned data, or an unrecorded acceptance criterion.

## Ticket boundary ledger

`External gate` values: `local` means safe local/synthetic work; `credential`
requires an approved credential and hosted target; `cost` requires provider,
estimate, recurrence/usage basis and cheaper alternative plus Kristian's explicit
approval; `data` requires approved terms/DPA/hosted controls and authority for
named-company data; `production` requires action-time authority; `public` covers
deployment, outreach, claims, ads and unrestricted opening.

| Ticket | Entry and exclusive zone | Output and acceptance evidence | Rollback, close, downstream, external gate |
|---|---|---|---|
| #188 | #139 closed; zone `L`. `architecture/compatibility.json` registry-enables banking/#140 as the next capability because its schema has no idle state, but open #188 route-blocks any #140 claim or banking migration; registry activation is not start authority | Ledger-owned full-year receiver/close contract, complete January-to-as-of coverage/gap topology, immutable economic/source/output bindings, and every #172 supported ledger pattern; `U C D W S X G G2` with typed downstream projection declarations | Block posting/close on gaps, unsupported cases, stale/unbound/mismatched facts or outputs; reverse rather than mutate; close only with official mappings, golden journals, receiving-contract facts and no duplicate rules. Actual canonical producer/calculator agreement is mandatory at #199. Then and only then claim #140. `local` |
| #140 | #188 closed; active ADR-0013 stage `banking`; zone `B` | CSV import, dedupe, suggestions, explicit acceptance, reconciliation and atomic ledger workflow; `U C D W S X G G2` | Disable import/acceptance, preserve previous single banking writer, reconcile source/idempotency IDs; delete banking facade/legacy rules before exit. Then #141; #189 continues independently. `local` |
| #189 | #140 exited; independent external provider-clearance lane, provider adapters only at system edge | Provider-neutral read-only port, local Neonomics/Enable conformance, sync/consent/recovery and CSV/CAMT.053 are complete; A9 still requires current written licence/coverage/commercial/legal/privacy/security/reliability/exit evidence and human `bank_aisp` signoff | Kill bank sync without inventing postings; retain file fallback and read/export; reconcile gaps/unknown provider outcomes. Does not block provider-neutral #141–#154, but must close before provider choice/activation, live bank use, #197 bank evidence, production banking or #198. Local fakes are `local`; provider contracts/credentials/live calls remain `credential cost production` |
| #141 | #140 closed; architecture registry active at `investments/#141`; #189 A9 is independent; active `investments` slice 1, zone `I` | Purchase validation, ledger workflow and acquisition lots through provider-neutral evidence seams only; `U C D W X G` | Atomic no-partial-state rollback; reconcile lots to ledger source IDs; remove purchase facade/rules. No provider-specific dependency or live-bank readiness claim. Then #142. `local` |
| #142 | #141 closed; same active zone `I` | Sale, FIFO allocation, gains/losses and remaining lots; `U C D W X G` | Reject oversell/invalid sale atomically; restore one investment writer; remove sale/FIFO facade. Then #143. `local` |
| #143 | #142 closed; same active zone `I`, stage exit | Received dividends/participation exemption and complete investment cleanup; `U C D W S X G G2` | Fail unsupported treatment before persistence; rollback/recutover positions/lots/postings; delete final investment facade/RPCs. Then #190. `local` |
| #190 | #143 exited; zone `I` | Complete domestic private/listed/fund purchase/sale/dividend/ownership patterns and reconciled filing facts; `U C D W S X G` | Hard-block foreign/crypto/derivative/reorganization/judgment cases; correct by owned reversals. Then #147. `local` |
| #147 | #190 closed; active `documents`, zone `D` | Validated private upload/preview/download/removal, quarantine/retention/hash, signed transfer and isolated row/object restore; `U C D W S X O G G2` | Preserve blobs, disable mutation, restore prior metadata writer without losing retention; delete direct web storage/document facade. Then #144. Hosted restore is `credential`; local is `local` |
| #144 | #147 exited; active governance slice 1, zone `G` | Owner dividend proposal/basis/approval/payment/readiness with ledger/doc contracts; `U C D W X G` | Block finalization/payment, preserve documents and ledger, reconcile workflow receipt; delete duplicate policy. Then #145. `local` |
| #145 | #144 closed; same active zone `G` | Shareholder-loan facts, validation, accounting and presentation; `U C D W X G` | Fail atomically and restore prior governance writer; no private-table collaboration. Then #148. `local` |
| #148 | #145 closed; same active zone `G`, stage exit | Decisions, reviewed facts, deterministic artifacts, signed immutable lifecycle and readiness; `U C D W S X G G2` | Block finalization/upload, preserve artifact hashes, rehearse rollback/recutover; remove subprocess bridge, legacy writers and governance facade. Then #191. `local` |
| #191 | #148 exited; zone `G` | Supported cash capital, loss coverage, owner/intercompany loans, bank debt and group contribution facts/documents/postings; `U C D W S X G` | Hard-block personal-company loans, foreign/non-cash/complex/consolidation/reorganization/judgment cases; owned correction/reversal only. Then #137. `local` |
| #137 | #191 closed; active `billing`, zone `BL` | Canonical plan/subscription/entitlement/refund policy and simulated provider port; `U C D W S X G G2` | Deny entitlement/consequential actions, quarantine ambiguous provider events, preserve disabled simulation; delete billing facade/TS policy. Then #192. `local`; no paid provider |
| #192 | #137 exited; zone `BL` | Exact NOK 1,490 incl. VAT company-year, definitive-eligibility checkout, recurring consent/renewal/cancel/refund/receipt/reconciliation and Vipps conformance | `U C D W S X O G`; stop checkout/charging, reconcile webhooks, preserve customer cancel/export and automatic refund. Then #150. Test adapter `local`; live adapter/charge/refund is `credential cost production` |
| #150 | #192 closed; active `authority_connections`, zone `AU` | System User/Maskinporten lifecycle, callback/token/scope checks, MFA operator controls, retries and observability; `U C D W S X O G G2` | Disable affected authority/filing operations, revoke/reconcile unknown outcomes, never expose credentials; delete authority facade/TS control policy. Then #151. Local fakes `local`; hosted credentials/provider calls `credential production` |
| #151 | #150 exited; active `shareholder_register_filing`, zone `RF` | RF-1086 readiness/payload/approval/journal/submit/feedback/receipt/archive with current golden/TT02 equivalence; `U C D W S X O G G2` | Kill submission, preserve journal/read/export, reconcile unknown outcome before retry; remove both CLI bridges/generic rows/facade. Then #146. Local/TT02 as authorized; real filing `credential data production` |
| #146 | #151 exited; active tax slice 1, zone `TX` | Tax-settlement validation/posting/bank match/presentation; `U C D W X G` | Block settlement atomically; reconcile bank/ledger receipt; remove duplicate rule. Then #152. `local` |
| #152 | #146 closed; same active zone `TX`, stage exit | Company-tax supported-scope calculation, XML/attachment gates, approval/journal/submission/feedback/receipt/archive; `U C D W S X O G G2` | Kill submission and reconcile unknown journal/cash/ledger effects; remove generic rows/TS calculations/facade. Then #153. Real filing `credential data production` |
| #153 | #152 exited; active `annual_accounts_filing`, zone `AA` | Annual-accounts calculations/XML/corporate evidence/hybrid signing/journal/feedback/receipt; `U C D W S X O G G2` | Kill filing, preserve governance/doc/ledger state and journal/read/export; remove generic rows/TS rules/facade. Then #193. Real filing `credential data production` |
| #193 | #153 exited; zones `RF`, then `TX`, then `AA`, never concurrently | Production-complete RF-1086 → tax → annual accounts. Before the first slice, create schema-validated `architecture/filing-production-slices.json`; it records each slice's two linked immutable gates/digests independently of ADR capability exits. Each sub-slice needs current schema/code list, TT02/service, representative final genuine-company result, correction and `U C D W S X O G G2 H` | Per-service kill switch, submit-once journal and unknown-effect reconciliation; close only after all three registered immutable sub-slices and old adapters are gone. Then #149. Credentials, named data and each real filing are separately `credential data production` |
| #149 | #193 closed; active `annual_compliance`, zone `AC` | Typed annual workspace over three published readiness/completion contracts; interview/deadlines/states/summaries; `U C D W S X G G2` | Preserve prior safe state, never override obligation decisions; remove six-file cycle, web readiness assembly and facade. Then #194. `local` |
| #194 | #149 exited; zones `AC` plus presentation-only shared UI under one integration owner | Complete calm journey across precheck/purchase/reconstruction/year/events/close/filings/archive/renewal/exit; `U C W S X G` plus WCAG 2.2 AA and ≥90% unaided/median support evidence | Keep canonical safe states and unsupported exit; revert presentation without changing business facts; close only after repeated confusion is fixed/rerun. Then #155. Representative users are `data/public` gated by #197 |
| #155 | #194 closed; active `audit`, zone `AD` | Atomic append-only public audit command/query for every consequential producer; actor/company/correlation/order/retention/redaction; `U C D W S X G G2` | Required audit failure blocks business commit; rollback restores the exact characterized mixed predecessor topology (Option-A continuations plus transaction-local future placements), reconciles immutable IDs, and never revives arbitrary writers; exit deletes every direct writer/facade. Then #156. `local` |
| #156 | #155 exited; active `notifications`, zone `N` | Owned intent/outbox, at-least-once delivery, dedupe/retry/terminal state/templates/redaction; `U C D W S O G G2` | Provider failure never rolls back committed business; retain pending intent and disabled/simulated delivery; remove old writers/workers/facade. Then #157. Local simulation `local`; external delivery `credential cost public` |
| #157 | #156 exited; active `company_archive`, zone `AR` | Deterministic archive from capability projections/contracts only; names/order/hashes/private access and incomplete-output discard; `U C D W S X O G G2` | Abort/discard incomplete output without source mutation; restore old exporter only as single writer during rehearsed rollback; delete broad direct-query exporter/facade. Then #195. `local` |
| #195 | #157 exited; zone `AR` | Official-schema/code-list SAF-T 1.40 and complete company-year archive reconciled to all facts/documents/payloads/receipts/audit; `U C D W S X O G H` | Fail closed on version drift/reconciliation, preserve source/read/export, isolated rows+objects restore; close only with golden and representative comparison. Then #199. Representative/hosted evidence is `credential data` |
| #199 | #195 closed and every canonical source/output owner exists; zone `CI`, no cross-capability writer | Actual source-owner January-to-close topology and executable stable-ID/hash agreement across ledger, bank, investments, governance, all filings, SAF-T, audit and archive; every #172 golden pattern against real calculators; `U C D W S X G G2` | Block close/readiness/export on incomplete, stale, drifted or unexplained facts; route fixes to one owner at a time and rerun the graph; no private-table reads, facade, or duplicate policy. Then #154 and #197's final archive/SAF-T tranche. `local`; representative data remains #197-gated |
| #154 | #199 closed and every capability exited; whole-repo contraction with one integration owner | Zero web business persistence, legacy rule/RPC/bridge/adapter/exception/debt; final manifests/docs/graph/tests; `C D W S X O G G2` | Contract artifacts apply only after preflight; rollback preserves canonical writers/read/export. Close with two immutable complete gates and recorded stage dispositions. Then #198 becomes implementation-chain-green. `local`; no deployment |
| #196 | #187 closed; zone `P`; may overlap only with explicit files not owned by serialized work | Homepage/free precheck/scope/price/refund/signup-consent-checkout shell/help/legal/SEO/privacy-safe aggregate funnel and capability-linked copy; `U C W S G` | Feature-gate checkout/live claims/analytics; revert public slice without business-state impact. Close when all rendered/copy/accessibility/performance/SEO/stop-rule evidence passes. Produces #179 lane 12 and opens #197 recruitment gate. Deployment/analytics/ads/outreach are `cost public` |
| #197 | Claim only after #196 closes; zone `V`, no code writer. Tranches: legal/DPA/hosted controls before named intake; ledger after #188; bank after #189; investments after #190; governance after #191; billing after #192; each filing after its #193 sub-slice; journey after #194; audit after #155; archive/SAF-T and final zero-difference acceptance after #199 | 8–12 company-years, pattern matrix, six near-boundary rejections, historical/live comparisons, UX/support, all three final genuine outcomes, zero unexplained material differences; `H X O` | Stop intake/effects, honor withdrawal/export/delete, log incident/refund/unsupported exit and rerun after fixes. Close only with named conclusions and immutable evidence. Then #198. `data credential cost production public` as applicable |
| #198 | Both #154 and #197 closed; zone `R`; immutable deployed candidate with switches off | Exact #179 record, all 12 lanes current and all 14 signoffs approved; deployed hash verification, kill/rollback/unknown-effect rehearsal; `H O G` | Any red/stale lane blocks admission and affected operation; systemic ledger/isolation/restore/eligibility/billing/submission failure stops all consequential operations while read/export remains. Founder signoff last. Charges/providers/filings/deployment/launch/ads each remain `cost production public` |

### Planned criterion map

`GH-<issue>-A<n>` is the stable ID for the nth acceptance bullet in the live
issue body at this snapshot. The map below is the planned evidence family, not a
claim that a future test exists or passes. Before each ticket is claimed, refresh
its live body and commit
`architecture/evidence/issues/<issue>/requirements.json`, mapping every stable
criterion ID to exact test/evidence paths, commands, source/version and expected
result. A not-yet-researched volatile official/provider source may be explicitly
`required-before-pass` at claim, but it must be pinned before its test/evidence can
turn green. Closing evidence fills exact source version, revision, result and
digest. A changed issue body requires an explicit map revision; criteria are never
silently renumbered.

| Ticket | Criterion → planned evidence family |
|---|---|
| #188 | A1→`U D W X`; A2→`U D S`; A3→`U X`; A4→`U D W`; A5→`U D W X`; A6→`C A`; A7→`D W S G G2` |
| #140 | A1→`C D W`; A2→`U D`; A3→`U D X`; A4→`C A`; A5→`A D`; A6→`D W S G G2` |
| #189 | A1→`H S`; A2→`U D S O`; A3→`D W X`; A4→`C D X`; A5→`H S O`; A6→`U S O`; A7→`S`; A8→`C S O W G` |
| #141 | A1→`C D W`; A2→`U X`; A3→`U D S`; A4→`C A D`; A5→`A D` |
| #142 | A1→`C D W`; A2→`U D X`; A3→`U D`; A4→`C A`; A5→`A D` |
| #143 | A1→`C D W`; A2→`U X`; A3→`U D`; A4→`C A D`; A5→`A D`; A6→`D W S X G G2` |
| #190 | A1→`U C D X`; A2→`U W X`; A3→`U D W`; A4→`X`; A5→`D S W X G`; A6→`A D` |
| #199 | A1→`C D W X`; A2→`U D X`; A3→`U D X`; A4→`U X`; A5→`D S X`; A6→`U D W X`; A7→`X`; A8→`C A D W S G G2`; A9→`H X` |
| #147 | A1→`C D W`; A2→`U D S`; A3→`D O X`; A4→`C A`; A5→`C A D`; A6→`C X`; A7→`A D`; A8→`D W S O G G2` |
| #144 | A1→`C D W`; A2→`U X`; A3→`D S`; A4→`U X`; A5→`C A`; A6→`A D` |
| #145 | A1→`C D W`; A2→`U D X`; A3→`D S`; A4→`C A`; A5→`A D` |
| #148 | A1→`U C W X`; A2→`U D S`; A3→`U X`; A4→`C W`; A5→`A C`; A6→`A D`; A7→`D W S X G G2` |
| #191 | A1→`U C D W X`; A2→`U H`; A3→`U D W`; A4→`X`; A5→`D S W X G`; A6→`A D` |
| #137 | A1→`C D W`; A2→`U W`; A3→`U D S`; A4→`D S`; A5→`C A`; A6→`A D`; A7→`D W S G G2` |
| #192 | A1→`U C D W`; A2→`U D`; A3→`U D`; A4→`C D S O`; A5→`U D X`; A6→`W O`; A7→`C S`; A8→`D S W X G` |
| #150 | A1→`C D W`; A2→`U D S`; A3→`D S O`; A4→`U D O`; A5→`C A`; A6→`A D S`; A7→`D W S O G G2` |
| #151 | A1→`U C X H`; A2→`D S O`; A3→`U D S O`; A4→`C W`; A5→`A D`; A6→`D W S X O G G2` |
| #146 | A1→`C D W`; A2→`U X`; A3→`U D S`; A4→`C A`; A5→`A D`; A6→`A D` |
| #152 | A1→`U C X H`; A2→`U D X`; A3→`U D S O`; A4→`C W`; A5→`A D`; A6→`D W S X O G G2` |
| #153 | A1→`U C X H`; A2→`U D X`; A3→`U D S O`; A4→`C W`; A5→`A D`; A6→`D W S X O G G2` |
| #193 | A1→`U C H`; A2→`U C D S X O`; A3→`H X`; A4→`D S O`; A5→`W O`; A6→`D S W O G G2`; A7→`A D` for each RF→tax→accounts registered sub-slice |
| #149 | A1→`C W X`; A2→`U X`; A3→`D S W`; A4→`A C`; A5→`A D`; A6→`D W S X G G2` |
| #194 | A1→`U W`; A2→`U C W`; A3→`U W S`; A4→`W S`; A5→`W H`; A6→`C A`; A7→`H W`; A8→`W S G` |
| #155 | A1→`C D X`; A2→`D S`; A3→`U D S`; A4→`C D S`; A5→`C D X`; A6→`A D`; A7→`D W S X G G2` |
| #156 | A1→`C D`; A2→`U D O`; A3→`D O`; A4→`U S`; A5→`S H`; A6→`A D`; A7→`D W S O G G2` |
| #157 | A1→`U C X`; A2→`C A X`; A3→`A D`; A4→`U D O`; A5→`A D`; A6→`D W S X O G G2` |
| #195 | A1→`U C H`; A2→`U C H`; A3→`X`; A4→`U X`; A5→`D S O`; A6→`C A`; A7→`U D W S X O G H` |
| #154 | A1→`A C`; A2→`A D`; A3→`A G`; A4→`A C G`; A5→`H G`; A6→`C D W S X O G G2` |
| #196 | A1→`U W`; A2→`U C W`; A3→`U C S`; A4→`C S`; A5→`S H`; A6→`U S`; A7→`C W S G`; A8→`U S O`; A9→`H S O` (negative authority proof: no deployment/tracker/ads/contact) |
| #197 | A1→`H`; A2→`H S O`; A3→`U X H`; A4→`X H`; A5→`X H`; A6→`W H`; A7→`H X`; A8→`H O`; A9→`H X O` |
| #198 | A1→`H G`; A2→`H G`; A3→`H`; A4→`O S`; A5→`O S`; A6→`H O`; A7→`O H`; A8→`H` |

## #179 requirement-to-evidence ledger

Each lane is accumulated by its producers and rechecked on the exact #198 launch
candidate. “Primary signoff” does not eliminate other reviewers required by the
ticket.

| #179 lane | Producing tickets | Required accumulated evidence | Primary signoff(s) |
|---|---|---|---|
| 1 Boundary/product completeness | #187, #188, #190, #191, #192, #193, #194, #195, #196, #197 | versioned supported/clarify/block matrix from public precheck through runtime; full-year only-product journey; every pattern golden + representative | `supported_boundary_validation` |
| 2 Architecture/migration | #138, #139, #140, #141/#142/#143, #147, #144/#145/#148, #137, #150, #151, #146/#152, #153, #149, #155, #156, #157 and final #154 | 15 exited capabilities, sole implementations/writers, zero active debt/obsolete paths, contracts/manifests/graph/builds and immutable gates | `architecture_migration_release` |
| 3 Accounting/SAF-T/archive | #188, #190, #144/#145/#148/#191, #146, #151/#152/#153/#193, #195 and #197 | exact ledger/investment/governance/filing/SAF-T/archive reconciliation, retention/reproduction/restore and versioned risk mapping | `accounting_system_saf_t_archive` |
| 4 Each production filing | #151, #152, #153, #193, #197 | separate current RF-1086/tax/annual-accounts schema, TT02/service, AAL2, journal, final feedback/correction/receipt/archive and genuine final outcome | `rf1086_authority`, `company_tax_authority`, `annual_accounts_authority` |
| 5 Authority/identity | #138, #150, #151–#153, #193 | deployed tenant/auth/AAL2, System User/Maskinporten, callback/token/secret/revocation/recovery and customer/operator separation | three authority signoffs plus `security_restore_incident_capacity` |
| 6 Banking | #140, #189, #197 | written AISP coverage/licence/contract/privacy/security/reliability/cost/exit plus sync/dedupe/reconnect/gap/file fallback/ledger evidence | `bank_aisp` |
| 7 Billing | #137, #192, #197 | exact offer, definitive eligibility, Vipps test lifecycle and separately authorized low-value live charge/full refund | `billing_refund`, `seller_terms_pricing` |
| 8 Security/privacy/legal/data | every code ticket, especially #147, #150, #155, #156, #195; public/legal #196; hosted #197 | deployed isolation/least privilege/MFA/secrets/headers/scans/abuse/redaction/support/audit/delete/export; RPO≤1h/RTO≤4h restore; pinned seller/privacy/DPA/subprocessors/roles/retention/incident/claims | `privacy_dpa_subprocessors`, `seller_terms_pricing`, `security_restore_incident_capacity` |
| 9 Reliability/monitoring/incident/capacity/rollback | #189, #192, #193, #147, #195, #154, #197 | correlated health/alerts and 15-minute coverage rule; ≥50 sessions, 10 imports, 10 callbacks/s and p95<2s excluding provider; independent kill/rollback/read-export/unknown-effect drills | `security_restore_incident_capacity` |
| 10 Frontend/accessibility/support | #194, #196, #197 | calm checklist with one action, short Norwegian, progressive detail, prefill, automatic visible save, exact shared states and actionable errors; representative confusion/unaided/support thresholds; automated checks plus keyboard-only use, focus order/visibility, screen-reader labels/status, contrast, error identification, 200% zoom/reflow and 390px checks; Norwegian help/contact ownership without accounting service | `accessibility_ux_support` |
| 11 Representative validation | #197 fed by all completed slices | 8–12 years, twice-covered common patterns across real+golden, six boundary rejects, zero unexplained material differences/incidents/duplicates/judgment dependency, ≥90% unaided and median <30m | `supported_boundary_validation` plus accounting, authority, security/privacy, UX and operations conclusions |
| 12 Public marketing/acquisition | #196, #197, #198 | rendered truthful public/checkout/legal/SEO/measurement/copy/stop rules; no capability ahead of evidence, formal coverage percentage, authority endorsement, guaranteed correctness or hidden provider limitation | `claims_marketing`, `seller_terms_pricing`, `privacy_dpa_subprocessors` |

## Fourteen signoffs and their producers

| Signoff | Earliest complete producer set |
|---|---|
| `architecture_migration_release` | every capability exit plus #154 and exact-sha gates |
| `seller_terms_pricing` | #192 + #196 + final rendered #198 candidate |
| `privacy_dpa_subprocessors` | #189/#192/#193 provider records + #196 legal/consent + #197 hosted-data evidence |
| `accounting_system_saf_t_archive` | full lane 3: #188, #190, #144/#145/#148/#191, #146, #151/#152/#153/#193, #195 and #197 |
| `supported_boundary_validation` | full lane 1: #187, #188/#190/#191/#192/#193/#194/#195/#196 and #197 |
| `rf1086_authority` | #151 + RF sub-slice #193 + final genuine #197 outcome |
| `company_tax_authority` | #152 + tax sub-slice #193 + final genuine #197 outcome |
| `annual_accounts_authority` | #153 + accounts sub-slice #193 + final genuine #197 outcome |
| `security_restore_incident_capacity` | cross-ticket security evidence + #147/#189/#192/#193/#195 restore/incident/capacity + #197 hosted proof |
| `accessibility_ux_support` | #194 + #196 + #197 representative thresholds |
| `bank_aisp` | #189 provider/technical evidence + #197 live-year evidence |
| `billing_refund` | #192 full lifecycle + separately authorized live rehearsal before #198 |
| `claims_marketing` | #196 rendered claims/measurement + final lane reconciliation in #198 |
| `founder_unrestricted_go_live` | #198 only, last, after the other 13 and all lanes are green |

Every signoff records reviewer/role, time, exact evidence digest/link and
scope/version, expiry/recheck, decision and conditions. No signoff can waive a
red lane.

## Freshness and immutable evidence protocol

CI, deployed runtime gates, provider feature flags and human clearance are
independent controls; none may infer approval from another. Any missing, expired,
rejected or conditionally out-of-scope item makes its lane red.

- Exact launch SHA: builds/scans, migration parity, generated contract,
  capability manifest, architecture, rendered copy and accessibility for the
  shipped journey.
- At most 30 days old at launch: hosted isolation/storage/restore,
  incident/alert/rollback drills, bank/billing/authority connectivity and
  credentials.
- Immediately current and drift-monitored: filing schemas/code lists,
  permissions and provider status.
- Materially identical launch boundary/release: representative validation.
- Every material change and at least annually: terms, DPA, subprocessors/provider
  contracts, official accounting/legal mappings.
- Launch release and every material journey redesign: accessibility.
- Launch release and whenever forecast load doubles: capacity.

For each ticket:

1. Claim in GitHub immediately before work; quote the exact predecessor evidence.
2. Record acceptance criterion → test/evidence ID → file/artifact → result. Link
   volatile official/provider facts rather than copying them into this document.
3. Keep commits small and attributable. Generated output follows its source in
   the same slice. Contract/rollback artifacts are separate from automatic
   additive migrations.
4. Run focused tests first, then the proportional `U/C/D/W/S/X/O/G` envelope.
5. For capability exit, commit the `exit-review` candidate R1; run the complete
   gate on R1; commit R1's immutable attestation/transcript to produce R2; run the
   second gate on R2 with `previousPassingRevision=R1`; commit R2's immutable
   attestation/transcript; only then register both canonical evidence digests and
   advance the registry to the successor in a later commit. Neither evidence
   commit is itself substituted for the revision it attests.
6. Publish the branch before citing commits. Close only after the GitHub evidence
   comment lists every criterion, exact immutable revisions/digests, rollback/
   recutover result, residual warnings and downstream state.
7. Update this requirement ledger; then inspect the live next ticket before
   claiming it.

Current immutable pointers:

- foundation recovery: `602629f7a8d3ce28a49de9a5e280162405b617e3`
  then `c41c11561455e117f0fc8d0fefe6083033c26ed5`.
- `company_access`: `65ea378dd74225a56f15ace603e1343b00dbac31`
  then `de35d1ead93ea28e9f9878b3cb57d460c7583c33`.
- `ledger`: `70c843018069caeaabf6b95eb33c72852397b89e`
  then `21a6c0bcdadeecfcc316e794f5c928a1533e86e3`; canonical
  evidence digests are recorded in `architecture/compatibility.json` and closure
  evidence is [#139 comment 5436264918](https://github.com/kristianelmer/Talli/issues/139#issuecomment-5436264918).
- partial #196 public lane: `df9b93a9` is an ancestor and its truthful
  free-recruitment homepage evidence is [#196 comment 5432587019](https://github.com/kristianelmer/Talli/issues/196#issuecomment-5432587019). It is not #196 closure or public-launch clearance.
- current control-plane revision before this document: `3ec163ef`; worktree branch
  `codex/issue-139-ledger-cutover-successor` is published.

## Loop breakers and escalation rules

- Live GitHub state, accepted ADRs, machine-readable registries and immutable
  evidence outrank stale ticket prose. Correct a stale blocker with a linked fact;
  do not infer a completed prerequisite while its issue is open. A
  `ready-for-agent` label means the ticket is specified, not that its live
  `Blocked by` edges are satisfied or that it may be claimed early.
- Do not reopen settled product decisions without contradictory official,
  provider, representative, or repository evidence. Route provider change,
  official schema/rule drift, disproved practical-majority coverage,
  customer-specific accounting work, or a requested price/seller/promise/date
  change back to its owning decision.
- At a cross-capability seam, stop speculative variants after one characterized
  mismatch. Name the transaction owner, public contracts, data owner, failure
  semantics and ADR impact. Escalate a genuinely new architecture decision;
  never iterate competing persistence writers.
- After two repeated diagnostics with the same result, verify the harness and
  immutable inputs. After a third identical external blocker, record it as a
  genuine blocker and continue all safe independent work.
- Unknown payment, filing or provider effects are reconciled from permanent
  journals before retry. Never trade ambiguity for schedule.
- Cost approval must name provider, best estimate, one-time/recurring/usage basis
  and a free/cheaper alternative. General authority to finish or launch is not
  spending authority.
- Credentials, legal acceptance, customer/outreach/data authority, live provider
  activation, charge/refund, production filing, deployment/public claims/ads and
  launch are action-time gates. When one blocks, continue local tests, adapters,
  documentation, synthetic evidence, accessibility and rollback work that does
  not cross it.
