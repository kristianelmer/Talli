# Billing web feature

## Approved interim and final billing scope

The [9 September 2026 owner decision](https://github.com/kristianelmer/Talli/issues/192#issuecomment-5599100453)
approves the exact legacy retirement and source-order option B. #192 stays open.
Implemented historical/annual recorded recovery and the unavailable acquisition
and renewal defaults form the interim checkpoint. It requires independent review,
two linked immutable complete gates and protected-main plus exact-main
Release/Preview before #150 may start. Billing implementation then pauses while
source owners execute serially. After #149 and Company Access year prerequisite
#208, #192 must bind actual source contracts and complete ordinary paid
entitlement, automatic renewal/refunds and every A1–A8 criterion before #194 or
#197's billing tranche. No absent source is replaced with a fixture or legacy
readiness row, and no future public dependency is declared before it exists.

<!-- architecture-inventory
{"apiOperations":["billingRecoverAnnualSupportCleanup","billingReadAnnualSupportRefundRecoveryTargets","billingRecoverAnnualSupportRefund","billingStartAnnualCheckout","billingWithdrawAnnualCheckoutRequest","billingPrepareAnnualCheckout","billingReadAnnualRefundRecoveryTargets","billingRecoverAnnualRefund","billingObserveAnnualCheckout","billingReadAnnualPurchaseHistory","billingReadAnnualRefundSnapshot","billingReadAnnualSupportPurchases","billingCleanupAnnualAgreement","billingCancelAnnualRenewal","billingCancelSubscription","billingManagePilotEntitlement","billingMarkUnsupported","billingReadAnnualSnapshot","billingReadEntitlement","billingReadSnapshot","billingRefundFilingPackage"],"dependencies":[],"publicEntryPoints":["@/features/billing","apps/web/features/billing","apps/web/features/billing/index.ts"],"routes":["/billing","/workspace","/operator","/filing/aksjonaerregisteroppgaven"]}
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
authorized empty page; rendering the view performs no provider or refund commands.

The owner view offers an explicit `billingCleanupAnnualAgreement` server action
only for a purchase whose stored local renewal cancellation is visible. It
retains company, purchase and history cursor through identity recovery and uses
the original purchase-owned STOP identity. The client displays the direct scoped
action result, never a URL/form/previous-state confirmation. Render and refresh
perform no cleanup; disabled/unavailable, deferred, pending and unknown remain
unconfirmed. A rejected browser-to-server action also returns a scoped unconfirmed
state so a response lost after commit leaves an explicit same-purchase retry.
This control does not establish complete historical exit or worker automation.

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

Company-wide owner history uses `billingReadAnnualPurchaseHistory`, independently
of current admission. Only an actual current admitted year selects the separate
published offer. Every purchase keeps its own terms, company/year, cancellation
and cleanup identity, and archive link. Offer unavailability cannot erase readable
history; a subsequent authentication/access failure hides earlier evidence.
A missing history endpoint may temporarily show only the newest current-year
purchases with an explicit limitation. Company-wide cursors never reach that
predecessor fallback; application BILLING_NOT_FOUND remains an error. Without
admission or a safe first-page fallback, absence is unavailable, not empty history.

An explicit pending-purchase control uses `billingObserveAnnualCheckout` to
reconcile only the original company/purchase intent. It does not start a checkout
or consume new admission/readiness authority. Every validated response revalidates
`/billing`, including pending responses, so the canonical history owns status,
balances and access together. Terminal observations remove the control through
that refreshed history; partial checkout DTOs and provider URLs never replace
the stored purchase view. Sign-in/MFA preserves company, history cursor and a
navigation-only purchase marker. Lost responses remain unconfirmed and retryable;
render, navigation and refresh never trigger a POST.


Owner refund recovery first uses `billingReadAnnualRefundRecoveryTargets` for one
selected purchase in authorized canonical history. Only an absent route (404
without a domain problem) is unavailable compatibility; scoped cursor and access
errors remain distinct. An access failure on this later read hides earlier
protected history and controls. Empty results do not erase recorded liability.

Each explicit `billingRecoverAnnualRefund` server action validates and sends the
original company, purchase and request IDs through the current session, with no
new operation key or source/provider authority. All scoped success statuses
revalidate canonical history, including pending/unknown; access rejection also
revalidates protected content. Operation confirmation is not total refund or bank
receipt. Client state is scoped to all three IDs, pending disables duplicate
submission, and a lost response retains an explicit same-request retry. Both
history cursors and the selected receipt survive login/MFA and reload links.
Intentional pagination may choose another page; a changed representative displays
a selection warning. Render, navigation, refresh and auth return never issue a
recovery POST. No automatic adjudication, new refund initiation or actual Merchant
Test evidence is supplied by this UI.

`prepareAnnualCheckout` uses the additive `billingPrepareAnnualCheckout` GET.
It validates company/year and mutually exclusive available/existing projections,
rejects private extra fields through the generated client, and treats only a
missing predecessor route as unavailable compatibility. It creates no key,
purchase, source authority or provider effect. Existing purchases expose no new
offer/consent; unavailable preparation cannot enable a purchase.


Owner checkout uses `prepareAnnualCheckout`, `startAnnualCheckout` and
`withdrawAnnualCheckoutRequest` through generated operations only. Start checks
returned company/year and accepted offer/digest; withdrawal checks exact scope
and mutually exclusive purchase/receipt fields. Mutation failures remain errors,
including predecessor404; they cannot release retained intent. Original keys and
choices cross unchanged. The web never supplies actor/source/provider authority.
`annualCheckoutNeedsWithdrawal` classifies recovery feedback only.

The page verifies initiating user identity and loads preparation without opening
payment when readiness/provider sources are unavailable. A later protected-read
401/403 suppresses earlier history and controls. `AnnualCheckoutControl` restores
one company-scoped tab-local draft without POST, synchronously saves it before an
explicit action, and retains its original user/body/key through refresh/MFA/reauth.
Withdrawal selection persists its phase before awaiting and cannot revert to
purchase start. Server actions verify the initiating user against the exact token
sent to billing. Only scoped committed results and matching current draft permit
removal; storage failure prevents a replacement request. Fresh review is explicit,
uses fresh preparation and unchecked purchase/optional recurring choices.

A fresh pending start or explicit original-purchase observation can expose a
backend-validated HTTPS approval link. It is not stored in drafts, query strings
or canonical history, and never opens automatically. Terminal/error/pending-retry
states hide prior links. Canonical purchase history alone owns money and access.
Selected old purchases remain selected through pagination, with the former cursor
as a separate backlink. Full browser/provider/source acceptance remains #192 work.


## Explicit operator recovery of recorded refunds

`loadAnnualSupportRefundRecoveryTargets` and `recoverAnnualSupportRefund` use only
`billingReadAnnualSupportRefundRecoveryTargets` and `billingRecoverAnnualSupportRefund`.
Every response must match its case/company/purchase and, for recovery, request.
Errors, missing routes and missing records remain failures rather than empty
success. No operation key, original requester, source, amount or provider fact is
created or inferred in the web layer.

Operator page access verifies the user against the exact backend token. The
selected case dashboard repeats that check against its expected operator, then
reads context, opened case, annual history and selected targets through one token.
The URL's company is an assertion against the opened case; only a purchase on the
current authorized page can load targets. Later failures or foreign target
case/company/purchase/year clear all earlier summaries, history and controls before
ancillary reads. Missing selected purchases/requests are explicit and never
silently replaced. Both pagination cursors and all selected IDs survive login/MFA.

Recovery requires an explicit click and the exact initiating operator. Strict
unique form fields carry continuity and navigation locally; POST sends only the
four recorded case/company/purchase/request IDs. The backend authorizes the
operator independently. Every failed action refreshes the operator page so loss
of case access can clear protected evidence; failed refresh cannot report
confirmation. The keyed client control blocks duplicate pending events and late
results after unmount, retains the same request after a lost response, and never
posts on render, navigation, reload or authentication return. Confirmation applies
to one operation; canonical history remains the authority for outstanding money.


## Explicit operator recovery of a recorded agreement stop

`recoverAnnualSupportCleanup` carries only the opened support case, company and
purchase IDs through `billingRecoverAnnualSupportCleanup`. The backend resolves
the purchase's unique recorded STOP and preserves its original intent, requester
and cancellation/refund receipt. Missing STOP evidence remains an error. The web
cannot create a cleanup claim, supply provider/source authority or execute STOP.

`AnnualSupportCleanupRecoveryControl` is available only when canonical authorized
history shows a recorded cleanup. An explicit click verifies the initiating user
against the exact session token, then reconciles that original operation. Scoped
results and failures refresh operator history. The control retains the case,
company, purchase and history cursor through identity recovery and lost-response
retry; it ignores foreign or late results and blocks duplicate pending submits.
Render, refresh, navigation and authentication return do not reconcile. Only a
scoped confirmed response announces provider confirmation; pending/unknown remain
unconfirmed. The feature test `annual-support-cleanup-recovery.test.mjs` exercises
these action and control boundaries; transport and support-view tests cover the
generated response validation and visibility of the control.
