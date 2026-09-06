# Billing backend capability

<!-- architecture-inventory
{"dependencies":[],"ownedTables":["billing.billing_accounts","billing.billing_payment_events","billing.production_pilot_entitlements","billing.annual_purchases","billing.annual_refund_cases","billing.annual_operations","billing.annual_cancellation_requests","billing.annual_refund_requests"],"ports":["BillingPersistence","BillingPaymentProvider","AnnualBillingProvider","AnnualCheckoutPersistence","AnnualCancellationPersistence","AnnualAgreementCleanupPersistence","AnnualBillingReadPersistence","AnnualRefundPersistence"],"publicEntryPoints":["talli_backend.modules.billing.public"]}
-->

## Purpose and ownership

`billing` owns annual offers, purchases, renewals, refunds and provider evidence,
plus historical billing records, cleanup and exact production-pilot exemptions.
Its relations are private capability storage; browser and presentation code never
query or mutate them directly. The billing entitlement decision is consumed by
readiness and production release gates.

The capability does not own filing content, filing readiness, authority,
company membership, authentication, or launch signoffs. Those facts arrive
through the application and persistence ports, and billing returns a decision
rather than exposing its policy for callers to reimplement.

## Public interface

Import only `talli_backend.modules.billing.public`. Commands carry a company,
verified actor, correlation ID, and durable idempotency key. Historical account
prices remain stored evidence. New account configuration, subscription activation
and filing-package purchases are retired; their deprecated HTTP endpoints reject
new acquisition with `BILLING_LEGACY_ACQUISITION_RETIRED`. Exact historical payment
replay and bounded reconciliation remain available. Current generated web clients
expose annual history/cancellation and legacy cleanup, without acquisition methods.

The exported commands are `ActivateSubscriptionCommand`,
`CancelSubscriptionCommand`, `ConfigureBillingAccountCommand`,
`ManageProductionPilotEntitlementCommand`, `MarkBillingUnsupportedCommand`,
`PurchaseFilingPackageCommand`, and `RefundFilingPackageCommand`. Queries and
results are `BillingEntitlementQuery`, `BillingEntitlementDecision`,
`BillingSnapshotQuery`, and `BillingSnapshot`. The remaining public vocabulary
is `BillingAccount`, `BillingCommands`, `BillingQueries`, `BillingObligation`,
`BillingPlan`, `BillingPilotCaseProfile`, `BillingPricing`, `BillingStatus`, `BillingPaymentEvent`,
`BillingPaymentEventId`, `BillingPaymentKind`, `BillingPaymentStatus`,
`BillingProviderIntent`, `BillingProviderResult`, `ProductionPilotEntitlement`,
`ProductionPilotEntitlementId`, `ProductionPilotStatus`, and
`SystemUserRequestReference`. `expected_payment_status` is the canonical mapping
from a payment kind to its successful terminal state. Failures use `BillingError` and
`BillingErrorCode`.

`BillingEntitlementDecision` is the only production billing gate. It expresses
whether readiness may continue, whether a charge may be initiated, whether
filing is allowed, and whether an exact active pilot entitlement provides the
billing exemption. Missing data and dependency failures fail closed.

`apps/backend/tests/test_billing_equivalence.py` executes a frozen semantic
oracle from base revision `4f807fe4239a208c573054b14cbed478277d1a2e`
against the canonical service with the same IDs and clock. Issue #192 deliberately
supersedes account resets, legacy acquisition and legacy paid entitlement. The
oracle now verifies that difference while preserving historical payment facts,
cleanup effects, duplicate replay, recovery quarantine and exact pilot identity
and time bounds. Database tests retain tenant, fresh-MFA, rollback and recutover
coverage by seeding genuine predecessor history before the retirement migration.

## Ports and adapters

