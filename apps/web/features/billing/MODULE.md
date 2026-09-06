# Billing web feature

<!-- architecture-inventory
{"apiOperations":["billingReadAnnualRefundSnapshot","billingReadAnnualSupportPurchases","billingCleanupAnnualAgreement","billingCancelAnnualRenewal","billingCancelSubscription","billingManagePilotEntitlement","billingMarkUnsupported","billingReadAnnualSnapshot","billingReadEntitlement","billingReadSnapshot","billingRefundFilingPackage"],"dependencies":[],"publicEntryPoints":["@/features/billing","apps/web/features/billing","apps/web/features/billing/index.ts"],"routes":["/billing","/workspace","/operator","/filing/aksjonaerregisteroppgaven"]}
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

The operator support view uses `billingReadAnnualSupportPurchases` with the company
and case returned by the explicitly opened support-case read. It lists stored
purchases across years and preserves the case in pagination. Billing-only grants
work without profile rows. Backend access/MFA failures remain distinct from an
authorized empty page; the view performs no provider or refund commands.

The owner view offers an explicit `billingCleanupAnnualAgreement` server action
only for a purchase whose stored local renewal cancellation is visible. It
retains company, purchase and history cursor through identity recovery and uses
the original purchase-owned STOP identity. The client displays the direct scoped
action result, never a URL/form/previous-state confirmation. Render and refresh
perform no cleanup; disabled/unavailable, deferred, pending and unknown remain
unconfirmed. A rejected browser-to-server action also returns a scoped unconfirmed
state so a response lost after commit leaves an explicit same-purchase retry.
The current owner page still selects its admitted year; this control
does not establish complete historical exit or worker automation.

Owner refund visibility uses the additive `billingReadAnnualRefundSnapshot` GET.
It carries purchase balances and recorded refund evidence together from one
backend snapshot. `billingReadAnnualSnapshot` retains its predecessor response
shape for older web deployments. If the expanded read is absent (HTTP404), the
new web falls back to that original history and explicitly marks refund details
unavailable; other errors preserve existing sign-in/MFA/unavailable recovery.
No default zero liability is invented. The view distinguishes recorded amounts,
request receipts, unknown/failed/pending attempts, and the initiation target
from provider/bank receipt timing; no late-initiation inference or new entitlement
policy runs in the browser. This is visibility, not automatic refund execution.
