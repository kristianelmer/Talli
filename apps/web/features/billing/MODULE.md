# Billing web feature

<!-- architecture-inventory
{"apiOperations":["billingActivateSubscription","billingCancelSubscription","billingConfigureAccount","billingManagePilotEntitlement","billingMarkUnsupported","billingPurchaseFilingPackage","billingReadEntitlement","billingReadSnapshot","billingRefundFilingPackage"],"dependencies":[],"publicEntryPoints":["@/features/billing","apps/web/features/billing","apps/web/features/billing/index.ts"],"routes":["/billing","/workspace","/operator","/filing/aksjonaerregisteroppgaven"]}
-->

## Purpose and boundary

This feature carries authenticated billing account, subscription, filing-package,
refund, unsupported-case, production-pilot, snapshot, and entitlement calls
through the committed generated API client. It deliberately contains no pricing,
provider-event transition, filing-readiness, refund, pilot, or authorization
policy. Those decisions belong to the backend billing capability.