The #192 annual-offer work introduces `AnnualBillingOffer`,
`AnnualRefundFacts`, `AnnualRefundReason`, `AnnualRefundDecision`,
`AnnualRenewalFacts`, and `AnnualRenewalDecision`. The internal `annual_policy`
module pins the NOK 1,490 gross company-year offer and derives renewal notice,
paid/read-export dates, and automatic refund amounts from recorded facts. Amounts
are integer minor units; Norwegian calendar dates govern month and notice limits.
These policy types alone do not initiate payment. The #192 acceptance record tracks the remaining persistence/API/provider/web
cutover and distinguishes local conformance from actual Vipps merchant-test proof.

`BillingPersistence` owns all reads and writes to `billing.*`. The Supabase
adapter authenticates the bearer token, scopes reads through RLS, and performs
each payment-event/account transition atomically. Non-provider commands use
the backend-system technical `billing.billing_command_receipts` for exact durable replay and reject a reused
key when its canonical request fingerprint differs. `BillingPaymentProvider`
accepts only a provider-neutral intent and must honor its idempotency key.
Before provider execution, persistence commits a `created` payment event with
its original company, kind, year, obligation, amount, provider, and key. Only the
winning insertion executes. A retry of an unfinished event calls read-only
`reconcile` with that stored intent, under a bounded deadline, and never issues
another payment. Unknown results remain pending without granting entitlement.
Confirmed cleanup outcomes and their account changes settle atomically. Historical
acquisition reconciliation records the outcome without activating paid account
flags. A new historical refund can use one confirmed original payment in the exact
company/year/provider scope when those flags are false; its recorded amount is
used, and missing or ambiguous originals fail closed. A database account lock
reserves one new historical refund atomically. Any prior refund intent blocks a
different key; the original key still reconciles. New recovery-based claims bind
the immutable original event/reference and reject amount/provider/year changes.
Settlement preserves that binding. Cleanup controls remain
reachable and the backend validates the request. Terminal events replay without
reapplying account effects. Changed filing obligations reject key reuse.

`BillingPilotCaseProfile` types the closed pilot record/administration scope.
Entitlement queries retain open strings so an unknown profile continues to fall
back to ordinary billing without narrowing the HTTP contract.

Pilot administration validates the initiating owner through the versioned
`company_access_is_accepted_owner_subject_v1` database contract. That predicate
and its lifecycle remain company-access-owned; billing has `EXECUTE` only and
never reads membership storage or implements membership policy.

Adapters register through `billing_persistence_adapter` and
`billing_provider_adapter`.

The registered provider is `SimulationBillingProvider`. It is explicitly
production-disabled and performs no external or paid operation. Adding a live
provider requires a new adapter, conformance tests, and explicit owner approval
before any paid action or production activation.

## Migration and rollback

`20260905010000_billing_capability.sql` moves the physical tables into the
private schema and temporarily exposes security-invoker views for deployment
overlap. `supabase/contract-migrations/20260905013000_billing_contract.sql` rewrites downstream database
readers and removes those views plus the obsolete write RPC. Matching rollback
artifacts restore the immediately preceding topology; the lifecycle test
rehearses expansion and contract rollback/cutover twice. Durable command receipts
move to a quarantined `backend_system` relation during expansion rollback and
return to `billing` on recutover, so rollback never erases replay history.

`20260905061339_billing_provider_reconciliation.sql` grants the initiating owner
with fresh MFA permission to settle pending events through the restricted billing
role. Apply it after expansion. On expansion rollback, first apply its matching
rollback to withdraw settlement authority; pending intents and confirmed outcomes
remain in the event table through rollback and recutover. Reapply the reconciliation
migration after expansion on recutover. This adds no live provider or paid I/O.

Persistence bounds the entire connection/transaction/commit scope to ten seconds,
with five-second statement and one-second lock limits. Timeout failures leave
committed intents available for later reconciliation; an uncommitted unsupported-case
receipt rolls back with its account mutation. Lock-contention runtime tests prove
both paths recover using the same operation key.

## Annual provider boundary under implementation (#192)

