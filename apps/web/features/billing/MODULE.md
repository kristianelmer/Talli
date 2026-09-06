# Billing web feature

<!-- architecture-inventory
{"apiOperations":["billingCleanupAnnualAgreement","billingCancelAnnualRenewal","billingCancelSubscription","billingManagePilotEntitlement","billingMarkUnsupported","billingReadAnnualSnapshot","billingReadEntitlement","billingReadSnapshot","billingRefundFilingPackage"],"dependencies":[],"publicEntryPoints":["@/features/billing","apps/web/features/billing","apps/web/features/billing/index.ts"],"routes":["/billing","/workspace","/operator","/filing/aksjonaerregisteroppgaven"]}
-->

## Purpose and boundary

This feature carries authenticated annual history and renewal cancellation,
historical refunds/cancellation, unsupported-case cleanup, production-pilot,
snapshot, and entitlement calls
through the committed generated API client. It deliberately contains no pricing,
provider-event transition, filing-readiness, refund, pilot, or authorization
policy. Those decisions belong to the backend billing capability.

`loadAnnualBillingEntitlements` shares the three supported annual-obligation
requests without interpreting the returned decisions. `presentBillingAccount`
maps the generated account wire fields once for workspace and archive consumers.

Annual purchase history and local renewal cancellation use the annual API. Recovery
classifies authentication and step-up failures without exposing internal errors.
Prices, terms, status and cancellation confirmations come from persisted backend facts.

Legacy account creation, subscription activation and filing-package purchase
methods and forms are retired. Workspace links to annual billing and exposes
previous-model cleanup only when historical account records exist.

`cleanupAnnualAgreement` carries authenticated company/purchase intent through
`billingCleanupAnnualAgreement`. The generated client validates the sanitized
cleanup status and uses POST with no cache. Provider/receipt/operation identities
remain backend-owned. This transport does not add customer UI or worker scheduling.
