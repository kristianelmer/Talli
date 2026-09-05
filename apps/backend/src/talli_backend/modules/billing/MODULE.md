# Billing backend capability

<!-- architecture-inventory
{"dependencies":[],"ownedTables":["billing.billing_accounts","billing.billing_payment_events","billing.production_pilot_entitlements","billing.annual_purchases","billing.annual_refund_cases","billing.annual_operations"],"ports":["BillingPersistence","BillingPaymentProvider","AnnualBillingProvider","AnnualCheckoutPersistence"],"publicEntryPoints":["talli_backend.modules.billing.public"]}
-->

## Purpose and ownership

`billing` owns the legacy launch prices, subscription state, filing-package
payments and refunds, provider outcome records, exact production-pilot billing
exemptions, and the single filing-entitlement decision consumed by readiness and
production release gates. Its three tables are private capability relations;
browser and presentation code never query or mutate them directly.

The capability does not own filing content, filing readiness, authority,
company membership, authentication, or launch signoffs. Those facts arrive
through the application and persistence ports, and billing returns a decision
rather than exposing its policy for callers to reimplement.

## Public interface

Import only `talli_backend.modules.billing.public`. Commands carry a company,
verified actor, correlation ID, and durable idempotency key. Pricing is selected
server-side: founder companies 1–100 retain NOK 29/month and NOK 299/filing;
standard accounts retain NOK 49/month and NOK 499/filing until #192 changes the
commercial model.

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
against the canonical service with the same IDs, clock, plans, states, and
failure injection. It compares defaults, prices, coded-error mappings, every
legacy gate, provider event facts, mutable account effects, duplicate replay,
retry quarantine, and production-pilot identity and time bounds. Static and
database tests preserve the matching audit facts, RLS, rollback, and recutover.

## Ports and adapters

The #192 annual-offer work introduces `AnnualBillingOffer`,
`AnnualRefundFacts`, `AnnualRefundReason`, `AnnualRefundDecision`,
`AnnualRenewalFacts`, and `AnnualRenewalDecision`. The internal `annual_policy`
module pins the NOK 1,490 gross company-year offer and derives renewal notice,
paid/read-export dates, and automatic refund amounts from recorded facts. Amounts
are integer minor units; Norwegian calendar dates govern month and notice limits.
These policy types alone do not initiate payment or replace the existing runtime
path. The #192 acceptance record tracks the remaining persistence/API/provider/web
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
Confirmed outcomes and account changes settle atomically; terminal events replay
without reapplying account effects. Changed filing obligations reject key reuse.

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
committed intents available for later reconciliation; an uncommitted configuration
receipt rolls back with its account mutation. Lock-contention runtime tests prove
both paths recover using the same operation key.

## Annual provider boundary under implementation (#192)

`AnnualBillingProvider` accepts durable `AnnualProviderIntent` values and returns
`AnnualProviderObservation`, using `AnnualProviderOperation` and
`AnnualProviderStatus`. The registered `VippsTestBillingProvider` is restricted to
`https://apitest.vipps.no`; it has no production switch. Its runtime composition
and annual persistence are still pending. Local HTTP fixtures verify request and
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
then-operation locking and monotonic financial settlement. Its PostgreSQL adapter
is still pending; the orchestration tests use an isolated in-memory adapter and
do not establish production persistence integration. Provider account identity
is pinned, and mismatched/malformed capture evidence cannot grant paid access.

The application prerequisite binding currently returns `FILING_NOT_READY`.
Company Access owns definitive eligibility. The eventual source for authoritative
aggregate filing readiness is Annual Compliance (#149, after #193/#153), through
its public source-owned contract. The current owner-writable legacy readiness
snapshot is not charging authority. Readiness must retain every non-billing hard
block; production release/provider clearance (#179/#198) is a separate gate.
This unavailable binding is safe interim behavior and does not satisfy #192's
end-to-end exit. HTTP/UI cutover, trusted readiness, actual MT evidence and all
remaining acceptance criteria stay pending. No annual runtime route is exposed
by this orchestration unit.