`AnnualBillingProvider` accepts durable `AnnualProviderIntent` values and returns
`AnnualProviderObservation`, using `AnnualProviderOperation` and
`AnnualProviderStatus`. The registered `VippsTestBillingProvider` is restricted to
`https://apitest.vipps.no`; it has no production switch. Its runtime composition
remains pending. The annual PostgreSQL adapter below is internal only. Local HTTP fixtures verify request and
recovery behavior; they are not evidence of actual Vipps merchant-test execution.

An ambiguous checkout recovers through a bounded, read-only search for its unique
merchant reference. Missing or ambiguous results remain unknown. A capture must
match the stored agreement, charge, type, currency and amount. Refund confirmation
requires its individual successful history entry and operation key. Cumulative
refunded amounts alone cannot confirm an operation. Observations retain captured
and refunded totals; a confirmed capture is not itself a current entitlement.

Webhook authentication uses raw request bytes, the registered callback target and
the configured merchant number. Signed notifications supply reconciliation
references only. Durable receipt deduplication and a resource GET must precede
financial state changes. Confirmation origins are empty by default until an
actual designated MT origin is verified. Credentials and diagnostics stay out of
returned observations.

Annual renewal facts distinguish the scheduling instant from the promised
collection date. Scheduling is allowed on 31 December in Norway for 1 January;
missing that window fails closed and does not silently postpone the agreed date.
Notice intervals are measured to the earliest collection instant. Eligibility,
readiness and separate consent remain mandatory, and a worker authorization
contract is still required before this can run automatically.

Capture observations include the provider history timestamp, validated against
the captured total. A delayed reconciliation cannot start a new refund window.
Missing, malformed or incomplete capture history leaves the result unknown.
Provider-confirmed refunds do not establish bank settlement.

## Annual purchase ledger under implementation (#192)

`supabase/migrations/20260905083150_annual_billing_purchase_ledger.sql` owns
`billing.annual_purchases`, `billing.annual_operations` and
`billing.annual_refund_cases`. An inserted purchase must match the exact locked
Company Access basis through its published function. Offer, scope, consent,
provider identity and original intent remain immutable. One unresolved or paid
purchase occupies each company-year. A definitively failed or fully refunded purchase remains
in the history while permitting a new accepted attempt.

Refund claims lock the purchase and reserve against captured money, confirmed
refunds and every created, pending or unknown refund. A case pins its source,
facts and maximum entitlement. Owner requests may record change of mind; other
attributions require an active admin with fresh MFA and an explicitly opened, unexpired billing
support case for the same company. Automatic source-owned
incident ingestion and worker authority remain pending. The private tables have
forced RLS and no browser or service-role privileges.

Rollback revokes access, removes annual policies and moves the three relations
to the inaccessible `billing_annual_retired` schema and removes annual triggers
and functions so the predecessor billing rollback can withdraw its schema. Recutover restores the same records, including
unknown operations. It does not erase replay history or grant paid entitlement.


## Initial annual checkout orchestration

`StartAnnualCheckoutCommand` and `AnnualCheckoutQuery` carry customer choices and
verified identity. The internal `AnnualCheckoutService` claims an immutable
purchase/operation before provider execution. Only a newly committed claim may
create a provider agreement. Lost claim responses, lost provider responses and
failed settlement writes recover by reading the original stored intent. New
requests validate the exact current offer and separately accepted recurring
consent. Existing requests reconcile before refreshing eligibility/readiness.

`AnnualCheckout` identifies the immutable purchase through `AnnualPurchaseId`
and its lifecycle through `AnnualPurchaseStatus`. `AnnualCheckoutClaim` marks
whether this caller won the committed claim. `AnnualAcceptanceBasisReference`
pins Company Access evidence; `AnnualCheckoutPrerequisites` adds the source
readiness reference, digest and evaluation time.

