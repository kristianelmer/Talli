# Billing backend capability

<!-- architecture-inventory
{"dependencies":[],"ownedTables":["billing.billing_accounts","billing.billing_payment_events","billing.production_pilot_entitlements"],"ports":["BillingPersistence","BillingPaymentProvider"],"publicEntryPoints":["talli_backend.modules.billing.public"]}
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
`BillingPlan`, `BillingPricing`, `BillingStatus`, `BillingPaymentEvent`,
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

`BillingPersistence` owns all reads and writes to `billing.*`. The Supabase
adapter authenticates the bearer token, scopes reads through RLS, and performs
each payment-event/account transition atomically. Non-provider commands use
the backend-system technical `billing.billing_command_receipts` for exact durable replay and reject a reused
key when its canonical request fingerprint differs. `BillingPaymentProvider`
accepts only a provider-neutral intent and must honor its idempotency key.

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
overlap. `20260905013000_billing_contract.sql` rewrites downstream database
readers and removes those views plus the obsolete write RPC. Matching rollback
artifacts restore the immediately preceding topology; the lifecycle test
rehearses expansion and contract rollback/cutover twice. Durable command receipts
move to a quarantined `backend_system` relation during expansion rollback and
return to `billing` on recutover, so rollback never erases replay history.
