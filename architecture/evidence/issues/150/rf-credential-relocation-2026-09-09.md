# Approved exact scope: #150 RF credential relocation

Status: **approved for implementation, not yet applied**. Base `b30312de11ad942479421def243e4a2252fbf166`. Kristian approved the [exact proposal and scope](https://github.com/kristianelmer/Talli/issues/150#issuecomment-5601305923) with **“Approve the exact relocation”**, recorded in [the owner decision](https://github.com/kristianelmer/Talli/issues/150#issuecomment-5601323119). The following source inventory binds the amendment; no provider activation, real filing or production promotion is authorized.

## Exact registry deletions

Only these eight **future #151** tuples may be removed by this approved exact exception. Every tuple has record `compat-rf1086-persistence`, path `apps/web/app/actions.ts`, rule `direct-web-business-persistence`, removal issue `#151`:

| Operation | Resource |
|---|---|
| `reconcileRf1086ProductionAction` | `rpc:claim_production_feedback_reconciliation` |
| `reconcileRf1086ProductionAction` | `rpc:release_production_feedback_reconciliation` |
| `reconcileRf1086ProductionAction` | `table:filing_approval_snapshots` |
| `reconcileRf1086ProductionAction` | `table:filing_previews` |
| `reconcileRf1086ProductionAction` | `table:production_filing_submissions` |
| `sendApprovedRf1086ProductionFiling` | `rpc:begin_production_filing` |
| `sendApprovedRf1086ProductionFiling` | `table:filing_approval_snapshots` |
| `sendApprovedRf1086ProductionFiling` | `table:filing_previews` |

The same two operations each also have `table:system_user_requests` at the same path/rule in **current** `compat-authority-connections-persistence`, removal issue `#150`. Those two deletions already fall within active owner cutover; they do not authorize any of the eight future deletions above. No whole RF facade deletion, baseline edit, other future tuple/count change or new scope is included. Delete the effects for both named coordinators together with source proof; preserve the one frozen RF implementation and its original ownership.

## Exact transitive source boundary

The two exported actions start at `actions.ts:5926` and `:6099`. Their in-scope transitive implementations are the following existing functions, only as used by those two actions:

| Source/function | Existing persistence/effect |
|---|---|
| `actions.ts:5702` `createRf1086DatabaseJournal` | `production_filing_events`: read latest operation ordered `created_at desc`, insert initial prepared event, read event's submission ID; call `append_production_filing_event` for success/failure. Maintain persisted body hash/idempotency key, successful result reuse, unknown-state stop and attempt cap 20. |
| `actions.ts:5788` `createRf1086FeedbackJournal` | Read `production_filing_submissions` feedback state/safe error/correlation; read `production_feedback_artifacts` SHA-256 set; invoke `append_production_feedback_reconciliation`. Store/remove feedback through the already-published Documents contracts, detailed below. |
| `actions.ts:5885` `claimRf1086FeedbackLease` | `claim_production_feedback_reconciliation` with exact submission + new lease UUID. |
| `actions.ts:5898` `readClaimedRf1086ForsendelseId` | Read `production_filing_submissions.feedback_forsendelse_id` filtered by both submission ID and exact current lease ID. |
| `actions.ts:5915` `releaseRf1086FeedbackLease` | `release_production_feedback_reconciliation` with same submission + lease. |
| `lib/rf1086-feedback-persistence.ts:37` `createRf1086FeedbackArtifactRecorder` / nested `recordArtifact` | Read `production_feedback_artifacts` by submission + SHA-256 before upload and after ambiguous persistence; call `record_production_feedback_artifact`; verify byte length/hash; preserve existing conditional cleanup of losing/uncommitted document. |
| `lib/rf1086-production.ts` | `executeRf1086ProductionRelease`, `executeJournaledRf1086Production` and `reconcileJournaledRf1086Production`, including their existing pure journal/state/retry/error/reference/hash helpers. Remain one frozen RF-owned state machine; do not put RF classifications/statutory rules into Authority Connections. |
| `lib/rf1086-feedback.ts` | Existing feedback classifier used by reconciliation, unchanged schema/reference/year/classification behavior. |
| `lib/rf1086-authority-client.ts:287` | Only the five existing typed methods below, with current parsing/bounds/error handling and fixed hosts. Shared test/evidence consumers are not implicitly migrated. |
| `lib/rf1086-submission.ts:115` and `lib/maskinporten.ts` | Production flag/config and credential acquisition used by these two coordinators; delete their credential exposure from web after cutover. Move RS256 grant/signing/token validation through owned backend authority ports. Do not replace the entire simulation/filing library or unrelated caller behavior. |

These helper effects exist in source but are not additional registered direct-export tuples in the current compatibility record. The amendment binds their existing resource set and behavior explicitly; it must not create a generic allowance for unregistered future effects.

The existing SQL contracts in scope are **invocation-equivalent compatibility implementations**, with only necessary actor/role/owner-resource seams reviewed for the cutover:

- `begin_production_filing(uuid)`, latest body `supabase/migrations/20260716125903_rf1086_system_user_requests.sql:597`, as subsequently rewritten by the billing contract.
- `append_production_filing_event(uuid,text,text,integer,text,uuid,text,text,text,boolean)`, `20260715180000_controlled_production_beta.sql:459`.
- `record_production_feedback_artifact(uuid,uuid,uuid,text,text,bigint,text,text)`, `20260716155621_rf1086_feedback_reconciliation.sql:229`.
- `claim_production_feedback_reconciliation(uuid,uuid)`, same file `:317`.
- `release_production_feedback_reconciliation(uuid,uuid)`, same file `:388`.
- `append_production_feedback_reconciliation(uuid,uuid,uuid,text,text[],text,text)`, same file `:415`.

Do not reproduce obsolete service-role authority as an ordinary backend business repository. Exact verified actor and least-privilege invocation must replace it without bypassing the existing release/identity checks or creating a second journal writer. This addendum grants no independent authority to move RF tables/schema/row families.

## Exactly five RF HTTP operations

Existing production base: `https://api.skatteetaten.no/api/aksjonaerregister/v1`. Existing test base: `https://api-test.sits.no/api/aksjonaerregister/v1`. These are current source constants, **not a new provider conformance or activation claim**. No caller chooses the base/host/path/method.

| Method in `rf1086-authority-client.ts` | HTTP template | Exact source of arguments |
|---|---|---|
| `postHovedskjema` `:347` | `POST /{incomeYear}/1086H` | Original approved preview's main XML/year; exact persisted operation UUID as `idempotencyKey`; XML content type. |
| `postUnderskjema` `:363` | `POST /{incomeYear}/{hovedskjemaId}/1086U` | Same approved preview's sorted subdocument XML; original persisted/recovered main ID; same persisted per-document operation UUID. |
| `confirm` `:381` | `POST /{incomeYear}/{hovedskjemaId}/bekreft?antall_underskjema={count}` | Approved subdocument count and original main ID; original persisted confirm UUID. |
| `listDocuments` `:405` | `GET /{incomeYear}/forsendelser/{referenceId}/dokumenter?page={page}&size={size}` | Original confirmed/lease-bound `forsendelseId`; existing calls use page 0 and size 50. Do not substitute arbitrary caller reference or add dialog fallback to this journalled flow. |
| `getDocument` `:455` | `GET /{incomeYear}/forsendelser/{forsendelseId}/dokumenter/{documentId}` | Same confirmed/lease-bound submission reference; document UUID returned by the preceding strict list response. |

Preserve no redirects, bounded timeouts (current default 20s), 64 KiB JSON, 10 MiB document cap, exact allowed document MIME types, response/error validation and safe correlation handling. Initial reconciliation permits at most five polling iterations with 2s waits; owner retry performs one polling iteration. Each iteration preserves the existing per-document `getDocument` GETs; this is not a cap on total HTTP reads. Unknown mutations remain blocked pending reconciliation, never a new POST. The new backend contracts accept only original authorized approval/submission identity and explicit intent. They do not take arbitrary XML, HTTP operations, org/scope, provider references, credentials or caller-stated success.

Maskinporten's existing token exchange is the separate Authority Connections credential operation required to authorize these RF calls; it is not a sixth RF filing method. Credentials/token/grant never return to web. No generic authority proxy or new provider endpoint is included.

## Billing, authorization, documents and audit preservation

**Send and reconcile have different rules; do not accidentally strengthen recovery into new-filing eligibility.**

- Send: current `actions.ts:5937–6086` checks explicit production enablement, authenticated session, valid approval, fresh production-filing MFA, current exact billing entitlement, original System User relation and payload/manifest. Acquire/discard delegated token with current order: **token before `begin_production_filing`**, then external execution. A token failure must leave no new submission. `begin_production_filing` locks exact System User first, linked entitlement second and rechecks existing permission/readiness/override/review-comment/launch-signoff requirements. Preserve the original six signoff keys and restore freshness rule.
- Reconcile: `actions.ts:6146–6319` uses stored submission relationship even after current billing eligibility expires. It does **not** call `loadBillingEntitlement` or reimpose fresh production-filing MFA; terminal `accepted/rejected/action_required` returns stored state early. It still requires authenticated owner and exact stored approval/entitlement/company/year/obligation/profile/System User/preflight relationship for a nonterminal retry. Do not add current-active entitlement/approval-expiry rejection or a new-filing release gate to this recovery operation. Preserve **claim lease → read original confirmed reference → token → read-only provider reconciliation → discard token → finally release lease**. Busy lease returns existing busy/manual-retry outcome.
- #137 billing: the actions call published `loadBillingSnapshot`; send additionally calls `loadBillingEntitlement`. They do not directly mutate payment/entitlement state, mark an entitlement completed, charge or refund. `supabase/contract-migrations/20260905013000_billing_contract.sql:20–57` rewrites legacy SQL relation references to `billing.production_pilot_entitlements` before dropping overlap views. Preserve that already-contracted reader/lock collaboration and public billing authority; never revive public billing views or add a billing mutation under this amendment.
- The separate System User accepted→verification-failed pilot suspension is part of the owned lifecycle cutover, **not a side effect of these two RF operations**. Do not smuggle it into the RF relocation scope.
- Documents: `createRf1086FeedbackJournal` calls `uploadDocumentObject` through signed document upload with type `authority_feedback`, link `production_filing_submission:{id}`, original company/year/user, exact bytes/header/length and immutable SHA-256; current idempotency keys are `rf1086-feedback-stage:{documentId}` and `rf1086-feedback-finalize:{documentId}`. Conditional cleanup uses `removeDocument`, reason `producer_rollback`, key `rf1086-feedback-cleanup:{documentId}`. Preserve these owned document operations, storage transfer and compensation through public ports, with existing audit consequences. No direct Documents table/storage ownership transfer is included.
- Audit: no direct `audit_events` insertion or standalone append-audit call exists in these two actions, journal helpers, or the six listed filing SQL routines. Their durable filing event journal and feedback artifact receipts are the direct evidence effects. Preserve those exact writes, plus existing audit behavior behind already-published Company Access/Billing/Documents contracts; do not invent a new audit continuation, move an audit append across a transaction, or remove existing owned-contract audit as part of relocation. The separate global authority-operation audit remains #150's normal scope.

## Review checklist addressed by the parent proposal

1. Replace “Before editing, enumerate …” with a binding reference to this concrete tuple/helper/HTTP inventory.
2. Qualify “fresh MFA, entitlement, accepted approval … remain required” per operation above. Applying send eligibility to reconciliation would contradict the existing expired-entitlement recovery behavior.
3. Keep RF payload/approval/state/feedback rules in a frozen RF compatibility implementation; Authority Connections supplies only its owned credential/connection/provider port. No RF owner reassignment.
4. Explicitly preserve the published Documents upload/finalize/compensation path, the #137 contracted billing reader/lock seam, and the absence of new RF audit side effects.
5. This exact two-operation decision does not authorize migrating the separate TT02 evidence scripts for tax/accounts/RF or the token-smoke CLI. Account for their credential path under #150 separately; do not claim the two-operation change alone deletes every TypeScript credential consumer.

## Physical implementation boundary

The one frozen RF implementation is `apps/backend/src/talli_backend/compatibility/rf1086_authority_workflow.py`, with invocation-equivalent persistence at `apps/backend/src/talli_backend/adapters/postgres_legacy_rf1086_authority.py`. Any extracted helper stays in the same frozen RF boundary and is listed before editing. Authority Connections supplies credential and connection contracts only. #151 absorbs/removes this compatibility implementation.

Before implementation, the existing five-method HTTP helper is assigned to
`apps/backend/src/talli_backend/adapters/rf1086_authority.py`, bound only to the
frozen RF workflow's typed port. It relocates exactly the enumerated
`rf1086-authority-client.ts` methods, response parsing and transport bounds; it
adds no endpoint, provider authority or generic relay. The existing feedback
classifier and journal/state helpers remain inside the single
`compatibility/rf1086_authority_workflow.py`. These are the same enumerated source
helpers above, with RF ownership preserved until #151 absorbs/removes them.

## Approval serialization and document-order equivalence

The relocated coordinator reads the existing immutable approval row's `manifest`
alongside its `manifest_hash`. It rebuilds the current manifest from the original
preview, actor and company, validates every stored document name/hash against the
current XML bytes, and preserves the approved document-array order. It then
compares all manifest fields and the original SHA-256. It does not regenerate
approval state or transfer its ownership. This preserves the order already
chosen by the web's `localeCompare` without depending on the backend host locale.
JavaScript integer object-key ordering, UTF-16 warning sorting, `trim` characters
and well-formed JSON string escaping are retained explicitly.

The production subdocument write order uses the stored shareholder UUIDs. The
shipped `buildNoActivityRf1086Case` in `apps/web/app/lib/rf1086.ts` takes `shareholder.id`
unchanged from PostgreSQL; the same renderer uses `snapshot.shareholder_id` as
each `underskjemaXml` key. Canonical lowercase UUIDs have identical hyphen
positions and the same lexical and original `localeCompare` order. A malformed
stored production preview with noncanonical keys fails before token acquisition,
journal creation or provider effects. Generic renderer/test inputs with arbitrary
identifiers do not establish another production basis. The standalone RF tool
retains its separate fixed JSON-only Node ordering helper under the independently
approved command-relocation scope.

`test_rf1086_compatibility.py` compares against the retained pure web approval
builder using mixed case, combining/non-ASCII characters, astral characters,
integer-like keys, JavaScript whitespace and UUIDs. It also rejects missing or
tampered approval fields and noncanonical production keys before any external
effect. The API runtime has no Node or ICU dependency.