`AnnualCheckoutPersistence` declares claim/load/settle operations with purchase-
then-operation locking and monotonic financial settlement.
`PostgresAnnualCheckoutSession` implements the port using restricted verified-actor
transactions. Claims serialize by company/year and recheck idempotency after
waiting. The source-owned purchase-basis function holds the eligibility lock; the
adapter compares its references and stores the exact returned JSONB. Full billing
terms are exposed on `AnnualBillingOffer` and saved alongside their digest. The
original operation stores provider intent plus readiness reference/digest/evaluation
and notice dates. No provider I/O occurs inside the persistence transaction.

The injected readiness verifier must validate the exact source-owned evidence,
including current identity, company/year and digest. Its default returns unavailable;
only isolated fixtures supply a verifier in this unit. This is not a production
readiness binding, and the default runtime verifier remains unavailable.

Settlement locks purchase before operation, invokes billing-owned public
`settle_annual_checkout` against that latest state, and commits both records
atomically. Terminal purchases and obsolete observations return the latest result
without updating terminal operation evidence. Only confirmed full capture grants
paid access; full capture already refunded in full becomes refunded, while a
refunded partial capture stays unresolved. The first capture timestamp, merchant
identity, bound agreement and monotonic totals remain immutable. Real independent-
connection tests cover claim races, visibility before provider execution, response
loss after commit, rollback between writes, lock ordering, current-source negatives,
tenant/MFA boundaries and two evidence-preserving rollback/recutover cycles.

The application prerequisite binding currently returns `FILING_NOT_READY`.
Company Access owns definitive eligibility. The eventual source for authoritative
aggregate filing readiness is Annual Compliance (#149, after #193/#153), through
its public source-owned contract. The current owner-writable legacy readiness
snapshot is not charging authority. Readiness must retain every non-billing hard
block; production release/provider clearance (#179/#198) is a separate gate.
This unavailable binding is safe interim behavior and does not satisfy #192's
end-to-end exit. HTTP/UI cutover, trusted readiness, actual MT evidence and all
remaining acceptance criteria stay pending. The subsequent HTTP composition exposes start/recovery routes with provider
disabled and source readiness unavailable by default.

## Durable local annual renewal cancellation

`CancelAnnualRenewalCommand` identifies an existing company/purchase and a unique
command key. `AnnualCancellationPersistence` is implemented by
`PostgresAnnualCancellationSession`, sharing a checkout session's verified actor
and restricted transaction implementation. `AnnualRenewalCancellation` returns
an immutable `AnnualCancellationId`, requester/time, original effective time and
unchanged paid/export dates. `AnnualCheckout.renewal_canceled_at` exposes the local
renewal stop without changing original consent or financial state.

`billing.annual_cancellation_requests` owns one immutable request receipt per
command key. A trigger locks the purchase and atomically sets its cancellation
time once, retaining a receipt for each distinct command. Same-key races replay
the original receipt; another target or actor conflicts. An insert failure rolls
back the local stop. Owner authority and fresh MFA remain mandatory; eligibility
and readiness blocks do not obstruct cancellation of future renewal.

The cancellation migration/rollback is
`supabase/migrations/20260905100130_annual_renewal_cancellation.sql`. Rollback moves
requests to `billing_annual_retired` before predecessor billing rollback, so the
original request and local cancellation survive recutover. No browser/service
role can read or insert the request table.

This command confirms local renewal cancellation only. It never cancels an initial
pending checkout, erases paid/export access, fabricates an agreement reference or
claims a refund. Provider agreement-stop/pending-renewal-charge cleanup, durable
worker recovery and annual runtime/UI composition are still pending #192 work.
Future renewal claims must honor this authority through explicit agreement/year
lineage; current next-year admission remains blocked.


## Annual agreement cleanup orchestration

`AnnualAgreementCleanupService` uses `AnnualAgreementCleanupPersistence` to claim
one durable `AnnualAgreementCleanup` for a persisted cancellation or refund
request and resolved original charge evidence. `AnnualRefundRequestId` is the
explicit alternative to `AnnualCancellationId`; exactly one must be present. `AnnualAgreementCleanupClaim` identifies the first
claim. The store must defer unresolved payments and competing charge intents,
verify current owner/fresh MFA, and preserve exact provider/account and references.
Its PostgreSQL adapter is `PostgresAnnualCleanupSession`; runtime composition
and worker authority remain pending. This is not a completed customer workflow.

A replay first reconciles the original operation. A confirmed stop returns as-is;
unknown evidence remains unknown. A pending observation permits retrying the same
immutable stop intent, covering a crash between claim and PATCH. The provider
rechecks the agreement and original charge before any PATCH.
`settle_annual_agreement_cleanup` validates linkage and zero cleanup money totals,
preserves confirmed state, and never settles the observation onto a purchase.
No worker authority, future agreement/year lineage, or actual MT proof is implied.


The cleanup adapter reauthorizes every claim and settlement, locks the original
purchase before operations, and chooses a persisted receipt. A unique partial
index enforces one agreement stop per purchase. The insert guard in
`supabase/migrations/20260905103149_annual_agreement_cleanup.sql` verifies receipt,
terminal checkout and exact original provider intent fields. The later refund
cleanup migration extends those receipt and terminal-proof alternatives as
described below. Cleanup settlement
never updates purchase money, status or access. Roll back this guard before the
cancellation and annual-ledger migrations; all operation evidence is retained.


## Annual customer reads and cancellation API

`AnnualBillingReadPersistence` returns a bounded `AnnualPurchasePage` of stored
`AnnualPurchaseSummary` values for `AnnualBillingSnapshotQuery`. The public
`annual_billing_offer` returns the published offer without declaring eligibility
or charge authority. `AnnualBillingSnapshot` combines that offer and the page.
Historical accepted amounts, terms and statuses come from each purchase, never
from the current offer. Descending accepted-at/ID pagination retains failed and
refunded history; each page has at most 50 summaries and a scoped purchase cursor.

`PostgresAnnualBillingReadSession` uses the existing verified-owner/fresh-MFA
boundary even for an empty snapshot. Its explicit projection excludes acceptance
basis/legal documents, merchant account, provider intent, keys and fingerprints.
GET is read-only and has no provider/readiness dependency. The provider-free
`AnnualBillingWorkflow` and `SupabaseAnnualBillingAdapter` compose reads and local
renewal cancellation from the same verified actor. The annual snapshot and
renewal-cancellations HTTP routes expose generated contracts with no-store
responses. Cancellation returns the immutable local receipt and unchanged access
dates; it does not claim provider acknowledgement or automatic worker cleanup.

## Legacy acquisition retirement (#192)

`20260905115700_legacy_billing_acquisition_retirement.sql` blocks inserts into
legacy accounts and new subscription/filing-package event claims, including old
`ON CONFLICT` writers. Existing account prices and identity cannot be reset;
paid/support flags cannot be reactivated and completed refunds cannot be reversed.
Payment identity, amount, company, year, obligation, provider and durable key stay
immutable, so a cleanup event cannot be repurposed into a purchase. Successful
historical events remain immutable. Pending historical events can settle from
provider reconciliation without changing paid account flags. Cancellation, refunds
and unsupported-case cleanup retain their existing authorization and receipts.

Every ordinary entitlement returns `annual_billing_unavailable`, with filing and
charge denied, regardless of legacy paid flags or owner-editable legacy readiness.
`readinessAllowed` permits preparation of the independent readiness assessment;
it asserts neither current eligibility nor readiness nor operational clearance.
Only the separate exact active billing-exempt pilot retains its existing exemption.
The trustworthy annual entitlement/runtime binding remains pending; retirement
alone does not satisfy #192 acceptance or permit production filing.

Rollback withdraws these guards without deleting historical records. It is an
explicit predecessor recovery operation, not a supported mixed-writer configuration.
Apply its rollback before earlier billing migrations and reapply retirement last.
The migration borrows SET authority only when needed and restores the invoking
principal's previous role capability, including admin-only memberships.


## Annual checkout HTTP boundary

`AnnualCheckoutOperations` and `annual_checkout_operations` expose the existing
single checkout service to application composition through the public package.
An absent provider is disabled; terminal stored results can still replay after
current owner/MFA authorization. The authenticated start and observation POST
routes map immutable customer choices to this service and return only purchase,
offer, status, monetary totals and a pending provider-validated checkout URL.
Original provider intent, merchant identity, acceptance source material and request
fingerprints remain backend-only. Snapshot GET and local cancellation keep their
provider-free behavior.

The default runtime has no configured annual provider. The source resolver and
PostgreSQL readiness verifier remain unavailable pending their actual owner.
Injected local HTTP/session fixtures prove only transport and orchestration;
actual MT, trusted readiness, complete checkout UI, webhook/worker/refund/renewal
runtime and final #192 gates remain outstanding. No production activation or
acceptance waiver follows from these endpoints.


## Annual refund orchestration contract

`AnnualRefundService` coordinates one recorded refund case and original provider
operation. `AnnualRefundCaseId` identifies the immutable case;
`AnnualRefundResolution` carries its request, facts, decision and optional
`AnnualRefundOperation`. `AnnualRefundClaim` identifies the winning executor.
`annual_refund_decision` exposes the existing policy and `settle_annual_refund`
is the required atomic-persistence settlement helper. `RequestAnnualRefundCommand` accepts a source lookup reference, never
caller-selected eligibility, money or incident facts. The mandatory
`AnnualRefundPersistence` contract requires verified source-owned facts, current
authority, purchase locks, durable request/case identity, balance reservations,
local renewal stop and preserved records/export. The registered `PostgresAnnualRefundSession` implements these durable operations.
Its source resolver is unavailable by default; no source resolver, worker,
support-case caller or HTTP route is bound. Synthetic orchestration tests and
real isolated persistence tests do not establish production source authority.

Billing uses the existing #177 policy for entitlement and the five-business-day
initiation deadline. The claimed operation separates actual captured money from
the original charge amount and caps execution at the remaining captured balance
and policy entitlement. A missing provider cannot erase an already recorded
liability. A missing operation may mean no automatic entitlement or deferred
execution; it never proves settlement. Confirmed and failed original operations
remain terminal; a failed attempt leaves the liability actionable and needs a
separate authorized retry operation before another modification.

Only a newly committed operation may execute. Lost claim/provider/settlement
responses recover its original identity by reconciliation, preserving unknown
outcomes and reservations without blind reissue. Settlement validates provider,
original references, capture timestamp and exact integer monotonic totals.
Later captures may grow up to the original charge without enlarging the already
claimed refund intent or changing its reservation basis.
The future adapter must apply the public settlement helper to locked current
state and persist operation/purchase evidence atomically. Digest shape checks
are not source authentication. No automatic-refund or real-provider acceptance
is claimed until those persistence, source and authority implementations exist.


## Durable annual refund requests

`PostgresAnnualRefundSession` uses the verified-actor transaction shared by annual
billing. Current owners can create change-of-mind cases. Other case reasons retain
the existing requirement for an active admin, fresh MFA, a current same-company
billing support grant and an explicitly opened case. Every replay and settlement
reauthorizes. This introduces no automatic worker identity or owner impersonation.

The default source resolver returns unavailable. A future resolver must read
immutable source-owned incident and production-submission evidence through its
declared public contract inside the transaction, without provider I/O. Missing
submission authority must never become an assertion that no filing was submitted.
Billing verifies its own purchase/year/gross/capture/acceptance facts and earliest
retained company capture before storing the canonical facts/digest and policy
liability. Repurchase retains the first-purchase window. A stored case and bound
request replay before any live source call.

`billing.annual_refund_requests` preserves request actor, company, purchase, case,
key, correlation and fingerprint. Its only mutable field is a write-once operation
assignment: a deferred request can acquire its original effect after competing
reservations resolve, without changing request identity. Purchase-before-operation
locks and the existing reservation trigger enforce one unresolved refund and cap
funds. Same-source concurrent keys share its unresolved operation; only the original
claim winner executes. New attempts after terminal failure require a new request
and fresh reservation. The AFTER INSERT trigger stops renewal with the committed
request, including provider outage, deferral and zero automatic entitlement.

Settlement compares the exact durable request/case/intent, invokes
`settle_annual_refund` against locked current operation evidence, and atomically
updates operation and monotonic purchase totals. It preserves capture identity,
cancellation and access/export dates. A partial capture refunded in full stays
unresolved; only confirmed refund of the complete original charge marks the
purchase refunded. Later capture growth cannot enlarge an existing refund intent.

Migration `supabase/migrations/20260905141500_annual_refund_requests.sql` and its
rollback preserve records across retirement/recutover and restore borrowed SET
and REFERENCES authority. The receipt table has forced RLS and no browser,
service-role or billing-executor grants. Real database tests cover durable recovery,
concurrency, deferral, exact binding, source mismatch, support revocation and
retained history. Actual source implementations, worker/support HTTP composition and final automatic
refund acceptance remain due. Owner-authorized original-agreement cleanup can
consume the refund request that caused the local renewal stop.


## Refund-triggered original agreement cleanup

`supabase/migrations/20260905145000_annual_refund_agreement_cleanup.sql` extends
the existing cleanup guard. The adapter and database share the private
`billing.annual_original_charge_resolved_v1` predicate under the purchase lock.
Ordinary terminal checkout evidence remains valid. An exact confirmed refund
operation can alternatively establish full cumulative capture and refund of the
original charge, even when its checkout operation remains unknown. This does not
rewrite checkout evidence or grant paid access. The final refund operation may
cover only the remaining balance; original provider/account/agreement/charge,
company/year, amount and first-capture identity must still match. Malformed
observations cannot provide that proof.

Financial resolution and stop intent are separate requirements. The chosen
manual cancellation or refund request must belong to the same purchase and match
its actual renewal-stop time. Later refund requests cannot replace the original
stop receipt. SQL rejects absent, conflicting, foreign or mismatched receipt
choices. Cleanup replay and settlement preserve the chosen typed receipt and
original operation, without changing purchase money, status or access/export.

Unresolved refunds, incomplete original charges, shared agreements and unsupported
renewal lineage defer new or unconfirmed cleanup. A confirmed cleanup remains
replayable after current owner/fresh-MFA authorization. The provider still checks
fresh original-charge safety immediately before STOP. The local MockTransport
rehearsal proves this adapter path and lost-response recovery, not actual MT.

Rollback restores the predecessor manual-receipt guard and removes the new
resolution function while retaining all provider operations and receipts. The
predecessor cannot initiate new refund-receipt cleanup; recutover restores its
forward recovery. No worker or support cleanup caller is activated by this change.

## Authenticated agreement cleanup recovery (#192)

`AnnualAgreementCleanupOperations` and `annual_agreement_cleanup_operations`
compose the existing receipt-bound cleanup policy through billing's public interface.
The authenticated POST accepts only company and purchase IDs. The verified session
uses `PostgresAnnualCleanupSession` with the same owner identity as the annual
checkout adapter. Every call, including confirmed replay, rechecks current owner
and fresh MFA; support-case and worker authority are not added.

The original persisted cancellation/refund receipt and STOP intent control recovery;
caller-provided receipt, provider or operation identity is rejected. The response
contains only company, purchase and deferred/pending/unknown/confirmed status.
Deferred or unknown does not establish provider cleanup. Default provider is absent,
so unresolved operations fail closed with PROVIDER_DISABLED while confirmed stored
cleanup can replay without provider I/O. Local renewal cancellation and GET history
remain provider-free. No new readiness authority, actual Merchant Test, automatic
worker, complete customer UI or final #192 acceptance is implied.
